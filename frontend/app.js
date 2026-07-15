/* ==============================================================================
   KEKA RESUME INTELLIGENCE POC - CLIENT LOGIC & BULK SCANNER
   Handles Live FastAPI REST requests and Standalone Preview simulation for 1,000 resumes
   ============================================================================== */

const MOCK_CANDIDATES = {
    "resume_1_arjun_verma_sr_python.pdf": {
        name: "Arjun Verma", email: "arjun.verma.py@gmail.com", phone: "+919876543210", location: "Hyderabad, India", is_hyderabad_based: true, total_years_experience: 6.0,
        score: 100, rec: "Strong Hire / Immediate Interview", tech: 35, exp: 30, edu: 15, keka: 20,
        strengths: ["Located in Hyderabad (Hyderabad, India), perfectly aligned with Keka's hybrid engineering team.", "Direct HR Tech / ATS / Payroll domain expertise (Ats, Payroll, Attendance).", "Strong demonstrated background in asynchronous data pipelines and automation engineering.", "Solid Python backend stack mastery (Python, Fastapi, Django)."],
        gaps: ["Minor gap: Can evaluate system design depth during technical rounds."], rationale: "Arjun Verma achieved an overall fit score of 100/100 against Keka's requirements. The candidate brings 6.0 years of experience with strong ratings in technical skills (35/35) and cultural/domain fit (20/20).",
        dedup: { is_duplicate: false, duplicate_type: "None", message: "Unique candidate profile validated." }
    },
    "resume_2_priya_sharma_data_eng.pdf": {
        name: "Priya Sharma", email: "priya.sharma.data@gmail.com", phone: "+919812345678", location: "Hyderabad, India", is_hyderabad_based: true, total_years_experience: 5.0,
        score: 94, rec: "Strong Hire / Immediate Interview", tech: 33, exp: 26, edu: 15, keka: 20,
        strengths: ["Located in Hyderabad, perfectly aligned with Keka's hybrid engineering team.", "Deep expertise in Apache Airflow, Celery, and distributed data pipelines processing 20M+ logs.", "Advanced PostgreSQL query optimization and automated data cleaning crons."],
        gaps: ["Primary background is Data Platform engineering rather than pure ATS application development."], rationale: "Priya Sharma scored 94/100. Excellent fit for Keka's high-throughput data processing and automation backend teams.",
        dedup: { is_duplicate: false, duplicate_type: "None", message: "Unique candidate profile validated." }
    },
    "resume_3_arjun_verma_duplicate.pdf": {
        name: "Arjun Verma (Reformatted CV)", email: "arjun.verma.py@gmail.com", phone: "+919876543210", location: "Hyderabad, India", is_hyderabad_based: true, total_years_experience: 6.0,
        score: 100, rec: "Strong Hire / Immediate Interview", tech: 35, exp: 30, edu: 15, keka: 20,
        strengths: ["Identical skills profile to Arjun Verma (Resume 1).", "FastAPI, Celery, PostgreSQL, and ATS domain expertise."],
        gaps: ["Candidate submitted duplicate profile under slightly different layout."], rationale: "Arjun Verma achieved 100/100. Flagged by Keka Deduplication Engine as a semantic profile match.",
        dedup: { is_duplicate: true, duplicate_type: "Semantic Profile Match (Identical Email/Phone)", message: "Candidate profile already exists in ATS via 'resume_1_arjun_verma_sr_python.pdf'. Email/Phone match." }
    },
    "resume_4_rahul_gupta_java_legacy.pdf": {
        name: "Rahul Gupta", email: "rahul.gupta.java@yahoo.com", phone: "+919700112233", location: "Bangalore, India", is_hyderabad_based: false, total_years_experience: 7.0,
        score: 47, rec: "Reject / Low Fit", tech: 8, exp: 14, edu: 15, keka: 10,
        strengths: ["7 years of professional software development experience.", "Strong enterprise banking domain foundation."],
        gaps: ["Located outside Hyderabad (Bangalore). May require relocation.", "Primary experience is in Java/Oracle monolithic stack rather than Python backend ecosystems required by Keka."], rationale: "Rahul Gupta scored 47/100. Low fit due to lack of Python/FastAPI skills and non-Hyderabad location.",
        dedup: { is_duplicate: false, duplicate_type: "None", message: "Unique candidate profile validated." }
    },
    "resume_5_sneha_reddy_jr_backend.pdf": {
        name: "Sneha Reddy", email: "sneha.reddy.dev@gmail.com", phone: "+919988776655", location: "Hyderabad, India", is_hyderabad_based: true, total_years_experience: 1.5,
        score: 68, rec: "Interview / Good Fit", tech: 24, exp: 16, edu: 13, keka: 15,
        strengths: ["Located in Hyderabad, India.", "Hands-on experience with Python, Django REST Framework, and automated reporting scripts.", "High GPA (8.5/10) from JNTU Hyderabad."],
        gaps: ["Only 1.5 years of experience (JD requires 4+ years for Senior role).", "Needs mentoring on large-scale distributed task queues (Celery/Kafka)."], rationale: "Sneha Reddy scored 68/100. Strong junior candidate suitable for mid-level Python pipeline development.",
        dedup: { is_duplicate: false, duplicate_type: "None", message: "Unique candidate profile validated." }
    },
    "resume_6_vikram_singh_devops.pdf": {
        name: "Vikram Singh", email: "vikram.singh.devops@outlook.com", phone: "+919445566778", location: "Hyderabad, India", is_hyderabad_based: true, total_years_experience: 6.0,
        score: 76, rec: "Interview / Good Fit", tech: 26, exp: 26, edu: 11, keka: 13,
        strengths: ["6 years of DevOps experience managing Kubernetes (EKS) clusters handling 20,000 req/sec.", "Expertise in Python automation scripts and Terraform IaC.", "Located in Hyderabad."],
        gaps: ["Specialized in infrastructure/cloud rather than application backend architecture.", "Limited direct exposure to HR tech or ATS application development."], rationale: "Vikram Singh scored 76/100. Excellent candidate for Keka DevOps & Infrastructure automation teams.",
        dedup: { is_duplicate: false, duplicate_type: "None", message: "Unique candidate profile validated." }
    },
    "resume_7_kavya_nair_hr_analyst.pdf": {
        name: "Kavya Nair", email: "kavya.nair.hr@gmail.com", phone: "+919112233445", location: "Hyderabad, India", is_hyderabad_based: true, total_years_experience: 4.0,
        score: 34, rec: "Reject / Low Fit", tech: 4, exp: 12, edu: 8, keka: 10,
        strengths: ["Deep understanding of ATS platform management (Keka, Greenhouse).", "Located in Hyderabad with strong talent acquisition background."],
        gaps: ["Non-engineering background (MBA in HR).", "Zero coding or Python backend engineering experience."], rationale: "Kavya Nair scored 34/100. Strong candidate for Keka HR Operations, but not applicable for Senior Python Backend Engineer.",
        dedup: { is_duplicate: false, duplicate_type: "None", message: "Unique candidate profile validated." }
    },
    "resume_8_rohit_kumar_fullstack.pdf": {
        name: "Rohit Kumar", email: "rohit.kumar.fs@gmail.com", phone: "+919667788990", location: "Hyderabad, India", is_hyderabad_based: true, total_years_experience: 4.0,
        score: 91, rec: "Strong Hire / Immediate Interview", tech: 32, exp: 26, edu: 15, keka: 18,
        strengths: ["Located in Hyderabad, India.", "Mastery of Python FastAPI microservices + modern React/TypeScript frontend interfaces.", "Proven track record reducing initial page loads by 45% for 100k+ users."],
        gaps: ["Can evaluate deep database partitioning knowledge in technical round."], rationale: "Rohit Kumar scored 91/100. Outstanding fit for Keka Full Stack and Core Portal engineering.",
        dedup: { is_duplicate: false, duplicate_type: "None", message: "Unique candidate profile validated." }
    },
    "resume_9_rohit_kumar_duplicate.pdf": {
        name: "Rohit Kumar (Duplicate Layout)", email: "rohit.kumar.fs@gmail.com", phone: "+919667788990", location: "Hyderabad, India", is_hyderabad_based: true, total_years_experience: 4.0,
        score: 91, rec: "Strong Hire / Immediate Interview", tech: 32, exp: 26, edu: 15, keka: 18,
        strengths: ["Full Stack Python + React skills matching Rohit Kumar (Resume 8)."],
        gaps: ["Candidate submitted duplicate profile across different recruitment channel."], rationale: "Rohit Kumar achieved 91/100. Flagged by Keka Deduplication Engine due to high fuzzy content similarity.",
        dedup: { is_duplicate: true, duplicate_type: "High Fuzzy Content Similarity (89.2% match)", message: "Resume content is 89.2% identical to existing candidate 'Rohit Kumar' (resume_8_rohit_kumar_fullstack.pdf)." }
    },
    "resume_10_ananya_deshmukh_ml_eng.pdf": {
        name: "Ananya Deshmukh", email: "ananya.deshmukh.ml@gmail.com", phone: "+919332211009", location: "Hyderabad, India", is_hyderabad_based: true, total_years_experience: 4.0,
        score: 95, rec: "Strong Hire / Immediate Interview", tech: 35, exp: 26, edu: 15, keka: 19,
        strengths: ["Located in Hyderabad, India.", "Architected and deployed production RAG document analysis pipelines using Python, FastAPI, and Groq LLaMA models.", "Built multi-format document parser improving ATS scoring accuracy by 38% over baseline keyword matching."],
        gaps: ["Primary focus is Applied AI / NLP rather than standard payroll/attendance crons."], rationale: "Ananya Deshmukh scored 95/100. Exceptional fit to lead Keka's Applied AI and ATS Resume Intelligence feature team.",
        dedup: { is_duplicate: false, duplicate_type: "None", message: "Unique candidate profile validated." }
    }
};

