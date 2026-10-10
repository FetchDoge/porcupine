#!/usr/bin/env python3
"""Create a deterministic, stratified opportunity × component label sheet."""

from __future__ import annotations

import argparse
import csv
import io
import random
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from porcupine import config  # noqa: E402
from porcupine.cli import assemble  # noqa: E402
from porcupine.moat import map_moat  # noqa: E402
from porcupine.radar import parse_opportunities_canadabuys_csv  # noqa: E402

RUBRIC_VERSION = "1.0"
COMPONENTS = (
    "interlock",
    "permit",
    "hermes-refuse",
    "adversarial-seat",
    "ep-aec-conformance",
    "exhibit",
)
FIELDS = (
    "rubric_version", "sampler_seed", "stratum", "rank", "opportunity_id",
    "title", "description", "url", "component", "predicted_label",
    "human_label", "evidence_quote", "adjudication_notes", "example",
)
STRATA = ("matched", "displayed-not-matched", "rejected-valid", "all-rows-rejected")


def _stratum(row: dict, all_rows_rejected: bool) -> str:
    if all_rows_rejected:
        return "all-rows-rejected"
    if row.get("disposition") == "matched":
        return "matched"
    if row.get("disposition") == "rejected":
        return "rejected-valid"
    return "displayed-not-matched"


def _allocate(groups: dict[str, list[dict]], n: int, rng: random.Random) -> list[dict]:
    """Round-robin non-empty strata, then fill from their remaining rows."""
    for rows in groups.values():
        rng.shuffle(rows)
    chosen: list[dict] = []
    while len(chosen) < n:
        progressed = False
        for name in STRATA:
            if groups[name] and len(chosen) < n:
                chosen.append(groups[name].pop())
                progressed = True
        if not progressed:
            break
    return chosen


def sample_capture(csv_path: Path, n: int, seed: int) -> tuple[list[dict], dict]:
    body = csv_path.read_text(encoding="utf-8-sig")
    opportunities, stats = parse_opportunities_canadabuys_csv(
        body,
        source="canadabuys-open-tenders-csv",
        page_url=str(csv_path),
        source_name="CanadaBuys capture",
        source_kind="tender",
        dataset_url=str(csv_path),
        today=date.today(),
    )
    if stats["parse_outcome"] in ("schema_drift", "unsupported"):
        raise ValueError("capture could not be parsed: " + stats["parse_outcome"])
    ranked = assemble(opportunities, today=date.today())
    all_rows_rejected = bool(ranked) and all(r.get("disposition") == "rejected" for r in ranked)
    groups = {name: [] for name in STRATA}
    for rank, row in enumerate(ranked, 1):
        enriched = dict(row)
        enriched["rank"] = rank
        enriched["stratum"] = _stratum(row, all_rows_rejected)
        groups[enriched["stratum"]].append(enriched)
    chosen = _allocate(groups, max(0, n), random.Random(seed))
    return chosen, stats


def label_rows(chosen: list[dict], seed: int) -> list[dict]:
    output = []
    for row in chosen:
        predicted = {
            repo["name"]: "fit" if repo["fit"] > 0 else "no-fit"
            for repo in map_moat(row)["repos"]
        }
        for component in COMPONENTS:
            output.append({
                "rubric_version": RUBRIC_VERSION,
                "sampler_seed": seed,
                "stratum": row["stratum"],
                "rank": row["rank"],
                "opportunity_id": row["id"],
                "title": row["title"],
                "description": row["description"],
                "url": row["url"],
                "component": component,
                "predicted_label": predicted.get(component, "no-fit"),
                "human_label": "",
                "evidence_quote": "",
                "adjudication_notes": "",
                "example": "false",
            })
    return output


def write_sheet(path: Path, rows: list[dict], seed: int, stats: dict) -> None:
    available = sorted({row["stratum"] for row in rows})
    unavailable = [name for name in STRATA if name not in available]
    buf = io.StringIO()
    buf.write(f"# sampler_seed={seed}\n")
    buf.write(f"# rubric_version={RUBRIC_VERSION}\n")
    buf.write("# unavailable_strata=" + (",".join(unavailable) or "none") + "\n")
    buf.write(
        f"# parse_outcome={stats['parse_outcome']};raw_rows={stats['raw_rows']};"
        f"valid_rows={stats['valid_rows']};rejected_rows={stats['rejected_rows']}\n"
    )
    writer = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(buf.getvalue(), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--n", required=True, type=int)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.n < 1:
        parser.error("--n must be at least 1")
    chosen, stats = sample_capture(args.csv, args.n, args.seed)
    write_sheet(args.out, label_rows(chosen, args.seed), args.seed, stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

