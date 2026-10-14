"""Map an opportunity's language onto the operator's assurance portfolio.

Fit is the count of primary signals that actually appear in the text.
One primary signal is 0.70. Two is 0.85. Three or more is 1.00.
Zero is 0.00. Those steps are the whole scale.
"""

from __future__ import annotations

import re

from . import config
from .radar import opportunity_text

# Primary signals are phrases the repo is allowed to claim. A generic word
# such as "AI" or "drone" is deliberately absent so it cannot mint a moat.
#
# Scoping rule (2026-10-14, issue #8): a signal must name the component's
# deliverable or method, not merely its topic. The labeled eval
# (eval/labels.csv, machine labels; eval/LABELS-PROVENANCE.md) falsified the
# bare topic nouns: every one of the 14 predicted fits was judged no-fit, and
# 13 of the 14 were minted by the single bare word "certification" firing on
# bundled or incidental language (a trainer certifying its own trainees,
# certification activities inside a refit contract, a bidder's eligibility
# certification form, a labour-category title, certification explicitly
# excluded from scope). The fourteenth was the bare adjective "adversarial"
# firing on geopolitical prose ("adversarial grand strategies"), not on any
# testing method. Bare "certification", "conformance", "attestation", and
# "adversarial" are therefore gone; what remains names the work itself:
# conformity/conformance assessment, certification/accreditation/attestation
# services, adversarial testing. The fit steps did not move.
PORTFOLIO = (
    {
        "name": "interlock",
        "blurb": "leased authority, e-stop, fault bus, and provenance",
        "primaries": (
            "provenance",
            "lineage",
            "full lineage",
            "fail-closed",
            "fail closed",
            "e-stop",
            "emergency stop",
            "fault bus",
            "leased authority",
            "attestation",
        ),
    },
    {
        "name": "permit",
        "blurb": "payment authority for agents",
        "primaries": (
            "payment authority",
            "agent payment",
            "spend authority",
        ),
    },
    {
        "name": "hermes-refuse",
        "blurb": "fail-closed execution layer",
        "primaries": (
            "compliance-by-design",
            "compliance by design",
            "fail-closed",
            "fail closed",
        ),
    },
    {
        "name": "adversarial-seat",
        "blurb": "red-team method",
        "primaries": (
            "red-team",
            "red team",
            "adversarial testing",
            "adversarial test",
            "adversarial evaluation",
            "adversarial assessment",
        ),
    },
    {
        "name": "ep-aec-conformance",
        "blurb": "independent conformance verifier",
        "primaries": (
            "compliance-by-design",
            "compliance by design",
            "conformity assessment",
            "conformance assessment",
            "conformance testing",
            "certification services",
            "accreditation services",
            "attestation services",
            "remote attestation",
            "independent verification",
            "verification and validation",
            "third-party certification",
            "third party certification",
        ),
    },
    {
        "name": "exhibit",
        "blurb": "claim-tiered OSINT",
        "primaries": (
            "explainable",
            "explainability",
            "claim-tiered",
            "osint",
        ),
    },
    {
        "name": "beacon",
        "blurb": "funding radar",
        "primaries": (
            "funding radar",
            "grant radar",
        ),
    },
)


def _fit(hit_count: int) -> float:
    """Hit count to fit: 0, 0.70, 0.85, 1.00. Those steps are the whole scale."""
    if hit_count <= 0:
        return 0.0
    if hit_count == 1:
        return 0.70
    if hit_count == 2:
        return 0.85
    return 1.0


def _signals_in_text(text: str, primaries: tuple[str, ...]) -> list[str]:
    """Primary signals actually present in the text. Generic words cannot mint a moat."""
    norm = " ".join(text.lower().replace("&amp;", "&").split())
    found = []
    for primary in primaries:
        pattern = r"(?<!\w)" + re.escape(primary.lower()) + r"(?!\w)"
        if re.search(pattern, norm):
            found.append(primary)
    return found


def map_moat(opp: dict) -> dict:
    """Map opportunity text onto the portfolio. Returns per-repo fits and the positioning paragraph."""
    text = opportunity_text(opp)
    repos = []
    for repo in PORTFOLIO:
        signals = _signals_in_text(text, repo["primaries"])
        repos.append(
            {
                "name": repo["name"],
                "blurb": repo["blurb"],
                "fit": _fit(len(signals)),
                "signals": signals,
            }
        )
    strength = max((repo["fit"] for repo in repos), default=0.0)
    leaders = [repo for repo in repos if repo["fit"] >= config.MOAT_HIGH_FIT]
    if leaders:
        strongest = max(leaders, key=lambda repo: repo["fit"])["name"]
    else:
        strongest = ""
    return {
        "repos": repos,
        "moat_strength": strength,
        "strongest_repo": strongest,
        "high_repos": [repo["name"] for repo in leaders],
        "paragraph": moat_paragraph(leaders),
    }


def moat_paragraph(high_repos: list[dict]) -> str:
    """Defensible-angle paragraph for a draft, or an honest no-moat statement."""
    if not high_repos:
        return (
            "No portfolio repo clears the high-fit bar on this text. "
            "An assurance moat is not claimed. Record the item and leave the angle for a later read."
        )
    parts = []
    for repo in high_repos:
        signals = ", ".join(repo["signals"])
        parts.append(f"{repo['name']} ({repo['blurb']}; signals: {signals})")
    joined = "; ".join(parts)
    return (
        "Defensible angle: cover the assurance layer this text names with "
        f"{joined}. "
        "A capability vendor would have to rebuild fail-closed execution, "
        "operator-held provenance, and independent conformance to match that, "
        "because those are architectural properties rather than a feature bolted on later. "
        "This paragraph positions a draft. It is not a submission."
    )
