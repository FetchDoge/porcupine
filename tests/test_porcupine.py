"""Stdlib-friendly tests. No network."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from porcupine import config
from porcupine.cli import assemble, format_table, load_p_win, record_win
from porcupine.config import CACHE_TTL_SECONDS, FETCH_GAP_SECONDS, RETRY_BACKOFF_SECONDS, TRL_FIT_BUMP
from porcupine.draft import SECTIONS, render_heilmeier
from porcupine.ledger import Ledger
from porcupine.moat import map_moat
from porcupine.radar import (
    cache_file,
    parse_deadline,
    parse_funding,
    parse_opportunities_html,
    read_cache,
    scout,
    write_cache,
)
from porcupine.scope import classify
from porcupine.scoring import expected_value, score_opportunity, wilson_lower_bound

FIXTURE = Path(__file__).parent / "fixtures" / "sample_opportunity.html"

ASSURANCE_TEXT = (
    "Embed compliance-by-design with provenance and full lineage "
    "so the operator can replay the decision."
)
DRONE_TEXT = "Pure drone flight software for the airframe autopilot."


def test_ev_known_fixture():
    funding = 100_000.0
    portfolio_fit = 0.5
    reachability = 0.5
    effort = 10_000.0
    assert expected_value(funding, portfolio_fit, reachability, effort) == 15_000.0


def test_wilson_lower_bound_n0_is_zero():
    assert wilson_lower_bound(0, 0) == 0.0
    assert wilson_lower_bound(5, 0) == 0.0


def test_wilson_lower_bound_is_not_a_constant_zero():
    bound = wilson_lower_bound(50, 100)
    assert 0.39 < bound < 0.42


def test_score_uses_ev_formula_and_conservative_p_win():
    opp = {
        "id": "fixture-ev",
        "title": "Provenance line",
        "description": "Operator trust via provenance and full lineage. Budget $100,000.",
        "source_kind": "tender",
        "funding": 100_000.0,
        "funding_trace": "funding_field=$100,000",
        "deadline": "2027-03-31",
        "deadline_trace": "deadline_field=2027-03-31",
    }
    scored = score_opportunity(opp, today=date(2026, 10, 4), p_win_successes=0, p_win_n=0)
    assert scored["p_win_lcb"] == 0.0
    assert scored["ev"] == expected_value(
        scored["funding_for_ev"],
        scored["portfolio_fit"],
        scored["reachability"],
        scored["effort"],
    )
    assert "provenance" in scored["traces"]["assurance_hits"]


def test_component_label_does_not_invent_funding():
    html = """
    <article data-id="C1A-NO-DOLLARS">
      <h2>Component 1a trust and provenance study</h2>
      <p>Explore operator trust and provenance. No award value is printed in this notice.
      The work mentions compliance-by-design and must be long enough to parse as a card.</p>
    </article>
    """
    found = parse_opportunities_html(html, source="ideas-test", source_kind="tender")
    assert len(found) == 1
    assert found[0]["funding"] is None
    scored = score_opportunity(found[0], today=date(2026, 10, 4))
    assert scored["funding_for_ev"] == 0.0
    assert scored["ev"] == expected_value(0.0, scored["portfolio_fit"], scored["reachability"], scored["effort"])


def test_moat_assurance_versus_drone():
    assurance = {"id": "a", "title": "Lineage", "description": ASSURANCE_TEXT}
    mapped = map_moat(assurance)
    high = set(mapped["high_repos"])
    assert {"interlock", "hermes-refuse", "ep-aec-conformance"} <= high
    drone = {"id": "d", "title": "Autopilot", "description": DRONE_TEXT}
    drone_map = map_moat(drone)
    assert drone_map["high_repos"] == []
    assert all(repo["fit"] < 0.4 for repo in drone_map["repos"])
    assert classify(drone)["classification"] == "capability-saturated"
    assert classify(assurance)["classification"] == "assurance-white-space"


def test_heilmeier_has_seven_sections():
    opp = {
        "id": "draft-1",
        "title": "Operator trust with full lineage",
        "description": ASSURANCE_TEXT,
        "source": "ideas-test",
        "source_name": "IDEaS fixture",
        "url": "https://example.test/ideas",
        "funding": None,
        "deadline": "2027-03-31",
        "trl": None,
        "raw_keywords_matched": ["compliance-by-design", "provenance", "lineage"],
    }
    text = render_heilmeier(opp, today=date(2026, 10, 4))
    for section in SECTIONS:
        assert section in text
    assert len(SECTIONS) == 7
    assert "[TO VERIFY]" in text
    assert "does not submit" in text


def test_ledger_append_is_idempotent(tmp_path):
    ledger = Ledger(tmp_path / "ledger" / "porcupine.jsonl")
    row = {
        "record_type": "opportunity",
        "source": "ideas-test",
        "id": "IDEAS-FCE-2026",
        "disposition": "near-miss",
        "title": "Fusion Compliance Engine",
    }
    first = ledger.append(row)
    second = ledger.append(dict(row))
    assert first["written"] is True
    assert second["written"] is False
    rows = ledger.read()
    assert len(rows) == 1
    assert rows[0]["id"] == "IDEAS-FCE-2026"
    other = ledger.append({**row, "id": "OTHER-1"})
    assert other["written"] is True
    assert len(ledger.read()) == 2


def test_parse_sample_html_matches_keywords():
    html = FIXTURE.read_text(encoding="utf-8")
    found = parse_opportunities_html(
        html,
        source="ideas-test",
        page_url="https://canadabuys.canada.ca/en/tender-opportunities",
        source_name="fixture",
        source_kind="tender",
    )
    assert len(found) == 1
    opp = found[0]
    assert opp["id"] == "IDEAS-FCE-2026"
    assert opp["title"] == "Fusion Compliance Engine"
    assert opp["funding"] == 6_750_000.0
    assert opp["deadline"] == "2026-07-21"
    assert opp["trl"] == "1-6"
    matched = set(opp["raw_keywords_matched"])
    for keyword in ("compliance-by-design", "provenance", "lineage", "trust", "explainable"):
        assert keyword in matched
    assert opp["url"].endswith("/ideas-fce")


def test_scout_skips_a_dead_feed(tmp_path):
    def explode(url, cache_dir, timeout):
        raise TimeoutError("timed out")

    result = scout(
        [{"id": "dead", "name": "Dead", "kind": "tender", "url": "https://example.invalid/feed"}],
        cache_directory=tmp_path,
        fetcher=explode,
        sleeper=lambda _seconds: None,
    )
    assert result["opportunities"] == []
    assert result["feeds"][0]["status"] == "skipped"
    assert "timed out" in result["feeds"][0]["error"]


def test_scout_waits_between_network_fetches(tmp_path):
    slept = []

    def fetch(url, cache_dir, timeout):
        return "<html><body><p>Nothing to match here at all.</p></body></html>", "fetched"

    scout(
        [
            {"id": "a", "name": "A", "kind": "tender", "url": "https://example.test/a"},
            {"id": "b", "name": "B", "kind": "tender", "url": "https://example.test/b"},
        ],
        cache_directory=tmp_path,
        fetcher=fetch,
        sleeper=slept.append,
        gap_seconds=FETCH_GAP_SECONDS,
    )
    assert slept == [FETCH_GAP_SECONDS]


def test_cache_ttl_expiry_refetches(tmp_path, monkeypatch):
    import porcupine.radar as radar

    url = "https://example.test/feed"
    write_cache(tmp_path, url, "OLD")
    path = cache_file(tmp_path, url)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["fetched_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=CACHE_TTL_SECONDS + 5)
    ).isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert read_cache(tmp_path, url) is None

    opened = []

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

    def fake_urlopen(request, timeout=20):
        opened.append(getattr(request, "full_url", url))
        return _Resp()

    monkeypatch.setattr(radar, "urlopen", fake_urlopen)
    source = {"id": "feed", "name": "Feed", "kind": "tender", "url": url}
    result = scout([source], cache_directory=tmp_path, sleeper=lambda _seconds: None)
    assert result["feeds"][0]["how"] == "fetched"
    assert len(opened) == 1
    assert read_cache(tmp_path, url) == "NEW BODY"
    again = scout([source], cache_directory=tmp_path, sleeper=lambda _seconds: None)
    assert again["feeds"][0]["how"] == "cache"
    assert len(opened) == 1


def test_parse_funding_prefers_component_figure_not_program_ceiling():
    amount, trace = parse_funding(
        "up to $250,000 for 1a, $1.5M for 1b, $5M for 2, $1.6B total"
    )
    assert amount == 250_000
    assert amount != 1_600_000_000
    assert "1a" in trace


def test_parse_funding_single_component_uses_nearest_figure():
    amount, _trace = parse_funding(
        "Component 1b competitive project. "
        "Funding up to $1,500,000 for the work. "
        "Travel costs of $2,000 may apply."
    )
    assert amount == 1_500_000


def test_deadline_labels_include_no_later_than_and_by():
    assert parse_deadline(
        "Submissions must be received no later than October 22, 2026."
    )[0] == "2026-10-22"
    assert parse_deadline("Applications are due by 22 October 2026.")[0] == "2026-10-22"
    assert parse_deadline("The package is received by 2026-10-22.")[0] == "2026-10-22"
    assert parse_deadline(
        "Proposals must be received by October 22, 2026."
    )[0] == "2026-10-22"
    assert parse_deadline("compliance-by-design 2026-04-01")[0] is None


def test_url_scheme_allowlist_rejects_file_and_ftp():
    def page(href: str) -> str:
        return f"""
        <article data-id="SCHEME-1">
          <h2><a href="{href}">Operator trust and provenance challenge</a></h2>
          <p>Explainable assurance with full lineage for the operator. This card is long enough to parse.</p>
        </article>
        """

    file_hit = parse_opportunities_html(
        page("file:///etc/passwd"),
        source="t",
        page_url="https://example.test/a",
        source_kind="tender",
    )
    ftp_hit = parse_opportunities_html(
        page("ftp://files.example/secret"),
        source="t",
        page_url="https://example.test/a",
        source_kind="tender",
    )
    https_hit = parse_opportunities_html(
        page("https://canadabuys.canada.ca/en/real"),
        source="t",
        page_url="https://example.test/a",
        source_kind="tender",
    )
    assert len(file_hit) == 1 and file_hit[0]["url"] == ""
    assert len(ftp_hit) == 1 and ftp_hit[0]["url"] == ""
    assert https_hit[0]["url"] == "https://canadabuys.canada.ca/en/real"


def test_record_win_persists_and_moves_wilson(tmp_path):
    assert load_p_win(tmp_path) == {"p_win_n": 0, "p_win_successes": 0.0}
    first = record_win(tmp_path)
    assert first["p_win_n"] == 1
    assert first["p_win_successes"] == 1.0
    second = record_win(tmp_path)
    assert second["p_win_n"] == 2
    assert load_p_win(tmp_path)["p_win_successes"] == 2.0
    opp = {
        "id": "win-1",
        "title": "Provenance line",
        "description": "Operator trust via provenance and full lineage.",
        "source": "ideas-test",
        "source_kind": "tender",
        "funding": 100_000.0,
        "deadline": "2027-03-31",
    }
    rows = assemble([opp], today=date(2026, 10, 4), root=tmp_path)
    assert rows[0]["p_win_n"] == 2
    assert rows[0]["p_win_successes"] == 2.0
    assert rows[0]["p_win_lcb"] == wilson_lower_bound(2, 2)
    assert rows[0]["p_win_lcb"] > 0


def test_scout_retries_transient_once(tmp_path):
    calls = {"n": 0}

    def fetch(url, cache_dir, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("timed out")
        return "<html><body><p>Nothing to match here at all.</p></body></html>", "fetched"

    slept = []
    result = scout(
        [{"id": "flaky", "name": "Flaky", "kind": "tender", "url": "https://example.test/flaky"}],
        cache_directory=tmp_path,
        fetcher=fetch,
        sleeper=slept.append,
        gap_seconds=FETCH_GAP_SECONDS,
    )
    assert calls["n"] == 2
    assert result["feeds"][0]["status"] == "ok"
    assert result["feeds"][0]["how"] == "fetched"
    assert slept == [RETRY_BACKOFF_SECONDS]


def test_scout_health_names_dead_feeds_and_days(tmp_path):
    health_path = tmp_path / "scout-health.json"
    health_path.write_text(
        json.dumps(
            {
                "feeds": {
                    "dead": {
                        "last_success": "2026-10-01",
                        "last_status": "ok",
                        "last_error": "",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def fetch(url, cache_dir, timeout):
        if url.endswith("/dead"):
            raise TimeoutError("timed out")
        return "<html><body><p>Nothing to match here at all.</p></body></html>", "fetched"

    result = scout(
        [
            {"id": "live", "name": "Live", "kind": "tender", "url": "https://example.test/live"},
            {"id": "dead", "name": "Dead", "kind": "tender", "url": "https://example.test/dead"},
        ],
        cache_directory=tmp_path,
        fetcher=fetch,
        sleeper=lambda _seconds: None,
        today=date(2026, 10, 4),
    )
    health = result["health"]
    assert health["healthy"] == 1
    assert health["total"] == 2
    assert health["summary"].startswith("1 of 2 feeds healthy")
    assert "3 days since last success" in health["summary"]
    assert health["dead"][0]["id"] == "dead"
    assert health["dead"][0]["days_since_success"] == 3


def test_link_fallback_skips_nav_and_non_listing_pages():
    nav = """
    <html><body>
      <nav><a href="https://example.test/textron">Textron Systems Aerosonde situational awareness</a></nav>
    </body></html>
    """
    assert parse_opportunities_html(nav, source="jobs", source_kind="job_board") == []
    assert parse_opportunities_html(nav, source="tenders", source_kind="tender") == []
    listing = """
    <html><body>
      <a href="https://example.test/opp">Operator trust and provenance for autonomous certification review</a>
      <p>Explainable assurance and full lineage for the operator decision.</p>
    </body></html>
    """
    found = parse_opportunities_html(
        listing,
        source="tenders",
        page_url="https://example.test/list",
        source_kind="tender",
    )
    assert len(found) == 1
    assert found[0]["url"] == "https://example.test/opp"


def test_markdown_escapes_title_structure():
    text = format_table([{"title": "[x](http://evil) # heading | cell", "ev": 1}])
    assert "\\[x]" in text
    assert "\\#" in text
    assert "\\|" in text


def test_trl_component_bumps_fit_and_stays_off_openness():
    opp = {
        "id": "trl",
        "title": "Provenance line",
        "description": "Operator trust via provenance and full lineage.",
        "source_kind": "tender",
        "funding": 100_000.0,
        "deadline": "2027-03-31",
    }
    base = score_opportunity(opp, today=date(2026, 10, 4))
    early = score_opportunity({**opp, "trl": "2"}, today=date(2026, 10, 4))
    late = score_opportunity({**opp, "trl": "8"}, today=date(2026, 10, 4))
    undated = score_opportunity({**opp, "trl": "2", "deadline": None}, today=date(2026, 10, 4))
    assert early["trl_component"] == "1a"
    assert early["portfolio_fit"] == min(1.0, base["portfolio_fit"] + TRL_FIT_BUMP["1a"])
    assert "trl_component=1a" in early["traces"]["reachability"]
    assert late["trl_component"] == "2"
    assert late["portfolio_fit"] == base["portfolio_fit"]
    assert early["open"] is True
    assert undated["open"] is None
    assert config.TRL_FIT_BUMP["2"] == 0.0
