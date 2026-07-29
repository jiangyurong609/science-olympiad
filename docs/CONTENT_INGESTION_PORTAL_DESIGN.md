# Fieldstone Content Ingestion & Authoring Portal

## Decision

Build a staff-only Content Studio, separate from the student and coach experiences. A parent may upload material only into a controlled intake area; publication, question generation, and course release remain staff actions. Uploaded files never become student-visible automatically.

The portal should turn a source into a traceable content pipeline:

```text
Upload / import
  → virus + file validation
  → durable artifact + checksum
  → extraction (PDF/OCR/transcript/table)
  → source review and rights decision
  → event/topic mapping
  → grounded lesson/question drafts
  → editor review → SME review → calibration
  → preview release → published release
```

The key product rule is provenance: every paragraph, question, answer key, and lesson checkpoint must be traceable to a source passage and its exact source version.

## Users and permissions

| Role | Can upload | Can see student data | Can generate drafts | Can approve | Can publish |
|---|---:|---:|---:|---:|---:|
| Parent / guardian | Assigned intake only | Their linked student only | No | No | No |
| Coach | Team/event scope | Their team | Request generation | No | No |
| Editor | Scoped events | No student PII by default | Yes | Editorial stage | Preview only |
| SME | Scoped events | No student PII by default | Yes | Accuracy stage | No |
| Calibrator | Scoped events | Anonymized attempts | Yes | Difficulty/release readiness | No |
| Admin | All | Audited access | Yes | Override with reason | Yes |

Parents should not be granted the existing content-staff role. Their upload is an untrusted contribution and must enter `intake_review`.

## Information architecture

```text
Fieldstone
├── Student app
│   ├── Home
│   ├── Courses
│   ├── Practice
│   └── Review
├── Coach portal
│   ├── Team overview
│   ├── Assignments
│   └── Student progress
└── Content Studio (staff)
    ├── Inbox
    │   ├── Parent uploads
    │   ├── Spreadsheet imports
    │   └── URL / YouTube imports
    ├── Sources
    │   ├── Source detail
    │   ├── Extracted text and passages
    │   ├── Rights and provenance
    │   └── Event/topic mapping
    ├── Author
    │   ├── Lesson builder
    │   ├── Question builder
    │   ├── Exam blueprint builder
    │   └── Coverage map
    ├── Review queues
    │   ├── Extraction issues
    │   ├── Lesson review
    │   ├── Question review
    │   ├── Rights / citation review
    │   └── Student feedback
    ├── Releases
    │   ├── Preview releases
    │   ├── Published courses
    │   └── Rollback history
    └── Audit log
```

Recommended URLs:

| Area | URL |
|---|---|
| Intake inbox | `/admin/content/inbox` |
| Upload material | `/admin/content/upload` |
| Source detail | `/admin/content/sources/{source-id}` |
| Topic workspace | `/admin/content/events/{event-slug}` |
| Lesson draft | `/admin/content/lessons/{lesson-id}` |
| Question bank | `/admin/content/questions` |
| Review queue | `/admin/content/review` |
| Release manager | `/admin/content/releases` |
| Parent uploads | `/parent/materials` |

## Core workflow

### 1. Intake

The uploader selects an event, season, material type, and ownership/permission statement. Supported first-class types:

- PDF: rules, handouts, past exams, answer keys, books the organization owns or has permission to use.
- DOCX/PPTX: tutorials, workshops, lab guides.
- Image bundle: specimen sheets, diagrams, scanned pages.
- URL: official page or publicly permitted resource.
- YouTube URL: captions/transcript metadata only; never download the video.
- CSV/Google Sheet export: structured material index or question import.

The upload form must show a prominent rights declaration and require event/topic mapping. A parent can submit without knowing the exact topic, but then the item remains `needs_triage` and is not processed into student content.

### 2. Ingestion agent

The ingestion agent is a durable, idempotent job—not a request/response endpoint. Each upload creates an `ingestion_run` with a state machine:

```text
received → quarantined → scanning → extracting → chunking → classifying
         → mapped → ready_for_authoring
         ↘ failed / needs_human_review
```

Agent stages:

