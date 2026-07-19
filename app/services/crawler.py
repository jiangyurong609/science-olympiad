import hashlib
import ipaddress
import socket
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from io import BytesIO
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.models.entities import (
    CrawlDomainPolicy, RawArtifact, Source, SourceChange, SourceMetadataCheck, SourceSnapshot,
)
from app.services.rights import can_fetch_full_text, domain_allowed
from app.services.discovery import discover_html_links, matching_domain_policy
from app.services.artifacts import ArtifactError, store_raw_artifact
from app.services.source_changes import classify_source_change, quarantine_source_dependents
from app.services.crawl_schedule import mark_crawl_success


class CrawlError(RuntimeError):
    pass


def _enforce_domain_policy(db: Session, url: str) -> None:
    parsed = urlparse(url)
    policy = matching_domain_policy(db, parsed.hostname or "")
    if not policy:
        return
    if not policy.enabled:
        raise CrawlError("Domain crawl policy is disabled")
    if policy.allow_paths and not any(parsed.path.startswith(path) for path in policy.allow_paths):
        raise CrawlError("Source path is outside the reviewed domain policy")
    if any(parsed.path.startswith(path) for path in policy.deny_paths):
        raise CrawlError("Source path is denied by the reviewed domain policy")


def _clean_html(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    return title, text[:500_000]


def _validate_public_host(url: str, allowlist: set[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise CrawlError("Production crawling requires a public HTTPS source")
    if not domain_allowed(url, allowlist):
        raise CrawlError("Domain is not in the crawl allowlist")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise CrawlError("Source hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise CrawlError("Source resolves to a non-public network address")


def _robots_allowed(client: httpx.Client, url: str, user_agent: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = client.get(robots_url)
        if response.status_code == 404:
            return True
        if response.status_code >= 400:
            return False
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return parser.can_fetch(user_agent, url)
    except httpx.HTTPError:
        return False


def _stream_response(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    max_bytes: int,
) -> httpx.Response:
    chunks: list[bytes] = []
    total = 0
    with client.stream("GET", url, headers=headers) as response:
        if response.status_code != 304 and not response.is_redirect:
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise CrawlError("Source exceeds configured crawl size limit")
                chunks.append(chunk)
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=b"".join(chunks),
            request=response.request,
        )


def crawl_source(db: Session, source: Source) -> Source:
    settings = get_settings()
    if not can_fetch_full_text(source.rights_status) or not source.approved:
        raise CrawlError("Approved rights policy does not allow full-text crawling")
    user_agent = "FieldstoneStudyBot/0.4 (+rights-aware educational indexing)"
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml,application/pdf"}
    prior_metadata = source.metadata_json or {}
    conditional_headers = {}
    if prior_metadata.get("etag"):
        conditional_headers["If-None-Match"] = prior_metadata["etag"]
    if prior_metadata.get("last_modified"):
        conditional_headers["If-Modified-Since"] = prior_metadata["last_modified"]
    current_url = source.url
    previous_snapshot = db.scalar(select(SourceSnapshot).where(
        SourceSnapshot.source_id == source.id
    ).order_by(SourceSnapshot.id.desc()))
    reviewed_domains = {
        policy.domain for policy in db.scalars(select(CrawlDomainPolicy).where(
            CrawlDomainPolicy.enabled.is_(True)
        )).all()
    }
    allowed_domains = settings.crawl_allowlist | reviewed_domains
    with httpx.Client(timeout=20, follow_redirects=False, headers=headers) as client:
        _validate_public_host(current_url, allowed_domains)
        if not _robots_allowed(client, current_url, user_agent):
            raise CrawlError("robots.txt does not allow crawling this URL")
        for _ in range(6):
            _validate_public_host(current_url, allowed_domains)
            _enforce_domain_policy(db, current_url)
            response = _stream_response(
                client,
                current_url,
                conditional_headers,
                settings.crawl_max_bytes,
            )
            if response.status_code == 304:
                break
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise CrawlError("Redirect response had no destination")
                current_url = urljoin(current_url, location)
                continue
            if response.status_code != 304:
                response.raise_for_status()
            break
        else:
            raise CrawlError("Too many redirects")
    now = datetime.now(timezone.utc)
    if response.status_code == 304:
        mark_crawl_success(db, source, now)
        source.metadata_json = {
            **prior_metadata,
            "last_checked_at": now.isoformat(),
            "last_fetch_status": 304,
        }
        db.add(source)
        db.commit()
        db.refresh(source)
        return source
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type and "application/pdf" not in content_type:
        raise CrawlError(f"Unsupported content type: {content_type}")
    try:
        artifact_info = store_raw_artifact(response.content, content_type)
    except ArtifactError as exc:
        raise CrawlError(str(exc)) from exc
    if prior_metadata.get("raw_content_hash") == artifact_info["content_hash"]:
        mark_crawl_success(db, source, now)
        source.metadata_json = {
            **prior_metadata,
            "etag": response.headers.get("etag", prior_metadata.get("etag", "")),
            "last_modified": response.headers.get(
                "last-modified", prior_metadata.get("last_modified", "")
            ),
            "last_checked_at": now.isoformat(),
            "last_fetch_status": response.status_code,
        }
        db.add(source)
        db.commit()
        db.refresh(source)
        return source
    if "text/html" in content_type:
        title, text = _clean_html(response.text)
        parser = "html"
        discovered_links = discover_html_links(db, response.text, current_url)
    elif "application/pdf" in content_type:
        try:
            reader = PdfReader(BytesIO(response.content))
            title = str((reader.metadata or {}).get("/Title") or "")
            pages = []
            for page_number, page in enumerate(reader.pages[:250], start=1):
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    pages.append(f"[Page {page_number}]\n{page_text}")
            text = "\n\n".join(pages)[:500_000]
            parser = "pypdf"
        except Exception as exc:
            raise CrawlError("PDF parsing failed") from exc
        if not text:
            raise CrawlError("PDF contains no extractable text")
    else:
        raise CrawlError(f"Unsupported content type: {content_type}")
    if "text/html" not in content_type:
        discovered_links = []
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    change_kind, change_summary = (
        classify_source_change(previous_snapshot.extracted_text, text)
        if previous_snapshot else ("initial", {
            "similarity": None,
            "previous_characters": 0,
            "current_characters": len(text),
        })
    )
    snapshot = SourceSnapshot(
        source_id=source.id,
        final_url=current_url,
        content_hash=digest,
        content_type=content_type,
        byte_count=len(response.content),
        extracted_text=text,
        previous_snapshot_id=previous_snapshot.id if previous_snapshot else None,
        etag=response.headers.get("etag", ""),
        last_modified=response.headers.get("last-modified", ""),
        change_kind=change_kind,
        metadata_json={
            "status_code": response.status_code,
            "parser": parser,
            "discovered_link_count": len(discovered_links),
        },
    )
    db.add(snapshot)
    db.flush()
    db.add(RawArtifact(snapshot_id=snapshot.id, **artifact_info))
    source.title = title or source.title or source.url
    source.extracted_text = text
    source.content_hash = digest
    mark_crawl_success(db, source, now)
    source.metadata_json = {
        **(source.metadata_json or {}),
        "content_type": content_type,
        "bytes": len(response.content),
        "final_url": current_url,
        "snapshot_hash": digest,
        "parser": parser,
        "discovered_link_count": len(discovered_links),
        "raw_content_hash": artifact_info["content_hash"],
        "raw_artifact_key": artifact_info["storage_key"],
        "etag": response.headers.get("etag", ""),
        "last_modified": response.headers.get("last-modified", ""),
        "last_checked_at": now.isoformat(),
        "last_fetch_status": response.status_code,
        "change_kind": change_kind,
    }
    db.add(source)
    if previous_snapshot:
        impact = quarantine_source_dependents(db, source) if change_kind == "material" else {}
        db.add(SourceChange(
            source_id=source.id,
            previous_snapshot_id=previous_snapshot.id,
            current_snapshot_id=snapshot.id,
            change_kind=change_kind,
            review_status="pending" if change_kind == "material" else "auto_accepted",
            summary=change_summary,
            impact=impact,
        ))
    db.commit()
    db.refresh(source)
    return source


def check_source_metadata(db: Session, source: Source) -> SourceMetadataCheck:
    if not source.approved or source.rights_status not in {"link_only", "metadata_only"}:
        raise CrawlError("Source is not approved for metadata-only monitoring")
    settings = get_settings()
    user_agent = "FieldstoneStudyBot/0.4 (+body-free source monitoring)"
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.1",
    }
    prior = source.metadata_json or {}
    if prior.get("etag"):
        headers["If-None-Match"] = prior["etag"]
    if prior.get("last_modified"):
        headers["If-Modified-Since"] = prior["last_modified"]
    reviewed_domains = {
        policy.domain for policy in db.scalars(select(CrawlDomainPolicy).where(
            CrawlDomainPolicy.enabled.is_(True)
        )).all()
    }
    allowed_domains = settings.crawl_allowlist | reviewed_domains
    current_url = source.url
    with httpx.Client(timeout=20, follow_redirects=False, headers={"User-Agent": user_agent}) as client:
        _validate_public_host(current_url, allowed_domains)
        if not _robots_allowed(client, current_url, user_agent):
            raise CrawlError("robots.txt does not allow monitoring this URL")
        for _ in range(6):
            _validate_public_host(current_url, allowed_domains)
            _enforce_domain_policy(db, current_url)
            response = client.head(current_url, headers=headers)
            if response.status_code in {405, 501}:
                # Some publishers disable HEAD. Request at most the first byte and
                # deliberately never iterate or persist the response body.
                range_headers = {**headers, "Range": "bytes=0-0"}
                with client.stream("GET", current_url, headers=range_headers) as streamed:
                    response = httpx.Response(
                        streamed.status_code,
                        headers=streamed.headers,
                        content=b"",
                        request=streamed.request,
                    )
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise CrawlError("Redirect response had no destination")
                current_url = urljoin(current_url, location)
                continue
            if response.status_code != 304:
                response.raise_for_status()
            break
        else:
            raise CrawlError("Too many redirects")
    now = datetime.now(timezone.utc)
    length_text = response.headers.get("content-length")
    try:
        content_length = int(length_text) if length_text is not None else None
    except ValueError:
        content_length = None
    check = SourceMetadataCheck(
        source_id=source.id,
        final_url=current_url,
        status_code=response.status_code,
        content_type=response.headers.get("content-type", "")[:160],
        content_length=content_length,
        etag=response.headers.get("etag", prior.get("etag", ""))[:500],
        last_modified=response.headers.get(
            "last-modified", prior.get("last_modified", "")
        )[:500],
        checked_at=now,
    )
    db.add(check)
    mark_crawl_success(db, source, now)
    source.metadata_json = {
        **prior,
        "monitoring_mode": "metadata_only",
        "final_url": current_url,
        "content_type": check.content_type,
        "content_length": content_length,
        "etag": check.etag,
        "last_modified": check.last_modified,
        "last_checked_at": now.isoformat(),
        "last_fetch_status": response.status_code,
    }
    db.add(source)
    db.commit()
    db.refresh(check)
    return check
