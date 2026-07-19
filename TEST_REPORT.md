# Verification Report

## Current automated verification

- `ruff check app tests scripts`: passed
- `pytest --cov=app --cov-report=term-missing`: 12 tests passed
- Application coverage: 81%

## Security and integrity behaviors tested

- Public registration always creates a student, even if a privileged role is submitted.
- Coaches cannot create or approve source records.
- Source approval requires an administrator.
- Published exam items use immutable question snapshots.
- Duplicate response writes are idempotent.
- Stale response writes are rejected.
- Server-side deadlines automatically close expired attempts.
- Authentication and duplicate registration behavior.
- Rights-policy default denial.
- Basic scoring and full exam/remediation flow.

## Known testing gaps

Crawler network behavior is structured for SSRF and redirect protection but still needs mocked integration tests for DNS, robots directives, redirects, oversized bodies, and unsupported content types. Production readiness also requires load tests, browser recovery tests, PostgreSQL migration tests, accessibility tests, security scanning, and backup restoration drills.
