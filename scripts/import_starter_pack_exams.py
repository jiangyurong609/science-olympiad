"""Import the sample papers from the 2027 Rocks & Minerals Starter Pack as practice exams.

The pack (a 171-slide deck supplied by the program) ends in five sample papers with answer keys:
Division B Regional, State and National, and Division C Regional and State. An agent
transcribed them into `data/review/rm-starter-pack-2027/exams.json`, checked every key against
the 2027 rules and the official list, and cropped each figure. See `pack_audit.md` there.

What is served, and why:
  * the three Division B papers, as written, minus the items the audit faulted;
  * one fourth paper made of the Division C items that are inside Division B scope (thin
    sections, facies diagrams and the rest of the Division C-only material stay out).

Faulted items are handled explicitly, never silently "fixed" into the key:
  * B-National Q28 is dropped: it keys olivine as crystallizing EARLIER than Ca-rich
    plagioclase, but the two begin together at the top of their two branches.
  * B-State Q21 is dropped: it keys "laccolith", and Division B igneous formations are limited
    to batholith, lava flow and pyroclastic deposits (rule 3.i.iv.3).
  * B-National Q14 is reworded: its stem endorsed tasting halite "in a safe classroom setting",
    which rule 3.g forbids. Taste may still be asked about as a described property, so the stem
    asks for halite's distinctive property and the key is unchanged.

These are neither transcribed tournament papers nor machine-written items, so they carry their
own release class, `study_pack_practice`. Disposition is `imported_practice`: a paper with its
own answer key, startable, labelled as not expert-reviewed.

Multi-select items have no native type here; each becomes an all-or-nothing short answer with
the options listed in the stem. Short answers keep the pack's sample answer as the reference,
with a rubric that says so.

    DATABASE_URL=... python -m scripts.import_starter_pack_exams
    DATABASE_URL=... python -m scripts.import_starter_pack_exams --apply
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, Exam, ExamItem, Question

PACK_DIR = Path("data/review/rm-starter-pack-2027")
# The pack's own photographs carry no stated licence, so none of them is served. Each figure
# is replaced by an openly licensed Wikimedia Commons photo or a diagram drawn for this
# platform, chosen to show what its question needs; `figure_replacements.json` records the
# file, author, licence and source page for every one.
MEDIA_DIR = Path("app/static/media/rocks-and-minerals-open")
MEDIA_URL = "/static/media/rocks-and-minerals-open"
REPLACEMENTS = json.loads((PACK_DIR / "figure_replacements.json").read_text())
EVENT_SLUG = "rocks-and-minerals-b-2027"
RELEASE_CLASS = "study_pack_practice"
IMPORT_KIND = "study_pack"
PACK_NAME = "Rocks & Minerals 2027 Starter Pack"

DROP = {("b-national", 28), ("b-state", 21)}
REWORD = {("b-national", 14): "Halite is known for which distinctive property?"}
LETTERS = "ABCDEFGHIJ"


def _letters(answer) -> list[str]:
    if isinstance(answer, list):
        return [str(a).strip().upper() for a in answer]
    return [a.strip().upper() for a in str(answer).replace(" and ", ",").split(",") if a.strip()]


def build_question(paper_id: str, q: dict) -> dict | None:
    """The Question fields for one pack item, or None when it must not be served."""
    key = (paper_id, q["number"])
    if key in DROP:
        return None
    stem = REWORD.get(key, q["stem"])
    points = float(q.get("points") or 1)
    assets = []
    if q.get("figure"):
        replacement = REPLACEMENTS[Path(q["figure"]).stem]
        assets = [{"url": f"{MEDIA_URL}/{replacement['file']}",
                   "alt": f"Figure for question {q['number']}",
                   "attribution": replacement["attribution"],
                   "license": replacement["license"],
                   "source_url": replacement["source_url"]}]
    if q["type"] == "multiple_choice":
        letter = str(q["answer"]).strip().upper()
        index = LETTERS.index(letter)
        if index >= len(q["choices"]):
            raise ValueError(f"{key}: key {letter} is past the last choice")
        return {"question_type": "single_choice", "stem": stem, "choices": q["choices"],
                "answer_spec": {"correct_index": index, "points": points,
                                "distractor_error_types": {}},
                "explanation": q.get("answer_text") or q["choices"][index], "assets": assets}
    if q["type"] == "multi_select":
        letters = _letters(q["answer"])
        if not letters or any(LETTERS.index(l) >= len(q["choices"]) for l in letters):
            raise ValueError(f"{key}: multi-select key {letters} does not fit its choices")
        options = "\n".join(f"{LETTERS[i]}. {c}" for i, c in enumerate(q["choices"]))
        joined = ", ".join(letters)
        return {"question_type": "short_answer",
                "stem": f"{stem}\n\n{options}\n\nAnswer with the letter of every correct option.",
                "choices": [],
                "answer_spec": {
                    "answer": joined,
                    "accepted": [",".join(letters), "".join(letters), " ".join(letters)],
                    "rubric": (f"All or nothing: credit only if the student gives exactly the "
                               f"letters {joined}, no more and no fewer, in any order or format."),
                    "points": points},
                "explanation": q.get("key_text") or f"Correct: {joined}", "assets": assets}
    sample = q.get("sample_answer") or (q.get("answer") if isinstance(q.get("answer"), str) else None)
    if not sample:
        raise ValueError(f"{key}: short answer with no sample answer")
    return {"question_type": "short_answer", "stem": stem, "choices": [],
            "answer_spec": {
                "answer": sample, "accepted": [],
                "rubric": (f"Worth {points:g} points. The reference is the study pack's sample "
                           "answer, not a point-by-point key: give full credit when the response "
                           "covers everything the question asks with correct science, partial "
                           "credit in proportion to the parts answered correctly, and accept "
                           "other correct examples from the 2027 Rocks and Minerals List."),
                "points": points},
            "explanation": sample, "assets": assets}


def papers(exams: list[dict]) -> list[dict]:
    """The four papers to serve: three Division B papers, and the in-scope Division C items."""
    out = []
    for paper in exams:
        if paper["division"] == "B":
            items = [q for q in paper["questions"]
                     if q["scope"] == "div_b" and (q["verified"] or (paper["id"], q["number"]) in REWORD)]
            out.append({"id": paper["id"], "title": f"Rocks and Minerals — {paper['level']} Sample "
                        f"Paper ({PACK_NAME})", "duration": paper["duration_minutes"],
                        "items": [(paper["id"], q) for q in items]})
    c_items = [(p["id"], q) for p in exams if p["division"] == "C"
               for q in p["questions"] if q["scope"] == "div_b" and q["verified"]]
    out.append({"id": "c-papers-b-scope", "title": f"Rocks and Minerals — Mixed-Level Sample "
                f"Paper ({PACK_NAME}, Division B topics from the Division C papers)",
                "duration": 50, "items": c_items})
    return out


def run(apply: bool) -> dict:
    exams = json.loads((PACK_DIR / "exams.json").read_text())
    plan = papers(exams)
    report = {"papers": []}
    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == EVENT_SLUG))
        if event is None:
            raise SystemExit(f"no event {EVENT_SLUG}")
        for paper in plan:
            built = [(pid, q, build_question(pid, q)) for pid, q in paper["items"]]
            built = [b for b in built if b[2] is not None]
            existing = db.scalar(select(Exam).where(Exam.event_id == event.id,
                                                    Exam.title == paper["title"]))
            report["papers"].append({"title": paper["title"], "items": len(built),
                                     "figures": sum(1 for b in built if b[2]["assets"]),
                                     "already_imported": existing is not None})
            if not apply or existing is not None:
                continue
            questions = []
            for pid, source, fields in built:
                question = Question(
                    event_id=event.id, status="draft", difficulty=0.5,   # not human-accepted, like past-test imports
                    cognitive_level="application",
                    estimated_seconds=60 if fields["question_type"] == "single_choice" else 150,
                    citations=[], validation_report={},
                    generation_provenance={
                        "import_kind": IMPORT_KIND, "pack": PACK_NAME, "paper": pid,
                        "number": source["number"], "section": source.get("section"),
                        "pack_slides": source.get("pack_slides"),
                        "reworded": (pid, source["number"]) in REWORD,
                        "original_type": source["type"],
                    },
                    **fields,
                )
                db.add(question)
                questions.append(question)
            db.flush()
            exam = Exam(
                event_id=event.id, title=paper["title"], duration_minutes=paper["duration"],
                question_ids=[q.id for q in questions], published=True,
                disposition="imported_practice", release_class=RELEASE_CLASS,
                blueprint={"import_kind": IMPORT_KIND, "pack": PACK_NAME, "paper": paper["id"],
                           "feedback_mode": "after_submit", "question_count": len(questions),
                           "audit": str(PACK_DIR / "pack_audit.md"), "snapshot_schema": 1},
            )
            db.add(exam)
            db.flush()
            for position, question in enumerate(questions):
                db.add(ExamItem(
                    exam_id=exam.id, question_id=question.id,
                    question_version=question.version or 1, position=position,
                    snapshot={"stem": question.stem, "choices": question.choices,
                              "assets": question.assets,
                              "question_type": question.question_type,
                              "answer_spec": question.answer_spec,
                              "explanation": question.explanation, "citations": [],
                              "concept_id": None,
                              "estimated_seconds": question.estimated_seconds},
                ))
            db.flush()
            report["papers"][-1]["exam_id"] = exam.id
        if apply:
            db.commit()
    return report


def refresh_figures(apply: bool) -> dict:
    """Re-point already-imported questions, and the exam snapshots students are served, at the
    current figure for each item. Exam items serve their snapshot, not the Question row, so
    changing only the Question would leave every started paper showing the old image."""
    exams = {p["id"]: {q["number"]: q for q in p["questions"]}
             for p in json.loads((PACK_DIR / "exams.json").read_text())}
    stats = {"questions": 0, "snapshots": 0}
    with SessionLocal() as db:
        questions = [q for q in db.scalars(select(Question)).all()
                     if (q.generation_provenance or {}).get("import_kind") == IMPORT_KIND]
        for question in questions:
            prov = question.generation_provenance
            source = exams[prov["paper"]][prov["number"]]
            built = build_question(prov["paper"], source)
            if built is None or built["assets"] == (question.assets or []):
                continue
            stats["questions"] += 1
            if apply:
                question.assets = built["assets"]
            for item in db.scalars(select(ExamItem).where(ExamItem.question_id == question.id)):
                stats["snapshots"] += 1
                if apply:
                    item.snapshot = {**item.snapshot, "assets": built["assets"]}
        if apply:
            db.commit()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--refresh-figures", action="store_true",
                        help="re-point imported items at the current figure files")
    args = parser.parse_args()
    if args.refresh_figures:
        print(json.dumps(refresh_figures(args.apply), indent=2))
        return
    print(json.dumps(run(args.apply), indent=2))


if __name__ == "__main__":
    main()
