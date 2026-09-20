"""Download past tests that tournaments publish publicly, into the local import tree.

Several tournaments post their own tests and answer keys in a public Google Drive folder —
UT Austin (ATX), Rickards (RSOI), Cornell, Princeton and MIT all do. A public folder page
embeds its whole listing in a `_DRIVE_ivd` blob, so the folder can be walked and its files
downloaded with no API key and no login.

The point of doing this is narrow: `scripts/import_local_tests` already turns a tree of
tournament PDFs into past-test Exams, and the corpus it was given holds nothing at all for
Botany, Thermodynamics or Food Science, and one or two papers for Codebusters, Experimental
Design and Write It Do It. A generated practice paper for those subjects has no measured
shape of its own to match (see `scripts/profile_past_exams`). This fetches the papers so it
does.

It downloads ONLY files whose folder path names an event we are building, and only the roles
that matter to an import: the test, its answer key, and the image or reference sheet an item
may depend on. Every file keeps a provenance record naming the archive and the Drive id.

    python -m scripts.fetch_public_test_archives --manifest walk.jsonl --plan
    python -m scripts.fetch_public_test_archives --manifest walk.jsonl --download

Walk a folder first to produce the manifest:

    python -m scripts.fetch_public_test_archives --walk <folder_id> --label atx-inv-2025
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
FOLDER_MIME = "application/vnd.google-apps.folder"
DEST = Path("docs/science_olympiad_tests/_extracted")

# The subjects a 2027 Division B season is built from. Values are the substrings that appear
# in a tournament's folder or file names for that event; tournaments spell them freely.
EVENT_KEYS = {
    "Anatomy and Physiology": ["anatomy", "a&p", "a_p", "anatomy_and_physiology"],
    "Botany": ["botany"],
    "Circuit Lab": ["circuit"],
    "Codebusters": ["codebuster", "code buster"],
    "Crime Busters": ["crime buster", "crimebuster"],
    "Disease Detectives": ["disease detective", "diseasedetective"],
    "Dynamic Planet": ["dynamic planet", "dynamicplanet"],
    "Experimental Design": ["experimental design", "exp design", "exdes"],
    "Food Science": ["food science", "foodscience"],
    "Heredity": ["heredity"],
    "Meteorology": ["meteorolog"],
    "Remote Sensing": ["remote sensing", "remotesensing"],
    "Rocks and Minerals": ["rocks and mineral", "rocks & mineral", "rocksandmineral",
                           "rocks_and_mineral"],
    "Solar System": ["solar system", "solarsystem"],
    "Thermodynamics": ["thermodynam", "thermo"],
    "Water Quality": ["water quality", "waterquality"],
    "Write It Do It": ["write it do it", "write-it-do-it", "widi", "write it, do it"],
}

# `import_local_tests` reads the division out of the FOLDER PATH ("Division B", "Div C").
# A test exchange filename spells it `_2021_b_`, which no word boundary can see because an
# underscore is a word character — so every paper would arrive with an unknown division and
# a Division C paper could be filed under the Division B event of the same name. The division
# is lifted out here and written into the path the importer will read.
DIVISION = re.compile(
    r"[_\- /](?:div(?:ision)?[ _\-]*)?([bc])[_\- /]"      # ..._2021_b_ut..., Div B/...
    r"|\bdiv(?:ision)?\s*([bc])\b"                        # Division C
    r"|[_\- ]([bc])\.[a-z]+$",                            # 2018-Thermodynamics-State-C.pdf
    re.I)

# An import needs the paper, the key, and whatever the paper's items point AT. Everything
# else in a tournament folder — team checklists, scoring rubrics, statistics images, build
# specs — is noise for this purpose and is left where it is.
WANTED = re.compile(
    r"test|exam|\bkey\b|answer|question|station|image\s*sheet|reference|resource", re.I)
UNWANTED = re.compile(r"checklist|rubric|statistic|score\s*sheet|roster|schedule", re.I)


def _curl(url: str, out: Path | None = None) -> bytes:
    cmd = ["curl", "-sL", "--max-time", "120", "-A", UA, url]
    if out:
        cmd += ["-o", str(out)]
        subprocess.run(cmd, check=False)
        return b""
    return subprocess.run(cmd, capture_output=True).stdout


def listing(folder_id: str) -> list[dict]:
    html = _curl(f"https://drive.google.com/drive/folders/{folder_id}").decode(
        "utf-8", "ignore")
    i = html.find("_DRIVE_ivd")
    if i < 0:
        return []
    start = html.index("'", html.index("=", i)) + 1
    raw = html[start:html.index("';", start)]
    decoded = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), raw)
    try:
        data = json.loads(decoded.replace("\\/", "/"))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for row in (data[0] or []):
        try:
            out.append({"id": row[0], "name": row[2], "mime": row[3]})
        except Exception:  # noqa: BLE001
            continue
    return out


def walk(folder_id: str, prefix: str = "", depth: int = 0, max_depth: int = 3):
    for entry in listing(folder_id):
        path = f"{prefix}/{entry['name']}" if prefix else entry["name"]
        if entry["mime"] == FOLDER_MIME:
            if depth < max_depth:
                time.sleep(0.3)
                yield from walk(entry["id"], path, depth + 1, max_depth)
        else:
            yield {**entry, "path": path}


def match_event(path: str) -> str | None:
    low = re.sub(r"[_\-]+", " ", path.lower())
    best = None
    for event, keys in EVENT_KEYS.items():
        for key in keys:
            if key in low and (best is None or len(key) > best[1]):
                best = (event, len(key))
    return best[0] if best else None


# A university invitational runs Division C only, and its folder tree never says so because
# there is nothing to distinguish it from. Without this the papers arrive division-unknown and
# the importer is free to file a high-school paper under the middle-school event.
DIVISION_C_ONLY = ("mit", "princeton", "cornell", "uchicago")


def detect_division(path: str, archive: str = "") -> str | None:
    match = DIVISION.search(path)
    if match:
        return next(g for g in match.groups() if g).upper()
    if re.search(r"-([bc])$", archive, re.I):                # rsoi-2026-C
        return archive[-1].upper()
    if archive.split("-")[0].lower() in DIVISION_C_ONLY:
        return "C"
    return None


def _folder(archive: str, event: str, source_path: str) -> Path:
    division = detect_division(source_path, archive)
    parent = DEST / f"public-{archive}"
    return (parent / f"Division {division}" / event) if division else (parent / event)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9 ._()&-]+", "_", name)[:120]


def plan(manifest: Path) -> list[dict]:
    rows = []
    for line in manifest.read_text().splitlines():
        try:
            entry = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        path = entry.get("path")
        if not path or not path.lower().endswith(".pdf"):
            continue
        event = match_event(path)
        name = Path(path).name
        if not event or UNWANTED.search(name) or not WANTED.search(name):
            continue
        rows.append({
            "archive": entry["archive"], "event": event, "id": entry["id"],
            "name": name, "source_path": path,
        })
    return rows


def download(rows: list[dict]) -> None:
    made = skipped = failed = 0
    for row in rows:
        folder = _folder(row["archive"], row["event"], row["source_path"])
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / _safe(row["name"])
        if target.exists() and target.stat().st_size > 2000:
            skipped += 1
            continue
        _curl(f"https://drive.google.com/uc?export=download&id={row['id']}", target)
        # A Drive file over the scan threshold answers with an interstitial HTML page
        # instead of the bytes. Importing that would register a Source whose "test" is a
        # virus-scan warning, so it is refused here rather than discovered downstream.
        head = target.read_bytes()[:5] if target.exists() else b""
        if head != b"%PDF-":
            target.unlink(missing_ok=True)
            failed += 1
            print(f"  not a pdf (scan interstitial?): {row['event']} / {row['name']}")
            continue
        (folder / ".provenance.jsonl").open("a").write(json.dumps({
            "file": target.name, "archive": row["archive"], "drive_id": row["id"],
            "source_path": row["source_path"],
            "url": f"https://drive.google.com/file/d/{row['id']}/view",
        }) + "\n")
        made += 1
        time.sleep(0.2)
    print(f"downloaded {made}, already held {skipped}, failed {failed}")


def download_urls(spec: Path, tries: int = 4, pause: float = 1.0) -> None:
    """Fetch past tests that a host serves as ordinary PDFs, not through Drive.

    Some archives — a state program's event pages, or the Internet Archive's copy of a test
    exchange — link the paper directly. The line format is `archive|Event Name|url`, and the
    file lands in the same tree with the same provenance record, so the import path cannot
    tell the two routes apart.

    Two things go wrong here and both are silent:

    * A rapid run gets throttled and the response body is an error page, not a PDF. Retried
      with a backoff rather than counted as a missing paper — a first pass over 28 files
      "failed" 19 of them and every one fetched cleanly on a second, slower try.
    * The Internet Archive's crawler stops at 1 MiB. A larger paper comes back CUT OFF, and
      a cut-off test still opens: it just has fewer questions than the real one. Importing
      it would publish a paper that silently ends early, so a truncated capture is refused
      and reported. The response says so itself — `x-archive-orig-x-crawler-content-length`
      is the real size and exceeds what was stored.
    """
    made = failed = truncated = 0
    for line in spec.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        archive, event, url, *rest = line.split("|")
        folder = (DEST / f"public-{archive}" / f"Division {rest[0]}" / event) if rest \
            else _folder(archive, event, url)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / _safe(url.rsplit("/", 1)[-1])
        if target.exists() and target.stat().st_size > 2000:
            continue
        headers = ""
        for attempt in range(tries):
            headers = subprocess.run(
                ["curl", "-sL", "--max-time", "180", "-A", UA, "-D", "-", "-o", str(target),
                 url], capture_output=True, text=True).stdout
            if target.exists() and target.read_bytes()[:5] == b"%PDF-":
                break
            time.sleep(pause * (2 ** attempt))
        if not target.exists() or target.read_bytes()[:5] != b"%PDF-":
            target.unlink(missing_ok=True)
            failed += 1
            print(f"  not a pdf after {tries} tries: {url}")
            continue
        real = re.search(r"x-archive-orig-x-crawler-content-length:\s*(\d+)", headers, re.I)
        if real and int(real.group(1)) > target.stat().st_size:
            target.unlink()
            truncated += 1
            print(f"  truncated capture ({real.group(1)} bytes upstream): {target.name}")
            continue
        (folder / ".provenance.jsonl").open("a").write(json.dumps({
            "file": target.name, "archive": archive, "url": url}) + "\n")
        made += 1
        time.sleep(pause)
    print(f"downloaded {made}, truncated {truncated}, failed {failed}")


def reorganize() -> None:
    """Re-file everything already downloaded under the current division rules.

    The rules for reading a division out of a path got better twice while papers were coming
    down, and a file does not move itself. This applies today's rules to what is on disk, so
    a paper fetched before a fix is not left in a folder that tells the importer nothing.
    """
    moved = 0
    for pdf in sorted(DEST.glob("public-*/**/*.pdf")):
        parts = pdf.relative_to(DEST).parts
        archive = parts[0].removeprefix("public-")
        event = parts[-2]
        if len(parts) > 3 and parts[-3].startswith("Division "):
            continue                                         # already filed under a division
        target_dir = _folder(archive, event, f"{'/'.join(parts[1:])}")
        if target_dir == pdf.parent:
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        pdf.rename(target_dir / pdf.name)
        provenance = pdf.parent / ".provenance.jsonl"
        if provenance.exists():
            (target_dir / ".provenance.jsonl").open("a").write(
                "".join(line + "\n" for line in provenance.read_text().splitlines()
                        if json.loads(line).get("file") == pdf.name))
        moved += 1
    print(f"re-filed {moved} papers")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--walk")
    parser.add_argument("--label", default="archive")
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--urls", type=Path, help="lines of archive|Event Name|url")
    parser.add_argument("--reorganize", action="store_true")
    args = parser.parse_args()

    if args.reorganize:
        reorganize()
        return

    if args.urls:
        download_urls(args.urls)
        return

    if args.walk:
        for item in walk(args.walk, max_depth=args.max_depth):
            print(json.dumps({"archive": args.label, **item}), flush=True)
        return
    if not args.manifest:
        raise SystemExit(__doc__)
    rows = plan(args.manifest)
    by_event: dict[str, int] = {}
    for row in rows:
        by_event[row["event"]] = by_event.get(row["event"], 0) + 1
    print(json.dumps({"matched_files": len(rows),
                      "by_event": dict(sorted(by_event.items()))}, indent=2))
    if args.download:
        download(rows)


if __name__ == "__main__":
    main()
