"""Fetch public pages and parse them into normalized opportunities.

Every feed error is logged and skipped. A dead source does not fail the run.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import logging
import re
import sys
import time
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional, Union
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request

from . import config
from .netguard import guarded_urlopen as urlopen

log = logging.getLogger("porcupine.radar")

# ---------------------------------------------------------------------------
# §1 — Text extraction: money, deadlines, keywords, TRL
#
# Pure functions over page text. Nothing here touches the network or the disk.
# ---------------------------------------------------------------------------

_ARTICLE_TAG = re.compile(r"(?is)<article\b([^>]*)>|</article\s*>")
_DATA_ID = re.compile(r"(?i)\bdata-id\s*=\s*[\"']([^\"']+)[\"']")
_ISO_DATE = re.compile(r"\b(20[0-9]{2})-(\d{2})-(\d{2})\b")
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_ALT = "|".join(_MONTHS)
_DATE_DMY = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\s+(20[0-9]{{2}})\b",
    re.IGNORECASE,
)
_DATE_MDY = re.compile(
    rf"\b({_MONTH_ALT})\s+(\d{{1,2}}),?\s+(20[0-9]{{2}})\b",
    re.IGNORECASE,
)
_MONEY = re.compile(
    r"(?i)(?:cad|cdn|c\$|\$)\s*"
    r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+(?:\.[0-9]+)?)"
    r"(?:\s*(billion|million|bn|m|k|b)\b)?"
)
_COMPONENT_LABEL = re.compile(
    r"(?i)\b(?:component\s*|for\s+)(1a|1b|2)\b|\b(1a|1b)\b"
)
_CEILING_WORD = re.compile(
    r"(?i)\b(?:total|ceiling|overall|envelope|program budget|programme budget)\b"
)
_LABEL_WINDOW = 80
_CHROME_TAGS = {"nav", "footer", "header", "aside"}
_CHROME_CONTEXT = re.compile(
    r"(?i)\b(?:navigation|footer|copyright|all rights reserved|cookie policy|"
    r"main menu|skip to content|news releases|subscribe to)\b"
)
_TRL = re.compile(r"(?i)\bTRL\s*([0-9](?:\s*(?:-|–|to)\s*[0-9])?)")
_SOLICITATION = re.compile(r"\b([A-Z]{1,3}\d{3,}-[0-9][A-Z0-9-]*)\b")
_DATE_LABEL = re.compile(
    r"(?i)(?:"
    r"\b(?:clos(?:e|ing|es|ed)|deadline|until|due date|end date)\b"
    r"|no later than"
    r"|must be received by"
    r"|received by"
    r"|\bdue\s+by\b"
    r")"
)


def opportunity_text(opp: dict) -> str:
    """Title plus description: the text every lens reads."""
    return "\n".join(str(opp.get(key) or "") for key in ("title", "description"))


def _keyword_variants(keyword: str) -> tuple[str, ...]:
    base = keyword.lower()
    extras = {
        "command & control": ("command and control",),
        "human-autonomy": ("human autonomy",),
        "human-machine teaming": ("human machine teaming",),
        "fail-closed": ("fail closed",),
        "compliance-by-design": ("compliance by design",),
    }
    return (base,) + extras.get(keyword, ())


def _contains_term(norm: str, term: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)"
    return re.search(pattern, norm) is not None


def match_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    """Terms present in text, with keyword variants. Empty text matches nothing."""
    if not text:
        return []
    norm = re.sub(r"\s+", " ", text.lower().replace("\u00a0", " ").replace("&amp;", "&"))
    found = []
    for term in terms:
        if any(_contains_term(norm, variant) for variant in _keyword_variants(term)):
            found.append(term)
    return found


def match_keywords(text: str) -> list[str]:
    """Return lens keywords present in text, in lens order."""
    return match_terms(text, config.KEYWORD_LENS)


def match_capability(text: str) -> list[str]:
    """Capability markers present in text, in marker order."""
    return match_terms(text, config.CAPABILITY_MARKERS)


def _scale_money(number: float, unit: str) -> float:
    unit = (unit or "").lower()
    if unit in ("million", "m"):
        return number * 1_000_000
    if unit in ("billion", "bn", "b"):
        return number * 1_000_000_000
    if unit == "k":
        return number * 1_000
    return number


def _funding_amounts(text: str) -> list[dict]:
    found = []
    for match in _MONEY.finditer(text or ""):
        number = _scale_money(float(match.group(1).replace(",", "")), match.group(2) or "")
        found.append(
            {
                "start": match.start(),
                "end": match.end(),
                "number": number,
                "raw": match.group(0).strip(),
            }
        )
    return found


def _is_program_ceiling(text: str, amount: dict) -> bool:
    """A program envelope, not a component award.

    The word total/ceiling must sit against this figure. A later "$1.6B total"
    must not also strike the $250K and $1.5M figures earlier on the same line.
    Call this only for a figure no component label is paired with. 250K, 1.5M,
    and 5M are legitimate awards when a label sits on them.
    """
    if amount["number"] >= config.FUNDING_PROGRAM_CEILING_CAD:
        return True
    before = text[max(0, amount["start"] - 16) : amount["start"]]
    after = text[amount["end"] : amount["end"] + 16]
    return _CEILING_WORD.search(before) is not None or _CEILING_WORD.search(after) is not None


def _component_mentions(text: str) -> list[dict]:
    mentions = []
    for match in _COMPONENT_LABEL.finditer(text or ""):
        name = (match.group(1) or match.group(2) or "").lower()
        if not name:
            continue
        # "$250,000 for 1a" — the award is the figure in front of "for".
        mentions.append(
            {
                "name": name,
                "start": match.start(),
                "end": match.end(),
                "before": match.group(0).lower().startswith("for"),
            }
        )
    return mentions


def _edge_gap(amount: dict, start: int, end: int) -> int:
    if amount["end"] <= start:
        return start - amount["end"]
    if end <= amount["start"]:
        return amount["start"] - end
    return 0


def _closest_amount(amounts: list[dict], start: int, end: int) -> Optional[dict]:
    within = [
        amount for amount in amounts if _edge_gap(amount, start, end) <= _LABEL_WINDOW
    ]
    if not within:
        return None
    return min(within, key=lambda amount: (_edge_gap(amount, start, end), amount["start"]))


def _amount_for_mention(amounts: list[dict], mention: dict) -> Optional[dict]:
    start = mention["start"]
    end = mention["end"]
    if mention["before"]:
        preceding = [amount for amount in amounts if amount["end"] <= start]
        chosen = _closest_amount(preceding, start, end)
        if chosen is not None:
            return chosen
    return _closest_amount(amounts, start, end)


def parse_funding(text: str) -> tuple[Optional[float], str]:
    """Dollar figure for this opportunity. Never the unbound program ceiling.

    One component label (1a, 1b, or 2) selects the figure paired with that
    label. "$250,000 for 1a" takes the figure in front of the label, not the
    next component's figure. A menu of components selects the smallest of
    those paired figures. A figure a label is actually paired with is kept.
    With no component label, the smallest plausible figure is used.
    """
    raw_text = text or ""
    amounts = _funding_amounts(raw_text)
    if not amounts:
        return None, "funding_field=absent"
    # $1.6B "total" is a program envelope. It is not a component award.
    # 250K / 1.5M / 5M stay in the pool: they are the component figures even
    # when the same numbers are also published as program ceilings.
    award_sized = [
        amount
        for amount in amounts
        if amount["number"] < config.FUNDING_PROGRAM_CEILING_CAD
    ]
    floored = [
        amount
        for amount in award_sized
        if amount["number"] >= config.FUNDING_PLAUSIBLE_FLOOR_CAD
    ]
    pool = floored or award_sized
    mentions = _component_mentions(raw_text)
    paired: list[tuple[str, dict]] = []
    if mentions and pool:
        for mention in mentions:
            chosen = _amount_for_mention(pool, mention)
            if chosen is not None:
                paired.append((mention["name"], chosen))
    if paired:
        distinct = {name for name, _amount in paired}
        if len(distinct) == 1:
            name, chosen = paired[0]
        else:
            name, chosen = min(paired, key=lambda item: (item[1]["number"], item[1]["start"]))
        return chosen["number"], f"funding_field={chosen['raw']} (component {name})"
    plausible = [amount for amount in pool if not _is_program_ceiling(raw_text, amount)]
    if not plausible:
        return None, "funding_field=absent"
    chosen = min(plausible, key=lambda amount: (amount["number"], amount["start"]))
    return chosen["number"], "funding_field=" + chosen["raw"]


def _iso_from_parts(year: int, month: int, day: int) -> Optional[str]:
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def _collect_date_candidates(text: str) -> list[tuple[int, str, str]]:
    """Every (position, iso, raw) date candidate in every supported format."""
    candidates = []
    for match in _ISO_DATE.finditer(text):
        iso = _iso_from_parts(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if iso:
            candidates.append((match.start(), iso, match.group(0)))
    for match in _DATE_DMY.finditer(text):
        iso = _iso_from_parts(int(match.group(3)), _MONTHS[match.group(2).lower()], int(match.group(1)))
        if iso:
            candidates.append((match.start(), iso, match.group(0)))
    for match in _DATE_MDY.finditer(text):
        iso = _iso_from_parts(int(match.group(3)), _MONTHS[match.group(1).lower()], int(match.group(2)))
        if iso:
            candidates.append((match.start(), iso, match.group(0)))
    return candidates


def parse_deadline(text: str) -> tuple[Optional[str], str]:
    """Pick a close date if one is written. Does not invent one."""
    if not text:
        return None, "deadline_absent"
    candidates = _collect_date_candidates(text)
    if not candidates:
        return None, "deadline_absent"
    labeled = []
    for start, iso, raw in candidates:
        window = text[max(0, start - 48) : start]
        if _DATE_LABEL.search(window):
            labeled.append((iso, raw))
    if not labeled:
        return None, "deadline_absent"
    iso, raw = labeled[-1]
    return iso, f"deadline_field={raw} (label)"


def parse_trl(text: str) -> Optional[str]:
    match = _TRL.search(text or "")
    if not match:
        return None
    return re.sub(r"\s+", "", match.group(1).lower().replace("–", "-").replace("to", "-"))


def sanitize_markdown(text: str) -> str:
    """Escape markdown structure characters in untrusted titles and descriptions."""
    escaped = []
    for char in text or "":
        if char in "#|[":
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)


# ---------------------------------------------------------------------------
# §2 — HTML parsing: articles, listing links, and program-page sections
#
# Three card shapes: <article> fragments, bare links on listing pages, and
# heading-delimited sections on program pages (DESIGN-v2 §3). All funnel
# through _normalize_html_card so one gate decides what exists. A shape that
# yields zero never suppresses the next shape for that page kind.
# ---------------------------------------------------------------------------

def _allowed_url(url: str, page_url: str) -> str:
    """Absolute http(s) URL, or empty when the scheme is not on the allowlist."""
    raw = (url or "").strip()
    if not raw:
        return ""
    joined = urljoin(page_url or "", raw)
    parsed = urlparse(joined)
    if parsed.scheme.lower() not in ("http", "https"):
        return ""
    if not parsed.netloc:
        return ""
    return joined


def _make_id(data_id: str, url: str, title: str, source: str) -> str:
    """Stable id: data-id, solicitation number, URL slug, then a content digest."""
    if data_id and data_id.strip():
        return data_id.strip()[:120]
    blob = f"{title} {url}"
    solicitation = _SOLICITATION.search(blob)
    if solicitation:
        return solicitation.group(1)
    if url:
        slug = url.rstrip("/").split("/")[-1].split("?")[0]
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", slug).strip("-")
        if len(slug) >= 6:
            return slug[:80]
    digest = hashlib.sha1(f"{source}|{title}|{url}".encode("utf-8")).hexdigest()[:12]
    return f"t-{digest}"


def _normalize_html_card(
    *,
    data_id: str,
    title: str,
    url: str,
    text: str,
    source: str,
    source_name: str,
    source_kind: str,
    page_url: str,
) -> Optional[dict]:
    """One HTML card to a normalized opportunity. None when too thin or lens-deaf."""
    title = " ".join((title or "").split())
    text = " ".join((text or "").split())
    if len(text) < 40 and len(title) < 12:
        return None
    if url:
        url = _allowed_url(url, page_url)
    keywords = match_keywords(f"{title}\n{text}")
    capability = match_capability(f"{title}\n{text}")
    if not keywords and not capability:
        return None
    if not title:
        title = text[:120]
    funding, funding_trace = parse_funding(text)
    deadline, deadline_trace = parse_deadline(text)
    description = text[: config.DESCRIPTION_MAX_CHARS]
    return {
        "id": _make_id(data_id, url, title, source),
        "title": title[:300],
        "source": source,
        "source_name": source_name,
        "source_kind": source_kind,
        "url": url,
        "funding": funding,
        "funding_trace": funding_trace,
        "trl": parse_trl(text),
        "deadline": deadline,
        "deadline_trace": deadline_trace,
        "description": description,
        "raw_keywords_matched": keywords,
        "capability_markers": capability,
    }


class _SectionParser(HTMLParser):
    """Split one article on headings so a date cannot borrow another section's words."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict] = [{"title": "", "url": "", "parts": []}]
        self.in_a = False
        self.in_h = False
        self.link_buf: list[str] = []
        self.heading_buf: list[str] = []

    @property
    def current(self) -> dict:
        return self.sections[-1]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        ad = {key: (value or "") for key, value in attrs}
        if tag in ("h1", "h2", "h3"):
            self.in_h = True
            self.heading_buf = []
        if tag == "a":
            self.in_a = True
            self.link_buf = []
            href = ad.get("href") or ""
            if href and not self.current["url"] and not href.startswith(("#", "javascript:", "mailto:")):
                self.current["url"] = href

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.in_a:
            text = " ".join("".join(self.link_buf).split())
            if text and not self.current["title"]:
                self.current["title"] = text
            self.in_a = False
        if tag in ("h1", "h2", "h3") and self.in_h:
            text = " ".join("".join(self.heading_buf).split())
            self.in_h = False
            if not text:
                return
            occupied = bool(self.current["title"] or "".join(self.current["parts"]).strip())
            if occupied:
                self.sections.append({"title": text, "url": "", "parts": []})
            else:
                self.current["title"] = text

    def handle_data(self, data: str) -> None:
        if self.in_h:
            self.heading_buf.append(data)
            return
        self.current["parts"].append(data)
        if self.in_a:
            self.link_buf.append(data)


