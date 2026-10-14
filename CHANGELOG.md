# Changelog

All notable changes to PORCUPINE. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-10-10

First public release.

### The radar
- CanadaBuys open-tender CSV intake (878-row verified capture) with schema, row-size, and malformed-row checks; broad intake independent of the keyword lens — relevance is applied downstream, never at the door.
- Configured public HTML sources with polite timeouts, delays, and local cache.
- Feed-health accounting: fetch failure, schema drift, truncation, stale cache, and healthy-empty are five distinct states. A failed feed is recorded and skipped, never displayed as a healthy zero.
- Provenance on every record: source hashes, acquisition timestamps, content-addressed snapshots; any acquisition replayable exactly (`replay-csv`).

### Scoring and drafting
- Heuristic ranking `EV = funding × portfolio_fit × reachability − effort`, labeled `heuristic_priority_uncalibrated` everywhere it appears. Funding counts only when parsed from the notice text.
- Publisher status cross-checked against parsed deadlines; contradictions surface as contradictions, never as confirmed-open.
- Draft gate: `disposition=matched` **and** confirmed-open. PORCUPINE drafts and records; it does not submit, apply, or click.

### Records
- Append-only opportunity ledger (idempotent on source + id).
- Hash-chained, tamper-evident decision journal (`journal log-decision` / `log-outcome` / `verify`).

### Engineering record
- 98 hermetic tests, stdlib only, Python 3.9+.
- Independent verification: 62/62 observed passing; legacy regression tests byte-identical.
- Performance: quadratic ledger write found by profiling (3,083,539 JSON parses per run) and fixed to a single locked batch write — ~8× faster (44s → 5.8s), output equivalence proved by side-by-side golden-output comparison.
- Adversarial design review: 6 objections, 3 verified true, fixed before v2 code (see `DESIGN-v2.md`).

### Known limits (stated, not hidden)
- Transport hardening (SSRF) explicitly unresolved.
- Classifier precision unmeasured — human labels required (eval harness in `eval/`).
- Coverage is the federal open-tender CSV plus configured public sources, not the full Canadian procurement market.
