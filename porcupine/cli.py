"""PORCUPINE command line.

    python3 -m porcupine.cli run
    python3 -m porcupine.cli top 10
    python3 -m porcupine.cli draft <id>
    python3 -m porcupine.cli record-win
    python3 -m porcupine.cli report

`run` scouts, scores, ranks, records, and auto-drafts only a matched portfolio row
that is confirmed-open. Zero high-fit open matches is a finished run.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from . import __version__, config
from .draft import render_heilmeier
from .ledger import Ledger
from .journal import Journal
from .moat import map_moat
from .radar import sanitize_markdown, scout, scout_source_body
from .scope import CLASS_OUT, CLASS_WHITE_SPACE, classify
from .scoring import rank_scores, score_opportunity, wilson_lower_bound

HELP = """PORCUPINE {version} — assurance radar. Drafts and records. Does not submit.

Commands:
  run           scout, score, rank, auto-draft top matched+open row, record
  top [N]       print the top N ledger rows by EV (default 10)
  draft <id>    write a Heilmeier draft for one recorded opportunity id
  record-win    increment global win counter (not a verified learning loop)
  report        counts from the ledger and the last run
  replay-csv    offline CSV parse (--file PATH --root DIR)
  journal       log decisions/outcomes or verify the hash chain

""".format(version=__version__)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe(value: str) -> str:
    cleaned = []
    for char in value:
        if char.isalnum() or char in "._-":
            cleaned.append(char)
        else:
            cleaned.append("_")
    text = "".join(cleaned).strip("_") or "item"
    return text[:80]


def _open_label(value: Optional[bool]) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unverified"


def p_win_path(root: Optional[Path] = None) -> Path:
    return config.ledger_path(root).with_name("p_win.json")


def load_p_win(root: Optional[Path] = None) -> dict:
    """Recorded outcomes. A missing or unreadable file is n=0, successes=0."""
    path = p_win_path(root)
    empty = {"p_win_n": 0, "p_win_successes": 0.0}
    if not path.exists():
        return empty
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(payload, dict):
        return empty
    try:
        n = int(payload.get("p_win_n") or 0)
        successes = float(payload.get("p_win_successes") or 0.0)
    except (TypeError, ValueError):
        return empty
    if n < 0:
        n = 0
    successes = max(0.0, min(float(n), successes))
    return {"p_win_n": n, "p_win_successes": successes}


def record_win(root: Optional[Path] = None) -> dict:
    """Persist one win. n and successes both increase by 1."""
    current = load_p_win(root)
    updated = {
        "p_win_n": int(current["p_win_n"]) + 1,
        "p_win_successes": float(current["p_win_successes"]) + 1.0,
        "updated_at": _now(),
    }
    path = p_win_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return {
        "p_win_n": updated["p_win_n"],
        "p_win_successes": updated["p_win_successes"],
    }


def _publisher_closed_status(status: str) -> bool:
    token = (status or "").strip().lower()
    if not token or token == "open":
        return False
    if token in ("closed", "cancelled", "canceled", "awarded", "award", "terminated", "expired"):
        return True
    return "closed" in token or "cancel" in token


def _publisher_explicit_open(status: str) -> bool:
    return (status or "").strip().lower() == "open"


def _is_canadabuys_csv_row(opp: dict) -> bool:
    return (opp.get("source_format") or "") == "canadabuys_csv"


def _csv_close_date_invalid(opp: dict) -> bool:
    close_at = str(opp.get("close_at") or "").strip()
    if not close_at:
        return False
    return opp.get("deadline") is None


def _same_day_close_unresolved(opp: dict, today: date) -> bool:
    close_at = str(opp.get("close_at") or "")
    if "T" not in close_at:
        return False
    if opp.get("close_timezone") not in (None, "", "unknown"):
        return False
    deadline = opp.get("deadline")
    if not deadline:
        return False
    try:
        return date.fromisoformat(str(deadline)) == today
    except ValueError:
        return False


def _actionable_open(opp: dict, score_open: Optional[bool], today: date) -> Optional[bool]:
    """Apply publisher status and CSV contradiction rules on top of scoring.open."""
    if _publisher_closed_status(str(opp.get("source_status") or "")):
        return False
    if opp.get("status_contradiction"):
        return False
    if _is_canadabuys_csv_row(opp):
        if _csv_close_date_invalid(opp):
            return False
        status = str(opp.get("source_status") or "").strip()
        if score_open is True and not _publisher_explicit_open(status):
            return None
    if score_open is not True:
        return score_open
    if _same_day_close_unresolved(opp, today):
        return None
    return True


def apply_display_shortlist(
    rows: list[dict],
    cap: int = config.MAX_OPPS_PER_FEED,
) -> tuple[list[dict], dict]:
    """Ranked rows are already ordered; cap only what operators see in ranked output."""
    capped = len(rows) > cap
    shown = rows[: max(0, cap)]
    matched = sum(1 for row in rows if row.get("disposition") == "matched")
    return shown, {
        "candidate_rows": len(rows),
        "displayed_rows": len(shown),
        "matched_rows": matched,
        "shortlist_capped": capped,
    }


def per_source_run_counts(
    candidate_rows: list[dict],
    source_id: str,
    cap: int = config.MAX_OPPS_PER_FEED,
) -> dict:
    """Per-feed scored counts; do not mirror global shortlist onto every feed."""
    subset = [row for row in candidate_rows if str(row.get("source") or "") == source_id]
    _shown, meta = apply_display_shortlist(subset, cap=cap)
    return meta


def assemble(
    opportunities: list[dict],
    today: Optional[date] = None,
    root: Optional[Path] = None,
) -> list[dict]:
    today = today or date.today()
    recorded = load_p_win(root)
    rows = []
    for opp in opportunities:
        moat = map_moat(opp)
        scope = classify(opp)
        score = score_opportunity(
            opp,
            moat=moat,
            today=today,
            p_win_successes=recorded["p_win_successes"],
            p_win_n=recorded["p_win_n"],
        )
        white = scope["classification"] == CLASS_WHITE_SPACE
        fit = float(score["portfolio_fit"])
        confirmed_open = _actionable_open(opp, score["open"], today) is True
        if scope["classification"] == CLASS_OUT:
            disposition = "rejected"
        elif white and fit >= config.MATCHED_FIT_MIN and confirmed_open:
            disposition = "matched"
        else:
            disposition = "near-miss"
        high_fit = white and fit >= config.HIGH_FIT_MIN and confirmed_open
        open_value = _actionable_open(opp, score["open"], today)
        rows.append(
            {
                "record_type": "opportunity",
                "source": opp.get("source") or "",
                "id": opp.get("id") or "",
                "recorded_at": _now(),
                "disposition": disposition,
                "classification": scope["classification"],
                "classification_reason": scope["reason"],
                "title": opp.get("title") or "",
                "url": opp.get("url") or "",
                "source_name": opp.get("source_name") or opp.get("source") or "",
                "source_kind": opp.get("source_kind") or "default",
                "funding": score["funding"],
                "funding_trace": opp.get("funding_trace") or score["traces"]["funding"],
                "trl": opp.get("trl"),
                "deadline": opp.get("deadline"),
                "deadline_trace": opp.get("deadline_trace"),
                "close_at": opp.get("close_at"),
                "close_timezone": opp.get("close_timezone"),
                "source_status": opp.get("source_status"),
                "status_contradiction": opp.get("status_contradiction"),
                "reference_number": opp.get("reference_number"),
                "solicitation_number": opp.get("solicitation_number"),
                "publication_date": opp.get("publication_date"),
                "source_dataset_url": opp.get("source_dataset_url"),
                "source_format": opp.get("source_format"),
                "detail_url_unknown": opp.get("detail_url_unknown"),
                "fetched_at": opp.get("fetched_at"),
                "acquisition_how": opp.get("acquisition_how"),
                "live_fetch": opp.get("live_fetch"),
                "body_text_sha256": opp.get("body_text_sha256"),
                "body_bytes_sha256": opp.get("body_bytes_sha256"),
                "source_snapshot_ref": opp.get("source_snapshot_ref"),
                "source_snapshot_meta_ref": opp.get("source_snapshot_meta_ref"),
                "evidence_persistence_warning": opp.get("evidence_persistence_warning"),
                "open": open_value,
                "description": opp.get("description") or "",
                "raw_keywords_matched": list(opp.get("raw_keywords_matched") or []),
                "capability_markers": list(opp.get("capability_markers") or []),
                "ev": score["ev"],
                "ev_label": "heuristic_priority_uncalibrated",
                "ev_at_wilson_lcb": score["ev_at_wilson_lcb"],
                "portfolio_fit": score["portfolio_fit"],
                "reachability": score["reachability"],
                "effort": score["effort"],
                "p_win_lcb": score["p_win_lcb"],
                "p_win_n": score["p_win_n"],
                "p_win_successes": score["p_win_successes"],
                "trl_component": score.get("trl_component"),
                "high_fit": high_fit,
                "formula": score["formula"],
                "traces": score["traces"],
                "moat_paragraph": moat.get("paragraph") or "",
                "high_repos": list(moat.get("high_repos") or []),
                "blind_spot_ids": [item["id"] for item in scope.get("blind_spots") or []],
            }
        )
    return rank_scores(rows)


def unused_note(row: dict) -> str:
    if row["classification"] == "capability-saturated":
        spots = ", ".join(row.get("blind_spot_ids") or []) or "capability-vs-assurance"
        return (
            "Capability-saturated. Recorded and deprioritized. "
            f"Blind-spot rows: {spots}. Not drafted as a primary concept."
        )
    if row["open"] is False:
        return "Closed or award notice. Kept as unused material so it is not drafted as a live proposal."
    if row["classification"] == "out-of-lens":
        return "Out of lens. Rejected as a target."
    if row["classification"] == "adjacent":
        return "Lens context without an assurance-core keyword. Near-miss, not a moat claim."
    if row["open"] is None:
        return "Assurance language without a parsed deadline. Unused until someone confirms it is open."
    return "Below the matched-fit bar. Kept for a later challenge cycle."


def format_table(rows: list[dict]) -> str:
    header = (
        f"{'rk':>3}  {'ev':>12}  {'fit':>5}  {'reach':>5}  {'p_lcb':>6}  "
        f"{'open':<10}  {'disp':<9}  {'class':<22}  {'source':<22}  title"
    )
    lines = [header]
    if not rows:
        lines.append("(no opportunities)")
        return "\n".join(lines)
    for index, row in enumerate(rows, 1):
        title = sanitize_markdown(" ".join(str(row.get("title") or "").split())[:64])
        lines.append(
            f"{index:>3}  {float(row.get('ev') or 0):12.0f}  "
            f"{float(row.get('portfolio_fit') or 0):5.2f}  "
            f"{float(row.get('reachability') or 0):5.2f}  "
            f"{float(row.get('p_win_lcb') or 0):6.3f}  "
            f"{_open_label(row.get('open')):<10}  "
            f"{str(row.get('disposition') or ''):<9}  "
            f"{str(row.get('classification') or ''):<22}  "
            f"{str(row.get('source') or ''):<22}  {title}"
        )
    return "\n".join(lines)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _record(ledger: Ledger, rows: list[dict]) -> dict:
    batch: list[dict] = []
    for row in rows:
        batch.append(row)
        if row["disposition"] in ("near-miss", "rejected"):
            batch.append(
                {
                    "record_type": "unused_material",
                    "source": row["source"],
                    "id": f"unused:{row['id']}",
                    "parent_id": row["id"],
                    "recorded_at": row["recorded_at"],
                    "title": row["title"],
                    "note": unused_note(row),
                    "disposition": row["disposition"],
                    "classification": row["classification"],
                }
            )
    appended = 0
    existed = 0
    for result in ledger.append_many(batch):
        if result["written"]:
            appended += 1
        else:
            existed += 1
    return {"appended": appended, "already_recorded": existed}


def _draft_open(rows: list[dict], out: Path) -> Optional[str]:
    matched_open = [
        row
        for row in rows
        if row.get("disposition") == "matched" and row.get("open") is True
    ]
    if matched_open:
        top = matched_open[0]
        text = render_heilmeier(
            top,
            moat={"paragraph": top.get("moat_paragraph"), "high_repos": top.get("high_repos")},
            score=top,
        )
        path = out / "drafts" / f"{_safe(str(top['id']))}.md"
        _write(path, text)
        return str(path)
    open_rows = [row for row in rows if row.get("open") is True]
    if open_rows:
        _write(
            out / "NO-VERIFIED-MATCH-DRAFT.md",
            "\n".join(
                [
                    "# No verified portfolio match for automatic draft",
                    "",
                    "This run found confirmed-open rows, but none met the matched disposition "
                    f"(assurance white-space, portfolio_fit ≥ {config.MATCHED_FIT_MIN:g}, confirmed open).",
                    "PORCUPINE does not auto-generate an assurance proposal for unrelated infrastructure "
                    "or near-miss rows merely because funding or keywords scored highly.",
                    "Opportunities still exist in the ledger and ranked.json.",
                    "Use `python3 -m porcupine.cli draft <id>` for an exploratory Heilmeier render "
                    "(uncalibrated heuristic scores; not a verified portfolio match).",
                    "",
                ]
            ),
        )
        return None
    _write(
        out / "NO-OPEN-DRAFT.md",
        "\n".join(
            [
                "# No confirmed-open source for automatic draft",
                "",
                "This run did not find an opportunity whose parsed deadline is still in the future "
                "with publisher-confirmed open status (CSV) or equivalent evidence.",
                "That is a complete radar result. PORCUPINE does not invent a challenge to draft.",
                "Closed and unverified rows, if any, are in the ledger and in ranked.json.",
                "Use `python3 -m porcupine.cli draft <id>` to render a Heilmeier file on purpose.",
                "",
            ]
        ),
    )
    return None


def cmd_run(
    root: Optional[Path] = None,
    sources: Optional[list[dict]] = None,
) -> int:
    root = Path(root) if root is not None else config.workspace_root()
    out = config.output_dir(root)
    out.mkdir(parents=True, exist_ok=True)
    scouted = scout(
        sources=sources,
        cache_directory=config.cache_dir(root),
        snapshot_root=root,
    )
    candidate_rows = assemble(scouted["opportunities"], root=root)
    rows, shortlist = apply_display_shortlist(candidate_rows)
    for feed in scouted.get("feeds") or []:
        if feed.get("raw_rows") is not None:
            per_feed = per_source_run_counts(candidate_rows, str(feed.get("id") or ""))
            feed["candidate_rows"] = per_feed["candidate_rows"]
            feed["displayed_rows"] = per_feed["displayed_rows"]
            feed["matched_rows"] = per_feed["matched_rows"]
            feed["shortlist_capped"] = per_feed["shortlist_capped"]
            feed["opportunities"] = per_feed["displayed_rows"]
    health = scouted.get("health") or {}
    ledger = Ledger(config.ledger_path(root))
    recorded = _record(ledger, candidate_rows)
    draft_path = _draft_open(candidate_rows, out)
    high = sum(1 for row in candidate_rows if row.get("high_fit"))
    summary = {
        "generated_at": _now(),
        "version": __version__,
        "opportunity_count": len(rows),
        "candidate_rows": shortlist["candidate_rows"],
        "displayed_rows": shortlist["displayed_rows"],
        "shortlist_capped": shortlist["shortlist_capped"],
        "high_fit_open_matches": high,
        "matched_rows": shortlist.get("matched_rows", 0),
        "draft": draft_path,
        "ledger": recorded,
        "feeds": scouted["feeds"],
        "scout_health": health,
    }
    _write(out / "ranked.json", json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    _write(out / "feeds.json", json.dumps(scouted["feeds"], indent=2, ensure_ascii=False) + "\n")
    _write(out / "last-run.json", json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    body = [
        f"# PORCUPINE run {summary['generated_at']}",
        "",
        f"Ranked display cap: {len(rows)} shown of {shortlist['candidate_rows']} scored candidates "
        f"({shortlist.get('matched_rows', 0)} matched disposition).",
        f"High-fit open matches: {high}",
        f"Draft: {draft_path or 'none — no automatic matched+open draft (see NO-*-DRAFT.md if present)'}",
        "",
        "EV is a heuristic priority score (uncalibrated): funding × portfolio_fit × reachability − effort.",
        "It is not expected financial return, profit, or actual win likelihood.",
        "p_lcb is the Wilson lower bound on the global `record-win` counter only (n=0 keeps that bound at 0).",
        "`record-win` is not a verified learning loop — it increments wins without opportunity linkage or losses.",
        "Eligibility, certification readiness, and commercial moat are not verified by this run.",
        "Primary-source coverage is partial: federal CSV when configured; HTML feeds may be unresolved.",
        "A zero in the high-fit column means no confirmed-open assurance match among processed sources.",
        "",
        health.get("summary") or "0 of 0 feeds healthy",
        "",
        "## Feeds",
        "",
    ]
    for feed in scouted["feeds"]:
        detail = feed.get("error") or feed.get("how") or ""
        counts = ""
        if feed.get("raw_rows") is not None:
            counts = (
                f" raw={feed.get('raw_rows')} valid={feed.get('valid_rows')} "
                f"unique={feed.get('unique_rows', feed.get('valid_rows'))} "
                f"dup={feed.get('duplicate_rows', 0)} "
                f"lens={feed.get('lens_matches')} matched={feed.get('matched_rows', 0)} "
                f"shown={feed.get('displayed_rows', feed.get('opportunities'))}"
            )
        warn = feed.get("coverage_warning") or ""
        snap = feed.get("source_snapshot_ref") or ""
        snap_bit = f" snapshot={snap}" if snap else ""
        persist_warn = feed.get("evidence_persistence_warning") or ""
        if persist_warn:
            snap_bit = snap_bit + f" WARN={persist_warn}"
        body.append(
            f"- {feed['id']}: {feed['status']} ({feed.get('opportunities', 0)} opps){counts} "
            f"{detail}{snap_bit} {warn}".rstrip()
        )
    body.extend(["", "## Ranked", "", format_table(rows), ""])
    _write(out / "ranked.md", "\n".join(body))
    print(f"PORCUPINE {__version__}")
    if health.get("summary"):
        print(health["summary"])
    for feed in scouted["feeds"]:
        if feed["status"] != "ok":
            print(f"SKIP {feed['id']}: {feed['error']}")
        elif feed.get("raw_rows") is not None:
            print(
                f"OK {feed['id']}: raw={feed.get('raw_rows')} valid={feed.get('valid_rows')} "
                f"unique={feed.get('unique_rows')} matched={feed.get('matched_rows', 0)} "
                f"shown={feed.get('displayed_rows', feed.get('opportunities', 0))} "
                f"(heuristic EV rank; display cap {config.MAX_OPPS_PER_FEED}) ({feed.get('how')})"
            )
        elif feed.get("opportunities", 0) == 0:
            print(f"EMPTY {feed['id']}: parsed 0 opportunities")
        else:
            print(
                f"OK {feed['id']}: {feed['opportunities']} scored rows "
                f"(heuristic EV rank; display cap {config.MAX_OPPS_PER_FEED}) ({feed.get('how')})"
            )
    print(format_table(rows))
    print(f"high-fit open matches: {high}")
    print(f"wrote {out / 'ranked.md'}")
    if draft_path:
        print(f"draft {draft_path}")
    elif any(row.get("open") is True for row in candidate_rows):
        print("draft none (no verified portfolio match for automatic draft; use draft <id> to explore)")
    else:
        print("draft none (no confirmed-open source)")
    print(
        f"ledger appended {recorded['appended']}, "
        f"already recorded {recorded['already_recorded']}"
    )
    return 0


def _source_by_id(ident: str) -> Optional[dict]:
    for item in config.SOURCES:
        if item["id"] == ident:
            return dict(item)
    return None


def cmd_replay_csv(
    csv_path: Path,
    root: Optional[Path] = None,
    source_id: str = "canadabuys-open-tenders-csv",
) -> int:
    root = Path(root) if root is not None else config.workspace_root()
    source = _source_by_id(source_id)
    if source is None:
        print(f"unknown source id {source_id}", file=sys.stderr)
        return 2
    path = Path(csv_path)
    if not path.is_file():
        print(f"CSV not found: {path}", file=sys.stderr)
        return 2
    body = path.read_text(encoding="utf-8-sig")
    opportunities, feed = scout_source_body(
        body, source, offline_replay=True, snapshot_root=root
    )
    feed["offline_replay"] = True
    feed["replay_file"] = str(path.resolve())
    feed["live_fetch"] = False
    feed["fetched_at"] = "unknown"
    out = config.output_dir(root)
    out.mkdir(parents=True, exist_ok=True)
    candidate_rows = assemble(opportunities, root=root)
    rows, shortlist = apply_display_shortlist(candidate_rows)
    per_feed = per_source_run_counts(candidate_rows, str(feed.get("id") or source_id))
    feed["candidate_rows"] = per_feed["candidate_rows"]
    feed["displayed_rows"] = per_feed["displayed_rows"]
    feed["matched_rows"] = per_feed["matched_rows"]
    feed["shortlist_capped"] = per_feed["shortlist_capped"]
    feed["opportunities"] = per_feed["displayed_rows"]
    _write(out / "feeds.json", json.dumps([feed], indent=2, ensure_ascii=False) + "\n")
    _write(out / "ranked.json", json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    summary = {
        "generated_at": _now(),
        "version": __version__,
        "mode": "replay-csv",
        "replay_file": str(path.resolve()),
        "opportunity_count": len(rows),
        "candidate_rows": shortlist["candidate_rows"],
        "displayed_rows": shortlist["displayed_rows"],
        "shortlist_capped": shortlist["shortlist_capped"],
        "feed": feed,
    }
    _write(out / "last-run.json", json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(
        f"replay-csv {path.name}: raw={feed.get('raw_rows')} "
        f"valid={feed.get('valid_rows')} unique={feed.get('unique_rows')} "
        f"shown={feed.get('displayed_rows')}"
    )
    print(format_table(rows[:15]))
    print(f"wrote {out / 'feeds.json'} and {out / 'ranked.json'}")
    return 0


def _run_options(args: list[str]) -> tuple[Optional[Path], Optional[list[dict]], list[str]]:
    root: Optional[Path] = None
    source_ids: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--root" and index + 1 < len(args):
            root = Path(args[index + 1])
            index += 2
            continue
        if token == "--source" and index + 1 < len(args):
            source_ids.append(args[index + 1])
            index += 2
            continue
        rest.append(token)
        index += 1
    sources: Optional[list[dict]] = None
    if source_ids:
        sources = []
        for ident in source_ids:
            item = _source_by_id(ident)
            if item is None:
                print(f"unknown source id {ident}", file=sys.stderr)
                sys.exit(2)
            sources.append(item)
    return root, sources, rest


def _opportunity_rows(ledger: Ledger) -> list[dict]:
    rows = [row for row in ledger.read() if row.get("record_type") == "opportunity"]
    return rank_scores(rows)


def cmd_top(n: int, root: Optional[Path] = None) -> int:
    root = Path(root) if root is not None else config.workspace_root()
    rows = _opportunity_rows(Ledger(config.ledger_path(root)))[: max(0, n)]
    print(format_table(rows))
    print(f"showing {len(rows)}")
    return 0


def cmd_record_win(root: Optional[Path] = None) -> int:
    state = record_win(root)
    bound = wilson_lower_bound(state["p_win_successes"], state["p_win_n"])
    print(
        f"recorded win p_win_n={state['p_win_n']} "
        f"p_win_successes={state['p_win_successes']} "
        f"p_win_lcb={bound:.4f} "
        "(global counter only; not a verified per-opportunity learning loop)"
    )
    return 0


def cmd_draft(ident: str, root: Optional[Path] = None) -> int:
    root = Path(root) if root is not None else config.workspace_root()
    rows = [
        row
        for row in Ledger(config.ledger_path(root)).read()
        if row.get("record_type") == "opportunity" and str(row.get("id")) == ident
    ]
    if not rows:
        print(f"no recorded opportunity with id {ident}", file=sys.stderr)
        return 2
    out = config.output_dir(root)
    written = []
    for row in rows:
        if row.get("disposition") != "matched":
            print(
                "WARNING: exploratory draft — disposition is not 'matched'. "
                "Heuristic EV/fit scores are uncalibrated and this is not a verified portfolio match.",
                file=sys.stderr,
            )
        text = render_heilmeier(
            row,
            moat={"paragraph": row.get("moat_paragraph"), "high_repos": row.get("high_repos") or []},
            score=row,
        )
        path = out / "drafts" / f"{_safe(str(row.get('source') or 'src'))}__{_safe(ident)}.md"
        _write(path, text)
        written.append(str(path))
        print(path)
    return 0 if written else 2


def cmd_report(root: Optional[Path] = None) -> int:
    root = Path(root) if root is not None else config.workspace_root()
    ledger = Ledger(config.ledger_path(root))
    rows = ledger.read()
    by_type: dict[str, int] = {}
    by_disp: dict[str, int] = {}
    for row in rows:
        by_type[str(row.get("record_type") or "?")] = by_type.get(str(row.get("record_type") or "?"), 0) + 1
        if row.get("record_type") == "opportunity":
            key = str(row.get("disposition") or "?")
            by_disp[key] = by_disp.get(key, 0) + 1
    opps = _opportunity_rows(ledger)
    high = sum(1 for row in opps if row.get("high_fit"))
    print(f"PORCUPINE {__version__} report")
    print(f"ledger rows: {len(rows)} at {config.ledger_path(root)}")
    print("record types: " + (", ".join(f"{key}={value}" for key, value in sorted(by_type.items())) or "(empty)"))
    print("dispositions: " + (", ".join(f"{key}={value}" for key, value in sorted(by_disp.items())) or "(empty)"))
    print(f"high-fit open matches in ledger: {high}")
    last = config.output_dir(root) / "last-run.json"
    if last.exists():
        try:
            payload = json.loads(last.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        print(f"last run: {payload.get('generated_at')} high-fit {payload.get('high_fit_open_matches')}")
        scout_health = payload.get("scout_health") or {}
        if scout_health.get("summary"):
            print(f"scout health: {scout_health['summary']}")
        for feed in payload.get("feeds") or []:
            if feed.get("status") != "ok":
                print(f"  skipped feed {feed.get('id')}: {feed.get('error')}")
    else:
        print("last run: none yet")
    print(format_table(opps[:10]))
    return 0


def _journal_options(args: list[str]) -> tuple[dict[str, str], list[str], Optional[Path]]:
    options: dict[str, str] = {}
    evidence_refs: list[str] = []
    root: Optional[Path] = None
    index = 0
    while index < len(args):
        token = args[index]
        if token in ("--id", "--verdict", "--rationale", "--outcome", "--note", "--root", "--evidence-ref"):
            if index + 1 >= len(args):
                raise ValueError(f"{token} expects a value")
            value = args[index + 1]
            if token == "--root":
                root = Path(value)
            elif token == "--evidence-ref":
                evidence_refs.append(value)
            else:
                options[token[2:].replace("-", "_")] = value
            index += 2
            continue
        raise ValueError(f"unknown journal option {token}")
    return options, evidence_refs, root


def cmd_journal(args: list[str]) -> int:
    if not args or args[0] not in ("log-decision", "log-outcome", "verify"):
        print("journal expects log-decision, log-outcome, or verify", file=sys.stderr)
        return 2
    operation = args[0]
    try:
        options, evidence_refs, root = _journal_options(args[1:])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    journal = Journal(config.journal_path(root))
    if operation == "verify":
        if options or evidence_refs:
            print("journal verify accepts only --root", file=sys.stderr)
            return 2
        ok, bad_seq = journal.verify()
        if ok:
            print(f"journal verified: {journal.path}")
            return 0
        print(f"journal verification failed at seq {bad_seq}: {journal.path}", file=sys.stderr)
        return 1
    try:
        if operation == "log-decision":
            required = ("id", "verdict", "rationale")
            missing = [name for name in required if name not in options]
            if missing:
                raise ValueError("log-decision missing: " + ", ".join("--" + name for name in missing))
            record = journal.log_decision(
                options["id"], options["verdict"], options["rationale"], evidence_refs
            )
        else:
            required = ("id", "outcome", "note")
            missing = [name for name in required if name not in options]
            if missing:
                raise ValueError("log-outcome missing: " + ", ".join("--" + name for name in missing))
            record = journal.log_outcome(options["id"], options["outcome"], options["note"])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"journal appended seq={record['seq']} type={record['type']}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0
    command = args[0]
    if command == "run":
        root, sources, _rest = _run_options(args[1:])
        return cmd_run(root=root, sources=sources)
    if command == "replay-csv":
        if len(args) < 2:
            print("replay-csv expects --file PATH", file=sys.stderr)
            return 2
        csv_path: Optional[Path] = None
        root: Optional[Path] = None
        source_id = "canadabuys-open-tenders-csv"
        index = 1
        while index < len(args):
            if args[index] == "--file" and index + 1 < len(args):
                csv_path = Path(args[index + 1])
                index += 2
            elif args[index] == "--root" and index + 1 < len(args):
                root = Path(args[index + 1])
                index += 2
            elif args[index] == "--source" and index + 1 < len(args):
                source_id = args[index + 1]
                index += 2
            else:
                print(f"unknown replay-csv option {args[index]}", file=sys.stderr)
                return 2
        if csv_path is None:
            print("replay-csv requires --file PATH", file=sys.stderr)
            return 2
        return cmd_replay_csv(csv_path, root=root, source_id=source_id)
    if command == "top":
        if len(args) == 1:
            return cmd_top(10)
        try:
            count = int(args[1])
        except ValueError:
            print("top expects an integer", file=sys.stderr)
            return 2
        return cmd_top(count)
    if command == "draft":
        if len(args) < 2:
            print("draft expects an id", file=sys.stderr)
            return 2
        return cmd_draft(args[1])
    if command == "record-win":
        return cmd_record_win()
    if command == "report":
        return cmd_report()
    if command == "journal":
        return cmd_journal(args[1:])
    print(f"unknown command {command}", file=sys.stderr)
    print(HELP, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
