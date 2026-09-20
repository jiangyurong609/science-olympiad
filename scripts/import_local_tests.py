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
  python -m scripts.import_local_tests --scan --root docs/science_olympiad_tests/_extracted/public-rsoi-2026-B
  python -m scripts.import_local_tests --parse --limit 5

--root narrows a scan to one subtree. A scan registers each PDF once, keyed by URL, and never
revisits it — so a file that is still being written when the scan reaches it is registered
truncated and stays that way. Point --root at the archives that have finished downloading.
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
    "material science": "materials science",
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
    # Underscores and hyphens are word characters to the regex engine, so \btest\b never
    # matched "BullSO_Div_B_Test.pdf" and "KEY BullSO..." (key first in the name) never
    # matched "[_ ]key" — both fell through to reference_material and were never parsed.
    low = re.sub(r"[_\-.]+", " ", name.lower())
    if re.search(r"answer\s*key|answerkey|\bkey\b", low):
        return "answer_key"
    if re.search(r"answer\s*sheet|answersheet", low):
        return "answer_sheet"
    if re.search(r"reference|resource|cheat|image\s*sheet", low):
        return "reference_material"
    if re.search(r"\btest\b|\bexam\b|stations?\b|question\s*sheets?\b|\bquestions\b", low):
        return "test"
    if re.search(r"checklist|rubric|score", low):
        return "team_checklist"
    return "reference_material"


def _build_event_index(db):
    """Map normalized 'name + division' -> Event for our division-specific events.

    Superseded events are excluded: a source mapped to one strands its import — the exam
    publishes under an event no catalog view lists (`import_past_test` now refuses this
    outright, but the mapping should never be created in the first place)."""
    # A 2026 event and its 2027 twin share a name and a division, so they collide on this
    # key and whichever the query yielded LAST used to win — arbitrarily. That is how Anatomy
    # & Physiology ended up with six past papers on the current event and three on the prior
    # season one: same subject, same papers, two places, depending on row order. The current
    # event wins now, because it is the one a student is shown.
    rank = {"current": 3, "foundational": 2, "prior_season_practice": 1}
    index: dict[tuple[str, str], Event] = {}
    for event in db.scalars(select(Event).where(Event.official_url != "")).all():
        if event.season_status == "superseded":
            continue
        key = (_norm(event.name), event.division)
        held = index.get(key)
        if held is None or rank.get(event.season_status, 0) > rank.get(held.season_status, 0):
            index[key] = event
    return index


_DIVISION_IN_PATH = re.compile(
    r"division\s+([bc])\b|div\s+([bc])\b|\[div\s+([bc])\]|\b([bc])\b\s*$")
# A filename states its own division in ways a folder name does not: `..._2019_c_umich_test`,
# `Disease_Detectives_C_Test`, `2018-Thermodynamics-State-C`.
_DIVISION_IN_NAME = re.compile(r"[_\- ]([bc])[_\- .]|[_\- ]([bc])\.[a-z]+$")


def _detect_division(relpath: str) -> str | None:
    """Which division this paper is for — the FILE's own answer beats its folder's.

    Tournaments hand both divisions one folder, named for both: `Disease Detectives B C`
    holds `Disease_Detectives_B_Test.pdf` and `Disease_Detectives_C_Test.pdf` side by side.
    Reading the folder gives "B" for both, and the Division C paper is then filed under the
    Division B event and offered to middle-school students as their own past test.
    """
    low = relpath.lower()
    name = low.rsplit("/", 1)[-1]
    for pattern, text in ((_DIVISION_IN_NAME, name), (_DIVISION_IN_PATH, name),
                          (_DIVISION_IN_PATH, low)):
        m = pattern.search(text)
        if m:
            return next(g for g in m.groups() if g).upper()
    return None


def _match_event(index, relpath: str) -> Event | None:
    norm_path = _norm(relpath)
    for alias, canonical in ALIASES.items():
        # word-bounded: the substring form turned "windpower" into "win[dynamic planet]ower"
        # and published two Wind Power papers under Dynamic Planet
        norm_path = re.sub(rf"\b{re.escape(alias)}\b", canonical, norm_path)
    division = _detect_division(relpath)
    best = None
    for (name, div), event in index.items():
        # an unscoped "B/C" event serves both divisions, so either detected division matches
        division_ok = division is None or div == division or div == "B/C"
        if name and name in norm_path and division_ok:
            # prefer the longest event-name match to avoid 'optics' vs 'optics lab' slips;
            # between equal names, a division-exact event beats a B/C twin
            if (best is None or len(name) > len(_norm(best.name))
                    or (len(name) == len(_norm(best.name)) and best.division == "B/C" and div == division)):
                best = event
    return best


def _iter_pdfs(root: Path):
    for path in sorted(root.rglob("*.pdf")):
        yield path


