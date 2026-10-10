# PORCUPINE fit-labeling rubric

Rubric version: **1.0**

**Threat this rubric exists to stop:** label drift — the slow slide where
"fit" starts meaning "sounds related," evidence quotes get skipped "just this
once," and disagreements get resolved by whoever argues longest. A rubric
that can't say no is a rubber stamp with a spreadsheet.

Label each opportunity × portfolio-component pair `fit` or `no-fit`. A `fit`
means the opportunity text names a problem the component can directly address;
similar subject matter or a generic technology mention is not enough. Copy a
short, exact quote from the title or description into `evidence_quote` for
every label, including `no-fit` (for example, the closest relevant language or
the sentence showing that the need is construction rather than assurance).
Do not use outside knowledge or infer requirements absent from the capture.

**Threat:** context masquerading as fit. The keyword lens has two different roles. Terms in `ASSURANCE_CORE` identify
the trust, verification, provenance, or accountability problem PORCUPINE is
built to find. Terms in `CONTEXT_LENS` identify a setting (such as AI,
autonomy, C2, or sensor fusion) but do not alone establish assurance fit. A
context-only hit therefore remains `no-fit` unless the quoted text also states
a component-relevant need. A drone that needs no assurance is just a drone.

Component tests (grounded in `porcupine/moat.py`):

- **Interlock:** fit for leased authority, emergency stop/fault handling, fail-closed control, provenance/lineage, or attestation.
- **Permit:** fit only for payment, agent-payment, or spend authority.
- **Hermes Refuse:** fit for compliance-by-design or fail-closed execution.
- **Adversarial Seat:** fit for red-team or adversarial testing/methods.
- **EP-AEC Conformance:** fit for independent conformance, certification, compliance-by-design, or attestation.
- **Exhibit:** fit for explainability or claim-tiered OSINT evidence.

**Threat:** disagreements evaporating. Two labelers should work independently. If their labels disagree, record the
disagreement in `adjudication_notes` and use the more conservative final label:
`no-fit`. Never erase the disagreement — the disagreement is data. Empty or ambiguous evidence also
resolves to `no-fit`: when in doubt, the label is no.

**Not claimed:** this rubric measures fit against the portfolio as built, not
market truth. Two honest labelers can still both be wrong about the world.
