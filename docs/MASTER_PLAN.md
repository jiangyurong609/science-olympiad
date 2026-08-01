# Master Plan — one ordered path to a shippable platform

**Created:** 2026-08-01 · **Supersedes as entry point:** `HONEN_GAP_CLOSURE_PLAN.md`,
`KHAN_STYLE_LEARNING_EXPERIENCE_PLAN.md` (both remain as detailed sub-plans; this document
decides *order* and *gates*).

This exists because work has been reactive: symptoms fixed one screen at a time while the
cause went untouched. Everything below is ordered by **dependency**, not by appeal. Nothing
starts before the thing it depends on is measurably done.

---

## 1. The one root cause

Content was **generated and published without grounding or review**. A single generation path
(`scripts/build_courses.py`) wrote lessons and exams straight to a student-visible state,
skipping the claim/rights gate and the editor→SME→calibration ladder that already existed.

Every headline problem is a symptom of that:

| Symptom (measured 2026-08-01) | Traces to |
|---|---|
| 0 of 67 courses pass the release audit | published without meeting the volume/review contract |
| 0 of 410 published lessons have review evidence | published without review |
| 0 questions are `published` (687 machine_validated, 5,270 draft) | never entered the ladder |
| **150 exams are published serving draft items** | published without review |
| 8.7% of items grounded; **0 of 410 lessons groundable** | published without claim extraction |
| The one video "grounded" on an unrelated mineral claim | no relevant-grounding gate (now fixed) |
| Video cannot scale | needs grounded lessons that do not exist |
| Uploaded past tests produce nothing | ingestion never wired to item creation |

**Consequence:** work that assumes good content — video at scale, mastery, calibration,
traceability — cannot succeed until grounding and review exist. That is why the last stretch
felt like patching: the foundation was missing while the roof was being decorated.

## 2. Operating rules

1. **Dependency order is binding.** A phase may not start until its predecessor's *Done when*
   number is met. No parallel "while we're at it".
2. **Done is a number, not a judgement.** Each phase states a measurement and the command
   that produces it.
3. **Verify where the user is.** API correctness is not completion; the intended person must
   complete the intended task on a real screen.
4. **No new student-facing capability until Phase 3 completes.** Capability on unreviewed
   content multiplies the defect (proved: 410 lessons, and a video citing the wrong claim).
5. **One plan.** New findings amend this document; they do not spawn another.

---

## Phase 0 — Stop serving unreviewed content  ⟵ START HERE

**Why first:** students are currently taking 150 published exams whose every item is `draft`
or `machine_validated`. This is a correctness problem affecting real users, and it is small.

- Gate exam serving on item status: an exam may only serve items that passed review, or the
  exam must be honestly reclassified (e.g. `unreviewed_practice`) and labelled in the UI.
- Same gate for lessons: a published lesson without review evidence is labelled, not silently
  presented as verified.
- Add the standing check to the Phase Q scorecard so this can never regress.

**Done when:** zero student-visible items lack either review evidence or an explicit
"unreviewed" label. `python -m scripts.audit_catalog_quality` reports 0 unlabelled violations.
**Unblocks:** everything — it is the honesty floor.
**Size:** S.

## Phase 1 — Grounding coverage

**Why now:** grounding is the single largest unlock. It is the prerequisite for regeneration
(Phase 2), for the §8 traceability criterion, and for video at scale (Phase 5). Today **0 of
410 lessons** can cite a claim that belongs to them; 101 approved claims exist but none are
attached to lessons.

- Run the existing claims pipeline at scale: `/sources/{id}/extract-claims` → `/claims` →
  approve, per event, from rights-cleared sources.
- Attach claims to lessons/concepts so `LessonVersion.claim_ids` is populated truthfully.
- Report coverage per event; record a `ContentGap` where sources cannot support a skill
  instead of implying coverage.

**Done when:** ≥80% of live-event lessons have ≥1 approved, rights-cleared, *relevant* claim.
Measure: the groundable-lessons query (0/410 today).
**Unblocks:** Phases 2, 5; §8 traceability.
**Size:** M–L. **This is the real work, and it has never been done.**

## Phase 2 — Regenerate content through the rigorous path

**Why now:** requires Phase 1 (nothing to ground on) and Phase 0 (do not add to an unlabelled
pool). Detail: `HONEN_GAP_CLOSURE_PLAN.md` Phases 1–2, ordered by the Phase Q backlog.

- Harden the generator first (independent solver + embedding similarity — already built).
- Regenerate catalog content through `model_generation.py`, writing new versioned rows that
  supersede rather than delete.
- Output lands at `machine_validated`; it does **not** auto-publish.

