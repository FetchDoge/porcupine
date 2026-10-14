"""Tunables for PORCUPINE. Sources, keyword lens, EV weights, and paths.

Program dollar ceilings from the 2026-10-04 design note are recorded here as
reference only. Scoring never copies them onto an opportunity. A funding
number is used only when that opportunity's own text states it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# Note: the package version lives in porcupine/__init__.py (single source of truth).

USER_AGENT = (
    "PORCUPINE/1.0 (Canada defence-assurance market radar; "
    "read-only research; no submission automation)"
)
FETCH_TIMEOUT_SECONDS = 20
FETCH_GAP_SECONDS = 2.5
# One retry after TimeoutError/URLError waits this long. Same gap as politeness.
RETRY_BACKOFF_SECONDS = FETCH_GAP_SECONDS
# A cached feed older than this is refetched and overwritten. 6 hours.
CACHE_TTL_SECONDS = 6 * 60 * 60
CACHE_MAX_BYTES = 2_000_000
# Verified CanadaBuys open-tender CSV is ~6.2 MB; cap separately from HTML cache.
CSV_MAX_BYTES = 16_000_000
CSV_MAX_ROWS = 10_000
CSV_MAX_FIELD_CHARS = 100_000
CANADABUYS_OPEN_TENDERS_CSV_URL = (
    "https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv"
)
CANADABUYS_CSV_REQUIRED_HEADERS = (
    "title-titre-eng",
    "referenceNumber-numeroReference",
    "solicitationNumber-numeroSollicitation",
    "publicationDate-datePublication",
    "tenderClosingDate-appelOffresDateCloture",
    "tenderStatus-appelOffresStatut-eng",
    "noticeURL-URLavis-eng",
    "tenderDescription-descriptionAppelOffres-eng",
)
MAX_OPPS_PER_FEED = 40
DESCRIPTION_MAX_CHARS = 5000
# A heading section longer than this is not one opportunity. A future date
# on a program homepage must not inherit assurance words from another section.
MAX_CARD_CHARS = 4000

# Design-doc ceilings. Not applied unless the fetched text states a dollar figure.
IDEAS_COMPONENT_REFERENCE_CAD = {
    "1a": 250_000,
    "1b": 1_500_000,
    "2": 5_000_000,
    "fce_extended_noted_in_design": 6_750_000,
}
# parse_funding never returns a number this large. $1.6B "total" is a program
# envelope. Component awards and the $6.75M extended note sit below it.
FUNDING_PROGRAM_CEILING_CAD = 100_000_000.0
# When a page states several figures, amounts under this floor lose to a
# larger one. A page whose only figure is under the floor still keeps it.
FUNDING_PLAUSIBLE_FLOOR_CAD = 1_000.0

# Cost to pursue, in CAD, by source kind. Same units as funding so EV can subtract.
EFFORT_CAD = {
    "tender": 25_000.0,
    "program": 20_000.0,
    "award": 5_000.0,
    "accelerator": 15_000.0,
    "job_board": 8_000.0,
    "default": 20_000.0,
}

# Reachability is one of these named values. Nothing in between is invented.
REACHABILITY = {
    "deadline_future": 0.75,
    "deadline_absent": 0.35,
    "closed": 0.05,
    "job_board": 0.60,
}

# Added to portfolio_fit after the keyword/moat blend, then clamped to 1.
# Absent TRL adds 0. Component 1a (TRL 1-3) is the entry door. Component 2 adds 0.
TRL_FIT_BUMP = {
    "1a": 0.10,
    "1b": 0.05,
    "2": 0.0,
}

# _LinkParser runs only for these kinds. Homepages and job boards are not
# listing pages; their nav and footer links are not opportunities.
# Program pages use the heading-section reader instead (DESIGN-v2 §3).
LISTING_KINDS = ("tender", "award")

FIT_KEYWORD_WEIGHT = 0.65
FIT_MOAT_WEIGHT = 0.35
# Distinct assurance-core hits that saturate the keyword-density term at 1.0.
ASSURANCE_DENSITY_SATURATION = 4
# portfolio_fit at or above this, plus assurance-white-space, counts as high-fit.
HIGH_FIT_MIN = 0.50
MATCHED_FIT_MIN = 0.50
MOAT_HIGH_FIT = 0.60

# Wilson two-sided 95% z. The reported figure is the lower bound only.
WILSON_Z = 1.96

KEYWORD_LENS = (
    "trust",
    "assurance",
    "provenance",
    "lineage",
    "compliance-by-design",
    "explainable",
    "explainability",
    "autonomy",
    "autonomous",
    "verification",
    "certification",
    "attestation",
    "human-autonomy",
    "human-machine teaming",
    "situational awareness",
    "sensor fusion",
    "command & control",
    "C2",
    "NORAD",
    "AI",
    "machine learning",
    "artificial intelligence",
    "fail-closed",
    "audit",
    "accountability",
)

# Subset of the lens that indicates the trust gap rather than a generic tech word.
ASSURANCE_CORE = (
    "trust",
    "assurance",
    "provenance",
    "lineage",
    "compliance-by-design",
    "explainable",
    "explainability",
    "verification",
    "certification",
    "attestation",
    "human-autonomy",
    "human-machine teaming",
    "fail-closed",
    "audit",
    "accountability",
)

# Lens terms that are real targeting flags but do not by themselves prove an assurance gap.
CONTEXT_LENS = (
    "autonomy",
    "autonomous",
    "situational awareness",
    "sensor fusion",
    "command & control",
    "C2",
    "NORAD",
    "AI",
    "machine learning",
    "artificial intelligence",
)

# Hardware / vehicle capability markers. Not part of the targeting lens.
CAPABILITY_MARKERS = (
    "drone",
    "uav",
    "uas",
    "flight software",
    "airframe",
    "hypersonic",
    "gimbal",
    "rf amplifier",
    "counter-drone",
    "unmanned aircraft",
)

# Public pages only. A dead URL is a skipped feed, not a crash.
SOURCES = (
    {
        "id": "canadabuys-open-tenders-csv",
        "name": "CanadaBuys open tender notices (CSV)",
        "kind": "tender",
        "format": "canadabuys_csv",
        "url": CANADABUYS_OPEN_TENDERS_CSV_URL,
        "dataset_url": CANADABUYS_OPEN_TENDERS_CSV_URL,
        "max_bytes": CSV_MAX_BYTES,
        "coverage_scope": "federal_open_tenders_csv_only",
    },
    {
        "id": "ideas-program",
        "name": "DND IDEaS program",
        "kind": "program",
        "url": "https://www.canada.ca/en/department-national-defence/programs/defence-ideas.html",
    },
    {
        "id": "canadabuys-tenders",
        "name": "CanadaBuys tender opportunities",
        "kind": "tender",
        "url": "https://canadabuys.canada.ca/en/tender-opportunities",
    },
    {
        "id": "canadabuys-ideas",
        "name": "CanadaBuys IDEaS keyword",
        "kind": "tender",
        "url": "https://canadabuys.canada.ca/en/tender-opportunities?keywords=IDEaS",
    },
    {
        "id": "canadabuys-awards",
        "name": "CanadaBuys IDEaS award notices",
        "kind": "award",
        "url": "https://canadabuys.canada.ca/en/award-notices?keywords=IDEaS",
    },
    {
        "id": "drdc",
        "name": "DRDC",
        "kind": "program",
        "url": "https://www.canada.ca/en/defence-research-development.html",
    },
    {
        "id": "cdl-defence",
        "name": "CDL Defence stream",
        "kind": "accelerator",
        "url": "https://creativedestructionlab.com/streams/defence/",
    },
    {
        "id": "mitacs",
        "name": "MITACS",
        "kind": "program",
        "url": "https://www.mitacs.ca/",
    },
    {
        "id": "vizworx",
        "name": "VizworX",
        "kind": "job_board",
        "url": "https://vizworx.com/",
    },
    {
        "id": "canadian-uavs",
        "name": "Canadian UAVs",
        "kind": "job_board",
        "url": "https://canadianuavs.ca/",
    },
)


def workspace_root() -> Path:
    """Runtime root. Everything the run writes stays under it."""
    return Path.cwd()


def ledger_path(root: Optional[Path] = None) -> Path:
    """Path of the append-only opportunity ledger."""
    base = workspace_root() if root is None else Path(root)
    return base / "ledger" / "porcupine.jsonl"


def journal_path(root: Optional[Path] = None) -> Path:
    """Path of the hash-chained decision journal."""
    base = workspace_root() if root is None else Path(root)
    return base / "ledger" / "journal.jsonl"


def cache_dir(root: Optional[Path] = None) -> Path:
    """Directory of cached feed bodies."""
    base = workspace_root() if root is None else Path(root)
    return base / "cache"


def output_dir(root: Optional[Path] = None) -> Path:
    """Directory of run artifacts: ranked, feeds, drafts, last-run."""
    base = workspace_root() if root is None else Path(root)
    return base / "output"
