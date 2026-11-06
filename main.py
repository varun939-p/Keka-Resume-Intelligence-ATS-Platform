"""
Keka Resume Intelligence — REST API and dashboard host.

Run locally:  venv/Scripts/python main.py   (or: uvicorn main:app --reload)
Dashboard:    http://127.0.0.1:8000/
API docs:     http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
from dedup import DedupEngine
from parser import ResumeParseError, extract_text
from pipeline import Pipeline, ProcessingError
from scorer import STAGES, ResumeScorer, profile_jd
from sheets import AuditLog, ExcelReport, SheetsSync
from store import JobLibrary, Store, analytics, now_iso, public_jd

config.ensure_dirs()
store = Store()
jobs = JobLibrary()
dedup_engine = DedupEngine(config.REGISTRY_FILE)
scorer = ResumeScorer()
audit = AuditLog()
sheets = SheetsSync()
excel = ExcelReport()
pipeline = Pipeline(store, jobs, dedup_engine, scorer, audit)
STARTED_AT = time.time()

app = FastAPI(
    title=f"{config.APP_NAME} API",
    version=config.APP_VERSION,
    description="Resume parsing, three-layer deduplication, multi-dimensional scoring and stage routing.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

Workspace = Literal["demo", "live"]
StageKey = Literal["shortlisted", "technical_review", "hold", "rejected", "duplicate"]


# ---------------------------------------------------------------------------
# Errors: one JSON shape everywhere -> {"error": {"code", "message"}}
# ---------------------------------------------------------------------------

def _error(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, **extra}})


@app.exception_handler(ProcessingError)
async def _processing_error(_request: Request, exc: ProcessingError) -> JSONResponse:
    return _error(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "request"
    return _error(422, "invalid_request", f"{field}: {first.get('msg', 'invalid value')}")


@app.exception_handler(HTTPException)
async def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        return _error(exc.status_code, exc.detail.get("code", "error"), exc.detail.get("message", ""))
    return _error(exc.status_code, "error", str(exc.detail))


def not_found(what: str) -> HTTPException:
    return HTTPException(404, {"code": "not_found", "message": f"{what} not found."})


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def slim_candidate(c: Dict[str, Any]) -> Dict[str, Any]:
    p, s = c["profile"], c["skills"]
    return {
        "id": c["id"],
        "name": p.get("name"),
        "email": p.get("email"),
        "phone": p.get("phone"),
        "title": p.get("current_title"),
        "company": p.get("current_company"),
        "city": p.get("city"),
        "years": p.get("total_experience_years"),
        "scores": c["scores"],
        "thresholds": c["thresholds"],
        "stage": c["stage"],
        "auto_stage": c["auto_stage"],
        "stage_overridden": c["stage_overridden"],
        "knockout": bool(c.get("knockout")),
        "dedup": {
            "status": c["dedup"]["status"],
            "primary_layer": c["dedup"]["primary_layer"],
            "duplicate_of": c["dedup"].get("duplicate_of"),
            "layers": [{"key": l["key"], "status": l["status"]} for l in c["dedup"]["layers"]],
        },
        "skills": {
            "critical": s["counts"]["critical"],
            "missing_critical": s["missing_critical"],
            "matched": s["matched"][:6],
            "critical_coverage": s["critical_coverage"],
        },
        "batch_id": c["batch_id"],
        "batch_label": c.get("batch_label"),
        "jd_title": c["jd"]["title"],
        "file_name": c["file"]["name"],
        "engine": c["engine"]["label"],
        "total_ms": c["metrics"]["total_ms"],
        "notes": len(c.get("notes", [])),
        "scanned_at": c["scanned_at"],
    }


def public_batch(b: Dict[str, Any]) -> Dict[str, Any]:
    return {**b, "summary": pipeline.batch_summary(b)}


def _require_candidate(candidate_id: str, workspace: Optional[str] = None) -> Dict[str, Any]:
    """Looks a candidate up; with a workspace, a candidate from the other workspace is treated as missing."""
    record = store.get_candidate(candidate_id)
    if record is None or (workspace and record["workspace"] != workspace):
        raise not_found("Candidate")
    return record


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "environment": config.KEKA_ENV,
        "uptime_s": round(time.time() - STARTED_AT),
        "data_dir": str(config.DATA_DIR),
        "storage": "ephemeral (/tmp)" if str(config.DATA_DIR).startswith("/tmp") else "persistent (local disk)",
        "candidates": {ws: len(store.workspace_candidates(ws)) for ws in config.WORKSPACES},
        "audit_events": audit.counts(),
    }


@app.get("/api/settings")
def get_settings() -> Dict[str, Any]:
    providers = scorer.providers()
    requested = store.settings.get("provider", "deterministic")
    return {
        "provider": scorer.resolve_provider(requested),
        "requested_provider": requested,
        "providers": providers,
        "sheets": sheets.status(),
        "limits": {"max_file_mb": config.MAX_UPLOAD_MB,
                   "formats": sorted(e.lstrip(".").upper() for e in config.SUPPORTED_RESUME_EXTENSIONS)},
    }


class SettingsPatch(BaseModel):
    provider: Literal["deterministic", "groq", "openai"]


@app.patch("/api/settings")
def patch_settings(payload: SettingsPatch) -> Dict[str, Any]:
    providers = scorer.providers()
    if not providers[payload.provider]["available"]:
        raise HTTPException(409, {"code": "provider_unavailable",
                                  "message": f"{providers[payload.provider]['label']} needs {providers[payload.provider]['missing']} in .env."})
    store.update_settings({"provider": payload.provider})
    audit.log("settings.updated", "live", actor="recruiter", detail=f"Scoring engine set to {payload.provider}")
    return get_settings()


@app.get("/api/integrations")
def integrations() -> Dict[str, Any]:
    providers = scorer.providers()
    sheet = sheets.status()
    return {
        "llm": providers,
        "sheets": sheet,
        "env": [
            {"key": "GROQ_API_KEY", "set": providers["groq"]["available"], "purpose": "Hybrid LLM scoring via Groq"},
            {"key": "OPENAI_API_KEY", "set": providers["openai"]["available"], "purpose": "Hybrid LLM scoring via OpenAI"},
            {"key": "GOOGLE_SHEET_ID", "set": bool(config.GOOGLE_SHEET_ID), "purpose": "Target spreadsheet for sync"},
            {"key": "GOOGLE_SERVICE_ACCOUNT_JSON", "set": config.service_account_path().exists(),
             "purpose": f"Service account key file ({config.GOOGLE_SERVICE_ACCOUNT_JSON})"},
        ],
        "audit_files": {"csv": config.AUDIT_CSV_FILE.name, "json": config.AUDIT_JSON_FILE.name},
    }


class SyncRequest(BaseModel):
    workspace: Workspace = "live"


@app.post("/api/integrations/sheets/sync")
def sync_sheets(payload: SyncRequest) -> Dict[str, Any]:
    status = sheets.status()
    if not status["configured"]:
        raise HTTPException(409, {"code": "sheets_not_configured",
                                  "message": "Google Sheets is not connected. Missing: " + ", ".join(status["missing"]) + "."})
    rows = store.workspace_candidates(payload.workspace)
    try:
        result = sheets.sync(rows)
    except RuntimeError as exc:
        raise HTTPException(502, {"code": "sheets_sync_failed", "message": str(exc)})
    audit.log("sheets.synced", payload.workspace, actor="recruiter", detail=f"{result['rows']} rows mirrored to Google Sheets")
    return result


@app.post("/api/workspaces/{workspace}/reset")
def reset_workspace(workspace: Workspace) -> Dict[str, Any]:
    return {"workspace": workspace, "removed": pipeline.reset_workspace(workspace, reason="Reset from dashboard")}


# ---------------------------------------------------------------------------
# Job descriptions
# ---------------------------------------------------------------------------

@app.get("/api/jds")
def list_jds(workspace: Workspace = "live") -> Dict[str, Any]:
    return {"jds": [public_jd(j) for j in jobs.list(workspace)]}


@app.get("/api/jds/{jd_id}")
def get_jd(jd_id: str) -> Dict[str, Any]:
    jd = jobs.get(jd_id)
    if jd is None:
        raise not_found("Job description")
    return public_jd(jd, include_text=True)


class JDPayload(BaseModel):
    title: str = Field(..., min_length=2, max_length=120)
    text: str = Field(..., min_length=40, max_length=40000)
    location: Optional[str] = Field(None, max_length=120)
    experience_min: Optional[float] = Field(None, ge=0, le=40)
    experience_max: Optional[float] = Field(None, ge=0, le=45)
    weights: Optional[Dict[str, float]] = None
    thresholds: Optional[Dict[str, float]] = None
    requirements: Optional[Dict[str, List[str]]] = None
    filename: Optional[str] = None


@app.post("/api/jds", status_code=201)
def create_jd(payload: JDPayload) -> Dict[str, Any]:
    jd = jobs.save_custom(payload.model_dump())
    audit.log("jd.created", "live", actor="recruiter", detail=f"{jd['title']} · weights {jd['weights']}")
    return public_jd(jd, include_text=True)


@app.put("/api/jds/{jd_id}")
def update_jd(jd_id: str, payload: JDPayload) -> Dict[str, Any]:
    existing = jobs.get(jd_id)
    if existing is None:
        raise not_found("Job description")
    if existing["kind"] != "custom":
        raise HTTPException(409, {"code": "read_only", "message": "Sample job descriptions are read-only. Copy one to Live to edit it."})
    jd = jobs.save_custom(payload.model_dump(), jd_id=jd_id)
    audit.log("jd.updated", "live", actor="recruiter", detail=f"{jd['title']} · weights {jd['weights']} · thresholds {jd['thresholds']}")
    return public_jd(jd, include_text=True)


@app.delete("/api/jds/{jd_id}")
def delete_jd(jd_id: str) -> Dict[str, Any]:
    jd = jobs.get(jd_id)
    if jd is None:
        raise not_found("Job description")
    if jd["kind"] != "custom":
        raise HTTPException(409, {"code": "read_only", "message": "Sample job descriptions cannot be deleted."})
    jobs.delete_custom(jd_id)
    audit.log("jd.deleted", "live", actor="recruiter", detail=jd["title"])
    return {"deleted": jd_id}


class AnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=40000)
    title: Optional[str] = None


@app.post("/api/jds/analyze")
def analyze_jd(payload: AnalyzeRequest) -> Dict[str, Any]:
    prof = profile_jd(payload.text, title=payload.title or None)
    prof.pop("keyword_vector", None)
    return prof


@app.post("/api/jds/extract")
async def extract_jd(file: UploadFile = File(...)) -> Dict[str, Any]:
    name = Path(file.filename or "jd.txt").name
    ext = Path(name).suffix.lower()
    if ext not in config.SUPPORTED_JD_EXTENSIONS:
        raise HTTPException(415, {"code": "unsupported_format", "message": f"{ext or 'File'} is not supported for job descriptions. Use TXT, PDF or DOCX."})
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, {"code": "too_large", "message": f"Job description file exceeds {config.MAX_UPLOAD_MB} MB."})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"jd{ext}"
        path.write_bytes(data)
        try:
            text = extract_text(path)["text"]
        except ResumeParseError as exc:
            raise HTTPException(422, {"code": exc.code, "message": exc.message})
    prof = profile_jd(text)
    prof.pop("keyword_vector", None)
    return {"filename": name, "text": text, "profile": prof}


# ---------------------------------------------------------------------------
# Samples and batches
# ---------------------------------------------------------------------------

def _sample_files() -> List[Path]:
    files = [p for p in config.SAMPLE_RESUMES_DIR.iterdir()
             if p.is_file() and p.suffix.lower() in config.SUPPORTED_RESUME_EXTENSIONS]

    def natural(p: Path):
        return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]
    return sorted(files, key=natural)


@app.get("/api/samples")
def list_samples() -> Dict[str, Any]:
    rows = []
    for path in _sample_files():
        label = re.sub(r"^resume_\d+_", "", path.stem).replace("_", " ")
        rows.append({"filename": path.name, "label": label.title(), "format": path.suffix.lstrip(".").upper(),
                     "size_kb": round(path.stat().st_size / 1024, 1)})
    return {"samples": rows}


class BatchCreate(BaseModel):
    workspace: Workspace
    jd_id: str
    expected: int = Field(0, ge=0, le=5000)
    provider: Optional[Literal["deterministic", "groq", "openai"]] = None
    label: Optional[str] = Field(None, max_length=80)
    reset: Optional[bool] = None


@app.post("/api/batches", status_code=201)
def create_batch(payload: BatchCreate) -> Dict[str, Any]:
    reset = payload.reset if payload.reset is not None else payload.workspace == "demo"
    batch = pipeline.create_batch(payload.workspace, payload.jd_id, payload.expected, payload.provider, payload.label, reset)
    return public_batch(batch)


@app.get("/api/batches")
def list_batches(workspace: Workspace = "live") -> Dict[str, Any]:
    return {"batches": [public_batch(b) for b in store.list_batches(workspace)]}


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str) -> Dict[str, Any]:
    batch = store.get_batch(batch_id)
    if batch is None:
        raise not_found("Batch")
    return public_batch(batch)


class SampleItem(BaseModel):
    filename: str


@app.post("/api/batches/{batch_id}/samples")
def process_sample(batch_id: str, payload: SampleItem) -> Dict[str, Any]:
    path = next((p for p in _sample_files() if p.name == payload.filename), None)
    if path is None:
        raise not_found("Sample resume")
    record = pipeline.process(batch_id, path.name, path.read_bytes(), source="sample", sample_path=path)
    return {"candidate": slim_candidate(record), "metrics": record["metrics"], "dedup": record["dedup"]["status"]}


@app.post("/api/batches/{batch_id}/files")
async def process_upload(batch_id: str, file: UploadFile = File(...), relative_path: Optional[str] = Form(None)) -> Dict[str, Any]:
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    name = relative_path or file.filename or "resume"
    record = await asyncio.to_thread(pipeline.process, batch_id, name, data, "upload")
    return {"candidate": slim_candidate(record), "metrics": record["metrics"], "dedup": record["dedup"]["status"]}


class RescoreRequest(BaseModel):
    jd_id: Optional[str] = None


@app.post("/api/batches/{batch_id}/rescore")
def rescore_batch(batch_id: str, payload: RescoreRequest) -> Dict[str, Any]:
    """Re-score every candidate in a batch against a JD (or the batch's own JD with its current weights)."""
    return pipeline.rescore_batch(batch_id, payload.jd_id)


@app.post("/api/batches/{batch_id}/complete")
def complete_batch(batch_id: str) -> Dict[str, Any]:
    return public_batch(pipeline.complete_batch(batch_id))


@app.get("/api/batches/{batch_id}/events")
async def batch_events(batch_id: str, request: Request, after: int = 0) -> StreamingResponse:
    if store.get_batch(batch_id) is None:
        raise not_found("Batch")
    last = int(request.headers.get("last-event-id") or after or 0)

    async def stream():
        nonlocal last
        deadline = time.monotonic() + 15 * 60
        idle = 0.0
        yield "retry: 2000\n\n"
        while time.monotonic() < deadline:
            if await request.is_disconnected():
                return
            events = pipeline.bus.since(batch_id, last)
            for event in events:
                last = event["seq"]
                yield f"id: {event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"
                if event["type"] == "batch.completed":
                    return
            idle = 0.0 if events else idle + 0.25
            if idle >= 15:
                idle = 0.0
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

SortKey = Literal["overall", "technical", "experience", "impact", "education", "years", "name", "stage", "scanned_at"]


@app.get("/api/candidates")
def list_candidates(
    workspace: Workspace = "live",
    batch_id: Optional[str] = None,
    stage: Optional[str] = None,
    q: Optional[str] = Query(None, max_length=120),
    jd_id: Optional[str] = None,
    min_score: Optional[int] = Query(None, ge=0, le=100),
    sort: SortKey = "overall",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    base = store.query_candidates(workspace, batch_id=batch_id, q=q, jd_id=jd_id, min_score=min_score, sort=sort, order=order)
    counts = {key: 0 for key in STAGES}
    for c in base:
        counts[c["stage"]] += 1
    rows = [c for c in base if not stage or stage == "all" or c["stage"] == stage]
    return {
        "total": len(rows),
        "stage_counts": {"all": len(base), **counts},
        "rows": [slim_candidate(c) for c in rows[offset: offset + limit]],
    }


@app.get("/api/candidates/{candidate_id}")
def get_candidate(candidate_id: str, workspace: Optional[Workspace] = None) -> Dict[str, Any]:
    record = _require_candidate(candidate_id, workspace)
    history = audit.entries(candidate_id=candidate_id, limit=50)["entries"]
    return {**record, "history": history}


class CandidatePatch(BaseModel):
    stage: Optional[StageKey] = None
    note: Optional[str] = Field(None, max_length=2000)


@app.patch("/api/candidates/{candidate_id}")
def update_candidate(candidate_id: str, payload: CandidatePatch, workspace: Optional[Workspace] = None) -> Dict[str, Any]:
    record = _require_candidate(candidate_id, workspace)
    if payload.stage is None and not (payload.note and payload.note.strip()):
        raise HTTPException(400, {"code": "empty_patch", "message": "Send a stage or a note."})
    previous = record["stage"]

    def _apply(c: Dict[str, Any]) -> None:
        if payload.stage:
            c["stage"] = payload.stage
            c["stage_overridden"] = payload.stage != c["auto_stage"]
        if payload.note and payload.note.strip():
            c["notes"].append({"text": payload.note.strip(), "at": now_iso(), "author": "Recruiter"})

    record = store.update_candidate(candidate_id, _apply)
    if payload.stage and payload.stage != previous:
        audit.log("candidate.stage_changed", record["workspace"], candidate=record, actor="recruiter",
                  detail=f"{STAGES[previous]} -> {STAGES[payload.stage]}")
    if payload.note and payload.note.strip():
        audit.log("candidate.note_added", record["workspace"], candidate=record, actor="recruiter",
                  detail=payload.note.strip()[:200])
    return get_candidate(candidate_id)


class BulkAction(BaseModel):
    ids: List[str] = Field(..., min_length=1, max_length=2000)
    action: Literal["stage", "delete", "restore_auto"]
    stage: Optional[StageKey] = None
    workspace: Optional[Workspace] = None


@app.post("/api/candidates/bulk")
def bulk_candidates(payload: BulkAction) -> Dict[str, Any]:
    found = [store.get_candidate(i) for i in payload.ids]
    found = [c for c in found if c]
    if not found:
        raise not_found("Candidates")
    if payload.workspace:
        outside = [c for c in found if c["workspace"] != payload.workspace]
        if outside:
            raise HTTPException(404, {"code": "not_found", "message": (
                f"{len(outside)} of the selected candidates are not in the {payload.workspace.title()} workspace.")})
    if payload.action == "delete":
        removed = store.delete_candidates([c["id"] for c in found])
        dedup_engine.remove([c["id"] for c in removed])
        for c in removed:
            audit.log("candidate.deleted", c["workspace"], candidate=c, actor="recruiter", detail="Removed from talent pool")
        return {"action": "delete", "affected": len(removed)}
    if payload.action == "stage" and not payload.stage:
        raise HTTPException(400, {"code": "stage_required", "message": "Choose a stage to move candidates to."})
    changed = 0
    for c in found:
        target = payload.stage if payload.action == "stage" else c["auto_stage"]
        if c["stage"] == target:
            continue
        previous = c["stage"]

        def _apply(rec: Dict[str, Any], target=target) -> None:
            rec["stage"] = target
            rec["stage_overridden"] = target != rec["auto_stage"]
        updated = store.update_candidate(c["id"], _apply)
        audit.log("candidate.stage_changed", updated["workspace"], candidate=updated, actor="recruiter",
                  detail=f"{STAGES[previous]} -> {STAGES[target]} (bulk)")
        changed += 1
    return {"action": payload.action, "affected": changed}


@app.delete("/api/candidates/{candidate_id}")
def delete_candidate(candidate_id: str, workspace: Optional[Workspace] = None) -> Dict[str, Any]:
    _require_candidate(candidate_id, workspace)
    return bulk_candidates(BulkAction(ids=[candidate_id], action="delete", workspace=workspace))


@app.get("/api/candidates/{candidate_id}/file")
def candidate_file(candidate_id: str, workspace: Optional[Workspace] = None) -> FileResponse:
    record = _require_candidate(candidate_id, workspace)
    meta = record["file"]
    if meta.get("stored_path"):
        path = config.UPLOAD_DIR / meta["stored_path"]
    elif meta.get("sample_name"):
        path = config.SAMPLE_RESUMES_DIR / meta["sample_name"]
    else:
        path = None
    if path is None or not path.exists():
        raise HTTPException(410, {"code": "file_gone", "message": "The original file is no longer stored on the server."})
    media = {"PDF": "application/pdf", "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    return FileResponse(path, filename=meta["name"], media_type=media.get(meta["format"], "text/plain"))


# ---------------------------------------------------------------------------
# Analytics, audit and exports
# ---------------------------------------------------------------------------

@app.get("/api/analytics")
def get_analytics(workspace: Workspace = "live", batch_id: Optional[str] = None) -> Dict[str, Any]:
    return analytics(store, workspace, batch_id)


@app.get("/api/audit")
def get_audit(workspace: Optional[Workspace] = None, event: Optional[str] = None,
              limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)) -> Dict[str, Any]:
    return audit.entries(workspace=workspace, event=event, limit=limit, offset=offset)


@app.get("/api/exports/candidates.xlsx")
def export_excel(workspace: Workspace = "live", batch_id: Optional[str] = None, stage: Optional[str] = None,
                 q: Optional[str] = None, ids: Optional[str] = None) -> FileResponse:
    rows = store.query_candidates(workspace, batch_id=batch_id, stage=stage, q=q)
    if ids:
        wanted = set(ids.split(","))
        rows = [c for c in rows if c["id"] in wanted]
    if not rows:
        raise HTTPException(404, {"code": "nothing_to_export", "message": "No candidates match this view."})
    scope = "Selected candidates" if ids else (next((b["label"] for b in store.list_batches(workspace) if b["id"] == batch_id), "All batches"))
    entries = audit.entries(workspace=workspace, limit=5000)["entries"]
    path = excel.build(rows, entries, {"workspace": workspace, "scope": scope})
    audit.log("export.excel", workspace, actor="recruiter", detail=f"{len(rows)} candidates · {scope}")
    return FileResponse(path, filename=path.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/exports/audit.csv")
def export_audit_csv(workspace: Optional[Workspace] = None) -> StreamingResponse:
    from sheets import AUDIT_COLUMNS
    entries = list(reversed(audit.entries(workspace=workspace, limit=100000)["entries"]))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(AUDIT_COLUMNS)
    for e in entries:
        writer.writerow(["" if e.get(c) is None else e.get(c) for c in AUDIT_COLUMNS])
    name = f"keka_sheets_audit_log{'_' + workspace if workspace else ''}.csv"
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/exports/audit.json")
def export_audit_json(workspace: Optional[Workspace] = None) -> JSONResponse:
    entries = list(reversed(audit.entries(workspace=workspace, limit=100000)["entries"]))
    name = f"keka_sheets_audit_log{'_' + workspace if workspace else ''}.json"
    return JSONResponse(entries, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(config.FRONTEND_DIR)), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:
    index = config.FRONTEND_DIR / "index.html"
    return HTMLResponse(index.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
