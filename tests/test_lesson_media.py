from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, EventSourceMap, Lesson, LessonVersion, Source, SourcePassage, SourceSnapshot
from app.services.lesson_media import compose_multimedia_blocks


def test_multimedia_composer_pairs_grounded_video_and_visual_observation(client):
    with SessionLocal() as db:
        event = Event(slug="rocks-and-minerals-b-2027", name="Rocks and Minerals", division="B", season=2027)
        source = Source(
            url="https://www.youtube.com/watch?v=abc12345678", title="Rocks field demonstration",
            publisher="Science Olympiad TV", approved=True, rights_status="derivative_generation_allowed",
            metadata_json={"kind": "youtube_transcript", "video_id": "abc12345678"},
        )
        db.add_all([event, source])
        db.flush()
        snapshot = SourceSnapshot(
            source_id=source.id, final_url=source.url, content_hash="a" * 64,
            content_type="text/plain", extracted_text="Quartz and calcite show different observable evidence.",
            metadata_json={"kind": "youtube_transcript", "video_id": "abc12345678", "title": "Rocks field demonstration", "channel": "Science Olympiad TV"},
        )
        db.add(snapshot)
        db.flush()
        db.add(SourcePassage(
            source_id=source.id, source_snapshot_id=snapshot.id, sequence=1,
            locator="00:00", passage_type="video_transcript", text="Compare quartz and calcite by observable evidence.", content_hash="b" * 64,
        ))
        db.add(EventSourceMap(
            event_id=event.id, source_id=source.id, purpose="video", source_tier=0,
            source_universe_version="test", reviewed=True,
        ))
        db.commit()
        blocks = compose_multimedia_blocks(db, event, [{
            "id": "opening", "type": "opening", "heading": "Observe minerals", "body": "Compare quartz and calcite before naming them.",
        }, {
            "id": "check", "type": "checkpoint", "heading": "Check", "question": "Which property helps?", "choices": ["Hardness", "Guess"], "correct_index": 0,
        }])
        assert [block["type"] for block in blocks] == ["opening", "video", "image_gallery", "checkpoint"]
        gallery = next(block for block in blocks if block["type"] == "image_gallery")
        assert len(gallery["images"]) >= 2
        video = next(block for block in blocks if block["type"] == "video")
        assert video["video_id"] == "abc12345678"
        assert video["passage_ids"]


def test_staff_media_enrichment_versions_published_lessons(client, admin_token):
    with SessionLocal() as db:
        event = Event(slug="rocks-and-minerals-b-2027", name="Rocks and Minerals", division="B", season=2027)
        source = Source(
            url="https://www.youtube.com/watch?v=def12345678", title="Mineral demonstration",
            approved=True, rights_status="derivative_generation_allowed",
        )
        db.add_all([event, source])
        db.flush()
        snapshot = SourceSnapshot(
            source_id=source.id, final_url=source.url, content_hash="c" * 64,
            extracted_text="Quartz and calcite evidence.",
            metadata_json={"kind": "youtube_transcript", "video_id": "def12345678", "title": "Mineral demonstration"},
        )
        db.add(snapshot)
        db.flush()
        db.add(EventSourceMap(event_id=event.id, source_id=source.id, purpose="video", source_tier=0, source_universe_version="test", reviewed=True))
        lesson = Lesson(event_id=event.id, slug="published-minerals", title="Mineral lesson", summary="Text", status="published", current_version=1, estimated_minutes=10)
        db.add(lesson)
        db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=1, review_status="published", content=[
            {"id": "opening", "type": "opening", "heading": "Observe", "body": "Compare quartz and calcite."},
        ]))
        db.commit()
        lesson_id = lesson.id
        event_id = event.id

    response = client.post("/api/content/lessons/media-enrich", headers={"Authorization": f"Bearer {admin_token}"}, data={"event_id": str(event_id)})
    assert response.status_code == 200
    assert response.json()["new_versions"] == [lesson_id]
    with SessionLocal() as db:
        lesson = db.get(Lesson, lesson_id)
        assert lesson.status == "draft" and lesson.current_version == 2
        version = db.scalar(select(LessonVersion).where(LessonVersion.lesson_id == lesson_id, LessonVersion.version == 2))
        assert [block["type"] for block in version.content] == ["opening", "video", "image_gallery"]
