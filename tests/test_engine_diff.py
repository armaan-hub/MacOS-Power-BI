"""Tests for tools/engine_diff.py."""

from __future__ import annotations

import json
from pathlib import Path

from tools import engine_diff


def test_reference_vs_reference_gives_zero_diff_and_crash(tmp_path: Path) -> None:
    json_path = tmp_path / "out.json"
    exit_code = engine_diff.main(["--rows", "200", "--json", str(json_path)])
    assert exit_code == 0
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(saved) >= 40
    assert all(row["status"] == "same" for row in saved)


def test_fake_right_path_diff(monkeypatch) -> None:
    def fake_right(expression: str, table: dict) -> str:
        return "DIFFERENT_ANSWER"

    monkeypatch.setitem(engine_diff.PATHS, "fake_diff", fake_right)
    rows, counts = engine_diff.run_diff(left_name="reference", right_name="fake_diff", row_count=50)
    assert counts["DIFF"] > 0
    assert counts["CRASH"] == 0
    exit_code = engine_diff.main(["--left", "reference", "--right", "fake_diff", "--rows", "50"])
    assert exit_code == 1


def test_fake_right_path_crash(monkeypatch) -> None:
    def fake_crash(expression: str, table: dict) -> str:
        return "LOCAL-CRASH:RuntimeError:simulated crash"

    monkeypatch.setitem(engine_diff.PATHS, "fake_crash", fake_crash)
    rows, counts = engine_diff.run_diff(left_name="reference", right_name="fake_crash", row_count=50)
    assert counts["CRASH"] == len(rows)
    assert counts["DIFF"] == 0
    exit_code = engine_diff.main(["--left", "reference", "--right", "fake_crash", "--rows", "50"])
    assert exit_code == 1


def test_formulas_file_honoured(tmp_path: Path) -> None:
    formulas_file = tmp_path / "custom_formulas.json"
    formulas_data = [
        {"name": "CUSTOM_SUM", "expr": "SUM(Facts[Sales])"},
        {"name": "CUSTOM_MAX", "expr": "MAX(Facts[Quantity])"},
    ]
    formulas_file.write_text(json.dumps(formulas_data), encoding="utf-8")
    out_json = tmp_path / "out.json"

    exit_code = engine_diff.main(["--formulas", str(formulas_file), "--rows", "50", "--json", str(out_json)])
    assert exit_code == 0
    saved = json.loads(out_json.read_text(encoding="utf-8"))
    assert len(saved) == 2
    assert saved[0]["name"] == "CUSTOM_SUM"
    assert saved[1]["name"] == "CUSTOM_MAX"
    assert saved[0]["status"] == "same"
    assert saved[1]["status"] == "same"


def test_generation_deterministic_for_same_seed() -> None:
    table1 = engine_diff.generate_table(100, seed=42)
    table2 = engine_diff.generate_table(100, seed=42)
    table3 = engine_diff.generate_table(100, seed=99)

    assert table1["rows"] == table2["rows"]
    assert table1["rows"] != table3["rows"]
