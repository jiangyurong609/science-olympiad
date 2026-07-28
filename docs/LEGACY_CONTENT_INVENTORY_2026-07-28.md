# Legacy Content Inventory

Inventory date: 2026-07-28  
Target: production Cloud SQL database `soplat-pg` in `video-agent-493605`  
Method: read-only Cloud SQL Auth Proxy queries; no records changed.

## Executive result

The existing system is substantially larger than the Google Sheet import. It contains a mature 2026 content corpus, a partially populated 2027 corpus, and live student dependencies that must be preserved.

| Area | Count |
|---|---:|
| Events | 102 |
| Concepts | 209 |
| Lessons | 458 |
| Lesson versions | 458 |
| Practice sets | 3 |
| Questions | 5,866 |
| Exams | 150 |
| Exam items/snapshots | 5,413 |
| Sources | 838 |
| Source snapshots | 780 |
| Raw stored artifacts | 291 |
| Event-source mappings | 650 |
| Scientific claims | 114 |
| Users | 8 |
| Attempts | 7 |
| Responses | 326 |
| Lesson progress rows | 3 |
| Mastery states | 1 |
| Teams | 1 |

## Content by season

### 2026 legacy corpus

- 48 events: 24 Division B, 23 Division C, and 5 B/C events.
- 410 published lessons.
- 3 published practice sets.
- 150 published exams.
- 5,413 immutable exam item snapshots.
- 5,842 questions, including 4,755 imported past-test questions and 375 generated-from-material questions.

This is the primary existing course/exam corpus and must not be replaced by the 2027 sheet workflow.

### 2027 current corpus

- 54 events: 25 Division B, 24 Division C, and 1 B/C season-resources event.
- 48 published lessons, currently concentrated in generated video lessons.
- 0 published exams.
- 0 practice sets.
- 16 video-transcript question candidates, not student-ready.

This confirms that the current 2027 experience has resources and some lessons, but not a complete Khan-style course or assessment system.

## Source and storage inventory

- 838 source records exist.
- 780 source snapshots exist.
- 291 raw artifacts exist: 238 PDFs and 53 HTML files.
- 31 YouTube transcript snapshots exist.
- 316 discovered-resource frontier records exist.
- 650 event-source mappings exist.
- 438 sources have local/file-style URLs and require explicit provenance review before any student use.
- `soinc.org` has 329 source records, only 4 currently approved.
- 31 YouTube transcript sources are approved; additional YouTube sources remain unapproved or unavailable.

The source system contains more than the 77 spreadsheet rows. The migration must reconcile spreadsheet rows, crawled sources, discovered resources, raw artifacts, and existing event mappings into one ledger.

## Assessment and learning integrity

- Existing 2026 exams are published and have immutable `ExamItem` snapshots; preserve these snapshots for historical attempts.
- Existing questions have 0 question reviews and 0 question calibration records in the production database. This means the current corpus should not automatically be labeled “Khan-quality mastery content.” It requires a review/calibration audit.
- There are 114 scientific claims but no question-review or calibration evidence, so claim coverage and assessment quality are not yet equivalent.
- There are 7 attempts and 326 responses. Any migration must preserve attempt scoring, answer snapshots, and student history.
- There are 3 lesson-progress rows and 1 mastery-state row. These are small but must remain linked to the same concepts/lessons or receive an explicit migration mapping.
- There are no assignments or remediation cases yet, so those parts of the planned experience are not represented in the legacy corpus.

## High-priority anomalies

1. 2027 has many event source mappings but almost no assessable content.
2. 2027 currently has no published exams or practice sets.
3. 2026 has a large question/exam corpus but no recorded question reviews or calibrations.
4. There are duplicate-looking legacy event identities, including both `heredity` and `heredity-b` in 2026; aliases must be resolved before course URLs are redesigned.
5. Local/file-style source URLs need provenance and rights classification.
6. Some stored sources are discovered/crawled artifacts rather than spreadsheet materials; they need source authority and freshness labels.
7. Video-derived 2027 lessons and questions need separate review from the legacy 2026 content; they should not inherit “approved” status merely because they are visible.

## Required migration sequence

1. Export this inventory on every release and diff it against the prior inventory.
2. Assign stable course/unit/skill identities before changing URLs.
3. Map every existing lesson, practice set, question, exam, and source to a migration state.
4. Preserve published exam snapshots and student attempts unchanged.
5. Audit 2026 questions/exams for rights, source evidence, answerability, and calibration.
6. Reconcile duplicate event aliases and preserve redirects.
7. Build the first complete 2027 vertical slice using both legacy assets and new sheet materials.
8. Only then expose the new course-map UI broadly.

## Release blocker

The platform is not ready to claim that it “utilizes all materials.” The inventory is complete enough to plan the migration, but source-to-skill mapping, lesson coverage, question review, and calibration are still incomplete.
