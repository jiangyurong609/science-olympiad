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

### 2.6 Non-negotiable product loop

The first usable release must implement the complete learning loop for at least one event:

```text
Approved source discovery
    → rights decision and versioned ingestion
    → claim extraction with citations
    → competition-style profile and blueprint
    → original item plus answer and rubric generation
    → independent factual, solver, ambiguity, and similarity validation
    → human approval
    → student exam attempt
    → error diagnosis
    → targeted teaching and guided correction
    → unseen transfer problem
    → delayed retrieval
    → resolved, reopened, or coach escalation
```

An exam result without a remediation case for each meaningful error is incomplete. A generated question without approved evidence, a reproducible answer, and publication review is not student-ready. Material gathering is therefore production infrastructure on the critical path, not a back-office content task.

The system must preserve traceability across this loop. From any student response, an authorized reviewer must be able to navigate to the exact question version, answer-key version, generation and validation runs, supporting claims, source snapshots, rights decisions, error diagnosis, assigned remediation, and evidence used to close or reopen the case.

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

## 3.6 Required web application journeys

The production web application is not complete until the following journeys work end to end on desktop, tablet, and keyboard-only navigation.

### Student journey

1. Sign up or accept a guardian, coach, or school invitation.
2. Complete required email verification and guardian consent before accessing student data.
3. Join a team and select assigned events for the current season.
4. Take an event diagnostic and receive a prioritized learning plan.
5. Study a concept through cited lessons, worked examples, and short checks.
6. Complete individual or partner practice with autosave and resumability.
7. Take a realistic timed mock exam in the event's supported modality.
8. Review score, confidence, pacing, and error diagnoses according to the configured answer-release policy.
9. Complete every required remediation case through correction, transfer, and delayed review.
10. See readiness, retained mastery, open errors, and the next recommended action on one dashboard.

### Coach journey

1. Create or join an organization and verify the coach account.
2. Create teams, invite students and guardians, and assign event partners.
3. View consent and invitation state without seeing unnecessary private data.
4. Assign lessons, diagnostics, practice, or mock exams by student, pair, event, or team.
5. Schedule and monitor a team mock tournament, including accommodations and controlled answer release.
6. Review completion, scores, pacing, confidence, objective mastery, recurring misconceptions, and unresolved remediation.
7. Intervene on flagged cases, leave notes, reassign practice, and acknowledge alerts.
8. Compare readiness by event while avoiding simplistic ranking of minors.
9. Export an accessible progress report and an event-preparation plan.

### Content operations journey

1. Register and classify a source before fetching full text.
2. Review crawl history, snapshots, changes, parsing quality, and rights status.
3. Approve claims with exact evidence locators.
4. Generate content only from eligible claims and permitted style profiles.
5. Review validation, independent solution, citations, similarity, assets, and accessibility together.
6. Publish, withdraw, correct, and rescore versioned material with a complete audit trail.

Every page should make the next action obvious. Student dashboards should prioritize learning and unresolved errors; coach dashboards should prioritize students requiring intervention; editorial dashboards should prioritize rights, factual, and content-quality risk.

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

## 5.8 Production crawler completeness

The current concept of a crawler includes discovery, policy, fetching, parsing, review, and refresh. A URL fetcher alone does not satisfy this requirement.

Required capabilities:

- Seed registries for approved official, government, open-education, licensed, and manually contributed sources.
- Discovery through sitemaps, feeds, approved link traversal, structured APIs, and manual submissions.
- Per-domain crawl budgets, concurrency, backoff, retry, and contact information.
- Conditional requests using `ETag` and `Last-Modified` where supported.
- Streaming byte limits, decompression limits, page-count limits, timeouts, and file-signature validation.
- DNS and redirect revalidation at connection time to prevent SSRF and DNS-rebinding bypasses.
- HTTPS by default, with explicit reviewed exceptions.
- HTML, accessible text PDF, OCR review queue, table, image, dataset, and structured metadata extraction.
- Immutable raw artifacts plus immutable normalized snapshots; derived text must never be the only retained evidence when retention is permitted.
- Canonical URL detection, content hashing, near-duplicate detection, language detection, and version lineage.
- Page, section, table, figure, and character-span locators for every extracted claim.
- Change classification for rules, event scope, formulas, corrections, dates, and scientific facts.
- Tombstone, license-expiration, retraction, and source-withdrawal handling that propagates to dependent claims and questions.
- Malware scanning, prompt-injection labeling, PII detection, leak detection, and quarantine.
- Reviewer queues with service-level targets and explicit approve, reject, supersede, and escalate actions.
- Crawl observability: coverage, freshness, failures, blocked requests, bytes, duplicates, parse confidence, review backlog, and downstream impact.
- A replayable job model with idempotency, dead-letter handling, and no request-thread crawling in production.

Crawler acceptance tests must include redirects across domains, robots denial, DNS rebinding, oversized and compressed files, malformed PDFs, duplicate content, changed licenses, retracted claims, malicious embedded instructions, stale official rules, and downstream invalidation of published or draft content.

## 5.9 Meaning of comprehensive online coverage

The acquisition goal is to build the most complete, current, and auditable Science Olympiad information index practical for the supported events. It is not technically possible to prove that the system has found every relevant page on the public internet, and discovery does not grant permission to copy, retain, display, or use content for generation.

The crawler must therefore operate in two distinct stages:

1. **Broad discovery:** find and catalog potentially relevant URLs and artifacts, including metadata-only and link-only records.
2. **Policy-controlled ingestion:** fetch, retain, parse, index, display, and use content only to the extent allowed by robots directives, source terms, licenses, contracts, privacy requirements, and the source policy engine.

