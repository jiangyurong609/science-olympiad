"""Two payloads with the same locator AND the same text must not both be inserted.

`uq_source_passage_locator` is on (source_snapshot_id, locator, content_hash). A PDF can
produce two payloads that agree on both — a scanned answer key whose repeated block of
"ANS: C PTS: 1" lines chunks identically under the same page locator does. Inserting both
raises UniqueViolation, which ends the extraction run for every snapshot after it and stops
a course build two steps before authoring. That is how the Food Science build died.
"""
import app.services.source_passages as module
from app.models.entities import SourceSnapshot


class _FakeSession:
    """Just enough Session for ensure_source_passages: no existing rows, collect adds."""

    def __init__(self):
        self.added = []

    def scalars(self, *_args, **_kwargs):
        return self

    def all(self):
        return []

    def add(self, row):
        self.added.append(row)

    def commit(self):
        pass

    def flush(self):
        pass


def test_a_repeated_locator_and_text_is_inserted_once(monkeypatch):
    duplicate = {"locator": "Page 1", "heading": "Page 1", "passage_type": "pdf_page",
                 "text": "ANS: C PTS: 1", "metadata_json": {"page": 1}}
    distinct = {"locator": "Page 2", "heading": "Page 2", "passage_type": "pdf_page",
                "text": "ANS: C PTS: 1", "metadata_json": {"page": 2}}
    monkeypatch.setattr(module, "extract_passage_payloads",
                        lambda _snapshot: [duplicate, dict(duplicate), distinct])

    snapshot = SourceSnapshot(source_id=1, final_url="local://x.pdf", content_hash="",
                              content_type="application/pdf", byte_count=1,
                              extracted_text="x", change_kind="initial")
    snapshot.id = 3359
    session = _FakeSession()

    rows = module.ensure_source_passages(session, snapshot, commit=False)

    keys = [(r.locator, r.content_hash) for r in rows]
    assert len(keys) == len(set(keys)), "a duplicate (locator, hash) reached the insert"
    # Same text under a DIFFERENT locator is a real second passage and is kept.
    assert len(rows) == 2
    assert {r.locator for r in rows} == {"Page 1", "Page 2"}
