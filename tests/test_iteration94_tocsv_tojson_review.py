"""Iteration 94 review: TOCSV / TOJSON against live Power BI (extra batteries, 10-row default, refusals)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

PARITY = Path(__file__).resolve().parents[1] / "tools" / "parity"

# Shapes whose Power BI behaviour differs from the local engine (or is not modelled): they must stay refused.
STAYS_REFUSED = [
    'TOCSV(Facts,5,"")',
    "TOCSV(Facts,1+1)",
    "TOCSV(Facts,DATE(2020,1,1))",
    "TOCSV(Facts,1E20)",
    'TOCSV(ROW("a",1,"b",2),5,SUM(Facts[Quantity]))',
    "TOCSV(TABLEOF(Facts[Region]))",
    "TOJSON(FILTERS(Facts[Quantity]))",  # Power BI sorts FILTERS ascending
    'TOCSV(TREATAS({"West","West"},Facts[Region]),5)',  # Power BI keeps the repeated member
    'TOCSV(SUMMARIZE(FILTER(Facts,Facts[Quantity]>3),Facts[Region],"x",SUM(Facts[Sales])))',  # added column over a FILTER
    'COUNTROWS(DATATABLE("a",INTEGER,{}))',
    'COUNTROWS(DATATABLE("a",DOUBLE,{{1/3}}))',
]


def _mismatches(name: str) -> list[tuple[str, str, str, str]]:
    saved = json.loads((PARITY / f"{name}.json").read_text())
    bad = []
    for item in saved["items"]:
        actual = dax.local(item["expr"])
        outcome = status(item["powerbi"], actual)
        if outcome != "match":
            bad.append((item["expr"], item["powerbi"], actual, outcome))
    return bad


class TocsvTojsonReviewTest(unittest.TestCase):
    def test_extra_battery_matches(self) -> None:
        self.assertEqual([], _mismatches("dax_battery_tocsv_tojson_extra"))

    def test_extra2_battery_matches(self) -> None:
        self.assertEqual([], _mismatches("dax_battery_tocsv_tojson_extra2"))

    def test_default_row_limit_is_ten(self) -> None:
        # live Power BI: every table prints at most 10 rows unless maxRows says otherwise
        out = dax.local("TOCSV(GENERATESERIES(1,50))")
        self.assertEqual(11, len(out.split("\n")))
        out = dax.local("TOCSV(GENERATESERIES(1,50),12)")
        self.assertEqual(13, len(out.split("\n")))

    def test_unary_minus_zero_stays_plain(self) -> None:
        self.assertEqual("0", dax.local("-0.0"))
        self.assertEqual("0", dax.local("-0"))

    def test_shapes_stay_refused(self) -> None:
        for expr in STAYS_REFUSED:
            self.assertTrue(dax.local(expr).startswith("LOCAL-REJECT"), expr)


if __name__ == "__main__":
    unittest.main()
