# Implementation Progress — v4

This release continues the production plan beyond v3.

## Added

- OpenAI-compatible model-provider abstraction with structured JSON output and deterministic fallback.
- Automated scientific-claim extraction from approved crawled content; extracted claims remain unapproved until editorial review.
- HTML and PDF source ingestion with parser metadata and immutable snapshots.
- Team and team-membership models with organization-level tenant enforcement.
- Team creation, member assignment, and team listing APIs.
- Generation-run audit records containing provider, prompt version, request, and generated question IDs.
- Delayed-review queue and retention-test APIs.
- Correct delayed review resolves a remediation case and strengthens mastery.
- Failed delayed review reopens the case and increases misconception risk.
- Alembic migration for teams, memberships, and generation runs.

## Production limitations still remaining

- External model calls require operator-supplied endpoint and credentials and have not been certified for autonomous publication.
- PDF extraction supports text PDFs; scanned PDFs require a separate OCR review pipeline.
- Extracted claims require human approval.
- No email-delivery provider, SSO, rostering, rate limiting, or background job scheduler yet.
- Team dashboards and coach analytics UI are not complete.
- Rich station, lab, diagram, and build-event exam modalities remain future work.