def _article_fragments(html: str) -> list[tuple[str, str]]:
    """Outermost <article> (attrs, body) pairs, in document order.

    Depth-aware: a nested <article> does not end the outer card early (the
    old non-greedy regex truncated the outer card at the inner close tag and
    lost everything after it). An unclosed article yields nothing, and a
    stray close tag is ignored — the same honesty as before, minus the
    silent truncation.
    """
    fragments: list[tuple[str, str]] = []
    depth = 0
    start = 0
    attrs = ""
    for match in _ARTICLE_TAG.finditer(html):
        if match.group(1) is not None:  # open tag; group 1 is its attributes
            if match.group(0).rstrip().endswith("/>"):
                continue  # self-closing: no body, never a card
            if depth == 0:
                start = match.end()
                attrs = match.group(1)
            depth += 1
        else:  # close tag
            if depth == 0:
                continue
            depth -= 1
            if depth == 0:
                fragments.append((attrs, html[start : match.start()]))
    return fragments


def _extract_articles(html: str) -> list[dict]:
    """Split <article> cards into title/text/url triples; skips oversized or empty sections."""
    fragments = _article_fragments(html)
    qualify = len(fragments) > 1
    cards = []
    for article_no, (attrs, body) in enumerate(fragments, 1):
        data_id_match = _DATA_ID.search(attrs)
        data_id = data_id_match.group(1) if data_id_match else ""
        parser = _SectionParser()
        try:
            parser.feed(body)
            parser.close()
        except Exception as exc:
            log.warning("article fragment skipped: %s", exc)
            continue
        usable = []
        for section in parser.sections:
            text = " ".join("".join(section["parts"]).split())
            title = " ".join((section["title"] or "").split())
            if len(text) > config.MAX_CARD_CHARS:
                log.warning("skip oversized section in %s (%s chars)", data_id or title[:40], len(text))
                continue
            if len(text) < 40 and len(title) < 12:
                continue
            usable.append({"url": section["url"], "title": title, "text": text})
        for index, section in enumerate(usable, 1):
            if len(usable) == 1:
                section_id = data_id
            elif data_id:
                section_id = f"{data_id}-{index}"
            elif qualify:
                # No data-id and several articles on the page: a bare
                # "section-N" would collide across articles and the dedup
                # in _cards_to_opportunities would silently drop cards.
                section_id = f"section-{article_no}-{index}"
            else:
                section_id = f"section-{index}"
            cards.append(
                {
                    "data_id": section_id,
                    "url": section["url"],
                    "title": section["title"],
                    "text": section["text"],
                }
            )
    return cards


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self.window: list[str] = []
        self.in_a = False
        self.href = ""
        self.buf: list[str] = []
        self.pending: Optional[dict] = None
        self.pending_budget = 0
        self._chrome_depth = 0

    def _push_window(self, data: str) -> None:
        self.window.append(data)
        size = sum(len(part) for part in self.window)
        while size > 500 and self.window:
            size -= len(self.window[0])
            self.window.pop(0)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in _CHROME_TAGS:
            self._chrome_depth += 1
        if tag != "a" or self._chrome_depth:
            return
        ad = {key: (value or "") for key, value in attrs}
        href = ad.get("href") or ""
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            return
        self.in_a = True
        self.href = href
        self.buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.in_a:
            text = " ".join("".join(self.buf).split())
            self.in_a = False
            if len(text) >= 20:
                self.pending = {
                    "url": self.href,
                    "title": text[:300],
                    "before": "".join(self.window),
                    "after": [],
                }
                self.pending_budget = 400
                self.links.append(self.pending)
        if tag in _CHROME_TAGS and self._chrome_depth:
            self._chrome_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_a:
            self.buf.append(data)
            return
        self._push_window(data)
        if self._chrome_depth:
            return
        if self.pending is not None and self.pending_budget > 0:
            self.pending["after"].append(data)
            self.pending_budget -= len(data)
            if self.pending_budget <= 0:
                self.pending = None


