"""Tests for tools/perf_check.py: running on size 200, fast formula, and timeout path."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from tools import perf_check


def test_perf_check_fast_formula(monkeypatch) -> None:
    monkeypatch.setenv(perf_check.SLEEP_ENV, "0")
    with tempfile.TemporaryDirectory() as tmpdir:
        out_json = str(Path(tmpdir) / "out.json")
        rows = perf_check.main(["--sizes", "200", "--only", "SUM", "--json", out_json])
        assert len(rows) == 1
        row = rows[0]
        assert row["size"] == 200
        assert row["name"] == "SUM"
        assert row["status"] == "ok"
        assert isinstance(row["seconds"], float)
        assert row["seconds"] >= 0
        assert isinstance(row["peak_mb"], float)
        assert row["peak_mb"] > 0
        assert row["value"] != ""

        saved = json.loads(Path(out_json).read_text(encoding="utf-8"))
        assert len(saved) == 1
        assert saved[0]["name"] == "SUM"
        assert saved[0]["status"] == "ok"


def test_perf_check_timeout_path(monkeypatch) -> None:
    monkeypatch.setenv(perf_check.SLEEP_ENV, "1.5")
    rows = perf_check.main(["--sizes", "200", "--only", "SUM", "--timeout", "0.5"])
    assert len(rows) == 1
    row = rows[0]
    assert row["size"] == 200
    assert row["name"] == "SUM"
    assert row["status"] == "timeout"
    assert isinstance(row["seconds"], float)
    assert row["seconds"] >= 0.4
    assert row["value"] == ""
    assert isinstance(row["peak_mb"], float)


def test_perf_check_skipped_over_max_rows() -> None:
    rows = perf_check.main(["--sizes", "5000", "--only", "SUM", "--max-rows", "2000"])
    assert len(rows) == 1
    row = rows[0]
    assert row["size"] == 5000
    assert row["status"] == "skipped (over --max-rows)"
    assert row["seconds"] == ""
    assert row["value"] == ""
