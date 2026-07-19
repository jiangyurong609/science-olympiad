# Test Report — v5

## Automated verification

- 22 tests passed.
- 79% total application coverage.
- Ruff linting passed.
- Fresh Alembic migration through revision `0003_jobs_assignments` passed.
- Fresh seed against the migrated database passed.

## Newly tested behavior

- Background job enqueue, execution, persistence, and result retrieval.
- Model-generation endpoint refuses operation without a configured provider or grounded claims.
- Organization-scoped team assignments.
- Student assignment visibility through membership.
- Coach dashboard metrics.
- Rate-limit response headers.

## Existing regression coverage retained

- Public role-escalation prevention.
- Guardian consent.
- Source rights controls.
- Crawling security boundaries.
- Immutable exam snapshots.
- Server-side deadlines.
- Idempotent and ordered response saves.
- Scoring and remediation.
- Transfer and delayed-retention checks.
- Team tenant isolation.
