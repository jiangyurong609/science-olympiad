"""Author a course from a blueprint, grounded in locator-bearing passages.

The script is safe by default: it prints the scaffold plan without writing.
``--apply`` creates the review-only course graph. ``--generate`` additionally
uses the configured model to draft lessons, but never records editor/SME
approval and never makes the course student-visible.

The blueprint names its own event (``event_slug``), so nothing here is specific to
one subject; it was hardwired to the Rocks & Minerals path only because that was
the first course it built.

    python -m scripts.author_course_from_blueprint \
        --blueprint data/courses/dynamic-planet-b-2027.json --apply --generate
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from sqlalchemy import and_, func, select

from app.core.database import SessionLocal
from app.models.entities import (
    AssessmentBlueprint, Concept, ContentGap, Course, CourseSourceCoverage,
    CourseUnit, CourseVersion, Event, EventSourceMap, Lesson, LessonSkill,
    LessonVersion, ReviewDecision, Skill, Source, SourcePassage,
)
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider


BLUEPRINT_DIR = Path(__file__).resolve().parent.parent / "data" / "courses"
DEFAULT_BLUEPRINT = BLUEPRINT_DIR / "rocks-and-minerals-b-2027.json"
PROMPT_VERSION = "passage-grounded-five-part-lesson-v1"
TEACHING_TYPES = {"property_cards", "steps", "worked_example"}

SYSTEM = """You are an expert middle-school Science Olympiad teacher drafting one lesson.
Use ONLY the supplied source passages. Do not invent a fact, rule, specimen property,
or test result. Return strict JSON with title, summary, estimated_minutes, misconceptions,
and blocks. The blocks must form this learning rhythm:
1. one opening block first, with the measurable goal;
2. at least three teaching blocks using property_cards, steps, or worked_example;
3. at least three checkpoint blocks spread through the lesson;
4. one summary block last with key points and next_step.

If the supplied passages cannot support ANY of this lesson's objective, return
{"insufficient_evidence": "<what is missing>"} and NOTHING ELSE. Do not write a lesson about
what the sources fail to say.

If the passages support MOST of the objective but not all of it, WRITE THE LESSON for the part
they do support, and list the rest in a top-level "uncovered" array of short phrases. Do not
refuse a whole lesson over one unsupported clause: a lesson that teaches four of five things
well, and says plainly which fifth is missing, is worth far more to a student than no lesson at
all, and the missing piece is recorded as a content gap for a human to source. Simply omit the
unsupported material from the blocks — never mention its absence inside the lesson itself. NEVER write a card, a step, an explanation or an answer choice
asserting that something is "not defined", "not supplied", "not provided", "not described",
"cannot be determined" or "must not be inferred", and NEVER make such a statement the correct
answer. A checkpoint keyed to the absence of evidence teaches a student nothing and silently
removes a required topic from the course. An honest empty result is far better.

Every teaching block and checkpoint MUST contain passage_ids using only IDs supplied in
the prompt. A checkpoint must contain id, heading, question, exactly four choices,
correct_index, explanation, misconception_by_choice for every incorrect choice,
cognitive_level (recall, application, or transfer), and passage_ids. Include at least
one application or transfer checkpoint. The explanation must teach why the answer fits
the evidence. Avoid long quotations and avoid referring to 'the passage'. Output JSON only.

Allowed shapes:
opening: {type,kicker,heading,body}
property_cards: {type,heading,body,cards:[{name,cue,detail}],passage_ids}
steps: {type,heading,steps:[{label,detail}],passage_ids}
worked_example: {type,heading,prompt,steps:[string],passage_ids}
checkpoint: {type,id,heading,question,choices,correct_index,explanation,
  misconception_by_choice,cognitive_level,passage_ids}
