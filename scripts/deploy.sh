#!/usr/bin/env bash
# Deploy the Science Olympiad platform (soplat-web) to Cloud Run.
#
# Builds the container image with Cloud Build (upload context respects
# .gcloudignore) and deploys it to the existing Cloud Run service, wiring the
# LLM (Sunra) config. Idempotent and safe to re-run: Cloud Run keeps prior
# revisions, so a bad deploy is an instant rollback (see the tip printed at the end).
#
# Usage:
#   scripts/deploy.sh                      # build a timestamped image and deploy
#   scripts/deploy.sh --tag v13            # build + deploy a specific tag
#   scripts/deploy.sh --skip-build --tag v12   # redeploy an already-built image
set -euo pipefail

PROJECT="video-agent-493605"
REGION="us-central1"
SERVICE="soplat-web"
IMAGE_REPO="us-central1-docker.pkg.dev/${PROJECT}/soplat/web"
# Azure OpenAI (resource soplat-llm, sub 8f3ae45d, eastus). Sunra ran dry 2026-08-15;
# the old pair was SUNRA_KEY + https://api-llm.sunra.ai/v1 + openai/gpt-5.5.
LLM_SECRET="AZURE_OPENAI_KEY"                  # Secret Manager secret -> OPENAI_API_KEY
LLM_BASE_URL="https://soplat-llm.openai.azure.com/openai/v1"
LLM_MODEL="gpt-5.6-luna"
# The image bundles ClamAV and refreshes signatures during the build. Override
# these only when using a separately provisioned scanner service.
ANTIVIRUS_COMMAND="${ANTIVIRUS_COMMAND:-clamscan --no-summary -}"
ANTIVIRUS_REQUIRED="${ANTIVIRUS_REQUIRED:-true}"
# Raw uploads are immutable production data. Keep them in the regional bucket
# rather than the ephemeral Cloud Run filesystem (override for local/staging).
ARTIFACT_STORE_BACKEND="${ARTIFACT_STORE_BACKEND:-gcs}"
ARTIFACT_STORE_BUCKET="${ARTIFACT_STORE_BUCKET:-soplat-artifacts-video-agent-493605}"
# Cloud Run's metadata credentials carry no private key, so signed playback URLs are minted by
# impersonating this account. It was set in .env and never in the deploy, so video worked from
# a developer shell and served nothing in production for as long as video existed.
GCS_SIGNING_SERVICE_ACCOUNT="${GCS_SIGNING_SERVICE_ACCOUNT:-696895430749-compute@developer.gserviceaccount.com}"
# Preflight gates. SKIP_PREFLIGHT=1 exists for an emergency rollback, not for convenience:
# every defect these catch reached students because nothing checked before a deploy.
SKIP_PREFLIGHT="${SKIP_PREFLIGHT:-0}"
# ClamAV loads a large signature database per scan process. Keep the scanner
# fail-closed without allowing concurrent uploads to exhaust the instance.
CLOUD_RUN_MEMORY="${CLOUD_RUN_MEMORY:-2Gi}"
# Concurrency 1 meant a single slow request — a large PDF scan, a cold DB pool — made every
# other request wait for a new instance, and Cloud Run returned "no available instance"
# aborts instead. Uploads appeared to hang and Refresh spun forever. ClamAV's signature
# database is the reason this was ever 1; 2Gi holds it comfortably for a handful of
# concurrent requests, and min-instances 1 removes the cold start that made it worse.
CLOUD_RUN_CONCURRENCY="${CLOUD_RUN_CONCURRENCY:-8}"
CLOUD_RUN_MIN_INSTANCES="${CLOUD_RUN_MIN_INSTANCES:-1}"

TAG=""
SKIP_BUILD=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG="${2:?}"; shift 2 ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done
[[ -z "$TAG" ]] && TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE="${IMAGE_REPO}:${TAG}"

cd "$(dirname "$0")/.."   # repo root

if [[ "$SKIP_PREFLIGHT" != "1" ]]; then
  echo "==> Preflight: test suite"
  python -m pytest -q -p no:warnings

  # A reference error in the reader breaks every view at once — "division is not defined"
  # blanked the whole workspace behind an error banner. This catches syntax only, which is
  # less than it should be, but it is the difference between a broken deploy and a caught one.
  if command -v node >/dev/null 2>&1; then
    echo "==> Preflight: client syntax"
    node --check app/static/app.js
  fi

  # What a student would actually see. Grounding, the solver and the topical screen all ask
  # whether content is well-formed or supported; none asks whether it renders. Four defects
  # reached students in a row — checkpoints with no question, cards showing the word
  # "Concept", slides with nothing in them, a worked example that threw and blanked the
  # reader — and every one was found by a person clicking, not by a gate.
  if [[ -n "${DATABASE_URL:-}" ]]; then
    echo "==> Preflight: rendered content audit"
    python -m scripts.audit_rendered_content --fail-on-defect
  else
    echo "==> Preflight: SKIPPED rendered content audit (no DATABASE_URL)"
    echo "    Run it against production before publishing:"
    echo "      scripts/prod_db_proxy.sh &"
    echo "      DATABASE_URL=<proxy-url> python -m scripts.audit_rendered_content --fail-on-defect"
  fi
  echo "==> Preflight passed"
fi

echo "==> Project ${PROJECT} | Service ${SERVICE} | Region ${REGION}"
echo "==> Image ${IMAGE}"

if [[ "$SKIP_BUILD" == false ]]; then
  echo "==> Building image via Cloud Build…"
  gcloud builds submit --project "$PROJECT" --region "$REGION" --tag "$IMAGE" .
fi

echo "==> Deploying to Cloud Run…"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" --region "$REGION" \
  --image "$IMAGE" \
  --update-env-vars "OPENAI_COMPATIBLE_BASE_URL=${LLM_BASE_URL},OPENAI_MODEL=${LLM_MODEL},REDIS_URL=${REDIS_URL:-redis://10.226.253.171:6379},ARTIFACT_STORE_BACKEND=${ARTIFACT_STORE_BACKEND},ARTIFACT_STORE_BUCKET=${ARTIFACT_STORE_BUCKET},ANTIVIRUS_COMMAND=${ANTIVIRUS_COMMAND},ANTIVIRUS_REQUIRED=${ANTIVIRUS_REQUIRED},GCS_SIGNING_SERVICE_ACCOUNT=${GCS_SIGNING_SERVICE_ACCOUNT}" \
  --memory "${CLOUD_RUN_MEMORY}" \
  --concurrency "${CLOUD_RUN_CONCURRENCY}" \
  --min-instances "${CLOUD_RUN_MIN_INSTANCES}" \
  --update-secrets "OPENAI_API_KEY=${LLM_SECRET}:latest" \
  --vpc-connector "${VPC_CONNECTOR:-soplat-connector}" \
  --vpc-egress private-ranges-only \
  --quiet

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
echo "==> Deployed: ${URL}"
curl -s -o /dev/null -w "    GET /            -> %{http_code}\n" "${URL}/" || true
curl -s -o /dev/null -w "    GET /api/events  -> %{http_code}\n" "${URL}/api/events" || true

PREV="$(gcloud run revisions list --project "$PROJECT" --region "$REGION" --service "$SERVICE" \
        --format='value(metadata.name)' --sort-by='~metadata.creationTimestamp' | sed -n 2p || true)"
echo "==> Rollback (if needed): gcloud run services update-traffic ${SERVICE} --region ${REGION} --to-revisions ${PREV:-<PRIOR>}=100"
