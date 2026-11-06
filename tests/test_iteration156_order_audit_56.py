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
    'CALCULATE(TOCSV(ALLSELECTED(Facts),2),Facts[Quantity]>=2)',  # the cut-off of a reversed walk
    'CALCULATE(TOCSV(ALLSELECTED(Facts),-1),Facts[Quantity]>=2)',
    'CALCULATE(TOCSV(ALLSELECTED(Facts)),Facts[Quantity]>=0)',  # a filter that keeps every row
    'CALCULATE(CONCATENATEX(UNION(FILTER(Facts,Facts[Quantity]<3),FILTER(Facts,Facts[Quantity]>3)),Facts[Region],","),Facts[Quantity]<>3)',  # arms a filter reaches
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
