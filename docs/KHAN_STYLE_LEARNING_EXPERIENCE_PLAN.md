# Fieldstone Learning Experience Plan

Status: product plan only. No content is considered student-ready until it passes the editorial gates below.

## 1. What we are copying—and what we are not

We are copying Khan Academy's learning mechanics, not its branding or visual design:

- A student chooses a course, unit, and skill rather than a pile of resources.
- Each unit has a visible sequence: learn, practice, quiz, unit test.
- Students can start at the beginning or take a diagnostic/unit test.
- Practice gives immediate feedback and a useful explanation.
- Mastery is earned over repeated evidence, not by merely opening a page.
- The next action is always obvious.

Khan's current course pages expose units, skills, quizzes, unit tests, and course challenge; its mastery model moves skills through states such as Not started, Attempted, Familiar, Proficient, and Mastered. Students can also use a quick unit test to find gaps before starting from the beginning. Sources: [course example](https://www.khanacademy.org/science/grade-6-science), [mastery model](https://support.khanacademy.org/hc/en-us/articles/115002552631-What-are-Course-and-Unit-Mastery-), and [student flow](https://en.khanacademy.org/khan-for-educators/resources/students/resources-for-students/a/getting-started-with-khan-academy).

## 2. Current Fieldstone diagnosis

The current product has useful infrastructure but the wrong student abstraction:

- Navigation is organized around `Overview`, `Learn`, `Practice & Exams`, and `Error Notebook`, while the student actually needs `Course → Unit → Skill`.
- Resources are mapped to events, but PDFs, web pages, and videos are not consistently converted into authored instruction.
- Lessons, practice sets, questions, mastery states, source snapshots, claims, reviews, and calibration already exist in the database, but they are not presented as one coherent learning system.
- Some generated video lessons were published before a real editorial/SME review. Those must be treated as provisional and re-gated.
- A “resource count” is currently more visible than “what you will learn next.”

The core correction is to make the event page a course map, not a library.

## 3. Student experience

### A. Start

The home screen answers one question: “What should I do now?”

It contains:

1. Current course and season.
2. One recommended next lesson or review task.
3. A compact course progress bar.
4. “Continue” as the primary action.
5. “Choose another event” as the secondary action.

No generic AI language, decorative metrics, or empty dashboard panels.

### B. Course map

`/courses/{season}/{event-slug}` shows:

- Course title and competition context.
- Diagnostic button: “Check what I know.”
- Course challenge button: “Test the whole course.”
- Ordered units with completion and mastery state.
- Each unit's lessons, practice, quiz, and unit test.
- Locked/unlocked state based on prerequisites, never hidden content.

Example for Rocks & Minerals:

1. Observe like a mineralogist
2. Physical properties
3. Hardness, streak, cleavage, and fracture
4. Density and magnetism
5. Identification workflow
6. Timed station practice
7. Competition review

### C. Lesson

Every lesson follows a predictable five-part rhythm:

1. **Goal** — “By the end, you can …”
2. **Teach** — short explanation, diagram, or attributed source video.
3. **Try** — a worked example or guided observation.
4. **Check** — one question at a time with immediate feedback and explanation.
5. **Exit** — recap, mastery evidence, and the next recommended action.

Video is one teaching component, never the lesson itself. A video lesson must include transcript-grounded notes, timestamps, explicit objectives, misconceptions, checks for understanding, and a source link.

### D. Practice

Practice is skill-specific, not a generic exam dump:

- One skill per session.
- Mixed difficulty: recall, interpretation, application, transfer.
- Immediate answer explanation.
- “Try a similar problem” after an error.
- Automatic remediation link to the exact lesson or concept.
- No question enters student practice until it is approved and calibrated.

### E. Assessment

Each unit has:

- Short quiz: 5–8 questions, formative, retryable.
- Unit test: broader sampling, no teaching during the attempt.
- Course challenge: diagnostic coverage across all skills.
- Timed competition simulation: event-specific station/test format.

An assessment reports skill-level changes, not only a percentage score.

### F. Review

The student sees:

- Skills needing review.
- Why an answer was wrong.
- A short corrective lesson.
- A transfer question using a new specimen, diagram, or scenario.
- Spaced review scheduled from evidence, not arbitrary reminders.

## 4. Content production standard

### 4.0 Review verdict

This plan is directionally correct but was not sufficient to prove that all imported materials would become useful instruction. The missing control is a measurable **material coverage ledger**. A course is not complete because sources were imported or because an LLM produced lessons; it is complete only when every usable source has a declared instructional role, extraction status, mapped skills, learner-facing destination, review status, and release decision.

The current spreadsheet inventory is documented as 77 rows: 41 `soinc.org` links, 36 YouTube links, 9 global/season-wide resources, and 3 malformed PDF references requiring correction. The repository also contains crawled PDF and HTML artifacts outside the sheet. The plan must track both inventories so material cannot silently disappear between import, extraction, and course authoring.

