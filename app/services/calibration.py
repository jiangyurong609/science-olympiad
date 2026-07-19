from __future__ import annotations

import math
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Attempt, ExamItem, Question, Response, User


CALIBRATION_THRESHOLDS = {
    "minimum_unique_students": 30,
    "minimum_facility": 0.15,
    "maximum_facility": 0.90,
    "minimum_discrimination": 0.15,
    "maximum_omission_rate": 0.05,
    "minimum_division_representation": 0.80,
}


def _correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    return numerator / denominator if denominator else 0.0


def calculate_item_calibration(db: Session, question: Question) -> dict:
    items = db.scalars(select(ExamItem).where(
        ExamItem.question_id == question.id,
        ExamItem.question_version == question.version,
    )).all()
    exam_ids = {item.exam_id for item in items}
    attempts = db.scalars(select(Attempt).where(
        Attempt.exam_id.in_(exam_ids), Attempt.submitted_at.is_not(None), Attempt.max_score > 0,
    ).order_by(Attempt.submitted_at, Attempt.id)).all() if exam_ids else []
    # A student's first scored exposure is used to avoid practice repetition inflating the sample.
    attempts_by_user = {}
    for attempt in attempts:
        attempts_by_user.setdefault(attempt.user_id, attempt)
    selected_attempts = list(attempts_by_user.values())
    attempt_ids = [attempt.id for attempt in selected_attempts]
    responses = db.scalars(select(Response).where(
        Response.attempt_id.in_(attempt_ids), Response.question_id == question.id,
        Response.is_correct.is_not(None),
    )).all() if attempt_ids else []
    response_by_attempt = {response.attempt_id: response for response in responses}
    item_scores = []
    corrected_totals = []
    omissions = 0
    times = []
    correct_confidence = []
    incorrect_confidence = []
    option_counts: Counter[str] = Counter()
    divisions: Counter[str] = Counter()
    item_max_points = float(question.answer_spec.get("points", 1))
    for attempt in selected_attempts:
        user = db.get(User, attempt.user_id)
        divisions[(user.division if user and user.division else "unknown")] += 1
        response = response_by_attempt.get(attempt.id)
        if not response or not response.answer:
            omissions += 1
            score = 0.0
            points = 0.0
        else:
            score = 1.0 if response.is_correct else 0.0
            points = float(response.points_awarded or 0.0)
            if "selected_index" in response.answer:
                option_counts[str(response.answer["selected_index"])] += 1
            if response.time_spent_seconds > 0:
                times.append(response.time_spent_seconds)
            if response.confidence is not None:
                (correct_confidence if response.is_correct else incorrect_confidence).append(response.confidence)
        item_scores.append(score)
        remaining_max = max(0.0, float(attempt.max_score or 0.0) - item_max_points)
        corrected_totals.append(
            max(0.0, float(attempt.score or 0.0) - points) / remaining_max if remaining_max else 0.0
        )
    sample_size = len(selected_attempts)
    facility = sum(item_scores) / sample_size if sample_size else 0.0
    discrimination = _correlation(item_scores, corrected_totals)
    omission_rate = omissions / sample_size if sample_size else 1.0
    represented = sum(count for division, count in divisions.items() if division in {"B", "C"})
    division_representation = represented / sample_size if sample_size else 0.0
    metrics = {
        "sample_size": sample_size,
        "facility": round(facility, 4),
        "corrected_item_total_discrimination": round(discrimination, 4),
        "omission_rate": round(omission_rate, 4),
        "median_response_seconds": sorted(times)[len(times) // 2] if times else None,
        "mean_confidence_correct": round(sum(correct_confidence) / len(correct_confidence), 2) if correct_confidence else None,
        "mean_confidence_incorrect": round(sum(incorrect_confidence) / len(incorrect_confidence), 2) if incorrect_confidence else None,
        "option_counts": dict(sorted(option_counts.items())),
        "division_counts": dict(sorted(divisions.items())),
        "division_representation": round(division_representation, 4),
        "unique_student_policy": "first_scored_exposure_per_user",
    }
    failures = []
    t = CALIBRATION_THRESHOLDS
    if sample_size < t["minimum_unique_students"]:
        failures.append("insufficient_unique_students")
    if not t["minimum_facility"] <= facility <= t["maximum_facility"]:
        failures.append("facility_out_of_range")
    if discrimination < t["minimum_discrimination"]:
        failures.append("low_discrimination")
    if omission_rate > t["maximum_omission_rate"]:
        failures.append("high_omission_rate")
    if division_representation < t["minimum_division_representation"]:
        failures.append("insufficient_division_metadata")
    return {
        "metrics": metrics,
        "thresholds": CALIBRATION_THRESHOLDS,
        "passed": not failures,
        "failures": failures,
        "calculator_version": "1.0",
    }
