# Worked example: one offline replay, read end to end

The main README explains what PORCUPINE does. This page **shows** it: one real
run, offline, against the bundled CanadaBuys reference capture — every output
below was produced by the commands on this page, not written by hand.

The threat this example teaches is **phantom coverage**: a radar that reports
"no matches" when it actually went blind three weeks ago. A failed feed and an
empty market look identical from the console. By the end of this page you will
know how PORCUPINE keeps them apart — and you will have seen a healthy run
that finds nothing, which is the outcome phantom coverage impersonates.

**The five-minute path**

1. Run the replay (Step 1) — 30 seconds.
2. Read `feeds.json` (Step 2) — proof the radar was awake, and the five feed states.
3. Read one scoring trace in `ranked.json` (Step 3) — why the top row scored what it scored.
4. Sit with the no-verified-match outcome (Step 4) — zero matches, finished run.
5. Touch the record (Step 5) — snapshot, hash-chained journal, and an honest note about the ledger.

Or skip the reading and run everything at once: `python3 examples/run_walkthrough.py`
(Step 6). It performs the same replay into a fresh temp root and prints the
artifacts with annotations.

## Before you start

Run every command from the repository root — `porcupine` is imported from the
working directory, not installed. Pick a scratch root; everything PORCUPINE
writes stays under it:

```bash
cd <your checkout of this repo>
ROOT=/tmp/porcupine-demo
rm -rf "$ROOT"
```

The reference capture (`source-evidence/canadabuys-reference.csv`) is a 5-row
verified excerpt of the CanadaBuys open-tender CSV, small enough to read in
full. It is not the production feed.

## Step 1 — Run the replay

```bash
python3 -m porcupine.cli replay-csv --file source-evidence/canadabuys-reference.csv --root "$ROOT"
```

Real output:

```text
replay-csv canadabuys-reference.csv: raw=5 valid=5 unique=5 shown=5
 rk            ev    fit  reach   p_lcb  open        disp       class                   source                  title
  1         -6250   0.10   0.75   0.000  yes         near-miss  adjacent                canadabuys-open-tenders-csv  RF Data Fusion for Command and Control
  2        -23750   0.10   0.05   0.000  no          near-miss  adjacent                canadabuys-open-tenders-csv  Secure Path to the Stars: Strengthening Cybersecurity in Hybrid
  3        -25000   0.00   0.75   0.000  yes         rejected   out-of-lens             canadabuys-open-tenders-csv  Open Construction Source List for CFB Halifax
  4        -25000   0.00   0.75   0.000  yes         rejected   out-of-lens             canadabuys-open-tenders-csv  Open Construction Source List for 9 Wing Gander
  5        -25000   0.00   0.75   0.000  yes         rejected   out-of-lens             canadabuys-open-tenders-csv  Innovation for Defence Excellence and Security (IDEaS) Program –
wrote /tmp/porcupine-demo/output/feeds.json and /tmp/porcupine-demo/output/ranked.json
```

How to read this:

- `raw=5 valid=5 unique=5 shown=5` — five CSV records in, five parsed, none
  duplicated, all five displayed. This is the intake accounting; Step 2 shows
  where it is recorded.
- Every EV is **negative**. That is normal here: EV is
  `funding × portfolio_fit × reachability − effort`, effort for a tender is a
  flat 25000, and nothing in this capture fits the portfolio well. A negative
  score is a ranking signal, not an error.
- `open` is `yes` / `no` / `unverified` — never guessed. Row 2 says `no` even
  though the publisher says "Open"; Step 3 shows why.
- `disp` is the disposition: `matched`, `near-miss`, or `rejected`. There is
  no `matched` row. Hold that thought until Step 4.
- Titles are cut at 64 characters in this table, with no ellipsis marker —
  rows 2 and 5 are truncated mid-word. The full titles live in `ranked.json`.

The console is a summary, and summaries can hide blindness. The proof is in
the files.

## Step 2 — `feeds.json`: proof the radar was awake

`$ROOT/output/feeds.json` holds one record per feed. This run's record
(excerpted; `…` marks omitted lines, everything shown is verbatim):

```json
    "id": "canadabuys-open-tenders-csv",
    "status": "ok",
    "how": "replay",
    …
    "parse_outcome": "ok",
    "raw_rows": 5,
    "valid_rows": 5,
    "lens_matches": 2,
    …
    "body_text_sha256": "c6ea60f71800866c30c975f1555b039f4baf6d951ebf6a63c2bbc4fcffed42ee",
    "coverage_scope": "federal_open_tenders_csv_only",
    "coverage_warning": "Primary CSV covers federal open tender notices only; not all Canadian procurement or the full IDEaS HTML market.",
    "transport_hardening": "unresolved",
    …
    "offline_replay": true,
    "source_snapshot_ref": "source-snapshots/c6ea60f71800866c30c975f1555b039f4baf6d951ebf6a63c2bbc4fcffed42ee.txt",
    …
    "candidate_rows": 5,
    "matched_rows": 0
```

