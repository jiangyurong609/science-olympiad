# Master Plan — one ordered path to a shippable platform

**Created:** 2026-08-01 · **Revised:** 2026-08-01 after adversarial review (findings M1–M5)
**Entry point for:** `HONEN_GAP_CLOSURE_PLAN.md`, `KHAN_STYLE_LEARNING_EXPERIENCE_PLAN.md`
(both remain detailed specs; this document decides *order* and *gates*).

Work has been reactive: symptoms fixed a screen at a time while the cause went untouched.
This orders everything by **dependency**, with gates that cannot be satisfied by relabelling.

> **Adversarial review corrections applied.** M1 removed a circular Phase 3/4 gate; M2 closed
> a Phase 0 metric that could pass while unsafe items were still served; M3 replaced a
> single-root-cause story with a write-path inventory; M4 replaced an undefined, gameable
> grounding percentage; M5 made the pilot course explicit and evidence-based.

---

## 1. Diagnosis — four publication paths, not one script

Content became student-visible without grounding or review. It was **not** one script; the
repository contains several independent paths that publish or serve unreviewed content, and
retiring any one of them closes nothing:

| Path | Behaviour | Evidence |
|---|---|---|
| `scripts/build_courses.py` | wrote lessons/exams straight to published | 410 lessons, 5,957 items |
| `app/services/mock_exam.py` | **selects `QuestionStatus.DRAFT` items** and creates `published=True` exams | `mock_exam.py:27,92` |
| `app/services/past_test_import.py` | creates `published=True` exams on import | `past_test_import.py:184` |
| `app/services/lesson_generation.py` | publishes directly when `publish` is set | `lesson_generation.py:250,256` |

**Therefore the fix is an invariant, not a deletion:** one centralized student-visibility rule
that every write and read path must satisfy, with tests proving no path can bypass it.

### Measured state (2026-08-01)

| Metric | Value |
|---|---|
| Courses `release_ready` | 0 / 67 |
| Published lessons with review evidence | 0 / 410 |
| Questions `published` | 0 (687 machine_validated, 5,270 draft) |
| Published exams serving unreviewed items | 150 |
| Items grounded | 8.7% |
| Lessons that can cite a *relevant* approved claim | **0 / 410** |
| **Current-season events with a rights-cleared usable source** | **0** |
| Attempts in progress (Phase 0 must not strand these) | 4 |

The last two rows matter most: grounding cannot begin by "running the extraction pipeline",
because no current-season event has a usable source to extract from. Phase 1 therefore starts
with source acquisition and rights clearance.

## 2. Operating rules

1. **Dependency order is binding.** No phase starts before its predecessor's number is met.
2. **Done is a number produced by a committed command.** If the command does not exist, the
   phase's first task is to write it (M4).
3. **A gate may not be satisfied by relabelling.** Reducing exposure is the goal; a label is
   at best an addition to a control, never the control (M2).
4. **No new student-facing capability until Phase 3 completes.** Capability on unreviewed
   content multiplies the defect — proved twice (410 lessons; a video citing a mineral claim).
5. **One plan.** New findings amend this document.

---

## Phase 0 — Make unreviewed content unservable (not merely labelled)

**Why first:** students can be scored on unreviewed items today, and the mock-exam path
actively manufactures them.

Three separate controls, all required:

- **0a Stop creation.** A published exam may not be assembled from items lacking review.
  Fix `mock_exam.py` (stop sampling `DRAFT`), `past_test_import.py`, and the
  `lesson_generation` publish flag to route through the one invariant.
- **0b Stop new exposure.** New starts of an exam containing unreviewed items are refused,
  or the exam is reclassified to a release class that is honest about what it is.
- **0c Preserve work in flight.** The **4 in-progress attempts** must remain resumable and
  scoreable from their immutable `ExamItem` snapshots. Unpublishing must never strand a
  student mid-attempt.
- **0d Disposition every existing exam:** preserve (historical, labelled), withdraw, or send
  to review. No exam is left implicitly published.

**Done when** (all four):
1. `pytest` proves no path can create a published exam/lesson containing unreviewed items;
2. no *new* attempt can start on an exam with unreviewed items;
3. every one of the 4 in-progress attempts resumes and scores correctly in a browser;
4. all 150 exams carry an explicit disposition — count of "implicitly published" is **0**.

**Size:** S–M. **Unblocks:** everything.

## Phase 1 — Grounding, defined and measured

**Why now:** grounding gates regeneration (2), traceability (§8), and video (5). Today
**0 / 410** lessons can cite a relevant approved claim, and **no current-season event has a
usable source at all**.

- **1a Write the audit first** (`scripts/audit_grounding.py`, versioned, committed). It must
  measure, per event and per lesson, and **fail on an empty population**:
  - claim → passage validity (evidence excerpt actually present in the retained snapshot),
  - source rights (`can_use_for_generation`),
  - **substantive coverage**: share of teaching blocks/assertions supported, not "≥1 claim",
  - skill coverage, with a `ContentGap` recorded for every unsupported skill.
- **1b Acquire and clear sources** for the pilot event (Phase 1 cannot be extraction-only).
- **1c Extract → approve claims** through the existing pipeline; attach to lessons/concepts.

**Done when:** the pilot course reports **100%** substantive coverage with zero unsupported
skills lacking a `ContentGap`. Catalog-wide thresholds come later (Phase 6), so the pilot is
not blocked behind 328 other lessons (M5).
**Size:** M. **This is the work that has never been done.**

