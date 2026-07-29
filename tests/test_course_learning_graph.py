from sqlalchemy import delete, func, select

from app.core.database import SessionLocal
from app.core.security import create_access_token, hash_password
from app.models.entities import (
    AssessmentBlueprint, ContentGap, ContentMigrationMap, Course, CourseSourceCoverage,
    CourseUnit, CourseVersion, Event, EventSourceMap, Exam, ExamItem, Lesson,
    LessonProgress, LessonSkill, LessonVersion, Question, ReviewDecision, Skill,
    Source, SourcePassage, SourceSnapshot, User,
)
from app.services.source_passages import ensure_source_passages, extract_passage_payloads
from scripts.migrate_legacy_learning_graph import migrate
from scripts.reconcile_content_inventory import build_report
from scripts.build_material_coverage_ledger import build as build_coverage


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def seed_course():
    with SessionLocal() as db:
        event = Event(
            slug="rocks-b-2027", name="Rocks & Minerals",
            division="B", season=2027, category="Earth Science",
        )
        db.add(event)
        db.flush()
        course = Course(
            event_id=event.id, slug="rocks-b-2027",
            title="Rocks & Minerals", summary="Identify specimens from evidence.",
            status="published", current_version=1,
        )
        db.add(course)
        db.flush()
        db.add(CourseVersion(
            course_id=course.id, version=1,
            objectives=["Identify minerals from observable properties."],
            review_status="sme_approved",
        ))
        unit = CourseUnit(
            course_id=course.id, slug="physical-properties",
            title="Physical Properties", summary="Use diagnostic observations.",
            sequence=1, status="published",
        )
        db.add(unit)
        db.flush()
        skill = Skill(
            course_id=course.id, unit_id=unit.id,
            slug="hardness", name="Use the Mohs Scale",
            description="Compare scratch resistance.", sequence=1,
            status="published",
        )
        db.add(skill)
        db.flush()
        lesson = Lesson(
            event_id=event.id, slug="hardness",
            title="Measure Hardness", summary="Run a scratch test.",
            status="published", current_version=1, sequence=1,
            estimated_minutes=8,
        )
        db.add(lesson)
        db.flush()
        db.add(LessonVersion(
            lesson_id=lesson.id, version=1,
            review_status="sme_approved",
            content=[{"type": "opening", "heading": "Hardness"}],
        ))
        db.add(LessonSkill(lesson_id=lesson.id, skill_id=skill.id, is_primary=True))
        db.add(AssessmentBlueprint(
            course_id=course.id, unit_id=unit.id,
            assessment_type="unit_quiz", version=1,
            title="Physical Properties Quiz",
            specification={"question_count": 5}, status="published",
        ))
        user = User(
            email="course@example.com", full_name="Course Student",
            password_hash=hash_password("password123"), role="student", division="B",
        )
        db.add(user)
        reviewer = User(
            email="reviewer@example.com", full_name="Course Reviewer",
            password_hash=hash_password("password123"), role="editor", division="B",
        )
        db.add(reviewer)
        db.flush()
        db.add_all([
            ReviewDecision(
                entity_type="lesson", entity_id=lesson.id, entity_version=1,
                stage=stage, decision="approved", reviewer_user_id=reviewer.id,
            )
            for stage in ("editor", "sme")
        ])
        db.commit()
        return (
            event.season, event.slug, course.id, unit.id, skill.id, lesson.id,
            create_access_token(str(user.id)),
        )


