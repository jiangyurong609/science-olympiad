"""Deterministic passage extraction for immutable source snapshots.

Passages are complete, locator-bearing slices used for claim, lesson, and
question grounding. The service never truncates the source to a model window.
"""
from __future__ import annotations

import hashlib
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import SourcePassage, SourceSnapshot


PAGE_RE = re.compile(r"(?m)^\[Page\s+(\d+)\]\s*$")
TIMESTAMP_RE = re.compile(
    r"(?m)^\[(?:(\d{1,2}:\d{2}(?::\d{2})?)|(\d+(?:\.\d+)?)s)\]\s*"
)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bounded_chunks(text: str, target_chars: int = 2_400) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for paragraph in paragraphs:
        if current and length + len(paragraph) + 2 > target_chars:
            chunks.append("\n\n".join(current))
            current, length = [], 0
        if len(paragraph) > target_chars:
            if current:
                chunks.append("\n\n".join(current))
                current, length = [], 0
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            sentence_chunk: list[str] = []
            sentence_length = 0
            for sentence in sentences:
                if len(sentence) > target_chars:
                    if sentence_chunk:
                        chunks.append(" ".join(sentence_chunk))
                        sentence_chunk, sentence_length = [], 0
                    words = sentence.split()
                    hard_chunk: list[str] = []
                    hard_length = 0
                    for word in words:
                        if hard_chunk and hard_length + len(word) + 1 > target_chars:
                            chunks.append(" ".join(hard_chunk))
                            hard_chunk, hard_length = [], 0
                        # A single token can exceed the target (for example,
                        # malformed OCR). Preserve every character while still
                        # bounding the stored passage.
                        while len(word) > target_chars:
                            if hard_chunk:
                                chunks.append(" ".join(hard_chunk))
                                hard_chunk, hard_length = [], 0
                            chunks.append(word[:target_chars])
                            word = word[target_chars:]
                        if word:
                            hard_chunk.append(word)
                            hard_length += len(word) + 1
                    if hard_chunk:
                        chunks.append(" ".join(hard_chunk))
                    continue
                if sentence_chunk and sentence_length + len(sentence) + 1 > target_chars:
                    chunks.append(" ".join(sentence_chunk))
                    sentence_chunk, sentence_length = [], 0
                sentence_chunk.append(sentence)
                sentence_length += len(sentence) + 1
            if sentence_chunk:
                chunks.append(" ".join(sentence_chunk))
            continue
        current.append(paragraph)
        length += len(paragraph) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _page_passages(text: str) -> list[dict]:
    markers = list(PAGE_RE.finditer(text))
    rows = []
    for index, marker in enumerate(markers):
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        page = marker.group(1)
        for part, chunk in enumerate(_bounded_chunks(text[start:end]), start=1):
            suffix = f", part {part}" if part > 1 else ""
            rows.append({
                "locator": f"Page {page}{suffix}",
                "heading": f"Page {page}",
                "passage_type": "pdf_page",
                "text": chunk,
                "metadata_json": {"page": int(page), "part": part},
            })
    return rows


def _timestamp_passages(text: str) -> list[dict]:
    markers = list(TIMESTAMP_RE.finditer(text))
    if not markers:
        return []
    segments: list[tuple[str, str]] = []
    for index, marker in enumerate(markers):
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        segment = text[start:end].strip()
        if segment:
            if marker.group(1):
                timestamp = marker.group(1)
            else:
                seconds = float(marker.group(2))
                hours, remainder = divmod(int(seconds), 3600)
                minutes, secs = divmod(remainder, 60)
                timestamp = (
                    f"{hours:02d}:{minutes:02d}:{secs:02d}"
                    if hours else f"{minutes:02d}:{secs:02d}"
                )
            segments.append((timestamp, segment))
    rows, current, start_time, end_time = [], [], None, None
    current_length = 0
    for timestamp, segment in segments:
        if current and current_length + len(segment) > 2_400:
            rows.append({
                "locator": f"Video {start_time}–{end_time}",
                "heading": "",
                "passage_type": "video_transcript",
                "text": "\n".join(current),
                "metadata_json": {"start": start_time, "end": end_time},
            })
            current, current_length, start_time = [], 0, None
        start_time = start_time or timestamp
        end_time = timestamp
        current.append(f"[{timestamp}] {segment}")
        current_length += len(segment)
    if current:
        rows.append({
            "locator": f"Video {start_time}–{end_time}",
            "heading": "",
            "passage_type": "video_transcript",
            "text": "\n".join(current),
            "metadata_json": {"start": start_time, "end": end_time},
        })
    return rows


def extract_passage_payloads(snapshot: SourceSnapshot) -> list[dict]:
    text = (snapshot.extracted_text or "").strip()
    if not text:
        return []
    if PAGE_RE.search(text):
        rows = _page_passages(text)
        if rows:
            return rows
    if (snapshot.metadata_json or {}).get("kind") == "youtube_transcript":
        rows = _timestamp_passages(text)
        if rows:
            return rows
    passage_type = "html_section" if "html" in (snapshot.content_type or "") else "text_section"
    return [{
        "locator": f"Section {index}",
        "heading": "",
        "passage_type": passage_type,
        "text": chunk,
        "metadata_json": {"section": index},
    } for index, chunk in enumerate(_bounded_chunks(text), start=1)]


def ensure_source_passages(db: Session, snapshot: SourceSnapshot, *, commit: bool = True) -> list[SourcePassage]:
    existing = db.scalars(select(SourcePassage).where(
        SourcePassage.source_snapshot_id == snapshot.id
    ).order_by(SourcePassage.sequence, SourcePassage.id)).all()
    if existing:
        return existing
    rows = []
    for sequence, payload in enumerate(extract_passage_payloads(snapshot), start=1):
        passage = SourcePassage(
            source_id=snapshot.source_id,
            source_snapshot_id=snapshot.id,
            sequence=sequence,
            locator=payload["locator"],
            heading=payload["heading"],
            passage_type=payload["passage_type"],
            text=payload["text"],
            content_hash=_hash(payload["text"]),
            metadata_json=payload["metadata_json"],
        )
        db.add(passage)
        rows.append(passage)
    if commit:
        db.commit()
    return rows
