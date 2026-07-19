from pathlib import Path
from contextlib import contextmanager

import httpx
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Event, Exam, ExamItem, Lesson, LessonVersion, Question, RawArtifact,
    PracticeSet, PracticeSetVersion, ScientificClaim, Source, SourceChange, SourceSnapshot,
)
from app.services.crawler import crawl_source


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def public_dns(*args, **kwargs):
    return [(2, 1, 6, "", ("8.8.8.8", 443))]


class ConditionalClient:
    def __init__(self, mode):
        self.mode = mode

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, url, **kwargs):
        request = httpx.Request("GET", url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /", request=request)
        if self.mode == "not_modified":
            assert kwargs["headers"]["If-None-Match"] == '"version-1"'
            return httpx.Response(304, request=request)
        if self.mode == "material":
            text = (
                "<html><head><title>Changed</title></head><body>"
                "Official rule correction: the required mineral formula and safety unit changed."
                "</body></html>"
            )
            etag = '"version-2"'
        else:
            text = (
                "<html><head><title>Initial</title></head><body>"
                "Mineral hardness is resistance to scratching."
                "</body></html>"
            )
            etag = '"version-1"'
        return httpx.Response(
            200,
            text=text,
            headers={
                "content-type": "text/html; charset=utf-8",
                "etag": etag,
                "last-modified": "Mon, 01 Jun 2026 12:00:00 GMT",
            },
            request=request,
        )

    @contextmanager
    def stream(self, method, url, **kwargs):
        yield self.get(url, **kwargs)


def test_conditional_fetch_raw_storage_and_material_change_quarantine(
    client, admin_token, monkeypatch,
):
    monkeypatch.setattr("app.services.crawler.socket.getaddrinfo", public_dns)
    monkeypatch.setattr(
        "app.services.crawler.httpx.Client",
        lambda *args, **kwargs: ConditionalClient("initial"),
    )
    with SessionLocal() as db:
        source = Source(
            url="https://science.nasa.gov/minerals",
            title="Minerals",
            rights_status="fact_grounding_allowed",
            approved=True,
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        source_id = source.id
        crawl_source(db, source)
        snapshot = db.scalar(select(SourceSnapshot).where(SourceSnapshot.source_id == source.id))
        artifact = db.scalar(select(RawArtifact).where(RawArtifact.snapshot_id == snapshot.id))
        assert snapshot.change_kind == "initial"
        assert artifact.scan_status == "basic_pass"
        assert Path("/tmp/science_olympiad_test_artifacts", artifact.storage_key).exists()

        event = Event(slug="source-change", name="Source Change", division="B", season=2026)
        db.add(event)
        db.flush()
        concept = Concept(event_id=event.id, name="Mineral properties")
        db.add(concept)
        db.flush()
        claim = ScientificClaim(
            source_id=source.id,
            concept_id=concept.id,
            claim_text="Hardness is resistance to scratching.",
            approved=True,
        )
        db.add(claim)
        db.flush()
        question = Question(
            event_id=event.id,
            concept_id=concept.id,
            source_id=source.id,
            status="published",
            stem="Which property describes resistance to scratching?",
            choices=["Hardness", "Luster"],
            answer_spec={"correct_index": 0, "points": 1},
            generation_provenance={"claim_ids": [claim.id]},
        )
        lesson = Lesson(
            event_id=event.id,
            concept_id=concept.id,
            slug="source-change",
            title="Source Change",
            status="published",
            current_version=1,
        )
        db.add_all([question, lesson])
        db.flush()
        db.add(LessonVersion(
            lesson_id=lesson.id,
            version=1,
            content=[],
            claim_ids=[claim.id],
            review_status="sme_approved",
        ))
        practice_set = PracticeSet(
            event_id=event.id,
            concept_id=concept.id,
            slug="affected-practice",
            title="Affected Practice",
            status="published",
            current_version=1,
        )
        db.add(practice_set)
        db.flush()
        db.add(PracticeSetVersion(
            practice_set_id=practice_set.id,
            version=1,
            items=[],
            claim_ids=[claim.id],
            review_status="sme_approved",
        ))
        exam = Exam(
            event_id=event.id,
            title="Affected Exam",
            question_ids=[question.id],
            published=True,
        )
        db.add(exam)
        db.flush()
        db.add(ExamItem(
            exam_id=exam.id,
            question_id=question.id,
            question_version=1,
            position=0,
            snapshot={"stem": question.stem},
        ))
        db.commit()

    monkeypatch.setattr(
        "app.services.crawler.httpx.Client",
        lambda *args, **kwargs: ConditionalClient("not_modified"),
    )
    with SessionLocal() as db:
        crawl_source(db, db.get(Source, source_id))
        assert len(db.scalars(select(SourceSnapshot)).all()) == 1
        assert len(db.scalars(select(RawArtifact)).all()) == 1

    monkeypatch.setattr(
        "app.services.crawler.httpx.Client",
        lambda *args, **kwargs: ConditionalClient("material"),
    )
    with SessionLocal() as db:
        crawl_source(db, db.get(Source, source_id))
        snapshots = db.scalars(select(SourceSnapshot).order_by(SourceSnapshot.id)).all()
        change = db.scalar(select(SourceChange))
        assert len(snapshots) == 2
        assert snapshots[1].previous_snapshot_id == snapshots[0].id
        assert snapshots[1].change_kind == "material"
        assert change.review_status == "pending"
        assert change.impact["claims_quarantined"] == 1
        assert change.impact["practice_sets_quarantined"] == 1
        assert db.scalar(select(ScientificClaim)).approved is False
        assert db.scalar(select(Question)).status == "quarantined"
        assert db.scalar(select(Lesson)).status == "review_required"
        assert db.scalar(select(PracticeSet)).status == "review_required"
        assert db.scalar(select(Exam)).published is False
        change_id = change.id

    listed = client.get("/api/source-changes", headers=auth(admin_token))
    assert listed.status_code == 200
    assert listed.json()[0]["impact"]["questions_quarantined"] == 1
    reviewed = client.post(
        f"/api/source-changes/{change_id}/review",
        headers=auth(admin_token),
        json={"decision": "confirmed", "notes": "Authoritative correction requires review."},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["dependencies_remain_quarantined"] is True
