"""Competitor scope: assurance white space versus capability-saturated work.

The blind-spot map is the design note's table, kept as data the classifier
actually returns. A row that no classification selects is unused.
"""

from __future__ import annotations

from . import config
from .radar import match_capability, match_keywords, opportunity_text

CLASS_WHITE_SPACE = "assurance-white-space"
CLASS_SATURATED = "capability-saturated"
CLASS_ADJACENT = "adjacent"
CLASS_OUT = "out-of-lens"

BLIND_SPOT_MAP = (
    {
        "id": "capability-vs-assurance",
        "when": CLASS_SATURATED,
        "competitors_chase": (
            "Better drone, sensor, or model capability "
            "(Anduril, Shield AI, Helsing, Qoherent, Rockwell Collins, "
            "and Calgary hardware shops such as NVD, Canadian UAVs, VizworX, MicroLynx)"
        ),
        "miss": (
            "Prove what the autonomous system did, on operator-held keys, "
            "with the vendor outside the trust path"
        ),
        "own_with": ("interlock", "hermes-refuse", "ep-aec-conformance", "adversarial-seat"),
    },
    {
        "id": "compliance-bolt-on",
        "when": CLASS_WHITE_SPACE,
        "competitors_chase": "Compliance as a bolt-on checkbox after the system is built",
        "miss": "Compliance-by-design: policy enforced in the execution path, not in a slide",
        "own_with": ("hermes-refuse", "ep-aec-conformance", "interlock"),
    },
    {
        "id": "black-box-autonomy",
        "when": CLASS_WHITE_SPACE,
        "competitors_chase": "Proprietary black-box autonomy and fusion",
        "miss": "Provenance and full lineage the operator can replay",
        "own_with": ("interlock", "exhibit"),
    },
    {
        "id": "hardware-incumbent",
        "when": CLASS_SATURATED,
        "competitors_chase": "Hardware and RF incumbents, slow and siloed",
        "miss": "A civilian agent-governance stack reframed for defence assurance",
        "own_with": ("interlock", "permit", "hermes-refuse", "adversarial-seat"),
    },
    {
        "id": "ignore-low-trl",
        "when": CLASS_WHITE_SPACE,
        "competitors_chase": "Skipping TRL 1-3 entry grants",
        "miss": "Component 1a as the door, only when a live challenge text says so",
        "own_with": ("beacon",),
    },
)


def blind_spots_for(classification: str) -> list[dict]:
    """Blind-spot rows for a classification, as copies. The map itself is never mutated."""
    return [dict(row) for row in BLIND_SPOT_MAP if row["when"] == classification]


def classify(opp: dict) -> dict:
    """Classify one opportunity. Capability with no assurance-core hit is saturated."""
    text = opportunity_text(opp)
    keywords = match_keywords(text)
    if not keywords and opp.get("raw_keywords_matched"):
        keywords = [item for item in opp["raw_keywords_matched"] if item in config.KEYWORD_LENS]
    capability = match_capability(text)
    if not capability and opp.get("capability_markers"):
        capability = list(opp["capability_markers"])
    core = [item for item in keywords if item in config.ASSURANCE_CORE]
    context = [item for item in keywords if item in config.CONTEXT_LENS]
    if core:
        classification = CLASS_WHITE_SPACE
        reason = "assurance-core keywords: " + ", ".join(core)
    elif capability:
        classification = CLASS_SATURATED
        reason = "capability markers and no assurance-core keyword: " + ", ".join(capability)
    elif context or keywords:
        classification = CLASS_ADJACENT
        reason = "lens context only: " + ", ".join(keywords)
    else:
        classification = CLASS_OUT
        reason = "no lens keyword and no capability marker"
    return {
        "classification": classification,
        "reason": reason,
        "assurance_core": core,
        "context_keywords": context,
        "capability_markers": capability,
        "blind_spots": blind_spots_for(classification),
    }
