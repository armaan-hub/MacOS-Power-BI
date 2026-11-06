"""Iteration 157: Task 67 order-audit2-57 (row orders of ALLEXCEPT, GROUPBY, SUMMARIZECOLUMNS and ADDCOLUMNS over RANKX).

Power BI answers below are recorded values of tools/parity/task67_order_audit2_spec.json (38 shapes that main answered wrong),
plus two measured matches of the 1,500-shape grid (one D row and the text-column guard):
  A. ALLEXCEPT(table, columns): the columns it lists walk in dictionary order (later table column is the major key, text first-seen with
     BLANK first, numbers sorted) while the product of their distinct counts is at most 54; at 108 (Facts, Sales x Quantity x Region or Note)
     Power BI keeps the storage order, which is what the engine does above the measured size.
  B. GROUPBY(table, group column, ...): the groups come out in the dictionary order of the group column.
  C. SUMMARIZECOLUMNS of plain columns: the combinations walk in dictionary order of their columns.
  C2. The same with measure columns ("s", SUM(...)) after the group columns.
  D. ADDCOLUMNS(table, "r", RANKX(ALL(table), expression)): the expression's columns join the walk.
  E. SUMMARIZE(table, column, "s", measure) under an outer filter on another column: the groups come in the order of their first combination
     of (group columns + filtered columns) in dictionary order (held-out grid t67c, 7 of 7 shapes).
"""
import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status

# (part, expression, Power BI answer)
ROWS = (
    ('A', 'TOCSV(ALLEXCEPT(Facts,Facts[Quantity]),100)',
     "'Facts'[Sales],'Facts'[Region],'Facts'[Note]\n2.5,East,\n20,West,\n-1.5,East,Paid\n10.5,East,Paid\n0,West,Paid\n,North,Late"),
    ('A', 'CALCULATE(CONCATENATEX(ALLEXCEPT(Facts,Facts[Quantity]),Facts[Sales],","),Facts[Quantity]<>3)',
     '2.5,20,-1.5,10.5,0,'),
    ('A', 'CONCATENATEX(ALLEXCEPT(Facts,Facts[Quantity]),Facts[Region],",")',
     'East,West,East,East,West,North'),
    ('A', 'CONCATENATEX(TOPN(4,ALLEXCEPT(Facts,Facts[Sales]),Facts[Quantity]),Facts[Quantity],",")',
     '2,4,3,5'),
    ('B', 'CONCATENATEX(GROUPBY(Facts,Facts[Quantity],"m",MAXX(CURRENTGROUP(),Facts[Sales])),Facts[Quantity],",")',
     '0,1,2,3,4,5'),
    ('B', 'CALCULATE(CONCATENATEX(GROUPBY(Facts,Facts[Note],"m",MAXX(CURRENTGROUP(),Facts[Sales])),Facts[Note],","),Facts[Note]<>"Late")',
     ',Paid'),
    ('C', 'CALCULATE(CONCATENATEX(SUMMARIZECOLUMNS(Facts[Sales],Facts[Quantity]),Facts[Sales],","),Facts[Note]<>"Late")',
     '0,-1.5,10.5,20,2.5'),
    ('C', 'CONCATENATEX(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity]),Facts[Quantity],",")',
     '1,2,5,0,3,4'),
    ('D', 'CONCATENATEX(ADDCOLUMNS(Facts,"r",RANKX(ALL(Facts),Facts[Sales])),Facts[Sales],",")',
     ',-1.5,0,2.5,10.5,20'),
    ('D', 'CALCULATE(CONCATENATEX(ADDCOLUMNS(Facts,"r",RANKX(ALL(Facts),Facts[Sales])),Facts[Region],","),Facts[Quantity]>=2)',
     'East,West,North,East'),
    ('A', 'CONCATENATEX(ALLEXCEPT(Facts,Facts[Region]),Facts[Sales],",")',
     '10.5,20,-1.5,,0,2.5'),
    ('A', 'TOCSV(ALLEXCEPT(Facts,Facts[Note]),100)',
     "'Facts'[Sales],'Facts'[Quantity],'Facts'[Region]\n10.5,2,East\n20,3,West\n-1.5,1,East\n,4,North\n0,0,West\n2.5,5,East"),
    ('A', 'CALCULATE(TOCSV(ALLEXCEPT(Facts,Facts[Note],Facts[Quantity]),100),Facts[Sales]>0)',
     "'Facts'[Sales],'Facts'[Region]\n-1.5,East\n2.5,East\n10.5,East\n0,West\n20,West\n,North"),
    ('A', 'CALCULATE(CONCATENATEX(ALLEXCEPT(Facts,Facts[Note],Facts[Sales]),Facts[Quantity],","),Facts[Region]<>"East")',
     '1,2,5,0,3,4'),
    ('A', 'CONCATENATEX(ALLEXCEPT(Facts,Facts[Region],Facts[Note]),Facts[Quantity],",")', '0,1,2,3,4,5'),
    ('A', 'TOCSV(ALLEXCEPT(Facts,Facts[Quantity],Facts[Region]),100)',
     "'Facts'[Sales],'Facts'[Note]\n2.5,\n20,\n-1.5,Paid\n0,Paid\n10.5,Paid\n,Late"),
    ('A', 'CONCATENATEX(ALLEXCEPT(Facts,Facts[Region],Facts[Sales]),Facts[Quantity],",")', '3,5,0,1,2,4'),
    ('C2', 'CONCATENATEX(SUMMARIZECOLUMNS(Facts[Note],Facts[Quantity],"s",SUM(Facts[Quantity])),Facts[Quantity],",")', '3,5,0,1,2,4'),
    ('C2', 'CONCATENATEX(SUMMARIZECOLUMNS(Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),Facts[Note],",")', ',,Paid,Paid,Late'),
    ('C2', 'CALCULATE(CONCATENATEX(SUMMARIZECOLUMNS(Facts[Region],Facts[Sales],"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Region]<>"East")', '0,20,'),
    ('C2', 'CALCULATE(CONCATENATEX(SUMMARIZECOLUMNS(Facts[Quantity],Facts[Note],"s",SUM(Facts[Quantity])),Facts[Note],","),Facts[Quantity]>1)', ',,Paid,Late'),
    ('C2', 'CALCULATE(CONCATENATEX(TOPN(4,SUMMARIZECOLUMNS(Facts[Quantity],Facts[Region],"s",SUM(Facts[Quantity])),Facts[Quantity]),Facts[Quantity],","),Facts[Quantity]>=2)', '2,5,3,4'),
    ('E', 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Region]<>"East")', '0,20,'),
    ('E', 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Note]<>"Late")', '2.5,20,-1.5,0,10.5'),
    ('E', 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Quantity]<>3)', '0,-1.5,10.5,,2.5'),
)


class Iteration157OrderAudit2Test(unittest.TestCase):
    def test_power_bi_answers_match(self) -> None:
        for part, expression, powerbi in ROWS:
            with self.subTest(part=part, expression=expression):
                self.assertEqual(status(powerbi, dax.local(expression)), "match")


if __name__ == "__main__":
    unittest.main()