“Comprehensive” is measured against a maintained source universe, supported event blueprint, season, and freshness target. Unknown coverage must be shown as unknown rather than reported as complete.

## 5.10 Source universe

Maintain a versioned source-universe registry for every supported season, division, state, and event.

### Tier 0: Authoritative competition control sources

- Science Olympiad national home, event, policy, and preparation pages.
- Current Division B and C rules manuals, stored or displayed only as permitted.
- Official rules corrections, clarifications, event FAQs, and submitted-question responses.
- Official event logistics resources, permitted-material rules, calculator policies, and safety requirements.
- National event-supervisor, tournament-director, trial-event, and training resources.
- Official Science Olympiad store metadata and licensed products.
- State Science Olympiad organizations and their official regional or tournament pages.
- Tournament-specific schedules, adaptations, corrections, scoring notes, and published results where appropriate.

Tier 0 changes receive the highest recrawl priority. A rule correction or clarification must be capable of invalidating dependent blueprints, lessons, questions, rubrics, tutor answers, and scheduled exams.

### Tier 1: Primary scientific sources

- U.S. government science and health agencies, including NASA, NOAA, USGS, NIH, CDC, EPA, NIST, USDA, DOE, and relevant museums or observatories.
- Peer-reviewed open-access publications and authoritative consensus reports.
- Official datasets, APIs, technical manuals, maps, imagery, taxonomies, and reference tables.
- Event-specific scientific partners linked by official Science Olympiad pages.

### Tier 2: Open educational sources

- Appropriately licensed university, museum, public library, and nonprofit educational resources.
- Open textbooks, laboratory manuals, simulations, diagrams, specimen collections, and datasets.
- Resources with clear authorship, revision date, citations, and license terms.

### Tier 3: Competition-practice ecosystem

- Public invitational, regional, state, and national practice-material indexes.
- Scioly.org wiki and Test Exchange metadata, subject to their stated restrictions.
- Coach-created public resources, event guides, study notes, videos, and discussion archives.
- Historical event lists and public scoring or results information.

Tier 3 is discovery-first and high-risk. Default to metadata or link-only treatment until rights and scientific review explicitly authorize more. Community popularity is not evidence of factual correctness.

### Tier 4: Licensed and private sources

- Licensed test packets and question banks.
- Publisher content covered by contract.
- School, coach, and contributor uploads.
- Private team notes and student work.

Tier 4 content must remain within its contractual or tenant boundary and must never leak into public retrieval, generation, evaluation, or model training.

### Explicit exclusions and quarantine targets

- Leaked, embargoed, stolen, or active tournament materials.
- Student answer dumps intended to facilitate cheating.
- Pages containing personal information about minors without a valid product purpose.
- Pirated mirrors and unclear reuploads.
- Automatically generated content farms without reliable provenance.
- Content containing malware or instructions designed to manipulate retrieval or model behavior.

## 5.11 Discovery strategy

Use complementary discovery methods because no single method provides adequate coverage.

1. **Curated seeds**
   - Begin with manually reviewed national, state, tournament, government, scientific-partner, and open-education domains.
   - Assign each seed an owner, scope, trust tier, crawl policy, and expected update cadence.

2. **Standards-based discovery**
   - Read `robots.txt` according to RFC 9309 and discover declared sitemaps.
   - Parse sitemap indexes, XML and text sitemaps, RSS, Atom, JSON Feed, and publisher APIs.
   - Treat sitemap dates as discovery hints, not proof that content is unchanged.

3. **Scoped link traversal**
   - Traverse links from approved pages within configured depth, domain, path, file-type, and URL-budget limits.
   - Record out-of-scope external links as discovery candidates instead of automatically crawling them.
   - Score anchors, surrounding text, headings, and referring pages for event and concept relevance.

4. **Search-assisted discovery**
   - Run scheduled queries for each event, division, season, state, source type, correction, clarification, dataset, and scientific concept.
   - Search results create candidate records; they do not bypass rights review or domain approval.
   - Track query coverage and newly discovered domains over time.

5. **Structured registries and APIs**
   - Prefer official APIs and bulk datasets over page scraping when available.
   - Respect API licenses, quotas, pagination, deletion semantics, and attribution requirements.

6. **Human contribution**
   - Allow coaches, editors, students, and experts to suggest URLs without granting publication or crawl approval.
   - Record who suggested a source and why, but protect student identity from editorial users who do not need it.

7. **Gap-driven discovery**
   - Compare indexed claims and assets against every event blueprint objective.
   - Generate discovery tasks for objectives with weak authority, stale evidence, insufficient diagrams, missing datasets, or conflicting claims.

## 5.12 Crawl frontier and scheduling

Every candidate URL enters a persistent crawl frontier.

```text
Discovered
    → normalized and deduplicated
    → domain and rights preflight
    → scheduled
    → fetched
    → safety scanned
    → parsed
    → classified
    → reviewed when required
    → approved, link-only, blocked, quarantined, or superseded
    → monitored for change
```

Priority score inputs:

- Authority tier.
- Current-season and event relevance.
- Rule, correction, clarification, or safety status.
- Source freshness target and observed change rate.
- Number and importance of dependent claims and questions.
- Newness and uniqueness of the content.
- Event-blueprint coverage gap.
- Pending student challenge or coach report.
- License-expiration or retraction risk.
- Fetch cost, prior failures, and domain budget.