class _PageSectionParser(HTMLParser):
    """Split a whole page into heading-delimited sections, chrome excluded.

    Program pages in the canada.ca WET shape carry their challenges as
    headed sections of the main content, not as <article> cards and not as
    listing links. DESIGN-v2 §3 names that shape the primary source.
    Sections start at h2/h3 headings; nav, footer, header, and aside
    content never reaches a section.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict] = []
        self.current: Optional[dict] = None
        self.in_h = False
        self.heading_buf: list[str] = []
        self._chrome_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in _CHROME_TAGS:
            self._chrome_depth += 1
            return
        if self._chrome_depth:
            return
        if tag in ("h2", "h3"):
            self.in_h = True
            self.heading_buf = []
            return
        if tag == "a" and not self.in_h and self.current is not None and not self.current["url"]:
            ad = {key: (value or "") for key, value in attrs}
            href = ad.get("href") or ""
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                self.current["url"] = href

    def handle_endtag(self, tag: str) -> None:
        if tag in _CHROME_TAGS and self._chrome_depth:
            self._chrome_depth -= 1
            return
        if tag in ("h2", "h3") and self.in_h:
            self.in_h = False
            title = " ".join("".join(self.heading_buf).split())
            if title:
                self.current = {"title": title, "url": "", "parts": []}
                self.sections.append(self.current)

    def handle_data(self, data: str) -> None:
        if self._chrome_depth:
            return
        if self.in_h:
            self.heading_buf.append(data)
            return
        if self.current is not None:
            self.current["parts"].append(data)


def _extract_page_sections(html: str) -> list[dict]:
    """Heading sections of a program page as cards, when opportunity-shaped.

    A section counts only with a heading title AND at least one opportunity
    signal: a usable link, a money amount, or a labeled deadline. Program
    prose with none of these is information, not a card. The lens gate in
    _normalize_html_card still decides what becomes an opportunity; zero
    cards from a page is a parse outcome, never a healthy empty market.
    """
    parser = _PageSectionParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        log.warning("page section parse failed: %s", exc)
        return []
    cards = []
    for section in parser.sections:
        text = " ".join("".join(section["parts"]).split())
        title = " ".join((section["title"] or "").split())
        if len(text) > config.MAX_CARD_CHARS:
            log.warning("skip oversized page section %s (%s chars)", title[:40], len(text))
            continue
        if not title:
            continue
        if not section["url"] and not _funding_amounts(text) and parse_deadline(text)[0] is None:
            continue
        cards.append({"data_id": "", "url": section["url"], "title": title, "text": text})
    if len(cards) > 1:
        # Sections on one page often share a single "details" URL; without
        # a per-section id they collide on the URL slug in _make_id and the
        # dedup silently drops all but the first. Same convention as the
        # multi-section article path.
        for index, card in enumerate(cards, 1):
            card["data_id"] = f"section-{index}"
    return cards


def _strip_noisy(html: str) -> str:
    html = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", html)
    html = re.sub(r"(?is)<noscript\b[^>]*>.*?</noscript>", " ", html)
    return html


def _cards_to_opportunities(
    cards: list[dict],
    *,
    source: str,
    source_name: str,
    source_kind: str,
    page_url: str,
) -> list[dict]:
    """Normalize cards, drop empties and duplicates, cap at MAX_OPPS_PER_FEED."""
    opportunities = []
    seen = set()
    for card in cards:
        opp = _normalize_html_card(
            data_id=card.get("data_id") or "",
            title=card.get("title") or "",
            url=card.get("url") or "",
            text=card.get("text") or "",
            source=source,
            source_name=source_name,
            source_kind=source_kind,
            page_url=page_url,
        )
        if opp is None:
            continue
        key = (opp["source"], opp["id"])
        if key in seen:
            continue
        seen.add(key)
        opportunities.append(opp)
        if len(opportunities) >= config.MAX_OPPS_PER_FEED:
            break
    return opportunities


def parse_opportunities_html(
    html: str,
    source: str,
    page_url: str = "",
    source_name: str = "",
    source_kind: str = "default",
) -> list[dict]:
    """Parse one page into opportunities. Pure function: no network."""
    source_name = source_name or source
    cleaned = _strip_noisy(html or "")
    articles = _extract_articles(cleaned)
    if articles:
        found = _cards_to_opportunities(
            articles,
            source=source,
            source_name=source_name,
            source_kind=source_kind,
            page_url=page_url,
        )
        if found:
            return found
        # Article elements existed but none survived the gate. On Drupal
        # pages the only <article> elements can be footer furniture
        # ("useful links" blocks) while the results sit in the page body:
        # zero from the article shape is a parse outcome for that shape,
        # not for the page. Fall through to the kind's page-shape fallback.
        log.info(
            "feed %s: %d article cards, 0 opportunities; trying page-shape fallback",
            source,
            len(articles),
        )
    # Nav and footer links on homepages are not challenges. The fallback is
    # only for explicit listing pages, and a chrome-context before-window
    # still drops a link that sits under navigation, a footer, or a news menu.
    if source_kind not in config.LISTING_KINDS:
        if source_kind == "program":
            # DESIGN-v2 §3: program pages with no <article> must be parsed;
            # that is the primary-source shape (headed sections, WET pages).
            sections = _extract_page_sections(cleaned)
            if sections:
                return _cards_to_opportunities(
                    sections,
                    source=source,
                    source_name=source_name,
                    source_kind=source_kind,
                    page_url=page_url,
                )
        return []
    links = _LinkParser()
    try:
        links.feed(cleaned)
        links.close()
    except Exception as exc:
        log.warning("HTML link parse failed for %s: %s", source, exc)
        return []
    cards = []
    for link in links.links:
        before = link.get("before") or ""
        if _CHROME_CONTEXT.search(before):
            continue
        after = "".join(link.get("after") or [])
        # Anchor text plus the following words only. The shared header before
        # the link is page chrome and must not mint a keyword hit.
        cards.append(
            {
                "data_id": "",
                "url": link["url"],
                "title": link["title"],
                "text": f"{link['title']}. {after}",
            }
        )
    return _cards_to_opportunities(
        cards,
        source=source,
        source_name=source_name,
        source_kind=source_kind,
        page_url=page_url,
    )


# ---------------------------------------------------------------------------
# §3 — Provenance: content-addressed snapshots and acquisition stamps
#
# Every record carries where it came from. A hash is identity, not authenticity.
# ---------------------------------------------------------------------------

_PUBLISHER_CLOSED_STATUS = frozenset(
    {
        "closed",
        "cancelled",
        "canceled",
        "awarded",
        "award",
        "terminated",
        "expired",
    }
)
_TAG_RE = re.compile(r"<[^>]+>")


def _sha256_text(text: str) -> str:
    """SHA-256 of decoded text, UTF-8 encoded. CRLF and LF hash differently."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    """SHA-256 of raw downloaded bytes."""
    return hashlib.sha256(raw).hexdigest()


def source_snapshots_dir(root: Path) -> Path:
    """Directory holding content-addressed source snapshots under the runtime root."""
    return Path(root) / "source-snapshots"


def snapshot_body_rel_path(body_text_sha256: str) -> str:
    """Relative path of the decoded-text snapshot for a body hash."""
    return f"source-snapshots/{body_text_sha256}.txt"


def snapshot_meta_rel_path(acquisition_meta_sha256: str) -> str:
    """Relative path of the acquisition-metadata sidecar for an identity hash."""
    return f"source-snapshots/{acquisition_meta_sha256}.json"


def _acquisition_identity_payload(acquisition: dict, text_hash: str) -> dict:
    """Canonical acquisition fields for metadata dedup (excludes observed_at)."""
    return {
        "acquired_at": acquisition.get("fetched_at") or "unknown",
        "body_bytes_sha256": acquisition.get("body_bytes_sha256") or "",
        "body_text_sha256": text_hash,
        "how": acquisition.get("how") or "",
        "live_fetch": bool(acquisition.get("live_fetch")),
        "offline": bool(acquisition.get("offline")),
        "parse_outcome": acquisition.get("parse_outcome") or "",
        "source_id": acquisition.get("source_id") or "",
        "source_url": acquisition.get("source_url") or "",
    }


def acquisition_meta_sha256(acquisition: dict, text_hash: str) -> str:
    """Content identity of one acquisition. Excludes observed_at so replays dedup."""
    payload = _acquisition_identity_payload(acquisition, text_hash)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _path_confined_under(root: Path, target: Path) -> bool:
    """True when target stays under root. Snapshots never escape the runtime dir."""
    root_resolved = Path(root).resolve()
    target_resolved = target.resolve()
    return target_resolved == root_resolved or root_resolved in target_resolved.parents


def provenance_supported_for_snapshot(
    *,
    body: str,
    how: str,
    parse_outcome: str,
    truncated: bool = False,
) -> bool:
    """Decoded text snapshot only for bodies we actually parsed, not transport errors."""
    if truncated or how == "error":
        return False
    if not (body or "").strip():
        return False
    if parse_outcome in ("schema_drift", "unsupported", "fetch_error"):
        return False
    return True


def persist_source_snapshot(
    root: Path,
    body: str,
    acquisition: dict,
) -> dict:
    """Content-addressed decoded text + per-acquisition metadata under runtime root only."""
    computed_hash = _sha256_text(body)
    supplied = str(acquisition.get("body_text_sha256") or "")
    empty = {
        "source_snapshot_ref": "",
        "source_snapshot_meta_ref": "",
        "evidence_persistence_warning": "",
    }
    if supplied and supplied != computed_hash:
        return {
            **empty,
            "evidence_persistence_warning": "body_text_sha256 does not match computed body hash",
        }
    text_hash = supplied or computed_hash
    meta_hash = acquisition_meta_sha256(acquisition, text_hash)
    snap_dir = source_snapshots_dir(root)
    txt_path = snap_dir / f"{text_hash}.txt"
    meta_path = snap_dir / f"{meta_hash}.json"
    if not _path_confined_under(root, txt_path) or not _path_confined_under(root, meta_path):
        return {
            **empty,
            "evidence_persistence_warning": "snapshot path escapes runtime root",
        }
    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    meta_record = {
        "body_text_sha256": text_hash,
        "body_bytes_sha256": acquisition.get("body_bytes_sha256") or "",
        "acquired_at": acquisition.get("fetched_at") or "unknown",
        "observed_at": observed_at,
        "how": acquisition.get("how") or "",
        "live_fetch": bool(acquisition.get("live_fetch")),
        "offline": bool(acquisition.get("offline")),
        "source_id": acquisition.get("source_id") or "",
        "source_url": acquisition.get("source_url") or "",
        "parse_outcome": acquisition.get("parse_outcome") or "",
        "identity_not_authenticity": (
            "SHA-256 of decoded text is content identity only, not independent authenticity."
        ),
    }
    try:
        snap_dir.mkdir(parents=True, exist_ok=True)
        if txt_path.exists():
            stored_text = txt_path.read_bytes().decode("utf-8")
            if _sha256_text(stored_text) != text_hash:
                return {
                    **empty,
                    "evidence_persistence_warning": (
                        "existing snapshot content does not match body_text_sha256"
                    ),
                }
        else:
            txt_path.write_bytes(body.encode("utf-8"))
        if not meta_path.exists():
            meta_path.write_text(
                json.dumps(meta_record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return {
            "source_snapshot_ref": snapshot_body_rel_path(text_hash),
            "source_snapshot_meta_ref": snapshot_meta_rel_path(meta_hash),
            "evidence_persistence_warning": "",
        }
    except OSError as exc:
        log.warning("source snapshot not saved under %s: %s", snap_dir, exc)
        return {
            **empty,
            "evidence_persistence_warning": f"evidence persistence failed: {exc}",
        }


def stamp_opportunities_acquisition(
    opportunities: list[dict],
    *,
    acquisition: dict,
    snapshot_refs: dict,
) -> None:
    """Attach feed-level acquisition fields to every opportunity from that feed."""
    for opp in opportunities:
        opp["fetched_at"] = acquisition.get("fetched_at") or "unknown"
        opp["acquisition_how"] = acquisition.get("how") or ""
        opp["live_fetch"] = bool(acquisition.get("live_fetch"))
        opp["body_text_sha256"] = acquisition.get("body_text_sha256") or ""
        opp["body_bytes_sha256"] = acquisition.get("body_bytes_sha256") or ""
        ref = snapshot_refs.get("source_snapshot_ref") or ""
        opp["source_snapshot_ref"] = ref
        opp["source_snapshot_meta_ref"] = snapshot_refs.get("source_snapshot_meta_ref") or ""
        warning = snapshot_refs.get("evidence_persistence_warning") or ""
        if warning:
            opp["evidence_persistence_warning"] = warning


def _apply_acquisition_stamp(
    opportunities: list[dict],
    *,
    source: dict,
    body: str,
    how: str,
    fetched_at: object,
    live_fetch: bool,
    body_text_sha256: str,
    body_bytes_sha256: str,
    parse_outcome: str,
    truncated: bool,
    offline: bool,
    snapshot_root: Optional[Path],
) -> dict:
    """Build the acquisition record, persist the snapshot when supported, stamp every opportunity."""
    stamp = fetched_at if isinstance(fetched_at, str) and fetched_at.strip() else "unknown"
    acquisition = {
        "source_id": source.get("id") or "",
        "source_url": source.get("url") or "",
        "how": how,
        "fetched_at": stamp,
        "live_fetch": live_fetch,
        "body_text_sha256": body_text_sha256 or _sha256_text(body),
        "body_bytes_sha256": body_bytes_sha256 or "",
        "parse_outcome": parse_outcome,
        "offline": offline,
    }
    snapshot_refs: dict = {
        "source_snapshot_ref": "",
        "source_snapshot_meta_ref": "",
        "evidence_persistence_warning": "",
    }
    if snapshot_root is not None and provenance_supported_for_snapshot(
        body=body,
        how=how,
        parse_outcome=parse_outcome,
        truncated=truncated,
    ):
        snapshot_refs = persist_source_snapshot(snapshot_root, body, acquisition)
    stamp_opportunities_acquisition(opportunities, acquisition=acquisition, snapshot_refs=snapshot_refs)
    return {**acquisition, **snapshot_refs}


# ---------------------------------------------------------------------------
# §4 — CanadaBuys CSV intake: broad parse, keyword gate downstream
#
# Rows are counted and normalized independent of the lens. Relevance is
# applied later; nothing vanishes without a recorded reason.
# ---------------------------------------------------------------------------

def _clean_csv_description(text: str) -> str:
    """HTML entities unescaped, tags stripped, whitespace collapsed."""
    raw = html.unescape(text or "")
    raw = _TAG_RE.sub(" ", raw)
    return " ".join(raw.split())


def _parse_csv_close(raw: str) -> tuple[Optional[str], str, str]:
    """Return (deadline date ISO, close_at raw, close_timezone token)."""
    close_at = (raw or "").strip()
    if not close_at:
        return None, "", "unknown"
    date_part = close_at.split("T", 1)[0].strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_part):
        deadline = date_part
    else:
        deadline = None
    tz = "unknown"
    if "T" in close_at:
        tail = close_at.split("T", 1)[1]
        if re.search(r"(?:Z|[+-]\d{2}:?\d{2})$", tail):
            tz = "present_in_source"
    return deadline, close_at, tz


def _publisher_status_closed(status: str) -> bool:
    """True when the publisher status names a closed state. Empty or 'open' is not closed."""
    token = (status or "").strip().lower()
    if not token:
        return False
    if token == "open":
        return False
    if token in _PUBLISHER_CLOSED_STATUS:
        return True
    return "closed" in token or "cancel" in token


_CSV_MONITORED_FIELDS = (
    ("title-titre-eng", "title"),
    ("referenceNumber-numeroReference", "reference"),
    ("solicitationNumber-numeroSollicitation", "solicitation"),
    ("publicationDate-datePublication", "publication"),
    ("tenderClosingDate-appelOffresDateCloture", "close"),
    ("tenderStatus-appelOffresStatut-eng", "status"),
    ("noticeURL-URLavis-eng", "notice_url"),
    ("tenderDescription-descriptionAppelOffres-eng", "description"),
)


def _csv_row_field_overflow(row: dict) -> Optional[str]:
    """Return a rejection reason when any monitored field exceeds the configured cap."""
    for column, label in _CSV_MONITORED_FIELDS:
        value = row.get(column)
        if value is None:
            continue
        if isinstance(value, list):
            return f"malformed_row:{label}_list_value"
        text = str(value)
        if len(text) > config.CSV_MAX_FIELD_CHARS:
            return f"field_overflow:{label}"
    return None


def _coerce_csv_dict_row(row: object) -> tuple[Optional[dict], str]:
    """DictReader row to a plain dict, or (None, reason) when it cannot be trusted."""
    if not isinstance(row, dict):
        return None, "malformed_row:not_dict"
    if None in row:
        extras = row.get(None)
        if extras:
            return None, "extra_columns"
        row = {key: value for key, value in row.items() if key is not None}
    for key, value in row.items():
        if value is not None and isinstance(value, list):
            return None, "malformed_row:list_value"
    return row, "ok"


def _set_csv_parser_field_limit() -> int:
    """Raise the parser field limit safely; return the prior limit for restore."""
    try:
        previous = csv.field_size_limit()
    except (OverflowError, TypeError):
        previous = 131072
    target = max(config.CSV_MAX_FIELD_CHARS + 4096, previous, 131072)
    try:
        csv.field_size_limit(target)
    except OverflowError:
        csv.field_size_limit(sys.maxsize)
    return previous


def _csv_status_contradiction(status: str, deadline: Optional[str], today: date) -> str:
    """'Open' with a past close is a contradiction to surface, never a confirmed-open."""
    if status.lower() != "open" or not deadline:
        return ""
    try:
        if date.fromisoformat(deadline) < today:
            return "publisher_open_but_close_date_past"
    except ValueError:
        pass
    return ""


def _normalize_csv_row(
    *,
    row: dict,
    source: str,
    source_name: str,
    source_kind: str,
    page_url: str,
    dataset_url: str,
    today: date,
) -> tuple[Optional[dict], str]:
    overflow = _csv_row_field_overflow(row)
    if overflow:
        return None, overflow
    title = (row.get("title-titre-eng") or "").strip()
    reference = (row.get("referenceNumber-numeroReference") or "").strip()
    solicitation = (row.get("solicitationNumber-numeroSollicitation") or "").strip()
    publication = (row.get("publicationDate-datePublication") or "").strip()
    close_raw = row.get("tenderClosingDate-appelOffresDateCloture") or ""
    status = (row.get("tenderStatus-appelOffresStatut-eng") or "").strip()
    notice_url = (row.get("noticeURL-URLavis-eng") or "").strip()
    description_raw = row.get("tenderDescription-descriptionAppelOffres-eng") or ""
    if not title and not reference:
        return None, "missing_title_and_reference"
    description = _clean_csv_description(description_raw)
    text = f"{title}\n{description}"
    if len(description) < 20 and len(title) < 8:
        return None, "row_too_short"
    url = _allowed_url(notice_url, page_url) if notice_url else ""
    data_id = reference or solicitation
    keywords = match_keywords(text)
    capability = match_capability(text)
    funding, funding_trace = parse_funding(text)
    deadline, close_at, close_timezone = _parse_csv_close(close_raw)
    deadline_trace = (
        f"deadline_field={close_at} (csv column tenderClosingDate)"
        if close_at
        else "deadline_absent"
    )
    status_contradiction = _csv_status_contradiction(status, deadline, today)
    opp = {
        "id": _make_id(data_id, url, title, source),
        "title": title[:300],
        "source": source,
        "source_name": source_name,
        "source_kind": source_kind,
        "url": url,
        "funding": funding,
        "funding_trace": funding_trace,
        "trl": parse_trl(text),
        "deadline": deadline,
        "deadline_trace": deadline_trace,
        "description": description[: config.DESCRIPTION_MAX_CHARS],
        "raw_keywords_matched": keywords,
        "capability_markers": capability,
        "reference_number": reference,
        "solicitation_number": solicitation,
        "publication_date": publication,
        "close_at": close_at,
        "close_timezone": close_timezone,
        "source_status": status,
        "status_contradiction": status_contradiction,
        "source_dataset_url": dataset_url or page_url,
        "source_format": "canadabuys_csv",
        "detail_url_unknown": not bool(url),
    }
    return opp, "ok"


def _tally_rejection(stats: dict, rejection_reasons: dict, reason: str) -> None:
    """Count one rejected row under its reason. Rejections are data, not silence."""
    stats["rejected_rows"] += 1
    rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1


def parse_opportunities_canadabuys_csv(
    body: str,
    *,
    source: str,
    page_url: str = "",
    source_name: str = "",
    source_kind: str = "tender",
    dataset_url: str = "",
    today: Optional[date] = None,
    max_rows: Optional[int] = None,
) -> tuple[list[dict], dict]:
    """Parse CanadaBuys open-tender CSV. Broad intake; keyword gate is downstream."""
    today = today or date.today()
    source_name = source_name or source
    dataset_url = dataset_url or page_url
    stats: dict = {
        "parse_outcome": "ok",
        "raw_rows": 0,
        "valid_rows": 0,
        "rejected_rows": 0,
        "lens_matches": 0,
        "rows_capped": False,
        "body_text_sha256": _sha256_text(body or ""),
        "required_headers": list(config.CANADABUYS_CSV_REQUIRED_HEADERS),
        "missing_headers": [],
        "rejection_reasons": {},
        "source_incomplete": False,
    }
    if not body or not body.strip():
        stats["parse_outcome"] = "unsupported"
        return [], stats
    prior_field_limit = _set_csv_parser_field_limit()
    try:
        reader = csv.DictReader(io.StringIO(body.lstrip("\ufeff")), strict=True)
        fieldnames = reader.fieldnames or []
        missing = [h for h in config.CANADABUYS_CSV_REQUIRED_HEADERS if h not in fieldnames]
        if missing:
            stats["missing_headers"] = missing
            stats["parse_outcome"] = "schema_drift"
            return [], stats
        row_limit = max_rows if max_rows is not None else config.CSV_MAX_ROWS
        opportunities: list[dict] = []
        seen: set[tuple[str, str]] = set()
        stats["duplicate_rows"] = 0
        stats["unique_rows"] = 0
        stats["identity_policy"] = "first_wins_by_source_and_id"
        stats["csv_parse_errors"] = 0
        stats["parse_error"] = ""
        rejection_reasons: dict[str, int] = {}
        while True:
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error as exc:
                stats["raw_rows"] += 1
                stats["rejected_rows"] += 1
                stats["csv_parse_errors"] += 1
                stats["source_incomplete"] = True
                key = f"csv_error:{type(exc).__name__}"
                rejection_reasons[key] = rejection_reasons.get(key, 0) + 1
                if not stats["parse_error"]:
                    stats["parse_error"] = str(exc)
                stats["parse_outcome"] = "partial"
                break
            stats["raw_rows"] += 1
            if stats["raw_rows"] > row_limit:
                stats["rows_capped"] = True
                stats["parse_outcome"] = "partial"
                break
            coerced, coerce_reason = _coerce_csv_dict_row(row)
            if coerced is None:
                _tally_rejection(stats, rejection_reasons, coerce_reason)
                continue
            opp, reason = _normalize_csv_row(
                row=coerced,
                source=source,
                source_name=source_name,
                source_kind=source_kind,
                page_url=page_url,
                dataset_url=dataset_url,
                today=today,
            )
            if opp is None:
                _tally_rejection(stats, rejection_reasons, reason)
                continue
            stats["valid_rows"] += 1
            if opp.get("raw_keywords_matched") or opp.get("capability_markers"):
                stats["lens_matches"] += 1
            key = (opp["source"], opp["id"])
            if key in seen:
                stats["duplicate_rows"] += 1
                continue
            seen.add(key)
            opportunities.append(opp)
        stats["rejection_reasons"] = rejection_reasons
        if stats.get("csv_parse_errors"):
            stats["parse_outcome"] = "partial"
        if stats["parse_outcome"] == "ok":
            if stats["raw_rows"] == 0:
                stats["parse_outcome"] = "empty_valid"
            elif stats["valid_rows"] == 0:
                stats["parse_outcome"] = "partial"
        stats["unique_rows"] = len(opportunities)
        stats["displayed_rows"] = len(opportunities)
        stats["shortlist_capped"] = False
        return opportunities, stats
    finally:
        try:
            csv.field_size_limit(prior_field_limit)
        except (OverflowError, TypeError):
            pass


def scout_source_body(
    body: str,
    source: dict,
    *,
    today: Optional[date] = None,
    offline_replay: bool = False,
    snapshot_root: Optional[Path] = None,
) -> tuple[list[dict], dict]:
    """Parse one cached or replayed body without network."""
    fmt = source.get("format") or ""
    source_id = source["id"]
    if fmt == "canadabuys_csv":
        opps, stats = parse_opportunities_canadabuys_csv(
            body,
            source=source_id,
            page_url=source.get("url") or "",
            source_name=source.get("name") or source_id,
            source_kind=source.get("kind") or "tender",
            dataset_url=source.get("dataset_url") or source.get("url") or "",
            today=today,
        )
        how = "replay" if offline_replay else "body"
        feed = _feed_record_from_csv_parse(source, stats, how=how)
        text_hash = stats.get("body_text_sha256") or _sha256_text(body)
        feed["body_text_sha256"] = text_hash
        feed["body_bytes_sha256"] = ""
        feed["live_fetch"] = False
        feed["fetched_at"] = "unknown" if offline_replay else feed.get("fetched_at") or "unknown"
        feed["offline_replay"] = offline_replay
        parse_outcome = str(stats.get("parse_outcome") or "ok")
        acq = _apply_acquisition_stamp(
            opps,
            source=source,
            body=body,
            how=how,
            fetched_at=feed["fetched_at"],
            live_fetch=False,
            body_text_sha256=text_hash,
            body_bytes_sha256="",
            parse_outcome=parse_outcome,
            truncated=False,
            offline=offline_replay,
            snapshot_root=snapshot_root,
        )
        if acq.get("source_snapshot_ref"):
            feed["source_snapshot_ref"] = acq["source_snapshot_ref"]
        if acq.get("evidence_persistence_warning"):
            feed["evidence_persistence_warning"] = acq["evidence_persistence_warning"]
        return opps, feed
    opps = parse_opportunities_html(
        body,
        source=source_id,
        page_url=source.get("url") or "",
        source_name=source.get("name") or source_id,
        source_kind=source.get("kind") or "default",
    )
    feed = {
        "id": source_id,
        "name": source.get("name") or source_id,
        "url": source.get("url") or "",
        "status": "ok",
        "how": "replay" if offline_replay else "body",
        "error": "",
        "opportunities": len(opps),
        "parse_outcome": "ok" if opps else "empty_valid",
        "coverage_scope": source.get("coverage_scope") or "",
        "coverage_warning": _html_coverage_warning(source.get("kind") or ""),
        "transport_hardening": "unresolved",
    }
    return opps, feed


# Parse outcome to feed status. A failed parse is never reported as healthy.
_CSV_OUTCOME_STATUS = {
    "schema_drift": "schema_drift",
    "partial": "partial",
    "unsupported": "skipped",
    "fetch_error": "skipped",
}


def _feed_record_from_csv_parse(source: dict, stats: dict, *, how: str) -> dict:
    """Feed record from CSV parse stats. A failed parse is never a healthy zero."""
    outcome = stats.get("parse_outcome") or "ok"
    status = _CSV_OUTCOME_STATUS.get(outcome, "ok")
    return {
        "id": source["id"],
        "name": source.get("name") or source["id"],
        "url": source.get("url") or "",
        "status": status,
        "how": how,
        "error": "",
        "opportunities": stats.get("displayed_rows", 0),
        "parse_outcome": outcome,
        "raw_rows": stats.get("raw_rows", 0),
        "valid_rows": stats.get("valid_rows", 0),
        "rejected_rows": stats.get("rejected_rows", 0),
        "lens_matches": stats.get("lens_matches", 0),
        "displayed_rows": stats.get("displayed_rows", 0),
        "rows_capped": stats.get("rows_capped", False),
        "shortlist_capped": stats.get("shortlist_capped", False),
        "duplicate_rows": stats.get("duplicate_rows", 0),
        "unique_rows": stats.get("unique_rows", stats.get("displayed_rows", 0)),
        "identity_policy": stats.get("identity_policy") or "first_wins_by_source_and_id",
        "missing_headers": stats.get("missing_headers") or [],
        "rejection_reasons": stats.get("rejection_reasons") or {},
        "csv_parse_errors": stats.get("csv_parse_errors", 0),
        "parse_error": stats.get("parse_error") or "",
        "body_text_sha256": stats.get("body_text_sha256") or "",
        "coverage_scope": source.get("coverage_scope")
        or "federal_open_tenders_csv_only",
        "coverage_warning": (
            "Primary CSV covers federal open tender notices only; "
            "not all Canadian procurement or the full IDEaS HTML market."
        ),
        "transport_hardening": "unresolved",
        "source_kind": source.get("kind") or "tender",
        "source_format": source.get("format") or "canadabuys_csv",
    }


# ---------------------------------------------------------------------------
# §5 — Cache and fetch: polite, bounded, truncation-honest
#
# A cache entry older than CACHE_TTL_SECONDS is a miss. A truncated response
# is a partial feed, never a healthy zero.
# ---------------------------------------------------------------------------

def cache_file(cache_dir: Path, url: str) -> Path:
    """Cache path for a URL: sha256 of the URL, so no unsafe characters reach the disk."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return Path(cache_dir) / f"{digest}.json"


