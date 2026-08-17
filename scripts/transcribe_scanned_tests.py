"""Transcribe scanned (image-only) past tests so the ordinary import path can read them.

Some collected PDFs are flattened scans: the BullSO25 Dynamic Planet exams and the Wichita
Heights 2026 tests are clean, importable papers, but pypdf extracts zero text, so `--scan`
skipped them as blank and they never became sources. This renders each page with pdftoppm,
transcribes it with the vision model, and registers the Source + SourceSnapshot + RawArtifact
exactly as a text PDF would have been — after which `import_past_test` needs no special casing.

The worklist is explicit, not a directory sweep: each entry names its answer key (they live in
sibling folders the same-folder key pairing cannot see) and the event it belongs to (divisions
verified against the papers themselves). Cipher tests (Codebusters), specimen-station events
(Entomology, per 2027 lineup) and subjects with no live event are deliberately absent.

Usage: [--only <substring>] [--dry-run]
"""
import argparse
import base64
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import httpx
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import (
    Event, EventSourceMap, RawArtifact, Source, SourceSnapshot,
)
from app.services import media_storage
from app.services.past_test_import import import_past_test

ROOT = Path("docs/science_olympiad_tests/_extracted")
UNIVERSE = "local-tests-v1"

W = "Tests & Keys - Heights Invite 2026"
B = "Division B Tests and Answer Keys/Dynamic Planet (1)"
C = "Division C Tests and Answer Keys/Dynamic Planet (1)"
U = "2025 UW River Falls Border Battle Tests"

# (relpath, role, event_slug, key_relpath) — key_relpath None means import without a key,
# and a bare key entry (role answer_key, no import) just registers the key for its exam's
# source folder so a later re-import can pick it up.
WORKLIST = [
    (f"{W}/Tests/Remote Sensing - Wichita Heights Div C 2026 TEST.pdf", "test",
     "remote-sensing-c", f"{W}/Keys/Remote Sensing - Wichita Heights Div C 2026 KEY.pdf"),
    # Engineering CAD deliberately absent: its "test" is a set of orthographic drawings to
    # model in CAD software — there are no questions to transcribe (verified by eye).
    (f"{B}/2025_B_BULLSO_DP_EXAM.pdf", "test",
     "dynamic-planet-b", f"{B}/2025_B_BULLSO_DP_KEY (1).pdf"),
    (f"{C}/2025_C_BULLSO_DP_EXAM.pdf", "test",
     "dynamic-planet-c", f"{C}/2025_C_BULLSO_DP_KEY (1).pdf"),
    (f"{U}/6 disease detectives/DONE 6 SO Print 16 SINGLE-SIDED COLOR Disease Detectives 2025 - Exam Booklet.pdf",
     "test", "disease-detectives-c",
     f"{U}/6 disease detectives/DONE 6 SO Print 3 Disease Detectives 2025 - Answer Key.pdf"),
    (f"{U}/16 material science/DONE 16 SO Print 16 Materials Science 2025 Exam booklet.pdf",
     "test", "materials-science-c", None),
    # keys for papers already imported (or imported above) — registered, not parsed directly
    (f"{W}/Keys/Chemistry Lab - Wichita Heights Div C 2026 KEY.pdf", "answer_key",
     "chemistry-lab-c", None),
    (f"{W}/Keys/Designer Genes - Wichita Heights Div C 2026 KEY.pdf", "answer_key",
     "designer-genes-c", None),
    (f"{W}/Keys/Materials Science - Wichita Heights Div C 2026 KEY.pdf", "answer_key",
     "materials-science-c", None),
    (f"{U}/11 forensics/Forensics 2025 Key.pdf", "answer_key", "forensics-c", None),
]

PROMPT = (
    "Transcribe this scanned Science Olympiad page faithfully to plain text. Preserve the "
    "printed question numbers, answer choice letters and text, section headings, point "
    "values, and any caption lines exactly as printed. Render tables as aligned plain text. "
    "Where a photograph, chart, map or diagram appears, insert a single bracketed line like "
    "[Figure: brief factual description] at its position. Output only the transcription — "
    "no commentary, no markdown fences."
)


def _vision_page(image_path: Path, base_url: str, api_key: str, model: str) -> str:
    # 100 DPI JPEG keeps a page around 100 KB; the 150 DPI PNG first tried was megabytes of
    # base64 and the endpoint reset the connection rather than refuse it politely
    data = base64.b64encode(image_path.read_bytes()).decode()
    last = None
    for _ in range(3):
        try:
            response = httpx.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}},
                ]}]},
                timeout=180,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError) as exc:
            last = exc
    raise RuntimeError(f"vision transcription failed after retries: {last}")


def transcribe(path: Path, base_url: str, api_key: str, model: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", "100", "-jpeg", "-jpegopt", "quality=70",
                        str(path), f"{tmp}/page"],
                       check=True, capture_output=True)
        pages = sorted(Path(tmp).glob("page-*.jpg"))
        out = []
        for number, png in enumerate(pages, start=1):
            text = _vision_page(png, base_url, api_key, model)
            out.append(f"[Page {number}]\n{text}")
            print(f"      page {number}/{len(pages)}: {len(text)} chars", flush=True)
        return "\n\n".join(out)


