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

**Done when:** every substantive block in the pilot is **accounted for** — either backed by
verifiable evidence or openly recorded as a `ContentGap` — and no skill is unsupported without
a gap. Coverage and accountability are reported separately so a gap can never be mistaken for
grounding. Catalog-wide thresholds come later (Phase 6).

**Result (2026-08-01):** pilot `rocks-and-minerals-b` — 933 verified claims from 26
rights-cleared sources, **56.0% evidence-backed**, **100% accounted for** (33 ungrounded
blocks recorded as gaps across 8 skills). Demanding 100% *coverage* would have meant loosening
the evidence rule, which is exactly the failure an earlier pass made; the shortfall is a fact
about available open sources and is now visible rather than hidden.

**Raised to 65.3% by acquiring more sources (2026-08-01).** Before that: 29.6%,
(58 of 196 blocks), accountability still 100%. The first re-measure said 47.2% because the
audit excluded `checkpoint` blocks on the reasoning that a question asserts nothing — true of
a bare question, false of a generated one, which carries choices and an explanation of why
the answer is right. Generated assessment content was therefore sitting outside the
denominator entirely. Splitting eight lessons into 24 added 48 generated openings and summaries, and those
carry no evidence of their own. The number could be restored to 56% by letting each generated
block cite its part's claims, and that is precisely the inheritance this audit removed after
it was found crediting unevidenced summaries — so the dilution stands as measured. The
teaching content did not get less grounded; there is simply more prose in front of it, and
grounding that prose is real work rather than a counting choice.
**Size:** M. **This is the work that has never been done.**

## Phase 2 — Regenerate the pilot course

Detail: `HONEN_GAP_CLOSURE_PLAN.md` Phases 1–2. Generator hardening (solver + embedding) is
already built.

**Done when:** `python -m scripts.audit_content_quality --status machine_validated
--generation-run <id>` reports ≥90% validation pass, 100% grounded, 0 blocking near-dups, and
every exam meets its blueprint. Output stays at `machine_validated`; nothing auto-publishes.

**Result (2026-08-01): met.** Run `regen-pilot-002` produced 100 items at
`machine_validated` — **93.1% validation pass** (the rest held at `draft` by the blind solver
and verifier), **100% structurally valid, 100% grounded, 0 near-duplicate clusters**, 0
single-shot provenance. Nothing was published.

## Phase 3 — Review the pilot to *content-ready* (not release-ready)

**M1 fix:** `audit_course` blocks on `release_missing`, which only Phase 4 can satisfy. So
Phase 3 gates on **content readiness** — every `audit_course` blocker *except* `release_missing`
— and full `release_ready` is asserted after promotion in Phase 4.

- Editor → SME review through the existing queues; publish only from `sme_approved`.
- Meet §4.4 volume and the question contract for every skill in the pilot.

**Done when:** the pilot course has zero `audit_course` blockers other than `release_missing`.
**Size:** M (human review dominates).

**Status (2026-08-01): mechanical half complete; blocked on review.** 172 → 243 blockers, and
the rise is the point: the count grew because content that did not exist now does and has to
be reviewed. **Every remaining blocker is a human decision.** What was fixed, and what was
deliberately not:

| Was | Cause | Resolution |
|---|---|---|
| 90 `claim_passage_missing` | claims stored an excerpt and a snapshot but no retained passage | passage reconstructed by locating the excerpt in the snapshot; unlocatable ⇒ still blocking |
| 16 `source_unreconciled` | mapped sources had no course disposition | role and extraction status recorded from what each source produced |
| 11 `source_destination` | instructional sources no lesson reached | **reverted** — see below |
| 8 `lesson_duration` | lessons ran 19–27 min against a 5–12 min target | split into 24 parts of 8–12 min |
| 8 `lesson_transfer` | parts had no check above recall | one application/transfer check generated per part |
| 1 `unit_skill_volume`, 1 `unit_quiz_missing` | all 8 skills in one "Legacy Learning Path" unit | 3 units of 2–3 skills, each with a quiz blueprint |
| 8 `question_volume` reported 0 items | **no skill had a `concept_id`**, and the audit reads items through it | one concept per skill; 72 items now reachable |

**Reverted after adversarial review.** The 11 `source_destination` blockers were cleared by
setting `instructional_role = "reference_only"`, a role `course_quality` exempts from that
very check. "No lesson cites it" is evidence a source is *unused*, not evidence of what it
was for — it may be instructional content lost in a regeneration, which is the case most
worth surfacing. The demotion was relabelling by the plan's own operating rule 3, the roles
are restored, and 9 blockers correctly stand awaiting a reviewer.

