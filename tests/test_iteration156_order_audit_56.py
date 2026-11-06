"""Iteration 156: Task 66 order-audit-56 (row orders of UNION, GENERATE and ALLSELECTED found wrong by a fresh audit grid).

Power BI answers below are the recorded values of tools/parity/task66_order_audit_spec.json (83 shapes that main answered wrong):
  1. CONCATENATEX over UNION: each table of the union is walked on its own in the dictionary order of the columns read, one after the other.
  2. GENERATE(VALUES(a), VALUES(b)) (CONCATENATEX, TOCSV, TOJSON): the right list is the major key, the left one varies fastest.
  3. TOCSV / TOJSON of ALLSELECTED(table) under an outer filter that cuts rows: reverse storage order.
Shapes that were not measured stay refused.
"""
import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

SPEC = Path(__file__).resolve().parents[1] / "tools" / "parity" / "task66_order_audit_spec.json"

UNION = 'UNION(FILTER(ALL(Facts),Facts[Quantity]<3),FILTER(ALL(Facts),Facts[Quantity]>3))'
GEN = "GENERATE(VALUES(Facts[Region]),VALUES(Facts[Note]))"

MEASURED = (
    (f'CONCATENATEX({UNION},Facts[Quantity],",")', "0,1,2,4,5"),
    (f'CONCATENATEX({UNION},Facts[Sales],",")', "-1.5,0,10.5,,2.5"),
    (f'CALCULATE(CONCATENATEX({UNION},Facts[Region],","),Facts[Note]="Paid")', "East,East,West,East,North"),
    (f'CALCULATE(CONCATENATEX({UNION},Facts[Note],","),Facts[Quantity]<>3)', "Paid,Paid,Paid,,Late"),
    # second grid (1500 probes): lists of ALL / DISTINCT / FILTER(VALUES), numeric columns, three-arm unions, TOPN arms, FILTER(ALLSELECTED)
    ('CALCULATE(CONCATENATEX(GENERATE(ALL(Facts[Quantity]),ALL(Facts[Region])),Facts[Region],","),Facts[Quantity]<>3)', "East,East,East,East,East,East,West,West,West,West,West,West,North,North,North,North,North,North"),
    ('CALCULATE(CONCATENATEX(GENERATE(DISTINCT(Facts[Note]),VALUES(Facts[Sales])),Facts[Sales],"|"),Facts[Quantity]>=2,Facts[Quantity]<>3)', "|||2.5|2.5|2.5|10.5|10.5|10.5"),
    ('CONCATENATEX(UNION(ALL(Facts),TOPN(2,ALL(Facts),Facts[Sales])),Facts[Region],",")', "East,East,East,West,West,North,East,West"),
    ('CALCULATE(CONCATENATEX(UNION(Facts,TOPN(2,ALL(Facts),Facts[Sales])),Facts[Sales],","),Facts[Quantity]<>3)', ",-1.5,0,2.5,10.5,10.5,20"),
    ('CALCULATE(CONCATENATEX(UNION(FILTER(ALL(Facts),Facts[Quantity]>2),TOPN(2,ALL(Facts),Facts[Sales]),Facts),Facts[Quantity],","),Facts[Sales]>0)', "3,4,5,2,3,2,3,5"),
    (
        "TOCSV(FILTER(ALLSELECTED(Facts),Facts[Quantity]>1))",
        "'Facts'[Sales],'Facts'[Quantity],'Facts'[Region],'Facts'[Note]\n2.5,5,East,\n,4,North,Late\n20,3,West,\n10.5,2,East,Paid",
    ),
    (
        'CALCULATE(TOCSV(FILTER(ALLSELECTED(Facts),Facts[Quantity]>1),3),Facts[Quantity]<>3)',
        "'Facts'[Sales],'Facts'[Quantity],'Facts'[Region],'Facts'[Note]\n2.5,5,East,\n,4,North,Late\n10.5,2,East,Paid",
    ),
    ('CALCULATE(TOCSV(ALLSELECTED(Facts),1),Facts[Quantity]>1)', None),
    (f'CONCATENATEX({GEN},Facts[Region],",")', "East,West,North,East,West,North,East,West,North"),
    (f'CALCULATE(CONCATENATEX({GEN},Facts[Region],","),Facts[Region]<>"East")', "West,North,West,North,West,North"),
    (f'CALCULATE(CONCATENATEX({GEN},Facts[Note],","),Facts[Region]<>"East")', ",,Paid,Paid,Late,Late"),
    (f"TOCSV({GEN})", "'Facts'[Region],'Facts'[Note]\nEast,\nWest,\nNorth,\nEast,Paid\nWest,Paid\nNorth,Paid\nEast,Late\nWest,Late\nNorth,Late"),
    (
        'CALCULATE(TOCSV(ALLSELECTED(Facts)),Facts[Region]="West")',
        "'Facts'[Sales],'Facts'[Quantity],'Facts'[Region],'Facts'[Note]\n0,0,West,Paid\n20,3,West,",
    ),
    (
        'CALCULATE(TOCSV(ALLSELECTED(Facts)),Facts[Note]="Paid")',
        "'Facts'[Sales],'Facts'[Quantity],'Facts'[Region],'Facts'[Note]\n0,0,West,Paid\n-1.5,1,East,Paid\n10.5,2,East,Paid",
    ),
)

# not measured: refused (a rejection is allowed, a wrong answer is not)
REFUSED = (
    'CALCULATE(TOCSV(ALLSELECTED(Facts),-1),Facts[Quantity]>=2)',  # every row asked for under a reversed walk
    'CALCULATE(TOCSV(ALLSELECTED(Facts)),Facts[Quantity]>=0)',  # a filter that keeps every row
    'CALCULATE(CONCATENATEX(GENERATE(VALUES(Facts[Region]),FILTER(VALUES(Facts[Note]),Facts[Region]="East")),Facts[Note],","),Facts[Quantity]<>3)',  # a right list that reads the left row
)


class SpecRows(unittest.TestCase):
    def test_every_recorded_row_matches(self):
        items = json.loads(SPEC.read_text())["items"]
        self.assertEqual(len(items), 83)
        wrong = [item["expr"] for item in items if status(item["powerbi"], dax.local(item["expr"])) not in ("match", "gap-reject")]
        self.assertEqual(wrong, [])


class MeasuredShapes(unittest.TestCase):
    def test_measured_answers(self):
        for expression, expected in MEASURED:
            with self.subTest(expression=expression):
                if expected is None:  # answered with the first row of the storage order (7 grid shapes matched main)
                    self.assertTrue(dax.local(expression).startswith("'Facts'[Sales],'Facts'[Quantity],'Facts'[Region],'Facts'[Note]\n10.5,2,East,Paid"))
                else:
                    self.assertEqual(dax.local(expression), expected)

    def test_refused_shapes_are_not_answered(self):
        for expression in REFUSED:
            with self.subTest(expression=expression):
                self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), dax.local(expression))

    def test_whole_allselected_keeps_storage_order(self):
        text = dax.local("TOCSV(ALLSELECTED(Facts))").split("\n")
        self.assertEqual(text[1], "10.5,2,East,Paid")
        self.assertEqual(text[-1], "2.5,5,East,")

    def test_generate_with_a_dependent_or_one_row_right_side_keeps_left_major(self):
        self.assertEqual(dax.local('CONCATENATEX(GENERATE(VALUES(Facts[Region]),ROW("z",1)),Facts[Region],",")'), "East,West,North")


if __name__ == "__main__":
    unittest.main()
