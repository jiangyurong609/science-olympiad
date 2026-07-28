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

### Phase 1 — One complete vertical slice

Choose Rocks & Minerals Division B. Build one complete unit end-to-end from the actual official materials: extraction, claims, lesson, practice, quiz, remediation, mastery, and review. Do not scale until a teacher can audit every claim and question.

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
