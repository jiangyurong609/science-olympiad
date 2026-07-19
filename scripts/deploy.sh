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
SUNRA_SECRET="SUNRA_KEY"                       # Secret Manager secret -> OPENAI_API_KEY
LLM_BASE_URL="https://api-llm.sunra.ai/v1"
LLM_MODEL="openai/gpt-5.5"

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
  --update-env-vars "OPENAI_COMPATIBLE_BASE_URL=${LLM_BASE_URL},OPENAI_MODEL=${LLM_MODEL},REDIS_URL=${REDIS_URL:-redis://10.226.253.171:6379}" \
  --update-secrets "OPENAI_API_KEY=${SUNRA_SECRET}:latest" \
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
