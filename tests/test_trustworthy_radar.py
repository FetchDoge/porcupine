"""Trustworthy radar increment tests. No network."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from porcupine.cli import (
    _draft_open,
    apply_display_shortlist,
    assemble,
    cmd_draft,
    per_source_run_counts,
)
from porcupine.radar import (
    _sha256_text,
    cache_file,
    fetch_url_with_meta,
    match_capability,
    match_keywords,
    parse_deadline,
    parse_opportunities_canadabuys_csv,
    persist_source_snapshot,
    read_cache,
    scout,
    scout_source_body,
    write_cache,
)
from porcupine import config

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE_CSV = Path(__file__).resolve().parents[1] / "source-evidence" / "canadabuys-reference.csv"
RIG_FULL_CSV = Path(
    "/Users/user/.hermes/profiles/rig/cache/scratch/porcupine-source-discovery/open-tenders.csv"
)


def _csv_data_row_count(path: Path) -> int:
    text = path.read_text(encoding="utf-8-sig")
    return len(list(csv.DictReader(io.StringIO(text))))


def _header_line() -> str:
    return ",".join(config.CANADABUYS_CSV_REQUIRED_HEADERS)


def _cb_row(
    title: str,
    reference: str,
    *,
    solicitation: str = "W1",
    publication: str = "2026-01-01",
    close: str = "2027-01-01T12:00:00",
    status: str = "Open",
    notice_url: str = "",
    description: str = "",
    **extra: str,
) -> dict[str, str]:
    row = {
        "title-titre-eng": title,
        "referenceNumber-numeroReference": reference,
        "solicitationNumber-numeroSollicitation": solicitation,
        "publicationDate-datePublication": publication,
        "tenderClosingDate-appelOffresDateCloture": close,
        "tenderStatus-appelOffresStatut-eng": status,
        "noticeURL-URLavis-eng": notice_url,
        "tenderDescription-descriptionAppelOffres-eng": description,
    }
    row.update(extra)
    return row


def _serialize_canadabuys_csv(
    rows: list[dict[str, str]],
    *,
    extra_fieldnames: tuple[str, ...] = (),
) -> str:
    """RFC-style CSV so commas and quotes in descriptions stay aligned."""
    fieldnames = list(config.CANADABUYS_CSV_REQUIRED_HEADERS) + list(extra_fieldnames)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in fieldnames})
    return buf.getvalue()


def _csv_with_unnamed_trailing_value(row: dict[str, str], trailing: str) -> str:
    """One more physical field than header (DictReader ``None`` key)."""
    fieldnames = list(config.CANADABUYS_CSV_REQUIRED_HEADERS)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(fieldnames)
    writer.writerow([row.get(name, "") for name in fieldnames] + [trailing])
    return buf.getvalue()


def test_issued_by_does_not_set_deadline():
    assert parse_deadline("Notice issued by 22 October 2027")[0] is None
    assert parse_deadline("Applications are due by 22 October 2026.")[0] == "2026-10-22"
    assert parse_deadline("Proposals received by 15 March 2027.")[0] == "2027-03-15"


def test_reference_fixture_rf_data_fusion_fields():
    body = REFERENCE_CSV.read_text(encoding="utf-8-sig")
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="canadabuys-open-tenders-csv",
        page_url=config.CANADABUYS_OPEN_TENDERS_CSV_URL,
        source_kind="tender",
        dataset_url=config.CANADABUYS_OPEN_TENDERS_CSV_URL,
        today=date(2026, 10, 4),
    )
    assert stats["parse_outcome"] == "ok"
    assert stats["valid_rows"] >= 2
    assert stats["unique_rows"] == len(opps)
    fusion = next(o for o in opps if o.get("reference_number") == "cb-846-73690703")
    assert fusion["solicitation_number"] == "W7714-248676/017"
    assert fusion["close_at"] == "2026-10-20T14:00:00"
    assert fusion["deadline"] == "2026-10-20"
    assert fusion["url"] == ""
    assert fusion["source_dataset_url"] == config.CANADABUYS_OPEN_TENDERS_CSV_URL
    assert fusion["detail_url_unknown"] is True
    assert "Command and Control" in fusion["title"]
    row = assemble([fusion], today=date(2026, 10, 4))[0]
    assert row["funding"] == 250_000.0
    assert "250" in (row.get("funding_trace") or "")


def test_missing_funding_stays_unknown_on_synthetic_row():
    body = (FIXTURES / "no_funding_row.csv").read_text(encoding="utf-8")
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="canadabuys-open-tenders-csv",
        page_url=config.CANADABUYS_OPEN_TENDERS_CSV_URL,
        today=date(2026, 10, 4),
    )
    assert stats["valid_rows"] == 1
    row = assemble(opps, today=date(2026, 10, 4))[0]
    assert row["funding"] is None


def test_keywordless_csv_row_intake_and_out_of_lens():
    # Fixture-only: description must not contain lens/capability tokens (negation is not modeled).
    description = (
        "Routine custodial work at federal office sites; "
        "cleaning floors and restocking paper supplies."
    )
    assert match_keywords(description) == []
    assert match_capability(description) == []
    body = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Office cleaning services nationwide",
                "cb-999-00000001",
                solicitation="W0000-000001/001",
                publication="2026-02-01",
                close="2026-12-15T17:00:00",
                description=description,
            )
        ]
    )
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="canadabuys-open-tenders-csv",
        page_url=config.CANADABUYS_OPEN_TENDERS_CSV_URL,
        today=date(2026, 10, 4),
    )
    assert stats["valid_rows"] == 1
    assert stats["lens_matches"] == 0
    row = assemble(opps, today=date(2026, 10, 4))[0]
    assert row["classification"] == "out-of-lens"


def test_out_of_lens_row_accounted_not_silent():
    body = REFERENCE_CSV.read_text(encoding="utf-8-sig")
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="canadabuys-open-tenders-csv",
        page_url=config.CANADABUYS_OPEN_TENDERS_CSV_URL,
        today=date(2026, 10, 4),
    )
    assert stats["valid_rows"] > stats["lens_matches"]
    rows = assemble(opps, today=date(2026, 10, 4))
    rejected = [r for r in rows if r["classification"] == "out-of-lens"]
    assert rejected, "keyword-less intake rows must appear as out-of-lens, not vanish"


def test_open_status_past_close_contradiction():
    body = REFERENCE_CSV.read_text(encoding="utf-8-sig")
    opps, _stats = parse_opportunities_canadabuys_csv(
        body,
        source="canadabuys-open-tenders-csv",
        page_url=config.CANADABUYS_OPEN_TENDERS_CSV_URL,
        today=date(2026, 10, 4),
    )
    stale = next(o for o in opps if o.get("reference_number") == "cb-495-14096276")
    assert stale["source_status"] == "Open"
    assert stale["status_contradiction"] == "publisher_open_but_close_date_past"
    rows = assemble([stale], today=date(2026, 10, 4))
    assert rows[0]["open"] is False


def test_closed_status_future_deadline_not_actionable():
    body = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Future close but publisher closed",
                "cb-closed-1",
                close="2027-06-01T12:00:00",
                status="Closed",
                description=(
                    "Explainable AI audit trail for command systems with verification "
                    "and assurance keywords."
                ),
            )
        ]
    )
    opps, _stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
        today=date(2026, 10, 4),
    )
    row = assemble(opps, today=date(2026, 10, 4))[0]
    assert row["open"] is False


def test_same_day_close_timezone_unknown_unresolved():
    today = date(2026, 10, 4)
    body = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Same-day close unknown tz",
                "cb-same-1",
                close=f"{today.isoformat()}T15:00:00",
                description=(
                    "Trust and assurance verification for autonomous systems with audit "
                    "and fail-closed language."
                ),
            )
        ]
    )
    opps, _stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
        today=today,
    )
    row = assemble(opps, today=today)[0]
    assert row["open"] is None


def test_schema_drift_not_empty_valid():
    body = (FIXTURES / "schema_drift.csv").read_text(encoding="utf-8")
    _opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
    )
    assert stats["parse_outcome"] == "schema_drift"
    assert stats["missing_headers"]


def test_empty_valid_csv_distinct_from_schema_drift():
    body = (FIXTURES / "schema_valid_empty.csv").read_text(encoding="utf-8")
    _opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
    )
    assert stats["parse_outcome"] == "empty_valid"
    assert stats["raw_rows"] == 0


def test_completely_empty_body_not_empty_valid():
    _opps, stats = parse_opportunities_canadabuys_csv(
        "   ",
        source="t",
        page_url="https://example.test/c.csv",
    )
    assert stats["parse_outcome"] == "unsupported"


def test_all_malformed_rows_not_empty_valid():
    body = (FIXTURES / "all_rows_rejected.csv").read_text(encoding="utf-8")
    _opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
    )
    assert stats["raw_rows"] > 0
    assert stats["valid_rows"] == 0
    assert stats["parse_outcome"] == "partial"


def test_html_error_body_not_parsed_as_csv_ok():
    source = config.SOURCES[0]
    opps, feed = scout_source_body("<html><body>error</body></html>", source)
    assert opps == []
    assert feed["parse_outcome"] == "schema_drift"


def test_replay_metadata_offline():
    source = config.SOURCES[0]
    body = (FIXTURES / "schema_valid_empty.csv").read_text(encoding="utf-8")
    _opps, feed = scout_source_body(body, source, offline_replay=True)
    assert feed["how"] == "replay"
    assert feed.get("transport_hardening") == "unresolved"
    assert feed.get("live_fetch") is False
    assert feed.get("fetched_at") == "unknown"


def test_provenance_fields_survive_assemble():
    body = REFERENCE_CSV.read_text(encoding="utf-8-sig")
    opps, _stats = parse_opportunities_canadabuys_csv(
        body,
        source="canadabuys-open-tenders-csv",
        page_url=config.CANADABUYS_OPEN_TENDERS_CSV_URL,
        today=date(2026, 10, 4),
    )
    fusion = next(o for o in opps if o.get("reference_number") == "cb-846-73690703")
    row = assemble([fusion], today=date(2026, 10, 4))[0]
    assert row["reference_number"] == "cb-846-73690703"
    assert row["source_status"] == "Open"
    assert row["close_at"] == "2026-10-20T14:00:00"
    assert row["source_dataset_url"] == config.CANADABUYS_OPEN_TENDERS_CSV_URL


def test_shortlist_applied_after_rank_not_during_parse():
    rows = [
        _cb_row(
            f"Filler procurement {n}",
            f"cb-fill-{n:04d}",
            solicitation=f"W{n:04d}",
            description=(
                f"Generic services without lens keywords for row {n} "
                "in the synthetic intake sweep."
            ),
        )
        for n in range(1, 81)
    ]
    rows.append(
        _cb_row(
            "RF Data Fusion for Command and Control",
            "cb-846-73690703",
            solicitation="W7714-248676/017",
            publication="2026-09-10",
            close="2026-10-20T14:00:00",
            description=(
                "Sensor fusion and command and control with assurance and verification "
                "for IDEaS component 1a maximum funding up to $250,000 CAD for six months."
            ),
        )
    )
    body = _serialize_canadabuys_csv(rows)
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="canadabuys-open-tenders-csv",
        page_url=config.CANADABUYS_OPEN_TENDERS_CSV_URL,
        today=date(2026, 10, 4),
    )
    assert stats["raw_rows"] == 81
    assert stats["valid_rows"] == 81
    assert any(o.get("reference_number") == "cb-846-73690703" for o in opps)
    ranked = assemble(opps, today=date(2026, 10, 4))
    shown, meta = apply_display_shortlist(ranked, cap=40)
    assert meta["candidate_rows"] == 81
    assert meta["displayed_rows"] == 40
    assert meta["shortlist_capped"] is True
    assert any(r.get("reference_number") == "cb-846-73690703" for r in shown)


def test_row_safety_cap_partial_rf_lost_only_when_beyond_cap():
    rows = [
        _cb_row(
            f"Filler {n}",
            f"cb-cap-{n:04d}",
            solicitation=f"W{n}",
            description=f"Enough description text for filler row number {n} without special keywords.",
        )
        for n in range(1, 6)
    ]
    rows.append(
        _cb_row(
            "RF tail",
            "cb-846-73690703",
            solicitation="W7714-248676/017",
            publication="2026-09-10",
            close="2026-10-20T14:00:00",
            description="Command and control sensor fusion assurance verification audit.",
        )
    )
    body = _serialize_canadabuys_csv(rows)
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
        max_rows=5,
        today=date(2026, 10, 4),
    )
    assert stats["rows_capped"] is True
    assert stats["parse_outcome"] == "partial"
    assert not any(o.get("reference_number") == "cb-846-73690703" for o in opps)


def test_full_capture_replay_row_counts_when_present():
    if not RIG_FULL_CSV.is_file():
        return
    expected = _csv_data_row_count(RIG_FULL_CSV)
    body = RIG_FULL_CSV.read_text(encoding="utf-8-sig")
    _opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="canadabuys-open-tenders-csv",
        page_url=config.CANADABUYS_OPEN_TENDERS_CSV_URL,
        today=date(2026, 10, 4),
    )
    assert stats["raw_rows"] == expected
    assert stats["valid_rows"] == expected
    assert any(
        o.get("reference_number") == "cb-846-73690703"
        for o in _opps
    )


def test_cache_hit_preserves_fetched_at_not_wall_time(tmp_path, monkeypatch):
    import porcupine.radar as radar_mod

    url = "https://example.test/csv"
    write_cache(tmp_path, url, "cached-body")
    path = cache_file(tmp_path, url)
    payload = json.loads(path.read_text(encoding="utf-8"))
    stamp = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0).isoformat()
    payload["fetched_at"] = stamp
    path.write_text(json.dumps(payload), encoding="utf-8")

    meta = fetch_url_with_meta(url, tmp_path)
    assert meta["how"] == "cache"
    assert meta.get("fetched_at") == stamp


def test_stale_cache_refetch_on_network_failure_distinct(tmp_path, monkeypatch):
    import porcupine.radar as radar_mod

    url = "https://example.test/feed"
    write_cache(tmp_path, url, "OLD")
    path = cache_file(tmp_path, url)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["fetched_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=config.CACHE_TTL_SECONDS + 5)
    ).isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert read_cache(tmp_path, url) is None

    class _Headers:
        def get_content_charset(self, failobj=None):
            return "utf-8"

    class _Resp:
        headers = _Headers()

        def read(self, _n):
            return b"NEW BODY"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(radar_mod, "urlopen", lambda *a, **k: _Resp())
    source = {"id": "feed", "name": "Feed", "kind": "tender", "url": url}
    result = scout([source], cache_directory=tmp_path, sleeper=lambda _s: None)
    assert result["feeds"][0]["how"] == "fetched"


def test_truncation_flag_on_oversized_read(tmp_path):
    from porcupine import radar as radar_mod

    class FakeResp:
        headers = {"Content-Length": "9999"}

        def read(self, n):
            return b"x" * (n + 1)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    original = radar_mod.urlopen
    radar_mod.urlopen = lambda *a, **k: FakeResp()
    try:
        result = fetch_url_with_meta(
            "https://example.test/big.csv",
            tmp_path,
            max_bytes=100,
        )
    finally:
        radar_mod.urlopen = original
    assert result["truncated"] is True
    assert result["how"] == "fetched"
    cache_files = list(tmp_path.glob("*.json"))
    assert cache_files == [], "truncated bodies must not be cached"


def test_automatic_draft_prefers_matched_assurance_over_open_construction(tmp_path):
    body = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Clowes Weir Reconstruction civil works",
                "cb-construct-1",
                close="2027-12-01T12:00:00",
                description=(
                    "Civil infrastructure reconstruction concrete pour machine learning "
                    "scheduling for project analytics. Total contract value $45,000,000 CAD."
                ),
            ),
            _cb_row(
                "Trust assurance verification IDEaS component",
                "cb-match-1",
                solicitation="W2",
                close="2027-06-01T12:00:00",
                description=(
                    "Explainable AI audit trail for command systems with verification "
                    "and assurance keywords. Maximum funding up to $250,000 CAD for 1a."
                ),
            ),
        ]
    )
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="canadabuys-open-tenders-csv",
        page_url=config.CANADABUYS_OPEN_TENDERS_CSV_URL,
        today=date(2026, 10, 4),
    )
    assert stats["valid_rows"] == 2
    assert {o["id"] for o in opps} == {"cb-construct-1", "cb-match-1"}
    ranked = assemble(opps, today=date(2026, 10, 4))
    construct = next(r for r in ranked if r["id"] == "cb-construct-1")
    matched = next(r for r in ranked if r["id"] == "cb-match-1")
    assert construct["open"] is True
    assert construct["disposition"] != "matched"
    assert matched["disposition"] == "matched"
    assert matched["open"] is True
    draft_path = _draft_open(ranked, tmp_path)
    assert draft_path is not None
    assert "cb-match-1" in draft_path
    assert "Clowes" not in Path(draft_path).read_text(encoding="utf-8")


def test_no_automatic_draft_when_zero_matched_but_open_rows_exist(tmp_path):
    body = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Clowes Weir Reconstruction only",
                "cb-construct-2",
                close="2027-12-01T12:00:00",
                description=(
                    "Civil infrastructure reconstruction concrete pour machine learning "
                    "scheduling for project analytics. Total contract value $45,000,000 CAD."
                ),
            )
        ]
    )
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
        today=date(2026, 10, 4),
    )
    assert stats["valid_rows"] == 1
    ranked = assemble(opps, today=date(2026, 10, 4))
    assert all(r.get("disposition") != "matched" for r in ranked)
    assert _draft_open(ranked, tmp_path) is None
    assert (tmp_path / "NO-VERIFIED-MATCH-DRAFT.md").is_file()


def test_explicit_draft_command_still_available(tmp_path):
    body = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Clowes exploratory only",
                "cb-construct-3",
                close="2027-12-01T12:00:00",
                description=(
                    "Civil infrastructure reconstruction concrete pour machine learning "
                    "scheduling."
                ),
            )
        ]
    )
    opps, _stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
        today=date(2026, 10, 4),
    )
    ranked = assemble(opps, today=date(2026, 10, 4))
    from porcupine.ledger import Ledger

    ledger = Ledger(tmp_path / "ledger" / "porcupine.jsonl")
    for row in ranked:
        ledger.append(row)
    import porcupine.config as cfg

    original = cfg.workspace_root
    cfg.workspace_root = lambda: tmp_path
    try:
        rc = cmd_draft(ranked[0]["id"], root=tmp_path)
    finally:
        cfg.workspace_root = original
    assert rc == 0
    assert list((tmp_path / "output" / "drafts").glob("*.md"))


def test_per_feed_counts_not_cloned_across_two_csv_sources():
    body_a = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Assurance row A",
                "cb-a-1",
                description=(
                    "Trust assurance verification audit fail-closed for autonomous systems."
                ),
            )
        ]
    )
    body_b = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Assurance row B1",
                "cb-b-1",
                solicitation="W2",
                description="Trust assurance verification audit.",
            ),
            _cb_row(
                "Assurance row B2",
                "cb-b-2",
                solicitation="W3",
                description="Explainable certification attestation for command systems.",
            ),
        ]
    )
    source_a = {
        "id": "feed-a",
        "name": "A",
        "kind": "tender",
        "format": "canadabuys_csv",
        "url": "https://example.test/a.csv",
    }
    source_b = {
        "id": "feed-b",
        "name": "B",
        "kind": "tender",
        "format": "canadabuys_csv",
        "url": "https://example.test/b.csv",
    }
    opps_a, feed_a = scout_source_body(body_a, source_a, offline_replay=True)
    opps_b, feed_b = scout_source_body(body_b, source_b, offline_replay=True)
    assert feed_a["raw_rows"] == 1
    assert feed_b["raw_rows"] == 2
    ranked = assemble(opps_a + opps_b, today=date(2026, 10, 4))
    meta_a = per_source_run_counts(ranked, "feed-a")
    meta_b = per_source_run_counts(ranked, "feed-b")
    assert meta_a["candidate_rows"] == 1
    assert meta_b["candidate_rows"] == 2
    assert meta_a["candidate_rows"] != meta_b["candidate_rows"]
    assert meta_a["matched_rows"] >= 1
    assert meta_b["matched_rows"] >= 1


def test_oversized_description_field_rejected_not_silently_truncated():
    huge = "x" * (config.CSV_MAX_FIELD_CHARS + 1)
    body = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Title ok",
                "cb-big-1",
                description=f"Short lead-in {huge}",
            )
        ]
    )
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
        today=date(2026, 10, 4),
    )
    assert opps == []
    assert stats["valid_rows"] == 0
    assert stats["rejection_reasons"].get("field_overflow:description") == 1


def test_unknown_publisher_status_not_confirmed_open():
    body = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Future close unknown status",
                "cb-unk-1",
                close="2027-06-01T12:00:00",
                status="",
                description=(
                    "Trust assurance verification audit fail-closed for autonomous systems."
                ),
            )
        ]
    )
    opps, _stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
        today=date(2026, 10, 4),
    )
    row = assemble(opps, today=date(2026, 10, 4))[0]
    assert row["source_status"] == ""
    assert row["open"] is None


def test_invalid_close_date_not_actionable():
    body = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Bad close field",
                "cb-bad-date",
                close="not-a-valid-date",
                description=(
                    "Trust assurance verification audit fail-closed for autonomous systems."
                ),
            )
        ]
    )
    opps, _stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
        today=date(2026, 10, 4),
    )
    row = assemble(opps, today=date(2026, 10, 4))[0]
    assert row["deadline"] is None
    assert row["open"] is False


def test_malformed_csv_row_does_not_crash_whole_parse():
    body = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Good row",
                "cb-good-1",
                solicitation="W2",
                description=(
                    "Trust assurance verification audit fail-closed for autonomous systems."
                ),
            )
        ]
    )
    # Second physical record: unterminated quote; must not yield a healthy parse outcome.
    body += '"Unclosed quote row,cb-bad-1,W1,2026-01-01,2027-01-01T12:00:00,Open,,broken\n'
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
        today=date(2026, 10, 4),
    )
    assert stats["raw_rows"] >= 1
    assert stats["valid_rows"] == 1
    assert any(o.get("reference_number") == "cb-good-1" for o in opps)
    assert stats.get("csv_parse_errors", 0) >= 1
    assert stats["rejected_rows"] >= 1
    assert stats["parse_outcome"] == "partial"
    assert stats.get("source_incomplete") is True


def test_extra_named_csv_column_compatible_with_official_shape():
    """Official export has many named columns beyond the required subset."""
    body = _serialize_canadabuys_csv(
        [
            _cb_row(
                "Extra col row",
                "cb-extra-1",
                description=(
                    "Trust assurance verification audit fail-closed for autonomous systems."
                ),
                extraColumn="publisher-metadata-surprise",
            )
        ],
        extra_fieldnames=("extraColumn",),
    )
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
        today=date(2026, 10, 4),
    )
    assert stats["valid_rows"] == 1
    assert len(opps) == 1
    assert opps[0]["reference_number"] == "cb-extra-1"


def test_extra_unnamed_csv_value_rejected_not_valid_row():
    """Premise fix: reject only when a physical field has no header (DictReader None key)."""
    row = _cb_row(
        "Trailing field row",
        "cb-extra-2",
        description="Trust assurance verification audit fail-closed.",
    )
    body = _csv_with_unnamed_trailing_value(row, "surprise")
    opps, stats = parse_opportunities_canadabuys_csv(
        body,
        source="t",
        page_url="https://example.test/c.csv",
        today=date(2026, 10, 4),
    )
    assert opps == []
    assert stats["rejection_reasons"].get("extra_columns") == 1


def _assurance_csv_body(reference: str = "cb-prov-1") -> str:
    return _serialize_canadabuys_csv(
        [
            _cb_row(
                "Trust assurance verification audit",
                reference,
                description=(
                    "Explainable AI audit trail for command systems with verification "
                    "and assurance keywords."
                ),
            )
        ]
    )


def test_scout_mocked_fetch_provenance_in_assembled_and_ledger(tmp_path, monkeypatch):
    import porcupine.radar as radar_mod
    from porcupine.ledger import Ledger

    body = _assurance_csv_body("cb-live-prov")
    url = "https://example.test/live-provenance.csv"
    source = {
        "id": "prov-live",
        "name": "Prov Live",
        "kind": "tender",
        "format": "canadabuys_csv",
        "url": url,
    }

    class FakeResp:
        headers = {"Content-Type": "text/csv; charset=utf-8"}

        def read(self, _n):
            return body.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(radar_mod, "urlopen", lambda *a, **k: FakeResp())
    result = scout(
        [source],
        cache_directory=tmp_path / "cache",
        snapshot_root=tmp_path,
        sleeper=lambda _s: None,
    )
    feed = result["feeds"][0]
    assert feed["how"] == "fetched"
    assert feed.get("live_fetch") is True
    assert feed.get("body_bytes_sha256")
    assert feed.get("body_text_sha256") == _sha256_text(body)
    opp = result["opportunities"][0]
    assert opp["acquisition_how"] == "fetched"
    assert opp["body_text_sha256"] == feed["body_text_sha256"]
    row = assemble([opp], today=date(2026, 10, 4), root=tmp_path)[0]
    assert row["fetched_at"] == opp["fetched_at"]
    assert row["body_bytes_sha256"] == opp["body_bytes_sha256"]
    assert row["source_snapshot_ref"]
    ledger = Ledger(tmp_path / "ledger" / "porcupine.jsonl")
    ledger.append(row)
    saved = [r for r in ledger.read() if r.get("id") == opp["id"]][0]
    assert saved["body_text_sha256"] == row["body_text_sha256"]
    assert saved["fetched_at"] == row["fetched_at"]


def test_replay_provenance_honest_and_snapshot(tmp_path):
    source = dict(config.SOURCES[0])
    body = _assurance_csv_body("cb-replay-prov")
    opps, feed = scout_source_body(
        body, source, offline_replay=True, snapshot_root=tmp_path
    )
    assert feed["how"] == "replay"
    assert feed["live_fetch"] is False
    assert feed["fetched_at"] == "unknown"
    assert feed.get("body_bytes_sha256") == ""
    row = assemble(opps, today=date(2026, 10, 4))[0]
    assert row["live_fetch"] is False
    assert row["fetched_at"] == "unknown"
    assert row["acquisition_how"] == "replay"
    ref = row["source_snapshot_ref"]
    assert ref.startswith("source-snapshots/")
    snap_text = (tmp_path / ref).read_bytes().decode("utf-8")
    assert _sha256_text(snap_text) == row["body_text_sha256"]
    meta = json.loads((tmp_path / row["source_snapshot_meta_ref"]).read_text(encoding="utf-8"))
    assert meta["offline"] is True
    assert meta["acquired_at"] == "unknown"
    assert "identity_not_authenticity" in meta


def test_identical_body_reuses_one_snapshot_file(tmp_path):
    source = dict(config.SOURCES[0])
    body = _assurance_csv_body("cb-dedupe")
    scout_source_body(body, source, offline_replay=True, snapshot_root=tmp_path)
    scout_source_body(body, source, offline_replay=True, snapshot_root=tmp_path)
    txt_files = list((tmp_path / "source-snapshots").glob("*.txt"))
    assert len(txt_files) == 1


def test_snapshot_persistence_failure_surfaces_warning(tmp_path, monkeypatch):
    import porcupine.radar as radar_mod

    def _fail_mkdir(*_args, **_kwargs):
        raise OSError(13, "permission denied")

    monkeypatch.setattr(radar_mod.Path, "mkdir", _fail_mkdir)
    stub_body = "title,ref\n"
    acquisition = {
        "body_text_sha256": _sha256_text(stub_body),
        "fetched_at": "unknown",
        "how": "replay",
        "live_fetch": False,
        "offline": True,
        "source_id": "t",
        "source_url": "https://example.test/x.csv",
        "parse_outcome": "ok",
    }
    result = persist_source_snapshot(tmp_path, stub_body, acquisition)
    assert not result["source_snapshot_ref"]
    assert "evidence persistence failed" in result["evidence_persistence_warning"]


def test_two_sources_do_not_share_provenance(tmp_path):
    body_a = _assurance_csv_body("cb-src-a")
    body_b = _assurance_csv_body("cb-src-b")
    source_a = {
        "id": "feed-a",
        "name": "A",
        "kind": "tender",
        "format": "canadabuys_csv",
        "url": "https://example.test/a.csv",
    }
    source_b = {
        "id": "feed-b",
        "name": "B",
        "kind": "tender",
        "format": "canadabuys_csv",
        "url": "https://example.test/b.csv",
    }
    opps_a, _fa = scout_source_body(body_a, source_a, offline_replay=True, snapshot_root=tmp_path)
    opps_b, _fb = scout_source_body(body_b, source_b, offline_replay=True, snapshot_root=tmp_path)
    assert opps_a[0]["body_text_sha256"] != opps_b[0]["body_text_sha256"]
    assert opps_a[0]["source_snapshot_ref"] != opps_b[0]["source_snapshot_ref"]
    rows = assemble(opps_a + opps_b, today=date(2026, 10, 4))
    by_id = {r["id"]: r for r in rows}
    assert by_id[opps_a[0]["id"]]["body_text_sha256"] == opps_a[0]["body_text_sha256"]
    assert by_id[opps_b[0]["id"]]["body_text_sha256"] == opps_b[0]["body_text_sha256"]


def test_crlf_vs_lf_distinct_body_text_hashes():
    lf = "header\nrow\n"
    crlf = "header\r\nrow\r\n"
    assert _sha256_text(lf) != _sha256_text(crlf)


def test_same_identical_body_two_sources_share_body_ref_distinct_meta(tmp_path):
    body = _assurance_csv_body("cb-shared-body")
    source_a = {
        "id": "feed-a",
        "name": "A",
        "kind": "tender",
        "format": "canadabuys_csv",
        "url": "https://example.test/a.csv",
    }
    source_b = {
        "id": "feed-b",
        "name": "B",
        "kind": "tender",
        "format": "canadabuys_csv",
        "url": "https://example.test/b.csv",
    }
    opps_a, _fa = scout_source_body(body, source_a, offline_replay=True, snapshot_root=tmp_path)
    opps_b, _fb = scout_source_body(body, source_b, offline_replay=True, snapshot_root=tmp_path)
    assert opps_a[0]["source_snapshot_ref"] == opps_b[0]["source_snapshot_ref"]
    assert opps_a[0]["source_snapshot_meta_ref"] != opps_b[0]["source_snapshot_meta_ref"]
    meta_a = json.loads(
        (tmp_path / opps_a[0]["source_snapshot_meta_ref"]).read_text(encoding="utf-8")
    )
    meta_b = json.loads(
        (tmp_path / opps_b[0]["source_snapshot_meta_ref"]).read_text(encoding="utf-8")
    )
    assert meta_a["source_id"] == "feed-a"
    assert meta_b["source_id"] == "feed-b"
    txt_files = list((tmp_path / "source-snapshots").glob("*.txt"))
    assert len(txt_files) == 1


def test_tampered_snapshot_content_surfaces_warning_no_refs(tmp_path):
    source = dict(config.SOURCES[0])
    body = _assurance_csv_body("cb-tamper")
    opps, _feed = scout_source_body(
        body, source, offline_replay=True, snapshot_root=tmp_path
    )
    ref = opps[0]["source_snapshot_ref"]
    snap_path = tmp_path / ref
    snap_path.write_bytes(b"tampered-not-the-original-body")
    opps2, _feed2 = scout_source_body(
        body, source, offline_replay=True, snapshot_root=tmp_path
    )
    assert not opps2[0].get("source_snapshot_ref")
    assert "existing snapshot content" in (opps2[0].get("evidence_persistence_warning") or "")


def test_csv_byte_cap_marks_partial_not_healthy(tmp_path, monkeypatch):
    import porcupine.radar as radar_mod

    source = dict(config.SOURCES[0])
    source["max_bytes"] = 50

    class FakeResp:
        headers = {"Content-Type": "text/csv; charset=utf-8"}

        def read(self, n):
            return b"a" * (n + 1)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(radar_mod, "urlopen", lambda *a, **k: FakeResp())
    result = scout([source], cache_directory=tmp_path, sleeper=lambda _s: None)
    feed = result["feeds"][0]
    assert feed["status"] == "partial"
    assert feed.get("parse_outcome") == "partial"