1. Validate MIME, extension, size, checksum, and archive contents.
2. Virus/malware scan before parsing.
3. Store the immutable original in GCS with tenant/event ACL metadata.
4. Extract text, page numbers, headings, tables, figures, and OCR confidence.
5. Normalize passages with stable IDs and page/section locators.
6. Detect material type and likely event/topic; never silently assign a topic when confidence is low.
7. Deduplicate by checksum and normalized-content fingerprint.
8. Create a source coverage report and extraction warnings.
9. Queue grounded draft generation only after a human approves the source and rights.

For a video, the agent stores URL, metadata, captions, timestamps, and transcript passages. The authoring model must cite timestamp ranges and create a lesson with video + notes + checkpoints; “read transcript” alone is not an acceptable published lesson.

### 3. Authoring agent

The authoring agent receives only approved passages plus the event rules/topic scope. It produces drafts, never releases:

- learning objectives and prerequisite skills;
- a short opening explanation;
- worked examples or observation routines;
- misconception-aware checkpoints;
- answer keys and explanations;
- source citations per claim/block/question;
- a coverage matrix showing which required topic objectives are and are not supported.

Generation must fail closed when the source has poor extraction confidence, missing answer-key evidence, rights restrictions, or insufficient coverage. The model must say “not supported by this source” instead of filling gaps from memory.

### 4. Human review

Every generated artifact passes independent gates:

1. Machine validation: schema, references, answer-key consistency, no empty blocks, accessibility checks.
2. Editor review: clarity, sequence, age appropriateness, duplication, citation completeness.
3. SME review: factual correctness and current rules.
4. Calibration: difficulty, distractor quality, timing, and student performance.
5. Release decision: preview, published, withdrawn, or rolled back.

Preview content is explicitly ungraded and feedback-enabled. Published content is versioned; editing creates a new version and never mutates a version students have attempted.

## End-to-end journeys and failure behavior

### Parent contributes a past exam

1. Parent signs in and sees only their linked team/student context.
2. Parent chooses `Past exam`, selects the event if known, attaches the file, and completes the rights/ownership declaration.
3. The upload is acknowledged immediately with an intake receipt and remains private.
4. The ingestion agent quarantines, scans, extracts, and reports page-level warnings.
5. Staff triages the event/topic and rights record; the parent receives `Accepted`, `Needs more information`, or `Rejected` with a reason.
6. Only after acceptance can staff request question or lesson drafts.
7. Generated artifacts appear in the review queue with citations; the parent never sees model prompts, private staff notes, or unreviewed student content.

### Editor creates a lesson from a video

1. Editor selects an approved transcript snapshot and target event objectives.
2. The authoring run creates a draft containing an embedded video, concise teaching notes, worked application, and checkpoints.
3. A validator verifies every claim citation and ensures checkpoint answers are present.
4. Editor and SME review the draft in a split view with timestamp/page citations.
5. The lesson enters preview as a new immutable release; student feedback is collected separately from mastery.
6. Calibration either promotes the lesson to published or returns it to a specific revision with actionable issues.

### Student encounters a missing or withdrawn class

The app must never show a launchable CTA for a lesson the API will reject. The materials endpoint and lesson catalog must use the same visibility predicate. If a source or lesson is withdrawn after a student has started it, the student sees a clear “Temporarily unavailable — review the updated version” state, while the original attempt remains pinned and auditable.

### Failure states that must be first-class

| Failure | User-visible state | Recovery |
|---|---|---|
| Upload interrupted | Resumable upload / retry | Continue from checksum-safe chunk |
| Malware or unsafe file | Rejected, no preview | Re-upload a clean file |
| OCR/table extraction poor | Needs human extraction review | Correct pages or upload a better scan |
| Rights unclear | Rights review blocked | Add license/proof or withdraw |
| Topic confidence low | Needs triage | Staff assigns event/topic |
| Generation timeout | Draft unavailable, source intact | Retry with same idempotency key |
| Missing citation/answer key | Draft blocked by validator | Editor fixes or regenerates |
| SME rejection | Returned with reason | Revise exact version |
| Source withdrawn | Dependents flagged | Replace source and create new release |

Every state must have a visible owner, next action, timestamp, and retry or escalation path. “In review” without an owner or action is not an acceptable terminal state.

## Data model additions

