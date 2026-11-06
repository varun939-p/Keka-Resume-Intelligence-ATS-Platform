# Product

<!-- impeccable:product-schema 1 -->

> Inferred from the build brief of 2026-11-06 (the owner asked for an autonomous build, so no interview was held). Every line below comes from that brief or the repository; correct anything that is wrong.

## Platform

web

## Users

- **Technical recruiters** screening batches of engineering resumes against an open role, many times a day.
- **HR directors** checking pipeline health: how many were scanned, how many converted to shortlist, how many duplicates were blocked.
- **Engineering hiring managers** reading one candidate in depth before deciding on an interview, and tuning what a role's score rewards.

They expect a fast, self-explanatory SaaS tool on par with Keka HR, Greenhouse and Linear.

## Product Purpose

Turn a folder of resumes (PDF, DOCX, TXT) plus a job description into a ranked, deduplicated, stage-routed shortlist, with every score explainable. Success: a recruiter goes from files to a defensible shortlist in one sitting, and every number can be traced to evidence in the resume.

## Positioning

Scoring is deterministic and auditable by default (same input, same score, evidence shown per dimension), with optional LLM assistance that never removes the audit trail. Deduplication runs three independent layers (file hash, contact hash, semantic similarity) and shows which one fired.

## Operating Context

- Two workspaces behind a global mode switch: **Demo** (bundled sample JDs from `sample_jd/` and resumes from `sample_resumes/`, reset per scan) and **Live** (the recruiter's own folders and custom JDs, persistent).
- Batches are processed file by file with live progress; results land in a filterable candidate table and a per-candidate drawer.
- Outputs leave the tool as Excel (.xlsx), the CSV/JSON audit log, and an optional Google Sheets mirror.
- Deploy targets: local FastAPI server, and Vercel (ephemeral `/tmp` storage).

## Capabilities and Constraints

- Stages: Shortlisted, Technical Review, Hold / Borderline, Rejected, Duplicate Flagged. Routing thresholds and the four dimension weights (Technical, Experience & Seniority, Project/Impact, Education & Keywords) are configurable per custom JD.
- Works fully offline without API keys. Groq/OpenAI keys enable hybrid scoring; Google Sheets needs a service account.
- No OCR: image-only PDFs are rejected with a clear reason. Legacy `.doc` is unsupported.
- Stack: vanilla HTML/CSS/JS frontend served by a Python FastAPI backend (existing codebase).

## Brand Commitments

- Product name in use: "Keka Resume Intelligence". No Keka logo assets exist in the repo; do not imitate one.
- Owner direction, revised 2026-11-06: replace the near-black rail and light-blue accent with a researched, non-default palette, and avoid fonts and number styles that read as AI-generated. Shipped as "petrol & brass": night-petrol rail, warm bone ground, graphite ink, petrol accent, brass mark; Mona Sans for UI and numbers, Fragment Mono only for machine strings.
- Owner direction, second revision the same day: richer, non-generic stage colours and type, with no traffic-light green/red. Shipped as a pigment set (viridian, cobalt, yellow ochre, stone, mulberry for duplicates, burnt sienna for errors only), drawn stage glyphs, semi-condensed tag labels, and plain proportional figures (Mona Sans's tabular digits have a code-style slashed zero).
- Kept from the original brief: Keka HR / Linear executive restraint, 1px structural borders, WCAG AA contrast, semantic status badges.
- Stage colours must stay distinct for colour-blind users (validated) and must not be Tailwind's default emerald/blue/amber/red.
- Banned by the owner: neon purple/cyan gradients, glowing borders, emoji as icons, uneven card grids, Tailwind-default palettes.

## Evidence on Hand

- 3 sample job descriptions (`sample_jd/`), 10 sample resumes including 2 deliberate duplicates (`sample_resumes/`).
- No real customers, testimonials, benchmarks or hiring outcomes exist; none may be invented.

## Product Principles

1. Every number is explainable: show the evidence beside the score.
2. Problems surface where the data is: a duplicate or a critical gap is flagged on the row, not in a separate report.
3. Never fail closed: no keys, no network, or a bad file degrades one feature or one file, never the batch.
4. One workspace, one truth: Demo data never mixes with Live data.

## Accessibility & Inclusion

WCAG AA contrast in light and dark themes; status never conveyed by colour alone; full keyboard operation of table, drawer and menus.
