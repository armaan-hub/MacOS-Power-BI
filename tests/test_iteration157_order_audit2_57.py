"""Iteration 157: Task 67 order-audit2-57 (row orders of ALLEXCEPT, GROUPBY, SUMMARIZECOLUMNS and ADDCOLUMNS over RANKX).

Power BI answers below are recorded values of tools/parity/task67_order_audit2_spec.json (38 shapes that main answered wrong),
plus two measured matches of the 1,500-shape grid (one D row and the text-column guard):
  A. ALLEXCEPT(table, numeric column): the kept columns walk in dictionary order (later table column is the major key).
     ALLEXCEPT over a text column keeps the storage order (guard row, measured on main).
  B. GROUPBY(table, group column, ...): the groups come out in the dictionary order of the group column.
  C. SUMMARIZECOLUMNS of plain columns: the combinations walk in dictionary order of their columns.
  D. ADDCOLUMNS(table, "r", RANKX(ALL(table), expression)): the expression's columns join the walk.
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
)


class Iteration157OrderAudit2Test(unittest.TestCase):
    def test_power_bi_answers_match(self) -> None:
        for part, expression, powerbi in ROWS:
            with self.subTest(part=part, expression=expression):
                self.assertEqual(status(powerbi, dax.local(expression)), "match")


if __name__ == "__main__":
    unittest.main()
