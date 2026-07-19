from app.models.entities import Question
from app.services.scoring import score_response


def test_single_choice_scoring():
    q = Question(
        event_id=1,
        stem="x",
        choices=["a", "b"],
        answer_spec={"correct_index": 1, "points": 2},
        question_type="single_choice",
    )
    assert score_response(q, {"selected_index": 1})[:2] == (True, 2.0)
    assert score_response(q, {"selected_index": 0})[:2] == (False, 0.0)