**Not fixed, on purpose:** `lesson_review` (24), `question_review` (72),
`question_calibration` (72), `source_review` (21), `content_gap` (8),
`unit_quiz_unpublished` (3). Approving these without a reviewer is the relabelling operating
rule 3 forbids. Two `lesson_citations` also remain: those parts contain no grounded block at
all, which is Phase 1's 56% coverage surfacing per lesson, and they need a source rather than
plumbing.

**Unblocking this needs a person**, and the queue that hid the work is now fixed (it skipped
any lesson in a published course, so it showed 0 of 24). The pending decisions are:
24 lesson reviews × 2 stages, 72 item reviews × 2 stages, 72 calibrations, 21 source reviews.

## Phase 4 — Release machinery, then promote the pilot

Detail: `HONEN_GAP_CLOSURE_PLAN.md` Phase 6 / R-C3 — catalog-release identity, immutable
membership, atomic active pointer, release-aware reads, backfill, dual-read deploy, promotion
job with dry-run manifest and a rehearsed **data** rollback (media included).

**Done when:** the pilot promotes atomically, `audit_course` now reports **`release_ready`**,
and a rehearsed rollback restores the prior state. **First genuinely finished course.**

**Status (2026-08-01): machinery built and tested; promotion waits on Phase 3.**
`decide_content_release` flipped `course.status` and wrote an audit line — nothing recorded
*what* shipped, so `release_missing` could never clear and a rollback moved a version pointer
over content that had already changed underneath it. `app/services/content_release.py` now
makes a release a manifest (lesson versions, published item versions, blueprints, claims,
sources, plus a digest), publishes it atomically with the pointer, refuses to rewrite an
already-published version's membership, rolls back to the previous manifest, and reports
drift when live content diverges from the active release. 10 tests cover these paths.
The pilot cannot promote until its review decisions exist — that is Phase 3, not this phase.

## Phase 5 — Video for the pilot

Rendering was never the constraint (measured 3.1 h wall at 8× parallel for all 410 lessons).

- Narration generated from lesson blocks + their *relevant* grounded claims (hand-authored
  today); the relevance gate added after the mineral-claim defect stays in force.
- Storyboard → approval → chaptered render → QA before student visibility.

**Done when:** every lesson in the pilot has grounded, QA-approved video.

**Status (2026-08-02): produced and in production; QA-approval outstanding.** All 24
published lessons carry video — 24 chapters, 52.4 minutes. The renders were produced against
the local database and the rows were carried across by `scripts/migrate_lesson_videos.py`
(both environments already share the GCS bucket, so only the rows were missing); it matches on
event slug, lesson slug and claim *text*, and refuses a lesson whose target content differs
rather than let a scene narrate the wrong sections. Three chapters whose first render failed
were re-rendered.

Two defects surfaced only once the data existed. `lesson_chapters` worked out which lesson
blocks a video covered by reading a `chapter` label off each scene; the pilot's scenes carry
no such label, so every chapter reported **no blocks** and the reader could not interleave
video with the reading it explains. It now rebuilds the same plan `render_lesson` rendered
from. And building the 22-chapter review queue took 27.7s, of which 1.2s was the database —
the rest was signing playback URLs serially through IAM; overlapping them gives 4.9s.

**What remains is not engineering:** 25 chapters sit at `qa_status=pending`. Staff see them in
context; students see none. Someone has to watch them.

## Phase 6 — Repeat at catalog scale

**Executed on a ten-event launch slice (2026-08-02).** The plan sized Phase 6 as ~50 declared
unit plans and ~1,200 lesson reviews. The measured production position was different and
smaller: 474 published lessons across 92 events, but only 2 events with any grounding at all,
so nothing downstream — items, exams, mastery — could be produced anywhere else.

Two faults, one of them not a content gap. `EVENT_DOMAIN` is keyed on base slugs and
`ground_event` looked up the full slug, so grounding refused 100 of 102 events with "no
open-source domain mapped" — a lookup bug that read as missing sources. And the source
catalogue itself was thin everywhere except geology: 64 curated URLs there against two
everywhere else, with `physics` expected to ground ten different events. 22 URLs were dead and
an entire domain (meteorology) was 403 on every page, so it could never have grounded at all.

