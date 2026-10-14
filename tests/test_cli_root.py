"""Issue #7: --root must be honored (or loudly rejected) by every command.

Before the fix, top/report/record-win (and draft) accepted --root and
silently read the default root — a user auditing a replay root got numbers
from a different ledger with no warning. These tests drive the real main()
dispatch against temp roots whose ledgers exist nowhere else.
"""
import json
from pathlib import Path

import pytest

from porcupine import cli, config
from porcupine.ledger import Ledger


def _seed_ledger(root: Path, ident: str = "opp-1") -> None:
    ledger = Ledger(config.ledger_path(root))
    ledger.append(
        {
            "record_type": "opportunity",
            "source": "test",
            "id": ident,
            "title": "Rooted opportunity",
            "disposition": "matched",
            "fit": 0.9,
            "ev": 100.0,
            "high_fit": True,
        }
    )


def test_top_honors_root(tmp_path, capsys):
    _seed_ledger(tmp_path)
    assert cli.main(["top", "5", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Rooted opportunity" in out
    assert "showing 1" in out


def test_top_root_before_count(tmp_path, capsys):
    _seed_ledger(tmp_path)
    assert cli.main(["top", "--root", str(tmp_path)]) == 0
    assert "Rooted opportunity" in capsys.readouterr().out


def test_report_honors_root(tmp_path, capsys):
    _seed_ledger(tmp_path)
    assert cli.main(["report", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert str(config.ledger_path(tmp_path)) in out
    assert "ledger rows: 1" in out


def test_record_win_honors_root(tmp_path, capsys):
    assert cli.main(["record-win", "--root", str(tmp_path)]) == 0
    state = json.loads(cli.p_win_path(tmp_path).read_text(encoding="utf-8"))
    assert state["p_win_n"] == 1
    assert "p_win_n=1" in capsys.readouterr().out


def test_draft_honors_root(tmp_path, capsys):
    _seed_ledger(tmp_path)
    assert cli.main(["draft", "opp-1", "--root", str(tmp_path)]) == 0
    assert str(tmp_path) in capsys.readouterr().out


def test_valueless_root_is_an_error_not_a_drop(tmp_path, capsys):
    for argv in (["top", "--root"], ["report", "--root"], ["record-win", "--root"], ["draft", "x", "--root"]):
        assert cli.main(list(argv)) == 2, argv
        assert "--root expects a directory" in capsys.readouterr().err


def test_unknown_arguments_are_loud(tmp_path, capsys):
    assert cli.main(["report", "--bogus"]) == 2
    assert "report takes no arguments" in capsys.readouterr().err
    assert cli.main(["record-win", "extra"]) == 2
    assert "record-win takes no arguments" in capsys.readouterr().err
    assert cli.main(["top", "1", "2"]) == 2
    assert "top takes at most one count" in capsys.readouterr().err


def test_report_high_fit_not_recorded_is_explicit(tmp_path, capsys):
    """A replay's last-run.json has no high_fit_open_matches key. The report
    must state that plainly instead of printing a bare None."""
    _seed_ledger(tmp_path)
    out_dir = config.output_dir(tmp_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "last-run.json").write_text(
        json.dumps({"generated_at": "2026-10-13T00:00:00Z", "feeds": []}),
        encoding="utf-8",
    )
    assert cli.main(["report", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "high-fit not recorded (the last run did not report it)" in out
    assert "high-fit None" not in out


def test_report_high_fit_recorded_still_numeric(tmp_path, capsys):
    _seed_ledger(tmp_path)
    out_dir = config.output_dir(tmp_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "last-run.json").write_text(
        json.dumps(
            {"generated_at": "2026-10-13T00:00:00Z", "high_fit_open_matches": 3, "feeds": []}
        ),
        encoding="utf-8",
    )
    assert cli.main(["report", "--root", str(tmp_path)]) == 0
    assert "high-fit 3" in capsys.readouterr().out