Use per-host queues with adaptive politeness. Honor explicit crawl delays where applicable, limit concurrency, apply exponential backoff with jitter, and suspend domains that return repeated throttling or abuse signals. Robots behavior must conform to RFC 9309; product policy may be stricter. A robots retrieval failure must not automatically authorize crawling high-risk or previously unknown domains.

## 5.13 Artifact and extraction model

Store the following separately:

```text
DiscoveredResource
├── canonical_url
├── discovered_url
├── referrer_url
├── discovery_method
├── discovery_query
├── domain_policy_id
├── source_tier
├── event_and_concept_candidates[]
└── frontier_status

FetchAttempt
├── request_and_redirect_chain
├── robots_decision
├── response_metadata
├── etag_and_last_modified
├── network_and_safety_results
├── failure_class
└── timing_and_byte_counts

RawArtifact
├── encrypted_object_key
├── cryptographic_hash
├── detected_media_type
├── malware_scan_result
├── retention_and_deletion_policy
└── access_policy

ParsedSnapshot
├── parser_and_version
├── document_structure
├── text_blocks_with_coordinates
├── tables_equations_figures_and_captions
├── accessibility_metadata
├── extraction_confidence
└── prior_snapshot_id
```

Parsing must preserve evidence location. A claim citation must identify the source snapshot and, where available, page, section, paragraph, table, figure, timestamp, cell range, or character span. OCR-derived evidence must carry OCR confidence and require review below a configured threshold.

## 5.14 Relevance, authority, and conflict resolution

Crawler output must not be treated as truth. Rank and review evidence using:

- Competition authority: national correction over clarification, clarification over unofficial interpretation.
- Scientific authority: primary agency or consensus source over tertiary summary.
- Season and jurisdiction: current national rules plus applicable state, regional, and tournament adaptations.
- Publication and revision time.
- Directness of support for the claim.
- Agreement with other independent authoritative sources.
- License and attribution clarity.
- Extraction quality.

Conflicting claims create a conflict record and block dependent generated content when the conflict could change an answer. Do not ask an LLM to silently choose between sources. A reviewer must resolve the conflict, scope it by season or jurisdiction, or mark it unresolved.

## 5.15 Coverage and freshness scorecard

Report coverage by season, division, event, objective, source tier, artifact type, state, and tournament jurisdiction.

Required metrics:

- Known authoritative domains reviewed versus expected.
- National, state, regional, and supported-tournament pages indexed.
- Current event pages, rules links, corrections, clarifications, FAQs, and logistics resources discovered.
- Event objectives with at least one current authoritative source.
- Event objectives with two independent sources where appropriate.
- Claims with exact evidence locators.
- Diagram, dataset, map, table, equation, and laboratory-resource coverage.
- Median and P95 age since last successful policy check and fetch.
- Change-detection latency for Tier 0 resources.
- Frontier size and age by state.
- Fetch, parse, OCR, classification, and review failure rates.
- Duplicate and near-duplicate rates.
- Rights-review and scientific-review backlog.
- Sources, claims, questions, and exams affected by changes or withdrawal.
- Search queries producing new relevant domains, used as a discovery-saturation indicator.

Coverage labels:

- `UNKNOWN`: source universe has not been reviewed.
- `DISCOVERING`: active discovery with material gaps.
- `BASELINE`: all known Tier 0 sources and minimum scientific grounding are covered.
- `STRONG`: blueprint objectives have current, authoritative, diverse evidence and required asset types.
- `MONITORED`: strong coverage plus functioning freshness and downstream invalidation targets.

No dashboard may display “100% of the internet.” It may display “100% of the reviewed Tier 0 source universe for Division C Astronomy, 2026, checked within the last 24 hours,” with the registry version and timestamp.

Initial service objectives:

- Tier 0 correction and clarification discovery: within 6 hours during the active season.
- Other Tier 0 change detection: within 24 hours during the active season.
- Tier 1 high-dependency source refresh: within 30 days or faster when feeds indicate change.
- Critical change impact analysis: within 15 minutes after an approved changed snapshot.
- No generated publication while a supporting critical claim is expired, withdrawn, materially conflicted, or awaiting impact review.

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

## 18.3 Firebase Authentication integration

Use **Firebase Authentication** as the identity provider for browser sign-up, sign-in, email verification, password reset, and approved federated login. Upgrade to Firebase Authentication with Identity Platform when multi-factor authentication, SAML/OIDC school SSO, multi-tenancy, blocking functions, or enterprise support is required.

Firebase owns authentication credentials. The platform database owns authorization and educational identity.

```text
Browser
    → Firebase sign-up/sign-in
    → verified Firebase ID token
    → HTTPS request to FastAPI with bearer token and App Check token
    → backend verifies token signature, issuer, audience, expiry, and revocation policy
    → lookup users.firebase_uid
    → enforce database role, organization, team, consent, and resource policy
    → serve authorized application data
```

Required behavior:

- Support email/password sign-up and sign-in, email verification, password reset, logout, and account recovery.
- Optionally support Google sign-in for families; school SAML/OIDC must be an organization-controlled feature.
- Never trust a role, organization ID, consent state, division, or team membership sent by the browser or stored only in client-visible token claims.
- Store an immutable unique `firebase_uid` on the local user record; do not use email as the authorization key.
- Provision the local profile idempotently on first verified login or invitation acceptance.
- Resolve account-linking and email-change conflicts explicitly; do not silently merge student records.
- Require verified email before coach, editor, administrator, invitation, or sensitive account actions.
- Require MFA for coaches, editors, and administrators; prefer phishing-resistant methods where the selected identity tier supports them.
- Check token revocation for sensitive operations and after role removal, account compromise, guardian withdrawal, or staff offboarding.
- Use Firebase custom claims only as a cache or coarse routing hint; database authorization remains authoritative.
- Enforce Firebase App Check on the custom backend after a monitored rollout, especially for authentication-adjacent, generation, upload, and crawl-management endpoints.
- Maintain separate Firebase projects and credentials for development, staging, and production.
- Keep Firebase service-account credentials only in a secret manager; never ship them to the browser or repository.
- Record authentication and authorization events without logging ID tokens, reset links, consent tokens, or sensitive student data.
- Provide emulator-based integration tests and production smoke tests for sign-up, verification, reset, token expiry, revoked token, disabled user, invitation acceptance, and tenant isolation.