let isOnlineMode = false;

document.addEventListener("DOMContentLoaded", async () => {
    await detectConnectionMode();
    loadEvaluations();
});

async function detectConnectionMode() {
    const badge = document.getElementById("connectionModeBadge");
    try {
        const res = await fetch("/api/status", { method: "GET" });
        if (res.ok) {
            const data = await res.json();
            isOnlineMode = true;
            badge.className = "badge green";
            badge.innerHTML = "🟢 Mode: Live FastAPI Backend Connected";
            return;
        }
    } catch (e) {
        // Standalone preview
    }
    isOnlineMode = false;
    badge.className = "badge amber";
    badge.innerHTML = "⚡ Mode: Standalone Preview & Interactive Simulation";
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    event.currentTarget.classList.add('active');
    if(tabId === 'sheetsTab') loadEvaluations();
}

function toggleCustomJD() {
    const select = document.getElementById("jdSelect");
    const box = document.getElementById("customJDBox");
    box.style.display = (select.value === "custom") ? "block" : "none";
}

async function runSingleScorer() {
    const fileInput = document.getElementById("customFileInput");
    const resumeSelect = document.getElementById("sampleResumeSelect");
    const jdSelect = document.getElementById("jdSelect");
    const customJD = document.getElementById("customJDText").value;
    const provider = document.getElementById("llmProviderSelect").value;

    const btn = document.getElementById("singleScoreBtn");
    const spinner = document.getElementById("singleSpinner");
    btn.disabled = true;
    spinner.style.display = "inline-block";

    try {
        if (isOnlineMode) {
            let data;
            if(fileInput.files.length > 0) {
                const formData = new FormData();
                formData.append("file", fileInput.files[0]);
                formData.append("jd_filename", jdSelect.value);
                if(jdSelect.value === "custom") formData.append("custom_jd_text", customJD);
                formData.append("llm_provider", provider);

                const res = await fetch("/api/score-upload", { method: "POST", body: formData });
                data = await res.json();
            } else {
                const payload = {
                    resume_filename: resumeSelect.value,
                    jd_filename: jdSelect.value,
                    custom_jd_text: (jdSelect.value === "custom") ? customJD : null,
                    llm_provider: provider
                };
                const res = await fetch("/api/score-sample", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                data = await res.json();
            }
            renderSingleResult(data.candidate_metadata, data.score_data, data.deduplication_info, data.jd_name);
            loadEvaluations();
        } else {
            await new Promise(resolve => setTimeout(resolve, 350));
            const filename = resumeSelect.value;
            const cand = MOCK_CANDIDATES[filename] || MOCK_CANDIDATES["resume_1_arjun_verma_sr_python.pdf"];
            
            const meta = {
                name: cand.name, email: cand.email, phone: cand.phone, location: cand.location,
                is_hyderabad_based: cand.is_hyderabad_based, total_years_experience: cand.total_years_experience
            };
            const score = {
                overall_fit_score: cand.score, recommendation: cand.rec,
                category_scores: { technical_skills_score: cand.tech, relevant_experience_score: cand.exp, education_and_certifications_score: cand.edu, keka_domain_and_cultural_fit_score: cand.keka },
                key_strengths: cand.strengths, missing_skills_and_gaps: cand.gaps, summary_rationale: cand.rationale, scoring_engine: provider === 'groq' ? 'Groq LLaMA 3.3 70B (Simulation)' : 'Keka High-Precision Local Heuristic Engine'
            };
            renderSingleResult(meta, score, cand.dedup, jdSelect.options[jdSelect.selectedIndex].text);
        }
    } catch(e) {
        alert("Error scoring candidate: " + e.message);
    } finally {
        btn.disabled = false;
        spinner.style.display = "none";
    }
}

function renderSingleResult(meta, score, dedup, jdName) {
    const cat = score.category_scores || { technical_skills_score: 30, relevant_experience_score: 25, education_and_certifications_score: 15, keka_domain_and_cultural_fit_score: 18 };

    let recClass = "interview";
    if(score.overall_fit_score >= 82) recClass = "strong";
    else if(score.overall_fit_score < 52) recClass = "reject";
    else if(score.overall_fit_score < 68) recClass = "hold";

    let dedupHtml = `<div class="dedup-alert unique"><span>🟢</span><div><strong>Unique Candidate Verified:</strong> No identical or semantic duplicate found in Keka ATS registry.</div></div>`;
    if(dedup && dedup.is_duplicate) {
        const cls = dedup.duplicate_type.includes("Exact") ? "duplicate" : "semantic";
        const icon = dedup.duplicate_type.includes("Exact") ? "🔴" : "⚠️";
        dedupHtml = `<div class="dedup-alert ${cls}"><span>${icon}</span><div><strong>Duplicate Detected (${dedup.duplicate_type}):</strong> ${dedup.message}</div></div>`;
    }

    const strengthsHtml = (score.key_strengths || []).map(s => `<div class="pill strength">✓ ${s}</div>`).join("");
    const gapsHtml = (score.missing_skills_and_gaps || []).map(g => `<div class="pill gap">✕ ${g}</div>`).join("");

    const html = `
        <div class="card-header">
            <div class="card-title">👤 ${meta.name} — Intelligence Report</div>
            <div class="rec-pill ${recClass}">${score.recommendation}</div>
        </div>

        ${dedupHtml}

        <div class="score-hero">
            <div>
                <div style="font-size: 0.85rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase; margin-bottom: 0.25rem;">Overall Keka Fit Score</div>
                <div style="font-size: 1.05rem; color: #fff; font-weight: 600;">Target: ${jdName || 'Senior Python Backend Engineer'}</div>
            </div>
            <div class="score-number" style="color: ${score.overall_fit_score >= 80 ? '#34d399' : (score.overall_fit_score >= 60 ? '#60a5fa' : '#f87171')}">
                ${score.overall_fit_score}<span>/100</span>
            </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 1.5rem; background: #0f172a; padding: 1rem; border-radius: 10px; border: 1px solid var(--border-color);">
            <div>
                <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Location & Fit</div>
                <div style="font-weight: 600; font-size: 0.95rem; margin-top: 0.2rem; color: ${meta.is_hyderabad_based ? '#34d399' : '#fbbf24'};">${meta.location} ${meta.is_hyderabad_based ? '✅' : '⚠️'}</div>
            </div>
            <div>
                <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Experience</div>
                <div style="font-weight: 600; font-size: 0.95rem; margin-top: 0.2rem;">${meta.total_years_experience} Years</div>
            </div>
            <div>
                <div style="font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 700;">Scoring Engine</div>
                <div style="font-weight: 600; font-size: 0.85rem; margin-top: 0.2rem; color: #60a5fa;">${score.scoring_engine || 'Keka Intelligence'}</div>
            </div>
        </div>

        <h4 style="font-size: 0.9rem; color: var(--text-muted); text-transform: uppercase; margin-bottom: 0.75rem;">Category Score Breakdowns</h4>
        <div class="breakdown-row">
            <div class="breakdown-top"><span>Technical Skills & Python Mastery</span><span>${cat.technical_skills_score} / 35</span></div>
            <div class="bar-bg"><div class="bar-fill" style="width: ${(cat.technical_skills_score / 35) * 100}%; background: #3b82f6;"></div></div>
        </div>
        <div class="breakdown-row">
            <div class="breakdown-top"><span>Relevant Scale & Backend Experience</span><span>${cat.relevant_experience_score} / 30</span></div>
            <div class="bar-bg"><div class="bar-fill" style="width: ${(cat.relevant_experience_score / 30) * 100}%; background: #8b5cf6;"></div></div>
        </div>
        <div class="breakdown-row">
            <div class="breakdown-top"><span>Keka Domain & Hyderabad Cultural Fit</span><span>${cat.keka_domain_and_cultural_fit_score} / 20</span></div>
            <div class="bar-bg"><div class="bar-fill" style="width: ${(cat.keka_domain_and_cultural_fit_score / 20) * 100}%; background: #10b981;"></div></div>
        </div>
        <div class="breakdown-row" style="margin-bottom: 1.5rem;">
            <div class="breakdown-top"><span>Education & Certifications</span><span>${cat.education_and_certifications_score} / 15</span></div>
            <div class="bar-bg"><div class="bar-fill" style="width: ${(cat.education_and_certifications_score / 15) * 100}%; background: #f59e0b;"></div></div>
        </div>

        <h4 style="font-size: 0.9rem; color: var(--text-muted); text-transform: uppercase; margin-bottom: 0.5rem;">Key Strengths & Competencies</h4>
        <div class="pill-list" style="margin-bottom: 1.25rem;">${strengthsHtml}</div>

        <h4 style="font-size: 0.9rem; color: var(--text-muted); text-transform: uppercase; margin-bottom: 0.5rem;">Missing Skills & Gap Analysis</h4>
        <div class="pill-list" style="margin-bottom: 1.25rem;">${gapsHtml}</div>

        <div style="background: #0f172a; padding: 1rem; border-radius: 8px; border-left: 4px solid var(--accent-primary);">
            <div style="font-size: 0.75rem; color: var(--text-muted); font-weight: 700; text-transform: uppercase; margin-bottom: 0.25rem;">Executive Summary & Rationale</div>
            <div style="font-size: 0.9rem; line-height: 1.5;">${score.summary_rationale || 'Score computed successfully.'}</div>
        </div>
    `;
    document.getElementById("singleResultCard").innerHTML = html;
}

// 🚀 BULK SCANNER (1,000+ RESUMES) LOGIC
async function runBulkScan1000() {
    const btn = document.getElementById("bulkScanBtn");
    const spinner = document.getElementById("bulkSpinner");
    const terminal = document.getElementById("bulkTerminal");
    const resultsBox = document.getElementById("bulkResultsContainer");
    const countVal = parseInt(document.getElementById("bulkCountSelect").value) || 1000;
    const jdVal = document.getElementById("bulkJDSelect").value;

    btn.disabled = true;
    spinner.style.display = "inline-block";
    terminal.style.display = "block";
    resultsBox.style.display = "none";

    terminal.innerHTML = `<div>[00:00:01] ⚡ Keka Celery Worker Pool initialized. Spawning 8 asynchronous intake nodes...</div>`;
    await new Promise(resolve => setTimeout(resolve, 250));
    terminal.innerHTML += `<div>[00:00:02] 📦 Ingesting ${countVal} candidate resume files (PDF, DOCX, TXT) from intake bucket...</div>`;
    await new Promise(resolve => setTimeout(resolve, 300));
    terminal.innerHTML += `<div>[00:00:03] 🛡️ Running 3-Layer Deduplication (Exact SHA-256 + Semantic Email/Phone + Fuzzy SequenceMatcher)...</div>`;
    await new Promise(resolve => setTimeout(resolve, 350));
    terminal.innerHTML += `<div>[00:00:04] 🧠 Executing high-speed competency scoring against target job description...</div>`;

    try {
        let data;
        if (isOnlineMode) {
            const res = await fetch("/api/bulk-scan-1000", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ jd_filename: jdVal, count: countVal })
            });
            data = await res.json();
        } else {
            await new Promise(resolve => setTimeout(resolve, 600));
            data = simulateBulkScanClientSide(countVal, jdVal);
        }

        terminal.innerHTML += `<div style="color:#60a5fa; font-weight:700;">[00:00:05] ✨ SUCCESS! ${data.total_scanned} candidate resumes processed in ${data.processing_time_seconds}s. Shortlisting Top 50...</div>`;
        await new Promise(resolve => setTimeout(resolve, 400));
        
        renderBulkAnalytics(data);
        resultsBox.style.display = "block";
    } catch(e) {
        terminal.innerHTML += `<div style="color:#ef4444;">[ERROR] Bulk screening encountered exception: ${e.message}</div>`;
    } finally {
        btn.disabled = false;
        spinner.style.display = "none";
    }
}

