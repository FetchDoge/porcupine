"""Heilmeier-catechism program concepts.

Pre-filled from the opportunity text and the moat paragraph.
Anything the page did not state is marked [TO VERIFY].
The file is a draft. Nothing in this module submits, applies, or clicks.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from .moat import map_moat
from .radar import sanitize_markdown
from .scoring import score_opportunity

SECTIONS = (
    "What are you trying to do?",
    "How is it done today?",
    "What is new and why will it succeed?",
    "Who cares?",
    "What are the risks?",
    "How much will it cost and how long?",
    "Mid-term + final exams (milestones)",
)


def _excerpt(text: str, limit: int = 500) -> str:
    """Collapsed excerpt, or a [TO VERIFY] marker when the text is empty."""
    clean = " ".join((text or "").split())
    if not clean:
        return "[TO VERIFY] the challenge text was empty after parsing."
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _status_line(open_state: Optional[bool]) -> str:
    """One status sentence. Unverified open state is never written as open."""
    if open_state is True:
        return "Deadline on the parsed page is still ahead. [TO VERIFY] the notice has not been amended or withdrawn."
    if open_state is False:
        return (
            "CLOSED on the parsed evidence (deadline already past, or the source is an award notice). "
            "This file is a historical record. It is not a proposal."
        )
    return (
        "OPEN STATUS UNVERIFIED. No deadline was parsed. "
        "[TO VERIFY] the notice is actually open before anyone treats this as a live concept."
    )


def render_heilmeier(
    opp: dict,
    moat: Optional[dict] = None,
    score: Optional[dict] = None,
    today: Optional[date] = None,
) -> str:
    """Render a Heilmeier concept draft. Anything unstated stays [TO VERIFY]; nothing is submitted."""
    today = today or date.today()
    moat = moat if moat is not None else map_moat(opp)
    score = score if score is not None else score_opportunity(opp, moat=moat, today=today)
    title = sanitize_markdown(" ".join(str(opp.get("title") or "").split()))
    if not title:
        title = "[TO VERIFY] untitled opportunity"
    raw_description = str(opp.get("description") or "")
    if raw_description.strip():
        description = sanitize_markdown(_excerpt(raw_description))
    else:
        description = _excerpt(raw_description)
    paragraph = moat.get("paragraph") or "[TO VERIFY] no moat paragraph was produced."
    funding = opp.get("funding")
    if isinstance(funding, (int, float)):
        funding_line = (
            f"The page states a figure traced as {opp.get('funding_trace') or funding}. "
            "That number is the page's number, not a promise of an award."
        )
    else:
        funding_line = (
            "[TO VERIFY] no dollar amount was written on the parsed page. "
            "A program ceiling from memory is not filled in here."
        )
    deadline = opp.get("deadline") or "[TO VERIFY] no deadline was parsed"
    trl = opp.get("trl") or "[TO VERIFY] no TRL was parsed"
    effort = score.get("effort")
    if isinstance(effort, (int, float)):
        effort_name = (score.get("traces") or {}).get("effort", "config.EFFORT_CAD")
        effort_line = (
            f"Pursuit effort subtracted in the EV formula is {effort:g} CAD "
            f"({effort_name}). "
            "That constant is a planning cost, not a price quoted by the buyer. "
            "[TO VERIFY] actual effort."
        )
    else:
        effort_line = "[TO VERIFY] pursuit effort was not scored."
    lcb = score.get("p_win_lcb")
    n_wins = int(score.get("p_win_n") or 0)
    successes = score.get("p_win_successes")
    if n_wins <= 0:
        win_line = (
            "Win probability is the Wilson lower bound p_win_lcb=0 on n=0 recorded outcomes. "
            "With n=0 the bound is 0. An unproven opportunity does not get a positive win probability "
            "from keyword overlap. [TO VERIFY] any private win history before someone treats EV as money."
        )
    else:
        win_line = (
            f"Win probability is the Wilson lower bound p_win_lcb={lcb} "
            f"on n={n_wins} recorded outcomes (successes={successes}). "
            "[TO VERIFY] ledger/p_win.json before someone treats EV as money."
        )
    keywords = ", ".join(opp.get("raw_keywords_matched") or []) or "(none matched)"
    source = opp.get("source_name") or opp.get("source") or "[TO VERIFY] source"
    url = opp.get("url") or "[TO VERIFY] url"
    open_state = score.get("open")
    if open_state is False:
        banner = "CLOSED RECORD — NOT A PROPOSAL"
    elif open_state is True:
        banner = "DRAFT ONLY — deadline parsed as still open"
    else:
        banner = "DRAFT ONLY — open status unverified"
    lines = [
        f"# {title}",
        "",
        f"**{banner}.** PORCUPINE writes this concept and stops. It does not submit, apply, or click.",
        "",
        f"- Source: {source}",
        f"- URL: {url}",
        f"- Parsed deadline: {deadline}",
        f"- Parsed TRL: {trl}",
        f"- Lens keywords: {keywords}",
        f"- Status: {_status_line(open_state)}",
        "",
        f"## {SECTIONS[0]}",
        "",
        f"Stand up an assurance layer for: {title}.",
        "",
        description,
        "",
        paragraph,
        "",
        "## " + SECTIONS[1],
        "",
        "Current practice, as this radar is built to see it, is a capability vendor shipping the "
        "vehicle, sensor, or model, with trust argued afterwards. [TO VERIFY] that this is what "
        "the challenge text itself says about today's practice. The parsed text is:",
        "",
        description,
        "",
        "## " + SECTIONS[2],
        "",
        paragraph,
        "",
        "The new part is architectural: fail-closed execution, operator-held provenance, and an "
        "independent conformance check. It succeeds only if those properties are the ones the "
        "challenge's desired outcomes actually name. [TO VERIFY] against the full statement of work, "
        "not against this keyword pass.",
        "",
        "## " + SECTIONS[3],
        "",
        f"The parsed source is {source}. The audience is whoever issued that page "
        "(for an IDEaS or CanadaBuys notice, that is a DND/CAF buyer; for a Calgary job page, "
        "that is the firm hiring the missing software layer). [TO VERIFY] the real sponsor, "
        "the evaluation criteria, and whether a civilian assurance stack is in scope.",
        "",
        "Who does not need another airframe from this draft: capability shops already building "
        "the drone, sensor, or model. The useful relationship is complementary. [TO VERIFY] "
        "there is a buyer for that complement.",
        "",
        "## " + SECTIONS[4],
        "",
        _status_line(open_state),
        "",
        win_line,
        "",
        "Keyword fit can fire on a shared word and miss the actual problem. "
        "[TO VERIFY] by reading the source page.",
        "",
        "A closed challenge must not be rewritten as a live submission. If the status line says "
        "closed, stop.",
        "",
        "## " + SECTIONS[5],
        "",
        funding_line,
        "",
        effort_line,
        "",
        "Duration is not stated unless the page stated it. [TO VERIFY] the performance period "
        "and which IDEaS component, if any, the notice actually names. This draft does not "
        "copy a component ceiling onto a page that did not print one.",
        "",
        "## " + SECTIONS[6],
        "",
        "Mid-term exam: a replay, on a fixture taken from the challenge text, that shows the "
        "provenance chain and the fail-closed stop. [TO VERIFY] the fixture the buyer will accept.",
        "",
        "Final exam: an independent conformance run against the buyer's stated rules, with the "
        "vendor outside the trust path. [TO VERIFY] the rule set and the examiner. No calendar "
        "dates are invented here.",
        "",
        "---",
        "",
        "Positioning note only: the public portfolio can carry the Canadian agent-assurance "
        "narrative. This file does not publish anything.",
        "",
    ]
    return "\n".join(lines)
