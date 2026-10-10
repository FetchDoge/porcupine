# Buildability verdict — Trustworthy radar (bounded increment)

**Session:** 1a8ed029-9abe-46bf-9915-89e62f9e168a (continued; prior plan run delivered no contract artifact)
**Scope:** `TRUSTWORTHY-RADAR-SPEC.md`, `source-evidence/capture.json`, `source-evidence/canadabuys-reference.csv`, current `porcupine/*` and `tests/test_porcupine.py` only. Historical DESIGN/DEEP-DESIGN/learning proposals are out of scope.
**Baseline:** No CanadaBuys CSV ingestion exists; scout is HTML-only. Verified capture: 6 200 542 bytes, SHA-256 `7f01ca72…`, 878 data rows (`capture.json`). Fixture rows include RF Data Fusion (`cb-846-73690703`, close `2026-10-20T14:00:00`, empty `noticeURL-URLavis-eng`) and stale `Open` with close `2026-03-10T14:00:00` (`canadabuys-reference.csv`).

**Verdict:** The increment is **buildable** in this worktree without new dependencies. Work is a coordinated extension of `radar.py` / `config.py` / `cli.py` plus new `tests/test_trustworthy_radar.py`, while preserving the 22 existing tests in `tests/test_porcupine.py`. No architect gate blocks starting implementation; remaining risks are compatibility and truthful status reporting called out below.

Each finding is a failure the current code permits. Each amendment is the mechanism that closes it.

---

## 1. Missing primary source path (CSV)

**Threat:** runtime never fetches or parses the verified open-data CSV. `config.SOURCES` lists only HTML listing pages (`porcupine/config.py:163–188`). `scout()` always calls `parse_opportunities_html()` (`porcupine/radar.py:879–885`). The proven primary source exists; the code never looks at it.

**Mechanism:** add a dedicated source entry (URL from `capture.json` / spec) with a distinct `kind` (e.g. `canadabuys_csv`) and a pure function `parse_opportunities_canadabuys_csv(body, *, source, page_url, …) -> tuple[list[dict], intake_stats]`. Branch in `scout()` on `kind` or URL suffix before HTML parsing. Keep `parse_opportunities_html()` unchanged for legacy tests.

## 2. Fetch byte cap vs verified 6.2 MB CSV (compatibility hazard)

**Threat:** `fetch_url()` reads at most `config.CACHE_MAX_BYTES` (2 000 000) (`porcupine/config.py:24`, `porcupine/radar.py:719`). The verified CSV is 6 200 542 bytes (`capture.json:5`). A live GET would truncate mid-file; UTF-8 decode + CSV parse could yield partial rows or silent loss with no oversize status.

**Mechanism:** introduce a separate limit (spec suggests ≥16 MB) applied only on CSV sources (or per-source `max_bytes` in `SOURCES`). On truncation, set feed status to partial/error, record `bytes_read` vs `content_length` when available, and never mark the feed `ok` with "healthy zero."

## 3. Keyword pre-filter before intake (spec violation if reused for CSV)

**Threat:** `_normalize()` drops candidates with no lens keyword and no capability marker (`porcupine/radar.py:358–361`). The radar decides what exists before it finishes looking — keyword-less rows vanish without a trace.

**Mechanism:** CSV normalization must not call the keyword gate. Populate `raw_keywords_matched` / `capability_markers` for accounting but always emit a normalized dict when required columns validate (subject to malformed-row rejection). Use `scope.classify()` for disposition (`porcupine/scope.py:67–89`) so keyword-less rows become `out-of-lens` with explicit feed counters, not silent absence.

## 4. Feed health conflates "HTTP ok + parse ran" with "coverage ok"

**Threat:** after fetch, `scout()` sets `status = "ok"` even when `found` is empty (`porcupine/radar.py:886–891`). `summarize_scout_health()` treats any `status == "ok"` as success (`porcupine/radar.py:797–803`). HTML error bodies parsed as HTML yield zero opps with `ok` — indistinguishable from a genuinely empty market.

