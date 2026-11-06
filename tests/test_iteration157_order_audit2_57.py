"""Iteration 157: Task 67 order-audit2-57 (row orders of ALLEXCEPT, GROUPBY, SUMMARIZECOLUMNS and ADDCOLUMNS over RANKX).

Power BI answers below are recorded values of tools/parity/task67_order_audit2_spec.json (38 shapes that main answered wrong),
plus two measured matches of the 1,500-shape grid (one D row and the text-column guard):
  A. ALLEXCEPT(table, columns): the columns it lists walk in dictionary order (later table column is the major key, text first-seen with
     BLANK first, numbers sorted) while the dense key space (product of the value-range sizes) is at most 567 (and space x (rows + 3) at most
     6,804); at 792 (standard Facts, Sales x Quantity x Region or Note) Power BI keeps the storage order; in between the engine refuses.
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


# ALLEXCEPT on two other row sets (Power BI answers of the d2 / d3 probes): sorted at a space of 567 (9 rows) and 216 (8 rows)
DATASET_3 = [("4", "1", "West", ""), ("2", "6", "North", "Paid"), ("9", "4", "East", "Late"), ("", "2", "West", "Paid"),
             ("7", "8", "North", "Late"), ("1", "3", "East", ""), ("6", "5", "West", "Late"), ("3", "7", "North", "Paid")]
DATASET_2 = [("5", "7", "North", "Late"), ("", "2", "East", ""), ("5", "3", "West", "Paid"), ("-2", "7", "East", "Paid"), ("8", "1", "North", ""),
             ("1.5", "2", "West", "Late"), ("8", "9", "East", "Paid"), ("0", "3", "North", "Paid"), ("3", "5", "West", "")]
OTHER_ROWS = (
    (DATASET_3, 'TOCSV(ALLEXCEPT(Facts,Facts[Quantity]),100)',
     "'Facts'[Sales],'Facts'[Region],'Facts'[Note]\n4,West,\n1,East,\n,West,Paid\n2,North,Paid\n3,North,Paid\n6,West,Late\n7,North,Late\n9,East,Late"),
    (DATASET_3, 'TOCSV(ALLEXCEPT(Facts,Facts[Note]),100)',
     "'Facts'[Sales],'Facts'[Quantity],'Facts'[Region]\n4,1,West\n,2,West\n6,5,West\n2,6,North\n3,7,North\n7,8,North\n1,3,East\n9,4,East"),
    (DATASET_3, 'TOCSV(ALLEXCEPT(Facts,Facts[Note],Facts[Region]),100)',
     "'Facts'[Sales],'Facts'[Quantity]\n4,1\n,2\n1,3\n9,4\n6,5\n2,6\n3,7\n7,8"),
    (DATASET_2, 'TOCSV(ALLEXCEPT(Facts,Facts[Note]),100)',
     "'Facts'[Sales],'Facts'[Quantity],'Facts'[Region]\n8,1,North\n0,3,North\n5,7,North\n,2,East\n-2,7,East\n8,9,East\n1.5,2,West\n5,3,West\n3,5,West"),
)


class Iteration157OtherRowsTest(unittest.TestCase):
    def test_allexcept_on_other_row_sets(self) -> None:
        for rows, expression, powerbi in OTHER_ROWS:
            with self.subTest(expression=expression, rows=len(rows)):
                saved = (dax.ROWS, dax.LOCAL_ROWS)
                dax.ROWS = rows
                dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in rows]
                try:
                    self.assertEqual(status(powerbi, dax.local(expression)), "match")
                finally:
                    dax.ROWS, dax.LOCAL_ROWS = saved


if __name__ == "__main__":
    unittest.main()
