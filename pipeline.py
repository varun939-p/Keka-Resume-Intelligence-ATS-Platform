"""
Batch screening pipeline: parse -> deduplicate -> score -> route -> persist -> audit.

A batch is created first, then files are submitted one at a time (sample files by
name in Demo mode, uploaded bytes in Live mode). Per-file requests keep every
upload under serverless body limits, give the browser real per-file progress,
and let a failed file fail alone. Each stage emits an event that the
/api/batches/{id}/events stream relays to the dashboard.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import config
from dedup import DedupEngine
from parser import ResumeParseError, extract_text, parse_resume
from scorer import STAGES, ResumeScorer
from sheets import AuditLog
from store import JobLibrary, Store, new_id, now_iso


class ProcessingError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class EventBus:
    """In-memory per-batch event history with monotonically increasing sequence numbers."""

    def __init__(self, capacity: int = 3000):
        self.lock = threading.Lock()
        self.capacity = capacity
        self.events: Dict[str, Deque[Dict[str, Any]]] = {}
        self.seq: Dict[str, int] = {}

    def emit(self, batch_id: str, kind: str, **data: Any) -> None:
        with self.lock:
            seq = self.seq.get(batch_id, 0) + 1
            self.seq[batch_id] = seq
            self.events.setdefault(batch_id, deque(maxlen=self.capacity)).append(
                {"seq": seq, "type": kind, "at": now_iso(), **data})

    def since(self, batch_id: str, after: int) -> List[Dict[str, Any]]:
        with self.lock:
            return [e for e in self.events.get(batch_id, ()) if e["seq"] > after]


def _safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    return re.sub(r"[^A-Za-z0-9._ ()-]", "_", base)[:140] or "resume"


class Pipeline:
    def __init__(self, store: Store, jobs: JobLibrary, dedup: DedupEngine, scorer: ResumeScorer, audit: AuditLog):
        self.store, self.jobs, self.dedup, self.scorer, self.audit = store, jobs, dedup, scorer, audit
        self.bus = EventBus()

    # -- batches -------------------------------------------------------------
    def create_batch(self, workspace: str, jd_id: str, expected: int, provider: Optional[str],
                     label: Optional[str], reset: bool) -> Dict[str, Any]:
        if workspace not in config.WORKSPACES:
            raise ProcessingError("bad_workspace", f"Unknown workspace '{workspace}'.", 400)
        jd = self.jobs.get(jd_id)
        if jd is None:
            raise ProcessingError("jd_not_found", "Job description not found.", 404)
        if reset:
            self.reset_workspace(workspace, actor="system", reason="Demo batch started on a clean workspace")
        resolved = self.scorer.resolve_provider(provider or self.store.settings.get("provider"))
        seq = len(self.store.list_batches(workspace)) + 1
        batch = {
            "id": new_id("bat"),
            "workspace": workspace,
            "label": label or f"Batch {seq:03d}",
            "jd_id": jd["id"],
            "jd_title": jd["title"],
            "provider": resolved,
            "status": "running",
            "expected": max(0, int(expected)),
            "processed": 0,
            "failed": 0,
            "duplicates": 0,
            "failures": [],
            "created_at": now_iso(),
            "completed_at": None,
            "busy_ms": 0.0,
        }
        self.store.create_batch(batch)
        self.audit.log("batch.created", workspace, batch_id=batch["id"],
                       detail=f"{batch['label']} · {jd['title']} · {batch['expected']} files expected · engine {resolved}")
        self.bus.emit(batch["id"], "batch.started", label=batch["label"], expected=batch["expected"], jd=jd["title"])
        return batch

    def complete_batch(self, batch_id: str) -> Dict[str, Any]:
        batch = self.store.get_batch(batch_id)
        if batch is None:
            raise ProcessingError("batch_not_found", "Batch not found.", 404)
        if batch["status"] != "completed":
            def _finish(b: Dict[str, Any]) -> None:
                b["status"] = "completed"
                b["completed_at"] = now_iso()
            batch = self.store.update_batch(batch_id, _finish)
            summary = self.batch_summary(batch)
            self.audit.log("batch.completed", batch["workspace"], batch_id=batch_id,
                           detail=f"{batch['processed']} scored · {batch['duplicates']} duplicates · {batch['failed']} failed")
            self.bus.emit(batch_id, "batch.completed", summary=summary)
        return batch

    def batch_summary(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        rows = [c for c in self.store.workspace_candidates(batch["workspace"]) if c["batch_id"] == batch["id"]]
        counts = {k: 0 for k in STAGES}
        for c in rows:
            counts[c["stage"]] += 1
        return {"processed": batch["processed"], "failed": batch["failed"], "duplicates": batch["duplicates"],
                "stage_counts": counts}

    def rescore_batch(self, batch_id: str, jd_id: Optional[str] = None, actor: str = "recruiter") -> Dict[str, Any]:
        """Re-runs scoring and routing for every candidate in a batch against a JD.

        Parsing and deduplication are not repeated: the stored profile and dedup
        trace are reused, and only the original text is re-read for keyword and
        LLM scoring. Recruiter stage overrides are kept; their auto route updates.
        """
        batch = self.store.get_batch(batch_id)
        if batch is None:
            raise ProcessingError("batch_not_found", "Batch not found.", 404)
        jd = self.jobs.get(jd_id or batch["jd_id"])
        if jd is None:
            raise ProcessingError("jd_not_found", "Job description not found.", 404)
        if batch["status"] == "running":
            raise ProcessingError("batch_running", "Wait for the batch to finish before rescoring it.", 409)

        rows = [c for c in self.store.workspace_candidates(batch["workspace"]) if c["batch_id"] == batch_id]
        started = time.perf_counter()
        rescored, skipped, moved = 0, [], 0
        for c in rows:
            meta = c["file"]
            source = (config.SAMPLE_RESUMES_DIR / meta["sample_name"]) if meta.get("sample_name") \
                else (config.UPLOAD_DIR / meta["stored_path"]) if meta.get("stored_path") else None
            if source is None or not source.exists():
                skipped.append(meta["name"])
                continue
            try:
                text = extract_text(source)["text"]
            except ResumeParseError:
                skipped.append(meta["name"])
                continue
            result = self.scorer.score(c["profile"], text, jd, c["dedup"], provider=batch["provider"])
            previous_stage = c["stage"]

            def _apply(rec: Dict[str, Any], result=result) -> None:
                for key in ("scores", "weights", "thresholds", "evidence", "knockout", "skills", "recommendation", "engine"):
                    rec[key] = result[key]
                # A duplicate stays a duplicate unless a recruiter cleared it.
                rec["auto_stage"] = "duplicate" if rec["dedup"]["is_duplicate"] else result["auto_stage"]
                if not rec["stage_overridden"]:
                    rec["stage"] = rec["auto_stage"]
                rec["stage_overridden"] = rec["stage"] != rec["auto_stage"]
                rec["jd"] = {"id": jd["id"], "title": jd["title"], "experience_min": jd["experience_min"],
                             "experience_max": jd["experience_max"], "city": jd["city"], "work_mode": jd["work_mode"]}
                rec["rescored_at"] = now_iso()
            updated = self.store.update_candidate(c["id"], _apply)
            rescored += 1
            if updated and updated["stage"] != previous_stage:
                moved += 1

        def _retarget(b: Dict[str, Any]) -> None:
            b["jd_id"], b["jd_title"] = jd["id"], jd["title"]
            b["rescored_at"] = now_iso()
        self.store.update_batch(batch_id, _retarget)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        self.audit.log("batch.rescored", batch["workspace"], batch_id=batch_id, actor=actor,
                       detail=f"{rescored} candidates rescored against {jd['title']} · {moved} changed stage"
                              f"{f' · {len(skipped)} skipped (original file unavailable)' if skipped else ''}")
        return {"batch_id": batch_id, "jd_id": jd["id"], "jd_title": jd["title"], "rescored": rescored,
                "changed_stage": moved, "skipped": skipped, "elapsed_ms": elapsed_ms}

    def reset_workspace(self, workspace: str, actor: str = "recruiter", reason: str = "") -> Dict[str, int]:
        removed = self.store.reset_workspace(workspace)
        registry = self.dedup.reset(workspace)
        self.audit.log("workspace.reset", workspace, actor=actor,
                       detail=f"{reason or 'Workspace cleared'} · {removed['candidates']} candidates, "
                              f"{removed['batches']} batches, {registry} registry entries removed")
        return {**removed, "registry_entries": registry}

    # -- files -----------------------------------------------------------------
    def process(self, batch_id: str, filename: str, file_bytes: bytes, source: str,
                sample_path: Optional[Path] = None) -> Dict[str, Any]:
        batch = self.store.get_batch(batch_id)
        if batch is None:
            raise ProcessingError("batch_not_found", "Batch not found.", 404)
        jd = self.jobs.get(batch["jd_id"])
        if jd is None:
            raise ProcessingError("jd_not_found", "The batch's job description was deleted.", 409)
        name = _safe_name(filename)
        ext = Path(name).suffix.lower()
        started = time.perf_counter()
        self.bus.emit(batch_id, "file.started", file=name)
        try:
            if ext not in config.SUPPORTED_RESUME_EXTENSIONS:
                raise ProcessingError("unsupported_format",
                                      f"{ext or 'No extension'} is not supported. Use PDF, DOCX or TXT.")
            if len(file_bytes) > config.MAX_UPLOAD_BYTES:
                raise ProcessingError("too_large", f"File is {len(file_bytes) / 1_048_576:.1f} MB; the limit is {config.MAX_UPLOAD_MB} MB.")
            if not file_bytes:
                raise ProcessingError("empty_file", "File is empty.")

            candidate_id = new_id("cand")
            if sample_path is not None:
                text_path, stored_path = sample_path, None
            else:
                stored_path = f"{candidate_id}{ext}"
                text_path = config.UPLOAD_DIR / stored_path
                text_path.write_bytes(file_bytes)

            # 1. Parse
            t0 = time.perf_counter()
            try:
                extracted = extract_text(text_path)
            except ResumeParseError as exc:
                if stored_path:
                    text_path.unlink(missing_ok=True)
                raise ProcessingError(exc.code, exc.message) from exc
            profile = parse_resume(extracted["text"], name)
            parse_ms = (time.perf_counter() - t0) * 1000
            self.bus.emit(batch_id, "file.parsed", file=name, name=profile["name"], ms=round(parse_ms, 1),
                          skills=len(profile["skills"]))

            # 2. Deduplicate (check + register atomically)
            t1 = time.perf_counter()
            prints = self.dedup.fingerprints(file_bytes, extracted["text"], profile)
            with self.dedup.lock:
                dedup = self.dedup.check(batch["workspace"], prints)
                if not dedup["is_duplicate"]:
                    self.dedup.register(batch["workspace"], candidate_id, profile["name"], name, prints)
            dedup_ms = (time.perf_counter() - t1) * 1000
            self.bus.emit(batch_id, "file.deduped", file=name, status=dedup["status"], ms=round(dedup_ms, 1),
                          layer=dedup["primary_layer"],
                          duplicate_of=(dedup.get("duplicate_of") or {}).get("name"))

            # 3. Score and route
            t2 = time.perf_counter()
            result = self.scorer.score(profile, extracted["text"], jd, dedup, provider=batch["provider"])
            score_ms = (time.perf_counter() - t2) * 1000
        except ProcessingError as exc:
            self._record_failure(batch_id, name, exc)
            raise
        except Exception as exc:  # unexpected parser/scorer fault: fail this file, keep the batch alive
            wrapped = ProcessingError("processing_error", f"Could not process file ({exc.__class__.__name__}).", 500)
            self._record_failure(batch_id, name, wrapped)
            raise wrapped from exc

        total_ms = (time.perf_counter() - started) * 1000
        record = {
            "id": candidate_id,
            "workspace": batch["workspace"],
            "batch_id": batch_id,
            "batch_label": batch["label"],
            "source": source,
            "file": {
                "name": name,
                "format": extracted["format"],
                "pages": extracted["pages"],
                "size_bytes": len(file_bytes),
                "sha256": prints["file_sha256"],
                "text_sha256": prints["text_sha256"],
                "stored_path": stored_path,
                "sample_name": sample_path.name if sample_path is not None else None,
            },
            "jd": {"id": jd["id"], "title": jd["title"], "experience_min": jd["experience_min"],
                   "experience_max": jd["experience_max"], "city": jd["city"], "work_mode": jd["work_mode"]},
            "profile": profile,
            "scores": result["scores"],
            "weights": result["weights"],
            "thresholds": result["thresholds"],
            "evidence": result["evidence"],
            "knockout": result["knockout"],
            "skills": result["skills"],
            "dedup": dedup,
            "auto_stage": result["auto_stage"],
            "stage": result["auto_stage"],
            "stage_overridden": False,
            "recommendation": result["recommendation"],
            "engine": result["engine"],
            "metrics": {"parse_ms": round(parse_ms, 1), "dedup_ms": round(dedup_ms, 1),
                        "score_ms": round(score_ms, 1), "total_ms": round(total_ms, 1)},
            "notes": [],
            "scanned_at": now_iso(),
            "updated_at": now_iso(),
        }
        self.store.add_candidate(record)

        def _progress(b: Dict[str, Any]) -> None:
            b["processed"] += 1
            b["duplicates"] += 1 if dedup["is_duplicate"] else 0
            b["busy_ms"] = round((b.get("busy_ms") or 0) + total_ms, 1)
            retried = [f for f in b["failures"] if f["file"] == name]
            if retried:  # a successful retry clears the earlier failure
                b["failures"] = [f for f in b["failures"] if f["file"] != name]
                b["failed"] = max(0, b["failed"] - len(retried))
        batch = self.store.update_batch(batch_id, _progress)

        self.audit.log("candidate.duplicate_flagged" if dedup["is_duplicate"] else "candidate.scored",
                       batch["workspace"], candidate=record,
                       detail=(f"Duplicate of {dedup['duplicate_of']['name']} via {dedup['primary_layer']} layer"
                               if dedup["is_duplicate"] else f"Routed to {STAGES[record['stage']]}"))
        self.bus.emit(batch_id, "file.scored", file=name, candidate_id=candidate_id, name=profile["name"],
                      overall=record["scores"]["overall"], stage=record["stage"], ms=round(total_ms, 1),
                      engine=record["engine"]["label"])
        self._auto_complete(batch)
        return record

    def _record_failure(self, batch_id: str, name: str, exc: ProcessingError) -> None:
        def _fail(b: Dict[str, Any]) -> None:
            b["failed"] += 1
            b["failures"].append({"file": name, "code": exc.code, "message": exc.message, "at": now_iso()})
        batch = self.store.update_batch(batch_id, _fail)
        if batch:
            self.audit.log("file.failed", batch["workspace"], batch_id=batch_id, detail=f"{name}: {exc.message}")
            self.bus.emit(batch_id, "file.failed", file=name, code=exc.code, message=exc.message)
            self._auto_complete(batch)

    def _auto_complete(self, batch: Optional[Dict[str, Any]]) -> None:
        if batch and batch["expected"] and batch["processed"] + batch["failed"] >= batch["expected"]:
            self.complete_batch(batch["id"])
