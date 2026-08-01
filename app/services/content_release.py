"""Phase 4 — atomic content releases with immutable membership.

`decide_content_release` used to flip `course.status` and write an audit line. Nothing
recorded *what* was released, so two things were impossible:

  * `audit_course` could never clear `release_missing`, because that asks for a published
    `ContentRelease` and none was ever created;
  * a rollback restored a version number but not the set of lessons, items, and sources that
    version actually contained — the course pointer moved while the content underneath it had
    already changed.

A release is therefore a manifest: the exact lesson versions, question versions, blueprints,
claims, and sources that were approved, plus a digest over all of it. Publishing writes that
manifest and moves the pointer in one transaction; rolling back re-points at an earlier
manifest. Membership is never edited after publication — a change means a new release.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    AssessmentBlueprint, ContentRelease, Course, CourseSourceCoverage, CourseUnit,
    Lesson, LessonSkill, LessonVersion, Question, ScientificClaim, Skill, User, now_utc,
)


class ReleaseError(RuntimeError):
    """Raised when a release cannot be built or promoted."""


def build_manifest(db: Session, course: Course) -> dict:
    """Snapshot exactly what this course consists of right now.

    Versions are recorded alongside ids because an id alone does not pin content: a lesson
    can be edited after release, and a manifest that named only the lesson would describe
    whatever it later became rather than what was approved.
    """
    units = db.scalars(select(CourseUnit).where(
        CourseUnit.course_id == course.id, CourseUnit.status != "withdrawn",
    ).order_by(CourseUnit.sequence)).all()
    skills = db.scalars(select(Skill).where(
        Skill.course_id == course.id, Skill.status != "withdrawn",
    ).order_by(Skill.sequence)).all()
    skill_ids = [s.id for s in skills]

    lesson_ids = sorted({
        link.lesson_id for link in db.scalars(select(LessonSkill).where(
            LessonSkill.skill_id.in_(skill_ids))).all()
    }) if skill_ids else []
    lessons = []
    for lesson in db.scalars(select(Lesson).where(
        Lesson.id.in_(lesson_ids), Lesson.status != "withdrawn",
    ).order_by(Lesson.sequence, Lesson.id)).all() if lesson_ids else []:
        version = db.scalar(select(LessonVersion).where(
            LessonVersion.lesson_id == lesson.id,
            LessonVersion.version == lesson.current_version))
        if version is None:
            raise ReleaseError(
                f"lesson {lesson.id} ({lesson.title!r}) has no row for its current version "
                f"{lesson.current_version}; a release cannot pin content that is missing"
            )
        # `title` is here because a release rehearsal on real content caught its absence:
        # renaming a lesson left the digest unchanged, so republishing was accepted and drift
        # reported nothing, even though what a student sees had changed. Any served field
        # missing from the manifest is a field the release cannot notice.
        lessons.append({"id": lesson.id, "slug": lesson.slug, "title": lesson.title,
                        "version": lesson.current_version,
                        "version_row_id": version.id, "status": lesson.status,
                        "estimated_minutes": lesson.estimated_minutes})

    concept_ids = [s.concept_id for s in skills if s.concept_id]
    questions = db.scalars(select(Question).where(
        Question.event_id == course.event_id,
        Question.concept_id.in_(concept_ids),
        Question.status == "published",
    ).order_by(Question.id)).all() if concept_ids else []

    claims = db.scalars(select(ScientificClaim).where(
        ScientificClaim.skill_id.in_(skill_ids), ScientificClaim.approved.is_(True),
    ).order_by(ScientificClaim.id)).all() if skill_ids else []

    manifest = {
        "course": {"id": course.id, "slug": course.slug, "version": course.current_version},
        "units": [{"id": u.id, "slug": u.slug, "sequence": u.sequence} for u in units],
        "skills": [{"id": s.id, "slug": s.slug, "concept_id": s.concept_id} for s in skills],
        "lessons": lessons,
        "questions": [{"id": q.id, "version": q.version, "status": q.status,
                       "cognitive_level": q.cognitive_level, "concept_id": q.concept_id}
                      for q in questions],
        "blueprints": [{"id": b.id, "unit_id": b.unit_id, "type": b.assessment_type,
                        "version": b.version, "status": b.status}
                       for b in db.scalars(select(AssessmentBlueprint).where(
                           AssessmentBlueprint.course_id == course.id
                       ).order_by(AssessmentBlueprint.id)).all()],
        "claims": [{"id": c.id, "source_id": c.source_id,
                    "source_passage_id": c.source_passage_id} for c in claims],
        "sources": [{"source_id": row.source_id, "role": row.instructional_role,
                     "rights_status": row.rights_status, "review_status": row.review_status}
                    for row in db.scalars(select(CourseSourceCoverage).where(
                        CourseSourceCoverage.course_id == course.id
                    ).order_by(CourseSourceCoverage.source_id)).all()],
    }
    manifest["counts"] = {key: len(manifest[key]) for key in
                          ("units", "skills", "lessons", "questions", "blueprints",
                           "claims", "sources")}
    manifest["digest"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return manifest


def publish_release(db: Session, actor: User, course: Course, notes: str = "") -> ContentRelease:
    """Write the manifest and move the active pointer in one transaction.

    The caller is responsible for having checked the quality gate; this refuses only the
    conditions that would make the release itself incoherent.
    """
    manifest = build_manifest(db, course)
    if not manifest["lessons"]:
        raise ReleaseError("a release must contain at least one lesson")

    existing = db.scalar(select(ContentRelease).where(
        ContentRelease.course_id == course.id,
        ContentRelease.version == course.current_version,
    ))
    if existing is not None and existing.status == "published":
        if existing.manifest.get("digest") == manifest["digest"]:
            return existing          # idempotent: same content, same version, same release
        raise ReleaseError(
            f"version {course.current_version} is already published with different content. "
            "Release membership is immutable — bump the course version instead."
        )

    # only one release may be active; supersede rather than delete, so history survives
    for row in db.scalars(select(ContentRelease).where(
        ContentRelease.course_id == course.id,
        ContentRelease.status == "published",
    )).all():
        row.status = "superseded"

    release = existing or ContentRelease(course_id=course.id, version=course.current_version)
    release.manifest = manifest
    release.status = "published"
    release.release_notes = notes
    release.published_by_user_id = actor.id if actor else None
    release.published_at = now_utc()
    db.add(release)
    db.flush()
    return release


def restore_from_manifest(db: Session, manifest: dict) -> dict:
    """Put the rows a student reads back to what the manifest pinned.

    Rollback used to move `course.current_version` and mark a manifest active, and stop there.
    Student lesson reads resolve `lesson.current_version`, not the manifest, so a lesson edited
    to v2 kept being served after a rollback to release v1: the audit record said one thing and
    the product served another. Adversarial review called this correctly — the rollback gate
    was not satisfied by what the manifest alone could do.

    Restoring is therefore explicit, and it reports what it could not restore instead of
    silently succeeding. A lesson deleted since the release cannot be brought back by moving a
    pointer, and pretending otherwise would recreate the same false confidence.
    """
    restored = {"lessons": 0, "questions": 0}
    missing: list[str] = []

    for row in manifest.get("lessons") or []:
        lesson = db.get(Lesson, row.get("id"))
        if lesson is None:
            missing.append(f"lesson {row.get('id')} ({row.get('slug')}) no longer exists")
            continue
        version_row = db.scalar(select(LessonVersion).where(
            LessonVersion.lesson_id == lesson.id,
            LessonVersion.version == row.get("version")))
        if version_row is None:
            missing.append(
                f"lesson {lesson.id} has no version {row.get('version')} to restore")
            continue
        changed = (
            lesson.current_version != row["version"]
            or lesson.title != row.get("title", lesson.title)
            or lesson.status != row.get("status", lesson.status)
        )
        lesson.current_version = row["version"]
        if row.get("title") is not None:
            lesson.title = row["title"]
        if row.get("status") is not None:
            lesson.status = row["status"]
        if row.get("estimated_minutes") is not None:
            lesson.estimated_minutes = row["estimated_minutes"]
        if changed:
            restored["lessons"] += 1

    # the manifest lists only the items that were *published* at release time; anything
    # published since was not part of it and is withdrawn from the restored release
    pinned = {row["id"]: row for row in (manifest.get("questions") or [])}
    for row in manifest.get("questions") or []:
        question = db.get(Question, row["id"])
        if question is None:
            missing.append(f"question {row['id']} no longer exists")
            continue
        if question.status != row.get("status"):
            question.status = row["status"]
            restored["questions"] += 1
    course_id = (manifest.get("course") or {}).get("id")
    course = db.get(Course, course_id) if course_id is not None else None
    if course is not None:
        concept_ids = [s["concept_id"] for s in (manifest.get("skills") or [])
                       if s.get("concept_id")]
        if concept_ids:
            # The event filter mirrors `build_manifest`. Without it the withdrawal reached any
            # published item sharing a concept id, so rolling back one course could demote
            # another course's items. No concept is shared across courses today, which is
            # exactly why the asymmetry would have gone unnoticed until it wasn't.
            for question in db.scalars(select(Question).where(
                Question.event_id == course.event_id,
                Question.concept_id.in_(concept_ids),
                Question.status == "published",
            )).all():
                if question.id not in pinned:
                    # published after the release being restored: it was never part of it
                    question.status = "machine_validated"
                    restored["questions"] += 1

    # Blueprints are pinned in the manifest and were not being restored. A unit quiz that
    # moved from draft to published after the release would have stayed published through a
    # rollback, so the restored release would serve an assessment it never contained.
    for row in manifest.get("blueprints") or []:
        blueprint = db.get(AssessmentBlueprint, row.get("id"))
        if blueprint is None:
            missing.append(f"blueprint {row.get('id')} no longer exists")
            continue
        if row.get("status") is not None and blueprint.status != row["status"]:
            blueprint.status = row["status"]
            restored["blueprints"] = restored.get("blueprints", 0) + 1

    db.flush()
    restored["unrestorable"] = missing
    return restored


def rollback_release(db: Session, actor: User, course: Course) -> ContentRelease:
    """Re-point the course at the most recent superseded release, content included.

    This restores a *manifest*, not just a version number, and then restores the rows that
    manifest pinned — because the pointer alone changed nothing a student could see.
    """
    current = db.scalar(select(ContentRelease).where(
        ContentRelease.course_id == course.id,
        ContentRelease.status == "published",
    ))
    previous = db.scalar(select(ContentRelease).where(
        ContentRelease.course_id == course.id,
        ContentRelease.status == "superseded",
    ).order_by(ContentRelease.version.desc(), ContentRelease.id.desc()))
    if previous is None:
        raise ReleaseError("no superseded release is available to roll back to")

    if current is not None:
        current.status = "rolled_back"
    previous.status = "published"
    previous.published_by_user_id = actor.id if actor else None
    previous.published_at = now_utc()
    course.current_version = previous.version
    # the pointer is not the rollback; restoring what the manifest pinned is
    restored = restore_from_manifest(db, previous.manifest or {})
    notes = (previous.release_notes or "").strip()
    previous.release_notes = (
        f"{notes}\n[rollback] restored {restored['lessons']} lesson(s), "
        f"{restored['questions']} item(s)"
        + (f"; UNRESTORABLE: {'; '.join(restored['unrestorable'])}"
           if restored["unrestorable"] else "")
    ).strip()
    db.flush()
    return previous


def release_drift(db: Session, course: Course) -> dict:
    """Compare what is live now against what the active release pinned.

    A published release whose content has since been edited is the failure this detects: the
    catalog would be serving something no one approved under a version that says otherwise.
    """
    active = db.scalar(select(ContentRelease).where(
        ContentRelease.course_id == course.id,
        ContentRelease.status == "published",
    ))
    if active is None:
        return {"released": False, "drifted": False, "changes": ["no_published_release"]}
    current = build_manifest(db, course)
    pinned = active.manifest or {}
    if pinned.get("digest") == current["digest"]:
        return {"released": True, "drifted": False, "changes": []}

    changes = []
    for key in ("units", "skills", "lessons", "questions", "blueprints", "claims", "sources"):
        was = (pinned.get("counts") or {}).get(key)
        now = current["counts"][key]
        if was != now:
            changes.append(f"{key}: {was} -> {now}")
    pinned_lessons = {row["id"]: row.get("version") for row in (pinned.get("lessons") or [])}
    edited = [row["id"] for row in current["lessons"]
              if row["id"] in pinned_lessons and pinned_lessons[row["id"]] != row["version"]]
    if edited:
        changes.append(f"lesson versions changed since release: {edited}")
    return {"released": True, "drifted": True, "changes": changes or ["content digest changed"],
            "released_version": active.version, "released_digest": pinned.get("digest"),
            "current_digest": current["digest"]}
