"""Rights-aware YouTube metadata and transcript ingestion.

This deliberately downloads captions only (never the video).  A transcript is
stored as a versioned :class:`SourceSnapshot`; the source remains unapproved
until an editor verifies the caption rights and lesson grounding.
"""
from __future__ import annotations

import hashlib
import html
import re
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.orm import Session
from yt_dlp import YoutubeDL

from app.models.entities import Source, SourceSnapshot

VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_TIMING = re.compile(r"^(\d{2}:\d{2}:\d{2}[.,]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[.,]\d{3})")


class TranscriptError(RuntimeError):
    pass


def youtube_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith("/shorts/") or parsed.path.startswith("/embed/"):
            candidate = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else ""
        else:
            return None
    else:
        return None
    return candidate if VIDEO_RE.fullmatch(candidate or "") else None


def _timestamp(value: str) -> float:
    h, m, rest = value.replace(",", ".").split(":")
    s, fraction = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + float(f"0.{fraction}")


def parse_vtt(payload: str) -> list[dict]:
    """Parse WebVTT into deduplicated, timestamped caption segments."""
    segments: list[dict] = []
    lines = [line.lstrip("\ufeff") for line in payload.splitlines()]
    i = 0
    while i < len(lines):
        match = _TIMING.match(lines[i].strip())
        if not match:
            i += 1
            continue
        start, end = _timestamp(match.group(1)), _timestamp(match.group(2))
        i += 1
        text_lines = []
        while i < len(lines) and lines[i].strip():
            if not _TIMING.match(lines[i].strip()):
                text_lines.append(lines[i].strip())
            i += 1
        text = re.sub(r"<[^>]+>", "", html.unescape(" ".join(text_lines)))
        text = re.sub(r"\s+", " ", text).strip()
        if text and (not segments or text != segments[-1]["text"]):
            segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
        i += 1
    return segments


def _caption_track(info: dict) -> tuple[dict, str] | None:
    tracks = info.get("subtitles") or {}
    automatic = False
    if not tracks:
        tracks, automatic = info.get("automatic_captions") or {}, True
    for lang in ("en", "en-US", "en-GB"):
        if lang in tracks:
            choices = sorted(
                [x for x in tracks[lang] if x.get("ext") in {"vtt", "srv3", "json3"}],
                key=lambda x: {"vtt": 0, "srv3": 1, "json3": 2}.get(x.get("ext"), 9),
            )
            if choices:
                return choices[0], "auto" if automatic else "manual"
    for lang, choices in tracks.items():
        if lang.lower().startswith("en") and choices:
            return choices[0], "auto" if automatic else "manual"
    return None


def _parse_caption(payload: str, extension: str) -> list[dict]:
    if extension == "vtt":
        return parse_vtt(payload)
    if extension == "srv3":
        root = ElementTree.fromstring(payload)
        segments = []
        for node in root.findall(".//text"):
            text = re.sub(r"<[^>]+>", "", html.unescape("".join(node.itertext())))
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                start = float(node.attrib.get("start", 0))
                end = start + float(node.attrib.get("dur", 0))
                if not segments or text != segments[-1]["text"]:
                    segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
        return segments
    data = json.loads(payload)
    segments = []
    for event in data.get("events", []):
        parts = [p.get("utf8", "") for p in event.get("segs", [])]
        text = re.sub(r"\s+", " ", "".join(parts)).strip()
        if text:
            start = event.get("tStartMs", 0) / 1000
            end = start + event.get("dDurationMs", 0) / 1000
            if not segments or text != segments[-1]["text"]:
                segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    return segments


def fetch_youtube_transcript(url: str) -> dict:
    video_id = youtube_video_id(url)
    if not video_id:
        raise TranscriptError("URL is a YouTube channel or unsupported video URL")
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extractor_args": {"youtube": {"player_client": ["android"]}}}
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            track = _caption_track(info)
            if not track:
                raise TranscriptError("No English captions available")
            caption, caption_source = track
            raw = ydl.urlopen(caption["url"]).read().decode("utf-8", "replace")
    except TranscriptError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a stable ingestion error
        raise TranscriptError(str(exc)[:300]) from exc
    segments = _parse_caption(raw, caption.get("ext", "vtt"))
    if not segments:
        raise TranscriptError("Caption track was empty or could not be parsed")
    text = "\n".join(f"[{s['start']:.1f}s] {s['text']}" for s in segments)
    return {
        "video_id": video_id,
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
        "caption_language": "en",
        "caption_source": caption_source,
        "segments": segments,
        "text": text,
    }


def ingest_youtube_source(db: Session, source: Source, *, commit: bool = True) -> dict:
    video = fetch_youtube_transcript(source.url)
    text = video.pop("text")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    prior = db.scalar(select(SourceSnapshot).where(
        SourceSnapshot.source_id == source.id, SourceSnapshot.content_hash == digest,
    ))
    now = datetime.now(timezone.utc)
    if prior:
        return {"source_id": source.id, "status": "unchanged", "video_id": video["video_id"], "text_chars": len(text)}
    previous = db.scalar(select(SourceSnapshot).where(
        SourceSnapshot.source_id == source.id,
    ).order_by(SourceSnapshot.id.desc()))
    metadata = {"kind": "youtube_transcript", "transcript_status": "pending_review", **video,
                "retrieved_at": now.isoformat(), "transcript_hash": digest}
    snapshot = SourceSnapshot(
        source_id=source.id, final_url=video["webpage_url"], content_hash=digest,
        content_type="text/vtt; profile=transcript", byte_count=len(text.encode("utf-8")),
        extracted_text=text, metadata_json=metadata,
        previous_snapshot_id=previous.id if previous else None,
        change_kind="initial" if previous is None else "updated",
    )
    db.add(snapshot)
    source.content_hash = digest
    source.extracted_text = text
    source.metadata_json = {**(source.metadata_json or {}), "video": metadata}
    source.fetched_at = now
    source.last_successful_crawl_at = now
    source.crawl_status = "transcript_pending_review"
    source.last_crawl_error = ""
    if commit:
        db.commit()
    return {"source_id": source.id, "status": "transcribed", "video_id": video["video_id"], "text_chars": len(text)}
