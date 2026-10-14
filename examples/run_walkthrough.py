#!/usr/bin/env python3
"""Run the PORCUPINE worked example end to end, offline, with annotations.

    python3 examples/run_walkthrough.py

Replays the bundled CanadaBuys reference capture into a fresh temporary root,
prints the CLI's own output, then annotates the artifacts it wrote: the feed
record and its health states, one scoring trace read line by line, the
no-verified-match outcome, the content-addressed snapshot, and the hash-chained
decision journal. Nothing here touches the network, drafts, or submits.

Stdlib only. Python 3.9+.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_CSV = REPO_ROOT / "source-evidence" / "canadabuys-reference.csv"
CLOSING_DATE_COLUMN = "tenderClosingDate-appelOffresDateCloture"


def _cli(args: list, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """One CLI invocation, exactly as a reader would type it (plus --root)."""
    return subprocess.run(
        [sys.executable, "-m", "porcupine.cli"] + args,
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _replay(csv_path: Path, root: Path) -> dict:
    """Replay one CSV offline; return its single feed record."""
    proc = _cli(
        ["replay-csv", "--file", str(csv_path), "--root", str(root)]
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"replay-csv failed with exit {proc.returncode}")
    print(proc.stdout, end="")
    feeds = json.loads((root / "output" / "feeds.json").read_text(encoding="utf-8"))
    return feeds[0]


def _note(text: str) -> None:
    print(f"    -> {text}")


def _variant_csvs(work: Path) -> dict:
    """Damaged variants of the reference capture, one per unhealthy feed state."""
    raw = REFERENCE_CSV.read_bytes()
    text = raw.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))

    headers_only = work / "headers-only.csv"
    headers_only.write_text(",".join(rows[0]) + "\n", encoding="utf-8")

    drop = rows[0].index(CLOSING_DATE_COLUMN)
    drift = work / "schema-drift.csv"
    with drift.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for row in rows:
            writer.writerow([cell for index, cell in enumerate(row) if index != drop])

    truncated = work / "truncated.csv"
    truncated.write_bytes(raw[:3000])
    return {"healthy-empty": headers_only, "schema drift": drift, "truncated": truncated}


def main() -> int:
    if not REFERENCE_CSV.is_file():
        print(f"reference capture not found: {REFERENCE_CSV}", file=sys.stderr)
        return 2
    root = Path(tempfile.mkdtemp(prefix="porcupine-walkthrough-"))
    print(f"PORCUPINE walkthrough — everything below happens under {root}")
    print("(offline: no network, no drafts, nothing submitted)\n")

    print("== 1. Replay the reference capture ==")
    feed = _replay(REFERENCE_CSV, root)
    _note(
        f"feed state: status={feed['status']} parse_outcome={feed['parse_outcome']} "
        f"raw={feed['raw_rows']} valid={feed['valid_rows']} — the feed was healthy."
    )
    _note(f"coverage, stated not hidden: {feed['coverage_warning']}")
    _note(f"transport hardening: {feed['transport_hardening']} (an open item, in the record)")

    body_hash = hashlib.sha256(
        REFERENCE_CSV.read_text(encoding="utf-8-sig").encode("utf-8")
    ).hexdigest()
    _note(
        f"provenance: sha256 of the replayed file is {body_hash[:16]}… "
        f"and feeds.json recorded body_text_sha256={feed['body_text_sha256'][:16]}… "
        f"— match: {body_hash == feed['body_text_sha256']}. "
        f"The snapshot is kept at {feed['source_snapshot_ref']}."
    )

    print("\n== 2. Read the top scoring trace ==")
    ranked = json.loads((root / "output" / "ranked.json").read_text(encoding="utf-8"))
    top = ranked[0]
    print(f"    {top['id']} — {top['title']}")
    print(f"    formula: {top['formula']}")
    for name, trace in top["traces"].items():
        print(f"    trace {name}: {trace}")
    _note(
        f"disposition={top['disposition']} classification={top['classification']} "
        f"({top['classification_reason']}); ev_label={top['ev_label']} — "
        "a ranking heuristic, not a win probability."
    )
    for row in ranked:
        if row.get("status_contradiction"):
            print(
                f"    contradiction caught: {row['id']} — publisher says "
                f"{row['source_status']!r}, close date {row['deadline']} is past, "
                f"so status_contradiction={row['status_contradiction']!r} and "
                f"open={row['open']}. The metadata lied; the record says so."
            )

    print("\n== 3. The no-verified-match outcome ==")
    matched = sum(1 for row in ranked if row.get("disposition") == "matched")
    _note(
        f"matched_rows={feed['matched_rows']} in feeds.json; {matched} of "
        f"{len(ranked)} ranked rows carry disposition 'matched'. No draft was "
        "written and the run still exits 0: a healthy feed that finds no "
        "verified match is a finished run, not a failure."
    )

    print("\n== 4. The same zero, three unhealthy ways ==")
    (root / "variants").mkdir(exist_ok=True)
    variants = _variant_csvs(root / "variants")
    for label, path in variants.items():
        state_root = root / ("state-" + label.replace(" ", "-"))
        variant_feed = _replay(path, state_root)
        _note(
            f"{label}: status={variant_feed['status']} "
            f"parse_outcome={variant_feed['parse_outcome']}"
            + (
                f" missing_headers={variant_feed['missing_headers']}"
                if variant_feed.get("missing_headers")
                else ""
            )
            + (
                f" parse_error={variant_feed['parse_error']!r}"
                if variant_feed.get("parse_error")
                else ""
            )
            + " — the console table above is identical for every state in "
            "this section; only feeds.json tells them apart."
        )

    print("\n== 5. Record the decision in the hash-chained journal ==")
    rationale = (
        "Replay shows adjacent, not assurance white-space; fit 0.10 is below "
        "the matched bar. No draft."
    )
    proc = _cli(
        [
            "journal", "log-decision", "--root", str(root),
            "--id", top["id"], "--verdict", "skip",
            "--rationale", rationale, "--evidence-ref", "output/ranked.json",
        ]
    )
    print(proc.stdout, end="")
    proc = _cli(["journal", "verify", "--root", str(root)])
    print(proc.stdout, end="")
    _note("the journal lives at ledger/journal.jsonl under the root; verify "
          "recomputes the hash chain and fails loudly if a line was edited.")

    print("\n== Artifacts written ==")
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        print(f"    {path.relative_to(root)}")
    _note("replay writes no ledger rows and no drafts — recording to the "
          "append-only ledger is a live `run` behavior; see examples/README.md.")
    print("\nWalkthrough complete. PORCUPINE drafted and submitted nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
