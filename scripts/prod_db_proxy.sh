#!/usr/bin/env bash
# Start the Cloud SQL Auth Proxy to the prod Postgres (soplat-pg) on localhost.
#
# One-time prerequisite (interactive, opens a browser):
#     gcloud auth application-default login
# Also needs Docker running.
#
# Usage:
#   scripts/prod_db_proxy.sh [PORT]     # default port 5434
#   scripts/prod_db_proxy.sh stop       # stop the proxy
set -euo pipefail

PROJECT="video-agent-493605"
INSTANCE="${PROJECT}:us-central1:soplat-pg"
ADC="${HOME}/.config/gcloud/application_default_credentials.json"
CONTAINER="soplatproxy"

if [[ "${1:-}" == "stop" ]]; then
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  echo "proxy stopped."
  exit 0
fi

PORT="${1:-5434}"
if [[ ! -f "$ADC" ]]; then
  echo "No Application Default Credentials file at ${ADC}." >&2
  echo "Run once:  gcloud auth application-default login" >&2
  exit 1
fi

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" -p "127.0.0.1:${PORT}:5432" \
  -v "${ADC}:/adc.json:ro" -e GOOGLE_APPLICATION_CREDENTIALS=/adc.json \
  gcr.io/cloud-sql-connectors/cloud-sql-proxy:latest \
  --address 0.0.0.0 --port 5432 "$INSTANCE" >/dev/null

sleep 8
docker logs "$CONTAINER" 2>&1 | tail -3
echo "Proxy listening on 127.0.0.1:${PORT} -> ${INSTANCE}"
echo "Prod DATABASE_URL (for scripts): postgresql+psycopg2://soplat_app:<PASS>@127.0.0.1:${PORT}/soplat"
echo "Get <PASS> from: gcloud secrets versions access latest --secret=soplat-database-url"
