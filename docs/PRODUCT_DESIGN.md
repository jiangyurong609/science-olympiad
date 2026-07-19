# Science Olympiad Learning, Competition Simulation, and Adaptive Remediation Platform

**Document type:** Production system design  
**Audience:** Founders, principal engineers, ML engineers, content leads, curriculum experts, security/privacy reviewers, and operations teams  
**Status:** Implementation blueprint  
**Primary market:** U.S. Science Olympiad Division B and Division C students, coaches, schools, and parents  
**Product positioning:** Independent learning and competition-preparation platform; not an official Science Olympiad tournament administrator unless separately authorized

---

## 1. Executive Summary

This platform should be built as a **season-aware Science Olympiad preparation operating system** that can:

1. Gather, crawl, classify, and continuously update high-quality scientific and competition-related materials.
2. Understand the structure and educational characteristics of past competition materials without unlawfully reproducing protected questions.
3. Generate original competition-style lessons, drills, stations, tests, diagrams, datasets, answer keys, and scoring rubrics using large language models and deterministic scientific tools.
4. Validate every generated item for factual correctness, solvability, licensing, ambiguity, difficulty, and answer consistency before it reaches students.
5. Deliver realistic individual, partner, station-based, laboratory, and tournament-style exams.
6. Diagnose not only which questions a student missed, but **why** the student missed them.
7. Create and enforce a personalized remediation path until the student can successfully solve an equivalent but unseen problem.
8. Give coaches visibility into student mastery, recurring misconceptions, pacing, event readiness, and team-level risk.
9. Support annual event changes through a versioned event, rule, source, and assessment model.
10. Meet production requirements for child privacy, accessibility, security, reliability, auditability, and content provenance.

The product's long-term moat should not be an unreviewed bank of AI-generated questions. It should be the combination of:

- A legally and scientifically curated source graph.
- A detailed event and concept ontology.
- A high-quality item-generation and validation pipeline.
- Real student response and misconception data.
- A trusted editorial review network.
- A remediation engine that can prove students learned from their mistakes.
- A growing library of original, calibrated, competition-style assessments.

---

## 2. Product Principles

### 2.1 Learning, not question volume

The system should not optimize for the number of generated questions. It should optimize for:

- Factual accuracy.
- Competition relevance.
- Difficulty calibration.
- Diagnostic power.
- Student learning gain.
- Long-term retention.
- Transfer to unfamiliar problems.
- Coach trust.

### 2.2 Similarity of educational structure, not copying

The platform may model lawful characteristics of past competition materials, such as:

- Event format.
- Test length.
- Time pressure.
- Topic distribution.
- Cognitive skill distribution.
- Use of diagrams, tables, maps, specimens, or datasets.
- Number of stations.
- Typical answer types.
- Relative difficulty.
- Degree of multi-step reasoning.
- Scoring density.
- Common distractor patterns.
- Expected use of reference sheets.
- Balance of recall, application, analysis, and synthesis.

The platform must not reproduce protected stems, answer choices, diagrams, data, keys, or distinctive wording without permission.

The core generation objective is:

> Produce a new, original assessment that matches the target event's blueprint and educational demands while remaining independently authored, source-grounded, and demonstrably non-derivative.

### 2.3 Source-grounded generation

No production question should exist without one or more approved scientific sources, except for purely mathematical or deterministic items whose assumptions are fully stated and independently verifiable.

### 2.4 Human accountability

LLMs assist with drafting, transformation, explanation, tagging, and critique. Humans remain accountable for production publication, especially for:

- High-stakes mock exams.
- Ambiguous or subjective questions.
- Medical, epidemiological, or safety topics.
- Diagrams and specimen identification.
- Rubric-scored responses.
- Current-season event alignment.
- Questions based on copyrighted or licensed material.

### 2.5 Closed-loop remediation

An exam is not complete when a score is published. The platform must continue until each meaningful error has been:

1. Identified.
2. Classified.
3. Explained.
4. Remediated.
5. Retested with a new problem.
6. Rechecked after a delay.
7. Marked as resolved or still at risk.

---

## 3. User Roles and Experiences

## 3.1 Student

A student can:

- Register through a guardian, school, or coach.
- Join one or more teams.
- Select Division B or Division C.
- Choose current-season events.
- Complete onboarding and diagnostics.
- Follow an adaptive study plan.
- Study lessons, diagrams, flashcards, formula sheets, and worked examples.
- Practice by concept, event, question type, or difficulty.
- Take realistic timed mock competitions.
- Collaborate with an event partner.
- Upload handwritten work, lab reports, calculations, device logs, and diagrams.
- Review every missed or uncertain question.
- Complete required remediation.
- Retake equivalent unseen questions.
- Build a personal mistake notebook.
- Track mastery, retention, speed, and competition readiness.

## 3.2 Coach

A coach can:

- Create a school and team.
- Invite students and guardians.
- Assign students to events.
- Identify schedule and event conflicts.
- Assign lessons, drills, and exams.
- Run a full team mock tournament.
- Create private team resources.
- Review student errors and remediation status.
- Compare event readiness across students.
- Detect concepts with team-wide weakness.
- View pacing and time-management issues.
- Export reports.
- Control answer-key and solution release.
- Author or upload private questions subject to rights checks.

## 3.3 Parent or guardian

A parent or guardian can:

- Provide and manage consent.
- View appropriate progress summaries.
- Manage subscriptions.
- Request account data export or deletion.
- Manage communication preferences.
- Review safety and privacy settings.

The parent interface should avoid exposing unnecessary educational or social data.

## 3.4 Content author and reviewer

Editorial users can:

- Propose sources.
- Record rights and license information.
- Build event blueprints.
- Draft lessons and questions.
- Generate candidate questions with an LLM.
- Add diagrams and datasets.
- Review answer keys and rubrics.
- Run validation suites.
- Compare candidates against existing content.
- Approve, reject, quarantine, or withdraw content.
- Publish versioned content to staging or production.
- Respond to student challenges.

## 3.5 Tournament or school administrator

Administrators can:

- Configure exam windows.
- Assign proctors.
- Configure accommodations.
- Set release and embargo policies.
- Monitor exam status.
- Review audit events.
- Resolve appeals.
- Recalculate scores after corrections.
- Export official internal reports.

