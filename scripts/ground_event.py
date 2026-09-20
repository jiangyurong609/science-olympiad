"""Phase 1b/1c — ground an event on rights-cleared open sources.

Grounding has never been run at scale, which is why substantive coverage sits at 0%. This
does the four steps for one event, idempotently:

  1. register the event's open-licensed reference sources (US federal works, public domain)
  2. fetch and snapshot them
  3. extract candidate claims and keep only those whose evidence excerpt is verifiably
     present in the retained snapshot
  4. attach each claim to the lesson blocks it actually supports, so coverage measures
     substance rather than a count

Only openly-licensed sources are used. Copyright-restricted material stays link-only and is
never a grounding source; see docs/MASTER_PLAN.md §1.

    PYTHONPATH=. python -m scripts.ground_event --event rocks-and-minerals-b --dry-run
    PYTHONPATH=. python -m scripts.ground_event --event rocks-and-minerals-b --apply
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import re
from collections import Counter

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import SessionLocal
from app.models.entities import (
    Concept, ContentGap, Course, Event, EventSourceMap, Lesson, LessonSkill, LessonVersion,
    ScientificClaim, Skill, Source, SourceSnapshot,
)
from scripts.open_sources import (
    BLOCKED_HOSTS, DOMAIN_SOURCES, DOMAIN_TERM_PATTERNS, domain_for_event,
    domain_terms_pattern, rights_for)

# Imported, not redeclared. These two scripts drifted: the audit began counting `checkpoint`
# as substantive while the grounder kept its own older set, so the grounder was not even
# attempting to ground the blocks the gate measures. A metric and the work aimed at it must
# read the same definition.
from scripts.audit_grounding import SUBSTANTIVE_BLOCKS
STOPWORDS = {
    "the", "and", "are", "for", "that", "with", "this", "from", "have", "which", "their",
    "when", "into", "than", "then", "them", "these", "those", "such", "each", "also", "can",
    "may", "one", "two", "how", "what", "why", "where", "some", "more", "most", "other",
    "you", "your", "its", "was", "were", "been", "has", "had", "will", "would", "about",
}
MIN_SENTENCE, MAX_SENTENCE = 60, 320
MIN_KEYWORD_OVERLAP = 3

# Government sites carry navigation and security boilerplate that is verbatim-present in the
# snapshot but asserts nothing about the subject. Provenance is not claimhood.
#
# Widened after reading what actually reached the claim table for Dynamic Planet: a CMS byline
# ("Watersheds and Drainage Basins Completed By Water Science School September 17, 2026"), a
# link menu ("• Water Science School HOME • Water Cycle Diagrams • Glossary of Water Cycle
# Terms"), a dataset promo repeated on every USGS page, Wikipedia's "[ edit ]" section markers
# and raw LaTeX from a formula. Each passed the old filter, sat in the pool as an approvable
# scientific claim, and would have grounded an exam question.
BOILERPLATE = re.compile(
    r"(skip to|official websites? use|share sensitive information|https?://|lock \(|"
    r"\.gov websites?|belongs to an official|secure websites?|cookie|javascript|"
    r"privacy policy|accessibility|last updated|contact us|sign up|subscribe|"
    r"national park (service|system)|park service|newsroom|press release|"
    # CMS furniture and dataset promos
    r"completed by|water science school|surface water data for the nation|"
    r"national water information system|data for the nation|"
    r"click (here|the)|read more|learn more about|related (topics|content)|"
    # navigation and markup
    r"\[\s*edit\s*\]|\{\\displaystyle|\|\s*\||^\s*[•·]|[•·].*[•·]|"
    r"^\s*(home|glossary|index|contents|references|see also|external links)\b)",
    re.I,
)
# A claim states something about the world. A heading glued to a sentence, a title-case
# fragment, or a citation-riddled line does not, however much subject vocabulary it carries.
NOT_A_STATEMENT = re.compile(
    r"^[A-Z][A-Za-z ]{0,60}(Completed|Overview|Introduction|Summary)\b|"     # heading + text
    r"(\[\s*\d+\s*\]\s*){2,}|"                                            # [1] [2] [3]
    r"^\s*[A-Z][a-z]+(\s+[A-Z][a-z]+){3,}\s*$"                              # Title Case Line
)

# The subject vocabulary a claim must use. Set per run from the event's domain — this was one
# hardcoded geology regex, so grounding a hydrology or physics event rejected nearly every
# candidate as "off_topic" and reported it as "no verified claims".
DOMAIN_TERMS = re.compile(DOMAIN_TERM_PATTERNS["geology"], re.I)


def set_domain_terms(domain: str) -> None:
    global DOMAIN_TERMS
    DOMAIN_TERMS = re.compile(domain_terms_pattern(domain), re.I)
    if domain not in DOMAIN_TERM_PATTERNS:
        print(f"   WARNING: no claim vocabulary tuned for domain {domain!r}; using the geology "
              f"pattern, which will reject most of this subject's sentences as off-topic")


# A proposition needs a verb doing assertive work.
PREDICATE = re.compile(r"\b(is|are|was|were|has|have|contains?|forms?|occurs?|consists?|"
                       r"produces?|causes?|results?|includes?|becomes?|creates?|"
                       r"appears?|ranges?|measures?|indicates?|means?)\b", re.I)


def is_claimlike(sentence: str) -> tuple[bool, str]:
    """Whether a scraped sentence is a scientific claim rather than site furniture."""
    if BOILERPLATE.search(sentence):
        return False, "boilerplate"
    if NOT_A_STATEMENT.search(sentence):
        return False, "not_a_statement"
    # A sentence carrying a date stamp or a bare measurement of the page itself is furniture.
    if re.search(r"\b(January|February|March|April|May|June|July|August|September|October|"
                 r"November|December)\s+\d{1,2},\s+\d{4}\b", sentence):
        return False, "boilerplate"
    if not DOMAIN_TERMS.search(sentence):
        return False, "off_topic"
    if not PREDICATE.search(sentence):
        return False, "not_a_proposition"
    if sentence.count(",") > 6 or sentence.isupper():
        return False, "list_or_heading"
    return True, "claimlike"


def _keywords(text: str, limit: int = 12) -> set[str]:
    words = re.findall(r"[a-z]{4,}", (text or "").lower())
    return {w for w, _ in Counter(w for w in words if w not in STOPWORDS).most_common(limit)}


def _fetch(url: str) -> tuple[str, str]:
    response = httpx.get(url, timeout=httpx.Timeout(45.0, connect=15.0),
                         follow_redirects=True,
                         # Wikipedia's policy requires a descriptive agent with contact
                         # details; a generic bot string is refused with 403.
                         headers={"User-Agent": (
                             "FieldstoneEducationalBot/1.0 (Science Olympiad learning "
                             "platform; +https://science-olympiad.com)")})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return str(response.url), text


def _sentences(text: str) -> list[str]:
    out = []
    for raw in re.split(r"(?<=[.!?])\s+", text):
        s = raw.strip()
        if MIN_SENTENCE <= len(s) <= MAX_SENTENCE and not s.endswith(":"):
            out.append(s)
    return out


def ensure_sources(db: Session, event: Event, apply: bool) -> list[Source]:
    domain = domain_for_event(event.slug)
    if not domain or domain not in DOMAIN_SOURCES:
        raise SystemExit(f"no open-source domain mapped for {event.slug!r}")
    spec = DOMAIN_SOURCES[domain]
    sources: list[Source] = []
    from urllib.parse import urlparse
    for url in spec["urls"]:
        if urlparse(url).netloc.lower() in BLOCKED_HOSTS:
            print(f"   skipping {url} — host refuses this crawler")
            continue
        # Rights come from a declared per-host rule, never from a hostname test at this call
        # site: federal works are public domain, CC-BY-SA references are cleared for *fact*
        # grounding with attribution and never for reproducing their expression, and anything
        # else must be declared before it can be used.
        rights = rights_for(url, spec)
        source = db.scalar(select(Source).where(Source.url == url))
        if source is None:
            if not apply:
                print(f"   would register {url}")
                continue
            source = Source(
                url=url,
                title=f"{rights['publisher']} — {domain} reference",
                rights_status=rights["rights_status"],
                approved=True,
                license_name=rights["license_name"],
                publisher=rights["publisher"])
            db.add(source); db.flush()
        elif apply:
            # make the rights explicit rather than assumed, and correct any earlier guess
            source.rights_status = rights["rights_status"]
            source.license_name = rights["license_name"]
            source.approved = True
        # Attach the source to the event. Grounding used to register sources and stop there,
        # which silently broke the other half of the pipeline: the course author selects its
        # passages with `EventSourceMap.event_id == event.id`, so a freshly grounded event had
        # 58 registered sources, thousands of extracted passages, and nothing an authoring run
        # could see. It looked identical to "no sources exist for this subject".
        if apply and not db.scalar(select(EventSourceMap).where(
            EventSourceMap.event_id == event.id,
            EventSourceMap.source_id == source.id,
            EventSourceMap.purpose == "fact_grounding",
            EventSourceMap.source_universe_version == domain,
        )):
            db.add(EventSourceMap(
                event_id=event.id, source_id=source.id, purpose="fact_grounding",
                source_tier=0, required=False, required_artifact_types=["parsed_text"],
                source_universe_version=domain, reviewed=True,
                notes=f"open {domain} reference registered by ground_event"))
        sources.append(source)
    if apply:
        db.flush()
    return sources


def ensure_snapshot(db: Session, source: Source, apply: bool) -> SourceSnapshot | None:
    existing = db.scalar(select(SourceSnapshot).where(
        SourceSnapshot.source_id == source.id
    ).order_by(SourceSnapshot.id.desc()))
    if existing and (existing.extracted_text or "").strip():
        return existing
    if not apply:
        print(f"   would fetch {source.url}")
        return None
    try:
        final_url, text = _fetch(source.url)
    except Exception as exc:
        print(f"   FETCH FAILED {source.url}: {type(exc).__name__}")
        return None
    if len(text) < 400:
        print(f"   too little text at {source.url} ({len(text)} chars)")
        return None
    digest = hashlib.sha256(text.encode()).hexdigest()
    # A body we have already stored under a DIFFERENT url is not a second source. Two ways
    # this happens, both measured rather than guessed at:
    #
    #   * a site serves the same page at several paths — `oceanservice.noaa.gov/facts/`
    #     returns byte-identical bodies for coral-reef, coralbleaching and why-care-about-
    #     corals, which counted one page three times;
    #   * a site serves its 404 as HTTP 200 — five NIAID urls each returned the same 8,807
    #     characters of navigation menu, which is long enough to pass every length threshold
    #     here and contains no science at all.
    #
    # Length cannot tell these apart from a real page; an identical hash can. Counting them
    # inflates a source set, and the second kind silently grounds a course in a nav bar.
    duplicate = db.scalar(select(SourceSnapshot).where(
        SourceSnapshot.content_hash == digest,
        SourceSnapshot.source_id != source.id,
    ))
    if duplicate is not None:
        other = db.get(Source, duplicate.source_id)
        print(f"   duplicate body at {source.url} — identical to "
              f"{other.url if other else duplicate.source_id}")
        return None
    snapshot = SourceSnapshot(source_id=source.id, final_url=final_url,
                              content_hash=digest, extracted_text=text)
    db.add(snapshot); db.flush()
    source.extracted_text = text
    source.content_hash = digest
    return snapshot


def harvest_claims(db: Session, event: Event, sources: list[Source], apply: bool,
                   approve: bool = False) -> list[ScientificClaim]:
    """Keep only claims whose evidence is verifiably in the snapshot AND that read as claims."""
    rejected: Counter[str] = Counter()
    concepts = db.scalars(select(Concept).where(Concept.event_id == event.id)).all()
    if not concepts:
        raise SystemExit(f"{event.slug} has no concepts to attach claims to")
    made: list[ScientificClaim] = []
    for source in sources:
        snapshot = ensure_snapshot(db, source, apply)
        if snapshot is None:
            continue
        text = snapshot.extracted_text or ""
        # One query for this source's existing claims, not one per candidate sentence. The
        # per-sentence lookup cost 120 round trips per source over a Cloud SQL proxy, which is
        # most of why a re-run of a 141-source event took as long as the first run did — and
        # re-runs are the normal case, because the scaffold has to change before grounding can
        # attach claims to the right concepts.
        existing_claims = {
            claim.evidence_excerpt: claim
            for claim in db.scalars(select(ScientificClaim).where(
                ScientificClaim.source_id == source.id))
        }
        for sentence in _sentences(text)[:120]:
            if sentence not in text:            # the audit's exact check
                continue
            ok, reason = is_claimlike(sentence)
            if not ok:
                rejected[reason] += 1
                continue
            words = _keywords(sentence)
            concept = max(concepts, key=lambda c: len(_keywords(c.name) & words))
            if not (_keywords(concept.name) & words):
                # Falling back to `concepts[0]` filed the claim under whichever concept
                # happened to sort first — by position, not by meaning. Those claims then read
                # as grounding for a concept nobody connected them to, and generation treats
                # them as authoritative context for it. A sentence that matches no concept is
                # not evidence for an arbitrary one.
                rejected["no_matching_concept"] += 1
                continue
            duplicate = existing_claims.get(sentence)
            if duplicate is not None:
                # A re-run must be able to change a claim's disposition. This used to `continue`
                # before the approval below, so `--approve` silently did nothing for any claim
                # that already existed: 187 claims sat on the right concepts, unapproved, and
                # generation refused every event for want of approved grounding. A second run
                # also re-files a claim whose concept assignment has since been corrected.
                if apply:
                    if approve and not duplicate.approved:
                        duplicate.approved = True
                    if duplicate.concept_id != concept.id:
                        duplicate.concept_id = concept.id
                made.append(duplicate)
                continue
            if not apply:
                continue
            claim = ScientificClaim(
                source_id=source.id, source_snapshot_id=snapshot.id, concept_id=concept.id,
                claim_text=sentence[:500], evidence_excerpt=sentence,
                locator=snapshot.final_url, confidence=0.8,
                # Extraction proposes; a human approves. Auto-approving scraped text was how
                # navigation fragments became "verified claims".
                approved=approve,
            )
            db.add(claim); db.flush()
            existing_claims[sentence] = claim
            made.append(claim)
        if apply:
            # Per source, not per run. A snapshot plus its claims is a complete unit of work:
            # committing it costs nothing if the next fetch dies, and NOT committing it meant
            # three separate grounding runs lost 40+ minutes of fetching to one dropped
            # connection, because the whole run sat in a single transaction until the end.
            db.commit()
    if rejected:
        print(f"   rejected candidates: {dict(rejected.most_common())}")
    return made


def _block_text(block: dict) -> str:
    """Every string a block teaches with, including those nested in lists and dicts."""
    parts: list[str] = []

    def walk(node) -> None:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key not in {"type", "claim_ids", "passage_ids", "id", "generated_by"}:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(block)
    return " ".join(parts)


def attach_to_blocks(db: Session, event: Event, claims: list[ScientificClaim], apply: bool) -> dict:
    """Attach claims to the blocks they support, so coverage reflects substance."""
    if not claims:
        return {"blocks": 0, "supported": 0}
    indexed = [(c, _keywords(c.evidence_excerpt, 16)) for c in claims]
    lessons = db.scalars(select(Lesson).where(Lesson.event_id == event.id)).all()
    total = supported = 0
    for lesson in lessons:
        version = db.scalar(select(LessonVersion).where(
            LessonVersion.lesson_id == lesson.id,
            LessonVersion.version == lesson.current_version,
        ))
        if version is None:
            continue
        content, used = copy.deepcopy(list(version.content or [])), set()
        changed = False
        for block in content:
            if block.get("type") not in SUBSTANTIVE_BLOCKS:
                continue
            total += 1
            # Nested strings count. This used to read only top-level string values, so a
            # summary — whose bullets live in `points`, a list — was matched on the words
            # "Closing Summary" alone, and a checkpoint on its heading rather than its
            # choices and explanation. 43 of 68 ungrounded blocks were summaries and
            # checkpoints whose actual content the matcher never saw.
            words = _keywords(_block_text(block), 40)
            scored = sorted(indexed, key=lambda pair: len(pair[1] & words), reverse=True)
            # A single shared word is coincidence, not evidence: "Official websites use .gov"
            # once counted as support for a crystal-systems block. Require real overlap that
            # includes subject vocabulary.
            best = [c for c, kw in scored[:2]
                    if len(kw & words) >= MIN_KEYWORD_OVERLAP
                    and any(DOMAIN_TERMS.search(w) for w in (kw & words))]
            if not best:
                continue
            supported += 1
            used.update(c.id for c in best)
            if apply and block.get("claim_ids") != [c.id for c in best]:
                block["claim_ids"] = [c.id for c in best]
                changed = True
        if apply and (changed or used):
            version.content = content
            flag_modified(version, "content")
            version.claim_ids = sorted(set((version.claim_ids or [])) | used)
    return {"blocks": total, "supported": supported}


def record_block_gaps(db: Session, event: Event, apply: bool) -> dict:
    """Record an explicit ContentGap for every teaching block open sources cannot support.

    Coverage below 100% is a fact about the available sources, not a reason to loosen the
    rule. Recording the shortfall keeps it visible and stops the course implying mastery it
    cannot yet support.
    """
    course = db.scalar(select(Course).where(Course.event_id == event.id))
    if not course:
        return {"unsupported": 0, "gaps": 0}
    lessons = db.scalars(select(Lesson).where(Lesson.event_id == event.id)).all()
    unsupported = gaps = 0
    current: dict[int, tuple[int, str]] = {}      # skill_id -> (missing count, lesson title)
    for lesson in lessons:
        version = db.scalar(select(LessonVersion).where(
            LessonVersion.lesson_id == lesson.id,
            LessonVersion.version == lesson.current_version,
        ))
        if version is None:
            continue
        missing = [b for b in (version.content or [])
                   if b.get("type") in SUBSTANTIVE_BLOCKS and not b.get("claim_ids")]
        if not missing:
            continue
        unsupported += len(missing)
        skill_link = db.scalar(select(LessonSkill).where(LessonSkill.lesson_id == lesson.id))
        if not skill_link:
            continue
        count, title = current.get(skill_link.skill_id, (0, lesson.title))
        current[skill_link.skill_id] = (count + len(missing), title)

    # Reconcile the whole ledger, rather than only adding to it. This used to `continue` past
    # any skill with nothing missing, so a gap opened once stayed open forever even after its
    # blocks were grounded — the records claimed 33 unsupported blocks while 9 actually were,
    # and `content_gap` could never clear. A gap ledger that only grows is not a record of
    # what is missing, it is a record of what was once missing.
    existing_gaps = db.scalars(select(ContentGap).where(
        ContentGap.course_id == course.id,
        ContentGap.gap_type == "ungrounded_blocks",
    )).all()
    by_skill = {gap.skill_id: gap for gap in existing_gaps}

    for skill_id, (count, title) in current.items():
        gaps += 1
        description = (f"{count} teaching block(s) in '{title[:60]}' have no "
                       "rights-cleared source support")
        gap = by_skill.get(skill_id)
        if not apply:
            continue
        if gap is None:
            db.add(ContentGap(
                course_id=course.id, skill_id=skill_id,
                gap_type="ungrounded_blocks", status="open", owner="content operations",
                description=description,
                resolution_notes=(
                    "Add rights-cleared sources covering these blocks before this skill can "
                    "claim mastery."),
            ))
        else:
            gap.description = description
            gap.status = "open"
            gap.resolution_notes = (
                f"{count} block(s) still unsupported; add sources before claiming mastery.")

    for skill_id, gap in by_skill.items():
        if skill_id in current or gap.status == "resolved":
            continue
        # every block this gap was opened for now cites a valid claim
        if apply:
            gap.status = "resolved"
            gap.description = f"{gap.description} — resolved: all blocks now cite a claim"
            gap.resolution_notes = (
                "Closed automatically: no teaching block for this skill lacks a claim. "
                "Reopened by the next run if that stops being true.")
    return {"unsupported": unsupported, "gaps": gaps}


def link_skills_and_record_gaps(db: Session, event: Event, apply: bool) -> dict:
    """Attach supporting claims to skills, and record an explicit ContentGap for any skill the
    open sources cannot support. A gap is an honest statement that mastery is not yet
    claimable — silence would imply coverage that does not exist."""
    course = db.scalar(select(Course).where(Course.event_id == event.id))
    if not course:
        return {"skills": 0, "supported": 0, "gaps": 0}
    skills = db.scalars(select(Skill).where(
        Skill.course_id == course.id, Skill.status != "withdrawn",
    )).all()
    supported = gaps = 0
    for skill in skills:
        lesson_ids = [l.lesson_id for l in db.scalars(select(LessonSkill).where(
            LessonSkill.skill_id == skill.id
        )).all()]
        claim_ids: set[int] = set()
        for lesson_id in lesson_ids:
            lesson = db.get(Lesson, lesson_id)
            if not lesson:
                continue
            version = db.scalar(select(LessonVersion).where(
                LessonVersion.lesson_id == lesson.id,
                LessonVersion.version == lesson.current_version,
            ))
            if version:
                claim_ids.update(c for c in (version.claim_ids or []) if isinstance(c, int))
        if claim_ids:
            supported += 1
            if apply:
                for claim in db.scalars(select(ScientificClaim).where(
                    ScientificClaim.id.in_(claim_ids), ScientificClaim.skill_id.is_(None)
                )).all():
                    claim.skill_id = skill.id
        else:
            gaps += 1
            if apply and not db.scalar(select(ContentGap).where(
                ContentGap.skill_id == skill.id, ContentGap.gap_type == "no_grounded_source"
            )):
                db.add(ContentGap(
                    course_id=course.id, skill_id=skill.id, gap_type="no_grounded_source",
                    status="open", owner="content operations",
                    description="No rights-cleared open source supports this skill yet",
                    resolution_notes=("Mastery cannot be claimed until a cleared source is "
                                      "added for this skill."),
                ))
    return {"skills": len(skills), "supported": supported, "gaps": gaps}


def main() -> None:
    ap = argparse.ArgumentParser(description="Ground an event on open sources")
    ap.add_argument("--event", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--approve", action="store_true",
                    help="approve harvested claims (otherwise they await human review)")
    args = ap.parse_args()
    apply = args.apply

    with SessionLocal() as db:
        event = db.scalar(select(Event).where(Event.slug == args.event))
        if not event:
            raise SystemExit(f"unknown event {args.event!r}")
        print(f"grounding {event.slug} ({'APPLY' if apply else 'dry-run'})")
        set_domain_terms(domain_for_event(event.slug) or "")
        sources = ensure_sources(db, event, apply)
        print(f"  open sources: {len(sources)}")
        claims = harvest_claims(db, event, sources, apply, approve=args.approve)
        print(f"  verified claims: {len(claims)}")
        stats = attach_to_blocks(db, event, claims, apply)
        print(f"  blocks supported: {stats['supported']}/{stats['blocks']}")
        block_gaps = record_block_gaps(db, event, apply)
        print(f"  ungrounded blocks recorded as gaps: {block_gaps['unsupported']} "
              f"across {block_gaps['gaps']} skill(s)")
        skill_stats = link_skills_and_record_gaps(db, event, apply)
        print(f"  skills supported: {skill_stats['supported']}/{skill_stats['skills']} "
              f"(content gaps recorded: {skill_stats['gaps']})")
        if apply:
            db.commit()
            print("  committed")


if __name__ == "__main__":
    main()
