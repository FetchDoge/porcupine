"""Append-only, hash-chained decision/action/outcome journal."""

from __future__ import annotations

import fcntl
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

GENESIS_HASH = "0" * 64
_VERDICTS = {"pursue", "skip", "defend"}
_OUTCOMES = {"won", "lost", "expired", "noise"}


class _ChainBreak(ValueError):
    """A broken journal link, carrying the offending sequence number."""

    def __init__(self, seq: int) -> None:
        super().__init__(f"invalid journal chain at seq {seq}")
        self.seq = seq


def _now() -> str:
    """UTC now, no microseconds."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical(record: dict) -> str:
    """Canonical JSON for hashing: sorted keys, tight separators, hash excluded."""
    payload = {key: value for key, value in record.items() if key != "hash"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _hash(record: dict) -> str:
    """SHA-256 of the canonical record. The chain's tamper tripwire."""
    return hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _validate(fields: dict) -> None:
        """Reject malformed records before they touch the chain. Raises ValueError."""
        record_type = fields.get("type")
        if record_type == "decision":
            required = ("opportunity_id", "verdict", "rationale", "evidence_refs")
            if fields.get("verdict") not in _VERDICTS:
                raise ValueError("decision verdict must be pursue, skip, or defend")
            if not isinstance(fields.get("evidence_refs"), list):
                raise ValueError("decision evidence_refs must be a list")
        elif record_type == "action":
            required = ("kind", "detail")
        elif record_type == "outcome":
            required = ("opportunity_id", "outcome", "note")
            if fields.get("outcome") not in _OUTCOMES:
                raise ValueError("outcome must be won, lost, expired, or noise")
        else:
            raise ValueError("journal type must be decision, action, or outcome")
        missing = [key for key in required if key not in fields]
        if missing:
            raise ValueError("journal record missing: " + ", ".join(missing))

    @staticmethod
    def _link_digest(record: dict, expected_seq: int, previous: str) -> str:
        """Digest of one chain link. Raises _ChainBreak naming the bad seq."""
        try:
            seq = int(record["seq"])
            digest = str(record["hash"])
        except (KeyError, TypeError, ValueError):
            raise _ChainBreak(expected_seq)
        if seq != expected_seq or record.get("prev_hash") != previous or _hash(record) != digest:
            raise _ChainBreak(seq)
        return digest

    @staticmethod
    def _tail(handle) -> tuple[int, str]:
        """Walk to the end of the chain. Returns (last_seq, last_hash); handle left at EOF."""
        handle.seek(0)
        last_seq = 0
        last_hash = GENESIS_HASH
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid journal line {line_no}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"invalid journal line {line_no}")
            last_hash = Journal._link_digest(record, last_seq + 1, last_hash)
            last_seq += 1
        handle.seek(0, 2)
        return last_seq, last_hash

    def append(self, fields: dict) -> dict:
        """Validate, chain, and append one record under an exclusive lock."""
        self._validate(fields)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                last_seq, last_hash = self._tail(handle)
                record = dict(fields)
                record.update(
                    {
                        "seq": last_seq + 1,
                        "ts": _now(),
                        "prev_hash": last_hash,
                    }
                )
                record["hash"] = _hash(record)
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return record

    def log_decision(
        self,
        opportunity_id: str,
        verdict: str,
        rationale: str,
        evidence_refs: Optional[list[str]] = None,
    ) -> dict:
        """Record a pursue/skip/defend decision with its rationale and evidence."""
        return self.append(
            {
                "type": "decision",
                "opportunity_id": opportunity_id,
                "verdict": verdict,
                "rationale": rationale,
                "evidence_refs": list(evidence_refs or []),
            }
        )

    def log_action(self, kind: str, detail: str) -> dict:
        """Record an operator action taken outside the pursue/skip decision."""
        return self.append({"type": "action", "kind": kind, "detail": detail})

    def log_outcome(self, opportunity_id: str, outcome: str, note: str) -> dict:
        """Record what actually happened: won, lost, expired, or noise."""
        return self.append(
            {
                "type": "outcome",
                "opportunity_id": opportunity_id,
                "outcome": outcome,
                "note": note,
            }
        )

    def verify(self) -> tuple[bool, Optional[int]]:
        """Walk the chain without writing. Returns (True, None) or (False, bad_seq)."""
        if not self.path.exists():
            return True, None
        expected_seq = 1
        previous = GENESIS_HASH
        with self.path.open("r", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        record = json.loads(stripped)
                    except json.JSONDecodeError:
                        return False, expected_seq
                    if not isinstance(record, dict):
                        return False, expected_seq
                    try:
                        previous = self._link_digest(record, expected_seq, previous)
                    except _ChainBreak as exc:
                        return False, exc.seq
                    expected_seq += 1
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return True, None
