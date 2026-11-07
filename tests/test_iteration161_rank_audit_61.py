"""Iteration 161: Task 71 RANK / ROWNUMBER / RANKX audit (rank-audit-61).

Covers (live Power BI evidence in tools/parity/task71_rank_audit_spec.json and the 1,500-shape audit grid t71a):
- Part A: ROWNUMBER over ALL(table) or ALLSELECTED(table) raises "Tied rows detected in the relation parameter" when two rows of the relation agree on
  the PARTITIONBY and ORDERBY keys (the rows filtered in by ALLSELECTED's outer context). The engine refuses that case (LOCAL-REJECT) with that message.
  A column-list relation or a relation whose ORDERBY keys identify every row is answered.
- Part B: RANK's blanks argument. FIRST puts every BLANK ahead of the other values of an ORDERBY column and LAST behind them, whatever the direction; KEEP and no
  argument keep the default position. ALLSELECTED's rows are the ones the outer filter leaves visible.
- Part C: CONCATENATEX over RANK / ROWNUMBER of a one-column projection walks the rows in dictionary order of that column, and RANKX over FILTER(ALL(table), p)
  walks by its body and its explicit value argument. Several-column projections are not reproduced by a rule and keep their earlier answers.
"""
from __future__ import annotations

import unittest

from analytics_studio import dax_iteration_order
from tools import dax_oracle_diff as dax


