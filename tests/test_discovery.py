import httpx
from contextlib import contextmanager
import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    CrawlDomainPolicy, DiscoveredResource, RawArtifact, Source, SourceMetadataCheck,
    SourceSnapshot,
)
from app.services.crawler import CrawlError, _stream_response, check_source_metadata, crawl_source
from app.services.discovery import (
    canonicalize_url, discover_html_links, discover_sitemap, record_discovered_resource,
)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


class FakeHttpClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, url, **kwargs):
        request = httpx.Request("GET", url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /", request=request)
        if url.endswith("sitemap.xml"):
            return httpx.Response(
                200,
                content=(
                    b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    b"<url><loc>https://science.nasa.gov/topic/?utm_source=test&amp;b=2</loc></url>"
                    b"<url><loc>https://science.nasa.gov/second</loc></url></urlset>"
                ),
                headers={"content-type": "application/xml"},
                request=request,
            )
        return httpx.Response(
            200,
            text=(
                '<html><head><title>Approved page</title></head><body>'
                '<a href="/topic/?utm_source=test&amp;b=2">Topic</a>'
                '<a href="https://example.org/outside">External</a>'
                '</body></html>'
            ),
            headers={"content-type": "text/html; charset=utf-8"},
            request=request,
        )

    def head(self, url, **kwargs):
        request = httpx.Request("HEAD", url)
        return httpx.Response(
            200,
            headers={
                "content-type": "text/html; charset=utf-8",
                "content-length": "98765",
                "etag": '"metadata-v1"',
                "last-modified": "Mon, 01 Jun 2026 12:00:00 GMT",
            },
            content=b"THIS BODY MUST NEVER BE STORED",
            request=request,
        )

    @contextmanager
    def stream(self, method, url, **kwargs):
        yield self.get(url, **kwargs)


def public_dns(*args, **kwargs):
    return [(2, 1, 6, "", ("8.8.8.8", 443))]


def test_canonicalization_removes_tracking_and_deduplicates():
    value = canonicalize_url(
        "https://Example.com/path/../science/?utm_source=x&b=2&a=1#fragment"
    )
    assert value == "https://example.com/science/?a=1&b=2"
    with SessionLocal() as db:
        first = record_discovered_resource(
            db, value, discovery_method="manual_seed", source_tier=0
        )
        second = record_discovered_resource(
            db,
            "https://example.com/science/?b=2&a=1&utm_campaign=again",
            discovery_method="search",
        )
        db.commit()
        assert first.id == second.id
        assert second.discovery_count == 2


def test_streaming_fetch_aborts_at_byte_limit():
    with FakeHttpClient() as client:
        with pytest.raises(CrawlError, match="size limit"):
            _stream_response(client, "https://science.nasa.gov/page", {}, 16)


def test_html_discovery_records_internal_and_external_candidates():
    with SessionLocal() as db:
        rows = discover_html_links(
            db,
            '<a href="/one">One</a><a href="/one#repeat">Repeat</a>'
            '<a href="https://other.example/two">Two</a><a href="mailto:test@example.com">Mail</a>',
            "https://science.nasa.gov/root/",
        )
        db.commit()
        assert len(rows) == 2
        assert {row.domain for row in rows} == {"science.nasa.gov", "other.example"}


def test_sitemap_discovery_obeys_policy_and_canonicalizes(monkeypatch):
    monkeypatch.setattr("app.services.discovery.socket.getaddrinfo", public_dns)
    monkeypatch.setattr("app.services.discovery.httpx.Client", FakeHttpClient)
    with SessionLocal() as db:
        rows = discover_sitemap(db, "https://science.nasa.gov/sitemap.xml")
        assert len(rows) == 2
        assert rows[0].canonical_url == "https://science.nasa.gov/topic/?b=2"
        assert all(row.discovery_method == "sitemap" for row in rows)


def test_crawl_records_links_without_promoting_or_approving(monkeypatch):
    monkeypatch.setattr("app.services.crawler.socket.getaddrinfo", public_dns)
    monkeypatch.setattr("app.services.crawler.httpx.Client", FakeHttpClient)
    with SessionLocal() as db:
        source = Source(
            url="https://science.nasa.gov/root/page",
            title="Approved",
            rights_status="fact_grounding_allowed",
            approved=True,
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        crawled = crawl_source(db, source)
        candidates = db.scalars(select(DiscoveredResource)).all()
        assert crawled.metadata_json["discovered_link_count"] == 2
        assert len(candidates) == 2
        assert all(candidate.source_id is None for candidate in candidates)
        assert all(candidate.status == "discovered" for candidate in candidates)


def test_metadata_monitor_records_headers_without_body_or_snapshot(monkeypatch):
    monkeypatch.setattr("app.services.crawler.socket.getaddrinfo", public_dns)
    monkeypatch.setattr("app.services.crawler.httpx.Client", FakeHttpClient)
    with SessionLocal() as db:
        db.add(CrawlDomainPolicy(
            domain="soinc.org",
            enabled=True,
            source_tier=0,
            default_rights_status="metadata_only",
        ))
        source = Source(
            url="https://www.soinc.org/entomology-c",
            title="Official event page",
            rights_status="metadata_only",
            approved=True,
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        check = check_source_metadata(db, source)
        assert check.status_code == 200
        assert check.content_length == 98765
        assert check.etag == '"metadata-v1"'
        assert check.final_url == source.url
        assert source.metadata_json["monitoring_mode"] == "metadata_only"
        assert source.extracted_text is None
        assert db.scalar(select(SourceSnapshot)) is None
        assert db.scalar(select(RawArtifact)) is None
        assert len(db.scalars(select(SourceMetadataCheck)).all()) == 1


def test_reviewed_domain_policy_enables_new_domain_and_enforces_paths(monkeypatch):
    monkeypatch.setattr("app.services.crawler.socket.getaddrinfo", public_dns)
    monkeypatch.setattr("app.services.crawler.httpx.Client", FakeHttpClient)
    with SessionLocal() as db:
        db.add(CrawlDomainPolicy(
            domain="example.org",
            enabled=True,
            source_tier=2,
            default_rights_status="metadata_only",
            allow_paths=["/approved"],
            deny_paths=["/approved/private"],
        ))
        allowed = Source(
            url="https://learn.example.org/approved/page",
            title="Allowed",
            rights_status="fact_grounding_allowed",
            approved=True,
        )
        denied = Source(
            url="https://learn.example.org/approved/private/page",
            title="Denied",
            rights_status="fact_grounding_allowed",
            approved=True,
        )
        db.add_all([allowed, denied])
        db.commit()
        assert crawl_source(db, allowed).content_hash
        from app.services.crawler import CrawlError
        try:
            crawl_source(db, denied)
            assert False, "denied path should not be crawled"
        except CrawlError as exc:
            assert "denied" in str(exc)


def test_domain_policy_seed_frontier_and_promotion(client, admin_token, coach_token):
    denied = client.post(
        "/api/discovery/domain-policies",
        headers=auth(coach_token),
        json={"domain": "usgs.gov", "enabled": True, "source_tier": 1},
    )
    assert denied.status_code == 403
    policy = client.post(
        "/api/discovery/domain-policies",
        headers=auth(admin_token),
        json={
            "domain": "usgs.gov",
            "enabled": True,
            "source_tier": 1,
            "default_rights_status": "metadata_only",
        },
    )
    assert policy.status_code == 200
    seeds = client.post(
        "/api/discovery/seeds",
        headers=auth(admin_token),
        json={
            "urls": ["https://www.usgs.gov/minerals?utm_source=seed", "javascript:alert(1)"],
            "source_tier": 1,
        },
    )
    assert seeds.status_code == 200
    assert len(seeds.json()["accepted"]) == 1
    assert len(seeds.json()["rejected"]) == 1
    resource_id = seeds.json()["accepted"][0]["id"]
    frontier = client.get(
        "/api/discovery/frontier?domain=www.usgs.gov",
        headers=auth(admin_token),
    )
    assert frontier.status_code == 200
    assert frontier.json()[0]["canonical_url"] == "https://www.usgs.gov/minerals"
    promoted = client.post(
        f"/api/discovery/resources/{resource_id}/promote",
        headers=auth(admin_token),
        json={"title": "USGS Minerals", "publisher": "USGS"},
    )
    assert promoted.status_code == 200
    with SessionLocal() as db:
        source = db.get(Source, promoted.json()["source_id"])
        resource = db.get(DiscoveredResource, resource_id)
        policy_row = db.scalar(select(CrawlDomainPolicy).where(
            CrawlDomainPolicy.domain == "usgs.gov"
        ))
        assert source.approved is False
        assert source.rights_status == "metadata_only"
        assert resource.status == "review_pending"
        assert policy_row.enabled is True
