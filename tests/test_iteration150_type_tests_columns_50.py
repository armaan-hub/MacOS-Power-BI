"""Iteration 150: Task 60 type-tests-columns-50.

A type test of one + - * / whose operands include a Facts column aggregate (MAX / SUM / AVERAGE, or CURRENCY of one) is answered
only for the leaf classes measured on Power BI (>= 5 rows each, all agreeing, no error), and the answer is the static type of the
arithmetic (Double). Every other column-read operand keeps refusing. The Power BI answers below are the recorded values of the spec
tools/parity/task60_type_tests_columns_spec.json and the saved batteries; the app never reads them.
"""
import unittest

from analytics_studio import measures
from tools import dax_oracle_diff as dax

# (expression, Power BI answer) pairs for measured leaf classes (Task 60, Part B of the spec)
ANSWERED = (
    ('ISDOUBLE(MAX(Facts[Sales])-"abc")', "True"),
    ('ISINT64(MAX(Facts[Sales])*"")', "False"),
    ('ISINT64(""+MAX(Facts[Sales]))', "False"),
    ('ISDOUBLE(""+CURRENCY(MAX(Facts[Sales])))', "True"),
    ('ISINT64(CURRENCY(MAX(Facts[Sales]))+"abc")', "False"),
    ('ISINT64(""-CURRENCY(MAX(Facts[Sales])))', "False"),
    ('ISDOUBLE(CURRENCY(MAX(Facts[Sales]))*"")', "False"),  # Currency times Text is a Currency (type cell, not a name)
)

# A column-read arithmetic whose saved Power BI answer is an error stays refused (the locked batteries raise here)
RAISES_REFUSED = (
    'ISDOUBLE(MAX(Facts[Sales])*"abc")',
)

# A column-read arithmetic outside the measured leaf classes (its saved class disagrees with the static type) stays refused
OUTSIDE_MEASURED = (
    'ISDOUBLE(CURRENCY(MAX(Facts[Sales]))-"TRUE")',  # the Currency[Double] - Text cell has ISINT64 evidence only
    'ISDOUBLE(MAX(Facts[Quantity])-"abc")',  # Int64 minus Text: no ISDOUBLE evidence in that type cell
    'ISDOUBLE(MAX(Facts[Sales])/"abc")',  # the Double / Text cell holds error rows
    'ISNUMBER(CURRENCY(MIN(Facts[Quantity]))*"")',  # Power BI raises; the (ISNUMBER, *, Currency, Text) rows were all CURRENCY of a literal, so Currency[Int64] has no evidence
)


