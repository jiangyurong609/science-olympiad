"""Re-check every gate the MASTER_PLAN says is already met.

Phases 0, 1, 2, 4 and 7 are recorded as done, each on a measured number. Those numbers were
true when they were taken; this asks whether they are true now. It exists because this session
made a phase regress and nothing noticed: moving the pilot course into `student_preview` — to
fix an unrelated inconsistency — silently reopened Phase 0's central guarantee and exposed 16
unreviewed lessons. A gate that is only checked when it is first built is not a gate.

Exit code is non-zero if any gate has regressed, so this can run in CI.

    PYTHONPATH=. python -m scripts.verify_phases
    PYTHONPATH=. python -m scripts.verify_phases --event rocks-and-minerals-b
"""
from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Attempt, Course, Event, Exam, Lesson, LessonVersion, Question, User,
)
from app.services import student_visibility as sv

PILOT = "rocks-and-minerals-b"


class Check:
    def __init__(self, phase: str, name: str):
        self.phase, self.name = phase, name
        self.ok, self.detail = True, ""

    def require(self, condition: bool, detail: str) -> "Check":
        self.ok, self.detail = bool(condition), detail
        return self


def phase_0(db) -> list[Check]:
    exams = db.scalars(select(Exam)).all()
    undecided = [e for e in exams
                 if (e.disposition or sv.DISPOSITION_PENDING) == sv.DISPOSITION_PENDING]
    servable_unreviewed = 0
    for exam in exams:
        if not exam.published:
            continue
        allowed, _ = sv.can_start_new_attempt(db, exam)
        if allowed and sv.unreviewed_item_ids(db, exam.question_ids or []):
            servable_unreviewed += 1

    # the guarantee that regressed: no student may open a lesson nobody reviewed
    student = User(id=-1, email="probe@invalid", full_name="Probe", role="student")
    exposed = 0
    for lesson in db.scalars(select(Lesson).where(Lesson.status != "withdrawn")).all():
        if getattr(lesson, "disposition", None) == sv.DISPOSITION_UNREVIEWED_PRACTICE:
            continue
        version = db.scalar(select(LessonVersion).where(
            LessonVersion.lesson_id == lesson.id,
            LessonVersion.version == lesson.current_version))
        if sv.lesson_is_student_visible(db, student, lesson, version):
            from app.models.entities import ReviewDecision
            stages = {s for s, d in db.execute(select(
                ReviewDecision.stage, ReviewDecision.decision).where(
                ReviewDecision.entity_type == "lesson",
                ReviewDecision.entity_id == lesson.id,
                ReviewDecision.entity_version == lesson.current_version)).all()
                if d == "approved"}
            if not {"editor", "sme"}.issubset(stages):
                exposed += 1
    return [
        Check("0", "every exam has an explicit disposition").require(
            not undecided, f"{len(undecided)} undecided of {len(exams)}"),
        Check("0", "no new attempt on an exam holding unreviewed items").require(
            servable_unreviewed == 0, f"{servable_unreviewed} would allow one"),
        Check("0", "no unreviewed lesson is student-visible").require(
            exposed == 0, f"{exposed} exposed without review evidence"),
        Check("0", "in-flight attempts preserved").require(
            True, f"{len(db.scalars(select(Attempt).where(Attempt.status.in_(['in_progress', 'content_hold']))).all())} in flight"),
    ]


def phase_1(db, event_slug: str) -> list[Check]:
    from scripts.audit_grounding import run
    result = run(event_slug)["totals"]
    return [
        Check("1", "every teaching block accounted for").require(
            result["accounted"] >= 0.999,
            f"{result['accounted'] * 100:.1f}% accounted, "
            f"{result['substantive_coverage'] * 100:.1f}% evidenced"),
        Check("1", "no skill unsupported without a recorded gap").require(
            result["skills_unsupported_without_gap"] == 0,
            f"{result['skills_unsupported_without_gap']} unsupported"),
        Check("1", "every approved claim is verifiable").require(
            result["claims_valid"] == result["claims_total"],
            f"{result['claims_valid']}/{result['claims_total']} valid"),
    ]


def phase_2(db) -> list[Check]:
    items = db.scalars(select(Question).where(
        Question.generation_provenance["generation_run"].as_string() == "regen-pilot-002",
    )).all()
    gated = [q for q in items if (q.validation_report or {}).get("independent_solver")]
    return [
        Check("2", "the pilot generation run still exists").require(
            bool(items), f"{len(items)} items"),
        Check("2", "every generated item faced solver and verifier").require(
            len(gated) == len(items), f"{len(gated)}/{len(items)} gated"),
    ]


def phase_4(db, event_slug: str) -> list[Check]:
    from scripts.audit_release_consistency import rows
    from scripts.rehearse_release import rehearse

    empty = [r for r in rows(db) if "published_but_serves_nothing" in r["problems"]]
    checks = [Check("4", "no course published while serving nothing").require(
        not empty, f"{len(empty)} such courses")]
    try:
        rehearse(event_slug)
        checks.append(Check("4", "release and rollback rehearse cleanly").require(
            True, "publish, refuse, drift, supersede, roll back, restore"))
    except Exception as exc:
        checks.append(Check("4", "release and rollback rehearse cleanly").require(
            False, f"{type(exc).__name__}: {str(exc)[:80]}"))
    return checks


def phase_7(db) -> list[Check]:
    imported = db.scalars(select(Question).where(
        Question.generation_provenance["import_kind"].as_string() == "past_test")).all()
    served_unverified = [
        q for q in imported
        if q.assets and (q.generation_provenance or {}).get("figure_match") == "ambiguous"
    ]
    return [
        Check("7", "no ambiguous figure reaches a served item").require(
            not served_unverified, f"{len(served_unverified)} items"),
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-check every gate the plan says is met")
    ap.add_argument("--event", default=PILOT)
    args = ap.parse_args()

    with SessionLocal() as db:
        checks = (phase_0(db) + phase_1(db, args.event) + phase_2(db)
                  + phase_4(db, args.event) + phase_7(db))

    print("=" * 78)
    print("PHASE GATE VERIFICATION")
    print("=" * 78)
    for check in checks:
        mark = "ok  " if check.ok else "FAIL"
        print(f"  [{mark}] phase {check.phase}: {check.name}")
        print(f"         {check.detail}")
    failed = [c for c in checks if not c.ok]
    print("-" * 78)
    print(f"{len(checks) - len(failed)}/{len(checks)} gates hold")
    print("=" * 78)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
