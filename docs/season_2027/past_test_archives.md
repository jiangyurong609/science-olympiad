# Where the past tests came from

The corpus we started with — 532 tournament PDFs under `docs/science_olympiad_tests/_extracted`
— held nothing at all for Botany, Thermodynamics or Food Science, and one or two papers for
Codebusters, Experimental Design and Write It Do It. A generated practice paper for those
subjects had no measured shape of its own to match, which `scripts/profile_past_exams` reports
as `no past test is held for this subject`.

These are the archives that closed the gap. All four are public; none needed a login.

## 1. The Internet Archive's copy of the scioly.org Test Exchange

`scioly.org` itself is behind an Anubis proof-of-work gate — `https://scioly.org/tests` answers
`Making sure you're not a bot!` to any client we have, including a direct hit on a file path.
The Wayback Machine crawled it before the gate went up, and serves the files ungated:

    curl -sG https://web.archive.org/cdx/search/cdx \
      --data-urlencode 'url=scioly.org/tests/*' \
      --data-urlencode 'filter=mimetype:application/pdf' \
      --data-urlencode 'fl=original,timestamp,statuscode,mimetype' \
      --data-urlencode 'collapse=urlkey'

1,525 test PDFs, captured 2017–2023. The filenames are structured —
`<event>_<year>_<division>_<tournament>_<test|key|sheet>.pdf` — so an event and a division fall
straight out of them. 538 of them belong to 2027 Division B subjects.

**Two things go wrong here and both are silent.** The crawler stops at 1 MiB, so a larger paper
comes back CUT OFF, and a cut-off test still opens — it just has fewer questions than the real
one. Four Botany captures are truncated this way. The response says so itself
(`x-archive-orig-x-crawler-content-length` exceeds what was stored) and the fetcher refuses
them. Separately, a fast run gets throttled and the body is an error page rather than a PDF; a
first pass over 28 files "failed" 19 and every one fetched cleanly on a slower retry.

## 2. Tournaments that publish their own tests in a public Google Drive folder

A public Drive folder page embeds its whole listing in a `_DRIVE_ivd` JavaScript blob, so it can
be walked and downloaded with no API key.

| Archive | Coverage | Where the folder ids come from |
| --- | --- | --- |
| UT Austin / ATX | 2018–2025 invitationals, 2019–2026 regionals | <https://www.atxscioly.org/resources> |
| Michigan SO | several seasons | <https://miscioly.org/tools> |
| Rickards (RSOI) | 2021–2026, both divisions | <https://rsoi.org/archives> |
| Cornell, MIT, Princeton, UChicago | Division C invitationals | each tournament's own archive page |

ATX and RSOI are the valuable ones for Division B: they are the only archives holding **Botany
Division B exams with keys** (UT Austin 2022 and 2023, RSOI 2023).

## 3. NC Science Olympiad

Serves papers as ordinary PDFs from per-event pages, e.g.
`https://ncscienceolympiad.ncsu.edu/thermodynamics/`. Three Thermodynamics papers (2018 Division
C regional and state, 2019 regional). Two of the three are scans with no text layer and need
`scripts/transcribe_scanned_tests`.

## 4. What is still missing

**Write It Do It** has no written paper to find, at any archive. The event is a technical-writing
task judged against a build, so what a tournament publishes is an instruction sheet and a rubric,
not a test with questions. Generating a practice paper "in the format of past tests" is not
meaningful for it.

## Rights

Every file carries a `.provenance.jsonl` record beside it naming the archive and the URL it came
from. The Drive archives are tournaments publishing their own tests. The Test Exchange papers
were uploaded by their authors to be used for practice. This is the same class of material as the
113 papers already imported from the supplied corpus, but it is a judgement worth making
deliberately rather than by default — if the Test Exchange set should stay out of the
student-facing catalog, it is separable: every one of those papers sits under
`_extracted/public-scioly-exchange/`.
