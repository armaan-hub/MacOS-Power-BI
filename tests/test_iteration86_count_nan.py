"""Iteration 86: COUNTX / COUNTAX do not count NaN (0/0), they count Infinity (x/0).

Found by the fresh probes of the Boolean-arithmetic slice: COUNTX(Facts, Facts[Quantity] / Facts[Quantity]) is 5 in live Power BI Desktop (the
quantity 0 row is 0/0 = NaN), the local engine said 6.  MAXX, MINX, SUMX and AVERAGEX already matched.  A COUNTX whose rows are all NaN is 0, not
BLANK (a NaN is a number, so the count exists), while rows that are all BLANK stay BLANK.

fixtures_iter86_count_nan.json: live Power BI answers (Facts scratch table, headless probe), every one must match."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

SAVED = json.loads((Path(__file__).parent / "fixtures_iter86_count_nan.json").read_text())


class CountSkipsNaN(unittest.TestCase):
    def test_saved_power_bi_answers_match_or_are_refused(self) -> None:
        wrong = []
        for row in SAVED:
            ours = dax.local(row["expr"])
            if status(row["powerbi"], ours) not in {"match", "gap-reject"}:
                wrong.append((row["expr"], row["powerbi"][:40], ours[:60]))
        self.assertEqual([], wrong[:5], f"{len(wrong)} of {len(SAVED)} saved answers are answered wrongly")

    def test_the_rule_spelled_out(self) -> None:
        facts = dax.local
        self.assertEqual("5", facts("COUNTX(Facts,Facts[Quantity]/Facts[Quantity])"))
        self.assertEqual("5", facts("COUNTAX(Facts,Facts[Quantity]/Facts[Quantity])"))
        self.assertEqual("6", facts("COUNTX(Facts,1/0)"))  # Infinity is counted
        self.assertEqual("0", facts("COUNTX(Facts,0/0)"))  # all NaN: a count of zero, not BLANK
        self.assertEqual("3", facts("COUNTAX(Facts,IF(Facts[Quantity]<3,0/0,7))"))
        self.assertEqual("BLANK", facts("COUNTX(Facts,IF(Facts[Quantity]<0,0/0))"))  # every row BLANK


if __name__ == "__main__":
    unittest.main()