function simulateBulkScanClientSide(totalCount, jdFilename) {
    const firstNames = ["Arjun", "Priya", "Rohit", "Ananya", "Vikram", "Sneha", "Rahul", "Kavya", "Siddharth", "Aditi", "Karan", "Neha", "Amit", "Pooja", "Suresh", "Divya", "Varun", "Meera", "Deepak", "Tanvi"];
    const lastNames = ["Verma", "Sharma", "Kumar", "Deshmukh", "Singh", "Reddy", "Gupta", "Nair", "Kulkarni", "Rao", "Malhotra", "Joshi", "Yadav", "Patel", "Menon", "Chopra", "Saxena", "Jain", "Mehta", "Iyer"];
    const locations = [["Hyderabad, India", true], ["Bangalore, India", false], ["Pune, India", false], ["Gurgaon, India", false], ["Mumbai, India", false]];
    const roles = [
        ["Senior Python Backend Engineer", ["Python", "FastAPI", "Celery", "PostgreSQL", "Docker", "AWS"], 88, "Strong Hire / Immediate Interview"],
        ["Lead Data & Backend Automation Engineer", ["Python", "Airflow", "Celery", "PostgreSQL", "Kafka"], 85, "Strong Hire / Immediate Interview"],
        ["AI / ML Lead Engineer (LLMs & RAG)", ["Python", "PyTorch", "LangChain", "Groq API", "FastAPI"], 92, "Strong Hire / Immediate Interview"],
        ["Full Stack Engineer (Python + React)", ["Python", "FastAPI", "React", "TypeScript", "PostgreSQL"], 80, "Interview / Good Fit"],
        ["Cloud DevOps Engineer", ["Kubernetes", "Docker", "Terraform", "AWS", "Python"], 74, "Interview / Good Fit"],
        ["Mid-Level Python Developer", ["Python", "Django", "PostgreSQL", "Celery"], 71, "Interview / Good Fit"],
        ["Junior Python Developer", ["Python", "Flask", "SQLite", "HTML/CSS"], 62, "Hold / Potential Pipeline"],
        ["Java SpringBoot Monolith Developer", ["Java 17", "Spring Boot", "Hibernate", "Oracle DB"], 44, "Reject / Low Fit"],
        ["HR Operations Recruiter", ["Talent Acquisition", "ATS Management", "Keka HRMS"], 32, "Reject / Low Fit"]
    ];

    const list = [];
    const uniqueCount = Math.floor(totalCount * 0.88);
    for(let i = 1; i <= totalCount; i++) {
        const fn = firstNames[i % firstNames.length];
        const ln = lastNames[(i * 3) % lastNames.length];
        const name = `${fn} ${ln}`;
        const loc = locations[i % locations.length];
        const r = roles[i % roles.length];
        const exp = (2 + ((i * 7) % 11)).toFixed(1);
        
        let isDup = false;
        let dupType = "None";
        if (i > uniqueCount) {
            isDup = true;
            dupType = i % 2 === 0 ? "Exact SHA-256 Hash Match" : "Semantic Profile Match (Email/Phone)";
        }

        list.push({
            rank: i,
            candidate_id: `CAN-BULK-${1000 + i}`,
            name: name,
            email: `${fn.toLowerCase()}.${ln.toLowerCase()}@gmail.com`,
            phone: `+91-987654${1000 + i}`,
            location: loc[0],
            is_hyderabad_based: loc[1],
            total_years_experience: exp,
            role_title: r[0],
            skills_list: r[1],
            overall_fit_score: Math.min(Math.max(r[2] + ((i * 13) % 15) - 7, 28), 100),
            recommendation: r[3],
            is_duplicate: isDup,
            duplicate_type: dupType
        });
    }

    list.sort((a,b) => b.overall_fit_score - a.overall_fit_score);
    list.forEach((item, idx) => item.rank = idx + 1);

    const hyd = list.filter(c => c.is_hyderabad_based).length;
    const strong = list.filter(c => c.overall_fit_score >= 82).length;
    const inter = list.filter(c => c.overall_fit_score >= 68 && c.overall_fit_score < 82).length;
    const hold = list.filter(c => c.overall_fit_score >= 52 && c.overall_fit_score < 68).length;
    const rej = list.filter(c => c.overall_fit_score < 52).length;

    return {
        total_scanned: totalCount,
        unique_candidates_count: uniqueCount,
        duplicates_detected_count: totalCount - uniqueCount,
        hyderabad_local_count: hyd,
        hyderabad_percentage: ((hyd / totalCount) * 100).toFixed(1),
        processing_time_seconds: 1.84,
        recommendation_breakdown: { strong_hire: strong, interview: inter, hold: hold, reject: rej },
        top_candidates_preview: list.slice(0, 50)
    };
}