Guardian consent is not equivalent to Firebase email verification. A student may authenticate successfully while the application still blocks learning records until required consent is granted. Disabling or deleting a Firebase identity must trigger an audited application-side access change and the applicable retention or deletion workflow.

Migration from the current local JWT system should use a temporary dual-auth period only in non-production or under a documented migration plan. New production accounts should not receive both a local password and a Firebase password.

---

# 19. Core Data Tables

```text
users
user_profiles
external_identities
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

The phases below describe capability growth, not permission to defer the core loop. Before expanding event breadth, the team must deliver a thin vertical slice for one carefully selected written event that includes source acquisition, grounded generation, human review, exam delivery, scoring, diagnosis, remediation, unseen transfer, and delayed review. Early implementations may use manual editorial steps, but may not omit provenance, answer verification, or remediation state.

## Mandatory first vertical slice

Build one complete event journey with:

- An approved, rights-classified source collection and reproducible crawl.
- A reviewed event blueprint derived only from permitted style features.
- Claim-level citations to immutable source snapshots.
- At least one parameterized item family with a trusted solver.
- A small reviewed question set containing full answer specifications and rubrics.
- One timed exam form with durable response capture.
- Error diagnosis for knowledge, reasoning, calculation, execution, and content-quality errors.
- A student correction flow with targeted explanation and guided retry.
- Near-transfer, far-transfer, and delayed-retrieval items.
- A coach view of open, resolved, reopened, and escalated misconceptions.

Exit criteria:

- A reviewer can trace every generated factual claim and answer to approved evidence.
- No restricted source text enters a generation prompt or student-visible asset.
- An intentionally wrong response creates and advances a remediation case automatically.
- Reading an explanation alone cannot close the case.
- Passing immediate and delayed unseen checks can close the case; failing either reopens or continues it.
- The entire journey is covered by an automated end-to-end test and an audit trail.

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
- Versioned source-universe registry.
- Persistent crawl frontier and per-domain budgets.
- Sitemap, feed, API, scoped-link, search-assisted, and manual-submission discovery.
- Domain connectors.
- Immutable raw artifact and parsed snapshot stores.
- Parsing.
- OCR, table, equation, figure, dataset, and locator extraction.
- Change detection.
- Retraction, deletion, license-expiration, and downstream invalidation workflows.
- Source review console.
- Claim extraction.
- Content authoring.
- Question authoring.
- Coverage and freshness scorecards.
- Crawl observability, replay, retry, and dead-letter operations.

Exit criteria:

- Approved sources can be crawled and updated reproducibly.
- Known Tier 0 sources for the first event are at `MONITORED` coverage.
- Discovery gaps and unknown coverage are visible and assigned.
- Every published object has provenance.
- License policy blocks unauthorized use.
- Source changes trigger review.
- Corrections, clarifications, withdrawals, and material scientific changes propagate to dependent content.
- Production crawling is asynchronous, idempotent, rate-limited, observable, and recoverable.

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

Do not launch every event superficially. The initial product should focus on a small cluster, prove source quality and student learning, and then expand through reusable event primitives.

Event names and availability vary by season. The platform may maintain subject libraries when an event is out of rotation, but it must label them as historical or foundational rather than presenting them as current competition requirements.

## 26.1 Launch cohort: identification and ecology

Begin with three subject families:

1. **Rocks and Minerals**
   - Mineral and rock identification.
   - Physical properties and diagnostic tests.
   - Formation processes, environments, uses, and hazards.
   - Photographs, specimen cards, tables, maps, and station-style questions.

2. **Entomology**
   - Insect anatomy, development, ecology, behavior, and classification.
   - Order and family identification at the depth required by the applicable season.
   - Image, specimen, dichotomous-key, range, habitat, and life-cycle tasks.
   - Clear separation between current official lists and broader enrichment material.

3. **Ecology**
   - Population, community, ecosystem, and conservation ecology.
   - Biomes, nutrient cycles, energy flow, succession, interactions, and human impacts.
   - Graphs, field observations, food webs, maps, datasets, and quantitative analysis.
   - Current-season ecosystem or topic emphasis where specified.

This cohort is intentionally coherent. It exercises reusable capabilities for taxonomy, hierarchical classification, visual identification, field evidence, maps, data interpretation, vocabulary, station timing, and source-grounded explanations without requiring the platform to solve every laboratory or build-event modality in its first release.

## 26.2 Cohort-one product scope

Each of the three subject families must include:

- A season- and division-specific event blueprint.
- An authoritative source map and monitored Tier 0 source set.
- A concept, prerequisite, specimen, and misconception ontology.
- Rights-cleared photographs, diagrams, maps, tables, and datasets.
- Searchable lessons, identification guides, glossaries, and worked examples.
- Adaptive flashcards and spaced retrieval.
- Image-based and text-based identification practice.
- Topic drills and station-mode practice.
- A diagnostic and personalized study plan.
- At least three reviewed full mock exams per supported division and season.
- Answers, acceptable alternatives, scoring rubrics, explanations, and citations.
- Student confidence capture and support for uploaded handwritten work.
- Error diagnosis and the complete remediation lifecycle.
- Coach assignments, event readiness, misconception alerts, pacing analysis, and progress reports.

Rocks and Minerals should be the first complete vertical slice because objective property tests and classification keys support strong deterministic validation. Ecology should follow to validate quantitative and data-interpretation workflows. Entomology should follow once the image-rights, taxonomy-versioning, and visual-similarity pipelines meet production standards.

## 26.3 Cohort-one release gates

Do not begin broad event expansion until:

- All known current Tier 0 sources for the supported cohort are at `MONITORED` coverage.
- Every blueprint objective has approved grounding and required asset coverage.
- Identification images have verified species or specimen labels, provenance, rights, and accessibility text.
- Taxonomic names and ranks are versioned and synonym-aware.
- Generated questions pass factual, answer, ambiguity, similarity, and visual-quality review.
- Mock-exam difficulty and timing have been piloted with representative Division B or C students.
- No known critical key, factual, rights, safety, or material ambiguity issue remains open at launch; the pilot editorial escape rate is below 0.5%, and every discovered issue is corrected, impact-assessed, and audited.
- Students can complete the entire diagnostic, learning, exam, review, transfer, and delayed-retention journey.
- Coaches can identify who needs help, on which concept, why, and what action remains.
- Retention and recurrence metrics demonstrate that remediation produces measurable improvement.
- Accessibility review covers images, specimen alternatives, color-independent encoding, keyboard operation, and timed accommodations.
- A subject-matter expert for each subject family signs off on the blueprint, source set, representative lessons, and mock forms.

## 26.4 Gradual expansion

Expand in cohorts, adding no more than two or three substantial event families at a time.

### Cohort 2: Adjacent identification and environmental events

- Forestry.
- Dynamic Planet.
- Water Quality.
- Meteorology.

Reuse taxonomy, specimen, map, graph, station, and environmental-data capabilities from the launch cohort.

### Cohort 3: Life and health science

- Anatomy and Physiology.
- Heredity or Designer Genes.
- Disease Detectives.

Add stronger medical-safety review, pedigree and genetics solvers, epidemiological calculations, and health-information controls.

### Cohort 4: Physical science and laboratory events

- Chemistry Lab.
- Circuit Lab.
- Optics or other current physical-science events.

Add laboratory workflows, equation and unit solvers, circuit simulation, safety checks, and richer partial-credit grading.

### Cohort 5: Inquiry, logic, and engineering preparation

- Experimental Design.
- Codebusters.
- Selected build events.

Add collaborative authoring, long-form rubrics, cryptographic validators, engineering notebooks, device trial logs, and coach-reviewed physical evidence. The platform must not imply that an online simulation replaces building and testing a physical device.

An event moves into the next cohort only when its official season status, source availability, rights-cleared asset supply, SME capacity, modality support, and validation strategy are known. Commercial demand alone is not sufficient.

## 26.5 Per-event completion definition

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

## 26.6 Production launch checklist for cohort one

Content completeness alone does not make the initial cohort production ready. Before admitting minors or school teams, require signoff in each area below.

### Product and user experience

- Firebase sign-up, sign-in, verification, recovery, logout, invitation acceptance, and staff MFA work end to end.
- Guardian consent and withdrawal are tested independently from authentication.
- Student, guardian, coach, editor, and administrator permissions are tenant-isolated.
- Student and coach journeys work on supported desktop, tablet, and mobile layouts.
- Exam autosave, resume, submit, scoring, answer release, challenge, and remediation flows have end-to-end tests.
- Empty, loading, offline, expired-session, late-submission, withdrawn-content, and service-failure states are designed and tested.

### Content and crawler operations

- Named content owner and backup SME exist for Rocks and Minerals, Ecology, and Entomology.
- Named source-policy owner monitors national, state, scientific, image, and community sources.
- Crawl frontier, freshness, rights review, scientific review, and extraction failures have dashboards and alerts.
- Tier 0 corrections and clarifications meet their detection target in a production-like environment.
- Editors can withdraw a source or question and identify every affected lesson, exam, answer, and student attempt.
- A correction runbook covers notification, exam pause, key revision, rescoring, remediation repair, and audit records.

### Reliability and security

- Production uses PostgreSQL, durable object storage, managed secrets, asynchronous workers, and isolated development, staging, and production environments.
- Database and artifact backups restore successfully in a timed exercise.
- Load tests cover concurrent sign-in, exam start, autosave, submission, scoring, and coach-dashboard traffic at five times the forecast peak.
- Penetration testing covers authentication, tenant isolation, uploads, crawler SSRF, prompt injection, authorization, and exam integrity.
- Rate limits, abuse controls, App Check, malware scanning, audit logging, alerting, and incident escalation are enabled.
- No secret, identity token, guardian-consent token, private student artifact, or restricted source text appears in logs or analytics.

### Privacy, safety, and accessibility

- Counsel has reviewed COPPA, school contracting, source rights, contributor terms, privacy notices, and retention policies.
- Data export, correction, consent withdrawal, account disablement, and deletion workflows pass production-like tests.
- Data collection is minimized by role and educational purpose.
- WCAG 2.2 AA review covers authentication, lessons, visual identification, exams, remediation, coach dashboards, and editorial tools.
- Timed accommodations, screen-reader alternatives, zoom, contrast, reduced motion, keyboard navigation, and non-color identification cues are verified.
- Safety-sensitive scientific guidance is reviewed and clearly distinguished from supervised physical procedures.

### Release and operations

- Each service and subject family has a named operational owner, escalation path, and on-call expectation.
- Dashboards cover availability, latency, errors, crawl freshness, job backlog, autosave success, scoring failures, content challenges, and remediation aging.
- Runbooks exist for identity-provider outage, crawler runaway, compromised source, wrong answer key, lost image rights, model-quality regression, exam outage, and suspected data exposure.
- Application, model, prompt, source-policy, question, and exam-form releases are versioned and independently reversible.
- Feature flags can disable model generation, new crawls, affected content, an event, or answer release without taking down unrelated learning.
- A staged launch begins with staff accounts, then invited coaches, then a small consented pilot, and only then broader enrollment.
- The first two weeks of each launch stage have daily review of student reports, content challenges, crawler changes, failed jobs, and unresolved remediation.

### Go/no-go authority

Launch requires recorded approval from product, engineering, security/privacy, content operations, and the SME for each enabled subject. Any owner may issue a no-go for an unresolved critical risk. Revenue or schedule pressure cannot override a known child-safety, privacy, rights, answer-key, or data-loss defect.

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

## 27.1 Learning-loop quality gates

These metrics must be reported by event, division, season, objective, item family, and publication-confidence level. Initial launch thresholds should be set from pilots and approved by the content and learning leads; they must not be silently weakened to increase question volume.

- **Grounding coverage:** percentage of student-visible factual claims linked to approved claim and source-snapshot records; target 100% for published generated material.
- **Answer reproducibility:** percentage of objective-answer items independently reproduced by a solver or second blinded solution; target 100% for scored exams.
- **Editorial escape rate:** percentage of published items later found to have a wrong key, material ambiguity, broken asset, or unsupported claim.
- **Similarity block rate:** candidates blocked or rewritten for excessive overlap, reported by source class and generator version.
- **Diagnosis agreement:** agreement between automated root-cause diagnosis and human-reviewed labeled samples.
- **Remediation initiation:** percentage of meaningful errors that create a remediation case; target 100% unless explicitly waived with an audited reason.
- **Remediation completion:** percentage of opened cases reaching a valid terminal state, with unresolved cases aging visibly rather than disappearing.
- **Transfer mastery:** percentage of cases passing an unseen far-transfer item without answer leakage or excessive hints.
- **Retention:** percentage of apparently resolved cases still passing delayed retrieval; failed checks must reopen the case.
- **Recurrence:** frequency of the same misconception after resolution, used to revise diagnosis, explanations, and practice selection.
- **Time-to-resolution:** median and tail time from error creation to demonstrated retained mastery.
- **Coach follow-through:** aging and acknowledgment of cases requiring human intervention.

Generated-content volume is an operational metric, not a success metric. The primary learning outcome is durable reduction in repeated, high-value errors on unseen problems.

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

# 29. Implementation Checkpoint and Enforced Release Gates

This section records what the current vertical implementation enforces. It is an engineering checkpoint, not a claim that the broad-production checklist in Section 26.6 has passed.

## 29.1 Initial subject rollout

The first cohort remains deliberately narrow:

1. **Rocks and Minerals** is the first complete learning, identification-lab, exam, and remediation vertical because observable properties support deterministic checking.
2. **Entomology** is the second identification vertical, but student-visible specimen assets remain blocked until taxonomy versioning, attribution, and derivative-use rights are verified.
3. **Ecology** is a foundational data-reasoning library and the first quantitative systems vertical. It must not be presented as a current national event unless the season-specific event registry proves that status.

Expansion to another event requires a reviewed event source map, named editor and SME, complete concept and misconception maps, release-ready source coverage, reviewed question inventory, three mock forms, and a pilot showing reliable scoring and remediation follow-through. Event count is not a launch metric.

## 29.2 Generated-question lifecycle now enforced

The application enforces the following path for scored content:

`draft → machine_validated → editor_reviewed → sme_approved → published`

- Human reviews are append-only and tied to the exact question version.
- Editorial approval requires checks for language clarity, a single best answer, plausible distractors, age appropriateness, and original wording.
- SME approval requires factual support, independent answer-key verification, verified citations, and no material ambiguity.
- The SME approver must be a different user from the editor for that version.
- Rejection or rewrite requests return the candidate to draft without deleting review history.
- Publication requires passed machine validation, approved snapshot-bound claim citations, citation/source consistency, and a non-blocked similarity report.
- Claim approval requires an exact evidence excerpt and locator tied to the immutable source snapshot; generation ignores legacy claims without that provenance.
- The content-operations web workspace exposes the role-specific queue, exact evidence excerpts, source links, snapshot hashes, answer, rationale, quality signals, checklists, notes, and publication action.
- Exam assembly selects only `published` questions. It returns a release-inventory error instead of generating or promoting missing items.

Calibration remains a post-publication operational gate before an item earns the separate **tournament-grade** designation described in Section 8.9. “Published for practice” must not be treated as “calibrated for high-stakes use.”

## 29.3 Crawler and evidence checkpoint

The implementation includes a policy-governed discovery frontier, HTTPS and public-IP enforcement, redirect revalidation, robots checks, domain/path allowlists, immutable snapshots and artifacts, source-change quarantine, freshness scheduling, body-free metadata monitoring for link-only sources, event source maps, and coverage scorecards. Restricted pages are monitored without persisting response bodies.

This does not mean “the entire Internet has been gathered.” Comprehensive coverage is achieved only when every required entry in a reviewed event source universe is monitored and its required artifacts are present. Production launch still requires real source-map population, OCR and structured-data extraction where authorized, alerting, operational ownership, and measured correction-detection service levels.

## 29.4 Current verification

- Database schema head: `0022_grounded_tutor`.
- Automated coverage includes editorial ordering, required checklists, role separation, snapshot provenance, evidence blockers, a positive editor-to-SME-to-publication-to-exam path, and prevention of unreviewed exam assembly.
- Browser JavaScript passes syntax validation.
- A clean migrated demo seed contains only the three launch subjects, snapshot-bound claims, independent review records, published questions, and exams assembled from those published versions. Fixture snapshots are labeled demo-only and do not satisfy live crawler coverage.

The remaining production work in Sections 24–27—managed PostgreSQL, durable workers and object storage, Firebase/App Check hardening, consent delivery and withdrawal, observability, load and penetration testing, accessibility certification, disaster recovery, legal review, content staffing, and pilot calibration—remains mandatory before broad deployment to minors or schools.

## 29.5 Exam release truthfulness

The application distinguishes 3 student-visible exam release classes:

- **Reviewed Practice** uses published, independently reviewed question versions. It may resemble competition structure but does not claim complete current-season coverage or psychometric calibration.
- **Foundational Practice** is automatically applied when a reviewed practice exam belongs to a foundational, archived, or otherwise non-current subject library. The student and coach interfaces state that it is not current-season competition coverage.
- **Competition Ready** requires a current-season event, every required source-map entry in the monitored state, and calibrated question inventory. The exam stores the coverage summary, source IDs, source-universe versions, and capture time used for its release decision.

If required coverage becomes stale, a new Competition Ready form cannot be released until monitoring recovers. Previously released forms retain their immutable coverage manifest for audit and can be withdrawn through the correction workflow. Unpublished exams are excluded from listings and cannot be started or assigned. Coaches see the release class before choosing an exam for a team.

The current demo seed deliberately creates Reviewed Practice forms for Rocks and Minerals and Entomology and a Foundational Practice form for Ecology. Its fixture snapshots are visibly demo-only and never qualify those forms as Competition Ready.

## 29.6 Evidence-backed item calibration

The `calibrated` lifecycle state is not trusted by itself. Competition Ready assembly requires an accepted immutable `QuestionCalibration` record for the exact question version. Each record captures the deterministic calculator version, thresholds, sample size, metrics, decision, independent reviewer, notes, and timestamp.

The first production calibration profile uses:

- At least 30 unique students, using only each student’s first scored exposure to reduce practice-repeat bias.
- Facility between 0.15 and 0.90.
- Corrected item-total discrimination of at least 0.15.
- Omission rate no greater than 0.05.
- Division B/C metadata on at least 80% of the sample.
- Supporting diagnostics for response time, option selection, confidence on correct and incorrect responses, and division mix.

These are conservative initial operational thresholds, not universal psychometric truths. A named assessment lead must revisit them after representative pilots, document any change, version the threshold profile, and never lower a threshold merely to increase inventory. Items with poor discrimination, extreme facility, excessive omissions, weak cohort metadata, or insufficient unique students remain Reviewed Practice even if their content review passed.

Calibration approval is restricted to an administrator or calibrator who did not provide the editor or SME approval for that version. The content-operations workspace presents exact metrics, ranges, failure reasons, option and confidence signals, and requires written decision notes. A manually changed question status without its accepted calibration record is rejected during Competition Ready exam assembly.

## 29.7 Content challenge and correction loop

Students can report a possible wrong key, ambiguity, factual error, broken asset, or accessibility barrier from the post-exam review. Every report is tied to the student, attempt, exam, question ID, and immutable question version. A student cannot create duplicate reports for the same item exposure, but staff can see the aggregate report count for that version.

The operational state machine is:

`submitted → triaged → upheld | not_upheld`

- Editor, SME, or administrator triage requires a severity and evidence note.
- High and critical triage quarantines the question, unpublishes every affected form, and places active attempts on content hold while preserving saved responses.
- A different administrator must resolve the challenge, preserving two-person control over a material correction.
- A rejected challenge restores the exact prior question, exam-publication, and active-attempt states unless another severe challenge still holds that version.
- An upheld challenge withdraws the question and keeps affected forms unpublished.
- `exclude_item` removes the item’s points from both score and maximum score for every submitted affected attempt.
- `correct_key` deterministically rescores every submitted response using the corrected answer specification.
- Every changed attempt receives an immutable before/after `ScoreCorrection` record. False remediation cases are voided; newly incorrect responses open a correction-specific remediation case so students still follow the error through transfer.
- Active attempts under an upheld challenge become `cancelled_content_correction`; under a rejected challenge they return to their prior in-progress state.
- Students see the public decision note in their report history. Internal evidence remains restricted to content operations and the audit trail.

The staff workspace exposes report counts, original choices and key, severity controls, student-facing and internal notes, correction type, corrected key, and impact totals. The student form uses plain-language categories and explains that the exact version is preserved. This implements the core sequence in Section 17.2.

## 29.8 Transactional student notifications

Material learning and scoring events now create an in-app `UserNotification` and an email `NotificationOutbox` row in the same database transaction. Notification creation uses a unique semantic deduplication key, so request retries cannot produce repeated student messages. Rolling back the educational action also rolls back its notification and delivery intent.

Notifications currently cover:

- A challenge entering triage.
- An active exam entering content hold.
- A challenge being upheld or not upheld.
- A completed exam receiving a score correction.
- A held attempt being resumed or cancelled.
- A coach publishing a team assignment.

The authenticated inbox is user-isolated, retains the 50 most recent messages, exposes unread count and localized timestamps, supports individual and bulk read state, and links to the relevant learning area. Student-facing text never includes internal triage notes. The header inbox is keyboard accessible, closes on Escape or outside interaction, announces asynchronous changes, and uses calm action-oriented language.

The worker processes email outbox records independently of the request. SMTP delivery records sent timestamps; provider or network errors persist a bounded error, retry with exponential delay, and become failed after 5 attempts. Development may set delivery to `disabled`, which records `suppressed` without losing the in-app message or falsely claiming delivery. Production startup requires SMTP configuration and a public application URL. A later provider adapter may add push or school messaging channels without changing transactional notification semantics.

## 29.9 Explainable daily learning missions

The student dashboard no longer selects a generic first exam. A deterministic server-side planner generates a subject-aware daily mission from current educational state:

1. Overdue or open remediation.
2. Coach assignments, weighted by time until due.
3. Spaced-retrieval reviews whose `next_review_at` has arrived, ordered by misconception risk.
4. An in-progress lesson before a new lesson, reducing context switching.
5. The next unfinished published lesson.
6. A reviewed timed form the student has not completed.

Every plan item includes its type, stable entity reference, title, concise purpose, plain-language “why now” explanation, estimated minutes, urgency label, action, route, priority, and event scope. Recommendations never rely on an unexplained model score. The current policy selects at most 3 distinct task types and targets no more than 35 minutes; a fixed-duration coach assessment may exceed the target and is labeled with its actual duration. This supports one remediation and one spaced review in the same plan while preventing repeated items of the same type.

The mission also reports active study days in the last 7 days, reviews due, pending assignments, and total estimated workload. Activity is derived from lesson views, submitted attempts, and practice sessions rather than self-reported streaks. The interface presents the mission as a calm evidence-based field plan: numbered steps, explicit urgency text, individual reasons, visible time estimates, large action targets, responsive layout, and an honest caught-up state. Selecting a lesson or retrieval task opens the exact item directly, including switching the active subject when required.

The current planner is intentionally deterministic and auditable. Later learning-model improvements must preserve the same explanation contract, workload safeguards, event/season scoping, and ability to reproduce why a task appeared at a given time.

## 29.10 Grounded learning tutor

Tutor sessions are persistent, student-owned, and bound to an exact published lesson version or the student’s own remediation case. Initial modes are Explain, Socratic Hint, Diagnose My Error, and Quiz Me. The session stores context type and ID, context version, concept, mode, status, and the approved grounding-claim set. Every user and assistant message is retained with provider/model provenance, citations, and a verification report.

The grounding pipeline is:

1. Authorize the student against the lesson or remediation case.
2. Reject the request if any scored attempt is active or on content hold.
3. Resolve the exact reviewed context version and concept.
4. Retrieve only approved claims linked to immutable source snapshots and approved sources.
5. Treat context and student text as untrusted data rather than instructions.
6. Ask the configured model for structured JSON containing the response, cited claim IDs, uncertainty, and follow-up question.
7. Reject uncited, out-of-set, empty, or excessive responses and use the deterministic grounded fallback.
8. Return exact source title, URL, evidence excerpt, locator, claim ID, and snapshot hash for every cited claim.

The deterministic fallback keeps tutoring available during provider outages without inventing science: it quotes one approved claim, frames an evidence-first hint or retrieval prompt, and asks the student to connect the claim to the activity. It does not masquerade as an LLM response. If any session claim is withdrawn or loses approval, the session enters `grounding_withdrawn` and stops. If the lesson version changes, the session enters `context_updated` and requires a fresh reviewed context.

The server enforces a configurable daily student-message cap in addition to general rate limiting. Sessions and histories are user-isolated. Tutor access remains disabled throughout active and content-held exams even if a client attempts the API directly. The tutor is currently enabled only in published lessons and remediation; practice-lab tutoring and open-resource exam modes require separate integrity policies before enablement.

The student interface presents the tutor as a focused source-grounded side panel rather than a generic chatbot. It includes explicit mode selection, suggested prompts, a grounding badge, distinct student/tutor messages, collapsible citation evidence, verification state, clear provider failure guidance, keyboard dismissal, mobile full-width layout, and direct entry from lessons and error-repair cards. The panel is absent from exam content and closes automatically when timed exam mode starts.

---

# 30. Reference and Policy Notes

The following public sources informed the platform constraints and should be rechecked during implementation:

- Science Olympiad official site and current event resources: https://www.soinc.org/
- Science Olympiad copyrights, media, and use terms: https://www.soinc.org/copyrights-media-and-use
- Science Olympiad preparation resources: https://www.soinc.org/preparation-tips
- Science Olympiad rules corrections and clarifications: https://www.soinc.org/rules-corrections-rules-clarifications
- Science Olympiad state organization discovery: https://www.soinc.org/join/state-websites
- Scioly.org Test Exchange: https://scioly.org/tests/
- Scioly.org Test Exchange usage warning: https://scioly.org/wiki/Scioly.org%3ATest_Exchange
- Robots Exclusion Protocol, RFC 9309: https://www.rfc-editor.org/rfc/rfc9309.html
- Sitemaps protocol: https://www.sitemaps.org/protocol.html
- FTC COPPA Rule: https://www.ftc.gov/legal-library/browse/rules/childrens-online-privacy-protection-rule-coppa
- FTC COPPA compliance guidance: https://www.ftc.gov/business-guidance/resources/complying-coppa-frequently-asked-questions
- W3C WCAG 2.2: https://www.w3.org/TR/WCAG22/

These references do not replace legal advice. Rights, privacy, and competition rules must be reviewed against the current versions before launch.