Both closed: one `domain_for_event`, 241 URLs all verified answering 200, and
`scripts/check_open_sources.py` so a dead source is caught before a commit rather than by an
empty run. Ten events then went through the proven pipeline end to end — ground → generate →
gate → assemble:

  claims 457 -> 2,525 across 17 events; items clearing every gate 66 -> 244 across 10 events;
  practice exams 0 -> 11.

**Exams are shaped by past tests, not made of them.** `derive_blueprint` reads the imported
past-test pool for structure — item count, cognitive mix, difficulty bands, topic weights,
which are facts — and the exam is then filled entirely with our own gated items. 247 items
placed across 11 exams, **0 carrying `import_kind=past_test`**, pinned by a test. This is the
form the "use their past exams" request takes that we can actually publish.

**Phase 6 remains review-bound, and the number is now precise:** 244 items, 11 exams, 24
lessons, 25 video chapters and 403 lesson→concept mappings are queued. `can_start_new_attempt`
returns False for all 11 exams, which is Phase 0 working. Engineering has stopped being the
constraint; it was replaced by a queue rather than by a launch.


Only now does a catalog-wide threshold make sense, because the pilot proved the pipeline.

- Phases 1–5 applied event by event, ordered by the Phase Q backlog (severity × usage).
- **Done when:** ≥80% of live-event lessons meet the Phase 1 substantive-coverage bar and
  ≥N courses are `release_ready`.

**Sized (2026-08-01) — `python -m scripts.audit_catalog_structure`.** The pilot's defects are
not the pilot's. Of 67 live events, **exactly one is free of all of them**:

| Defect | Events |
|---|---:|
| Skills with no `concept_id` — their items are invisible to the audit | **50** |
| All skills in a single oversized unit | **50** |
| No unit-quiz blueprint | **50** |
| Course carrying no skills at all | **16** |
| **Lessons over the 12-minute target** | **402 of 426 (94%)** |

**Corrected (2026-08-02): the table above measures the *local* database, not production.**
Production holds 2 courses, 22 skills and 231 concepts — but **474 published lessons across 92
events**, 6,042 questions and 150 published exams. The catalog-scale defect there is not badly
shaped courses; it is lessons served with no course structure behind them at all.

What that costs was measured, not assumed: `MasteryState` is keyed on `Concept`, and the only
mastery evidence reading produces is `if lesson.concept_id:` in the checkpoint route. **450 of
the 474 published lessons had no `concept_id`**, so a student could read one, answer every
checkpoint, complete it — and nothing was recorded. The daily plan had nothing to schedule,
remediation had no concept to route to, progress had nothing to show. Phase 8's chain was
severed for 95% of the catalog by the same kind of unset field that severed it for the pilot's
checkpoints.

`scripts/link_lessons_to_concepts.py` closes the half that needs no judgement and refuses the
half that does. Where an event has **no authored concepts**, a concept is created per lesson:
that groups nothing and asserts nothing. Where an event **has** authored concepts — `ecology`
has "Energy flow", "Population ecology" and two more, none matching any lesson title — mapping
a lesson onto one is a pedagogical decision and adding a lesson-named fifth asserts it belongs
to none of them. Both are refused and reported. **71/474 now record mastery (was 24); 403 await
a human mapping.** Creations are tagged and reversible, and re-running is a no-op.

This is the number that decides Phase 6's shape. The per-event work is now scripted and
proven on the pilot, but two parts do not automate: unit boundaries are a pedagogical
decision (`build_course_structure` refuses to guess them and requires a declared plan), and
every split lesson needs the same editor and SME review the pilot's 24 are waiting on. The
engineering is ~50 declared unit plans; the review is ~1,200 lesson decisions at the pilot's
rate. **Phase 6 is review-bound, not engineering-bound**, and no amount of further tooling
changes that.

## Phase 7 — Ingestion fidelity (uploaded past tests)

- **7a** figures survive import (today text-only; ~224 items reference figures that do not
  exist and are excluded from scoring); **7b** upload → *draft* exam behind review, with
  per-item parse confidence and low-confidence answers routed to the needs-key queue;
  **7c** per-import fidelity report feeding the Phase Q scorecard.
- Sequenced here because it competes for the same review capacity and must clear the same
  Phase 0 invariant. **Brought forward** when Phase 3 stalled on human review: this is
  engineering that produces drafts, so it consumes no review capacity while it waits.

**Status (2026-08-01): complete.**

