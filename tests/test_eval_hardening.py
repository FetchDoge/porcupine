"""Hardening tests for the eval harness: hand-verified scorer math,
edge-case behavior, and sampler strata traceability.

Every expected number below was computed by hand from the fixture rows
in the same test; nothing is copied from the implementation's output.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "source-evidence" / "canadabuys-reference.csv"
FIXTURES = ROOT / "tests" / "fixtures"
FIELDS = [
    "rubric_version", "sampler_seed", "stratum", "rank", "opportunity_id",
    "title", "description", "url", "component", "predicted_label",
    "human_label", "evidence_quote", "adjudication_notes", "example",
]

_spec = importlib.util.spec_from_file_location("eval_score", ROOT / "eval" / "score.py")
score = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(score)


def _label(**updates: str) -> dict:
    row = {field: "" for field in FIELDS}
    row.update({
        "rubric_version": "1.0", "sampler_seed": "11", "stratum": "matched",
        "rank": "1", "opportunity_id": "one", "component": "interlock",
        "predicted_label": "fit", "human_label": "fit", "example": "false",
    })
    row.update(updates)
    return row


def _write_labels(path: Path, rows: list[dict], header: bool = True) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        if header:
            handle.write("# sampler_seed=11\n# rubric_version=1.0\n")
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _run_score(labels: Path, report: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "eval" / "score.py"),
         "--labels", str(labels), "--report", str(report)],
        cwd=ROOT, capture_output=True, text=True,
    )


def _run_sample(csv_path: Path, n: int, seed: int, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "eval" / "sample.py"), "--csv", str(csv_path),
         "--n", str(n), "--seed", str(seed), "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True,
    )


def _sheet(path: Path) -> tuple[dict, list[dict]]:
    header = {}
    data = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            token = line[1:].strip()
            if "=" in token:
                key, value = token.split("=", 1)
                header[key.strip()] = value.strip()
        else:
            data.append(line)
    return header, list(csv.DictReader(io.StringIO("\n".join(data))))


# ---------------------------------------------------------------- scorer math

# (rank, component, human truth, predicted) — hand-counted below.
_CONFUSION = [
    (1, "interlock", "fit", "fit"),        # TP
    (2, "interlock", "fit", "no-fit"),     # FN
    (3, "interlock", "no-fit", "fit"),     # FP
    (4, "interlock", "fit", "fit"),        # TP
    (5, "interlock", "no-fit", "no-fit"),  # TN
    (6, "interlock", "fit", "no-fit"),     # FN
    (7, "permit", "no-fit", "fit"),        # FP
    (8, "permit", "fit", "fit"),           # TP
    (9, "permit", "no-fit", "no-fit"),     # TN
    (10, "permit", "fit", "no-fit"),       # FN
    (11, "permit", "fit", "fit"),          # TP
    (12, "permit", "no-fit", "no-fit"),    # TN
]
# Overall by hand: TP=4, FP=2, FN=3, TN=3, N=12, positives=7.
# precision = 4/6, recall = 4/7. Top-10 by rank holds fit truths at
# ranks 1,2,4,6,8,10 -> precision@10 = 6/10.


def _confusion_rows() -> list[dict]:
    return [
        _label(rank=str(rank), component=component, opportunity_id=f"opp-{rank}",
               human_label=truth, predicted_label=pred)
        for rank, component, truth, pred in _CONFUSION
    ]


def test_metrics_match_hand_computed_confusion_counts():
    metrics = score._metrics(_confusion_rows())
    assert metrics["n"] == 12
    assert metrics["positive"] == 7
    assert (metrics["tp"], metrics["fp"], metrics["fn"], metrics["tn"]) == (4, 2, 3, 3)
    assert metrics["precision"] == 4 / 6
    assert metrics["recall"] == 4 / 7
    assert metrics["p_at_10"] == 0.6
    assert metrics["k"] == 10


def test_report_lines_match_hand_computed_scopes(tmp_path):
    labels = tmp_path / "labels.csv"
    report = tmp_path / "report.md"
    _write_labels(labels, _confusion_rows())
    result = _run_score(labels, report)
    assert result.returncode == 0, result.stderr
    text = report.read_text(encoding="utf-8")
    assert "| Overall | 12 | 4 | 2 | 3 | 3 | 0.667 | 0.571 | 0.600 (k=10) |" in text
    # interlock by hand: TP=2, FP=1, FN=2, TN=1; P=2/3, R=2/4, P@10=4/6 (k=6)
    assert "| interlock | 6 | 2 | 1 | 2 | 1 | 0.667 | 0.500 | 0.667 (k=6) |" in text
    # permit by hand: TP=2, FP=1, FN=1, TN=2; P=2/3, R=2/3, P@10=3/6 (k=6)
    assert "| permit | 6 | 2 | 1 | 1 | 2 | 0.667 | 0.667 | 0.500 (k=6) |" in text


def test_p_at_10_uses_rank_order_not_file_order():
    # File order is scrambled; fit truths sit at ranks 2 and 11 only.
    # Rank order -> top-10 contains rank 2 alone -> 1/10. File order would
    # wrongly include rank 11 in the first ten rows -> 2/10.
    rows = [_label(rank="11", opportunity_id="r11", human_label="fit")]
    rows.append(_label(rank="", opportunity_id="norank", human_label="fit"))
    for rank in (12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
        rows.append(_label(rank=str(rank), opportunity_id=f"r{rank}",
                           human_label="fit" if rank == 2 else "no-fit",
                           predicted_label="no-fit"))
    metrics = score._metrics(rows)
    # The rankless row sorts last (sentinel), so it cannot enter the top-10.
    assert metrics["k"] == 10
    assert metrics["p_at_10"] == 0.1


def test_p_at_10_denominator_is_labeled_count_below_ten():
    rows = [
        _label(rank="1", opportunity_id="a", human_label="fit"),
        _label(rank="2", opportunity_id="b", human_label="fit"),
        _label(rank="3", opportunity_id="c", human_label="fit"),
        _label(rank="4", opportunity_id="d", human_label="no-fit"),
    ]
    metrics = score._metrics(rows)
    assert metrics["k"] == 4
    assert metrics["p_at_10"] == 0.75


def test_unlabeled_rows_ignored_and_blank_prediction_defaults_no_fit():
    rows = [
        _label(opportunity_id="a", human_label="fit", predicted_label="fit"),
        _label(opportunity_id="b", human_label="fit", predicted_label=""),
        _label(opportunity_id="c", human_label="", predicted_label="fit"),
    ]
    metrics = score._metrics(rows)
    assert metrics["n"] == 2
    assert (metrics["tp"], metrics["fn"]) == (1, 1)
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 0.5


def test_precision_is_na_when_no_positive_predictions(tmp_path):
    labels = tmp_path / "labels.csv"
    report = tmp_path / "report.md"
    _write_labels(labels, [
        _label(opportunity_id="a", human_label="fit", predicted_label="no-fit"),
        _label(opportunity_id="b", rank="2", human_label="no-fit", predicted_label="no-fit"),
    ])
    result = _run_score(labels, report)
    assert result.returncode == 0, result.stderr
    text = report.read_text(encoding="utf-8")
    assert "| Overall | 2 | 0 | 0 | 1 | 1 | n/a | 0.000 | 0.500 (k=2) |" in text


# ------------------------------------------------------------- scorer edges

def test_zero_positive_labels_reports_insufficient_but_keeps_counts(tmp_path):
    labels = tmp_path / "labels.csv"
    report = tmp_path / "report.md"
    _write_labels(labels, [
        _label(opportunity_id="a", human_label="no-fit", predicted_label="fit"),
        _label(opportunity_id="b", rank="2", human_label="no-fit", predicted_label="fit"),
        _label(opportunity_id="c", rank="3", human_label="no-fit", predicted_label="no-fit"),
    ])
    result = _run_score(labels, report)
    assert result.returncode == 0, result.stderr
    text = report.read_text(encoding="utf-8")
    assert "**Insufficient labels:**" in text
    assert "| Overall | 3 | 0 | 2 | 0 | 1 | insufficient labels |" in text


def test_empty_labels_file_reports_insufficient(tmp_path):
    labels = tmp_path / "labels.csv"
    labels.write_bytes(b"")
    report = tmp_path / "report.md"
    result = _run_score(labels, report)
    assert result.returncode == 0, result.stderr
    text = report.read_text(encoding="utf-8")
    assert "Insufficient labels" in text
    assert "Rubric version: unknown" in text
    assert "Sampler seed: unknown" in text
    assert "- Rows in file: 0 (0 example excluded, 0 unlabeled, 0 scored)" in text


def test_header_only_labels_file_reports_insufficient(tmp_path):
    labels = tmp_path / "labels.csv"
    _write_labels(labels, [])
    report = tmp_path / "report.md"
    result = _run_score(labels, report)
    assert result.returncode == 0, result.stderr
    text = report.read_text(encoding="utf-8")
    assert "Insufficient labels" in text
    assert "| Overall | 0 |" in text


def test_example_rows_excluded_regardless_of_case(tmp_path):
    labels = tmp_path / "labels.csv"
    report = tmp_path / "report.md"
    _write_labels(labels, [
        _label(opportunity_id="kept", human_label="fit", predicted_label="fit"),
        _label(opportunity_id="ex1", rank="2", example="true"),
        _label(opportunity_id="ex2", rank="3", example="True"),
        _label(opportunity_id="ex3", rank="4", example=" TRUE "),
    ])
    result = _run_score(labels, report)
    assert result.returncode == 0, result.stderr
    text = report.read_text(encoding="utf-8")
    assert "| Overall | 1 | 1 | 0 | 0 | 0 | 1.000 | 1.000 | 1.000 (k=1) |" in text
    assert "- Rows in file: 4 (3 example excluded, 0 unlabeled, 1 scored)" in text


def test_missing_human_label_column_fails_loudly(tmp_path):
    labels = tmp_path / "labels.csv"
    fields = [f for f in FIELDS if f != "human_label"]
    with labels.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({f: "x" for f in fields})
    result = _run_score(labels, tmp_path / "report.md")
    assert result.returncode != 0
    assert "missing required column" in result.stderr
    assert "human_label" in result.stderr


def test_missing_predicted_label_column_fails_loudly(tmp_path):
    labels = tmp_path / "labels.csv"
    fields = [f for f in FIELDS if f != "predicted_label"]
    with labels.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({f: "x" for f in fields})
    result = _run_score(labels, tmp_path / "report.md")
    assert result.returncode != 0
    assert "missing required column" in result.stderr
    assert "predicted_label" in result.stderr


def test_duplicate_labeled_rows_fail_loudly(tmp_path):
    labels = tmp_path / "labels.csv"
    _write_labels(labels, [_label(), _label()])
    result = _run_score(labels, tmp_path / "report.md")
    assert result.returncode != 0
    assert "duplicate labeled row" in result.stderr
    assert "opportunity_id='one'" in result.stderr


def test_conflicting_duplicate_labels_fail_loudly(tmp_path):
    labels = tmp_path / "labels.csv"
    _write_labels(labels, [_label(), _label(human_label="no-fit")])
    result = _run_score(labels, tmp_path / "report.md")
    assert result.returncode != 0
    assert "duplicate labeled row" in result.stderr


def test_duplicate_rows_with_only_one_labeled_copy_score_once(tmp_path):
    labels = tmp_path / "labels.csv"
    report = tmp_path / "report.md"
    _write_labels(labels, [_label(), _label(human_label="")])
    result = _run_score(labels, report)
    assert result.returncode == 0, result.stderr
    text = report.read_text(encoding="utf-8")
    assert "| Overall | 1 | 1 | 0 | 0 | 0 |" in text


def test_invalid_label_value_fails_loudly(tmp_path):
    labels = tmp_path / "labels.csv"
    _write_labels(labels, [_label(human_label="maybe")])
    result = _run_score(labels, tmp_path / "report.md")
    assert result.returncode != 0
    assert "label must be fit or no-fit" in result.stderr


def test_report_states_rubric_seed_and_row_accounting(tmp_path):
    labels = tmp_path / "labels.csv"
    report = tmp_path / "report.md"
    _write_labels(labels, [
        _label(opportunity_id="a"),
        _label(opportunity_id="b", rank="2"),
        _label(opportunity_id="c", rank="3", human_label="no-fit"),
        _label(opportunity_id="d", rank="4", human_label="no-fit", predicted_label="no-fit"),
        _label(opportunity_id="e", rank="5", human_label=""),
        _label(opportunity_id="f", rank="6", example="true"),
    ])
    result = _run_score(labels, report)
    assert result.returncode == 0, result.stderr
    text = report.read_text(encoding="utf-8")
    assert "- Rubric version: 1.0" in text
    assert "- Sampler seed: 11" in text
    assert "- Rows in file: 6 (1 example excluded, 1 unlabeled, 4 scored)" in text


def test_rubric_and_seed_fallback_to_row_columns(tmp_path):
    labels = tmp_path / "labels.csv"
    report = tmp_path / "report.md"
    _write_labels(labels, [_label(rubric_version="2.5", sampler_seed="99")], header=False)
    result = _run_score(labels, report)
    assert result.returncode == 0, result.stderr
    text = report.read_text(encoding="utf-8")
    assert "- Rubric version: 2.5" in text
    assert "- Sampler seed: 99" in text


# ------------------------------------------------------------ sampler audit

def test_sampler_records_available_strata_counts(tmp_path):
    out = tmp_path / "sheet.csv"
    result = _run_sample(REFERENCE, 500, 7, out)
    assert result.returncode == 0, result.stderr
    header, rows = _sheet(out)
    # Reference capture, counted by hand from the ranked rows: 5 valid
    # opportunities — 3 rejected-valid, 2 displayed-not-matched, 0 matched.
    assert header["strata_available"] == (
        "matched:0,displayed-not-matched:2,rejected-valid:3,all-rows-rejected:0"
    )
    assert header["unavailable_strata"] == "matched,all-rows-rejected"
    assert {row["stratum"] for row in rows} == {"displayed-not-matched", "rejected-valid"}


def test_sampler_starved_stratum_leaves_a_trace(tmp_path):
    out = tmp_path / "sheet.csv"
    result = _run_sample(REFERENCE, 1, 7, out)
    assert result.returncode == 0, result.stderr
    header, rows = _sheet(out)
    # Budget 1: round-robin reaches displayed-not-matched first; the
    # rejected-valid stratum (3 available) is unsampled but must be named
    # both as unavailable and with its available count.
    assert {row["stratum"] for row in rows} == {"displayed-not-matched"}
    assert "rejected-valid" in header["unavailable_strata"]
    assert "rejected-valid:3" in header["strata_available"]


def test_sampler_all_rows_rejected_stratum(tmp_path):
    out = tmp_path / "sheet.csv"
    result = _run_sample(FIXTURES / "no_funding_row.csv", 12, 3, out)
    assert result.returncode == 0, result.stderr
    header, rows = _sheet(out)
    assert len(rows) == 6  # one opportunity x six components
    assert {row["stratum"] for row in rows} == {"all-rows-rejected"}
    assert header["strata_available"] == (
        "matched:0,displayed-not-matched:0,rejected-valid:0,all-rows-rejected:1"
    )
    assert header["unavailable_strata"] == "matched,displayed-not-matched,rejected-valid"


def test_sampler_seed_recorded_in_header_and_every_row(tmp_path):
    out = tmp_path / "sheet.csv"
    result = _run_sample(REFERENCE, 12, 42, out)
    assert result.returncode == 0, result.stderr
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# sampler_seed=42\n")
    _, rows = _sheet(out)
    assert rows
    assert all(row["sampler_seed"] == "42" for row in rows)
    assert all(row["rubric_version"] == "1.0" for row in rows)


def test_sampler_empty_valid_capture_records_all_strata_unavailable(tmp_path):
    out = tmp_path / "sheet.csv"
    result = _run_sample(FIXTURES / "schema_valid_empty.csv", 12, 3, out)
    assert result.returncode == 0, result.stderr
    header, rows = _sheet(out)
    assert rows == []
    assert header["parse_outcome"].startswith("empty_valid")
    assert header["unavailable_strata"] == (
        "matched,displayed-not-matched,rejected-valid,all-rows-rejected"
    )
    assert header["strata_available"] == (
        "matched:0,displayed-not-matched:0,rejected-valid:0,all-rows-rejected:0"
    )


def test_sampler_parse_rejected_rows_leave_a_trace(tmp_path):
    out = tmp_path / "sheet.csv"
    result = _run_sample(FIXTURES / "all_rows_rejected.csv", 12, 3, out)
    assert result.returncode == 0, result.stderr
    header, rows = _sheet(out)
    # The fixture's rows die at parse time, so no stratum can form; the
    # header stats line is the trace that they existed and were rejected.
    assert rows == []
    parts = header["parse_outcome"].split(";")
    assert parts[0] == "partial"
    stats = dict(part.split("=", 1) for part in parts[1:])
    assert stats["valid_rows"] == "0"
    assert int(stats["rejected_rows"]) >= 1
