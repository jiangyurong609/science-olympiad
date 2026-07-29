FROM python:3.12-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends clamav clamav-freshclam \
    && freshclam --stdout \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml LICENSE ./
RUN pip install --no-cache-dir .
COPY . .
EXPOSE 8000
# Cloud Run supplies PORT; default to 8000 for local/docker-compose use.
# Migrations run at startup so the schema always matches the code.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
