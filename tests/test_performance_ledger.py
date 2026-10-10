"""Ledger batch append, locking, and scan-count instrumentation."""

from __future__ import annotations

import json
import multiprocessing
import threading
from datetime import date
from pathlib import Path

import pytest

from porcupine import config
from porcupine.cli import _record, assemble
from porcupine.ledger import Ledger, key_scan_count, reset_key_scan_count
from porcupine.radar import parse_opportunities_canadabuys_csv

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_RECORD_FIXTURE_TODAY = date(2026, 10, 4)

# Keys `_record` and `unused_note` dereference with subscripts (not optional .get defaults).
_RECORD_PATH_DEREF_KEYS = frozenset(
    {
        "source",
        "id",
        "recorded_at",
        "title",
        "disposition",
        "classification",
        "open",
    }
)

# Committed fingerprint of porcupine.cli.assemble() row keys for
# tests/fixtures/no_funding_row.csv @ _RECORD_FIXTURE_TODAY. Update when assemble() shape changes.
_RECORD_PATH_ROW_KEYS_FIXTURE_JSON = json.dumps(
    sorted(
        [
            "blind_spot_ids",
            "body_bytes_sha256",
            "body_text_sha256",
            "capability_markers",
            "classification",
            "classification_reason",
            "close_at",
            "close_timezone",
            "deadline",
            "deadline_trace",
            "description",
            "detail_url_unknown",
            "disposition",
            "effort",
            "ev",
            "ev_at_wilson_lcb",
            "ev_label",
            "evidence_persistence_warning",
            "fetched_at",
            "acquisition_how",
            "formula",
            "funding",
            "funding_trace",
            "high_fit",
            "high_repos",
            "id",
            "live_fetch",
            "moat_paragraph",
            "open",
            "p_win_lcb",
            "p_win_n",
            "p_win_successes",
            "portfolio_fit",
            "publication_date",
            "raw_keywords_matched",
            "reachability",
            "record_type",
            "recorded_at",
            "reference_number",
            "solicitation_number",
            "source",
            "source_dataset_url",
            "source_format",
            "source_kind",
            "source_name",
            "source_snapshot_meta_ref",
            "source_snapshot_ref",
            "source_status",
            "status_contradiction",
            "title",
            "traces",
            "trl",
            "trl_component",
            "url",
        ]
    )
)


def _parse_fixture_opportunities() -> list[dict]:
    body = (_FIXTURES / "no_funding_row.csv").read_text(encoding="utf-8")
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="canadabuys-open-tenders-csv",
        page_url=config.CANADABUYS_OPEN_TENDERS_CSV_URL,
        today=_RECORD_FIXTURE_TODAY,
    )
    assert stats["valid_rows"] >= 1
    return opps


def _single_production_assembled_row() -> dict:
    """One row through parse → assemble with fixture ids unchanged (for drift fixtures)."""
    return assemble(_parse_fixture_opportunities(), today=_RECORD_FIXTURE_TODAY)[0]


def _assemble_record_path_rows(count: int) -> list[dict]:
    """Production path: fixture CSV → parse_opportunities_canadabuys_csv → assemble."""
    base = _parse_fixture_opportunities()[0]
    opportunities = []
    for index in range(count):
        opp = dict(base)
        opp["id"] = f"perf-record-{index}"
        opportunities.append(opp)
    return assemble(opportunities, today=_RECORD_FIXTURE_TODAY)


def _row(source: str, ident: str, **extra) -> dict:
    base = {
        "record_type": "opportunity",
        "source": source,
        "id": ident,
        "title": "t",
    }
    base.update(extra)
    return base


def test_record_path_row_fixture_matches_production_assembly_keys():
    """Drift control: committed key fingerprint must match live assemble() output."""
    live = _single_production_assembled_row()
    committed_keys = set(json.loads(_RECORD_PATH_ROW_KEYS_FIXTURE_JSON))
    assert committed_keys == set(live.keys()), (
        "assemble() row keys changed; update _RECORD_PATH_ROW_KEYS_FIXTURE_JSON "
        "after verifying _record/unused_note still succeed"
    )
    missing = _RECORD_PATH_DEREF_KEYS - committed_keys
    assert not missing, f"fixture key set missing _record/unused_note derefs: {missing}"


