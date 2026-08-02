"""A source approval is about the content that was read, not about the URL.

`CourseSourceCoverage` pins the snapshot an editor approved, and nothing compared it against
the source's current snapshot — so a re-crawl could replace the content while the approval sat
unchanged. This is the fourth appearance of one mistake in this codebase: an approval attached
to a thing rather than to a version of it. The others were a release manifest that did not pin
lesson titles, `student_preview` skipping the review check, and a lesson keeping its exposure
decision through a rewrite.
"""
from __future__ import annotations

import itertools

from app.core.database import SessionLocal
from app.models.entities import (
    Course, CourseSourceCoverage, CourseUnit, Event, Source, SourceSnapshot,
)
from app.services.course_quality import audit_course

_UNIQUE = itertools.count(1)


def _fixture(db, *, recrawl: bool, review_status: str = "approved"):
    n = next(_UNIQUE)
    event = Event(slug=f"sa-ev-{n}", name="E", division="B", season=2026)
    db.add(event); db.flush()
    course = Course(event_id=event.id, slug=f"sa-c-{n}", title="C", status="draft")
    db.add(course); db.flush()
    db.add(CourseUnit(course_id=course.id, slug=f"sa-u-{n}", title="U", sequence=1))
    source = Source(url=f"https://example.org/s-{n}", title="S",
                    rights_status="public_domain", approved=True)
    db.add(source); db.flush()
    first = SourceSnapshot(source_id=source.id, final_url=source.url,
                           content_hash="a", extracted_text="original text")
    db.add(first); db.flush()
    db.add(CourseSourceCoverage(
        course_id=course.id, source_id=source.id, source_snapshot_id=first.id,
        instructional_role="reference_only", extraction_status="extracted",
        rights_status="public_domain", review_status=review_status))
    if recrawl:
        db.add(SourceSnapshot(source_id=source.id, final_url=source.url,
                              content_hash="b", extracted_text="the source changed"))
    db.flush()
    return course


def _codes(db, course):
    return {row["code"] for row in audit_course(db, course.id)["blockers"]}


def test_an_approval_survives_while_the_content_is_unchanged():
    with SessionLocal() as db:
        course = _fixture(db, recrawl=False)
        assert "source_review_stale" not in _codes(db, course)


def test_a_re_crawl_invalidates_the_approval():
    with SessionLocal() as db:
        course = _fixture(db, recrawl=True)
        assert "source_review_stale" in _codes(db, course)


def test_an_unapproved_source_reports_only_the_unapproved_blocker():
    """It is already blocking for review; adding a staleness blocker would double-count."""
    with SessionLocal() as db:
        course = _fixture(db, recrawl=True, review_status="unreviewed")
        codes = _codes(db, course)
    assert "source_review" in codes
    assert "source_review_stale" not in codes


def test_a_coverage_row_with_no_pinned_snapshot_is_not_reported_stale():
    """Nothing is known about what was approved, so nothing can be said about drift."""
    with SessionLocal() as db:
        course = _fixture(db, recrawl=True)
        row = db.query(CourseSourceCoverage).filter(
            CourseSourceCoverage.course_id == course.id).first()
        row.source_snapshot_id = None
        db.flush()
        assert "source_review_stale" not in _codes(db, course)
