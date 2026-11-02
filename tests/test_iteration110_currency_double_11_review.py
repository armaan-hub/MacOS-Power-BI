"""Review of Task 21 (currency-double-11): fresh Power BI answers on other tables.

Every expected value is Power BI's answer. Fresh answers: dax_battery_currency11_extra (the standard table) and tests/fixtures_currency11_review_alt.json.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]


class FreshProbesTest(unittest.TestCase):
    def test_fresh_probes_on_another_table_match_or_are_refused(self) -> None:
        fixture = json.loads((ROOT / "tests" / "fixtures_currency11_review_alt.json").read_text())
        saved = (dax.ROWS, dax.LOCAL_ROWS)
        try:
            for dataset in fixture["datasets"].values():
                dax.ROWS = [tuple(row) for row in dataset["rows"]]
                dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in dax.ROWS]
                wrong = [(item["expr"], item["powerbi"][:60]) for item in dataset["items"] if status(item["powerbi"], dax.local(item["expr"])) not in {"match", "gap-reject"}]
                self.assertEqual([], wrong[:10])
        finally:
            dax.ROWS, dax.LOCAL_ROWS = saved


if __name__ == "__main__":
    unittest.main()
