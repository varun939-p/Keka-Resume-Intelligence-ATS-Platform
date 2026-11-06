"""
Persistence for candidates, batches, the job-description library and settings.

JSON files under config.DATA_DIR, written atomically under a process-wide lock.
Every record carries a workspace ('demo' or 'live') so the two modes never mix.
"""
from __future__ import annotations

import json
import re
import statistics
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import config
from scorer import (DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, STAGES, normalize_thresholds, normalize_weights,
                    parse_requirement_labels, profile_jd)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


class Store:
    def __init__(self) -> None:
        config.ensure_dirs()
        self.lock = threading.RLock()
        self.candidates: Dict[str, Dict[str, Any]] = {c["id"]: c for c in _read_json(config.CANDIDATES_FILE, [])
                                                      if isinstance(c, dict) and c.get("id")}
        self.batches: Dict[str, Dict[str, Any]] = {b["id"]: b for b in _read_json(config.BATCHES_FILE, [])
                                                   if isinstance(b, dict) and b.get("id")}
        self.settings: Dict[str, Any] = {"provider": config.DEFAULT_LLM_PROVIDER, **_read_json(config.SETTINGS_FILE, {})}

    # -- candidates ----------------------------------------------------------
    def _save_candidates(self) -> None:
        _write_json(config.CANDIDATES_FILE, list(self.candidates.values()))

    def add_candidate(self, record: Dict[str, Any]) -> None:
        with self.lock:
            self.candidates[record["id"]] = record
            self._save_candidates()

    def get_candidate(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            return self.candidates.get(candidate_id)

    def update_candidate(self, candidate_id: str, mutate: Callable[[Dict[str, Any]], None]) -> Optional[Dict[str, Any]]:
        with self.lock:
            record = self.candidates.get(candidate_id)
            if record is None:
                return None
            mutate(record)
            record["updated_at"] = now_iso()
            self._save_candidates()
            return record

    def delete_candidates(self, ids: List[str]) -> List[Dict[str, Any]]:
        with self.lock:
            removed = [self.candidates.pop(i) for i in ids if i in self.candidates]
            if removed:
                self._save_candidates()
            return removed

    def query_candidates(self, workspace: str, batch_id: Optional[str] = None, stage: Optional[str] = None,
                         q: Optional[str] = None, jd_id: Optional[str] = None, min_score: Optional[int] = None,
                         sort: str = "overall", order: str = "desc") -> List[Dict[str, Any]]:
        with self.lock:
            rows = [c for c in self.candidates.values() if c["workspace"] == workspace]
        if batch_id:
            rows = [c for c in rows if c["batch_id"] == batch_id]
        if jd_id:
            rows = [c for c in rows if c["jd"]["id"] == jd_id]
        if stage and stage != "all":
            rows = [c for c in rows if c["stage"] == stage]
        if min_score is not None:
            rows = [c for c in rows if c["scores"]["overall"] >= min_score]
        if q:
            needle = q.strip().lower()
            rows = [c for c in rows if needle in _search_blob(c)]
        key = SORT_KEYS.get(sort, SORT_KEYS["overall"])
        rows.sort(key=key, reverse=(order != "asc"))
        return rows

    def workspace_candidates(self, workspace: str) -> List[Dict[str, Any]]:
        with self.lock:
            return [c for c in self.candidates.values() if c["workspace"] == workspace]

    # -- batches -------------------------------------------------------------
    def _save_batches(self) -> None:
        _write_json(config.BATCHES_FILE, list(self.batches.values()))

    def create_batch(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            self.batches[batch["id"]] = batch
            self._save_batches()
            return batch

    def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            return self.batches.get(batch_id)

    def update_batch(self, batch_id: str, mutate: Callable[[Dict[str, Any]], None]) -> Optional[Dict[str, Any]]:
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                return None
            mutate(batch)
            self._save_batches()
            return batch

    def list_batches(self, workspace: str) -> List[Dict[str, Any]]:
        with self.lock:
            rows = [b for b in self.batches.values() if b["workspace"] == workspace]
        return sorted(rows, key=lambda b: b["created_at"], reverse=True)

    def reset_workspace(self, workspace: str) -> Dict[str, int]:
        with self.lock:
            cand_ids = [cid for cid, c in self.candidates.items() if c["workspace"] == workspace]
            for cid in cand_ids:
                record = self.candidates.pop(cid)
                stored = record.get("file", {}).get("stored_path")
                if stored and record.get("source") == "upload":
                    try:
                        (config.UPLOAD_DIR / stored).unlink(missing_ok=True)
                    except OSError:
                        pass
            batch_ids = [bid for bid, b in self.batches.items() if b["workspace"] == workspace]
            for bid in batch_ids:
                self.batches.pop(bid)
            self._save_candidates()
            self._save_batches()
            return {"candidates": len(cand_ids), "batches": len(batch_ids)}

    # -- settings ------------------------------------------------------------
    def update_settings(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            self.settings.update(patch)
            _write_json(config.SETTINGS_FILE, self.settings)
            return dict(self.settings)


def _search_blob(c: Dict[str, Any]) -> str:
    p = c["profile"]
    parts = [p.get("name"), p.get("email"), p.get("phone"), p.get("current_title"), p.get("current_company"),
             p.get("city"), c["file"].get("name"), " ".join(p.get("skills", [])), STAGES.get(c["stage"], "")]
    return " ".join(x for x in parts if x).lower()


SORT_KEYS: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "overall": lambda c: (c["scores"]["overall"], c["scores"]["technical"]),
    "technical": lambda c: c["scores"]["technical"],
    "experience": lambda c: c["scores"]["experience"],
    "impact": lambda c: c["scores"]["impact"],
    "education": lambda c: c["scores"]["education"],
    "years": lambda c: c["profile"].get("total_experience_years") or 0,
    "name": lambda c: (c["profile"].get("name") or "").lower(),
    "stage": lambda c: list(STAGES).index(c["stage"]) * -1,
    "scanned_at": lambda c: c["scanned_at"],
}


# ---------------------------------------------------------------------------
# Job description library
# ---------------------------------------------------------------------------

class JobLibrary:
    """Sample JDs come from sample_jd/ (read-only); custom JDs persist in custom_jds.json."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.custom: Dict[str, Dict[str, Any]] = {j["id"]: j for j in _read_json(config.CUSTOM_JDS_FILE, [])
                                                  if isinstance(j, dict) and j.get("id")}
        self._samples: Optional[Dict[str, Dict[str, Any]]] = None

    def samples(self) -> Dict[str, Dict[str, Any]]:
        if self._samples is None:
            samples = {}
            for path in sorted(config.SAMPLE_JD_DIR.glob("*.txt")):
                text = path.read_text(encoding="utf-8")
                prof = profile_jd(text)
                jd_id = f"sample-{path.stem}"
                samples[jd_id] = self._assemble(jd_id, "sample", path.name, text, prof, DEFAULT_WEIGHTS,
                                                DEFAULT_THRESHOLDS, created_at=None)
            self._samples = samples
        return self._samples

    @staticmethod
    def _assemble(jd_id, kind, filename, text, prof, weights, thresholds, created_at, overrides=None) -> Dict[str, Any]:
        overrides = overrides or {}
        requirements = prof["requirements"]
        if overrides.get("requirements"):
            requirements = {t: parse_requirement_labels(overrides["requirements"].get(t, requirements.get(t, [])))
                            for t in ("critical", "core", "bonus")}
        return {
            "id": jd_id,
            "kind": kind,
            "filename": filename,
            "title": overrides.get("title") or prof["title"],
            "location": overrides.get("location") or prof["location"],
            "city": prof["city"],
            "work_mode": prof["work_mode"],
            "department": prof["department"],
            "experience_min": overrides["experience_min"] if overrides.get("experience_min") is not None else prof["experience_min"],
            "experience_max": overrides["experience_max"] if overrides.get("experience_max") is not None else prof["experience_max"],
            "seniority": prof["seniority"],
            "requirements": requirements,
            "keyword_vector": prof["keyword_vector"],
            "weights": normalize_weights(weights),
            "thresholds": normalize_thresholds(thresholds),
            "text": text,
            "created_at": created_at,
            "updated_at": overrides.get("updated_at"),
        }

    def list(self, workspace: str) -> List[Dict[str, Any]]:
        """JDs owned by one workspace: Demo has the sample JDs, Live has only the recruiter's own."""
        if workspace == "demo":
            return list(self.samples().values())
        with self.lock:
            return sorted(self.custom.values(), key=lambda j: j["created_at"] or "", reverse=True)

    def get(self, jd_id: str) -> Optional[Dict[str, Any]]:
        if jd_id in self.samples():
            return self.samples()[jd_id]
        with self.lock:
            return self.custom.get(jd_id)

    def _save(self) -> None:
        _write_json(config.CUSTOM_JDS_FILE, list(self.custom.values()))

    def save_custom(self, payload: Dict[str, Any], jd_id: Optional[str] = None) -> Dict[str, Any]:
        text = (payload.get("text") or "").strip()
        title = (payload.get("title") or "").strip() or None
        prof = profile_jd(text, title=title)
        overrides = {
            "title": title,
            "location": (payload.get("location") or "").strip() or None,
            "experience_min": payload.get("experience_min"),
            "experience_max": payload.get("experience_max"),
            "requirements": payload.get("requirements"),
            "updated_at": now_iso() if jd_id else None,
        }
        with self.lock:
            existing = self.custom.get(jd_id) if jd_id else None
            record = self._assemble(
                jd_id or new_id("jd"), "custom", payload.get("filename") or (existing or {}).get("filename"),
                text, prof, payload.get("weights") or DEFAULT_WEIGHTS, payload.get("thresholds") or DEFAULT_THRESHOLDS,
                created_at=(existing or {}).get("created_at") or now_iso(), overrides=overrides,
            )
            self.custom[record["id"]] = record
            self._save()
            return record

    def delete_custom(self, jd_id: str) -> bool:
        with self.lock:
            if jd_id not in self.custom:
                return False
            self.custom.pop(jd_id)
            self._save()
            return True


def jd_workspace(jd: Dict[str, Any]) -> str:
    """Sample JDs belong to the Demo workspace; every custom JD belongs to Live."""
    return "demo" if jd["kind"] == "sample" else "live"


def public_jd(jd: Dict[str, Any], include_text: bool = False) -> Dict[str, Any]:
    out = {k: v for k, v in jd.items() if k not in {"keyword_vector", "text"}}
    out["workspace"] = jd_workspace(jd)
    out["requirement_counts"] = {t: len(v) for t, v in jd["requirements"].items()}
    if include_text:
        out["text"] = jd["text"]
    else:
        preview = re.sub(r"[=]{3,}", "", jd["text"])
        out["preview"] = re.sub(r"\s+", " ", preview).strip()[:220]
    return out


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def is_duplicate(c: Dict[str, Any]) -> bool:
    """Current stage wins: a recruiter can clear a dedup flag by moving the candidate."""
    return c["stage"] == "duplicate"


def _scope_metrics(rows: List[Dict[str, Any]], batches: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    duplicates = [c for c in rows if is_duplicate(c)]
    unique = [c for c in rows if not is_duplicate(c)]
    shortlisted = [c for c in unique if c["stage"] == "shortlisted"]
    scores = [c["scores"]["overall"] for c in unique]
    timings = [c["metrics"]["total_ms"] for c in rows if c.get("metrics")]
    busy_ms = sum(b.get("busy_ms") or 0 for b in batches)
    processed = sum(b.get("processed") or 0 for b in batches)
    return {
        "total_scanned": total,
        "unique": len(unique),
        "shortlisted": len(shortlisted),
        "shortlist_rate": round(len(shortlisted) / len(unique) * 100, 1) if unique else None,
        "duplicates_blocked": len(duplicates),
        "duplicate_rate": round(len(duplicates) / total * 100, 1) if total else None,
        "avg_match": round(statistics.mean(scores), 1) if scores else None,
        "median_match": round(statistics.median(scores), 1) if scores else None,
        "median_ms": round(statistics.median(timings), 1) if timings else None,
        "throughput_per_min": round(processed / (busy_ms / 60000), 1) if busy_ms and processed else None,
    }


def analytics(store: Store, workspace: str, batch_id: Optional[str] = None) -> Dict[str, Any]:
    batches = store.list_batches(workspace)
    all_rows = store.workspace_candidates(workspace)
    if batch_id:
        scope_batches = [b for b in batches if b["id"] == batch_id]
        rows = [c for c in all_rows if c["batch_id"] == batch_id]
        idx = next((i for i, b in enumerate(batches) if b["id"] == batch_id), None)
        prev_batch = batches[idx + 1] if idx is not None and idx + 1 < len(batches) else None
    else:
        scope_batches, rows, prev_batch = batches, all_rows, None

    previous = None
    if prev_batch:
        previous = _scope_metrics([c for c in all_rows if c["batch_id"] == prev_batch["id"]], [prev_batch])
        previous["batch_label"] = prev_batch.get("label")

    stage_counts = {key: 0 for key in STAGES}
    for c in rows:
        stage_counts[c["stage"]] = stage_counts.get(c["stage"], 0) + 1

    histogram = [0] * 10
    for c in rows:
        if not is_duplicate(c):
            histogram[min(9, c["scores"]["overall"] // 10)] += 1

    missing = Counter(skill for c in rows if not is_duplicate(c) for skill in c["skills"]["missing_critical"])
    unique_count = sum(1 for c in rows if not is_duplicate(c))
    thresholds = rows[0]["thresholds"] if rows else DEFAULT_THRESHOLDS

    return {
        "workspace": workspace,
        "batch_id": batch_id,
        "current": _scope_metrics(rows, scope_batches),
        "previous": previous,
        "stage_counts": stage_counts,
        "score_histogram": histogram,
        "thresholds": thresholds,
        "skill_gaps": [{"skill": s, "missing": n, "share": round(n / unique_count * 100) if unique_count else 0}
                       for s, n in missing.most_common(8)],
        "batch_count": len(batches),
    }
