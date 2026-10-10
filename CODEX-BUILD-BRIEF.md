# PORCUPINE v2 — build brief (increments 1–2)

You are building inside this repo — run all commands from the repo root.
The suite is green (`python3 -m pytest tests/ -q` → 98 passed). Implement
increments 1 and 2 below, in order, each landing green before the next.

## Increment 1 — Transport hardening (`porcupine/netguard.py`, new file)

**Threat:** the fetcher follows redirects anywhere — including into private
network space. A radar that can be steered at localhost is a confused deputy
with a network stack.

- `guarded_urlopen(request, timeout)`: validate the initial URL and EVERY
  redirect hop before following: scheme http/https only, no userinfo, host
  must not resolve to private / loopback / link-local / multicast / reserved /
  unspecified ranges. Use the `ipaddress` module; resolve hostnames via
  `socket.getaddrinfo`; check IP literals without DNS.
- Max 5 redirect hops; each hop re-validated; record the hop chain and expose
  it on the result/exception.
- `NetGuardError(Exception)` — it must NOT be treated as transient/retryable
  (see `_is_transient` in `porcupine/radar.py`: only `TimeoutError`/`URLError`
  retry; make sure `NetGuardError` does not inherit from `URLError`). A
  blocked malicious destination must not be retried into compliance.
- Wire into `fetch_url_with_meta` in `porcupine/radar.py`: replace the bare
  `urlopen(request, timeout=timeout)` call with the guarded version.
- Document the residual DNS-TOCTOU caveat honestly in the module docstring
  (validation-time vs connect-time resolution can differ; no silent claim of
  perfection).

## Increment 2 — Decision/action/outcome journal (`porcupine/journal.py`, new file)

**Threat:** decisions without a tamper-evident record get rewritten by memory.
Six months later, nobody remembers why a pursuit was passed — and the lesson
is lost with the memory.

- Append-only JSONL, hash-chained: each record carries `seq`, `ts`,
  `prev_hash`, and `hash` = sha256 over canonical JSON
  (`json.dumps(sort_keys=True, separators=(",", ":"))`, excluding `hash`
  itself). Genesis record uses `prev_hash` = 64 zeroes.
- `fcntl` locking exactly like `porcupine/ledger.py`. Default file
  `ledger/journal.jsonl` under the workspace root (accept a root override like
  the other modules do via `config`).
- Record types and required fields:
  - `decision`: {opportunity_id, verdict: pursue|skip|defend, rationale, evidence_refs: list}
  - `action`: {kind, detail}
  - `outcome`: {opportunity_id, outcome: won|lost|expired|noise, note}
- `Journal.verify()` recomputes the full chain → `(ok: bool, bad_seq: int | None)`.
- CLI in `porcupine/cli.py`: `journal log-decision --id X --verdict pursue --rationale "..."`,
  `journal log-outcome --id X --outcome won --note "..."`, `journal verify`
  (exit 0 iff chain verifies). Follow the existing `main()`/subcommand style.
- This is evidence substrate, NOT a learning engine: no scoring changes. A
  journal that learns is a journal that can be gamed.

## Hard constraints

- Python 3.9-compatible, stdlib only (no new dependencies), match existing
  code style (type hints, `from __future__ import annotations`, module
  docstrings).
- All existing tests stay green and unmodified; add hermetic tests:
  `tests/test_netguard.py` (IP literals blocked incl. 127.0.0.1, 10/8,
  192.168/16, 169.254.169.254, ::1, 0.0.0.0; public IP literal allowed;
  `localhost` blocked via resolution; userinfo/scheme rejected; redirect to a
  private hop raises before connecting; `fetch_url_with_meta` refuses
  `http://127.0.0.1:9/` without network) and `tests/test_journal.py`
  (append/verify round-trip, tamper detection via byte flip, seq continuity).
  No local test servers, no network in tests.
- No auto-submission, no invented opportunity data, no credential changes.

## Verifier commands (run from repo root)

```bash
python3 -m pytest tests/ -q
python3 -m porcupine.cli replay-csv --file source-evidence/canadabuys-reference.csv --root /tmp/pq-test
```

Expect: full suite green; replay completes.

## Done =

Both increments landed, full suite green, verifier commands executed, residual
limitations documented. Final response: per-increment receipt (files changed,
tests added, how verified, what remains unknown).

**Not claimed:** netguard is transport hygiene, not a security proof. The
DNS-TOCTOU caveat stands.
