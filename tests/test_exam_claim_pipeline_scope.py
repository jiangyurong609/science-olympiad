from app.core.database import SessionLocal
from app.models.entities import Event, Exam, ExamItem, Question, ScientificClaim, Source
from scripts.apply_claim_review import apply_verdicts
from scripts.link_exam_items_to_claims import _squash


def test_verbatim_check_ignores_only_whitespace():
    # a PDF snapshot breaks the quoted sentence across lines
    snapshot = "Outliers are commonly identified as being 1.5 times the IQR\noutside of the range"
    assert _squash("identified as being 1.5 times the IQR outside of") in _squash(snapshot)
    assert _squash("identified as 1.5 times the IQR") not in _squash(snapshot)


def _exam_with_unapproved_item(db, event, title):
    source = Source(url=f"https://example.org/{title}", title=title, publisher="x")
    db.add(source)
    db.flush()
    claim = ScientificClaim(source_id=source.id, claim_text="c", evidence_excerpt=f"claim {title}",
                            locator="", confidence=0.8, approved=False)
    db.add(claim)
    db.flush()
    question = Question(event_id=event.id, stem="stem", question_type="single_choice",
                        choices=["a", "b", "c", "d"], answer_spec={"correct_index": 0},
                        validation_report={"claim_ids": [claim.id]})
    db.add(question)
    db.flush()
    exam = Exam(event_id=event.id, title=title, question_ids=[question.id],
                release_class="machine_practice")
    db.add(exam)
    db.flush()
    db.add(ExamItem(exam_id=exam.id, question_id=question.id, position=0, snapshot={}))
    db.flush()
    return exam, claim


def test_claim_review_scoped_to_one_exam_leaves_other_papers_alone():
    with SessionLocal() as db:
        event = Event(slug="e-b-2027", name="E", division="B", season=2027, category="x")
        db.add(event)
        db.flush()
        reviewed, claim = _exam_with_unapproved_item(db, event, "reviewed")
        other, _ = _exam_with_unapproved_item(db, event, "other")
        db.commit()
        stats = apply_verdicts(db, approve={claim.id}, reject=set(), apply=True,
                               exam_ids={reviewed.id})
        db.refresh(other)
        assert stats["exams_touched"] == 0          # the reviewed paper's item is now grounded
        assert other.question_ids                   # the unreviewed paper kept its item
