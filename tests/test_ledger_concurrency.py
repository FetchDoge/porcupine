"""Multi-process contention tests for the ledger (GitHub issue #4).

The flock design was asserted and unit-tested but never load-tested under real
multi-process contention. These tests run bounded versions of the stress
workload in tests: N spawned writer processes, released simultaneously by a
barrier, each appending a disjoint set plus a shared overlapping set against
one ledger file. Verification is on the raw file bytes, independent of
Ledger.read(): exact line count, every line valid JSON, (source, id) key set
exact, and the writers' "written" results summing to the final line count —
each line claimed by exactly one writer.

Full-scale results (up to 128 writers, 58,200 final lines) are recorded in
RELIABILITY-VERIFICATION.md; the standalone harness is described there.
"""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

from porcupine.ledger import Ledger

_JOIN_TIMEOUT = 120


def _rows(source: str, prefix: str, count: int, pad: int) -> list[dict]:
    filler = "x" * pad
    return [
        {
            "record_type": "opportunity",
            "source": source,
            "id": f"{prefix}-{i}",
            "title": f"stress {prefix} {i}",
            "pad": filler,
        }
        for i in range(count)
    ]


def _writer(
    path_str: str,
    index: int,
    disjoint: int,
    shared: int,
    batch: int,
    pad: int,
    mode: str,
    barrier,
    result_dir_str: str,
) -> None:
    ledger = Ledger(Path(path_str))
    rows = _rows(f"stress-w{index}", f"w{index}", disjoint, pad) + _rows(
        "stress-shared", "s", shared, pad
    )
    written = 0
    total = 0
    barrier.wait(timeout=60)
    if mode == "singleton":
        for row in rows:
            total += 1
            written += 1 if ledger.append(row)["written"] else 0
    else:
        for start in range(0, len(rows), batch):
            for res in ledger.append_many(rows[start : start + batch]):
                total += 1
                written += 1 if res["written"] else 0
    Path(result_dir_str, f"writer-{index}.json").write_text(
        json.dumps({"written": written, "total": total}), encoding="utf-8"
    )


def _run_contention(
    tmp_path: Path,
    writers: int,
    disjoint: int,
    shared: int,
    batch: int,
    pad: int,
    mode: str,
) -> None:
    path = tmp_path / "ledger.jsonl"
    path.touch()
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(writers)
    procs = [
        ctx.Process(
            target=_writer,
            args=(
                str(path),
                i,
                disjoint,
                shared,
                batch,
                pad,
                mode,
                barrier,
                str(tmp_path),
            ),
        )
        for i in range(writers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=_JOIN_TIMEOUT)
    for p in procs:
        assert not p.is_alive(), "writer process did not finish (possible deadlock)"
        assert p.exitcode == 0, f"writer exited with {p.exitcode}"

    expected_keys = {
        (f"stress-w{w}", f"w{w}-{i}") for w in range(writers) for i in range(disjoint)
    } | {("stress-shared", f"s-{i}") for i in range(shared)}
    expected_lines = writers * disjoint + shared

    raw = path.read_bytes()
    assert raw.endswith(b"\n")
    lines = raw.decode("utf-8").splitlines()
    assert len(lines) == expected_lines
    keys = []
    for line in lines:
        payload = json.loads(line)  # a torn/interleaved line fails here
        assert isinstance(payload, dict)
        keys.append((str(payload["source"]), str(payload["id"])))
    assert len(keys) == len(set(keys)), "duplicate keys under contention"
    assert set(keys) == expected_keys

    written_sum = 0
    total_sum = 0
    for i in range(writers):
        result = json.loads(
            (tmp_path / f"writer-{i}.json").read_text(encoding="utf-8")
        )
        written_sum += result["written"]
        total_sum += result["total"]
    assert written_sum == expected_lines
    assert total_sum == writers * (disjoint + shared)


def test_multi_process_batched_contention(tmp_path):
    """8 writers x (100 disjoint + 50 shared), batches of 25 -> 850 lines."""
    _run_contention(tmp_path, writers=8, disjoint=100, shared=50, batch=25, pad=0, mode="batch")


def test_multi_process_singleton_contention(tmp_path):
    """6 writers x (40 disjoint + 20 shared) via append() -> 260 lines, one lock per row."""
    _run_contention(tmp_path, writers=6, disjoint=40, shared=20, batch=1, pad=0, mode="singleton")


def test_multi_process_large_lines_no_interleave(tmp_path):
    """Lines of ~8.4 KB cross the stdio buffer; under contention none may interleave."""
    _run_contention(tmp_path, writers=6, disjoint=30, shared=10, batch=10, pad=8192, mode="batch")
