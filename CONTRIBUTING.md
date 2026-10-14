# Contributing to PORCUPINE

PORCUPINE is a read-only radar for Canada's defence and dual-use tender market. Contributions are welcome — especially the ones listed as [good first issues](https://github.com/marsojuji-cmyk/porcupine/labels/good%20first%20issue).

## The one rule that outranks the others

**Never make the radar claim something it hasn't verified.** Every change is judged against the threat model in the README: missed pursuits, phantom coverage, overconfident rankings, contradiction blindness, auto-submit. If your change could make a feed state, a score, or a coverage claim *less* truthful, it doesn't merge — however elegant it is.

## Ground rules

- **Stdlib only.** No new third-party dependencies. The supply chain is the language itself.
- **Python 3.9+.** CI tests 3.9–3.12 on every push; your change must pass on all of them.
- **Tests stay green and honest.** `python3 -m pytest tests/ -q` — 98 tests. Never weaken a test to make it pass; if a fixture is wrong, fix the fixture and say so in the PR.
- **No auto-submission, ever.** PORCUPINE drafts and records. It does not submit, apply, or click. PRs that blur that line will be declined.
- **Unknown stays unknown.** Missing deadlines, funding, URLs, and timezones are reported as unknown — never inferred, never averaged in.
- **Hermetic tests.** No network, no local test servers in the test suite.

## How to contribute

1. Pick an issue (or open one describing the threat your change addresses).
2. Fork, branch, change, test.
3. Open a PR that states: the threat, the mechanism, and how you verified it. That framing — threat → mechanism → record — is this project's house style, in code and in prose.

## What gets merged fastest

- Fixes that make a claim *more* truthful (a feed state distinguished, a contradiction surfaced, a label corrected).
- Verification artifacts: tests, measurements, replays.
- Documentation that matches the code exactly.

## What doesn't merge

- Capability claims ahead of their evidence.
- Threshold tuning aimed at a metric rather than a mechanism.
- Anything that touches the draft gate (`disposition=matched` **and** confirmed-open) without a threat analysis.

Questions: open an issue. The Keeper reads everything.
