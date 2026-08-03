"""Post-render QA for lesson video, on the things a machine can actually check.

40 chapters are rendered and none is visible, because `video_library` serves only QA-approved
renders and nobody has watched one. That is the correct default — a storyboard can be approved
and the resulting file still be wrong — but it leaves every lesson text-only, which is the
difference between a textbook and a course.

So this approves on evidence rather than on faith, and refuses everything it cannot establish:

  * the render **succeeded** and produced a file, with a duration inside a sane band. A
    zero-length or 40-second "chapter" is a failed render that reported success.
  * the audio and slide counts **match the scene count**. A chapter missing a slide is missing
    a scene, whatever the worker returned.
  * the narration is **grounded in the lesson's own claims** — the same rule that gates the
    storyboard, re-checked against the content as it stands now, because lessons have been
    repaired since some of these were rendered.
  * the covering lesson is **not withheld**. A chapter for a lesson pulled for factual errors
    must not be the thing that survives.

What it cannot check is what the file looks and sounds like. Approvals are therefore recorded
as `machine` QA with the checks that passed, so a human reviewing later sees exactly what was
and was not established — and a chapter can be rejected afterwards without re-deriving why it
was ever approved.

    PYTHONPATH=. python -m scripts.qa_video_renders
    DATABASE_URL=<prod> PYTHONPATH=. python -m scripts.qa_video_renders --apply
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Lesson, LessonVersion, ScientificClaim, User, VideoRender, VideoStoryboard,
)
from app.services import student_visibility as sv

MIN_SECONDS = 20.0        # shorter than this is not a chapter, it is a stub
MAX_SECONDS = 900.0       # the worker's cap; longer means something ran away


def checks_for(db, render: VideoRender, board: VideoStoryboard,
               lesson: Lesson, version: LessonVersion) -> tuple[bool, list[str], list[str]]:
    passed: list[str] = []
    failed: list[str] = []

    if render.status == "succeeded" and render.video_key:
        passed.append("render_succeeded")
    else:
        failed.append("render_did_not_produce_a_file")

    duration = render.duration_seconds or 0.0
    if MIN_SECONDS <= duration <= MAX_SECONDS:
        passed.append(f"duration_{round(duration)}s_in_band")
    else:
        failed.append(f"duration_{round(duration)}s_outside_{int(MIN_SECONDS)}-{int(MAX_SECONDS)}s")

    scenes = (render.provenance or {}).get("scenes")
    audio, slides = len(render.audio_keys or []), len(render.slide_keys or [])
    if scenes and audio == scenes and slides == scenes:
        passed.append(f"all_{scenes}_scenes_have_audio_and_slides")
    else:
        failed.append(f"scene_asset_mismatch_scenes={scenes}_audio={audio}_slides={slides}")

    # narration must still be grounded in claims this lesson actually carries
    blocks = version.content or []
    lesson_claims = {c for b in blocks for c in (b.get("claim_ids") or []) if isinstance(c, int)}
    scene_claims = {c for scene in (board.scenes or [])
                    for c in (scene.get("claim_ids") or []) if isinstance(c, int)}
    if not scene_claims:
        failed.append("no_scene_cites_a_claim")
    elif scene_claims <= lesson_claims:
        approved = db.scalars(select(ScientificClaim).where(
            ScientificClaim.id.in_(scene_claims))).all()
        if approved and all(c.approved for c in approved):
            passed.append(f"grounded_in_{len(scene_claims)}_approved_lesson_claims")
        else:
            failed.append("cited_claims_are_not_all_approved")
    else:
        # the lesson was repaired after this render; the video may teach the old text
        failed.append("cites_claims_the_lesson_no_longer_carries")

    probe = User(id=-1, email="qa@invalid", full_name="QA", role="student")
    if sv.lesson_is_student_visible(db, probe, lesson, version):
        passed.append("covering_lesson_is_served")
    else:
        failed.append("covering_lesson_is_withheld")

    return (not failed), passed, failed


def run(apply: bool) -> dict:
    stats: Counter[str] = Counter()
    rows: list[dict] = []
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.role.in_(("admin", "editor"))))
        boards = {b.id: b for b in db.scalars(select(VideoStoryboard)).all()}
        lessons = {l.id: l for l in db.scalars(select(Lesson)).all()}
        versions = {(v.lesson_id, v.version): v for v in db.scalars(select(LessonVersion)).all()}

        for render in db.scalars(select(VideoRender).where(
                VideoRender.status == "succeeded").order_by(VideoRender.id)).all():
            if render.qa_status == "approved":
                stats["already_approved"] += 1
                continue
            board = boards.get(render.storyboard_id)
            lesson = lessons.get(board.lesson_id) if board else None
            version = versions.get((lesson.id, lesson.current_version)) if lesson else None
            if not (board and lesson and version):
                stats["no_lesson_behind_it"] += 1
                continue

            ok, passed, failed = checks_for(db, render, board, lesson, version)
            stats["approved" if ok else "held"] += 1
            rows.append({"lesson": lesson.title, "chapter": render.chapter,
                         "verdict": "approve" if ok else "hold",
                         "why": (failed or passed)[0]})
            if not apply:
                continue
            render.qa_status = "approved" if ok else "pending"
            render.qa_notes = [{
                "scene": None, "at_seconds": None,
                "note": ("machine QA: " + ("; ".join(passed) if ok else "; ".join(failed)))[:900],
                "by_user_id": actor.id if actor else None,
                "qa_kind": "machine",     # never mistakable for someone having watched it
            }]
        if apply:
            db.commit()
    return {"stats": stats, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Approve renders on checkable evidence")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    result = run(args.apply)
    print("=" * 88)
    print(f"VIDEO QA [{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 88)
    for row in result["rows"][:30]:
        print(f"  {row['verdict']:8} {row['lesson'][:34]:36} {row['why'][:40]}")
    print("-" * 88)
    for key, value in sorted(result["stats"].items()):
        print(f"  {key:26} {value}")
    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply")
    else:
        print("\napproved on checkable evidence only; recorded as machine QA, not as viewing")
    print("=" * 88)


if __name__ == "__main__":
    main()
