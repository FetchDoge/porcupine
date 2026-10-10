"""Hermetic tests for the offline evaluation harness."""

from __future__ import annotations

import csv
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "source-evidence" / "canadabuys-reference.csv"
FIELDS = [
    "rubric_version", "sampler_seed", "stratum", "rank", "opportunity_id",
    "title", "description", "url", "component", "predicted_label",
    "human_label", "evidence_quote", "adjudication_notes", "example",
]


def _data_rows(path: Path) -> list[dict]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if not line.startswith("#")]
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def test_sampler_is_deterministic_and_covers_reference_strata(tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    command = [
        sys.executable, str(ROOT / "eval" / "sample.py"), "--csv", str(REFERENCE),
        "--n", "12", "--seed", "7", "--out",
    ]
    subprocess.run(command + [str(first)], cwd=ROOT, check=True)
    subprocess.run(command + [str(second)], cwd=ROOT, check=True)
    assert first.read_bytes() == second.read_bytes()
    text = first.read_text(encoding="utf-8")
    assert text.startswith("# sampler_seed=7\n")
    rows = _data_rows(first)
    assert len(rows) == 5 * 6
    assert set(rows[0]) == set(FIELDS)
    assert {row["stratum"] for row in rows} == {
        "displayed-not-matched", "rejected-valid"
    }
    assert {row["component"] for row in rows} == {
        "interlock", "permit", "hermes-refuse", "adversarial-seat",
        "ep-aec-conformance", "exhibit",
    }


def _write_labels(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# sampler_seed=11\n# rubric_version=1.0\n")
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _label(**updates: str) -> dict:
    row = {field: "" for field in FIELDS}
    row.update({
        "rubric_version": "1.0", "sampler_seed": "11", "stratum": "matched",
        "rank": "1", "opportunity_id": "one", "component": "interlock",
        "predicted_label": "fit", "human_label": "fit", "example": "false",
    })
    row.update(updates)
    return row


def test_score_report_counts_metrics_and_excludes_examples(tmp_path):
    labels = tmp_path / "labels.csv"
    report = tmp_path / "report.md"
    _write_labels(labels, [
        _label(),
        _label(opportunity_id="two", rank="2", human_label="no-fit"),
        _label(opportunity_id="three", rank="3", predicted_label="no-fit", human_label="fit"),
        _label(opportunity_id="ignored", example="true"),
    ])
    subprocess.run([
        sys.executable, str(ROOT / "eval" / "score.py"), "--labels", str(labels),
        "--report", str(report),
    ], cwd=ROOT, check=True)
    text = report.read_text(encoding="utf-8")
    assert "Rubric version: 1.0" in text
    assert "Sampler seed: 11" in text
    assert "| Overall | 3 | 1 | 1 | 1 | 0 | 0.500 | 0.500 | 0.667 (k=3) |" in text


def test_score_reports_insufficient_when_no_positive_labels(tmp_path):
    labels = tmp_path / "labels.csv"
    report = tmp_path / "report.md"
    _write_labels(labels, [_label(human_label="no-fit")])
    subprocess.run([
        sys.executable, str(ROOT / "eval" / "score.py"), "--labels", str(labels),
        "--report", str(report),
    ], cwd=ROOT, check=True)
    text = report.read_text(encoding="utf-8").lower()
    assert "insufficient labels" in text
    assert "| overall | 1 | 0 | 1 | 0 | 0 | insufficient labels" in text


def test_example_file_has_five_excluded_rows(tmp_path):
    example = ROOT / "eval" / "labels.example.csv"
    rows = list(csv.DictReader(example.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 5
    assert all(row["example"] == "true" for row in rows)
    report = tmp_path / "report.md"
    subprocess.run([
        sys.executable, str(ROOT / "eval" / "score.py"), "--labels", str(example),
        "--report", str(report),
    ], cwd=ROOT, check=True)
    assert "Insufficient labels" in report.read_text(encoding="utf-8")
