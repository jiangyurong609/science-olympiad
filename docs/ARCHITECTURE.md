# Architecture and Next Build Stages

## Current vertical slice

The application is a modular FastAPI monolith with domain services for rights policy, crawling, generation, scoring, and remediation. It deliberately demonstrates the complete student loop:

`event → generated questions → published exam → timed attempt → saved responses → scoring → root-cause case → reflection → delayed review`

## Recommended next stages

1. Add organization, school, team, guardian, and consent models with strict tenant-scoped authorization.
2. Move PostgreSQL migrations to Alembic and add row-level security or equivalent authorization tests.
3. Add Temporal workflows for crawl, parse, source review, generation, validation, pilot, and publication.
4. Implement claim-level knowledge records and citation spans.
5. Add an OpenAI-compatible model gateway with generator, solver, critic, and pedagogy roles.
6. Add symbolic/numeric validators for units, algebra, chemistry, statistics, circuits, astronomy, and graph tasks.
7. Add MinHash, embeddings, and perceptual-hash similarity checks.
8. Add station, laboratory, constructed-response, diagram, team, and build-event response types.
9. Add item calibration, classical test theory metrics, and eventually IRT.
10. Generate near-transfer, far-transfer, and delayed-review questions automatically.
11. Add coach analytics, assignments, alerts, and team mock tournaments.
12. Add privacy request workflows, audit logs, SSO, rate limits, observability, backup tests, and penetration testing.