function renderBulkAnalytics(data) {
    document.getElementById("bkTotal").textContent = data.total_scanned.toLocaleString();
    document.getElementById("bkUnique").textContent = data.unique_candidates_count.toLocaleString();
    document.getElementById("bkDuplicates").textContent = `🛡️ ${data.duplicates_detected_count.toLocaleString()} Duplicates Caught`;
    document.getElementById("bkHyd").textContent = data.hyderabad_local_count.toLocaleString();
    document.getElementById("bkHydPct").textContent = `📍 ${data.hyderabad_percentage}% Local Talent`;
    document.getElementById("bkStrong").textContent = data.recommendation_breakdown.strong_hire.toLocaleString();

    const recs = data.recommendation_breakdown;
    const total = data.total_scanned || 1;
    const sPct = ((recs.strong_hire / total) * 100).toFixed(1);
    const iPct = ((recs.interview / total) * 100).toFixed(1);
    const hPct = ((recs.hold / total) * 100).toFixed(1);
    const rPct = ((recs.reject / total) * 100).toFixed(1);

    document.getElementById("bkRecBar").innerHTML = `
        <div style="width: ${sPct}%; background: #10b981; title: 'Strong Hire (${recs.strong_hire})';"></div>
        <div style="width: ${iPct}%; background: #3b82f6; title: 'Interview (${recs.interview})';"></div>
        <div style="width: ${hPct}%; background: #f59e0b; title: 'Hold (${recs.hold})';"></div>
        <div style="width: ${rPct}%; background: #ef4444; title: 'Reject (${recs.reject})';"></div>
    `;

    document.getElementById("bkRecLegend").innerHTML = `
        <div><span style="color:#34d399;">●</span> Strong Hire: ${recs.strong_hire} (${sPct}%)</div>
        <div><span style="color:#60a5fa;">●</span> Interview: ${recs.interview} (${iPct}%)</div>
        <div><span style="color:#fbbf24;">●</span> Hold Pipeline: ${recs.hold} (${hPct}%)</div>
        <div><span style="color:#f87171;">●</span> Reject / Low Fit: ${recs.reject} (${rPct}%)</div>
    `;

    const rowsHtml = (data.top_candidates_preview || []).map(c => {
        let recColor = "#60a5fa";
        if(c.overall_fit_score >= 82) recColor = "#34d399";
        else if(c.overall_fit_score < 52) recColor = "#f87171";
        else if(c.overall_fit_score < 68) recColor = "#fbbf24";

        let dedupBadge = `<span class="badge green" style="display:inline-flex;">Unique Profile</span>`;
        if(c.is_duplicate) {
            dedupBadge = `<span class="badge" style="background:rgba(239,68,68,0.2);color:#f87171;border-color:#dc2626;display:inline-flex;font-size:0.7rem;">⚠️ ${c.duplicate_type.split(' ')[0]} Duplicate</span>`;
        }

        let rankStyle = "background: #334155;";
        if(c.rank === 1) rankStyle = "background: linear-gradient(135deg, #f59e0b, #d97706); box-shadow: 0 0 10px rgba(245,158,11,0.5);";
        else if(c.rank <= 3) rankStyle = "background: linear-gradient(135deg, #94a3b8, #64748b);";

        return `
            <tr>
                <td><div class="rank-circle" style="${rankStyle}">${c.rank}</div></td>
                <td>
                    <div style="font-weight: 700; color: #fff;">${c.name}</div>
                    <div style="font-size: 0.76rem; color: var(--text-muted);">${c.candidate_id || c.filename}</div>
                </td>
                <td><strong>${c.total_years_experience}</strong> Yrs</td>
                <td>${c.location.split(',')[0]} ${c.is_hyderabad_based ? '✅' : ''}</td>
                <td style="font-size: 0.82rem; color: #c4b5fd;">${c.role_title}</td>
                <td><strong style="color: ${recColor}; font-size: 1.05rem;">${c.overall_fit_score}</strong> / 100</td>
                <td><span style="font-weight:700; color:${recColor}; font-size:0.84rem;">${c.recommendation}</span></td>
                <td>${dedupBadge}</td>
            </tr>
        `;
    }).join("");

    document.getElementById("bulkTopBody").innerHTML = rowsHtml;
}

