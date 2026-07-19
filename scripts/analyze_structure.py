"""LLM structure analysis: learn an event's real test blueprint from a past test.

For each event that has an imported past test, the model reads the test's text and
produces a blueprint (sections + weights, recommended size/time, question-type and
cognitive-level mix). Merged with the pool-derived profile and cached under
data/blueprints/ for structure-aware mock assembly.

Usage:
  python -m scripts.analyze_structure --all
  python -m scripts.analyze_structure --event <event_id>
"""
from __future__ import annotations

import json
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Exam, Source, SourceSnapshot
from app.services.blueprint import derive_blueprint, save_blueprint
from app.services.mock_exam import event_question_pool
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider

_SYSTEM = (
    "You analyze the STRUCTURE of a Science Olympiad test (not its answers). "
    "Given the test's raw text, return STRICT JSON: {\"sections\":[{\"name\":str,"
    "\"approx_questions\":int}], \"recommended_size\":int, \"recommended_minutes\":int, "
    "\"type_mix\":{\"single_choice\":float,\"short_answer\":float,\"numeric\":float}, "
    "\"cognitive_mix\":{\"recall\":float,\"application\":float,\"analysis\":float}, "
    "\"notes\":str}. Fractions in each *_mix sum to ~1. Base it on the real test's "
    "organization and question styles. Output only the JSON object."
)


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _past_test_source(db, event_id: int) -> Source | None:
    exam = db.scalar(select(Exam).where(
        Exam.event_id == event_id, Exam.release_class == "past_test"
    ).order_by(Exam.id))
    if not exam:
        return None
    return db.get(Source, (exam.blueprint or {}).get("exam_source_id"))


def analyze_event(db, event: Event, provider: OpenAICompatibleProvider) -> dict | None:
    source = _past_test_source(db, event.id)
    if not source:
        return None
    snap = db.scalar(select(SourceSnapshot).where(
        SourceSnapshot.source_id == source.id
    ).order_by(SourceSnapshot.id.desc()))
    text = (snap.extracted_text if snap else "") or ""
    if len(text.strip()) < 400:
        return None
    user = json.dumps({"event": event.name, "division": event.division, "test_text": text[:20000]})
    llm = provider.generate_json(_SYSTEM, user).payload
    # The real parsed length is a reliable floor; the model sometimes under-counts
    # on truncated/answer-key-heavy text.
    exam = db.scalar(select(Exam).where(
        Exam.event_id == event.id, Exam.release_class == "past_test"
    ).order_by(Exam.id))
    parsed_count = (exam.blueprint or {}).get("question_count") if exam else None
    rec_size = llm.get("recommended_size")
    if not isinstance(rec_size, int) or rec_size < 5:
        rec_size = parsed_count or rec_size
    blueprint = {
        "source": "llm",
        "analyzed_source_id": source.id,
        "sections": llm.get("sections", []),
        "recommended_size": rec_size,
        "recommended_minutes": llm.get("recommended_minutes"),
        "type_mix": llm.get("type_mix", {}),
        "cognitive_mix": llm.get("cognitive_mix", {}),
        "notes": str(llm.get("notes", ""))[:600],
        "derived": derive_blueprint(event_question_pool(db, event)),
    }
    return blueprint


def main() -> None:
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise SystemExit("External model provider is not configured")
    with SessionLocal() as db:
        if "--event" in sys.argv:
            targets = [db.get(Event, int(_arg("--event")))]
        elif "--all" in sys.argv:
            ids = {e.event_id for e in db.scalars(
                select(Exam).where(Exam.release_class == "past_test")
            ).all()}
            targets = [db.get(Event, i) for i in sorted(ids)]
        else:
            raise SystemExit(__doc__)
        print(f"Analyzing structure for {len(targets)} event(s)…\n")
        done = 0
        for i, event in enumerate(targets, start=1):
            try:
                blueprint = analyze_event(db, event, provider)
                if not blueprint:
                    print(f"[{i}/{len(targets)}] skip {event.slug}: no past-test source")
                    continue
                path = save_blueprint(event, blueprint)
                secs = len(blueprint.get("sections") or [])
                print(f"[{i}/{len(targets)}] {event.slug:26} {secs} sections, "
                      f"rec_size={blueprint.get('recommended_size')} -> {path}")
                done += 1
            except (ModelProviderError, Exception) as exc:  # noqa: BLE001
                print(f"[{i}/{len(targets)}] FAIL {event.slug}: {str(exc)[:90]}")
        print(f"\nDone: {done} blueprints written.")


if __name__ == "__main__":
    main()