summary: {type,heading,points:[string],next_step}
"""


# Wikipedia titles the Stefan-Boltzmann law, the Saffir-Simpson scale and the
# Wegener-Bergeron-Findeisen process with EN DASHES, and its prose follows the title. A
# blueprint keyword written with an ordinary hyphen — which is what anyone types, and what the
# 2027 scope outline uses — then matches none of it: "Wegener-Bergeron" selects 0 passages
# while 5 passages contain "Wegener\u2013Bergeron". The lesson is authored without the one page
# that explains its subject, and reports the subject as unsupported.
# The same trap with apostrophes: NIDDK and MedlinePlus render "Crohn\u2019s" with a curly
# apostrophe, so a keyword typed as "Crohn's" matches nothing on the page about it.
_DASHES = str.maketrans({"\u2013": "-", "\u2014": "-", "\u2011": "-", "\u00ad": "-", "\u2212": "-",
                         "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})


def _fold(text: str) -> str:
    """Lower-case and reduce every dash to a plain hyphen, for matching only."""
    return text.translate(_DASHES).lower()


def _terms(values: list[str]) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9]+", " ".join(values).lower())
        if len(token) > 2
    ]


def _passage_score(passage: SourcePassage, source: Source, keywords: list[str]) -> int:
    haystack = _fold(f"{source.title} {passage.heading} {passage.text}")
    return sum(
        (6 if term in _fold(source.title) else 0) + min(haystack.count(term), 4)
        for term in _terms(keywords)
    )


def _select_passages(
    passages: list[SourcePassage],
    sources: dict[int, Source],
    keywords: list[str],
    *,
    require_video: bool,
    # 10 passages is roughly 21,000 characters, and it was the binding constraint on whether a
    # lesson could be authored at all. The model's context is not the scarce resource here;
    # 24 passages is about 58,000 characters and well within it.
    limit: int = 24,
) -> list[SourcePassage]:
    """Cover every keyword first, then fill by relevance.

    Ranking purely by total keyword hits looked sensible and quietly starved the specific.
    A lesson on fluvial landforms lists thirteen keywords; the top of that ranking fills with
    passages that say "floodplain" and "point bar" many times each, and the ONE passage that
    explains how an alluvial fan forms — from a page that is in the source set for exactly
    that reason — never makes the cut. The author then reported alluvial fans as unsupported,
    which reads as a gap in the corpus and was a gap in the selection.

    So each keyword gets its best passage before any keyword gets its second.
    """
    scored = sorted(
        (
            (_passage_score(passage, sources[passage.source_id], keywords), passage)
            for passage in passages
        ),
        key=lambda pair: (pair[0], -pair[1].sequence, -pair[1].id),
        reverse=True,
    )
    selected: list[SourcePassage] = []
    chosen_ids: set[int] = set()

    def take(passage: SourcePassage) -> None:
        selected.append(passage)
        chosen_ids.add(passage.id)

    if require_video:
        video = next(
            (passage for score, passage in scored
             if score > 0 and passage.passage_type == "video_transcript"),
            None,
        )
        if video:
            take(video)

    # One pass per keyword, in the blueprint's own order, so the terms an author named are the
    # terms it actually gets evidence for.
    for term in keywords:
        if len(selected) >= limit:
            break
        needle = _fold(term)
        best = next(
            (passage for score, passage in scored
             if passage.id not in chosen_ids and score > 0
             and needle in _fold(f"{passage.heading} {passage.text}")),
            None,
        )
        if best is not None:
            take(best)

    # Remaining slots by relevance, capped per source.
    #
    # These used to go to sources not yet drawn on, which reads as healthy diversity and
    # starves a focused lesson. "Proteins, Nucleic Acids, Lipids and Carbohydrates" has four
    # obvious sources holding 94 passages between them, and got SEVEN of its twenty-four
    # slots; the other seventeen went one apiece to Enceladus, Rosetta, OSIRIS-REx, Titan and
    # a dozen more that mention "organic compound" once. The lesson was then written from what
    # it was given, and three separate reviewers rejected it for teaching habitability instead
    # of biomolecules. Three repair attempts could not fix it, because the evidence in front
    # of the author was genuinely about something else.
    #
    # A cap keeps one page from supplying an entire lesson without pretending a mission page
    # is as relevant as the article on proteins.
    per_source_cap = max(3, limit // 4)
    counts: Counter[int] = Counter(passage.source_id for passage in selected)
    for score, passage in scored:
        if len(selected) >= limit:
            break
        if score <= 0 or passage.id in chosen_ids:
            continue
        if counts[passage.source_id] >= per_source_cap:
            continue
        take(passage)
        counts[passage.source_id] += 1
    return selected

def _prompt(blueprint: dict, unit: dict, lesson: dict, passages: list[SourcePassage],
            sources: dict[int, Source]) -> str:
    return json.dumps({
        "course": blueprint["title"],
        "division": "B",
        "unit": unit["title"],
        "lesson_title": lesson["title"],
        "objective": lesson["objective"],
        "passages": [{
            "passage_id": passage.id,
            "source_title": sources[passage.source_id].title,
            "locator": passage.locator,
            "text": passage.text,
        } for passage in passages],
    })


# The author is told not to invent facts, and was never told what to do when the passages do
# not cover its objective — so it wrote lessons ABOUT the absence and keyed the answer to them.
# Nine Dynamic Planet checkpoints keyed to "the supplied evidence does not define this", for
# continentality, lake effect, sinuosity, turnover, wetland types and alluvial fans: in-scope
# topics deleted from the course, with the deletion graded. The prompt now forbids it and this
# refuses it, because a prompt is a request and a validator is a guarantee.
ABSENCE = re.compile(
    r"\b(not|never)\s+(defined|supplied|provided|described|stated|specified|given|available)\b|"
    r"\bcannot\s+be\s+(determined|inferred|justified|assigned|established|distinguished)\b|"
    r"\bmust\s+not\s+be\s+inferred\b|\bis\s+not\s+(supported|established)\s+by\b|"
    r"\bthe\s+(supplied|available)\s+(evidence|material|description|sources?)\b|"
    r"\bappears?\s+in\s+the\s+supplied\s+list\b|\bno\s+.{0,30}\s+is\s+(supplied|provided)\b",
    re.I)


def _reject_absence_content(blocks: list[dict]) -> None:
    """Refuse a lesson that teaches, or grades, the absence of its own evidence."""
    for block in blocks:
        if block.get("type") == "checkpoint":
            choices = block.get("choices") or []
            key = block.get("correct_index")
            if isinstance(key, int) and 0 <= key < len(choices) and ABSENCE.search(str(choices[key])):
                raise ValueError("checkpoint is keyed to the absence of evidence")
            if ABSENCE.search(str(block.get("explanation") or "")):
                raise ValueError("checkpoint explanation asserts the evidence is missing")
        text = json.dumps({k: v for k, v in block.items() if k != "passage_ids"})
        if len(ABSENCE.findall(text)) >= 2:
            raise ValueError(f"{block.get('type')} block is written about missing evidence")


def _normalize_blocks(raw: dict, allowed_passage_ids: set[int], lesson_slug: str) -> list[dict]:
    if isinstance(raw, dict) and raw.get("insufficient_evidence"):
        # The honest empty result. Better an absent lesson, recorded as a gap, than a lesson
        # that teaches students the sources were quiet.
        raise ValueError(f"insufficient evidence: {str(raw['insufficient_evidence'])[:160]}")
    blocks = raw.get("blocks") if isinstance(raw, dict) else None
    if not isinstance(blocks, list):
        raise ValueError("model returned no lesson blocks")
    _reject_absence_content([b for b in blocks if isinstance(b, dict)])
    normalized = []
    checkpoint_index = 0
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") not in {
            "opening", "property_cards", "steps", "worked_example", "checkpoint", "summary",
        }:
            continue
        item = dict(block)
        if item["type"] in TEACHING_TYPES | {"checkpoint"}:
            passage_ids = [
                int(value) for value in item.get("passage_ids", [])
                if str(value).isdigit() and int(value) in allowed_passage_ids
            ]
            if not passage_ids:
                raise ValueError(f"{item['type']} block has no valid passage citation")
            item["passage_ids"] = list(dict.fromkeys(passage_ids))
        if item["type"] == "checkpoint":
            choices = [str(value).strip() for value in item.get("choices", [])]
            correct = item.get("correct_index")
            if len(choices) != 4 or not isinstance(correct, int) or not 0 <= correct < 4:
                raise ValueError("checkpoint must have four choices and one valid answer")
            misconceptions = {
                str(key): str(value).strip()
                for key, value in (item.get("misconception_by_choice") or {}).items()
            }
            if any(str(index) not in misconceptions for index in range(4) if index != correct):
                raise ValueError("checkpoint is missing a distractor misconception")
            checkpoint_index += 1
            item["id"] = f"{lesson_slug}-check-{checkpoint_index}"
            item["choices"] = choices
            item["correct_index"] = correct
            item["misconception_by_choice"] = misconceptions
        normalized.append(item)
    if not normalized or normalized[0].get("type") != "opening":
        raise ValueError("lesson must begin with an opening")
    if normalized[-1].get("type") != "summary":
        raise ValueError("lesson must end with a summary")
    if sum(block["type"] in TEACHING_TYPES for block in normalized) < 3:
        raise ValueError("lesson needs at least three teaching interactions")
    checkpoints = [block for block in normalized if block["type"] == "checkpoint"]
    if len(checkpoints) < 3:
        raise ValueError("lesson needs at least three checkpoints")
    if not any(
        block.get("cognitive_level") in {"application", "transfer"}
        for block in checkpoints
    ):
        raise ValueError("lesson needs an application or transfer checkpoint")
    return normalized


def _course_sources(db, event: Event):
    source_ids = db.scalars(select(EventSourceMap.source_id).where(
        EventSourceMap.event_id == event.id
    )).all()
    sources = {
        source.id: source for source in db.scalars(select(Source).where(
            Source.id.in_(source_ids)
        )).all()
    }
    passages = db.scalars(select(SourcePassage).where(
        SourcePassage.source_id.in_(source_ids)
    ).order_by(SourcePassage.source_id, SourcePassage.sequence)).all()
    return sources, passages


def _ensure_scaffold(db, blueprint: dict, *, allow_live: bool = False):
    event = db.scalar(select(Event).where(
        Event.slug == blueprint["event_slug"],
        Event.season == blueprint["season"],
    ))
    if not event:
        raise ValueError(
            f"no event {blueprint['event_slug']!r} in season {blueprint['season']}")
    # Authoring rewrites the course's units and objectives and withdraws the legacy unit. Run
    # against a course students are already reading, that silently reshapes live teaching and
    # can take lessons dark — the failure this project has already had once. A course that is
    # serving published lessons must be extended deliberately, not re-scaffolded by default.
    published = db.scalar(select(func.count()).select_from(Lesson).where(
        Lesson.event_id == event.id, Lesson.status == "published")) or 0
    if published and not allow_live:
        raise SystemExit(
            f"{event.slug} already serves {published} published lesson(s). Re-scaffolding a "
            f"live course rewrites its units and can take that teaching dark. Pass "
            f"--allow-live only after deciding what happens to those lessons."
        )
    course = db.scalar(select(Course).where(Course.event_id == event.id))
    if course is None:
        course = Course(
            event_id=event.id, slug=event.slug, title=blueprint["title"],
            summary=blueprint["summary"], status="review_required", current_version=1,
        )
        db.add(course)
        db.flush()
        db.add(CourseVersion(
            course_id=course.id, version=1, objectives=blueprint["objectives"],
            review_status="authoring",
            release_notes="Passage-grounded vertical slice in editorial review.",
        ))
    else:
        course.title = blueprint["title"]
        course.summary = blueprint["summary"]
        course.status = "review_required"
        version = db.scalar(select(CourseVersion).where(
            CourseVersion.course_id == course.id,
            CourseVersion.version == course.current_version,
        ))
        if version:
            version.objectives = blueprint["objectives"]
            version.review_status = "authoring"
    legacy = db.scalar(select(CourseUnit).where(
        CourseUnit.course_id == course.id,
        CourseUnit.slug == "legacy-learning-path",
    ))
    if legacy:
        legacy.status = "withdrawn"
        legacy.sequence = 10_000

    rows = []
    sequence = 0
    for unit_index, unit_data in enumerate(blueprint["units"], start=1):
        unit = db.scalar(select(CourseUnit).where(
            CourseUnit.course_id == course.id,
            CourseUnit.slug == unit_data["slug"],
        ))
        if unit is None:
            unit = CourseUnit(
                course_id=course.id, slug=unit_data["slug"],
                title=unit_data["title"], summary=unit_data["summary"],
            )
            db.add(unit)
            db.flush()
        unit.title = unit_data["title"]
        unit.summary = unit_data["summary"]
        unit.objectives = unit_data["objectives"]
        unit.sequence = unit_index * 10
        unit.status = "review_required"
        skill_ids = []
        for lesson_data in unit_data["lessons"]:
            sequence += 1
            concept = db.scalar(select(Concept).where(
                Concept.event_id == event.id,
                Concept.name == lesson_data["title"],
            ))
            if concept is None:
                concept = Concept(
                    event_id=event.id, name=lesson_data["title"],
                    description=lesson_data["objective"], prerequisites=[],
                )
                db.add(concept)
                db.flush()
            skill = db.scalar(select(Skill).where(
                Skill.course_id == course.id,
                Skill.slug == lesson_data["slug"],
            ))
            if skill is None:
                skill = Skill(
                    course_id=course.id, unit_id=unit.id,
                    slug=lesson_data["slug"], name=lesson_data["title"],
                )
                db.add(skill)
                db.flush()
            skill.unit_id = unit.id
            skill.concept_id = concept.id
            skill.description = lesson_data["objective"]
            skill.sequence = sequence * 10
            skill.weight = 1.5 if lesson_data.get("high_weight") else 1.0
            skill.status = "review_required"
            skill_ids.append(skill.id)
            rows.append((unit_data, unit, lesson_data, skill, concept, sequence))
            for gap_type, description in (
                ("lesson", "Needs a passage-grounded teach lesson."),
                ("formative_check", "Needs approved formative practice."),
                ("transfer_item", "Needs an unseen transfer item."),
            ):
                gap = db.scalar(select(ContentGap).where(
                    ContentGap.skill_id == skill.id,
                    ContentGap.gap_type == gap_type,
                ))
                if gap is None:
                    db.add(ContentGap(
                        course_id=course.id, unit_id=unit.id, skill_id=skill.id,
                        gap_type=gap_type, description=description,
                    ))
        blueprint_row = db.scalar(select(AssessmentBlueprint).where(
            AssessmentBlueprint.course_id == course.id,
            AssessmentBlueprint.unit_id == unit.id,
            AssessmentBlueprint.assessment_type == "unit_quiz",
            AssessmentBlueprint.version == 1,
        ))
        if blueprint_row is None:
            db.add(AssessmentBlueprint(
                course_id=course.id, unit_id=unit.id, assessment_type="unit_quiz",
                version=1, title=f"{unit.title} Quiz", status="draft",
                specification={
                    "skill_ids": skill_ids, "question_count": 6,
                    "cognitive_mix": {"recall": 0.25, "application": 0.5, "transfer": 0.25},
                    "retryable": True,
                },
            ))
    for assessment_type, title in (
        ("course_diagnostic", "Check What I Know"),
        ("course_challenge", "Rocks and Minerals Course Challenge"),
        ("timed_simulation", "Competition Station Simulation"),
    ):
        existing = db.scalar(select(AssessmentBlueprint).where(
            AssessmentBlueprint.course_id == course.id,
            AssessmentBlueprint.unit_id.is_(None),
            AssessmentBlueprint.assessment_type == assessment_type,
            AssessmentBlueprint.version == 1,
        ))
        if existing is None:
            db.add(AssessmentBlueprint(
                course_id=course.id, unit_id=None, assessment_type=assessment_type,
                version=1, title=title, status="draft",
                specification={"coverage": "all_skills", "review_required": True},
            ))
    db.flush()
    return event, course, rows


def _video_block(passages: list[SourcePassage], sources: dict[int, Source]) -> dict | None:
    video_passage = next(
        (passage for passage in passages if passage.passage_type == "video_transcript"),
        None,
    )
    if not video_passage:
        return None
    # Snapshot metadata is loaded by the caller into the Source's metadata after
    # transcript ingestion; avoid another model call or external lookup.
    source = sources[video_passage.source_id]
    video = (source.metadata_json or {}).get("video") or {}
    if not video.get("video_id"):
        return None
    return {
        "type": "video",
        "video_id": video["video_id"],
        "title": video.get("title") or source.title,
        "channel": video.get("channel") or "",
        "duration": video.get("duration"),
        "transcript_source": source.id,
        "transcript_excerpt": (
            f"Focus on {video_passage.locator}; the notes and checks that follow "
            "use the retained transcript."
        ),
        "passage_ids": [video_passage.id],
    }


# A rejection names a specific falsehood — "3.9 to 7.3 micrometres described as a water-vapour
# channel", "hail initiation attributed to condensation nuclei rather than ice nuclei". Handing
# that back to the author is worth far more than regenerating the lesson blind and hoping the
# same sentence comes out differently: the reviewer has already done the hard part, which is
# saying exactly what is wrong.
REPAIR_PREFIX = """A subject-matter reviewer read your previous draft of this lesson and
REJECTED it. Their finding, verbatim:

