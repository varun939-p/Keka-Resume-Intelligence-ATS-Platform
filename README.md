# Keka Resume Intelligence

Resume screening for recruiting teams: parse a folder of resumes, block duplicates with three independent checks, score every candidate on four explainable dimensions against a job description, and route each one to a pipeline stage.

Runs fully offline with a deterministic scoring engine. Groq or OpenAI keys add hybrid LLM scoring; a Google service account adds a Sheets mirror.

[![5-minute walkthrough on Loom](https://cdn.loom.com/sessions/thumbnails/942f148659e6439ea4d83f5d73935d63-with-play.gif)](https://www.loom.com/share/942f148659e6439ea4d83f5d73935d63)

[Watch the 5-minute walkthrough on Loom](https://www.loom.com/share/942f148659e6439ea4d83f5d73935d63) (recorded on the July 2026 build).

## Run it

```bash
python -m venv venv
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python main.py                   # http://127.0.0.1:8000  ·  API docs at /docs
```

Open the dashboard and press **Run demo scan**: 10 sample resumes (two of them planted duplicates) are scored against the Senior Python Backend Engineer JD in under a second.

## Two workspaces

| | Demo | Live |
|---|---|---|
| Job descriptions | `sample_jd/` (read-only) | samples plus your own, with editable requirements, weights and thresholds |
| Resumes | `sample_resumes/` | **Select folder** (recursive), **Select files**, or drag and drop a folder; PDF, DOCX, TXT up to 10 MB (4 MB on Vercel) |
| Persistence | Reset on every scan | Kept until you reset it in Integrations |

The mode switch in the header is remembered per browser. Demo and Live data never mix: candidates, batches and the dedup registry are all scoped per workspace.

## Pipeline

Every resume passes four stages, and each stage is streamed to the dashboard over server-sent events.

1. **Parse** (`parser.py`): text from PDF/DOCX/TXT; name, email, phone, LinkedIn, GitHub, location, headline, dated roles (overlaps merged), total experience (stated or from dates), education (level, field, institution, GPA), skills from a 120-skill taxonomy (`taxonomy.py`), and quantified achievements.
2. **Deduplicate** (`dedup.py`):
   - **L1 file fingerprint:** SHA-256 of the bytes and of the normalized text.
   - **L2 contact hash:** SHA-256 of the normalized email and phone. Raw contact data never enters the registry.
   - **L3 semantic similarity:** cosine similarity of term and bigram vectors; 86% or more is a match, 72% or more is flagged for review.
3. **Score** (`scorer.py`), each dimension 0–100, with weights set per JD (default 40/25/20/15):
   - **Technical skills match:** requirements extracted from the JD into critical / core / nice-to-have tiers. "FastAPI, Django, or Flask" becomes one any-of requirement.
   - **Experience & seniority:** years against the JD band, scaled by how much of the critical stack appears in actual roles.
   - **Project & impact depth:** quantified outcomes, ownership verbs, leadership signals.
   - **Education & keywords:** degree level and field, blended with JD keyword similarity.
   - A candidate covering under 35% of critical requirements is capped below the Hold threshold.
4. **Route:** Shortlisted / Technical Review / Hold / Rejected at the JD's thresholds (default 75 / 60 / 45), or Duplicate Flagged. Recruiters can override any stage; the auto route is kept and can be restored.

Each candidate carries a written recommendation (summary, strengths, concerns, interview focus), per-dimension evidence, the full dedup trace, and per-stage timings.

Recruiter tools on top of the pipeline:
- **Rescore batch:** re-rank the same resumes against another role, or against a JD whose weights you just changed, without re-uploading.
- **Compare:** select 2–4 candidates for a side-by-side view, with the best value marked on every dimension.
- **Keyboard:** `/` search · `Enter` open · `J`/`K` next and previous · `S`/`T`/`H`/`R` set the stage from the drawer.

## LLM and Sheets (optional)

Copy `.env.example` to `.env`.

- `GROQ_API_KEY` or `OPENAI_API_KEY`: choose the engine in **Integrations**. The model supplies half of each dimension score and the written narrative. Skill matching, gaps and routing stay deterministic, and any API failure falls back per candidate, with the reason recorded.
- `GOOGLE_SHEET_ID` + `GOOGLE_SERVICE_ACCOUNT_JSON`: share the sheet with the service account's email. **Sync to Sheets** mirrors the workspace into an `ATS Candidates` worksheet.

## Outputs

- **Excel** (`/api/exports/candidates.xlsx`): Summary, Candidates (ranked, stage-coloured, filterable), Skill Gaps and Audit Log sheets. It respects the current scope, stage filter, search or selection.
- **Audit log**: every scan, duplicate flag, stage change, note, export, sync and reset, appended to `data/keka_sheets_audit_log.csv` and `.json` and downloadable from the Audit log view.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health`, `/api/settings`, `/api/integrations` | Status, engine, keys, storage |
| PATCH | `/api/settings` | Choose the scoring engine |
| GET/POST/PUT/DELETE | `/api/jds`, `/api/jds/{id}` | Job description library |
| POST | `/api/jds/analyze`, `/api/jds/extract` | Profile JD text, or read a JD file |
| GET | `/api/samples` | Sample resumes |
| POST | `/api/batches` | Start a batch (`workspace`, `jd_id`, `expected`) |
| POST | `/api/batches/{id}/samples`, `/api/batches/{id}/files` | Process one sample or one uploaded file |
| GET | `/api/batches/{id}/events` | Server-sent progress events |
| POST | `/api/batches/{id}/rescore` | Re-score a finished batch against any JD (`jd_id`) or its own JD's latest weights; keeps dedup results and recruiter overrides |
| GET | `/api/candidates` | Filter, search and sort (`workspace`, `batch_id`, `stage`, `q`, `min_score`, `sort`, `order`) |
| GET/PATCH/DELETE | `/api/candidates/{id}` | Detail with audit history; change stage or add a note |
| POST | `/api/candidates/bulk` | Bulk stage change, restore auto stage, or delete |
| GET | `/api/analytics` | KPI ribbon, stage counts, skill gaps (with previous-batch comparison) |
| GET | `/api/audit`, `/api/exports/*` | Audit log and downloads |
| POST | `/api/integrations/sheets/sync`, `/api/workspaces/{ws}/reset` | Sheets mirror, workspace reset |

Errors always return `{"error": {"code", "message"}}`.

## Layout

```
main.py        REST API and dashboard host
config.py      environment, paths (./data locally, /tmp/keka on Vercel)
parser.py      text extraction and profile parsing
taxonomy.py    skill taxonomy and matching
dedup.py       three-layer deduplication registry
scorer.py      JD profiling, scoring, routing, recommendation, LLM hybrid
pipeline.py    batch orchestration and event stream
store.py       candidates, batches, JD library, analytics
sheets.py      audit log, Excel report, Google Sheets sync
frontend/      dashboard (vanilla HTML/CSS/JS)
sample_jd/, sample_resumes/   demo inputs (regenerate with generate_sample_resumes.py)
```

## Deploy on Vercel

No `vercel.json` is needed. Vercel detects FastAPI from `requirements.txt` and serves the `app` object in `main.py`; the dashboard, `sample_jd/` and `sample_resumes/` ship inside the function. Add the optional keys from `.env.example` as project environment variables.

When the `VERCEL` variable is set (Vercel sets it automatically):
- Data is written to `/tmp/keka`, the only writable location.
- Uploads are capped at 4 MB per file, under Vercel's 4.5 MB request-body limit.

## Limits

- No OCR: image-only PDFs are rejected with a clear reason, as are legacy `.doc` files.
- On Vercel, storage under `/tmp` is ephemeral and per instance: a cold start or a second instance begins with an empty Live workspace. Use local hosting, or set `KEKA_DATA_DIR` to a persistent volume, for a durable talent pool.
