"""The arithmetic combiner and the parser of an arithmetic measure (Stage C4b, no store, no Qt).

Every expected value below is worked out by hand on a small number, never taken from the code under test. The
engine facts come from the saved Power BI answers the brief lists and from the engine's source (see dax_arith.py).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from analytics_studio.measures import MeasureError, parse_expression
from analytics_studio.store import dax_arith
from analytics_studio.store.dax_arith import (
    ArithUnsupported, Num, combine, divide, evaluate, negate, parse_arith,
)

D = Decimal


def i(value: str | int) -> Num:
    return Num("int", D(value))


def f(value: str | int) -> Num:
    return Num("double", D(value))


INT_BLANK = Num("int", None)
DOUBLE_BLANK = Num("double", None)


def signed(num: Num) -> bool:
    assert num.value is not None
    return num.value.is_signed()


# ---------------------------------------------------------------------------------------------------
# + and -: blank rules, exactness, kinds
# ---------------------------------------------------------------------------------------------------
def test_plus_both_blank_is_blank() -> None:
    assert combine("+", DOUBLE_BLANK, DOUBLE_BLANK) == Num("double", None)
    assert combine("-", INT_BLANK, INT_BLANK) == Num("int", None)


def test_plus_one_blank_returns_the_other_operand_unchanged() -> None:
    total = f("48.9872")
    assert combine("+", total, DOUBLE_BLANK) == Num("double", D("48.9872"))
    assert combine("+", DOUBLE_BLANK, total) == Num("double", D("48.9872"))
    assert combine("-", total, DOUBLE_BLANK) == Num("double", D("48.9872"))
    # not a double: the digits of the exact total survive (a float would give 48.98720000000000283...)
    assert combine("+", total, DOUBLE_BLANK).value.as_tuple() == D("48.9872").as_tuple()


def test_blank_minus_x_is_minus_x_exactly() -> None:
    assert combine("-", DOUBLE_BLANK, f("48.9872")) == Num("double", D("-48.9872"))
    assert combine("-", INT_BLANK, i(7)) == Num("int", D(-7))


def test_blank_minus_zero_keeps_the_sign_only_for_a_double() -> None:
    assert signed(combine("-", DOUBLE_BLANK, f(0)))
    assert not signed(combine("-", INT_BLANK, i(0)))


def test_two_ints_are_exact_and_stay_int() -> None:
    assert combine("+", i(2), i(3)) == Num("int", D(5))
    assert combine("-", i(2), i(3)) == Num("int", D(-1))
    assert combine("*", i(6), i(7)) == Num("int", D(42))


def test_int_plus_wraps_at_signed_64_bit() -> None:
    # 9223372036854775807 + 1 = 2**63, which wraps to -2**63
    assert combine("+", i(2**63 - 1), i(1)) == Num("int", D(-(2**63)))
    assert combine("-", i(-(2**63)), i(1)) == Num("int", D(2**63 - 1))
    assert combine("+", i(2**63 - 1), i(0)) == Num("int", D(2**63 - 1))


def test_int_times_wraps_like_the_engine_on_twelve_rows() -> None:
    # 12 * 10**15 * 1000 = 12 * 10**18 = 12000000000000000000; minus 2**64 (18446744073709551616) = -6446744073709551616
    first = combine("*", i(12), i(10**15))
    assert first == Num("int", D(12 * 10**15))
    assert combine("*", first, i(1000)) == Num("int", D(-6446744073709551616))


def test_int_square_wraps() -> None:
    # 24000000000240 squared is 576000000011520000000057600; reduced modulo 2**64 into the signed range it is
    # -7965174444529229568 (the engine answer of the brief)
    assert combine("*", i(24000000000240), i(24000000000240)) == Num("int", D(-7965174444529229568))


def test_a_double_operand_is_never_wrapped() -> None:
    result = combine("*", i(2**62), f(4))
    assert result.kind == "double"
    assert result.value == D(2**64)


def test_double_plus_is_done_in_ieee_doubles() -> None:
    # 0.1 + 0.2 is 0.3000000000000000444089209850062616169452667236328125 as a double
    assert combine("+", f("0.1"), f("0.2")) == Num("double", D("0.3000000000000000444089209850062616169452667236328125"))
    assert combine("+", f("0.5"), f("0.25")) == Num("double", D("0.75"))
    assert combine("-", f("0.5"), f("0.25")) == Num("double", D("0.25"))


def test_total_plus_itself_as_double_gives_the_exact_binary_value() -> None:
    # 48.9872 as a double doubled: the exact value of the double is not 97.9744 (saved engine answer)
    assert combine("+", f("48.9872"), f("48.9872")) == Num("double", D("97.97440000000000281943357549607753753662109375"))


def test_int_with_a_double_gives_a_double() -> None:
    assert combine("+", i(1), f("0.5")) == Num("double", D("1.5"))
    assert combine("*", i(3), f("0.5")) == Num("double", D("1.5"))
    assert combine("-", f("0.5"), i(1)) == Num("double", D("-0.5"))


# ---------------------------------------------------------------------------------------------------
# *
# ---------------------------------------------------------------------------------------------------
def test_times_blank_on_either_side_is_blank() -> None:
    assert combine("*", f("48.9872"), DOUBLE_BLANK) == Num("double", None)
    assert combine("*", DOUBLE_BLANK, f("48.9872")) == Num("double", None)
    assert combine("*", i(5), INT_BLANK) == Num("int", None)
    assert combine("*", INT_BLANK, i(5)) == Num("int", None)


def test_times_zero_sign() -> None:
    # -0.0 * 5 as doubles is -0.0
    assert signed(combine("*", f("-0.0"), f(5)))
    assert signed(combine("*", f(0), f(-5)))
    # two ints: exact 0, no sign
    assert not signed(combine("*", i(0), i(-5)))


# ---------------------------------------------------------------------------------------------------
# /
# ---------------------------------------------------------------------------------------------------
def test_slash_is_always_a_double() -> None:
    assert combine("/", i(10), i(4)) == Num("double", D("2.5"))
    assert combine("/", i(12), i(7)) == Num(
        "double", D("1.7142857142857141905523121749865822494029998779296875")
    )
    assert combine("/", i(1), i(3)) == Num("double", D("0.333333333333333314829616256247390992939472198486328125"))


def test_slash_of_exact_totals_is_the_double_quotient() -> None:
    # 24000000000240 / 12 = 2000000000020 exactly
    assert combine("/", i(24000000000240), i(12)) == Num("double", D("2000000000020"))


def test_slash_blank_left_is_blank() -> None:
    assert combine("/", DOUBLE_BLANK, f(3)) == Num("double", None)
    assert combine("/", INT_BLANK, i(3)) == Num("double", None)
    assert combine("/", DOUBLE_BLANK, f(0)) == Num("double", None)


def test_slash_blank_right_is_read_as_zero() -> None:
    assert combine("/", f(5), DOUBLE_BLANK) == Num("double", D("Infinity"))
    assert combine("/", f(-5), DOUBLE_BLANK) == Num("double", D("-Infinity"))
    zero_over_blank = combine("/", f(0), INT_BLANK).value
    assert zero_over_blank is not None and zero_over_blank.is_nan()


def test_slash_by_zero_is_infinity_and_zero_over_zero_is_nan() -> None:
    assert combine("/", i(5), i(0)) == Num("double", D("Infinity"))
    assert combine("/", i(-5), i(0)) == Num("double", D("-Infinity"))
    nan = combine("/", i(0), i(0)).value
    assert nan is not None and nan.is_nan() and nan.is_signed()  # the engine's NaN of 0/0 is the negative NaN


def test_slash_by_negative_zero_flips_the_infinity() -> None:
    assert combine("/", f(5), f("-0.0")).value == D("-Infinity")
    assert combine("/", f(-5), f("-0.0")).value == D("Infinity")


def test_slash_of_a_nan_by_zero_stays_nan() -> None:
    nan = combine("/", f("NaN"), f(0)).value
    assert nan is not None and nan.is_nan()


def test_infinity_arithmetic_follows_ieee() -> None:
    assert combine("+", f("Infinity"), f(1)).value == D("Infinity")
    assert combine("-", f("Infinity"), f("Infinity")).value.is_nan()
    assert combine("*", f("Infinity"), f(0)).value.is_nan()
    assert combine("*", f("Infinity"), f(-2)).value == D("-Infinity")
    assert combine("/", f(1), f("Infinity")).value == D(0)


def test_double_overflow_is_infinity_and_underflow_a_zero() -> None:
    assert combine("*", f("1e200"), f("1e200")).value == D("Infinity")
    assert combine("*", f("-1e200"), f("1e200")).value == D("-Infinity")
    tiny = combine("*", f("1e-200"), f("1e-200")).value
    assert tiny == 0


def test_subnormal_result_uses_fifteen_digits() -> None:
    # 1e-200 * 1e-120 = 1e-320, below the smallest normal double: the engine shows f"{value:.15G}"
    result = combine("*", f("1e-200"), f("1e-120")).value
    assert result == D(f"{1e-200 * 1e-120:.15G}")


def test_two_to_the_53_plus_one_as_int_and_as_double() -> None:
    big = 2**53 + 1
    assert combine("+", i(big), i(0)) == Num("int", D(big))  # exact: ints are never converted
    as_double = combine("+", f(big), f(0))
    assert as_double.value == D(2**53)  # the double nearest to 2**53 + 1 is 2**53 (ties to even)


# ---------------------------------------------------------------------------------------------------
# unary minus
# ---------------------------------------------------------------------------------------------------
def test_negate_is_exact_and_blank_stays_blank() -> None:
    assert negate(f("48.9872")) == Num("double", D("-48.9872"))
    assert negate(f("-0.5")) == Num("double", D("0.5"))
    assert negate(DOUBLE_BLANK) == DOUBLE_BLANK
    assert negate(INT_BLANK) == INT_BLANK


def test_negate_zero_sign_follows_the_type() -> None:
    assert signed(negate(f(0)))
    assert not signed(negate(f("-0.0")))
    assert not signed(negate(i(0)))


def test_negate_of_the_int64_minimum_wraps_to_itself() -> None:
    assert negate(i(-(2**63))) == Num("int", D(-(2**63)))
    assert negate(i(2**63 - 1)) == Num("int", D(-(2**63 - 1)))
    # a double of the same value is negated exactly
    assert negate(f(-(2**63))) == Num("double", D(2**63))


# ---------------------------------------------------------------------------------------------------
# DIVIDE
# ---------------------------------------------------------------------------------------------------
def test_divide_is_the_exact_decimal_quotient_in_28_digits() -> None:
    assert divide(i(1), i(3)) == Num("double", D("0.3333333333333333333333333333"))
    assert divide(i(2), i(3)) == Num("double", D("0.6666666666666666666666666667"))  # half even at digit 28
    assert divide(i(10), i(4)) == Num("double", D("2.5"))
    # -4.082266666...: 48.9872 / -12 = -4.08226666666666666666666666666... rounded at 28 digits
    assert divide(f("48.9872"), f("-12")) == Num("double", D("-4.082266666666666666666666667"))


def test_divide_zero_or_blank_denominator_gives_the_alternate() -> None:
    assert divide(i(1), i(0), i(-1)) == Num("double", D(-1))
    assert divide(i(1), INT_BLANK, i(7)) == Num("double", D(7))
    assert divide(i(1), i(0), f("0.5")) == Num("double", D("0.5"))
    assert divide(i(1), i(0)) == Num("double", None)
    assert divide(i(1), INT_BLANK) == Num("double", None)
    assert divide(i(0), i(0)) == Num("double", None)
    assert divide(i(0), i(0), i(0)) == Num("double", D(0))


def test_divide_blank_numerator_is_blank_even_with_an_alternate() -> None:
    assert divide(DOUBLE_BLANK, i(0), i(5)) == Num("double", None)
    assert divide(DOUBLE_BLANK, i(3), i(5)) == Num("double", None)
    assert divide(INT_BLANK, INT_BLANK, i(5)) == Num("double", None)


def test_divide_zero_numerator_over_a_number_keeps_the_sign_of_the_quotient() -> None:
    assert divide(i(0), i(5)).value == 0 and not signed(divide(i(0), i(5)))
    assert signed(divide(i(0), i(-5)))


def test_divide_result_is_a_double_for_the_next_operator() -> None:
    assert divide(i(6), i(3)).kind == "double"
    assert combine("+", divide(i(6), i(3)), i(1)) == Num("double", D(3))


def test_divide_refuses_a_number_that_is_not_finite() -> None:
    with pytest.raises(ArithUnsupported) as caught:
        divide(f("Infinity"), i(2))
    assert caught.value.reason == dax_arith.REASON_ARITH_DIVIDE_NON_FINITE
    with pytest.raises(ArithUnsupported):
        divide(i(2), f("NaN"))


def test_divide_tiny_denominator_counts_as_zero() -> None:
    # below the smallest normal double the engine answers the alternate
    assert divide(i(1), f("1e-320"), i(9)) == Num("double", D(9))


# ---------------------------------------------------------------------------------------------------
# parse_arith + evaluate: precedence, brackets, literals
# ---------------------------------------------------------------------------------------------------
def value_of(text: str, measures: dict[str, str] | None = None) -> Decimal | None:
    parsed = parse_arith(parse_expression(text), measures)
    assert parsed.ok, parsed.reasons
    assert not parsed.leaves
    return evaluate(parsed.tree, []).value


@pytest.mark.parametrize("text,expected", [
    ("1+2*3", 7),               # * before +
    ("(1+2)*3", 9),             # brackets
    ("10-4-3", 3),              # left associative (right associative would give 9)
    ("100/10/5", 2),            # (100/10)/5 = 2, not 100/(10/5) = 50
    ("8/4*2", 4),               # (8/4)*2 = 4, not 8/(4*2) = 1
    ("2*3+4*5", 26),
    ("-2*3", -6),
    ("2*-3", -6),
    ("1-(2-3)", 2),
    ("DIVIDE(1,0,-1)", -1),
    ("DIVIDE(10,4)", D("2.5")),
])
def test_precedence_and_brackets_through_parse_arith(text: str, expected: object) -> None:
    assert value_of(text) == D(expected)


def test_integer_literal_is_int_and_point_or_exponent_is_double() -> None:
    assert evaluate(parse_arith(parse_expression("5"), None).tree, []).kind == "int"
    assert evaluate(parse_arith(parse_expression("5.0+1"), None).tree, []).kind == "double"
    assert evaluate(parse_arith(parse_expression("1e2*1"), None).tree, []).kind == "double"
    # an int times an int stays int and wraps: 4611686018427387904 * 2 = 2**63 -> -2**63
    assert value_of("4611686018427387904*2") == D(-(2**63))
    # with a point it is a double
    assert value_of("4611686018427387904.0*2") == D(2**63)


def test_literal_beyond_64_bit_is_refused() -> None:
    parsed = parse_arith(parse_expression("1+9223372036854775808"), None)
    assert not parsed.ok and parsed.reasons == (dax_arith.REASON_ARITH_LITERAL,)
    assert parse_arith(parse_expression("1+9223372036854775807"), None).ok
    assert not parse_arith(parse_expression("1e400+1"), None).ok


def test_unknown_operator_and_unary_plus_keep_the_arithmetic_reason() -> None:
    for text in ("2^3", "+SUM(t[a])"):
        parsed = parse_arith(parse_expression(text), None)
        assert not parsed.ok and parsed.reasons == (dax_arith.REASON_ARITH_OPERATOR,), text


def test_leaves_are_listed_once_in_order_of_first_use() -> None:
    parsed = parse_arith(parse_expression("SUM(t[a]) / COUNTROWS(t) + SUM(t[a]) * 2"), None)
    assert parsed.ok
    assert [leaf.text for leaf in parsed.leaves] == ["SUM(t[a])", "COUNTROWS(T)"]
    assert parsed.tree == (
        "bin", "+", ("bin", "/", ("leaf", 0), ("leaf", 1)), ("bin", "*", ("leaf", 0), ("num", Num("int", D(2))))
    )


def test_leaf_text_parses_back_to_the_same_node() -> None:
    expression = (
        "CALCULATE(SUM(t[a]), t[b] > 5, NOT(t[c] = 3), t[d] IN {\"x\", \"it's\"}, t[e] >= DATE(2026,1,1)) / "
        "CALCULATE(COUNTROWS(t), t[b] = 0 || t[b] = 1)"
    )
    parsed = parse_arith(parse_expression(expression), None)
    assert parsed.ok and len(parsed.leaves) == 2
    for leaf in parsed.leaves:
        assert parse_expression(leaf.text) == leaf.node


def test_measure_reference_is_expanded_inline() -> None:
    measures = {"Revenue": "SUM(t[amt])", "Cost": "SUM(t[cost])", "Margin": "[Revenue] - [Cost]"}
    parsed = parse_arith(parse_expression("DIVIDE([Margin], [Revenue])"), measures)
    assert parsed.ok
    assert [leaf.text for leaf in parsed.leaves] == ["SUM(t[amt])", "SUM(t[cost])"]
    # every expanded reference is a "ref" node: the engine gives a measure name no static type
    assert parsed.tree == (
        "divide", ("ref", ("bin", "-", ("ref", ("leaf", 0)), ("ref", ("leaf", 1)))), ("ref", ("leaf", 0)), None
    )


def test_measure_reference_names_are_case_insensitive() -> None:
    parsed = parse_arith(parse_expression("[revenue] * 2"), {"Revenue": "SUM(t[amt])"})
    assert parsed.ok and [leaf.text for leaf in parsed.leaves] == ["SUM(t[amt])"]


def test_measure_reference_keeps_the_own_filter_of_the_measure() -> None:
    measures = {"East": 'CALCULATE(SUM(t[amt]), t[region] = "East")'}
    parsed = parse_arith(parse_expression("[East] + 1"), measures)
    assert parsed.ok
    assert parsed.leaves[0].text == 'CALCULATE(SUM(t[amt]), t[region] = "East")'


def test_unknown_name_and_cycle_keep_the_existing_reasons() -> None:
    parsed = parse_arith(parse_expression("[Nope] + 1"), {})
    assert parsed.reasons == ("unknown column or measure 'Nope'",)
    cyc = parse_arith(parse_expression("[A] + 1"), {"A": "[B] * 2", "B": "[A] - 1"})
    assert cyc.reasons == ("cycle detected in measure reference 'A'",)
    self_cycle = parse_arith(parse_expression("[A] + 1"), {"A": "[A] + 1"})
    assert self_cycle.reasons == ("cycle detected in measure reference 'A'",)


def test_reference_chain_longer_than_32_is_refused() -> None:
    # pure aliases add no depth to the tree, only to the chain of references
    measures = {f"M{n}": f"[M{n + 1}]" for n in range(40)}
    measures["M40"] = "SUM(t[a])"
    parsed = parse_arith(parse_expression("[M0] + 1"), measures)
    assert parsed.reasons == (dax_arith.MEASURE_CHAIN_TOO_DEEP,)
    assert parse_arith(parse_expression("[M10] + 1"), measures).ok  # 31 references: within the cap
    assert parse_arith(parse_expression("[M9] + 1"), measures).ok  # M9 ... M40: 32 references, the limit
    assert parse_arith(parse_expression("[M8] + 1"), measures).reasons == (dax_arith.MEASURE_CHAIN_TOO_DEEP,)  # 33


def test_calculate_over_an_arithmetic_measure_is_refused() -> None:
    measures = {"Avg": "SUM(t[a]) / COUNTROWS(t)", "Alias": "[Avg]", "Plain": "SUM(t[a])"}
    for text in ("CALCULATE([Avg], t[b] = 1) + 1", "CALCULATE([Alias], t[b] = 1) * 2"):
        parsed = parse_arith(parse_expression(text), measures)
        assert parsed.reasons == (dax_arith.REASON_ARITH_IN_CALCULATE,), text
    ok = parse_arith(parse_expression("CALCULATE([Plain], t[b] = 1) + 1"), measures)
    assert ok.ok and ok.leaves[0].text == "CALCULATE([Plain], t[b] = 1)"


def test_calculate_with_only_a_measure_is_that_measure() -> None:
    measures = {"Avg": "SUM(t[a]) / COUNTROWS(t)"}
    parsed = parse_arith(parse_expression("CALCULATE([Avg]) + 1"), measures)
    assert parsed.ok and [leaf.text for leaf in parsed.leaves] == ["SUM(t[a])", "COUNTROWS(T)"]


def test_divide_alternate_must_be_a_number_literal() -> None:
    assert parse_arith(parse_expression("DIVIDE(SUM(t[a]), 0, -1)"), None).ok
    assert parse_arith(parse_expression("DIVIDE(SUM(t[a]), 0, 0.5)"), None).ok
    for text in ("DIVIDE(1, 0, BLANK())", 'DIVIDE(1, 0, "x")', "DIVIDE(1, 0, TRUE())"):
        parsed = parse_arith(parse_expression(text), None)
        assert parsed.reasons == (dax_arith.REASON_ARITH_DIVIDE_ALT,), text
    # a computed alternate is already an error of the parser, before parse_arith sees it
    for text in ("DIVIDE(1, 0, SUM(t[a]))", "DIVIDE(1, 0, 1+1)"):
        with pytest.raises(MeasureError):
            parse_expression(text)


def test_divide_alternate_value_is_the_literal() -> None:
    parsed = parse_arith(parse_expression("DIVIDE(1, 0, -7)"), None)
    assert parsed.tree[3] == Num("int", D(-7))
    assert value_of("DIVIDE(1, 0, 0.5)") == D("0.5")


def test_a_leaf_that_is_not_a_total_is_handed_on_as_a_leaf() -> None:
    parsed = parse_arith(parse_expression("ROUND(SUM(t[a]), 2) + SUMX(t, t[a])"), None)
    assert parsed.ok
    assert [leaf.text for leaf in parsed.leaves] == ["ROUND(SUM(t[a]), 2)", "SUMX(T, t[a])"]


def test_a_leaf_that_cannot_be_written_back_is_refused() -> None:
    node = ("call", "FOO", (("let", (), ("number", D(1), "1")),))
    parsed = parse_arith(("binary", "+", node, ("number", D(1), "1")), None)
    assert not parsed.ok
    assert parsed.reasons == ("function FOO is not on the store whitelist",)


# ---------------------------------------------------------------------------------------------------
# caps: at the limit and one over
# ---------------------------------------------------------------------------------------------------
def balanced(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    middle = len(items) // 2
    return f"({balanced(items[:middle])} + {balanced(items[middle:])})"


def totals(count: int) -> list[str]:
    return [f"SUM(t[c{n}])" for n in range(count)]


def test_cap_of_eight_distinct_totals() -> None:
    at_limit = parse_arith(parse_expression(balanced(totals(8))), None)
    assert at_limit.ok and len(at_limit.leaves) == 8
    over = parse_arith(parse_expression(balanced(totals(9))), None)
    assert over.reasons == (dax_arith.REASON_ARITH_CAP_LEAVES,)


def test_a_repeated_total_counts_once_for_the_leaf_cap() -> None:
    items = totals(8) + [totals(8)[0]]
    parsed = parse_arith(parse_expression(balanced(items)), None)
    assert parsed.ok and len(parsed.leaves) == 8


def test_cap_of_24_nodes() -> None:
    twelve = balanced(["1"] * 12)  # 12 numbers and 11 operators: 23 nodes
    assert parse_arith(parse_expression(twelve), None).nodes == 23
    assert parse_arith(parse_expression(f"-{twelve}"), None).nodes == 24  # exactly at the limit
    over = parse_arith(parse_expression(f"-(-{twelve})"), None)
    assert over.reasons == (dax_arith.REASON_ARITH_CAP_NODES,)


def test_cap_of_depth_8() -> None:
    chain = "+".join(["1"] * 8)  # a left chain of 8 numbers is 8 levels deep
    at_limit = parse_arith(parse_expression(chain), None)
    assert at_limit.ok and at_limit.depth == 8
    over = parse_arith(parse_expression("+".join(["1"] * 9)), None)
    assert over.reasons == (dax_arith.REASON_ARITH_CAP_DEPTH,)


def test_depth_counts_through_measure_references() -> None:
    measures = {"A": "[B] + 1", "B": "[C] + 1", "C": "1 + 1"}
    parsed = parse_arith(parse_expression("[A] + 1"), measures)
    assert parsed.ok and parsed.depth == 5  # the root, then A, B and C one level each, then the numbers
    deep = {f"M{n}": f"[M{n + 1}] + 1" for n in range(8)}
    deep["M8"] = "1"
    assert parse_arith(parse_expression("[M0] + 1"), deep).reasons == (dax_arith.REASON_ARITH_CAP_DEPTH,)


# ---------------------------------------------------------------------------------------------------
# the range check of a whole-number total
# ---------------------------------------------------------------------------------------------------
def test_leaf_value_in_range() -> None:
    assert dax_arith.leaf_value_in_range(i(2**63 - 1))
    assert dax_arith.leaf_value_in_range(i(-(2**63)))
    assert not dax_arith.leaf_value_in_range(i(2**63))
    assert not dax_arith.leaf_value_in_range(i(-(2**63) - 1))
    assert dax_arith.leaf_value_in_range(f(2**70))  # a double has no such limit
    assert dax_arith.leaf_value_in_range(INT_BLANK)


def test_evaluate_uses_the_leaf_values_by_index() -> None:
    parsed = parse_arith(parse_expression("SUM(t[a]) - COUNTROWS(t) * 2"), None)
    assert evaluate(parsed.tree, [i(100), i(7)]) == Num("int", D(86))
    # the kind of a blank is the kind of its total: a blank double minus an int is a double, a blank int an int
    assert evaluate(parsed.tree, [DOUBLE_BLANK, i(7)]) == Num("double", D(-14))
    assert evaluate(parsed.tree, [INT_BLANK, i(7)]) == Num("int", D(-14))


# ---------------------------------------------------------------------------------------------------
# C4b fix 1: the parser refuses a divisor that can be a minus zero, and a DIVIDE by a subnormal literal
# ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "COUNT(t[sd]) / MIN(t[sw])", "COUNT(t[sd]) / MAX(t[sd])", "COUNT(t[sd]) / (MIN(t[sw]) * 2)",
    "DIVIDE(COUNT(t[sd]), MIN(t[sw]))", "DIVIDE(COUNT(t[sd]), 1 + MAX(t[sw]) - 1)",
])
def test_a_divisor_with_min_or_max_of_a_column_is_refused_by_name(text: str) -> None:
    parsed = parse_arith(parse_expression(text), None)
    assert parsed.reasons == (dax_arith.REASON_ARITH_SIGNED_ZERO_DIVISOR,), (text, parsed.reasons)


def test_a_minus_zero_rule_keeps_the_other_divisors_and_the_numerator() -> None:
    # the numerator may be MIN: its sign does not reach a division by a sum; a literal 0 divisor stays allowed
    assert parse_arith(parse_expression("MIN(t[sw]) / SUM(t[sw])"), None).ok
    assert parse_arith(parse_expression("DIVIDE(MIN(t[sw]), SUM(t[sw]), 7)"), None).ok
    assert parse_arith(parse_expression("COUNT(t[sd]) / 0"), None).ok
    assert parse_arith(parse_expression("DIVIDE(COUNT(t[sd]), 0)"), None).ok


@pytest.mark.parametrize("text", ["DIVIDE(COUNT(t[sd]), 1E-310, 1E3)", "DIVIDE(COUNT(t[sd]), 1E-308)", "DIVIDE(COUNT(t[sd]), -1E-310)"])
def test_divide_by_a_subnormal_literal_is_refused_by_name(text: str) -> None:
    parsed = parse_arith(parse_expression(text), None)
    assert parsed.reasons == (dax_arith.REASON_ARITH_DIVIDE_SUBNORMAL,), (text, parsed.reasons)


def test_divide_by_a_normal_small_literal_is_not_refused() -> None:
    # 1E-300 is above the smallest normal double (about 2.2E-308): a normal denominator, planned as the engine does
    assert parse_arith(parse_expression("DIVIDE(COUNT(t[sd]), 1E-300)"), None).ok


def test_the_depth_sentence_names_both_limits() -> None:
    sentence = dax_arith.REASON_ARITH_CAP_DEPTH
    assert "more than 8 terms in a row" in sentence and "nested more than 8 levels deep" in sentence
    flat = parse_arith(parse_expression("+".join(["1"] * 9) + " + COUNT(t[sd])"), None)
    assert flat.reasons == (dax_arith.REASON_ARITH_CAP_DEPTH,)
