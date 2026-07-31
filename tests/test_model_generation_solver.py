"""Phase 1 — independent-solver stage in the model generation path."""
from __future__ import annotations

import pytest

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, Event, QuestionStatus, ScientificClaim, Source, SourceSnapshot, User,
)
import app.services.model_generation as mg


# ---- pure verdict logic ------------------------------------------------------

def test_solver_verdict_agrees():
    ok, reason = mg._solver_verdict({"chosen_index": 2, "ambiguous": False, "insufficient": False}, 2)
    assert ok and reason == "solver_agrees"


@pytest.mark.parametrize("solver,expected", [
    ({"chosen_index": 1}, "solver_disagrees_with_key"),
    ({"chosen_index": 0, "ambiguous": True}, "solver_reports_ambiguous"),
    ({"chosen_index": 0, "insufficient": True}, "solver_insufficient_information"),
    ({"chosen_index": "x"}, "solver_disagrees_with_key"),
])
def test_solver_verdict_rejects(solver, expected):
    ok, reason = mg._solver_verdict(solver, 0)
    assert not ok and reason == expected


# ---- integration with a mocked provider --------------------------------------

def _seed_grounding(db):
    actor = User(email="ed@example.com", full_name="Editor", password_hash="x", role="editor")
    event = Event(slug="astronomy-c", name="Astronomy", division="C", season=2026)
    db.add_all([actor, event])
    db.flush()
    concept = Concept(event_id=event.id, name="Planets")
    src = Source(url="https://sci.gov/planets", title="Planets", rights_status="public_domain", approved=True)
    db.add_all([concept, src])
    db.flush()
    snap = SourceSnapshot(source_id=src.id, final_url=src.url, content_hash="abc123")
    db.add(snap)
    db.flush()
    claim = ScientificClaim(source_id=src.id, source_snapshot_id=snap.id, concept_id=concept.id,
                            claim_text="Saturn has the most confirmed moons.", approved=True)
    db.add(claim)
    db.commit()
    return actor, event, concept, claim


class _MockProvider:
    """Dispatches writer / solver / verifier by the system prompt; configurable solver answer."""
    def __init__(self, solver_index=0, ambiguous=False, insufficient=False):
        self.model = "mock-model"
        self._solver = {"chosen_index": solver_index, "confidence": 0.9,
                        "ambiguous": ambiguous, "insufficient": insufficient}

    configured = True

    def generate_json(self, system, user):
        from app.services.model_provider import ModelResult
        if "INDEPENDENT solver" in system:
            payload = self._solver
        elif "verifier" in system:
            payload = {"passed": True, "errors": [], "warnings": []}
        else:  # item writer
            payload = {"items": [{
                "stem": "Which planet has the most confirmed moons in our solar system?",
                "choices": ["Saturn", "Earth", "Mars", "Venus"],
                "correct_index": 0,
                "explanation": "Saturn currently has the most confirmed moons.",
                "claim_ids": [self._claim_id],
                "estimated_seconds": 60,
                "distractor_error_types": {},
            }]}
        return ModelResult(payload=payload, provider="mock", model=self.model)


def _run_with(monkeypatch, provider):
    with SessionLocal() as db:
        actor, event, concept, claim = _seed_grounding(db)
        provider._claim_id = claim.id
        monkeypatch.setattr(mg, "OpenAICompatibleProvider", lambda: provider)
        return mg.generate_model_questions(
            db, actor, event, concept, count=1, difficulty=0.5, cognitive_level="application"
        )


def test_solver_agreement_yields_machine_validated(monkeypatch):
    questions = _run_with(monkeypatch, _MockProvider(solver_index=0))
    assert len(questions) == 1
    q = questions[0]
    assert q.status == QuestionStatus.MACHINE_VALIDATED.value
    assert q.validation_report["independent_solver"]["passed"] is True


def test_solver_disagreement_keeps_draft(monkeypatch):
    questions = _run_with(monkeypatch, _MockProvider(solver_index=1))  # solver picks wrong choice
    q = questions[0]
    assert q.status == QuestionStatus.DRAFT.value
    assert q.validation_report["independent_solver"]["verdict"] == "solver_disagrees_with_key"
    assert "solver_disagrees_with_key" in q.validation_report["errors"]


def test_solver_ambiguous_keeps_draft(monkeypatch):
    questions = _run_with(monkeypatch, _MockProvider(solver_index=0, ambiguous=True))
    assert questions[0].status == QuestionStatus.DRAFT.value
