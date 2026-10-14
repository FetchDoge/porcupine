# PORCUPINE

[![CI](https://github.com/marsojuji-cmyk/porcupine/actions/workflows/ci.yml/badge.svg)](https://github.com/marsojuji-cmyk/porcupine/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-98%20passed-green.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Defence contracts go to whoever was watching. Most teams aren't — and the ones running a radar can't tell when it goes blind.**

PORCUPINE is a read-only radar for Canada's defence and dual-use tender market. It watches the open feeds, preserves acquisition provenance, ranks what it finds against your portfolio — and refuses to pretend it saw what it didn't.

## The threat

Five ways opportunity capture fails. Each one has been observed in the wild, and each one has a dedicated countermeasure below — not a policy, a mechanism.

**1. Missed pursuits.** Notices publish daily; nobody watches systematically. The contract goes to whoever happened to look that week.

**2. Phantom coverage.** The radar reports "no matches" — but its parser broke three weeks ago and nobody noticed. A failed feed looks exactly like an empty market, and "all clear" becomes the most dangerous sentence in the building.

**3. Overconfident rankings.** A heuristic score gets read as a win probability. Real pursuit effort — weeks of capture work — gets bet on noise wearing a number.

**4. Contradiction blindness.** A notice marked "Open" with a deadline six months in the past. An umbrella program date mistaken for a challenge deadline. The metadata lies; nobody checks.

**5. The auto-submit disaster.** A tool that drafts *and* submits, with no human gate between "interesting" and "legally committed."

## The mechanism

| Failure | Countermeasure — what PORCUPINE does instead |
|---|---|
| Missed pursuits | Weekly radar runs against the official CanadaBuys open-tender CSV (878-row verified capture) plus configured public HTML sources, with polite timeouts, delays, and local cache |
| Phantom coverage | Feed-health accounting: fetch failure, schema drift, truncation, stale cache, and healthy-empty are **five distinct states**. A failed feed is recorded and skipped — never displayed as a healthy zero |
| Overconfident rankings | Every score is labeled `heuristic_priority_uncalibrated`, always. The win-probability lower bound is **zero** until real outcomes are recorded. Funding counts only when parsed from the notice text; absent amounts contribute zero, not an average |
| Contradiction blindness | Publisher status is cross-checked against the parsed deadline. "Open" with a past close surfaces as a **contradiction**, never as confirmed-open. Umbrella dates are never mistaken for child deadlines |
| Auto-submit | Drafts require `disposition=matched` **and** confirmed-open. PORCUPINE drafts and records — it does not submit, apply, or click. Ever |

Underneath it all:

- **Provenance or it didn't happen.** Every record carries source hashes, acquisition timestamps, and content-addressed snapshots. Any acquisition can be replayed exactly.
- **Append-only journals.** Opportunity ledger and decision journal; the journal is hash-chained and tamper-evident. History is written once and verified, not edited.
- **Fail-soft.** A dead source degrades the run; it never poisons the record.
- **No silent learning.** Thresholds are never tuned on the samples they're scored on. Adaptation is propose-only — a human disposes. (The full adversarial story is in `DESIGN-v2.md`: an independent red-team found 6 objections; 3 verified true and were fixed before a line of v2 code was written.)

## The record

- **98 hermetic tests**, stdlib only, Python 3.9+. CI runs on every push.
- **Independent verification**: 62/62 observed passing in an isolated worktree; the original 22 regression tests byte-identical.
- **Performance, proved not asserted**: profiling found the ledger doing 3,083,539 JSON parses per run (quadratic). One locked batch write later: **~8× faster** (44s → 5.8s), with golden-output equivalence demonstrated by side-by-side execution — all 1,756 ledger rows identical modulo timestamps.
- **Adversarial design**: the v2 blueprint survived a red-team with 6 objections at 0.86 confidence; the 3 that verified true became structural fixes (split drift organ, calibrated loop, structural gate).

## Not claimed

- Scores are heuristics, not calibrated win probabilities or proof of fit.
- Coverage is the federal open-tender CSV plus configured public sources — not all Canadian procurement, not the full IDEaS market.
- Transport hardening (SSRF) is **explicitly unresolved** — stated, not hidden.
- A run may legitimately find nothing actionable. "No matches among processed sources" is not "no market opportunities."
- Drafts require human verification and an explicit pursue decision. Missing deadlines, funding, URLs, and timezones remain unknown — they are not inferred.

## Run

Python 3.9 or newer. No third-party runtime dependencies; pytest only for the test suite.

```bash
python3 -m pytest tests/ -q
python3 -m porcupine.cli run
python3 -m porcupine.cli top 10
python3 -m porcupine.cli draft <id>
python3 -m porcupine.cli report
python3 -m porcupine.cli journal --help
```

The live run uses configured timeouts, a delay between network fetches, and a local cache. A failed feed is recorded and skipped rather than represented as successful coverage.

New here? [examples/](examples/README.md) walks one offline replay end to end — the five feed states, a scoring trace read line by line, and a run that finds nothing — in about five minutes.

## Outputs

- `output/ranked.md` and `output/ranked.json`: ranked, traced records.
- `output/feeds.json`: per-source acquisition and parse status.
- `output/drafts/`: drafts allowed by the CLI's gating rules.
- `output/NO-OPEN-DRAFT.md`: explicit no-open-result artifact.
- `ledger/porcupine.jsonl`: append-only opportunity ledger.
- `ledger/journal.jsonl`: append-only decision journal.

## Score

`EV = funding × portfolio_fit × reachability − effort`

Heuristic priority only — uncalibrated, not expected financial return or actual win likelihood. Funding is used only when parsed from the opportunity text; an absent amount contributes zero.

## Evaluation

`eval/RUBRIC.md` defines the human-labeling rules — every label needs an exact evidence quote, disagreements resolve to the conservative label and are never erased. Generate a component-level sheet and score completed labels with:

```bash
python3 eval/sample.py --csv source-evidence/canadabuys-reference.csv --n 120 --seed 7 --out eval/to_label.csv
python3 eval/score.py --labels eval/labels.csv --report eval/report.md
```

## The Keeper

PORCUPINE is operated under a standing protocol by its Keeper — maintainer and witness, not promoter. Public-read, draft-never-submit. The uncalibrated stays uncalibrated until outcomes say otherwise. Precision@10 below 0.5 on the eval set falsifies the targeting approach: redesign the lens, don't tune the thresholds.

---

*Built to watch the market without lying about what it saw.*
