# Live-run protocol

**Threat this protocol exists to stop:** a tool that runs forever on vibes —
no baseline, no stop rule, no falsifier. Four weeks of unattended optimism is
how dead products consume live calendars.

Run PORCUPINE once per week for four weeks against the live CanadaBuys CSV
source. For each run, retain its output and record every decision with the
`journal` CLI. This is observation and drafting only; nothing is submitted.

## Cadence and time logging

**Threat:** "it saves time" asserted without ever measuring time.

*Mechanism:* before week 1, establish the week-0 manual baseline: record the hours spent
scanning notices by hand, without PORCUPINE. In weeks 1–4, record both any
manual verification time and all radar-assisted scanning/review time in
`docs/time-log-template.csv`. Put the IDs receiving a pursue decision in the
`pursued_ids` field (semicolon-separated when there is more than one).
Time saved for a week is the week-0 manual baseline minus that week's total
radar-assisted review time, using the same scanning scope.

An opportunity is **pursued** only when its journal `decision` has
`verdict=pursue`. It is **surfaced** only when the run records
`disposition=matched` and `open=true`. A draft or a high score is neither —
scores do not pursue, people do.

## Weekly procedure

1. Run the live CanadaBuys intake and preserve the run artifacts.
2. Review surfaced items and log the time consistently with week 0.
3. Record each pursue/pass decision with `journal log-decision`, citing its ID
   and using `--verdict pursue` only for an actual pursue decision.
4. Update the time log, including pursued IDs, and note feed failures or scope changes.

## Stop rules and falsifier

**Threat:** the sunk-cost autopilot — week five happens because week four did.

*Mechanism:* if two consecutive weeks have both zero pursued opportunities and zero time
saved, park the product bet and keep PORCUPINE only as a personal tool. Record
that call as a journal decision so it is auditable — the shutdown itself leaves
a receipt.

**Falsifier:** after labeling the evaluation set, precision@10 below 0.5
falsifies the radar's current targeting approach: redesign the keyword lens; do
not merely tune its thresholds or weights. Tuning a broken lens is polishing
the wrong instrument.

**Not claimed:** four good weeks prove the market, not the machine. They prove
the radar earns its calendar slot — nothing more.
