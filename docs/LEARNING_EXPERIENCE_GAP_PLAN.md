# Learning-Experience Gap Plan — closing the distance to Khan Academy / Coursera

**Status:** proposed · **Created:** 2026-08-01 · **Companion to:** `HONEN_GAP_CLOSURE_PLAN.md`

`HONEN_GAP_CLOSURE_PLAN.md` closes the *content-production* gap (generate → validate →
release). This plan closes the *learner-experience* gap: what a student actually does, and
whether imported material is faithful enough to learn from.

It exists because the last stretch of work was reactive — a screen at a time, corrected three
times on one lesson. The failure mode was designing outward from the data model instead of
inward from what a student does. Every phase below therefore states the **student-visible
behaviour** it delivers, and is verified at the layer a student sees.

---

## Honest baseline (measured this session, not assumed)

| Area | Evidence | State |
|---|---|---|
| Course quality | fleet scorecard | **0 of 67** courses `release_ready` |
| Lesson review | queue inspection | **410 of 424** lessons auto-published, never reviewed |
| Item grounding | item audit | **8.7%** of 5,957 questions grounded |
| Item structure | item audit | 69.2% pass structural checks; 232 duplicate clusters |
| PDF → exam | code read | upload creates **zero** questions/exams; converter is CLI-only |
| Figures from PDFs | `flag_missing_figures.py` | text-only extraction; ~224 items reference figures that do not exist and are **excluded from scoring** |
| Video lessons | live render | working: chapters, narration, captions, diagrams, QA gate |
| Tutor / remediation / mastery / calibration | code + tests | present and tested |

**What is already competitive:** a grounded tutor with citations, misconception-tagged
remediation with near-transfer and spaced retests, a mastery model, item calibration
(facility/discrimination), coach assignments, and now chaptered video lessons with diagrams.

**What is not:** the content itself is unreviewed and thinly grounded, and imported past
tests lose their figures, answers and structure — which for a station-based, image-heavy
competition is the difference between "imported" and "usable".

---

## The two real gaps

**Gap A — ingestion fidelity.** A coach uploads a past test; nothing becomes practice.
Khan/Coursera ship professionally authored content; this platform's equivalent is faithful
import. Today it drops exactly what Science Olympiad depends on: the figures.

**Gap B — learning flow.** Capabilities exist but do not yet form one arc a student moves
along: *learn → practice → prove → repair*. Progress is recorded but not legible; there is
no placement, and practice has no scaffolding (no hints, no step-by-step).

---

## Phase A1 — Figures survive the import

**Student-visible:** a past test with diagrams imports with its diagrams, so visual items are
answerable and *scored* instead of silently excluded.

- Extend `content_ingestion._extract` (today text-only) to detect and crop page figure regions
  into `ExtractionAsset` images; store via the artifact store with the upload's reviewed rights.
- Attach extracted figures to the item that references them; keep the existing
  `figure_missing` scorer-skip as the fallback when extraction fails, never as the norm.
- Reviewer UI: show page image beside extracted item so a human can confirm or re-crop.

**Tests:** a fixture PDF with N figures yields N assets with inherited rights; an item whose
figure failed extraction is flagged `figure_missing` and excluded from scoring, not scored wrong.
**Real verification:** import a real image-based past test on staging; every visual item
renders its figure in the exam runner. Measure: share of imported items with a usable figure
(baseline today: 0%).
**Exit:** ≥90% of figure-referencing items import with their figure, or are explicitly flagged.

## Phase A2 — Upload becomes a reviewable exam

**Student-visible:** nothing, until a coach approves — which is the point.

- Wire the existing converter (`scripts/import_past_tests.py`) into the intake flow as a
  service: upload → extract → parse items → **draft** exam, behind the existing review gate.
- Parse item structure explicitly: stem, choices, points, multi-part; record per-item parse
  confidence rather than guessing silently.
- Answer keys: extract where present, pair keys to items, and route low-confidence items to
  `/content/questions/needs-key` instead of inventing an answer.
- Never auto-publish: imported exams land as drafts requiring review (the lesson of Phase 2 —
  410 lessons reached students unreviewed because a pipeline published directly).

**Tests:** a paired test+key PDF produces a draft exam with correct item count and keys; an
unpaired test produces items flagged as needing a key; nothing reaches `published` without review.
**Real verification:** a coach account uploads a real past test on staging and walks it to a
published practice exam; a student then takes it.
**Exit:** upload → draft exam → review → student-visible, with zero silently-guessed answers.

