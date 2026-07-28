"""Validate and import the public Science Olympiad material spreadsheet.

Dry-run is the default. Add --apply only after reviewing the JSON report.

Examples:
  python -m scripts.import_material_sheet --season 2027
  python -m scripts.import_material_sheet --season 2027 --apply
  python -m scripts.import_material_sheet --season 2027 --csv exported.csv
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import httpx

from app.core.database import SessionLocal
from app.services.material_sheet_import import import_materials, utc_timestamp


DEFAULT_SPREADSHEET_ID = "1tiGm0vIj-3H8eGBotL8zJ2kwR52v7L7-Rjw9aC7d29A"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--spreadsheet-id", default=DEFAULT_SPREADSHEET_ID)
    parser.add_argument("--gid", default="0")
    parser.add_argument("--csv", type=Path, help="Use a local CSV export instead of Google Sheets")
    parser.add_argument("--report", type=Path, help="Write the JSON report to this path")
    parser.add_argument("--apply", action="store_true", help="Commit accepted rows to the database")
    parser.add_argument(
        "--include-global",
        action="store_true",
        help="Map global workshop rows to the registered season-resources event",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any row is rejected or globally unmapped",
    )
    return parser.parse_args()


def _download(spreadsheet_id: str, gid: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", spreadsheet_id):
        raise ValueError("Invalid Google spreadsheet ID")
    if not re.fullmatch(r"\d+", gid):
        raise ValueError("Google Sheet gid must be numeric")
    url = (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export"
        f"?format=csv&gid={gid}"
    )
    response = httpx.get(url, follow_redirects=True, timeout=30)
    response.raise_for_status()
    payload = response.content
    if not payload or b"Internal URL Reference" not in payload[:4096]:
        raise ValueError(
            "Google Sheets did not return the expected CSV. "
            "Confirm that link sharing allows read access."
        )
    return payload


def main() -> int:
    args = _arguments()
    payload = args.csv.read_bytes() if args.csv else _download(args.spreadsheet_id, args.gid)
    with SessionLocal() as db:
        report = import_materials(
            db,
            payload,
            season=args.season,
            spreadsheet_id=args.spreadsheet_id,
            gid=args.gid,
            apply=args.apply,
            include_global=args.include_global,
        )
    output = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    print(output)
    report_path = args.report
    if report_path is None:
        mode = "apply" if args.apply else "dry-run"
        report_path = (
            Path("data")
            / "import-reports"
            / f"material-sheet-{args.season}-{mode}-{utc_timestamp()}.json"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(f"{output}\n")
    print(f"Report written to {report_path}")
    if args.strict and (report.rejected or report.skipped_global):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