## Phase 2 — Regenerate the pilot course

Detail: `HONEN_GAP_CLOSURE_PLAN.md` Phases 1–2. Generator hardening (solver + embedding) is
already built.

**Done when:** `python -m scripts.audit_content_quality --status machine_validated
--generation-run <id>` reports ≥90% validation pass, 100% grounded, 0 blocking near-dups, and
every exam meets its blueprint. Output stays at `machine_validated`; nothing auto-publishes.

## Phase 3 — Review the pilot to *content-ready* (not release-ready)

**M1 fix:** `audit_course` blocks on `release_missing`, which only Phase 4 can satisfy. So
Phase 3 gates on **content readiness** — every `audit_course` blocker *except* `release_missing`
— and full `release_ready` is asserted after promotion in Phase 4.

- Editor → SME review through the existing queues; publish only from `sme_approved`.
- Meet §4.4 volume and the question contract for every skill in the pilot.

**Done when:** the pilot course has zero `audit_course` blockers other than `release_missing`.
**Size:** M (human review dominates).

## Phase 4 — Release machinery, then promote the pilot

Detail: `HONEN_GAP_CLOSURE_PLAN.md` Phase 6 / R-C3 — catalog-release identity, immutable
membership, atomic active pointer, release-aware reads, backfill, dual-read deploy, promotion
job with dry-run manifest and a rehearsed **data** rollback (media included).

**Done when:** the pilot promotes atomically, `audit_course` now reports **`release_ready`**,
and a rehearsed rollback restores the prior state. **First genuinely finished course.**

## Phase 5 — Video for the pilot

Rendering was never the constraint (measured 3.1 h wall at 8× parallel for all 410 lessons).

- Narration generated from lesson blocks + their *relevant* grounded claims (hand-authored
  today); the relevance gate added after the mineral-claim defect stays in force.
- Storyboard → approval → chaptered render → QA before student visibility.

**Done when:** every lesson in the pilot has grounded, QA-approved video.

## Phase 6 — Repeat at catalog scale

Only now does a catalog-wide threshold make sense, because the pilot proved the pipeline.

- Phases 1–5 applied event by event, ordered by the Phase Q backlog (severity × usage).
- **Done when:** ≥80% of live-event lessons meet the Phase 1 substantive-coverage bar and
  ≥N courses are `release_ready`.

## Phase 7 — Ingestion fidelity (uploaded past tests)

- **7a** figures survive import (today text-only; ~224 items reference figures that do not
  exist and are excluded from scoring); **7b** upload → *draft* exam behind review, with
  per-item parse confidence and low-confidence answers routed to the needs-key queue;
  **7c** per-import fidelity report feeding the Phase Q scorecard.
- Sequenced here because it competes for the same review capacity and must clear the same
  Phase 0 invariant.

## Phase 8 — Learning-flow completion

Learn → practice → prove wired to lesson completion; scaffolding (hints, worked steps);
progress legibility; placement diagnostic last.

---

## 3. Pilot course selection (M5) — evidence, not preference

`KHAN_STYLE_LEARNING_EXPERIENCE_PLAN.md` Phase 1 designates **Rocks & Minerals Division B**.
The measured position complicates that and must be resolved before Phase 1 starts:

| Candidate | Season status | Lessons | Items | Usable sources | Approved claims |
|---|---|---:|---:|---:|---:|
| `rocks-and-minerals-b` (designated) | current | 8 | 105 | **0** | **0** |
| `rocks-and-minerals` (seed) | prior-season | 8 | 48 | 1 | 4 |
| `ecology` (seed) | prior-season | 8 | 11 | 1 | 5 |
| `astronomy-c` | current | 8 | 558 | **0** | **0** |

Facts that must drive the choice:

- **No current-season event has any grounding foundation.** Choosing a current-season pilot
  means Phase 1b (acquire + clear sources) is the bulk of the work.
- The two events with any foundation are **prior-season practice**, so a pilot there proves
  the pipeline but does not ship a current-season course.
- The hand-authored Rocks vertical-slice lessons (14) sit on `rocks-and-minerals-b-2027`,
  which consolidation archived; recovering them is a prerequisite if Rocks is chosen.

**Decision required before Phase 1.** Recommended: **Rocks & Minerals Division B**, honouring
the existing design decision and the 14 hand-authored lessons, accepting that Phase 1b must
acquire and clear its sources. Ecology is the faster proof but ships a prior-season course.
Record the decision and its rationale here when made.

## 4. Scoreboard

| Metric | Today | Target | Phase |
|---|---:|---:|---|
| Paths able to publish unreviewed content | 4 | 0 | 0 |
| Exams without an explicit disposition | 150 | 0 | 0 |
| In-progress attempts stranded | — | 0 | 0 |
| Pilot substantive grounding coverage | 0% | 100% | 1 |
| Pilot items passing validation | — | ≥90% | 2 |
| Pilot `audit_course` blockers (excl. release) | many | 0 | 3 |
| Courses `release_ready` | 0 / 67 | 1 | 4 |
| Pilot lessons with grounded video | 0 | all | 5 |
| Live-event lessons meeting the grounding bar | 0 / 410 | ≥80% | 6 |
| Imported items with usable figures | 0% | ≥90% | 7 |
