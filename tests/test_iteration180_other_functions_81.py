"""Task 91 (iteration 180): EXTERNALMEASURE, NATURALJOINUSAGE, SAMPLEAXISWITHLOCALMINMAX,
SAMPLECARTESIANPOINTSBYCOVER and SELECTEDMEASUREFORMATSTRING against Power BI's live answers (spec JSON, test only)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio import measures
from tools import dax_oracle_diff as oracle

SPEC = Path(__file__).resolve().parents[1] / "docs" / "plans" / "2026-11-08-other-functions-81-spec.json"
# Power BI samples these two by an unmeasured rule (MaxPoints below the row count of Facts); refusal is the correct local answer.
REFUSED_BY_DESIGN = {
    "COUNTROWS(SAMPLECARTESIANPOINTSBYCOVER(3,Facts,Facts[Quantity],Facts[Sales]))",
    "COUNTROWS(SAMPLECARTESIANPOINTSBYCOVER(5,Facts,Facts[Quantity],Facts[Sales]))",
}
NEW_NAMES = ("EXTERNALMEASURE", "NATURALJOINUSAGE", "SAMPLEAXISWITHLOCALMINMAX", "SAMPLECARTESIANPOINTSBYCOVER", "SELECTEDMEASUREFORMATSTRING")


class OtherFunctions81Test(unittest.TestCase):
    def test_spec_cases_match_power_bi(self):
        cases = json.loads(SPEC.read_text(encoding="utf-8"))["cases"]
        self.assertEqual(len(cases), 66)
        failures = []
        for case in cases:
            expression, power_bi = case["expression"], case["power_bi"]
            local = oracle.local(expression)
            self.assertNotIn("LOCAL-CRASH", local, expression)
            if power_bi.startswith("ERR") or expression in REFUSED_BY_DESIGN:
                ok = local.startswith("LOCAL-REJECT")
            else:
                ok = oracle.same(power_bi, local)
            if not ok:
                failures.append((expression, power_bi[:80], local[:120]))
        self.assertEqual(failures, [])

    def test_radius_must_be_numeric(self):
        """Power BI live answers: argument 5 (Radius) is validated like the coordinates; arguments 6 and 7 are not."""
        base = "COUNTROWS(SAMPLECARTESIANPOINTSBYCOVER(6,Facts,Facts[Quantity],Facts[Sales],{radius},{ratios}))"
        reject = base.format(radius="Facts[Region]", ratios="2,3")
        self.assertEqual(
            oracle.local(reject),
            "LOCAL-REJECT:The SampleCartesianPointsByCover function requires radius parameter (at argument number 5) to be a numeric scalar expression.",
        )
        accepted = [
            base.format(radius="1", ratios="2,3"),
            base.format(radius="Facts[Sales]", ratios='"a",3'),
            base.format(radius="Facts[Sales]", ratios='"a","b"'),
            base.format(radius="Facts[Sales]", ratios="-1,3"),
            base.format(radius="Facts[Sales]", ratios="BLANK(),3"),
        ]
        for expression in accepted:
            self.assertTrue(oracle.same("6", oracle.local(expression)), (expression, oracle.local(expression)))

    def test_names_are_supported(self):
        for name in NEW_NAMES:
            self.assertIn(name, measures.DAX_FUNCTION_NAMES, name)


if __name__ == "__main__":
    unittest.main()
