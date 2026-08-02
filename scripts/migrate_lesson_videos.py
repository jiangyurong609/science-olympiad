"""Carry produced lesson video from one database to another.

The 24 storyboards and 22 rendered chapters were produced against the local database, so
production has none of them and every lesson there is still prose and checks. The video files
themselves are already in the shared GCS bucket — both environments point at
`soplat-artifacts-video-agent-493605` — so what production is missing is only the rows.

This is the same shape as the course manifest: export from one database keyed by things that
survive the crossing (event slug, lesson slug, claim *text*), import into the other. Primary
keys do not survive; nothing here trusts one.

Two checks refuse rather than guess, and both fail closed on the whole lesson:

  * a scene addresses `block_indexes` into the lesson version's content. If the target's copy
    of that lesson has different blocks, those indexes point at different material and the
    narration would be attached to the wrong section. Every block is compared by a hash of its
    full content — an earlier version compared only type and heading, which let a block whose
    body or choices had changed under an unchanged heading pass as identical.
  * `claim_ids` are local primary keys, remapped by claim text within the event. Claim text is
    not unique, so a text matching more than one claim is ambiguous and refused rather than
    resolved by whichever row the database returned first. A claim that does not resolve
    refuses the storyboard outright: dropping it would leave an approved storyboard citing
    less than it was validated against, and nothing downstream re-runs that validation.

Renders arrive at `qa_status="pending"`, which is where `render_lesson` leaves them. That is
the gate: `video_library` serves only QA-approved chapters, so importing this puts the video in
front of a reviewer, not in front of a student.

    PYTHONPATH=. python -m scripts.migrate_lesson_videos export --event rocks-and-minerals-b --out video.json
    DATABASE_URL=<target> PYTHONPATH=. python -m scripts.migrate_lesson_videos import --in video.json
    DATABASE_URL=<target> PYTHONPATH=. python -m scripts.migrate_lesson_videos import --in video.json --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Course, Event, Lesson, LessonVersion, ScientificClaim, Skill, User, VideoRender,
    VideoStoryboard,
)


def _event_claims(db, event_id: int) -> list[ScientificClaim]:
    """Claims belonging to this event's course.

    `ScientificClaim` has no `event_id`; it reaches an event through its skill's course. Doing
    the lookup globally instead would let a claim from another event answer to the same text.
    """
    skill_ids = db.scalars(select(Skill.id).join(Course, Skill.course_id == Course.id)
                           .where(Course.event_id == event_id)).all()
    if not skill_ids:
        return []
    return db.scalars(select(ScientificClaim).where(
        ScientificClaim.skill_id.in_(skill_ids))).all()


def _content_fingerprint(version: LessonVersion | None) -> list[str]:
    """What a scene's `block_indexes` actually resolve against.

    The first version of this hashed only each block's type and heading, on the reasoning that
    the indexes depend on block *identity* and a typo fix should not reject a whole lesson.
    That is too weak to make the promise it was making: a block whose body, choices or meaning
    changed under an unchanged heading compared equal, and the narration — written for the old
    text — would have been attached to the new. Since the claim being made is "this narration
    was produced from this content", the whole block has to be in the comparison.
    """
    out = []
    for block in (version.content if version else None) or []:
        canonical = json.dumps(block, sort_keys=True, ensure_ascii=False, default=str)
        out.append(hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32])
    return out


def export(event_slug: str) -> dict:
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == event_slug))
        if not event:
            raise SystemExit(f"unknown event {event_slug!r}")
        boards = db.scalars(select(VideoStoryboard).where(
            VideoStoryboard.event_id == event.id).order_by(VideoStoryboard.id)).all()
        lessons = {l.id: l for l in db.scalars(select(Lesson).where(
            Lesson.event_id == event.id)).all()}
        referenced = {c for board in boards for scene in (board.scenes or [])
                      for c in (scene.get("claim_ids") or []) if isinstance(c, int)}
        claims = {c.id: c.claim_text for c in db.scalars(select(ScientificClaim).where(
            ScientificClaim.id.in_(referenced or {-1}))).all()}

        payload = {"event": event_slug, "storyboards": []}
        for board in boards:
            lesson = lessons.get(board.lesson_id)
            if lesson is None:
                continue
            version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == board.lesson_version))
            scenes = []
            for scene in board.scenes or []:
                scene = dict(scene)
                # ids do not cross; carry the text the id stood for
                scene["claim_texts"] = [claims[c] for c in (scene.get("claim_ids") or [])
                                        if c in claims]
                scene.pop("claim_ids", None)
                scenes.append(scene)
            renders = db.scalars(select(VideoRender).where(
                VideoRender.storyboard_id == board.id).order_by(VideoRender.id)).all()
            payload["storyboards"].append({
                "lesson_slug": lesson.slug,
                "lesson_title": lesson.title,
                "lesson_version": board.lesson_version,
                "content_fingerprint": _content_fingerprint(version),
                "version": board.version,
                "title": board.title,
                "status": board.status,
                "scenes": scenes,
                "renders": [{
                    "version": r.version, "chapter": r.chapter, "status": r.status,
                    "spec_hash": r.spec_hash, "duration_seconds": r.duration_seconds,
                    "audio_keys": r.audio_keys or [], "slide_keys": r.slide_keys or [],
                    "video_key": r.video_key, "worker_job_id": r.worker_job_id,
                    "provenance": r.provenance or {}, "error": r.error,
                    # deliberately not carrying qa_status: a QA decision made against one
                    # database is not a QA decision made against another
                } for r in renders],
            })
        return payload


def load(payload: dict, apply: bool) -> dict:
    stats: Counter[str] = Counter()
    rows: list[dict] = []
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == payload["event"]))
        if not event:
            raise SystemExit(f"target has no event {payload['event']!r}")
        lessons = {l.slug: l for l in db.scalars(select(Lesson).where(
            Lesson.event_id == event.id)).all()}
        # Claim text is not unique by construction, and the query has no deterministic order,
        # so `setdefault` silently picked whichever duplicate the database happened to return
        # first. An ambiguous match is recorded as ambiguous and refused, not resolved by luck.
        claim_ids: dict[str, int] = {}
        ambiguous: set[str] = set()
        for claim in _event_claims(db, event.id):
            key = " ".join((claim.claim_text or "").split()).lower()
            if key in claim_ids and claim_ids[key] != claim.id:
                ambiguous.add(key)
            claim_ids.setdefault(key, claim.id)
        actor = db.scalar(select(User).where(User.role.in_(("editor", "admin"))))

        for entry in payload["storyboards"]:
            title = entry["lesson_title"]
            lesson = lessons.get(entry["lesson_slug"])
            if lesson is None:
                stats["lesson_absent"] += 1
                rows.append({"lesson": title, "outcome": "no such lesson in target"})
                continue

            target_version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version))
            if _content_fingerprint(target_version) != entry["content_fingerprint"]:
                stats["content_diverged"] += 1
                rows.append({"lesson": title,
                             "outcome": "target lesson content differs — scenes would "
                                        "narrate the wrong sections"})
                continue

            existing = db.scalar(select(VideoStoryboard).where(
                VideoStoryboard.lesson_id == lesson.id,
                VideoStoryboard.version == entry["version"]))
            if existing is not None:
                stats["storyboard_existed"] += 1
                rows.append({"lesson": title, "outcome": "storyboard already present"})
                continue

            # A storyboard's grounding is not partially importable. Dropping a claim that does
            # not resolve left an approved storyboard citing less than it was validated
            # against, and nothing downstream re-runs `validate_scenes`, so post-render QA
            # would have approved a video whose provenance had quietly thinned. Refuse the
            # whole lesson instead and say which claim.
            scenes, unresolved = [], []
            for scene in entry["scenes"]:
                scene = dict(scene)
                mapped = []
                for text in scene.pop("claim_texts", []):
                    key = " ".join(str(text).split()).lower()
                    if key in ambiguous:
                        unresolved.append(f"ambiguous: {str(text)[:60]}")
                    elif key in claim_ids:
                        mapped.append(claim_ids[key])
                    else:
                        unresolved.append(f"missing: {str(text)[:60]}")
                scene["claim_ids"] = mapped
                scenes.append(scene)
            if unresolved:
                stats["claims_unresolved"] += len(unresolved)
                rows.append({"lesson": title,
                             "outcome": f"refused — {len(unresolved)} claim(s) do not resolve "
                                        f"in the target ({unresolved[0]})"})
                continue

            if not apply:
                stats["would_import"] += 1
                rows.append({"lesson": title,
                             "outcome": f"would import {len(scenes)} scene(s), "
                                        f"{len(entry['renders'])} chapter(s)"})
                continue

            board = VideoStoryboard(
                lesson_id=lesson.id,
                lesson_version=lesson.current_version,
                event_id=event.id,
                version=entry["version"],
                title=entry["title"],
                scenes=scenes,
                status=entry["status"],
                approved_by_user_id=actor.id if entry["status"] == "approved" and actor else None,
            )
            db.add(board)
            db.flush()
            for render in entry["renders"]:
                db.add(VideoRender(storyboard_id=board.id, qa_status="pending", **render))
            stats["imported"] += 1
            stats["chapters"] += len(entry["renders"])
            rows.append({"lesson": title,
                         "outcome": f"imported {len(scenes)} scene(s), "
                                    f"{len(entry['renders'])} chapter(s)"})
        if apply:
            db.commit()
        else:
            db.rollback()
    return {"stats": stats, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Move produced lesson video between databases")
    sub = ap.add_subparsers(dest="command", required=True)
    exporter = sub.add_parser("export")
    exporter.add_argument("--event", required=True)
    exporter.add_argument("--out", required=True)
    importer = sub.add_parser("import")
    importer.add_argument("--in", dest="path", required=True)
    importer.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if args.command == "export":
        payload = export(args.event)
        with open(args.out, "w") as handle:
            json.dump(payload, handle, indent=1)
        chapters = sum(len(s["renders"]) for s in payload["storyboards"])
        print(f"exported {len(payload['storyboards'])} storyboard(s), "
              f"{chapters} chapter(s) -> {args.out}")
        return

    with open(args.path) as handle:
        payload = json.load(handle)
    result = load(payload, args.apply)
    print("=" * 78)
    print(f"LESSON VIDEO MIGRATION — {payload['event']} "
          f"[{'APPLY' if args.apply else 'DRY RUN'}]")
    print("=" * 78)
    for row in result["rows"]:
        print(f"  {row['lesson'][:44]:46} {row['outcome']}")
    print("-" * 78)
    for key, value in sorted(result["stats"].items()):
        print(f"  {key:24} {value}")
    if not args.apply:
        print("\ndry run — nothing written. re-run with --apply")
    else:
        print("\nchapters land at qa_status=pending; only QA-approved chapters reach students")
    print("=" * 78)


if __name__ == "__main__":
    main()
