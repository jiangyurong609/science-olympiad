"""A generated citation must carry a real passage id, never null.

`_attach_passage_citations` creates the source's passages on demand with
`ensure_source_passages(..., commit=False)`. That call added the rows without flushing, so the
objects it handed back still had `id is None` — and the author wrote `source_passage_id: null`
into the citation. The review queue resolves evidence by passage id, so those lessons showed
"no retained source passages are attached" and could not be approved.

It only hit the first lesson generated per source, because the next `db.flush()` in the author
loop assigned the ids for everyone after it. That is why it survived: 16 of 19 repaired events
had exactly one ungrounded lesson and the rest looked fine.
"""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Source, SourceSnapshot, SourcePassage
from app.services.source_passages import ensure_source_passages


def _snapshot(db):
    source = Source(
        title="Passage Source", url="https://example.org/passages.pdf", publisher="Example",
        approved=True, rights_status="public_domain", content_hash="passageids",
        extracted_text="Feldspar is a rock-forming mineral group. " * 60,
    )
    db.add(source)
    db.flush()
    snapshot = SourceSnapshot(
        source_id=source.id, final_url=source.url, content_hash="passageids",
        extracted_text=source.extracted_text,
    )
    db.add(snapshot)
    db.flush()
    return source, snapshot


def test_uncommitted_passages_still_come_back_with_ids():
    with SessionLocal() as db:
        _source, snapshot = _snapshot(db)
        passages = ensure_source_passages(db, snapshot, commit=False)
        assert passages, "the snapshot should yield at least one passage"
        assert all(p.id is not None for p in passages), (
            "a caller citing these by id would write source_passage_id: null"
        )
        db.rollback()


def test_attached_citations_never_carry_a_null_passage_id():
    from app.services.lesson_generation import _attach_passage_citations

    with SessionLocal() as db:
        source, snapshot = _snapshot(db)
        # no passages exist yet, so the author must create them mid-call — the exact path
        # that produced null ids
        assert not db.scalars(select(SourcePassage).where(
            SourcePassage.source_id == source.id)).all()

        blocks = [
            {"type": "opening", "heading": "Feldspar", "body": "Feldspar is a mineral group."},
            {"type": "summary", "heading": "Recap", "points": ["Feldspar is rock-forming."]},
        ]
        enriched, citations = _attach_passage_citations(db, source, blocks)

        assert citations, "the lesson must end up grounded"
        assert all(c["source_passage_id"] is not None for c in citations), (
            f"null passage id in citations: {citations}"
        )
        for block in enriched:
            assert all(pid is not None for pid in block.get("passage_ids", []))
        db.rollback()
