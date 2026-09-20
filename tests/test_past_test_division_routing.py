"""A past test must reach the division that sat it.

Getting this wrong is not cosmetic: a Division C paper filed under the Division B event is
offered to middle-school students as their own past test, and `profile_past_exams` then
measures the wrong shape for the practice papers we generate from it.

Every case here is a real path from the corpus, and each one broke a rule that looked fine.
"""
from scripts.fetch_public_test_archives import detect_division as fetch_division
from scripts.import_local_tests import _detect_division


def test_folder_naming_one_division_beats_a_disagreeing_filename():
    # A Division B folder reusing the Division C station sheet. The supervisor's filing wins.
    assert _detect_division(
        "BullSO 2026 Division B/Rocks and Minerals B/Stations Rocks and Minerals C.pdf") == "B"


def test_filename_beats_a_folder_that_names_both_divisions():
    # ATX hands both divisions one folder; reading the folder calls both papers Division B.
    base = "public-atx-reg-2026/Division B/Disease Detectives"
    assert _detect_division(f"{base}/Disease_Detectives_C_Test.pdf") == "C"
    assert _detect_division(f"{base}/Disease_Detectives_B_Test.pdf") == "B"


def test_camel_case_division_needs_a_capital_after_a_lowercase_letter():
    # `BotanyC_Exam` says C with no separator at all...
    assert _detect_division("public-atx-inv-2022/Division B/Botany/BotanyC_Exam.pdf") == "C"
    assert _detect_division("public-atx-inv-2022/Division B/Botany/BotanyB_Exam.pdf") == "B"
    # ...but a case-insensitive version of that rule reads the last letter of an ordinary
    # word as a division. These are the three that re-filed 55 papers wrongly.
    assert _detect_division(
        "public-rsoi-2026-B/Division B/Dynamic Planet/RSOI Dynamic Planet B 2026 Test.pdf") == "B"
    assert _detect_division(
        "public-rsoi-2026-C/Division C/Circuit Lab/RSOI Circuit Lab C 2026 Key.pdf") == "C"
    assert _detect_division(
        "public-ncso/Division C/Thermodynamics/2019ThermoCRegionalsforWeb.pdf") == "C"


def test_ancestor_folder_answers_for_a_paper_whose_name_says_nothing():
    assert _detect_division(
        "public-princeton-a/Division C/Circuit Lab/PUSO 2026 Circuit Lab Test.pdf") == "C"
    assert _detect_division(
        "Division B Tests and Answer Keys/Fossils (1)/BullSO 25 Fossils Answer Sheet.pdf") == "B"


def test_unknown_stays_unknown():
    # A tournament that runs both divisions and says so nowhere. Guessing would be worse.
    assert _detect_division(
        "2025 UW River Falls Border Battle Tests/5 codebusters/Codebusters 2025 test.pdf") is None


def test_underscore_is_a_word_character_so_the_fetcher_reads_the_division_itself():
    # `\b[bc]\b` never matches `_b_`, which is how a test exchange spells the division.
    assert fetch_division("botany_2021_b_ut_test.pdf") == "B"
    assert fetch_division("thermodynamics_2019_c_uflorida_key.pdf") == "C"
    assert fetch_division("2018-Thermodynamics-State-C.pdf") == "C"
    assert fetch_division("Heredity/whatever.pdf") is None


def test_fetcher_falls_back_to_a_division_only_archive():
    # A university invitational runs Division C and its tree never says so.
    assert fetch_division("Circuit Lab/PUSO 2026 Circuit Lab Test.pdf", "princeton-a") == "C"
    assert fetch_division("Codebusters/RSOI Codebusters 2026.pdf", "rsoi-2026-C") == "C"
