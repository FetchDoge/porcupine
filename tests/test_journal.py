from __future__ import annotations

import json

from porcupine.journal import GENESIS_HASH, Journal


def test_append_and_verify_round_trip(tmp_path):
    journal = Journal(tmp_path / "ledger" / "journal.jsonl")
    first = journal.log_decision("opp-1", "pursue", "Strong fit", ["evidence/1"])
    second = journal.log_action("draft", "Prepared an internal draft")
    third = journal.log_outcome("opp-1", "won", "Award confirmed")

    assert first["prev_hash"] == GENESIS_HASH
    assert [first["seq"], second["seq"], third["seq"]] == [1, 2, 3]
    assert second["prev_hash"] == first["hash"]
    assert third["prev_hash"] == second["hash"]
    assert journal.verify() == (True, None)


def test_tamper_detection_via_byte_flip(tmp_path):
    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    journal.log_decision("opp-1", "skip", "Not aligned", [])
    journal.log_outcome("opp-1", "noise", "Duplicate listing")
    raw = bytearray(path.read_bytes())
    offset = raw.index(b"Not aligned")
    raw[offset] = ord("n")
    path.write_bytes(raw)

    assert journal.verify() == (False, 1)


def test_sequence_continuity_is_verified(tmp_path):
    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    journal.log_action("review", "Reviewed evidence")
    journal.log_action("record", "Recorded finding")
    lines = path.read_text(encoding="utf-8").splitlines()
    second = json.loads(lines[1])
    second["seq"] = 4
    lines[1] = json.dumps(second, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert journal.verify() == (False, 4)
