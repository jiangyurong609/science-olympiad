# Google Sheet Material Import

The material spreadsheet can be loaded into Fieldstone without copying links by hand:

```text
https://docs.google.com/spreadsheets/d/1tiGm0vIj-3H8eGBotL8zJ2kwR52v7L7-Rjw9aC7d29A
```

The importer is intentionally two-phase. A run is a dry-run unless `--apply` is present.

## Current Sheet Assessment

As checked on 2026-07-28, tab `gid=0` contains 77 data rows:

- 41 `soinc.org` links
- 36 YouTube links
- 9 global or non-event resources
- 3 malformed PDF URLs ending in `.pdf4`, `.pdf6`, or `.pdf8`
- 65 otherwise valid event materials

The resources prepare teams for the 2027 season. They must not be silently attached to
same-named 2026 events. The 2027 event catalog must be registered first.

## Workflow

1. Register the official 2027 Division B and C events in the `events` table:

   ```bash
   PYTHONPATH=. uv run python -m scripts.register_2027_catalog --apply
   ```
2. Run a strict dry-run:

   ```bash
   PYTHONPATH=. uv run python -m scripts.import_material_sheet \
     --season 2027 \
     --strict \
     --report data/import-reports/material-sheet-2027-dry-run.json
   ```

3. Fix or remove every rejected row in the spreadsheet. To make valid season-wide
   workshops available to students, include them under the special `Season Resources`
   event with `--include-global`.
4. Run the exact import with `--apply`:

   ```bash
   PYTHONPATH=. uv run python -m scripts.import_material_sheet \
     --season 2027 \
     --include-global \
     --apply \
     --strict \
     --report data/import-reports/material-sheet-2027-apply.json
   ```

5. Re-run the dry-run or apply command. It should report existing sources and mappings,
   with zero new records.

For a pinned export instead of the live sheet:

```bash
PYTHONPATH=. uv run python -m scripts.import_material_sheet \
  --season 2027 \
  --csv path/to/export.csv \
  --report data/import-reports/material-sheet-2027-pinned.json
```

## Safety and Data Contract

The importer:

- requires the exact `Link Text` and `Internal URL Reference` columns;
- accepts only HTTPS/HTTP URLs canonicalized by the discovery service;
- allowlists `soinc.org`, `youtube.com`, and `youtu.be`;
- rejects malformed PDF suffixes and spreadsheet-rendering artifacts;
- carries generic rows forward only within a recognized event section;
- honors an explicit Division B or C marker in the row title;
- maps to events from the exact `--season` only;
- optionally maps valid season-wide rows to the `Season Resources` event;
- creates `Source` records as `link_only`, unapproved for generation;
- creates non-required, reviewed `EventSourceMap` links for student display;
- records the sheet ID, tab, row, row fingerprint, and full-export fingerprint;
- uses a stable source-universe key, so repeat imports are idempotent;
- commits the apply operation as one database transaction;
- writes a JSON report suitable for release evidence and troubleshooting.

The web application already reads these records through
`GET /api/events/{event_id}/materials`. Downloading, parsing, and retaining full text
remain separate rights-aware crawler operations.
