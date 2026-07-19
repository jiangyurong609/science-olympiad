# Implementation Progress — v5

## Completed in this increment

- Durable `background_jobs` records with queued, running, completed, retry, and failed states.
- Polling worker entrypoint (`python -m scripts.worker`).
- Jobs for source crawling, scientific-claim extraction, and delayed-review scanning.
- Administrative job inspection and manual run APIs.
- OpenAI-compatible competition-item generation pipeline.
- Strict structured generation contract grounded only in approved scientific claims.
- Independent second-pass model verifier before an item can be machine validated.
- Generation-run provenance, prompt version, provider, model, claim IDs, and failure recording.
- Tenant-scoped coach assignments for teams and exams.
- Student assignment listing based on team membership.
- Coach dashboard with student count, assignment completion, average score ratio, and open remediation count.
- Process-local API rate limiting with standard retry headers.
- Separate web and worker services in Docker Compose.
- Alembic revision for jobs and assignments.
- Removed implicit schema creation from application import; database schema is now migration-controlled.

## Important operational notes

- The included rate limiter is appropriate for one application process. A multi-replica production deployment should replace its storage with Redis.
- The worker is database-polled and intentionally simple. Temporal, Celery, or a managed queue remains preferable once workflows require high throughput or long-running orchestration.
- External model generation is disabled unless `OPENAI_COMPATIBLE_BASE_URL` and `OPENAI_API_KEY` are configured.
- Model-generated items remain drafts unless both deterministic validation and the independent model verifier pass.
- Human/SME approval is still required before tournament-grade use.
