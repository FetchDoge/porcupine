"""transport_hardening label split (fleet security follow-up, 2026-10-13).

'guarded' is claimed only for records whose body this process fetched
through netguard's guarded opener. Everything else — cache, replay,
caller-supplied body, skipped — keeps 'unresolved', because the run did
not establish that record's fetch provenance.
"""
from porcupine import config
from porcupine.radar import (
    _feed_record_from_csv_parse,
    _html_feed_record,
    _transport_hardening,
    scout_source_body,
)


def test_helper_truth_table():
    assert _transport_hardening("fetch") == "guarded"
    for how in ("cache", "replay", "body", "skipped", ""):
        assert _transport_hardening(how) == "unresolved", how


def test_csv_record_labels_by_how():
    source = config.SOURCES[0]
    stats = {"parse_outcome": "ok", "fetched_at": "2026-10-13T00:00:00Z"}
    assert _feed_record_from_csv_parse(source, stats, how="fetch")["transport_hardening"] == "guarded"
    assert _feed_record_from_csv_parse(source, stats, how="cache")["transport_hardening"] == "unresolved"


def test_html_record_labels_by_how():
    source = {"id": "s", "name": "S", "kind": "program"}
    assert _html_feed_record(source, "https://example.test", [], "ok", "", "fetch")["transport_hardening"] == "guarded"
    assert _html_feed_record(source, "https://example.test", [], "ok", "", "cache")["transport_hardening"] == "unresolved"


def test_replay_stays_unresolved():
    source = config.SOURCES[0]
    _opps, feed = scout_source_body("", source, offline_replay=True)
    assert feed["transport_hardening"] == "unresolved"
