# Trustworthy radar — fix-back report

**Worktree:** `/Users/user/.hermes/profiles/rig/workspace/porcupine-trustworthy-radar`
**Scope:** Fix-back per independent verifier (`FIXBACK-BRIEF.md`); no commit/push/cutover.

Every defect below is a way the radar could lie. Each fix is the mechanism that stops it.

## Defects addressed — threat, then fix

| Threat (how the radar could lie) | Fix (mechanism) |
|--------|-----|
| Header handling assumed one shape — a differently-shaped response breaks parsing silently | `_header_value` + `_response_charset`; legacy `_Headers` mocks and dict headers both work |
| Parser stopped at 40 unique rows — the intake censored the market before ranking | Removed intake shortlist break; parse through `CSV_MAX_ROWS`; shortlist applied after `assemble` in CLI |
| Header-only vs empty body vs all-rejected conflated — three different failures, one "empty" | `empty_valid` only when schema OK and zero data rows; blank body → `unsupported`; raw>0 valid=0 → `partial` |
| Test asserted funding the fixture never had — a test proving a fiction | RF row asserts `$250,000`; missing funding tested via `fixtures/no_funding_row.csv` |
| Cache hits stamped fiction timestamps — replayed data wearing fresh clothes | `read_cache_payload`; cache hits return stored `fetched_at`; replay sets `fetched_at=replay_offline`, `live_fetch=false` |
| Truncation got cached — a partial file became the "truth" on disk | Unchanged guard; charset fix keeps truncation test on dict headers |
| Duplicates/amendments passed in silence | `duplicate_rows`, `unique_rows`, `identity_policy=first_wins_by_source_and_id` in parse stats and feeds |

## Per-file changes

| File | Change |
|------|--------|
| `porcupine/radar.py` | Full CSV intake; duplicate stats; cache `fetched_at`; content-addressed `source-snapshots/` under runtime root; stamp acquisition on each opportunity |
| `porcupine/cli.py` | `assemble` carries provenance into ranked.json/ledger; `run`/`replay-csv` pass `snapshot_root`; feed lines note snapshot ref / persistence warnings |
| `porcupine/config.py` | **Unchanged** (caps documented in report) |
| `tests/test_trustworthy_radar.py` | Expanded acceptance (closed/same-day/provenance/shortlist/cap/replay/cache/truncation/byte partial) |
| `tests/fixtures/no_funding_row.csv` | Synthetic row with no stated funding |
| `tests/fixtures/all_rows_rejected.csv` | Negative control: schema OK, zero valid rows |
| `tests/test_porcupine.py` | **Byte-identical** (not edited) |

## Hash domains (explicit)

**Threat:** one hash name covering two different byte streams — verification passes against the wrong thing.

- **`body_text_sha256`:** SHA-256 of decoded Unicode text used for CSV/HTML parse (UTF-8 encode). No newline canonicalization: CRLF and LF are distinct decoded text and yield different hashes. Verify stored snapshots with `read_bytes().decode("utf-8")`, not `read_text()` (universal newline translation).
- **`body_bytes_sha256`:** SHA-256 of raw downloaded bytes on live fetch only; empty on cache/replay.

Do not equate text and byte hashes or assume capture download hash matches normalized text.

## Acquisition provenance (opportunity + ledger)

**Threat:** a record that can't prove where it came from is a rumor with formatting. A later cache overwrite must never orphan a saved record.

| Field | Meaning |
|-------|---------|
| `fetched_at` | Original cache acquisition time when `how=cache`; `unknown` on offline replay; live ISO on fresh fetch |
| `acquisition_how` | `cache`, `fetched`, `replay`, or `body` |
| `live_fetch` | `true` only when this run performed a network GET for that body |
| `source_snapshot_ref` | Relative path under runtime `--root`, e.g. `source-snapshots/<body_text_sha256>.txt` (decoded text UTF-8 bytes; deduped by text hash; reuse verifies stored bytes match hash) |
| `source_snapshot_meta_ref` | Sidecar JSON keyed by SHA-256 of canonical acquisition identity (source id/url, `acquired_at`, how, live/offline, byte/text hashes, `parse_outcome`; excludes `observed_at`). Same body from two feeds shares one `.txt` but distinct meta refs. Immutable: mismatch on existing `.txt` yields warning and empty refs |
| `evidence_persistence_warning` | Set when snapshot write fails, supplied `body_text_sha256` ≠ computed body hash, or existing snapshot bytes disagree with hash; no snapshot ref is claimed |

Feed-level fields in `feeds.json` mirror the same acquisition; each scored opportunity and ledger row carries a copy so a later cache overwrite cannot orphan a saved record.

## Heuristic labeling

**Threat:** labels that imply knowledge they don't have.

- **EV / `ev_label`:** heuristic priority only (`heuristic_priority_uncalibrated`); not financial return or win probability.
- **`p_win_lcb`:** Wilson lower bound on recorded wins; not per-target win likelihood.

## Final fix-back (promotion gate)

| Threat | Fix |
|--------|-----|
| Auto-draft on any `open` row — including irrelevant construction | `_draft_open` requires `disposition=='matched'` and `open is True`; separate NO-VERIFIED-MATCH vs NO-OPEN notes |
| Per-feed counts cloned from global shortlist — feeds taking credit for each other's work | `per_source_run_counts` by `source` id; feed lines include `matched=` |
| Silent CSV field truncation — data lost without a trace | `field_overflow:*` rejection + `rejection_reasons`; parser limit raised/restored safely |
| Unknown/missing publisher status → confirmed open — absence of evidence treated as evidence | CanadaBuys rows need explicit `Open` for confirmed actionability; invalid close date → not actionable |
| `record-win` nudge presented as evidence | Removed from ranked.md; HELP/`record-win` output document global counter only |