**Mechanism:** extend feed records with explicit fields: `parse_outcome` (`ok` | `schema_drift` | `empty_valid` | `partial` | `fetch_error`), `raw_rows`, `valid_rows`, `rejected_rows`, `lens_matches`, `body_sha256`, `fetched_at`, `coverage_scope` (federal CSV only). Map outcomes to status so health summary does not increment healthy on unsupported parse or unresolved primary CSV. Never imply full coverage while primary CSV is failed/truncated/stale.

## 5. Authoritative close timestamp and timezone

**Threat:** HTML path uses date-only deadlines; CSV provides `2026-10-20T14:00:00` without offset. A deadline without a timezone is a guess wearing a timestamp.

**Mechanism:** for CSV rows, set `deadline` from the date portion conservatively for existing interfaces; add `close_at` (raw string), `close_timezone` = `"unknown"` unless source adds offset. Do not parse "issued under … CFP" prose for deadlines. Document in traces, not invented UTC.

## 6. Source status "Open" vs past close (contradiction)

**Threat:** `openness()` ignores publisher status; it only compares parsed `deadline` to `today` (`porcupine/scoring.py:132–147`). A row marked Open with a close six months past could be confirmed actionable — and drafted.

**Mechanism:** carry `source_status` from CSV. If status implies open but `close_at` date is before `today`, set `open=False`, add `status_contradiction` (or trace), and exclude from `confirmed_open` / high-fit matched paths. Do not treat umbrella CFP closing dates in description text as child challenge deadlines.

## 7. Bare `by` deadline label bug (HTML path; spec regression)

**Threat:** `_DATE_LABEL` includes a bare `(?<![\w-])by(?!\w)` alternative (`porcupine/radar.py:70–77`). Text like "issued by 22 October 2027" mints a false deadline within the 48-character window. Existing test asserts positive `by` cases but not the issued-by bait.

**Mechanism:** remove or narrow bare `by` to require close/deadline/submission context (keep `no later than`, `received by`, `due by`, etc.). Add regression: `parse_deadline("Notice issued by 22 October 2027")[0] is None` while labelled closing strings still parse.

## 8. Missing detail URL (fixture contract)

**Threat:** the RF Data Fusion fixture has empty `noticeURL-URLavis-eng`. The temptation is to manufacture an official-looking detail URL — a small fabrication that poisons provenance.

**Mechanism:** set `url` empty or explicit unknown; set `source_dataset_url` / `page_url` to the CSV catalog or download URL from spec. Tests must assert empty notice URL without synthetic CanadaBuys detail links.

## 9. Quoted multiline CSV and description cleanup

**Threat:** reference fixture contains multiline quoted descriptions with HTML entities and embedded URLs. No parser exists; the HTML path's cleanup is not applicable to CSV cells — unhandled, they corrupt or silently drop rows.

**Mechanism:** `utf-8-sig`, `csv.DictReader`, validate exact header set from spec §Verified discovery. Light description cleanup (entity unescape, strip tags if present) without changing funding/deadline authority fields. Schema drift (missing required header) → `schema_drift` outcome, not `empty_valid`.

## 10. Parser replay API and test suite compatibility

**Threat:** without a replay entry point, verification depends on live network — unrepeatable, unauditable.

**Mechanism:** export CSV parser + optional `scout_source_body(body, source_meta)` for offline replay. CLI subcommand (e.g. `python3 -m porcupine.cli replay-csv --file … --root …`) writing isolated `cache/` / `output/` without hitting network. Do not patch legacy tests to accept broken behavior.

## 11. Operator-facing report / EV wording (incremental)

**Threat:** run summary presents EV as funding × fit × reachability without "heuristic priority / uncalibrated" labelling — the number quietly upgrades itself in the operator's mind.

**Mechanism:** add disclaimer lines to `ranked.md` / report output; optional metadata in `last-run.json`. No change to ranking formula this round.

## 12. SSRF / fetch hardening boundary (report-only if deferred)

**Threat:** `_allowed_url()` filters hrefs in parsed cards but `fetch_url()` has no redirect/private-IP guard. Claiming SSRF protection from scheme checks would be a lie.

**Mechanism:** if not implemented, set `transport_hardening: unresolved` in feed metadata and do not label security fixed. Stated, not hidden.

---

## Blockers (architect decisions required before safe implementation)