---

## 4. Scope of Event Coverage

The system must not encode Science Olympiad as a fixed list of courses. Events, topics, formats, and rules can change each season.

## 4.1 Top-level scientific domains

- Life science
- Anatomy and physiology
- Genetics and molecular biology
- Ecology and environmental science
- Epidemiology and public health
- Earth science
- Geology and mineralogy
- Oceanography and hydrology
- Meteorology and climate science
- Astronomy and space science
- Physics
- Chemistry
- Materials science
- Electricity and electronics
- Mechanical systems
- Engineering design
- Experimental design
- Data analysis and statistics
- Inquiry and scientific reasoning
- Mapping and remote sensing
- Cryptography and logic
- Technology and build events
- Scientific communication

## 4.2 Competition modalities

Each event version may use one or more modalities:

- Written exam.
- Timed stations.
- Identification.
- Laboratory practical.
- Experimental design.
- Team collaborative exam.
- Build and test.
- Device impound.
- Presentation.
- Oral defense.
- Map or image interpretation.
- Hybrid assessment.

## 4.3 Season-aware event representation

```text
Event
├── canonical_event_id
├── event_name
├── division
├── season
├── status
├── official_resource_links[]
├── topic_blueprint_version
├── skill_blueprint_version
├── competition_modalities[]
├── expected_team_size
├── expected_duration
├── permitted_material_profile
├── calculator_policy
├── scoring_model
├── tie_breaker_model
├── source_policy
└── editorial_notes
```

The system must retain old event versions so that historical student attempts remain reproducible.

---

# 5. Material Gathering, Crawling, and Knowledge Acquisition

Material acquisition is a first-class product subsystem, not a one-time scraping script.

## 5.1 Goals

The acquisition system should continuously discover and process:

- Official event pages.
- Official clarifications and corrections.
- Public event logistics resources.
- Public sample tests where reuse is authorized.
- Past competition materials where permission permits analysis.
- Publicly accessible practice exchanges, subject to their stated restrictions.
- Government scientific publications.
- Open educational resources.
- Open-access research and review articles.
- University lecture notes and laboratory manuals where licensed appropriately.
- Public-domain diagrams, images, maps, and datasets.
- Licensed third-party question banks.
- Contributor-authored tests.
- Coach- and school-supplied private content.
- Current scientific updates relevant to event topics.

## 5.2 Explicit source classes

Every source must be classified before use.

### Class A: Link-only official competition material

Examples:

- Official rules manuals.
- Paid official test packets.
- Official content with restrictive terms.
- Materials whose reproduction or automated reuse is not authorized.

Allowed uses:

- Store URL, title, season, event, publication date, checksum, and access status.
- Present a link to authorized users.
- Record high-level manually authored metadata.
- Use human-created event blueprints that do not copy protected expression.

Prohibited by default:

- Republishing text.
- Showing copied questions.
- Feeding full protected content into generation prompts.
- Training or fine-tuning a model on the material.
- Creating close paraphrases.
- Redistributing images or diagrams.

### Class B: Publicly viewable practice material with no tournament reuse

Examples include community test exchanges that state tests are for practice and may not be reproduced for future competitions.

Allowed uses depend on the stated terms and legal review. Safe default:

- Link to the original.
- Index metadata.
- Allow a human analyst to derive non-expressive aggregate features.
- Do not expose copied questions in generated exams.
- Do not use item text as few-shot examples in production generation.
- Do not create near-duplicate variants.

### Class C: Licensed competition material

Allowed according to contract:

- Student display.
- Internal analysis.
- Format modeling.
- Derivative generation.
- Commercial use.
- Limited-term or perpetual access.
- Attribution or royalty rules.

The license record must express exactly which actions are permitted.

### Class D: Open educational and open scientific material

Examples:

- Public-domain government works.
- Creative Commons resources.
- Open-access publications.
- Open datasets.

Usage depends on the exact license. The platform must enforce:

- Attribution.
- Noncommercial restrictions.
- Share-alike obligations.
- No-derivatives restrictions.
- Image-specific restrictions.
- Third-party content exceptions.

### Class E: Original platform material

Authored by staff, contractors, or contributors under a written agreement.

This is the preferred long-term source of lessons and assessments.

### Class F: User-private material

Uploaded by coaches, schools, or students.

The platform must:

- Ask the uploader to confirm rights.
- Keep it tenant-private by default.
- Exclude it from model training and public generation unless separately licensed.
- Support takedown and deletion.
- Scan for malware and sensitive data.

---

## 5.3 Source registry

Every discovered source is stored in a source registry.

```json
{
  "source_id": "src_01H...",
  "canonical_url": "https://example.org/resource",
  "title": "Resource title",
  "publisher": "Publisher",
  "authors": ["Author"],
  "source_class": "OPEN_EDUCATIONAL",
  "event_mappings": ["water-quality-b"],
  "season_mappings": ["2026"],
  "published_at": "2025-10-20",
  "retrieved_at": "2026-07-12T18:00:00Z",
  "content_type": "application/pdf",
  "content_hash": "sha256:...",
  "license_id": "lic_01H...",
  "rights_status": "APPROVED_WITH_ATTRIBUTION",
  "crawl_policy": "FULL_TEXT_ALLOWED",
  "generation_policy": "FACT_GROUNDING_ALLOWED",
  "display_policy": "EXCERPT_WITH_ATTRIBUTION",
  "review_status": "APPROVED",
  "last_checked_at": "2026-07-12T18:00:00Z"
}
```

## 5.4 License policy engine

No source enters retrieval, generation, or student delivery without a policy decision.

Policy outputs:

- `LINK_ONLY`
- `METADATA_ONLY`
- `INTERNAL_FEATURE_ANALYSIS_ONLY`
- `FULL_TEXT_RETRIEVAL_ALLOWED`
- `FACT_GROUNDING_ALLOWED`
- `DERIVATIVE_GENERATION_ALLOWED`
- `STUDENT_DISPLAY_ALLOWED`
- `COMMERCIAL_DISPLAY_ALLOWED`
- `MODEL_TRAINING_ALLOWED`
- `REQUIRES_ATTRIBUTION`
- `REQUIRES_HUMAN_APPROVAL`
- `BLOCKED`
- `QUARANTINED`

