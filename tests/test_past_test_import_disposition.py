"""An imported past test must be startable the moment it is published.

`build_exam` published straight into `unreviewed_practice`, which exists for *historical*
content of unknown provenance and refuses new attempts outright. A freshly transcribed paper
whose every item is answerable and keyed is `imported_practice`: labelled just as loudly, but
serveable. The re-imported Meteorology paper went live and every student who clicked it was
told "no longer offered for new attempts", while the 47 imports already in production opened
normally.
"""
from app.models.entities import Event, Exam, ExamItem, Question
from app.services import student_visibility as sv
from app.services.past_test_import import build_exam
from app.core.database import SessionLocal


def _question(event_id: int, stem: str) -> Question:
    return Question(
        event_id=event_id, status="draft", stem=stem, question_type="single_choice",
        choices=["A", "B", "C", "D"],
        answer_spec={"correct_index": 0, "points": 1},
    )


def test_a_freshly_imported_paper_can_be_started(client, student_token):
    from app.models.entities import Source
    with SessionLocal() as db:
        event = Event(slug="import-disp", name="Import Disposition", division="B", season=2026)
        source = Source(url="local://import-disp.pdf", title="Import Disposition TEST",
                        publisher="test")
        db.add_all([event, source])
        db.flush()
        questions = [_question(event.id, f"Question {n}?") for n in range(3)]
        db.add_all(questions)
        db.flush()
        exam = build_exam(db, event, source, questions, "after_submit")
        db.commit()
        exam_id = exam.id
        assert exam.disposition == sv.DISPOSITION_IMPORTED_PRACTICE, \
            "unreviewed_practice refuses new attempts; a keyed transcription is not that"

    with SessionLocal() as db:
        exam = db.get(Exam, exam_id)
        allowed, reason = sv.can_start_new_attempt(db, exam)
        assert allowed, f"a published import must be startable, got: {reason}"
        assert sv.is_unreviewed_practice(exam), \
            "it is still unreviewed and every surface must keep saying so"

    started = client.post(f"/api/exams/{exam_id}/start",
                          headers={"Authorization": f"Bearer {student_token}"})
    assert started.status_code == 200, started.text
    assert started.json()["release_label"] == "Past Test · Transcribed, Not Reviewed"


def test_an_item_whose_answer_was_withheld_never_reaches_the_exam(monkeypatch):
    """The 2014 Heredity paper's key skips one question as "duplicate; omitted from the answer
    key". The question is kept as a draft for an editor to key later, but the served exam must
    hold only items the scorer can actually mark — an ungradeable item sits in an attempt as a
    question the student can answer and the platform can never score."""
    from app.models.entities import Source, SourceSnapshot
    from app.services import past_test_import as pti
    from app.services.scoring import is_gradeable

    keyed = {"label": "1", "stem": "Which nitrogenous base pairs with adenine in DNA?",
             "question_type": "single_choice",
             "choices": ["Thymine", "Cytosine", "Guanine", "Uracil"],
             "correct_index": 0, "has_key_source": True, "points": 1}
    key_omitted = {"label": "2", "stem": "In Drosophila, what should the offspring of this cross be?",
                   "question_type": "single_choice",
                   "choices": ["All red-eyed", "All white-eyed", "Red daughters, white sons"],
                   "correct_index": None, "has_key_source": True, "points": 1}
    monkeypatch.setattr(pti, "parse_items",
                        lambda *args, **kwargs: [dict(keyed), dict(key_omitted)])

    with SessionLocal() as db:
        event = Event(slug="withheld-serve", name="Withheld Serve", division="B", season=2026)
        source = Source(url="local://withheld-serve.pdf", title="Withheld Serve TEST",
                        publisher="test")
        db.add_all([event, source])
        db.flush()
        db.add(SourceSnapshot(source_id=source.id, final_url=source.url, content_hash="x" * 64,
                              extracted_text="[Page 1]\n1. ...\n2. ...\n"))
        db.flush()
        result = pti.import_past_test(db, event, source, key_source=source,
                                      build=True, commit=True)

        assert result["questions_created"] == 2, "the withheld item is still worth an editor's review"
        assert result["withheld_from_exam"] == 1
        exam = db.get(Exam, result["exam_id"])
        snapshots = [item.snapshot for item in db.query(ExamItem).filter_by(exam_id=exam.id)]
        assert len(snapshots) == 1
        assert all(is_gradeable(s["question_type"], s["answer_spec"]) for s in snapshots), \
            "every served item must clear the scorer's own bar"
