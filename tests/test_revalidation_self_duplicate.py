"""Re-validating a stored question must not flag it as a duplicate of itself.

`validate_candidate` scans every stored stem for near-duplicates, which is correct for a new
candidate. Re-running it over an item already in the catalog compares the stem against its own
row, scores 1.0, and returns `near_duplicate_question` — so an item could never be re-validated
into a passing state no matter how good it is.
"""
from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Event, Question, QuestionStatus, ScientificClaim, Source, SourceSnapshot,
)


STEM = "Which mineral property is measured on the Mohs scale in a station event?"
CHOICES = ["Hardness", "Streak", "Luster", "Density"]


def _stored_question(db):
    event = Event(slug="reval", name="Reval", division="C", season=2026)
    db.add(event)
    db.flush()
    concept = Concept(event_id=event.id, name="Properties", description="d")
    db.add(concept)
    db.flush()
    source = Source(
        title="Reval Source", url="https://example.org/reval.pdf", publisher="Example",
        approved=True, rights_status="public_domain", content_hash="reval",
        extracted_text="Hardness is measured on the Mohs scale. " * 40,
    )
    db.add(source)
    db.flush()
    snapshot = SourceSnapshot(
        source_id=source.id, final_url=source.url, content_hash="reval",
        extracted_text=source.extracted_text,
    )
    db.add(snapshot)
    db.flush()
    claim = ScientificClaim(
        source_id=source.id, source_snapshot_id=snapshot.id, concept_id=concept.id,
        claim_text="Hardness is measured on the Mohs scale.",
        evidence_excerpt="Hardness is measured on the Mohs scale.",
        locator="p1", confidence=0.9, approved=True,
    )
    db.add(claim)
    db.flush()
    question = Question(
        event_id=event.id, concept_id=concept.id, source_id=source.id,
        status=QuestionStatus.MACHINE_VALIDATED.value, question_type="single_choice",
        stem=STEM, choices=CHOICES,
        answer_spec={"correct_index": 0, "points": 1},
        explanation="Mohs measures hardness.",
        citations=[{"source_id": source.id, "claim_id": claim.id}],
        difficulty=0.5, cognitive_level="recall", estimated_seconds=60,
        validation_report={}, similarity_report={},
    )
    db.add(question)
    db.commit()
    return question.id, claim.id, source.id


def test_revalidating_a_stored_item_does_not_match_itself():
    from app.services.validation import validate_candidate

    with SessionLocal() as db:
        question_id, claim_id, source_id = _stored_question(db)

        without = validate_candidate(
            db, stem=STEM, choices=CHOICES, answer_spec={"correct_index": 0},
            claim_ids=[claim_id], source_id=source_id,
        )
        assert "near_duplicate_question" in without["errors"], (
            "sanity check: the stored row should collide with itself when not excluded"
        )

        with_exclusion = validate_candidate(
            db, stem=STEM, choices=CHOICES, answer_spec={"correct_index": 0},
            claim_ids=[claim_id], source_id=source_id,
            exclude_question_id=question_id,
        )
        assert with_exclusion["errors"] == [], with_exclusion["errors"]
        assert with_exclusion["passed"] is True
        assert with_exclusion["factual_grounding"] == "approved_claims"
        assert with_exclusion["claim_ids"] == [claim_id]


def test_excluding_one_item_still_catches_a_real_duplicate():
    """The exclusion must be surgical: another item with the same stem still blocks."""
    from app.services.validation import validate_candidate

    with SessionLocal() as db:
        question_id, claim_id, source_id = _stored_question(db)
        twin = Question(
            event_id=db.get(Question, question_id).event_id,
            concept_id=db.get(Question, question_id).concept_id,
            source_id=source_id, status=QuestionStatus.DRAFT.value,
            question_type="single_choice", stem=STEM, choices=CHOICES,
            answer_spec={"correct_index": 0, "points": 1}, explanation="dup",
            citations=[], difficulty=0.5, cognitive_level="recall",
            estimated_seconds=60, validation_report={}, similarity_report={},
        )
        db.add(twin)
        db.commit()

        report = validate_candidate(
            db, stem=STEM, choices=CHOICES, answer_spec={"correct_index": 0},
            claim_ids=[claim_id], source_id=source_id,
            exclude_question_id=question_id,
        )
        assert "near_duplicate_question" in report["errors"], (
            "excluding the item under review must not hide a genuine duplicate"
        )
