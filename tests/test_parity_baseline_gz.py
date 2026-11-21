"""The lock list lives in ``tools/parity/baseline.json.gz``; the plain ``baseline.json`` is only a read fallback.

Every test points both module names at its own tmp folder, so nothing here touches the real lock list.  The gzip is
written byte-stable (fixed mtime, sorted keys, sorted locked ids), which is what keeps a re-save from churning a
95 MB file.
"""

from __future__ import annotations

import json

from tools import parity_check


def _point_at(tmp_path, monkeypatch):
    """Both module names at this test's own folder; returns (plain, gz)."""
    plain = tmp_path / "baseline.json"
    gz = tmp_path / "baseline.json.gz"
    monkeypatch.setattr(parity_check, "BASELINE", plain)
    monkeypatch.setattr(parity_check, "BASELINE_GZ", gz)
    return plain, gz


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    _plain, gz = _point_at(tmp_path, monkeypatch)
    original = {"locked": ["b:=1", "a:=2"], "import_digests": {"VAT": "digest"}, "powerbi_version": "1.2.3"}
    parity_check.save_baseline(original)
    assert gz.exists()
    assert parity_check.load_baseline() == {**original, "locked": ["a:=2", "b:=1"]}
    assert parity_check.load_baseline() == parity_check.load_baseline()


def test_two_saves_give_identical_bytes(tmp_path, monkeypatch):
    _plain, gz = _point_at(tmp_path, monkeypatch)
    baseline = {"locked": [f"battery:=1+{i}" for i in range(500)], "import_digests": {"VAT": "digest"}}
    parity_check.save_baseline(baseline)
    first = gz.read_bytes()
    parity_check.save_baseline(baseline)
    assert gz.read_bytes() == first
    assert first[:2] == b"\x1f\x8b"  # a gzip member, not plain json


def test_load_falls_back_to_plain_json_when_no_gz(tmp_path, monkeypatch):
    plain, gz = _point_at(tmp_path, monkeypatch)
    plain.write_text(json.dumps({"locked": ["a:=1"], "import_digests": {"VAT": "digest"}}))
    assert not gz.exists()
    assert parity_check.load_baseline() == {"locked": ["a:=1"], "import_digests": {"VAT": "digest"}}


def test_gz_wins_when_both_exist(tmp_path, monkeypatch):
    plain, _gz = _point_at(tmp_path, monkeypatch)
    plain.write_text(json.dumps({"locked": ["plain:=1"], "import_digests": {}}))
    parity_check.save_baseline({"locked": ["gz:=2"], "import_digests": {"VAT": "digest"}})
    assert plain.exists()
    assert parity_check.load_baseline() == {"locked": ["gz:=2"], "import_digests": {"VAT": "digest"}}


def test_neither_file_gives_an_empty_lock_list(tmp_path, monkeypatch):
    _point_at(tmp_path, monkeypatch)
    assert parity_check.load_baseline() == {"locked": [], "import_digests": {}}
