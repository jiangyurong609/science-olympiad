from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import (
    Event, EventSourceMap, EventTaxonScope, Lesson, LessonVersion, PracticeSet,
    PracticeSetVersion,
    ScientificClaim, Source, SpecimenAsset, Taxon,
)
from scripts.seed import main as seed_main


def test_seed_is_idempotent_and_publishes_grounded_launch_courses():
    seed_main()
    seed_main()

    with SessionLocal() as db:
        rocks = db.scalar(select(Event).where(Event.slug == "rocks-and-minerals"))
        ecology = db.scalar(select(Event).where(Event.slug == "ecology"))
        assert rocks and ecology
        assert rocks.season_status == "current"
        assert ecology.season_status == "foundational"

        ecology_lesson = db.scalar(select(Lesson).where(
            Lesson.event_id == ecology.id,
            Lesson.slug == "read-energy-through-food-webs",
        ))
        ecology_lab = db.scalar(select(PracticeSet).where(
            PracticeSet.event_id == ecology.id,
            PracticeSet.slug == "food-web-evidence-lab",
        ))
        assert ecology_lesson.status == "published"
        assert ecology_lab.status == "published"
        assert db.scalar(select(func.count()).select_from(Lesson).where(
            Lesson.slug == "read-energy-through-food-webs"
        )) == 1
        assert db.scalar(select(func.count()).select_from(PracticeSet).where(
            PracticeSet.slug == "food-web-evidence-lab"
        )) == 1

        lesson_version = db.scalar(select(LessonVersion).where(
            LessonVersion.lesson_id == ecology_lesson.id,
            LessonVersion.version == 1,
        ))
        lab_version = db.scalar(select(PracticeSetVersion).where(
            PracticeSetVersion.practice_set_id == ecology_lab.id,
            PracticeSetVersion.version == 1,
        ))
        assert lesson_version.review_status == "sme_approved"
        assert len(lesson_version.content) == 7
        assert len(lab_version.items) == 5
        assert lesson_version.claim_ids and lesson_version.citations
        assert lab_version.claim_ids and lab_version.citations

        source_ids = {citation["source_id"] for citation in lesson_version.citations}
        claims = db.scalars(select(ScientificClaim).where(
            ScientificClaim.id.in_(lesson_version.claim_ids)
        )).all()
        assert claims and all(claim.approved and claim.source_id in source_ids for claim in claims)
        sources = db.scalars(select(Source).where(Source.id.in_(source_ids))).all()
        assert sources and all(source.approved for source in sources)

        checkpoints = [
            block for block in lesson_version.content if block.get("type") == "checkpoint"
        ]
        assert len(checkpoints) >= 2
        for checkpoint in checkpoints:
            assert 0 <= checkpoint["correct_index"] < len(checkpoint["choices"])
            assert checkpoint["explanation"]
            assert len(set(checkpoint["choices"])) == len(checkpoint["choices"])
        for item in lab_version.items:
            assert item["id"] and item["prompt"] and item["property_profile"]
            assert 0 <= item["correct_index"] < len(item["choices"])
            assert len(set(item["choices"])) == len(item["choices"])
            assert item["explanation"]
            assert all(
                0 <= int(index) < len(item["choices"])
                for index in item.get("misconception_by_choice", {})
            )

        entomology = db.scalar(select(Event).where(Event.slug == "entomology"))
        entomology_lesson = db.scalar(select(Lesson).where(
            Lesson.event_id == entomology.id,
            Lesson.slug == "read-the-insect-body-plan",
        ))
        entomology_lab = db.scalar(select(PracticeSet).where(
            PracticeSet.event_id == entomology.id,
            PracticeSet.slug == "insect-anatomy-evidence-lab",
        ))
        assert entomology_lesson and entomology_lab
        assert db.scalar(select(func.count()).select_from(Taxon)) == 3
        assert db.scalar(select(func.count()).select_from(EventTaxonScope).where(
            EventTaxonScope.event_id == entomology.id
        )) == 3
        candidate = db.scalar(select(SpecimenAsset))
        assert candidate.rights_status == "metadata_only"
        assert candidate.review_status == "pending"
        assert candidate.alt_text and candidate.long_description
        assert db.scalar(select(func.count()).select_from(EventSourceMap).where(
            EventSourceMap.event_id == rocks.id
        )) == 3
        assert db.scalar(select(func.count()).select_from(EventSourceMap).where(
            EventSourceMap.event_id == ecology.id
        )) == 3
        assert db.scalar(select(func.count()).select_from(EventSourceMap).where(
            EventSourceMap.event_id == entomology.id
        )) == 4
