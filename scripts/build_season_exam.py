"""Build a season mock exam shaped like the real papers for that event.

A generic pile of multiple choice is not what a student meets at a tournament. The 2026 BullSO
Dynamic Planet B paper runs True/False worth a point each, then two matching sets, then multiple
choice, then picture-based questions, then a hypothetical-world scenario as the tie-breaker — and
its True/False items are multi-clause traps, not trivia ("because seawater density increases with
decreasing temperature and increasing salinity, regions of intense evaporation at low latitudes
are the primary sites of deep water formation" is false for a reason a student has to reason
about). Practice that does not rehearse that shape leaves the shape itself untrained.

So the section structure here is copied from real papers, while every question is newly written
from this event's own grounded passages. Nothing is copied from a past test: the papers are
copyright-restricted and stay link-only, and their content is the wrong season's topic anyway.

The exam is labelled `machine_practice` — "AI Practice · Not Expert Reviewed" — because that is
what it is. It never claims editor, SME or calibration approval.

Usage:
  python -m scripts.build_season_exam --event dynamic-planet-b-2027 --format invitational
  python -m scripts.build_season_exam --event dynamic-planet-b-2027 --format invitational --apply
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from pathlib import Path

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import (
    Event, Exam, ExamItem, EventSourceMap, Question, Source, SourcePassage,
)
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider
from app.services.scoring import is_gradeable
from app.services.season_status import HIDDEN_SEASON_STATUSES
from scripts.author_course_from_blueprint import _select_passages

PROMPT_VERSION = "season-exam-sectioned-v2"
REPO = Path(__file__).resolve().parent.parent


def _scope_topics(event) -> list[str]:
    """This event's tested topics, from the season scope manifest.

    Without these, a long single-section run is steered by nothing: every batch gets the same
    passage selection and writes about the same few ideas. The first 32-item state paper spent
    7 items on Strahler ordering and 8 on drainage basins and never once asked about groundwater,
    karst, sediment, floods or lakes — four of thirteen topics for a whole paper. The syllabus is
    already written down; the exam should walk it.
    """
    base = re.sub(r"-(19|20)\d{2}$", "", event.slug)
    division = "b" if base.endswith("-b") else "c" if base.endswith("-c") else None
    season = re.search(r"-((?:19|20)\d{2})$", event.slug)
    if not (division and season):
        return []
    path = REPO / f"docs/season_{season.group(1)}/division_{division}_scope.json"
    if not path.exists():
        return []
    name = re.sub(r"[^a-z0-9]+", " ", event.name.lower()).strip()
    for spec in json.loads(path.read_text()).get("events", []):
        if re.sub(r"[^a-z0-9]+", " ", spec["event"].lower()).strip() == name:
            return [t for t in spec.get("topics", []) if t]
    return []

# Section shapes taken from real papers for this event family. `points` is what the source paper
# pays for such an item; the platform scores one point per item, so it is recorded for
# transparency and to set item timing rather than to weight the score.
FORMATS = {
    "invitational": {
        "reference": ("BullSO 2026 Invitational, Dynamic Planet B — 58 points: True/False, "
                      "two matching sets, multiple choice, picture-based, scenario tie-breaker"),
        "duration_minutes": 50,
        "sections": [
            {"key": "true_false", "title": "I. True/False", "kind": "true_false",
             "count": 8, "points": 1,
             "guidance": "Each statement must be a MULTI-CLAUSE claim that sounds authoritative "
                         "and is decidable from the passage. Roughly half should be false "
                         "because a correct mechanism is attached to a wrong conclusion, a "
                         "wrong place, or an overreaching 'always/solely/primary'. Never write "
                         "a bare definition. The statement is yours to compose; quote the "
                         "passage sentence that establishes the mechanism it hinges on."},
            {"key": "matching_surface", "title": "II. Matching — Channels and Landforms",
             "kind": "matching", "count": 5, "points": 1,
             "guidance": "Each item names one landform or channel term and asks which "
                         "description matches it. Distractors must be OTHER real terms' "
                         "descriptions from the same family, so the set works as a matching "
                         "column."},
            {"key": "matching_subsurface", "title": "II. Matching — Groundwater and Karst",
             "kind": "matching", "count": 5, "points": 1,
             "guidance": "As above, for subsurface and karst vocabulary."},
            {"key": "multiple_choice", "title": "III. Multiple Choice", "kind": "single_choice",
             "count": 14, "points": 2,
             "guidance": "Mix recall, application and at least three transfer items that require "
                         "reasoning across two ideas (for example a control on precipitation "
                         "combined with a consequence for streamflow)."},
            {"key": "data", "title": "IV. Data Interpretation", "kind": "data",
             "count": 5, "points": 2,
             "guidance": "Each stem must EMBED a small data display as aligned plain text — a "
                         "stage/discharge table, a hydrograph given as time-value pairs, a "
                         "grain-size distribution, a longitudinal profile as distance/elevation "
                         "pairs, or a flood-frequency series. The question must be unanswerable "
                         "without reading the numbers. State units. Keep arithmetic doable "
                         "without a calculator. The numbers are yours to construct and need "
                         "not appear in any passage; the RELATIONSHIP they test must be the "
                         "one your quoted excerpt establishes. The answer must NOT be a value "
                         "readable straight off the display — that tests looking, not "
                         "interpreting. Require interpolation between rows, a computation from "
                         "two quantities, a comparison of rates or slopes, a ranking, or an "
                         "inference about what the pattern implies."},
            {"key": "scenario", "title": "V. Scenario (Tie-Breaker)", "kind": "short_answer",
             "count": 2, "points": 3,
             "guidance": "Pose a short hypothetical basin or aquifer scenario and ask for one "
                         "specific term, landform or direction as the answer. The answer must be "
                         "one or two words so it can be marked objectively; supply every "
                         "acceptable spelling and synonym in `accepted`."},
        ],
    },
    "state": {
        "reference": ("2025 USC Invitational, Dynamic Planet C — 192 points: a long "
                      "topic-ordered multiple-choice run at 2 points each"),
        "duration_minutes": 50,
        "sections": [
            {"key": "multiple_choice", "title": "Multiple Choice", "kind": "single_choice",
             "count": 40, "points": 2,
             "guidance": "Order the run so it walks the event's topics in teaching order and "
                         "rises in difficulty. Include quantitative items."},
        ],
    },
}

BASE_RULES = """You are an expert Science Olympiad assessment author writing ORIGINAL exam
questions from supplied source passages. Never copy a question from any existing test. Never
invent a measurement, rule or landform property that the passages do not support.

