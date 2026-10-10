# Test fixture provenance

- `schema_valid_empty.csv` — synthetic header row only (no data rows); created for empty-valid parse tests.
- `schema_drift.csv` — synthetic; required column `referenceNumber-numeroReference` removed.
- `issued_by_bait.txt` — synthetic one-line HTML-ish text for deadline regression (not a network capture).

Reference rows with real CanadaBuys field shapes are read from repo-root
`source-evidence/canadabuys-reference.csv` (read-only evidence; not copied here).