class MeasuredLeafClasses(unittest.TestCase):
    def test_power_bi_answers_match(self):
        for expression, powerbi in ANSWERED:
            with self.subTest(expression=expression):
                self.assertEqual(dax.local(expression), powerbi)

    def test_raising_row_stays_refused(self):
        for expression in RAISES_REFUSED:
            with self.subTest(expression=expression):
                self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"))

    def test_outside_measured_class_stays_refused(self):
        for expression in OUTSIDE_MEASURED:
            with self.subTest(expression=expression):
                self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"))

    def test_leaf_types(self):
        columns = {"facts": {"sales": "decimal_number", "quantity": "whole_number", "note": "text"}, "other": {"amount": "whole_number"}}
        leaf = measures._arithmetic_leaf
        self.assertEqual(leaf(('string', 'abc'), columns), ("Text", False))
        self.assertEqual(leaf(('call', 'MAX', (('reference', 'Facts', 'Sales'),)), columns), ("Double", True))
        self.assertEqual(leaf(('call', 'SUM', (('reference', 'Facts', 'Quantity'),)), columns), ("Int64", True))
        self.assertEqual(leaf(('call', 'AVERAGE', (('reference', 'Facts', 'Quantity'),)), columns), ("Double", True))
        self.assertEqual(leaf(('call', 'MAX', (('reference', 'Other', 'Amount'),)), columns), ("Int64", True))  # any table, by column type
        self.assertEqual(leaf(('call', 'CURRENCY', (('call', 'MAX', (('reference', 'Facts', 'Sales'),)),)), columns), ("Currency[Double]", True))  # the Currency of a column read keeps the column type
        self.assertEqual(leaf(('call', 'CURRENCY', (('call', 'MIN', (('reference', 'Facts', 'Quantity'),)),)), columns), ("Currency[Int64]", True))
        self.assertEqual(leaf(('call', 'CURRENCY', (('number', 1, '1'),)), columns), ("Currency", False))
        self.assertIsNone(leaf(('call', 'MAX', (('reference', 'Facts', 'Note'),)), columns))  # a text column is unknown
        self.assertIsNone(leaf(('call', 'MAX', (('reference', 'Facts', 'Missing'),)), columns))
        self.assertIsNone(leaf(('call', 'MAX', (('reference', 'Facts', 'Sales'),)), None))

    def test_promotion_table(self):
        result = measures._arithmetic_result_type
        self.assertEqual(result("+", "Int64", "Int64"), "Int64")
        self.assertEqual(result("*", "Int64", "Int64"), "Int64")
        self.assertEqual(result("/", "Int64", "Int64"), "Double")
        self.assertEqual(result("+", "Currency", "Double"), "Double")
        self.assertEqual(result("+", "Currency", "Int64"), "Currency")
        self.assertEqual(result("*", "Currency", "Text"), "Currency")
        self.assertEqual(result("*", "Currency", "Double"), "Currency")
        self.assertEqual(result("*", "Currency", "Currency"), "Double")
        self.assertEqual(result("-", "Text", "Currency"), "Double")
        self.assertEqual(result("/", "Text", "Currency"), "Double")
        self.assertEqual(result("/", "Currency", "Text"), "Currency")

    def test_gate_ignores_other_shapes(self):
        columns = {"facts": {"sales": "decimal_number"}}
        sales = ('call', 'MAX', (('reference', 'Facts', 'Sales'),))
        plus = ('binary', '+', ('string', ''), sales)
        answer = measures._measured_column_arithmetic_answer
        self.assertIsNone(answer("ISLOGICAL", plus, columns))  # no evidence for this type test in the cell
        self.assertIsNone(answer("ISDOUBLE", ('logical', '&&', ('boolean', True), ('blank',)), columns))
        self.assertIsNone(answer("ISDOUBLE", sales, columns))
        self.assertIsNone(answer("ISDOUBLE", plus))  # no model: the column type is unknown
        self.assertIsNone(answer("ISDOUBLE", ('binary', '+', ('number', 1, '1'), ('number', 2, '2')), columns))  # no column leaf
        self.assertEqual(answer("ISINT64", plus, columns), False)
        self.assertEqual(answer("ISDOUBLE", plus, columns), True)

    def test_rule_follows_column_type_not_name(self):
        cases = (
            ("Revenue", "decimal_number", (('ISDOUBLE(MAX(T[{n}])-"abc")', "True"), ('ISINT64(MAX(T[{n}])*"")', "False"))),
            ("Count", "whole_number", (('ISINT64(MAX(T[{n}])-"abc")', "False"), ('ISDOUBLE(MAX(T[{n}])*"")', "True"))),
        )
        for name, kind, expected in cases:
            for template, powerbi in expected:
                expression = template.format(n=name)
                with self.subTest(expression=expression):
                    value = measures.evaluate_measures(
                        [{"name": "P", "expression": expression}], [{name: 1}], [name], "T", measure_names=["P"],
                        table_context=[{"id": "t", "name": "T", "headers": [name], "rows": [{name: 1}], "column_types": {name: kind}}], active_table_id="t",
                    )["P"]
                    self.assertEqual(str(value), powerbi)


if __name__ == "__main__":
    unittest.main()
