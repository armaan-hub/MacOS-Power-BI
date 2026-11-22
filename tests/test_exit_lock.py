"""The parity gate's exit_model group: the exit-test model's saved Power BI answers are replayed locally and locked like the DAX batteries."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import parity_check  # noqa: E402


def _items() -> list[dict]:
    items = parity_check.exit_answers()
    assert items is not None, "saved exit-model answer files are missing"
    return items


def _by_id(items: list[dict], item_id: str) -> dict:
    return next(item for item in items if item["id"] == item_id)


def test_group_loads_all_items_with_unique_ids():
    items = _items()
    assert len(items) == 663
    ids = [item["id"] for item in items]
    assert len(set(ids)) == len(ids)


def test_small_slice_matches_power_bi():
    # Five fast items; XT-AB-008 (about 60 s locally) is left out on purpose.
    slice_ = [item for item in _items() if item["id"] != "XT-AB-008"][:5]
    rows = parity_check._replay_exit(slice_, parity_check.load_known_diffs())
    assert len(rows) == 5
    for row in rows:
        assert row["group"] == parity_check.EXIT_GROUP
        assert row["id"].startswith("exit_model:")
        assert row["status"] == "match", (row["id"], row["powerbi"], row["ours"])


def test_doctored_expectation_is_a_diff():
    item = copy.deepcopy([i for i in _items() if i["id"] != "XT-AB-008"][0])
    item["powerbi"] = "424242.5"
    rows = parity_check._replay_exit([item], parity_check.load_known_diffs())
    assert rows[0]["status"] == "DIFF", (rows[0]["powerbi"], rows[0]["ours"], rows[0]["status"])


def test_known_open_items_are_not_diffs():
    items = _items()
    known_items = [_by_id(items, "HP-043"), _by_id(items, "HP-061")]
    rows = {row["id"]: row for row in parity_check._replay_exit(known_items, parity_check.load_known_diffs())}
    assert rows["exit_model:HP-043"]["status"] == "known-diff", rows["exit_model:HP-043"]
    assert rows["exit_model:HP-061"]["status"] == "gap-reject", rows["exit_model:HP-061"]
    assert all(row["status"] != "DIFF" for row in rows.values())
