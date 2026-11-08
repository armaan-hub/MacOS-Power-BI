"""Task 96 (Iteration 185): CROSSFILTER directions and CROSSFILTER with USERELATIONSHIP (crossfilter-dirs-86).

The spec file holds Power BI's live answers (630 cases on models ZO and ZB of tests/critic3_models.py). Only this test
reads it; the app never does. Rule: an ERR case must be refused (LOCAL-REJECT); a value case must match Power BI (same),
with no refusal and no crash (LOCAL-CRASH).
"""

import json
import unittest
from pathlib import Path

from tools.dax_oracle_diff import same

SPEC = Path(__file__).resolve().parents[1] / "docs" / "plans" / "2026-11-08-crossfilter-dirs-86-spec.json"


class CrossfilterDirectionsSpecTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(SPEC.read_text(encoding="utf-8"))["cases"]

    def test_every_spec_case(self):
        from tests import critic3_models

        failures = []
        total = 0
        for model in ("ZO", "ZB"):
            for case in self.cases[model]:
                total += 1
                expression, expected = case["expression"], case["power_bi"]
                ours = critic3_models.ours_for(model, expression)
                if ours.startswith("LOCAL-CRASH"):
                    failures.append(f"CRASH {model} {expression!r}: {ours[:120]}")
                    continue
                if expected.startswith("ERR:"):
                    if not ours.startswith("LOCAL-REJECT"):
                        failures.append(f"NOT REFUSED {model} {expression!r}: local {ours[:80]!r}, Power BI {expected[:80]!r}")
                    continue
                if ours.startswith("LOCAL-REJECT"):
                    failures.append(f"REFUSED {model} {expression!r}: local {ours[:80]!r}, Power BI {expected[:80]!r}")
                elif not same(expected, ours):
                    failures.append(f"WRONG {model} {expression!r}: local {ours[:80]!r}, Power BI {expected[:80]!r}")
        self.assertEqual(failures, [], f"{len(failures)} of {total} spec cases fail:\n" + "\n".join(failures[:40]))


if __name__ == "__main__":
    unittest.main()
