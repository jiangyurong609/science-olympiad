"""A lesson must never be written from another tournament's test paper.

An imported past test is registered as a Source and mapped to its Event exactly like a
teaching source, and `extract_source_passages` walks every snapshot in the database — so
those PDFs become SourcePassages too. A course author that reads every passage mapped to its
event will therefore quote a rival tournament's question, or its ANSWER KEY, as the evidence
behind a lesson. 639 citations across the 2026 courses point at one.
"""
from app.models.entities import Source
from scripts.author_course_from_blueprint import is_past_test_source


def _source(url: str) -> Source:
    return Source(url=url, title="t", publisher="p")


def test_an_imported_past_test_is_not_teaching_evidence():
    assert is_past_test_source(_source(
        "local://public-scioly-exchange/Division B/Botany/botany_2021_b_ut_key.pdf"))
    assert is_past_test_source(_source(
        "local://BullSO 2026 Division B/Meteorology B/Meterology B 2026 Test.pdf"))


def test_an_open_source_page_still_is():
    assert not is_past_test_source(_source("https://en.wikipedia.org/wiki/Casein"))
    assert not is_past_test_source(_source("https://www.genome.gov/genetics-glossary"))
    assert not is_past_test_source(_source(""))
