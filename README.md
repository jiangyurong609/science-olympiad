# Science Olympiad Study Lab

A rights-aware learning, mock-exam, scoring, and remediation platform for Science Olympiad. It
turns vetted primary sources (NASA, NOAA, USGS, NPS, and other government/official material) into
grounded lessons, calibrated practice, and season-aware competition exams — with every claim,
question, and exam item traceable back to an immutable source snapshot.

The application is a FastAPI backend serving a single-page vanilla-JS frontend, backed by
SQLAlchemy models that run on SQLite locally and PostgreSQL in production. A background worker
handles email delivery, model-based generation jobs, and the discovery crawler schedule.

- **Live:** https://science-olympiad.com — deployed on Google Cloud Run (`soplat-web`, `us-central1`)
- **API docs:** `/docs` (Swagger UI) on any running instance

---

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Project layout](#project-layout)
- [Quickstart (local)](#quickstart-local)
- [Configuration](#configuration)
- [Content pipeline](#content-pipeline)
- [Scripts](#scripts)
- [Testing & linting](#testing--linting)
- [Docker](#docker)
- [Deployment (Google Cloud Run)](#deployment-google-cloud-run)
- [Further docs](#further-docs)
- [License](#license)

---

## Features

**Identity & access**
- Public self-registration restricted to the student role; staff accounts are provisioned separately.
- Firebase email/password authentication in production; local JWT auth for development.
- Role-based permissions for administrator, content editor, subject-matter (SME) reviewer, coach, and student.
- Organization- and team-scoped visibility; guardian-consent gating for students under 13.

**Rights-aware content pipeline**
- Source registry with default-deny rights policies and administrator-only approval with immutable audit records.
- Discovery crawler with domain allowlists, robots checks, redirect revalidation, public-IP validation, byte limits, and content-addressed immutable snapshots.
- Review-required scientific claim extraction bound to exact source snapshots, with approval-time quote and locator verification.
- Material-change detection that automatically quarantines dependent claims, questions, lessons, and exams.

**Questions & exams**
- Deterministic and optional model-assisted question generation with answers, explanations, citations, and provenance.
- Version-specific editorial + independent SME review, similarity reports, and explicit publication decisions.
- Pilot calibration (facility, discrimination, timing, omissions) gates competition-ready items.
- Immutable per-attempt exam-item snapshots; server-authoritative deadlines; ordered, idempotent autosave.
- Exam classes: Reviewed Practice, Foundational Practice, and Competition Ready, with season-aware labels.
- Blueprint-aware mock-exam assembly built from published, calibrated question versions.

**Scoring, remediation & tutoring**
- Automated scoring for single-choice, numeric-tolerance, and normalized-text responses.
- Content challenges with severity triage, two-person resolution, audited score correction, and remediation cases.
- Error Notebook: every miss becomes a traceable case with reflection, near-transfer practice, and delayed retention checks.
- Source-grounded lesson and remediation tutor with approved-claim citations and a deterministic grounded fallback.

**Learning experience**
- Versioned, resumable, source-grounded lessons and evidence labs (Rocks & Minerals, Ecology, Entomology).
- Event-aware practice hub and in-app materials browser with deep-linkable subject context.
- Explainable personalized daily missions capped at ~3 actions / ~35 minutes.
- Audited timed-accommodation profiles with server-authoritative extended time and immutable timing snapshots.
- Responsive interface verified at desktop and mobile widths.

> The full capability history by version lives in `IMPLEMENTATION_PROGRESS*.md` and `TEST_REPORT*.md`.

---

## Architecture

```
Browser SPA (app/static)  ──HTTP/JSON──►  FastAPI app (app/main.py)
  index.html / app.js                       ├─ app/api/routes.py     (~67 endpoints)
  styles.css / theme.css                     ├─ app/api/v5_routes.py  (jobs, model-gen, assignments, coach)
                                             ├─ RateLimitMiddleware
                                             └─ app/services/*        (business logic)
                                                        │
                                             SQLAlchemy models (app/models/entities.py, 54 entities)
                                                        │
                                    SQLite (dev)  /  PostgreSQL via Cloud SQL (prod)

Background worker (scripts/worker.py) ──► email outbox delivery, model-generation jobs, crawl scheduler
```

- **`app/core`** — settings (`config.py`), DB engine/session (`database.py`), auth & hashing (`security.py`), and the rate-limit middleware.
- **`app/services`** — one module per domain concern: crawler, discovery, claim extraction, generation, validation, calibration, scoring, remediation, tutor, notifications, mock-exam assembly, blueprint, source-change and coverage tracking, jobs, and Firebase identity.
- **`app/schemas`** — Pydantic request/response models.
- **Migrations** — Alembic (`alembic/`); the schema is authoritative in PostgreSQL and applied at container startup.

---

## Tech stack

| Layer        | Choice |
|--------------|--------|
| API          | FastAPI + Uvicorn |
| ORM / models | SQLAlchemy 2.0 (PostgreSQL-compatible) |
| Validation   | Pydantic v2 / pydantic-settings |
| Auth         | Firebase Admin (prod) · python-jose JWT + passlib (dev) |
| Migrations   | Alembic |
| Crawling     | httpx + BeautifulSoup4 + pypdf |
| Frontend     | Vanilla JS SPA (no build step) served from `app/static` |
| Database     | SQLite (dev) · PostgreSQL / Cloud SQL (prod) |
| Packaging    | Docker · Docker Compose |
| Tooling      | pytest + pytest-cov · ruff |

Requires Python **3.11+**.

---

## Project layout

```
app/
  main.py            FastAPI app: routers, static mount, rate limiting
  api/               routes.py (core) + v5_routes.py (jobs/model-gen/assignments/coach)
  core/              config, database, security, rate_limit
  models/entities.py 54 SQLAlchemy entities (users, sources, questions, exams, remediation, …)
  schemas/           Pydantic API schemas
  services/          domain logic (crawler, generation, scoring, tutor, calibration, …)
  static/            SPA: index.html, app.js, styles.css, theme.css, media, fonts
alembic/             database migrations
scripts/             seed, admin creation, worker, and the content-build pipeline
tests/               28 test modules (auth, exams, scoring, crawler, tutor, …)
docs/                architecture, product design, and the 2026 material catalog
Dockerfile           runs `alembic upgrade head` then Uvicorn
docker-compose.yml   web + worker on a shared SQLite volume
```

---

## Quickstart (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'          # or: make install

alembic upgrade head             # create the SQLite schema
python -m scripts.seed           # demo content + accounts  (or: make seed)
uvicorn app.main:app --reload    # or: make run
```

Open http://localhost:8000 · API docs at http://localhost:8000/docs

**Demo accounts** (after seeding):

| Role        | Email                  | Password         |
|-------------|------------------------|------------------|
| Student     | `student@example.com`  | `StudentPass123!`|
| Coach       | `coach@example.com`    | `CoachPass123!`  |
| Admin       | `admin@example.com`    | `AdminPass123!`  |
| Editor      | `editor@example.com`   | `EditorPass123!` |
| SME reviewer| `sme@example.com`      | `SmePass123!`    |

Create a real (non-demo) administrator:

```bash
python -m scripts.create_admin --email admin@school.org --name "School Admin" --password 'use-a-strong-password'
```

Run the background worker in a second terminal (email delivery, generation jobs, crawl schedule):

```bash
python -m scripts.worker
```

---

## Configuration

Settings load from environment variables (see `app/core/config.py`); copy `.env.example` to `.env`
for local development. Key variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `ENVIRONMENT` | `development` / `staging` / `production` | `development` |
| `DATABASE_URL` | SQLAlchemy URL (`sqlite:///…` or `postgresql+psycopg://…`) | SQLite file |
| `JWT_SECRET` | Signing secret for local auth (must be strong in prod) | — |
| `AUTH_PROVIDER` | `local` or `firebase` | `local` |
| `FIREBASE_PROJECT_ID` / `FIREBASE_WEB_API_KEY` | Firebase auth config | — |
| `GOOGLE_APPLICATION_CREDENTIALS` | Service-account file (or use workload identity) | — |
| `ALLOWED_CRAWL_DOMAINS` | Comma-separated crawl allowlist | gov science domains |
| `CRAWL_MAX_BYTES` | Per-download byte cap | `5_000_000` |
| `ARTIFACT_STORE_PATH` | Snapshot/artifact storage dir | `./data/artifacts` |
| `OPENAI_COMPATIBLE_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL` | Optional model provider for generation | — / — / `gpt-4.1-mini` |
| `EMAIL_DELIVERY_PROVIDER` | `disabled` or `smtp` | `disabled` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM_EMAIL` | SMTP delivery | — |
| `PUBLIC_APP_URL` | Base URL used in emails/links | `http://localhost:8000` |
| `TUTOR_DAILY_MESSAGES` | Per-user daily tutor limit | `50` |
| `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` | Request rate limiter | `120` / `60` |
| `CRAWL_SCHEDULER_MINUTES` | Self-renewing crawl scheduler cadence | `15` |
| `WORKER_POLL_SECONDS` | Worker poll interval | `2` |

**Production requirements.** In `production`, local password authentication is refused — the
browser uses Firebase for email/password, verification, reset, and token refresh, and FastAPI
verifies each Firebase ID token and maps its immutable UID to a local user. Roles, organizations,
teams, guardian consent, and all learning data remain authoritative in PostgreSQL. Prefer workload
identity over a service-account file where the platform supports it. Minimum production env:

```bash
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg://...
AUTH_PROVIDER=firebase
FIREBASE_PROJECT_ID=<firebase-project-id>
FIREBASE_WEB_API_KEY=<firebase-web-api-key>
EMAIL_DELIVERY_PROVIDER=smtp   # + SMTP_* values
PUBLIC_APP_URL=https://your-app.example
```

---

## Content pipeline

Content flows through a rights-aware pipeline where each stage is gated and auditable:

```
discovery → source approval → crawl snapshot → claim extraction → review
         → question generation → editorial + SME review → calibration → exam assembly
```

1. **Discovery** (`services/discovery.py`) — allowlisted domains, sitemap/RSS/Atom parsing, and a deduplicated resource frontier; discovery never authorizes or publishes.
2. **Approval** (`services/rights.py`) — administrators promote candidates to source records under default-deny rights policies with immutable audit trails.
3. **Crawl** (`services/crawler.py`) — bounded streaming downloads with robots/redirect/IP/byte protections, conditional `ETag`/`Last-Modified` refresh, and content-addressed immutable snapshots.
4. **Claims** (`services/claim_extraction.py`) — review-required extraction bound to exact snapshots with quote/locator verification.
5. **Questions** (`services/question_generation.py`, `model_generation.py`) — deterministic or model-assisted generation with provenance; both a candidate and an independent verifier response are persisted.
6. **Review** (`services/validation.py`) — versioned editorial + independent SME review, similarity reports, quality checklists, explicit publish decisions.
7. **Calibration** (`services/calibration.py`) — pilot metrics gate competition-ready items.
8. **Assembly** (`services/mock_exam.py`, `blueprint.py`) — blueprint-driven exams from published, calibrated versions only.
9. **Change management** (`services/source_changes.py`, `source_coverage.py`) — material-change detection quarantines dependents; coverage scorecards drive the competition release gate.

The 2026 material catalog and its reports live in `docs/science-olympiad-material-catalog-2026/`.

---

## Scripts

Run with `python -m scripts.<name>`:

| Script | Purpose |
|--------|---------|
| `seed` | Seed demo organizations, users, content, lessons, and exams |
| `create_admin` | Provision a real administrator account |
| `worker` | Background worker: email outbox, generation jobs, crawl scheduler |
| `crawl_catalog` | Crawl the 2026 material catalog |
| `open_sources` | Register/approve source records |
| `import_past_tests` | Ingest past competition tests |
| `analyze_structure` | Analyze test structure for blueprints |
| `generate_questions` | Generate grounded questions from downloaded materials |
| `build_courses` / `build_visual_content` | Build lessons and visual learning content |
| `fetch_specimen_images` / `enrich_flagship_visuals` | Populate rights-gated specimen assets |
| `interleave_visual_exams` | Assemble visual practice exams |
| `generate_lessons` | Two-stage systematic deep-course generator (per event / `--all`) |
| `ingest_reference_material` | Ingest public-domain `.gov` reference text (NOAA/genome.gov/NIST/EPA) to ground courses |
| `enrich_lesson_media` | Add per-lesson specimen image galleries drawn from the media library |
| `remove_thin_lessons` | Remove the redundant thin `foundations-*` lesson so the deep course is surfaced |
| `attach_specimen_images` / `attach_snapshot_images` | Attach labelled specimen photos to questions / frozen exam snapshots |
| `flag_missing_figures` | Flag exam items that depend on a figure we can't reproduce (excluded from scoring) |
| `map_distractor_misconceptions` | LLM pass mapping every MCQ distractor to a specific misconception |

**Production data sync** (via the Cloud SQL proxy — `scripts/prod_db_proxy.sh`):

| Script | Purpose |
|--------|---------|
| `mirror_db_to_prod` | Content-only mirror (preserves prod accounts) |
| `sync_lessons_to_prod` | Replace generated (`auto-`) courses for named events |
| `sync_assets_to_prod` | Push question images + exam-snapshot figure flags (no deletes) |
| `sync_question_specs_to_prod` | Push MCQ misconception mappings + backfill exam snapshots |

---

## Testing & linting

```bash
ruff check app tests scripts                 # or: make lint
pytest --cov=app --cov-report=term-missing   # or: make test
```

28 test modules cover authentication and authorization, immutable exams, timing and autosave
integrity, scoring, calibration, the crawler and source-change pipeline, the tutor, remediation,
and the seeded content.

---

## Docker

Run the web app and worker together on a shared SQLite volume:

```bash
docker compose up --build
```

The image runs `alembic upgrade head` at startup so the schema always matches the code, then serves
Uvicorn on the port from `$PORT` (default `8000`; `8080` on Cloud Run).

---

## Deployment (Google Cloud Run)

The platform runs as the Cloud Run service **`soplat-web`** in **`us-central1`** (project
`video-agent-493605`), backed by a Cloud SQL PostgreSQL instance (`soplat-pg`) with the database URL
and JWT secret stored in Secret Manager (`soplat-database-url`, `soplat-jwt-secret`).

To ship a new revision, build and push a new image tag, then deploy it (config carries over):

```bash
# 1. Build & push the image to Artifact Registry
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/video-agent-493605/soplat/web:vNEXT .

# 2. Roll it out (env, secrets, and Cloud SQL binding are preserved)
gcloud run deploy soplat-web \
  --region=us-central1 \
  --image=us-central1-docker.pkg.dev/video-agent-493605/soplat/web:vNEXT
```

Database migrations run automatically at container startup via the Dockerfile `CMD`. Deploying with
only `--image` preserves the existing env vars, Secret Manager references, and Cloud SQL connection.

---

## Further docs

- `docs/ARCHITECTURE.md` — system architecture
- `docs/PRODUCT_DESIGN.md` — product design
- `docs/science_olympiad_platform_comprehensive_design.md` — comprehensive design reference
- `docs/science-olympiad-material-catalog-2026/` — 2026 source material catalog and reports
- `IMPLEMENTATION_PROGRESS*.md` / `TEST_REPORT*.md` — capability history by version

---

## Status

This is a security-hardened vertical MVP, not yet ready for broad minors or school deployment.
Working vertical slices exist for Firebase identity, guardian-consent gating, tenant-scoped teams,
coach analytics, assignments, claim grounding, and transfer remediation. Major remaining layers
include consent-email delivery and withdrawal, school SSO and rostering, production PostgreSQL
operations, Firebase App Check, a full model-validation gateway, durable discovery crawling,
OCR/dataset ingestion, richer assessment modalities, accessibility certification, load and
penetration testing, and legal review.

---

## License

Copyright © 2026 Fieldstone — Science Olympiad Study Lab.

This program is free software: you can redistribute it and/or modify it under the terms of the
**GNU Affero General Public License, version 3** (or, at your option, any later version) as
published by the Free Software Foundation. See [`LICENSE`](LICENSE) for the full text.

Because this is network software, the AGPL's §13 applies: **if you run a modified version of
this software on a server and let users interact with it over a network, you must offer those
users access to the corresponding source code** of your modified version. The canonical source
is https://science-olympiad.com (and the repository it is built from).

Third-party content follows its own terms: generated lessons and answer keys are grounded in
public-domain U.S. government sources (NOAA, NASA, USGS, NIST, EPA, genome.gov/MedlinePlus), and
specimen imagery is limited to public-domain / CC0 / CC-BY(-SA) files from Wikimedia Commons with
attribution retained in each asset's manifest entry.
