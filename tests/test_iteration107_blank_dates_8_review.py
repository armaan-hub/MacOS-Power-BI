"""Review of Task 18 (blank-dates-8): fresh Power BI answers on other tables.

Every expected value is Power BI's answer. Fresh answers: dax_battery_blank8_extra (the standard table) and tests/fixtures_blank8_review_alt.json.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures_blank8_review_alt.json").read_text())
CHUNK_SIZE = 15000
CHUNKS = []
for ds_name, ds in sorted(FIXTURE["datasets"].items()):
    ds_items = ds["items"]
    rows = ds["rows"]
    for i in range(0, len(ds_items), CHUNK_SIZE):
        CHUNKS.append((ds_name, rows, ds_items[i:i + CHUNK_SIZE]))


@pytest.mark.parametrize("ds_name,rows,items", CHUNKS)
def test_fresh_probes_on_another_table_match_or_are_refused(ds_name: str, rows: list, items: list[dict]) -> None:
    saved = (dax.ROWS, dax.LOCAL_ROWS)
    try:
        dax.ROWS = [tuple(r) for r in rows]
        dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, r)} for r in dax.ROWS]
        wrong = [(item["expr"], item["powerbi"][:60]) for item in items if status(item["powerbi"], dax.local(item["expr"])) not in {"match", "gap-reject"}]
        assert wrong == [], f"{len(wrong)} of {len(items)} failed in dataset {ds_name}"
    finally:
        dax.ROWS, dax.LOCAL_ROWS = saved


class FreshProbesTest(unittest.TestCase):
    pass


if __name__ == "__main__":
    unittest.main()