**None.** Spec resolves: CSV URL and headers, byte limit target, keyword accounting split, timezone unknown, contradiction handling, empty detail URL, and status vocabulary extensions. Builder chooses concrete constant names and cap values within spec bounds.

## Recommended implementation order

1. Config: CSV source entry, `CSV_MAX_BYTES`, required header tuple, optional per-source limits.
2. Pure CSV parser + intake stats; fixture tests from `canadabuys-reference.csv` (multiline, accents, RF Data Fusion row, empty URL).
3. `scout()` dispatch + truncated-response / schema-drift statuses; wire `body_sha256` / counts into `feeds.json`.
4. Provenance fields on opportunities (`close_at`, `source_status`, dataset URL); contradiction logic in scoring or assembly layer without breaking date-only HTML opps.
5. Fix `_DATE_LABEL` bare-`by` + regression in `test_porcupine.py` or trustworthy tests.
6. CLI replay entry + report disclaimers; `tests/test_trustworthy_radar.py` for acceptance matrix in spec §Tests.
7. Residual: HTML CanadaBuys feeds remain visibly partial; primary CSV is the proven path.

## Verifier commands (rig; not executed in this review)

```text
cd /Users/user/.hermes/profiles/rig/workspace/porcupine-trustworthy-radar
python3 -m unittest discover -s tests -p 'test_*.py' -v

# After implementation — offline full capture replay (spec path)
python3 -m porcupine.cli replay-csv \
  --file /Users/user/.hermes/profiles/rig/cache/scratch/porcupine-source-discovery/open-tenders.csv \
  --root /tmp/porcupine-replay-root

# Fixture subset (repo)
python3 -m porcupine.cli replay-csv \
  --file source-evidence/canadabuys-reference.csv \
  --root /tmp/porcupine-fixture-replay

# Live primary source (mandatory before cutover; isolated root)
python3 -m porcupine.cli run --root /tmp/porcupine-live-csv-run
```

Adjust CLI names to match implemented subcommand; contract is isolated `--root`, no unrelated feeds, and hash/count assertions against `capture.json`.

## Machine-readable verdict

```json
{
  "buildable": true,
  "blockers": [],
  "amendments": [
    "Add CanadaBuys CSV source + parse_opportunities_canadabuys_csv(); branch scout() off HTML-only path (config.py:163-188, radar.py:879-885).",
    "Separate CSV max bytes >= 16MB; detect truncation vs capture.json 6200542 (config.py:24, radar.py:719).",
    "CSV normalize without radar.py:360-361 keyword drop; feed-level raw/valid/rejected/lens counters.",
    "Extend feed status/metadata so ok/healthy != schema failure or truncated body (radar.py:886-803, cli.py:329-336).",
    "CSV close from tenderClosingDate column + close_timezone unknown; source_status contradiction with openness (scoring.py:132-147).",
    "Fix bare-by in _DATE_LABEL; add issued-by regression (radar.py:70-77, test_porcupine.py:265-274).",
    "Preserve empty noticeURL; attach dataset URL (spec + canadabuys-reference.csv).",
    "replay-csv CLI + tests/test_trustworthy_radar.py; keep 22 legacy tests green.",
    "Report disclaimers for partial coverage and heuristic EV (cli.py:312-314)."
  ],
  "implementation_order": [
    "config CSV source and byte limits",
    "pure CSV parser and fixture tests",
    "scout dispatch and feed health semantics",
    "provenance and contradiction fields",
    "deadline label fix",
    "replay CLI and trustworthy test module",
    "operator report copy"
  ],
  "verifier_commands": [
    "cd /Users/user/.hermes/profiles/rig/workspace/porcupine-trustworthy-radar && python3 -m unittest discover -s tests -p 'test_*.py' -v",
    "python3 -m porcupine.cli replay-csv --file /Users/user/.hermes/profiles/rig/cache/scratch/porcupine-source-discovery/open-tenders.csv --root /tmp/porcupine-replay-root",
    "python3 -m porcupine.cli replay-csv --file source-evidence/canadabuys-reference.csv --root /tmp/porcupine-fixture-replay",
    "python3 -m porcupine.cli run --root /tmp/porcupine-live-csv-run"
  ]
}
```
