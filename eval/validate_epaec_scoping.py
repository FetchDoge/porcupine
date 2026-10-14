#!/usr/bin/env python3
"""Validate the issue #8 moat scoping against the labeled eval set.

Recomputes predictions over every row of eval/labels.csv twice:

- OLD: the pre-#8 primary sets for ep-aec-conformance and adversarial-seat,
  frozen below. The other components never changed, so their current sets
  are used for both passes.
- NEW: the live porcupine.moat.PORTFOLIO.

The prediction rule is sample.py's: a component predicts "fit" when its
moat fit is > 0. The OLD pass must reproduce the stored predicted_label
column exactly; if it does not, this script's method has drifted from the
original measurement and its numbers mean nothing, so it exits non-zero.

Labels are MACHINE labels (see eval/LABELS-PROVENANCE.md). All 720 final
labels are no-fit, so this validates false-positive elimination only.
Recall is unmeasured: there are no positive labels to protect.

Run: python3 eval/validate_epaec_scoping.py
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from porcupine.moat import PORTFOLIO, _fit, _signals_in_text  # noqa: E402
from porcupine.radar import opportunity_text  # noqa: E402

# Frozen pre-#8 primary sets (git history: moat.py before the scoping).
OLD_PRIMARIES = {
    "adversarial-seat": (
        "red-team",
        "red team",
        "adversarial",
    ),
    "ep-aec-conformance": (
        "compliance-by-design",
        "compliance by design",
        "certification",
        "conformance",
        "attestation",
    ),
}

COMPONENTS = (
    "interlock",
    "permit",
    "hermes-refuse",
    "adversarial-seat",
    "ep-aec-conformance",
    "exhibit",
)


def _read_labels(path: Path) -> list[dict]:
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith("#")
    ]
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def _predict(row: dict, primaries: dict[str, tuple[str, ...]]) -> str:
    text = opportunity_text({"title": row["title"], "description": row["description"]})
    signals = _signals_in_text(text, primaries[row["component"]])
    return "fit" if _fit(len(signals)) > 0 else "no-fit"


def main() -> int:
    rows = _read_labels(REPO_ROOT / "eval" / "labels.csv")
    current = {repo["name"]: repo["primaries"] for repo in PORTFOLIO}
    old = dict(current)
    old.update(OLD_PRIMARIES)

    drift = [
        (row["opportunity_id"], row["component"])
        for row in rows
        if _predict(row, old) != row["predicted_label"]
    ]
    if drift:
        print(f"FAIL: OLD pass disagrees with stored predictions on {len(drift)} rows;")
        print("the recomputation method has drifted from eval/sample.py. Stopping.")
        return 1
    print(f"Method check: OLD pass reproduces all {len(rows)} stored predictions exactly.")

    fp_old = {name: 0 for name in COMPONENTS}
    fp_new = {name: 0 for name in COMPONENTS}
    survivors = []
    for row in rows:
        new_prediction = _predict(row, current)
        if row["predicted_label"] == "fit" and row["human_label"] == "no-fit":
            fp_old[row["component"]] += 1
        if new_prediction == "fit" and row["human_label"] == "no-fit":
            fp_new[row["component"]] += 1
        if new_prediction == "fit":
            text = opportunity_text(
                {"title": row["title"], "description": row["description"]}
            )
            survivors.append(
                (row["opportunity_id"], row["component"], row["human_label"],
                 _signals_in_text(text, current[row["component"]]))
            )

    print()
    print(f"{'component':<22} {'FP before':>9} {'FP after':>8}")
    for name in COMPONENTS:
        print(f"{name:<22} {fp_old[name]:>9} {fp_new[name]:>8}")
    print(f"{'TOTAL':<22} {sum(fp_old.values()):>9} {sum(fp_new.values()):>8}")

    print()
    if survivors:
        print(f"Surviving predicted-fit rows under the NEW pattern: {len(survivors)}")
        for opp_id, component, label, signals in survivors:
            print(f"  {opp_id} | {component} | label={label} | signals={signals}")
        print("Each survivor needs a written justification in EVAL-ADDENDUM.md.")
    else:
        print("Surviving predicted-fit rows under the NEW pattern: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
