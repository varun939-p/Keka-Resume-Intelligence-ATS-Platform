"""
Job-description profiling, multi-dimensional candidate scoring and stage routing.

Deterministic by default: the same resume and JD always produce the same scores,
so recruiters can audit every number. When a Groq or OpenAI key is configured
and selected, the LLM contributes half of each dimension score and writes the
narrative; skill matching, gaps and routing stay deterministic either way, and
any LLM failure falls back to the deterministic result for that candidate.

Dimensions (0-100 each, weighted into Overall Role Fit):
  technical    Required-skill coverage by tier (critical / core / bonus)
  experience   Years against the JD band, scaled by how much of that time used the critical stack
  impact       Quantified outcomes, ownership verbs, leadership and scope signals
  education    Degree level and field, blended with JD keyword alignment
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

import config
from dedup import cosine, term_vector
from taxonomy import SKILL_CATEGORY, canonicalize, compiled_skills, find_skills, strip_links

try:
    from groq import Groq
except ImportError:  # pragma: no cover
    Groq = None
try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None


DEFAULT_WEIGHTS = {"technical": 40, "experience": 25, "impact": 20, "education": 15}
DEFAULT_THRESHOLDS = {"shortlist": 75, "review": 60, "hold": 45}
TIER_WEIGHTS = {"critical": 0.70, "core": 0.20, "bonus": 0.10}
KNOCKOUT_COVERAGE = 0.35

STAGES = {
    "shortlisted": "Shortlisted",
    "technical_review": "Technical Review",
    "hold": "Hold / Borderline",
    "rejected": "Rejected",
    "duplicate": "Duplicate Flagged",
}
STAGE_HEADLINES = {
    "shortlisted": "Advance to interview",
    "technical_review": "Route to technical screen",
    "hold": "Hold for pipeline review",
    "rejected": "Decline for this role",
    "duplicate": "Merge with existing record",
}

# Concept skills are satisfied by any of their concrete tools.
IMPLIED_SKILLS = {
    "Task Queues": {"Celery", "RQ", "RabbitMQ", "Kafka"},
    "Vector Databases": {"Pinecone", "Weaviate", "Qdrant", "pgvector"},
    "Caching": {"Redis"},
    "REST APIs": {"FastAPI", "Django REST Framework", "Flask", "Express", "Spring Boot"},
    "Data Pipelines": {"Airflow", "ETL", "Spark"},
    "Unit Testing": {"PyTest", "Jest", "JUnit"},
    "CI/CD": {"Jenkins", "GitHub Actions", "ArgoCD"},
    "Distributed Systems": {"Kafka", "Microservices"},
    "LLMs": {"OpenAI API", "Groq", "LLaMA", "LangChain", "LlamaIndex", "RAG"},
    "Machine Learning": {"PyTorch", "TensorFlow", "Scikit-learn", "Deep Learning"},
    "SQL": {"PostgreSQL", "MySQL", "SQLite", "Oracle"},
}


# ---------------------------------------------------------------------------
# JD profiling
# ---------------------------------------------------------------------------

_HEADING_TIERS = [
    ("bonus", re.compile(r"nice|bonus|preferred|good to have|\bplus\b|desirable|optional", re.I)),
    ("ignore", re.compile(r"about (?!the role)|why join|benefit|perks|culture|equal opportunit|compensation|how to apply", re.I)),
    ("critical", re.compile(r"required|requirement|must|qualification|what you('ll| will)? need|looking for|skills|eligibility", re.I)),
    ("core", re.compile(r"responsibilit|role|what you('ll| will)? do|duties|overview|key|day to day|mission", re.I)),
]
_INLINE_LABEL = re.compile(
    r"\b(nice to have|good to have|bonus(?: skills)?|preferred|plus|must[- ]haves?|requirements?|required(?: skills)?)\s*:\s*",
    re.I,
)
_SOFT_LANGUAGE = re.compile(r"familiarity|interest in|exposure to|nice to have|bonus|a plus|preferred|ideally", re.I)
_FIELD_RE = re.compile(r"^\s*(position|title|role|location|experience|department|team|employment type)\s*:\s*(.+)$", re.I)


def _heading_tier(line: str) -> Optional[str]:
    text = line.strip().rstrip(":").strip()
    if not text or len(text) > 70 or _FIELD_RE.match(line):
        return None
    letters = [c for c in text if c.isalpha()]
    uppercase = letters and sum(c.isupper() for c in letters) / len(letters) > 0.8
    ends_colon = line.strip().endswith(":") and len(text) < 60
    if not (uppercase or ends_colon) or set(text) <= set("=-_*# "):
        return None
    for tier, pattern in _HEADING_TIERS:
        if pattern.search(text):
            return tier
    return "core"


_ALTERNATIVE_JOIN = re.compile(r"[\s()]*(?:/|\bor\b)[\s()]*", re.I)


def _segment_groups(segment: str) -> List[List[str]]:
    """Groups skills joined directly by '/' or 'or' ("Redux/Zustand"); everything else stands alone."""
    text = strip_links(segment).lower()
    spans = sorted((m.start(), m.end(), name) for name, _cat, pattern in compiled_skills() for m in pattern.finditer(text))
    groups: List[List[str]] = []
    prev_end: Optional[int] = None
    for start, end, name in spans:
        joined = prev_end is not None and start >= prev_end and _ALTERNATIVE_JOIN.fullmatch(text[prev_end:start])
        if groups and joined:
            if name not in groups[-1]:
                groups[-1].append(name)
        elif [name] not in groups:
            groups.append([name])
        prev_end = end if prev_end is None else max(prev_end, end)
    return groups


def _clause_groups(clause: str) -> List[List[str]]:
    """Splits one requirement clause into requirement groups (a group is satisfied by any member).

    "Celery, RQ, or Kafka" is one any-of group; "Python, FastAPI or Django, and PostgreSQL"
    yields Python, (FastAPI | Django), PostgreSQL.
    """
    groups: List[List[str]] = []
    prefix, _, body = clause.rpartition(":") if ":" in clause else ("", "", clause)
    groups.extend(_segment_groups(prefix))
    pending: List[List[str]] = []
    for seg in (s for s in re.split(r",\s*|\s+and\s+", body) if s.strip()):
        seg_groups = _segment_groups(seg)
        if re.match(r"^\s*or\s+", seg, re.I):
            merged = [s for grp in pending + seg_groups for s in grp]
            pending = [list(dict.fromkeys(merged))] if merged else pending
        else:
            pending.extend(seg_groups)
    groups.extend(pending)
    return groups


def _requirement_label(group: List[str]) -> str:
    return " / ".join(group)


def profile_jd(text: str, title: Optional[str] = None) -> Dict[str, Any]:
    """Builds the structured requirement profile used for scoring."""
    lines = [l.rstrip() for l in text.replace("\r", "").split("\n")]
    fields: Dict[str, str] = {}
    tiers: Dict[str, List[List[str]]] = {"critical": [], "core": [], "bonus": []}
    current: Optional[str] = None
    saw_heading = False

    for raw in lines:
        line = raw.strip()
        if not line or set(line) <= set("=-_*# "):
            continue
        field = _FIELD_RE.match(line)
        if field:
            fields.setdefault(field.group(1).lower(), field.group(2).strip())
            continue
        tier = _heading_tier(line)
        if tier:
            current, saw_heading = tier, True
            continue
        # Inline labels ("Must have: X. Nice to have: Y") switch tier mid-line.
        pieces: List[Tuple[Optional[str], str]] = []
        cursor, forced = 0, None
        for match in _INLINE_LABEL.finditer(line):
            pieces.append((forced, line[cursor:match.start()]))
            forced = "bonus" if re.match(r"nice|bonus|prefer|good|plus", match.group(1), re.I) else "critical"
            cursor = match.end()
        pieces.append((forced, line[cursor:]))
        for forced_tier, piece in pieces:
            for clause in re.split(r"[;.](?:\s|$)", piece):
                if not clause.strip():
                    continue
                if forced_tier:
                    target = forced_tier
                else:
                    target = current if saw_heading else "critical"
                    if target in (None, "ignore"):
                        continue
                    if _SOFT_LANGUAGE.search(clause):
                        target = "core" if target == "critical" else target
                for group in _clause_groups(clause):
                    if target == "core" and all(SKILL_CATEGORY.get(s) == "HR Domain" for s in group):
                        tiers["bonus"].append(group)
                    else:
                        tiers[target].append(group)

    if not saw_heading and not any(tiers.values()):
        tiers["critical"] = [[s] for s in find_skills(text)]

    requirements = _dedupe_requirements(tiers)
    exp_min, exp_max = _experience_band(fields.get("experience", "") + " " + text)
    resolved_title = (title or fields.get("position") or fields.get("title") or fields.get("role") or "").strip()
    if not resolved_title:
        resolved_title = next((l.strip() for l in lines if l.strip() and not set(l.strip()) <= set("=-_*# ")
                               and "job description" not in l.lower()), "Untitled role")[:90]
    location = fields.get("location", "")
    return {
        "title": resolved_title,
        "location": location or None,
        "city": _city(location),
        "work_mode": "Remote" if re.search(r"\bremote\b", location, re.I) else ("Hybrid" if re.search(r"hybrid", location, re.I) else ("On-site" if location else None)),
        "department": fields.get("department"),
        "experience_min": exp_min,
        "experience_max": exp_max,
        "seniority": _seniority(resolved_title),
        "requirements": requirements,
        "keyword_vector": term_vector(text),
    }


def _dedupe_requirements(tiers: Dict[str, List[List[str]]]) -> Dict[str, List[str]]:
    seen_singles: set = set()
    seen_labels: set = set()
    result: Dict[str, List[str]] = {}
    for tier in ("critical", "core", "bonus"):
        singles = {g[0] for g in tiers[tier] if len(g) == 1}
        labels: List[str] = []
        for group in tiers[tier]:
            members = [s for s in group if s not in seen_singles] if len(group) == 1 else group
            if not members:
                continue
            if len(group) > 1 and (set(group) & (singles | seen_singles)):
                continue  # an alternative list that includes a hard requirement adds nothing
            label = _requirement_label(members)
            if label not in labels and label not in seen_labels:
                labels.append(label)
        seen_singles |= singles
        seen_labels |= set(labels)
        result[tier] = labels
    return result


def _experience_band(text: str) -> Tuple[Optional[float], Optional[float]]:
    rng = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)", text, re.I)
    if rng:
        return float(rng.group(1)), float(rng.group(2))
    plus = re.search(r"(\d+(?:\.\d+)?)\s*\+\s*(?:years|yrs)", text, re.I) or \
        re.search(r"(?:minimum|at least|min\.?)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*(?:years|yrs)", text, re.I)
    if plus:
        return float(plus.group(1)), None
    return None, None


def _seniority(title: str) -> str:
    t = title.lower()
    if re.search(r"\b(principal|staff|head|director|architect)\b", t):
        return "principal"
    if re.search(r"\blead\b", t):
        return "lead"
    if re.search(r"\b(senior|sr\.?)\b", t):
        return "senior"
    if re.search(r"\b(junior|jr\.?|intern|trainee|graduate|associate)\b", t):
        return "junior"
    return "mid"


def _city(location: str) -> Optional[str]:
    if not location:
        return None
    first = re.split(r"[,(]", location)[0].strip()
    return {"Bengaluru": "Bangalore", "Gurugram": "Gurgaon"}.get(first, first) or None


def parse_requirement_labels(labels: List[str]) -> List[str]:
    """Normalizes user-edited requirement chips ('FastAPI / Django') to canonical names."""
    out: List[str] = []
    for label in labels:
        parts = [canonicalize(p) for p in re.split(r"\s*/\s*|\s+or\s+", label) if p.strip()]
        if parts:
            joined = " / ".join(dict.fromkeys(parts))
            if joined not in out:
                out.append(joined)
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def normalize_weights(weights: Optional[Dict[str, float]]) -> Dict[str, int]:
    merged = {**DEFAULT_WEIGHTS, **{k: v for k, v in (weights or {}).items() if k in DEFAULT_WEIGHTS}}
    merged = {k: max(0.0, float(v)) for k, v in merged.items()}
    total = sum(merged.values()) or 1.0
    scaled = {k: round(v * 100 / total) for k, v in merged.items()}
    drift = 100 - sum(scaled.values())
    if drift:
        top = max(scaled, key=scaled.get)
        scaled[top] += drift
    return scaled


def normalize_thresholds(thresholds: Optional[Dict[str, float]]) -> Dict[str, int]:
    merged = {**DEFAULT_THRESHOLDS, **{k: v for k, v in (thresholds or {}).items() if k in DEFAULT_THRESHOLDS}}
    shortlist = int(min(100, max(1, merged["shortlist"])))
    review = int(min(shortlist - 1, max(1, merged["review"])))
    hold = int(min(review - 1, max(0, merged["hold"])))
    return {"shortlist": shortlist, "review": review, "hold": hold}


def route_stage(score: int, thresholds: Dict[str, int]) -> str:
    if score >= thresholds["shortlist"]:
        return "shortlisted"
    if score >= thresholds["review"]:
        return "technical_review"
    if score >= thresholds["hold"]:
        return "hold"
    return "rejected"


def _has(skill: str, owned: set) -> bool:
    return skill in owned or bool(IMPLIED_SKILLS.get(skill, set()) & owned)


def _skill_analysis(profile: Dict[str, Any], requirements: Dict[str, List[str]]) -> Dict[str, Any]:
    owned = set(profile.get("skills", []))
    demonstrated = set(profile.get("demonstrated_skills", []))
    tiers: Dict[str, Dict[str, Any]] = {}
    for tier in ("critical", "core", "bonus"):
        matched, missing, credit = [], [], 0.0
        demonstrated_credit = 0.0
        for label in requirements.get(tier, []):
            members = label.split(" / ")
            hit = next((m for m in members if _has(m, owned)), None)
            if hit:
                shown = any(_has(m, demonstrated) for m in members)
                credit += 1.0 if shown else 0.85
                demonstrated_credit += 1.0 if shown else 0.0
                matched.append({"requirement": label, "skill": hit, "demonstrated": shown})
            else:
                missing.append(label)
        total = len(requirements.get(tier, []))
        tiers[tier] = {
            "matched": matched,
            "missing": missing,
            "total": total,
            "coverage": (credit / total) if total else None,
            "demonstrated_coverage": (demonstrated_credit / total) if total else None,
        }
    required_labels = {lbl for t in ("critical", "core", "bonus") for lbl in requirements.get(t, [])}
    required_members = {m for lbl in required_labels for m in lbl.split(" / ")}
    additional = [s for s in profile.get("skills", []) if s not in required_members][:12]
    return {"tiers": tiers, "additional": additional}


def _technical_score(analysis: Dict[str, Any]) -> Tuple[int, str]:
    weighted, weight_total = 0.0, 0.0
    for tier, weight in TIER_WEIGHTS.items():
        coverage = analysis["tiers"][tier]["coverage"]
        if coverage is not None:
            weighted += coverage * weight
            weight_total += weight
    score = round(100 * weighted / weight_total) if weight_total else 50
    crit = analysis["tiers"]["critical"]
    evidence = f"{len(crit['matched'])} of {crit['total']} critical" if crit["total"] else "No critical skills listed in JD"
    core = analysis["tiers"]["core"]
    if core["total"]:
        evidence += f" · {len(core['matched'])} of {core['total']} core"
    return max(0, min(100, score)), evidence


def _experience_score(profile: Dict[str, Any], jd: Dict[str, Any], analysis: Dict[str, Any]) -> Tuple[int, str]:
    years = float(profile.get("total_experience_years") or 0)
    lo, hi = jd.get("experience_min"), jd.get("experience_max")
    if profile.get("experience_source") == "not found":
        band_score, band_text = 40.0, "Experience not stated"
    elif lo is None:
        band_score, band_text = min(100.0, 55 + years * 9), f"{years:g} yrs · JD sets no band"
    elif years < lo:
        band_score = 100 * (years / lo) ** 1.3 if lo else 100
        band_text = f"{years:g} yrs vs {lo:g}+ yr minimum"
    elif hi is not None and years > hi + 2:
        band_score = max(70.0, 100 - (years - hi - 2) * 6)
        band_text = f"{years:g} yrs · above {lo:g}-{hi:g} yr band"
    else:
        band_score = 100.0
        band_text = f"{years:g} yrs · inside {lo:g}-{hi:g} yr band" if hi is not None else f"{years:g} yrs · meets {lo:g}+ yrs"

    demo_cov = analysis["tiers"]["critical"]["demonstrated_coverage"]
    relevance = demo_cov if demo_cov is not None else 0.7
    score = band_score * (0.55 + 0.45 * relevance)

    title = (profile.get("current_title") or profile.get("headline") or "").lower()
    seniority = jd.get("seniority")
    if seniority in {"senior", "lead", "principal"} and re.search(r"\b(junior|jr|intern|trainee)\b", title):
        score -= 12
    if seniority == "junior" and re.search(r"\b(lead|principal|staff|head)\b", title):
        score -= 6
    evidence = f"{band_text} · {round(relevance * 100)}% of critical stack used in roles"
    return max(0, min(100, round(score))), evidence


def _impact_score(profile: Dict[str, Any]) -> Tuple[int, str]:
    imp = profile.get("impact", {})
    quantified = imp.get("quantified_count", 0)
    verbs = len(imp.get("strong_verbs", []))
    leadership = len(imp.get("leadership_signals", []))
    bullets = imp.get("bullet_count", 0)
    support = imp.get("support_count", 0)
    score = (min(quantified, 4) / 4 * 45 + min(verbs, 5) / 5 * 25 + min(leadership, 2) / 2 * 15
             + min(bullets, 6) / 6 * 15 - min(support, 3) * 3)
    evidence = f"{quantified} quantified outcome{'s' if quantified != 1 else ''} · {verbs} ownership verb{'s' if verbs != 1 else ''}"
    if leadership:
        evidence += " · leadership signals"
    return max(8, min(100, round(score))), evidence


def _education_score(profile: Dict[str, Any], jd: Dict[str, Any], resume_text: str) -> Tuple[int, str, float]:
    edu = profile.get("highest_education") or {}
    base = {5: 100, 4: 90, 3: 78, 2: 55}.get(edu.get("rank", 0), 35)
    if edu.get("relevant_field"):
        base += 12
    if edu.get("tier_one"):
        base += 10
    gpa = edu.get("gpa")
    if edu.get("honors") or (gpa and _gpa_ratio(gpa) >= 0.8):
        base += 5
    edu_score = min(100, base)
    similarity = cosine(jd.get("keyword_vector") or {}, term_vector(resume_text))
    keyword_score = min(100.0, similarity / 0.42 * 100)
    score = round(edu_score * 0.5 + keyword_score * 0.5)
    degree = edu.get("degree") or "No degree found"
    evidence = f"{degree}{' · ' + edu['institution'] if edu.get('institution') else ''} · JD keyword match {round(similarity * 100)}%"
    return max(0, min(100, score)), evidence, similarity


def _gpa_ratio(gpa: str) -> float:
    try:
        num, _, den = gpa.partition("/")
        return float(num) / float(den or 10)
    except ValueError:
        return 0.0


def _join(items: List[str], limit: int = 3) -> str:
    items = items[:limit]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _short(text: str, limit: int = 110) -> str:
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _narrative(profile, jd, analysis, scores, stage, dedup, thresholds) -> Dict[str, Any]:
    crit = analysis["tiers"]["critical"]
    imp = profile.get("impact", {})
    years = profile.get("total_experience_years") or 0
    lo, hi = jd.get("experience_min"), jd.get("experience_max")
    name = profile.get("name", "Candidate")
    title = jd.get("title", "this role")

    if stage == "duplicate" and dedup.get("duplicate_of"):
        layer = next((l for l in dedup["layers"] if l["key"] == dedup["primary_layer"]), {})
        summary = (f"Same person as {dedup['duplicate_of']['name']} ({layer.get('label', 'dedup')}: {layer.get('detail', '').lower()}). "
                   f"Scored {scores['overall']} for reference; keep the original record in the pipeline.")
    else:
        parts = []
        if crit["total"]:
            gap = f", missing {_join(crit['missing'])}" if crit["missing"] else ""
            parts.append(f"Covers {len(crit['matched'])} of {crit['total']} critical requirements for {title}{gap}.")
        if lo is not None:
            if years < lo:
                parts.append(f"{years:g} years of experience against a {lo:g}-year minimum.")
            elif hi is not None and years > hi + 2:
                parts.append(f"{years:g} years of experience, above the {lo:g}-{hi:g} year band.")
            else:
                parts.append(f"{years:g} years of experience, inside the target band.")
        q = imp.get("quantified_count", 0)
        if q >= 2 and imp.get("evidence"):
            parts.append(f"{q} quantified outcomes, strongest: “{_short(imp['evidence'][0], 96)}”")
        elif q == 1:
            parts.append("One measurable outcome stated; impact is thin.")
        else:
            parts.append("No measurable outcomes stated.")
        summary = " ".join(parts)

    strengths: List[str] = []
    if crit["matched"]:
        strengths.append(f"Critical stack: {_join([m['skill'] for m in crit['matched']], 5)}")
    if lo is not None and years >= lo:
        strengths.append(f"{years:g} yrs experience meets the {lo:g}+ yr requirement")
    for bullet in imp.get("evidence", [])[:2]:
        strengths.append(_short(bullet, 120))
    if imp.get("leadership_signals"):
        strengths.append("Team leadership or mentoring evidence")
    edu = profile.get("highest_education") or {}
    if edu.get("tier_one"):
        strengths.append(f"{edu.get('degree')} from {edu.get('institution')}")

    concerns: List[str] = []
    if crit["missing"]:
        concerns.append(f"Missing critical: {_join(crit['missing'], 4)}")
    if lo is not None and years < lo:
        concerns.append(f"{round(lo - years, 1):g} yrs short of the experience minimum")
    listed_only = [m["skill"] for m in crit["matched"] if not m["demonstrated"]]
    if listed_only:
        concerns.append(f"Listed but not shown in any role: {_join(listed_only, 3)}")
    if imp.get("quantified_count", 0) == 0:
        concerns.append("No quantified outcomes in work history")
    if jd.get("city") and profile.get("city") and jd["work_mode"] != "Remote" and jd["city"].lower() != profile["city"].lower():
        concerns.append(f"Based in {profile['city']}; role is {jd['work_mode'] or 'on-site'} in {jd['city']}")
    semantic = next((l for l in dedup.get("layers", []) if l["key"] == "semantic"), None)
    if dedup.get("status") == "review" and semantic and semantic.get("matched"):
        concerns.append(f"{round(semantic['score'] * 100)}% similar to {semantic['matched']['name']}; confirm not a duplicate")

    focus: List[str] = []
    for label in crit["missing"][:2]:
        focus.append(f"Probe {label}: hands-on depth and recency")
    for skill in listed_only[:1]:
        focus.append(f"Verify {skill}: listed, not evidenced in project work")
    if scores["impact"] < 50:
        focus.append("Ask for measurable outcomes from the most recent role")
    if jd.get("seniority") in {"senior", "lead", "principal"} and not imp.get("leadership_signals"):
        focus.append("Assess ownership and mentoring at senior scope")
    if not focus:
        focus.append("System design depth on the team's core services")

    return {
        "headline": STAGE_HEADLINES[stage],
        "summary": summary,
        "strengths": strengths[:5],
        "concerns": concerns[:5],
        "interview_focus": focus[:3],
    }


class ResumeScorer:
    def __init__(self) -> None:
        self.groq_client = None
        self.openai_client = None
        if Groq and config.GROQ_API_KEY:
            try:
                self.groq_client = Groq(api_key=config.GROQ_API_KEY, timeout=config.LLM_TIMEOUT_SECONDS)
            except Exception as exc:  # pragma: no cover - network/env specific
                print(f"[scorer] Groq client unavailable: {exc}")
        if OpenAI and config.OPENAI_API_KEY:
            try:
                self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=config.LLM_TIMEOUT_SECONDS)
            except Exception as exc:  # pragma: no cover
                print(f"[scorer] OpenAI client unavailable: {exc}")

    def providers(self) -> Dict[str, Dict[str, Any]]:
        return {
            "deterministic": {"available": True, "label": "Deterministic engine", "model": "rules v2"},
            "groq": {"available": bool(self.groq_client), "label": "Groq", "model": config.GROQ_MODEL,
                     "missing": None if self.groq_client else "GROQ_API_KEY"},
            "openai": {"available": bool(self.openai_client), "label": "OpenAI", "model": config.OPENAI_MODEL,
                       "missing": None if self.openai_client else "OPENAI_API_KEY"},
        }

    def resolve_provider(self, requested: Optional[str]) -> str:
        requested = (requested or "deterministic").lower()
        if requested == "groq" and self.groq_client:
            return "groq"
        if requested == "openai" and self.openai_client:
            return "openai"
        return "deterministic"

    def score(self, profile: Dict[str, Any], resume_text: str, jd: Dict[str, Any], dedup: Dict[str, Any],
              provider: str = "deterministic") -> Dict[str, Any]:
        requirements = jd["requirements"]
        weights = normalize_weights(jd.get("weights"))
        thresholds = normalize_thresholds(jd.get("thresholds"))
        analysis = _skill_analysis(profile, requirements)

        technical, tech_ev = _technical_score(analysis)
        experience, exp_ev = _experience_score(profile, jd, analysis)
        impact, imp_ev = _impact_score(profile)
        education, edu_ev, similarity = _education_score(profile, jd, resume_text)
        dims = {"technical": technical, "experience": experience, "impact": impact, "education": education}

        engine = {"provider": "deterministic", "label": "Deterministic engine", "model": "rules v2", "fallback_reason": None}
        llm_narrative: Optional[Dict[str, Any]] = None
        resolved = self.resolve_provider(provider)
        if provider and provider != "deterministic" and resolved == "deterministic":
            engine["fallback_reason"] = f"{provider} not configured"
        if resolved != "deterministic":
            try:
                llm = self._llm_assess(resolved, profile, resume_text, jd, analysis, dims)
                dims = {k: round(0.5 * dims[k] + 0.5 * llm["scores"][k]) for k in dims}
                llm_narrative = llm
                model = config.GROQ_MODEL if resolved == "groq" else config.OPENAI_MODEL
                engine = {"provider": resolved, "label": f"Hybrid · {resolved.title()}", "model": model, "fallback_reason": None}
            except Exception as exc:
                engine["fallback_reason"] = f"{resolved} call failed: {exc.__class__.__name__}"

        overall = round(sum(dims[k] * weights[k] for k in dims) / 100)
        crit_cov = analysis["tiers"]["critical"]["coverage"]
        knockout = None
        if crit_cov is not None and crit_cov < KNOCKOUT_COVERAGE:
            capped = min(overall, thresholds["hold"] - 1)
            if capped < overall:
                knockout = f"Covers under {round(KNOCKOUT_COVERAGE * 100)}% of critical requirements; capped at {capped}"
            overall = capped

        auto_stage = "duplicate" if dedup.get("is_duplicate") else route_stage(overall, thresholds)
        scores = {**dims, "overall": overall}
        narrative = _narrative(profile, jd, analysis, scores, auto_stage, dedup, thresholds)
        if llm_narrative:
            for key in ("summary", "strengths", "concerns", "interview_focus"):
                # A duplicate keeps the deterministic summary: it must name the original record.
                if llm_narrative.get(key) and not (key == "summary" and auto_stage == "duplicate"):
                    narrative[key] = llm_narrative[key]

        tiers = analysis["tiers"]
        return {
            "scores": scores,
            "weights": weights,
            "thresholds": thresholds,
            "evidence": {"technical": tech_ev, "experience": exp_ev, "impact": imp_ev, "education": edu_ev},
            "keyword_similarity": round(similarity, 3),
            "knockout": knockout,
            "skills": {
                "matched": [m["skill"] for t in ("critical", "core", "bonus") for m in tiers[t]["matched"]],
                "matched_detail": {t: tiers[t]["matched"] for t in tiers},
                "missing_critical": tiers["critical"]["missing"],
                "missing_core": tiers["core"]["missing"],
                "bonus_matched": [m["skill"] for m in tiers["bonus"]["matched"]],
                "additional": analysis["additional"],
                "critical_coverage": round((crit_cov or 0) * 100),
                "counts": {t: {"matched": len(tiers[t]["matched"]), "total": tiers[t]["total"]} for t in tiers},
            },
            "auto_stage": auto_stage,
            "recommendation": narrative,
            "engine": engine,
        }

    # -- LLM ---------------------------------------------------------------
    def _llm_assess(self, provider: str, profile, resume_text, jd, analysis, dims) -> Dict[str, Any]:
        system = (
            "You are a senior technical recruiter. Score the candidate against the role on four dimensions, "
            "each an integer 0-100: technical (required-skill fit), experience (years and seniority relevant to the role), "
            "impact (measurable outcomes and ownership), education (degree relevance and keyword alignment). "
            "Base every claim on the resume text; never invent employers, numbers or skills. "
            "Reply with JSON only: {\"scores\": {\"technical\": int, \"experience\": int, \"impact\": int, \"education\": int}, "
            "\"summary\": \"2-3 sentence hiring recommendation\", \"strengths\": [\"...\"], \"concerns\": [\"...\"], "
            "\"interview_focus\": [\"...\"]}. Keep each list to at most 4 short items."
        )
        reqs = jd["requirements"]
        user = (
            f"ROLE: {jd.get('title')}\nEXPERIENCE BAND: {jd.get('experience_min')}-{jd.get('experience_max')} years\n"
            f"CRITICAL REQUIREMENTS: {', '.join(reqs.get('critical', []))}\n"
            f"CORE REQUIREMENTS: {', '.join(reqs.get('core', []))}\n"
            f"NICE TO HAVE: {', '.join(reqs.get('bonus', []))}\n"
            f"DETERMINISTIC REFERENCE SCORES: {json.dumps(dims)}\n"
            f"MISSING CRITICAL (deterministic): {', '.join(analysis['tiers']['critical']['missing']) or 'none'}\n\n"
            f"RESUME:\n{resume_text[:6000]}"
        )
        client = self.groq_client if provider == "groq" else self.openai_client
        model = config.GROQ_MODEL if provider == "groq" else config.OPENAI_MODEL
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        parsed = json.loads(content)
        scores = parsed.get("scores", {})
        clean = {k: max(0, min(100, int(round(float(scores.get(k, dims[k])))))) for k in dims}

        def _list(key: str) -> List[str]:
            value = parsed.get(key) or []
            return [str(v).strip()[:160] for v in value if str(v).strip()][:4] if isinstance(value, list) else []

        return {
            "scores": clean,
            "summary": str(parsed.get("summary", "")).strip()[:600],
            "strengths": _list("strengths"),
            "concerns": _list("concerns"),
            "interview_focus": _list("interview_focus"),
        }
