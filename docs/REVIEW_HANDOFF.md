# Review handoff — pilot course `rocks-and-minerals-b`

**Prepared:** 2026-08-01 · **Blocking:** MASTER_PLAN Phases 3, 4, 5, 6

Everything an engineer can do on this course is done. What remains is **247 blockers, of which
~198 are human decisions**, and this document exists so they are a bounded afternoon rather
than an open-ended slog. Every number below comes from a committed command, listed with each
section, and is current as of the last commit — earlier drafts of this file quoted 252 and
29.6% before further work moved both.

---

## Why this cannot be automated

The catalog reached its current state because content was published without review — four
separate write paths did it, and 402 lessons went in front of students unchecked. Recording an
approval that nobody performed would reproduce exactly that, while making the audit report a
finished course.

This is not a hypothetical concern about care. Over this session, four consecutive rounds of
verification were themselves wrong: a rollback that restored a pointer but nothing a student
reads, sources cleared by relabelling them into an exempt role, a figure recovery that was
inert in production, and a review-evidence summary that would have shown 684 never-checked
items as vetted. Each passed its own tests. **A review decision has no test that catches it
being wrong**, which is why it needs a person.

---

## 1. Items — 67 to review (2 stages each)

```
PYTHONPATH=. python -c "..."   # or:
GET /api/content/questions/review-queue?course_id=<pilot course id>
```

All 67 went through the hardened generator, and the signals are unusually clean:

| Signal | Count | What it means |
|---|---:|---|
| Both gates ran | **67 / 67** | blind solver *and* independent verifier executed |
| Blind solver reproduced the key | **67 / 67** | a solver that never saw the answer chose it |
| Verifier raised errors | **1** | ← read this one closely |
| Nearest neighbour > 0.80 similarity | **4** | ← check these are not near-duplicates |

**Suggested order: the 5 flagged items first.** If they hold up, the remaining 62 agree on
every independent signal available, and reviewing them is confirmation rather than
investigation.

Each queue row now carries `review_evidence` with the solver's verdict and chosen index, the
verifier's per-check findings, the grounding claim ids, and the similarity score — so the
decisive facts are visible without opening `validation_report`.

> **Do not bulk-approve on `gates_run` alone.** Catalog-wide only 136 of 820
> machine-validated items have solver evidence at all; the other 684 predate the hardened
> generator. That is why `gates_run` is reported rather than assumed. The pilot's 67 are all
> gated — other courses are not.

## 2. Lessons — 24 to review (2 stages each)

```
GET /api/content/lessons/review-queue     # 24 rows, all at stage "editor"
```

All 24 carry a `preview_url` that renders the lesson as a student sees it. They are the
result of splitting 8 lessons that ran 19–27 minutes into parts of 8–12 minutes.

**What to look at, in order of how likely it is to be wrong:**

1. **Generated connective blocks.** Openings, summaries and checkpoints written by a model
   during the split are tagged `generated_by: split_lessons` in the block JSON. Teaching
   blocks were *moved*, never rewritten, and keep their original claim and passage ids — so
   review effort belongs on the generated joins, not the body.
2. **The seams.** Each part should open and close as a lesson, not as half of one.
3. **Blocks pointing at material the student never got.** Each queue row now carries
   `unavailable_source_blocks`. **15 of the 24 lessons have at least one, and 6 of those are
   checkpoints** — items assessing a student on "the source packet" or "the source's 1500 C
   solid-solution example", which they have never seen. Those 6 are unanswerable as written
   and are the highest-value thing to fix in this pass; the rest are teaching blocks that read
   oddly but do not score anyone.

## 3. Sources — 21 dispositions to review

```
PYTHONPATH=. python -m scripts.phase3_mechanical --event rocks-and-minerals-b
```

Each has an auto-recorded disposition (role, extraction status, claim count) and
`review_status: unreviewed`. **9 are flagged `source_destination`**: they are marked
instructional but no lesson cites a claim from them. That is a real question — the content may
have been lost in a regeneration — and it needs an answer, not a label. An earlier pass
cleared these by switching them to a role the audit exempts; that was reverted.

---

## After the reviews

1. `PYTHONPATH=. python -m scripts.phase3_mechanical --event rocks-and-minerals-b --apply`
   — re-run; blockers should fall to `release_missing` alone.
2. Promote via `POST /api/content/releases/{course_id}` with `decision=published`. This writes
   an immutable manifest and moves the pointer atomically.
3. `PYTHONPATH=. python -m scripts.rehearse_release --event rocks-and-minerals-b`
   — rehearses promotion *and rollback* against real content, committing nothing. It has
   caught two real defects already.

## Known limits, stated rather than buried

- **Grounding is 96.4%** (189 of 196 blocks), 100% accounted for. It read 29.6% earlier, and
  the climb was almost entirely bug-fixing rather than new content: the grounder and the audit
  had drifted to different definitions of a substantive block, and the matcher was comparing
  claims against each block's *heading only* because it read top-level strings while summaries
  keep their bullets in a list. 38 targeted references were added on top of that.
  **What the number means:** a supported block cites a claim that is approved, rights-cleared,
  verifiably present in a retained snapshot, and topically relevant. It does **not** assert the
  claim entails the block's specific statement — that judgement is exactly what the SME pass is
  for. Spot-checking found the pairings sound but sometimes adjacent rather than entailing.
- **7 blocks remain ungrounded and mostly should not be grounded** — they cite the same
  unavailable source packet flagged in §2 and need rewriting, not a citation.
- **Figure recovery cannot help this catalog.** These tests use vector diagrams that
  `page.images` cannot see and print them on separate image sheets. 0 of 43 blocked items are
  recoverable; closing it needs vector rendering and caption OCR. See
  `scripts/backfill_figures.py`.
- **Catalog scale is 50 more events** with the same defects and ~1,200 more lesson reviews.
  See `scripts/audit_catalog_structure.py`. Phase 6 is review-bound, not engineering-bound.
