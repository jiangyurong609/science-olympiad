from __future__ import annotations
import random
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import Concept, Event, Question, QuestionStatus, ScientificClaim, Source
from app.services.rights import can_use_for_generation
from app.services.validation import validate_candidate

SCIENCE_TEMPLATES: dict[str, list[dict]] = {
    "meteorology": [
        {
            "stem": "Which instrument directly measures atmospheric pressure?",
            "choices": ["Barometer", "Anemometer", "Hygrometer", "Rain gauge"],
            "correct": 0,
            "explanation": "A barometer measures atmospheric pressure.",
            "claim_hint": "barometer",
            "errors": {"1": "instrument_confusion_wind", "2": "instrument_confusion_humidity", "3": "instrument_confusion_precipitation"},
        },
        {
            "stem": "A rapidly falling barometer most directly suggests which change?",
            "choices": ["Improving visibility", "Approaching low-pressure weather", "Decreasing humidity", "A stationary front has dissipated"],
            "correct": 1,
            "explanation": "Falling pressure commonly indicates an approaching low-pressure system and potentially unsettled weather.",
            "claim_hint": "falling pressure",
            "errors": {"0": "pressure_trend_misinterpretation", "2": "humidity_pressure_confusion", "3": "front_pressure_confusion"},
        },
    ],
    "heredity": [
        {
            "stem": "In a cross Aa × Aa, what fraction of offspring is expected to have genotype aa?",
            "choices": ["1/4", "1/2", "3/4", "1"],
            "correct": 0,
            "explanation": "A Punnett square gives AA, Aa, Aa, and aa, so one of four offspring is expected to be aa.",
            "claim_hint": "Aa",
            "errors": {"1": "punnett_ratio_error", "2": "phenotype_genotype_confusion", "3": "dominance_misconception"},
        },
        {
            "stem": "Which term describes different versions of the same gene?",
            "choices": ["Alleles", "Chromatids", "Ribosomes", "Phenotypes"],
            "correct": 0,
            "explanation": "Alleles are alternative versions of a gene.",
            "claim_hint": "allele",
            "errors": {"1": "chromosome_gene_confusion", "2": "organelle_gene_confusion", "3": "genotype_phenotype_confusion"},
        },
    ],
    "rocks-and-minerals": [
        {
            "stem": "Which mineral property is measured by comparison with the Mohs scale?",
            "choices": ["Hardness", "Streak", "Luster", "Cleavage"],
            "correct": 0,
            "explanation": "The Mohs scale compares a mineral's resistance to scratching, which is its hardness.",
            "claim_hint": "hardness",
            "errors": {"1": "property_confusion_streak", "2": "property_confusion_luster", "3": "property_confusion_cleavage"},
        },
        {
            "stem": "A mineral breaks repeatedly along smooth, flat planes. Which property does this demonstrate?",
            "choices": ["Cleavage", "Fracture", "Streak", "Magnetism"],
            "correct": 0,
            "explanation": "Cleavage is the tendency of a mineral to break along planes of weakness in its crystal structure.",
            "claim_hint": "cleavage",
            "errors": {"1": "cleavage_fracture_confusion", "2": "property_confusion_streak", "3": "unsupported_test_selection"},
        },
    ],
    "ecology": [
        {
            "stem": "Which group forms the first trophic level in most ecosystems?",
            "choices": ["Primary producers", "Primary consumers", "Decomposers", "Secondary consumers"],
            "correct": 0,
            "explanation": "Primary producers capture energy and form the first trophic level of most ecosystems.",
            "claim_hint": "trophic level",
            "errors": {"1": "trophic_level_shift", "2": "decomposer_role_confusion", "3": "trophic_level_shift"},
        },
        {
            "stem": "A population exceeds the resources its habitat can sustain over time. Which limit has it exceeded?",
            "choices": ["Carrying capacity", "Biotic potential", "Species richness", "Ecological succession"],
            "correct": 0,
            "explanation": "Carrying capacity is the population size an environment can sustain over time with available resources.",
            "claim_hint": "carrying capacity",
            "errors": {"1": "growth_capacity_confusion", "2": "population_community_confusion", "3": "succession_population_confusion"},
        },
    ],
    "entomology": [
        {
            "stem": "Which body regions are present in an adult insect?",
            "choices": ["Head, thorax, and abdomen", "Cephalothorax and abdomen", "Head and trunk", "Thorax and tail"],
            "correct": 0,
            "explanation": "Adult insects have three primary body regions: the head, thorax, and abdomen.",
            "claim_hint": "head, thorax",
            "errors": {"1": "insect_arachnid_confusion", "2": "body_plan_confusion", "3": "body_plan_confusion"},
        },
        {
            "stem": "On which body region are an adult insect's legs attached?",
            "choices": ["Thorax", "Head", "Abdomen", "Antenna"],
            "correct": 0,
            "explanation": "An adult insect's three pairs of legs attach to the thorax.",
            "claim_hint": "legs",
            "errors": {"1": "appendage_location_confusion", "2": "appendage_location_confusion", "3": "structure_category_confusion"},
        },
    ],
    "default": [
        {
            "stem": "Which practice best improves the reliability of an experiment?",
            "choices": ["Repeating trials", "Changing multiple variables", "Using no control", "Recording only successful results"],
            "correct": 0,
            "explanation": "Repeated trials reduce the influence of random variation and improve reliability.",
            "claim_hint": "repeated trials",
            "errors": {"1": "variable_control_error", "2": "control_group_error", "3": "selection_bias"},
        },
        {
            "stem": "What is the primary purpose of a control group?",
            "choices": ["Provide a baseline for comparison", "Increase the sample's temperature", "Guarantee the hypothesis is correct", "Eliminate the need for repeated trials"],
            "correct": 0,
            "explanation": "A control group provides a baseline against which the experimental treatment can be compared.",
            "claim_hint": "control group",
            "errors": {"1": "treatment_control_confusion", "2": "hypothesis_certainty_error", "3": "replication_control_confusion"},
        },
    ],
}