What each part proves:

- `status: "ok"` + `parse_outcome: "ok"` + `raw_rows: 5` — the feed was
  fetched (here: replayed), its schema matched, and rows actually flowed.
  "No matches" downstream of this record means the market had no match, not
  that the pipe was broken.
- `body_text_sha256` — the hash of the exact bytes parsed. Recompute it
  yourself: `python3 -c "import hashlib; print(hashlib.sha256(open('source-evidence/canadabuys-reference.csv', encoding='utf-8-sig').read().encode()).hexdigest())"`.
  The snapshot of those bytes is kept under `source-snapshots/`, named by the
  same hash — any run can be replayed against the identical input.
- `coverage_warning` and `transport_hardening: "unresolved"` — the limits of
  the run, recorded in the run. The radar states what it did not cover and
  what is not fixed, in the artifact, not in a footnote somewhere else.
- `matched_rows: 0` — of five candidates, zero verified matches. Step 4 is
  about why this is a result and not a failure.

### The five feed states

A feed that produces zero opportunities is not one thing; it is five. Each
state is a different `status` / `parse_outcome` pair in `feeds.json`, and each
proves something different:

| State | `status` / `parse_outcome` | What it proves | See it here |
|---|---|---|---|
| Healthy | `ok` / `ok` | Rows parsed; a zero downstream is a market fact | Step 1 |
| Healthy-empty | `ok` / `empty_valid` | Feed worked; it genuinely contained no rows | Gallery A |
| Schema drift | `schema_drift` / `schema_drift` | The publisher changed the format; the radar is blind on this feed, and says so | Gallery B |
| Truncation | `partial` / `partial` | The input ended early (`parse_error` names how); kept rows are suspect, not silently trusted | Gallery C |
| Fetch failure | feed recorded as not-`ok` with `error` set (live `run`); offline, a missing file stops the replay before any record exists | The radar never saw the feed at all — recorded as a skip, never as a zero | Gallery D |

A sixth state, **stale cache**, exists in live runs only: a cached body older
than the TTL is treated as a miss, not served as if fresh. The offline replay
has no cache, so it cannot occur here.

The crucial detail: **the console cannot tell these apart.** Every gallery run
below prints the same `(no opportunities)` table as a healthy-empty run. Only
`feeds.json` carries the difference. That is the whole design in one sentence:
the artifact knows what the summary cannot say.

**Gallery A — healthy-empty.** Headers, no rows:

```bash
head -1 source-evidence/canadabuys-reference.csv > /tmp/headers-only.csv
python3 -m porcupine.cli replay-csv --file /tmp/headers-only.csv --root /tmp/porcupine-empty
```

Console: `replay-csv headers-only.csv: raw=0 valid=0 unique=0 shown=0`, then
`(no opportunities)`. In `/tmp/porcupine-empty/output/feeds.json`:
`"status": "ok"`, `"parse_outcome": "empty_valid"`. A working feed with
nothing in it — the only zero that means "quiet market."

**Gallery B — schema drift.** Delete the `tenderClosingDate-appelOffresDateCloture`
column from a copy of the capture (this is the one gallery input that needs a
CSV-aware edit; `examples/run_walkthrough.py` generates it for you) and replay
it. The console is again `(no opportunities)` — but `feeds.json` says
`"status": "schema_drift"` and names the missing column:
`"missing_headers": ["tenderClosingDate-appelOffresDateCloture"]`. Without a
closing-date column the radar cannot judge openness, so it records blindness
instead of guessing. Note it also stores **no snapshot**: an unparsed body is
not kept as evidence.

**Gallery C — truncation.** Cut the file off mid-record:

```bash
head -c 3000 source-evidence/canadabuys-reference.csv > /tmp/truncated.csv
python3 -m porcupine.cli replay-csv --file /tmp/truncated.csv --root /tmp/porcupine-trunc
```

`feeds.json`: `"status": "partial"`, `"parse_error": "unexpected end of data"`,
`"csv_parse_errors": 1`, `"rejected_rows": 1`. The damaged row is counted and
the reason kept — not dropped silently, not half-parsed into a phantom row.

**Gallery D — the input is not there.**

```bash
python3 -m porcupine.cli replay-csv --file /tmp/nope.csv --root /tmp/porcupine-missing
echo $?
```

