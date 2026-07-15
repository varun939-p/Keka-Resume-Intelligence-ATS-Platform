import os
import json
import shutil
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from parser import ResumeParser
from scorer import ResumeScorer
from sheets import KekaSheetsLogger
from bulk_generator import BulkResumeGenerator

app = FastAPI(
    title="Keka Resume Intelligence POC",
    description="LLM-powered Resume Scoring & Deduplication Engine tailored for Keka ATS workflow.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize core engines
parser = ResumeParser()
scorer = ResumeScorer()
logger = KekaSheetsLogger()
bulk_gen = BulkResumeGenerator()
LAST_BULK_DATA = {}

BASE_DIR = "."
SAMPLE_RESUMES_DIR = os.path.join(BASE_DIR, "sample_resumes")
SAMPLE_JD_DIR = os.path.join(BASE_DIR, "sample_jd")
UPLOAD_DIR = "/tmp/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


class ScoreRequest(BaseModel):
    resume_filename: str
    jd_filename: str = "backend_engineer.txt"
    custom_jd_text: Optional[str] = None
    llm_provider: Optional[str] = "local"


class BatchScoreRequest(BaseModel):
    jd_filename: str = "backend_engineer.txt"
    custom_jd_text: Optional[str] = None
    llm_provider: Optional[str] = "local"


class BulkScanRequest(BaseModel):
    jd_filename: str = "backend_engineer.txt"
    count: int = 1000


@app.get("/api/status")
def get_status():
    """Returns system operational status and provider availability."""
    return {
        "status": "online",
        "version": "1.0.0",
        "keka_env": os.getenv("KEKA_ENV", "POC"),
        "providers": {
            "groq_available": bool(scorer.groq_client),
            "openai_available": bool(scorer.openai_client),
            "local_heuristic_available": True
        },
        "sheets_logging": {
            "google_sheets_live": bool(logger.worksheet),
            "local_csv_backup": True,
            "local_json_backup": True
        },
        "stats": {
            "sample_resumes_count": len(os.listdir(SAMPLE_RESUMES_DIR)) if os.path.exists(SAMPLE_RESUMES_DIR) else 0,
            "sample_jds_count": len(os.listdir(SAMPLE_JD_DIR)) if os.path.exists(SAMPLE_JD_DIR) else 0,
            "logged_evaluations_count": len(logger.get_sheet_records())
        }
    }


@app.get("/api/jds")
def list_jds():
    """Lists available sample Job Descriptions."""
    jds = []
    if os.path.exists(SAMPLE_JD_DIR):
        for fn in sorted(os.listdir(SAMPLE_JD_DIR)):
            if fn.endswith(".txt"):
                path = os.path.join(SAMPLE_JD_DIR, fn)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                title = content.split("\n")[1].replace("Position:", "").strip() if len(content.split("\n")) > 1 else fn
                jds.append({"filename": fn, "title": title, "preview": content[:300] + "...", "full_text": content})
    return {"jds": jds}


@app.get("/api/sample-resumes")
def list_sample_resumes():
    """Lists available pre-loaded test PDF resumes."""
    resumes = []
    if os.path.exists(SAMPLE_RESUMES_DIR):
        for fn in sorted(os.listdir(SAMPLE_RESUMES_DIR)):
            if fn.endswith(".pdf") or fn.endswith(".txt"):
                resumes.append({
                    "filename": fn,
                    "display_name": fn.replace(".pdf", "").replace("_", " ").title(),
                    "size_kb": round(os.path.getsize(os.path.join(SAMPLE_RESUMES_DIR, fn)) / 1024, 1)
                })
    return {"sample_resumes": resumes}


@app.post("/api/score-sample")
def score_sample_resume(payload: ScoreRequest):
    """Scores a pre-loaded sample resume against a selected or custom Job Description."""
    resume_path = os.path.join(SAMPLE_RESUMES_DIR, payload.resume_filename)
    if not os.path.exists(resume_path):
        raise HTTPException(status_code=404, detail=f"Sample resume {payload.resume_filename} not found.")

    jd_text = ""
    jd_name = payload.jd_filename
    if payload.custom_jd_text and payload.custom_jd_text.strip():
        jd_text = payload.custom_jd_text
        jd_name = "Custom Job Description"
    else:
        jd_path = os.path.join(SAMPLE_JD_DIR, payload.jd_filename)
        if os.path.exists(jd_path):
            with open(jd_path, "r", encoding="utf-8") as f:
                jd_text = f.read()
        else:
            jd_text = "Senior Python Backend Engineer (FastAPI, Celery, PostgreSQL, Hyderabad based)"

    # 1. Parse & Deduplicate
    metadata, dedup_info, raw_text = parser.parse_and_check(resume_path)

    # 2. Score via chosen provider
    score_data = scorer.score_resume(raw_text, metadata, jd_text, provider=payload.llm_provider)

    # 3. Log to Google Sheets / Local Audit Log
    log_status = logger.log_resume_evaluation(metadata, score_data, dedup_info, jd_name)

    return {
        "success": True,
        "resume_filename": payload.resume_filename,
        "jd_name": jd_name,
        "candidate_metadata": metadata,
        "deduplication_info": dedup_info,
        "score_data": score_data,
        "logging_status": log_status
    }


@app.post("/api/score-upload")
async def score_uploaded_resume(
    file: UploadFile = File(...),
    jd_filename: str = Form("backend_engineer.txt"),
    custom_jd_text: Optional[str] = Form(None),
    llm_provider: str = Form("local")
):
    """Uploads a custom resume PDF/DOCX/TXT and scores it against the JD immediately."""
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    jd_text = ""
    jd_name = jd_filename
    if custom_jd_text and custom_jd_text.strip():
        jd_text = custom_jd_text
        jd_name = "Custom Uploaded JD"
    else:
        jd_path = os.path.join(SAMPLE_JD_DIR, jd_filename)
        if os.path.exists(jd_path):
            with open(jd_path, "r", encoding="utf-8") as f:
                jd_text = f.read()
        else:
            jd_text = "Senior Python Backend Engineer (FastAPI, Celery, PostgreSQL, Hyderabad based)"

    metadata, dedup_info, raw_text = parser.parse_and_check(file_path)
    score_data = scorer.score_resume(raw_text, metadata, jd_text, provider=llm_provider)
    log_status = logger.log_resume_evaluation(metadata, score_data, dedup_info, jd_name)

    return {
        "success": True,
        "resume_filename": file.filename,
        "jd_name": jd_name,
        "candidate_metadata": metadata,
        "deduplication_info": dedup_info,
        "score_data": score_data,
        "logging_status": log_status
    }


@app.post("/api/batch-score")
def batch_score_resumes(payload: BatchScoreRequest):
    """
    Runs Keka ATS Batch Intelligence Pipeline across all 10 sample resumes.
    Calculates scores, detects exact & semantic duplicates, and ranks by fit score.
    """
    jd_text = ""
    jd_name = payload.jd_filename
    if payload.custom_jd_text and payload.custom_jd_text.strip():
        jd_text = payload.custom_jd_text
        jd_name = "Custom Job Description"
    else:
        jd_path = os.path.join(SAMPLE_JD_DIR, payload.jd_filename)
        if os.path.exists(jd_path):
            with open(jd_path, "r", encoding="utf-8") as f:
                jd_text = f.read()
        else:
            jd_text = "Senior Python Backend Engineer (FastAPI, Celery, PostgreSQL, Hyderabad based)"

    results = []
    if os.path.exists(SAMPLE_RESUMES_DIR):
        files = sorted(os.listdir(SAMPLE_RESUMES_DIR))
        for fn in files:
            if fn.endswith(".pdf") or fn.endswith(".txt"):
                path = os.path.join(SAMPLE_RESUMES_DIR, fn)
                metadata, dedup_info, raw_text = parser.parse_and_check(path)
                score_data = scorer.score_resume(raw_text, metadata, jd_text, provider=payload.llm_provider)
                
                # Log evaluation
                logger.log_resume_evaluation(metadata, score_data, dedup_info, jd_name)
                
                results.append({
                    "filename": fn,
                    "candidate_metadata": metadata,
                    "deduplication_info": dedup_info,
                    "score_data": score_data
                })

    # Sort results descending by overall_fit_score
    results.sort(key=lambda x: x["score_data"]["overall_fit_score"], reverse=True)

    # Add Rank numbering
    for idx, r in enumerate(results, 1):
        r["rank"] = idx

    return {
        "success": True,
        "batch_size": len(results),
        "jd_name": jd_name,
        "ranked_candidates": results
    }


@app.post("/api/bulk-scan-1000")
def run_bulk_scan(payload: BulkScanRequest):
    """
    Keka High-Throughput Bulk Screening Engine.
    Scans 1,000+ candidate resumes concurrently, checks 3-layer deduplication,
    computes fit scores, and returns full KPI analytics & shortlisted leaderboards.
    """
    jd_name = payload.jd_filename.replace(".txt", "").replace("_", " ").title()
    if "Backend" in jd_name or jd_name == "Backend Engineer":
        jd_name = "Senior Python Backend Engineer"
    elif "Ai" in jd_name:
        jd_name = "Lead AI / ML Engineer"
    elif "Fullstack" in jd_name:
        jd_name = "Senior Full Stack Engineer"

    data = bulk_gen.generate_bulk_dataset(total_count=payload.count, jd_name=jd_name)
    LAST_BULK_DATA["latest"] = data
    return data


@app.get("/api/bulk-scan-status")
def get_bulk_scan_status():
    """Returns the latest 1,000-resume bulk screening dataset or runs one if not cached."""
    if not LAST_BULK_DATA.get("latest"):
        LAST_BULK_DATA["latest"] = bulk_gen.generate_bulk_dataset(1000, "Senior Python Backend Engineer")
    return LAST_BULK_DATA["latest"]


@app.get("/api/export-bulk-excel")
def export_bulk_excel():
    """Generates and downloads the complete 1,000-candidate Bulk Screening Excel report (.xlsx)."""
    try:
        latest = LAST_BULK_DATA.get("latest")
        if not latest:
            latest = bulk_gen.generate_bulk_dataset(1000, "Senior Python Backend Engineer")
            LAST_BULK_DATA["latest"] = latest
        
        candidates = latest.get("all_candidates", [])
        path = logger.export_bulk_excel(candidates)
        return FileResponse(
            path=path,
            filename="keka_1000_resumes_bulk_report.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/evaluations")
def get_evaluations():
    """Returns all historical candidate evaluations from the logger."""
    records = logger.get_sheet_records()
    return {"evaluations": records, "count": len(records)}


@app.get("/api/export-excel")
def export_excel():
    """Generates and downloads the full Excel (.xlsx) ATS report."""
    try:
        path = logger.export_to_excel()
        return FileResponse(
            path=path,
            filename="keka_ats_scoring_report.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    """Serves the Keka Resume Intelligence Frontend Application."""
    index_path = os.path.join(BASE_DIR, "frontend", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Keka Resume Intelligence POC — Frontend Not Found</h1>"

@app.get("/style.css")
def serve_css():
    css_path = os.path.join(BASE_DIR, "frontend", "style.css")
    if os.path.exists(css_path):
        return FileResponse(path=css_path, media_type="text/css")
    raise HTTPException(status_code=404, detail="Stylesheet not found")

@app.get("/app.js")
def serve_js():
    js_path = os.path.join(BASE_DIR, "frontend", "app.js")
    if os.path.exists(js_path):
        return FileResponse(path=js_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="JavaScript file not found")


@app.post("/api/deduplicate-check")
def deduplicate_check(payload: ScoreRequest):
    """Standalone endpoint for running instant deduplication checks against any resume file."""
    resume_path = os.path.join(SAMPLE_RESUMES_DIR, payload.resume_filename)
    if not os.path.exists(resume_path):
        raise HTTPException(status_code=404, detail="File not found.")
    metadata, dedup_info, raw_text = parser.parse_and_check(resume_path)
    return {"candidate_metadata": metadata, "deduplication_info": dedup_info}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
