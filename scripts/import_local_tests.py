"""Import local past-test PDF bundles into the system.

Point it at an extracted tree (default docs/science_olympiad_tests/_extracted) of
tournament PDFs. Two phases, split to control token cost:

  --scan   FREE (no LLM): extract text with pypdf, create a Source + SourceSnapshot
           for every meaningful PDF, classify test/key/other, map each to one of our
           events, link an EventSourceMap, and print a manifest. Costs no tokens.

  --parse [--limit N]  LLM: turn un-parsed Test sources into past_test Questions + a
           mock Exam (reusing past_test_import), pairing each test with its answer key.
           Only Test PDFs are ever sent to the model; keys ride along in the same call.

Usage:
  python -m scripts.import_local_tests --scan
  python -m scripts.import_local_tests --parse --limit 5
"""
from __future__ import annotations

import re
import sys
from io import BytesIO
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Event, EventSourceMap, Exam, Source, SourceSnapshot,
)
from app.services.past_test_import import import_past_test

ROOT = Path("docs/science_olympiad_tests/_extracted")
UNIVERSE = "local-tests-v1"
MIN_CHARS = 300

# Normalized-name aliases for tournament spellings that differ from our event names.
ALIASES = {
    "crimebusters": "crime busters",
    "helicopters": "helicopter",
    "a&p": "anatomy and physiology",
    "anatomy & physiology": "anatomy and physiology",
    "chem lab": "chemistry lab",
    "wq": "water quality",
    "dp": "dynamic planet",
    "codebusters": "codebusters",
}


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _norm(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    try:
        reader = PdfReader(BytesIO(path.read_bytes()))
    except Exception:  # noqa: BLE001
        return ""
    pages = []
    for number, page in enumerate(reader.pages[:250], start=1):
        try:
            extracted = (page.extract_text() or "").strip()
        except Exception:  # noqa: BLE001
            extracted = ""
        if extracted:
            pages.append(f"[Page {number}]\n{extracted}")
    return "\n\n".join(pages)[:500_000]


def _classify(name: str) -> str:
    low = name.lower()
    if re.search(r"answer\s*key|answerkey|[_ ]key\b|key\.pdf", low):
        return "answer_key"
    if re.search(r"answer\s*sheet|answersheet", low):
        return "answer_sheet"
    if re.search(r"\btest\b|\bexam\b|stations?\b", low):
        return "test"
    if re.search(r"reference|resource|cheat", low):
        return "reference_material"
    if re.search(r"checklist|rubric|score", low):
        return "team_checklist"
    return "reference_material"


def _build_event_index(db):
    """Map normalized 'name + division' -> Event for our division-specific events."""
    index = {}
    for event in db.scalars(select(Event).where(Event.official_url != "")).all():
        index[(_norm(event.name), event.division)] = event
    return index


def _detect_division(relpath: str) -> str | None:
    m = re.search(r"division\s+([bc])\b|div\s+([bc])\b|\[div\s+([bc])\]|\b([bc])\b\s*$",
                  relpath.lower())
    if m:
        return next(g for g in m.groups() if g).upper()
    return None


def _match_event(index, relpath: str) -> Event | None:
    norm_path = _norm(relpath)
    for alias, canonical in ALIASES.items():
        if alias in norm_path:
            norm_path = norm_path.replace(alias, canonical)
    division = _detect_division(relpath)
    best = None
    for (name, div), event in index.items():
        if name and name in norm_path and (division is None or div == division):
            # prefer the longest event-name match to avoid 'optics' vs 'optics lab' slips
            if best is None or len(name) > len(_norm(best.name)):
                best = event
    return best


def _iter_pdfs(root: Path):
    for path in sorted(root.rglob("*.pdf")):
        yield path


def scan(db) -> None:
    if not ROOT.exists():
        raise SystemExit(f"Extracted tree not found: {ROOT}")
    index = _build_event_index(db)
    created = mapped = tests = keys = skipped_blank = unmapped = 0
    unmapped_dirs = set()
    for path in _iter_pdfs(ROOT):
        relpath = str(path.relative_to(ROOT))
        url = f"local://{relpath}"
        if db.scalar(select(Source).where(Source.url == url)):
            continue  # idempotent
        text = _pdf_text(path)
        if len(text.strip()) < MIN_CHARS:
            skipped_blank += 1
            continue
        role = _classify(path.name)
        event = _match_event(index, relpath)
        source = Source(url=url, title=path.stem, publisher="Science Olympiad (local import)")
        source.extracted_text = text
        source.metadata_json = {"local_import": True, "role": role, "relpath": relpath,
                                "catalog_version": UNIVERSE}
        db.add(source)
        db.flush()
        db.add(SourceSnapshot(
            source_id=source.id, final_url=url, content_hash="",
            content_type="application/pdf", byte_count=path.stat().st_size,
            extracted_text=text, change_kind="initial",
        ))
        created += 1
        if role == "test":
            tests += 1
        elif role == "answer_key":
            keys += 1
        if event:
            mapped += 1
            db.add(EventSourceMap(
                event_id=event.id, source_id=source.id, purpose=role, source_tier=0,
                required=False, required_artifact_types=["parsed_text"],
                source_universe_version=UNIVERSE, reviewed=True,
                notes="local past-test import",
            ))
        else:
            unmapped += 1
            unmapped_dirs.add(str(Path(relpath).parent))
        db.commit()
    print(f"Scan complete: {created} sources created "
          f"({tests} tests, {keys} keys), {skipped_blank} blank skipped.")
    print(f"Event-mapped: {mapped} | unmapped: {unmapped}")
    if unmapped_dirs:
        print(f"Unmapped folders ({len(unmapped_dirs)}) — events not in our catalog or unrecognized:")
        for d in sorted(unmapped_dirs)[:25]:
            print(f"   {d}")


def _paired_key(db, test_source: Source):
    """A same-event, same-folder answer-key source with the best filename overlap."""
    meta = test_source.metadata_json or {}
    folder = str(Path(meta.get("relpath", "")).parent)
    esm = db.scalar(select(EventSourceMap).where(EventSourceMap.source_id == test_source.id))
    if not esm:
        return None
    keys = []
    for other in db.scalars(select(Source).where(Source.url.like("local://%"))).all():
        om = other.metadata_json or {}
        if om.get("role") != "answer_key" or str(Path(om.get("relpath", "")).parent) != folder:
            continue
        oesm = db.scalar(select(EventSourceMap).where(EventSourceMap.source_id == other.id))
        if oesm and oesm.event_id == esm.event_id:
            keys.append(other)
    return keys[0] if keys else None


def parse(db, limit: int | None) -> None:
    already = {(e.blueprint or {}).get("exam_source_id")
               for e in db.scalars(select(Exam).where(Exam.release_class == "past_test")).all()}
    test_sources = []
    for source in db.scalars(select(Source).where(Source.url.like("local://%"))).all():
        meta = source.metadata_json or {}
        if meta.get("role") != "test" or source.id in already:
            continue
        esm = db.scalar(select(EventSourceMap).where(EventSourceMap.source_id == source.id))
        if esm:
            test_sources.append((source, esm.event_id))
    if limit:
        test_sources = test_sources[:limit]
    print(f"Parsing {len(test_sources)} local test sources…\n")
    made = 0
    for index, (source, event_id) in enumerate(test_sources, start=1):
        event = db.get(Event, event_id)
        key_source = _paired_key(db, source)
        try:
            result = import_past_test(
                db, event, source, key_source, feedback_mode="after_submit", min_questions=3,
            )
            if result.get("exam_id"):
                made += 1
                print(f"[{index}/{len(test_sources)}] {event.slug:26} {source.title[:34]!r} -> "
                      f"exam {result['exam_id']} ({result['questions_created']} q)"
                      f"{' +key' if key_source else ''}")
            else:
                print(f"[{index}/{len(test_sources)}] skip {source.title[:40]!r} (too few questions)")
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            print(f"[{index}/{len(test_sources)}] FAIL {source.title[:40]!r}: {str(exc)[:80]}")
    print(f"\nDone: {made} exams created from local tests.")


def main() -> None:
    with SessionLocal() as db:
        if "--scan" in sys.argv:
            scan(db)
        elif "--parse" in sys.argv:
            parse(db, int(_arg("--limit")) if "--limit" in sys.argv else None)
        else:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
