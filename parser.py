"""
Resume text extraction and structured profile parsing.

Extracts text from PDF, DOCX and plain-text resumes, then pulls out the fields
recruiters screen on: contact details and profile links, current title,
employment timeline and total experience, education, skills, and the
quantified achievements that drive the project/impact score.

Deduplication lives in dedup.py; scoring lives in scorer.py.
"""
from __future__ import annotations

import datetime as dt
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree

from taxonomy import find_skills, group_by_category

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - dependency is in requirements.txt
    PdfReader = None


class ResumeParseError(Exception):
    """Raised when a file cannot be turned into usable resume text."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _extract_pdf(path: Path) -> Tuple[str, int]:
    if PdfReader is None:
        raise ResumeParseError("dependency_missing", "PDF support needs the pypdf package.")
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ResumeParseError("encrypted_pdf", "PDF is password-protected.") from exc
        pages = [page.extract_text() or "" for page in reader.pages]
    except ResumeParseError:
        raise
    except Exception as exc:
        raise ResumeParseError("corrupt_file", f"PDF could not be read ({exc.__class__.__name__}).") from exc
    return "\n".join(pages), len(pages)


def _extract_docx(path: Path) -> Tuple[str, int]:
    """Reads paragraphs and table cells from word/document.xml without extra dependencies."""
    try:
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ResumeParseError("corrupt_file", "DOCX file is damaged or not a Word document.") from exc
    root = ElementTree.fromstring(xml_bytes)
    paragraphs: List[str] = []
    for para in root.iter(f"{_W_NS}p"):
        parts = []
        for node in para.iter():
            if node.tag == f"{_W_NS}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{_W_NS}tab":
                parts.append(" | ")
            elif node.tag == f"{_W_NS}br":
                parts.append("\n")
        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs), 1


def extract_text(path: Path) -> Dict[str, Any]:
    """Returns {'text', 'pages', 'format'} or raises ResumeParseError."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        text, pages = _extract_pdf(path)
    elif ext == ".docx":
        text, pages = _extract_docx(path)
    elif ext in (".txt", ".md"):
        text, pages = path.read_text(encoding="utf-8", errors="ignore"), 1
    elif ext == ".doc":
        raise ResumeParseError("unsupported_format", "Legacy .doc files are not supported. Save as PDF or DOCX.")
    else:
        raise ResumeParseError("unsupported_format", f"Unsupported file type '{ext or 'none'}'. Use PDF, DOCX or TXT.")

    text = text.replace("\r", "\n").replace(" ", " ").replace("–", "-").replace("—", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(re.sub(r"\s", "", text)) < 80:
        raise ResumeParseError(
            "no_text",
            "No extractable text. The file is likely a scanned image; OCR is not enabled.",
        )
    return {"text": text, "pages": pages, "format": ext.lstrip(".").upper()}


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_CANDIDATE_RE = re.compile(r"(?<![\w/])\+?\d[\d\s().-]{8,16}\d(?![\w/])")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub)/[A-Za-z0-9_%-]+/?", re.I)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9_-]+/?", re.I)
URL_RE = re.compile(r"(?:https?://)?(?:www\.)?[a-z0-9-]+\.(?:dev|io|me|com|in|tech|site|page)(?:/[^\s|,]*)?", re.I)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = rf"(?:{_MONTH}\s*'?\s*)?(?:\d{{1,2}}\s*/\s*)?(?:19|20)\d{{2}}"
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE})\s*(?:-|to|until|till)\s*(?P<end>{_DATE}|present|current|now|till date|ongoing|today)",
    re.I,
)
STATED_EXP_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b(?:\s+of)?(?:\s+[\w-]+){0,3}?\s+experience",
    re.I,
)

SECTION_KEYWORDS = {
    "summary": ["summary", "profile", "objective", "about me", "professional summary"],
    "skills": ["skills", "technical skills", "core competencies", "technologies", "tech stack", "expertise"],
    "experience": ["experience", "employment", "work history", "professional experience", "career history"],
    "projects": ["projects", "key projects", "personal projects", "open source"],
    "education": ["education", "academic", "qualifications", "education & certifications"],
    "certifications": ["certifications", "certificates", "licenses", "awards", "achievements"],
}

