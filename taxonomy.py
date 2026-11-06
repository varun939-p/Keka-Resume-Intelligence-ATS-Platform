"""
Skill taxonomy shared by the resume parser and the JD profiler.

Each skill has a canonical display name, a category, and the aliases recruiters
actually see on resumes. Aliases are matched on token boundaries, so "Java"
never matches inside "JavaScript" and "SQL" never matches inside "PostgreSQL".
An alias prefixed with "re:" is a raw regular expression.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict, Iterable, List, Pattern, Tuple

# (canonical, category, aliases)
SKILLS: List[Tuple[str, str, List[str]]] = [
    # Languages
    ("Python", "Languages", ["python", "python3"]),
    ("Java", "Languages", ["java", "java 8", "java 11", "java 17"]),
    ("JavaScript", "Languages", ["javascript", "es6"]),
    ("TypeScript", "Languages", ["typescript"]),
    ("Go", "Languages", ["golang", "go lang"]),
    ("Rust", "Languages", ["rust"]),
    ("C#", "Languages", ["c#"]),
    ("C++", "Languages", ["c++"]),
    ("Scala", "Languages", ["scala"]),
    ("Kotlin", "Languages", ["kotlin"]),
    ("PHP", "Languages", ["php"]),
    ("Ruby", "Languages", ["ruby", "ruby on rails", "rails"]),
    ("SQL", "Languages", ["sql", "t-sql", "pl/sql", "sql schemas", "sql queries"]),
    ("Bash", "Languages", ["bash", "shell scripting", "shell scripts"]),
    # Backend frameworks
    ("FastAPI", "Backend", ["fastapi", "fast api"]),
    ("Django", "Backend", ["django", "django orm"]),
    ("Django REST Framework", "Backend", ["django rest framework", "drf"]),
    ("Flask", "Backend", ["flask"]),
    ("AsyncIO", "Backend", ["asyncio", "async io", "asynchronous python", "async/await"]),
    ("Spring Boot", "Backend", ["spring boot", "springboot", "spring mvc", "spring security"]),
    ("Node.js", "Backend", ["node.js", "nodejs"]),
    ("Express", "Backend", ["express.js", "expressjs"]),
    (".NET", "Backend", [".net", ".net core", "asp.net"]),
    ("Hibernate", "Backend", ["hibernate"]),
    ("SQLAlchemy", "Backend", ["sqlalchemy"]),
    ("Pydantic", "Backend", ["pydantic"]),
    ("GraphQL", "Backend", ["graphql"]),
    ("gRPC", "Backend", ["grpc"]),
    ("REST APIs", "Backend", ["restful", "rest api", "rest apis", "re:\\brest\\s*(?:&|and)\\s*graphql\\s+apis?\\b"]),
    ("Microservices", "Backend", ["microservice", "microservices"]),
    # Data & storage
    ("PostgreSQL", "Data & Storage", ["postgresql", "postgres"]),
    ("MySQL", "Data & Storage", ["mysql"]),
    ("MongoDB", "Data & Storage", ["mongodb", "mongo"]),
    ("Redis", "Data & Storage", ["redis"]),
    ("Elasticsearch", "Data & Storage", ["elasticsearch", "elastic search", "elk stack", "elk"]),
    ("Oracle", "Data & Storage", ["oracle", "oracle db", "oracle sql"]),
    ("SQLite", "Data & Storage", ["sqlite"]),
    ("Cassandra", "Data & Storage", ["cassandra"]),
    ("DynamoDB", "Data & Storage", ["dynamodb"]),
    ("Snowflake", "Data & Storage", ["snowflake"]),
    ("Vector Databases", "Data & Storage", ["vector database", "vector databases", "vector db", "vector search"]),
    ("Pinecone", "Data & Storage", ["pinecone"]),
    ("Weaviate", "Data & Storage", ["weaviate"]),
    ("Qdrant", "Data & Storage", ["qdrant"]),
    ("pgvector", "Data & Storage", ["pgvector"]),
    # Messaging, queues & data engineering
    ("Celery", "Messaging & Pipelines", ["celery"]),
    ("RabbitMQ", "Messaging & Pipelines", ["rabbitmq"]),
    ("Kafka", "Messaging & Pipelines", ["kafka", "apache kafka"]),
    ("RQ", "Messaging & Pipelines", ["re:\\brq\\b"]),
    ("Task Queues", "Messaging & Pipelines", ["task queue", "task queues"]),
    ("Airflow", "Messaging & Pipelines", ["airflow", "apache airflow"]),
    ("Spark", "Messaging & Pipelines", ["pyspark", "apache spark", "spark"]),
    ("ETL", "Messaging & Pipelines", ["etl", "elt"]),
    ("Data Pipelines", "Messaging & Pipelines", ["data pipeline", "data pipelines", "data processing pipelines", "etl pipeline"]),
    ("Data Warehousing", "Messaging & Pipelines", ["data warehouse", "data warehousing", "redshift"]),
    # Cloud & DevOps
    ("AWS", "Cloud & DevOps", ["aws", "amazon web services", "ec2", "s3", "rds", "ecs", "eks", "lambda", "sagemaker", "redshift"]),
    ("GCP", "Cloud & DevOps", ["gcp", "google cloud"]),
    ("Azure", "Cloud & DevOps", ["azure"]),
    ("Docker", "Cloud & DevOps", ["docker", "containerization", "containerized", "containers"]),
    ("Kubernetes", "Cloud & DevOps", ["kubernetes", "k8s", "eks", "gke", "aks"]),
    ("Terraform", "Cloud & DevOps", ["terraform"]),
    ("Ansible", "Cloud & DevOps", ["ansible"]),
    ("Jenkins", "Cloud & DevOps", ["jenkins"]),
    ("GitHub Actions", "Cloud & DevOps", ["github actions"]),
    ("CI/CD", "Cloud & DevOps", ["ci/cd", "ci / cd", "ci-cd", "continuous integration", "continuous delivery"]),
    ("Git", "Cloud & DevOps", ["git", "gitlab", "bitbucket"]),
    ("Helm", "Cloud & DevOps", ["helm"]),
    ("ArgoCD", "Cloud & DevOps", ["argocd", "argo cd"]),
    ("Linux", "Cloud & DevOps", ["linux", "unix"]),
    ("Nginx", "Cloud & DevOps", ["nginx"]),
    # Observability
    ("Prometheus", "Observability", ["prometheus"]),
    ("Grafana", "Observability", ["grafana"]),
    ("OpenTelemetry", "Observability", ["opentelemetry", "open telemetry"]),
    ("Datadog", "Observability", ["datadog"]),
    # AI & ML
    ("Machine Learning", "AI & ML", ["machine learning", "ml models", "ml engineer", "ml inference"]),
    ("Deep Learning", "AI & ML", ["deep learning", "neural networks"]),
    ("NLP", "AI & ML", ["nlp", "natural language processing", "entity extraction"]),
    ("LLMs", "AI & ML", ["llm", "llms", "large language model", "large language models"]),
    ("RAG", "AI & ML", ["rag", "retrieval augmented generation", "retrieval-augmented generation"]),
    ("LangChain", "AI & ML", ["langchain"]),
    ("LlamaIndex", "AI & ML", ["llamaindex", "llama index"]),
    ("PyTorch", "AI & ML", ["pytorch"]),
    ("TensorFlow", "AI & ML", ["tensorflow", "keras"]),
    ("Hugging Face", "AI & ML", ["hugging face", "huggingface", "transformers"]),
    ("OpenAI API", "AI & ML", ["openai", "gpt-4", "gpt-4o", "gpt 4"]),
    ("Groq", "AI & ML", ["groq"]),
    ("LLaMA", "AI & ML", ["llama", "llama-3", "llama 3", "llama-2"]),
    ("Embeddings", "AI & ML", ["embedding", "embeddings"]),
    ("Prompt Engineering", "AI & ML", ["prompt engineering", "prompt optimization", "prompt guardrails", "prompt design"]),
    ("Scikit-learn", "AI & ML", ["scikit-learn", "sklearn"]),
    ("Pandas", "AI & ML", ["pandas"]),
    ("NumPy", "AI & ML", ["numpy"]),
    ("OCR", "AI & ML", ["ocr"]),
    ("MLOps", "AI & ML", ["mlops", "model serving", "model deployment"]),
    ("Evaluation & Benchmarks", "AI & ML", ["evaluation metrics", "evaluation benchmarks", "statistical evaluation", "model evaluation"]),
    # Frontend
    ("React", "Frontend", ["react", "react.js", "reactjs"]),
    ("Next.js", "Frontend", ["next.js", "nextjs"]),
    ("Redux", "Frontend", ["redux"]),
    ("Zustand", "Frontend", ["zustand"]),
    ("Tailwind CSS", "Frontend", ["tailwind", "tailwind css"]),
    ("HTML", "Frontend", ["html", "html5"]),
    ("CSS", "Frontend", ["css", "css3"]),
    ("Vue", "Frontend", ["vue", "vue.js", "vuejs"]),
    ("Angular", "Frontend", ["angular"]),
    ("Webpack", "Frontend", ["webpack", "vite"]),
    # Testing & quality
    ("PyTest", "Testing & Quality", ["pytest"]),
    ("Jest", "Testing & Quality", ["jest"]),
    ("JUnit", "Testing & Quality", ["junit"]),
    ("Unit Testing", "Testing & Quality", ["unit test", "unit tests", "unit testing", "integration testing", "automated testing"]),
    ("Postman", "Testing & Quality", ["postman"]),
    ("Selenium", "Testing & Quality", ["selenium", "cypress", "playwright"]),
    ("Code Review", "Testing & Quality", ["code review", "code reviews", "clean code"]),
    # Architecture & practice
    ("System Design", "Architecture", ["system design", "system architecture", "architectural standards"]),
    ("Distributed Systems", "Architecture", ["distributed system", "distributed systems", "distributed backend", "distributed data"]),
    ("Caching", "Architecture", ["caching", "cache"]),
    ("Rate Limiting", "Architecture", ["rate limiting", "rate limiter"]),
    ("Event-Driven Architecture", "Architecture", ["event-driven", "event driven", "event pipelines"]),
    ("High Concurrency", "Architecture", ["high-concurrency", "high concurrency", "high-throughput", "high throughput"]),
    ("JWT / OAuth", "Architecture", ["jwt", "oauth", "oauth2"]),
    # HR domain
    ("ATS", "HR Domain", ["ats", "applicant tracking"]),
    ("Payroll", "HR Domain", ["payroll"]),
    ("HRMS", "HR Domain", ["hrms", "hris", "hr tech"]),
    ("Talent Acquisition", "HR Domain", ["talent acquisition", "full-cycle recruitment", "recruitment"]),
    ("Employee Onboarding", "HR Domain", ["employee onboarding", "onboarding"]),
]

CATEGORY_ORDER = [
    "Languages", "Backend", "Data & Storage", "Messaging & Pipelines", "Cloud & DevOps",
    "Observability", "AI & ML", "Frontend", "Testing & Quality", "Architecture", "HR Domain",
]

SKILL_CATEGORY: Dict[str, str] = {name: cat for name, cat, _ in SKILLS}
_CANONICAL_LOOKUP: Dict[str, str] = {}
for _name, _cat, _aliases in SKILLS:
    _CANONICAL_LOOKUP[_name.lower()] = _name
    for _alias in _aliases:
        if not _alias.startswith("re:"):
            _CANONICAL_LOOKUP.setdefault(_alias.lower(), _name)


def _alias_pattern(alias: str) -> str:
    if alias.startswith("re:"):
        return alias[3:]
    escaped = re.escape(alias.lower()).replace("\\ ", " ").replace(" ", r"\s+")
    return rf"(?<![a-z0-9]){escaped}(?![a-z0-9+#])"


@lru_cache(maxsize=1)
def compiled_skills() -> List[Tuple[str, str, Pattern[str]]]:
    compiled = []
    for name, category, aliases in SKILLS:
        pattern = "|".join(_alias_pattern(a) for a in aliases)
        compiled.append((name, category, re.compile(pattern, re.IGNORECASE)))
    return compiled


_URL_RE = re.compile(r"(?:https?://)?(?:www\.)?[a-z0-9-]+\.(?:com|in|io|dev|me|org|net|ai)(?:/[^\s|,]*)?", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def strip_links(text: str) -> str:
    """Removes emails and URLs so 'github.com/x' never counts as the Git skill."""
    return _URL_RE.sub(" ", _EMAIL_RE.sub(" ", text))


def find_skills(text: str) -> List[str]:
    """Returns canonical skills mentioned in text, in taxonomy order."""
    clean = strip_links(text).lower()
    return [name for name, _cat, pattern in compiled_skills() if pattern.search(clean)]


def find_skill_spans(text: str) -> List[Tuple[int, str]]:
    """Returns (position, canonical) for every skill mention, sorted by position."""
    clean = text.lower()
    spans: List[Tuple[int, str]] = []
    for name, _cat, pattern in compiled_skills():
        for match in pattern.finditer(clean):
            spans.append((match.start(), name))
    spans.sort()
    return spans


def canonicalize(label: str) -> str:
    """Maps a user-typed skill label to its canonical name when we know it."""
    key = label.strip().lower()
    if key in _CANONICAL_LOOKUP:
        return _CANONICAL_LOOKUP[key]
    found = find_skills(label)
    if len(found) == 1:
        return found[0]
    return label.strip()


def group_by_category(skills: Iterable[str]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for skill in skills:
        grouped.setdefault(SKILL_CATEGORY.get(skill, "Other"), []).append(skill)
    ordered = {cat: grouped[cat] for cat in CATEGORY_ORDER if cat in grouped}
    if "Other" in grouped:
        ordered["Other"] = grouped["Other"]
    return ordered