**Done when:** ≥90% of regenerated items pass `validate_candidate`, 100% grounded, 0 blocking
near-duplicates, every exam meets its blueprint. Measure:
`python -m scripts.audit_content_quality --status machine_validated --generation-run <id>`.
**Size:** M–L (LLM spend).

## Phase 3 — Drive content through the review ladder

**Why now:** regenerated content is worthless while it sits at `machine_validated`.

- Editor and SME review queues (built) worked through per event.
- Publish only from `sme_approved`; calibration follows publication as the code implements.
- Coach-visible coverage so a gap is explicit rather than an empty screen.

**Done when:** ≥1 event fully satisfies §4.4 volume and the question contract, and passes
`audit_course` as `release_ready` — the first course that is genuinely done.
**Unblocks:** production rollout; a truthful vertical slice.
**Size:** M (human review time dominates).

## Phase 4 — Release machinery and production rollout

**Why now:** only meaningful once something is worth releasing.

- Catalog-release identity, immutable membership, atomic active-release pointer, release-aware
  reads, backfill, dual-read deploy (`HONEN_GAP_CLOSURE_PLAN.md` Phase 6 / R-C3).
- Promotion job with dry-run manifest, hash reconciliation, and a rehearsed **data** rollback
  distinct from Cloud Run revision rollback. Media travels with the release.

**Done when:** a release promotes to production atomically and rolls back cleanly in a
rehearsal; post-cutover audit beats the baseline.
**Size:** M–L.

## Phase 5 — Video at scale

**Why now:** requires grounded lessons (Phase 1) and reviewed content (Phase 3). Rendering is
*not* the constraint: measured 3.1 h wall at 8× parallel for all 410 lessons.

- Narration generation from lesson blocks + their grounded claims (hand-authored today).
- Batch storyboard → approval → chaptered render → QA.
- Keep the relevant-grounding gate; keep QA before student visibility.

**Done when:** ≥1 full event has video on every lesson, all grounded and QA-approved.
**Size:** M (mostly compute, some review).

## Phase 6 — Ingestion fidelity (uploaded past tests)

**Why here:** independent of 1–5 but competes for the same review capacity; it also produces
content that must pass the same gates, so it lands after the ladder works.

- **6a Figures survive import** — crop page regions to `ExtractionAsset`; today extraction is
  text-only and ~224 items reference figures that do not exist and are excluded from scoring.
- **6b Upload → draft exam** — wire the CLI converter into intake as a service behind review;
  parse structure with per-item confidence; low-confidence answers go to the needs-key queue.
- **6c Fidelity report** per import; imported exams enter the Phase Q scorecard.

**Done when:** ≥90% of figure-referencing imported items carry a usable figure, and an upload
reaches a published practice exam only through review.
**Size:** M–L.

## Phase 7 — Learning-flow completion

**Why last:** polish on content that is finally trustworthy.

- Learn → practice → prove arc wired to lesson completion (machinery exists, unwired).
- Scaffolding in practice: hints and worked steps from grounded claims.
- Progress legibility; placement diagnostic last.

**Done when:** a student completes lesson → practice → mastery change without navigating a
menu, verified in a browser.
**Size:** M.

---

## 3. Scoreboard — the numbers that define progress

Re-measured at every phase boundary; no phase is "done" on judgement.

| Metric | Today | Target | Phase |
|---|---:|---:|---|
| Student-visible items lacking review or a label | many | 0 | 0 |
| Live-event lessons with a relevant approved claim | 0 / 410 | ≥80% | 1 |
| Regenerated items passing validation | — | ≥90% | 2 |
| Items grounded | 8.7% | 100% of regenerated | 2 |
| Courses `release_ready` | 0 / 67 | ≥1, then rising | 3 |
| Questions with editor+SME review | 0 | all published | 3 |
| Published `ContentRelease` records | 0 | ≥1 promoted + rolled back | 4 |
| Lessons with grounded video | 1 (invalid) | 1 full event | 5 |
| Imported items with usable figures | 0% | ≥90% | 6 |

## 4. What this replaces

- `HONEN_GAP_CLOSURE_PLAN.md` — remains the **detailed** spec for Phases 2, 4 (its Phases
  0/Q/1/2/6). Its Phase 3 (authoring gate) folds into Phase 3 here.
- `KHAN_STYLE_LEARNING_EXPERIENCE_PLAN.md` — remains the **content standard** (§4.4 volume,
  question contract) and the learner-experience spec used by Phases 3 and 7. Its §9 audit is
  the evidence base for this plan.
- Superseded behaviour: choosing what to build next by what is most visible. Order is fixed
  above.