## Phase A3 — Import fidelity is measured, not asserted

- A per-import fidelity report: items parsed, figures attached, keys found, low-confidence
  items, items excluded — surfaced to the uploader.
- Extend the Phase Q scorecard to cover imported exams so fidelity trends over time.

**Exit:** every import produces a fidelity report; catalog-wide fidelity is tracked.

---

## Phase B1 — One arc: learn → practice → prove

**Student-visible:** finishing a lesson leads directly into practice on that lesson's skills,
then a check that says whether they have it — instead of the student choosing from a menu.

- Lesson completion hands off to practice scoped to the lesson's skills (the daily-plan
  machinery already exists; it is not wired to lesson completion).
- Practice ends in a short mastery check; passing advances the skill, failing opens the
  existing remediation path.
- One progress spine: the lesson step sequence (now video → reading) continues into practice
  rather than restarting in a different surface.

**Tests:** completing a lesson queues practice for its skills; passing the check raises
`MasteryState`; failing opens a `RemediationCase`.
**Real verification:** on staging, complete a lesson and follow the arc through to a mastery
change without navigating a menu.

## Phase B2 — Scaffolding inside practice

**Student-visible:** a stuck student gets a hint and a worked step, the way Khan does, instead
of only being told they were wrong.

- Per-item hints and step-by-step reveals, generated from the item's grounded claims and
  reviewed like any other content.
- "Show me a worked example" uses the existing tutor, scoped to the item's concept, with
  exam-integrity rules already implemented (no tutor during a timed exam).

**Tests:** hints exist only for reviewed items; hint use is recorded; tutor stays blocked
during exams.

## Phase B3 — Progress a student can read

**Student-visible:** "you are 3 of 8 skills into Ecology; this is due for review" — mastery
made legible, not just stored.

- Surface `MasteryState` as a per-event skill map with due-for-review counts.
- Show the lesson arc's position and what is next; make streaks and due reviews visible where
  the student already is, rather than on a separate dashboard.

## Phase B4 — Placement

**Student-visible:** a short diagnostic that puts a student at the right starting point.

- A blueprint-sampled diagnostic per event; results seed `MasteryState` and the study plan.
- Explicitly out of scope until B1–B3 land: placement into an incoherent arc has no value.

---

## Sequencing and dependencies

| Phase | Depends on | Size | Why this order |
|---|---|---|---|
| A1 figures | — | M | Highest fidelity win; unblocks visual items |
| A2 upload → exam | A1 | M–L | Needs figures to be worth importing |
| A3 fidelity report | A2 | S | Measures what A1/A2 deliver |
| B1 learn→practice arc | — | M | Independent of ingestion; biggest flow win |
| B2 scaffolding | B1 | M | Needs the arc to have somewhere to scaffold |
| B3 progress legibility | B1 | S–M | Reads the state B1 produces |
| B4 placement | B1–B3 | M | Pointless before the arc exists |

A-track and B-track are independent and can run in parallel. Content *quality* (regeneration,
review, calibration) stays in `HONEN_GAP_CLOSURE_PLAN.md` Phases 1–2 and Q — this plan assumes
that work continues rather than duplicating it.

## Verification discipline (the correction from this session)

Every phase is checked at the layer a student uses, not at the layer that is convenient:

1. A capability is not done when its API returns correct data; it is done when the intended
   person completes the intended task on a real screen at a real viewport.
2. Before building a new surface, state how it joins the surfaces that already exist. Two
   lists of the same content is a design failure, not a layout detail.
3. Where a known pattern exists (a course leads with video and advances with Continue),
   follow it rather than inventing a layout.
4. Regression-test the contract, not just the unit: the lesson sequence test exists because a
   person had to click Continue sixteen times to find a broken one.

## Risks

- **Figure extraction accuracy** — PDFs vary wildly; mitigate with per-item confidence, human
  confirmation in review, and the existing `figure_missing` fallback.
- **Import volume vs review capacity** — imported exams need human review; batch the queue by
  event and let a coach approve a whole exam rather than item-by-item.
- **Scope creep against content quality** — this plan does not fix unreviewed content; that is
  the Honen plan's Phase 2. Running both matters, and neither substitutes for the other.