Existing `Source`, `SourceSnapshot`, `SourcePassage`, `EventSourceMap`, course, lesson, question, review, and release entities are the correct foundation. Add:

```text
ContentWorkspace
  id, owner_scope, event_id, status, created_by

UploadSubmission
  id, workspace_id, uploader_id, filename, artifact_key, sha256,
  declared_type, rights_attestation, status, created_at

IngestionRun
  id, upload_id, stage, status, worker_version, started_at, finished_at,
  error_code, diagnostics_json

ExtractionAsset
  id, upload_id, page_count, text_chars, ocr_confidence,
  extraction_version, artifact_key

SourceTopicAssignment
  source_id, event_id, topic_id, confidence, assigned_by, status

GenerationRun
  id, source_snapshot_ids, target_type, prompt_version, model,
  output_version, status, cost, diagnostics

ContentIssue
  id, entity_type, entity_id, severity, category, report, assignee,
  status, resolution, resolved_by

ParentMaterialShare
  upload_id, student_id/team_id, expires_at, consent_scope
```

All agent and human transitions must emit audit events with actor, previous state, new state, reason, and source/version IDs.

## Safety and privacy requirements

- Parent uploads are private to the assigned workspace until staff triage.
- GCS objects use generated keys; original filenames are metadata only.
- Enforce size, page, image, and OCR budgets to prevent denial-of-service uploads.
- Malware scanning and content-type sniffing precede extraction.
- Strip active content/macros from office files; reject encrypted files unless staff supplies a password through a secure flow.
- Do not expose student PII to generation workers.
- Keep copyright/rights status attached to every source and block publication when unknown.
- Rate-limit generation and show estimated cost before a large batch.
- Provide “pause source” and “withdraw dependents” controls when a source changes or is challenged.
- Retain exact source snapshots so an answer can be audited later.

## MVP sequence

### Phase 1: reliable intake (no AI release)

- Staff upload PDF/DOCX/image/URL/YouTube.
- GCS artifact storage, checksum deduplication, extraction, passage viewer.
- Event/topic assignment, rights attestation, ingestion diagnostics.
- Inbox and source review actions.

### Phase 2: grounded authoring

- Generate lesson/question drafts from approved passages.
- Show side-by-side source citations and coverage gaps.
- Add editor/SME review actions and version diff.
- Export/import review bundles for subject-matter experts.

### Phase 3: release and feedback

- Preview release with student feedback.
- Calibrated exam generation from approved questions only.
- Release manager with rollback and source withdrawal propagation.
- Parent/coach notifications when contributed material is used.

## Acceptance criteria

- A parent can upload a PDF and see only “Received / In review,” never an unreviewed lesson.
- Staff can open extracted text with page citations and diagnose OCR/table failures.
- Duplicate uploads create one canonical source with linked submissions.
- A generated question cannot be saved without a source passage and answer rationale.
- A lesson cannot publish with unresolved required coverage gaps or unreviewed claims.
- A withdrawn source automatically identifies affected lessons, questions, and exams.
- Students see only preview or published versions according to release status.
- Every published answer can be traced: student item → content version → claim/block → passage → immutable source snapshot.

## Initial implementation recommendation

Reuse the current content-operations authorization and source/crawl/artifact services. Add the intake and ingestion-run tables/API first, then a staff-only inbox UI. Do not start by adding a generic “Generate course” button: the system must first make extraction quality, rights, topic mapping, and evidence coverage visible to the reviewer.

## Visual direction: calm, modern learning workspace

The current yellow/green editorial treatment is too decorative and makes the product feel like a marketing site. The learning product should feel closer to Apple’s system apps: quiet chrome, generous whitespace, precise typography, and one clear action at a time. “Apple-like” here means restraint and clarity, not copying Apple UI or assets.

### Design principles

1. **Content is the visual priority.** Lessons, diagrams, worked examples, and exam questions get the strongest contrast; navigation recedes.
2. **One primary action per screen.** “Continue,” “Check answer,” “Start exam,” or “Review source” should be unmistakable. Secondary actions are quiet text buttons.
3. **Neutral surfaces.** Replace cream/yellow panels with white and cool-neutral gray surfaces. Reserve one accent color for progress and the primary action.
4. **Short learning loop.** Every lesson screen answers: What am I learning? What should I do now? How will I know I understand it?
5. **Predictable geometry.** Use a 720–800px reading measure, a stable left outline on desktop, and a bottom action bar that remains visible without forcing the learner to scroll back.
6. **Less dashboard theater.** Reduce decorative metrics and oversized promotional headings. Show progress only when it informs the next learning decision.

