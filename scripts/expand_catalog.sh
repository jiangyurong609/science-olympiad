#!/usr/bin/env bash
# Bring the catalog forward one stage at a time, safely re-runnable.
#
# Every stage here is idempotent: grounding skips sentences it already harvested (and now
# approves and re-files the ones it does), generation adds items rather than replacing them,
# video skips lessons that already have a storyboard, and exam assembly rebuilds from whatever
# currently clears the gates. So this can be killed at any point and started again — which is
# necessary, because long runs in this environment are routinely stopped part-way.
#
#   scripts/expand_catalog.sh ground     # harvest + approve evidence for every mapped event
#   scripts/expand_catalog.sh items      # generate + gate items where evidence exists
#   scripts/expand_catalog.sh video      # narrate and render lessons whose blocks are grounded
#   scripts/expand_catalog.sh hints      # write and verify checkpoint hints
#   scripts/expand_catalog.sh exams      # reassemble and reclassify practice exams
#   scripts/expand_catalog.sh status     # what is done and what remains
#
# Run stages in that order the first time; after that any stage may be run alone.
set -u

cd "$(dirname "$0")/.."
export PYTHONPATH=.
: "${DATABASE_URL:?set DATABASE_URL (use scripts/prod_db_proxy.sh for production)}"
SIGNER="${GCS_SIGNING_SERVICE_ACCOUNT:-696895430749-compute@developer.gserviceaccount.com}"

py() { env -u OPENAI_API_KEY python "$@"; }

events_needing() {   # $1 = python predicate module-level helper name
  py - "$1" <<'PY'
import sys
from collections import Counter
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.entities import Concept, Event, Lesson, LessonVersion, ScientificClaim, VideoStoryboard
from scripts.open_sources import domain_for_event
want = sys.argv[1]
with SessionLocal() as db:
    events = {e.id: e for e in db.scalars(select(Event).where(Event.active.is_(True))).all()}
    concepts = {c.id: c for c in db.scalars(select(Concept)).all()}
    approved = set()
    for claim in db.scalars(select(ScientificClaim).where(ScientificClaim.approved.is_(True))).all():
        concept = concepts.get(claim.concept_id)
        if concept:
            approved.add(concept.event_id)
    lessons = Counter()
    for lesson in db.scalars(select(Lesson).where(Lesson.status == "published")).all():
        lessons[lesson.event_id] += 1
    boarded = {b.lesson_id for b in db.scalars(select(VideoStoryboard)).all()}
    versions = {(v.lesson_id, v.version): v for v in db.scalars(select(LessonVersion)).all()}
    video_ready = set()
    for lesson in db.scalars(select(Lesson).where(Lesson.status == "published")).all():
        if lesson.id in boarded:
            continue
        version = versions.get((lesson.id, lesson.current_version))
        if any(b.get("claim_ids") for b in (version.content if version else []) or []):
            video_ready.add(lesson.event_id)
    for event_id, _ in lessons.most_common():
        event = events.get(event_id)
        if not event or not domain_for_event(event.slug):
            continue
        if want == "ground":
            print(event.slug)                                    # re-runs approve existing claims
        elif want == "items" and event_id in approved:
            print(event.slug)
        elif want == "video" and event_id in video_ready:
            print(event.slug)
        elif want == "hints":
            print(event.slug)
PY
}

stage="${1:-status}"
case "$stage" in
  ground)
    events_needing ground | while read -r ev; do
      echo "== ground $ev"
      py -m scripts.ground_event --event "$ev" --apply --approve 2>&1 | grep -E "verified claims" | head -1
    done ;;
  items)
    events_needing items | while read -r ev; do
      echo "== items $ev"
      py -m scripts.regenerate_course --event "$ev" --per-concept 2 --run-id "expand-$ev" 2>&1 | tail -3
    done ;;
  video)
    events_needing video | while read -r ev; do
      echo "== video $ev"
      py -m scripts.produce_lesson_videos --event "$ev" --apply --render --impersonate "$SIGNER" 2>&1 | tail -4
    done ;;
  hints)
    events_needing hints | while read -r ev; do
      echo "== hints $ev"
      py -m scripts.write_checkpoint_hints --event "$ev" --apply 2>&1 | tail -4
    done ;;
  exams)
    py -m scripts.build_launch_exams --all --apply 2>&1 | tail -20
    py -m scripts.audit_topical_fit --top 15 2>&1 | tail -12 ;;
  status)
    py -m scripts.audit_launch_readiness --top 5 2>&1 | tail -16 ;;
  *)
    echo "unknown stage '$stage' (ground|items|video|hints|exams|status)"; exit 2 ;;
esac
