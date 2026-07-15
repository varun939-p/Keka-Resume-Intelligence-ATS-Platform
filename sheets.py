import os
import json
import csv
import datetime
from typing import Dict, Any, List, Optional

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None

try:
    import pandas as pd
except ImportError:
    pd = None


class KekaSheetsLogger:
    """
    Google Sheets Logger for Keka Resume Intelligence ATS.
    Logs candidate scores, deduplication status, and skill gap recommendations directly
    to Google Sheets, or falls back to local CSV/JSON persistence when API credentials are not set.
    """

    DEFAULT_CSV_PATH = "/tmp/keka_sheets_audit_log.csv"
    DEFAULT_JSON_PATH = "/tmp/keka_sheets_audit_log.json"

    def __init__(self, sheet_id: Optional[str] = None, credentials_path: Optional[str] = None):
        self.sheet_id = sheet_id or os.getenv("GOOGLE_SHEET_ID", "").strip()
        self.credentials_path = credentials_path or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json").strip()
        self.client = None
        self.worksheet = None

        if gspread and Credentials and self.sheet_id and not self.sheet_id.startswith("your_"):
            if os.path.exists(self.credentials_path):
                try:
                    scopes = [
                        "https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive"
                    ]
                    creds = Credentials.from_service_account_file(self.credentials_path, scopes=scopes)
                    self.client = gspread.authorize(creds)
                    sheet = self.client.open_by_key(self.sheet_id)
                    self.worksheet = sheet.sheet1
                except Exception as e:
                    print(f"[Sheets Init Warning] Could not connect to Google Sheet ({e}). Using Local CSV/JSON Backup.")
            else:
                print(f"[Sheets Init Warning] Credential file '{self.credentials_path}' not found. Using Local CSV/JSON Backup.")

        # Initialize local storage headers if not present
        self._ensure_local_storage()

    def _ensure_local_storage(self):
        """Creates local CSV and JSON log files if they don't exist yet."""
        if not os.path.exists(self.DEFAULT_CSV_PATH):
            headers = [
                "Timestamp", "Candidate Name", "Email", "Phone", "Location",
                "Total Exp (Yrs)", "Job Description", "Fit Score (/100)", "Recommendation",
                "Is Duplicate", "Duplicate Type", "Duplicate Of", "Technical Score (/35)",
                "Experience Score (/30)", "Education Score (/15)", "Keka Cultural Score (/20)",
                "Key Strengths", "Missing Gaps", "Scoring Engine"
            ]
            try:
                with open(self.DEFAULT_CSV_PATH, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
            except Exception as e:
                print(f"[Storage Warning] Could not create CSV log: {e}")

        if not os.path.exists(self.DEFAULT_JSON_PATH):
            try:
                with open(self.DEFAULT_JSON_PATH, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=2)
            except Exception as e:
                print(f"[Storage Warning] Could not create JSON log: {e}")

    def log_resume_evaluation(
        self,
        candidate_metadata: Dict[str, Any],
        score_data: Dict[str, Any],
        dedup_data: Dict[str, Any],
        jd_name: str = "Backend Engineer"
    ) -> Dict[str, Any]:
        """
        Logs a single candidate evaluation row to Google Sheets or Local Backup.
        Returns logging status and row summary.
        """
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cat_scores = score_data.get("category_scores", {})

        row_data = [
            timestamp,
            candidate_metadata.get("name", "Unknown"),
            candidate_metadata.get("email", "N/A"),
            candidate_metadata.get("phone", "N/A"),
            candidate_metadata.get("location", "N/A"),
            str(candidate_metadata.get("total_years_experience", 0.0)),
            jd_name,
            str(score_data.get("overall_fit_score", 0)),
            score_data.get("recommendation", "Hold"),
            "Yes" if dedup_data.get("is_duplicate", False) else "No",
            dedup_data.get("duplicate_type", "None"),
            dedup_data.get("duplicate_of_filename", "N/A") if dedup_data.get("is_duplicate") else "None",
            str(cat_scores.get("technical_skills_score", 0)),
            str(cat_scores.get("relevant_experience_score", 0)),
            str(cat_scores.get("education_and_certifications_score", 0)),
            str(cat_scores.get("keka_domain_and_cultural_fit_score", 0)),
            " | ".join(score_data.get("key_strengths", [])),
            " | ".join(score_data.get("missing_skills_and_gaps", [])),
            score_data.get("scoring_engine", "Local Heuristic")
        ]

        # 1. Try appending to Google Sheets
        sheets_success = False
        if self.worksheet:
            try:
                self.worksheet.append_row(row_data)
                sheets_success = True
            except Exception as e:
                print(f"[Sheets Log Error] Failed to append row to live Google Sheet: {e}")

        # 2. Always persist to local CSV audit log
        try:
            with open(self.DEFAULT_CSV_PATH, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(row_data)
        except Exception as e:
            print(f"[Local CSV Log Error] Failed to write CSV: {e}")

        # 3. Persist to local JSON log
        try:
            records = []
            if os.path.exists(self.DEFAULT_JSON_PATH):
                with open(self.DEFAULT_JSON_PATH, "r", encoding="utf-8") as f:
                    records = json.load(f)
            
            record_dict = {
                "timestamp": timestamp,
                "candidate_name": candidate_metadata.get("name", "Unknown"),
                "email": candidate_metadata.get("email", "N/A"),
                "phone": candidate_metadata.get("phone", "N/A"),
                "location": candidate_metadata.get("location", "N/A"),
                "total_years_experience": candidate_metadata.get("total_years_experience", 0.0),
                "jd_name": jd_name,
                "overall_fit_score": score_data.get("overall_fit_score", 0),
                "recommendation": score_data.get("recommendation", "Hold"),
                "is_duplicate": dedup_data.get("is_duplicate", False),
                "duplicate_type": dedup_data.get("duplicate_type", "None"),
                "duplicate_of_filename": dedup_data.get("duplicate_of_filename", None),
                "category_scores": cat_scores,
                "key_strengths": score_data.get("key_strengths", []),
                "missing_skills_and_gaps": score_data.get("missing_skills_and_gaps", []),
                "scoring_engine": score_data.get("scoring_engine", "Local Heuristic")
            }
            records.append(record_dict)
            with open(self.DEFAULT_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
        except Exception as e:
            print(f"[Local JSON Log Error] Failed to write JSON: {e}")

        return {
            "logged_to_google_sheets": sheets_success,
            "logged_to_local_csv": True,
            "timestamp": timestamp,
            "candidate_name": candidate_metadata.get("name")
        }

    def batch_log_evaluations(self, evaluation_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Logs multiple candidate evaluations in bulk."""
        results = []
        for item in evaluation_records:
            res = self.log_resume_evaluation(
                item.get("candidate_metadata", {}),
                item.get("score_data", {}),
                item.get("dedup_data", {}),
                item.get("jd_name", "Backend Engineer")
            )
            results.append(res)
        return {
            "total_processed": len(results),
            "logged_to_google_sheets_count": sum(1 for r in results if r["logged_to_google_sheets"]),
            "logged_to_local_csv_count": sum(1 for r in results if r["logged_to_local_csv"])
        }

    def get_sheet_records(self) -> List[Dict[str, Any]]:
        """Retrieves all logged evaluations from local JSON/CSV or Google Sheet."""
        if os.path.exists(self.DEFAULT_JSON_PATH):
            try:
                with open(self.DEFAULT_JSON_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def export_to_excel(self, output_path: str = "./keka_ats_scoring_report.xlsx") -> str:
        """Exports the entire ATS evaluation log to a beautifully formatted Excel (.xlsx) file."""
        if not pd:
            raise ImportError("pandas library required for Excel export.")

        records = self.get_sheet_records()
        if not records:
            # If no JSON records yet, check if CSV exists and read it
            if os.path.exists(self.DEFAULT_CSV_PATH):
                df = pd.read_csv(self.DEFAULT_CSV_PATH)
                df.to_excel(output_path, index=False)
                return output_path
            else:
                raise ValueError("No records available to export.")

        # Flatten dict for clean Excel display
        flat_list = []
        for r in records:
            cat = r.get("category_scores", {})
            flat_list.append({
                "Timestamp": r.get("timestamp"),
                "Candidate Name": r.get("candidate_name"),
                "Email": r.get("email"),
                "Phone": r.get("phone"),
                "Location": r.get("location"),
                "Experience (Yrs)": r.get("total_years_experience"),
                "Job Description": r.get("jd_name"),
                "Overall Fit Score (/100)": r.get("overall_fit_score"),
                "Recommendation": r.get("recommendation"),
                "Is Duplicate": "YES" if r.get("is_duplicate") else "NO",
                "Duplicate Type": r.get("duplicate_type"),
                "Duplicate Of": r.get("duplicate_of_filename", ""),
                "Tech Score (/35)": cat.get("technical_skills_score"),
                "Experience Score (/30)": cat.get("relevant_experience_score"),
                "Education Score (/15)": cat.get("education_and_certifications_score"),
                "Keka Culture Fit (/20)": cat.get("keka_domain_and_cultural_fit_score"),
                "Key Strengths": " | ".join(r.get("key_strengths", [])),
                "Missing Gaps": " | ".join(r.get("missing_skills_and_gaps", [])),
                "Scoring Engine": r.get("scoring_engine")
            })

        df = pd.DataFrame(flat_list)
        df.to_excel(output_path, index=False)
        return output_path

    def export_bulk_excel(
        self,
        bulk_candidates: List[Dict[str, Any]],
        output_path: str = "./keka_1000_resumes_bulk_report.xlsx"
    ) -> str:
        """Exports the complete 1,000-candidate Bulk Screening dataset to a formatted Excel workbook (.xlsx)."""
        if not pd:
            raise ImportError("pandas library required for Excel export.")

        flat_list = []
        for r in bulk_candidates:
            cat = r.get("category_scores", {})
            flat_list.append({
                "Rank": r.get("rank"),
                "Candidate ID": r.get("candidate_id"),
                "Candidate Name": r.get("name"),
                "Email": r.get("email"),
                "Phone": r.get("phone"),
                "Location": r.get("location"),
                "Hyderabad Based?": "YES ✅" if r.get("is_hyderabad_based") else "NO",
                "Total Exp (Yrs)": r.get("total_years_experience"),
                "Primary Stack / Role": r.get("role_title"),
                "Overall Fit Score (/100)": r.get("overall_fit_score"),
                "Recommendation": r.get("recommendation"),
                "Is Duplicate?": "YES 🔴" if r.get("is_duplicate") else "NO 🟢",
                "Duplicate Type": r.get("duplicate_type"),
                "Duplicate Of ID": r.get("duplicate_of", ""),
                "Tech Score (/35)": cat.get("technical_skills_score"),
                "Experience Score (/30)": cat.get("relevant_experience_score"),
                "Education Score (/15)": cat.get("education_and_certifications_score"),
                "Keka Culture Fit (/20)": cat.get("keka_domain_and_cultural_fit_score"),
                "Key Strengths": " | ".join(r.get("key_strengths", [])),
                "Missing Gaps": " | ".join(r.get("missing_skills_and_gaps", []))
            })

        df = pd.DataFrame(flat_list)
        df.to_excel(output_path, index=False)
        return output_path