KNOWN_CITIES = [
    "Hyderabad", "Bangalore", "Bengaluru", "Pune", "Mumbai", "Delhi", "New Delhi", "Gurgaon", "Gurugram",
    "Noida", "Chennai", "Kolkata", "Ahmedabad", "Kochi", "Jaipur", "Indore", "Coimbatore", "Visakhapatnam",
    "Warangal", "Vijayawada", "Trivandrum", "Chandigarh", "Remote", "Singapore", "Dubai", "London",
    "San Francisco", "New York", "Seattle", "Austin", "Toronto", "Berlin", "Sydney",
]

DEGREE_PATTERNS = [
    (re.compile(r"\bph\.?\s?d\b|\bdoctorate\b", re.I), "Doctorate", 5),
    (re.compile(r"\bm\.?\s?tech\b|\bmaster|\bm\.?s\.?c?\b(?=\s+in\b)|\bmba\b|\bmca\b|\bm\.e\.?(?=\s)", re.I), "Master's", 4),
    (re.compile(r"\bb\.?\s?tech\b|\bbachelor|\bb\.?s\.?c?\b(?=\s+in\b)|\bbca\b|\bb\.e\.?(?=\s)", re.I), "Bachelor's", 3),
    (re.compile(r"\bdiploma\b", re.I), "Diploma", 2),
]
RELEVANT_FIELD_RE = re.compile(
    r"computer|software|information technology|\bit\b|artificial intelligence|\bai\b|machine learning|\bml\b|"
    r"data science|electronics|electrical|engineering|mathematics|statistics",
    re.I,
)
TIER_ONE_RE = re.compile(r"\biit\b|\biiit\b|\bnit\b|\bbits\b|\biisc\b|\biim\b", re.I)

STRONG_VERBS = {
    "architected", "led", "scaled", "reduced", "improved", "optimized", "increased", "launched", "owned",
    "drove", "mentored", "established", "designed", "engineered", "built", "deployed", "migrated",
    "automated", "spearheaded", "delivered", "provisioned", "integrated", "developed", "implemented",
}
HIGH_IMPACT_VERBS = {
    "architected", "led", "scaled", "reduced", "improved", "optimized", "increased", "launched", "owned",
    "drove", "mentored", "established", "spearheaded",
}
SUPPORT_VERBS = {"assisted", "helped", "supported", "fixed", "coordinated", "maintained", "wrote", "prepared"}
METRIC_RE = re.compile(
    r"\d+(?:\.\d+)?\s*%|"
    r"[<>~]?\s*\d+(?:\.\d+)?\s*(?:ms|s)\b|"
    r"\$\s?\d[\d,]*(?:\.\d+)?\s*[kmb]?|"
    r"\b\d+(?:\.\d+)?\s*[kmb]\+?(?=\s|$|[^\w])|"
    r"\b\d{1,3}(?:,\d{3})+\+?|"
    r"\b\d+\+|"
    r"\b\d+(?:\.\d+)?x\b|"
    r"\b\d+\s*(?:users|requests|req/sec|rps|tps|clients|customers|engineers|developers|microservices|"
    r"candidates|applications|events|transactions)",
    re.I,
)
LEADERSHIP_RE = re.compile(
    r"\bmentor(?:ed|ing)?\b|\bled\s+(?:a\s+)?team\b|\bteam of \d+|\bmanaged\s+(?:a\s+)?team|\btech(?:nical)? lead\b|"
    r"\bhiring\b|\bcode review",
    re.I,
)
BULLET_RE = re.compile(r"^\s*(?:[-•*▪●‣⁃]|o\s|\d+[.)])\s*")


def _today() -> dt.date:
    return dt.date.today()


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _classify_heading(line: str) -> Optional[str]:
    stripped = re.sub(r"[:\-_=#*]+$", "", line.strip()).strip()
    if not stripped or len(stripped) > 48 or any(ch.isdigit() for ch in stripped):
        return None
    lower = stripped.lower()
    letters = [c for c in stripped if c.isalpha()]
    is_upper = letters and sum(c.isupper() for c in letters) / len(letters) > 0.8
    for section, keys in SECTION_KEYWORDS.items():
        for key in keys:
            if lower == key or (is_upper and key in lower) or lower.startswith(key + " ") and len(lower) < 32:
                return section
    return None


