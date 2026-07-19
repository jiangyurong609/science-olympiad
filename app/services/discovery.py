from __future__ import annotations

import hashlib
import ipaddress
import posixpath
import socket
from xml.etree import ElementTree
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import CrawlDomainPolicy, DiscoveredResource
from app.services.rights import domain_allowed


TRACKING_PARAMETERS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "ref", "referrer",
}


class DiscoveryError(RuntimeError):
    pass


def matching_domain_policy(db: Session, domain: str) -> CrawlDomainPolicy | None:
    policies = db.scalars(select(CrawlDomainPolicy)).all()
    matches = [
        policy for policy in policies
        if domain == policy.domain or domain.endswith(f".{policy.domain}")
    ]
    return max(matches, key=lambda policy: len(policy.domain)) if matches else None


def canonicalize_url(value: str, base_url: str | None = None) -> str:
    absolute = urljoin(base_url, value) if base_url else value
    parsed = urlparse(absolute.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise DiscoveryError("Only HTTP(S) resources can enter the discovery frontier")
    if parsed.username or parsed.password:
        raise DiscoveryError("URLs containing credentials are not allowed")
    host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    scheme = parsed.scheme.lower()
    port = parsed.port
    netloc = host if not port or (scheme == "https" and port == 443) or (
        scheme == "http" and port == 80
    ) else f"{host}:{port}"
    raw_path = parsed.path or "/"
    normalized_path = posixpath.normpath(raw_path)
    if raw_path.endswith("/") and not normalized_path.endswith("/"):
        normalized_path += "/"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    query_items = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_PARAMETERS:
            continue
        query_items.append((key, item))
    query = urlencode(sorted(query_items))
    canonical = urlunparse((scheme, netloc, normalized_path, "", query, ""))
    if len(canonical) > 2048:
        raise DiscoveryError("Canonical URL exceeds the supported length")
    return canonical


def record_discovered_resource(
    db: Session,
    url: str,
    *,
    referrer_url: str = "",
    discovery_method: str,
    source_tier: int | None = None,
) -> DiscoveredResource:
    canonical = canonicalize_url(url, referrer_url or None)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    existing = db.scalar(select(DiscoveredResource).where(
        DiscoveredResource.canonical_hash == digest
    ))
    now = datetime.now(timezone.utc)
    if existing:
        existing.discovery_count += 1
        existing.last_discovered_at = now
        if not existing.referrer_url and referrer_url:
            existing.referrer_url = referrer_url
        if existing.source_tier is None and source_tier is not None:
            existing.source_tier = source_tier
        db.add(existing)
        return existing
    domain = urlparse(canonical).hostname or ""
    policy = matching_domain_policy(db, domain)
    row = DiscoveredResource(
        canonical_url=canonical,
        canonical_hash=digest,
        discovered_url=urljoin(referrer_url, url) if referrer_url else url,
        domain=domain,
        referrer_url=referrer_url,
        discovery_method=discovery_method,
        source_tier=source_tier if source_tier is not None else (
            policy.source_tier if policy else None
        ),
        status="discovered",
        first_discovered_at=now,
        last_discovered_at=now,
    )
    db.add(row)
    db.flush()
    return row


def discover_html_links(
    db: Session,
    html: str,
    base_url: str,
    *,
    source_tier: int | None = None,
    max_links: int = 5000,
) -> list[DiscoveredResource]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[DiscoveredResource] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        try:
            canonical = canonicalize_url(href, base_url)
        except (DiscoveryError, ValueError):
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        found.append(record_discovered_resource(
            db,
            canonical,
            referrer_url=base_url,
            discovery_method="html_link",
            source_tier=source_tier,
        ))
        if len(found) >= max_links:
            break
    return found


def _approved_domains(db: Session) -> set[str]:
    configured = get_settings().crawl_allowlist
    reviewed = db.scalars(select(CrawlDomainPolicy).where(
        CrawlDomainPolicy.enabled.is_(True)
    )).all()
    return configured | {row.domain for row in reviewed}


def _validate_public_discovery_url(db: Session, url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DiscoveryError("Discovery fetching requires HTTPS")
    if not domain_allowed(url, _approved_domains(db)):
        raise DiscoveryError("Domain has no enabled discovery policy")
    policy = matching_domain_policy(db, parsed.hostname.lower())
    if policy:
        if not policy.enabled:
            raise DiscoveryError("Domain discovery policy is disabled")
        if policy.allow_paths and not any(parsed.path.startswith(path) for path in policy.allow_paths):
            raise DiscoveryError("URL path is outside the reviewed domain policy")
        if any(parsed.path.startswith(path) for path in policy.deny_paths):
            raise DiscoveryError("URL path is denied by the reviewed domain policy")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, 443)}
    except socket.gaierror as exc:
        raise DiscoveryError("Discovery hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise DiscoveryError("Discovery source resolves to a non-public network address")


def _robots_allows(client: httpx.Client, url: str, user_agent: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = client.get(robots_url)
    except httpx.HTTPError:
        return False
    if response.status_code == 404:
        return True
    if response.status_code >= 400:
        return False
    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(response.text.splitlines())
    return parser.can_fetch(user_agent, url)


def discover_sitemap(db: Session, sitemap_url: str, max_urls: int = 10_000) -> list[DiscoveredResource]:
    canonical = canonicalize_url(sitemap_url)
    _validate_public_discovery_url(db, canonical)
    policy = matching_domain_policy(db, urlparse(canonical).hostname or "")
    if policy:
        max_urls = min(max_urls, policy.max_urls)
    user_agent = "FieldstoneDiscoveryBot/0.3 (+rights-aware educational indexing)"
    headers = {"User-Agent": user_agent, "Accept": "application/xml,text/xml,application/rss+xml,application/atom+xml"}
    settings = get_settings()
    with httpx.Client(timeout=20, follow_redirects=False, headers=headers) as client:
        if not _robots_allows(client, canonical, user_agent):
            raise DiscoveryError("robots.txt does not allow sitemap discovery")
        current_url = canonical
        for _ in range(6):
            _validate_public_discovery_url(db, current_url)
            response = client.get(current_url)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise DiscoveryError("Sitemap redirect has no destination")
                current_url = canonicalize_url(location, current_url)
                continue
            response.raise_for_status()
            break
        else:
            raise DiscoveryError("Too many sitemap redirects")
    if len(response.content) > settings.crawl_max_bytes:
        raise DiscoveryError("Sitemap exceeds the configured byte limit")
    xml_prefix = response.content[:4096].upper()
    if b"<!DOCTYPE" in xml_prefix or b"<!ENTITY" in xml_prefix:
        raise DiscoveryError("Sitemap XML declarations are not allowed")
    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as exc:
        raise DiscoveryError("Sitemap or feed XML is malformed") from exc
    found: list[DiscoveredResource] = []
    root_name = root.tag.rsplit("}", 1)[-1].lower()
    if root_name in {"urlset", "sitemapindex"}:
        locations = [
            (element.text or "").strip()
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1].lower() == "loc" and (element.text or "").strip()
        ]
        method = "sitemap_index" if root_name == "sitemapindex" else "sitemap"
    else:
        locations = []
        for element in root.iter():
            name = element.tag.rsplit("}", 1)[-1].lower()
            if name == "link":
                candidate = element.attrib.get("href") or (element.text or "")
                if candidate.strip():
                    locations.append(candidate.strip())
        method = "feed"
    for location in locations[:max_urls]:
        try:
            found.append(record_discovered_resource(
                db,
                location,
                referrer_url=current_url,
                discovery_method=method,
            ))
        except DiscoveryError:
            continue
    db.commit()
    return found
