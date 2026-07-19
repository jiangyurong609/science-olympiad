"""Give every multiple-choice distractor a diagnosed misconception.

Generated MCQs shipped with an empty `distractor_error_types`, so the scorer
labels every wrong answer a generic "knowledge_or_reasoning" and the Error
Notebook can't tell a student WHICH mistake they made. This asks the model, for
each incorrect option, for a short error-type category and a one-sentence
misconception, and writes them into `answer_spec.distractor_error_types` and
`answer_spec.misconception_by_choice`.

Resumable: skips any question that already has `distractor_error_types`.
Batched + concurrent to keep the run affordable.

Usage:
  python -m scripts.map_distractor_misconceptions [--limit N] [--batch 10]
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Question
from app.services.model_provider import ModelProviderError, OpenAICompatibleProvider

_SYSTEM = (
    "You are a Science Olympiad assessment expert diagnosing why students pick "
    "wrong multiple-choice options. For each question, examine every INCORRECT "
    "option and name the specific misconception behind choosing it. Return STRICT "
    "JSON {\"items\":[{\"id\":int,\"distractors\":[{\"index\":int,\"error_type\":str,"
    "\"misconception\":str}]}]}. `error_type` is a short snake_case category (e.g. "
    "\"definition_confusion\", \"unit_or_scale_error\", \"process_reversed\", "
    "\"correlation_vs_causation\", \"overgeneralization\", \"common_name_mixup\"). "
    "`misconception` is ONE sentence naming the wrong belief and why it's wrong. "
    "Include ONLY incorrect indices. Output only JSON."
)


def _arg(flag, default):
    return type(default)(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default


def _map_batch(provider, batch: list[dict]) -> dict[int, dict]:
    # `batch` is plain dicts (extracted before threading) so worker threads never
    # touch the ORM session — accessing expired attributes across threads raises
    # "concurrent operations are not permitted".
    user = json.dumps({"questions": batch})
    payload = provider.generate_json(_SYSTEM, user).payload
    out: dict[int, dict] = {}
    for item in (payload.get("items", []) if isinstance(payload, dict) else []):
        qid = item.get("id")
        error_types, misconceptions = {}, {}
        for d in item.get("distractors", []):
            idx = d.get("index")
            if not isinstance(idx, int):
                continue
            if d.get("error_type"):
                error_types[str(idx)] = str(d["error_type"])[:60]
            if d.get("misconception"):
                misconceptions[str(idx)] = str(d["misconception"])[:400]
        if error_types:
            out[qid] = {"distractor_error_types": error_types,
                        "misconception_by_choice": misconceptions}
    return out


def main() -> None:
    limit = _arg("--limit", 0)
    batch_size = _arg("--batch", 10)
    provider = OpenAICompatibleProvider()
    if not provider.configured:
        raise ModelProviderError("Model provider not configured")

    with SessionLocal() as db:
        # Extract plain data up front; threads never touch the ORM afterward.
        pending = [{"id": q.id, "stem": q.stem, "choices": q.choices or [],
                    "correct_index": (q.answer_spec or {}).get("correct_index")}
                   for q in db.scalars(select(Question).where(
                       Question.question_type == "single_choice")).all()
                   if not (q.answer_spec or {}).get("distractor_error_types")
                   and isinstance((q.answer_spec or {}).get("correct_index"), int)
                   and (q.choices or [])]
        if limit:
            pending = pending[:limit]
        print(f"Mapping distractors for {len(pending)} MCQs (batch {batch_size})…")
        batches = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]

        def _safe(batch):
            try:
                return _map_batch(provider, batch)
            except Exception as exc:  # noqa: BLE001
                print(f"  batch failed: {str(exc)[:80]}")
                return {}

        done = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            for group_start in range(0, len(batches), 4):
                group = batches[group_start:group_start + 4]
                results = list(pool.map(_safe, group))
                for mapping in results:
                    for qid, fields in mapping.items():
                        q = db.get(Question, qid)
                        if not q:
                            continue
                        spec = dict(q.answer_spec or {})
                        spec["distractor_error_types"] = fields["distractor_error_types"]
                        spec["misconception_by_choice"] = fields["misconception_by_choice"]
                        q.answer_spec = spec
                        done += 1
                db.commit()
                print(f"  {done}/{len(pending)} mapped", flush=True)
    print(f"Done: mapped {done} MCQs.")


if __name__ == "__main__":
    main()
