#!/usr/bin/env python3
"""Score human labels against PORCUPINE's component predictions."""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path


def _read(path: Path) -> tuple[list[dict], dict[str, str]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    metadata = {}
    data = []
    for line in lines:
        if line.startswith("#"):
            token = line[1:].strip()
            if "=" in token:
                key, value = token.split("=", 1)
                metadata[key.strip()] = value.strip()
        else:
            data.append(line)
    reader = csv.DictReader(io.StringIO("\n".join(data)))
    if reader.fieldnames:
        missing = [name for name in ("human_label", "predicted_label")
                   if name not in reader.fieldnames]
        if missing:
            raise ValueError(
                "labels file is missing required column(s): " + ", ".join(missing)
            )
    all_rows = list(reader)
    if "rubric_version" not in metadata:
        metadata["rubric_version"] = next(
            (row.get("rubric_version", "") for row in all_rows if row.get("rubric_version")),
            "unknown",
        )
    if "sampler_seed" not in metadata:
        metadata["sampler_seed"] = next(
            (row.get("sampler_seed", "") for row in all_rows if row.get("sampler_seed")),
            "unknown",
        )
    rows = [row for row in all_rows if row.get("example", "").strip().lower() != "true"]
    seen = set()
    for row in rows:
        if not (row.get("human_label") or "").strip():
            continue
        key = (row.get("opportunity_id") or "", row.get("component") or "")
        if key in seen:
            raise ValueError(
                f"duplicate labeled row for opportunity_id={key[0]!r} "
                f"component={key[1]!r}: adjudicate to one final label before scoring"
            )
        seen.add(key)
    metadata["rows_in_file"] = str(len(all_rows))
    metadata["example_rows"] = str(len(all_rows) - len(rows))
    return rows, metadata


def _truth(value: str) -> bool:
    token = (value or "").strip().lower()
    if token not in ("fit", "no-fit"):
        raise ValueError(f"label must be fit or no-fit, got {value!r}")
    return token == "fit"


def _metrics(rows: list[dict]) -> dict:
    evaluated = [row for row in rows if (row.get("human_label") or "").strip()]
    truth = [_truth(row["human_label"]) for row in evaluated]
    predicted = [_truth(row.get("predicted_label") or "no-fit") for row in evaluated]
    tp = sum(p and t for p, t in zip(predicted, truth))
    fp = sum(p and not t for p, t in zip(predicted, truth))
    fn = sum(not p and t for p, t in zip(predicted, truth))
    tn = sum(not p and not t for p, t in zip(predicted, truth))
    ordered = sorted(
        zip(evaluated, truth),
        key=lambda pair: (int(pair[0].get("rank") or 10**9), pair[0].get("opportunity_id") or ""),
    )[:10]
    return {
        "n": len(evaluated), "positive": sum(truth), "tp": tp, "fp": fp,
        "fn": fn, "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "p_at_10": sum(item[1] for item in ordered) / len(ordered) if ordered else None,
        "k": len(ordered),
    }


def _fmt(value: object) -> str:
    return "n/a" if value is None else f"{float(value):.3f}"


def build_report(rows: list[dict], metadata: dict[str, str]) -> str:
    rubric = metadata.get("rubric_version") or next(
        (row.get("rubric_version", "") for row in rows if row.get("rubric_version")), "unknown"
    )
    seed = metadata.get("sampler_seed") or next(
        (row.get("sampler_seed", "") for row in rows if row.get("sampler_seed")), "unknown"
    )
    overall = _metrics(rows)
    lines = ["# Evaluation report", "", f"- Rubric version: {rubric}", f"- Sampler seed: {seed}"]
    if "rows_in_file" in metadata:
        lines.append(
            f"- Rows in file: {metadata['rows_in_file']} "
            f"({metadata.get('example_rows', '0')} example excluded, "
            f"{len(rows) - overall['n']} unlabeled, {overall['n']} scored)"
        )
    lines.append("")
    if overall["positive"] == 0:
        lines.extend(["## Result", "", "**Insufficient labels:** the scored rows contain zero positive (`fit`) labels.", ""])
    lines.extend([
        "## Metrics", "",
        "| Scope | N | TP | FP | FN | TN | Precision | Recall | Precision@10 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    scopes = [("Overall", rows)]
    scopes.extend((component, [r for r in rows if r.get("component") == component])
                  for component in sorted({r.get("component", "") for r in rows if r.get("component")}))
    for name, subset in scopes:
        metric = _metrics(subset)
        if metric["positive"] == 0:
            precision = recall = p_at_10 = "insufficient labels"
        else:
            precision, recall, p_at_10 = map(_fmt, (metric["precision"], metric["recall"], metric["p_at_10"]))
        lines.append(
            f"| {name} | {metric['n']} | {metric['tp']} | {metric['fp']} | {metric['fn']} | "
            f"{metric['tn']} | {precision} | {recall} | {p_at_10} (k={metric['k']}) |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    rows, metadata = _read(args.labels)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(build_report(rows, metadata), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
