import os
import json
import re
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

# Attempt importing Groq and OpenAI clients
try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class ResumeScorer:
    """
    Keka Resume Intelligence LLM Scoring Engine.
    Scores candidates against specific Job Descriptions using Groq LLaMA, OpenAI,
    or a high-precision Local Heuristic Fallback Engine for instant offline evaluation.
    """

    def __init__(self, provider: Optional[str] = None):
        self.groq_key = os.getenv("GROQ_API_KEY", "").strip()
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.default_provider = provider or os.getenv("DEFAULT_LLM_PROVIDER", "groq").lower()
        self.groq_model = os.getenv("DEFAULT_GROQ_MODEL", "llama-3.3-70b-versatile")
        self.openai_model = os.getenv("DEFAULT_OPENAI_MODEL", "gpt-4o-mini")

        self.groq_client = None
        if Groq and self.groq_key and not self.groq_key.startswith("your_"):
            try:
                self.groq_client = Groq(api_key=self.groq_key)
            except Exception as e:
                print(f"[Scorer Init] Could not initialize Groq client: {e}")

        self.openai_client = None
        if OpenAI and self.openai_key and not self.openai_key.startswith("your_"):
            try:
                self.openai_client = OpenAI(api_key=self.openai_key)
            except Exception as e:
                print(f"[Scorer Init] Could not initialize OpenAI client: {e}")

    def score_resume(self, resume_text: str, candidate_metadata: Dict[str, Any], jd_text: str, provider: Optional[str] = None) -> Dict[str, Any]:
        """
        Main scoring entry point. Routes to Groq LLaMA, OpenAI, or Local Heuristic Scorer.
        Returns a clean structured JSON dictionary with detailed category breakdowns.
        """
        chosen_provider = (provider or self.default_provider).lower()

        # Try Groq API
        if chosen_provider == "groq" and self.groq_client:
            try:
                return self._score_with_groq(resume_text, candidate_metadata, jd_text)
            except Exception as e:
                print(f"[Scorer Fallback] Groq API call failed ({e}). Switching to Local Heuristic Scorer.")

        # Try OpenAI API
        elif chosen_provider == "openai" and self.openai_client:
            try:
                return self._score_with_openai(resume_text, candidate_metadata, jd_text)
            except Exception as e:
                print(f"[Scorer Fallback] OpenAI API call failed ({e}). Switching to Local Heuristic Scorer.")

        # Default or Fallback to Local Heuristic Scorer
        return self._score_with_local_heuristics(resume_text, candidate_metadata, jd_text)

    def _score_with_groq(self, resume_text: str, candidate_metadata: Dict[str, Any], jd_text: str) -> Dict[str, Any]:
        """Calls Groq API using LLaMA 3.3 70B for fast, accurate structured JSON evaluation."""
        system_prompt = (
            "You are an expert HR Intelligence & Technical Hiring Assistant for Keka, a leading Hyderabad-based "
            "HR tech platform processing massive daily datasets (500+ employees, heavy Python backend, ATS & automation focus). "
            "Evaluate the candidate resume against the provided Job Description strictly in JSON format with NO markdown formatting outside the JSON object.\n"
            "Return JSON matching exactly this structure:\n"
            "{\n"
            '  "overall_fit_score": <int 0-100>,\n'
            '  "category_scores": {\n'
            '    "technical_skills_score": <int 0-35>,\n'
            '    "relevant_experience_score": <int 0-30>,\n'
            '    "education_and_certifications_score": <int 0-15>,\n'
            '    "keka_domain_and_cultural_fit_score": <int 0-20>\n'
            '  },\n'
            '  "key_strengths": [<array of 3-5 string bullet points>],\n'
            '  "missing_skills_and_gaps": [<array of 2-4 string bullet points>],\n'
            '  "recommendation": "<Strong Hire / Immediate Interview | Interview / Good Fit | Hold / Potential Pipeline | Reject / Low Fit>",\n'
            '  "summary_rationale": "<2-3 sentence executive evaluation>"\n'
            "}"
        )

        user_prompt = f"""JOB DESCRIPTION:
{jd_text[:3500]}

CANDIDATE METADATA:
{json.dumps(candidate_metadata, indent=2)}

RESUME TEXT:
{resume_text[:4000]}
"""
        response = self.groq_client.chat.completions.create(
            model=self.groq_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        return self._parse_and_validate_llm_json(content, candidate_metadata)

    def _score_with_openai(self, resume_text: str, candidate_metadata: Dict[str, Any], jd_text: str) -> Dict[str, Any]:
        """Calls OpenAI API using GPT-4o-mini for structured resume evaluation."""
        system_prompt = (
            "You are Keka's Lead AI Technical Recruiter evaluating candidate resumes against specific Job Descriptions. "
            "Respond ONLY with a valid JSON object matching exactly this schema:\n"
            "{\n"
            '  "overall_fit_score": <int 0-100>,\n'
            '  "category_scores": {\n'
            '    "technical_skills_score": <int 0-35>,\n'
            '    "relevant_experience_score": <int 0-30>,\n'
            '    "education_and_certifications_score": <int 0-15>,\n'
            '    "keka_domain_and_cultural_fit_score": <int 0-20>\n'
            '  },\n'
            '  "key_strengths": [<array of strings>],\n'
            '  "missing_skills_and_gaps": [<array of strings>],\n'
            '  "recommendation": "<Strong Hire / Immediate Interview | Interview / Good Fit | Hold / Potential Pipeline | Reject / Low Fit>",\n'
            '  "summary_rationale": "<executive summary string>"\n'
            "}"
        )

        user_prompt = f"JD:\n{jd_text[:3500]}\n\nCandidate Meta:\n{json.dumps(candidate_metadata)}\n\nResume:\n{resume_text[:4000]}"
        response = self.openai_client.chat.completions.create(
            model=self.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        return self._parse_and_validate_llm_json(content, candidate_metadata)

    def _parse_and_validate_llm_json(self, raw_content: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Cleans and validates JSON returned by LLM APIs."""
        try:
            # Strip markdown fence if present
            clean_str = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw_content.strip(), flags=re.MULTILINE)
            parsed = json.loads(clean_str)
            
            # Ensure required fields and numeric bounds
            scores = parsed.get("category_scores", {})
            tech_score = min(max(int(scores.get("technical_skills_score", 20)), 0), 35)
            exp_score = min(max(int(scores.get("relevant_experience_score", 15)), 0), 30)
            edu_score = min(max(int(scores.get("education_and_certifications_score", 10)), 0), 15)
            keka_score = min(max(int(scores.get("keka_domain_and_cultural_fit_score", 10)), 0), 20)

            total = tech_score + exp_score + edu_score + keka_score

            # Validate recommendation string
            rec = parsed.get("recommendation", "Interview / Good Fit")
            if total >= 82:
                rec = "Strong Hire / Immediate Interview"
            elif total >= 68:
                rec = "Interview / Good Fit"
            elif total >= 50:
                rec = "Hold / Potential Pipeline"
            else:
                rec = "Reject / Low Fit"

            return {
                "overall_fit_score": total,
                "category_scores": {
                    "technical_skills_score": tech_score,
                    "relevant_experience_score": exp_score,
                    "education_and_certifications_score": edu_score,
                    "keka_domain_and_cultural_fit_score": keka_score
                },
                "key_strengths": parsed.get("key_strengths", ["Strong technical foundation.", "Relevant domain experience."]),
                "missing_skills_and_gaps": parsed.get("missing_skills_and_gaps", ["Specific framework depth can be evaluated in technical round."]),
                "recommendation": rec,
                "summary_rationale": parsed.get("summary_rationale", f"Candidate {metadata.get('name')} scored {total}/100 against the Keka engineering job description."),
                "scoring_engine": "LLM API (Groq/OpenAI)"
            }
        except Exception as e:
            print(f"[LLM JSON Error] Could not parse LLM output: {e}. Falling back to heuristics.")
            return self._score_with_local_heuristics("", metadata, "")

    def _score_with_local_heuristics(self, resume_text: str, candidate_metadata: Dict[str, Any], jd_text: str) -> Dict[str, Any]:
        """
        High-Precision Local Heuristic NLP Scorer for Keka ATS.
        Provides 100% deterministic, ultra-fast evaluation when offline or when LLM API keys are not supplied.
        Analyzes skill overlaps, experience duration, location match (Hyderabad), and domain affinity.
        """
        jd_lower = jd_text.lower() if jd_text else "python fastapi celery postgresql backend hr tech ats hyderabad 4+ years"
        cand_name = candidate_metadata.get("name", "Candidate")
        skills_list = [s.lower() for s in candidate_metadata.get("skills_list", [])]
        exp_years = candidate_metadata.get("total_years_experience", 3.0)
        is_hyd = candidate_metadata.get("is_hyderabad_based", False)
        location = candidate_metadata.get("location", "")
        education = candidate_metadata.get("education", "")

        # Also extract skills directly from resume_text if not enough found in metadata
        text_lower = resume_text.lower() if resume_text else ""
        combined_text = (text_lower + " " + " ".join(skills_list)).lower()

        # 1. Technical Skills Scoring (Max 35 points)
        core_python_keywords = ["python", "fastapi", "django", "flask", "celery", "asyncio", "pytest"]
        db_keywords = ["postgresql", "redis", "sql", "sqlalchemy", "mysql", "mongodb"]
        devops_keywords = ["docker", "kubernetes", "aws", "git", "ci/cd", "terraform"]
        frontend_keywords = ["react", "typescript", "javascript", "tailwind"]
        ai_keywords = ["llm", "llama", "groq", "openai", "langchain", "rag"]

        matched_core = [k for k in core_python_keywords if k in combined_text]
        matched_db = [k for k in db_keywords if k in combined_text]
        matched_devops = [k for k in devops_keywords if k in combined_text]
        matched_frontend = [k for k in frontend_keywords if k in combined_text]
        matched_ai = [k for k in ai_keywords if k in combined_text]

        tech_score = 0
        if "python" in matched_core:
            tech_score += 10
        if "fastapi" in matched_core or "django" in matched_core:
            tech_score += 8
        if "celery" in matched_core or "asyncio" in matched_core:
            tech_score += 5
        if matched_db:
            tech_score += min(len(matched_db) * 2, 6)
        if matched_devops:
            tech_score += min(len(matched_devops) * 2, 6)

        # Adjust based on whether JD is specifically Fullstack or AI
        if "react" in jd_lower and matched_frontend:
            tech_score = min(tech_score + 6, 35)
        if ("ai" in jd_lower or "llm" in jd_lower) and matched_ai:
            tech_score = min(tech_score + 8, 35)

        tech_score = min(max(tech_score, 8), 35)

        # 2. Relevant Experience Scoring (Max 30 points)
        exp_score = 12
        if exp_years >= 6.0:
            exp_score = 30
        elif exp_years >= 4.0:
            exp_score = 26
        elif exp_years >= 3.0:
            exp_score = 22
        elif exp_years >= 1.5:
            exp_score = 16
        else:
            exp_score = 10

        # Penalty if Java/Monolith candidate with low python experience
        if "java" in combined_text and "python" not in matched_core:
            tech_score = min(tech_score, 12)
            exp_score = min(exp_score, 14)

        # 3. Education Scoring (Max 15 points)
        edu_score = 11
        if any(w in education.lower() for w in ["iit", "nit", "iiit", "bits", "distinction", "gpa: 8", "gpa: 9"]):
            edu_score = 15
        elif any(w in education.lower() for w in ["b.tech", "b.e.", "m.tech", "computer science", "it", "engineering"]):
            edu_score = 13

        # 4. Keka Domain & Cultural Fit Scoring (Max 20 points)
        # Check Keka's exact preferences: Hyderabad based, automation, HR tech / ATS / payroll domain, 500+ scale
        keka_score = 10
        strengths = []
        gaps = []

        if is_hyd or "hyderabad" in location.lower():
            keka_score += 5
            strengths.append(f"Located in Hyderabad ({location}), perfectly aligned with Keka's hybrid engineering team.")
        else:
            gaps.append(f"Located outside Hyderabad ({location}). May require relocation or remote work arrangement.")

        hr_domain_words = ["ats", "payroll", "attendance", "hrms", "keka", "recruitment", "human resources", "applicant tracking"]
        matched_domain = [w for w in hr_domain_words if w in combined_text]
        if matched_domain:
            keka_score += 5
            strengths.append(f"Direct HR Tech / ATS / Payroll domain expertise ({', '.join([w.title() for w in matched_domain[:3]])}).")

        if any(w in combined_text for w in ["automation", "pipeline", "high-throughput", "concurrency", "celery", "rabbitmq", "kafka"]):
            strengths.append("Strong demonstrated background in asynchronous data pipelines and automation engineering.")
        else:
            gaps.append("Could show more explicit background in high-throughput task queues (Celery/Kafka) for large-scale HR data.")

        if "python" in matched_core and ("fastapi" in matched_core or "django" in matched_core):
            strengths.append(f"Solid Python backend stack mastery ({', '.join([w.title() for w in matched_core[:3]])}).")
        elif "python" not in matched_core:
            gaps.append("Primary experience is not in Python backend ecosystems required by Keka.")

        if not gaps:
            gaps.append("Minor gap: Can evaluate system design depth during technical rounds.")

        keka_score = min(max(keka_score, 6), 20)
        total_score = tech_score + exp_score + edu_score + keka_score

        # Recommendation
        if total_score >= 82:
            recommendation = "Strong Hire / Immediate Interview"
        elif total_score >= 68:
            recommendation = "Interview / Good Fit"
        elif total_score >= 52:
            recommendation = "Hold / Potential Pipeline"
        else:
            recommendation = "Reject / Low Fit"

        rationale = (
            f"{cand_name} achieved an overall fit score of {total_score}/100 against Keka's requirements. "
            f"The candidate brings {exp_years} years of experience with strong ratings in technical skills ({tech_score}/35) "
            f"and cultural/domain fit ({keka_score}/20)."
        )

        return {
            "overall_fit_score": total_score,
            "category_scores": {
                "technical_skills_score": tech_score,
                "relevant_experience_score": exp_score,
                "education_and_certifications_score": edu_score,
                "keka_domain_and_cultural_fit_score": keka_score
            },
            "key_strengths": strengths[:4],
            "missing_skills_and_gaps": gaps[:3],
            "recommendation": recommendation,
            "summary_rationale": rationale,
            "scoring_engine": "Keka High-Precision Local Heuristic Engine (Offline / Zero-Latency)"
        }
