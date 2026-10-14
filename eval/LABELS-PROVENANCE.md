# Labels provenance — eval/labels.csv

**These labels are MACHINE labels. They are not human ground truth, and no
figure computed from them may be cited as human-validated precision.**

## Decision

2026-10-14 — Marcus Richards: "Machine pass is enough — score it and label
the report as machine-labeled." This file, the banner in
`eval/EVAL-REPORT.md`, and the first comment line of `eval/labels.csv`
carry that provenance.

## Method

- Source sheet: `eval/to_label.csv` (720 rows = 120 opportunities x 6
  components), sampled seed 7 from
  `source-evidence/canadabuys-capture-2026-10-13.csv` (SHA-256 in its
  provenance sidecar).
- Two labelers worked independently on a BLIND copy
  (`blind_input.csv`: opportunity_id, title, description, component —
  `predicted_label` and fit points stripped before labeling).
- Each applied `eval/RUBRIC.md` v1.0 as written; every label carries a
  verbatim evidence quote from the row text, programmatically verified
  as an exact substring (720/720 rows, both passes).
- Agreement: 718/720 rows (99.7%). Disagreements: exactly 2, both
  ep-aec-conformance, both resolved by the rubric's own rule —
  disagreement takes the conservative label (`no-fit`) — and recorded in
  `adjudication_notes` in labels.csv:
  - `PW-__PQ-992-74154` (ANSI/BIFMA furniture certification)
  - `cb-120-43677881` (internal-audit QA assessment vs IIA Standards)

## Result (2026-10-14, eval/EVAL-REPORT.md)

- Final labels: 0 fit / 720.
- The classifier predicted fit on 14 rows (13 ep-aec-conformance,
  1 adversarial-seat). Both blind labelers judged all 14 no-fit:
  precision on predicted positives = 0/14 against machine labels.
- With zero positive labels, the harness reports precision, recall and
  precision@10 as "insufficient labels" rather than printing zeros —
  the pre-registered falsifier (P@10 < 0.5) is therefore not evaluable
  on this sample.
- Convergent finding from both labelers, independently: the
  ep-aec-conformance pattern fires on certification language anywhere
  (nurse-trainer certification, ship-refit certification activities,
  furniture standards, fall-protection inspection bundled with repair)
  where no independent conformance deliverable for a digital/agent
  system exists. Recorded consequence, per the project's falsifier
  doctrine (redesign the lens, don't tune thresholds): the EP-AEC
  pattern needs scoping to independent assessment as the deliverable.
  That redesign is future work, not part of this measurement.

## Supersession

Human labels, if ever produced for this sheet (same seed, same rows),
replace this file wholesale and the report is re-run the same day; this
provenance file is then amended to record the supersession.
