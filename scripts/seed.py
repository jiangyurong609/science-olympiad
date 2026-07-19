import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models.entities import (
    BackgroundJob, Concept, CrawlDomainPolicy, Event, Exam, ExamItem, Lesson, LessonVersion,
    EventSourceMap, EventTaxonScope, Organization, PracticeSet, PracticeSetVersion, Question,
    QuestionReview, ScientificClaim, Source, SourceSnapshot, SpecimenAsset, Taxon, Team,
    TeamMembership, User,
)
from app.services.generation import generate_questions
from app.services.validation import build_similarity_report

Base.metadata.create_all(bind=engine)


def main():
    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.email == "admin@example.com"))
        if not admin:
            db.add(
                User(
                    email="admin@example.com",
                    full_name="Platform Admin",
                    password_hash=hash_password("AdminPass123!"),
                    role="admin",
                )
            )
        student = db.scalar(select(User).where(User.email == "student@example.com"))
        if not student:
            db.add(
                User(
                    email="student@example.com",
                    full_name="Demo Student",
                    password_hash=hash_password("StudentPass123!"),
                    role="student",
                    division="B",
                )
            )
        db.commit()
        editor = db.scalar(select(User).where(User.email == "editor@example.com"))
        if not editor:
            editor = User(
                email="editor@example.com", full_name="Demo Content Editor",
                password_hash=hash_password("EditorPass123!"), role="editor",
            )
            db.add(editor)
        sme = db.scalar(select(User).where(User.email == "sme@example.com"))
        if not sme:
            sme = User(
                email="sme@example.com", full_name="Demo Subject Reviewer",
                password_hash=hash_password("SmePass123!"), role="sme",
            )
            db.add(sme)
        db.commit()
        organization = db.scalar(select(Organization).where(Organization.slug == "fieldstone-demo"))
        if not organization:
            organization = Organization(name="Fieldstone Demo Academy", slug="fieldstone-demo")
            db.add(organization)
            db.commit()
            db.refresh(organization)
        student = db.scalar(select(User).where(User.email == "student@example.com"))
        if student and student.organization_id is None:
            student.organization_id = organization.id
        coach = db.scalar(select(User).where(User.email == "coach@example.com"))
        if not coach:
            coach = User(
                email="coach@example.com",
                full_name="Coach Rivera",
                password_hash=hash_password("CoachPass123!"),
                role="coach",
                organization_id=organization.id,
            )
            db.add(coach)
        elif coach.organization_id is None:
            coach.organization_id = organization.id
        db.commit()
        team = db.scalar(select(Team).where(
            Team.organization_id == organization.id,
            Team.name == "Varsity Green",
        ))
        if not team:
            team = Team(
                organization_id=organization.id,
                name="Varsity Green",
                division="B",
                season=2026,
                created_by_user_id=coach.id,
            )
            db.add(team)
            db.commit()
            db.refresh(team)
        for member, role in ((coach, "coach"), (student, "student")):
            if member and not db.scalar(select(TeamMembership).where(
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == member.id,
            )):
                db.add(TeamMembership(team_id=team.id, user_id=member.id, membership_role=role))
        db.commit()
        admin = db.scalar(select(User).where(User.email == "admin@example.com"))
        domain_policy_specs = [
            ("soinc.org", True, 0, "metadata_only", 5.0, 360, "Official competition control source"),
            ("nasa.gov", True, 1, "fact_grounding_allowed", 2.0, 43_200, "Primary science source"),
            ("noaa.gov", True, 1, "fact_grounding_allowed", 2.0, 43_200, "Primary science source"),
            ("usgs.gov", True, 1, "fact_grounding_allowed", 2.0, 43_200, "Primary science source"),
            ("nps.gov", True, 1, "fact_grounding_allowed", 2.0, 43_200, "Government education source"),
            ("epa.gov", True, 1, "fact_grounding_allowed", 2.0, 43_200, "Primary science source"),
            ("usda.gov", True, 1, "fact_grounding_allowed", 2.0, 43_200, "Primary science source"),
            ("scioly.org", False, 3, "metadata_only", 10.0, 43_200, "Community source pending explicit review"),
        ]
        for domain, enabled, tier, rights, delay, cadence, notes in domain_policy_specs:
            if not db.scalar(select(CrawlDomainPolicy).where(CrawlDomainPolicy.domain == domain)):
                db.add(CrawlDomainPolicy(
                    domain=domain,
                    enabled=enabled,
                    source_tier=tier,
                    default_rights_status=rights,
                    crawl_delay_seconds=delay,
                    recrawl_minutes=cadence,
                    notes=notes,
                    reviewed_by_user_id=admin.id if admin else None,
                ))
        db.commit()
        source_specs = {
            "general": ("https://science.nasa.gov/learn/basics-of-space-flight/chapter3-4/", "NASA educational science reference", "NASA", "fact_grounding_allowed"),
            "rocks-and-minerals": ("https://www.nps.gov/subjects/geology/rocks-and-minerals.htm", "Rocks and Minerals", "National Park Service", "fact_grounding_allowed"),
            "ecology": ("https://www.noaa.gov/education/resource-collections/marine-life/aquatic-food-webs", "Aquatic Food Webs", "National Oceanic and Atmospheric Administration", "fact_grounding_allowed"),
            "entomology": ("https://www.ars.usda.gov/plains-area/sidney-mt/northern-plains-agricultural-research-laboratory/pest-management-research/pmru-docs/grasshoppers-their-biology-identification-and-management/id-tools-apps/field-guide/fg-external-anatomy", "Field Guide to Common Western Grasshoppers: External Anatomy", "USDA Agricultural Research Service", "fact_grounding_allowed"),
            "entomology-images": ("https://www.ars.usda.gov/oc/images/photos/insects/", "USDA Insect Image Gallery", "U.S. Department of Agriculture", "metadata_only"),
            "entomology-official": ("https://www.soinc.org/entomology-c", "Entomology Event Overview", "Science Olympiad", "metadata_only"),
            "rocks-official": ("https://www.soinc.org/rocks-and-minerals-c", "Rocks and Minerals Event Overview", "Science Olympiad", "metadata_only"),
            "ecology-archive": ("https://www.soinc.org/ecology-c", "Ecology Archived Event Overview", "Science Olympiad", "metadata_only"),
            "season-2026": ("https://www.soinc.org/events/2026-event-table", "2026 National Event Table", "Science Olympiad", "metadata_only"),
        }
        sources = {}
        for key, (url, title, publisher, rights_status) in source_specs.items():
            source = db.scalar(select(Source).where(Source.url == url))
            if not source:
                source = Source(
                    url=url, title=title, publisher=publisher,
                    rights_status=rights_status,
                    license_name="US Government Work" if rights_status == "fact_grounding_allowed" else "pending review",
                    approved=True,
                )
                db.add(source)
                db.commit()
                db.refresh(source)
            sources[key] = source
        fixture_texts = {
            "general": "Repeated trials reduce the influence of random variation and improve experimental reliability.",
            "rocks-and-minerals": "Mineral identification uses observable and testable properties including hardness, streak, luster, cleavage, and fracture.",
            "ecology": "Ecologists describe energy flow through trophic levels and use carrying capacity to reason about populations and available resources. Food webs describe who eats whom and how energy flows; arrows point from prey to predator, and trophic levels begin with producers.",
            "entomology": "Adult insects have a head, thorax, and abdomen, with three pairs of legs attached to the thorax. Class Insecta has three body regions, three pairs of legs, one pair of antennae, and usually two pairs of wings.",
        }
        source_snapshots = {}
        for key, text in fixture_texts.items():
            source = sources[key]
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            snapshot = db.scalar(select(SourceSnapshot).where(
                SourceSnapshot.source_id == source.id,
                SourceSnapshot.content_hash == content_hash,
            ))
            if not snapshot:
                snapshot = SourceSnapshot(
                    source_id=source.id, final_url=source.url, content_hash=content_hash,
                    content_type="text/plain; charset=utf-8", byte_count=len(text.encode()),
                    extracted_text=text, metadata_json={"fixture": True, "student_release": "demo_only"},
                )
                db.add(snapshot)
                db.flush()
            source.content_hash = content_hash
            source.extracted_text = text
            source.metadata_json = {**(source.metadata_json or {}), "fixture": True}
            source_snapshots[source.id] = snapshot
        db.commit()
        event_specs = [
            (
                "rocks-and-minerals",
                "Rocks and Minerals",
                "B/C",
                "stations",
                "Mineral and rock properties, identification, formation, uses, and station strategy.",
            ),
            (
                "ecology",
                "Ecology",
                "B/C",
                "written_stations",
                "Populations, communities, ecosystems, biomes, cycles, and environmental data.",
            ),
            (
                "entomology",
                "Entomology",
                "B/C",
                "identification_stations",
                "Insect anatomy, development, ecology, behavior, classification, and identification.",
            ),
        ]
        for slug, name, division, modality, desc in event_specs:
            event = db.scalar(select(Event).where(Event.slug == slug, Event.season == 2026))
            if not event:
                event = Event(
                    slug=slug,
                    name=name,
                    division=division,
                    season=2026,
                    modality=modality,
                    description=desc,
                )
                db.add(event)
                db.commit()
                db.refresh(event)
            event.season_status = "foundational" if slug == "ecology" else (
                "current" if slug in {"rocks-and-minerals", "entomology"} else "unscoped"
            )
            db.add(event)
            db.commit()
            if not db.scalar(select(Concept).where(Concept.event_id == event.id)):
                concepts = {
                    "rocks-and-minerals": ["Observable properties", "Diagnostic tests", "Rock formation", "Station strategy"],
                    "ecology": ["Energy flow", "Population ecology", "Community interactions", "Biogeochemical cycles"],
                    "entomology": ["Insect anatomy", "Development and life cycles", "Classification", "Ecology and behavior"],
                    "meteorology": ["Atmospheric pressure", "Fronts", "Weather maps"],
                    "heredity": ["Mendelian inheritance", "Pedigrees", "Molecular genetics"],
                    "experimental-design": [
                        "Variables and controls",
                        "Reliability",
                        "Data analysis",
                    ],
                }[slug]
                db.add_all(
                    [
                        Concept(event_id=event.id, name=c, description=f"Core objective: {c}")
                        for c in concepts
                    ]
                )
                db.commit()
            for concept in db.scalars(select(Concept).where(Concept.event_id == event.id)).all():
                if not db.scalar(select(ScientificClaim).where(ScientificClaim.concept_id == concept.id)):
                    claim_specs = {
                        "rocks-and-minerals": (
                            "Mineral identification uses observable and testable properties including hardness, streak, luster, cleavage, and fracture.",
                            "Mineral properties and identification",
                        ),
                        "ecology": (
                            "Ecologists describe energy flow through trophic levels and use carrying capacity to reason about populations and available resources.",
                            "Ecosystem energy and population limits",
                        ),
                        "entomology": (
                            "Adult insects have a head, thorax, and abdomen, with three pairs of legs attached to the thorax.",
                            "Adult insect body plan",
                        ),
                    }
                    claim_text, locator = claim_specs.get(event.slug, (
                        f"{concept.name} is a core scientific concept for {event.name} preparation.",
                        "seeded curriculum reference",
                    ))
                    source = sources.get(event.slug, sources["general"])
                    db.add(ScientificClaim(
                        source_id=source.id, source_snapshot_id=source_snapshots[source.id].id,
                        concept_id=concept.id,
                        claim_text=claim_text,
                        evidence_excerpt=claim_text,
                        locator=locator, confidence=0.9, approved=True,
                    ))
            db.commit()
            source_map_specs = {
                "rocks-and-minerals": [
                    ("season-2026", "season_control", 0, ["metadata"], "National event availability and season"),
                    ("rocks-official", "rules_control", 0, ["metadata"], "Official event overview; rules manual remains controlling"),
                    ("rocks-and-minerals", "science_grounding", 1, ["raw_snapshot", "parsed_text", "claims"], "Physical properties and identification grounding"),
                ],
                "ecology": [
                    ("season-2026", "season_control", 0, ["metadata"], "Confirms Ecology is not a current 2026 national event"),
                    ("ecology-archive", "historical_rules_context", 0, ["metadata"], "Archived/foundational event context only"),
                    ("ecology", "science_grounding", 1, ["raw_snapshot", "parsed_text", "claims"], "Food-web and trophic-system grounding"),
                ],
                "entomology": [
                    ("season-2026", "season_control", 0, ["metadata"], "National event availability and season"),
                    ("entomology-official", "rules_control", 0, ["metadata"], "Official event overview; rules manual remains controlling"),
                    ("entomology", "science_grounding", 1, ["raw_snapshot", "parsed_text", "claims"], "External anatomy and hierarchy grounding"),
                    ("entomology-images", "specimen_imagery", 1, ["image"], "Candidate imagery; image-level rights and accessibility review required"),
                ],
            }.get(event.slug, [])
            for source_key, purpose, tier, artifacts, notes in source_map_specs:
                source = sources[source_key]
                if not db.scalar(select(EventSourceMap).where(
                    EventSourceMap.event_id == event.id,
                    EventSourceMap.source_id == source.id,
                    EventSourceMap.purpose == purpose,
                    EventSourceMap.source_universe_version == "2026.1",
                )):
                    db.add(EventSourceMap(
                        event_id=event.id,
                        source_id=source.id,
                        purpose=purpose,
                        source_tier=tier,
                        jurisdiction="national",
                        required=True,
                        required_artifact_types=artifacts,
                        source_universe_version="2026.1",
                        freshness_minutes=360 if tier == 0 else 43_200,
                        coverage_owner="content operations",
                        reviewed=True,
                        reviewed_by_user_id=admin.id if admin else None,
                        notes=notes,
                    ))
            db.commit()
            if event.slug == "entomology":
                anatomy_source = sources["entomology"]
                taxonomy_version = "usda-ars-field-guide-2026-07"
                insecta = db.scalar(select(Taxon).where(
                    Taxon.scientific_name == "Insecta",
                    Taxon.rank == "class",
                    Taxon.taxonomy_authority == "USDA ARS",
                    Taxon.taxonomy_version == taxonomy_version,
                ))
                if not insecta:
                    insecta = Taxon(
                        scientific_name="Insecta",
                        common_name="insects",
                        rank="class",
                        source_id=anatomy_source.id,
                        taxonomy_authority="USDA ARS",
                        taxonomy_version=taxonomy_version,
                        diagnostic_traits=[
                            "Three body regions: head, thorax, and abdomen",
                            "Three pairs of legs attached to the thorax",
                            "One pair of antennae",
                            "Jointed appendages and an exoskeleton",
                        ],
                        reviewed=True,
                    )
                    db.add(insecta)
                    db.flush()
                orthoptera = db.scalar(select(Taxon).where(
                    Taxon.scientific_name == "Orthoptera",
                    Taxon.rank == "order",
                    Taxon.taxonomy_authority == "USDA ARS",
                    Taxon.taxonomy_version == taxonomy_version,
                ))
                if not orthoptera:
                    orthoptera = Taxon(
                        scientific_name="Orthoptera",
                        common_name="grasshoppers, crickets, and katydids",
                        rank="order",
                        parent_id=insecta.id,
                        source_id=anatomy_source.id,
                        taxonomy_authority="USDA ARS",
                        taxonomy_version=taxonomy_version,
                        diagnostic_traits=[
                            "Chewing mouthparts",
                            "Leathery forewings called tegmina",
                            "Hind legs commonly enlarged for jumping",
                            "Gradual metamorphosis through egg, nymph, and adult",
                        ],
                        reviewed=True,
                    )
                    db.add(orthoptera)
                    db.flush()
                acrididae = db.scalar(select(Taxon).where(
                    Taxon.scientific_name == "Acrididae",
                    Taxon.rank == "family",
                    Taxon.taxonomy_authority == "USDA ARS",
                    Taxon.taxonomy_version == taxonomy_version,
                ))
                if not acrididae:
                    acrididae = Taxon(
                        scientific_name="Acrididae",
                        common_name="short-horned grasshoppers",
                        rank="family",
                        parent_id=orthoptera.id,
                        source_id=anatomy_source.id,
                        taxonomy_authority="USDA ARS",
                        taxonomy_version=taxonomy_version,
                        diagnostic_traits=[
                            "Short antennae",
                            "Tympanum on the first abdominal segment",
                            "Three-segmented tarsi",
                        ],
                        reviewed=True,
                    )
                    db.add(acrididae)
                    db.flush()
                for taxon in (insecta, orthoptera, acrididae):
                    if not db.scalar(select(EventTaxonScope).where(
                        EventTaxonScope.event_id == event.id,
                        EventTaxonScope.taxon_id == taxon.id,
                        EventTaxonScope.list_version == "foundations-2026-07",
                    )):
                        db.add(EventTaxonScope(
                            event_id=event.id,
                            taxon_id=taxon.id,
                            designation="foundational",
                            division=event.division,
                            season=event.season,
                            list_version="foundations-2026-07",
                            notes="Foundational anatomy and hierarchy; not a claim of current official-list inclusion.",
                            reviewed=True,
                        ))
                candidate_url = (
                    "https://www.ars.usda.gov/ARSUserFiles/30320505/grasshopper/Guide/Images/fig1.jpg"
                )
                candidate_hash = hashlib.sha256(candidate_url.encode()).hexdigest()
                if not db.scalar(select(SpecimenAsset).where(
                    SpecimenAsset.taxon_id == acrididae.id,
                    SpecimenAsset.source_url == candidate_url,
                    SpecimenAsset.content_hash == candidate_hash,
                )):
                    db.add(SpecimenAsset(
                        taxon_id=acrididae.id,
                        source_id=sources["entomology-images"].id,
                        source_url=candidate_url,
                        media_type="image/jpeg",
                        rights_status="metadata_only",
                        license_name="pending image-level review",
                        attribution="USDA ARS Field Guide to Common Western Grasshoppers",
                        alt_text="Candidate grasshopper anatomy figure; not published to students pending review.",
                        long_description="Candidate diagram of a female grasshopper with external structures; detailed accessibility description requires editorial verification.",
                        content_hash=candidate_hash,
                        review_status="pending",
                        taxon_verified=True,
                    ))
                db.commit()
            if event.slug == "entomology":
                anatomy_concept = db.scalar(select(Concept).where(
                    Concept.event_id == event.id,
                    Concept.name == "Insect anatomy",
                ))
                anatomy_source = sources["entomology"]
                anatomy_claim_text = (
                    "Insects have three body regions and three pairs of legs attached to the thorax; "
                    "external anatomy provides evidence for classification and identification."
                )
                anatomy_claim = db.scalar(select(ScientificClaim).where(
                    ScientificClaim.source_id == anatomy_source.id,
                    ScientificClaim.claim_text == anatomy_claim_text,
                ))
                if not anatomy_claim:
                    anatomy_claim = ScientificClaim(
                        source_id=anatomy_source.id,
                        source_snapshot_id=source_snapshots[anatomy_source.id].id,
                        concept_id=anatomy_concept.id if anatomy_concept else None,
                        claim_text=anatomy_claim_text,
                        evidence_excerpt=(
                            "Class Insecta has three body regions, three pairs of legs, one pair of "
                            "antennae, and usually two pairs of wings."
                        ),
                        locator="External Anatomy; Table 1 taxonomic hierarchy",
                        confidence=0.95,
                        approved=True,
                    )
                    db.add(anatomy_claim)
                    db.flush()
                lesson = db.scalar(select(Lesson).where(
                    Lesson.event_id == event.id,
                    Lesson.slug == "read-the-insect-body-plan",
                ))
                if not lesson:
                    lesson = Lesson(
                        event_id=event.id,
                        concept_id=anatomy_concept.id if anatomy_concept else None,
                        slug="read-the-insect-body-plan",
                        title="Read the Insect Body Plan",
                        summary="Use body regions, appendage location, development, and hierarchy as identification evidence.",
                        status="published",
                        current_version=1,
                        sequence=1,
                        estimated_minutes=14,
                    )
                    db.add(lesson)
                    db.flush()
                    citation = {
                        "title": anatomy_source.title,
                        "publisher": anatomy_source.publisher,
                        "url": anatomy_source.url,
                        "source_id": anatomy_source.id,
                        "claim_ids": [anatomy_claim.id],
                    }
                    db.add(LessonVersion(
                        lesson_id=lesson.id,
                        version=1,
                        review_status="sme_approved",
                        claim_ids=[anatomy_claim.id],
                        citations=[citation],
                        content=[
                            {
                                "id": "opening",
                                "type": "opening",
                                "kicker": "Morphology method 01",
                                "heading": "Identify Structure Before Color",
                                "body": "External anatomy supplies stable identification evidence. Begin with body regions and the location of legs, wings, antennae, and mouthparts.",
                            },
                            {
                                "id": "body-regions",
                                "type": "property_cards",
                                "heading": "Map Each Structure to Its Region",
                                "body": "Location matters: a correct structure assigned to the wrong body region leads to a weak identification.",
                                "cards": [
                                    {"name": "Head", "cue": "Sense and feed", "detail": "Bears antennae, eyes, and mouthparts."},
                                    {"name": "Thorax", "cue": "Move", "detail": "Three thoracic segments bear all three pairs of true legs and, when present, wings."},
                                    {"name": "Abdomen", "cue": "Digest and reproduce", "detail": "Contains most digestive and reproductive structures and may bear diagnostic appendages."},
                                    {"name": "Exoskeleton", "cue": "Support and protect", "detail": "A jointed, segmented external skeleton is an arthropod characteristic."},
                                ],
                            },
                            {
                                "id": "worked-hierarchy",
                                "type": "worked_example",
                                "heading": "Move Down the Taxonomic Ladder",
                                "prompt": "A specimen has six legs, chewing mouthparts, leathery forewings, enlarged jumping hind legs, and gradual metamorphosis.",
                                "steps": [
                                    "Six legs on the thorax support Class Insecta.",
                                    "Chewing mouthparts, tegmina, jumping hind legs, and gradual metamorphosis support Order Orthoptera.",
                                    "Use finer traits only after the class and order evidence agree.",
                                    "Do not infer family or species from color alone.",
                                ],
                            },
                            {
                                "id": "check-thorax",
                                "type": "checkpoint",
                                "heading": "Locate the Legs",
                                "question": "On an adult insect, where are all three pairs of true legs attached?",
                                "choices": ["Head", "Thorax", "Abdomen", "Antennae"],
                                "correct_index": 1,
                                "explanation": "Each of the three thoracic segments bears one pair of legs.",
                                "misconception_by_choice": {
                                    "0": "The head bears sensory structures and mouthparts, not the walking legs.",
                                    "2": "The abdomen does not bear the three pairs of adult true legs.",
                                    "3": "Antennae attach to the head and are sensory appendages.",
                                },
                            },
                            {
                                "id": "morphology-routine",
                                "type": "steps",
                                "heading": "Use the PARTS Routine",
                                "steps": [
                                    {"label": "Partition", "detail": "Locate head, thorax, and abdomen."},
                                    {"label": "Attach", "detail": "Record where legs, wings, and antennae originate."},
                                    {"label": "Read", "detail": "Describe mouthparts, wing texture, and leg specializations."},
                                    {"label": "Trace", "detail": "Use the observed development pattern when provided."},
                                    {"label": "Step down", "detail": "Move from class to order to family only as evidence permits."},
                                ],
                            },
                            {
                                "id": "check-orthoptera",
                                "type": "checkpoint",
                                "heading": "Use a Trait Combination",
                                "question": "Which combination most strongly supports Order Orthoptera?",
                                "choices": [
                                    "Eight legs and no antennae",
                                    "Chewing mouthparts, tegmina, and enlarged jumping hind legs",
                                    "Six legs attached to the abdomen",
                                    "Two body regions and spinnerets",
                                ],
                                "correct_index": 1,
                                "explanation": "USDA ARS identifies chewing mouthparts, leathery forewings, enlarged jumping hind legs, and gradual metamorphosis as Orthoptera traits.",
                                "misconception_by_choice": {
                                    "0": "Eight legs and no antennae support an arachnid, not an insect order.",
                                    "2": "Adult insect legs attach to the thorax.",
                                    "3": "Two body regions and spinnerets describe spider anatomy.",
                                },
                            },
                            {
                                "id": "summary",
                                "type": "summary",
                                "heading": "Your Competition Takeaway",
                                "points": [
                                    "Use anatomy before variable color.",
                                    "All six adult insect legs attach to the thorax.",
                                    "Identify with combinations of independent traits.",
                                    "Move down the hierarchy only as far as the evidence supports.",
                                ],
                            },
                        ],
                    ))
                    db.commit()
            if event.slug == "rocks-and-minerals":
                first_concept = db.scalar(select(Concept).where(
                    Concept.event_id == event.id,
                    Concept.name == "Observable properties",
                ))
                lesson = db.scalar(select(Lesson).where(
                    Lesson.event_id == event.id,
                    Lesson.slug == "observe-before-you-identify",
                ))
                if not lesson:
                    lesson = Lesson(
                        event_id=event.id,
                        concept_id=first_concept.id if first_concept else None,
                        slug="observe-before-you-identify",
                        title="Observe Before You Identify",
                        summary="Use evidence from physical properties before committing to a mineral name.",
                        status="published",
                        current_version=1,
                        sequence=1,
                        estimated_minutes=12,
                    )
                    db.add(lesson)
                    db.flush()
                    lesson_claims = db.scalars(select(ScientificClaim).where(
                        ScientificClaim.concept_id == first_concept.id,
                        ScientificClaim.approved.is_(True),
                    )).all() if first_concept else []
                    source = sources["rocks-and-minerals"]
                    db.add(LessonVersion(
                        lesson_id=lesson.id,
                        version=1,
                        review_status="sme_approved",
                        claim_ids=[claim.id for claim in lesson_claims],
                        citations=[{
                            "title": source.title,
                            "publisher": source.publisher,
                            "url": source.url,
                            "source_id": source.id,
                            "claim_ids": [claim.id for claim in lesson_claims],
                        }],
                        content=[
                            {
                                "id": "opening",
                                "type": "opening",
                                "kicker": "Field method 01",
                                "heading": "A Name Is a Conclusion, Not an Observation",
                                "body": "Strong identifiers begin with evidence. Describe what the specimen does under a test before deciding what it is.",
                            },
                            {
                                "id": "property-set",
                                "type": "property_cards",
                                "heading": "Build a Property Profile",
                                "body": "One property rarely proves an identification. Combine independent observations.",
                                "cards": [
                                    {"name": "Luster", "cue": "How light reflects", "detail": "Start broadly: metallic or nonmetallic."},
                                    {"name": "Hardness", "cue": "Resistance to scratching", "detail": "Compare against known materials or Mohs standards."},
                                    {"name": "Streak", "cue": "Color of powdered mineral", "detail": "Use an unglazed porcelain streak plate when appropriate."},
                                    {"name": "Cleavage", "cue": "Breakage along flat planes", "detail": "Count directions and notice their angles."},
                                    {"name": "Fracture", "cue": "Irregular breakage", "detail": "Describe conchoidal, uneven, splintery, or fibrous surfaces."},
                                    {"name": "Density", "cue": "Mass relative to volume", "detail": "A useful discriminator when specimens look similar."},
                                ],
                            },
                            {
                                "id": "worked-example",
                                "type": "worked_example",
                                "heading": "Think Like a Station Competitor",
                                "prompt": "A pale specimen scratches glass and breaks in two flat directions near 90 degrees.",
                                "steps": [
                                    "Record only the evidence: pale color, hardness above glass, two cleavage directions.",
                                    "Use hardness and cleavage geometry before color because color can vary.",
                                    "Eliminate candidates that are too soft or lack the observed cleavage.",
                                    "Choose an identification only after the property profile is consistent.",
                                ],
                            },
                            {
                                "id": "check-hardness",
                                "type": "checkpoint",
                                "heading": "Check Your Evidence",
                                "question": "A specimen scratches a glass plate. Which conclusion is best supported?",
                                "choices": [
                                    "Its hardness is greater than the glass plate's hardness.",
                                    "It must have metallic luster.",
                                    "Its streak must be white.",
                                    "It has exactly two cleavage directions.",
                                ],
                                "correct_index": 0,
                                "explanation": "A scratch test supports a relative-hardness conclusion. It does not determine luster, streak, or cleavage.",
                                "misconception_by_choice": {
                                    "1": "A hardness test does not measure reflected light.",
                                    "2": "Streak requires a separate observation of powdered mineral.",
                                    "3": "Cleavage requires observing repeated breakage planes.",
                                },
                            },
                            {
                                "id": "decision-routine",
                                "type": "steps",
                                "heading": "Use the EVIDENCE Routine",
                                "steps": [
                                    {"label": "Examine", "detail": "Look at the whole specimen before testing."},
                                    {"label": "Verify", "detail": "Choose a diagnostic test that separates likely candidates."},
                                    {"label": "Interpret", "detail": "State exactly what the result supports."},
                                    {"label": "Discard", "detail": "Eliminate candidates contradicted by the evidence."},
                                    {"label": "Explain", "detail": "Connect the final name to at least two properties."},
                                ],
                            },
                            {
                                "id": "check-cleavage",
                                "type": "checkpoint",
                                "heading": "Distinguish Similar Terms",
                                "question": "A mineral repeatedly breaks along smooth, parallel surfaces. Which property are you observing?",
                                "choices": ["Cleavage", "Streak", "Hardness", "Luster"],
                                "correct_index": 0,
                                "explanation": "Repeated breakage along flat planes is cleavage. Fracture describes breakage that does not follow cleavage planes.",
                                "misconception_by_choice": {
                                    "1": "Streak is the color of powdered mineral.",
                                    "2": "Hardness is resistance to scratching.",
                                    "3": "Luster describes reflected light.",
                                },
                            },
                            {
                                "id": "field-summary",
                                "type": "summary",
                                "heading": "Your Competition Takeaway",
                                "points": [
                                    "Observe before naming.",
                                    "Prefer diagnostic properties over variable color.",
                                    "Combine independent evidence.",
                                    "Explain why rejected candidates do not fit.",
                                ],
                            },
                        ],
                    ))
                    db.commit()
            if event.slug == "ecology":
                energy_concept = db.scalar(select(Concept).where(
                    Concept.event_id == event.id,
                    Concept.name == "Energy flow",
                ))
                ecology_source = sources["ecology"]
                ecology_claim_text = (
                    "Food-web arrows show energy moving from a consumed organism to its consumer; "
                    "producers form the base, followed by primary, secondary, and tertiary consumers."
                )
                ecology_claim = db.scalar(select(ScientificClaim).where(
                    ScientificClaim.source_id == ecology_source.id,
                    ScientificClaim.claim_text == ecology_claim_text,
                ))
                if not ecology_claim:
                    ecology_claim = ScientificClaim(
                        source_id=ecology_source.id,
                        source_snapshot_id=source_snapshots[ecology_source.id].id,
                        concept_id=energy_concept.id if energy_concept else None,
                        claim_text=ecology_claim_text,
                        evidence_excerpt=(
                            "Food webs describe who eats whom and how energy flows; arrows point "
                            "from prey to predator, and trophic levels begin with producers."
                        ),
                        locator="Aquatic food webs: food-web arrows and trophic levels",
                        confidence=0.95,
                        approved=True,
                    )
                    db.add(ecology_claim)
                    db.flush()
                lesson = db.scalar(select(Lesson).where(
                    Lesson.event_id == event.id,
                    Lesson.slug == "read-energy-through-food-webs",
                ))
                if not lesson:
                    lesson = Lesson(
                        event_id=event.id,
                        concept_id=energy_concept.id if energy_concept else None,
                        slug="read-energy-through-food-webs",
                        title="Read Energy Through a Food Web",
                        summary="Trace energy pathways, trophic roles, and cascading effects from ecological evidence.",
                        status="published",
                        current_version=1,
                        sequence=1,
                        estimated_minutes=14,
                    )
                    db.add(lesson)
                    db.flush()
                    citation = {
                        "title": ecology_source.title,
                        "publisher": ecology_source.publisher,
                        "url": ecology_source.url,
                        "source_id": ecology_source.id,
                        "claim_ids": [ecology_claim.id],
                    }
                    db.add(LessonVersion(
                        lesson_id=lesson.id,
                        version=1,
                        review_status="sme_approved",
                        claim_ids=[ecology_claim.id],
                        citations=[citation],
                        content=[
                            {
                                "id": "opening",
                                "type": "opening",
                                "kicker": "Systems method 01",
                                "heading": "Follow Energy Before Predicting Change",
                                "body": "A food web is a map of energy pathways. Read each arrow from the organism being consumed toward the organism receiving that energy.",
                            },
                            {
                                "id": "trophic-roles",
                                "type": "property_cards",
                                "heading": "Assign Roles From Evidence",
                                "body": "An organism's trophic role follows how it obtains energy, not its size or how familiar it looks.",
                                "cards": [
                                    {"name": "Producer", "cue": "Builds biomass", "detail": "Plants and algae use photosynthesis; some microbes use chemosynthesis."},
                                    {"name": "Primary Consumer", "cue": "Consumes producers", "detail": "Herbivores connect producer energy to higher trophic levels."},
                                    {"name": "Secondary Consumer", "cue": "Consumes primary consumers", "detail": "Its position depends on the pathway being analyzed."},
                                    {"name": "Omnivore", "cue": "Feeds at multiple levels", "detail": "One species can occupy more than one trophic position."},
                                ],
                            },
                            {
                                "id": "worked-cascade",
                                "type": "worked_example",
                                "heading": "Trace a Cascade One Link at a Time",
                                "prompt": "Kelp → sea urchin → sea otter. A disease sharply reduces sea otters.",
                                "steps": [
                                    "Start with the direct effect: fewer otters consume fewer sea urchins.",
                                    "Predict the next supported change: sea urchin abundance can increase.",
                                    "Trace the indirect effect: more grazing can reduce kelp.",
                                    "Avoid adding unsupported causes; follow only links shown by the web.",
                                ],
                            },
                            {
                                "id": "check-arrow",
                                "type": "checkpoint",
                                "heading": "Read the Arrow",
                                "question": "In the pathway phytoplankton → zooplankton → herring, what does the first arrow show?",
                                "choices": [
                                    "Energy moves from phytoplankton to zooplankton when zooplankton feed.",
                                    "Phytoplankton hunt zooplankton.",
                                    "Zooplankton produce phytoplankton.",
                                    "Both organisms occupy the same trophic level.",
                                ],
                                "correct_index": 0,
                                "explanation": "Food-web arrows follow energy from the consumed organism toward its consumer.",
                                "misconception_by_choice": {
                                    "1": "The arrow is not pointing from predator to prey; it follows transferred energy.",
                                    "2": "Feeding transfers energy but does not mean one organism produces the other.",
                                    "3": "Phytoplankton are producers while zooplankton are consumers.",
                                },
                            },
                            {
                                "id": "systems-routine",
                                "type": "steps",
                                "heading": "Use the TRACE Routine",
                                "steps": [
                                    {"label": "Target", "detail": "Name the population or process that changes first."},
                                    {"label": "Read", "detail": "Follow the direction of each relevant energy pathway."},
                                    {"label": "Assign", "detail": "Identify producer and consumer roles from feeding evidence."},
                                    {"label": "Connect", "detail": "Separate direct effects from indirect cascading effects."},
                                    {"label": "Evaluate", "detail": "Reject conclusions that require a link the evidence does not show."},
                                ],
                            },
                            {
                                "id": "check-cascade",
                                "type": "checkpoint",
                                "heading": "Predict the Supported Cascade",
                                "question": "In grass → rabbit → hawk, rabbit abundance falls sharply. Which immediate effect is best supported?",
                                "choices": [
                                    "Less rabbit prey is available to hawks.",
                                    "Hawks become producers.",
                                    "Grass immediately disappears.",
                                    "Energy begins flowing from hawks to rabbits.",
                                ],
                                "correct_index": 0,
                                "explanation": "The shown link directly supports reduced prey availability for hawks; later population outcomes require additional evidence.",
                                "misconception_by_choice": {
                                    "1": "Trophic roles do not switch because prey becomes scarce.",
                                    "2": "Reduced herbivory would not directly support immediate grass loss.",
                                    "3": "The energy pathway remains from consumed rabbit to consuming hawk.",
                                },
                            },
                            {
                                "id": "summary",
                                "type": "summary",
                                "heading": "Your Competition Takeaway",
                                "points": [
                                    "Read arrows in the direction of energy transfer.",
                                    "Assign trophic roles from what each organism consumes.",
                                    "Separate direct effects from indirect cascades.",
                                    "Make only predictions supported by the given web or dataset.",
                                ],
                            },
                        ],
                    ))
                    db.commit()
            if event.slug == "entomology":
                anatomy_concept = db.scalar(select(Concept).where(
                    Concept.event_id == event.id,
                    Concept.name == "Insect anatomy",
                ))
                practice_set = db.scalar(select(PracticeSet).where(
                    PracticeSet.event_id == event.id,
                    PracticeSet.slug == "insect-anatomy-evidence-lab",
                ))
                if not practice_set:
                    anatomy_source = sources["entomology"]
                    claims = db.scalars(select(ScientificClaim).where(
                        ScientificClaim.source_id == anatomy_source.id,
                        ScientificClaim.approved.is_(True),
                    )).all()
                    practice_set = PracticeSet(
                        event_id=event.id,
                        concept_id=anatomy_concept.id if anatomy_concept else None,
                        slug="insect-anatomy-evidence-lab",
                        title="Insect Anatomy Evidence Lab",
                        summary="Solve 5 text-first morphology and hierarchy challenges while specimen imagery remains in rights review.",
                        practice_type="classification",
                        status="published",
                        current_version=1,
                        estimated_minutes=9,
                    )
                    db.add(practice_set)
                    db.flush()
                    db.add(PracticeSetVersion(
                        practice_set_id=practice_set.id,
                        version=1,
                        review_status="sme_approved",
                        claim_ids=[claim.id for claim in claims],
                        citations=[{
                            "title": anatomy_source.title,
                            "publisher": anatomy_source.publisher,
                            "url": anatomy_source.url,
                            "source_id": anatomy_source.id,
                            "claim_ids": [claim.id for claim in claims],
                        }],
                        items=[
                            {
                                "id": "insect-or-arachnid",
                                "prompt": "Which classification is best supported by this external anatomy?",
                                "property_profile": [
                                    {"label": "Body regions", "value": "Head, thorax, abdomen"},
                                    {"label": "Legs", "value": "3 pairs; all on thorax"},
                                    {"label": "Antennae", "value": "1 pair"},
                                ],
                                "choices": ["Class Insecta", "Class Arachnida", "Class Diplopoda", "Class Crustacea"],
                                "correct_index": 0,
                                "explanation": "Three body regions, six thoracic legs, and one pair of antennae support Class Insecta.",
                                "misconception_by_choice": {"1": "Arachnids have eight legs and lack antennae.", "2": "Millipedes have many leg-bearing body segments.", "3": "Crustaceans do not match this three-region, six-leg profile."},
                            },
                            {
                                "id": "thorax-function",
                                "prompt": "Which body region is the locomotor center described by these observations?",
                                "property_profile": [
                                    {"label": "Appendages", "value": "3 pairs of jointed legs"},
                                    {"label": "Wings", "value": "2 pairs attached here"},
                                    {"label": "Segments", "value": "3"},
                                ],
                                "choices": ["Head", "Thorax", "Abdomen", "Tarsus"],
                                "correct_index": 1,
                                "explanation": "The three-segmented thorax bears the insect's legs and wings.",
                                "misconception_by_choice": {"0": "The head bears eyes, antennae, and mouthparts.", "2": "The abdomen contains many internal organs but not all six adult legs.", "3": "A tarsus is part of a leg, not a body region."},
                            },
                            {
                                "id": "orthoptera-order",
                                "prompt": "Which order is supported by this trait combination?",
                                "property_profile": [
                                    {"label": "Mouthparts", "value": "Chewing"},
                                    {"label": "Forewings", "value": "Leathery tegmina"},
                                    {"label": "Hind legs", "value": "Enlarged for jumping"},
                                    {"label": "Development", "value": "Gradual metamorphosis"},
                                ],
                                "choices": ["Orthoptera", "Diptera", "Coleoptera", "Siphonaptera"],
                                "correct_index": 0,
                                "explanation": "USDA ARS lists this combined profile for Orthoptera.",
                                "misconception_by_choice": {"1": "Diptera are characterized by one functional wing pair and halteres.", "2": "Coleoptera have hardened forewings called elytra.", "3": "Fleas are wingless and laterally compressed, without jumping hind legs of this form."},
                            },
                            {
                                "id": "gradual-development",
                                "prompt": "Which development sequence matches gradual metamorphosis?",
                                "property_profile": [
                                    {"label": "Immature form", "value": "Resembles a smaller adult"},
                                    {"label": "Pupal stage", "value": "Absent"},
                                    {"label": "Change", "value": "Successive molts"},
                                ],
                                "choices": ["Egg → larva → pupa → adult", "Egg → nymph → adult", "Adult → pupa → egg", "Egg → adult with no molts"],
                                "correct_index": 1,
                                "explanation": "Gradual metamorphosis proceeds from egg to nymphal stages to adult without a pupa.",
                                "misconception_by_choice": {"0": "Larva and pupa describe complete metamorphosis.", "2": "A pupa does not follow the adult.", "3": "Nymphs grow through molts before adulthood."},
                            },
                            {
                                "id": "hierarchy-family",
                                "prompt": "What is the most specific supported classification?",
                                "property_profile": [
                                    {"label": "Class traits", "value": "Insecta confirmed"},
                                    {"label": "Order traits", "value": "Orthoptera confirmed"},
                                    {"label": "Antennae", "value": "Short"},
                                    {"label": "Tympanum", "value": "First abdominal segment"},
                                    {"label": "Tarsi", "value": "3 segmented"},
                                ],
                                "choices": ["Class Insecta only", "Order Orthoptera only", "Family Acrididae", "A species-level name"],
                                "correct_index": 2,
                                "explanation": "The short antennae, tympanum position, and three-segmented tarsi support Family Acrididae within Orthoptera.",
                                "misconception_by_choice": {"0": "The evidence supports levels below class.", "1": "The additional family traits permit a more specific conclusion.", "3": "No species-level diagnostic profile is provided."},
                            },
                        ],
                    ))
                    db.commit()
            if event.slug == "rocks-and-minerals":
                diagnostic_concept = db.scalar(select(Concept).where(
                    Concept.event_id == event.id,
                    Concept.name == "Diagnostic tests",
                ))
                practice_set = db.scalar(select(PracticeSet).where(
                    PracticeSet.event_id == event.id,
                    PracticeSet.slug == "mystery-mineral-evidence-lab",
                ))
                if not practice_set:
                    practice_set = PracticeSet(
                        event_id=event.id,
                        concept_id=diagnostic_concept.id if diagnostic_concept else None,
                        slug="mystery-mineral-evidence-lab",
                        title="Mystery Mineral Evidence Lab",
                        summary="Identify 5 minerals from diagnostic property profiles—not from color alone.",
                        practice_type="identification",
                        status="published",
                        current_version=1,
                        estimated_minutes=8,
                    )
                    db.add(practice_set)
                    db.flush()
                    claims = db.scalars(select(ScientificClaim).where(
                        ScientificClaim.source_id == sources["rocks-and-minerals"].id,
                        ScientificClaim.approved.is_(True),
                    )).all()
                    source = sources["rocks-and-minerals"]
                    db.add(PracticeSetVersion(
                        practice_set_id=practice_set.id,
                        version=1,
                        review_status="sme_approved",
                        claim_ids=[claim.id for claim in claims],
                        citations=[{
                            "title": source.title,
                            "publisher": source.publisher,
                            "url": source.url,
                            "source_id": source.id,
                            "claim_ids": [claim.id for claim in claims],
                        }],
                        items=[
                            {
                                "id": "quartz-profile",
                                "prompt": "Which mineral best matches this evidence profile?",
                                "property_profile": [
                                    {"label": "Luster", "value": "Vitreous, nonmetallic"},
                                    {"label": "Hardness", "value": "7"},
                                    {"label": "Streak", "value": "White"},
                                    {"label": "Breakage", "value": "No cleavage; conchoidal fracture"},
                                ],
                                "choices": ["Quartz", "Calcite", "Gypsum", "Halite"],
                                "correct_index": 0,
                                "explanation": "Quartz is distinguished here by hardness 7 and conchoidal fracture without cleavage.",
                                "misconception_by_choice": {
                                    "1": "Calcite is much softer and has rhombohedral cleavage.",
                                    "2": "Gypsum can be scratched by a fingernail.",
                                    "3": "Halite is softer and shows cubic cleavage.",
                                },
                            },
                            {
                                "id": "calcite-profile",
                                "prompt": "Which mineral best matches this evidence profile?",
                                "property_profile": [
                                    {"label": "Luster", "value": "Vitreous to pearly"},
                                    {"label": "Hardness", "value": "3"},
                                    {"label": "Cleavage", "value": "3 directions, not at 90°"},
                                    {"label": "Test", "value": "Effervesces in dilute acid"},
                                ],
                                "choices": ["Fluorite", "Calcite", "Quartz", "Magnetite"],
                                "correct_index": 1,
                                "explanation": "Calcite combines hardness 3, rhombohedral cleavage, and a strong reaction with dilute acid.",
                                "misconception_by_choice": {
                                    "0": "Fluorite has hardness 4 and four cleavage directions.",
                                    "2": "Quartz is harder and does not show this cleavage or acid reaction.",
                                    "3": "Magnetite has a dark streak and strong magnetism.",
                                },
                            },
                            {
                                "id": "halite-profile",
                                "prompt": "Which mineral best matches this evidence profile?",
                                "property_profile": [
                                    {"label": "Luster", "value": "Vitreous"},
                                    {"label": "Hardness", "value": "About 2.5"},
                                    {"label": "Streak", "value": "White"},
                                    {"label": "Cleavage", "value": "3 directions at 90°"},
                                ],
                                "choices": ["Halite", "Calcite", "Talc", "Quartz"],
                                "correct_index": 0,
                                "explanation": "Halite's three cleavage directions meet at right angles, producing cubic fragments.",
                                "misconception_by_choice": {
                                    "1": "Calcite cleavage directions do not meet at 90 degrees.",
                                    "2": "Talc is softer and typically has one perfect cleavage direction.",
                                    "3": "Quartz lacks cleavage and is much harder.",
                                },
                            },
                            {
                                "id": "magnetite-profile",
                                "prompt": "Which mineral best matches this evidence profile?",
                                "property_profile": [
                                    {"label": "Luster", "value": "Metallic to submetallic"},
                                    {"label": "Streak", "value": "Black"},
                                    {"label": "Hardness", "value": "5.5–6.5"},
                                    {"label": "Test", "value": "Strongly magnetic"},
                                ],
                                "choices": ["Hematite", "Graphite", "Magnetite", "Galena"],
                                "correct_index": 2,
                                "explanation": "Strong magnetism paired with a black streak is highly diagnostic of magnetite.",
                                "misconception_by_choice": {
                                    "0": "Hematite commonly has a reddish-brown streak and is not strongly magnetic.",
                                    "1": "Graphite is much softer and marks paper.",
                                    "3": "Galena is very dense with cubic cleavage but is not strongly magnetic.",
                                },
                            },
                            {
                                "id": "gypsum-profile",
                                "prompt": "Which mineral best matches this evidence profile?",
                                "property_profile": [
                                    {"label": "Luster", "value": "Vitreous to silky"},
                                    {"label": "Hardness", "value": "2"},
                                    {"label": "Streak", "value": "White"},
                                    {"label": "Test", "value": "Scratched by a fingernail"},
                                ],
                                "choices": ["Quartz", "Gypsum", "Feldspar", "Fluorite"],
                                "correct_index": 1,
                                "explanation": "A fingernail scratches gypsum because its Mohs hardness is about 2.",
                                "misconception_by_choice": {
                                    "0": "Quartz has hardness 7 and cannot be scratched by a fingernail.",
                                    "2": "Feldspar is substantially harder than a fingernail.",
                                    "3": "Fluorite has hardness 4 and is not scratched by a fingernail.",
                                },
                            },
                        ],
                    ))
                    db.commit()
            if event.slug == "ecology":
                energy_concept = db.scalar(select(Concept).where(
                    Concept.event_id == event.id,
                    Concept.name == "Energy flow",
                ))
                practice_set = db.scalar(select(PracticeSet).where(
                    PracticeSet.event_id == event.id,
                    PracticeSet.slug == "food-web-evidence-lab",
                ))
                if not practice_set:
                    ecology_source = sources["ecology"]
                    ecology_claims = db.scalars(select(ScientificClaim).where(
                        ScientificClaim.source_id == ecology_source.id,
                        ScientificClaim.approved.is_(True),
                    )).all()
                    practice_set = PracticeSet(
                        event_id=event.id,
                        concept_id=energy_concept.id if energy_concept else None,
                        slug="food-web-evidence-lab",
                        title="Food Web Evidence Lab",
                        summary="Solve 5 food-web and trophic-system challenges from pathways, field observations, and energy data.",
                        practice_type="data_interpretation",
                        status="published",
                        current_version=1,
                        estimated_minutes=10,
                    )
                    db.add(practice_set)
                    db.flush()
                    db.add(PracticeSetVersion(
                        practice_set_id=practice_set.id,
                        version=1,
                        review_status="sme_approved",
                        claim_ids=[claim.id for claim in ecology_claims],
                        citations=[{
                            "title": ecology_source.title,
                            "publisher": ecology_source.publisher,
                            "url": ecology_source.url,
                            "source_id": ecology_source.id,
                            "claim_ids": [claim.id for claim in ecology_claims],
                        }],
                        items=[
                            {
                                "id": "arrow-direction",
                                "prompt": "A marsh food-web diagram shows cordgrass → grasshopper → frog. Which interpretation is supported?",
                                "property_profile": [
                                    {"label": "Pathway", "value": "Cordgrass → grasshopper"},
                                    {"label": "Pathway", "value": "Grasshopper → frog"},
                                    {"label": "Arrow convention", "value": "Direction of energy transfer"},
                                ],
                                "choices": ["The frog transfers energy to the grasshopper.", "The grasshopper is a primary consumer.", "Cordgrass is a secondary consumer.", "The frog produces cordgrass."],
                                "correct_index": 1,
                                "explanation": "The grasshopper consumes the producer cordgrass, so it is a primary consumer in this pathway.",
                                "misconception_by_choice": {"0": "Energy moves from consumed grasshopper to consuming frog.", "2": "Cordgrass is the producer at the base of the pathway.", "3": "Feeding links do not indicate that animals produce plants."},
                            },
                            {
                                "id": "transfer-efficiency",
                                "prompt": "Which conclusion best describes the energy pattern between these trophic levels?",
                                "property_profile": [
                                    {"label": "Producers", "value": "20,000 kJ m⁻² yr⁻¹"},
                                    {"label": "Primary consumers", "value": "2,100 kJ m⁻² yr⁻¹"},
                                    {"label": "Secondary consumers", "value": "230 kJ m⁻² yr⁻¹"},
                                ],
                                "choices": ["Available energy increases at each level.", "About one-tenth transfers at each shown step.", "All producer energy reaches secondary consumers.", "The values prove consumers photosynthesize."],
                                "correct_index": 1,
                                "explanation": "2,100 is about 10.5% of 20,000 and 230 is about 11% of 2,100, so the data support roughly one-tenth transfer at each step.",
                                "misconception_by_choice": {"0": "The measured energy decreases sharply at higher levels.", "2": "Most measured producer energy is not represented at the secondary-consumer level.", "3": "Energy values alone do not indicate photosynthesis by consumers."},
                            },
                            {
                                "id": "otter-cascade",
                                "prompt": "Sea otter abundance declines while all shown feeding relationships remain the same. Which sequence is best supported?",
                                "property_profile": [
                                    {"label": "Energy pathway", "value": "Kelp → sea urchin"},
                                    {"label": "Energy pathway", "value": "Sea urchin → sea otter"},
                                    {"label": "Initial change", "value": "Fewer sea otters"},
                                ],
                                "choices": ["Fewer urchins, then more kelp", "More urchins, then less kelp", "More otters, then more kelp", "Kelp becomes a consumer"],
                                "correct_index": 1,
                                "explanation": "With fewer otters consuming them, urchins can increase; greater urchin grazing can then reduce kelp.",
                                "misconception_by_choice": {"0": "Reduced predation supports more—not fewer—urchins.", "2": "The initial condition specifies fewer otters.", "3": "Kelp remains a producer."},
                            },
                            {
                                "id": "omnivore-role",
                                "prompt": "A fish eats algae and insect larvae. Which conclusion is most accurate?",
                                "property_profile": [
                                    {"label": "Food item 1", "value": "Algae · producer"},
                                    {"label": "Food item 2", "value": "Insect larvae · primary consumers"},
                                    {"label": "Observed diet", "value": "Both food items consumed"},
                                ],
                                "choices": ["The fish can feed at multiple trophic levels.", "The fish is always a producer.", "The larvae must be tertiary consumers.", "No energy reaches the fish."],
                                "correct_index": 0,
                                "explanation": "Consuming both producers and consumers makes the fish an omnivore that feeds across trophic levels.",
                                "misconception_by_choice": {"1": "Eating a producer does not make the consumer a producer.", "2": "The evidence identifies the larvae as primary consumers.", "3": "Energy reaches the fish through both feeding pathways."},
                            },
                            {
                                "id": "direct-effect",
                                "prompt": "A pesticide sharply reduces zooplankton. Which is the most direct supported effect in the shown web?",
                                "property_profile": [
                                    {"label": "Pathway", "value": "Phytoplankton → zooplankton"},
                                    {"label": "Pathway", "value": "Zooplankton → small fish"},
                                    {"label": "Measured change", "value": "Zooplankton decline"},
                                ],
                                "choices": ["Small fish have less zooplankton prey available.", "Small fish immediately become producers.", "Phytoplankton stop photosynthesizing.", "Energy arrows reverse direction."],
                                "correct_index": 0,
                                "explanation": "The direct feeding link supports reduced zooplankton prey availability for small fish.",
                                "misconception_by_choice": {"1": "Resource scarcity does not change consumers into producers.", "2": "The web does not support an immediate end to photosynthesis.", "3": "The convention for energy-flow arrows does not reverse."},
                            },
                        ],
                    ))
                    db.commit()
            existing = db.scalars(select(Question).where(Question.event_id == event.id)).all()
            for claim in db.scalars(select(ScientificClaim).where(
                ScientificClaim.source_snapshot_id.is_(None)
            )).all():
                snapshot = source_snapshots.get(claim.source_id)
                if snapshot and " ".join(claim.evidence_excerpt.casefold().split()) in " ".join(snapshot.extracted_text.casefold().split()):
                    claim.source_snapshot_id = snapshot.id
            db.commit()
            # Seed only unique authored templates; never manufacture volume by repeating stems.
            if len(existing) < 2:
                generate_questions(
                    db, event, None, 2 - len(existing), 0.5, "application", "single_choice"
                )
            for question in db.scalars(select(Question).where(Question.event_id == event.id)).all():
                claim_ids = [citation.get("claim_id") for citation in question.citations or [] if citation.get("claim_id")]
                claims = db.scalars(select(ScientificClaim).where(
                    ScientificClaim.id.in_(claim_ids), ScientificClaim.approved.is_(True),
                    ScientificClaim.source_snapshot_id.is_not(None),
                )).all() if claim_ids else []
                if not question.validation_report.get("passed") or len(claims) != len(set(claim_ids)):
                    continue
                editor_review = db.scalar(select(QuestionReview).where(
                    QuestionReview.question_id == question.id,
                    QuestionReview.question_version == question.version,
                    QuestionReview.stage == "editor",
                    QuestionReview.decision == "approved",
                ))
                if not editor_review:
                    db.add(QuestionReview(
                        question_id=question.id, question_version=question.version,
                        stage="editor", decision="approved", reviewer_user_id=editor.id,
                        checklist={
                            "clear_language": True, "single_best_answer": True,
                            "distractors_plausible": True, "age_appropriate": True,
                            "original_wording": True,
                        }, notes="Demo fixture editorial review.",
                    ))
                sme_review = db.scalar(select(QuestionReview).where(
                    QuestionReview.question_id == question.id,
                    QuestionReview.question_version == question.version,
                    QuestionReview.stage == "sme",
                    QuestionReview.decision == "approved",
                ))
                if not sme_review:
                    db.add(QuestionReview(
                        question_id=question.id, question_version=question.version,
                        stage="sme", decision="approved", reviewer_user_id=sme.id,
                        checklist={
                            "factually_supported": True, "answer_key_verified": True,
                            "citations_verified": True, "no_material_ambiguity": True,
                        }, notes="Demo fixture scientific review.",
                    ))
                question.similarity_report = build_similarity_report(
                    db, question.stem, question.choices or [], exclude_question_id=question.id
                )
                if question.similarity_report.get("outcome") != "blocked":
                    question.status = "published"
            db.commit()
            if not db.scalar(select(Exam).where(Exam.event_id == event.id)):
                qs = db.scalars(
                    select(Question).where(
                        Question.event_id == event.id, Question.status == "published"
                    ).limit(8)
                ).all()
                if not qs:
                    continue
                exam = Exam(
                    event_id=event.id,
                    title=f"{name} Competition-Style Mock 1",
                    duration_minutes=20,
                    question_ids=[q.id for q in qs],
                    published=True,
                    release_class="foundational_practice" if event.season_status != "current" else "reviewed_practice",
                    coverage_snapshot={
                        "fixture": True,
                        "competition_release_ready": False,
                        "notice": "Demo-only fixture; not evidence of live crawler coverage.",
                    },
                    published_by_user_id=admin.id if admin else None,
                    published_at=datetime.now(timezone.utc),
                    blueprint={"level": "practice", "question_count": len(qs), "snapshot_schema": 1},
                )
                db.add(exam)
                db.flush()
                for position, q in enumerate(qs):
                    db.add(ExamItem(
                        exam_id=exam.id,
                        question_id=q.id,
                        question_version=q.version,
                        position=position,
                        snapshot={
                            "question_id": q.id,
                            "question_version": q.version,
                            "concept_id": q.concept_id,
                            "question_type": q.question_type,
                            "stem": q.stem,
                            "choices": q.choices,
                            "answer_spec": q.answer_spec,
                            "explanation": q.explanation,
                            "citations": q.citations,
                            "difficulty": q.difficulty,
                            "cognitive_level": q.cognitive_level,
                            "estimated_seconds": q.estimated_seconds,
                        },
                    ))
                db.commit()
        if not db.scalar(select(BackgroundJob).where(
            BackgroundJob.job_type == "schedule_due_crawls",
            BackgroundJob.status.in_(["queued", "running"]),
        )):
            db.add(BackgroundJob(
                job_type="schedule_due_crawls",
                payload={"recurring": True},
            ))
            db.commit()
        print("Seed complete. Demo student: student@example.com / StudentPass123!")
        print("Demo coach: coach@example.com / CoachPass123!")
        print("Admin: admin@example.com / AdminPass123!")
    finally:
        db.close()


if __name__ == "__main__":
    main()