Exit code `2`, and on stderr: `CSV not found: /tmp/nope.csv`. No `feeds.json`
is written at all — a missing input produces no record that could later be
mistaken for an empty feed. In a live `run`, the same situation is recorded
per-feed as a skip with the error attached; either way, absence is never
dressed up as a zero.

## Step 3 — `ranked.json`: one score, read line by line

`$ROOT/output/ranked.json` holds one object per candidate, EV-ranked. Each
object is 54 fields; the ones that carry the argument are these (verbatim,
from row 1):

```json
    "id": "cb-846-73690703",
    "disposition": "near-miss",
    "classification": "adjacent",
    "classification_reason": "lens context only: command & control, C2",
    "title": "RF Data Fusion for Command and Control",
    …
    "funding": 250000.0,
    "funding_trace": "funding_field=$250,000 (component 1a)",
    "deadline": "2026-10-20",
    "close_timezone": "unknown",
    "source_status": "Open",
    "open": true,
    …
    "ev": -6250.0,
    "ev_label": "heuristic_priority_uncalibrated",
    "p_win_lcb": 0.0,
    "formula": "ev = 250000 * 0.1000 * 0.75 - 25000 = -6250.00 ; funding uses 0 when the page stated no dollar amount",
    "traces": {
      "funding": "funding_field=$250,000 (component 1a)",
      "effort": "config.EFFORT_CAD.tender",
      "assurance_hits": "(none)",
      "assurance_density": "0 / config.ASSURANCE_DENSITY_SATURATION(4)",
      "moat_strength": "0.00 max repo (none)",
      "portfolio_fit": "0.65*density + 0.35*moat_strength + TRL_FIT_BUMP.1a(0.1)",
      "reachability": "reachability=config.REACHABILITY.deadline_future (deadline 2026-10-20); trl_component=1a TRL_FIT_BUMP=0.1 trl=1-3",
      "p_win_lcb": "wilson_lower_bound(successes=0.0, n=0) = 0 because n=0",
      "deadline": "deadline_field=2026-10-20T14:00:00 (csv column tenderClosingDate)"
    },
```

Read it as an argument, not a number:

- **`classification_reason`** says why the lens kept this row: it matched
  command-and-control context keywords, nothing more. `classification` is
  `adjacent` — in the neighbourhood of the portfolio, not in its
  assurance-core white space.
