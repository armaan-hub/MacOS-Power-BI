"""Iteration 96 Part B review: ADDMISSINGITEMS against live Power BI Desktop (2.157.879.0).

Two review batteries (4,724 and 3,743 shapes that are not in dax_battery_table_fns2.json) never differ from Power BI. What they showed:
  - the added rows are built level by level in groupBy order: a showAll level takes the values of its column that exist in the model
    beside the values of the earlier levels, any other level takes only what the table already holds there, and where a level has
    nothing the columns from there on are BLANK (the first build gave every showAll column its whole domain);
  - the loaded cells are text: the table's rows are typed before they are compared with the model's values;
  - a showAll column named twice among the groupBy columns is an error, a repeated plain groupBy column is not;
  - the join uses data lineage: SELECTCOLUMNS (and DATATABLE, ROW ...) hands it none;
  - the row order TOCSV / TOJSON print is the order of the table argument with the added rows after it, so only a table whose own
    order is modelled is accepted (SUMMARIZECOLUMNS, TOPN, a filtered numeric SUMMARIZE and a several-column ALL are not).
Open (logged in HANDOFF.md): a column that does not exist is never validated when an iterator walks an empty table, and unordered
iteration over SUMMARIZE with a computed column under a filter (both older than this task) differ from Power BI in a few shapes.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio.measures import MeasureError, evaluate_measures
from tools import dax_oracle_diff as dax
from tools.dax_oracle_diff import HEADERS, LOCAL_ROWS
from tools.parity_check import status

PARITY = Path(__file__).resolve().parents[1] / "tools" / "parity"

R, N, Q = "Facts[Region]", "Facts[Note]", "Facts[Quantity]"

# Valid DAX (Power BI answers) that the local engine refuses on purpose.
STAYS_REFUSED = [
    # the group order of SUMMARIZE over a numeric column under a filter is not modelled
    f'TOCSV(CALCULATETABLE(SUMMARIZE(Facts,{Q},"s",SUM({Q})),{R}<>"West"))',
    # a SELECTCOLUMNS column named "Facts[Region]" keeps the join in Power BI
    f'COUNTROWS(ADDMISSINGITEMS({R},SELECTCOLUMNS(VALUES({R}),"Facts[Region]",{R}),{R}))',
]

# Power BI answers an error; the local engine must not produce a value.
ERRORS = [
    f"COUNTROWS(ADDMISSINGITEMS({R},SUMMARIZE(Facts,{R}),{R},{R}))",  # a showAll column twice among the groupBy columns
    f"COUNTROWS(ADDMISSINGITEMS({R},SUMMARIZE(Facts,{R}),{R},{N},{R}))",
    f'COUNTROWS(ADDMISSINGITEMS({R},SELECTCOLUMNS(Facts,"Region",{R}),{R}))',  # SELECTCOLUMNS has no lineage to join on
    f'COUNTROWS(ADDMISSINGITEMS({R},DATATABLE("Region",STRING,{{{{"East"}}}}),{R}))',
    f"COUNTROWS(ADDMISSINGITEMS({R},ROW(\"Region\",1),{R}))",
    f"COUNTROWS(ADDMISSINGITEMS({R},SUMMARIZE(Facts,{R}),{R},FILTER(Facts,{Q}>3),{N}))",  # a column after a filter table
    f"COUNTROWS(ADDMISSINGITEMS(Facts,Facts,{R}))",
    f"COUNTROWS(DISTINCT(ADDMISSINGITEMS({R},VALUES({R}),{R})))",  # DISTINCT directly over it
    f"COUNTROWS(DISTINCT(SUMMARIZE(ADDMISSINGITEMS({R},VALUES({R}),{R}),{R})))",
    f"COUNTROWS(ADDMISSINGITEMS({R}))",
    "COUNTROWS(ADDMISSINGITEMS())",
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


def _csv(expression: str) -> str:
    return dax.local(f'CONCATENATEX({expression},{R}&"/"&{N}&"/"&[s],"|",{R},ASC,{N},ASC)')


class AddMissingItemsReviewTest(unittest.TestCase):
    def test_review_batteries_never_differ_from_power_bi(self) -> None:
        matched, bad = _replay("dax_battery_ami_extra")
        self.assertEqual([], bad)
        self.assertGreaterEqual(matched, 4000)
        matched2, bad2 = _replay("dax_battery_ami_extra2")
        self.assertEqual([], bad2)
        self.assertGreaterEqual(matched2, 3500)

    def test_levels_follow_the_group_by_order(self) -> None:
        """Facts rows (Region, Note, Quantity): East/Paid/2, West/-/3, East/Paid/1, North/Late/4, West/Paid/0, East/-/5.
        The table is the East rows; every expected text is what Power BI printed."""
        east = f'CALCULATETABLE(SUMMARIZE(Facts,{R},{N},{Q},"s",SUM({Q})),{R}="East")'
        table = f'CALCULATETABLE(SUMMARIZE(Facts,{R},{N},"s",SUM({Q})),{R}="East")'
        cases = [
            (f"ADDMISSINGITEMS({R},{east},{R},{N},{Q})", "East//5/5|East/Paid/1/1|East/Paid/2/2|North///|West///"),
            (f"ADDMISSINGITEMS({R},{east},{N},{R},{Q})", "East//5/5|East/Paid/1/1|East/Paid/2/2|West///|West/Paid//"),
            (f"ADDMISSINGITEMS({R},{east},{N},{Q},{R})", "East//5/5|East/Paid/1/1|East/Paid/2/2"),
            (f"ADDMISSINGITEMS({Q},{east},{N},{Q},{R})", "//3/|/Paid/0/|East//5/5|East/Paid/1/1|East/Paid/2/2"),
            (f"ADDMISSINGITEMS({R},{Q},{east},{R},{Q},{N})", "East//5/5|East/Paid/1/1|East/Paid/2/2|North//4/|West//0/|West//3/"),
            (f"ADDMISSINGITEMS({R},{Q},{east},{R},{N},{Q})", "East//5/5|East/Paid/1/1|East/Paid/2/2|North///|West///"),
        ]
        for expression, want in cases:
            got = dax.local(f'CONCATENATEX({expression},{R}&"/"&{N}&"/"&{Q}&"/"&[s],"|",{R},ASC,{N},ASC,{Q},ASC)')
            self.assertEqual(want, got, expression)
        two = [
            (f"ADDMISSINGITEMS({R},{table},{R},{N})", "East//5|East/Paid/3|North//|West//"),
            (f"ADDMISSINGITEMS({N},{table},{R},{N})", "East//5|East/Paid/3"),
            (f"ADDMISSINGITEMS({N},{table},{N},{R})", "/Late/|East//5|East/Paid/3"),
            (f"ADDMISSINGITEMS({R},{table},{N},{R})", "East//5|East/Paid/3|West//|West/Paid/"),
        ]
        for expression, want in two:
            self.assertEqual(want, _csv(expression), expression)

    def test_added_rows_follow_the_table_in_print_order(self) -> None:
        self.assertEqual(
            "'Facts'[Region],'Facts'[Note],[s]\nEast,,5\nWest,,3\nEast,Paid,3\nWest,Paid,0\nNorth,Late,4",
            dax.local(f'TOCSV(ADDMISSINGITEMS({R},SUMMARIZE(Facts,{R},{N},"s",SUM({Q})),{R},{N}))'),
        )
        # nothing is added to the rows of the table, the missing ones follow it in the model's grouped order
        self.assertEqual(
            "'Facts'[Quantity],[s]\n5,5\n0,\n1,\n2,\n3,\n4,",
            dax.local(f'TOCSV(ADDMISSINGITEMS({Q},FILTER(SUMMARIZE(Facts,{Q},"s",SUM({Q})),[s]>4),{Q}))'),
        )

    def test_numeric_cells_of_a_loaded_table_are_compared_as_numbers(self) -> None:
        self.assertEqual("6", dax.local(f"COUNTROWS(ADDMISSINGITEMS({Q},FILTER(VALUES({Q}),{Q}>1),{Q}))"))
        self.assertEqual("6", dax.local(f"COUNTROWS(ADDMISSINGITEMS(Facts[Sales],FILTER(Facts,{Q}>2),Facts[Sales]))"))

    def test_distinct_of_added_rows_only_errors_when_it_reads_them_directly(self) -> None:
        added = f"ADDMISSINGITEMS({R},VALUES({R}),{R})"
        for wrapped in (f"FILTER({added},TRUE())", f'ADDCOLUMNS({added},"k",1)', f"TOPN(5,{added},{R})", f"UNION({added},{added})"):
            self.assertEqual("3", dax.local(f"COUNTROWS(DISTINCT({wrapped}))"), wrapped)

    def test_a_single_table_argument_is_the_table(self) -> None:
        self.assertEqual("3", dax.local(f"COUNTROWS(ADDMISSINGITEMS(SUMMARIZE(Facts,{R})))"))

    def test_errors_stay_errors(self) -> None:
        for expression in ERRORS:
            outcome = dax.local(expression)
            self.assertTrue(outcome.startswith(("LOCAL-REJECT", "ERR:")), f"{expression} -> {outcome}")

    def test_several_column_all_matches_power_bi(self) -> None:
        # live Power BI (Task 123 review, 2026-11-10): a several-column ALL keeps the storage order of its combinations,
        # and ADDMISSINGITEMS over it adds no rows
        expected = "'Facts'[Region],'Facts'[Note]\nEast,\nWest,\nEast,Paid\nWest,Paid\nNorth,Late"
        for expression in (f"TOCSV(ADDMISSINGITEMS({R},ALL({R},{N}),{R},{N}))", f"TOCSV(ALL({R},{N}))"):
            self.assertEqual(dax.local(expression), expected, expression)

    def test_valid_dax_stays_refused(self) -> None:
        for expression in STAYS_REFUSED:
            outcome = dax.local(expression)
            self.assertTrue(outcome.startswith("LOCAL-REJECT"), f"{expression} -> {outcome}")

    def test_addmissingitems_calculatetable_summarize_matches_power_bi(self) -> None:
        # Power BI Desktop confirmed this answer on 2026-11-11 (Task 138).
        expression = f'TOCSV(ADDMISSINGITEMS({Q},CALCULATETABLE(SUMMARIZE(Facts,{Q},"s",SUM({Q})),{R}<>"West"),{Q}))'
        powerbi = "'Facts'[Quantity],[s]\n1,1\n2,2\n5,5\n4,4\n0,\n3,"
        actual = dax.local(expression)
        self.assertEqual(powerbi, actual, expression)
        self.assertTrue(dax.same(powerbi, actual), expression)

    def test_addmissingitems_summarizecolumns_and_topn_match_power_bi(self) -> None:
        # Power BI confirmed (Task 139, 2026-11-11): the first answer is live-probed, the second is in dax_battery_ami_extra.json
        cases = [
            (f'TOCSV(ADDMISSINGITEMS({R},SUMMARIZECOLUMNS({R},FILTER(ALL(Facts),{Q}>2),"s",SUM({Q})),{R}))',
             "'Facts'[Region],[s]\nEast,5\nWest,3\nNorth,4"),
            (f"TOCSV(ADDMISSINGITEMS({R},TOPN(2,VALUES({R}),{R},DESC),{R}))", "'Facts'[Region]\nNorth\nWest\nEast"),
        ]
        for expression, powerbi in cases:
            with self.subTest(expression=expression):
                self.assertEqual(powerbi, dax.local(expression), expression)

    def test_columns_of_two_tables_are_refused(self) -> None:
        tables = [
            {"id": "facts", "name": "Facts", "headers": HEADERS, "rows": LOCAL_ROWS,
             "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"}},
            {"id": "other", "name": "Other", "headers": ["A"], "rows": [{"A": v} for v in ("x", "y")], "column_types": {"A": "text"}},
        ]
        with self.assertRaises(MeasureError):
            evaluate_measures(
                [{"name": "P__", "expression": f"COUNTROWS(ADDMISSINGITEMS({R},CROSSJOIN(VALUES({R}),VALUES(Other[A])),{R},Other[A]))"}],
                LOCAL_ROWS, HEADERS, "Facts", measure_names=["P__"], table_context=tables, active_table_id="facts",
            )


if __name__ == "__main__":
    unittest.main()
