"""Pin the issue #8 scoping: signals name the deliverable, not the topic.

Every negative case below is the operative text pattern of a real falsified
row from eval/labels.csv (machine labels; eval/LABELS-PROVENANCE.md). Under
the pre-#8 pattern each minted a predicted fit; both blind labelers judged
every one no-fit. The positive cases pin that work which actually names an
independent conformance deliverable, or an adversarial method, still fits —
at the unchanged steps (1 signal = 0.70, 2 = 0.85).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from porcupine.moat import map_moat

LABELS_CSV = Path(__file__).resolve().parents[1] / "eval" / "labels.csv"
COMPONENTS = (
    "interlock",
    "permit",
    "hermes-refuse",
    "adversarial-seat",
    "ep-aec-conformance",
    "exhibit",
)


def _fit(text: str, component: str) -> float:
    mapped = map_moat({"id": "t", "title": "", "description": text})
    return next(repo["fit"] for repo in mapped["repos"] if repo["name"] == component)


def test_bundled_and_incidental_certification_mints_no_ep_aec_fit():
    falsified_patterns = [
        # cb-339-81272830: a trainer certifying its own trainees.
        "Provide Emergency Trauma Care certification to each successful participant.",
        # MX-444129852464: certification activities bundled into a refit.
        "repairs, coating and preservation activities, safety equipment "
        "servicing, and associated class and regulatory certification activities",
        # cb-745-66293289 / cb-514-87962660: bidder declaration-form boilerplate.
        "Bidders must also complete and submit a certification.",
        # WS5898966485-Doc5898988671: bidder eligibility credential.
        "the first phase will evaluate the required Indigenous Eligibility Certification",
        # cb-20-75132174: bidder eligibility process.
        "the Supplier must complete the Indigenous Business certification in the CPSS",
        # cb-733-59986617: a labour-category title, not a deliverable.
        "Information technology security threat and risk assessment and "
        "certification and accreditation analyst, Level 2",
        # cb-323-15781251: certification explicitly excluded from scope.
        "without including installation, system integration, testing, or certification",
        # MX-444181617777: certification bundled with maintenance and repair.
        "The Inspection, Certification, Maintenance and Minor Repair of Fall Protection Systems",
        # cb-435-94227930: the bidder's own credentials in a bid-component list.
        "Requirement, project experience, certification, corporate qualification",
        # PW-__PQ-992-74154: products must hold third-party certification.
        # The deliverable is furniture; certification is a product attribute.
        "certified by an independent third-part certificate as compliant with "
        "the ANSI/BIFMA e3 Furniture Sustainability Standard. Part 5 "
        "Certifications and Additional Information 5.2.4 Product Conformance",
    ]
    for text in falsified_patterns:
        assert _fit(text, "ep-aec-conformance") == 0.0, text


def test_adversarial_as_topic_mints_no_fit():
    # cb-565-60949693: "adversarial" naming an opponent's strategy (topic),
    # not red-team or adversarial testing (method).
    text = "Strengthening the strategic understanding of adversarial grand strategies"
    assert _fit(text, "adversarial-seat") == 0.0


def test_deliverable_language_still_fits_at_unchanged_steps():
    # One deliverable phrase = 0.70, two = 0.85: the steps did not move.
    assert _fit("Canada requires conformity assessment for this program.",
                "ep-aec-conformance") == 0.70
    assert _fit("third-party certification services for the platform",
                "ep-aec-conformance") == 0.85
    assert _fit("independent verification and validation of the flight software",
                "ep-aec-conformance") == 0.85
    assert _fit("compliance-by-design evidence for the operator",
                "ep-aec-conformance") == 0.70


def test_method_language_still_fits_adversarial_seat():
    assert _fit("adversarial testing of the autonomy stack",
                "adversarial-seat") == 0.70
    assert _fit("a standing red team for the program",
                "adversarial-seat") == 0.70


def test_scoped_pattern_eliminates_false_positives_on_labeled_corpus():
    lines = [
        line for line in LABELS_CSV.read_text(encoding="utf-8").splitlines()
        if not line.startswith("#")
    ]
    rows = list(csv.DictReader(io.StringIO("\n".join(lines))))
    assert len(rows) == 720
    false_positives = []
    for row in rows:
        mapped = map_moat(
            {"id": row["opportunity_id"], "title": row["title"],
             "description": row["description"]}
        )
        fit = next(
            repo["fit"] for repo in mapped["repos"]
            if repo["name"] == row["component"]
        )
        if fit > 0 and row["human_label"] == "no-fit":
            false_positives.append((row["opportunity_id"], row["component"]))
    assert false_positives == []
