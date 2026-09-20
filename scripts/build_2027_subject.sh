#!/usr/bin/env bash
# Take one 2027 subject from a blueprint to a hardened draft course, in the right order.
#
# The order is not obvious and two of the steps fail SILENTLY when skipped, which cost two
# authoring runs before it was written down:
#
#   scaffold BEFORE grounding — `harvest_claims` matches each claim to an existing Concept and
#     rejects the rest as `no_matching_concept`. Grounding an event whose 2027 concepts do not
#     exist yet looks like a bad source set: Meteorology produced 129 claims that way and 1,955
#     once the scaffold was there.
#   extract AFTER grounding — grounding writes `SourceSnapshot.extracted_text`; the author reads
#     `SourcePassage` rows, which only `extract_source_passages` creates. Skip it and the event
#     has every source, the full text of each, and nothing the author can see.
#
# Every step is idempotent, so re-running after an interruption resumes rather than repeats.
# It runs ONE python process at a time on purpose: running six of these in parallel is what
# put this laptop into memory pressure and had the OS kill the lot of them mid-run.
#
#   DATABASE_URL=... scripts/build_2027_subject.sh solar-system-b-2027
#   DATABASE_URL=... scripts/build_2027_subject.sh botany-b-2027 --skip-harden
set -uo pipefail

EVENT="${1:?usage: build_2027_subject.sh <event-slug> [--skip-harden] [--rounds N]}"
shift
HARDEN=true
ROUNDS=3
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-harden) HARDEN=false; shift ;;
    --rounds) ROUNDS="${2:?}"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

BLUEPRINT="data/courses/${EVENT}.json"
[[ -f "$BLUEPRINT" ]] || { echo "no blueprint at $BLUEPRINT" >&2; exit 2; }
: "${DATABASE_URL:?set DATABASE_URL}"
export PYTHONPATH=. PYTHONUNBUFFERED=1
# A step that dies must stop the subject. Without this the script sails past a killed grounding
# run straight into authoring and writes a course from whatever fraction of the corpus had been
# extracted when the OS ran out of memory — a plausible, quietly thin course rather than an error.
#
# `check` is called AFTER each pipeline rather than wrapping it, because the left-hand side of a
# pipe runs in a subshell: an `exit` inside a wrapper would end the subshell and let the script
# carry on, which is exactly the failure this is here to prevent.
step() { echo; echo "---- $EVENT: $1"; }
check() {
  local status=$1 label=$2
  if [[ "$status" -ne 0 ]]; then
    echo "!!!! $EVENT: '$label' exited $status — stopping before the next step" >&2
    exit "$status"
  fi
}

# `--allow-live` because every 2027 event already serves one video "event strategy" lesson, so
# without it the scaffold refuses every subject in the season.
step "scaffold (creates the concepts grounding needs)"
python -m scripts.author_course_from_blueprint --blueprint "$BLUEPRINT" --apply --allow-live \
  | grep -E '"units"|"planned_lessons"|"failed"'
check "${PIPESTATUS[0]}" scaffold

step "ground on the open sources"
python -m scripts.ground_event --event "$EVENT" --apply \
  | grep -E "open sources|verified claims|blocks supported|skills supported|committed|duplicate body|FETCH FAILED|connection dropped"
check "${PIPESTATUS[0]}" ground

step "extract passages (the step the author actually reads)"
python -m scripts.extract_source_passages --apply | grep -E '"passages"|"snapshots_extracted"'
check "${PIPESTATUS[0]}" extract

step "audit keywords against the corpus they will author from"
python -m scripts.audit_blueprint_keywords --blueprint "$BLUEPRINT" \
  | python3 -c 'import json, sys; d = json.load(sys.stdin); print("   %d of %d keywords match nothing" % (d.get("missing_keywords", 0), d.get("keywords", 0))); [print("   MISS", m["lesson"], m["keywords"]) for m in d.get("misses", [])]'
check "${PIPESTATUS[0]}" audit

step "author the lessons"
env -u OPENAI_API_KEY python -m scripts.author_course_from_blueprint \
    --blueprint "$BLUEPRINT" --apply --generate --allow-live \
  | python3 -c 'import json, sys; d = json.load(sys.stdin); print("   generated %d, failed %d" % (d["generated_lessons"], len(d["failed"]))); [print("   FAIL", f["lesson"], f["reason"][:90]) for f in d["failed"]]; [print("   GAP ", u["lesson"], u["missing"]) for u in d.get("uncovered", [])]'
check "${PIPESTATUS[0]}" author

# Ground once more, now that the lessons exist. `attach_to_blocks` links each claim to the
# lesson blocks it supports, and it can only do that for blocks that are there — grounding
# before authoring reports "blocks supported: 7/13" against the one pre-existing video lesson
# and nothing else, so coverage reads as near-zero for a course that is in fact well grounded.
# Cheap now: the snapshots are cached and the claims are deduped in one query per source.
step "re-ground to attach claims to the lessons just written"
python -m scripts.ground_event --event "$EVENT" --apply \
  | grep -E "verified claims|blocks supported|skills supported|committed"
check "${PIPESTATUS[0]}" reground

if [[ "$HARDEN" == true ]]; then
  echo; echo "---- $EVENT: review and repair until clean"
  bash scripts/harden_course.sh "$EVENT" --rounds "$ROUNDS"
fi
echo; echo "==== $EVENT done"
