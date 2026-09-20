#!/usr/bin/env bash
# Review a course, repair what the review faults, and do it again until it stops finding things.
#
# Three machine-authored courses were reviewed on the same afternoon and came back at 45%, 64%
# and 65% approval. That is not a bad run; it is what a first draft is. The reviewer names a
# specific, checkable error — "3.9 micrometres described as a water-vapour channel", "the Mohs
# reference list is wrong", "gradient is determined by discharge" — and the author can act on
# exactly that. Doing it by hand, per course, is the part that does not scale.
#
# The loop stops when a round produces no rejections and no revisions, or after --rounds passes,
# whichever comes first. It does NOT stop when the approval rate looks good: a single lesson
# teaching something false is the failure this exists to prevent.
#
# What it will never do: mark anything reviewed by a human, or publish. A pass here means the
# automated reviewer stopped objecting, which is the floor, not the bar.
#
#   scripts/harden_course.sh dynamic-planet-b-2027
#   scripts/harden_course.sh meteorology-b-2027 --rounds 4 --corrections data/review/x.json
set -uo pipefail

EVENT="${1:?usage: harden_course.sh <event-slug> [--rounds N] [--corrections FILE]}"
shift
ROUNDS=3
CORRECTIONS=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rounds) ROUNDS="${2:?}"; shift 2 ;;
    --corrections) CORRECTIONS="${2:?}"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

BLUEPRINT="data/courses/${EVENT}.json"
[[ -f "$BLUEPRINT" ]] || { echo "no blueprint at $BLUEPRINT" >&2; exit 2; }
: "${DATABASE_URL:?set DATABASE_URL}"
export PYTHONPATH=. PYTHONUNBUFFERED=1

for (( round=1; round<=ROUNDS; round++ )); do
  echo "=============== $EVENT — review round $round of $ROUNDS"
  out="$(env -u OPENAI_API_KEY python -m scripts.agentic_course_review \
          --event "$EVENT" --include-drafts --apply 2>&1)"
  echo "$out" | tail -20
  # Ask the DATABASE which lessons stand faulted at their current version, rather than
  # counting fault lines in the reviewer's output. The reviewer SKIPS a lesson whose current
  # version it has already judged, so a course with four standing rejections and nothing new
  # to read prints no fault lines at all — and this loop read that silence as success and
  # stopped. It reported "clean after 1 round" at the exact moment it had run out of things
  # to try. A gate that cannot fail is not a gate.
  faults="$(env -u OPENAI_API_KEY python -m scripts.faulted_lessons --event "$EVENT" --quiet)"
  if [[ "$faults" -eq 0 ]]; then
    echo "=============== $EVENT — clean after $round round(s)"
    exit 0
  fi
  if [[ "$round" -eq "$ROUNDS" ]]; then
    echo "=============== $EVENT — STILL FAULTED after $ROUNDS rounds ($faults lessons)" >&2
    env -u OPENAI_API_KEY python -m scripts.faulted_lessons --event "$EVENT" >&2 || true
    exit 1
  fi
  echo "=============== $EVENT — repairing $faults lesson(s)"
  args=(--blueprint "$BLUEPRINT" --apply --generate --allow-live --repair)
  # Findings from outside this pipeline are applied on the FIRST repair only. They describe the
  # draft a human read; once the lesson has been rewritten they are about a version that no
  # longer exists, and re-applying them would ask the author to fix text that is already gone.
  if [[ -n "$CORRECTIONS" && "$round" -eq 1 ]]; then
    args+=(--corrections "$CORRECTIONS")
  fi
  env -u OPENAI_API_KEY python -m scripts.author_course_from_blueprint "${args[@]}" \
    | python3 -c 'import json, sys; d = json.load(sys.stdin); print("   repaired %d, failed %d" % (d["generated_lessons"], len(d["failed"])))'
done