The default is deny.

## 5.5 Crawler architecture

```text
Source scheduler
    ↓
Robots and policy preflight
    ↓
Domain-specific connector
    ↓
Fetch raw artifact
    ↓
Virus and file safety scan
    ↓
Content hashing and deduplication
    ↓
Metadata extraction
    ↓
License and rights classification
    ↓
Parsing and structural extraction
    ↓
Scientific entity extraction
    ↓
Event and concept mapping
    ↓
Quality scoring
    ↓
Human review queue
    ↓
Approved source index
```

### Components

1. **Source Scheduler**
   - Periodically checks approved domains.
   - Supports event-driven re-crawl when a page changes.
   - Applies domain-specific rate limits.
   - Records fetch history.

2. **Policy Preflight**
   - Checks robots directives.
   - Checks source-specific terms.
   - Checks internal legal allowlist.
   - Prevents crawling blocked paths.
   - Supports manual override only through documented approval.

3. **Connectors**
   - HTML connector.
   - PDF connector.
   - Structured API connector.
   - RSS/Atom connector.
   - Sitemap connector.
   - Dataset connector.
   - Image and map connector.
   - Manual upload connector.

4. **Raw Artifact Store**
   - Immutable storage.
   - Versioning enabled.
   - Content-addressed hashes.
   - Encrypted.
   - Access controlled.
   - Retention policy based on rights.

5. **Parser**
   - Extracts headings, paragraphs, tables, equations, captions, references, and alt text.
   - Preserves page and section coordinates for citations.
   - Extracts images only when permitted.
   - Does not rely on OCR unless necessary.
   - Records extraction confidence.

6. **Change Detector**
   - Compares current and prior snapshots.
   - Separates cosmetic changes from substantive changes.
   - Triggers review for changes to dates, event topics, rules, corrections, formulas, and terminology.

7. **Scientific Entity Extractor**
   - Maps terms to canonical concepts.
   - Resolves synonyms.
   - Extracts formulas, units, constants, organism names, chemical names, geological names, and instrument names.

8. **Source Quality Scorer**
   - Authority.
   - Recency.
   - Citation completeness.
   - Scientific consensus.
   - Educational appropriateness.
   - License clarity.
   - Extraction quality.

9. **Review Queue**
   - Rights review.
   - Scientific review.
   - Event alignment review.
   - Accessibility review.
   - Image rights review.

## 5.6 Crawl frequency

Suggested cadence:

- Official event pages and clarifications: daily during competition season.
- Event logistics and resource pages: weekly.
- Government scientific sources: monthly or based on feed updates.
- Open educational sources: quarterly.
- Licensed sources: upon contract updates.
- Community practice exchanges: metadata checks monthly; no prohibited reproduction.
- Current scientific topics: weekly, with strict relevance and age-level filtering.

## 5.7 Preventing source poisoning

The source pipeline must defend against:

- SEO spam.
- AI-generated factual sludge.
- Malicious instructions embedded in documents.
- Prompt injection.
- Fabricated references.
- Stale or superseded scientific guidance.
- Unlicensed mirrors.
- Student answer dumps.
- Leaked active tournament materials.
- Personally identifiable information.
- Malware.

All source text must be treated as untrusted data. Retrieval documents must never be allowed to override system instructions.

---

# 6. Past Competition Material Analysis

## 6.1 Purpose

Past materials are useful for understanding the target distribution of competition assessments:

- Number and type of questions.
- Point allocation.
- Time demand.
- Topic frequency.
- Skill demand.
- Difficulty.
- Use of visual material.
- Station design.
- Partial-credit patterns.
- Common traps.
- Tie-breaker design.
- Expected depth.

The system should convert authorized materials into an **Assessment Style Profile**, not a reusable text corpus.

## 6.2 Assessment Style Profile

```json
{
  "event": "dynamic-planet",
  "division": "C",
  "season_range": ["2023", "2026"],
  "duration_minutes": 50,
  "median_question_count": 42,
  "question_type_distribution": {
    "single_select": 0.18,
    "short_answer": 0.28,
    "numeric": 0.16,
    "diagram": 0.14,
    "data_interpretation": 0.24
  },
  "cognitive_distribution": {
    "recall": 0.20,
    "application": 0.30,
    "analysis": 0.35,
    "synthesis": 0.15
  },
  "difficulty_distribution": {
    "foundational": 0.20,
    "regional": 0.45,
    "state": 0.25,
    "national": 0.10
  },
  "visual_density": 0.35,
  "multi_part_ratio": 0.40,
  "median_points_per_minute": 1.9,
  "common_task_families": [
    "interpret_cross_section",
    "calculate_rate",
    "identify_process",
    "compare_models"
  ]
}
```

## 6.3 Feature extraction restrictions

For link-only or restricted materials:

- Human reviewers may enter aggregate attributes.
- Automated systems should not retain or expose question text unless authorized.
- Derived profiles should be reviewed for excessive specificity.
- No distinctive phrases should enter prompts.
- No diagram should be reconstructed from a protected original.
- No answer-choice ordering or numeric values should be copied.

## 6.4 Similarity guard

Before publishing a generated item, compare it against:

- The platform's question bank.
- Licensed source items.
- Restricted-material fingerprints where legal review permits internal comparison.
- Public web text.
- Previously generated candidates.

Checks:

- Exact string similarity.
- Character and token n-gram overlap.
- Embedding similarity.
- Structural similarity.
- Shared uncommon numeric values.
- Shared uncommon entity combinations.
- Diagram perceptual similarity.
- Answer-choice similarity.
- Distinctive wording patterns.

Candidate outcomes:

- Pass.
- Rewrite required.
- Human review required.
- Blocked as likely derivative.

---

# 7. Scientific Knowledge Graph and Curriculum Model

## 7.1 Concept graph

The platform should maintain a graph rather than a folder tree.

```text
Concept
├── canonical_concept_id
├── preferred_name
├── synonyms[]
├── domain
├── definition
├── prerequisite_concepts[]
├── child_concepts[]
├── related_concepts[]
├── formulas[]
├── units[]
├── misconceptions[]
├── source_claims[]
├── event_mappings[]
├── season_mappings[]
└── learning_objectives[]
```