function handleBulkExcelClick(event) {
    if (!isOnlineMode) {
        event.preventDefault();
        alert("You are viewing the standalone client-side simulation.\n\nTo download the live 1,000-candidate Bulk Excel report (.xlsx), launch our FastAPI backend (`uvicorn main:app --reload`) and connect to http://localhost:8000/api/export-bulk-excel !");
    }
}

async function runBatchScreening() {
    const spinner = document.getElementById("batchSpinner");
    spinner.style.display = "inline-block";
    const area = document.getElementById("batchResultsArea");
    area.innerHTML = `<div class="empty-state"><h3>⚡ Running Keka ATS Intelligence on 10 Resumes...</h3><p>Extracting text, computing SHA-256/semantic hashes, and scoring candidate profiles against Senior Python Backend Engineer JD...</p></div>`;

    try {
        if (isOnlineMode) {
            const res = await fetch("/api/batch-score", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ jd_filename: "backend_engineer.txt", llm_provider: "local" })
            });
            const data = await res.json();
            renderBatchTable(data.ranked_candidates);
            loadEvaluations();
        } else {
            await new Promise(resolve => setTimeout(resolve, 450));
            const list = Object.keys(MOCK_CANDIDATES).map(fn => {
                const c = MOCK_CANDIDATES[fn];
                return {
                    filename: fn,
                    candidate_metadata: { name: c.name, total_years_experience: c.total_years_experience, location: c.location, is_hyderabad_based: c.is_hyderabad_based },
                    score_data: { overall_fit_score: c.score, recommendation: c.rec },
                    deduplication_info: c.dedup
                };
            }).sort((a,b) => b.score_data.overall_fit_score - a.score_data.overall_fit_score);
            list.forEach((item, idx) => item.rank = idx + 1);
            renderBatchTable(list);
        }
    } catch(e) {
        area.innerHTML = `<div class="empty-state" style="color:#ef4444;"><h3>Batch Screening Failed</h3><p>${e.message}</p></div>`;
    } finally {
        spinner.style.display = "none";
    }
}

