targets: porcupine/radar.py porcupine/config.py porcupine/cli.py tests/test_trustworthy_radar.py TRUSTWORTHY-RADAR-REPORT.md

# Trustworthy radar — bounded first increment

**Why this spec exists:** a working radar cannot treat a broken parser as an
empty market. Every obligation below is a named failure with a mechanism
attached — the spec is a list of things that must not be allowed to happen,
each paired with what stops it.

## Authority / routing
Marcus approved this approach and iterative development. This authorizes code in this isolated worktree, NOT live cutover, automatic submissions, spend, credential changes, gateway changes, or unrestricted expansion. Architect/verifier = rig; a separate builder writes the code. Existing DESIGN-v2/ALGORITHM/DEEP-DESIGN are historical proposals, NOT implementation requirements. This spec supersedes them for this increment.

## Read first
porcupine/radar.py, config.py, cli.py, scoring.py, ledger.py, tests/test_porcupine.py, source-evidence/capture.json, source-evidence/canadabuys-reference.csv. Fresh reassessment at the separate reassessment notes is read-only rationale. Check git status/log before editing. Base b7ff5a2; original live checkout <live-checkout> must remain untouched. Work only here.

## Goal
Give PORCUPINE trustworthy eyes: machine-readable primary-source intake, truthful coverage accounting and provenance, without adding a learning engine or silently suppressing unfamiliar candidates.

**Threat:** the alternative is a radar that reports confidence it never earned — green lights over broken feeds, probabilities over heuristics, silence over missing data.

## Verified discovery
Official dataset catalog: https://open.canada.ca/data/en/dataset/6abd20d4-7a1c-4b38-baa2-9525d0bb2fd2
Verified CSV: https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv
Direct urllib GET returned 200, complete 6200542 bytes, csv.DictReader counted 878 rows. Exact source capture manifest and selected REAL row fixture are in source-evidence/. These are not simulated notices. Dataset covers federal notices only, not all Canadian procurement or the entire IDEaS market.
Actual field names include title-titre-eng, referenceNumber-numeroReference, solicitationNumber-numeroSollicitation, publicationDate-datePublication, tenderClosingDate-appelOffresDateCloture, tenderStatus-appelOffresStatut-eng, noticeURL-URLavis-eng, tenderDescription-descriptionAppelOffres-eng. Read exact headers/fixture, do not guess status enums or API endpoints.
Fixture includes RF Data Fusion for Command and Control, reference cb-846-73690703, solicitation W7714-248676/017, closing 2026-10-20T14:00:00; CSV notice URL is EMPTY. Do not manufacture an official detail URL. Keep source dataset URL and identifiers, with detail URL unknown.
Fixture also includes a row marked Open with deadline 2026-03-10. Contradiction must surface, not become confirmed-open. Umbrella CFP notice closes 2027-03-31; umbrella close is NOT every child challenge's deadline.
Direct fetches of IDEaS competitive-projects index and two challenge pages timed out at 25s. Do not claim HTML coverage fixed or fabricate HTML fixtures. Implement the proven CSV path first; keep remaining sources visibly partial/failed. No arbitrary >=1 assurance match requirement: matching availability is not under our control.

## Implementation obligations — each a failure, each with its countermeasure

**1. Threat: no primary-source path.** Runtime never fetches or parses the verified CSV; the scout is HTML-only.
*Mechanism:* source-specific stdlib CSV ingestion (csv.DictReader, utf-8-sig, quoted multiline fields, HTML entity/markup cleanup within descriptions) for official CanadaBuys open notices. Validate required headers; surface schema drift separately from valid empty data. Prefer existing fetch/cache seams; preserve legacy parsers and their tests. Do not download the historical complete dataset.

**2. Threat: keyword pre-filter eats the intake.** Rows with no lens keyword vanish before counting — the radar decides what exists before it looks.
*Mechanism:* retain broad CSV candidates independent of preferred keywords. Count raw rows, valid normalized rows, rejected malformed rows, lens matches and displayed candidates separately. Apply relevance downstream; unrelated rows need not flood the operator shortlist. Missing funding/keywords/deadline is unknown, not malicious. Preserve meaningful reasons for exclusion; no synthetic 'verified empty' from an unrecognized response or unsupported parser.

**3. Threat: provenance loss.** A record without its acquisition history is a rumor with formatting.
*Mechanism:* preserve authoritative field provenance: publication timestamp, full close timestamp, status, solicitation/reference ids, dataset URL, fetched_at and source body hash. Extract application dates from the closing field, NOT a free-text 'issued by' or umbrella date. Report timezone unknown if source omits it; do not invent UTC. Contradictory past-deadline/Open rows must not be confirmed actionable. Do not conflate awards, closed rows or overall CFP windows with open child challenges.

