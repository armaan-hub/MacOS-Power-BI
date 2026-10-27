"""Iteration 93 review (Claude): the extra Power BI probes for ISINTEGER / ISINT64 / ISDOUBLE / ISDECIMAL / ISCURRENCY.

The planned battery missed ROUND/TRUNC/INT/MOD/FLOOR/CEILING/MROUND/EVEN/ODD/MAX/MIN/DIVIDE/AVERAGEX typing and
currency*currency; the review asked Power BI for those shapes and the answers are replayed here.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

PARITY = Path(__file__).resolve().parents[1] / "tools" / "parity"


class TypeTestsReviewTest(unittest.TestCase):
    def test_extra_batteries_match(self) -> None:
        for name in ("dax_battery_type_tests_extra", "dax_battery_type_tests_extra2"):
            items = json.loads((PARITY / f"{name}.json").read_text())["items"]
            bad = [(i["expr"], i["powerbi"], dax.local(i["expr"])) for i in items if status(i["powerbi"], dax.local(i["expr"])) != "match"]
            self.assertEqual([], bad[:10], f"{name}: {len(bad)} of {len(items)} differ")

    def test_review_fixes(self) -> None:
        for expr, answer in (
            ("ISINTEGER(ROUND(1,0))", "True"), ("ISDOUBLE(ROUND(2.5,0))", "True"), ("ISCURRENCY(CURRENCY(1)*CURRENCY(1))", "False"),
            ("ISDOUBLE(CURRENCY(1)*CURRENCY(1))", "True"), ("ISCURRENCY(CURRENCY(2)/0.5)", "True"), ("ISCURRENCY(INT(CURRENCY(1.5)))", "True"),
            ("ISDOUBLE(MAX(1,2.5))", "True"), ("ISCURRENCY(FLOOR(CURRENCY(2.5),1))", "True"), ("ISDOUBLE(EVEN(1.5))", "True"),
            ("ISCURRENCY(AVERAGEX(Facts,CURRENCY(1)))", "True"), ("ISCURRENCY(DIVIDE(CURRENCY(1),2,1.5))", "True"),
        ):
            self.assertEqual("match", status(answer, dax.local(expr)), expr)

    def test_unknown_types_stay_refused(self) -> None:
        for expr in ('ISINTEGER(DIVIDE(1,0,"a"))', "ISINTEGER(SWITCH(2,1,Facts[Quantity],CURRENCY(1)))", "ISDOUBLE(Facts[Sales])",
                     "ISINTEGER(IF(TRUE(),UNKNOWNFN(1),1))"):
            self.assertTrue(dax.local(expr).startswith("LOCAL-REJECT"), expr)


if __name__ == "__main__":
    unittest.main()