## 7.2 Claim-level grounding

Store scientific claims separately from source passages.

```text
ScientificClaim
├── claim_id
├── normalized_claim
├── scope_conditions
├── source_citations[]
├── confidence
├── consensus_status
├── valid_from
├── valid_until
├── supersedes_claim_id
└── reviewer_status
```

Examples:

- A physical equation and its assumptions.
- A biological process definition.
- A mineral property.
- A disease surveillance definition.
- A meteorological relationship.
- A statistical interpretation.

Questions and explanations should reference claim IDs, not only unstructured documents.

## 7.3 Learning objectives

Each event is decomposed into assessable objectives.

```text
Objective:
"Given a pedigree, infer the most likely mode of inheritance and justify the conclusion."

Prerequisites:
- genotype and phenotype
- dominant and recessive inheritance
- pedigree notation

Evidence of mastery:
- correct classification
- correct reasoning
- ability to reject alternatives
- completion within target time
```

---

# 8. LLM-Assisted Competition Material Generation

## 8.1 Generation outputs

The generation system should produce:

- Lessons.
- Study guides.
- Flashcards.
- Worked examples.
- Concept checks.
- Topic drills.
- Full-length written tests.
- Station sets.
- Laboratory scenarios.
- Experimental-design prompts.
- Diagram-labeling tasks.
- Data tables.
- Graph interpretation tasks.
- Map interpretation tasks.
- Team-based questions.
- Answer keys.
- Step-by-step explanations.
- Partial-credit rubrics.
- Common-error notes.
- Remediation exercises.
- Equivalent retest items.

## 8.2 Generation pipeline

```text
Assessment request
    ↓
Resolve event, season, division, level, and modality
    ↓
Load approved event blueprint
    ↓
Select learning objectives
    ↓
Retrieve approved factual claims and sources
    ↓
Select item archetype
    ↓
Generate candidate stem, assets, answer, and rubric
    ↓
Run deterministic solvers
    ↓
Run independent LLM critics
    ↓
Check factual claims against sources
    ↓
Check ambiguity and distractors
    ↓
Check similarity and rights
    ↓
Estimate difficulty and time
    ↓
Render and accessibility test
    ↓
Human editorial review
    ↓
Pilot and calibrate
    ↓
Publish versioned item
```

## 8.3 Prompt contract

The generation model must receive structured inputs, not a vague instruction.

```yaml
task: generate_assessment_item
event: heredity
division: B
season: 2026
objective: infer_mendelian_inheritance
difficulty_target: state
cognitive_level: analysis
question_type: multi_part_short_answer
estimated_time_seconds: 180
points: 6
approved_claim_ids:
  - claim_mendel_001
  - claim_pedigree_014
allowed_sources:
  - src_nih_genetics_001
prohibited_content:
  - copied competition wording
  - unsupported medical claims
  - trick ambiguity
required_outputs:
  - stem
  - response_schema
  - canonical_answer
  - alternate_acceptable_answers
  - scoring_rubric
  - step_by_step_solution
  - source_citations
  - misconception_tags
  - expected_time
  - difficulty_rationale
```

## 8.4 Multi-model review

Use separated roles:

1. **Generator**
   - Produces the candidate.

2. **Scientific verifier**
   - Checks each factual statement against approved claims and sources.

3. **Solver**
   - Solves the question independently without seeing the proposed answer.

4. **Ambiguity critic**
   - Searches for alternative interpretations and multiple correct answers.

5. **Assessment critic**
   - Checks alignment, difficulty, distractors, point allocation, and time.

6. **Rights and similarity critic**
   - Detects possible copying or excessive derivation.

7. **Pedagogy critic**
   - Checks age appropriateness and explanation quality.

The same model may perform several roles during early development, but prompts and context must remain isolated. For important exams, use model diversity and deterministic checks.

## 8.5 Answer generation requirements

Every question must include:

- Canonical answer.
- Acceptable alternatives.
- Unacceptable-but-common responses.
- Explanation.
- Source citations.
- Unit expectations.
- Significant-figure policy.
- Tolerance policy for numeric answers.
- Partial-credit rubric.
- Tie-breaking field if used.
- Confidence and review status.

## 8.6 Deterministic validation

Use tools rather than LLM judgment where possible:

- Symbolic algebra.
- Unit dimensional analysis.
- Numerical solvers.
- Chemical equation balancing.
- Statistical calculation.
- Graph generation and checking.
- Circuit simulation.
- Geometry.
- Date and astronomical calculations.
- Cryptographic encoders/decoders.
- Dataset schema validation.
- Formula recomputation.

A numeric candidate should be generated from a parameterized item family with a trusted solver.

```python
result = trusted_solver(parameters)
assert unit_check(result)
assert valid_range(result)
assert round_trip_check(parameters, result)
```

## 8.7 Parameterized item families

Store:

- Template.
- Parameter ranges.
- Constraints.
- Trusted solver.
- Renderer.
- Explanation template.
- Misconception distractor generators.
- Difficulty controls.
- Random seed.

This enables large numbers of unique but equivalent variants.

## 8.8 Diagram and data generation

Generated visual materials require additional controls:

- Provenance of base assets.
- Originality.
- Scientific labels.
- Scale and unit correctness.
- Legibility.
- Alt text.
- Screen-reader-compatible table equivalent.
- Color-independent encoding.
- Render snapshot tests.
- Human visual inspection.

For factual scientific imagery, prefer approved public-domain or licensed assets over unconstrained image generation.

## 8.9 Publication confidence levels

- **Draft:** AI-generated, unreviewed.
- **Machine-validated:** Passed automated checks.
- **Editor-reviewed:** Reviewed by trained content editor.
- **SME-approved:** Approved by subject-matter expert.
- **Calibrated:** Used in pilots with acceptable statistics.
- **Tournament-grade simulation:** SME-approved, calibrated, rights-cleared, and fully audited.

Students should not receive draft content in scored exams.

---

# 9. Question and Assessment Data Model

## 9.1 Question

