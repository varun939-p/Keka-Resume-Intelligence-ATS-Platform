import random
import hashlib
import datetime
from typing import Dict, Any, List

class BulkResumeGenerator:
    """
    High-Throughput Bulk Resume Generator & Scorer for Keka ATS.
    Simulates the ingestion, parsing, deduplication, and LLM/Heuristic scoring of 1,000+
    applicant resumes across realistic Indian tech talent pools with exact & semantic duplicates.
    """

    FIRST_NAMES = [
        "Arjun", "Priya", "Rohit", "Ananya", "Vikram", "Sneha", "Rahul", "Kavya", "Siddharth", "Aditi",
        "Karan", "Neha", "Amit", "Pooja", "Suresh", "Divya", "Varun", "Meera", "Deepak", "Tanvi",
        "Rishabh", "Shruti", "Manish", "Swati", "Nikhil", "Simran", "Prashant", "Pallavi", "Akash", "Ritu",
        "Gaurav", "Nandini", "Harsh", "Sakshi", "Abhishek", "Radhika", "Vivek", "Preeti", "Kunal", "Isha"
    ]

    LAST_NAMES = [
        "Verma", "Sharma", "Kumar", "Deshmukh", "Singh", "Reddy", "Gupta", "Nair", "Kulkarni", "Rao",
        "Malhotra", "Joshi", "Yadav", "Patel", "Menon", "Chopra", "Saxena", "Jain", "Mehta", "Iyer",
        "Pillai", "Bhatia", "Mishra", "Pandey", "Chauhan", "Thakur", "Sinha", "Das", "Roy", "Banerjee"
    ]

    LOCATIONS = [
        ("Hyderabad, Telangana, India", True, 0.42),
        ("Bangalore, Karnataka, India", False, 0.24),
        ("Pune, Maharashtra, India", False, 0.12),
        ("Gurgaon, Haryana, India", False, 0.10),
        ("Mumbai, Maharashtra, India", False, 0.08),
        ("Remote / India", False, 0.04)
    ]

    ROLES_STACKS = [
        # (Role Title, Skills List, Base Tech Score, Base Exp Range, Target Rec)
        ("Senior Python Backend Engineer", ["Python", "FastAPI", "Django", "Celery", "PostgreSQL", "Redis", "Docker", "AWS", "AsyncIO", "PyTest"], 33, (5.0, 9.0), "Strong Hire / Immediate Interview"),
        ("Lead Data & Backend Automation Engineer", ["Python", "FastAPI", "Apache Airflow", "Celery", "PostgreSQL", "Kafka", "Docker", "AWS S3"], 31, (4.5, 8.5), "Strong Hire / Immediate Interview"),
        ("AI / ML Lead Engineer (LLMs & RAG)", ["Python", "PyTorch", "LangChain", "LlamaIndex", "Groq API", "OpenAI", "Vector Database", "FastAPI", "Docker"], 34, (3.5, 7.5), "Strong Hire / Immediate Interview"),
        ("Full Stack Engineer (Python + React)", ["Python", "FastAPI", "React.js", "TypeScript", "Tailwind CSS", "PostgreSQL", "Docker", "Git"], 29, (3.0, 6.0), "Strong Hire / Immediate Interview"),
        ("Cloud DevOps & Infrastructure Engineer", ["Kubernetes", "Docker", "AWS EKS", "Terraform", "Ansible", "Python Scripting", "Prometheus", "CI/CD"], 25, (4.0, 8.0), "Interview / Good Fit"),
        ("Mid-Level Python Developer", ["Python", "Django REST Framework", "PostgreSQL", "Celery", "Git", "Docker Basic"], 26, (2.5, 4.5), "Interview / Good Fit"),
        ("Junior Python Developer", ["Python", "Flask", "SQLite", "HTML/CSS", "Git", "Postman"], 18, (1.0, 2.0), "Hold / Potential Pipeline"),
        ("Senior Java SpringBoot Engineer", ["Java 17", "Spring Boot", "Hibernate ORM", "Oracle DB", "MySQL", "Apache Tomcat", "SOAP", "Monolith"], 10, (5.0, 10.0), "Reject / Low Fit"),
        ("Java & .NET Enterprise Developer", ["C#", ".NET Core", "Java", "SQL Server", "IIS", "Legacy API"], 8, (4.0, 9.0), "Reject / Low Fit"),
        ("Senior HR Operations & ATS Recruiter", ["Talent Acquisition", "ATS Management", "Keka HRMS", "Employee Onboarding", "Excel Pivot Tables"], 4, (3.0, 7.0), "Reject / Low Fit")
    ]

    def __init__(self, seed: int = 42):
        random.seed(seed)

    def generate_bulk_dataset(self, total_count: int = 1000, jd_name: str = "Senior Python Backend Engineer") -> Dict[str, Any]:
        """
        Generates `total_count` resumes with exact & semantic duplicates, runs automated scoring,
        and returns complete analytics for the Keka Bulk ATS dashboard.
        """
        candidates = []
        unique_profiles = []
        duplicate_count = 0

        # We will generate ~88% unique candidates and ~12% duplicates
        target_unique = int(total_count * 0.88)

        for i in range(1, target_unique + 1):
            cand = self._create_single_candidate(i, jd_name)
            candidates.append(cand)
            unique_profiles.append(cand)

        # Generate ~12% duplicates based on already created unique profiles
        remaining = total_count - len(candidates)
        for j in range(remaining):
            orig = random.choice(unique_profiles)
            dup_type = random.choices(
                ["Exact SHA-256 Hash Match", "Semantic Profile Match (Identical Email/Phone)", "High Fuzzy Content Similarity (89.4% match)"],
                weights=[0.35, 0.45, 0.20]
            )[0]

            dup_cand = dict(orig)
            dup_cand["candidate_id"] = f"CAN-BULK-DUP-{1000 + j + 1}"
            dup_cand["filename"] = f"resume_{orig['candidate_id'].lower()}_duplicate.pdf"
            dup_cand["is_duplicate"] = True
            dup_cand["duplicate_type"] = dup_type
            dup_cand["duplicate_of"] = orig["candidate_id"]
            dup_cand["duplicate_of_name"] = orig["name"]

            # If semantic or fuzzy duplicate, slightly tweak display experience or summary
            if "Semantic" in dup_type or "Fuzzy" in dup_type:
                dup_cand["filename"] = f"resume_{orig['name'].lower().replace(' ', '_')}_updated_cv.pdf"
            
            candidates.append(dup_cand)
            duplicate_count += 1

        # Sort all 1,000 candidates descending by overall_fit_score
        candidates.sort(key=lambda x: x["overall_fit_score"], reverse=True)

        # Assign rankings (#1 to #1000)
        for idx, c in enumerate(candidates, 1):
            c["rank"] = idx

        # Compute summary KPIs
        hyderabad_count = sum(1 for c in candidates if c["is_hyderabad_based"])
        strong_hires = sum(1 for c in candidates if c["overall_fit_score"] >= 82)
        interviews = sum(1 for c in candidates if 68 <= c["overall_fit_score"] < 82)
        holds = sum(1 for c in candidates if 52 <= c["overall_fit_score"] < 68)
        rejects = sum(1 for c in candidates if c["overall_fit_score"] < 52)

        return {
            "success": True,
            "total_scanned": len(candidates),
            "unique_candidates_count": len(candidates) - duplicate_count,
            "duplicates_detected_count": duplicate_count,
            "hyderabad_local_count": hyderabad_count,
            "hyderabad_percentage": round((hyderabad_count / len(candidates)) * 100, 1),
            "processing_time_seconds": 1.84,
            "jd_name": jd_name,
            "recommendation_breakdown": {
                "strong_hire": strong_hires,
                "interview": interviews,
                "hold": holds,
                "reject": rejects
            },
            "top_candidates_preview": candidates[:50], # return Top 50 directly for immediate table rendering
            "all_candidates": candidates # return all 1,000 for export/deep dive
        }

    def _create_single_candidate(self, index: int, jd_name: str) -> Dict[str, Any]:
        first = random.choice(self.FIRST_NAMES)
        last = random.choice(self.LAST_NAMES)
        name = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}.{random.randint(10,99)}@gmail.com"
        phone = f"+91-{random.randint(9000000000, 9999999999)}"

        # Weighted location
        loc_choice = random.choices(self.LOCATIONS, weights=[l[2] for l in self.LOCATIONS])[0]
        location = loc_choice[0]
        is_hyd = loc_choice[1]

        # Weighted role/skills selection
        role_tuple = random.choices(
            self.ROLES_STACKS,
            weights=[0.18, 0.12, 0.10, 0.14, 0.10, 0.12, 0.08, 0.08, 0.05, 0.03]
        )[0]

        role_title, skills, base_tech, exp_range, target_rec = role_tuple
        exp_years = round(random.uniform(exp_range[0], exp_range[1]), 1)

        # Calculate category scores with realistic variation
        tech_score = min(max(int(base_tech + random.randint(-2, 2)), 4), 35)
        
        # Experience score (/30)
        if exp_years >= 6.0: exp_score = random.randint(27, 30)
        elif exp_years >= 4.0: exp_score = random.randint(24, 27)
        elif exp_years >= 2.5: exp_score = random.randint(19, 23)
        elif exp_years >= 1.0: exp_score = random.randint(14, 18)
        else: exp_score = random.randint(8, 13)

        # Education score (/15)
        edu_score = random.choice([15, 14, 13, 12, 11]) if "Java" not in role_title and "HR" not in role_title else random.choice([12, 11, 10, 9])

        # Keka domain & cultural fit (/20)
        keka_score = 10
        if is_hyd: keka_score += 5
        if any(w in " ".join(skills) for w in ["Celery", "FastAPI", "PostgreSQL", "Kafka", "Airflow"]): keka_score += 4
        if "HR" in role_title or "ATS" in role_title: keka_score += 3
        keka_score = min(max(keka_score + random.randint(-1, 1), 5), 20)

        total_score = tech_score + exp_score + edu_score + keka_score
        total_score = min(max(total_score, 25), 100)

        # Final recommendation assignment based on strict Keka thresholds
        if total_score >= 82: rec = "Strong Hire / Immediate Interview"
        elif total_score >= 68: rec = "Interview / Good Fit"
        elif total_score >= 52: rec = "Hold / Potential Pipeline"
        else: rec = "Reject / Low Fit"

        # Generate strengths & gaps strings
        strengths = []
        if is_hyd: strengths.append(f"Located in Hyderabad ({location}), aligned with Keka hybrid team.")
        if "Python" in skills: strengths.append(f"Strong Python backend skills ({', '.join(skills[:3])}).")
        if exp_years >= 4.5: strengths.append(f"Solid senior tenure ({exp_years} years experience).")
        if not strengths: strengths.append("Meets minimum baseline criteria.")

        gaps = []
        if not is_hyd: gaps.append(f"Located in {location.split(',')[0]} (Relocation or remote arrangement required).")
        if "Python" not in skills: gaps.append("Primary tech stack is not Python backend ecosystems required by Keka.")
        if exp_years < 3.0: gaps.append("Junior experience level compared to target senior backend criteria.")
        if not gaps: gaps.append("No critical skill gaps identified.")

        return {
            "candidate_id": f"CAN-BULK-{10000 + index}",
            "filename": f"resume_{name.lower().replace(' ', '_')}_{index}.pdf",
            "name": name,
            "email": email,
            "phone": phone,
            "location": location,
            "is_hyderabad_based": is_hyd,
            "total_years_experience": exp_years,
            "role_title": role_title,
            "skills_list": skills,
            "overall_fit_score": total_score,
            "recommendation": rec,
            "category_scores": {
                "technical_skills_score": tech_score,
                "relevant_experience_score": exp_score,
                "education_and_certifications_score": edu_score,
                "keka_domain_and_cultural_fit_score": keka_score
            },
            "key_strengths": strengths,
            "missing_skills_and_gaps": gaps,
            "is_duplicate": False,
            "duplicate_type": "None",
            "duplicate_of": None,
            "duplicate_of_name": None
        }

if __name__ == "__main__":
    gen = BulkResumeGenerator()
    data = gen.generate_bulk_dataset(1000)
    print(f"Generated {data['total_scanned']} candidates in {data['processing_time_seconds']}s. Unique: {data['unique_candidates_count']}, Duplicates: {data['duplicates_detected_count']}")
