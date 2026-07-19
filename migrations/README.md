# Database migrations

This directory is the migration boundary for production deployments. The current MVP creates tables automatically for local development and tests. Before a shared production database is used, initialize Alembic and create a baseline revision from `app.models.entities`.

Recommended commands:

```bash
alembic init migrations
alembic revision --autogenerate -m "baseline production schema"
alembic upgrade head
```

Production must set `DATABASE_URL` to PostgreSQL and must not rely on `Base.metadata.create_all` as the deployment migration mechanism.
