# PORCUPINE — DESIGN v2

**How this design earned its shape:** an independent red-team reviewed the v1
design and returned 6 objections at 0.86 confidence. Three verified true
against the source on the spot. This document is what changed because of them —
each fix is recorded as the attack it stops, not as a feature.

Supersedes `DEEP-DESIGN.md` and `ALGORITHM-TARGETING.md` where they conflict.

## §1 — The split organ

**Threat:** one drift statistic carrying two opposite actuators (adapt vs
defend) with no discriminator — and a slow baseline update turns the attack
into the trusted normal, after which the 90-day falsifier *deletes the
sensor*. A patient attacker doesn't break the radar; it becomes the weather.

**Mechanism:**
- A **human-signed REFERENCE** — lens tuple + per-source shape + scoring
  weights — is pinned. The drift monitor may **alarm against** it; it may
  **not write** it.
- Adaptation is **PROPOSE-ONLY**: it emits a queue; a human disposes. The
  monitor's baseline is the *pinned reference*, never its own running history.
- The slow-poison fixed point is removed: an attacker can raise alarms, but
  cannot move the reference the alarms are measured against.

**Record:** objections 1–3 verified TRUE against source by independent recount
(Raven) — `record-win` was wins-only (cli.py:91, no loss path); `rank_scores`
sorted on raw `ev` (scoring.py:237); the 90-day-silence falsifier existed
(DEEP-DESIGN.md:100).

**Not claimed:** the monitor detects drift; it does not attribute it. Alarm ≠
diagnosis.

## §2 — The calibration loop

**Threat:** `g = p̂ − Wilson_LCB` was mathematically wrong — it measures
*interval width* (a function of n), not honesty. A perfectly calibrated model
at n=20, p̂=0.5 reports as ~+0.20 "overconfident." Worse: `record-win` was an
unbounded wins-only oracle (n clicks → LCB ≈ 0.84) — a machine that learns
only from its victories and calls the result calibration.

**Mechanism:**
- Report **Brier prequentially against the outcome rate**, plus ECE, with a
  **cluster id** (IDEaS notices in one call are *not* iid — three
  solicitations is not twenty exposures).
- Record **every outcome** as `(opportunity_id, predicted_p_frozen, outcome ∈
  {won, lost, expired, noise}, receipt)`. Losses are recorded. `predicted_p`
  is frozen at decision time so a later re-fit cannot grade itself.
- Thresholds are **not retuned on the same sample** they are scored on
  (prequential holdout).
- Rank on a utility that uses the held-out estimate — not raw optimistic `ev`.

**Record:** the wins-only oracle was demonstrated in source before the fix.

**Not claimed:** calibration against outcomes not yet observed. The lower bound
stays zero until the ledger says otherwise.

## §3 — The gate

**Threat:** density-independent structural scoring was false of the live gate —
a keyword hit with no money and no deadline still counted. A bare "by"
forges an open deadline (*"issued by 22 October 2027"*), and a single
component label could select an adversarial multi-million figure.

**Mechanism:**
- A keyword hit counts **only inside a window of a parsed money amount AND a
  deadline label that is not a bare "by"**.
- A **single** component label must not select an adversarial figure → the
  figure must be adjacent to the challenge's own component name.
- **Program pages with no `<article>` must be parsed** — that is the *primary
  source*.

**Record:** bare-"by" regression test `test_issued_by_does_not_set_deadline`.

**Not claimed:** the gate is complete. Transport hardening remains explicitly
unresolved.

## §4 — Contradictions in the author's own docs, reconciled

| The contradiction (threat: the design argues with itself) | Resolution (mechanism) |
|---|---|
| Φ = keyword density vs density-independent | **one** definition: structural fit |
| online Bayes *mean* vs median/trimmed never-mean | **robust estimator + prequential holdout**; no naive mean |
| "re-fit without a human" vs "lens additions human-approved" | the **human gate wins** — the deepest principle must not delete the only gate on the layer an attacker most wants to write |
| FIGHT needs `p_actual ≥ θ` but `n=0 ⇒ p_actual=0` ⇒ never fights, yet the CLI drafts anyway | with real outcomes recorded, `n=0 ⇒ FLIGHT` (no pursuit) — and the CLI must **not** draft a confirmed-open row at `p_actual=0` |

## §5 — Deleted

**Threat:** the falsifier *"90 days of silence ⇒ delete the nervous system"*
is not a mechanism — it is a **retirement ceremony a patient attacker
satisfies by staying inside the deadband**. Likewise the "silent assassin"
*silence-as-value* line, to the extent it equates **no alarm** with **no
value**.

**Mechanism:** both deleted. Silence is now an observation with a confidence
interval, not a verdict.

## §6 — What survives (do not touch)

**Threat addressed by keeping:** ripping out working brakes because the
blueprint changed. The reviewer explicitly agreed these are "actual brakes,
misused" — keep them: Wilson function · draft-never-submit · fail-soft ·
cache TTL (6h) · the verified funding / deadline / scheme-allowlist fixes.

## §7 — Falsifiers (v2)

Each is a tripwire with a named failure:

- A planted slow-drift poison still moves a decision **without** an alarm ⇒
  the split organ failed.
- `record` accepts an outcome with no opportunity id or no receipt ⇒ the
  oracle is open again.
- A bare-"by" date still mints `open=True` ⇒ the gate fix did not land.
- Rank still sorts on raw `ev` ⇒ the calibrated utility is inert.

## §8 — Status

**Blueprint only — held.** No code written for v2. The live code is the
verified hardened v1. Building v2 requires: C2 (feed parsers) + the §1–§4
changes, each with its own falsifier.

**Not claimed:** v2 is not implemented, not tested, not deployed. This
document is a blueprint with tripwires, not a changelog.
