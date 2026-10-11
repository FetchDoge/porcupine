"""Append-only JSONL ledger.

Idempotent on (source, id). A second write of the same pair does not add a line.
"""

from __future__ import annotations

import fcntl
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("porcupine.ledger")

# Incremented once per locked full-file key scan (append / append_many). Tests only.
_key_scan_count = 0


def reset_key_scan_count() -> None:
    global _key_scan_count
    _key_scan_count = 0


def key_scan_count() -> int:
    """Locked full-file key scans so far. Tests only; the count is the perf tripwire."""
    return _key_scan_count


def _decode_ledger_line(line: str, line_no: int) -> Optional[dict]:
    """One JSONL line to a dict. Bad lines are logged and skipped, never fatal."""
    stripped = line.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        log.warning("skip bad ledger line %s: %s", line_no, exc)
        return None
    return payload if isinstance(payload, dict) else None


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def read(self) -> list[dict]:
        """All rows. A missing file is empty; bad lines are skipped with a warning."""
        if not self.path.exists():
            return []
        rows = []
        text = self.path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            payload = _decode_ledger_line(line, line_no)
            if payload is not None:
                rows.append(payload)
        return rows

    def seen(self) -> set[tuple[str, str]]:
        """(source, id) pairs already recorded. Powers idempotent appends."""
        keys = set()
        for row in self.read():
            source = row.get("source")
            ident = row.get("id")
            if source and ident:
                keys.add((str(source), str(ident)))
        return keys

    @staticmethod
    def _scan_keys_from_handle(handle) -> set[tuple[str, str]]:
        """One locked full-file key scan. The handle is left at end-of-file for append."""
        global _key_scan_count
        _key_scan_count += 1
        handle.seek(0)
        keys: set[tuple[str, str]] = set()
        for line_no, line in enumerate(handle, 1):
            payload = _decode_ledger_line(line, line_no)
            if payload is None:
                continue
            source = payload.get("source")
            ident = payload.get("id")
            if source and ident:
                keys.add((str(source), str(ident)))
        handle.seek(0, 2)
        return keys

    def append_many(self, rows: list[dict]) -> list[dict]:
        """Append rows idempotently under one exclusive lock. One scan per batch, not per row."""
        if not rows:
            return []

        parsed: list[tuple[dict, tuple[str, str], str]] = []
        for row in rows:
            source = row.get("source")
            ident = row.get("id")
            if not source or not ident:
                raise ValueError("ledger row requires source and id")
            key = (str(source), str(ident))
            line = json.dumps(row, ensure_ascii=False, sort_keys=True)
            parsed.append((row, key, line))

        self.path.parent.mkdir(parents=True, exist_ok=True)
        results: list[dict] = []
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                existing = self._scan_keys_from_handle(handle)
                lines_to_write: list[str] = []
                for _row, key, line in parsed:
                    if key in existing:
                        results.append(
                            {
                                "written": False,
                                "reason": "exists",
                                "source": key[0],
                                "id": key[1],
                            }
                        )
                    else:
                        existing.add(key)
                        lines_to_write.append(line)
                        results.append(
                            {
                                "written": True,
                                "reason": "appended",
                                "source": key[0],
                                "id": key[1],
                            }
                        )
                for line in lines_to_write:
                    handle.write(line + "\n")
                if lines_to_write:
                    handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return results

    def append(self, row: dict) -> dict:
        """Append one row. Delegates to append_many: there is one write path."""
        return self.append_many([row])[0]
