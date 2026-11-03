"""Iteration 124: colstats-utc-24 (COLUMNSTATISTICS, UTCNOW, UTCTODAY).

Plan: docs/plans/2026-11-03-colstats-utc-24.md
Spec: tools/parity/task34_colstats_utc_spec.json
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]


class ColstatsUtc24Test(unittest.TestCase):
    def test_columnstatistics_structure_and_values(self) -> None:
        self.assertEqual(dax.local("COUNTROWS(COLUMNSTATISTICS())"), "5")
        self.assertEqual(
            dax.local('CONCATENATEX(COLUMNSTATISTICS(),[Column Name],"|")'),
            "RowNumber-2662979B-1795-4F74-8F37-6A1BA8059B61|Sales|Quantity|Region|Note",
        )
        self.assertEqual(
            dax.local('CONCATENATEX(COLUMNSTATISTICS(),[Cardinality],"|")'),
            "6|6|6|3|3",
        )
        self.assertEqual(
            dax.local('CONCATENATEX(COLUMNSTATISTICS(),[Min],"|")'),
            "|-1.5|0|East|Late",
        )
        self.assertEqual(
            dax.local('CONCATENATEX(COLUMNSTATISTICS(),[Max],"|")'),
            "|20|5|West|Paid",
        )
        self.assertEqual(
            dax.local('CONCATENATEX(COLUMNSTATISTICS(),[Max Length],"|")'),
            "|||5|4",
        )
        self.assertEqual(dax.local("SUMX(COLUMNSTATISTICS(),[Cardinality])"), "24")
        self.assertEqual(dax.local("SUMX(COLUMNSTATISTICS(),[Max Length])"), "9")

    def test_columnstatistics_guards_and_errors(self) -> None:
        # Scalar conversion
        scalar_res = dax.local("COLUMNSTATISTICS()")
        self.assertTrue(scalar_res.startswith("LOCAL-REJECT:"))
        self.assertIn("The expression refers to multiple columns", scalar_res)

        # Arity check
        arg_res = dax.local("COLUMNSTATISTICS(1)")
        self.assertTrue(arg_res.startswith("LOCAL-REJECT:"))
        self.assertIn("Too many arguments were passed to the COLUMNSTATISTICS function", arg_res)

        # Filter context
        filter_res = dax.local('CALCULATE(COUNTROWS(COLUMNSTATISTICS()),Facts[Region]="East")')
        self.assertTrue(filter_res.startswith("LOCAL-REJECT:"))
        self.assertIn("COLUMNSTATISTICS() cannot be used with a filter context", filter_res)

    def test_utc_functions(self) -> None:
        self.assertEqual(dax.local("YEAR(UTCNOW())>2000"), "True")
        self.assertEqual(dax.local("HOUR(UTCTODAY())"), "0")
        self.assertEqual(dax.local("MINUTE(UTCTODAY())"), "0")
        self.assertEqual(dax.local("SECOND(UTCTODAY())"), "0")
        self.assertEqual(dax.local("INT(UTCNOW())=UTCTODAY()"), "True")
        self.assertEqual(dax.local("ISDATETIME(UTCNOW())"), "True")
        self.assertEqual(dax.local("ISDATETIME(UTCTODAY())"), "True")

        # Arity checks
        self.assertTrue(dax.local("UTCNOW(1)").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local("UTCTODAY(1)").startswith("LOCAL-REJECT:"))

    def test_task34_spec_scores_zero_wrong(self) -> None:
        spec_path = ROOT / "tools" / "parity" / "task34_colstats_utc_spec.json"
        items = json.loads(spec_path.read_text(encoding="utf-8"))["items"]
        wrong = []
        for item in items:
            ours = dax.local(item["expr"])
            st = status(item["powerbi"], ours)
            if st not in ("match", "gap-reject"):
                wrong.append((item["part"], item["expr"], item["powerbi"], ours))
        self.assertEqual(len(wrong), 0, f"Found wrong items: {wrong}")


if __name__ == "__main__":
    unittest.main()
