import json
from pathlib import Path

from scripts.import_starter_pack_exams import PACK_DIR, build_question, papers

EXAMS = json.loads((Path(PACK_DIR) / "exams.json").read_text())


def item(paper, number):
    return next(q for p in EXAMS if p["id"] == paper for q in p["questions"] if q["number"] == number)


def test_faulted_items_are_dropped_not_rekeyed():
    assert build_question("b-national", item("b-national", 28)) is None
    assert build_question("b-state", item("b-state", 21)) is None


def test_taste_stem_is_reworded_but_key_is_kept():
    built = build_question("b-national", item("b-national", 14))
    assert "classroom" not in built["stem"]
    assert built["choices"][built["answer_spec"]["correct_index"]] == "Salty taste"


def test_multiple_choice_letter_maps_to_index():
    built = build_question("b-regional", item("b-regional", 3))
    assert built["question_type"] == "single_choice"
    assert built["choices"][built["answer_spec"]["correct_index"]] == "Cubic"
    assert built["assets"][0]["url"].endswith("b-regional_q03.png")


def test_multi_select_is_all_or_nothing_short_answer_with_options_in_stem():
    q = next(q for p in EXAMS if p["id"] == "b-regional" for q in p["questions"]
             if q["type"] == "multi_select")
    built = build_question("b-regional", q)
    assert built["question_type"] == "short_answer"
    assert "A. " in built["stem"] and "All or nothing" in built["answer_spec"]["rubric"]


def test_no_division_c_only_item_is_served_and_every_figure_exists():
    for paper in papers(EXAMS):
        for pid, q in paper["items"]:
            assert q["scope"] == "div_b"
            built = build_question(pid, q)
            for asset in (built or {}).get("assets", []):
                assert (Path(PACK_DIR) / "figures" / Path(asset["url"]).name).exists()
