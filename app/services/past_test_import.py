"""Parse a downloaded past test (a Source's extracted PDF text) into structured
Question rows, then assemble them into a takeable mock Exam.

The heavy lifting — segmenting the raw PDF text into items, aligning an answer
key, classifying question type, flagging items that need an image we don't have —
is done by the configured LLM (OpenAICompatibleProvider). Imported questions are
DRAFT/practice, clearly marked in generation_provenance as import_kind="past_test".
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.student_visibility import DISPOSITION_UNREVIEWED_PRACTICE
from app.models.entities import (
    Event, EventSourceMap, Exam, ExamItem, Question, QuestionStatus, RawArtifact,
    Source, SourceSnapshot,
)
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider
from app.services.pdf_figures import (
    RESOLVING_MATCHES, attach_figures_to_items, extract_figures,
)

MAX_TEXT_CHARS = 30_000
PROMPT_VERSION = "past-test-parse-v1"

FEEDBACK_MODES = {"after_submit", "per_question"}

_SYSTEM = (
    "You parse Science Olympiad practice tests into structured assessment items. "
    "You are given the raw extracted text of a test, and optionally its answer key. "
    "Return STRICT JSON of the form {\"items\": [ ... ]}. Each item is one smallest "
    "answerable unit and has fields: "
    "section (string|null, e.g. 'Station A' or 'Section A'), "
    "label (string, the item's number/letter as printed, e.g. '1' or '2b'), "
    "stem (string, the full cleaned question text; expand it so it is answerable on "
    "its own), "
    "question_type (one of 'single_choice','short_answer','numeric'), "
    "choices (array of strings; [] unless it is genuinely multiple choice), "
    "correct_index (integer index into choices, or null), "
    "reference_answer (string; the official answer from the key or clearly stated in "
    "the text; '' if unknown), "
    "accepted (array of acceptable answer strings/synonyms; may be []), "
    "acceptance_notes (string; rubric guidance like 'accept >= 5 solar masses'; '' if "
    "none), "
    "points (number; default 1), "
    "image_dependent (boolean; true if the item cannot be answered without a specific "
    "image, specimen, illustration, or figure that is not reproduced in the text). "
    "Rules: never invent answers you cannot support from the provided text/key; "
    "preserve the printed numbering; do not copy long verbatim passages beyond the "
    "question wording; output only the JSON object."
)


def _normalize(text: str) -> str:
    # pypdf frequently doubles inter-word spaces; collapse runs of whitespace.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _latest_snapshot(db: Session, source_id: int) -> SourceSnapshot | None:
    return db.scalar(select(SourceSnapshot).where(
        SourceSnapshot.source_id == source_id
    ).order_by(SourceSnapshot.created_at.desc(), SourceSnapshot.id.desc()))


def parse_items(exam_text: str, key_text: str, event: Event) -> list[dict]:
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise ModelProviderError("External model provider is not configured")
    user = json.dumps({
        "event": event.name,
        "division": event.division,
        "test_text": _normalize(exam_text)[:MAX_TEXT_CHARS],
        "answer_key_text": _normalize(key_text)[:MAX_TEXT_CHARS] if key_text else "",
    })
    result = provider.generate_json(_SYSTEM, user)
    items = result.payload.get("items", [])
    if not isinstance(items, list) or not items:
        raise ModelProviderError("Model returned no items")
    return items


def _safe_points(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0


def _answer_spec(item: dict) -> tuple[str, list, dict]:
    """Return (question_type, choices, answer_spec) compatible with scoring.score_response."""
    points = _safe_points(item.get("points"))
    choices = [str(c) for c in (item.get("choices") or [])]
    qtype = item.get("question_type") or "short_answer"
    correct_index = item.get("correct_index")
    if qtype == "single_choice" and choices and isinstance(correct_index, int):
        return "single_choice", choices, {
            "correct_index": correct_index, "points": points, "distractor_error_types": {},
        }
    reference = str(item.get("reference_answer") or "").strip()
    accepted = [str(a).strip() for a in (item.get("accepted") or []) if str(a).strip()]
    if qtype == "numeric":
        try:
            value = float(reference)
            return "numeric", [], {
                "answer": value, "tolerance": max(abs(value) * 0.01, 1e-6), "points": points,
            }
        except (TypeError, ValueError):
            pass  # fall through to short_answer when the reference is not a clean number
    return "short_answer", [], {
        "answer": reference, "accepted": accepted, "points": points,
        "rubric": str(item.get("acceptance_notes") or ""),
    }


_TEST_TOKENS = re.compile(r"\b(TEST|EXAM|QUESTIONS?)\b", re.I)
_KEY_TOKENS = re.compile(r"\b(KEY|ANSWERS?|SOLUTIONS?)\b", re.I)
_TRIM = re.compile(r"[^a-z0-9]+")


def _stem_title(title: str) -> str:
    """The part of a title that identifies the test, with the role word removed."""
    without_role = _KEY_TOKENS.sub(" ", _TEST_TOKENS.sub(" ", title or ""))
    return _TRIM.sub(" ", without_role.lower()).strip()


def find_key_source(db: Session, exam_source: Source,
                    event: "Event | None" = None) -> Source | None:
    """Find the answer key that belongs to this test.

    27 of 96 imports ran with no key at all — 1,226 items — while the matching key sat in the
    database under a title differing by one word. `Astronomy … 2026 TEST` imported 55
    multiple-choice items with an empty answer on every one, next to `Astronomy … 2026 KEY`
    that nothing ever opened. The importer simply never looked.

    Matching is on the title with the role word removed, and it must be exact after
    normalisation. A fuzzy match here would attach one event's key to another event's test,
    which produces confidently wrong grading — strictly worse than the missing key it
    replaces. When two candidates tie, none is chosen.

    Normalised titles are not unique across the catalog, so title alone is not enough:
    adversarial review pointed out that two events can own identically-named files and the
    sole match would then be another event's key. When the event is known, candidates are
    restricted to sources mapped to it.
    """
    if not _TEST_TOKENS.search(exam_source.title or ""):
        # not named as a test; there is no role word to swap, so nothing reliable to match on
        return None
    wanted = _stem_title(exam_source.title)
    if not wanted:
        return None
    candidates = [
        source for source in db.scalars(select(Source).where(
            Source.id != exam_source.id)).all()
        if _KEY_TOKENS.search(source.title or "") and _stem_title(source.title) == wanted
    ]
    if event is not None:
        mapped = set(db.scalars(select(EventSourceMap.source_id).where(
            EventSourceMap.event_id == event.id)).all())
        if mapped:
            scoped = [c for c in candidates if c.id in mapped]
            # only narrow when the mapping actually knows about this event's sources; an
            # empty intersection means the mapping is incomplete, not that the key is wrong
            if scoped:
                candidates = scoped
        exam_mapped = db.scalar(select(EventSourceMap).where(
            EventSourceMap.event_id == event.id,
            EventSourceMap.source_id == exam_source.id))
        if exam_mapped is not None and mapped:
            # the test is mapped to this event, so a key that is not is a different event's
            candidates = [c for c in candidates if c.id in mapped]
    if len(candidates) != 1:
        return None
    return candidates[0]


LOW_CONFIDENCE = 0.6

# Some findings are not deductions, they are the absence of the thing being scored. Weighing
# them alongside cosmetic signals put "no answer at all" at exactly 0.6 and an out-of-range
# choice index at 0.65 — so the two most decisive defects cleared the bar on their own while
# a missing label and a short stem together did not. Any of these disqualifies the parse
# regardless of what the arithmetic says.
DISQUALIFYING = {
    "no_reference_answer",
    "no_valid_correct_index",
    "multiple_choice_without_choices",
    "stem_too_short_to_be_a_question",
}


def is_trustworthy(score: float, reasons: list[str]) -> bool:
    """Whether the parse established enough for its answer to be graded against."""
    if any(reason in DISQUALIFYING for reason in reasons):
        return False
    return score >= LOW_CONFIDENCE


def parse_confidence(item: dict) -> tuple[float, list[str]]:
    """Score how much of an item the parser actually established, from observable facts.

    The model is not asked to rate its own output. A parser confident enough to be wrong is
    exactly the failure mode here, and self-reported confidence is the one signal that cannot
    be checked. Every signal below is verifiable after the fact: whether the stem was found
    in the source text, whether an answer exists, whether the choice structure is coherent.
    """
    reasons: list[str] = []
    score = 1.0

    # A stem that cannot be found in the source is a paraphrase at best, invented at worst.
    if item.get("page") is None:
        score -= 0.35
        reasons.append("stem_not_found_in_source")

    qtype = item.get("question_type") or "short_answer"
    choices = [c for c in (item.get("choices") or []) if str(c).strip()]
    correct_index = item.get("correct_index")
    if qtype == "single_choice":
        if len(choices) < 2:
            score -= 0.4
            reasons.append("multiple_choice_without_choices")
        if not isinstance(correct_index, int) or not 0 <= correct_index < len(choices):
            score -= 0.35
            reasons.append("no_valid_correct_index")
    else:
        if not str(item.get("reference_answer") or "").strip():
            score -= 0.4
            reasons.append("no_reference_answer")
        if choices:
            score -= 0.1
            reasons.append("choices_on_a_non_choice_item")

    stem = str(item.get("stem") or "").strip()
    if len(stem) < 15:
        score -= 0.3
        reasons.append("stem_too_short_to_be_a_question")
    elif len(stem) > 1200:
        # several printed items almost certainly ran together into one
        score -= 0.2
        reasons.append("stem_long_enough_to_be_merged_items")
    if not str(item.get("label") or "").strip():
        score -= 0.1
        reasons.append("no_printed_label")
    if item.get("image_dependent") and item.get("figure_match") != "unique":
        score -= 0.2
        reasons.append("needs_a_figure_that_is_not_pinned")

    return max(0.0, round(score, 3)), reasons


def answer_confidence(item: dict) -> tuple[float, list[str]]:
    """Score only whether the *answer* was established — not whether the stem was.

    These were one number, and adversarial review showed the conflation cut both ways: a
    perfectly good official answer was erased because its stem could not be located in the
    extracted text (a PDF-extraction artefact, not an answer problem), while a multiple-choice
    item with equally poor signals kept a valid-looking index and stayed gradeable. So a
    correct key was discarded and an unverified one was not.

    Stem signals belong to segmentation and are scored by `parse_confidence`. This looks only
    at answer provenance.
    """
    reasons: list[str] = []
    score = 1.0
    qtype = item.get("question_type") or "short_answer"
    choices = [c for c in (item.get("choices") or []) if str(c).strip()]
    correct_index = item.get("correct_index")

    if qtype == "single_choice":
        if len(choices) < 2:
            score -= 0.6
            reasons.append("multiple_choice_without_choices")
        if not isinstance(correct_index, int) or not 0 <= correct_index < len(choices):
            score -= 0.6
            reasons.append("no_valid_correct_index")
    else:
        reference = str(item.get("reference_answer") or "").strip()
        if not reference:
            score -= 0.6
            reasons.append("no_reference_answer")
        elif len(reference) > 400:
            # a paragraph is a passage the parser lifted, not an answer it isolated
            score -= 0.3
            reasons.append("reference_answer_looks_like_prose")
    if not item.get("has_key_source", True):
        # no answer key was supplied, so any answer came from the test paper itself
        score -= 0.2
        reasons.append("no_answer_key_supplied")
    return max(0.0, round(score, 3)), reasons


def _withhold_untrusted_answer(item: dict, spec: dict, qtype: str,
                               reasons: list[str]) -> dict:
    """Make an unestablished answer ungradeable, whatever the question type.

    This used to blank short answers only, leaving a low-confidence multiple-choice item with
    a plausible-looking index that scoring would happily use. Every type is now made
    ungradeable, and the parsed value is kept in `withheld_answer` rather than destroyed —
    an editor confirming the key needs to see what the parser proposed, and deleting it would
    make review harder than it needs to be.
    """
    withheld = dict(spec)
    withheld["withheld_reason"] = ", ".join(reasons) or "low_answer_confidence"
    if qtype == "single_choice":
        withheld["withheld_answer"] = spec.get("correct_index")
        withheld.pop("correct_index", None)
    else:
        withheld["withheld_answer"] = spec.get("answer")
        withheld["answer"] = ""
        withheld["accepted"] = []
    return withheld


def attach_source_figures(db: Session, exam_source: Source, snapshot: SourceSnapshot,
                          items: list[dict]) -> dict:
    """Recover the PDF's figures and attach each to the items printed on its page.

    Import has always read only `extract_text()`, so every diagram and specimen photo was
    discarded and the items depending on one were dropped. The bytes are still retained, so
    this re-reads them.

    It fails soft on purpose: a source with no retained bytes, an unreadable PDF, or a
    storage backend that is not configured must degrade to today's text-only behaviour rather
    than fail the whole import. What it must never do is attach a figure it is not sure about
    — that decision lives in `attach_figures_to_items`, which marks ambiguity instead of
    guessing.
    """
    stats = {"figures_found": 0, "attached": 0, "status": "no_bytes"}
    raw = _retained_bytes(db, exam_source, snapshot)
    if not raw:
        for item in items:
            item.setdefault("figures", [])
            item.setdefault("figure_match", "no_source_bytes")
        return stats
    try:
        report = extract_figures(raw)
    except Exception as exc:                       # a broken PDF is not a broken import
        stats["status"] = f"extraction_failed:{type(exc).__name__}"
        for item in items:
            item.setdefault("figures", [])
            item.setdefault("figure_match", "extraction_failed")
        return stats

    stats["figures_found"] = len(report.figures)
    stats["rejected"] = report.rejected
    for figure in report.figures:
        figure.storage_key = _store_figure(exam_source, snapshot, figure)
    stats.update(attach_figures_to_items(snapshot.extracted_text or "", items, report.figures))
    stats["status"] = "ok"
    stats["attached"] = stats.get("with_figures", 0)
    return stats


def _retained_bytes(db: Session, source: Source, snapshot: SourceSnapshot) -> bytes | None:
    """Fetch the PDF bytes this snapshot was extracted from, if they were kept.

    The first version looked only in `metadata_json["artifact_key"]`, which the *upload* path
    sets. The crawler retains bytes too, but records them as a `RawArtifact` row against the
    snapshot — so figure recovery reported "no retained bytes" for every crawled PDF in the
    catalog and silently did nothing. The authoritative record is checked first.
    """
    artifact = db.scalar(select(RawArtifact).where(
        RawArtifact.snapshot_id == snapshot.id).order_by(RawArtifact.id.desc()))
    keys = [artifact.storage_key if artifact else None,
            (snapshot.metadata_json or {}).get("artifact_key"),
            (source.metadata_json or {}).get("artifact_key")]
    for key in [k for k in keys if k]:
        try:
            from app.services import media_storage
            return media_storage.download_media(key)
        except Exception:
            continue
    return None


def _store_figure(source: Source, snapshot: SourceSnapshot, figure) -> str:
    key = f"figures/source-{source.id}/snapshot-{snapshot.id}/p{figure.page}-{figure.sha256[:12]}"
    try:
        from app.services import media_storage
        stored = media_storage.upload_media(key, figure.content, figure.content_type)
        return getattr(stored, "key", key)
    except Exception:
        # the descriptor still records page, size and hash, so an operator can find it later
        return ""


def build_questions(
    db: Session, event: Event, exam_source: Source, key_source: Source | None,
    items: list[dict], include_image_dependent: bool = False,
) -> list[Question]:
    questions: list[Question] = []
    for item in items:
        image_dependent = bool(item.get("image_dependent"))
        figures = item.get("figures") or []
        # An image-dependent item used to be dropped unconditionally, because the figure it
        # referred to was never extracted. If a figure from its own page is now attached and
        # the attachment is unambiguous, the item is answerable and belongs in the import.
        # An `ambiguous` attachment does not qualify: several questions and several figures
        # shared that page, and guessing which pairs with which would make an unanswerable
        # item look answerable — the exact failure this is meant to end.
        resolved = bool(figures) and item.get("figure_match") in RESOLVING_MATCHES
        # Only a verified pairing reaches `Question.assets`, which is what the exam snapshot
        # serves. Ambiguous candidates used to be copied there for *every* item on the page,
        # including plain text items the model never flagged as image-dependent — so a
        # question could be served a figure that belongs to its neighbour. Candidates are kept
        # in provenance for review instead, where they inform an editor without being shown.
        served_assets = list(figures) if resolved else []
        candidate_figures = [] if resolved else list(figures)
        if image_dependent and not resolved and not include_image_dependent:
            continue
        stem = str(item.get("stem") or "").strip()
        if not stem:
            continue
        qtype, choices, answer_spec = _answer_spec(item)
        confidence, confidence_reasons = parse_confidence(item)
        item.setdefault("has_key_source", key_source is not None)
        ans_confidence, ans_reasons = answer_confidence(item)
        # segmentation quality and answer quality are judged separately: an unlocated stem is
        # a reason to review the item, not a reason to throw away a valid official key
        trustworthy = is_trustworthy(ans_confidence, ans_reasons)
        if not trustworthy:
            answer_spec = _withhold_untrusted_answer(
                item, answer_spec, qtype, ans_reasons)
        question = Question(
            event_id=event.id,
            source_id=exam_source.id,
            status=QuestionStatus.DRAFT.value,
            question_type=qtype,
            stem=stem,
            choices=choices,
            assets=served_assets,
            answer_spec=answer_spec,
            explanation=str(item.get("acceptance_notes") or item.get("reference_answer") or ""),
            citations=[{"source_id": exam_source.id}],
            difficulty=0.5,
            cognitive_level="application",
            estimated_seconds=int(_safe_points(item.get("points"))) * 60,
            generation_provenance={
                "import_kind": "past_test",
                "prompt_version": PROMPT_VERSION,
                "exam_source_id": exam_source.id,
                "key_source_id": key_source.id if key_source else None,
                "section": item.get("section"),
                "label": item.get("label"),
                "image_dependent": image_dependent,
                "figure_match": item.get("figure_match", "none"),
                "source_page": item.get("page"),
                "figure_resolved": resolved,
                "figure_candidates": candidate_figures,
                "parse_confidence": confidence,
                "parse_confidence_reasons": confidence_reasons,
                "answer_confidence": ans_confidence,
                "answer_confidence_reasons": ans_reasons,
                "answer_withheld": not trustworthy,
                "unverified_auto_import": True,
            },
        )
        db.add(question)
        db.flush()
        questions.append(question)
    return questions


def _snapshot(question: Question) -> dict:
    return {
        "stem": question.stem,
        "choices": question.choices,
        "assets": question.assets,
        "question_type": question.question_type,
        "answer_spec": question.answer_spec,
        "explanation": question.explanation,
        "citations": question.citations,
        "concept_id": question.concept_id,
        "estimated_seconds": question.estimated_seconds,
    }


def build_exam(
    db: Session, event: Event, exam_source: Source, questions: list[Question],
    feedback_mode: str, title: str | None = None, duration_minutes: int = 50,
) -> Exam:
    if feedback_mode not in FEEDBACK_MODES:
        raise ValueError(f"feedback_mode must be one of {sorted(FEEDBACK_MODES)}")
    exam = Exam(
        event_id=event.id,
        title=title or f"{event.name} — Past Test: {exam_source.title}",
        duration_minutes=duration_minutes,
        question_ids=[q.id for q in questions],
        published=True,
        # Imported items are unreviewed by definition; label the exposure honestly.
        disposition=DISPOSITION_UNREVIEWED_PRACTICE,
        release_class="past_test",
        blueprint={
            "import_kind": "past_test",
            "feedback_mode": feedback_mode,
            "exam_source_id": exam_source.id,
            "question_count": len(questions),
            "snapshot_schema": 1,
        },
    )
    db.add(exam)
    db.flush()
    for position, question in enumerate(questions):
        db.add(ExamItem(
            exam_id=exam.id, question_id=question.id, question_version=question.version,
            position=position, snapshot=_snapshot(question),
        ))
    return exam


def import_past_test(
    db: Session, event: Event, exam_source: Source, key_source: Source | None = None,
    feedback_mode: str = "after_submit", include_image_dependent: bool = False,
    build: bool = True, commit: bool = True, min_questions: int = 1,
) -> dict:
    """Parse a past-test Source into Questions and (optionally) assemble a mock Exam."""
    exam_snapshot = _latest_snapshot(db, exam_source.id)
    if not exam_snapshot or not (exam_snapshot.extracted_text or "").strip():
        raise ValueError(f"Source {exam_source.id} has no retained text to parse")
    # the caller may not know a key exists; look for the obvious sibling before giving up on
    # answers entirely, which is how 1,226 items were imported with an empty key
    key_source = key_source or find_key_source(db, exam_source, event)
    key_snapshot = _latest_snapshot(db, key_source.id) if key_source else None
    key_text = (key_snapshot.extracted_text if key_snapshot else "") or ""

    items = parse_items(exam_snapshot.extracted_text, key_text, event)
    image_dependent = sum(1 for i in items if i.get("image_dependent"))
    figure_stats = attach_source_figures(db, exam_source, exam_snapshot, items)

    questions = build_questions(
        db, event, exam_source, key_source, items, include_image_dependent,
    )
    if len(questions) < min_questions:
        db.rollback()
        return {
            "parsed_items": len(items), "image_dependent_items": image_dependent,
            "questions_created": 0, "exam_id": None, "skipped": True, "items": items,
            "figures": figure_stats,
        }
    exam = build_exam(db, event, exam_source, questions, feedback_mode) if (build and questions) else None
    if commit:
        db.commit()
        if exam:
            db.refresh(exam)
    else:
        db.rollback()
    return {
        "parsed_items": len(items),
        "image_dependent_items": image_dependent,
        "low_confidence_items": sum(
            1 for i in items if not is_trustworthy(*parse_confidence(i))),
        "answers_withheld": sum(
            1 for i in items if not is_trustworthy(*answer_confidence(i))),
        "image_dependent_recovered": sum(
            1 for i in items
            if i.get("image_dependent") and i.get("figure_match") == "unique"),
        "questions_created": len(questions),
        "exam_id": exam.id if exam else None,
        "items": items,
        "figures": figure_stats,
    }
