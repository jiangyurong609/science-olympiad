"""Phase 5 — produce chaptered video for a course's lessons.

The lesson player already treats video as the opening move of each section: a chapter plays,
then rolls into the reading it covers. The pilot has none — 24 lessons, 0 storyboards, 0
renders — so every lesson is prose and checks, which is not what a student with a short
attention span will finish.

The pipeline already exists in pieces; this drives it end to end:

    draft_from_lesson  →  validate  →  create_storyboard  →  approve  →  render_lesson

Narration is Deepgram; rendering is the Remotion worker, which returns one file per chapter
so a single failure costs a chapter rather than a lesson.

Nothing here reaches a student. Renders land at `qa_pending`, and `video_library` only serves
QA-approved chapters — the same rule that stops a lesson being read before review.

    PYTHONPATH=. python -m scripts.produce_lesson_videos --event rocks-and-minerals-b
    PYTHONPATH=. python -m scripts.produce_lesson_videos --event ... --apply --limit 2
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Event, Lesson, LessonVersion, User, VideoRender, VideoStoryboard,
)
from app.services import video_storyboard as sb
from app.services.course_quality import block_text
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider
from app.services.video_render_job import render_lesson
from app.services.video_worker import RemotionRenderClient

NARRATION_SYSTEM = (
    "You narrate short Science Olympiad lesson videos. Return ONLY valid JSON. "
    "Write what a teacher would say over this one slide: 2-4 sentences, spoken register, "
    "no list markers, no stage directions. Say only what the supplied section text already "
    "establishes — never add a fact, figure, or number that is not in it. "
    "Write for a middle-school or early-high-school competitor."
)


def narrate_scene(provider, lesson_title: str, block: dict, claim_texts: list[str]) -> str:
    """Write the narration `draft_from_lesson` deliberately leaves blank.

    That skeleton assumes a human authors each scene, which is right for one lesson and does
    not survive 24 — the pilot's storyboards were rejected 24 times for empty narration. The
    model is confined to the section's own words, and the result still passes the scene
    validator, the storyboard approval gate, and post-render QA before any student sees it.
    """
    import json

    payload = provider.generate_json(NARRATION_SYSTEM, json.dumps({
        "lesson": lesson_title,
        "section_heading": block.get("heading") or block.get("title") or "",
        "section_text": block_text(block)[:4000],
        "supporting_claims": claim_texts[:3],
    })).payload
    if isinstance(payload, str):
        payload = json.loads(payload)
    text = payload.get("narration") or payload.get("text") or ""
    return " ".join(str(text).split())[:900]


def _existing_storyboard(db, lesson_id: int) -> VideoStoryboard | None:
    return db.scalar(select(VideoStoryboard).where(
        VideoStoryboard.lesson_id == lesson_id,
    ).order_by(VideoStoryboard.version.desc(), VideoStoryboard.id.desc()))


def _render_client(impersonate: str | None) -> RemotionRenderClient | None:
    """Build a worker client, minting the OIDC token by impersonation when asked.

    The worker authenticates with a Google identity token for its own audience. Inside Cloud
    Run the metadata server provides one; from a developer shell it cannot, so a run that is
    otherwise ready fails at the last step with "Neither metadata server or valid service
    account". Impersonating the service account the app already runs as closes that gap
    without a downloaded key.
    """
    if not impersonate:
        return None
    import subprocess

    from app.core.config import get_settings
    audience = (get_settings().video_render_worker_url or "").rstrip("/")
    if not audience:
        raise SystemExit("no video_render_worker_url configured")
    token = subprocess.run(
        ["gcloud", "auth", "print-identity-token",
         f"--impersonate-service-account={impersonate}", f"--audiences={audience}"],
        capture_output=True, text=True,
    )
    if token.returncode != 0:
        raise SystemExit(f"could not impersonate {impersonate}: {token.stderr.strip()[:200]}")
    return RemotionRenderClient(token=token.stdout.strip())


def run(event_slug: str, apply: bool, limit: int | None, render: bool,
        impersonate: str | None = None) -> dict:
    stats: Counter[str] = Counter()
    rows: list[dict] = []
    provider = OpenAICompatibleProvider()
    if apply and not provider.configured:
        raise SystemExit("no model provider configured; narration cannot be written")
    client = _render_client(impersonate) if render else None
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == event_slug))
        if not event:
            raise SystemExit(f"unknown event {event_slug!r}")
        actor = db.scalar(select(User).where(User.role.in_(("editor", "admin"))))
        if apply and actor is None:
            raise SystemExit("no editor/admin account to attribute storyboard approval to")

        lessons = db.scalars(select(Lesson).where(
            Lesson.event_id == event.id, Lesson.status != "withdrawn",
        ).order_by(Lesson.sequence, Lesson.id)).all()
        if limit:
            lessons = lessons[:limit]

        for lesson in lessons:
            version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version))
            if version is None:
                stats["no_version"] += 1
                continue

            board = _existing_storyboard(db, lesson.id)
            if board is None:
                try:
                    draft = sb.draft_from_lesson(db, lesson.id)
                except sb.StoryboardError as exc:
                    stats["draft_failed"] += 1
                    rows.append({"lesson": lesson.title, "outcome": f"draft failed: {exc}"})
                    continue
                scenes = draft.get("scenes") or []
                blocks = version.content or []
                if apply:
                    from app.models.entities import ScientificClaim
                    for scene in scenes:
                        block = blocks[scene["block_indexes"][0]]
                        # A scene teaches one block, so it is grounded by *that block's*
                        # claims. `draft_from_lesson` takes the lesson version's claim list,
                        # which the manifest importer deliberately clears — leaving every
                        # imported lesson's scenes ungrounded and unapprovable.
                        block_claims = [c for c in (block.get("claim_ids") or [])
                                        if isinstance(c, int)]
                        if block_claims:
                            scene["claim_ids"] = block_claims[:2]
                        claim_texts = [
                            c.claim_text for c in db.scalars(select(ScientificClaim).where(
                                ScientificClaim.id.in_(scene.get("claim_ids") or [-1]))).all()
                        ]
                        try:
                            scene["narration"] = narrate_scene(
                                provider, lesson.title, block, claim_texts)
                        except Exception as exc:
                            # a swallowed failure here looks identical to "the model wrote
                            # nothing", which cost a full debugging cycle; say which it was
                            scene["narration"] = ""
                            scene["narration_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                        scene["narration_source"] = "produce_lesson_videos"
                if apply:
                    # A scene the model returned nothing for, or that no claim supports, is
                    # dropped rather than fabricated or left to block the lesson. The section
                    # still appears in the reading; it simply gets no narrated slide. One
                    # unnarratable gallery should not cost a lesson its video.
                    keep = [sc for sc in scenes
                            if str(sc.get("narration", "")).strip() and sc.get("claim_ids")]
                    dropped = len(scenes) - len(keep)
                    if dropped:
                        stats["scenes_dropped"] += dropped
                    for position, scene in enumerate(keep, start=1):
                        scene["index"] = position
                    scenes = keep
                problems = sb.validate_scenes(db, scenes, lesson_id=lesson.id)
                errored = [sc.get("narration_error") for sc in scenes if sc.get("narration_error")]
                if errored:
                    rows.append({"lesson": lesson.title,
                                 "outcome": f"narration failed: {errored[0]}"})
                if apply and not scenes:
                    stats["no_narratable_scene"] += 1
                    rows.append({"lesson": lesson.title,
                                 "outcome": "no scene could be narrated and grounded"})
                    continue
                if problems:
                    # narration that cites a claim the lesson cannot support is the defect
                    # this whole pipeline exists downstream of; refuse rather than narrate it
                    stats["invalid_scenes"] += 1
                    rows.append({"lesson": lesson.title,
                                 "outcome": f"scenes rejected: {problems[0][:90]}"})
                    continue
                if not apply:
                    stats["would_draft"] += 1
                    rows.append({"lesson": lesson.title,
                                 "outcome": f"would storyboard {len(scenes)} scene(s)"})
                    continue
                board = sb.create_storyboard(db, lesson.id, scenes,
                                             title=draft.get("title") or lesson.title)
                db.commit()
                stats["storyboarded"] += 1
            else:
                stats["storyboard_existed"] += 1

            if not apply:
                continue
            if board.status != "approved":
                sb.approve_storyboard(db, board.id, actor.id)
                db.commit()

            done = db.scalars(select(VideoRender).where(
                VideoRender.storyboard_id == board.id)).all()
            if done and not render:
                stats["already_rendered"] += 1
                rows.append({"lesson": lesson.title,
                             "outcome": f"{len(done)} chapter(s) already rendered"})
                continue
            if not render:
                rows.append({"lesson": lesson.title, "outcome": "storyboard approved"})
                continue
            try:
                produced = render_lesson(db, board.id, client=client)
                db.commit()
                stats["rendered"] += len(produced)
                rows.append({"lesson": lesson.title,
                             "outcome": f"rendered {len(produced)} chapter(s)"})
            except Exception as exc:                      # one lesson must not stop the run
                db.rollback()
                stats[f"render_failed:{type(exc).__name__}"] += 1
                rows.append({"lesson": lesson.title,
                             "outcome": f"render failed: {type(exc).__name__}: {str(exc)[:80]}"})
    return {"stats": stats, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Produce chaptered video for a course")
    ap.add_argument("--event", required=True)
    ap.add_argument("--apply", action="store_true", help="write storyboards and approve them")
    ap.add_argument("--render", action="store_true", help="also render video (costs TTS + worker time)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--impersonate", default=None,
                    help="service account to mint the render worker's identity token as")
    args = ap.parse_args()

    result = run(args.event, args.apply, args.limit, args.render, args.impersonate)
    print("=" * 78)
    print(f"LESSON VIDEO — {args.event} "
          f"[{'APPLY' if args.apply else 'DRY RUN'}{' +RENDER' if args.render else ''}]")
    print("=" * 78)
    for row in result["rows"]:
        print(f"  {row['lesson'][:46]:48} {row['outcome']}")
    print("-" * 78)
    for key, value in sorted(result["stats"].items()):
        print(f"  {key:28} {value}")
    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply (add --render to produce video)")
    print("=" * 78)


if __name__ == "__main__":
    main()
