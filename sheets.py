"""
Audit logging, Excel reporting and Google Sheets sync.

AuditLog      Append-only event log written to keka_sheets_audit_log.csv and .json.
ExcelReport   Formatted .xlsx workbook: Summary, Candidates, Skill Gaps, Audit Log.
SheetsSync    Mirrors the candidate table into a Google Sheet via a service account.
              Optional: everything else works without it.
"""
from __future__ import annotations

import csv
import json
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import config
from scorer import STAGES

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:  # pragma: no cover
    gspread = None
    Credentials = None

try:
    from openpyxl import Workbook
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    Workbook = None


AUDIT_COLUMNS = [
    "timestamp", "event", "workspace", "batch_id", "candidate_id", "candidate_name", "email", "job",
    "overall", "technical", "experience", "impact", "education", "stage", "dedup_status", "duplicate_of",
    "engine", "actor", "detail",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AuditLog:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.csv_path = config.AUDIT_CSV_FILE
        self.json_path = config.AUDIT_JSON_FILE
        self._entries: List[Dict[str, Any]] = []
        if self.json_path.exists():
            try:
                loaded = json.loads(self.json_path.read_text(encoding="utf-8"))
                # Keep only v2 events; the v1 prototype wrote a different row shape.
                self._entries = [e for e in loaded if isinstance(e, dict) and e.get("event")]
            except (json.JSONDecodeError, OSError):
                self._entries = []
        if not self.csv_path.exists() or not self._csv_has_v2_header():
            with self.csv_path.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(AUDIT_COLUMNS)

    def _csv_has_v2_header(self) -> bool:
        try:
            with self.csv_path.open(encoding="utf-8") as fh:
                return fh.readline().strip().split(",")[:2] == AUDIT_COLUMNS[:2]
        except OSError:
            return False

    def log(self, event: str, workspace: str, candidate: Optional[Dict[str, Any]] = None, batch_id: Optional[str] = None,
            detail: str = "", actor: str = "system") -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            "id": f"evt_{len(self._entries) + 1:06d}",
            "timestamp": _now(),
            "event": event,
            "workspace": workspace,
            "batch_id": batch_id or (candidate or {}).get("batch_id"),
            "candidate_id": (candidate or {}).get("id"),
            "candidate_name": (candidate or {}).get("profile", {}).get("name"),
            "email": (candidate or {}).get("profile", {}).get("email"),
            "job": (candidate or {}).get("jd", {}).get("title"),
            "actor": actor,
            "detail": detail,
        }
        if candidate:
            scores = candidate["scores"]
            dup = candidate["dedup"].get("duplicate_of") or {}
            entry.update({
                "overall": scores["overall"], "technical": scores["technical"], "experience": scores["experience"],
                "impact": scores["impact"], "education": scores["education"],
                "stage": STAGES.get(candidate["stage"], candidate["stage"]),
                "dedup_status": candidate["dedup"]["status"],
                "duplicate_of": dup.get("name"),
                "engine": candidate["engine"]["label"],
            })
        with self.lock:
            self._entries.append(entry)
            try:
                with self.csv_path.open("a", newline="", encoding="utf-8") as fh:
                    csv.writer(fh).writerow([entry.get(col, "") if entry.get(col) is not None else "" for col in AUDIT_COLUMNS])
                tmp = self.json_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(self._entries, ensure_ascii=False, indent=1), encoding="utf-8")
                tmp.replace(self.json_path)
            except OSError as exc:
                print(f"[audit] write failed: {exc}")
        return entry

    def entries(self, workspace: Optional[str] = None, candidate_id: Optional[str] = None,
                event: Optional[str] = None, limit: int = 200, offset: int = 0) -> Dict[str, Any]:
        with self.lock:
            rows = list(reversed(self._entries))
        if workspace:
            rows = [r for r in rows if r.get("workspace") == workspace]
        if candidate_id:
            rows = [r for r in rows if r.get("candidate_id") == candidate_id]
        if event:
            rows = [r for r in rows if r.get("event", "").startswith(event)]
        return {"total": len(rows), "entries": rows[offset: offset + limit]}

    def counts(self) -> int:
        with self.lock:
            return len(self._entries)


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

CANDIDATE_COLUMNS = [
    ("Rank", 7), ("Candidate", 22), ("Email", 30), ("Phone", 16), ("LinkedIn", 30), ("GitHub", 30),
    ("Location", 20), ("Current title", 30), ("Experience (yrs)", 12), ("Job", 34), ("Overall fit", 11),
    ("Technical", 11), ("Experience", 11), ("Impact", 11), ("Education & keywords", 13), ("Stage", 18),
    ("Matched skills", 44), ("Missing critical", 36), ("Dedup status", 13), ("Duplicate of", 22),
    ("Dedup layer", 18), ("File", 34), ("File SHA-256", 66), ("Engine", 22), ("Recommendation", 70),
    ("Scanned at (UTC)", 21),
]