Every item must include:
  stem, explanation, cognitive_level (recall|application|transfer), difficulty (0-1),
  estimated_seconds, passage_id, claim_text, evidence_excerpt.
`evidence_excerpt` must be a SHORT EXACT quote (40 words max) copied character-for-character
from the cited passage. It grounds the PRINCIPLE the item tests, not the wording of your stem:
you may compose a statement or a dataset that applies the principle, but the sentence you quote
must be one that actually appears in the passage and must establish the mechanism the item turns
on. Copy it by exact substring, changing nothing — not punctuation, not capitalisation.
`explanation` must teach the reasoning, not restate the key.
Output strict JSON {"items": [...]} and nothing else."""

KIND_RULES = {
    "true_false": """This section is True/False. Each item has exactly two choices,
["True", "False"], with correct_index 0 or 1, plus misconception_by_choice for the wrong
choice explaining the specific reasoning error. Do NOT prefix the stem with "True or False:" —
the choices already say so, and the real papers do not.""",
    "matching": """Each item has exactly four distinct choices and correct_index, plus
rationale_by_choice for all four and misconception_by_choice for the three wrong ones.""",
    "single_choice": """Each item has exactly four distinct choices and correct_index, plus
rationale_by_choice for all four and misconception_by_choice for the three wrong ones.""",
    "data": """Each item has exactly four distinct choices and correct_index, plus
rationale_by_choice for all four and misconception_by_choice for the three wrong ones. The data
display goes INSIDE the stem, as plain text lines the student can read.""",
    "short_answer": """This section is short answer. Give no choices. Instead give