### Proposed token direction

```css
--background: #f5f5f7;
--surface: #ffffff;
--surface-muted: #f2f2f4;
--ink: #1d1d1f;
--muted: #6e6e73;
--line: #d2d2d7;
--accent: #0071e3;
--accent-strong: #0066cc;
--success: #248a3d;
--warning: #9a6700;
--radius-card: 16px;
--shadow-card: 0 4px 18px rgb(0 0 0 / 0.06);
```

Use the accent sparingly: primary buttons, active progress, links, and selected navigation. Do not use yellow cards for normal actions or green backgrounds for every selected state. Warning/preview states should use a compact status pill and a short explanation, not a large tinted banner.

### Student information architecture

```text
Home        → one recommended next action
Courses     → event → unit → skill → lesson
Practice    → skill practice → timed exam
Review      → mistakes, feedback, retry
```

The lesson reader should have no competing dashboard content: breadcrumb/back link, lesson title, progress, outline, content, and a persistent action bar. The source library belongs after or beside the guided lesson as “Sources used,” not as a substitute for teaching.

### Parent / admin visual hierarchy

Content Studio can use a denser operations layout than students:

- neutral left sidebar with Inbox, Sources, Author, Review, Releases;
- table/list views for throughput and status;
- a split-pane source viewer with page/section citations on the left and generated content on the right;
- explicit status chips: `Needs review`, `Extracting`, `Grounded draft`, `SME review`, `Preview`, `Published`;
- no decorative hero cards; use counts only for actionable queues.

### Accessibility and interaction requirements

- Maintain visible `:focus-visible` states and keyboard navigation.
- Use semantic buttons for actions and links for navigation.
- Keep headings balanced and source text readable at 200% zoom.
- Honor reduced motion; animate only opacity/transform for short transitions.
- Keep touch targets at least 44px and use `touch-action: manipulation`.
- Use `aria-live="polite"` for ingestion progress, saves, and review decisions.
- Never hide the primary lesson action below a large card or decorative footer.

This visual system should be implemented as a small token/component pass before adding more portal screens; otherwise the ingestion portal will inherit the current visual noise and students will continue to experience the product as an AI dashboard rather than a focused learning environment.

## Implementation status (2026-07-29)

The first vertical slice is implemented and verified in the application:

- Content Studio intake is available to content staff at the existing content-operations workspace.
- Staff can upload a PDF or UTF-8 text artifact with event mapping and a rights declaration.
- Staff can also import a public HTTPS page or YouTube URL; the import is queued as a durable job, stores captions only for YouTube, and remains quarantined until review.
- The upload is checksum-deduplicated, stored as an immutable artifact, and processed by a durable ingestion job.
- PDF pages and text sections are persisted as `SourcePassage` records with page/section locators.
- Scanned image uploads use Google Cloud Vision document OCR; page count and average block confidence are retained in `ExtractionAsset`, and provider/empty-text failures remain `needs_human_review`.
- Quarantined upload sources are excluded from the student material library.
- An admin can accept or reject an extracted upload; acceptance records rights status, approves the source, and marks the event mapping reviewed.
- Accepted sources can be sent to grounded authoring, which creates draft/editor-review lessons and never publishes automatically.
- A parent role has a separate private materials view and upload endpoint; parent submissions have an `intake_only` share scope and cannot access staff queues or approve content.
- Background jobs now carry leases/heartbeats and reclaim stale running jobs; ingestion is idempotent for completed runs.
- An end-to-end integration test exercises upload → background extraction → passage persistence → quarantine visibility → admin acceptance → student visibility.

The following design items remain explicit follow-on work rather than hidden behavior: real antivirus scanning, resumable chunked uploads, parent-to-student/team relationship approval, a dedicated split-pane source editor, and production worker heartbeat updates during long-running model calls. DOCX/PPTX XML extraction, URL/YouTube import, Google Vision OCR, extraction diagnostics, stale-job recovery, and block-level passage IDs are now supported.