class TestIteration161RankAudit61(unittest.TestCase):
    def assertLocal(self, expr: str, expected: str) -> None:
        with self.subTest(expr=expr):
            self.assertEqual(str(dax.local(expr)), expected)

    def assertRefused(self, expr: str, message: str) -> None:
        with self.subTest(expr=expr):
            result = str(dax.local(expr))
            self.assertTrue(result.startswith("LOCAL-REJECT"), result)
            self.assertIn(message, result)

    def test_part_a_rownumber_over_whole_table_with_tied_keys_is_refused(self) -> None:
        tied = "Tied rows detected in the relation parameter for ROWNUMBER function."
        self.assertRefused('CONCATENATEX(Facts,ROWNUMBER(ALL(Facts),ORDERBY(Facts[Note],ASC)),",")', tied)
        self.assertRefused('CALCULATE(CONCATENATEX(Facts,ROWNUMBER(ALL(Facts),ORDERBY(Facts[Note],ASC)),","),Facts[Quantity]<>3)', tied)
        self.assertRefused('CONCATENATEX(Facts,ROWNUMBER(ALLSELECTED(Facts),ORDERBY(Facts[Note],ASC)),",")', tied)
        self.assertRefused('MAXX(Facts,ROWNUMBER(ALL(Facts),ORDERBY(Facts[Note],ASC,Facts[Region],ASC)))', tied)

    def test_part_a_rownumber_is_answered_when_the_keys_identify_each_row(self) -> None:
        # Sales is unique in the table, so ORDERBY(Sales) identifies every row of ALL(Facts)
        self.assertLocal('CALCULATE(CONCATENATEX(Facts,ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales],ASC)),","),Facts[Region]="West")', "6,3")
        self.assertLocal('CALCULATE(CONCATENATEX(Facts,ROWNUMBER(ALL(Facts),ORDERBY(Facts[Sales],DESC)),","),Facts[Quantity]<>3)', "2,6,5,4,3")

    def test_part_a_allselected_visible_rows_decide_the_tie(self) -> None:
        self.assertRefused(
            'CALCULATE(CONCATENATEX(Facts,ROWNUMBER(ALLSELECTED(Facts),ORDERBY(Facts[Note],DESC)),","),Facts[Sales]>0)',
            "Tied rows detected in the relation parameter for ROWNUMBER function.",
        )

    def test_part_b_rank_blanks_first_puts_blank_ahead_in_either_direction(self) -> None:
        self.assertLocal('CALCULATE(CONCATENATEX(Facts,RANK(DENSE,ALL(Facts),ORDERBY(Facts[Note],DESC),FIRST),","),Facts[Note]="Paid")', "2,2,2")
        self.assertLocal('CONCATENATEX(Facts,RANK(DENSE,ALL(Facts),ORDERBY(Facts[Note],DESC),FIRST),",")', "2,1,2,3,2,1")
        self.assertLocal('CALCULATE(CONCATENATEX(Facts,RANK(DENSE,ALL(Facts),ORDERBY(Facts[Sales],DESC),FIRST),","),Facts[Region]="West")', "2,5")

    def test_part_b_rank_blanks_last_puts_blank_behind(self) -> None:
        self.assertLocal('CALCULATE(CONCATENATEX(Facts,RANK(DENSE,ALL(Facts[Quantity],Facts[Note]),ORDERBY(Facts[Note],ASC),LAST),","),Facts[Note]="Paid")', "2,2,2")
        self.assertLocal('CALCULATE(CONCATENATEX(Facts,RANK(DENSE,ALLSELECTED(Facts),ORDERBY(Facts[Note],ASC),LAST),","),Facts[Note]="Paid")', "2,2,2")

    def test_part_b_rank_allselected_ranks_the_visible_rows(self) -> None:
        self.assertLocal('CALCULATE(CONCATENATEX(Facts,RANK(DENSE,ALLSELECTED(Facts),ORDERBY(Facts[Note],DESC),FIRST),","),Facts[Sales]>0)', "2,1,1")

    def test_part_c_rank_over_one_column_projection_walks_by_the_orderby_column(self) -> None:
        self.assertLocal('CALCULATE(CONCATENATEX(Facts,ROWNUMBER(ALL(Facts[Quantity],Facts[Quantity]),ORDERBY(Facts[Quantity],DESC)),","),Facts[Region]<>"East")', "6,3,2")

    def test_part_c_rank_over_whole_table_keeps_source_order(self) -> None:
        self.assertLocal('CALCULATE(CONCATENATEX(Facts,RANK(DENSE,ALL(Facts),ORDERBY(Facts[Region],DESC,Facts[Note],DESC),FIRST),","),Facts[Region]="West")', "1,2")

    def test_part_c_rankx_over_filter_walks_by_body_and_value(self) -> None:
        self.assertLocal('CALCULATE(CONCATENATEX(Facts,RANKX(FILTER(ALL(Facts),Facts[Quantity]>1),Facts[Sales],Facts[Sales],ASC),","),Facts[Note]="Paid")', "1,1,3")

    def test_walk_keys_recognise_rank_and_rownumber_relations(self) -> None:
        nodes = [("call", "RANK", (("table", "DENSE"), ("call", "ALL", (("reference", "Facts", "Quantity"), ("reference", "Facts", "Quantity"))),
                                   ("call", "ORDERBY", (("reference", "Facts", "Quantity"), ("table", "DESC")))))]
        rebuilt, bodies = dax_iteration_order.rankx_walk(nodes, "Facts")
        self.assertEqual(rebuilt[0][2][0], ("call", "ORDERBY", (("reference", "Facts", "Quantity"),)))
        self.assertEqual(bodies, [])

    def test_walk_keys_leave_whole_table_relations_alone(self) -> None:
        nodes = [("call", "ROWNUMBER", (("call", "ALL", (("table", "Facts"),)), ("call", "ORDERBY", (("reference", "Facts", "Sales"), ("table", "ASC")))))]
        rebuilt, _bodies = dax_iteration_order.rankx_walk(nodes, "Facts")
        self.assertEqual(rebuilt, nodes)

    def test_order_expressions_drop_direction_tokens(self) -> None:
        arguments = (("reference", "Facts", "Note"), ("table", "ASC"), ("reference", "Facts", "Sales"), ("table", "DESC"))
        self.assertEqual(dax_iteration_order._order_expressions(arguments), (("reference", "Facts", "Note"), ("reference", "Facts", "Sales")))


if __name__ == "__main__":
    unittest.main()