def _cache_fetched_at(value: object) -> Optional[datetime]:
    """Parse a cache timestamp. Unparseable stamps count as missing, never as fresh."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def cache_is_fresh(
    fetched_at: object,
    *,
    now: Optional[datetime] = None,
    ttl_seconds: Optional[float] = None,
) -> bool:
    """True when fetched_at is within TTL. Missing or unparseable stamps are stale."""
    stamp = _cache_fetched_at(fetched_at)
    if stamp is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    ttl = config.CACHE_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    return (current - stamp).total_seconds() <= ttl


def _header_value(headers: object, name: str) -> Optional[str]:
    """First present header value, with a case-insensitive fallback. None when absent."""
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(name)
        if value is not None:
            return value
        value = getter(name.lower())
        if value is not None:
            return value
    return None


def _response_charset(headers: object) -> str:
    """Charset from headers, defaulting to utf-8. Never raises on junk."""
    charset_getter = getattr(headers, "get_content_charset", None)
    if callable(charset_getter):
        charset = charset_getter()
        if charset:
            return charset
    content_type = _header_value(headers, "Content-Type") or ""
    match = re.search(r"charset=([^\s;]+)", content_type, flags=re.I)
    if match:
        return match.group(1).strip("\"'") or "utf-8"
    return "utf-8"


def read_cache_payload(
    cache_dir: Path, url: str, *, now: Optional[datetime] = None
) -> Optional[dict]:
    """Fresh cache payload or None. Expired or unreadable entries are misses, not errors."""
    path = cache_file(cache_dir, url)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("cache unreadable %s: %s", path.name, exc)
        return None
    if not isinstance(payload, dict):
        return None
    body = payload.get("body")
    if not isinstance(body, str) or payload.get("url") != url:
        return None
    if not cache_is_fresh(payload.get("fetched_at"), now=now):
        log.info("cache expired %s", path.name)
        return None
    return payload


def read_cache(cache_dir: Path, url: str, *, now: Optional[datetime] = None) -> Optional[str]:
    """Cached body or None."""
    payload = read_cache_payload(cache_dir, url, now=now)
    if payload is None:
        return None
    body = payload.get("body")
    return body if isinstance(body, str) else None


def write_cache(cache_dir: Path, url: str, body: str) -> None:
    """Atomic cache write: tmp file then replace, so readers never see a half write."""
    path = cache_file(cache_dir, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "body": body,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def fetch_url(
    url: str,
    cache_directory: Path,
    timeout: int = config.FETCH_TIMEOUT_SECONDS,
    max_bytes: Optional[int] = None,
) -> tuple[str, str]:
    """Return (body, how) where how is 'cache' or 'fetched'.

    A cache entry older than config.CACHE_TTL_SECONDS is a miss. The refetch
    overwrites that entry. Raises on network failure.
    """
    meta = fetch_url_with_meta(url, cache_directory, timeout=timeout, max_bytes=max_bytes)
    return meta["body"], meta["how"]


def fetch_url_with_meta(
    url: str,
    cache_directory: Path,
    timeout: int = config.FETCH_TIMEOUT_SECONDS,
    max_bytes: Optional[int] = None,
) -> dict:
    """Fetch or read cache; include byte/truncation metadata for feed health."""
    limit = max_bytes if max_bytes is not None else config.CACHE_MAX_BYTES
    cached_payload = read_cache_payload(cache_directory, url)
    if cached_payload is not None:
        cached = cached_payload.get("body")
        if isinstance(cached, str):
            return {
                "body": cached,
                "how": "cache",
                "truncated": False,
                "bytes_read": len(cached.encode("utf-8")),
                "content_length": None,
                "body_bytes_sha256": "",
                "body_text_sha256": _sha256_text(cached),
                "from_cache": True,
                "fetched_at": cached_payload.get("fetched_at"),
            }
    request = Request(
        url,
        headers={
            "User-Agent": config.USER_AGENT,
            "Accept": "text/csv,text/plain,application/json,text/html,application/xhtml+xml,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(limit + 1)
        truncated = len(raw) > limit
        if truncated:
            raw = raw[:limit]
        cl_header = _header_value(response.headers, "Content-Length")
        content_length = int(cl_header) if cl_header and str(cl_header).isdigit() else None
        if content_length is not None and content_length > len(raw):
            truncated = True
        charset = _response_charset(response.headers)
        body = raw.decode(charset, errors="replace")
    fetched_at = datetime.now(timezone.utc).isoformat()
    result = {
        "body": body,
        "how": "fetched",
        "truncated": truncated,
        "bytes_read": len(raw),
        "content_length": content_length,
        "body_bytes_sha256": _sha256_bytes(raw),
        "body_text_sha256": _sha256_text(body),
        "from_cache": False,
        "fetched_at": fetched_at,
    }
    if not truncated:
        try:
            write_cache(cache_directory, url, body)
        except OSError as exc:
            log.warning("cache write failed for %s: %s", url, exc)
    else:
        log.warning("fetch truncated %s at %s bytes (limit %s)", url, len(raw), limit)
    return result


Fetcher = Callable[[str, Path, int], tuple[str, str]]
Sleeper = Callable[[float], None]


def _is_transient(exc: BaseException) -> bool:
    """Timeouts and connection failures retry once. HTTP status errors do not."""
    if isinstance(exc, HTTPError):
        return False
    return isinstance(exc, (TimeoutError, URLError))


# ---------------------------------------------------------------------------
# §6 — Feed health and the scout run: one failure is a skipped feed
#
# The scout never raises for a dead source. Health is persisted per feed so
# a broken parser cannot masquerade as an empty market.
# ---------------------------------------------------------------------------

def scout_health_path(cache_directory: Path) -> Path:
    """Path of the per-feed last-success record."""
    return Path(cache_directory) / "scout-health.json"


def _load_scout_health(path: Path) -> dict:
    """Last-success map. Unreadable files start empty rather than failing the run."""
    if not path.exists():
        return {"feeds": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("scout health unreadable: %s", exc)
        return {"feeds": {}}
    feeds = payload.get("feeds") if isinstance(payload, dict) else None
    if not isinstance(feeds, dict):
        return {"feeds": {}}
    return {"feeds": feeds}


def _save_scout_health(path: Path, state: dict) -> None:
    """Atomic health write: tmp file then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _days_since(today: date, last_success: object) -> Optional[int]:
    """Days since an ISO date, or None when the last success is unknown."""
    if not isinstance(last_success, str) or not last_success:
        return None
    try:
        prior = date.fromisoformat(last_success)
    except ValueError:
        return None
    return (today - prior).days