def scan(db, root: Path | None = None) -> None:
    root = root or ROOT
    if not root.exists():
        raise SystemExit(f"Extracted tree not found: {root}")
    index = _build_event_index(db)
    created = mapped = tests = keys = skipped_blank = unmapped = 0
    unmapped_dirs = set()
    for path in _iter_pdfs(root):
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


def reclassify(db) -> None:
    """Re-run the (fixed) filename classifier over already-registered local sources.

    `--scan` is idempotent by URL and never revisits an existing Source, so a classifier fix
    alone leaves every earlier misclassification in place. This updates the stored role and
    the EventSourceMap purpose, and prints each change so the sweep is reviewable."""
    changes = {}
    for source in db.scalars(select(Source).where(Source.url.like("local://%"))).all():
        meta = dict(source.metadata_json or {})
        relpath = meta.get("relpath", "")
        if not relpath:
            continue
        old = meta.get("role")
        new = _classify(Path(relpath).name)
        if new == old:
            continue
        meta["role"] = new
        source.metadata_json = meta
        for esm in db.scalars(select(EventSourceMap).where(
                EventSourceMap.source_id == source.id)).all():
            esm.purpose = new
        changes[(old, new)] = changes.get((old, new), 0) + 1
        print(f"  {old} -> {new}: {relpath}")
    db.commit()
    print(f"\nReclassified {sum(changes.values())} sources: "
          + ", ".join(f"{o}->{n}: {c}" for (o, n), c in sorted(changes.items())))


def remap(db) -> None:
    """Give unmapped local sources another chance against the current event catalog.

    `--scan` maps a source once, at registration. Events added later (Protein Modeling) and
    matcher fixes (Materials Science's missing alias) leave registered sources permanently
    unmapped unless something retries them — this does, and prints every new mapping."""
    index = _build_event_index(db)
    mapped = 0
    for source in db.scalars(select(Source).where(Source.url.like("local://%"))).all():
        if db.scalar(select(EventSourceMap).where(EventSourceMap.source_id == source.id)):
            continue
        meta = source.metadata_json or {}
        relpath = meta.get("relpath", "")
        event = _match_event(index, relpath)
        if not event:
            continue
        db.add(EventSourceMap(
            event_id=event.id, source_id=source.id, purpose=meta.get("role", "test"),
            source_tier=0, required=False, required_artifact_types=["parsed_text"],
            source_universe_version=UNIVERSE, reviewed=True,
            notes="local past-test import (remapped)",
        ))
        mapped += 1
        print(f"  {event.slug:28} <- {relpath}")
    db.commit()
    print(f"\nRemapped {mapped} sources.")


def rescope(db) -> None:
    """Re-point already-registered local sources at the event the matcher picks TODAY.

    `--scan` maps a source once and `--remap` only visits sources with no mapping at all, so
    a fix to the matcher or a change in which twin is current leaves every existing mapping
    as it was. This recomputes them.

    It refuses to touch a source whose test has already been PARSED: the resulting Exam and
    its Questions point at the old event, and moving the mapping alone would leave a source
    claiming one event and its paper sitting on another. Move those with
    `scripts/port_past_tests_to_current`, which moves the paper and its questions together.
    """
    index = _build_event_index(db)
    parsed = {(e.blueprint or {}).get("exam_source_id")
              for e in db.scalars(select(Exam)).all()}
    parsed.discard(None)
    changed = skipped = 0
    for source in db.scalars(select(Source).where(Source.url.like("local://%"))).all():
        meta = source.metadata_json or {}
        relpath = meta.get("relpath", "")
        event = _match_event(index, relpath) if relpath else None
        if event is None:
            continue
        for esm in db.scalars(select(EventSourceMap).where(
                EventSourceMap.source_id == source.id)).all():
            if esm.event_id == event.id:
                continue
            if source.id in parsed:
                skipped += 1
                continue
            old = db.get(Event, esm.event_id)
            print(f"  {old.slug if old else esm.event_id} -> {event.slug}: {relpath}")
            esm.event_id = event.id
            changed += 1
    db.commit()
    print(f"\nRe-pointed {changed} mapping(s); left {skipped} alone because the test is "
          f"already parsed into an exam.")


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
    # Any exam that already names this source — published, held for review, or retired —
    # means the source has been parsed. Filtering on release_class == "past_test" missed the
    # 146 imports that carry "imported_practice", and a full run would have re-parsed and
    # re-published every one of them as a duplicate.
    already = {(e.blueprint or {}).get("exam_source_id")
               for e in db.scalars(select(Exam)).all()}
    already.discard(None)
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
            root = _arg("--root")
            scan(db, Path(root) if root else None)
        elif "--reclassify" in sys.argv:
            reclassify(db)
        elif "--remap" in sys.argv:
            remap(db)
        elif "--rescope" in sys.argv:
            rescope(db)
        elif "--parse" in sys.argv:
            parse(db, int(_arg("--limit")) if "--limit" in sys.argv else None)
        else:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