{notes}

Write the lesson again, fixing exactly that. Everything the reviewer did not fault should come
out substantially as it was. Do not mention the review, the correction, or the previous draft
anywhere in the lesson — a student reads only the result.

"""


def _generate_one(provider, blueprint, unit_data, lesson_data, passages, sources,
                  correction: str = ""):
    prompt = _prompt(blueprint, unit_data, lesson_data, passages, sources)
    if correction:
        prompt = REPAIR_PREFIX.format(notes=correction.strip()) + prompt
    result = provider.generate_json(SYSTEM, prompt)
    blocks = _normalize_blocks(
        result.payload, {passage.id for passage in passages}, lesson_data["slug"]
    )
    if lesson_data.get("video"):
        block = _video_block(passages, sources)
        if block:
            blocks.insert(1, block)
    return {
        "payload": result.payload,
        "blocks": blocks,
        "provider": result.provider,
        "model": result.model,
    }


def author(*, apply: bool, generate: bool, regenerate: bool = False,
           blueprint_path: Path | None = None, allow_live: bool = False,
           only: set[str] | None = None, repair: bool = False,
           corrections_file: Path | None = None) -> dict:
    path = Path(blueprint_path or DEFAULT_BLUEPRINT)
    if not path.exists():
        raise SystemExit(f"no blueprint at {path}")
    blueprint = json.loads(path.read_text())
    report = {
        "mode": "apply" if apply else "dry_run",
        "blueprint": path.name,
        "event_slug": blueprint["event_slug"],
        "generate": generate,
        "units": len(blueprint["units"]),
        "planned_lessons": sum(len(unit["lessons"]) for unit in blueprint["units"]),
        "generated_lessons": 0,
        "failed": [],
    }
    if not apply:
        return report
    with SessionLocal() as db:
        event, course, scaffold = _ensure_scaffold(db, blueprint, allow_live=allow_live)
        corrections: dict[str, str] = {}
        if repair:
            # Every lesson an automated review faulted AT ITS CURRENT VERSION, with the
            # reviewer's own words. A lesson approved at version 3 and rejected at version 2 is
            # not repaired again; the decision that counts is the one about what is there now.
            for lesson, decision in db.execute(
                select(Lesson, ReviewDecision)
                .join(ReviewDecision, and_(
                    ReviewDecision.entity_type == "lesson",
                    ReviewDecision.entity_id == Lesson.id,
                    ReviewDecision.entity_version == Lesson.current_version,
                ))
                .where(
                    Lesson.event_id == event.id,
                    ReviewDecision.stage == "automated",
                    ReviewDecision.decision.in_(["reject", "rejected", "revise"]),
                )
                .order_by(ReviewDecision.id)
            ).all():
                corrections[lesson.slug] = decision.notes or ""
            # Findings from a reviewer that is not this pipeline — an expert read, a coach's
            # email, a student's bug report. An independent reviewer found a Tier 1 error in a
            # lesson the automated pass had APPROVED (the 4/3 refraction model stated as an
            # effective Earth curvature rather than an effective radius, which inverts it), so
            # the repair set cannot be only what one reviewer flagged.
            if corrections_file:
                for slug, note in json.loads(Path(corrections_file).read_text()).items():
                    corrections[slug] = (corrections.get(slug, "") + "\n\n" + note).strip()
            # A faulted lesson this blueprint does not contain cannot be repaired here at all.
            # The video "event strategy" lessons come from the video pipeline, not from a
            # blueprint, so `--repair` skips them in silence — and a repair loop then spends
            # every remaining round re-reviewing a lesson nothing it runs can touch, and
            # reports STILL FAULTED without ever saying why. Name them instead.
            authorable = {l["slug"] for unit in blueprint["units"] for l in unit["lessons"]}
            unrepairable = sorted(set(corrections) - authorable)
            if unrepairable:
                report["unrepairable"] = unrepairable
                for slug in unrepairable:
                    corrections.pop(slug, None)
            report["repairing"] = sorted(corrections)
            # Repair means repair: lessons nobody faulted are left exactly as they are.
            only = set(corrections) if only is None else (only & set(corrections))
            regenerate = True
        sources, all_passages = _course_sources(db, event)
        generation_rows = []
        for unit_data, unit, lesson_data, skill, concept, sequence in scaffold:
            passages = _select_passages(
                all_passages, sources, lesson_data["keywords"],
                require_video=bool(lesson_data.get("video")),
            )
            if not passages:
                gap = ContentGap(
                    course_id=course.id, unit_id=unit.id, skill_id=skill.id,
                    gap_type="source_support",
                    description="No retained source passage matched this skill.",
                )
                if not db.scalar(select(ContentGap).where(
                    ContentGap.skill_id == skill.id,
                    ContentGap.gap_type == "source_support",
                )):
                    db.add(gap)
                report["failed"].append({
                    "lesson": lesson_data["slug"], "reason": "no_matching_passages",
                })
                continue
            if only and lesson_data["slug"] not in only:
                continue
            generation_rows.append(
                (unit_data, unit, lesson_data, skill, concept, sequence, passages)
            )
        if generate:
            provider = OpenAICompatibleProvider()
            if not provider.configured:
                raise ModelProviderError("External model provider is not configured")
            results = {}
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = {
                    pool.submit(
                        _generate_one, provider, blueprint, unit_data, lesson_data,
                        passages, sources, corrections.get(lesson_data["slug"], ""),
                    ): lesson_data["slug"]
                    for unit_data, _, lesson_data, _, _, _, passages in generation_rows
                }
                for future in as_completed(futures):
                    slug = futures[future]
                    try:
                        results[slug] = future.result()
                    except Exception as exc:  # noqa: BLE001 - retain per-lesson failure
                        report["failed"].append({"lesson": slug, "reason": str(exc)[:500]})

            for unit_data, unit, lesson_data, skill, concept, sequence, passages in generation_rows:
                generated = results.get(lesson_data["slug"])
                if not generated:
                    continue
                lesson = db.scalar(select(Lesson).where(
                    Lesson.event_id == event.id,
                    Lesson.slug == lesson_data["slug"],
                ))
                if lesson and not regenerate:
                    continue
                if lesson is None:
                    lesson = Lesson(
                        event_id=event.id, slug=lesson_data["slug"],
                        title=lesson_data["title"], status="draft",
                    )
                    db.add(lesson)
                    db.flush()
                    version_number = 1
                else:
                    version_number = lesson.current_version + 1
                lesson.concept_id = concept.id
                lesson.title = lesson_data["title"]
                lesson.summary = str(
                    generated["payload"].get("summary") or lesson_data["objective"]
                )
                lesson.status = "draft"
                lesson.current_version = version_number
                lesson.sequence = sequence * 10
                lesson.estimated_minutes = max(
                    5, min(12, int(generated["payload"].get("estimated_minutes") or 8))
                )
                citations = [{
                    "source_id": passage.source_id,
                    "source_snapshot_id": passage.source_snapshot_id,
                    "source_passage_id": passage.id,
                    "title": sources[passage.source_id].title,
                    "publisher": sources[passage.source_id].publisher,
                    "url": sources[passage.source_id].url,
                    "locator": passage.locator,
                } for passage in passages]
                db.add(LessonVersion(
                    lesson_id=lesson.id, version=version_number,
                    content=generated["blocks"], claim_ids=[], citations=citations,
                    review_status="ai_draft",
                ))
                # Whatever the sources could not support is recorded here, as a gap a human
                # can close by finding a source — NOT written into the lesson. Before this,
                # the author's only two moves were to teach an unsupported claim or to refuse
                # the whole lesson, and it spent ten consecutive refusals declining to teach
                # four-fifths of a subject because one clause was unsourced.
                uncovered = [str(item)[:200] for item in
                             (generated["payload"].get("uncovered") or []) if str(item).strip()]
                if uncovered:
                    note = "; ".join(uncovered)[:1000]
                    gap = db.scalar(select(ContentGap).where(
                        ContentGap.skill_id == skill.id,
                        ContentGap.gap_type == "source_support",
                    ))
                    if gap is None:
                        db.add(ContentGap(
                            course_id=course.id, unit_id=unit.id, skill_id=skill.id,
                            gap_type="source_support",
                            description=f"Authored without source support for: {note}",
                        ))
                    else:
                        gap.description = f"Authored without source support for: {note}"
                    report.setdefault("uncovered", []).append(
                        {"lesson": lesson_data["slug"], "missing": uncovered})
                link = db.scalar(select(LessonSkill).where(
                    LessonSkill.lesson_id == lesson.id,
                    LessonSkill.skill_id == skill.id,
                ))
                if link is None:
                    db.add(LessonSkill(
                        lesson_id=lesson.id, skill_id=skill.id,
                        is_primary=True, weight=1.0,
                    ))
                lesson_gap = db.scalar(select(ContentGap).where(
                    ContentGap.skill_id == skill.id,
                    ContentGap.gap_type == "lesson",
                ))
                if lesson_gap:
                    lesson_gap.status = "in_review"
                    lesson_gap.resolution_notes = (
                        f"AI draft lesson {lesson.id} version {version_number}; "
                        "editor and SME approval still required."
                    )
                for passage in passages:
                    coverage = db.scalar(select(CourseSourceCoverage).where(
                        CourseSourceCoverage.course_id == course.id,
                        CourseSourceCoverage.source_id == passage.source_id,
                    ))
                    if not coverage:
                        continue
                    coverage.mapped_unit_ids = sorted(set(coverage.mapped_unit_ids + [unit.id]))
                    coverage.mapped_skill_ids = sorted(set(coverage.mapped_skill_ids + [skill.id]))
                    coverage.lesson_ids = sorted(set(coverage.lesson_ids + [lesson.id]))
                    if coverage.student_destination != "staff_only":
                        coverage.student_destination = (
                            f"/courses/{event.season}/{event.slug}/lesson/{lesson.slug}"
                        )
                    if coverage.review_status == "needs_instructional_mapping":
                        coverage.review_status = "lesson_draft_review"
                report["generated_lessons"] += 1
        db.commit()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--regenerate", action="store_true")
    parser.add_argument("--blueprint", default=str(DEFAULT_BLUEPRINT),
                        help="path to a course blueprint JSON under data/courses/")
    parser.add_argument("--allow-live", action="store_true",
                        help="permit re-scaffolding a course that serves published lessons")
    # `--regenerate` rewrites every lesson in the blueprint and sets each one back to draft.
    # That is right for a first rebuild and wrong for a repair: when a review withdraws 15 of
    # a course's 21 lessons, regenerating the blueprint would also pull the 6 that survived
    # out of the catalog, and a student mid-course would watch the subject empty out. Name the
    # lessons being repaired and the rest are left exactly as they are.
    parser.add_argument("--corrections", default=None,
                        help="JSON file mapping lesson slug -> a reviewer's finding, merged "
                             "into --repair (use for findings from outside this pipeline)")
    parser.add_argument("--repair", action="store_true",
                        help="re-author only the lessons an automated review faulted, handing "
                             "the reviewer's own finding back to the author")
    parser.add_argument("--only", default="",
                        help="comma-separated lesson slugs to author; others are left untouched")
    args = parser.parse_args()
    if args.generate and not args.apply:
        raise SystemExit("--generate requires --apply")
    print(json.dumps(author(
        apply=args.apply, generate=args.generate, regenerate=args.regenerate,
        blueprint_path=Path(args.blueprint), allow_live=args.allow_live,
        only={s.strip() for s in args.only.split(",") if s.strip()} or None,
        repair=args.repair,
        corrections_file=Path(args.corrections) if args.corrections else None,
    ), indent=2))


if __name__ == "__main__":
    main()