def test_course_map_has_units_skills_lessons_and_assessments(client):
    season, event_slug, _, _, _, _, token = seed_course()
    response = client.get(
        f"/api/courses/{season}/{event_slug}",
        headers=auth(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Rocks & Minerals"
    assert body["progress"] == {
        "mastered_skills": 0, "total_skills": 1, "percent": 0,
    }
    assert body["units"][0]["title"] == "Physical Properties"
    assert body["units"][0]["skills"][0]["mastery"]["level"] == "not_started"
    assert body["units"][0]["skills"][0]["lessons"][0]["title"] == "Measure Hardness"
    assert body["units"][0]["assessments"][0]["type"] == "unit_quiz"


def test_course_page_has_stable_shareable_url(client):
    response = client.get("/courses/2027/rocks-and-minerals-b-2027")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, must-revalidate"
    assert "id=\"course-unit-list\"" in response.text
    lesson = client.get(
        "/courses/2027/rocks-and-minerals-b-2027/lesson/mineral-hardness",
    )
    assert lesson.status_code == 200
    assert lesson.headers["cache-control"] == "no-cache, must-revalidate"


def test_current_season_lesson_is_hidden_without_both_review_decisions(client):
    _, _, _, _, _, lesson_id, token = seed_course()
    with SessionLocal() as db:
        db.execute(delete(ReviewDecision).where(
            ReviewDecision.entity_type == "lesson",
            ReviewDecision.entity_id == lesson_id,
            ReviewDecision.stage == "sme",
        ))
        event_id = db.get(Lesson, lesson_id).event_id
        db.commit()
    listing = client.get(f"/api/events/{event_id}/lessons", headers=auth(token))
    assert listing.status_code == 200
    assert listing.json() == []
    assert client.post(
        f"/api/lessons/{lesson_id}/start", headers=auth(token),
    ).status_code == 404


def test_staff_can_preview_draft_lesson_while_students_cannot(client):
    season, event_slug, _, _, _, lesson_id, student_token = seed_course()
    with SessionLocal() as db:
        lesson = db.get(Lesson, lesson_id)
        lesson.status = "draft"
        course = db.scalar(select(Course).where(Course.event_id == lesson.event_id))
        course.status = "review_required"
        db.add(CourseUnit(
            course_id=course.id,
            slug="legacy-learning-path",
            title="Legacy Learning Path",
            sequence=10000,
            status="withdrawn",
        ))
        reviewer = db.scalar(select(User).where(User.email == "reviewer@example.com"))
        reviewer_token = create_access_token(str(reviewer.id))
        db.commit()
    assert client.get(
        f"/api/courses/{season}/{event_slug}", headers=auth(student_token),
    ).status_code == 404
    staff_course = client.get(
        f"/api/courses/{season}/{event_slug}", headers=auth(reviewer_token),
    )
    assert staff_course.status_code == 200
    assert len(staff_course.json()["units"]) == 1
    assert staff_course.json()["units"][0]["skills"][0]["lessons"][0]["id"] == lesson_id
    assert client.post(
        f"/api/lessons/{lesson_id}/start", headers=auth(student_token),
    ).status_code == 404
    assert client.post(
        f"/api/lessons/{lesson_id}/start", headers=auth(reviewer_token),
    ).status_code == 200


def test_lesson_review_queue_requires_complete_independent_editor_and_sme_reviews(client):
    _, _, _, _, _, lesson_id, _ = seed_course()
    with SessionLocal() as db:
        lesson = db.get(Lesson, lesson_id)
        lesson.status = "draft"
        course = db.scalar(select(Course).where(Course.event_id == lesson.event_id))
        course.status = "review_required"
        version = db.scalar(select(LessonVersion).where(
            LessonVersion.lesson_id == lesson.id,
            LessonVersion.version == lesson.current_version,
        ))
        version.review_status = "ai_draft"
        source = Source(
            url="https://example.org/review-guide",
            title="Review Guide",
            publisher="Science Source",
        )
        db.add(source)
        db.flush()
        snapshot = SourceSnapshot(
            source_id=source.id,
            final_url=source.url,
            content_hash="lesson-review-snapshot",
            content_type="text/html",
            byte_count=50,
            extracted_text="Hardness is resistance to scratching.",
        )
        db.add(snapshot)
        db.flush()
        passage = SourcePassage(
            source_id=source.id,
            source_snapshot_id=snapshot.id,
            sequence=1,
            locator="Hardness section",
            passage_type="html_section",
            text="Hardness is resistance to scratching.",
            content_hash="lesson-review-passage",
        )
        db.add(passage)
        db.flush()
        version.content = [{
            "id": "hardness-teach",
            "type": "steps",
            "heading": "Measure hardness",
            "passage_ids": [passage.id],
        }]
        version.citations = [{
            "source_id": source.id,
            "source_snapshot_id": snapshot.id,
            "source_passage_id": passage.id,
        }]
        db.execute(delete(ReviewDecision).where(
            ReviewDecision.entity_type == "lesson",
            ReviewDecision.entity_id == lesson.id,
        ))
        editor = db.scalar(select(User).where(User.email == "reviewer@example.com"))
        sme = User(
            email="lesson-sme@example.com",
            full_name="Independent Lesson SME",
            password_hash=hash_password("password123"),
            role="sme",
            division="B",
        )
        db.add(sme)
        db.flush()
        editor_token = create_access_token(str(editor.id))
        sme_token = create_access_token(str(sme.id))
        db.commit()

    queue = client.get(
        "/api/content/lessons/review-queue",
        headers=auth(editor_token),
    )
    assert queue.status_code == 200
    assert queue.json()[0]["next_stage"] == "editor"
    assert queue.json()[0]["preview_url"].endswith("/lesson/hardness")
    assert queue.json()[0]["evidence"][0]["text"] == (
        "Hardness is resistance to scratching."
    )

    incomplete = client.post(
        f"/api/content/lessons/{lesson_id}/reviews",
        headers=auth(editor_token),
        json={
            "stage": "editor",
            "decision": "approved",
            "checklist": {"objective_measurable": True},
            "notes": "",
        },
    )
    assert incomplete.status_code == 422

    editor_checks = {
        "objective_measurable": True,
        "sequence_coherent": True,
        "reading_level_appropriate": True,
        "interactions_useful": True,
        "feedback_actionable": True,
        "no_ai_filler": True,
    }
    approved = client.post(
        f"/api/content/lessons/{lesson_id}/reviews",
        headers=auth(editor_token),
        json={
            "stage": "editor",
            "decision": "approved",
            "checklist": editor_checks,
            "notes": "The lesson sequence and feedback are clear.",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["review_status"] == "editor_reviewed"
    assert approved.json()["student_visible"] is False

    sme_checks = {
        "claims_supported": True,
        "citations_verified": True,
        "examples_accurate": True,
        "answer_keys_verified": True,
        "misconceptions_accurate": True,
        "competition_alignment": True,
    }
    approved = client.post(
        f"/api/content/lessons/{lesson_id}/reviews",
        headers=auth(sme_token),
        json={
            "stage": "sme",
            "decision": "approved",
            "checklist": sme_checks,
            "notes": "The scientific content and competition alignment are sound.",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["review_status"] == "sme_approved"
    assert approved.json()["student_visible"] is False

    queue = client.get(
        "/api/content/lessons/review-queue",
        headers=auth(sme_token),
    )
    assert queue.json()[0]["next_stage"] == "complete"


def test_release_manager_surfaces_blockers_and_version_diff(client):
    _, _, course_id, _, _, lesson_id, _ = seed_course()
    with SessionLocal() as db:
        admin = User(
            email="release-admin@example.com", full_name="Release Admin",
            password_hash=hash_password("password123"), role="admin", division="B",
        )
        db.add(admin)
        db.flush()
        lesson = db.get(Lesson, lesson_id)
        db.add(LessonVersion(
            lesson_id=lesson.id, version=2, review_status="draft",
            content=[{"type": "opening", "heading": "Hardness updated"}],
        ))
        db.commit()
        token = create_access_token(str(admin.id))
    response = client.get("/api/content/releases", headers=auth(token))
    assert response.status_code == 200
    row = next(item for item in response.json() if item["id"] == course_id)
    assert row["release_ready"] is False
    assert row["blockers"]
    diff = client.get(
        f"/api/content/lessons/{lesson_id}/versions/diff?from_version=1&to_version=2",
        headers=auth(token),
    )
    assert diff.status_code == 200
    assert diff.json()["changed_blocks"][0]["position"] == 1
    blocked = client.post(
        f"/api/content/releases/{course_id}",
        data={"decision": "preview", "notes": "Try preview"},
        headers=auth(token),
    )
    assert blocked.status_code == 409
    assert "blockers" in blocked.json()["detail"]
def test_content_staff_can_audit_source_coverage_and_open_gaps(client):
    _, _, course_id, unit_id, skill_id, lesson_id, _ = seed_course()
    with SessionLocal() as db:
        source = Source(
            url="https://example.org/rocks", title="Official Rocks Guide",
            approved=True, rights_status="fact_grounding_allowed",
        )
        db.add(source)
        db.flush()
        snapshot = SourceSnapshot(
            source_id=source.id, final_url=source.url, content_hash="coverage",
            content_type="text/html", byte_count=20, extracted_text="Mineral evidence.",
        )
        db.add(snapshot)
        db.flush()
        db.add(SourcePassage(
            source_id=source.id, source_snapshot_id=snapshot.id, sequence=1,
            locator="Section 1", passage_type="html_section",
            text="Mineral evidence.", content_hash="passage",
        ))
        db.add(CourseSourceCoverage(
            course_id=course_id, source_id=source.id, source_snapshot_id=snapshot.id,
            source_type="text/html", authority_tier=1, instructional_role="lesson_evidence",
            extraction_status="extracted", rights_status="fact_grounding_allowed",
            passage_count=1, claim_count=0, mapped_unit_ids=[unit_id],
            mapped_skill_ids=[skill_id], lesson_ids=[lesson_id],
            review_status="approved", student_destination=f"/lesson/{lesson_id}",
        ))
        db.add(ContentGap(
            course_id=course_id, unit_id=unit_id, skill_id=skill_id,
            gap_type="transfer_item", description="Needs an unseen transfer item.",
        ))
        reviewer = db.scalar(select(User).where(User.email == "reviewer@example.com"))
        token = create_access_token(str(reviewer.id))
        db.commit()
    response = client.get(
        f"/api/content/courses/{course_id}/coverage", headers=auth(token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["sources"] == 1
    assert body["summary"]["passages"] == 1
    assert body["summary"]["open_gaps"] == 1
    assert body["summary"]["release_ready"] is False
    assert body["sources"][0]["skills"][0]["name"] == "Use the Mohs Scale"
    quality = client.get(
        f"/api/content/courses/{course_id}/quality", headers=auth(token),
    )
    assert quality.status_code == 200
    assert quality.json()["release_ready"] is False
    assert quality.json()["blocker_counts"]["question_volume"] == 1
    assert quality.json()["blocker_counts"]["release_missing"] == 1


def test_material_coverage_builder_is_idempotent(client):
    _, _, course_id, _, _, _, _ = seed_course()
    with SessionLocal() as db:
        course = db.get(Course, course_id)
        source = Source(
            url="https://example.org/reference", title="Reference",
            approved=False, rights_status="link_only",
        )
        db.add(source)
        db.flush()
        db.add(EventSourceMap(
            event_id=course.event_id, source_id=source.id,
            purpose="reference_material", source_tier=2,
            source_universe_version="test",
        ))
        db.commit()
        first = build_coverage(db, apply=True, course_id=course_id)
        second = build_coverage(db, apply=True, course_id=course_id)
        assert first["rows_created"] == 1
        assert second["rows_created"] == 0
        assert db.scalar(select(func.count()).select_from(CourseSourceCoverage)) == 1


def test_course_map_reports_mastery_and_lesson_resume(client):
    season, event_slug, _, _, skill_id, lesson_id, token = seed_course()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "course@example.com"))
        skill = db.get(Skill, skill_id)
        skill.concept_id = None
        db.add(LessonProgress(
            user_id=user.id, lesson_id=lesson_id, lesson_version=1,
            status="in_progress", current_block=1,
        ))
        db.commit()
    response = client.get(
        f"/api/courses/{season}/{event_slug}",
        headers=auth(token),
    )
    lesson_payload = response.json()["units"][0]["skills"][0]["lessons"][0]
    assert lesson_payload["progress"]["status"] == "in_progress"
    assert lesson_payload["progress"]["current_block"] == 1


def test_source_passages_cover_pdf_pages_and_video_timestamps():
    with SessionLocal() as db:
        source = Source(url="https://example.org/source.pdf", title="Source")
        db.add(source)
        db.flush()
        pdf = SourceSnapshot(
            source_id=source.id, final_url=source.url, content_hash="pdf",
            content_type="application/pdf", byte_count=100,
            extracted_text="[Page 1]\nFirst page evidence.\n\n[Page 2]\nSecond page evidence.",
        )
        db.add(pdf)
        db.flush()
        rows = ensure_source_passages(db, pdf, commit=False)
        assert [row.locator for row in rows] == ["Page 1", "Page 2"]
        assert "First page" in rows[0].text

        video = SourceSnapshot(
            source_id=source.id, final_url="https://youtu.be/abcdefghijk",
            content_hash="video", content_type="text/vtt; profile=transcript",
            byte_count=100,
            extracted_text="[0.0s] Observe color.\n[15.2s] Test hardness.\n[95.0s] Record evidence.",
            metadata_json={"kind": "youtube_transcript"},
        )
        payloads = extract_passage_payloads(video)
        assert payloads[0]["passage_type"] == "video_transcript"
        assert payloads[0]["locator"].startswith("Video 00:00")
        assert "[01:35]" in payloads[0]["text"]


def test_source_passages_preserve_and_bound_unstructured_text():
    text = "A" * 5_100
    snapshot = SourceSnapshot(
        source_id=1, final_url="https://example.org/ocr.txt",
        content_hash="ocr", content_type="text/plain", byte_count=len(text),
        extracted_text=text,
    )
    payloads = extract_passage_payloads(snapshot)
    assert "".join(row["text"] for row in payloads) == text
    assert max(len(row["text"]) for row in payloads) <= 2_400


def test_legacy_migration_preserves_exam_snapshot_and_student_history():
    with SessionLocal() as db:
        event = Event(slug="legacy-rocks", name="Legacy Rocks", division="B", season=2026)
        db.add(event)
        db.flush()
        lesson = Lesson(
            event_id=event.id, slug="legacy-lesson", title="Legacy Lesson",
            status="published", current_version=1,
        )
        db.add(lesson)
        db.flush()
        db.add(LessonVersion(lesson_id=lesson.id, version=1, content=[]))
        question = Question(
            event_id=event.id, status="draft", stem="Legacy question?",
            choices=["A", "B"], answer_spec={"correct_index": 0},
        )
        db.add(question)
        db.flush()
        exam = Exam(
            event_id=event.id, title="Legacy Exam", duration_minutes=10,
            question_ids=[question.id], published=True, release_class="past_test",
        )
        db.add(exam)
        db.flush()
        snapshot = {"stem": "Frozen legacy question?", "answer_spec": {"correct_index": 0}}
        db.add(ExamItem(
            exam_id=exam.id, question_id=question.id, question_version=1,
            position=0, snapshot=snapshot,
        ))
        db.commit()
        before = db.scalar(select(ExamItem).where(ExamItem.exam_id == exam.id)).snapshot.copy()
        report = migrate(db, apply=True)
        counts_before = {
            "skills": db.scalar(select(func.count()).select_from(Skill)),
            "links": db.scalar(select(func.count()).select_from(LessonSkill)),
            "maps": db.scalar(select(func.count()).select_from(ContentMigrationMap)),
        }
        migrate(db, apply=True)
        counts_after = {
            "skills": db.scalar(select(func.count()).select_from(Skill)),
            "links": db.scalar(select(func.count()).select_from(LessonSkill)),
            "maps": db.scalar(select(func.count()).select_from(ContentMigrationMap)),
        }
        after = db.scalar(select(ExamItem).where(ExamItem.exam_id == exam.id)).snapshot
        assert report["exam_snapshots_rewritten"] is False
        assert counts_after == counts_before
        assert before == after
        assert db.scalar(select(Course).where(Course.event_id == event.id))
        assert db.scalar(select(ContentMigrationMap).where(
            ContentMigrationMap.legacy_type == "exam",
            ContentMigrationMap.legacy_id == exam.id,
        )).migration_state == "immutable_snapshot_preserve"
        ledger = build_report(db)
        assert ledger["release_gates"]["events_without_course"] == 0
        assert ledger["counts"]["lesson_skill_links"] == 1
        assert ledger["migration_state_counts"]["immutable_snapshot_preserve"] == 1