def _days_phrase(days: Optional[int]) -> str:
    """Human phrase for a day count, for the health summary."""
    if days is None:
        return "never succeeded"
    if days == 1:
        return "1 day since last success"
    return f"{days} days since last success"


def summarize_scout_health(
    cache_directory: Path,
    feeds: list[dict],
    today: Optional[date] = None,
) -> dict:
    """Persist last success per feed and report how many eyes are open."""
    today = today or date.today()
    path = scout_health_path(cache_directory)
    stored = dict(_load_scout_health(path).get("feeds") or {})
    dead = []
    healthy = 0
    for feed in feeds:
        ident = str(feed.get("id") or "")
        prior = stored.get(ident) if isinstance(stored.get(ident), dict) else {}
        parse_outcome = feed.get("parse_outcome")
        healthy_parse = parse_outcome in (None, "ok", "empty_valid")
        if feed.get("status") == "ok" and healthy_parse:
            healthy += 1
            stored[ident] = {
                "last_success": today.isoformat(),
                "last_status": "ok",
                "last_error": "",
            }
            continue
        last_success = prior.get("last_success") if isinstance(prior, dict) else None
        days = _days_since(today, last_success)
        stored[ident] = {
            "last_success": last_success if isinstance(last_success, str) else None,
            "last_status": feed.get("status") or "skipped",
            "last_error": feed.get("error") or "",
        }
        dead.append(
            {
                "id": ident,
                "days_since_success": days,
                "error": feed.get("error") or "",
            }
        )
    try:
        _save_scout_health(path, {"feeds": stored})
    except OSError as exc:
        log.warning("scout health not saved: %s", exc)
    total = len(feeds)
    bits = [f"{item['id']} ({_days_phrase(item['days_since_success'])})" for item in dead]
    summary = f"{healthy} of {total} feeds healthy"
    if bits:
        summary = summary + "; dead: " + ", ".join(bits)
    return {
        "healthy": healthy,
        "total": total,
        "summary": summary,
        "dead": dead,
    }