**4. Threat: numbers that lie.** Parsed money presented as profit; heuristic scores presented as win odds.
*Mechanism:* funding reported only when supported by the notice, with trace and scope (component, program envelope, unknown). Missing amount remains unknown. Do not treat parsed money as economic profit. Keep existing ev keys for backward compatibility but visibly label the displayed value 'heuristic priority', uncalibrated — not expected financial return or actual win likelihood. Do not alter ranking formula or add probabilistic learning this round.

**5. Threat: phantom coverage.** "No matches" displayed over a dead feed.
*Mechanism:* feed-health output distinguishing successful supported parse with zero records from fetch failure, unsupported/changed schema, partial/truncated processing, stale cache and healthy coverage. Carry reason, fetched time, counts, source scope and primary coverage warning into feeds.json and ranked report/CLI. State 'no matches among processed sources' rather than 'no market opportunities'. Never display GREEN/full coverage while required sources are unresolved. Report truncation/candidate caps and show source-level total counts before caps.

**6. Threat: hash claims that overreach.** A content hash proves identity, not authenticity — conflating them manufactures trust.
*Mechanism:* source snapshot/evidence records support exact replay of acquisition without secrets. Do not make a hash-chain/authenticity claim. Keep source acquisition metadata separate from the deduplicated opportunity ledger. No outcome-learning subsystem this round.

**7. Threat: the bare-"by" forgery.** *"Issued by 22 October 2027"* mints a deadline from prose.
*Mechanism:* fix the demonstrated bare-by semantic bug with explicit close/submission wording, preserving genuine 'no later than' deadlines. Add regression for issued-by. Do NOT impose money AND deadline proximity as an intake rule.

**8. Threat: silent truncation and SSRF.** A 6.2 MB file through a 2 MB pipe; fetches to untrusted destinations.
*Mechanism:* separate CSV byte limit large enough for the verified file (e.g. 16 MB), explicit over-limit failure or partial status (never healthy/empty). Bounded timeouts/retries/polite public reads. Network guard on the actual fetch/redirect path, tested against private/local destinations, no local test servers. If full transport hardening cannot be safely completed, explicitly report the unresolved boundary and keep endpoints configured/trusted; do not claim SSRF protection from scheme checks.

**9. Threat: report text that overclaims.** Operator-facing prose quietly upgrading heuristics to facts.
*Mechanism:* replace fact-overclaims in report text; leave original historical design/review docs intact. Add report disclaimer that eligibility, certification readiness and commercial moat remain unverified.

## Tests / verifier acceptance
Tests are written first; the rig runs them. Never say tests passed if shell denied.
- Existing 22 regression tests remain green.
- Fixture parser preserves expected reference/solicitation/close fields from REAL captured CSV, including multiline and accented text; missing detail URL is unknown, source dataset link preserved.
- A real fixture row outside keyword lens remains an intake record or is explicitly accounted for, not silently lost.
- Missing funding stays unknown. 'Open' with past close is not actionable and reports contradiction. Umbrella vs child deadlines remain distinct.
- Header loss/HTML error body is parse/schema failure, not healthy zero.
- Empty schema-valid CSV vs HTTP error vs oversized/truncated response vs stale cache are observably distinct.
- Synthetic bait regression: 'issued by 22 October 2027' never establishes application deadline; genuine labelled closing dates still parse.
- Report explicitly warns about partial primary-source coverage; no numerical pseudo-probability added.
- Deterministic replay against the captured full CSV will be run by rig. Return exact API/CLI commands needed for source-specific replay/live verification with isolated output/cache/ledger directories, no network to unrelated feeds.
- One live official CSV acquisition and parser execution under the actual runtime, independent of fixtures, are mandatory before any cutover. rig runs this.

## Hard constraints
Only this worktree may be written. No commits, push, merges, live deploy, cron/config/profile changes, auth files, new paid services, dependencies or model calls. Stdlib-first Python 3.9-compatible existing style. No auto-submission, competitor interaction, hidden threshold/lens tuning, record-win accumulation or invented source data. Source-evidence originals are read-only. New fixture derivatives must identify transformations. Protect the original live checkout even if sandbox Shell works. Do not patch tests to mask defects.

## Deliverable
Implement the bounded increment, tests, and TRUSTWORTHY-RADAR-REPORT.md with per-file changes, buildability findings, residual risks, exact verifier commands, and status of each acceptance criterion. Explicit UNKNOWN for commands you could not run. If a necessary design choice is ambiguous or unsafe, report the blocker rather than widening scope. This is not the full maximal end-state; it is the verified foundation on which future iterations earn promotion.
