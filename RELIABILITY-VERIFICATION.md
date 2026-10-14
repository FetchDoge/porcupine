# PORCUPINE ledger concurrency — reliability verification (issue #4)

Tree: `~/workspace/porcupine-fleet/reliability`. No production code changed; no commit.
Environment: Python 3.12.3, Linux 7.0.0-39-generic x86_64, 2 CPUs, local btrfs volume.

## 1. The threat: an asserted lock, never load-tested

**Threat:** `porcupine/ledger.py` claims concurrent-writer safety from one mechanism — an
exclusive `fcntl.flock` held across a batched scan+write. PERFORMANCE-VERIFICATION.md states
the open limit plainly: that safety "is asserted by the exclusive lock and exercised by
tests, but has not been load-tested under real multi-process contention." The pre-existing
process test used 4 processes × 1 row. If the claim were wrong, the failure modes are the
quiet kind: torn or interleaved lines corrupting the JSONL, lost appends when two writers
scan the same pre-write state, or duplicate lines when the shared (source, id) space is
written by every process at once. A reliability claim without a measurement is a rumor;
this note is the measurement.

## 2. Mechanism — the stress workload

**Harness:** N writer processes against one ledger file, released at the same instant by a
barrier so contention is maximal, not incidental. Each writer appends:

- a **disjoint set** (source `stress-w<index>`, unique ids) — tests lost appends;
- a **shared overlapping set** (source `stress-shared`, identical ids in every writer) —
  tests idempotency when all writers race the same keys.

Both write shapes are exercised: batched `append_many` and singleton `append` (one lock
acquisition and one full-file scan per row). Line sizes span ~107 B to ~66 KB — the large
phases cross the 8 KiB stdio buffer many times over, so a batch flushes in several chunks
while holding the lock.

**Verification is on the raw file bytes, independent of `Ledger.read()`:**

1. File ends with a newline; line count exact.
2. Every line parses as a JSON object (a torn or interleaved line fails here).
3. The (source, id) key set equals the expected set exactly — no duplicates, no losses.
4. Each writer's per-call results sum to the final line count for `written` and to
   writers × (disjoint + shared) overall: every line was claimed by exactly one writer.
5. All writer exit codes 0; no process stuck at join (no deadlock).

## 3. The record — measured, not asserted

| Phase | Writers | Shape | Workload per writer | Final lines | File size | Wall time | Verdict |
|---|---|---|---|---|---|---|---|
| p1 | 8 | batch 50 | 250 disjoint + 100 shared | 2,100 | 222,920 B | 0.31 s | PASS |
| p2 | 16 | batch 100 | 500 disjoint + 200 shared | 8,200 | 883,060 B | 5.70 s | PASS |
| p3 | 32 | batch 100 | 500 disjoint + 200 shared | 16,200 | 1,759,540 B | 22.69 s | PASS |
| p4 | 64 | batch 50 | 250 disjoint + 200 shared | 16,200 | 1,760,000 B | 62.59 s | PASS |
| p5 | 16 | singleton | 100 disjoint + 50 shared | 1,650 | 174,810 B | 27.91 s | PASS |
| p6 | 16 | batch 25, ~8.4 KB lines | 100 disjoint + 50 shared | 1,650 | 13,691,610 B | 7.14 s | PASS |
| p7 | 8 | batch 10, ~66 KB lines | 50 disjoint + 25 shared | 425 | 27,897,295 B | 5.36 s | PASS |
| p8 | 128 | batch 25 | 125 disjoint + 100 shared | 16,100 | 1,749,270 B | 107.62 s | PASS |
| p9 | 16 | batch 100, 50,000-line prefill | 500 disjoint + 200 shared | 58,200 | 6,160,840 B | 32.46 s | PASS |

Across all phases: **110,600 append results accounted for; 120,725 final lines verified
byte-by-byte; zero unparseable lines, zero duplicate keys, zero lost appends, zero writer
errors, zero stuck processes.** The correctness breaking point was not found — the ladder
was stopped at 128 writers / 58,200 lines because the failure being hunted (corruption)
had not appeared at any scale, while the cost curve (next section) was already decisive.

**Why it holds (mechanism, consistent with the record):** each `append_many` opens the
file in append mode (`O_APPEND`, so every write lands at end-of-file), takes `LOCK_EX` on
that open file description, scans, writes, and completes `flush()` *before* `LOCK_UN` is
released in the `finally`. Writers therefore never interleave bytes, and no writer scans
a state another writer is mid-way through changing.

## 4. The measured limit — throughput, not correctness

**Threat:** a lock that is correct but so expensive that writers time out upstream is
still a reliability failure, just a slower one.

**Record:** the lock is held across a full-file key scan, so writers serialize and every
batch costs O(file size). The same 16,200-line outcome took 22.69 s at 32 writers
(batch 100) and 62.59 s at 64 writers (batch 50 — more batches, more full scans).
Singleton appends are the worst shape: 1,650 rows in 27.91 s. Aggregate throughput at
128 writers was ≈150 lines/s on 2 CPUs. Total work grows quadratically with rows
appended, exactly the trade the performance increment accepted (44 s → 5.8 s) for the
single-writer case.

**Context:** production today is one process appending 1,756 rows in one batch per run —
far inside the envelope. Contention only becomes the binding constraint if parallel
collectors are introduced; if that day comes, the fix direction is a key index, not a
lock change. Recorded as an observation; nothing implemented.

## 5. Test status

`python3 -m pytest tests/ -q` → **101 passed** (baseline 98 + 3 new), exit 0.
New file `tests/test_ledger_concurrency.py` carries bounded versions of this workload
into the suite: 8-writer batched contention, 6-writer singleton contention, and
6-writer ~8.4 KB-line no-interleave, all with the raw-byte verification above; run
5× consecutively, 5× green. Existing test files unmodified. `porcupine/ledger.py`
unmodified: per the issue's condition, a fix requires a demonstrated defect, and none
was demonstrated.

## 6. Verdict and limits

**Record:** concurrent-writer safety of the ledger is now measured, not asserted, up to
**128 simultaneous writers, 58,200 lines, ~66 KB lines, and both write shapes**, on a
local filesystem. Verdict: the claim holds inside that envelope.

**Not claimed:**

- **Network filesystems** (NFS/SMB): `flock` semantics differ there; untested. Do not
  place a multi-writer ledger on a network mount on the strength of this note.
- **Crash durability:** a writer killed mid-flush (e.g. SIGKILL) can leave a torn final
  line; readers skip bad lines by design, but the kill-mid-write case was not exercised.
- **Concurrent readers:** `Ledger.read()` takes no lock; a read racing a flush can see
  a partial final line, which `read()` skips with a warning — by design, not tested here.
- **Power-loss durability:** `append_many` flushes to the OS but never `fsync`s.
- Anything beyond the tested envelope (>128 writers, >58,200 lines) is extrapolation,
  not measurement.
