"""Iteration 96 Part C review: the ROLLUP family against live Power BI Desktop (2.157.879.0).

Three review batteries (3,243 + 2,431 + 168 shapes that are not in dax_battery_table_fns2.json) and 900 more asked on two other Facts
tables (rows in another order, groups not in alphabetical order) never differ from Power BI. The first build matched the 23 saved
items and differed from Power BI on 686 of the first 4,055 fresh shapes. What they showed:
  - SUMMARIZE lists every subtotal level on its own, in the dictionary order of the columns that level keeps; SUMMARIZECOLUMNS builds
    the subtotal rows of ROLLUPADDISSUBTOTAL from the detail rows when its expressions are aggregates ("first appearance in the
    detail rows") and level by level in dictionary order when there is no expression or one that is not (IF, a constant ...);
  - ROLLUPADDISSUBTOTAL calls are groups of a cube (the first group varies fastest), the pairs inside one call roll up from the last;
  - errors: two ROLLUP groups in SUMMARIZE, a column named twice, a name written like the column, a name without an expression,
    ISSUBTOTAL of a column that is not a group column or inside an iterator;
  - an empty table has no subtotal rows at all, a combination whose expressions are all BLANK takes no part in the subtotals;
  - KEEPFILTERS around the table of an iterator does not change its walk order.
Refused on purpose: expressions that read the filter state of a group column (SELECTEDVALUE, VALUES, ISINSCOPE ...), DISTINCTCOUNT /
COUNTA beside ROLLUPADDISSUBTOTAL, IGNORE / NONVISUAL there, and SUMMARIZE ROLLUP without an added column except directly inside
COUNTROWS, TOCSV or TOJSON.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio.measures import MeasureError, evaluate_measures
from tools import dax_oracle_diff as dax
from tools.dax_oracle_diff import HEADERS
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]
PARITY = ROOT / "tools" / "parity"

R, N, Q = "Facts[Region]", "Facts[Note]", "Facts[Quantity]"

# Valid DAX (Power BI answers) that the local engine refuses on purpose.
STAYS_REFUSED = [
    f'TOCSV(SUMMARIZE(Facts,ROLLUP({R}),"v",SELECTEDVALUE({R})))',
    f'TOCSV(SUMMARIZE(Facts,ROLLUP({R}),"v",ISINSCOPE({R})))',
    f'TOCSV(SUMMARIZE(Facts,ROLLUP({R}),"v",COUNTROWS(VALUES({R}))))',
    f'TOCSV(SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL({R},"t"),"s",DISTINCTCOUNT({N})))',
    f'TOCSV(SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL({R},"t"),"s",SELECTEDVALUE({R},"all")))',
    f'TOCSV(SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL({R},"t"),"s",IGNORE(SUM({Q}))))',
    f"CONCATENATEX(SUMMARIZE(Facts,ROLLUP({R})),{R},\",\")",  # a ROLLUP with no added column is read only by COUNTROWS, TOCSV, TOJSON
    f"COUNTROWS(FILTER(SUMMARIZE(Facts,ROLLUP({R})),TRUE()))",
]

# Power BI answers an error; the local engine must not produce a value.
ERRORS = [
    f"COUNTROWS(SUMMARIZE(Facts,ROLLUP({R}),ROLLUP({N})))",  # more than one group of subtotal columns
    f'TOCSV(SUMMARIZE(Facts,ROLLUP({R}),ROLLUP({N}),"s",SUM({Q})))',
    f"COUNTROWS(SUMMARIZE(Facts,ROLLUP({R},{R})))",  # a column named twice
    f"COUNTROWS(SUMMARIZE(Facts,{R},ROLLUP({R})))",
    f"COUNTROWS(SUMMARIZE(Facts,ROLLUP(ROLLUPGROUP({R},{N}),{R})))",
    f'COUNTROWS(SUMMARIZE(Facts,ROLLUP({R}),"{R}",SUM({Q})))',  # a name written like the column
    f'COUNTROWS(SUMMARIZE(Facts,ROLLUP({R}),"Region",SUM({Q})))',
    f'COUNTROWS(SUMMARIZE(Facts,ROLLUP({R}),"s"))',  # a name without an expression
    f'TOCSV(SUMMARIZE(Facts,ROLLUP({R}),"s",SUM({Q}),"x",ISSUBTOTAL({N})))',  # ISSUBTOTAL of a column that is not a group column
    f'TOCSV(SUMMARIZE(Facts,ROLLUP({R}),"s",SUM({Q}),"x",ISSUBTOTAL({Q})))',
    f'TOCSV(SUMMARIZE(Facts,ROLLUP({R}),"x",SUMX(VALUES({R}),IF(ISSUBTOTAL({R}),1,0))))',  # ISSUBTOTAL inside an iterator
    f"COUNTROWS(ROLLUP({R}))",
    f"TOCSV(ROLLUPGROUP({R},{N}))",
    f'TOCSV(SUMMARIZECOLUMNS(ROLLUP({R}),"s",SUM({Q})))',
    f'TOCSV(SUMMARIZECOLUMNS(ROLLUPGROUP({R}),"s",SUM({Q})))',
    f'TOCSV(SUMMARIZE(Facts,ROLLUPADDISSUBTOTAL({R},"t"),"s",SUM({Q})))',
    f"COUNTROWS(KEEPFILTERS(VALUES({R})))",
]


def _replay(name: str) -> tuple[int, list[tuple[str, str, str, str]]]:
    saved = json.loads((PARITY / f"{name}.json").read_text())
    matched, bad = 0, []
    for item in saved["items"]:
        actual = dax.local(item["expr"])
        outcome = status(item["powerbi"], actual)
        if outcome == "match":
            matched += 1
        elif outcome != "gap-reject":
            bad.append((item["expr"], item["powerbi"], actual, outcome))
    return matched, bad


def _local_on(rows: list[tuple[str, ...]], expression: str) -> str:
    data = [{h: (v if v != "" else None) for h, v in zip(HEADERS, row)} for row in rows]
    saved = dax.ROWS, dax.LOCAL_ROWS
    dax.ROWS, dax.LOCAL_ROWS = rows, data
    try:
        return dax.local(expression)
    finally:
        dax.ROWS, dax.LOCAL_ROWS = saved


class RollupReviewTest(unittest.TestCase):
    def test_review_batteries_never_differ_from_power_bi(self) -> None:
        for name, floor in (("dax_battery_rollup_extra", 3000), ("dax_battery_rollup_extra2", 2300), ("dax_battery_rollup_extra3", 150)):
            matched, bad = _replay(name)
            self.assertEqual([], bad, name)
            self.assertGreaterEqual(matched, floor, name)

    def test_other_facts_tables_never_differ_from_power_bi(self) -> None:
        """900 shapes on two Facts tables whose groups are not in alphabetical order (the order rules are not luck of the standard rows)."""
        fixture = json.loads((ROOT / "tests" / "fixtures_rollup_alt.json").read_text())
        for key, dataset in fixture["datasets"].items():
            rows = [tuple(row) for row in dataset["rows"]]
            bad = []
            for item in dataset["items"]:
                outcome = status(item["powerbi"], _local_on(rows, item["expr"]))
                if outcome != "match":
                    bad.append((item["expr"], item["powerbi"], outcome))
            self.assertEqual([], bad, key)
            self.assertGreaterEqual(len(dataset["items"]), 400)

    def test_summarize_levels_are_ordered_one_by_one(self) -> None:
        """Rows East/Paid/2, West/-/3, East/Paid/1, North/Late/4, West/Paid/0, East/-/5. SUMMARIZE lists the levels on their own."""
        self.assertEqual(
            "'Facts'[Region],'Facts'[Quantity],[s]\nEast,1,1\nEast,2,2\nEast,5,5\nWest,0,0\nWest,3,3\nNorth,4,4\n,0,0\n,1,1\n,2,2\n,3,3\n,4,4\n,5,5",
            dax.local(f'TOCSV(SUMMARIZE(Facts,ROLLUP({R}),{Q},"s",SUM({Q})),100)'),
        )

    def test_summarizecolumns_subtotals_follow_the_detail_rows(self) -> None:
        self.assertEqual(  # aggregates: each level in the order its combinations first appear in the detail rows
            "'Facts'[Quantity],'Facts'[Region],[t],[s]\n1,East,FALSE,1\n2,East,FALSE,2\n5,East,FALSE,5\n0,West,FALSE,0\n3,West,FALSE,3\n4,North,FALSE,4\n1,,TRUE,1\n2,,TRUE,2\n5,,TRUE,5\n0,,TRUE,0\n3,,TRUE,3\n4,,TRUE,4",
            dax.local(f'TOCSV(SUMMARIZECOLUMNS({Q},ROLLUPADDISSUBTOTAL({R},"t"),"s",SUM({Q})),100)'),
        )
        self.assertEqual(  # no expression: each level on its own in dictionary order
            "'Facts'[Quantity],'Facts'[Region],[t]\n1,East,FALSE\n2,East,FALSE\n5,East,FALSE\n0,West,FALSE\n3,West,FALSE\n4,North,FALSE\n0,,TRUE\n1,,TRUE\n2,,TRUE\n3,,TRUE\n4,,TRUE\n5,,TRUE",
            dax.local(f'TOCSV(SUMMARIZECOLUMNS({Q},ROLLUPADDISSUBTOTAL({R},"t")),100)'),
        )

    def test_separate_rollupaddissubtotal_calls_form_a_cube(self) -> None:
        self.assertEqual(
            "12",
            dax.local(f'COUNTROWS(SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL({R},"a"),ROLLUPADDISSUBTOTAL({N},"b"),"s",SUM({Q})))'),
        )
        self.assertEqual(  # one call with two pairs is one hierarchy: 5 + 3 + 1 rows
            "9",
            dax.local(f'COUNTROWS(SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL({R},"a",{N},"b"),"s",SUM({Q})))'),
        )

    def test_bare_rollup_counts_levels_and_prints_rows(self) -> None:
        self.assertEqual("3", dax.local(f"COUNTROWS(SUMMARIZE(Facts,ROLLUP({R},{N})))"))
        self.assertEqual(
            "'Facts'[Region]\nEast\nWest\nNorth\n",
            dax.local(f"TOCSV(SUMMARIZE(Facts,ROLLUP({R})))"),
        )

    def test_an_empty_table_has_no_subtotal_rows(self) -> None:
        self.assertEqual("BLANK", dax.local(f'COUNTROWS(SUMMARIZE(FILTER(Facts,FALSE()),ROLLUP({R}),"s",SUM({Q})))'))
        self.assertEqual(
            "'Facts'[Region],[t],[s]\n",
            dax.local(f'TOCSV(SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL({R},"t"),FILTER(ALL(Facts),FALSE()),"s",SUM({Q})))'),
        )

    def test_keepfilters_does_not_change_the_walk_order(self) -> None:
        for table in ("Facts", f"FILTER(Facts,{Q}>1)", "ALL(Facts)", f"TOPN(2,Facts,{Q})", f"VALUES({R})"):
            plain = dax.local(f'CONCATENATEX({table},{R},"|")')
            self.assertEqual(plain, dax.local(f'CONCATENATEX(KEEPFILTERS({table}),{R},"|")'), table)

    def test_errors_stay_errors(self) -> None:
        for expression in ERRORS:
            outcome = dax.local(expression)
            self.assertTrue(outcome.startswith(("LOCAL-REJECT", "ERR:")), f"{expression} -> {outcome}")

    def test_valid_dax_stays_refused(self) -> None:
        for expression in STAYS_REFUSED:
            outcome = dax.local(expression)
            self.assertTrue(outcome.startswith("LOCAL-REJECT"), f"{expression} -> {outcome}")

    def test_the_measure_dialog_has_templates(self) -> None:
        from analytics_studio.measure_dialog import DAX_FUNCTION_TEMPLATES

        for name in ("ROLLUP", "ROLLUPGROUP", "ROLLUPADDISSUBTOTAL", "ROLLUPISSUBTOTAL", "ISSUBTOTAL"):
            self.assertIn(name, DAX_FUNCTION_TEMPLATES)


if __name__ == "__main__":
    unittest.main()