`answer` (the reference answer, one or two words) and `accepted` (an array of other acceptable
spellings, synonyms and casings). Also give `misconception` naming the most likely wrong answer
and why it is wrong.""",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


def _feedback_map(raw) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): str(v).strip() for k, v in raw.items() if str(v).strip()}
    if isinstance(raw, list):
        return {str(i): str(v).strip() for i, v in enumerate(raw) if str(v).strip()}
    return {}


def _validate(raw: dict, kind: str, passages: dict[int, SourcePassage]) -> dict:
    """Shared checks, then the ones specific to the section's question kind.

    The evidence check is the load-bearing one: an excerpt that is not verbatim in the cited
    passage means the item is not actually grounded, whatever it claims.
    """
    if not isinstance(raw, dict):
        raise ValueError("item is not an object")
    stem = str(raw.get("stem") or "").strip()
    if len(stem) < 15:
        raise ValueError("stem is too short")
    passage_id = raw.get("passage_id")
    if not isinstance(passage_id, int) or passage_id not in passages:
        raise ValueError("item cites an unavailable passage")
    excerpt = str(raw.get("evidence_excerpt") or "").strip()
    if not excerpt or len(excerpt.split()) > 40:
        raise ValueError("evidence excerpt is missing or too long")
    if _normalize(excerpt) not in _normalize(passages[passage_id].text):
        raise ValueError("evidence excerpt is not verbatim in the cited passage")
    claim = str(raw.get("claim_text") or "").strip()
    if len(claim) < 20:
        raise ValueError("grounding claim is too short")
    cognitive = str(raw.get("cognitive_level") or "application").lower()
    if cognitive not in {"recall", "application", "transfer"}:
        raise ValueError(f"invalid cognitive level {cognitive!r}")
    try:
        difficulty = max(0.0, min(1.0, float(raw.get("difficulty", 0.5))))
        seconds = max(20, min(300, int(raw.get("estimated_seconds", 60))))
    except (TypeError, ValueError) as exc:
        raise ValueError("timing or difficulty is invalid") from exc

    out = {
        "stem": stem, "explanation": str(raw.get("explanation") or "").strip(),
        "cognitive_level": cognitive, "difficulty": difficulty,
        "estimated_seconds": seconds, "passage_id": passage_id,
        "claim_text": claim, "evidence_excerpt": excerpt,
    }

    if kind == "short_answer":
        answer = str(raw.get("answer") or "").strip()
        if not answer:
            raise ValueError("short answer item has no reference answer")
        if len(answer.split()) > 4:
            raise ValueError("short answer reference is too long to mark objectively")
        accepted = [str(v).strip() for v in (raw.get("accepted") or []) if str(v).strip()]
        out.update(question_type="short_answer", choices=[],
                   answer_spec={"answer": answer, "accepted": accepted,
                                "misconception": str(raw.get("misconception") or "").strip()})
        return out

    choices = [str(v).strip() for v in (raw.get("choices") or [])]
    expected = 2 if kind == "true_false" else 4
    if len(choices) != expected or len({c.casefold() for c in choices}) != expected:
        raise ValueError(f"{kind} item needs {expected} distinct choices")
    if kind == "true_false" and [c.casefold() for c in choices] != ["true", "false"]:
        raise ValueError("true/false choices must be exactly True then False")
    correct = raw.get("correct_index")
    if not isinstance(correct, int) or not 0 <= correct < expected:
        raise ValueError("invalid correct_index")
    misconceptions = _feedback_map(raw.get("misconception_by_choice"))
    if kind == "true_false" and not misconceptions:
        # With two choices there is exactly one wrong answer, so a single `misconception`
        # string is the natural shape and the model reaches for it; accept it rather than
        # discarding a sound item over the key it was filed under.
        single = str(raw.get("misconception") or "").strip()
        if single:
            misconceptions = {str(1 - correct): single}
    if any(str(i) not in misconceptions for i in range(expected) if i != correct):
        raise ValueError("item is missing a distractor misconception")
    rationales = _feedback_map(raw.get("rationale_by_choice"))
    if kind != "true_false" and any(str(i) not in rationales for i in range(expected)):
        raise ValueError("item is missing a choice rationale")
    out.update(question_type="single_choice", choices=choices,
               answer_spec={"correct_index": correct,
                            "rationale_by_choice": rationales,
                            "misconception_by_choice": misconceptions})
    return out


# Asking for many items in one call produces a long reply that gets truncated, and the items at
# the end come back missing fields — the True/False section returned 8 stems and lost
# `evidence_excerpt` on all of them, which the validator then correctly refused. Small batches
# keep every item whole.
BATCH_SIZE = 4


def _one_batch(provider, event, section, chosen, index, want, avoid, topics) -> list[dict]:
    system = f"{BASE_RULES}\n\n{KIND_RULES[section['kind']]}"
    payload = provider.generate_json(system, json.dumps({
        "event": event.name,
        "topic_focus": event.topic_focus,
        "section": section["title"],
        "item_count": want,
        "section_guidance": section["guidance"],
        "write_about_these_topics_only": topics,
        "avoid_these_stems": avoid[-16:],
        "passages": [{"passage_id": p.id, "locator": p.locator,
                      "source_title": p.source_title,
                      "text": p.text[:1600]} for p in chosen],
    }, ensure_ascii=False)).payload
    items, failures = [], []
    for raw in (payload or {}).get("items", []):
        try:
            item = _validate(raw, section["kind"], index)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        if not is_gradeable(item["question_type"], item["answer_spec"]):
            failures.append("item is not auto-gradeable")
            continue
        items.append(item)
    if failures:
        print(f"      {section['title']}: rejected {len(failures)} "
              f"({', '.join(sorted(set(failures))[:2])})", flush=True)
    return items


def _generate_section(provider, event, section, passages, sources,
                      scope_topics: list[str]) -> list[dict]:
    wanted = section["count"]
    # Walk the syllabus in slices, so a long run spreads across topics instead of circling the
    # handful that the section's own wording happens to favour.
    slices: list[list[str]] = []
    if scope_topics and section["kind"] in {"single_choice", "data", "true_false"}:
        per_batch = max(1, -(-len(scope_topics) // max(1, -(-wanted // BATCH_SIZE))))
        slices = [scope_topics[i:i + per_batch] for i in range(0, len(scope_topics), per_batch)]
    collected: list[dict] = []
    seen: set[str] = set()
    batches = -(-wanted // BATCH_SIZE) + 1
    for attempt in range(batches):
        if len(collected) >= wanted:
            break
        topics = slices[attempt % len(slices)] if slices else []
        keywords = re.findall(r"[a-z]{4,}",
                              (" ".join(topics) or section["guidance"]).lower())
        chosen = _select_passages(passages, sources, keywords or [event.name.lower()],
                                 require_video=False)[:14]
        if not chosen:
            continue
        for p in chosen:               # the prompt needs the title, the row has only the id
            p.source_title = sources[p.source_id].title
        index = {p.id: p for p in chosen}
        want = min(BATCH_SIZE, wanted - len(collected))
        try:
            batch = _one_batch(provider, event, section, chosen, index, want,
                               [i["stem"] for i in collected], topics)
        except ModelProviderError as exc:
            print(f"      {section['title']}: provider error {exc}", flush=True)
            break
        for item in batch:
            key = _normalize(item["stem"])[:120]
            if key in seen:
                continue
            seen.add(key)
            item["section"] = section["title"]
            item["source_points"] = section["points"]
            item["scope_topics"] = topics
            collected.append(item)
    return collected[:wanted]


def build(event_slug: str, format_key: str, apply: bool) -> dict:
    spec = FORMATS[format_key]
    db = SessionLocal()
    event = db.scalar(select(Event).where(Event.slug == event_slug))
    if not event:
        raise SystemExit(f"unknown event {event_slug!r}")
    source_ids = db.scalars(select(EventSourceMap.source_id).where(
        EventSourceMap.event_id == event.id)).all()
    sources = {s.id: s for s in db.scalars(
        select(Source).where(Source.id.in_(source_ids))).all()}
    passages = db.scalars(select(SourcePassage).where(
        SourcePassage.source_id.in_(source_ids)
    ).order_by(SourcePassage.source_id, SourcePassage.sequence)).all()
    print(f"{event.slug}: {len(sources)} sources, {len(passages)} passages")
    if not passages:
        raise SystemExit("no grounded passages; run ground_event and extract passages first")

    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise SystemExit("model provider is not configured")
    scope_topics = _scope_topics(event)
    print(f"   steering across {len(scope_topics)} scope topics"
          if scope_topics else "   no scope manifest topics; sections steer themselves")

    built: list[dict] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_generate_section, provider, event, s, passages, sources,
                                   scope_topics): s
                   for s in spec["sections"]}
        for future in as_completed(futures):
            section = futures[future]
            try:
                items = future.result()
            except (ModelProviderError, ValueError) as exc:
                print(f"   {section['title']}: FAILED {exc}", flush=True)
                continue
            print(f"   {section['title']}: {len(items)}/{section['count']} items", flush=True)
            built.append({"section": section, "items": items})

    order = {s["key"]: i for i, s in enumerate(spec["sections"])}
    built.sort(key=lambda b: order[b["section"]["key"]])
    items = [i for b in built for i in b["items"]]
    points = sum(i["source_points"] for i in items)
    report = {"event": event.slug, "format": format_key, "items": len(items),
              "source_points": points,
              "by_section": {b["section"]["title"]: len(b["items"]) for b in built}}
    if not apply:
        report["mode"] = "dry_run"
        for b in built[:1]:
            for i in b["items"][:2]:
                print(f"\n   sample [{i['section']}] {i['stem'][:160]}")
                print(f"      choices={i['choices']} spec={list(i['answer_spec'])}")
        return report
    if len(items) < 10:
        raise SystemExit(f"only {len(items)} valid items; refusing to publish a thin exam")

    passage_by_id = {p.id: p for p in passages}
    questions: list[Question] = []
    for item in items:
        passage = passage_by_id[item["passage_id"]]
        source = sources[passage.source_id]
        question = Question(
            event_id=event.id, source_id=source.id,
            status="draft",
            question_type=item["question_type"], stem=item["stem"],
            choices=item["choices"], answer_spec=item["answer_spec"],
            explanation=item["explanation"],
            citations=[{"source_id": source.id,
                        "source_snapshot_id": passage.source_snapshot_id,
                        "source_passage_id": passage.id,
                        "title": source.title, "url": source.url,
                        "locator": passage.locator}],
            difficulty=item["difficulty"], cognitive_level=item["cognitive_level"],
            estimated_seconds=item["estimated_seconds"],
            validation_report={
                "passed": False, "structural_checks": "passed",
                "errors": ["unreviewed_machine_authored"],
                "review_required": ["editor", "sme", "calibration"],
                "validator_version": PROMPT_VERSION,
            },
            generation_provenance={
                "prompt_version": PROMPT_VERSION,
                "section": item["section"],
                "source_paper_points": item["source_points"],
                "format_reference": spec["reference"],
                "claim_text": item["claim_text"],
                "evidence_excerpt": item["evidence_excerpt"],
                "machine_authored": True,
            },
        )
        db.add(question)
        questions.append(question)
    db.flush()

    existing = db.scalar(select(func.count()).select_from(Exam).where(
        Exam.event_id == event.id,
        Exam.blueprint["exam_format"].as_string() == format_key)) or 0
    # An exam published under an event no catalog lists is findable by nobody. While the course
    # is `in_development` the exam is built but left unpublished, which is the same honest state
    # its lessons are in as drafts — it is published when the event goes live, not before.
    event_hidden = event.season_status in HIDDEN_SEASON_STATUSES or not event.active
    exam = Exam(
        event_id=event.id,
        title=f"{event.name} — {format_key.title()} Mock Exam"
              + (f" {existing + 1}" if existing else ""),
        duration_minutes=spec["duration_minutes"],
        question_ids=[q.id for q in questions],
        published=not event_hidden,
        disposition="machine_practice",
        release_class="machine_practice",
        blueprint={
            "import_kind": "authored_season_exam",
            "exam_format": format_key,
            "format_reference": spec["reference"],
            "feedback_mode": "after_submit",
            "question_count": len(questions),
            "source_points_total": points,
            "sections": [{"title": b["section"]["title"], "items": len(b["items"]),
                          "points_each": b["section"]["points"]} for b in built],
            "snapshot_schema": 1,
        },
    )
    db.add(exam)
    db.flush()
    for position, (question, item) in enumerate(zip(questions, items)):
        db.add(ExamItem(
            exam_id=exam.id, question_id=question.id, question_version=question.version,
            position=position,
            snapshot={
                "stem": question.stem, "choices": question.choices,
                "question_type": question.question_type,
                "answer_spec": question.answer_spec,
                "explanation": question.explanation,
                "section": item["section"],
                "source_points": item["source_points"],
                "scope_topics": item.get("scope_topics") or [],
            },
        ))
    db.commit()
    report.update(mode="apply", exam_id=exam.id, published=exam.published,
                  question_ids=[q.id for q in questions][:5])
    if event_hidden:
        print(f"   built unpublished: {event.slug} is {event.season_status!r}, so a published "
              f"exam there would be reachable by nobody. Publish it when the event goes live.")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True)
    ap.add_argument("--format", default="invitational", choices=sorted(FORMATS))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    print(json.dumps(build(args.event, args.format, args.apply), indent=2))


if __name__ == "__main__":
    main()
