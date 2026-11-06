"""
Runtime configuration for the Resume Intelligence ATS service.

All paths resolve from here so the app runs the same way locally (persistent
./data directory) and on Vercel (ephemeral /tmp, the only writable location).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

APP_NAME = "Keka Resume Intelligence"
APP_VERSION = "2.0.0"


def _default_data_dir() -> Path:
    override = os.getenv("KEKA_DATA_DIR", "").strip()
    if override:
        return Path(override)
    if os.getenv("VERCEL"):
        return Path("/tmp/keka")
    return BASE_DIR / "data"


DATA_DIR = _default_data_dir()
UPLOAD_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "exports"

SAMPLE_RESUMES_DIR = BASE_DIR / "sample_resumes"
SAMPLE_JD_DIR = BASE_DIR / "sample_jd"
FRONTEND_DIR = BASE_DIR / "frontend"

CANDIDATES_FILE = DATA_DIR / "candidates.json"
BATCHES_FILE = DATA_DIR / "batches.json"
CUSTOM_JDS_FILE = DATA_DIR / "custom_jds.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
REGISTRY_FILE = DATA_DIR / "dedup_registry.json"
AUDIT_CSV_FILE = DATA_DIR / "keka_sheets_audit_log.csv"
AUDIT_JSON_FILE = DATA_DIR / "keka_sheets_audit_log.json"

# 10 MB per file locally. Vercel rejects request bodies over 4.5 MB before they reach
# the app, so the cap drops to 4 MB there and oversized files get a clear message.
MAX_UPLOAD_BYTES = (4 if os.getenv("VERCEL") else 10) * 1024 * 1024
MAX_UPLOAD_MB = MAX_UPLOAD_BYTES // (1024 * 1024)
SUPPORTED_RESUME_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
SUPPORTED_JD_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}

WORKSPACES = ("demo", "live")


def _clean_secret(name: str) -> str:
    """Returns an env value, treating template placeholders as unset."""
    value = os.getenv(name, "").strip()
    if not value or value.lower().startswith("your_") or value.lower().startswith("your-"):
        return ""
    return value


GROQ_API_KEY = _clean_secret("GROQ_API_KEY")
OPENAI_API_KEY = _clean_secret("OPENAI_API_KEY")
DEFAULT_LLM_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "deterministic").strip().lower() or "deterministic"
GROQ_MODEL = os.getenv("DEFAULT_GROQ_MODEL", "llama-3.3-70b-versatile").strip()
OPENAI_MODEL = os.getenv("DEFAULT_OPENAI_MODEL", "gpt-4o-mini").strip()
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))

GOOGLE_SHEET_ID = _clean_secret("GOOGLE_SHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json").strip()

KEKA_ENV = os.getenv("KEKA_ENV", "POC").strip()


def ensure_dirs() -> None:
    for path in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def service_account_path() -> Path:
    path = Path(GOOGLE_SERVICE_ACCOUNT_JSON)
    return path if path.is_absolute() else BASE_DIR / path