def _skipped_feed(source_id: str, url: str, exc: BaseException) -> tuple[str, str, str, bool]:
    """A dead feed becomes a skipped record, never a raised error."""
    error = f"{type(exc).__name__}: {exc}"
    log.warning("skip feed %s %s (%s)", source_id, url, error)
    return "skipped", error, "error", True


def _attach_fetch_meta(feed: dict, fetch_meta: dict) -> None:
    """Copy byte/truncation metadata from the fetch onto the feed record."""
    feed["body_bytes_sha256"] = fetch_meta.get("body_bytes_sha256") or ""
    feed["body_text_sha256"] = fetch_meta.get("body_text_sha256") or ""
    feed["bytes_read"] = fetch_meta.get("bytes_read")
    feed["content_length"] = fetch_meta.get("content_length")


def _cache_hit_fetch_meta(body: str, fetched_at: object) -> dict:
    """Synthetic fetch metadata for a cache hit: nothing truncated, nothing fetched."""
    return {
        "truncated": False,
        "body_text_sha256": _sha256_text(body),
        "body_bytes_sha256": "",
        "bytes_read": len(body.encode("utf-8")),
        "content_length": None,
        "fetched_at": fetched_at,
        "from_cache": True,
    }


def _resolve_feed_fetched_at(fetch_meta: dict, how: str) -> str:
    """Prefer the fetch timestamp; a cache hit without one stays 'unknown'."""
    stamp = fetch_meta.get("fetched_at")
    if isinstance(stamp, str) and stamp.strip():
        return stamp
    if how == "cache":
        return "unknown"
    return stamp or datetime.now(timezone.utc).isoformat()