- **7a limitation, measured.** Recovery works — 76 figures from 8 real PDFs, furniture
  correctly rejected — but **0 of the 43 currently-blocked items can be recovered**, and that
  is the right answer rather than a tuning failure. Science Olympiad tests reference images
  that are mostly **vector drawings** (`page.images` sees rasters only: one exam references 21
  images and yields 2) and print them on a **separate image sheet**, so page adjacency carries
  no information. Label counts and figure counts across three documents (21/2, 18/25, 3/13)
  rule out an ordinal mapping too. Closing this needs vector-region rendering and caption OCR.
  `scripts/backfill_figures.py` records the breakdown.
- **7a** — `pdf_figures` recovers embedded figures from the retained PDF bytes. Furniture is
  rejected by dimensions, aspect, and cross-page repetition. Only an *unambiguous* attachment
  (one figure, one question, one page) un-drops an item; `ambiguous` attaches for review but
  leaves the item excluded, because guessing which figure a question means is the failure
  this exists to end. Encoded byte size was tried as a content test and removed — it
  discarded a real line drawing, which compresses as well as any logo.
- **7b** — every item carries a parse confidence computed from checkable facts (was the stem
  found in the source, does an answer exist, is the choice structure coherent). The model is
  never asked to rate itself. A short answer that fails is emptied so it reaches the
  needs-key queue rather than grading a student against a guess.
- **7c** — `scripts/audit_import_fidelity.py`. First run: **96 imports, 4,755 items, 83.2%
  gradeable, 19 imports below 60%**. It found that **27 imports (1,226 items) ran with no
  answer key while the key was in the database**, unopened. `find_key_source` recovers 8 of
  those 27 (362 items); the remaining 19 have no key at all. Matching refuses on a tie —
  the wrong event's key is worse than none.

## Phase 8 — Learning-flow completion

Learn → practice → prove wired to lesson completion; scaffolding (hints, worked steps);
progress legibility; placement diagnostic last.

**Status (2026-08-02): the wiring was severed and is repaired; two parts are unbuilt and
rule 4 holds them.**

The chain existed but did not run for most of the published content. Checkpoints are written
in two shapes — hand-authored (`question`/`correct_index`, with an `id`) and `split_lessons`
output (`prompt`/`answer_index`, no `id`) — and nothing declared a canonical form, so serve,
render and grade each picked a pair and ignored the other. **41 of the 73 published pilot
checkpoints were the second shape**: they shipped their answer key to the browser, arrived
with no question attached, could not be submitted, could not have been graded correct if they
had been, and raised a `KeyError` that broke the well-formed checkpoints beside them. Since a
lesson completes only when every checkpoint is correct, and lesson completion is the only
mastery evidence reading produces, **no such lesson could ever complete and no mastery
evidence was recorded from lesson work at all.**

`app/services/lesson_blocks.py` now reads both shapes in one place and every path uses it —
not a content migration, which would leave the same bug waiting for the next generator.
Measured after: **73/73 checkpoints gradeable, 0 leaking a key, 24/24 lessons completable.**
The existing lesson tests passed throughout because every fixture was built the hand-authored
way; `tests/test_lesson_checkpoint_schemas.py` builds them the way the content is, and all
five fail without the fix.

**Scaffolding and the placement diagnostic are now built, gated on review.** Rule 4 forbids
new capability *on unreviewed content*, not the engineering that will serve reviewed content —
the distinction Phase 7 was brought forward on. Both ship dark and light up per lesson as
review completes, consuming no review capacity while they wait.

- **Hints** (`app/services/lesson_hints.py`, `scripts/write_checkpoint_hints.py`). A hint is
  requested, not delivered beside the question: asking is a signal about confidence, and it is
  recorded on `LessonProgress`. Two refusals gate it. It is served only for a lesson with
  editor **and** SME decisions on *that version* — the same evidence `student_visibility`
  demands, not a parallel mechanism, because this codebase has already shipped three gates
  that agreed only by coincidence of the data. And a hint faces the blind solver every other
  assessment artefact faces, inverted: the hint is refused when a solver denied the lesson
  could not pick the key without it and could with it. A solver that already knew the answer
  proves nothing about the hint, so only a hint that *turns* a wrong answer into the key is
  implicated. Refused hints are kept with `hint_too_revealing` so the reviewer sees what was
  rejected.
