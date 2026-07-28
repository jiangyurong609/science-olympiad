"""Register the official Science Olympiad 2027 Division B/C event slate."""
from __future__ import annotations

import argparse
import json

from app.core.database import SessionLocal
from app.services.season_catalog import OFFICIAL_2027_SLATE_URL, register_2027_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--keep-older-current",
        action="store_true",
        help="Do not relabel older current-season events as foundational",
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        report = register_2027_catalog(
            db,
            apply=args.apply,
            archive_older=not args.keep_older_current,
        )
    output = report.to_dict()
    output["official_slate"] = OFFICIAL_2027_SLATE_URL
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
