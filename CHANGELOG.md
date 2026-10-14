# Changelog

All notable changes to PORCUPINE. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

Fleet pass, 2026-10-13 — five role-mirrored engineering lanes, integrated and verified by the Keeper. Tests: 98 → 170.

### Security
- Transport hardening verified end-to-end and closed on the fetch path: the sole fetch entry routes the initial URL and every redirect hop through netguard validation. Two gaps found and closed — environment proxies neutralized (a proxy would otherwise resolve/connect instead of the validated addresses) and HTTPS→HTTP downgrade redirects refused. Residual, stated not hidden: DNS TOCTOU between validation and connect.
- Feed metadata `transport_hardening` split by provenance: `guarded` for bodies fetched in-process through the guarded opener; `unresolved` kept for cache hits, replays, and supplied bodies.

### Feeds
- IDEaS HTML coverage partially repaired: footer `<article>` blocks no longer short-circuit listing parsing (the live CanadaBuys page parsed to zero; it now yields real opportunities, proven on a byte-pinned capture). Program pages without `<article>` parse via a chrome-excluded section reader. canada.ca remains fetch-blocked from the capture network and the configured awards URL is a verified 404 — both stay visibly partial.

### Evaluation harness
- Scorer math hand-verified. Missing label columns and duplicate labeled rows now fail loudly instead of silently skewing precision; the sampler records per-stratum availability; reports carry rows-accounting and warn when unlabeled rows hold top-10 ranks (Precision@10 then covers labeled rows only).
- First classifier measurement landed 2026-10-14 (issue #3): two independent blind machine labelers (Marcus Richards' direction), 718/720 agreement, report bannered machine-labeled (`eval/LABELS-PROVENANCE.md`). Zero confirmed fits in the sample; the classifier's 14 positive predictions were all judged no-fit.
- EP-AEC pattern scoped (issue #8): signals must now name the deliverable or method (conformance/certification/accreditation/attestation *services*, third-party certification, adversarial *testing*) — bare topic nouns no longer mint fits. Recomputed over the labeled sample: false positives 14 → 0, no other prediction moved; fit steps unchanged. Record: `EVAL-ADDENDUM.md`. Recall remains unmeasured (the sample holds no positives).

### Reliability
- Ledger concurrent-writer safety measured, not asserted: 128 writers, 120,725 lines verified byte-by-byte — zero torn lines, zero duplicate keys, zero lost appends. No defect found; the measured limit is throughput under contention, far outside production shape. Record: `RELIABILITY-VERIFICATION.md`.

### Usability
- `examples/` walkthrough: one offline replay end to end — the five feed states, a scoring trace read line by line, and a run that finds nothing (NO-VERIFIED-MATCH), every excerpt verified against real output.
- CLI fix (issue #7): `top` / `report` / `record-win` / `draft` honor `--root`; a valueless or unknown flag is a loud error, never a silent drop. `report` states explicitly when the last run did not record a high-fit count instead of printing a bare `None`.

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
