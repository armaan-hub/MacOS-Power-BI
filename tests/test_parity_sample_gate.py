"""The quick task gate (`--sample N`, `--only NAME`) is read-only and replays only the chosen answers.

Fake battery files in a tmp directory stand in for the saved Power BI answers; the engine is stubbed so nothing
touches the real baseline or PARITY_LEDGER.md.
"""

from __future__ import annotations

import json
import sys

import pytest

from tools import parity_check

NAMES = ["fake_a", "fake_b"]
ITEMS = 10


@pytest.fixture
def gate(tmp_path, monkeypatch):
    parity = tmp_path / "parity"
    parity.mkdir()
    for name in NAMES:
        items = [{"expr": f"=1+{i}", "powerbi": "1"} for i in range(ITEMS)]
        (parity / f"{name}.json").write_text(json.dumps({"powerbi_version": "test", "frozen": "2026-11-17", "items": items}))
    monkeypatch.setattr(parity_check, "PARITY", parity)
    monkeypatch.setattr(parity_check, "BASELINE", parity / "baseline.json")
    monkeypatch.setattr(parity_check, "LEDGER", tmp_path / "PARITY_LEDGER.md")
    monkeypatch.setattr(parity_check, "DAX_BATTERIES", list(NAMES))
    monkeypatch.setattr(parity_check, "TABLES", {})
    monkeypatch.setattr(parity_check.dax, "local", lambda expr: "1")
    monkeypatch.setattr(parity_check, "replay_tables", lambda: ([], {}, []))
    return tmp_path


def _run(monkeypatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["parity_check.py", *args])
    return parity_check.main()


def test_sample_takes_n_per_file_in_file_order(gate):
    rows = parity_check.replay_dax(sample=3, seed=0)
    for name in NAMES:
        picked = [r["expr"] for r in rows if r["group"] == name]
        assert len(picked) == 3
        indices = [int(e.split("+")[1]) for e in picked]
        assert indices == sorted(indices)


def test_same_seed_same_picks_and_other_seed_can_differ(gate):
    first = [r["id"] for r in parity_check.replay_dax(sample=3, seed=0)]
    again = [r["id"] for r in parity_check.replay_dax(sample=3, seed=0)]
    assert first == again
    seen = {tuple(r["id"] for r in parity_check.replay_dax(sample=3, seed=s)) for s in range(1, 10)}
    assert any(tuple(first) != s for s in seen)


def test_small_file_is_replayed_whole(gate):
    rows = parity_check.replay_dax(sample=50)
    assert len(rows) == ITEMS * len(NAMES)


def test_only_replays_named_file_in_full(gate):
    rows = parity_check.replay_dax(sample=3, only=["fake_a"])
    assert sum(1 for r in rows if r["group"] == "fake_a") == ITEMS
    assert sum(1 for r in rows if r["group"] == "fake_b") == 3


def test_sample_with_accept_is_refused_and_writes_nothing(gate, monkeypatch):
    assert _run(monkeypatch, "--sample", "3", "--accept") == 2
    assert not parity_check.BASELINE.exists()
    assert not parity_check.LEDGER.exists()


def test_only_with_freeze_is_refused_before_anything_runs(gate, monkeypatch):
    called = []
    monkeypatch.setattr(parity_check, "freeze", lambda: called.append(1))
    assert _run(monkeypatch, "--only", "fake_a", "--freeze") == 2
    assert called == []


def test_unknown_only_name_returns_2(gate, monkeypatch):
    assert _run(monkeypatch, "--only", "nope") == 2
    assert not parity_check.LEDGER.exists()


def test_sampled_run_does_not_create_or_modify_ledger_or_baseline(gate, monkeypatch, capsys):
    parity_check.LEDGER.write_text("untouched\n")
    before = parity_check.LEDGER.read_text()
    assert _run(monkeypatch, "--sample", "3") == 0
    assert parity_check.LEDGER.read_text() == before
    assert not parity_check.BASELINE.exists()
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1] == "PARITY GATE (SAMPLE) PASSED"
    assert "sampled 6 of 20 saved answers" in out


def test_sampled_run_does_not_create_ledger_when_absent(gate, monkeypatch):
    assert _run(monkeypatch, "--sample", "3") == 0
    assert not parity_check.LEDGER.exists()


def test_regression_checked_only_for_replayed_ids(gate, monkeypatch, capsys):
    # every item is locked and now refused by the engine (gap-reject on a locked id = regression); only the 6 replayed ids may fail
    locked = [f"{name}:=1+{i}" for name in NAMES for i in range(ITEMS)]
    parity_check.BASELINE.write_text(json.dumps({"locked": locked, "import_digests": {}}))
    monkeypatch.setattr(parity_check.dax, "local", lambda expr: "LOCAL-REJECT nope")
    assert _run(monkeypatch, "--sample", "3") == 1
    out = capsys.readouterr().out
    assert out.count("FAIL: REGRESSION") == 6
    assert out.strip().splitlines()[-1] == "PARITY GATE (SAMPLE) FAILED"
