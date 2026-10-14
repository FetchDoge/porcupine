# Eval addendum — issue #8: EP-AEC pattern scoping (2026-10-14)

**Threat this addendum exists to stop:** a falsified pattern surviving as
folklore — "the lens had a certification problem once" — with no record of
what exactly was falsified, what replaced it, or what the replacement was
never validated against.

## The finding

The first labeled measurement of the classifier (`eval/EVAL-REPORT.md`,
machine labels per `eval/LABELS-PROVENANCE.md`) produced zero confirmed
fits. The classifier predicted fit on 14 of 720 rows; both independent
blind labelers judged all 14 no-fit. Thirteen were `ep-aec-conformance`,
and every one of the thirteen was minted by the single bare primary
**"certification"** (one row added "conformance" from a table-of-contents
heading, "Product Conformance"). The fourteenth was `adversarial-seat`,
minted by the bare adjective **"adversarial"**.

The falsified contexts, from the labeled rows:

| Falsified context | Example row |
|---|---|
| Trainer certifying its own trainees | cb-339-81272830 |
| Certification activities bundled into a refit contract | MX-444129852464 |
| Bidder's own credentials in a bid-component list | cb-435-94227930 |
| Bidder declaration-form boilerplate ("complete and submit a certification") | cb-745-66293289, cb-514-87962660 |
| Products required to hold third-party certification (deliverable: furniture) | PW-__PQ-992-74154 |
| Bidder eligibility certification (Indigenous Eligibility / Business) | WS5898966485, WS5908167494, cb-20-75132174 |
| Certification explicitly excluded from scope ("without including … certification") | cb-323-15781251 |
| Labour-category title ("certification and accreditation analyst") | cb-733-59986617 |
| Certification bundled with inspection, maintenance, and repair | MX-444181617777 |
| Deferred, undefined mention ("certifications … will be defined in future stages") | cb-44-67693139 |
| "Adversarial" as geopolitical topic, not method | cb-565-60949693 |

In none of them is an independent conformance assessment the deliverable
being bought — which is what the component is: its blurb is "independent
conformance verifier," and the rubric's test begins with the word
"independent."

## The mechanism

Pattern redesign in `porcupine/moat.py`, one rule applied to both falsified
components: **a primary signal must name the component's deliverable or
method, not merely its topic.**

- `ep-aec-conformance`: bare `certification`, `conformance`, and
  `attestation` removed. In their place, phrases that denote the assessment
  as the work being bought: `conformity assessment`, `conformance
  assessment`, `conformance testing`, `certification services`,
  `accreditation services`, `attestation services`, `remote attestation`,
  `independent verification`, `verification and validation`,
  `third-party certification`, `third party certification`.
  `compliance-by-design` / `compliance by design` are unchanged — they are
  already deliverable claims, and no labeled row falsified them.
- `adversarial-seat`: bare `adversarial` removed (same defect class: a
  topic adjective minting a fit). It is replaced by the method collocations
  the rubric names — `adversarial testing`, `adversarial test`,
  `adversarial evaluation`, `adversarial assessment`. `red-team` /
  `red team` are unchanged.

No exclusion list was added: once signals must name the deliverable, the
bundled, negated, eligibility, staffing, and product-attribute contexts
above simply contain no signal. Simpler mechanism, same falsified set.

## Validation

`eval/validate_epaec_scoping.py` recomputes predictions over all 720
labeled rows with the frozen pre-#8 pattern and with the live pattern,
using sample.py's rule (fit > 0 ⇒ predicted fit). The old pass first
reproduces the stored `predicted_label` column on all 720 rows exactly —
the recomputation is the original measurement, not a re-imagining of it.

| Component | FP before | FP after |
|---|---:|---:|
| interlock | 0 | 0 |
| permit | 0 | 0 |
| hermes-refuse | 0 | 0 |
| adversarial-seat | 1 | 0 |
| ep-aec-conformance | 13 | 0 |
| exhibit | 0 | 0 |
| **Total** | **14** | **0** |

Surviving predicted-fit rows under the new pattern: **none** — nothing to
justify. Exactly 14 predictions change across the whole corpus, and they
are exactly the 14 falsified rows; no other row's prediction moves, and no
new fit is minted anywhere. `tests/test_moat_scoping.py` pins each falsified
text pattern, the deliverable phrases that still fit, and the corpus result.

Full suite after the change: see the run recorded with this addendum —
all pre-existing tests pass unmodified, plus the 5 new scoping tests.

## What was NOT changed

- **The fit steps.** 1 signal = 0.70, 2 = 0.85, 3+ = 1.00, 0 = 0.00. No
  threshold moved; this is a pattern redesign, not a tuning pass.
- **`eval/RUBRIC.md`.** The rubric already said "independent conformance";
  the pattern was brought to the rubric, not the reverse.
- **`eval/labels.csv`.** The ground truth this was validated against is
  untouched, including the two adjudicated disagreement rows.
- **Every other component's primaries**, and the radar keyword lens in
  `config.py` (a different instrument: it sets disposition and strata, not
  the eval's predicted labels).

## Standing caveat

The labels are **machine labels**, not human ground truth
(`eval/LABELS-PROVENANCE.md`). All 720 final labels are no-fit, so this
scoping is validated on **false-positive elimination only**. Recall is
unmeasured: there are no confirmed positives in the set, so nothing here
proves the narrower pattern still catches real independent-conformance
solicitations — the deliverable phrases in the new set are the design's
answer to that risk, pinned by positive tests, but they have never been
scored against a labeled positive. If human labels are ever produced for
this sheet, this validation must be re-run against them the same day, and
any positive the new pattern misses is a finding against this addendum.