def _acquire_body(
    source: dict,
    url: str,
    *,
    cache_directory: Path,
    fetcher: Fetcher,
    sleeper: Sleeper,
    gap_seconds: float,
    attempt: int,
    pending_gap: bool,
) -> tuple[str, str, dict, bool]:
    """Return (body, how, fetch_meta, pending_gap). Raises on fetch failure."""
    source_format = source.get("format") or ""
    max_bytes = source.get("max_bytes")
    cached = read_cache(cache_directory, url)
    if attempt == 0 and cached is not None and fetcher is fetch_url:
        cache_payload = read_cache_payload(cache_directory, url) or {}
        return (
            cached,
            "cache",
            _cache_hit_fetch_meta(cached, cache_payload.get("fetched_at")),
            pending_gap,
        )
    if attempt == 0 and pending_gap:
        sleeper(gap_seconds)
    elif attempt > 0:
        sleeper(config.RETRY_BACKOFF_SECONDS)
    pending_gap = False
    if source_format == "canadabuys_csv":
        fetch_meta = fetch_url_with_meta(
            url,
            cache_directory,
            config.FETCH_TIMEOUT_SECONDS,
            max_bytes=max_bytes or config.CSV_MAX_BYTES,
        )
        body, how = fetch_meta["body"], fetch_meta["how"]
    else:
        body, how = fetcher(url, cache_directory, config.FETCH_TIMEOUT_SECONDS)
        fetch_meta = {
            "truncated": False,
            "body_text_sha256": _sha256_text(body),
            "body_bytes_sha256": "",
            "bytes_read": len(body.encode("utf-8")),
            "content_length": None,
        }
    if how == "fetched":
        pending_gap = True
    return body, how, fetch_meta, pending_gap


