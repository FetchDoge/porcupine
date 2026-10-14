"""Eval residuals from the fleet evals lane, closed by the Keeper.

1. A non-numeric rank used to crash _metrics with a bare int() ValueError.
   It now fails with the row named.
2. Precision@10 is computed over labeled rows only; when unlabeled rows
   hold top-10 ranks, the report must say the true top-10 is unmeasured.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("eval_score", ROOT / "eval" / "score.py")
score = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(score)


def _row(ident, rank, human="", predicted="no-fit", example=""):
    return {
        "opportunity_id": ident,
        "component": "",
        "rank": rank,
        "human_label": human,
        "predicted_label": predicted,
        "example": example,
    }


def test_non_numeric_rank_fails_with_row_named():
    rows = [_row("opp-9", "1st", human="fit", predicted="fit")]
    with pytest.raises(ValueError, match=r"opp-9.*rank '1st' is not an integer"):
        score._metrics(rows)


def test_missing_rank_sorts_last_not_crashes():
    rows = [
        _row("opp-a", "", human="fit", predicted="fit"),
        _row("opp-b", "1", human="fit", predicted="fit"),
    ]
    metric = score._metrics(rows)
    assert metric["p_at_10"] == 1.0  # both fit; rankless row still counted in k


def test_unlabeled_top_rank_triggers_p_at_10_warning():
    rows = [_row(f"opp-{i}", str(i + 1), human="fit", predicted="fit") for i in range(3)]
    rows.append(_row("opp-unlabeled", "2", human=""))
    report = score.build_report(rows, {})
    assert "Precision@10 covers labeled rows only" in report
    assert "1 unlabeled row(s) carry rank <= 10" in report


def test_fully_labeled_sheet_has_no_warning():
    rows = [_row(f"opp-{i}", str(i + 1), human="fit", predicted="fit") for i in range(3)]
    assert "Warnings" not in score.build_report(rows, {})


def test_example_rows_do_not_trigger_warning():
    rows = [_row("opp-1", "1", human="fit", predicted="fit")]
    rows.append(_row("opp-example", "2", human="", example="true"))
    assert "Warnings" not in score.build_report(rows, {})