```text
Question
├── question_id
├── question_family_id
├── version
├── lifecycle_status
├── generation_provenance
├── stem
├── assets[]
├── response_schema
├── answer_specification
├── scoring_rules
├── solution
├── hints[]
├── common_error_models[]
├── source_claim_ids[]
├── source_citations[]
├── license_record
├── event_mappings[]
├── objective_mappings[]
├── season_mappings[]
├── difficulty_estimate
├── cognitive_level
├── expected_time_seconds
├── exposure_metrics
├── similarity_report
├── validation_report
└── reviewer_signoffs[]
```

## 9.2 Supported response types

- Single choice.
- Multiple choice.
- Numeric.
- Unit-aware numeric.
- Scientific notation.
- Short answer.
- Extended response.
- Fill-in table.
- Matching.
- Ordering.
- Diagram labeling.
- Image hotspot.
- Graph plotting.
- Freehand annotation.
- Multi-part response.
- File upload.
- Laboratory report.
- Experimental-design report.
- Engineering log.
- Team response.

## 9.3 Immutable versions

Completed attempts must reference the exact content version shown to the student. Corrections create a new version; they do not mutate history.

---

# 10. Exam Blueprint and Assembly

## 10.1 Blueprint example

```yaml
event: disease-detectives
division: C
season: 2026
level: state
duration_minutes: 50
total_points: 100
team_size: 2

sections:
  - objective_group: epidemiologic_methods
    points: 25
    cognitive_mix:
      recall: 0.15
      application: 0.45
      analysis: 0.40

  - objective_group: data_interpretation
    points: 35

  - objective_group: outbreak_investigation
    points: 40

constraints:
  minimum_data_sets: 2
  minimum_multi_step_items: 4
  minimum_graph_items: 2
  maximum_item_family_overlap: 0
  maximum_recent_exposure: 0.10
  require_tie_breakers: true
```

## 10.2 Assembly validation

A generated exam must pass:

- Topic coverage.
- Objective coverage.
- Difficulty distribution.
- Cognitive distribution.
- Total points.
- Time budget.
- Item independence.
- No duplicate families.
- No excessive student exposure.
- Answer-key completeness.
- Asset completeness.
- Rights clearance.
- Accessibility.
- Expected score distribution.
- Security classification.

## 10.3 Exam forms

Generate multiple equivalent forms:

- Form A.
- Form B.
- Form C.
- Make-up form.
- Retest form.

Forms should match on:

- Blueprint.
- Expected difficulty.
- Expected completion time.
- Cognitive demand.
- Topic balance.

They should differ in stems, parameters, datasets, diagrams, and answer ordering.

---

# 11. Exam Delivery Engine

## 11.1 Modes

- Untimed practice.
- Timed topic drill.
- Full event simulation.
- Station rotation.
- Team attempt.
- Proctored school exam.
- Full mock tournament.
- Laboratory submission.
- Build-event documentation.

## 11.2 Exam state machine

```text
CREATED
→ SCHEDULED
→ READY
→ IN_PROGRESS
→ SUBMITTED
→ AUTO_SCORED
→ HUMAN_REVIEW
→ FINALIZED
→ RELEASED
→ REMEDIATION_OPEN
→ REMEDIATION_COMPLETE
→ ARCHIVED
```

## 11.3 Reliability requirements

- Server-authoritative timer.
- Local and remote autosave.
- Idempotent writes.
- Monotonic response sequence numbers.
- Offline response queue.
- Reconnect support.
- Duplicate-tab detection.
- Device-switch policy.
- Immutable submission record.
- Audit logging.
- Accommodation support.
- Proctor pause.
- Grace-period policy.
- Recovery after browser crash.

## 11.4 Team collaboration

Partner events require:

- Shared answer state.
- Presence indicators.
- Conflict-safe editing.
- Optional section ownership.
- Shared scratchpad.
- Individual action logs.
- Team submission.
- Coach-visible collaboration summary after release.

---

# 12. Scoring and Feedback

## 12.1 Scoring layers

1. Deterministic auto-scoring.
2. Rule-based short-answer normalization.
3. LLM-assisted rubric proposal.
4. Human review where required.
5. Challenge and appeal processing.

LLMs should not be the sole scorer for consequential free-response questions.

## 12.2 Confidence-aware scoring

Each score should record:

- Score.
- Maximum score.
- Scoring method.
- Scorer version.
- Confidence.
- Rubric version.
- Human override.
- Override reason.
- Audit timestamp.

## 12.3 Release package

After release, a student receives:

- Total score.
- Section scores.
- Time distribution.
- Mastery changes.
- Questions missed.
- Questions answered correctly with low confidence.
- Questions answered incorrectly with high confidence.
- Unattempted questions.
- Error categories.
- Required remediation.
- Suggested study sequence.
- Retest schedule.

---

# 13. Error Diagnosis Engine

The platform must diagnose **root causes**, not only mark answers wrong.

## 13.1 Error taxonomy

### Knowledge errors

- Missing fact.
- Incorrect concept.
- Confused terminology.
- Missing prerequisite.
- Outdated knowledge.

### Reasoning errors

- Incorrect inference.
- Unsupported assumption.
- Causal/correlation confusion.
- Failure to consider alternatives.
- Incomplete multi-step reasoning.
- Misapplied formula or principle.

### Calculation errors

- Arithmetic.
- Algebra.
- Unit conversion.
- Significant figures.
- Rounding.
- Formula substitution.
- Calculator input.

### Data and visual errors

- Misread graph.
- Misread table.
- Incorrect axis interpretation.
- Ignored scale.
- Incorrect map orientation.
- Diagram-label confusion.
- Specimen-identification confusion.

### Execution errors

- Misread prompt.
- Missed qualifier.
- Answered wrong subpart.
- Failed to show work.
- Formatting error.
- Time pressure.
- Left blank.
- Accidental click.

### Metacognitive errors

- Correct by guess.
- Incorrect with high confidence.
- Overconfidence.
- Underconfidence.
- Changed from correct to incorrect.
- Used hint excessively.
- Failed to verify.

### Collaboration errors

- Duplicate work.
- Partner conflict.
- Poor task division.
- Failure to communicate.
- Unreviewed teammate answer.

### Content-quality flags