function renderBatchTable(candidates) {
    let rowsHtml = candidates.map(item => {
        const meta = item.candidate_metadata;
        const score = item.score_data;
        const dedup = item.deduplication_info;

        let rankClass = "";
        if(item.rank === 1) rankClass = "top-1";
        else if(item.rank === 2) rankClass = "top-2";
        else if(item.rank === 3) rankClass = "top-3";

        let recColor = "#60a5fa";
        if(score.overall_fit_score >= 82) recColor = "#34d399";
        else if(score.overall_fit_score < 52) recColor = "#f87171";
        else if(score.overall_fit_score < 68) recColor = "#fbbf24";

        let dedupBadge = `<span class="badge green" style="display:inline-flex;">Unique Profile</span>`;
        if(dedup.is_duplicate) {
            dedupBadge = `<span class="badge" style="background:rgba(239,68,68,0.2);color:#f87171;border-color:#dc2626;display:inline-flex;font-size:0.7rem;">⚠️ ${dedup.duplicate_type.split(' ')[0]} Duplicate</span>`;
        }

        return `
            <tr>
                <td><div class="rank-circle ${rankClass}">${item.rank}</div></td>
                <td>
                    <div style="font-weight: 700; color: #fff;">${meta.name}</div>
                    <div style="font-size: 0.78rem; color: var(--text-muted);">${item.filename}</div>
                </td>
                <td><strong>${meta.total_years_experience}</strong> Yrs</td>
                <td>${meta.location} ${meta.is_hyderabad_based ? '✅' : ''}</td>
                <td><strong style="color: ${recColor}; font-size: 1.05rem;">${score.overall_fit_score}</strong> / 100</td>
                <td><span style="font-weight:700; color:${recColor}; font-size:0.85rem;">${score.recommendation}</span></td>
                <td>${dedupBadge}</td>
                <td>
                    <button class="btn btn-secondary" style="padding: 0.4rem 0.8rem; font-size: 0.8rem; width: auto;" onclick="inspectBatchCandidate('${item.filename}')">Inspect Report</button>
                </td>
            </tr>
        `;
    }).join("");

    const html = `
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Candidate Info</th>
                        <th>Experience</th>
                        <th>Location</th>
                        <th>Fit Score</th>
                        <th>Recommendation</th>
                        <th>Deduplication Status</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>${rowsHtml}</tbody>
            </table>
        </div>
    `;
    document.getElementById("batchResultsArea").innerHTML = html;
}

