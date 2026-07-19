# Implementation Progress v3

## Added in v3

- Guardian-consent gate for students under 13, including one-time consent tokens and inactive accounts until consent is granted.
- Scientific claim registry linked to approved sources and concepts.
- Administrator approval workflow for scientific claims.
- Grounded generation validation with approved-claim checks, source-rights checks, answer-index checks, duplicate-choice checks, and existing-question similarity detection.
- Distractor-specific misconception tags in generated multiple-choice questions.
- Unseen transfer-question workflow after student reflection.
- Transfer scoring, retry routing, delayed-review scheduling, and concept mastery updates.
- Student mastery API with mastery probability, evidence count, misconception risk, and next review date.
- Browser UI for guardian-aware registration and transfer-question completion.
- Alembic configuration and baseline schema migration.
- Expanded automated tests for guardian consent, claim-grounded generation, transfer remediation, and mastery updates.

## Still required before school deployment

- Transactional email delivery for guardian consent, verification, and password reset.
- Real model-provider integration with structured outputs and independent model critics.
- Claim extraction from crawled documents with human review.
- PDF, image, dataset, and table ingestion.
- Delayed-review worker and far-transfer generation.
- Organization memberships, team rosters, coach dashboards, and school SSO.
- PostgreSQL production configuration, rate limiting, centralized audit export, load testing, and penetration testing.