- **Placement diagnostic** (`app/services/placement.py`). Sequenced last because it depends on
  everything else being real: concepts to place against, items a human accepted, lessons to
  send people to. It refuses rather than running thin — below 2 concepts or 4 student-ready
  items it reports nothing, because a placement from less claims a measurement it did not
  make. It draws only `item_is_student_ready` items (Phase 0's rule, since a diagnostic
  scores), excludes concepts with no student-visible lesson (placing someone where they cannot
  then go is a dead end), and **never overwrites mastery a student earned by doing the work** —
  it seeds with `evidence_count = 0`, because a diagnostic is the weakest evidence here.

What remains in Phase 8 is content and review, not engineering.

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

| Metric | Start | Now (2026-08-01) | Target | Phase |
|---|---:|---:|---:|---|
| Paths able to publish unreviewed content | 4 | **0** | 0 | 0 |
| Exams without an explicit disposition | 150 | **0** | 0 | 0 |
| In-progress attempts stranded | — | **0** | 0 | 0 |
| Pilot blocks accounted for (evidenced or an open gap) | 0% | **100%** | 100% | 1 |
| Pilot blocks evidence-backed (topical) | 0% | **96.4%** (189/196) | — | 1 |
| Pilot checkpoints clean on solver **and** verifier | — | **43 / 73** | all | 3 |
| Pilot items passing validation | — | **93.1%** | ≥90% | 2 |
| Pilot `audit_course` blockers needing no human | many | **0** | 0 | 3 |
| Pilot `audit_course` blockers needing a human | — | **252** | 0 | 3 |
| Pilot lessons within the 5–12 min target | 0 / 8 | **24 / 24** | all | 3 |
| Pilot lessons visible to a reviewer | 0 / 24 | **24 / 24** | all | 3 |
| Release manifest + rehearsed rollback | absent | **built, 10 tests** | proven on pilot | 4 |
| Courses `release_ready` | 0 / 67 | 0 / 67 | 1 | 4 |
| Courses published while serving no lesson | unmeasured | **0** | 0 | 4 |
| Courses published without a content release | unmeasured | **50** | 0 | 4/6 |
| Pilot lessons with grounded video | 0 | **24 / 24** (52.4 min) | all | 5 |
| Published lessons able to record mastery | — | **71 / 474** (was 24) | all | 6/8 |
| Published lessons awaiting a concept mapping | — | **403** | 0 | 6 |
| Production items a student may be scored on | — | **0 / 6,270** | — | 3 |
| Events grounded (any approved claim) | 2 | **17** | ≥10 | 1/6 |
| Grounded claims | 457 | **2,525** | — | 1/6 |
| Curated source URLs answering 200 | 71 / 93 | **241 / 241** | all | 1 |
| Items clearing every machine gate | 66 (1 event) | **244** (10 events) | — | 2/6 |
| Practice exams assembled | 0 | **11** | ≥10 | 6 |
| Imported past-test items placed in an exam | — | **0** | 0 | 7 |
| Pilot video chapters QA-approved | 0 | 0 / 25 | all | 5 |
| Published pilot checkpoints a student can answer | — | **73 / 73** (was 32) | all | 8 |
| Published pilot checkpoints shipping their answer key | — | **0** (was 41) | 0 | 8 |
| Live-event lessons meeting the grounding bar | 0 / 410 | — | ≥80% | 6 |
| Imported items with usable figures | 0% | recovery built | ≥90% | 7 |
| Imported items gradeable | unmeasured | **83.2%** (4,755) | ≥90% | 7 |
| Imports running with an available answer key | 69 / 96 | **77 / 96** | 96 / 96 | 7 |
| Imports below 60% gradeable | unmeasured | **19** | 0 | 7 |

**Measured in production, 2026-08-02: not one of the 6,042 items is student-scoreable.** Every
one sits at `draft` or `machine_validated`; none has reached `published` or `calibrated`. This
is Phase 0 working exactly as specified rather than a defect — `can_start_new_attempt` refuses
the 150 published exams because their items carry no human acceptance — but it is the single
number that describes the platform's real position, and it is a review number, not an
engineering one. The placement diagnostic refuses every event for this reason, which is the
behaviour it was built to have.

**The one line that matters:** every blocker between the pilot and a finished course is now a
review decision. There is no remaining engineering task standing in front of it.

Restated after Phases 5 and 8 (2026-08-02): still true, and it survived two rounds of the same
failure mode. Both defects closed since — video chapters reporting no blocks, and 41 published
checkpoints unanswerable — were invisible to every gate because the gates and the fixtures were
written against content shaped the way the *first* generator wrote it. Neither was found by a
test; both were found by measuring the real published data. A gate that has never met the
content it guards is not evidence.
