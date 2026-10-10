# PORCUPINE v2 — build brief (increments 3–5)

You are building inside this repo — run all commands from the repo root.
Increments 1–2 (netguard, journal) are already landed and green; do not modify them except to fix a breakage you can demonstrate with a failing test. Implement increments 3, 4, 5 below, in order.

## Increment 3 — Eval harness (`eval/`, new directory; NOT part of the installed package)

**Threat:** precision claims without labeled ground truth. "It works" measured
against nothing is a feeling with a test suite.

- `eval/RUBRIC.md`: labeling rubric for (opportunity × portfolio-component)
  fit/no-fit judgments. Required: an evidence quote from the opportunity text
  for every label; the assurance-core vs context-lens distinction from
  `porcupine/config.py` (ASSURANCE_CORE vs CONTEXT_LENS); adjudication rule
  (two labels disagree → the more conservative label wins, disagreement
  recorded and never erased); what "fit" means per component (Interlock, Permit, Hermes Refuse,
  Adversarial Seat, EP-AEC Conformance, Exhibit — one line each, grounded in
  `porcupine/moat.py`).
- `eval/sample.py`: stratified sampler. Usage:
  `python3 eval/sample.py --csv <capture> --n 120 --seed 7 --out eval/to_label.csv`.
  Runs the pipeline's CSV parse + scoring over the capture, then samples
  across strata (matched / displayed-not-matched / rejected-valid /
  all-rows-rejected) with the sampling seed recorded in the output header
  comment. Must work with the repo's existing `parse_opportunities_canadabuys_csv`
  and scoring functions — import from `porcupine`, do not reimplement.
- `eval/score.py`: `python3 eval/score.py --labels eval/labels.csv --report eval/report.md`.
  Computes precision, recall, precision@k (k=10) overall and per portfolio
  component against the labels file; writes a Markdown report with the raw
  counts, the rubric version, and the sampler seed. A label file with zero
  positive labels must report "insufficient labels" rather than zeros — zeros
  would be a fabricated measurement.
- `eval/labels.example.csv`: 5 example rows in the exact labels schema, every
  row marked `example=true`, and `score.py` must exclude example rows from
  scoring.

## Increment 4 — Live-run protocol (`docs/LIVE-RUN-PROTOCOL.md`, new file)

**Threat:** a tool that runs forever on vibes — no baseline, no stop rule, no
falsifier. See `docs/LIVE-RUN-PROTOCOL.md` for the full protocol: 4-week
cadence, week-0 manual baseline, time logging, pursue/surface definitions, and
the stop rules (two dead weeks → park the product bet; precision@10 < 0.5 →
redesign the lens, don't tune it).

## Increment 5 — Sustainability

**Threat:** dependency rot and untested pushes. A repo whose CI doesn't run is
a repo whose tests are decoration.

- `pyproject.toml`: stdlib only — no new dependencies; package `porcupine`,
  `requires-python = ">=3.9"`, pytest config pointing at `tests/`.
- `.github/workflows/ci.yml`: run `python3 -m pytest tests/ -q` on push and
  pull_request (3.11 and 3.12 matrix is fine; keep it minimal).
- README honesty pass: rewrite `README.md` claims to match only what is
  verified (98 tests, CSV intake, provenance, draft gating, heuristic
  labeling, unresolved items list). No new capability claims — the README is
  a record, not a pitch deck.

## Hard constraints

- Python 3.9-compatible, stdlib only, match existing code style.
- Full suite stays green; new hermetic tests for `eval/score.py` (synthetic
  labels incl. the insufficient-labels case) and `eval/sample.py` (strata
  coverage on the reference fixture
  `source-evidence/canadabuys-reference.csv`).
- No auto-submission, no invented opportunity data, no credential changes.

## Verifier commands (run from repo root)

```bash
python3 -m pytest tests/ -q
python3 eval/sample.py --csv source-evidence/canadabuys-reference.csv --n 12 --seed 7 --out /tmp/to_label.csv && head -5 /tmp/to_label.csv
```

Expect: full suite green; sampler emits a labeled-schema CSV.

## Done =

Increments 3–5 landed, full suite green, verifier commands executed.
Final response: per-increment receipt (files changed, tests added, how
verified, what remains unknown).

**Not claimed:** the eval harness measures the radar against human labels; it
does not certify the labels. Garbage labels in, garbage precision out — the
rubric is the defense, not a guarantee.