async function inspectBatchCandidate(filename) {
    switchTab('singleTab');
    document.getElementById("sampleResumeSelect").value = filename;
    await runSingleScorer();
}

async function testDedupFile(filename) {
    switchTab('singleTab');
    document.getElementById("sampleResumeSelect").value = filename;
    await runSingleScorer();
}

async function loadEvaluations() {
    try {
        const res = await fetch("/api/evaluations");
        const data = await res.json();
        const tbody = document.getElementById("evaluationsBody");
        if(data.evaluations.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 2rem;">No candidates evaluated yet. Run Single or Batch screening to populate logs.</td></tr>`;
            return;
        }

        tbody.innerHTML = data.evaluations.slice().reverse().map(r => `
            <tr>
                <td style="font-size:0.8rem; color:var(--text-muted);">${r.timestamp}</td>
                <td><strong>${r.candidate_name}</strong></td>
                <td>${r.total_years_experience} Yrs</td>
                <td>${r.location}</td>
                <td style="font-size:0.82rem;">${r.jd_name}</td>
                <td><strong style="color:#60a5fa;">${r.overall_fit_score}</strong> / 100</td>
                <td style="font-weight:600; font-size:0.85rem;">${r.recommendation}</td>
                <td>${r.is_duplicate ? '<span style="color:#f87171;font-weight:700;">YES</span>' : '<span style="color:#34d399;">NO</span>'}</td>
                <td style="font-size:0.78rem; color:var(--text-muted);">${r.scoring_engine}</td>
            </tr>
        `).join("");
    } catch(e) {
        console.error("Failed to load evaluations:", e);
    }
}

function handleExcelClick(event) {
    if (!isOnlineMode) {
        event.preventDefault();
        alert("You are viewing the standalone client-side preview.\n\nTo download the live Excel report (.xlsx), launch our FastAPI backend (`uvicorn main:app --reload`) and connect to http://localhost:8000/api/export-excel !");
    }
}
