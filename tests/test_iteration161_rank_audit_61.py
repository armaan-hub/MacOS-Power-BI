"""Iteration 161: Task 71 RANK / ROWNUMBER / RANKX audit (rank-audit-61).

Covers (live Power BI evidence in tools/parity/task71_rank_audit_spec.json and the 1,500-shape audit grid t71a):
- Part A: ROWNUMBER over ALL(table) or ALLSELECTED(table) raises "Tied rows detected in the relation parameter" when two rows of the relation agree on
  the PARTITIONBY and ORDERBY keys (the rows filtered in by ALLSELECTED's outer context). The engine refuses that case (LOCAL-REJECT) with that message.
  A column-list relation or a relation whose ORDERBY keys identify every row is answered.
- Part B: RANK's blanks argument. FIRST puts every BLANK ahead of the other values of an ORDERBY column and LAST behind them, whatever the direction; KEEP and no
  argument keep the default position. ALLSELECTED's rows are the ones the outer filter leaves visible.
- Part C: CONCATENATEX over RANK / ROWNUMBER of a projection of one or two columns walks the rows by the projection's columns (and the ORDERBY columns) in the
  walk order of those columns (dictionary order inside the measured key space, source order beside a fractional column), and RANKX over FILTER(ALL(table), p)
  walks by its body and its explicit value argument. A fractional column beside columns that hold one value over the filtered rows comes out sorted: refused.
  ALLSELECTED's tie is judged on the rows ALLSELECTED returns inside the iterator (CONCATENATEX: the whole table, SUMX / MAXX / TOCSV: the filtered rows).
  A relation of several columns is walked in dictionary order inside a measured key space and in source order outside it (rank_walk_order); between: refused.
  ROWNUMBER is the only function with the tie error (54 errors in 260 ROWNUMBER answers; no RANK or column-list ROWNUMBER of 400 raised it).
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

    def test_part_a_allselected_tie_is_judged_on_the_rows_allselected_returns(self) -> None:
        tied = "Tied rows detected in the relation parameter for ROWNUMBER function."
        # CONCATENATEX clears the outer filter on its own columns, so ALLSELECTED(Facts) is the whole table: tied on Note although the visible rows are not (t71b)
        self.assertRefused('CALCULATE(CONCATENATEX(Facts,ROWNUMBER(ALLSELECTED(Facts),ORDERBY(Facts[Note],ASC)),","),Facts[Region]<>"East")', tied)
        self.assertRefused('CALCULATE(CONCATENATEX(Facts,ROWNUMBER(ALLSELECTED(Facts),ORDERBY(Facts[Note],DESC,Facts[Region],DESC)),","),Facts[Region]="West")', tied)
        # SUMX keeps the outer filter: the three visible rows are not tied on Note (t71a, Power BI answered 3)
        self.assertLocal('CALCULATE(SUMX(Facts,ROWNUMBER(ALLSELECTED(Facts),ORDERBY(Facts[Note],DESC))),Facts[Region]="West")', "3")

    def test_rank_walk_order_follows_the_measured_key_spaces(self) -> None:
        from decimal import Decimal
        profile = lambda values: dax_iteration_order.Profile([Decimal(v) if v is not None else None for v in values])
        small = [profile(["1", "2", "3"]), profile(["1", "2"])]
        self.assertTrue(dax_iteration_order.rank_walk_order(6, small))
        self.assertTrue(dax_iteration_order.rank_walk_order(9, [profile([str(n) for n in range(1, 22)]), profile(["1", "2", "3"])]))  # 63 over 9 rows (d2)
        self.assertFalse(dax_iteration_order.rank_walk_order(13, [profile([str(n) for n in range(1, 74)]), profile(["1", "2", "3", "4"])]))  # 292 over 13 rows (d16)
        self.assertIsNone(dax_iteration_order.rank_walk_order(6, [profile([str(n) for n in range(1, 51)]), profile(["1", "2"])]))  # 100 over 6 rows: between the measured points

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
        self.assertEqual(bodies, [("reference", "Facts", "Quantity"), ("reference", "Facts", "Quantity")])  # the relation's columns are read by the walk

    def test_part_c_two_column_projection_walks_by_its_columns(self) -> None:
        self.assertLocal('CONCATENATEX(Facts,ROWNUMBER(ALL(Facts[Quantity],Facts[Note]),ORDERBY(Facts[Note],DESC,Facts[Quantity],DESC)),",")', "6,5,3,2,1,4")
        self.assertLocal('CONCATENATEX(Facts,RANK(SKIP,ALL(Facts[Region],Facts[Note]),ORDERBY(Facts[Region],DESC)),",")', "4,1,4,4,1,3")
        self.assertLocal('CALCULATE(CONCATENATEX(Facts,RANK(DENSE,ALL(Facts[Region],Facts[Note]),ORDERBY(Facts[Note],ASC),FIRST),","),Facts[Quantity]<>3)', "1,3,3,3,2")

    def test_part_c_two_column_projection_beside_a_fractional_column_keeps_source_order(self) -> None:
        self.assertLocal('CONCATENATEX(Facts,ROWNUMBER(ALL(Facts[Sales],Facts[Region]),ORDERBY(Facts[Sales],ASC,Facts[Region],ASC)),",")', "5,6,1,2,3,4")

    def test_part_c_fractional_column_beside_a_constant_column_is_refused(self) -> None:
        result = str(dax.local('CALCULATE(CONCATENATEX(Facts,RANK(SKIP,ALL(Facts[Sales],Facts[Note]),ORDERBY(Facts[Note],ASC,Facts[Sales],DESC)),","),Facts[Note]="Paid")'))
        self.assertTrue(result.startswith("LOCAL-REJECT"), result)

    def test_part_a_rank_and_column_list_rownumber_are_never_tie_errors(self) -> None:
        self.assertFalse(str(dax.local('CONCATENATEX(Facts,RANK(DENSE,ALL(Facts),ORDERBY(Facts[Note],ASC)),",")')).startswith("LOCAL-REJECT"))
        self.assertFalse(str(dax.local('CONCATENATEX(Facts,ROWNUMBER(ALL(Facts[Region],Facts[Note]),ORDERBY(Facts[Region],ASC)),",")')).startswith("LOCAL-REJECT"))

    def test_walk_keys_leave_whole_table_relations_alone(self) -> None:
        nodes = [("call", "ROWNUMBER", (("call", "ALL", (("table", "Facts"),)), ("call", "ORDERBY", (("reference", "Facts", "Sales"), ("table", "ASC")))))]
        rebuilt, _bodies = dax_iteration_order.rankx_walk(nodes, "Facts")
        self.assertEqual(rebuilt, nodes)

    def test_order_expressions_drop_direction_tokens(self) -> None:
        arguments = (("reference", "Facts", "Note"), ("table", "ASC"), ("reference", "Facts", "Sales"), ("table", "DESC"))
        self.assertEqual(dax_iteration_order._order_expressions(arguments), (("reference", "Facts", "Note"), ("reference", "Facts", "Sales")))


if __name__ == "__main__":
    unittest.main()