- Possible ambiguous question.
- Multiple valid answers.
- Missing information.
- Broken asset.
- Incorrect key.
- Unfairly advanced content.

## 13.2 Evidence used for diagnosis

- Final answer.
- Intermediate work.
- Response revisions.
- Time spent.
- Confidence rating.
- Hint usage.
- Scratchpad.
- Calculator events where permitted.
- Uploaded work.
- Comparison with misconception models.
- Similar past errors.
- Student explanation.
- Partner action log.
- Item statistics.

## 13.3 Diagnosis workflow

```text
Incorrect or uncertain response
    ↓
Run deterministic error checks
    ↓
Compare against known misconception patterns
    ↓
Analyze work and response history
    ↓
Generate candidate diagnoses
    ↓
Ask student one short diagnostic question if needed
    ↓
Assign primary and secondary error categories
    ↓
Select remediation pathway
```

The student should be able to disagree with the diagnosis and provide an explanation.

---

# 14. Post-Exam Remediation System

## 14.1 Remediation contract

Every meaningful error creates a remediation case.

```text
RemediationCase
├── student_id
├── source_attempt_id
├── question_id
├── objective_id
├── primary_error_type
├── secondary_error_types[]
├── evidence[]
├── assigned_content[]
├── assigned_practice[]
├── status
├── first_retest_at
├── delayed_retest_at
├── resolution_confidence
└── coach_notes
```

## 14.2 Remediation sequence

### Step 1: Student self-explanation

Before revealing the full answer, ask:

- What approach did you use?
- Where do you think the error occurred?
- How confident were you?
- Which part of the question was unclear?

This encourages metacognition and improves diagnosis.

### Step 2: Targeted explanation

The system provides:

- The key concept.
- Why the student's approach failed.
- The correct approach.
- A short worked example.
- A warning about the specific misconception.
- Source-grounded references.

Do not overwhelm the student with a generic chapter.

### Step 3: Minimal prerequisite repair

If the error came from a missing prerequisite, assign the smallest required lesson first.

### Step 4: Guided correction

The student retries the original reasoning with:

- Socratic hints.
- Step checkpoints.
- Unit checks.
- Graph-reading prompts.
- Formula selection prompts.

### Step 5: Near-transfer practice

Give a new problem that uses the same concept with different surface features.

### Step 6: Far-transfer practice

Give a new problem that applies the concept in a less familiar context.

### Step 7: Delayed retrieval

Schedule another equivalent item after an interval.

### Step 8: Resolution

Mark resolved only when the student:

- Solves an unseen equivalent problem.
- Explains the reasoning.
- Meets the time target.
- Shows acceptable confidence calibration.
- Passes delayed review.

## 14.3 Remediation status

- `OPEN`
- `DIAGNOSING`
- `PREREQUISITE_REPAIR`
- `GUIDED_PRACTICE`
- `NEAR_TRANSFER`
- `FAR_TRANSFER`
- `DELAYED_REVIEW`
- `RESOLVED`
- `REOPENED`

## 14.4 Error notebook

Each student has a structured notebook:

- Original problem summary.
- Student's original answer.
- Correct answer.
- Root cause.
- Correct method.
- Personal takeaway.
- Similar problems completed.
- Last verified date.
- Risk of recurrence.

The notebook should support filters by:

- Event.
- Concept.
- Error type.
- Date.
- Severity.
- Resolution status.

## 14.5 Coach intervention triggers

Notify a coach when:

- The same misconception appears three times.
- A prerequisite remains unresolved.
- A student repeatedly runs out of time.
- Confidence remains poorly calibrated.
- A student fails delayed review.
- A question is challenged by several students.
- An entire team performs poorly on the same objective.

---

# 15. Adaptive Learning and Scheduling

## 15.1 Mastery state

```text
MasteryState
├── student_id
├── objective_id
├── mastery_probability
├── evidence_count
├── confidence
├── response_speed
├── retention_estimate
├── misconception_risk
├── last_practiced_at
├── next_review_at
└── model_version
```

## 15.2 Recommendation priority

```text
priority =
    event_weight
  × knowledge_gap
  × forgetting_risk
  × misconception_severity
  × expected_learning_gain
  × tournament_urgency
  × coach_assignment_weight
```

## 15.3 Daily plan

A daily plan may include:

- One overdue remediation.
- One spaced-retrieval set.
- One current-event lesson.
- One timed competition drill.
- One confidence reflection.

The system should cap workload and avoid repetitive fatigue.

---

# 16. AI Tutor

## 16.1 Tutor modes

- Explain.
- Socratic hint.
- Diagnose my error.
- Review my work.
- Quiz me.
- Generate a similar problem.
- Help me interpret a graph.
- Help me build a study sheet.
- Practice under time pressure.
- Coach partner communication.

## 16.2 Grounding

```text
Student request
    ↓
Resolve event, season, and learning objective
    ↓
Retrieve approved claims and lessons
    ↓
Apply active-exam restrictions
    ↓
Generate cited response
    ↓
Verify math and factual claims
    ↓
Return with uncertainty label
```

## 16.3 Exam integrity modes

- During scored exams: tutor disabled.
- During coach-approved open-resource exams: restricted retrieval only.
- During remediation: tutor enabled with progressive hints.
- Never reveal an unreleased answer key.

---

# 17. Content Review and Challenge Workflow

## 17.1 Publication workflow

```text
DRAFT
→ MACHINE_VALIDATED
→ EDITOR_REVIEWED
→ SME_APPROVED
→ PILOT
→ CALIBRATED
→ PUBLISHED
→ DEPRECATED
→ WITHDRAWN
```

## 17.2 Student challenge workflow

```text
Challenge submitted
    ↓
Severity triage
    ↓
Suspend item if severe
    ↓
Scientific and assessment review
    ↓
Decision
    ↓
Recalculate affected scores
    ↓
Update remediation records
    ↓
Notify affected users
    ↓
Publish correction note
```

## 17.3 Automatic content monitoring

Monitor:

- Challenge rate.
- Unexpectedly low discrimination.
- Unusual answer distributions.
- High omission rate.
- Excessive time.
- Multiple answer clusters.
- Sudden performance differences between groups.
- Citation changes.
- Source withdrawal.
- License expiration.

