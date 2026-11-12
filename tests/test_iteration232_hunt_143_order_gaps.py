"""Task 143 review of follow-up 3: the order of a TOPNSKIP over VALUES(column) / ALL(column) is not derivable, so every consumer
that shows or depends on that order refuses, however the TOPNSKIP is reached (VAR, FILTER, ADDCOLUMNS, ...)."""
import unittest

from tools import dax_oracle_diff as dax

TS = "TOPNSKIP(2,0,VALUES(Facts[Region]),Facts[Region])"


class SingleColumnTopnskipOrderGaps(unittest.TestCase):
    def _rejects(self, expr):
        self.assertTrue(dax.local(expr).startswith("LOCAL-REJECT"), expr)

    def _answers(self, expr, expected):
        self.assertEqual(dax.local(expr), expected, expr)

    def test_unordered_concatenatex_refuses_through_wrappers(self):
        for expr in (
            f'VAR t={TS} RETURN CONCATENATEX(t,Facts[Region],"|")',
            f'CONCATENATEX(FILTER({TS},TRUE()),Facts[Region],"|")',
            f'CONCATENATEX(ADDCOLUMNS({TS},"x",1),Facts[Region],"|")',
            f'CONCATENATEX(SELECTCOLUMNS({TS},"x",Facts[Region]),[x],"|")',
            f'CONCATENATEX(DISTINCT({TS}),Facts[Region],"|")',
            f'CONCATENATEX(UNION({TS},TOPNSKIP(1,0,VALUES(Facts[Region]),Facts[Region])),Facts[Region],"|")',
            f'CONCATENATEX(GENERATE({TS},ROW("a",1)),Facts[Region],"|")',
            f'CONCATENATEX(CALCULATETABLE(VALUES(Facts[Region]),{TS}),Facts[Region],"|")',
        ):
            self._rejects(expr)

    def test_order_by_that_ties_refuses(self):
        self._rejects('CONCATENATEX(TOPNSKIP(3,0,VALUES(Facts[Region]),Facts[Region]),Facts[Region],"|",LEN(Facts[Region]),ASC)')
        self._rejects('CONCATENATEX(TOPNSKIP(3,0,VALUES(Facts[Region]),Facts[Region]),Facts[Region],"|",1,ASC)')

    def test_order_by_that_breaks_every_tie_answers(self):
        self._answers(f'CONCATENATEX({TS},Facts[Region],"|",Facts[Region],ASC)', "North|West")
        self._answers(f'CONCATENATEX({TS},Facts[Region],"|",Facts[Region],DESC)', "West|North")

    def test_row_picking_consumers_refuse(self):
        for expr in (
            f'CONCATENATEX(TOPN(1,{TS},LEN(Facts[Region])),Facts[Region],"|")',
            f'CONCATENATEX(SAMPLE(1,{TS},Facts[Region]),Facts[Region],"|")',
            f'MAXX(INDEX(1,{TS}),Facts[Region])',
            f'VAR t={TS} RETURN CONCATENATEX(TOPN(1,t,Facts[Region]),Facts[Region],"|")',
        ):
            self._rejects(expr)

    def test_unmeasured_count_and_skip_refuse(self):
        for count, skip in (("0", "0"), ("-1", "0"), ("BLANK()", "0"), ("1.5", "0"), ("2", "BLANK()"), ("2", "-1"), ('2', '"a"'), ("0", "1")):
            self._rejects(f'COUNTROWS(TOPNSKIP({count},{skip},VALUES(Facts[Region]),Facts[Region]))')

    def test_order_free_shapes_keep_answering(self):
        self._answers(f'CONCATENATEX({TS},"x","|")', "x|x")
        self._answers(f'COUNTROWS({TS})', "2")
        self._answers('CONCATENATEX(TOPNSKIP(1,0,VALUES(Facts[Region]),Facts[Region]),Facts[Region],"|")', "West")
        self._answers('COUNTROWS(TOPNSKIP(2,1,Facts,Facts[Sales]))', "2")
        self._answers('CONCATENATEX(TOPNSKIP(2,0,Facts,Facts[Sales],ASC),Facts[Quantity],"|")', "4|1")
        self._answers('CONCATENATEX(TOPNSKIP(2,0,ALL(Facts),Facts[Sales],ASC),Facts[Quantity],"|")', "4|1")
        self._answers('CONCATENATEX(TOPNSKIP(2,0,FILTER(Facts,Facts[Quantity]>1),Facts[Sales],ASC),Facts[Quantity],"|")', "4|5")
        self._answers('MAXX(SUBSTITUTEWITHINDEX(TOPNSKIP(2,0,VALUES(Facts[Region]),Facts[Region]),"i",TOPNSKIP(2,0,VALUES(Facts[Region]),Facts[Region]),Facts[Region]),[i])', "1")


if __name__ == "__main__":
    unittest.main()
