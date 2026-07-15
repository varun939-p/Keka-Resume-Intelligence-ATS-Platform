import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

RESUME_DATA = [
    {
        "filename": "resume_1_arjun_verma_sr_python.pdf",
        "name": "Arjun Verma",
        "contact": "Hyderabad, Telangana | arjun.verma.py@gmail.com | +91-9876543210 | linkedin.com/in/arjunverma-py",
        "title": "Senior Python Backend Engineer",
        "summary": "Passionate and results-driven Senior Python Engineer with 6+ years of experience architecting high-throughput distributed backend services, asynchronous pipelines, and RESTful APIs. Specialized in FastAPI, Django, Celery, and PostgreSQL with a proven track record of processing millions of daily transactions in HR Tech and enterprise automation.",
        "skills": "Python (AsyncIO, Typing), FastAPI, Django REST Framework, Celery, RabbitMQ, Redis, PostgreSQL, SQLAlchemy, Docker, Kubernetes, AWS (EC2, S3, RDS), Git, PyTest, Microservices Architecture, ATS & Payroll Data Pipelines.",
        "experience": [
            ("Lead Python Developer | TechFlow Systems, Hyderabad", "2022 - Present",
             "- Architected and deployed high-concurrency FastAPI microservices handling 5M+ daily API requests with <30ms average latency.\n"
             "- Designed asynchronous Celery task pipelines with Redis broker for real-time employee attendance and payroll calculations.\n"
             "- Reduced PostgreSQL query execution time by 62% through optimized indexing, table partitioning, and connection pooling.\n"
             "- Mentored a team of 6 backend developers and established strict code review and PyTest CI/CD standards."),
            ("Senior Backend Engineer | CloudScale HR Solutions, Hyderabad", "2019 - 2022",
             "- Built core Applicant Tracking System (ATS) backend modules using Django and PostgreSQL.\n"
             "- Integrated multi-format resume parsing and candidate ranking pipelines processing 10,000+ monthly applications.\n"
             "- Deployed containerized services on AWS ECS using Docker and Terraform with automated Prometheus observability.")
        ],
        "education": "B.Tech in Computer Science & Engineering | IIT Hyderabad (2015 - 2019) | GPA: 8.8/10"
    },
    {
        "filename": "resume_2_priya_sharma_data_eng.pdf",
        "name": "Priya Sharma",
        "contact": "Hyderabad, Telangana | priya.sharma.data@gmail.com | +91-9812345678 | github.com/priyasharma-data",
        "title": "Senior Data & Backend Automation Engineer",
        "summary": "Data-oriented Backend Engineer with 5 years of experience in Python automation, ETL pipeline architecture, and high-volume data handling. Expert in building scalable data processing engines with Airflow, Celery, FastAPI, and complex SQL databases.",
        "skills": "Python, FastAPI, Apache Airflow, Celery, Pandas, PySpark, PostgreSQL, MongoDB, Redis, Apache Kafka, Docker, AWS S3/Redshift, CI/CD Automation, Data Warehousing, High Throughput Pipelines.",
        "experience": [
            ("Senior Data Platform Engineer | NexaCorp India, Hyderabad", "2021 - Present",
             "- Engineered fault-tolerant distributed data pipelines using Python and Celery processing over 20M daily user log events.\n"
             "- Built internal automation APIs using FastAPI to feed cleaned data directly into analytics and machine learning models.\n"
             "- Managed high-performance PostgreSQL clusters and implemented automated data deduplication and validation crons."),
            ("Python Backend Developer | FinTrack Analytics, Hyderabad", "2019 - 2021",
             "- Developed automated backend services using Python and Flask for financial transaction processing.\n"
             "- Designed automated reporting tools and integrated third-party REST APIs with robust retry mechanisms.")
        ],
        "education": "B.E. in Information Technology | Osmania University, Hyderabad (2015 - 2019) | Distinction"
    },
    {
        "filename": "resume_3_arjun_verma_duplicate.pdf",
        "name": "Arjun Verma",
        "contact": "Hyderabad, India | arjun.verma.py@gmail.com | +91 9876543210 | linkedin.com/in/arjunverma-py",
        "title": "Senior Python Backend Architect & Developer",
        "summary": "Passionate and results-driven Senior Python Engineer with 6+ years of experience architecting high-throughput distributed backend services, asynchronous pipelines, and RESTful APIs. Specialized in FastAPI, Django, Celery, and PostgreSQL with a proven track record of processing millions of daily transactions in HR Tech and enterprise automation.",
        "skills": "Python (AsyncIO), FastAPI, Django REST Framework, Celery, RabbitMQ, Redis, PostgreSQL, SQLAlchemy, Docker, Kubernetes, AWS, PyTest, Microservices.",
        "experience": [
            ("Lead Python Developer | TechFlow Systems (Hyderabad)", "2022 - Current",
             "- Architected and deployed high-concurrency FastAPI microservices handling 5M+ daily API requests with <30ms average latency.\n"
             "- Designed asynchronous Celery task pipelines with Redis broker for real-time employee attendance and payroll calculations.\n"
             "- Reduced PostgreSQL query execution time by 62% through optimized indexing, table partitioning, and connection pooling."),
            ("Senior Backend Engineer | CloudScale HR Solutions (Hyderabad)", "2019 - 2022",
             "- Built core Applicant Tracking System (ATS) backend modules using Django and PostgreSQL.\n"
             "- Integrated multi-format resume parsing and candidate ranking pipelines processing 10,000+ monthly applications.")
        ],
        "education": "Bachelor of Technology in Computer Science | IIT Hyderabad (2015 - 2019)"
    },
    {
        "filename": "resume_4_rahul_gupta_java_legacy.pdf",
        "name": "Rahul Gupta",
        "contact": "Bangalore, Karnataka | rahul.gupta.java@yahoo.com | +91-9700112233",
        "title": "Senior Java SpringBoot Engineer",
        "summary": "Accomplished Enterprise Java Developer with 7 years of experience specializing in Java 11/17, Spring Boot, Hibernate, and Oracle SQL. Experienced in banking and retail domain monoliths and microservices.",
        "skills": "Java 17, Spring Boot, Spring Security, Hibernate ORM, Oracle DB, MySQL, Apache Tomcat, SOAP, XML, JUnit, Maven, Jenkins, Monolithic Architectures.",
        "experience": [
            ("Lead Java Specialist | Global Tech Systems, Bangalore", "2020 - Present",
             "- Developed enterprise banking microservices using Java Spring Boot and Hibernate ORM.\n"
             "- Maintained legacy SOAP web services and migrated SQL queries on Oracle 19c database.\n"
             "- Coordinated with QA teams to execute integration testing and Jenkins deployment pipelines."),
            ("Java Developer | Enterprise Solutions Ltd, Pune", "2017 - 2020",
             "- Implemented business logic layers in Java 8 using Spring MVC and JSP for e-commerce portals.\n"
             "- Wrote stored procedures and triggers in MySQL for order tracking modules.")
        ],
        "education": "B.Tech in Electronics & Communication | VIT Vellore (2013 - 2017)"
    },
    {
        "filename": "resume_5_sneha_reddy_jr_backend.pdf",
        "name": "Sneha Reddy",
        "contact": "Hyderabad, Telangana | sneha.reddy.dev@gmail.com | +91-9988776655",
        "title": "Junior Python Developer",
        "summary": "Enthusiastic Junior Software Engineer with 1.5 years of hands-on experience in Python, Django, and REST API development. Quick learner passionate about automation, clean coding, and learning high-scale backend architectures.",
        "skills": "Python, Django, Flask, SQLite, PostgreSQL (Basic), HTML/CSS, Git, Postman, Linux Command Line, Basic Docker.",
        "experience": [
            ("Junior Python Developer | StartUp Hub, Hyderabad", "2023 - Present",
             "- Assisted senior engineers in building RESTful APIs using Django REST Framework for customer management modules.\n"
             "- Wrote Python scripts to automate daily data backups and generate CSV reports for accounting teams.\n"
             "- Fixed bugs in frontend-backend integration using Postman and PyTest unit tests.")
        ],
        "education": "B.Tech in Computer Science | JNTU Hyderabad (2019 - 2023) | GPA: 8.5/10"
    },
    {
        "filename": "resume_6_vikram_singh_devops.pdf",
        "name": "Vikram Singh",
        "contact": "Hyderabad, Telangana | vikram.singh.devops@outlook.com | +91-9445566778",
        "title": "Senior DevOps & Cloud Infrastructure Engineer",
        "summary": "DevOps Specialist with 6 years of experience managing high-availability AWS cloud infrastructure, Kubernetes clusters, and automated CI/CD pipelines. Strong proficiency in Python automation scripting and Infrastructure as Code.",
        "skills": "AWS (EKS, EC2, VPC, IAM, Route53), Kubernetes, Docker, Terraform, Ansible, Python Scripting, Bash, Jenkins, GitHub Actions, Prometheus, Grafana, ArgoCD.",
        "experience": [
            ("Cloud DevOps Lead | InfraStack Technologies, Hyderabad", "2021 - Present",
             "- Designed and provisioned multi-region AWS cloud architectures using Terraform and Ansible for 50+ microservices.\n"
             "- Managed production Kubernetes (EKS) clusters handling 20,000 requests/sec with automated horizontal pod autoscaling.\n"
             "- Wrote Python and Bash automation scripts to detect and clean up orphaned cloud resources, saving $4,000/month."),
            ("DevOps Engineer | CloudNine Solutions, Hyderabad", "2018 - 2021",
             "- Maintained Jenkins CI/CD pipelines for Python and Node.js applications with automated security scanning.\n"
             "- Implemented centralized logging and alerting using ELK Stack and Prometheus.")
        ],
        "education": "B.E. in Computer Science | Andhra University (2014 - 2018)"
    },
    {
        "filename": "resume_7_kavya_nair_hr_analyst.pdf",
        "name": "Kavya Nair",
        "contact": "Hyderabad, Telangana | kavya.nair.hr@gmail.com | +91-9112233445",
        "title": "Senior HR Operations & ATS Specialist",
        "summary": "Dedicated Human Resources and Talent Acquisition professional with 4+ years of experience managing full-cycle recruitment, employee onboarding, and HRMS platform administration. Deep expertise in optimizing ATS workflows.",
        "skills": "Talent Acquisition, ATS Management (Keka, Greenhouse, Lever), Employee Onboarding, Payroll Coordination, HR Operations, Excel/Google Sheets Pivot Tables, Stakeholder Management.",
        "experience": [
            ("Talent Acquisition Specialist | PeopleFirst HR, Hyderabad", "2021 - Present",
             "- Screened and interviewed 1,000+ engineering and product candidates annually, maintaining a 25% hire-to-offer ratio.\n"
             "- Administered Keka HRMS platform for attendance tracking, leave policies, and employee document verification.\n"
             "- Collaborated with engineering hiring managers to draft job descriptions and optimize sourcing channels."),
            ("HR Coordinator | TalentSource India, Hyderabad", "2020 - 2021",
             "- Coordinated interview scheduling and candidate feedback loops across 5 regional offices.\n"
             "- Prepared weekly recruitment analytics reports using Excel and Google Sheets.")
        ],
        "education": "MBA in Human Resource Management | ICFAI University, Hyderabad (2018 - 2020)"
    },
    {
        "filename": "resume_8_rohit_kumar_fullstack.pdf",
        "name": "Rohit Kumar",
        "contact": "Hyderabad, Telangana | rohit.kumar.fs@gmail.com | +91-9667788990 | github.com/rohitkumar-dev",
        "title": "Full Stack Engineer (Python + React)",
        "summary": "Versatile Full Stack Software Engineer with 4 years of experience delivering high-impact SaaS web applications. Expert at pairing modern React frontend interfaces with high-speed Python/FastAPI backend architectures.",
        "skills": "Python, FastAPI, Django, React.js, TypeScript, Next.js, Redux, Tailwind CSS, PostgreSQL, Docker, Git, REST & GraphQL APIs, Jest, PyTest.",
        "experience": [
            ("Full Stack Engineer | WebPulse Tech, Hyderabad", "2022 - Present",
             "- Built intuitive customer-facing dashboards using React, TypeScript, and Tailwind CSS serving 100k+ active users.\n"
             "- Developed high-speed RESTful backend microservices using Python FastAPI and PostgreSQL with JWT authentication.\n"
             "- Reduced initial frontend page load times by 45% through code splitting and efficient backend response payloads."),
            ("Software Engineer | AgileDev Solutions, Hyderabad", "2020 - 2022",
             "- Built end-to-end features for internal CRM software using Python Django and React.\n"
             "- Designed relational SQL schemas and implemented automated data validation testing.")
        ],
        "education": "B.Tech in Information Technology | NIT Warangal (2016 - 2020)"
    },
    {
        "filename": "resume_9_rohit_kumar_duplicate.pdf",
        "name": "Rohit Kumar",
        "contact": "Hyderabad, India - rohit.kumar.fs@gmail.com - 9667788990 - github.com/rohitkumar-dev",
        "title": "Senior Full Stack Python/React Developer",
        "summary": "Versatile Full Stack Software Engineer with 4+ years of experience delivering high-impact SaaS web applications. Expert at pairing modern React frontend interfaces with high-speed Python/FastAPI backend architectures.",
        "skills": "Python, FastAPI, Django, React.js, TypeScript, Next.js, Redux, Tailwind CSS, PostgreSQL, Docker, Git, REST & GraphQL APIs.",
        "experience": [
            ("Full Stack Engineer | WebPulse Tech (Hyderabad)", "2022 to Present",
             "- Built intuitive customer-facing dashboards using React, TypeScript, and Tailwind CSS serving 100k+ active users.\n"
             "- Developed high-speed RESTful backend microservices using Python FastAPI and PostgreSQL with JWT authentication.\n"
             "- Reduced initial frontend page load times by 45% through code splitting and efficient backend response payloads."),
            ("Software Engineer | AgileDev Solutions (Hyderabad)", "2020 to 2022",
             "- Built end-to-end features for internal CRM software using Python Django and React.\n"
             "- Designed relational SQL schemas and implemented automated data validation testing.")
        ],
        "education": "Bachelor of Technology in IT | NIT Warangal (2016 - 2020)"
    },
    {
        "filename": "resume_10_ananya_deshmukh_ml_eng.pdf",
        "name": "Ananya Deshmukh",
        "contact": "Hyderabad, Telangana | ananya.deshmukh.ml@gmail.com | +91-9332211009 | github.com/ananyaml",
        "title": "Lead AI / ML Engineer (LLMs & RAG)",
        "summary": "Applied Artificial Intelligence and Machine Learning Engineer with 4+ years of experience building and deploying production-grade LLM applications, RAG pipelines, and semantic document understanding systems. Deep expertise in Groq LLaMA, OpenAI APIs, LangChain, and Python vector search engines.",
        "skills": "Python, PyTorch, LangChain, LlamaIndex, Groq API (LLaMA 3), OpenAI GPT-4, Vector Databases (Weaviate, pgvector, Pinecone), FastAPI, Document OCR/Parsing, NLP Semantic Search, Docker, AWS Sagemaker.",
        "experience": [
            ("Applied AI Lead Engineer | CognitiveAI India, Hyderabad", "2022 - Present",
             "- Architected and deployed production RAG document analysis pipelines using Python, FastAPI, and Groq LLaMA-3 models.\n"
             "- Built multi-format document parser (PDF, DOCX) with intelligent layout detection and semantic vector embeddings.\n"
             "- Optimized LLM prompt guardrails and evaluation metrics, improving automated scoring accuracy by 38% over baseline keyword matching.\n"
             "- Collaborated with product engineers to serve AI endpoints with sub-500ms response times under heavy load."),
            ("Machine Learning Engineer | DataSense Systems, Hyderabad", "2020 - 2022",
             "- Developed NLP classification and entity extraction models using PyTorch and HuggingFace transformers.\n"
             "- Deployed ML inference services in Docker containers on AWS ECS with asynchronous task queues.")
        ],
        "education": "M.Tech in Artificial Intelligence & ML | IIIT Hyderabad (2018 - 2020)"
    }
]