- **`funding_trace`** shows the $250,000 was *parsed from the notice text*
  (Component 1a's stated maximum), not estimated. A row whose text states no
  amount gets `funding: 0` — absence contributes zero, never an average.
- **`traces`** is the scoring, line by line. `assurance_hits: (none)` and
  `moat_strength: 0.00` are why `portfolio_fit` is 0.10 despite the C2
  keywords: fit is mostly assurance density and portfolio moat, and this
  notice has neither. Every component names the config constant or rule that
  produced it, so the score can be re-derived by hand.
- **`formula`** restates the arithmetic with the actual operands. Check it:
  250000 × 0.10 × 0.75 − 25000 = −6250. ✓
- **`ev_label: heuristic_priority_uncalibrated`** travels with the score,
  always. And **`p_win_lcb: 0.0`** — the Wilson lower bound on recorded wins
  — stays at zero because `n=0`: no outcomes have been recorded, so the
  win-probability bound is honestly zero rather than a plausible-looking
  guess. Until real outcomes exist, no score in this file is a probability.
- **`close_timezone: "unknown"`** is printed, not papered over. The close
  time is 14:00 in *some* timezone; the record says it doesn't know which.
  (A same-day close with an unknown timezone would be recorded
  `open: unverified` rather than confirmed open.)

### The contradiction, caught in row 2

Row 2's publisher metadata lies, and the record shows the catch (verbatim):

```json
    "source_status": "Open",
    "status_contradiction": "publisher_open_but_close_date_past",
    "deadline": "2026-03-10",
    "open": false,
```

The publisher says `Open`; the close date is in the past. PORCUPINE
cross-checks status against the parsed deadline and records the contradiction
instead of believing either field alone — that is why the console showed
`open: no` and `reach: 0.05` for this row. A radar that trusted the status
column would have presented a dead challenge as live.

*Caveat on dates:* `open` is computed against the day you run the replay.
These excerpts were captured on 2026-10-14; row 1's deadline is 2026-10-20,
so after that date row 1 flips to closed and its EV drops. The artifacts you
produce are the record of *your* run date.

## Step 4 — No verified match: a finished run, not a failed one

Now back to the held thought. This run's record is complete:

- Feed healthy: `status: "ok"`, 5 of 5 rows valid (Step 2).
- Every candidate scored, traced, and dispositioned (Step 3).
- `matched_rows: 0`. No row was both assurance white-space, at or above the
  matched fit bar, and confirmed open — so **no draft was written**, and the
  command still exited `0`.

That is the NO-VERIFIED-MATCH outcome, and it is the point of the tool. The
alternative — a radar that always produces a draft — would have generated an
assurance proposal for a command-and-control notice with zero assurance
content, because keywords scored. PORCUPINE refuses: drafting requires a
verified match, and "the processed sources contained none" is a complete,
honest answer. In a live `run`, this same outcome is materialized as an
artifact — `output/NO-VERIFIED-MATCH-DRAFT.md` — so the absence of a draft is
itself on the record, not a missing file someone has to explain later. (The
offline replay does not draft at all; see Step 5.)

Distinguish the three zeros you have now seen:

- **Healthy zero** (this step): the radar saw the market; there was no match.
- **Blind zero** (Gallery B/C): the radar could not see; `feeds.json` says so.
- **Empty zero** (Gallery A): the feed worked and contained nothing.

Only the first is a finished market result. The record lets you tell which
one you are holding.

## Step 5 — The record: snapshot, journal, ledger

Everything the run wrote, after Steps 1–5 of this page:

```text
/tmp/porcupine-demo/ledger/journal.jsonl
/tmp/porcupine-demo/output/feeds.json
/tmp/porcupine-demo/output/last-run.json
/tmp/porcupine-demo/output/ranked.json
/tmp/porcupine-demo/source-snapshots/0ec9101ab20913180b4600762e0afaa3eeefd435ad142c5442c1e43d4ddb198c.json
/tmp/porcupine-demo/source-snapshots/c6ea60f71800866c30c975f1555b039f4baf6d951ebf6a63c2bbc4fcffed42ee.txt
```

- **`source-snapshots/`** — the exact replayed bytes (`.txt`, named by the
  sha256 you verified in Step 2) plus a metadata record (`.json`). Provenance
  is content-addressed: re-running the replay reuses the same names.
- **`output/last-run.json`** — the run summary: mode, replay file, candidate
  and displayed counts, and the full feed record again.

**The journal.** The decision journal is where a human's verdict on a row is
recorded — append-only and hash-chained. Record this walkthrough's verdict on
the top row (note: `--verdict` accepts only `pursue`, `skip`, or `defend`):

```bash
python3 -m porcupine.cli journal log-decision --root "$ROOT" \
  --id cb-846-73690703 --verdict skip \
  --rationale "Replay shows adjacent, not assurance white-space; fit 0.10 is below the matched bar. No draft." \
  --evidence-ref output/ranked.json
python3 -m porcupine.cli journal verify --root "$ROOT"
```

Real output:

```text
journal appended seq=1 type=decision
journal verified: /tmp/porcupine-demo/ledger/journal.jsonl
```

And the line itself (timestamps — and therefore the hash, which chains over
them — differ on your run):

```json
{"evidence_refs": ["output/ranked.json"], "hash": "3c95d8ab116f7d8ee955f3da9f698bab5d1ba62b58d5240d885e5202f5a9f45b", "opportunity_id": "cb-846-73690703", "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000", "rationale": "Replay shows adjacent, not assurance white-space; fit 0.10 is below the matched bar. No draft.", "seq": 1, "ts": "2026-10-14T01:49:01+00:00", "type": "decision", "verdict": "skip"}
```

Each entry carries the previous entry's hash (`prev_hash`; all zeros for the
genesis entry), so editing history breaks the chain and `journal verify`
fails. History is written once and verified, not edited.

**The ledger — an honest gap.** Note what is *not* in the listing: there is
no `ledger/porcupine.jsonl`. The offline replay deliberately writes no
opportunity-ledger rows; appending to the append-only ledger is a behavior of
the live `run` command, which appends the same row objects you read in
`ranked.json` (plus a companion `unused_material` record, with its reason,
for every near-miss and rejected row). If you expected a ledger from the
replay and found none, that is the current design boundary, stated here
rather than discovered later.

## Step 6 — All of it, one command

```bash
python3 examples/run_walkthrough.py
```

The script performs the replay, the hash check, the trace reading, the
contradiction catch, all three gallery states, and the journal write + verify
into a fresh temporary root, printing the CLI's real output with annotations
as it goes. If any claim on this page stops being true, the script's output
will be the first thing to disagree with it.

## Not claimed

- This capture is 5 rows chosen to exercise the parser. It proves nothing
  about market coverage; `feeds.json` itself says the feed covers federal
  open tenders only.
- Every score shown is `heuristic_priority_uncalibrated`. Nothing here ranks
  your chances of winning anything.
- The replay is not the live radar: no network was touched, no cache was
  read, no ledger was written, no draft was produced, and nothing was
  submitted to anyone. PORCUPINE drafts and records — it does not submit,
  apply, or click. Ever.