---

# 18. Technical Architecture

## 18.1 Architectural approach

Start with a **modular monolith** plus specialized asynchronous workers.

```text
Web clients
    ↓
API gateway / application backend
    ├── Identity and consent
    ├── Organizations and teams
    ├── Curriculum and content
    ├── Question bank
    ├── Exam delivery
    ├── Scoring
    ├── Remediation
    ├── Analytics
    └── Billing
         ↓
PostgreSQL / Redis / Object storage
         ↓
Workflow engine and workers
    ├── Crawling
    ├── Parsing
    ├── Rights classification
    ├── LLM generation
    ├── Scientific validation
    ├── Similarity detection
    ├── Rendering
    ├── Analytics
    └── Notifications
```

## 18.2 Suggested stack

### Web

- Next.js.
- TypeScript.
- React.
- TanStack Query.
- Accessible component system.
- KaTeX or MathJax.
- IndexedDB for local exam persistence.
- WebSocket or server-sent events.

### Backend

- NestJS or structured TypeScript application.
- PostgreSQL.
- Redis.
- Temporal for durable workflows.
- S3-compatible object storage.
- OpenSearch only when required.
- Python workers for scientific computation and ML pipelines.

### ML and retrieval

- Approved-source vector index.
- Keyword and metadata search.
- Claim graph.
- Model gateway with per-task routing.
- Prompt and model version registry.
- Offline evaluation harness.
- Embedding-based similarity service.
- Deterministic solver service.

### Infrastructure

- Managed cloud database.
- Container deployment.
- Terraform.
- CI/CD.
- OpenTelemetry.
- Sentry.
- Central logs.
- WAF and CDN.
- Secrets manager.
- Separate development, staging, and production.

---

# 19. Core Data Tables

```text
users
user_profiles
guardians
guardian_consents
organizations
teams
team_memberships

seasons
divisions
events
event_versions
objectives
concepts
concept_edges
event_objective_mappings

sources
source_snapshots
licenses
source_policies
scientific_claims
claim_citations
crawl_jobs
crawl_events
content_assets

lessons
lesson_versions
questions
question_versions
question_families
question_assets
question_validations
question_reviews
question_similarity_reports
rubrics

exam_blueprints
exam_forms
exam_form_items
exam_sessions
exam_participants
responses
response_revisions
scores
score_adjustments
challenges

error_diagnoses
remediation_cases
remediation_steps
mastery_states
review_schedule
mistake_notebook_entries

model_runs
prompt_versions
generation_jobs
generation_candidates
solver_runs
evaluation_results

audit_logs
security_events
notifications
subscriptions
data_requests
```

---

# 20. Security, Privacy, and Compliance

Because Division B includes students under 13, child privacy must be part of the product architecture.

Required controls:

- Verifiable guardian consent where applicable.
- School-managed account support.
- Data minimization.
- No behavioral advertising.
- No sale of student data.
- No general model training on identifiable student data.
- Tenant isolation.
- Role-based authorization.
- Encryption in transit and at rest.
- MFA for staff and coaches.
- SSO for schools.
- Data retention controls.
- Data export and deletion.
- Vendor and subprocessor inventory.
- Audit logs.
- Incident response.
- Penetration testing.
- Backup restoration drills.
- Moderated or disabled student messaging.
- Redaction of PII from model prompts.
- Regional data controls when required.

A qualified attorney should review COPPA, FERPA-related contracts, state student privacy laws, terms of service, contributor agreements, and content licenses before launch.

---

# 21. Accessibility

Target WCAG 2.2 AA.

- Keyboard access.
- Visible focus.
- Screen-reader-compatible math.
- Alt text and long descriptions.
- Accessible timers.
- Non-color-only charts.
- Adjustable text.
- Reduced motion.
- Captions and transcripts.
- Accessible drag-and-drop alternatives.
- Extended-time accommodations.
- Accessible diagrams and table equivalents.
- Human assistive-technology testing.

---

# 22. Observability and Auditability

Track:

- Crawl success and failures.
- Source changes.
- Rights decisions.
- Generation model and prompt version.
- Sources used for each item.
- Solver results.
- Review decisions.
- Exam state changes.
- Response-save latency.
- Score changes.
- Challenge outcomes.
- Remediation completion.
- Tutor citations.
- Security events.

Every published question should be reproducible from:

- Question version.
- Generation provenance.
- Prompt version.
- Model version.
- Approved source claims.
- Solver version.
- Reviewer decisions.

---

# 23. Testing Strategy

## 23.1 Software tests

- Unit tests.
- Integration tests.
- End-to-end tests.
- Authorization tests.
- Property-based tests.
- Load tests.
- Browser interruption tests.
- Offline recovery tests.
- Chaos tests.
- Backup restoration tests.

## 23.2 Content tests

- Answer recomputation.
- Unit checks.
- Formula checks.
- Alternative-answer analysis.
- Distractor quality.
- Similarity detection.
- Citation availability.
- Rights policy.
- Rendering.
- Accessibility.
- Reading level.
- Event blueprint alignment.

## 23.3 Model evaluation

Maintain a benchmark set for:

- Factual accuracy.
- Solvability.
- Answer-key consistency.
- Ambiguity.
- Difficulty targeting.
- Non-copying.
- Citation correctness.
- Remediation quality.
- Error diagnosis accuracy.

No model or prompt version enters production without offline evaluation and a controlled rollout.

---

# 24. Reliability Objectives

Initial targets:

- Standard application availability: 99.9%.
- Scheduled exam delivery availability: 99.95%.
- Response-save success: 99.99% or better.
- No accepted loss of submitted responses.
- P95 standard API latency below 400 ms.
- P95 autosave acknowledgment below 750 ms.
- Recovery point objective below five minutes.
- Recovery time objective below one hour initially.
- Versioned rollback for application and content releases.

---

# 25. Delivery Roadmap

## Phase 0: Legal, source, and taxonomy foundation

Build:

- Product naming and disclaimer.
- Source classes.
- License schema.
- Policy engine.
- Contributor agreement.
- Event and concept ontology.
- Initial official-link registry.
- Privacy and consent design.

Exit criteria:

