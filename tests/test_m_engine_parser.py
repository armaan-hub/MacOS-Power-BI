"""Tests for the Power Query M lexer and parser (analytics_studio.m_engine).

Part A: source text to AST only. Every battery expression that Power BI parsed
must parse; the two that Power BI rejected with ERR:PARTITION must raise
MSyntaxError. The battery JSON is read here in the test only.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio.m_engine import MSyntaxError, parse
from analytics_studio.m_engine import ast as A

BATTERY = Path(__file__).resolve().parent.parent / "docs" / "plans" / "2026-11-08-m-core-battery.json"
SYNTAX_ERROR_PREFIX = "ERR:PARTITION"


def _battery_cases() -> list[dict]:
    with BATTERY.open(encoding="utf-8") as handle:
        return json.load(handle)["cases"]


class BatteryParseTests(unittest.TestCase):
    """One generated test per battery expression (174 in total)."""


def _make_battery_test(expression: str, rejected: bool):
    def test(self):
        if rejected:
            with self.assertRaises(MSyntaxError):
                parse(expression)
        else:
            parse(expression)
    return test


for _index, _case in enumerate(_battery_cases()):
    _rejected = _case["power_bi"].startswith(SYNTAX_ERROR_PREFIX)
    _kind = "rejects" if _rejected else "parses"
    setattr(
        BatteryParseTests,
        f"test_{_kind}_{_index:03d}",
        _make_battery_test(_case["expression"], _rejected),
    )


class AstShapeTests(unittest.TestCase):

    def num(self, value):
        return A.NumberLiteral(str(value), value)

    def ident(self, name, inclusive=False):
        return A.Identifier(name, inclusive)

    def test_precedence_multiplication_binds_tighter(self):
        self.assertEqual(
            parse("1+2*3"),
            A.BinaryOp("+", self.num(1), A.BinaryOp("*", self.num(2), self.num(3))),
        )

    def test_subtraction_is_left_associative(self):
        self.assertEqual(
            parse("1-2-3"),
            A.BinaryOp("-", A.BinaryOp("-", self.num(1), self.num(2)), self.num(3)),
        )

    def test_and_binds_tighter_than_or(self):
        self.assertEqual(
            parse("a and b or c"),
            A.BinaryOp("or", A.BinaryOp("and", self.ident("a"), self.ident("b")), self.ident("c")),
        )
        self.assertEqual(
            parse("a or b and c"),
            A.BinaryOp("or", self.ident("a"), A.BinaryOp("and", self.ident("b"), self.ident("c"))),
        )

    def test_not_binds_tighter_than_equality(self):
        self.assertEqual(
            parse("not a = b"),
            A.BinaryOp("=", A.UnaryOp("not", self.ident("a")), self.ident("b")),
        )

    def test_unary_minus_binds_tighter_than_multiplication(self):
        self.assertEqual(
            parse("-1 * 2"),
            A.BinaryOp("*", A.UnaryOp("-", self.num(1)), self.num(2)),
        )

    def test_meta_binds_tighter_than_multiplication(self):
        self.assertEqual(
            parse("1 * 2 meta [a=1]"),
            A.BinaryOp("*", self.num(1), A.BinaryOp(
                "meta", self.num(2), A.RecordExpr((A.RecordField("a", self.num(1)),)))),
        )

    def test_is_and_as_sit_between_and_and_equality(self):
        node = parse("1 = 1 as number")
        self.assertIsInstance(node, A.TypeOp)
        self.assertEqual(node.op, "as")
        self.assertEqual(node.operand, A.BinaryOp("=", self.num(1), self.num(1)))

    def test_item_access_optional_after_field_access(self):
        self.assertEqual(
            parse("x[a]{0}?"),
            A.ItemAccess(A.FieldAccess(self.ident("x"), "a"), self.num(0), optional=True),
        )

    def test_each_with_implicit_field_and_underscore(self):
        self.assertEqual(
            parse("each [a] + _"),
            A.EachExpr(A.BinaryOp("+", A.FieldSelector("a"), self.ident("_"))),
        )

    def test_nested_let(self):
        node = parse("let a = 1, b = let c = 2 in c in b")
        self.assertIsInstance(node, A.LetExpr)
        self.assertEqual([b.name for b in node.bindings], ["a", "b"])
        self.assertIsInstance(node.bindings[1].value, A.LetExpr)
        self.assertEqual(node.body, self.ident("b"))

    def test_function_literal_with_optional_and_typed_params(self):
        node = parse("(x as number, optional y) as text => x")
        self.assertIsInstance(node, A.FunctionLiteral)
        self.assertEqual(
            node.params,
            (
                A.Param("x", A.PrimitiveType("number"), False),
                A.Param("y", None, True),
            ),
        )
        self.assertEqual(node.return_type, A.PrimitiveType("text"))
        self.assertEqual(node.body, self.ident("x"))

    def test_empty_parameter_list(self):
        node = parse("() => 1")
        self.assertEqual(node, A.FunctionLiteral((), None, self.num(1)))

    def test_parenthesised_expression_with_as_is_not_a_function(self):
        node = parse("(1) as number")
        self.assertEqual(node, A.TypeOp("as", self.num(1), A.PrimitiveType("number")))

    def test_try_otherwise(self):
        self.assertEqual(parse("try 1 otherwise 2"), A.TryExpr(self.num(1), self.num(2), None))

    def test_try_catch_with_function_handler(self):
        node = parse("try 1 catch (e) => e")
        self.assertIsInstance(node, A.TryExpr)
        self.assertIsNone(node.otherwise)
        self.assertIsInstance(node.catch, A.FunctionLiteral)

    def test_error_takes_whole_expression(self):
        self.assertEqual(
            parse('error "a" & "b"'),
            A.ErrorExpr(A.BinaryOp("&", A.TextLiteral("a"), A.TextLiteral("b"))),
        )

    def test_error_is_not_an_operand_of_or(self):
        with self.assertRaises(MSyntaxError):
            parse('true or error "x"')

    def test_meta_operator(self):
        self.assertEqual(
            parse("1 meta [a=1]"),
            A.BinaryOp("meta", self.num(1), A.RecordExpr((A.RecordField("a", self.num(1)),))),
        )

    def test_list_with_range_and_text(self):
        self.assertEqual(
            parse('{1..5, "a"}'),
            A.ListExpr((A.ListRange(self.num(1), self.num(5)), A.TextLiteral("a"))),
        )

    def test_quoted_identifier_and_dotted_name(self):
        self.assertEqual(
            parse('#"a b" + 1'),
            A.BinaryOp("+", self.ident("a b"), self.num(1)),
        )
        self.assertEqual(parse("Value.Type(1)"), A.Invocation(self.ident("Value.Type"), (self.num(1),)))

    def test_inclusive_reference(self):
        self.assertEqual(
            parse("@rec(n-1)"),
            A.Invocation(self.ident("rec", inclusive=True),
                         (A.BinaryOp("-", self.ident("n"), self.num(1)),)),
        )

    def test_comments_are_skipped(self):
        self.assertEqual(
            parse("1 // line comment\n + /* block */ 2"),
            A.BinaryOp("+", self.num(1), self.num(2)),
        )

    def test_text_escapes_are_decoded(self):
        node = parse('"a""b#(tab)#(0041)#(cr,lf)#(lf)"')
        self.assertEqual(node, A.TextLiteral('a"b\tA\r\n\n'))

    def test_number_forms(self):
        self.assertEqual(parse("0x1F"), A.NumberLiteral("0x1F", 31))
        self.assertEqual(parse(".5").value, 0.5)
        self.assertEqual(parse("1.5E-3").value, 0.0015)
        self.assertEqual(parse("1e3").value, 1000.0)

    def test_projection(self):
        self.assertEqual(parse("x[[a],[b]]"), A.Projection(self.ident("x"), ("a", "b")))

    def test_record_field_names_quoted_and_with_spaces(self):
        node = parse('[#"b c" = 2, Column 1 = 3]')
        self.assertEqual([f.name for f in node.fields], ["b c", "Column 1"])

    def test_field_selector_versus_record(self):
        self.assertEqual(parse("[a]"), A.FieldSelector("a"))
        self.assertEqual(parse("[a=1][a]"), A.FieldAccess(A.RecordExpr((A.RecordField("a", self.num(1)),)), "a"))

    def test_special_literals(self):
        self.assertEqual(parse("#infinity"), A.SpecialLiteral("infinity"))
        self.assertEqual(parse("-#nan"), A.UnaryOp("-", A.SpecialLiteral("nan")))

    def test_if_expression(self):
        self.assertEqual(
            parse("if true then 1 else 2"),
            A.IfExpr(A.LogicalLiteral(True), self.num(1), self.num(2)),
        )

    def test_invocation_of_parenthesised_each(self):
        self.assertEqual(
            parse("(each _ * 2)(4)"),
            A.Invocation(A.EachExpr(A.BinaryOp("*", self.ident("_"), self.num(2))), (self.num(4),)),
        )

    def test_type_literal_list_and_table(self):
        self.assertEqual(parse("type {number}"), A.TypeLiteral(A.ListType(A.PrimitiveType("number"))))
        self.assertEqual(
            parse("type table [a = number, optional b = text]"),
            A.TypeLiteral(A.TableType(A.RecordType((
                A.TypeField("a", A.PrimitiveType("number"), False),
                A.TypeField("b", A.PrimitiveType("text"), True),
            )))),
        )

    def test_nullable_type_assertion(self):
        self.assertEqual(
            parse("1 as nullable number"),
            A.TypeOp("as", self.num(1), A.NullableType(A.PrimitiveType("number"))),
        )

    def test_syntax_error_reports_position_and_line(self):
        with self.assertRaises(MSyntaxError) as ctx:
            parse("1 +\n  )")
        self.assertEqual(ctx.exception.line, 2)
        self.assertEqual(ctx.exception.column, 3)
        self.assertEqual(ctx.exception.position, 6)

    def test_trailing_tokens_are_an_error(self):
        with self.assertRaises(MSyntaxError):
            parse("1 2")

    def test_unterminated_text_is_an_error(self):
        with self.assertRaises(MSyntaxError):
            parse('"abc')


if __name__ == "__main__":
    unittest.main()
