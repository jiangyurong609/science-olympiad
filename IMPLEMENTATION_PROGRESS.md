# Implementation Progress Against the Comprehensive Plan

## Completed in this iteration

### P0 security and correctness
- Public users cannot self-register as admin, editor, or coach.
- Staff permissions are split: administrators approve source rights; editors manage content; coaches manage exams only when approved content exists.
- Production rejects the default or short JWT secret.
- Inactive users cannot authenticate with existing tokens.
- Privileged actions create audit records.
- Organization-aware exam visibility has been added as a tenancy foundation.

### Exam integrity
- Published exams freeze question content into immutable `ExamItem` snapshots.
- Active attempts receive a server-side `deadline_at`.
- Expired attempts are automatically finalized by the server.
- A student re-opening an active exam resumes the same attempt.
- Autosave uses monotonic sequence numbers and idempotency keys.
- Duplicate writes are safe and stale writes are rejected.

### Source acquisition safety
- A source must be both rights-approved and approved by an administrator.
- Every redirect destination is rechecked against the domain allowlist.
- DNS results are rejected when they resolve to private, loopback, link-local, reserved, or multicast addresses.
- `robots.txt` is checked.
- Download size and content type are restricted.
- Each successful crawl creates an immutable source snapshot.

### Scoring and remediation
- Scoring supports single-choice, numeric tolerance, and normalized text answers.
- Distractor-specific error categories can be stored in answer specifications.
- Remediation plans explicitly require an unseen transfer item before final resolution.
- Reflections require meaningful minimum content.

### Verification
- 12 automated tests pass.
- Ruff lint passes.
- Fresh-database seed and login/exam-start smoke test passes.
- Application coverage is 81%.

## Still not complete

- Guardian consent, parent accounts, school rostering, SSO, and full tenant administration.
- Email verification, password recovery, MFA, refresh-token rotation, and rate limiting.
- Alembic production migration configuration and PostgreSQL integration testing.
- Durable Temporal or queue-based crawler workflows.
- PDF, image, table, and dataset extraction.
- Claim-level scientific knowledge graph.
- Real LLM gateway, independent solver/critic stages, and similarity service.
- Human editorial and SME review user interfaces.
- Station, laboratory, diagram, team, rubric, and build-event assessment modes.
- Actual near-transfer, far-transfer, and delayed-review question generation.
- Mastery modeling, spaced repetition, coach analytics, and notifications.
- Accessibility certification, load testing, penetration testing, and legal review.

The current repository is a substantially safer engineering MVP, but it remains an internal-development build rather than a public school-ready product.