- Every source has a policy decision.
- Restricted material cannot reach generation or student delivery.
- Event content is season-versioned.
- Counsel has reviewed core policies.

## Phase 1: Crawler and content platform

Build:

- Source scheduler.
- Domain connectors.
- Raw artifact store.
- Parsing.
- Change detection.
- Source review console.
- Claim extraction.
- Content authoring.
- Question authoring.

Exit criteria:

- Approved sources can be crawled and updated reproducibly.
- Every published object has provenance.
- License policy blocks unauthorized use.
- Source changes trigger review.

## Phase 2: Initial learning system

Build:

- Student and coach accounts.
- Guardian consent.
- Teams.
- Lessons.
- Topic practice.
- Diagnostics.
- Mastery tracking.
- Basic error notebook.

Exit criteria:

- Student can diagnose, study, practice, and review errors.
- Coach can assign and monitor.
- All content is versioned and cited.

## Phase 3: LLM generation and validation

Build:

- Model gateway.
- Structured generation prompts.
- Multi-agent review.
- Deterministic solvers.
- Similarity guard.
- Editorial queue.
- Parameterized item families.

Exit criteria:

- Generated items include answers, explanations, rubrics, and citations.
- Automated checks catch known failure classes.
- No draft item appears in scored exams.
- SME approval workflow works end to end.

## Phase 4: Production exam engine

Build:

- Blueprints.
- Timed exams.
- Autosave.
- Team attempts.
- Scoring.
- Rubrics.
- Proctoring.
- Appeals.
- Multiple equivalent forms.

Exit criteria:

- Network interruption causes no response loss.
- Timing is server authoritative.
- Score recalculation is audited.
- Forms meet equivalence thresholds.

## Phase 5: Closed-loop remediation

Build:

- Error diagnosis.
- Student self-explanation.
- Misconception matching.
- Targeted lessons.
- Guided correction.
- Near- and far-transfer generation.
- Delayed review.
- Coach alerts.

Exit criteria:

- Every missed objective can produce a remediation case.
- Students must demonstrate transfer before resolution.
- Delayed failures reopen cases.
- Coaches can see unresolved error risk.

## Phase 6: Event-specific modalities

Build:

- Station mode.
- Diagram labeling.
- Graphing.
- Lab report.
- Experimental design.
- Build notebooks.
- Device trial logs.
- Map and specimen workflows.

Exit criteria:

- At least one event in each major modality is credibly simulated.
- Event experts approve the workflows.
- Accessibility review passes.

## Phase 7: School-grade launch

Build:

- SSO.
- Rostering.
- Billing.
- School administration.
- Data-processing workflows.
- Support console.
- Status page.
- Disaster recovery.
- Security review.

Exit criteria:

- Penetration test completed.
- Privacy requests tested.
- Load target exceeded by at least 5x.
- Backup restoration verified.
- School onboarding is repeatable.

---

# 26. Initial Event Rollout

Do not launch every event superficially. Start with a representative set:

- Anatomy and Physiology.
- Heredity or Designer Genes.
- Disease Detectives.
- Astronomy or Reach for the Stars.
- Dynamic Planet.
- Meteorology.
- Rocks and Minerals.
- Chemistry Lab.
- Circuit Lab.
- Experimental Design.
- Codebusters.
- Water Quality.

For each launch event require:

- Complete event blueprint.
- Concept and prerequisite graph.
- Approved source set.
- Diagnostic assessment.
- Core lesson set.
- At least three full mock forms.
- Reviewed question families.
- Error and misconception taxonomy.
- Remediation content.
- SME signoff.
- Pilot statistics.

---

# 27. Production Acceptance Criteria

The system is ready for broad production only when:

1. No published question lacks source and rights metadata.
2. Restricted competition materials cannot enter generation prompts.
3. Every generated factual claim is traceable to approved sources.
4. Numeric questions are independently solved.
5. Ambiguity and similarity checks run automatically.
6. Scored exams use only reviewed content.
7. Every student response is durably saved.
8. Every score is reproducible.
9. Every material score correction is audited.
10. Every important error can create a remediation pathway.
11. A remediation case cannot close based only on reading an explanation.
12. Resolution requires success on an unseen transfer problem.
13. Delayed review can reopen apparent mastery.
14. Coaches can see unresolved misconceptions and pacing problems.
15. Child privacy, accessibility, security, and disaster-recovery reviews pass.

---

# 28. Principal Engineering Decisions

1. Treat acquisition, licensing, and provenance as core infrastructure.
2. Learn the assessment distribution of past materials without copying protected expression.
3. Store scientific claims and citations, not merely text chunks.
4. Use LLMs for candidate generation, not as the final authority.
5. Use deterministic tools for math, units, chemistry, statistics, circuits, and other computable domains.
6. Separate generator, solver, critic, and reviewer roles.
7. Require full answer specifications and rubrics.
8. Make question versions immutable.
9. Build error diagnosis and remediation into the exam lifecycle.
10. Measure transfer and retention, not just immediate correction.
11. Start with a modular monolith and durable worker workflows.
12. Launch deeply in a subset of events, then expand through reusable content and assessment primitives.
13. Make original, calibrated assessments and student misconception data the defensible long-term asset.

---

# 29. Reference and Policy Notes

The following public sources informed the platform constraints and should be rechecked during implementation:

- Science Olympiad official site and current event resources: https://www.soinc.org/
- Science Olympiad copyrights, media, and use terms: https://www.soinc.org/copyrights-media-and-use
- Science Olympiad preparation resources: https://www.soinc.org/preparation-tips
- Scioly.org Test Exchange: https://scioly.org/tests/
- Scioly.org Test Exchange usage warning: https://scioly.org/wiki/Scioly.org%3ATest_Exchange
- FTC COPPA Rule: https://www.ftc.gov/legal-library/browse/rules/childrens-online-privacy-protection-rule-coppa
- FTC COPPA compliance guidance: https://www.ftc.gov/business-guidance/resources/complying-coppa-frequently-asked-questions
- W3C WCAG 2.2: https://www.w3.org/TR/WCAG22/

These references do not replace legal advice. Rights, privacy, and competition rules must be reviewed against the current versions before launch.
