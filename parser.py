import re
import hashlib
import json
import os
from typing import Dict, Any, List, Optional, Tuple
from difflib import SequenceMatcher

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


class ResumeParser:
    """
    Advanced Resume Text Extractor & Structured Entity Parser for Keka ATS.
    Extracts text from multi-format documents (PDF, DOCX, TXT) and parses
    structured contact information, skills, experience metrics, and deduplication signatures.
    """

    SKILL_DICTIONARY = {
        "Python Ecosystem": ["python", "fastapi", "django", "flask", "celery", "asyncio", "pytest", "sqlalchemy", "pydantic"],
        "Databases & Caching": ["postgresql", "mysql", "mongodb", "redis", "elasticsearch", "sqlite", "oracle", "sql"],
        "DevOps & Cloud": ["docker", "kubernetes", "aws", "ec2", "s3", "rds", "eks", "terraform", "ansible", "jenkins", "git", "ci/cd"],
        "AI & NLP": ["llm", "llama", "groq", "openai", "langchain", "llamaindex", "rag", "pytorch", "nlp", "vector database", "pgvector"],
        "Frontend & Fullstack": ["react", "typescript", "javascript", "next.js", "tailwind", "redux", "html", "css"],
        "HR Tech & Domain": ["ats", "payroll", "attendance", "hrms", "keka", "recruitment", "talent acquisition"]
    }

    def __init__(self, registry_file: str = "./dedup_registry.json"):
        self.registry_file = registry_file
        self.registry = self._load_registry()

    def _load_registry(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.registry_file):
            try:
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_registry(self):
        try:
            with open(self.registry_file, "w", encoding="utf-8") as f:
                json.dump(self.registry, f, indent=2)
        except Exception as e:
            print(f"[Warning] Failed to save deduplication registry: {e}")

    def extract_text(self, file_path: str) -> str:
        """Extracts raw text from PDF, TXT, or supported resume formats."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Resume file not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            if PdfReader is None:
                raise ImportError("pypdf library not installed.")
            try:
                reader = PdfReader(file_path)
                text = ""
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"
                return text.strip()
            except Exception as e:
                raise RuntimeError(f"Error reading PDF {file_path}: {e}")
        elif ext in [".txt", ".md", ".csv"]:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read().strip()
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    def parse_metadata(self, text: str, filename: str = "") -> Dict[str, Any]:
        """Parses candidate metadata, skills, and contact info from raw resume text."""
        normalized_text = text.replace("\r", "\n")
        lines = [l.strip() for l in normalized_text.split("\n") if l.strip()]

        # Extract Email
        email_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text)
        email = email_match.group(0).lower() if email_match else "N/A"

        # Extract Phone
        phone_match = re.search(r'(\+?\d{1,3}[\s-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}', text)
        phone = re.sub(r'[^\d+]', '', phone_match.group(0)) if phone_match else "N/A"

        # Extract Candidate Name (First non-empty title line that doesn't look like contact/header)
        name = "Unknown Candidate"
        if lines:
            first_line = lines[0]
            if len(first_line) < 40 and not any(w in first_line.lower() for w in ["resume", "curriculum", "cv", "@", "www."]):
                name = re.sub(r'[^a-zA-Z\s.-]', '', first_line).strip()
            elif len(lines) > 1 and len(lines[1]) < 40:
                name = re.sub(r'[^a-zA-Z\s.-]', '', lines[1]).strip()
        if name == "Unknown Candidate" and filename:
            clean_fn = re.sub(r'^resume_\d+_|_duplicate|\.pdf|\.txt', '', filename, flags=re.I)
            clean_fn = clean_fn.replace("_", " ").title()
            if clean_fn.strip():
                name = clean_fn.strip()

        # Extract Location / Hyderabad Check
        location = "India / Remote"
        loc_keywords = ["Hyderabad", "Bangalore", "Bengaluru", "Pune", "Mumbai", "Delhi", "Gurgaon", "Noida", "Chennai"]
        for loc in loc_keywords:
            if re.search(rf'\b{loc}\b', text, re.IGNORECASE):
                location = f"{loc}, India"
                break

        # Extract Total Experience (Heuristic regex search)
        exp_years = 0.0
        exp_match = re.search(r'(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)\s*(?:of\s*)?(?:experience|exp)', text, re.IGNORECASE)
        if exp_match:
            exp_years = float(exp_match.group(1))
        else:
            # Estimate from year mentions like 2018 - Present or 2019 to 2022
            year_matches = re.findall(r'\b(201\d|202\d)\b', text)
            if len(year_matches) >= 2:
                years = [int(y) for y in year_matches]
                span = max(years) - min(years)
                if 0 < span <= 20:
                    exp_years = float(span)

        # Extract Skills by category
        found_skills = []
        skill_categories = {}
        text_lower = text.lower()
        for cat, skills in self.SKILL_DICTIONARY.items():
            matched = [s.title() for s in skills if re.search(rf'\b{re.escape(s)}\b', text_lower)]
            if matched:
                skill_categories[cat] = matched
                found_skills.extend(matched)

        # Extract Education
        education_summary = "Degree/University Not Specified"
        for line in lines:
            if any(deg in line.lower() for deg in ["b.tech", "b.e.", "m.tech", "bachelor", "master", "gpa", "iit", "nit", "iiit"]):
                if len(line) < 120:
                    education_summary = line
                    break

        return {
            "name": name,
            "email": email,
            "phone": phone,
            "location": location,
            "is_hyderabad_based": "hyderabad" in location.lower(),
            "total_years_experience": exp_years,
            "skills_list": sorted(list(set(found_skills))),
            "skills_by_category": skill_categories,
            "education": education_summary
        }

    def compute_signatures(self, text: str, metadata: Dict[str, Any]) -> Dict[str, str]:
        """Computes cryptographic and semantic fingerprints for candidate deduplication."""
        # Exact raw hash of clean lowercase text
        clean_text = re.sub(r'\s+', ' ', text).strip().lower()
        exact_hash = hashlib.sha256(clean_text.encode('utf-8')).hexdigest()

        # Semantic profile fingerprint (normalized email + phone + clean name)
        email_clean = metadata.get("email", "").lower().strip()
        phone_clean = re.sub(r'\D', '', metadata.get("phone", ""))
        name_clean = re.sub(r'[^a-z0-9]', '', metadata.get("name", "").lower())
        
        # If valid email exists (not N/A), use email as primary semantic key
        if email_clean and email_clean != "n/a":
            semantic_key = f"email:{email_clean}"
        elif len(phone_clean) >= 8:
            semantic_key = f"phone:{phone_clean[-10:]}_{name_clean[:6]}"
        else:
            semantic_key = f"name_exp:{name_clean}_{metadata.get('total_years_experience', 0)}"

        semantic_fingerprint = hashlib.md5(semantic_key.encode('utf-8')).hexdigest()

        return {
            "exact_sha256": exact_hash,
            "semantic_key": semantic_key,
            "semantic_fingerprint": semantic_fingerprint
        }

    def check_duplicate(self, text: str, metadata: Dict[str, Any], filename: str) -> Dict[str, Any]:
        """
        Checks if the candidate is a duplicate against the Keka Resume Registry.
        Checks:
        1. Exact SHA-256 Text Match (exact duplicate upload)
        2. Semantic Profile Match (Same Email or Phone Number across different formats)
        3. Fuzzy Text Similarity (> 88% sequence match)
        """
        signatures = self.compute_signatures(text, metadata)
        clean_text = re.sub(r'\s+', ' ', text).strip().lower()

        for record in self.registry:
            # Skip comparing identical filename to itself if re-run
            if record.get("filename") == filename:
                continue

            # Check 1: Exact Hash
            if record.get("exact_sha256") == signatures["exact_sha256"]:
                return {
                    "is_duplicate": True,
                    "duplicate_type": "Exact File Hash Match",
                    "duplicate_of_id": record.get("record_id"),
                    "duplicate_of_filename": record.get("filename"),
                    "duplicate_of_name": record.get("name"),
                    "similarity_score": 100.0,
                    "message": f"Exact identical resume previously uploaded as '{record.get('filename')}' ({record.get('name')})."
                }

            # Check 2: Semantic Profile Match (Email / Phone)
            rec_email = record.get("email", "").lower().strip()
            cand_email = metadata.get("email", "").lower().strip()
            rec_phone = re.sub(r'\D', '', record.get("phone", ""))[-10:]
            cand_phone = re.sub(r'\D', '', metadata.get("phone", ""))[-10:]

            if (cand_email != "n/a" and rec_email == cand_email) or (len(cand_phone) >= 8 and rec_phone == cand_phone):
                # Calculate text similarity just to see formatting drift
                rec_text = record.get("raw_clean_text", "")
                sim = SequenceMatcher(None, clean_text, rec_text).ratio() * 100.0 if rec_text else 85.0
                return {
                    "is_duplicate": True,
                    "duplicate_type": "Semantic Profile Match (Identical Email/Phone)",
                    "duplicate_of_id": record.get("record_id"),
                    "duplicate_of_filename": record.get("filename"),
                    "duplicate_of_name": record.get("name"),
                    "similarity_score": round(sim, 1),
                    "message": f"Candidate profile already exists in ATS via '{record.get('filename')}'. Email/Phone match."
                }

            # Check 3: Fuzzy Content Similarity
            rec_text = record.get("raw_clean_text", "")
            if rec_text:
                sim = SequenceMatcher(None, clean_text, rec_text).ratio() * 100.0
                if sim >= 88.0:
                    return {
                        "is_duplicate": True,
                        "duplicate_type": "High Fuzzy Content Similarity",
                        "duplicate_of_id": record.get("record_id"),
                        "duplicate_of_filename": record.get("filename"),
                        "duplicate_of_name": record.get("name"),
                        "similarity_score": round(sim, 1),
                        "message": f"Resume content is {round(sim, 1)}% identical to existing candidate '{record.get('name')}' ({record.get('filename')})."
                    }

        return {
            "is_duplicate": False,
            "duplicate_type": "None",
            "duplicate_of_id": None,
            "duplicate_of_filename": None,
            "duplicate_of_name": None,
            "similarity_score": 0.0,
            "message": "Unique candidate profile validated."
        }

    def register_candidate(self, record_id: str, filename: str, text: str, metadata: Dict[str, Any], signatures: Dict[str, str]):
        """Registers a newly parsed candidate into the deduplication registry."""
        clean_text = re.sub(r'\s+', ' ', text).strip().lower()
        # Remove any existing record with same filename to avoid clutter
        self.registry = [r for r in self.registry if r.get("filename") != filename]
        
        new_record = {
            "record_id": record_id,
            "filename": filename,
            "name": metadata.get("name"),
            "email": metadata.get("email"),
            "phone": metadata.get("phone"),
            "exact_sha256": signatures["exact_sha256"],
            "semantic_fingerprint": signatures["semantic_fingerprint"],
            "raw_clean_text": clean_text[:3000] # store top 3000 chars for fast fuzzy comparison
        }
        self.registry.append(new_record)
        self._save_registry()

    def parse_and_check(self, file_path: str, record_id: str = "") -> Tuple[Dict[str, Any], Dict[str, Any], str]:
        """Complete workflow: Extracts text, parses metadata, runs deduplication check, and registers record."""
        filename = os.path.basename(file_path)
        if not record_id:
            record_id = hashlib.md5(filename.encode()).hexdigest()[:10]

        text = self.extract_text(file_path)
        metadata = self.parse_metadata(text, filename)
        signatures = self.compute_signatures(text, metadata)
        dedup_info = self.check_duplicate(text, metadata, filename)

        # Register candidate in registry
        self.register_candidate(record_id, filename, text, metadata, signatures)

        return metadata, dedup_info, text
