"""Unit tests for exit_check.compare_results: both-error and reject handling.

No guest VM connection required. Uses tiny temp JSON files via tmp_path.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools import exit_check


def _compare(tmp_path: Path, pbi_ans: str, loc_ans: str) -> dict:
    """Write one item to each side and run compare_results on them."""
    file_a = tmp_path / "pbi.json"
    file_b = tmp_path / "local.json"
    file_a.write_text(json.dumps([{"id": "t1", "expr": "1", "powerbi": pbi_ans}]), encoding="utf-8")
    file_b.write_text(json.dumps([{"id": "t1", "expr": "1", "local": loc_ans, "time_ms": 1.0}]), encoding="utf-8")
    return exit_check.compare_results(str(file_a), str(file_b))


def test_match(tmp_path: Path) -> None:
    stats = _compare(tmp_path, "42", "42")
    assert stats["right"] == 1
    assert stats["wrong"] == 0
    assert stats["refused"] == 0
    assert stats["both_error"] == 0
    assert stats["crash"] == 0
    assert stats["wrong_items"] == []


def test_mismatch(tmp_path: Path) -> None:
    stats = _compare(tmp_path, "42", "43")
    assert stats["right"] == 0
    assert stats["wrong"] == 1
    assert stats["both_error"] == 0
    assert [w["category"] for w in stats["wrong_items"]] == ["mismatch"]


def test_local_reject_with_pbi_error_is_both_error(tmp_path: Path) -> None:
    stats = _compare(tmp_path, "ERR: something failed", "LOCAL-REJECT: unsupported")
    assert stats["both_error"] == 1
    assert stats["refused"] == 0
    assert stats["wrong"] == 0
    assert stats["wrong_items"] == []


def test_local_reject_with_pbi_value_is_refused(tmp_path: Path) -> None:
    stats = _compare(tmp_path, "42", "LOCAL-REJECT: unsupported")
    assert stats["refused"] == 1
    assert stats["both_error"] == 0
    assert stats["wrong"] == 0
    assert [w["category"] for w in stats["wrong_items"]] == ["refused"]


def test_local_crash(tmp_path: Path) -> None:
    stats = _compare(tmp_path, "42", "LOCAL-CRASH: boom")
    assert stats["crash"] == 1
    assert stats["refused"] == 0
    assert stats["both_error"] == 0
    assert [w["category"] for w in stats["wrong_items"]] == ["crash"]


def test_pbi_error_with_local_value_is_wrong(tmp_path: Path) -> None:
    stats = _compare(tmp_path, "ERR: something failed", "42")
    assert stats["wrong"] == 1
    assert stats["both_error"] == 0
    assert stats["refused"] == 0
    assert [w["category"] for w in stats["wrong_items"]] == ["mismatch"]