def test_record_path_sample_row_json_covers_deref_fields(tmp_path):
    """Drift control: assemble() row must include every subscripted _record/unused_note field."""
    row = _single_production_assembled_row()
    missing = _RECORD_PATH_DEREF_KEYS - set(row.keys())
    assert not missing, f"assembled row missing _record/unused_note derefs: {missing}"
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    reset_key_scan_count()
    out = _record(ledger, [row])
    assert out["appended"] == 2
    assert out["already_recorded"] == 0
    assert key_scan_count() == 1


def test_append_many_writes_new_rows_in_order(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    rows = [
        _row("s1", "a"),
        _row("s1", "b"),
        _row("s2", "c"),
    ]
    results = ledger.append_many(rows)
    assert [r["written"] for r in results] == [True, True, True]
    saved = ledger.read()
    assert [r["id"] for r in saved] == ["a", "b", "c"]


def test_append_many_duplicate_in_batch_second_exists(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    row = _row("s1", "dup")
    results = ledger.append_many([row, dict(row)])
    assert results[0]["written"] is True
    assert results[1]["written"] is False
    assert results[1]["reason"] == "exists"
    assert len(ledger.read()) == 1


def test_append_many_idempotent_against_existing(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    row = _row("s1", "x")
    assert ledger.append(row)["written"] is True
    results = ledger.append_many([row, _row("s1", "y")])
    assert results[0]["written"] is False
    assert results[1]["written"] is True
    assert len(ledger.read()) == 2


def test_append_unicode_preserved(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    row = _row("s1", "u", title="café — naïve")
    ledger.append(row)
    text = path.read_text(encoding="utf-8")
    assert "café" in text
    assert ledger.read()[0]["title"] == "café — naïve"


def test_bad_ledger_line_skipped_for_keys(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('not json\n{"source":"s","id":"ok","title":"t"}\n', encoding="utf-8")
    ledger = Ledger(path)
    result = ledger.append(_row("s", "new"))
    assert result["written"] is True
    assert len(ledger.read()) == 2


def test_invalid_batch_missing_id_writes_nothing(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    good = _row("s1", "good")
    bad = {"source": "s1", "title": "no id"}
    with pytest.raises(ValueError, match="source and id"):
        ledger.append_many([good, bad])
    assert not path.exists() or path.read_text(encoding="utf-8") == ""


def test_two_ledger_instances_see_fresh_keys(tmp_path):
    path = tmp_path / "ledger.jsonl"
    a = Ledger(path)
    b = Ledger(path)
    assert a.append(_row("s", "1"))["written"] is True
    assert b.append(_row("s", "1"))["written"] is False
    assert b.append(_row("s", "2"))["written"] is True


def test_append_many_single_scan_counter(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    reset_key_scan_count()
    batch = [_row("s", f"id-{i}") for i in range(50)]
    ledger.append_many(batch)
    assert key_scan_count() == 1


def test_append_singleton_single_scan_counter(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    reset_key_scan_count()
    ledger.append(_row("s", "singleton"))
    assert key_scan_count() == 1


def test_record_path_one_scan_via_append_many(tmp_path):
    """_record on production-shaped rows: one locked key scan for the full batch."""
    path = tmp_path / "ledger" / "porcupine.jsonl"
    ledger = Ledger(path)
    rows = _assemble_record_path_rows(10)
    reset_key_scan_count()
    out = _record(ledger, rows)
    assert out["appended"] == 20
    assert out["already_recorded"] == 0
    assert key_scan_count() == 1


def test_append_still_works_singleton(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    first = ledger.append(_row("s", "a"))
    second = ledger.append(_row("s", "a"))
    assert first["written"] and not second["written"]


def _worker_append_many(path_str: str, index: int) -> None:
    ledger = Ledger(path_str)
    ledger.append_many([_row("pool", f"w-{index}")])


def test_concurrent_append_many_workers(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    workers = 8
    threads = [
        threading.Thread(target=_worker_append_many, args=(str(path), i))
        for i in range(workers)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ids = {r["id"] for r in Ledger(path).read()}
    assert ids == {f"w-{i}" for i in range(workers)}


def test_concurrent_process_append_many(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    ctx = multiprocessing.get_context("spawn")
    procs = [
        ctx.Process(target=_worker_append_many, args=(str(path), i))
        for i in range(4)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
        assert p.exitcode == 0
    rows = Ledger(path).read()
    assert len(rows) == 4
    assert len({r["id"] for r in rows}) == 4


def test_append_many_empty_list(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    assert ledger.append_many([]) == []


def test_seen_unchanged_full_read(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append(_row("s", "1"))
    assert ("s", "1") in ledger.seen()
    assert ("s", "2") not in ledger.seen()
