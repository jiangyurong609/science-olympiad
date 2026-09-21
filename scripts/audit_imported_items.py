"""Find imported past-test questions a student cannot answer, or that answer themselves.

Transcribing a paper test into single questions loses whatever the question pointed AT. A
student walking the live site found all of these in one session:

* a MATCHING question whose right-hand column was dropped — "Match the term 'Wavelength'
  with its definition." and no definitions anywhere. Unanswerable, and typed short_answer so
  it auto-scores zero.
* the same failure the other way round — "Match the term 'Nephology' to its definition: the
  study of clouds and cloud formation." The definition is in the stem, so the item answers
  itself. All 11 questions of one Meteorology paper were like this.
* "...with the corresponding problem from the answer choices" on an item with no choices.
* paper furniture imported as a gradeable item — "Write your salinity estimate on the answer
  sheet. This estimate will be used as Tiebreaker 1."

    DATABASE_URL=... python -m scripts.audit_imported_items
    DATABASE_URL=... python -m scripts.audit_imported_items --apply   # withdraw from exams
"""
from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import AuditLog, Exam, ExamItem, Question

IMPORTED = {"imported_practice", "unreviewed_practice"}

FURNITURE = re.compile(r"\b(on the answer sheet|tie ?-?breaker|write your (name|team)|"
                       r"do not write|this page intentionally|turn the page|"
                       r"station \d+ ends|stop here)\b", re.I)
# "Match the term X to its definition: <definition>" — names the term AND gives the definition.
TERM_THEN_DEFINITION = re.compile(
    r"\bmatch\b.{0,60}\b(term|word|name)\b.{0,80}\b(to|with)\b.{0,20}\b(definition|"
    r"description|meaning)\b\s*[:\-\u2013\u2014]\s*\S", re.I)
# A key that is only a letter, or "answer choice C", points at a column the student cannot see.
LETTER_KEY = re.compile(r"^\s*(?:(?:matching\s+)?(?:answer\s+)?choice\s+)?[A-Za-z]\s*\.?\s*$", re.I)


def _accepted(question: Question) -> list[str]:
    spec = question.answer_spec
    if isinstance(spec, str):
        return [spec]
    spec = spec or {}
    values = list(spec.get("accepted") or []) + [spec.get("answer")]
    return [str(v).strip() for v in values if v is not None and str(v).strip()]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def classify(question: Question) -> str | None:
    """Judge an item by whether a student who KNOWS the answer can be graded correct.

    The first version judged the stem's wording and was wrong in both directions. It flagged
    "Match the definition: A disease that occurs infrequently and irregularly" as broken
    because the word bank was lost — but the key is "Sporadic", so a student who types
    "sporadic" is graded correct, and it is a perfectly good recall question. And it flagged
    items that HAVE fifteen choices, which are ordinary matching items. What decides it is the
    answer key.
    """
    stem = (question.stem or "").strip()
    choices = [c for c in (question.choices or []) if str(c).strip()]
    if FURNITURE.search(stem):
        return "paper_furniture"
    if choices:
        return None                     # a real choice list: the student can answer it
    accepted = _accepted(question)
    if not accepted:
        return "no_answer_key"
    # Every accepted answer is a bare letter: "Match the disorder Myopia to the correct
    # description" keyed "A". The letter names a row in a column that was lost.
    if all(LETTER_KEY.match(a) for a in accepted):
        return "letter_key_to_lost_column"
    # The answer is sitting in the question: "Match the term 'Nephology' to its definition:
    # the study of clouds" keyed "Nephology". The student copies it from the stem.
    #
    # Restricted to that one shape on purpose. An answer appearing in its own stem is normal
    # for an either/or item ("Is radiance a scalar or vector quantity?" -> vector), a
    # true/false item, or a word-bank item, and a sample of the unrestricted rule was almost
    # entirely those. What is broken is a stem that NAMES the term and then SUPPLIES its
    # definition, keyed to the term it already named.
    if TERM_THEN_DEFINITION.search(stem):
        words = [a for a in accepted if not LETTER_KEY.match(a)]
        if words and any(len(_norm(a)) >= 3 and _norm(a) in _norm(stem) for a in words):
            return "answer_in_stem"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--min-items", type=int, default=5,
                        help="hold an exam that falls below this many answerable items")
    args = parser.parse_args()
    kinds: Counter[str] = Counter()
    per_exam: dict[int, list[tuple[int, str]]] = defaultdict(list)
    with SessionLocal() as db:
        exams = db.scalars(select(Exam).where(Exam.release_class.in_(IMPORTED),
                                              Exam.published.is_(True))).all()
        for exam in exams:
            ids = list(exam.question_ids or [])
            if not ids:
                continue
            questions = {q.id: q for q in db.scalars(
                select(Question).where(Question.id.in_(ids))).all()}
            for qid in ids:
                question = questions.get(qid)
                kind = classify(question) if question else "missing_question"
                if kind:
                    kinds[kind] += 1
                    per_exam[exam.id].append((qid, kind))

        print(f"{sum(kinds.values())} defective item(s) in {len(per_exam)} exam(s)")
        for kind, n in kinds.most_common():
            print(f"  {n:4d}  {kind}")
        held = 0
        for exam_id, bad in sorted(per_exam.items(), key=lambda kv: -len(kv[1])):
            exam = db.get(Exam, exam_id)
            ids = list(exam.question_ids or [])
            bad_ids = {qid for qid, _ in bad}
            keep = [qid for qid in ids if qid not in bad_ids]
            verdict = "HOLD" if len(keep) < args.min_items else "trim"
            held += verdict == "HOLD"
            print(f"  [{verdict}] exam {exam_id}: {len(bad)}/{len(ids)} defective "
                  f"-> {len(keep)} left | {exam.title[:70]}")
            if not args.apply:
                continue
            db.query(ExamItem).filter(ExamItem.exam_id == exam.id,
                                      ExamItem.question_id.in_(bad_ids)).delete(
                synchronize_session=False)
            db.flush()
            remaining = db.scalars(select(ExamItem).where(ExamItem.exam_id == exam.id)
                                   .order_by(ExamItem.position)).all()
            for offset, item in enumerate(remaining):
                item.position = 100_000 + offset
            db.flush()
            for position, item in enumerate(remaining):
                item.position = position
            exam.question_ids = keep
            if verdict == "HOLD":
                exam.published = False
            db.add(AuditLog(
                actor_user_id=None, action="exam.defective_imported_items_withdrawn",
                entity_type="exam", entity_id=str(exam.id),
                details={"withdrawn": [{"question_id": q, "kind": k} for q, k in bad],
                         "remaining_items": len(keep), "unpublished": verdict == "HOLD"}))
        if args.apply:
            db.commit()
        print(f"\n{'applied' if args.apply else 'dry run'}: {held} exam(s) would fall below "
              f"{args.min_items} answerable items and be unpublished")


if __name__ == "__main__":
    main()
