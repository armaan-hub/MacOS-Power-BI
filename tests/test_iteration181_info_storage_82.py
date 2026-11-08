"""Task 92 (Iteration 181): the 22 INFO functions Power BI has and the app lacked (info-storage-82).

The spec file holds Power BI's live answers. Only this test reads it; the app never does.
Rule: an ERR answer must be refused (LOCAL-REJECT). A value answer must match, or be refused when the
function is one whose rows are engine storage metadata (GROUP_C). Nothing may crash or be wrong.
"""

import json
import re
import unittest
from pathlib import Path

from analytics_studio import measures
from tools.dax_oracle_diff import local, same

SPEC = Path(__file__).resolve().parents[1] / "docs" / "plans" / "2026-11-08-info-storage-82-spec.json"

# Group A: Power BI returns no rows (empty-table schemas)
GROUP_A = {"INFO.ANNOTATIONS", "INFO.CULTURES"}
# Group B: Power BI returns exactly one row; every value is unmodelled
GROUP_B = {"INFO.MODEL", "INFO.CATALOGS", "INFO.CSDLMETADATA"}
# Group C: row count depends on engine storage / static engine metadata; rows are refused
GROUP_C = {
    "INFO.ATTRIBUTEHIERARCHIES", "INFO.ATTRIBUTEHIERARCHYSTORAGES", "INFO.COLUMNPARTITIONSTORAGES",
    "INFO.COLUMNSTORAGES", "INFO.DICTIONARYSTORAGES", "INFO.FUNCTIONS", "INFO.PARTITIONS",
    "INFO.PARTITIONSTORAGES", "INFO.PROPERTIES", "INFO.SEGMENTMAPSTORAGES", "INFO.SEGMENTSTORAGES",
    "INFO.STORAGEFILES", "INFO.STORAGEFOLDERS", "INFO.STORAGETABLECOLUMNS",
    "INFO.STORAGETABLECOLUMNSEGMENTS", "INFO.STORAGETABLES", "INFO.TABLESTORAGES",
}
ALL_NEW = GROUP_A | GROUP_B | GROUP_C


def _function_name(expression: str) -> str:
    match = re.search(r"INFO\.[A-Z]+(?:\.[A-Z]+)?", expression)
    return match.group(0) if match else ""


def _power_bi_matches(expression: str, power_bi: str, loc: str) -> bool:
    if same(power_bi, loc):
        return True
    # TOCSV answers from Power BI end with a line break; the local header-only answer does not
    # (same convention as the earlier INFO tests)
    if expression.startswith("TOCSV(") and power_bi.endswith("\n"):
        return same(power_bi[:-1], loc)
    return False


class TestIteration181InfoStorage82(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = json.loads(SPEC.read_text(encoding="utf-8"))
        cls.cases = cls.spec["cases"]

    def test_all_22_names_are_registered(self):
        self.assertEqual(len(ALL_NEW), 22)
        for name in sorted(ALL_NEW):
            self.assertIn(name, measures.DAX_FUNCTION_NAMES, name)

    def test_spec_covers_the_22_functions(self):
        seen = {_function_name(case["expression"]) for case in self.cases}
        self.assertEqual(seen, ALL_NEW)

    def test_every_spec_case_matches_or_is_refused(self):
        for case in self.cases:
            expression, power_bi = case["expression"], case["power_bi"]
            name = _function_name(expression)
            with self.subTest(expression=expression):
                loc = local(expression)
                self.assertFalse(loc.startswith("LOCAL-CRASH"), loc)
                if power_bi.startswith("ERR:"):
                    self.assertTrue(loc.startswith("LOCAL-REJECT"), f"Power BI {power_bi[:80]} but local {loc[:120]}")
                    continue
                if loc.startswith("LOCAL-REJECT") and name in GROUP_C:
                    continue
                self.assertTrue(
                    _power_bi_matches(expression, power_bi, loc),
                    f"Power BI {power_bi[:80]!r} but local {loc[:120]!r}",
                )

    def test_group_c_rows_are_refused_never_counted(self):
        for name in sorted(GROUP_C):
            with self.subTest(name=name):
                self.assertTrue(local(f"COUNTROWS({name}())").startswith("LOCAL-REJECT"))
                self.assertTrue(local(f'IF(ISEMPTY({name}()),"e","n")').startswith("LOCAL-REJECT"))
                self.assertTrue(local(f"TOCSV(FILTER({name}(),FALSE()),3,\",\",TRUE)").startswith("LOCAL-REJECT"))

    def test_group_c_restriction_errors_still_fire(self):
        for name in sorted(GROUP_C):
            with self.subTest(name=name):
                numeric = local(f"COUNTROWS({name}(1))")
                self.assertTrue(numeric.startswith(
                    f"LOCAL-REJECT:The '{name}' function expects a constant string representing a restriction name."), numeric)
                named = local(f'COUNTROWS({name}("ID"))')
                self.assertTrue(named.startswith("LOCAL-REJECT:'ID' is not a valid restriction name."), named)

    def test_group_b_single_row_values_are_never_readable(self):
        for name in sorted(GROUP_B):
            with self.subTest(name=name):
                self.assertEqual(local(f"COUNTROWS({name}())"), "1")
                self.assertEqual(local(f'IF(ISEMPTY({name}()),"e","n")'), "n")
                self.assertTrue(local(f"{name}()").startswith("LOCAL-REJECT"))

    def test_group_a_is_empty(self):
        for name in sorted(GROUP_A):
            with self.subTest(name=name):
                self.assertEqual(local(f"COUNTROWS({name}())"), "BLANK")
                self.assertEqual(local(f'IF(ISEMPTY({name}()),"e","n")'), "e")


if __name__ == "__main__":
    unittest.main()