def _truncated_csv_feed(
    source: dict, how: str, fetch_meta: dict, max_bytes: Optional[int]
) -> tuple[list[dict], dict, str, str]:
    """A truncated response is a partial feed, never a parsed one."""
    error = (
        f"response truncated at {fetch_meta.get('bytes_read')} bytes "
        f"(limit {max_bytes or config.CSV_MAX_BYTES})"
    )
    csv_stats = {
        "parse_outcome": "partial",
        "truncated": True,
        "raw_rows": 0,
        "valid_rows": 0,
        "rejected_rows": 0,
        "lens_matches": 0,
        "displayed_rows": 0,
        "body_text_sha256": fetch_meta.get("body_text_sha256") or "",
    }
    feed_extra = _feed_record_from_csv_parse(source, csv_stats, how=how)
    _attach_fetch_meta(feed_extra, fetch_meta)
    feed_extra["status"] = "partial"
    feed_extra["error"] = error
    return [], feed_extra, "partial", error


def _parsed_csv_feed(
    source: dict,
    body: str,
    how: str,
    fetch_meta: dict,
    today: date,
    snapshot_root: Optional[Path],
) -> tuple[list[dict], dict, str, str]:
    """Parse one CSV body; stamp acquisition; decide feed status from the parse outcome."""
    url = source["url"]
    found, csv_stats = parse_opportunities_canadabuys_csv(
        body,
        source=source["id"],
        page_url=url,
        source_name=source.get("name") or source["id"],
        source_kind=source.get("kind") or "tender",
        dataset_url=source.get("dataset_url") or url,
        today=today,
    )
    feed_extra = _feed_record_from_csv_parse(source, csv_stats, how=how)
    _attach_fetch_meta(feed_extra, fetch_meta)
    feed_extra["fetched_at"] = _resolve_feed_fetched_at(fetch_meta, how)
    feed_extra["live_fetch"] = how == "fetched"
    if csv_stats.get("parse_outcome") == "schema_drift":
        status = "schema_drift"
        error = "missing headers: " + ", ".join(csv_stats.get("missing_headers") or [])
    elif csv_stats.get("parse_outcome") == "partial":
        status = "partial"
        if csv_stats.get("csv_parse_errors"):
            error = "csv parse error: " + (csv_stats.get("parse_error") or "malformed record")
        else:
            error = "row or byte cap hit during parse"
    else:
        status = feed_extra.get("status") or "ok"
        error = ""
    feed_extra["status"] = status
    feed_extra["error"] = error
    _apply_acquisition_stamp(
        found,
        source=source,
        body=body,
        how=how,
        fetched_at=feed_extra.get("fetched_at"),
        live_fetch=how == "fetched",
        body_text_sha256=feed_extra.get("body_text_sha256") or _sha256_text(body),
        body_bytes_sha256=feed_extra.get("body_bytes_sha256") or "",
        parse_outcome=str(feed_extra.get("parse_outcome") or "ok"),
        truncated=bool(fetch_meta.get("truncated")),
        offline=False,
        snapshot_root=snapshot_root,
    )
    ref = (found[0].get("source_snapshot_ref") if found else "") or ""
    if ref:
        feed_extra["source_snapshot_ref"] = ref
    warn = (found[0].get("evidence_persistence_warning") if found else "") or ""
    if warn:
        feed_extra["evidence_persistence_warning"] = warn
    return found, feed_extra, status, error


def _scout_csv_source(
    source: dict,
    body: str,
    how: str,
    fetch_meta: dict,
    today: date,
    snapshot_root: Optional[Path],
) -> tuple[list[dict], dict, str, str]:
    """Handle one CanadaBuys CSV body. Returns (found, feed, status, error)."""
    if fetch_meta.get("truncated"):
        return _truncated_csv_feed(source, how, fetch_meta, source.get("max_bytes"))
    return _parsed_csv_feed(source, body, how, fetch_meta, today, snapshot_root)


def _scout_html_source(source: dict, body: str) -> tuple[list[dict], str, str]:
    """Parse one HTML body. Zero rows is logged, never treated as failure."""
    found = parse_opportunities_html(
        body,
        source=source["id"],
        page_url=source["url"],
        source_name=source.get("name") or source["id"],
        source_kind=source.get("kind") or "default",
    )
    if not found:
        log.warning(
            "feed %s parsed 0 opportunities (page shape may have changed or no lens hit)",
            source["id"],
        )
    return found, "ok", ""


def _scout_source(
    source: dict,
    *,
    cache_directory: Path,
    fetcher: Fetcher,
    sleeper: Sleeper,
    gap_seconds: float,
    today: date,
    snapshot_root: Optional[Path],
    pending_gap: bool,
) -> tuple[list[dict], Optional[dict], str, str, str, bool]:
    """Fetch and parse one source, with one retry on transient failure.

    Never raises: failures become skipped feeds. Returns
    (found, feed_extra, status, error, how, pending_gap).
    """
    url = source["url"]
    attempt = 0
    while True:
        try:
            body, how, fetch_meta, pending_gap = _acquire_body(
                source,
                url,
                cache_directory=cache_directory,
                fetcher=fetcher,
                sleeper=sleeper,
                gap_seconds=gap_seconds,
                attempt=attempt,
                pending_gap=pending_gap,
            )
            if (source.get("format") or "") == "canadabuys_csv":
                found, feed_extra, status, error = _scout_csv_source(
                    source, body, how, fetch_meta, today, snapshot_root
                )
            else:
                found, status, error = _scout_html_source(source, body)
                feed_extra = None
            return found, feed_extra, status, error, how, pending_gap
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            if attempt < 1 and _is_transient(exc):
                attempt += 1
                log.warning("retry feed %s after transient %s", source["id"], exc)
                continue
            status, error, how, pending_gap = _skipped_feed(source["id"], url, exc)
            return [], None, status, error, how, pending_gap
        except Exception as exc:
            status, error, how, pending_gap = _skipped_feed(source["id"], url, exc)
            return [], None, status, error, how, pending_gap


def _html_coverage_warning(source_kind: str) -> str:
    """Caveat carried by HTML feed records whose shape the parser reads heuristically.

    Zero rows from an HTML page is a parse outcome, never proof of a
    healthy empty market. Program pages get the same warning as listing
    pages: the section fallback is a reader for one documented page shape
    (DESIGN-v2 §3), not a coverage guarantee.
    """
    if source_kind in config.LISTING_KINDS:
        shape = "listing"
    elif source_kind == "program":
        shape = "program-page"
    else:
        return ""
    return (
        f"HTML {shape} parse; zero rows is not proof of a healthy empty market "
        "when fetch/parse support is unresolved."
    )


def _html_feed_record(
    source: dict, url: str, found: list[dict], status: str, error: str, how: str
) -> dict:
    """Feed record for an HTML source. Zero rows is empty_valid, never proof of coverage."""
    return {
        "id": source["id"],
        "name": source.get("name") or source["id"],
        "url": url,
        "status": status,
        "how": how,
        "error": error,
        "opportunities": len(found),
        "parse_outcome": "empty_valid" if status == "ok" and not found else "ok",
        "coverage_scope": source.get("coverage_scope") or "",
        "coverage_warning": _html_coverage_warning(source.get("kind") or ""),
        "transport_hardening": "unresolved",
    }


def scout(
    sources: Optional[Union[tuple[dict, ...], list[dict]]] = None,
    cache_directory: Optional[Path] = None,
    fetcher: Optional[Fetcher] = None,
    sleeper: Optional[Sleeper] = None,
    gap_seconds: float = config.FETCH_GAP_SECONDS,
    today: Optional[date] = None,
    snapshot_root: Optional[Path] = None,
) -> dict:
    """Fetch each source. One failure is a skipped feed, never a raised error.

    A TimeoutError or URLError is retried once after RETRY_BACKOFF_SECONDS.
    HTTP errors are not retried. The return value includes a health summary.
    """
    sources = list(sources if sources is not None else config.SOURCES)
    cache_directory = Path(cache_directory) if cache_directory is not None else config.cache_dir()
    cache_directory.mkdir(parents=True, exist_ok=True)
    fetcher = fetcher or fetch_url
    sleeper = sleeper or time.sleep
    today = today or date.today()
    feeds = []
    opportunities = []
    pending_gap = False
    for source in sources:
        found, feed_extra, status, error, how, pending_gap = _scout_source(
            source,
            cache_directory=cache_directory,
            fetcher=fetcher,
            sleeper=sleeper,
            gap_seconds=gap_seconds,
            today=today,
            snapshot_root=snapshot_root,
            pending_gap=pending_gap,
        )
        if (source.get("format") or "") == "canadabuys_csv" and feed_extra is not None:
            feeds.append(feed_extra)
        else:
            feeds.append(_html_feed_record(source, source["url"], found, status, error, how))
        opportunities.extend(found)
    health = summarize_scout_health(cache_directory, feeds, today=today)
    return {"opportunities": opportunities, "feeds": feeds, "health": health}