_INK = "0F2A31"
# Same pigment tints and text as the dashboard's stage tags.
_STAGE_FILLS = {
    "Shortlisted": "E7F6EF", "Technical Review": "E9F1FE", "Hold / Borderline": "FFF1DA",
    "Rejected": "F0EDE9", "Duplicate Flagged": "F9EDF2",
}
_STAGE_FONTS = {
    "Shortlisted": "0F5642", "Technical Review": "23457B", "Hold / Borderline": "6D4F19",
    "Rejected": "56524B", "Duplicate Flagged": "6F2D4C",
}


class ExcelReport:
    def build(self, candidates: List[Dict[str, Any]], audit: List[Dict[str, Any]], meta: Dict[str, Any]) -> Path:
        if Workbook is None:
            raise RuntimeError("openpyxl is not installed.")
        wb = Workbook()
        header_font = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
        header_fill = PatternFill("solid", fgColor=_INK)
        thin = Side(style="thin", color="D9DBE1")
        border = Border(bottom=thin)

        # Summary ---------------------------------------------------------
        ws = wb.active
        ws.title = "Summary"
        ws["A1"] = "Resume Intelligence report"
        ws["A1"].font = Font(bold=True, size=16, color=_INK)
        unique = [c for c in candidates if c["stage"] != "duplicate"]
        shortlisted = [c for c in unique if c["stage"] == "shortlisted"]
        avg = round(sum(c["scores"]["overall"] for c in unique) / len(unique), 1) if unique else None
        rows = [
            ("Workspace", meta.get("workspace", "").title()),
            ("Scope", meta.get("scope", "All batches")),
            ("Generated (UTC)", _now()),
            ("Candidates in report", len(candidates)),
            ("Unique candidates", len(unique)),
            ("Duplicates flagged", len(candidates) - len(unique)),
            ("Shortlisted", len(shortlisted)),
            ("Shortlist conversion", f"{round(len(shortlisted) / len(unique) * 100, 1)}%" if unique else "-"),
            ("Average match (unique)", avg if avg is not None else "-"),
        ]
        for idx, (label, value) in enumerate(rows, start=3):
            ws.cell(row=idx, column=1, value=label).font = Font(color="68645C")
            ws.cell(row=idx, column=2, value=value).font = Font(bold=True, color=_INK)
        stage_row = len(rows) + 5
        ws.cell(row=stage_row, column=1, value="Stage").font = header_font
        ws.cell(row=stage_row, column=2, value="Candidates").font = header_font
        for col in (1, 2):
            ws.cell(row=stage_row, column=col).fill = header_fill
        counts = Counter(STAGES[c["stage"]] for c in candidates)
        for offset, label in enumerate(STAGES.values(), start=1):
            ws.cell(row=stage_row + offset, column=1, value=label)
            ws.cell(row=stage_row + offset, column=2, value=counts.get(label, 0))
        ws.column_dimensions["A"].width = 26
        ws.column_dimensions["B"].width = 30

        # Candidates --------------------------------------------------------
        wc = wb.create_sheet("Candidates")
        for col, (title, width) in enumerate(CANDIDATE_COLUMNS, start=1):
            cell = wc.cell(row=1, column=col, value=title)
            cell.font, cell.fill = header_font, header_fill
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            wc.column_dimensions[get_column_letter(col)].width = width
        wc.row_dimensions[1].height = 30
        ranked = sorted(candidates, key=lambda c: (c["stage"] == "duplicate", -c["scores"]["overall"]))
        for r, c in enumerate(ranked, start=2):
            p, s, d = c["profile"], c["scores"], c["dedup"]
            layer = next((l["label"] for l in d["layers"] if l["key"] == d.get("primary_layer")), "")
            values = [
                r - 1, p.get("name"), p.get("email"), p.get("phone"), p.get("linkedin"), p.get("github"),
                p.get("location"), p.get("current_title"), p.get("total_experience_years"), c["jd"]["title"],
                s["overall"], s["technical"], s["experience"], s["impact"], s["education"], STAGES[c["stage"]],
                ", ".join(c["skills"]["matched"]), ", ".join(c["skills"]["missing_critical"]),
                d["status"].title(), (d.get("duplicate_of") or {}).get("name"), layer, c["file"]["name"],
                c["file"]["sha256"], c["engine"]["label"], c["recommendation"]["summary"],
                c["scanned_at"][:19].replace("T", " "),
            ]
            for col, value in enumerate(values, start=1):
                cell = wc.cell(row=r, column=col, value=value)
                cell.border = border
                cell.alignment = Alignment(vertical="top", wrap_text=col in (17, 18, 25))
            stage_cell = wc.cell(row=r, column=16)
            stage_cell.fill = PatternFill("solid", fgColor=_STAGE_FILLS.get(STAGES[c["stage"]], "FFFFFF"))
            stage_cell.font = Font(bold=True, color=_STAGE_FONTS.get(STAGES[c["stage"]], _INK))
        last = max(2, len(ranked) + 1)
        wc.freeze_panes = "C2"
        wc.auto_filter.ref = f"A1:{get_column_letter(len(CANDIDATE_COLUMNS))}{last}"
        score_range = f"K2:O{last}"
        wc.conditional_formatting.add(score_range, CellIsRule(operator="greaterThanOrEqual", formula=["75"],
                                                              font=Font(bold=True, color="0F5642")))
        wc.conditional_formatting.add(score_range, CellIsRule(operator="lessThan", formula=["45"],
                                                              font=Font(color="847F78")))

        # Skill gaps ----------------------------------------------------------
        wg = wb.create_sheet("Skill Gaps")
        gaps = Counter(skill for c in unique for skill in c["skills"]["missing_critical"])
        for col, title in enumerate(("Critical requirement", "Candidates missing it", "Share of unique"), start=1):
            cell = wg.cell(row=1, column=col, value=title)
            cell.font, cell.fill = header_font, header_fill
        for r, (skill, n) in enumerate(gaps.most_common(), start=2):
            wg.cell(row=r, column=1, value=skill)
            wg.cell(row=r, column=2, value=n)
            wg.cell(row=r, column=3, value=round(n / len(unique), 3) if unique else 0).number_format = "0%"
        wg.column_dimensions["A"].width = 44
        wg.column_dimensions["B"].width = 22
        wg.column_dimensions["C"].width = 16

        # Audit log -----------------------------------------------------------
        wa = wb.create_sheet("Audit Log")
        for col, title in enumerate(AUDIT_COLUMNS, start=1):
            cell = wa.cell(row=1, column=col, value=title.replace("_", " ").title())
            cell.font, cell.fill = header_font, header_fill
            wa.column_dimensions[get_column_letter(col)].width = 18 if title not in {"detail", "job"} else 40
        for r, entry in enumerate(audit, start=2):
            for col, key in enumerate(AUDIT_COLUMNS, start=1):
                wa.cell(row=r, column=col, value=entry.get(key))
        wa.freeze_panes = "A2"

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = config.EXPORT_DIR / f"keka_ats_report_{meta.get('workspace', 'all')}_{stamp}.xlsx"
        wb.save(path)
        return path


# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------

SHEET_HEADERS = [
    "Candidate", "Email", "Phone", "Location", "Experience (yrs)", "Job", "Overall fit", "Technical",
    "Experience", "Impact", "Education & keywords", "Stage", "Missing critical", "Dedup status",
    "Duplicate of", "Engine", "Scanned at (UTC)", "Candidate ID",
]


class SheetsSync:
    WORKSHEET = "ATS Candidates"

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_sync: Optional[Dict[str, Any]] = None
        self.last_error: Optional[str] = None

    def status(self) -> Dict[str, Any]:
        creds_path = config.service_account_path()
        missing = []
        if not config.GOOGLE_SHEET_ID:
            missing.append("GOOGLE_SHEET_ID")
        if not creds_path.exists():
            missing.append(f"service account file ({config.GOOGLE_SERVICE_ACCOUNT_JSON})")
        if gspread is None:
            missing.append("gspread package")
        return {
            "configured": not missing,
            "missing": missing,
            "sheet_id": config.GOOGLE_SHEET_ID or None,
            "sheet_url": f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEET_ID}" if config.GOOGLE_SHEET_ID else None,
            "last_sync": self.last_sync,
            "last_error": self.last_error,
        }

    def sync(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        status = self.status()
        if not status["configured"]:
            raise RuntimeError("Google Sheets is not configured: missing " + ", ".join(status["missing"]))
        with self.lock:
            try:
                creds = Credentials.from_service_account_file(
                    str(config.service_account_path()),
                    scopes=["https://www.googleapis.com/auth/spreadsheets"],
                )
                client = gspread.authorize(creds)
                book = client.open_by_key(config.GOOGLE_SHEET_ID)
                try:
                    sheet = book.worksheet(self.WORKSHEET)
                except gspread.WorksheetNotFound:
                    sheet = book.add_worksheet(self.WORKSHEET, rows=max(100, len(candidates) + 10), cols=len(SHEET_HEADERS))
                rows = [SHEET_HEADERS]
                for c in sorted(candidates, key=lambda x: -x["scores"]["overall"]):
                    p, s = c["profile"], c["scores"]
                    rows.append([
                        p.get("name") or "", p.get("email") or "", p.get("phone") or "", p.get("location") or "",
                        p.get("total_experience_years") or 0, c["jd"]["title"], s["overall"], s["technical"],
                        s["experience"], s["impact"], s["education"], STAGES[c["stage"]],
                        ", ".join(c["skills"]["missing_critical"]), c["dedup"]["status"],
                        (c["dedup"].get("duplicate_of") or {}).get("name") or "", c["engine"]["label"],
                        c["scanned_at"][:19].replace("T", " "), c["id"],
                    ])
                sheet.clear()
                sheet.update(values=rows, range_name="A1")
                self.last_sync = {"at": _now(), "rows": len(rows) - 1}
                self.last_error = None
                return {**self.last_sync, "sheet_url": status["sheet_url"]}
            except Exception as exc:
                self.last_error = f"{exc.__class__.__name__}: {exc}"[:300]
                raise RuntimeError(f"Google Sheets sync failed: {self.last_error}") from exc
