# Test Report — v4

- 18 automated tests passed.
- 81% application statement coverage.
- Ruff linting passed.
- Fresh Alembic migration through revision `0002_teams_generation` passed.
- Fresh database seed passed.
- Tests cover guardian consent, rights controls, immutable exams, ordered autosave, grounded generation, claim extraction, team tenant isolation, near-transfer remediation, and delayed-review resolution.

## Important interpretation

Coverage reflects the implemented application, not the entire long-term product plan. External LLM provider behavior, live web crawling, PDF variants, load testing, penetration testing, and browser accessibility testing require environment-specific validation.
