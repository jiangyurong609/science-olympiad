from types import SimpleNamespace

from scripts.reclassify_generated_exams import is_transcribed


def q(provenance):
    return SimpleNamespace(generation_provenance=provenance)


def test_only_past_test_imports_count_as_transcribed():
    assert is_transcribed(q({"import_kind": "past_test", "exam_source_id": 1}))
    assert not is_transcribed(q({"marker": "catalog-2026-generated", "model": "gpt-4o-mini"}))
    assert not is_transcribed(q({"prompt_version": "competition-item-v3-self-contained"}))
    assert not is_transcribed(q(None))
    assert not is_transcribed(None)
