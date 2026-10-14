"""Issue #2 — IDEaS HTML source coverage. No network.

Three page shapes are exercised against fixtures with recorded provenance
(see fixtures/PROVENANCE.md):

- the live CanadaBuys IDEaS search page, whose only <article> elements are
  footer furniture while the results are body links (real capture);
- a canada.ca WET-shaped program page with no <article> at all (synthetic;
  DESIGN-v2 §3 names this the primary-source shape);
- nested <article> elements and multi-section articles without data-id
  (synthetic).

Honesty contract under test: a shape that yields zero never suppresses the
next shape; a page that still yields zero stays visibly caveated
(empty_valid plus a coverage warning), and a dead URL stays skipped.
"""

import hashlib
from pathlib import Path
from urllib.error import HTTPError

from porcupine import config
from porcupine.radar import parse_opportunities_html, scout, scout_source_body

FIXTURES = Path(__file__).parent / "fixtures"
LIVE_FIXTURE = FIXTURES / "canadabuys-ideas-live-2026-10-14.html"
LIVE_SHA256 = "e44a13338b6b1a764b21eda4caab97ca07635bbe686c59f1d62eda9c4a87e996"
LIVE_URL = "https://canadabuys.canada.ca/en/tender-opportunities?keywords=IDEaS"
PROGRAM_URL = (
    "https://www.canada.ca/en/department-national-defence/programs/defence-ideas.html"
)


def _source(source_id):
    return next(source for source in config.SOURCES if source["id"] == source_id)


def test_live_fixture_is_the_recorded_capture():
    raw = LIVE_FIXTURE.read_bytes()
    assert len(raw) == 416_046
    assert hashlib.sha256(raw).hexdigest() == LIVE_SHA256


def test_live_canadabuys_ideas_page_parses_past_footer_articles():
    body = LIVE_FIXTURE.read_text(encoding="utf-8")
    found = parse_opportunities_html(
        body,
        source="canadabuys-ideas",
        page_url=LIVE_URL,
        source_name="CanadaBuys IDEaS keyword",
        source_kind="tender",
    )
    # The page's four <article> elements are "useful links" furniture and
    # normalize to zero; the listing fallback must still run and surface
    # the gated result the old article short-circuit hid.
    assert len(found) >= 1
    assert "W8703-270055" in {opp["id"] for opp in found}
    for opp in found:
        assert opp["url"].startswith("https://canadabuys.canada.ca/")


def test_live_page_yields_nothing_for_a_kind_with_no_fallback():
    body = LIVE_FIXTURE.read_text(encoding="utf-8")
    assert (
        parse_opportunities_html(
            body, source="jobs", page_url=LIVE_URL, source_kind="job_board"
        )
        == []
    )


def test_program_page_without_article_parses_heading_sections():
    body = (FIXTURES / "program_page_no_article.html").read_text(encoding="utf-8")
    found = parse_opportunities_html(
        body,
        source="ideas-program",
        page_url=PROGRAM_URL,
        source_name="DND IDEaS program",
        source_kind="program",
    )
    assert len(found) == 2
    by_title = {opp["title"]: opp for opp in found}
    first = by_title["Component 1a: operator trust and provenance studies"]
    assert first["funding"] == 250_000.0
    assert first["deadline"] == "2027-03-31"
    assert first["trl"] == "1-3"
    second = by_title["Component 1b: provenance for sensor fusion"]
    assert second["funding"] == 1_500_000.0
    assert second["deadline"] == "2027-06-30"
    # Program prose with no link, money, or deadline is not a card, and
    # nav/footer lens bait never leaks into a section.
    assert not any("history" in title.lower() for title in by_title)
    assert not any("contact" in title.lower() for title in by_title)
    assert {opp["id"] for opp in found} == {"section-1", "section-2"}


def test_program_section_fallback_is_scoped_to_program_kind():
    body = (FIXTURES / "program_page_no_article.html").read_text(encoding="utf-8")
    for kind in ("tender", "job_board", "accelerator"):
        assert (
            parse_opportunities_html(
                body, source="x", page_url=PROGRAM_URL, source_kind=kind
            )
            == []
        )


def test_nested_articles_not_truncated_and_section_ids_unique():
    body = (FIXTURES / "nested_articles.html").read_text(encoding="utf-8")
    found = parse_opportunities_html(body, source="nested", source_kind="tender")
    assert len(found) == 4
    titles = {opp["title"] for opp in found}
    assert titles == {
        "Alpha challenge: trust verification",
        "Beta challenge: sensor assurance",
        "Gamma challenge: audit lineage",
        "Delta challenge: fail-closed control",
    }
    # Text after the nested </article> survives: the old non-greedy regex
    # ended the outer card at the inner close tag and lost it.
    alpha = next(opp for opp in found if opp["title"].startswith("Alpha"))
    assert "attestation" in alpha["description"]
    ids = [opp["id"] for opp in found]
    assert len(set(ids)) == len(ids)
    assert set(ids) == {"section-1-1", "section-1-2", "section-2-1", "section-2-2"}


def test_repaired_listing_feed_shows_its_evidence(tmp_path):
    body = LIVE_FIXTURE.read_text(encoding="utf-8")

    def fake_fetch(url, cache_dir, timeout):
        return body, "fetched"

    result = scout(
        sources=[_source("canadabuys-ideas")],
        cache_directory=tmp_path,
        fetcher=fake_fetch,
        sleeper=lambda _seconds: None,
    )
    feed = result["feeds"][0]
    assert feed["status"] == "ok"
    assert feed["parse_outcome"] == "ok"
    assert feed["opportunities"] >= 1
    assert result["health"]["healthy"] == 1


def test_unparseable_program_body_is_empty_valid_with_warning():
    source = _source("ideas-program")
    opps, feed = scout_source_body(
        "<html><body><p>hello</p></body></html>", source
    )
    assert opps == []
    assert feed["status"] == "ok"
    assert feed["parse_outcome"] == "empty_valid"
    assert "not proof of a healthy empty market" in feed["coverage_warning"]


def test_dead_awards_url_stays_skipped_not_healthy(tmp_path):
    def dead_fetch(url, cache_dir, timeout):
        raise HTTPError(url, 404, "Not Found", hdrs=None, fp=None)

    result = scout(
        sources=[_source("canadabuys-awards")],
        cache_directory=tmp_path,
        fetcher=dead_fetch,
        sleeper=lambda _seconds: None,
    )
    feed = result["feeds"][0]
    assert feed["status"] == "skipped"
    assert "404" in feed["error"]
    assert feed["opportunities"] == 0
    assert result["health"]["healthy"] == 0
    assert result["health"]["dead"][0]["id"] == "canadabuys-awards"