## Residual limitations — stated, not hidden

1. **Transport / SSRF:** `transport_hardening: unresolved` — `_allowed_url` on card links only, not fetch redirects.
2. **Coverage:** Federal open-tender CSV primary; IDEaS HTML captures not repaired.
3. **HTML listing zero rows:** Still not proof of healthy empty market (`coverage_warning`).
4. **Ranking:** Still keyword/heuristic-driven; EV is not financial return.
5. **Display shortlist:** `MAX_OPPS_PER_FEED` caps ranked.md / ranked.json / console table after scoring; ledger records full candidate set from `run`.
6. **Row safety cap:** `CSV_MAX_ROWS` marks `partial`; RF at end of file is lost only if beyond that cap, not because of display shortlist.
7. **`record-win`:** Retained for compatibility; not a verified per-opportunity learning loop.

## Verifier commands (rig — profile scratch roots)

```bash
cd /Users/user/.hermes/profiles/rig/workspace/porcupine-trustworthy-radar

python3 -m pytest tests/ -q

python3 -m porcupine.cli replay-csv \
  --file source-evidence/canadabuys-reference.csv \
  --root /Users/user/.hermes/profiles/rig/cache/scratch/porcupine-trustworthy-radar-fixture

python3 -m porcupine.cli replay-csv \
  --file /Users/user/.hermes/profiles/rig/cache/scratch/porcupine-source-discovery/open-tenders.csv \
  --root /Users/user/.hermes/profiles/rig/cache/scratch/porcupine-trustworthy-radar-replay
# Expect raw/valid/unique derived from file (878 rows at current capture); shown≤40 when shortlist applies

python3 -m porcupine.cli run \
  --root /Users/user/.hermes/profiles/rig/cache/scratch/porcupine-trustworthy-radar-live \
  --source canadabuys-open-tenders-csv
```

## Narrow fixture repair (2026-10-04)

**Threat:** fixtures that prove fictions — tests green over false premises.

| Issue | Fix |
|--------|-----|
| Synthetic tests hand-built CSV with unquoted commas in descriptions (`$250,000`, `software, AI, drones`) | `_serialize_canadabuys_csv` / `csv.DictWriter` in `test_trustworthy_radar.py`; production `extra_columns` / overflow rules unchanged |
| `test_extra_csv_columns_rejected_not_valid_row` wrong premise | Official export has many **named** extra headers; only **unnamed** trailing fields (`DictReader` `None` key) reject. Split into `test_extra_named_csv_column_compatible_with_official_shape` + `test_extra_unnamed_csv_value_rejected_not_valid_row` |
| Unterminated quote + healthy `parse_outcome` | `csv.DictReader(..., strict=True)` so unterminated records raise `csv.Error`; one error → `partial`, `csv_parse_errors`, `source_incomplete`, stop read (no resync); prior valid rows kept |
| Keywordless intake test false premise | **Fixture-only:** custodial description without AI/drone/defence tokens; pre-check `match_keywords` / `match_capability` empty before intake assertion |
| Auto-draft tests empty-pass risk | Assert `valid_rows` and both construction + assurance ids before disposition/draft checks |

## Test status

Rig must run (builder shell could not execute pytest this session):

```bash
cd /Users/user/.hermes/profiles/rig/workspace/porcupine-trustworthy-radar
python3 -m pytest tests/test_trustworthy_radar.py tests/test_porcupine.py -q
```

Provenance seam adds tests: mocked live fetch → assembled/ledger; replay `fetched_at=unknown`; snapshot hash match via `read_bytes().decode`; deduped snapshot file; persistence failure warning; two-source body isolation; CRLF vs LF hash distinction; same-body/two-source distinct meta; tampered snapshot negative control.

## Hash-domain fix-back (2026-10-04)

| Threat | Fix |
|--------|-----|
| `read_text()` on snapshot broke CRLF bodies vs `body_text_sha256` | Tests verify `read_bytes().decode("utf-8")`; snapshots written as UTF-8 bytes without text-mode newline translation |
| Reused `.txt` without digest check | On reuse, stored UTF-8 decoded text must hash to `body_text_sha256`; mismatch → warning, no refs |
| Shared `<text_hash>.json` wrong attribution | Meta path = hash of canonical acquisition record; same content, different feeds → one body ref, two meta refs |

Prior independent receipt: 54 passed before provenance seam (rig).

## Acceptance evidence

| Criterion | Where verified |
|-----------|----------------|
| No 40-row acquisition censor | `test_shortlist_applied_after_rank_not_during_parse`, parse loop has no shortlist break |
| Full file row counts | `test_full_capture_replay_row_counts_when_present` (skips if capture absent) |
| RF cb-846-73690703 discoverable | Reference + ordering tests |
| Issued-by rejected | `test_issued_by_does_not_set_deadline` |
| Closed + future close not actionable | `test_closed_status_future_deadline_not_actionable` |
| Same-day TZ unknown | `test_same_day_close_timezone_unknown_unresolved` |
| Schema empty vs unsupported vs partial | empty_valid / unsupported / all_rows_rejected tests |
| Cache TTL refetch seam | Existing `test_cache_ttl_expiry_refetches` + charset fix |
| Truncation not cached | `test_truncation_flag_on_oversized_read` |
| Legacy 22 tests untouched | `tests/test_porcupine.py` not modified |