def _source_for_generation(db: Session) -> Source | None:
    sources = db.scalars(select(Source).where(Source.approved.is_(True))).all()
    return next((s for s in sources if can_use_for_generation(s.rights_status, s.approved)), None)


def _matching_claims(db: Session, source: Source | None, concept: Concept | None, hint: str) -> list[ScientificClaim]:
    stmt = select(ScientificClaim).where(
        ScientificClaim.approved.is_(True), ScientificClaim.source_snapshot_id.is_not(None)
    )
    if concept:
        stmt = stmt.where((ScientificClaim.concept_id == concept.id) | (ScientificClaim.concept_id.is_(None)))
    claims = db.scalars(stmt).all()
    hint_lower = hint.lower()
    ranked = sorted(claims, key=lambda c: hint_lower not in c.claim_text.lower())
    return ranked[:2]


def generate_questions(
    db: Session,
    event: Event,
    concept: Concept | None,
    count: int,
    difficulty: float,
    cognitive_level: str,
    question_type: str,
) -> list[Question]:
    if question_type != "single_choice":
        raise ValueError("Grounded generator currently supports single_choice only")
    source = _source_for_generation(db)
    templates = SCIENCE_TEMPLATES.get(event.slug.lower(), SCIENCE_TEMPLATES["default"])
    results: list[Question] = []
    for i in range(count):
        template = templates[i % len(templates)]
        tagged = list(enumerate(template["choices"]))
        random.Random(f"{event.slug}:{concept.id if concept else 0}:{i}:{len(results)}").shuffle(tagged)
        choices = [choice for _, choice in tagged]
        correct_index = next(pos for pos, (old, _) in enumerate(tagged) if old == template["correct"])
        distractor_errors = {
            str(pos): template["errors"].get(str(old), "knowledge_or_reasoning")
            for pos, (old, _) in enumerate(tagged)
            if old != template["correct"]
        }
        claims = _matching_claims(db, source, concept, template["claim_hint"])
        question_source = db.get(Source, claims[0].source_id) if claims else source
        answer_spec = {
            "correct_index": correct_index,
            "points": 1,
            "distractor_error_types": distractor_errors,
        }
        report = validate_candidate(
            db,
            stem=template["stem"],
            choices=choices,
            answer_spec=answer_spec,
            claim_ids=[c.id for c in claims],
            source_id=question_source.id if question_source else None,
        )
        status = QuestionStatus.MACHINE_VALIDATED.value if report["passed"] else QuestionStatus.DRAFT.value
        citations = [
            {
                "source_id": c.source_id,
                "claim_id": c.id,
                "locator": c.locator,
                "evidence_excerpt": c.evidence_excerpt,
            }
            for c in claims
        ]
        if question_source and not citations:
            citations = [{"source_id": question_source.id, "url": question_source.url, "title": question_source.title}]
        q = Question(
            event_id=event.id,
            concept_id=concept.id if concept else None,
            source_id=question_source.id if question_source else None,
            status=status,
            question_type=question_type,
            stem=template["stem"],
            choices=choices,
            answer_spec=answer_spec,
            explanation=template["explanation"],
            citations=citations,
            difficulty=difficulty,
            cognitive_level=cognitive_level,
            estimated_seconds=75,
            validation_report=report,
            generation_provenance={
                "provider": "grounded-deterministic",
                "version": "2.0",
                "original": True,
                "claim_ids": [c.id for c in claims],
            },
        )
        db.add(q)
        db.flush()
        results.append(q)
    db.commit()
    for q in results:
        db.refresh(q)
    return results