def _split_sections(lines: List[str]) -> Tuple[List[str], Dict[str, List[str]]]:
    header: List[str] = []
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in lines:
        section = _classify_heading(line)
        if section:
            current = section
            sections.setdefault(section, [])
            continue
        if current is None:
            header.append(line)
        else:
            sections[current].append(line)
    return header, sections


def _join_bullets(lines: List[str]) -> List[str]:
    """Re-joins bullet points that PDF extraction wrapped onto several lines."""
    joined: List[str] = []
    for line in lines:
        if BULLET_RE.match(line):
            joined.append(BULLET_RE.sub("- ", line, count=1))
        elif joined and joined[-1].startswith("- ") and not DATE_RANGE_RE.search(line) and "|" not in line:
            joined[-1] = f"{joined[-1]} {line.strip()}"
        else:
            joined.append(line)
    return joined


def _parse_date(token: str, is_end: bool) -> Optional[Tuple[int, int]]:
    token = token.strip().lower()
    if token in {"present", "current", "now", "till date", "ongoing", "today"}:
        today = _today()
        return today.year, today.month
    year_match = re.search(r"(19|20)\d{2}", token)
    if not year_match:
        return None
    year = int(year_match.group(0))
    month_match = re.match(r"([a-z]{3})", token)
    numeric_month = re.match(r"(\d{1,2})\s*/", token)
    if month_match and month_match.group(1) in MONTHS:
        month = MONTHS[month_match.group(1)]
    elif numeric_month and 1 <= int(numeric_month.group(1)) <= 12:
        month = int(numeric_month.group(1))
    else:
        month = 1  # year-only ranges count whole years: 2019 - 2022 = 36 months
    return year, month


def _months_between(start: Tuple[int, int], end: Tuple[int, int]) -> int:
    return max(0, (end[0] - start[0]) * 12 + (end[1] - start[1]))


def _parse_role_line(line: str, match: re.Match) -> Dict[str, str]:
    before = line[: match.start()].strip(" ()|,-")
    parts = [p.strip(" ()") for p in re.split(r"\s+\|\s+|\s+@\s+|\s+at\s+", before) if p.strip(" ()")]
    title = parts[0] if parts else before
    company = parts[1] if len(parts) > 1 else ""
    company = re.split(r",\s*|\s+\(", company)[0].strip()
    return {"title": title[:90], "company": company[:90]}


def _timeline(lines: List[str]) -> Tuple[List[Dict[str, Any]], float]:
    roles: List[Dict[str, Any]] = []
    intervals: List[Tuple[int, int]] = []
    for line in lines:
        match = DATE_RANGE_RE.search(line)
        if not match:
            continue
        start = _parse_date(match.group("start"), False)
        end = _parse_date(match.group("end"), True)
        if not start or not end or end < start:
            continue
        months = _months_between(start, end)
        if months <= 0 or months > 12 * 45:
            continue
        role = _parse_role_line(line, match)
        role.update({
            "start": f"{start[0]}-{start[1]:02d}",
            "end": "Present" if match.group("end").lower() in {"present", "current", "now", "till date", "ongoing", "today"}
            else f"{end[0]}-{end[1]:02d}",
            "months": months,
        })
        roles.append(role)
        intervals.append((start[0] * 12 + start[1], end[0] * 12 + end[1]))

    # Merge overlapping roles so concurrent jobs are not double counted.
    merged: List[List[int]] = []
    for start_idx, end_idx in sorted(intervals):
        if merged and start_idx <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end_idx)
        else:
            merged.append([start_idx, end_idx])
    total_months = sum(end - start for start, end in merged)
    return roles, round(total_months / 12.0, 1)


