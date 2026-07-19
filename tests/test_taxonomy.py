from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Event, EventTaxonScope, Source, SpecimenAsset, Taxon


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_taxonomy_api_keeps_foundations_and_image_release_separate(client, student_token):
    with SessionLocal() as db:
        event = Event(
            slug="taxonomy-entomology", name="Entomology", division="C", season=2026
        )
        source = Source(
            url="https://www.ars.usda.gov/example",
            title="USDA anatomy",
            publisher="USDA ARS",
            rights_status="fact_grounding_allowed",
            approved=True,
        )
        db.add_all([event, source])
        db.flush()
        taxon = Taxon(
            scientific_name="Insecta",
            common_name="insects",
            rank="class",
            source_id=source.id,
            taxonomy_authority="USDA ARS",
            taxonomy_version="2026-07",
            diagnostic_traits=["three body regions", "six thoracic legs"],
            reviewed=True,
        )
        db.add(taxon)
        db.flush()
        scope = EventTaxonScope(
            event_id=event.id,
            taxon_id=taxon.id,
            designation="foundational",
            division="C",
            season=2026,
            list_version="foundations-1",
            reviewed=True,
        )
        candidate = SpecimenAsset(
            taxon_id=taxon.id,
            source_id=source.id,
            source_url="https://www.ars.usda.gov/candidate.jpg",
            media_type="image/jpeg",
            rights_status="metadata_only",
            license_name="pending",
            attribution="USDA ARS",
            alt_text="Candidate insect image",
            long_description="Candidate image awaiting independent rights review.",
            content_hash="a" * 64,
            review_status="pending",
            taxon_verified=True,
        )
        db.add_all([scope, candidate])
        db.commit()
        event_id = event.id
        taxon_id = taxon.id

    foundational = client.get(
        f"/api/events/{event_id}/taxonomy", headers=auth(student_token)
    )
    assert foundational.status_code == 200
    assert foundational.json()["scope_status"] == "foundational"
    assert foundational.json()["official_list_verified"] is False
    assert foundational.json()["image_release_ready"] is False
    assert foundational.json()["entries"][0]["asset_count"] == 1
    assert foundational.json()["entries"][0]["ready_asset_count"] == 0

    with SessionLocal() as db:
        scope = db.scalar(select(EventTaxonScope).where(
            EventTaxonScope.event_id == event_id,
            EventTaxonScope.taxon_id == taxon_id,
        ))
        scope.designation = "official"
        db.add(SpecimenAsset(
            taxon_id=taxon_id,
            source_id=scope.official_source_id or db.scalar(select(Source.id)),
            source_url="https://www.ars.usda.gov/reviewed.jpg",
            media_type="image/jpeg",
            rights_status="public_domain",
            license_name="U.S. Government work",
            attribution="USDA Agricultural Research Service",
            alt_text="Adult insect viewed from above with six legs attached to the thorax.",
            long_description=(
                "Dorsal view showing the head, three-segmented thorax, abdomen, one pair "
                "of antennae, and three pairs of legs originating on the thorax."
            ),
            content_hash="b" * 64,
            review_status="approved",
            taxon_verified=True,
        ))
        db.commit()

    ready = client.get(f"/api/events/{event_id}/taxonomy", headers=auth(student_token)).json()
    assert ready["scope_status"] == "official"
    assert ready["official_list_verified"] is True
    assert ready["image_release_ready"] is True
    assert ready["entries"][0]["ready_asset_count"] == 1
