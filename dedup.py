"""
Three-layer candidate deduplication engine.

Layer 1  File fingerprint   SHA-256 of the uploaded bytes, plus SHA-256 of the
                            normalized text (catches the same resume re-exported).
Layer 2  Contact hash       SHA-256 of the normalized email and of the last ten
                            phone digits. Raw contact data never enters the registry.
Layer 3  Semantic content   Cosine similarity of term + bigram frequency vectors,
                            which survives reformatting, reordering and retitling.

The registry is scoped per workspace (demo / live) and persisted to
dedup_registry.json. Only unique candidates are registered: a flagged duplicate
always points at the original record, never at another duplicate.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SEMANTIC_MATCH_THRESHOLD = 0.86
SEMANTIC_REVIEW_THRESHOLD = 0.72
VECTOR_TERMS = 400

_STOPWORDS = set(
    "a an the and or of to in on for with at by from as is are was were be been this that these those it its "
    "into over under using use used via per our we i my me you your their they he she his her who which while "
    "across within about after before during than then also more most very such can will able including include "
    "based new high strong deep proven track record years year experience professional".split()
)


def sha256(value: bytes | str) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def normalize_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    local, _, domain = email.strip().lower().partition("@")
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}" if domain else None


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else None


def term_vector(text: str) -> Dict[str, int]:
    tokens = [t for t in re.findall(r"[a-z][a-z0-9+#.]*[a-z0-9+#]|[a-z]", text.lower()) if t not in _STOPWORDS and len(t) > 1]
    counts: Counter = Counter(tokens)
    counts.update(f"{a}_{b}" for a, b in zip(tokens, tokens[1:]))
    return dict(counts.most_common(VECTOR_TERMS))


def cosine(a: Dict[str, int], b: Dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in shared)
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


class DedupEngine:
    def __init__(self, registry_file: Path):
        self.registry_file = registry_file
        self._lock = threading.RLock()
        # Callers hold this across check() + register() so concurrent uploads of
        # the same person cannot both pass as unique.
        self.lock = self._lock
        self._entries: List[Dict[str, Any]] = self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> List[Dict[str, Any]]:
        if not self.registry_file.exists():
            return []
        try:
            data = json.loads(self.registry_file.read_text(encoding="utf-8"))
            # Registries written by the v1 prototype have no workspace field; they are not reusable.
            return [e for e in data if isinstance(e, dict) and e.get("workspace")]
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self) -> None:
        tmp = self.registry_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._entries, indent=1), encoding="utf-8")
        tmp.replace(self.registry_file)

    # -- core --------------------------------------------------------------
    def fingerprints(self, file_bytes: bytes, text: str, profile: Dict[str, Any]) -> Dict[str, Any]:
        normalized = re.sub(r"\s+", " ", text).strip().lower()
        email = normalize_email(profile.get("email"))
        phone = normalize_phone(profile.get("phone"))
        return {
            "file_sha256": sha256(file_bytes),
            "text_sha256": sha256(normalized),
            "email_hash": sha256(email) if email else None,
            "phone_hash": sha256(phone) if phone else None,
            "vector": term_vector(normalized),
        }

    def check(self, workspace: str, prints: Dict[str, Any]) -> Dict[str, Any]:
        """Runs all three layers against the workspace registry and returns a full trace."""
        with self._lock:
            pool = [e for e in self._entries if e["workspace"] == workspace]

        file_hit = next((e for e in pool if e["file_sha256"] == prints["file_sha256"]), None)
        text_hit = None if file_hit else next((e for e in pool if e["text_sha256"] == prints["text_sha256"]), None)
        l1_hit = file_hit or text_hit

        email_hit = next((e for e in pool if prints["email_hash"] and e.get("email_hash") == prints["email_hash"]), None)
        phone_hit = None if email_hit else next(
            (e for e in pool if prints["phone_hash"] and e.get("phone_hash") == prints["phone_hash"]), None)
        l2_hit = email_hit or phone_hit

        best, best_score = None, 0.0
        for entry in pool:
            score = cosine(prints["vector"], entry.get("vector", {}))
            if score > best_score:
                best, best_score = entry, score

        layers = [
            {
                "key": "file",
                "label": "File fingerprint",
                "method": "SHA-256 of file bytes and normalized text",
                "status": "match" if l1_hit else "clear",
                "hash": prints["file_sha256"],
                "detail": ("Identical file bytes" if file_hit else "Identical text, different file") if l1_hit
                else "No identical file in talent pool",
                "matched": self._ref(l1_hit),
            },
            {
                "key": "contact",
                "label": "Contact hash",
                "method": "SHA-256 of normalized email and phone",
                "status": "match" if l2_hit else ("skipped" if not (prints["email_hash"] or prints["phone_hash"]) else "clear"),
                "hash": prints["email_hash"] or prints["phone_hash"],
                "detail": ("Same email address" if email_hit else "Same phone number") if l2_hit
                else ("No email or phone found" if not (prints["email_hash"] or prints["phone_hash"]) else "Contact details are new"),
                "matched": self._ref(l2_hit),
            },
            {
                "key": "semantic",
                "label": "Semantic similarity",
                "method": "Cosine similarity of term and bigram vectors",
                "status": "match" if best_score >= SEMANTIC_MATCH_THRESHOLD
                else ("review" if best_score >= SEMANTIC_REVIEW_THRESHOLD else "clear"),
                "score": round(best_score, 3),
                "threshold": SEMANTIC_MATCH_THRESHOLD,
                "detail": f"{round(best_score * 100, 1)}% similar to closest profile" if best else "Talent pool is empty",
                "matched": self._ref(best) if best_score >= SEMANTIC_REVIEW_THRESHOLD else None,
            },
        ]
        primary = next((layer for layer in layers if layer["status"] == "match"), None)
        original = primary["matched"] if primary else None
        status = "duplicate" if primary else ("review" if layers[2]["status"] == "review" else "unique")
        return {
            "status": status,
            "is_duplicate": bool(primary),
            "primary_layer": primary["key"] if primary else None,
            "duplicate_of": original,
            "layers": layers,
            "pool_size": len(pool),
        }

    @staticmethod
    def _ref(entry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not entry:
            return None
        return {"candidate_id": entry["candidate_id"], "name": entry.get("name"), "filename": entry.get("filename")}

    def register(self, workspace: str, candidate_id: str, name: str, filename: str, prints: Dict[str, Any]) -> None:
        with self._lock:
            self._entries = [e for e in self._entries if e["candidate_id"] != candidate_id]
            self._entries.append({
                "workspace": workspace,
                "candidate_id": candidate_id,
                "name": name,
                "filename": filename,
                "file_sha256": prints["file_sha256"],
                "text_sha256": prints["text_sha256"],
                "email_hash": prints["email_hash"],
                "phone_hash": prints["phone_hash"],
                "vector": prints["vector"],
                "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            self._save()

    def remove(self, candidate_ids: List[str]) -> None:
        ids = set(candidate_ids)
        with self._lock:
            self._entries = [e for e in self._entries if e["candidate_id"] not in ids]
            self._save()

    def reset(self, workspace: str) -> int:
        with self._lock:
            before = len(self._entries)
            self._entries = [e for e in self._entries if e["workspace"] != workspace]
            self._save()
            return before - len(self._entries)

    def size(self, workspace: str) -> int:
        with self._lock:
            return sum(1 for e in self._entries if e["workspace"] == workspace)