def _parse_education(lines: List[str]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for line in lines:
        for pattern, level, rank in DEGREE_PATTERNS:
            if not pattern.search(line):
                continue
            segments = [s.strip() for s in line.split("|") if s.strip()]
            degree_seg = segments[0] if segments else line
            field_match = re.search(r"\bin\s+(.+)$", degree_seg, re.I) or re.search(r"\bof\s+(.+)$", degree_seg, re.I)
            institution = ""
            for seg in segments[1:]:
                if not re.search(r"gpa|cgpa|distinction|^\(?\d{4}", seg, re.I):
                    institution = re.sub(r"\s*\(.*?\)\s*", " ", seg).strip()
                    break
            years = re.findall(r"(?:19|20)\d{2}", line)
            gpa = re.search(r"c?gpa\s*:?\s*(\d+(?:\.\d+)?)\s*(?:/\s*(\d+(?:\.\d+)?))?", line, re.I)
            entries.append({
                "degree": re.sub(r"\s+in\s+.*$", "", degree_seg, flags=re.I).strip()[:60],
                "level": level,
                "rank": rank,
                "field": (field_match.group(1).strip() if field_match else "")[:80],
                "institution": institution[:80],
                "graduation_year": int(years[-1]) if years else None,
                "gpa": f"{gpa.group(1)}/{gpa.group(2) or '10'}" if gpa else None,
                "honors": "Distinction" if re.search(r"distinction", line, re.I) else None,
                "relevant_field": bool(RELEVANT_FIELD_RE.search(line)),
                "tier_one": bool(TIER_ONE_RE.search(line)),
            })
            break
    entries.sort(key=lambda e: e["rank"], reverse=True)
    return entries


def _extract_phone(text: str) -> Optional[str]:
    for match in PHONE_CANDIDATE_RE.finditer(text):
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if not 10 <= len(digits) <= 13:
            continue
        if re.fullmatch(r"(?:19|20)\d{2}\s*-\s*(?:19|20)\d{2}", raw.strip()):
            continue
        if len(digits) == 12 and digits.startswith("91"):
            return f"+91 {digits[2:7]} {digits[7:]}"
        if len(digits) == 10:
            return f"+91 {digits[:5]} {digits[5:]}" if digits[0] in "6789" else digits
        return ("+" if raw.strip().startswith("+") else "") + digits
    return None


def _extract_name(header: List[str], filename: str) -> str:
    for line in header[:3]:
        candidate = re.sub(r"[^A-Za-z .'-]", "", line).strip()
        words = candidate.split()
        if 2 <= len(words) <= 4 and len(candidate) <= 40 and not EMAIL_RE.search(line) \
                and not any(w.lower() in {"resume", "curriculum", "vitae", "cv"} for w in words):
            return " ".join(w if w.isupper() and len(w) <= 3 else w.capitalize() for w in words)
    stem = re.sub(r"^resume[_-]?\d*[_-]?|[_-](?:duplicate|resume|cv|final)\b.*$", "", Path(filename).stem, flags=re.I)
    stem = re.sub(r"[_-]+", " ", stem).strip()
    words = [w for w in stem.split() if w.isalpha()][:3]
    return " ".join(w.capitalize() for w in words) if words else "Unnamed Candidate"


def _extract_location(header: List[str], text: str) -> Optional[str]:
    for line in header[:6]:
        if EMAIL_RE.search(line) or PHONE_CANDIDATE_RE.search(line):
            first = re.split(r"\s+\|\s+|\s+-\s+|\s+·\s+|\s+•\s+", line)[0].strip()
            if first and not EMAIL_RE.search(first) and not re.search(r"\d{4}", first) and len(first) < 48:
                return first
    for city in KNOWN_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", text[:600], re.I):
            return city
    return None


def _city_of(location: Optional[str]) -> Optional[str]:
    if not location:
        return None
    for city in KNOWN_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", location, re.I):
            return {"Bengaluru": "Bangalore", "Gurugram": "Gurgaon", "New Delhi": "Delhi"}.get(city, city)
    return location.split(",")[0].strip() or None


def _headline(header: List[str], name: str) -> Optional[str]:
    for line in header[1:6]:
        if EMAIL_RE.search(line) or PHONE_CANDIDATE_RE.search(line) or line.strip().lower() == name.lower():
            continue
        if 4 <= len(line) <= 90:
            return line.strip()
    return None


def _impact(lines: List[str]) -> Dict[str, Any]:
    bullets = [line[2:].strip() for line in lines if line.startswith("- ")]
    quantified, evidence = [], []
    verbs_used, high_impact, support = set(), 0, 0
    for bullet in bullets:
        metrics = METRIC_RE.findall(bullet)
        first_word = re.sub(r"[^a-z]", "", bullet.split(" ")[0].lower()) if bullet else ""
        if first_word in STRONG_VERBS:
            verbs_used.add(first_word)
        if first_word in HIGH_IMPACT_VERBS:
            high_impact += 1
        if first_word in SUPPORT_VERBS:
            support += 1
        if metrics:
            quantified.append(bullet)
            weight = len(metrics) + (1 if first_word in HIGH_IMPACT_VERBS else 0)
            evidence.append((weight, bullet))
    evidence.sort(key=lambda item: item[0], reverse=True)
    leadership = sorted({m.group(0).lower() for line in lines for m in LEADERSHIP_RE.finditer(line)})
    return {
        "bullet_count": len(bullets),
        "quantified_count": len(quantified),
        "strong_verbs": sorted(verbs_used),
        "high_impact_count": high_impact,
        "support_count": support,
        "leadership_signals": leadership,
        "evidence": [b for _w, b in evidence[:3]],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_resume(text: str, filename: str = "") -> Dict[str, Any]:
    """Turns raw resume text into a structured candidate profile."""
    raw_lines = [line.strip() for line in text.split("\n") if line.strip()]
    header, sections = _split_sections(raw_lines)
    experience_lines = _join_bullets(sections.get("experience", []) + sections.get("projects", []))
    if not sections.get("experience"):
        # Unstructured resume: scan everything except education for the timeline.
        experience_lines = _join_bullets([l for l in raw_lines if l not in sections.get("education", [])])

    name = _extract_name(header or raw_lines[:3], filename)
    email_match = EMAIL_RE.search(text)
    linkedin = LINKEDIN_RE.search(text)
    github = GITHUB_RE.search(text)
    portfolio = None
    for match in URL_RE.finditer(text):
        url = match.group(0)
        if not re.search(r"linkedin|github|gmail|yahoo|outlook|hotmail", url, re.I) and "@" not in text[max(0, match.start() - 1):match.start()]:
            portfolio = url
            break

    roles, timeline_years = _timeline(experience_lines)
    stated = STATED_EXP_RE.search(" ".join(sections.get("summary", [])) or text)
    stated_years = float(stated.group(1)) if stated else None
    if stated_years is not None and stated_years <= 45:
        total_years, exp_source = stated_years, "stated"
    elif timeline_years > 0:
        total_years, exp_source = timeline_years, "timeline"
    else:
        total_years, exp_source = 0.0, "not found"

    location = _extract_location(header, text)
    skills = find_skills(text)
    skills_section_text = " ".join(sections.get("skills", []))
    listed = set(find_skills(skills_section_text)) if skills_section_text else set()
    demonstrated = set(find_skills(" ".join(experience_lines)))
    education = _parse_education(sections.get("education", []) or raw_lines)
    headline = _headline(header, name)
    current = roles[0] if roles else {}

    def _url(value: Optional[re.Match]) -> Optional[str]:
        if not value:
            return None
        url = value.group(0).rstrip("/")
        return url if url.startswith("http") else f"https://{url}"

    return {
        "name": name,
        "email": email_match.group(0).lower() if email_match else None,
        "phone": _extract_phone(text),
        "linkedin": _url(linkedin),
        "github": _url(github),
        "portfolio": (portfolio if portfolio and portfolio.startswith("http") else f"https://{portfolio}") if portfolio else None,
        "location": location,
        "city": _city_of(location),
        "headline": headline,
        "current_title": current.get("title") or headline,
        "current_company": current.get("company") or None,
        "total_experience_years": total_years,
        "experience_source": exp_source,
        "timeline_years": timeline_years,
        "timeline": roles[:8],
        "education": education[:3],
        "highest_education": education[0] if education else None,
        "skills": skills,
        "skills_by_category": group_by_category(skills),
        "demonstrated_skills": sorted(demonstrated),
        "listed_only_skills": sorted(listed - demonstrated),
        "impact": _impact(experience_lines),
        "sections_found": sorted(sections.keys()),
        "word_count": len(re.findall(r"\w+", text)),
    }


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()