def generate_pdf(data, output_dir="./sample_resumes"):
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, data["filename"])
    doc = SimpleDocTemplate(filepath, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('NameTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#1e3a8a'), alignment=TA_CENTER)
    contact_style = ParagraphStyle('ContactInfo', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14, textColor=colors.HexColor('#475569'), alignment=TA_CENTER)
    role_style = ParagraphStyle('RoleTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=12, leading=16, textColor=colors.HexColor('#0284c7'), alignment=TA_CENTER)
    header_style = ParagraphStyle('SectionHeader', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=13, leading=17, textColor=colors.HexColor('#0f172a'), spaceBefore=12, spaceAfter=4)
    body_style = ParagraphStyle('BodyTextCustom', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14, textColor=colors.HexColor('#334155'))
    bullet_style = ParagraphStyle('BulletTextCustom', parent=styles['Normal'], fontName='Helvetica', fontSize=9.5, leading=13.5, textColor=colors.HexColor('#334155'), leftIndent=15)
    job_header_style = ParagraphStyle('JobHeaderCustom', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10.5, leading=14.5, textColor=colors.HexColor('#1e293b'))
    
    story = []
    story.append(Paragraph(data["name"], title_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(data["contact"], contact_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(data["title"], role_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#cbd5e1'), spaceBefore=1, spaceAfter=8))
    
    # Professional Summary
    story.append(Paragraph("PROFESSIONAL SUMMARY", header_style))
    story.append(Paragraph(data["summary"], body_style))
    story.append(Spacer(1, 8))
    
    # Technical Skills
    story.append(Paragraph("TECHNICAL SKILLS", header_style))
    story.append(Paragraph(data["skills"], body_style))
    story.append(Spacer(1, 8))
    
    # Professional Experience
    story.append(Paragraph("PROFESSIONAL EXPERIENCE", header_style))
    for job_title_date, period, bullets in data["experience"]:
        story.append(Paragraph(f"<b>{job_title_date}</b> ({period})", job_header_style))
        for line in bullets.split("\n"):
            story.append(Paragraph(line, bullet_style))
        story.append(Spacer(1, 6))
        
    # Education
    story.append(Paragraph("EDUCATION & CERTIFICATIONS", header_style))
    story.append(Paragraph(data["education"], body_style))
    
    doc.build(story)
    print(f"Generated: {filepath}")

if __name__ == "__main__":
    for resume in RESUME_DATA:
        generate_pdf(resume)