### 4.1 Material utilization matrix

| Material | Required treatment | Student destination |
|---|---|---|
| Official rules/manuals | Extract headings, tables, page locators, constraints, terminology, and update dates | Rules reference plus linked lessons |
| Study guides/handouts | Extract prose, tables, figures, captions, and page references; map to skills | Lessons, glossary, and reference |
| YouTube teaching videos | Retrieve full transcript, timestamp segments, objectives, and misconceptions | Embedded lesson with transcript-grounded checks |
| Web pages/articles | Snapshot the complete page with authority and freshness metadata | Reading lesson or cited explanation |
| Practice tests | Use as blueprint evidence; do not reproduce protected questions | Original practice sets and simulations |
| Answer keys/rubrics | Validate scoring and create feedback; preserve rights boundaries | Feedback and coach review tools |
| Images/specimens/diagrams | Preserve attribution, dimensions, captions, rights, and alt text | Visual lessons and identification labs |
| Season-wide resources | Map to multiple events or cross-event skills | Shared season fundamentals |
| Rejected/malformed rows | Correct, replace, or quarantine with an owner | Operations queue only |

“Reference-only” is allowed, but it must be an explicit editorial decision with a reason.

### 4.2 Coverage ledger

Create one release-report row per source with: `source_id`, sheet row, event(s), season, source type, authority tier, rights status, snapshot ID, extraction status, passage count, claim count, mapped units, mapped skills, lesson IDs, practice-set IDs, question IDs, review status, student destination, last verification, and withdrawal reason.

No valid source may remain unexplained in `imported`, `link_only`, `extraction_failed`, or `unmapped` state at release.

### 4.3 Existing content and exam migration

The Google Sheet is only one input. The release inventory must also include every existing database and storage object:

- Published and draft `Lesson`/`LessonVersion` records.
- `PracticeSet`/`PracticeSetVersion` records.
- `Question` records and their review/calibration history.
- Published `Exam`/`ExamItem` immutable snapshots.
- Imported past-test sources and answer keys.
- PDF, HTML, image, and other `RawArtifact` objects in storage.
- Existing event, concept, taxonomy, and blueprint records.
- Student progress, attempts, mastery states, error-notebook records, and assignments.

Existing published exams must not be rewritten in place. Preserve their immutable snapshots and audit them into one of these states: `verified legacy`, `needs review`, `withdrawn`, or `migrate to new blueprint`. Existing lessons and practice sets need the same treatment, with redirects from their current student URLs.

Legacy past tests are assessment evidence and may remain available as clearly labeled past-test practice when rights permit. They must not be silently presented as newly authored course lessons, and their questions must not be mixed into a new competition-ready exam pool without an explicit release decision.

Migration acceptance requires a reconciliation report: every pre-existing record is either linked to a new course/unit/skill, preserved as historical content, intentionally withdrawn, or assigned to an owner for remediation. No old student progress may disappear during the migration.

### Source pipeline

For every PDF, web page, or video:

1. Preserve the original URL/file and immutable snapshot.
2. Extract text, headings, tables, figures, page numbers, and timestamps.
3. Split into source passages with stable locators.
4. Create approved scientific claims linked to passages.
5. Map claims to event, unit, skill, and prerequisite.
6. Generate lesson and question drafts only from approved claims.
7. Run factual, duplicate, answerability, reading-level, and rights checks.
8. Require editor review and independent SME review.
9. Pilot questions and calibrate difficulty/discrimination.
10. Publish a versioned release; retain the source snapshot used.

LLMs may draft explanations, distractors, summaries, and lesson structure. They may not decide truth, publish content, or silently fill missing facts.

Extraction must finish before generation begins. Do not truncate a transcript or PDF merely to fit a prompt; retrieve bounded passages, generate against each passage, then reconcile claims and citations deterministically.

### Lesson contract

Every published lesson must have:

- 1–3 measurable objectives.
- Prerequisite skills.
- 5–12 minute target duration.
- At least one representation (text, diagram, specimen image, or video).
- At least two guided interactions.
- At least three checks, including one application/transfer check.
- Explanations for every answer choice.
- Citation for each substantive claim.
- Author, editor, SME, source snapshot, and version.

### 4.4 Minimum content volume

Before an event is called a complete vertical slice, counts must come from the skill blueprint:

- Every skill: one teach lesson and one formative check.
- Every unit: 2–3 lessons, one 5–8 item quiz, and one unit-test blueprint.
- Every high-weight skill: 8–12 approved items across recall, application, and transfer.
- Course challenge: a coverage table showing the sample count for every skill.
- Competition simulator: its own event-format, timing, scoring, and accommodation blueprint.

