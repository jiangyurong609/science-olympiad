"""Durable upload ingestion for the Content Studio.

This first worker intentionally creates an unapproved SourceSnapshot. It does
not generate or publish lessons; authoring is a later, explicit staff action.
"""
from __future__ import annotations

import io
import hashlib
import re
import zipfile
from html import unescape
from datetime import datetime, timezone

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import EventSourceMap, ExtractionAsset, IngestionRun, RawArtifact, Source, SourcePassage, SourceSnapshot, UploadSubmission
from app.services.artifacts import read_raw_artifact


def _extract(content: bytes, media_type: str, filename: str) -> tuple[str, dict]:
    kind = (media_type or "").lower()
    if "pdf" in kind or filename.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs require a staff-assisted secure review")
        pages = []
        for number, page in enumerate(reader.pages, start=1):
            pages.append(f"[Page {number}]\n{page.extract_text() or ''}")
        text = "\n\n".join(pages).strip()
        return text, {"page_count": len(reader.pages), "extraction": "pypdf"}
    if kind.startswith("text/") or filename.lower().endswith((".txt", ".md", ".csv")):
        return content.decode("utf-8", errors="replace").strip(), {"page_count": 0, "extraction": "utf8"}
    suffix = filename.lower()
    if suffix.endswith(".docx") or "wordprocessingml.document" in kind:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
        text = re.sub(r"</w:p>", "\n\n", xml)
        text = re.sub(r"<w:tab[^>]*/>", "\t", text)
        text = re.sub(r"<[^>]+>", "", text)
        return unescape(text).strip(), {"page_count": 0, "extraction": "docx-xml"}
    if suffix.endswith(".pptx") or "presentationml.presentation" in kind:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            slide_names = sorted(name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name))
            slides = []
            for number, name in enumerate(slide_names, start=1):
                xml = archive.read(name).decode("utf-8", errors="replace")
                xml = re.sub(r"<a:br[^>]*/>", "\n", xml)
                xml = re.sub(r"<[^>]+>", "", xml)
                slides.append(f"[Slide {number}]\n{unescape(xml).strip()}")
        return "\n\n".join(slides).strip(), {"page_count": len(slides), "extraction": "pptx-xml"}
    if kind.startswith("image/") or suffix.endswith((".png", ".jpg", ".jpeg", ".webp")):
        raise ValueError("Image upload requires OCR review; no OCR engine is configured for this worker")
    raise ValueError("Unsupported upload type; use PDF, DOCX, PPTX, or UTF-8 text")


def _passages(text: str, diagnostics: dict) -> list[dict]:
    """Create stable, human-reviewable chunks with page/section locators."""
    chunks = []
    for index, raw in enumerate(re.split(r"\n\s*\n", text), start=1):
        body = re.sub(r"\s+", " ", raw).strip()
        if len(body) < 30:
            continue
        page = re.search(r"\[Page (\d+)\]", raw)
        locator = f"page:{page.group(1)}" if page else f"section:{index}"
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        chunks.append({"sequence": index, "locator": locator, "text": body, "content_hash": digest})
    return chunks


def process_ingestion_run(db: Session, run_id: int) -> IngestionRun:
    run = db.get(IngestionRun, run_id)
    if not run:
        raise ValueError("Ingestion run not found")
    if run.status == "completed" and run.stage in {"ready_for_review", "ready_for_authoring", "withdrawn"}:
        return run
    upload = db.get(UploadSubmission, run.upload_id)
    if not upload:
        raise ValueError("Upload submission not found")
    now = datetime.now(timezone.utc)
    run.status, run.stage, run.started_at = "running", "extracting", now
    upload.status = "extracting"
    db.commit()
    try:
        content = read_raw_artifact(upload.artifact_key)
        text, diagnostics = _extract(content, upload.declared_media_type, upload.filename)
        if len(text) < 80:
            raise ValueError("Extraction produced too little text for authoring")
        run.stage = "snapshotting"
        extraction = db.scalar(select(ExtractionAsset).where(ExtractionAsset.upload_id == upload.id))
        if not extraction:
            extraction = ExtractionAsset(
                upload_id=upload.id, page_count=int(diagnostics.get("page_count", 0)),
                text_chars=len(text), extraction_version="v2", artifact_key=upload.artifact_key,
                status="completed", diagnostics_json=diagnostics,
            )
            db.add(extraction)
            db.flush()
        source = db.scalar(select(Source).where(Source.content_hash == upload.sha256))
        if not source:
            source = Source(
                url=f"upload://{upload.sha256}", title=upload.filename,
                publisher="User submitted material", rights_status="quarantined",
                license_name="pending_review", content_hash=upload.sha256,
                extracted_text=text, metadata_json={"origin_type": "upload", "upload_id": upload.id},
                approved=False, crawl_status="uploaded",
            )
            db.add(source)
            db.flush()
        snapshot = db.scalar(select(SourceSnapshot).where(
            SourceSnapshot.source_id == source.id,
            SourceSnapshot.content_hash == upload.sha256,
        ))
        if not snapshot:
            snapshot = SourceSnapshot(
                source_id=source.id, final_url=source.url, content_hash=upload.sha256,
                content_type=upload.declared_media_type, byte_count=upload.byte_count,
                extracted_text=text, metadata_json={**diagnostics, "upload_id": upload.id},
            )
            db.add(snapshot)
            db.flush()
            db.add(RawArtifact(
                snapshot_id=snapshot.id, storage_key=upload.artifact_key,
                content_hash=upload.sha256, byte_count=upload.byte_count,
                detected_media_type=upload.declared_media_type, scan_status="basic_pass",
            ))
            for passage in _passages(text, diagnostics):
                db.add(SourcePassage(
                    source_id=source.id, source_snapshot_id=snapshot.id,
                    sequence=passage["sequence"], locator=passage["locator"],
                    text=passage["text"], content_hash=passage["content_hash"],
                    metadata_json={"extraction": diagnostics.get("extraction", "unknown")},
                ))
        if upload.event_id and not db.scalar(select(EventSourceMap).where(
            EventSourceMap.event_id == upload.event_id, EventSourceMap.source_id == source.id,
            EventSourceMap.purpose == "submitted_material",
        )):
            db.add(EventSourceMap(
                event_id=upload.event_id, source_id=source.id, purpose="submitted_material",
                source_tier=0, required=False, required_artifact_types=[upload.declared_media_type],
                source_universe_version="upload-v1", freshness_minutes=0, reviewed=False,
                notes="Submitted through Content Studio; pending rights and topic review",
            ))
        run.source_id = source.id
        run.stage, run.status = "ready_for_review", "completed"
        run.diagnostics_json = {**diagnostics, "text_chars": len(text), "source_id": source.id}
        upload.status = "needs_review"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        return run
    except Exception as error:
        db.rollback()
        run = db.get(IngestionRun, run_id)
        upload = db.get(UploadSubmission, run.upload_id)
        run.stage, run.status = "failed", "failed"
        run.diagnostics_json = {"error": str(error)[:1000]}
        run.finished_at = datetime.now(timezone.utc)
        upload.status = "needs_human_review"
        db.commit()
        raise
