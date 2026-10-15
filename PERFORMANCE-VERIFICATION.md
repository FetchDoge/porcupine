# PORCUPINE performance increment — independent verification

Worktree: `<worktree>` (the trustworthy-radar feature branch).
Live checkout `<live-checkout>` untouched, clean, at `b7ff5a2`. No deploy, no cron change, no commit.

## 1. The threat: silent quadratic

**Threat:** the ledger worked — and got slower every week, with no alarm. Silent performance rot is how tools die: not with an error, but with a run nobody bothers to wait for.

**Mechanism — baseline measurement before any change.** Profiled and wall-clock measured the existing cached-feed workload:

| Sample | Seconds |
|---|---|
| Unprofiled run 1 | 43.70 |
| Unprofiled run 2 | 44.97 |

`cProfile` over the same workload: **49.59 s total**, of which `cli._record` = **44.16 s (89%)**.
Cause: `Ledger.append` called `Ledger.seen()` per record, and `seen()` re-read and re-parsed the
whole ledger file — 1,756 appends × full-file parse = **3,083,539 JSON parses**. Quadratic work.

## 2. The fix

**Mechanism:** `Ledger.append_many` added; `Ledger.append` delegates to it, so there is one write path.
A single locked full-file key scan per batch (exclusive `fcntl.flock` held across scan+write),
in-batch key tracking, serialization validated before any write, one flush per batch.
No production change outside `ledger.py` / `cli.py`.

## 3. The record — measured, not asserted

Same workload, same corpus, three samples: **6.04 / 5.58 / 5.80 s → median 5.8 s**.
Earlier three-sample set after the build: 5.41 / 5.47 / 5.49 s → median 5.47 s.
**≈7.6–8.1× faster.** Baseline median 44.3 s.

## 4. Behavior preservation — golden-output comparison

**Threat:** a "faster" rewrite that quietly changes what the system says.

**Mechanism — the strongest available check:** restored the pre-build `ledger.py` + `cli.py` from
`.../porcupine-prebuild-backup/` (sha verified against PREBUILD.sha256) into a copy of the
package, then ran **baseline code** and **optimized code** against the identical captured
feed into two separate roots (`porcupine-perf-snapshot/out-old`, `out-new`).

**Record:** every difference found was volatile only —
`fetched_at`, `recorded_at`, `source_snapshot_meta_ref` (a hash computed *over* acquisition
fields including fetch time, so it moves legitimately), and the `ranked.md` header timestamp.
All other fields, across **all 1,756 ledger rows** (878 `opportunity` + 878 `unused_material`)
and **all 40 ranked rows**, are identical.

| Artifact | Baseline vs optimized |
|---|---|
| `output/last-run.json` | identical (modulo timestamps) |
| `output/feeds.json` | identical (modulo timestamps) |
| `output/NO-VERIFIED-MATCH-DRAFT.md` | identical |
| `output/ranked.json` (40 rows) | identical (modulo timestamps) |
| `ledger/porcupine.jsonl` (1,756 rows) | identical (modulo timestamps) |

Run counters unchanged: 878 candidates, 40 displayed, 0 matched, `draft: null`,
ledger `appended: 0 / already_recorded: 1756`, source snapshot digest preserved.

## 5. Test status
`python3 -m pytest tests/ -q` → **79 passed, exit 0**.
`tests/test_porcupine.py` — **byte-identical to pre-build baseline** (sha `4f0913a4…`).

**Threat:** fixtures that lie — tests green over false premises. Two fixture defects were found by the new tests during this increment and repaired in the
test file only, never by weakening production:

- A hand-built row dict missing the `open` key made `unused_note` raise `KeyError`.
  `unused_note` was verified **unchanged from baseline** against the pre-build backup —
  the fault was the fixture, so production was left alone.
- The drift control then caught the replacement fixture missing `recorded_at` and `title`.
  Final design: the representative row is **constructed by calling production
  `assemble()`** (`_single_production_assembled_row`, `_assemble_record_path_rows`) rather
  than hand-written, so the fixture cannot drift from production by construction. The
  committed `assemble()` key fingerprint remains as the shape-change tripwire.

## 6. Verdict and limits

**Record:** the performance objective is met and independently measured, with output equivalence
demonstrated by side-by-side execution rather than by the builder's report.

**Not claimed:** any change to matching, ranking, coverage, provenance semantics, or drafting policy — none were in scope and none changed. Transport hardening remains explicitly unresolved. Concurrent-writer safety is asserted by the exclusive lock and exercised by tests, but has not been load-tested under real multi-process contention.
Deployment, merge, cron cutover and submissions have NOT occurred.
