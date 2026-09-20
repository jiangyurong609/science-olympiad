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
run() { echo; echo "---- $EVENT: $1"; shift; "$@"; }

# `--allow-live` because every 2027 event already serves one video "event strategy" lesson, so
# without it the scaffold refuses every subject in the season.
run "scaffold (creates the concepts grounding needs)" \
  python -m scripts.author_course_from_blueprint --blueprint "$BLUEPRINT" --apply --allow-live \
  | grep -E '"units"|"planned_lessons"|"failed"'

run "ground on the open sources" \
  python -m scripts.ground_event --event "$EVENT" --apply \
  | grep -E "open sources|verified claims|blocks supported|skills supported|committed|duplicate body|FETCH FAILED|connection dropped"

run "extract passages (the step the author actually reads)" \
  python -m scripts.extract_source_passages --apply \
  | grep -E '"passages"|"snapshots_extracted"'

run "audit keywords against the corpus they will author from" \
  python -m scripts.audit_blueprint_keywords --blueprint "$BLUEPRINT" \
  | python3 -c 'import json, sys; d = json.load(sys.stdin); print(f"   {d.get(\"missing_keywords\", 0)} of {d.get(\"keywords\", 0)} keywords match nothing"); [print("   MISS", m["lesson"], m["keywords"]) for m in d.get("misses", [])]'

run "author the lessons" \
  env -u OPENAI_API_KEY python -m scripts.author_course_from_blueprint \
    --blueprint "$BLUEPRINT" --apply --generate --allow-live \
  | python3 -c 'import json, sys; d = json.load(sys.stdin); print(f"   generated {d[\"generated_lessons\"]}, failed {len(d[\"failed\"])}"); [print("   FAIL", f["lesson"], f["reason"][:90]) for f in d["failed"]]; [print("   GAP ", u["lesson"], u["missing"]) for u in d.get("uncovered", [])]'

if [[ "$HARDEN" == true ]]; then
  echo; echo "---- $EVENT: review and repair until clean"
  bash scripts/harden_course.sh "$EVENT" --rounds "$ROUNDS"
fi
echo; echo "==== $EVENT done"