If approved sources cannot support a skill, the course must label the gap and create an authoring task rather than imply mastery is possible.

### Question contract

Every published question must have:

- One unambiguous answer.
- Source claim IDs and locators.
- A rationale and misconception tag for each distractor.
- Cognitive level and difficulty estimate.
- Appropriate asset/diagram attribution where needed.
- Editor approval, SME approval, and calibration record.

## 5. Information architecture

```
Home
├── My Learning
│   ├── Continue
│   ├── Review queue
│   └── Mastery overview
├── Courses
│   └── {Season} / {Event}
│       ├── Course map
│       ├── Unit
│       │   ├── Lesson
│       │   ├── Practice
│       │   ├── Quiz
│       │   └── Unit test
│       ├── Course challenge
│       └── Competition simulator
├── Mistakes to fix
└── Source library (secondary, not the default learning path)
```

URL state should be deep-linkable:

- `/courses/2027/rocks-and-minerals-b`
- `/courses/2027/rocks-and-minerals-b/unit/physical-properties`
- `/courses/2027/rocks-and-minerals-b/lesson/streak`
- `/courses/2027/rocks-and-minerals-b/practice/streak`
- `/courses/2027/rocks-and-minerals-b/test/unit-2`

## 6. Data model changes

Reuse existing `Event`, `Concept`, `Lesson`, `LessonVersion`, `PracticeSet`, `Question`, `SourceSnapshot`, `ScientificClaim`, `QuestionReview`, `QuestionCalibration`, and `MasteryState`.

Add or formalize:

- `Course` / `CourseVersion` — season, event, release status.
- `Unit` — ordered grouping with objectives and prerequisites.
- `Skill` — assessable capability, not just a topic label.
- `LessonSkill` — many-to-many mapping with weight.
- `AssessmentBlueprint` — coverage, cognitive levels, difficulty targets.
- `ContentRelease` — atomic release of course, lessons, and questions.
- `SourcePassage` — page/heading/timestamp locator and normalized text.
- `ReviewDecision` — editor/SME/rights decisions for lesson versions.

## 7. Build phases

### Phase 0 — Content safety reset

- Unpublish auto-generated lessons that lack editor/SME approval.
- Keep them in an internal review workspace.
- Mark video-derived questions as candidates only.
- Produce a source coverage report for every event.
- Build the 77-row spreadsheet-to-source-to-artifact coverage ledger.
- Correct the three malformed PDF references or quarantine them with an owner and resolution date.
- Classify every source as instructional, assessment evidence, reference-only, season-wide, or rejected.
- Export and reconcile the full legacy database/storage inventory before changing student routes.
- Freeze direct publication of new generated content during migration; preserve existing exam snapshots and student attempts.
- Assign every legacy lesson, practice set, question, exam, and artifact a migration state and owner.

### Phase 1 — One complete vertical slice

Choose Rocks & Minerals Division B. Build one complete unit end-to-end from the actual official materials: extraction, claims, lesson, practice, quiz, remediation, mastery, and review. The slice must include at least one PDF/manual section, one web source, one video transcript, one visual/specimen asset, and one practice-test blueprint. Do not scale until a teacher can audit every claim and question.

### Phase 2 — Course map and mastery UX

Replace the event library screen with the course map, unit cards, skill states, Continue action, diagnostic, quizzes, and unit tests.

### Phase 3 — Authoring/review console

Give content staff a source passage viewer, generated draft side-by-side with evidence, review checklist, version diff, and publish gates.

### Phase 4 — Expand event coverage

Roll out event-by-event. Each event must meet the same release checklist; no “content in review” student dead ends.

### Phase 5 — Teacher/team workflows

Add assignments, due dates, team dashboards, accommodations, and teacher reports only after the self-paced learner loop is reliable.

## 8. Definition of done

We do not call an event production-ready until:

- Every published lesson is evidence-linked and human-reviewed.
- Every unit has enough approved practice to support mastery.
- Diagnostic, quiz, unit test, and competition simulation work.
- Wrong answers produce useful explanations and remediation.
- A student can reach the next recommended action in one click.
- A teacher can inspect why every claim and answer is present.
- No empty state says content is “being prepared” when a source is available.
- Desktop and mobile flows pass accessibility, keyboard, focus, and no-overflow checks.
- The coverage ledger has no unexplained valid source; every source has a student destination or documented reference-only decision.
- The event meets the minimum lesson and question volume thresholds for every skill.
- A teacher can trace every student-facing sentence and answer explanation to a page, heading, table, figure, or video timestamp.
- A fresh source snapshot produces a reviewable diff and never silently overwrites published content.
- Existing courses, exams, attempts, mastery records, and error-notebook entries survive migration with a traceable mapping or an explicit withdrawal record.
