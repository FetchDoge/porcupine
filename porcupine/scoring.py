"""Expected-value scoring.

EV = funding × portfolio_fit × reachability − effort

portfolio_fit and reachability sit on 0–1 and are built only from named inputs:
matched assurance keywords, moat signal hits, source kind, the deadline field,
and a parsed TRL when one is present. TRL adds TRL_FIT_BUMP for component 1a
or 1b. It does not change the open/closed boolean.
p_win is a Wilson lower bound. With n = 0 the bound is 0, so an unproven
opportunity does not receive a positive win probability. Callers pass
p_win_n and p_win_successes from recorded outcomes. A parsed TRL maps to an
IDEaS component and adds that component's fit bump. It does not invent a deadline.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Optional

from . import config
from .moat import map_moat
from .radar import match_keywords, opportunity_text


def expected_value(
    funding: float,
    portfolio_fit: float,
    reachability: float,
    effort: float,
) -> float:
    return (funding * portfolio_fit * reachability) - effort


def wilson_lower_bound(successes: float, n: int, z: float = config.WILSON_Z) -> float:
    """Lower end of the Wilson interval. n = 0 returns 0.0 without dividing."""
    if n <= 0:
        return 0.0
    total = float(n)
    phat = max(0.0, min(1.0, float(successes) / total))
    z2 = z * z
    denom = 1.0 + z2 / total
    centre = phat + z2 / (2.0 * total)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * total)) / total)
    lower = (centre - margin) / denom
    return max(0.0, min(1.0, lower))


def component_for_trl(trl: Optional[str]) -> Optional[str]:
    """Map a parsed TRL token to an IDEaS component. None when TRL is absent or unusable.

    The low end of a range is the door: 1-3 is component 1a, 4-6 is 1b, 7-9 is 2.
    """
    if trl is None or not str(trl).strip():
        return None
    nums = []
    for part in str(trl).replace("–", "-").split("-"):
        part = part.strip()
        if part.isdigit():
            nums.append(int(part))
    if not nums:
        return None
    low = min(nums)
    if low < 1 or low > 9:
        return None
    if low <= 3:
        return "1a"
    if low <= 6:
        return "1b"
    return "2"


def portfolio_fit_score(assurance_hits: int, moat_strength: float) -> float:
    saturation = config.ASSURANCE_DENSITY_SATURATION
    density = min(1.0, assurance_hits / saturation) if saturation else 0.0
    fit = (config.FIT_KEYWORD_WEIGHT * density) + (config.FIT_MOAT_WEIGHT * moat_strength)
    return max(0.0, min(1.0, fit))


def _with_trl(trace: str, opp: dict) -> str:
    component = component_for_trl(opp.get("trl"))
    if not component:
        return trace
    bump = config.TRL_FIT_BUMP.get(component, 0.0)
    return f"{trace}; trl_component={component} TRL_FIT_BUMP={bump:g} trl={opp.get('trl')}"


def reachability_score(opp: dict, today: date) -> tuple[float, str]:
    kind = opp.get("source_kind") or "default"
    if kind == "award":
        return (
            config.REACHABILITY["closed"],
            _with_trl("reachability=config.REACHABILITY.closed (source_kind=award)", opp),
        )
    deadline = opp.get("deadline")
    if deadline:
        try:
            closed = date.fromisoformat(str(deadline)) < today
        except ValueError:
            closed = False
            deadline = None
        if deadline and closed:
            return (
                config.REACHABILITY["closed"],
                _with_trl(
                    f"reachability=config.REACHABILITY.closed (deadline {opp.get('deadline')} before {today.isoformat()})",
                    opp,
                ),
            )
        if deadline and not closed:
            return (
                config.REACHABILITY["deadline_future"],
                _with_trl(
                    f"reachability=config.REACHABILITY.deadline_future (deadline {deadline})",
                    opp,
                ),
            )
    if kind == "job_board":
        return (
            config.REACHABILITY["job_board"],
            _with_trl(
                "reachability=config.REACHABILITY.job_board (no deadline on a job board)",
                opp,
            ),
        )
    return (
        config.REACHABILITY["deadline_absent"],
        _with_trl("reachability=config.REACHABILITY.deadline_absent", opp),
    )


def openness(opp: dict, today: date) -> Optional[bool]:
    """True when the deadline is still ahead, False when closed or an award, None if unknown.

    A parsed TRL selects the IDEaS component used in portfolio_fit. It is not a
    close date: component 1a still needs a future deadline before the call is open,
    and a missing deadline stays unknown.
    """
    if (opp.get("source_kind") or "") == "award":
        return False
    deadline = opp.get("deadline")
    if not deadline:
        return None
    try:
        return date.fromisoformat(str(deadline)) >= today
    except ValueError:
        return None


def _assurance_hits(opp: dict) -> list[str]:
    text = opportunity_text(opp)
    matched = match_keywords(text)
    if not matched and opp.get("raw_keywords_matched"):
        matched = [item for item in opp["raw_keywords_matched"] if item in config.KEYWORD_LENS]
    return [item for item in matched if item in config.ASSURANCE_CORE]


def score_opportunity(
    opp: dict,
    moat: Optional[dict] = None,
    today: Optional[date] = None,
    p_win_successes: float = 0.0,
    p_win_n: int = 0,
) -> dict:
    today = today or date.today()
    moat = moat if moat is not None else map_moat(opp)
    hits = _assurance_hits(opp)
    component = component_for_trl(opp.get("trl"))
    bump = float(config.TRL_FIT_BUMP.get(component, 0.0)) if component else 0.0
    fit = portfolio_fit_score(len(hits), float(moat.get("moat_strength") or 0.0))
    if bump:
        fit = max(0.0, min(1.0, fit + bump))
    reach, reach_trace = reachability_score(opp, today)
    funding = opp.get("funding")
    funding_for_ev = float(funding) if isinstance(funding, (int, float)) else 0.0
    funding_trace = opp.get("funding_trace") or (
        "funding_field=absent" if funding is None else f"funding_field={funding}"
    )
    kind = opp.get("source_kind") or "default"
    effort = float(config.EFFORT_CAD.get(kind, config.EFFORT_CAD["default"]))
    ev = expected_value(funding_for_ev, fit, reach, effort)
    lcb = wilson_lower_bound(p_win_successes, p_win_n)
    # Conservative dollar figure. When n = 0 this is 0 × funding − effort.
    ev_at_lcb = (funding_for_ev * lcb) - effort
    open_state = openness(opp, today)
    strongest = moat.get("strongest_repo") or "(none)"
    formula = (
        f"ev = {funding_for_ev:g} * {fit:.4f} * {reach:.2f} - {effort:g} = {ev:.2f}"
        f" ; funding uses 0 when the page stated no dollar amount"
    )
    return {
        "ev": ev,
        "ev_at_wilson_lcb": ev_at_lcb,
        "portfolio_fit": fit,
        "reachability": reach,
        "funding": funding if isinstance(funding, (int, float)) else None,
        "funding_for_ev": funding_for_ev,
        "effort": effort,
        "p_win_lcb": lcb,
        "p_win_n": int(p_win_n),
        "p_win_successes": float(p_win_successes),
        "open": open_state,
        "trl_component": component,
        "high_fit": fit >= config.HIGH_FIT_MIN and len(hits) > 0,
        "formula": formula,
        "traces": {
            "funding": funding_trace,
            "effort": f"config.EFFORT_CAD.{kind if kind in config.EFFORT_CAD else 'default'}",
            "assurance_hits": ", ".join(hits) if hits else "(none)",
            "assurance_density": (
                f"{len(hits)} / config.ASSURANCE_DENSITY_SATURATION"
                f"({config.ASSURANCE_DENSITY_SATURATION})"
            ),
            "moat_strength": f"{float(moat.get('moat_strength') or 0.0):.2f} max repo {strongest}",
            "portfolio_fit": (
                f"{config.FIT_KEYWORD_WEIGHT}*density + {config.FIT_MOAT_WEIGHT}*moat_strength"
                + (
                    f" + TRL_FIT_BUMP.{component}({bump:g})"
                    if component
                    else ""
                )
            ),
            "reachability": reach_trace,
            "p_win_lcb": (
                f"wilson_lower_bound(successes={p_win_successes}, n={p_win_n})"
                + (" = 0 because n=0" if int(p_win_n) <= 0 else "")
            ),
            "deadline": opp.get("deadline_trace") or "deadline_absent",
        },
    }


def rank_scores(rows: list[dict]) -> list[dict]:
    """Descending EV, then portfolio_fit, then id. Stable and deterministic."""
    return sorted(
        rows,
        key=lambda row: (
            -float(row.get("ev") or 0.0),
            -float(row.get("portfolio_fit") or 0.0),
            str(row.get("id") or ""),
        ),
    )
