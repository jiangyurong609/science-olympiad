# Honen Gap-Closure Plan — Science Olympiad Prep Compiler

> **Order and gates are decided in [`MASTER_PLAN.md`](MASTER_PLAN.md).** This document is the detailed spec; do not start a phase here without checking its position and prerequisites there.

**Status:** proposed · **Owner:** platform · **Created:** 2026-07-30

## Goal

Turn the latent closed-loop machinery already in the schema into the *governing*
pipeline for all student-facing content, and close the four real gaps against the
Honen-style compiler:

1. Live catalog was built by the weak single-shot generator (`scripts/build_courses.py`),
   not the rigorous in-app path (`app/services/model_generation.py`).
2. No **outline/blueprint approval gate** before generation (Honen's strongest idea).
3. Validation lacks an **independent solver** and **embedding-similarity** leakage check
   (`similarity_report.embedding_check == "not_configured"`).
4. No **item-pattern store** — past-question abstractions used to seed original items.

Every phase below ships with (a) automated tests and (b) a **real verification** step
that exercises the running app/DB (not just unit mocks). No phase is "done" until its
real-verification checklist passes on staging.

---

## Codex adversarial-review resolutions (2026-07-30)

An adversarial review flagged four issues (three high, one medium); all are now folded
into the phases and cross-referenced inline as **R1–R4**:

- **R1 — Phase 2 audit measured the wrong population.** The auditor is now parameterized
  by `--status` and `--generation-run`; Phase 2 audits the *newly generated*
  `machine_validated` rows (with a zero-unaudited-rows census + expected-count assertion),
  and a second audit certifies the `published` release after cutover. → Phases 0, 2, 6.
- **R2 — Coach authoring had no authz/tenant boundary.** Decided explicitly: coach plans
  are **org-scoped drafts** (`CoursePlan.organization_id`, all ops org-filtered, cross-org
  → 404); **global catalog publication stays content-staff only** (`require_content_staff`,
  which excludes coaches). Adversarial role + IDOR tests added. → Phase 3.
- **R3 — Rollout promoted no data and had no data rollback.** Added an image-independent
  `promote_content_release.py` plus a rehearsed **data** rollback distinct from Cloud Run
  revision rollback. → Phase 6. *(Superseded in scope by R-C3 below — the existing
  `ContentRelease` cannot back this without a schema/read-path sub-phase.)*
- **R4 — Documented status ladder was backwards.** Corrected to the implemented order
  `… sme_approved → published → calibrated`; note that practice vs competition readiness
  is already separated via `Exam.release_class`. Transition-table tests added. → Guiding
  principles, Phases 2/5/6.

## Second adversarial-review resolutions (2026-07-31 — consolidation focus)

A second review of Phase C + the consolidation/audit scripts flagged four highs
(**R-C1…R-C4**), all folded in:

- **R-C1 — Duplicate events silently dropped.** The planner grouped one event per
  `(name,division,season)`, overwriting the two real 2026 Division-B *Heredity* events.
  Fixed: group into lists, **block on any intra-season duplicate**, and **assert exactly one
  active event per (name,division)** post-apply. `--resolve-intra-season` archives the
  smaller sibling but refuses if it has published content (Heredity does → manual merge). → Phase C.
- **R-C2 — Retiring twins hid non-published content.** Deactivating a twin stranded its
  questions/lessons/concepts/gaps behind `Event.active`. Fixed: **explicit per-table
  disposition** (`merge`/`archive`), a printed `content_archived_totals`, an
  **`archived_superseded`** status that stays queryable, and **block-on-unclassified**
  event-dependent tables. The claim is corrected to "no *live/published* content lost." → Phase C.
- **R-C3 — Atomic content rollback isn't supported by the schema.** `ContentRelease` is
  course-scoped, no entity has a `release_id`, and reads don't resolve through a pointer.
  Added a **release-schema + read-path compatibility sub-phase** (catalog-release identity,
  immutable membership, atomic active pointer, release-aware reads, backfill, dual-read
  deploy order, concurrent-reader + rollback tests) that must land **before** the promotion
  job. → Phase 6.
- **R-C4 — DB backup leaked user PII/credentials.** The `.bak` (emails + password hashes +
  attempts/responses) wasn't ignored. Fixed: `.gitignore` now covers `*.db*`/`*.bak`/
  `*.sqlite*`; backups live **outside the repo tree**; never committed. → Phase C tasks.

## Third adversarial-review resolutions (2026-07-31 — consolidation hardening)

A third review confirmed **R-C3/R-C4 closed** and flagged four refinements of the
consolidation/audit *scripts* (**R-C5…R-C8**). Per "plan, not execution," these are folded in
as hard **pre-apply gates**, not patched ad hoc:

- **R-C5 — live-content guard was incomplete.** The retirement check looked only at published
  lessons/questions, so a duplicate with a published `Course`, `Exam`, or `PracticeSet` could
  be archived. Gate: **block archival if ANY student-visible row exists** on the twin —
  `Course.status=="published"`, `Exam.published`, published `PracticeSet`, plus lessons/
  questions. Fixtures per content type. → Phase C.
- **R-C6 — archiving still hid content at the product level.** Archived courses drop out of
  active-event/published-course discovery with no archive surface. Gate: **`--apply` is
  blocked until an authenticated archive listing/detail surface + canonical redirects exist
  and are tested**; archived courses/lessons/questions/exams must be reachable through
  supported app paths, not just DB queries. → Phase C.
- **R-C7 — the invariant allowed *zero* active events.** `_assert_invariant` rejected >1 but
  not 0, so archiving an active twin whose canonical was already inactive could empty a key.
  Gate: build the **expected normalized-key set** and require **exactly one** active canonical
  per key; reject (or deliberately reactivate) inactive canonical candidates; test
  inactive-canonical + partial/retry states. → Phase C.
- **R-C8 — the scorecard could overstate health.** It excluded only `retired_duplicate`/
  `withdrawn` (not `archived_superseded` or inactive-event courses), and dropped errored
  courses from the denominator. Gate: exclude `archived_superseded` + inactive-event courses
  by default, add a separate **archive audit mode**, **count audit errors as not-release-ready**
  using total selected as the denominator, and assert the population post-consolidation. → Phase Q.

---

## Integration with the existing admin/import portal

This plan **extends the existing Content Studio intake pipeline — it does not fork it.**
Surfaces we build on (confirmed present, not rebuilt):

- **Intake:** staff single + chunked uploads (`POST /api/content/intake/uploads[...]`),
  URL/YouTube-caption import (`.../imports`), parent share (`POST /api/parent/materials`).
  All land as `Source(approved=False, rights_status=quarantined)` + `SourceSnapshot` +
  `SourcePassage`, then a **review→approve** step (admin) flips rights + `approved`.
- **Rights:** reuse `RightsStatus` + `can_use_for_generation` / `can_fetch_full_text`.
  No new rights model.
- **Association & coverage:** reuse `EventSourceMap` (purpose/tier/reviewed) and the
  coverage scorecards (`/content/source-coverage`, `/content/courses/{id}/coverage`,
  `ContentGap`, `CourseSourceCoverage`).
- **Review/release:** reuse the lesson/question review queues, calibration queue, and
  release manager already wired into the content-staff UI.

Three integration facts that reshape the plan (previously wrong or unstated):

1. **Generation is decoupled from source selection.** Both generators query the *global*
   pool of approved, rights-cleared claims (optionally by event/concept); there is **no
   "pick these sources → generate" flow.** Phase 3's gate therefore adds **per-plan
   source scoping** (`CoursePlan` → an explicit set of approved `EventSourceMap`/`Source`
   rows) and constrains generation to that set. Net-new capability.
2. **Coaches have no authoring access today** (`require_content_staff` = `{admin, editor,
   sme, calibrator}`, excludes `coach`). The wizard ships **content-staff-first** (matches
   reality); the org-scoped *coach* authoring from R2 is an explicit later extension behind
   `require_exam_manager`, never a silent grant. Until then global publish stays
   content-staff/admin only.
3. **Powerful surfaces are API-only, no UI** (v5 crawler, `/questions/generate*`, claims
   pipeline, lesson-authoring "generate"). The wizard is largely **UI over endpoints that
   already exist**, plus the gate — smaller than greenfield.

---

## Guiding principles

- **Reversible.** Every content mutation writes new versioned rows (`LessonVersion`,
  `ExamItem` snapshots, `Question.status`) — never destructive in place. A DB snapshot
  is taken before any regeneration.
- **Measure first, then change.** Phase 0 establishes a defect baseline so we can prove
  improvement with numbers, not vibes.
- **Gate on evidence.** Content only advances through the *actual* implemented status
  ladder (`draft → machine_validated → editor_reviewed → sme_approved → published →
  calibrated`). Publication happens **from `sme_approved`** (`routes.py:3157→3188`);
  calibration happens **after** publication (`published → calibrated`,
  `routes.py:3216→3239`). Release readiness is already separated from practice
  visibility: `Exam.release_class == "competition_ready"` requires `calibrated`
  items, while practice exams accept `published` (`routes.py:3314`). We stop
  auto-publishing batch content and route everything through this ladder.
- **Verify in real.** Each phase runs against a live staging Cloud Run + Cloud SQL
  instance and, where user-facing, a Playwright browser check.

---

## Environments & test infrastructure

| Layer | Tool / location |
|---|---|
| Unit + integration tests | `pytest` (`tests/`), SQLite in-memory + Postgres testcontainer |
| API contract tests | `pytest` + FastAPI `TestClient` |
| Browser E2E | Playwright (headless Chromium) against staging URL |
| Staging | New Cloud Run service `soplat-web-staging` + Cloud SQL DB `soplat_staging` (clone of prod schema, sampled data) |
| Prod deploy | `scripts/deploy.sh` (unchanged) |
| LLM in tests | Recorded/stubbed provider for deterministic unit tests; a small **live-LLM smoke suite** (marked `@pytest.mark.live`) run only in real-verification steps |

**Pre-req task (P0.0):** stand up `soplat-web-staging` pointing at `soplat_staging`,
seeded from a prod snapshot. All real-verification steps target staging until Phase 6.

---

## Phase 0 — Baseline, safety net, golden set

**Objective:** know exactly how bad/good the current content is, and make regeneration safe.

### Tasks
- `scripts/audit_content_quality.py` — read-only, **parameterized** so the *same*
  auditor scores any population, not just the live one:
  - `--status` (e.g. `published`, `machine_validated`) and `--generation-run <id>` /
    `--catalog-version <v>` filters, so Phase 2 can audit exactly the rows it produced
    (see finding resolution R1). Default filter = `published` (the current live catalog).
  - re-run `validate_candidate()` retroactively; record pass/fail + reasons.
  - flag items whose `generation_provenance` marks them from `build_courses.py`
    (`catalog-2026-generated`) vs the rigorous path.
  - count: grounding coverage (has approved `claim_ids`?), missing verifier record,
    duplicate/near-duplicate clusters (lexical), exams with fewer than blueprint-required items.
  - **also emit population census**: total rows matched, and any rows in the target
    population that were *not* audited (must be zero) — prevents an empty/mis-scoped
    population from silently passing the gate.
  - emit `docs/history/content_audit_<label>_<date>.json` + a human summary.
- Golden regression set: hand-verify ~40 questions across 6 events (answers known-correct)
  → `tests/fixtures/golden_questions.json`. Used to detect regressions when we regenerate.
- DB snapshot procedure documented + scripted (`scripts/snapshot_db.sh`, Cloud SQL export to GCS).

### Tests
- Unit: `tests/test_audit_content_quality.py` — audit correctly classifies seeded
  good/bad/duplicate fixtures.

### Real verification ✅
- Run audit against a **prod read replica / snapshot**; produce the baseline report.
- Record the numbers we must beat: `% questions passing validate_candidate`,
  `% grounded`, `# near-dup clusters`, `# exams under blueprint`.
- **Exit criteria:** baseline report committed; staging stood up; snapshot restore tested once.
- Note: the *course-level* baseline (fleet scorecard over the whole catalog) is **Phase Q**;
  this phase's audit is the *item-level* half. Together they form the honest baseline.

---

## Phase Q — Catalog-wide course quality program (all courses, standing)

**Objective:** make course quality a **measured, prioritized, continuously-tracked** program
across the *whole catalog — existing courses included* — not a side effect of regenerating
new ones. This is the phase that answers "improve overall quality, not only the new ones."

**Build on what exists:** `app/services/course_quality.py::audit_course` is already a strong
machine-checkable rubric (unit/skill structure; lesson rhythm/duration/≥3 teaching
interactions/≥3 checks/transfer check/citations/publish + editor + SME review; question
volume/transfer/review/**calibration**; claim approval + retained passage; source
reconciliation/extraction/review/destination; content gaps; atomic release) returning
`release_ready` + blocker counts. Today it runs **one course at a time** via
`GET /content/courses/{id}/quality`. The gaps: no catalog rollup, no prioritization, no
trend, and it's **structural-only** (its own docstring says structural checks don't
substitute for correctness/pedagogy).

**Reality check:** most of the existing catalog was built by the single-shot path and will
**fail** these blockers (no editor/SME review, no calibration, thin claim/passage grounding).
So the program's job is to drive the *entire* catalog to pass this bar and stay there.

### Tasks
- **Fleet scorecard** `scripts/audit_catalog_quality.py` + `GET /content/quality/catalog`:
  run `audit_course` over **every live** course; return per-course `release_ready` + blocker
  counts, plus a catalog rollup (how many pass, worst offenders, blocker histogram).
- **Correct population + denominator (R-C8):** by default exclude `archived_superseded`,
  `retired_duplicate`, `withdrawn`, **and courses on inactive events**; provide a separate
  `--archive` audit mode. **Count audit errors as not-release-ready** and keep them in the
  percentage denominator (total selected), so an audit failure can never *raise* the headline
  pass rate. Assert the audited population after consolidation (no archived/inactive leak-in).
- **Composite quality score** per course = structural (`audit_course`) + item validity
  (Phase 1 solver/validator pass-rate) + grounding coverage + **media readiness (Phase M)** +
  calibration/student-outcome signal (Phase 5). One number **plus its components**, so
  "quality" is not only structural. Missing components degrade gracefully, not to zero.
- **Prioritized remediation backlog**: rank courses by `severity × usage/enrollment` so we
  fix the worst, most-used first. **This backlog drives Phase 2 regeneration order.**
- **Trend tracking**: persist each course's score per `ContentRelease`; flag any release that
  *lowers* a course's score (regression guard).
- **Content dashboard**: surface the fleet scorecard + backlog in the content-staff UI
  (extends the existing Source-Coverage / quality panels — not a new app).

### Tests
- Fleet audit aggregates per-course `audit_course` correctly; rollup counts match; a seeded
  failing course appears in the backlog with the right blocker codes.
- **Population/denominator (R-C8):** archived/inactive courses are excluded by default and
  only appear under `--archive`; a course that raises an audit error counts as
  **not-release-ready** and stays in the denominator (never inflates the pass rate); the
  post-consolidation population assertion catches any archived/inactive leak-in.
- Composite score combines components with documented weights; a missing component (e.g. no
  calibration yet) degrades gracefully.
- Trend: two releases of one course store two scores; a score drop is flagged as a regression.

### Real verification ✅
- Run the fleet scorecard against the **prod snapshot** and **publish the real number**: how
  many of the ~46 courses are `release_ready` today, and the top blocker codes. This is the
  honest catalog baseline the whole plan is judged against.
- After Phase 2, the fleet pass-rate must climb materially versus this baseline, and the
  backlog must shrink.
- **Exit criteria:** every course has a composite score + release-over-release trend; a ranked
  remediation backlog exists and drives regeneration; the catalog pass-rate is tracked over time.

---

## Phase C — Season consolidation (2026 + 2027 → one season-agnostic catalog)

**Objective:** collapse the two parallel catalogs (2026 = 52 published courses / 5,850 Qs /
410 lessons of real content; 2027 = 50 `review_required` near-empty shells from the material
sheet) into **one canonical event per (name, division)**, with season as a content tag rather
than a duplicate event. **Decided model:** season-agnostic single catalog; the 17 events
rotated out of 2027 are kept as **prior-season practice**, not deleted.

**Hard constraint:** `uq_course_event` — **one course per event** (`entities.py:159`). So we
cannot repoint a second course onto an event; canonical selection must yield ≤1 course/event.

**Honest scope (corrected after adversarial review):** this preserves **all live/published
content** on canonical events, and **explicitly archives the redundant 2027 import stubs** —
they stay in the DB, are queryable via `season_status="archived_superseded"`, and are
recoverable, but leave the live catalog. This is *not* a "zero content loss" claim; it is
"no live/published content lost; redundant stubs explicitly archived."

**Shape (67 canonical events):**
- **34 recurring (both seasons):** canonical = the **2026 event** (it holds the course +
  content). Carry current-season metadata from its 2027 twin (`official_url`, `category`,
  `season_status="current"`) + merge the 2027 twin's `EventSourceMap` rows (dedup on
  `event_id,source,purpose,source_universe_version`). **Archive** the 2027 twin + its
  subordinate content (course/lessons/questions/concepts) — never silently deactivate.
- **16 only-2027:** keep as `current`; content to be built (Phase 2).
- **17 only-2026:** keep; set `season_status="prior_season_practice"`.

**Safeguards (from the review — all implemented in `scripts/consolidate_seasons.py`):**
- **Intra-season duplicate detection (R-C1):** events are grouped into *lists* per
  `(name,division,season)`; any key with >1 event is a **blocking conflict** (e.g. two 2026
  Division-B *Heredity* events, id 5 `heredity` + id 10 `heredity-b`). `--resolve-intra-season`
  archives the smaller into the richer — but **refuses if it carries published content**
  (Heredity id 5 does → must be merged by hand). Apply is blocked while any conflict stands.
- **Dependent-row disposition (R-C2):** every event-dependent content table is classified
  (`merge` vs `archive`); the report prints `content_archived_totals` so what leaves the live
  catalog is **explicit, not silent**. Apply **blocks on any unclassified** non-null
  `event_id` table (schema growth can't drop rows). Archived content is queryable/recoverable.
- **Complete live-content guard (R-C5):** refuse to archive a twin with **any** student-visible
  row — published `Course`/`Exam`/`PracticeSet` **and** published lessons/questions — not just
  lessons/questions. (The Heredity id-5 duplicate trips this today.)
- **Archive reachability is a release gate (R-C6):** `--apply` stays **blocked until an
  authenticated archive listing/detail surface + canonical redirects** are built and tested.
  Archiving isn't "done" until archived courses/lessons/questions/exams are reachable through
  supported app paths — DB-queryable is not enough.
- **Exactly-one-active invariant (R-C7):** build the expected normalized-key set and assert
  **each key has exactly one active canonical event** — reject the count being **0** (an
  already-inactive canonical whose active twin gets archived) as well as >1. Reject or
  deliberately reactivate inactive canonical candidates; test inactive-canonical + partial/
  retry states.

### Tasks
- `scripts/consolidate_seasons.py` — dry-run default; `--apply` in one transaction, requires
  `--i-took-a-backup`, refuses on any conflict, asserts the invariant before commit.
- **Archive surface (blocks `--apply`, R-C6):** an authenticated archive listing + detail API
  and UI for `archived_superseded` (and `prior_season_practice`) events, plus **canonical
  redirects** from retired twin slugs → canonical, wired into catalog discovery
  (`/events`, course listing). `--apply` is not permitted until this exists and is tested.
- Backups live **outside the repo tree** (contain user emails/hashes + attempts); `.gitignore`
  covers `*.db*`/`*.bak` (R-C4).

### Tests
- Intra-season dup → blocking conflict; `--resolve-intra-season` still refuses published dups.
- **Complete live-content guard (R-C5):** fixtures per type — a twin with a published
  `Course`, a published `Exam`, or a published `PracticeSet` (not just lessons/questions) each
  **block** archival.
- Recurring merge yields exactly one active course per canonical event; source maps deduped.
- `content_archived_totals` matches the rows actually archived; an **unclassified
  event-dependent table with rows → apply blocks**.
- **Invariant (R-C7):** exactly one active event per key — a case where the canonical is
  already inactive must **fail** (count 0), not pass; test partial/retry states.
- **Archive reachability (R-C6):** archived course/lesson/question/exam is reachable via the
  archive API/UI and old slugs redirect to canonical.

### Real verification ✅
- Dry-run on the real DB; **review conflicts + `content_archived_totals`** before `--apply`.
- Resolve the Heredity duplicate (merge id 5 → id 10) so the catalog can reach zero conflicts.
- **Build + test the archive surface first**; only then apply on a DB copy.
- After apply on a DB copy: live content conserved on canonical events; archived content
  **reachable through the app** (not just DB); invariant passes with exactly one active event
  per key; **re-run the Phase Q scorecard** (active-catalog filter) on the consolidated catalog.
- **Exit criteria:** exactly one active event per (name,division); no live/published content
  lost; archived content reachable in-app + redirects work; invariant asserted; Phase Q
  baseline re-taken on the active catalog.

---

## Phase 1 — Harden validation (independent solver + embedding similarity)

**Objective:** make the rigorous generator actually rigorous before we run it at scale.

### Tasks
- **Independent solver stage** in `model_generation.py`: after the item writer, a
  separate LLM call receives *only stem + choices* (no proposed answer) and must
  solve it. Reject (keep `DRAFT`) when: solver disagrees, declares ambiguity, or
  says info-insufficient. Persist solver transcript into `validation_report`.
- **Embedding similarity**: implement the `embedding_check` currently stubbed
  `not_configured`. Compute embeddings via the configured provider (fallback: local
  MiniLM). Store cosine max-similarity vs (a) source passages and (b) existing item
  bank in `similarity_report`. Thresholds: ≥0.92 block, 0.80–0.92 warn (mirrors
  existing lexical gate).
- Programmatic numeric validator hook for calculation items (SymPy) — recompute,
  check units/sig-figs, answer uniqueness. (Scoped to numeric question types.)

### Tests
- Unit: solver-disagreement → item stays `DRAFT`; ambiguous stem rejected;
  embedding block at ≥0.92; numeric validator catches unit error and non-unique answer.
- **Asset integrity:** an item whose `assets` reference a missing or non-rights-approved
  image is blocked from `MACHINE_VALIDATED` (or flagged `figure_missing`), so validation
  covers media, not only text. (Ties to Phase M.)
- Integration: generate a batch containing 3 deliberately-broken seeds
  (wrong key, near-duplicate, ambiguous) → assert none reach `MACHINE_VALIDATED`.

### Real verification ✅
- `@pytest.mark.live` run on staging against a real event using the live LLM:
  generate 20 items, confirm the solver+similarity gates fire and the pass-rate/rejection
  reasons are sane (manually inspect 5).
- **Exit criteria:** live batch shows solver + embedding checks recorded on every item;
  seeded-bad items rejected 3/3.

---

## Phase 2 — Regenerate the live catalog through the rigorous path

**Objective:** replace single-shot content with verified content, provably better than baseline.
**Driven by the Phase Q backlog** — worst/most-used courses first — and covering **every**
course, not just visually-rich or new ones. Each regenerated course must move toward
`audit_course` `release_ready`, not merely pass item validation.

### Tasks
- `scripts/regenerate_catalog.py`: for each event, run the `model_generation.py`
  pipeline (writer → validator → solver → verifier → grounding/rights/similarity),
  writing **new** `Question`/`LessonVersion` rows tagged with a single immutable
  **`generation_run` id** (recorded in `generation_provenance`). Old rows are
  *superseded*, not deleted.
- Stop auto-publishing: batch output lands at `machine_validated`, then flows through
  the existing review/calibration queues (`sme_approved → published`). Only reviewed
  items publish.
- **Audit the rows we actually produced (R1).** The Phase 2 quality gate runs
  `audit_content_quality.py --status machine_validated --generation-run <id>` over the
  *newly generated* rows — not the old `published` catalog — and asserts:
  (a) generated count == expected count per event blueprint, (b) zero unaudited rows in
  the run, (c) defect thresholds below (see real verification). A **second** audit runs
  `--status published` *after* the atomic cutover (Phase 6) to certify the released set.
- Preserve visual content (see **Phase M**): re-run `lesson_media.py` /
  `build_visual_content.py` / `enrich_flagship_visuals.py` after regeneration so
  `image_gallery` blocks, image-ID items, and video blocks persist; assert no course loses
  media vs its prior version.
- Backfill `ExamItem` snapshots; ensure every exam meets its `AssessmentBlueprint`.

### Tests
- Integration: regeneration is idempotent (second run creates no dupes); every published
  exam satisfies blueprint counts; no orphaned `ExamItem`/`Question` rows; golden set
  answers unchanged where content is stable.
- Migration test: superseded rows retained + queryable (audit trail intact).
- **Status transition-table test (R4):** assert the *actual* implemented ladder — publish
  only from `sme_approved`; calibrate only from `published`; and that
  `competition_ready` exams reject non-`calibrated` items while practice exams accept
  `published`. Cover every forbidden transition (e.g. publish from `machine_validated`
  must 409). This locks the plan's assumptions to code behavior.

### Real verification ✅
- On staging, regenerate 5 representative events (1 visual-ID, 1 lab, 1 build, 1 math-heavy,
  1 reading-heavy). Run the audit **scoped to the new `generation_run`**
  (`--status machine_validated --generation-run <id>`) → the *generated* rows must beat
  baseline (target: ≥90% pass `validate_candidate`, 100% grounded, 0 blocking near-dups),
  and the census must show **0 unaudited rows** and generated count == blueprint expectation.
- Playwright: open each regenerated course + take its exam on staging; assert images
  render, checkpoints work, submit → review flow returns a score.
- **Exit criteria:** audit numbers beat baseline on all 5; browser flow green; sign-off to
  roll remaining events.

---

## Phase 3 — Outline/blueprint approval gate + authoring flow (content-staff first, coach later)

**Objective:** add Honen's "approve the plan before generating" — the one idea we lack entirely.

> **Ships content-staff-first; coach authoring is a later, explicit extension (R2 +
> portal integration).** Today `Course` is **global per event** (no `organization_id`)
> and `require_content_staff` = `{admin, editor, sme, calibrator}` — **coaches cannot
> author or publish** (`routes.py:143`). So:
> - **Milestone 3a (now):** the authoring wizard is a **content-staff** tool layered on
>   Content Studio. It adds the missing **plan → approve → generate** gate over endpoints
>   that already exist (`/questions/generate-model`, lesson authoring, review/release).
>   No new tenant surface, no coach grant.
> - **Milestone 3b (later, opt-in):** org-scoped **coach** authoring behind
>   `require_exam_manager`. Coach plans get `organization_id` + `created_by_user_id`;
>   every read/write/generate is org-filtered (cross-org → **404**, not 403, to avoid ID
>   probing); coach output is an **org-scoped draft** and **global publish stays
>   content-staff only**. (Org-private courses need `Course.organization_id` + read
>   filters — its own migration, called out as such.)
> - **Source scoping is the real new capability**, needed even for 3a: generation is
>   decoupled from source selection today, so the plan must carry an explicit selected
>   source set and constrain generation to it.

### Tasks (Milestone 3a — content staff)
- Data model: `CoursePlan` (new) with `event_id`, `division`, `season`, `created_by_user_id`,
  `status` (`draft → approved → generating → generated`), `blueprint_json`,
  `coverage_report_json`, and **`scoped_source_ids`** (the selected approved
  `EventSourceMap`/`Source` set). Nullable `organization_id` reserved for 3b. + migration.
- API (all `require_content_staff` in 3a):
  - `POST /authoring/plans` — from event + division + season + **a chosen set of approved,
    rights-cleared sources**, the planning agent proposes units → topics → objectives →
    activity plan + an `AssessmentBlueprint` draft + a **coverage/gap report** (from
    `ContentGap`, `CourseSourceCoverage`). Rejects sources failing `can_use_for_generation`.
  - `GET /authoring/plans/{id}` — review payload: topics, rule coverage, prereq gaps, est.
    study time, question mix, unsupported areas needing more sources.
  - `POST /authoring/plans/{id}/approve` — **the gate**: generation refuses to run until an
    approved plan exists.
  - `POST /authoring/plans/{id}/generate` — **constrains generation to `scoped_source_ids`**
    (not the global pool), fans out per approved unit into draft lessons/questions that then
    flow through the existing review/calibration/release ladder.
- Content-staff UI (`app/static/app.js` `#content` mode, extending Content Studio, not a new
  app): wizard — `select approved sources → review knowledge map → approve outline+blueprint
  → generate (draft) → existing review queues → release manager publish`.
- Targeted regeneration: editing one unit regenerates only that unit's nodes.

### Tasks (Milestone 3b — coach, opt-in extension)
- Add `organization_id` + `created_by_user_id` enforcement to every plan op; open
  `POST /authoring/plans*` to `require_exam_manager`; coach generate → org-scoped draft only;
  global publish remains `require_content_staff`.

### Tests
- **3a — gate + source scoping:** generation blocked without approved plan (409); approval
  unblocks; plan lifecycle transitions; gap report lists genuinely-uncovered skills;
  **generation is constrained to `scoped_source_ids`** (an approved source *not* in the
  plan's set contributes no claims; a scoped source failing `can_use_for_generation` is
  rejected at plan creation).
- UI E2E (3a): wizard walks all steps in `#content` mode; approve gate visibly blocks
  "generate" until approved.
- **3b — adversarial authorization (R2), when coach authoring lands:**
  - coach **cannot** publish to the global catalog (403).
  - **cross-org IDOR**: coach A gets 404 (not 403) reading/approving/generating coach B's
    plan by numeric ID.
  - a student role is rejected from all authoring endpoints.
  - coach generation writes only org-scoped draft courses, never the global published catalog.

### Real verification ✅
- **3a:** on staging, a content-staff account selects a scoped source set, gets a plan,
  approves, generates drafts, and publishes via the release manager; the course appears to a
  student account. Confirm an approved-but-unscoped source did **not** leak into generation.
- **3b (if built):** cross-org IDOR check with two coach accounts (expect 404); coach cannot
  publish globally.
- **Exit criteria:** cannot generate without approval (verified in browser); generation
  honors source scoping; staff-published course is student-visible; (3b) coach cannot publish
  globally and cross-org access returns 404.

---

## Phase M — Multimedia as first-class content (runs alongside Phases 2–4)

**Objective:** courses carry images/diagrams/video (and optionally audio) governed by the
*same* rights + review gates as text — not a parallel, unjoined system.

**Current reality (recon):** images = curated Wikimedia stills → `/static/media` +
`manifest.json` → `Question.assets` JSON + `image_gallery` blocks; video = YouTube-embed
only (captions ingested via `video_transcripts.py`, never hosted) → `type:"video"` blocks +
transcript-grounded lessons/questions (editor-gated); **audio = none**; upload extraction is
**text-only** (no figures pulled from PDFs — hence `flag_missing_figures.py`); LLM generation
is **text-only** (Vision used only for OCR); and `SpecimenAsset` (rights bookkeeping) is
**disconnected** from the served images (the manifest) — two unjoined systems.

### Tasks
- **Join media rights to delivery.** Make served media reference `SpecimenAsset` (asset id /
  FK) so `Question.assets` + gallery blocks inherit `rights_status`/`license`/`attribution`
  from the governed table instead of a free-floating `manifest.json`. One source of truth for
  media rights; add an asset resolver keyed by asset id.
- **Preserve media on regeneration (ties to Phase 2).** `regenerate_catalog.py` must re-run
  `lesson_media.py` / `build_visual_content.py` / `enrich_flagship_visuals.py` so galleries,
  `image_gallery` blocks, image-ID questions, and video blocks survive; assert no course loses
  media versus its prior version.
- **Figure extraction from uploads (optional, gated).** Extend
  `content_ingestion._extract` to crop figures from uploaded PDFs into `ExtractionAsset`/
  assets (today text-only). Extracted figures inherit the upload's reviewed rights. If
  deferred, keep the `figure_missing` scorer-skip behavior explicit.
- **Data-drive the media library.** Replace the hardcoded specimen dicts in
  `fetch_specimen_images.py` with `EventTaxonScope`/`Taxon`-driven fetch so new events get
  media without code edits.
- **Audio (optional / Honen parity).** If narration/podcast is wanted, add a TTS step that
  reads only *published, grounded* lesson text into a new `audio` block; else explicitly out
  of scope.

### Tests
- Media rights: a question/gallery referencing a non-approved asset is blocked from publish;
  `figure_missing` still skips scoring.
- Regeneration preserves media: golden courses keep gallery/figure/video counts ≥ prior.
- Figure extraction (if built): a PDF with N figures yields N `ExtractionAsset` images with
  inherited rights.

### Real verification ✅
- On staging, regenerate the 5 events and confirm via Playwright that galleries, question
  figures, and video embeds render (extends the existing `/static/media` image checks) — no
  broken media; every caption shows license + attribution.
- Rights spot-check: a deliberately non-free asset cannot reach a published course.
- **Exit criteria:** every regenerated visual/video event renders its media; media rights
  enforced through `SpecimenAsset`; 0 broken/hotlinked external images.

---

## Phase V — Generated video classes (Remotion + Deepgram)

**Objective:** turn a *published, grounded* text lesson into a narrated video "class" —
programmatically, rights-safe, no hallucinated media or facts.

**Current reality (recon + `../dreamvibe`):** the `DEEPGRAM` key is in `.env` but **unused**;
there is **no Remotion project in this repo**. `../dreamvibe` has a reusable Remotion render
worker (`packages/vibe-remotion/scripts/render-worker.mjs`) we integrate with — **we do not
build Remotion from scratch.** The artifact store already supports a **GCS backend**. Existing
"video" is YouTube-embed only.

**Worker contract (extracted from `../dreamvibe` — this is V.0, mostly resolved):**
- Cloud Run **HTTP service**, port 9120, image from `packages/vibe-remotion/Dockerfile.render-worker`
  (bundled Chromium + ffmpeg; env `VIBE_REMOTION_BROWSER=""`, `VIBE_RENDER_CONCURRENCY`,
  `VIBE_RENDER_TIMEOUT_MS≈900000`, `VIBE_RENDER_STUB=1` for a no-Chromium test placeholder).
  **NB:** dreamvibe's `cloud-run-video-worker.yaml` is a *different* (ffmpeg) worker — ignore it.
- **Trigger:** `POST {WORKER_URL}/render/edit-spec`, body `{"spec": <EditSpec v0>, "uploadUrl":
  "<optional v4 signed GCS PUT URL>"}`. **Synchronous/blocking** (~16 min); no polling/callback.
- **Auth:** OIDC **ID token, audience = worker URL** (`Authorization: Bearer`); worker deployed
  `--no-allow-unauthenticated`, caller SA needs `roles/run.invoker`.
- **Input = EditSpec v0** (`packages/vibe-remotion/src/editspec.ts`, mirrored by
  `edit_spec.py::validate_edit_spec`): `{version:0, format:{aspect,width,height,fps},
  clips:[≥1], overlays?, captions?, audio?, watermark?}`. For a *lesson* we use
  `clips[].sourceKind:"image"` (specimen stills) + `overlays[]` (text) +
  `captions.segments[].words[]` (**word-level timing = Deepgram output**) +
  `audio.voiceover[]` (narration mp3). Richer animated scenes can later use
  `sourceKind:"component"` (TSX via `/render/component`, base64 assets, no egress).
- **Assets must be HTTPS URLs the worker can GET (signed GCS)** — worker has no filesystem.
  This **depends on Phase M moving media to GCS**.
- **Output:** with `uploadUrl` the worker PUTs the MP4 there and returns `{"ok":true,"bytes":N}`.

> **Remaining V.0 unknown:** worker B has **no committed knative YAML** (dreamvibe deploys it
> by hand). Confirm whether it's already running in `video-agent-493605` (capture its URL +
> invoker SA), else deploy our own from `Dockerfile.render-worker` +
> `cloudbuild.render-worker.yaml`. Target ~8 vCPU / 16 GiB per the worker's code comments.

**Deepgram role:** Aura **TTS** for narration + **word-level timestamps** for caption sync.
(If a different TTS voice is preferred, Deepgram instead runs forced-alignment ASR on that
audio to recover timings.)

**Production discipline:** a good video lesson needs a clear **outline → storyboard →
aligned narration** *before* any voice or render. Visuals and narration are authored
together so each spoken beat maps to exactly what's on screen; iteration happens on cheap
text/storyboard, and an **approval gate precedes the expensive render** (same "approve the
plan before you generate" ethos as Phase 3). Pipeline — every stage sourced only from
already-published, rights-cleared content:

1. **Outline** — from a `published` `LessonVersion`, derive the teaching arc: ordered
   sections tied to the lesson's concepts/objectives (hook → concept → worked example →
   check → recap). Reuses the lesson's structure; adds no new facts.
2. **Storyboard** — expand the outline into ordered **scenes**, each with: the on-screen
   plan (which block/`SpecimenAsset` image/diagram/text, key labels, transitions), an
   intended duration, and the **beat of narration that matches that visual**. Narration and
   visuals are authored *together*, not narration bolted onto slides. Each narration beat
   **maps to an approved lesson claim/citation** (grounded like the tutor); imagery resolves
   only to approved `SpecimenAsset`.
3. **Storyboard approval gate** — a reviewer (content staff) approves the storyboard +
   narration script. **No TTS or render runs until approved.** Cheap to revise here;
   expensive after render. `VideoStoryboard` status `draft → approved`.
4. **Voice (Deepgram Aura)** — synthesize narration mp3 *per approved scene*; capture
   word-level timings. Upload mp3 to GCS; it becomes an `audio.voiceover[]` source.
5. **Compose (EditSpec v0)** — build the EditSpec from the **approved storyboard**: one
   `image` clip per scene (specimen still via signed GCS URL), text `overlays[]` for
   on-screen labels, `captions.segments[].words[]` populated **directly from the Deepgram
   word timings**, and `audio.voiceover[]` for narration. Clip durations reconcile to the
   narration length. Validate with `validate_edit_spec` before sending.
6. **Render (dreamvibe worker)** — `POST /render/edit-spec` with `{spec, uploadUrl}` and an
   OIDC token (audience = worker URL); the worker renders and PUTs the MP4 to our signed GCS
   object. Blocking (~16 min) → runs inside the background job, never a request. No render
   infra in this repo.
7. **Post-render review (QA gate)** — a reviewer *watches the rendered MP4* and either
   approves it or leaves **scene/timestamp-anchored feedback** (wrong image, narration
   error, pacing, caption drift, audio glitch). Not student-visible until approved — a
   render passing the storyboard gate can still be wrong, so a second gate on the *actual
   video* is required.
8. **Publish** — a new hosted `video_lesson` block + player; the video **inherits the
   lesson's review/rights state**; a `VideoRender` row records provenance (source lesson
   version, storyboard id, script hash, audio key, video key, asset ids, worker job id).

**Review → feedback → regeneration loop** (mirrors the rest of the plan's improve stage):
- **Reviewer feedback** at step 7 attaches to the `VideoStoryboard`/scene; requesting changes
  sends it back to storyboard edit — **cheap text/storyboard edit, then re-render** — rather
  than hand-fixing the MP4.
- **Regeneration is versioned, never destructive.** Editing the storyboard mints a new
  `VideoRender` version (prior retained/superseded, like Question/Lesson versions). Where the
  worker supports it, **only changed scenes re-render** (keyed by scene content hash);
  otherwise a full re-render. Idempotent by storyboard id + content hash.
- **Student feedback once live** reuses the existing improve loop: students flag a video via
  `StudentContentFeedback` / a `ContentChallenge`-style path (timestamp-anchored); triage can
  unpublish + queue a regeneration. Auto-trigger on a bad-signal threshold is possible but
  stays human-gated (consistent with R1/R2 discipline).

### Tasks
- **V.0 finalize:** confirm/obtain the worker URL + invoker SA in `video-agent-493605` (or
  deploy from dreamvibe's `Dockerfile.render-worker`); grant our runtime SA `roles/run.invoker`;
  set `VIBE_RENDER_WORKER_URL`. Capture a known-good EditSpec as a test fixture; smoke it with
  `VIBE_RENDER_STUB=1`.
- `app/services/video_worker.py` — thin **adapter**: POST `/render/edit-spec` with `{spec,
  uploadUrl}`, mint the **OIDC ID token** (audience = worker URL), handle the long blocking
  call + timeouts. No Remotion code in this repo.
- `app/services/edit_spec_builder.py` — storyboard → **EditSpec v0** (image clips + overlays
  + `captions.segments[].words[]` from Deepgram + `audio.voiceover[]`); validate before send
  (port/mirror `edit_spec.py::validate_edit_spec`). Mint v4 signed GCS GET URLs for every
  asset and a signed PUT `uploadUrl` for the output.
- `app/services/video_storyboard.py` — outline + storyboard authoring: turn a published
  lesson into ordered scenes (visual plan + aligned narration beat + duration), each beat
  grounded to a lesson claim and each image to an approved `SpecimenAsset`.
- API + UI for the **storyboard approval gate** (content staff): review/edit/approve the
  storyboard & narration before render; render endpoints refuse a non-`approved` storyboard.
- API + UI for the **post-render QA gate**: a review workspace to watch the MP4, approve, or
  leave scene/timestamp-anchored feedback; video stays non-student-visible until approved.
- **Regeneration**: edit-storyboard → re-render mints a new `VideoRender` version (prior
  superseded, not deleted); changed-scene-only re-render if the worker supports it.
- **Student feedback path** for published videos (timestamp-anchored) reusing
  `StudentContentFeedback` / `ContentChallenge`; triage can unpublish + queue regeneration.
- `app/services/tts_deepgram.py` — Aura synthesis + word timings; reads the `DEEPGRAM` key
  via a new `deepgram_api_key` setting in `app/core/config.py`.
- Config: ensure `artifact_store_backend=gcs` + bucket wired for the shared render output.
- Data: `VideoStoryboard` (lesson_version_id, scenes JSON, narration, status, approver) +
  `VideoRender` table + a `video_lesson` block type and player in `app.js`.
- Worker: `render_video_lesson` `BackgroundJob` (approved storyboard → TTS → submit to
  worker → poll → attach block), idempotent by storyboard id + content hash.
- Rights/grounding gate: narration uses only the published lesson's claims; imagery only from
  approved `SpecimenAsset`; no external footage; captions from the synthesized audio.

### Tests
- **Storyboard grounding + gate:** every narration beat maps to a lesson claim/citation and
  every scene image to an approved `SpecimenAsset` (un-grounded beat or non-approved image →
  rejected); **render refuses a non-`approved` storyboard** (409); scene durations are
  present and ordered.
- Unit: Deepgram client parses word timings; scene durations reconcile to actual narration
  length; `VideoStoryboard` + `VideoRender` state machines.
- Integration (no real render): a lesson produces an **EditSpec that passes
  `validate_edit_spec`** — ≥1 image clip, asset URLs resolve to approved GCS assets,
  `captions.words` align to the Deepgram timings, `audio.voiceover` present — asserted without
  a real render.
- Adapter: `video_worker` handles success (`{ok,bytes}`), 4xx/5xx text errors, and timeout
  (mocked worker); OIDC token minted with the correct audience; `VideoRender` transitions
  accordingly. A `VIBE_RENDER_STUB=1` smoke returns a placeholder MP4 end-to-end.
- **Review/feedback/regeneration:** a rendered video stays non-student-visible until QA
  approval; scene-anchored feedback → storyboard edit → re-render mints a **new** version
  with the prior retained; changed-scene-only re-render touches only edited scenes; a
  student `ContentChallenge` on a live video can unpublish it and queue regeneration.
- Render smoke (`@pytest.mark.live`): submit one short lesson to the **real worker**; assert
  the produced MP4 in GCS is valid via `ffprobe` (video+audio streams, duration in tolerance).

### Real verification ✅
- On staging, take one real lesson through the full chain: **generate storyboard → review &
  approve it → render** to MP4 → GCS → attach the `video_lesson` block. Playwright confirms
  the player loads/plays, **narration matches the on-screen visual per scene**, captions
  show, and the media caption carries license + attribution.
- Gate check: attempting to render before storyboard approval is rejected.
- **Full review loop on staging:** leave scene-anchored feedback on a rendered video →
  edit the storyboard → re-render → confirm a **new version** supersedes the old, the fix is
  visible, and the pre-fix video is retained/rolled-back-able. Then approve at QA and confirm
  it becomes student-visible only after approval.
- Rights spot-check: a lesson referencing a non-approved image cannot produce a video using it.
- Record cost + wall-clock per render to size throughput.
- **Exit criteria:** one grounded lesson becomes a playable, caption-synced MP4 whose
  narration and visuals are aligned scene-by-scene, served from GCS, rights-clean, with
  `VideoStoryboard` approval + `VideoRender` provenance recorded; and a **review → feedback
  → regenerate** cycle produces a corrected, versioned re-render with the prior retained.

---

## Phase 4 — Item-pattern store (past questions → original items)

**Objective:** generate from abstractions, not paraphrases; prove originality.

### Tasks
- New table `ItemPattern` (concepts[], skills[], question_form, reasoning_steps,
  distractor_patterns[], visual_dependency, est_difficulty, source provenance) + migration.
- `scripts/extract_item_patterns.py`: from *rights-cleared* items only, derive patterns
  (no verbatim stems stored — abstraction only).
- Generation-from-pattern mode in `model_generation.py`: instantiate new values/context
  from a pattern, then run the full validation gate **including leakage check vs the
  originating corpus** (embedding + lexical). Reject items too close to any source item.

### Tests
- Unit: pattern extraction produces no verbatim source text; generation-from-pattern
  yields items that pass leakage (<0.80) or are rejected; visual_dependency respected.
- Integration: generate N from patterns; 0 exceed similarity block threshold.

### Real verification ✅
- On staging, extract patterns from a cleared set, generate 15 items, manually confirm
  5 are conceptually-equivalent-but-original; run leakage report → all under threshold.
- **Exit criteria:** originality report clean; no verbatim reuse detectable.

---

## Phase 5 — Feedback-loop tightening (secondary, high-leverage)

**Objective:** make the "improve" stage partly automatic.

### Tasks
- Auto-write calibration facility → `Question.difficulty` once an item passes the
  `CALIBRATION_THRESHOLDS` gate (≥30 students, etc.), with an audit-logged change.
- (Optional, if time) normalize `Concept.prerequisites` JSON into an edge table for
  real graph queries; keep JSON as denormalized cache.
- (Optional) replace fixed 3/14-day SRS bumps with a simple half-life model driven by
  `MasteryState`.
- **Feed outcomes into the Phase Q composite score + trend** so the fleet scorecard reflects
  real student performance, and a regressive release is flagged automatically.

### Tests
- Unit: difficulty write-back only fires past threshold; audit row created; below-threshold
  items untouched. Prereq edge table stays consistent with JSON cache.

### Real verification ✅
- On staging, simulate ≥30 scored exposures for an item (seeded attempts) → confirm
  difficulty updates and an `AuditLog` entry is written.
- **Exit criteria:** difficulty reflects real response data for calibrated items.

---

## Phase 6 — Full end-to-end verification, then production rollout

**Objective:** prove the entire closed loop works on real infrastructure, then ship.

### Tasks
- One comprehensive Playwright E2E on staging exercising the **whole loop**:
  1. Content staff (or coach, if 3b built) scopes sources + approves plan + generates +
     publishes a course, with its images/video rendering (Phase 3 + Phase M).
  2. Student takes a diagnostic/mock exam.
  3. Student answers one question wrong → `RemediationCase` opens.
  4. Student completes remediation → near-transfer → delayed-review → `MasteryState` updates.
  5. Tutor answers a grounded question (citations render).
  6. Student files a `ContentChallenge` → coach triages/resolves → `ScoreCorrection` rescores.
  7. Calibration accrues → difficulty write-back (Phase 5).
- Regression: full `pytest` suite + golden set + Phase 0 audit re-run over all
  regenerated events (defect rate beats baseline everywhere).

- **Schema + read-path compatibility FIRST (R3 — the existing model can't do this).**
  Adversarial review is correct: `ContentRelease` is **course-scoped**, no content entity
  carries a `release_id`, and student reads do **not** resolve through an active pointer. A
  promotion script alone therefore *cannot* give an atomic cutover or rollback — mixed
  old/new content would be visible during deploy/recovery. So Phase 6 gets an explicit
  **release-schema sub-phase before any promotion job**:
  - **Catalog-release identity** — a release that spans the whole catalog (or a versioned set
    of courses), not one course. New table or a catalog-scoped `ContentRelease` variant.
  - **Immutable release membership** — add `release_id` (or a membership table) to every
    promoted entity: `Question`, `LessonVersion`, `ExamItem`, `AssessmentBlueprint`, media
    assets, and difficulty write-backs. Membership is write-once per release.
  - **Atomic active-release storage** — a single row holding the active catalog-release id;
    the cutover is one committed update of that row.
  - **Release-aware read paths** — student-facing queries (`/events`, course/lesson/exam
    reads) resolve content **through the active release**, so a reader sees only one complete
    release. This is app-code change, not just data.
  - **Backfill** — enroll all current content into a genesis release so existing reads keep
    working (dual-read: fall back to "latest published" until membership is universal).
  - **Deployment order** — ship release-aware reads (dual-read) *before* the first pointer
    switch; retire the fallback only once membership is complete.
  - **Integration tests** — concurrent readers see only complete *old* or *new* content
    (never a mix) across a cutover; rollback restores the full prior experience.
  Only after this sub-phase does the promotion job below become implementable.
- **Content promotion job.** `scripts/deploy.sh` ships a Cloud Run *image* only; it does
  **not** move regenerated DB rows to prod, and a Cloud Run revision rollback cannot undo
  migrations, publication-state, exam rewiring, or difficulty write-backs. The dedicated,
  image-independent job `scripts/promote_content_release.py`:
  - **Immutable release id.** Bind every regenerated row to one catalog-release (per the
    schema sub-phase above). Student reads resolve through the *active* release, so
    promotion = an **atomic active-release switch**, not row surgery.
  - **Dry-run manifest.** `--dry-run` emits a manifest: per-event row counts, content
    hashes, and a diff vs the currently-active release. No writes.
  - **Reconciliation.** On apply, verify prod row counts + per-row content hashes match
    the manifest before flipping the pointer; abort on mismatch.
  - **Idempotent + resumable.** Re-running with the same release id is a no-op; a job
    interrupted mid-copy resumes without duplicating rows (keyed by release id + row key).
  - **Transactional cutover.** The pointer flip is a single committed transaction.
  - **Media travels with the release (Phase M).** Display media today are local
    `/static/media` files baked into the container image, so a DB-only promotion would
    leave images stale/missing. The release manifest must include media (path + content
    hash); newly-fetched/uploaded media move to **object storage (GCS)** and are promoted
    and rolled back *together with* the rows. Otherwise a data rollback desyncs images.
  - **Data rollback.** `promote_content_release.py --rollback --to <prior_release_id>`
    restores the previous release pointer, its media set, and any difficulty write-backs
    captured in that release **independently of Cloud Run**. Rehearsed on staging first.
- Rollout order: regenerate remaining events on staging → **run promotion dry-run against
  prod, review manifest** → snapshot prod (`scripts/snapshot_db.sh`) →
  `scripts/deploy.sh --tag v<next>` (image, incl. any migrations) →
  `promote_content_release.py --apply --release <id>` (atomic pointer switch) →
  post-deploy smoke (`GET /`, `GET /api/events`, spot-check one course + exam on
  `science-olympiad.com`).

### Real verification ✅ (acceptance checklist)
- [ ] Whole-loop Playwright run green on staging.
- [ ] `pytest` (incl. `@pytest.mark.live` smoke) green.
- [ ] Post-cutover content audit over the **`published` release** (not the pre-release
      `machine_validated` set) beats Phase 0 baseline (≥90% validate pass, 100% grounded,
      0 blocking near-dups, every exam meets blueprint); census shows 0 unaudited rows.
- [ ] Generation refuses to run without an approved plan, and honors per-plan source
      scoping (verified in prod UI).
- [ ] (If 3b built) coach cannot publish globally; cross-org plan access returns 404.
- [ ] Media governed through `SpecimenAsset`; galleries/figures/video render; no broken or
      hotlinked images (Phase M).
- [ ] Promotion dry-run manifest reviewed (rows **and media**); apply reconciled row
      counts/hashes before the atomic pointer switch.
- [ ] `science-olympiad.com` serves the promoted release; images render; exam submit→review works.
- [ ] **Two** rollback paths captured and rehearsed on staging: (a) Cloud Run revision
      (app/image), and (b) `promote_content_release.py --rollback` (data/release pointer).

---

## Sequencing & rough sizing

| Phase | Depends on | Rough size |
|---|---|---|
| 0 Baseline + staging | — | S–M |
| Q Catalog-wide quality program (all courses) | 0 | M |
| 1 Solver + embedding | 0 | M |
| 2 Regenerate catalog | 1 | M–L |
| 3 Approval gate + authoring UI (3a staff; 3b coach later) | 1 | L |
| M Multimedia first-class | 1 (with 2) | M |
| V Generated video classes (Remotion+Deepgram) | M, existing worker | M–L |
| 4 Item-pattern store | 1 | M |
| 5 Feedback tightening | 2 | S–M |
| 6 E2E + promotion/rollback + rollout | all | M–L |

Phase Q runs right after Phase 0 (it turns the baseline into a standing, catalog-wide
program) and its backlog drives Phase 2's order; the scorecard then stays live for good.
Phases 1, 3, M, and 4 can partly parallelize after Phase 0. Phase M runs alongside Phase 2
(media must survive regeneration). Phase 2 gates production content quality, so it precedes
any prod rollout. Milestone 3b (coach authoring) is optional and can follow the prod rollout.
Phase V builds on published lessons (needs Phase M media governance) and the existing
Remotion worker in `video-agent-493605`; its V.0 discovery step can start anytime but the
render pipeline should follow Phase 2 so videos are built from verified lessons.

## Risks & mitigations
- **LLM cost/time on full regeneration** → regenerate in batches, cache, run off-hours;
  staging-validate before prod.
- **Regeneration regresses a good hand-authored event** → golden set + superseding
  (never delete) + per-event human review gate.
- **Live-LLM test flakiness** → deterministic stubbed suite is the gate; live suite is
  smoke-only and inspected, not asserted exact-match.
- **Staging drift from prod** → staging seeded from prod snapshot at Phase 0; re-sync
  before Phase 6.