def register(db, relpath: str, role: str, event_slug: str, text: str) -> Source:
    url = f"local://{relpath}"
    path = ROOT / relpath
    source = db.scalar(select(Source).where(Source.url == url))
    if not source:
        source = Source(url=url, title=path.stem, publisher="Science Olympiad (local import)")
        db.add(source)
    source.metadata_json = {"local_import": True, "role": role, "relpath": relpath,
                            "catalog_version": UNIVERSE, "transcription": "vision_ocr"}
    db.flush()
    snapshot = SourceSnapshot(
        source_id=source.id, final_url=url, content_hash="",
        content_type="application/pdf", byte_count=path.stat().st_size,
        extracted_text=text, change_kind="initial",
    )
    db.add(snapshot)
    db.flush()
    if not db.scalar(select(RawArtifact).where(RawArtifact.snapshot_id == snapshot.id)):
        data = path.read_bytes()
        key = f"sources/{source.id}/snapshot-{snapshot.id}/{path.name}"
        stored = media_storage.upload_media(key, data, "application/pdf")
        db.add(RawArtifact(snapshot_id=snapshot.id, storage_key=getattr(stored, "key", key),
                           content_hash=hashlib.sha256(data).hexdigest(), byte_count=len(data),
                           detected_media_type="application/pdf", scan_status="local_corpus"))
    event = db.scalar(select(Event).where(Event.slug == event_slug))
    assert event, f"no event {event_slug}"
    if not db.scalar(select(EventSourceMap).where(EventSourceMap.source_id == source.id)):
        db.add(EventSourceMap(event_id=event.id, source_id=source.id, purpose=role,
                              source_tier=0, required=False,
                              required_artifact_types=["parsed_text"],
                              source_universe_version=UNIVERSE, reviewed=True,
                              notes="scanned paper transcribed by vision model"))
    db.commit()
    return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    base_url = os.environ["OPENAI_COMPATIBLE_BASE_URL"]
    api_key = os.environ["OPENAI_API_KEY"]
    model = os.environ["OPENAI_MODEL"]
    db = SessionLocal()

    def _done(relpath: str, role: str) -> bool:
        """Already transcribed (and for tests, already carrying an exam) — safe to skip."""
        source = db.scalar(select(Source).where(Source.url == f"local://{relpath}"))
        if not source or (source.metadata_json or {}).get("transcription") != "vision_ocr":
            return False
        if role != "test":
            return True
        from sqlalchemy import text as sql
        return bool(db.execute(sql(
            "select 1 from exams where (blueprint::jsonb->>'exam_source_id')::int = :s limit 1"
        ).bindparams(s=source.id)).first())

    worklist = [w for w in WORKLIST if not args.only or args.only.lower() in w[0].lower()]
    print(f"{len(worklist)} documents to transcribe", flush=True)
    failures = []
    for relpath, role, event_slug, key_rel in worklist:
        path = ROOT / relpath
        assert path.exists(), f"missing on disk: {relpath}"
        if _done(relpath, role):
            print(f"\n== [{role}] {relpath}\n    already done — skipping", flush=True)
            continue
        print(f"\n== [{role}] {relpath}", flush=True)
        if args.dry_run:
            continue
        try:
            text = transcribe(path, base_url, api_key, model)
            source = register(db, relpath, role, event_slug, text)
            print(f"    registered source {source.id} · {len(text)} chars", flush=True)
            if role != "test":
                continue
            key_source = None
            if key_rel:
                key_path = ROOT / key_rel
                assert key_path.exists(), f"key missing on disk: {key_rel}"
                if not _done(key_rel, "answer_key"):
                    key_text = transcribe(key_path, base_url, api_key, model)
                    key_source = register(db, key_rel, "answer_key", event_slug, key_text)
                    print(f"    registered key source {key_source.id} · {len(key_text)} chars", flush=True)
                else:
                    key_source = db.scalar(select(Source).where(Source.url == f"local://{key_rel}"))
            event = db.scalar(select(Event).where(Event.slug == event_slug))
            result = import_past_test(db, event, source, key_source)
            print(f"    import: parsed {result['parsed_items']} · created {result['questions_created']}"
                  f" · withheld from exam {result.get('withheld_from_exam')}"
                  f" · exam {result['exam_id']}", flush=True)
        except Exception as exc:  # noqa: BLE001 — one broken scan must not strand the rest
            db.rollback()
            failures.append((relpath, f"{type(exc).__name__}: {str(exc)[:120]}"))
            print(f"    FAILED: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
    print(f"\ndone · failures: {len(failures)}", flush=True)
    for rel, why in failures:
        print(f"  {rel}: {why}", flush=True)


if __name__ == "__main__":
    main()
