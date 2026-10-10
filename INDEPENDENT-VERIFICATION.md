# PORCUPINE isolated increment — independent verification

**What this document is:** an independent party ran the code and recorded what
happened — not what the builder said would happen. Every claim below names its
execution trace. Where verification stops, the boundary is stated, not implied.

## Observed execution

**Threat:** "tests pass" asserted by the party that wrote the code.

*Mechanism — rig ran it:*
- `python3 -m pytest tests/ -q`: **62 passed in 2.26s, exit 0.**
- Original `tests/test_porcupine.py`: `git diff --exit-code` returned no changes — the 22 legacy tests are byte-identical, not "preserved."
- Fresh official CanadaBuys CSV run: exit 0; **878 raw, valid, unique rows; 76 lens matches; 40 displayed; 0 matched rows; draft null.** Bytes read 6200542. Source scope explicitly federal open tender CSV only.
- Independently parsed opportunity ledger: 878 opportunity records, each carrying acquisition timestamp, text digest, source body and metadata snapshot references. Stored snapshot SHA-256 matched feed and metadata digest; metadata source ID matched acquisition feed.
- Repeated same-root run: exit 0; acquisition marked cache, live_fetch false; one body snapshot reused; 878 candidates; draft null; ledger appended 0, already_recorded 1756.
- `git diff --check`: no whitespace errors.
- Live checkout `/Users/user/.hermes/workspace/porcupine-build`: clean status; no cutover performed.

## Receipts
Runtime evidence root: `/Users/user/.hermes/profiles/rig/cache/scratch/porcupine-radar-receipted-final` (temporary scratch, not permanent archive).
Execution logs in this worktree: `live-receipted-final.log`, `cache-receipted-final.log`.
Builder implementation report: `TRUSTWORTHY-RADAR-REPORT.md`.

## Verdict and limits

**Threat:** a passing test suite mistaken for a proof of the whole system.

*Verdict:* the bounded CSV intake/provenance/no-irrelevant-auto-draft increment meets exercised verification gates in its isolated worktree.

*Explicitly not established:* full IDEaS/DRDC coverage, validated financial EV, classifier precision, independent source authenticity, or transport security. Transport hardening remains explicitly unresolved. **Zero matched rows means zero under the current policy in this feed, not zero market opportunities.** Heuristic ranking can still place irrelevant construction near the top; the verified gate prevents automatic drafting from such near misses.

Deployment, merge, cron cutover, and submissions have NOT occurred. Preserve isolation until a separately scoped promotion decision.
