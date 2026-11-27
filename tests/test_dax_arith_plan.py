"""Arithmetic over totals on the store (Stage C4b): ArithPlan and GroupedArithPlan, with hand-worked values.

The table below has 12 rows; every expected value is worked out on paper from it (or is a value the brief measured
on the engine for 12 rows). No test asserts on SQL text, on elapsed time or on a timeout.

      n   q    a     r      g   d
      1   10   1.50  East   x   2024-01-01
      2   20   2.25  East   y   2024-01-02
      3   30   ''    West   x   2024-01-03
      4   -5   4.00  West   y   2024-01-01
      5   5    0.50  North  x   ''
      6   ''   3.00  North  y   2024-01-02
      7   7    1.00  East   x   2024-01-03
      8   8    2.00  West   y   2024-01-04
      9   9    3.00  North  x   2024-01-05
      10  1    0.25  East   y   2024-01-06
      11  2    0.75  West   x   2024-01-07
      12  3    1.50  North  y   2024-01-08

  SUM(q) = 90, COUNT(q) = 11, SUM(a) = 19.75, COUNT(a) = 11, COUNTROWS = 12.
  East: q 38, a 5.00, 4 rows.  West: q 35, a 6.75, 4 rows.  North: q 17, a 8.00, 4 rows.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from analytics_studio import dax_dates
from analytics_studio.store import DuckStore, dax_arith, dax_route, dax_sql, dax_whitelist, import_csv_to_store
from analytics_studio.store.dax_sql import (
    ArithPlan, GroupByPlan, GroupedArithPlan, MeasurePlan, Refusal, column_decimal_meta, plan_group_by, plan_measure,
)

CSV = (
    "n,q,a,r,g,d\n"
    "1,10,1.50,East,x,2024-01-01\n"
    "2,20,2.25,East,y,2024-01-02\n"
    "3,30,,West,x,2024-01-03\n"
    "4,-5,4.00,West,y,2024-01-01\n"
    "5,5,0.50,North,x,\n"
    "6,,3.00,North,y,2024-01-02\n"
    "7,7,1.00,East,x,2024-01-03\n"
    "8,8,2.00,West,y,2024-01-04\n"
    "9,9,3.00,North,x,2024-01-05\n"
    "10,1,0.25,East,y,2024-01-06\n"
    "11,2,0.75,West,x,2024-01-07\n"
    "12,3,1.50,North,y,2024-01-08\n"
)
TYPES = {"n": "whole_number", "q": "whole_number", "a": "decimal_number", "r": "text", "g": "text", "d": "date"}
D = Decimal
BLANK = 'CALCULATE(SUM(s[a]), s[r] = "Nowhere")'  # a Double total that is blank
BLANK_INT = 'CALCULATE(SUM(s[q]), s[r] = "Nowhere")'  # an Int64 total that is blank


class World:
    def __init__(self, base: Path) -> None:
        path = base / "s.csv"
        path.write_text(CSV, encoding="utf-8")
        self.store = DuckStore(str(base / "s.db"))
        import_csv_to_store(self.store, "s_csv", path, {})
        self.meta = {("s", c): m for c, m in column_decimal_meta(self.store, "s_csv", list(TYPES)).items()}

    def kwargs(self, **extra: Any) -> dict[str, Any]:
        base: dict[str, Any] = dict(
            home_table="s", tables={"s": TYPES}, store_tables={"s": "s_csv"}, column_meta=self.meta,
        )
        base.update(extra)
        return base

    def plan(self, expression: str, **extra: Any) -> Any:
        return plan_measure(expression, **self.kwargs(**extra))

    def value(self, expression: str, **extra: Any) -> Any:
        plan = self.plan(expression, **extra)
        assert isinstance(plan, ArithPlan), (expression, plan)
        return plan.execute(self.store)

    def group_plan(self, expression: str, column: str, **extra: Any) -> Any:
        return plan_group_by(expression, group_by=("s", column), **self.kwargs(**extra))

    def groups(self, expression: str, column: str, **extra: Any) -> Any:
        plan = self.group_plan(expression, column, **extra)
        assert isinstance(plan, GroupedArithPlan), (expression, plan)
        return plan.execute(self.store)

    def close(self) -> None:
        self.store.close()


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Any:
    w = World(tmp_path_factory.mktemp("arith"))
    yield w
    w.close()


@pytest.fixture()
def fresh(tmp_path: Path) -> Any:
    w = World(tmp_path)
    yield w
    w.close()


def same(value: Any, expected: Any) -> None:
    """Exactly the expected value, the same class, and the sign of a zero."""
    assert type(value) is type(expected), (value, expected)
    if expected is None:
        return
    assert value == expected, (value, expected)
    if expected.is_zero():
        assert value.is_signed() == expected.is_signed(), (value, expected)


# ---------------------------------------------------------------------------------------------------
# scalar values
# ---------------------------------------------------------------------------------------------------
SCALARS: list[tuple[str, Decimal | None]] = [
    ("SUM(s[q]) + 1", D(91)),
    ("1 + SUM(s[q])", D(91)),
    ("SUM(s[q]) * 2 - COUNTROWS(s)", D(168)),
    ("SUM(s[q]) * SUM(s[q])", D(8100)),
    ("SUM(s[a]) + SUM(s[a])", D("39.5")),
    ("SUM(s[a]) - 0.25", D("19.5")),
    ("SUM(s[q]) - COUNTROWS(s) * 2 + 0.5", D("66.5")),
    ("SUM(s[q]) / COUNTROWS(s)", D("7.5")),
    ("COUNTROWS(s) / 4", D(3)),
    ("COUNTROWS(s) / 7", D("1.7142857142857141905523121749865822494029998779296875")),  # the double quotient
    ("SUM(s[q]) / 0", D("Infinity")),
    ("-SUM(s[q]) / 0", D("-Infinity")),
    ("-SUM(s[a])", D("-19.75")),
    ("-(SUM(s[a]) - 20)", D("0.25")),
    ("(SUM(s[q]) + 10) / 4", D(25)),
    ("10 - 4 - SUM(s[q]) / 90", D(5)),  # (10 - 4) - 1.0 = 5
    ("100 / 10 / 5 + COUNTROWS(s) - COUNTROWS(s)", D(2)),
    ("8 / 4 * 2 + SUM(s[q]) - SUM(s[q])", D(4)),
    ("1 + 2 * 3 + COUNTROWS(s) - COUNTROWS(s)", D(7)),
    # integer wrap at signed 64 bit: 12 * 2**61 = 3 * 2**63 wraps to -2**63
    ("COUNTROWS(s) * 2305843009213693952", D(-(2**63))),
    ("COUNTROWS(s) * 2305843009213693952 * 3", D(-(2**63))),  # wraps twice: -2**63 * 3 = -3 * 2**63 wraps to -2**63
    ("COUNTROWS(s) * 4611686018427387904", D(0)),  # 12 * 2**62 = 3 * 2**64
    ("SUM(s[q]) + 9223372036854775807", D(90 + 2**63 - 1 - 2**64)),
    # blank rules
    (BLANK + " + 5", D(5)),
    (BLANK + " - 5", D(-5)),
    ("5 - " + BLANK, D(5)),
    (BLANK + " * 5", None),
    ("5 * " + BLANK, None),
    (BLANK + " / 5", None),
    ("5 / " + BLANK, D("Infinity")),
    (BLANK + " + " + BLANK, None),
    (BLANK_INT + " + 1", D(1)),
    (BLANK_INT + " - SUM(s[q])", D(-90)),
    # DIVIDE
    ("DIVIDE(SUM(s[a]), 0)", None),
    ("DIVIDE(SUM(s[a]), 0, -1)", D(-1)),
    ("DIVIDE(SUM(s[a]), 3)", D("6.583333333333333333333333333")),
    ("DIVIDE(SUM(s[q]), COUNTROWS(s))", D("7.5")),
    ("DIVIDE(" + BLANK + ", 0, 5)", None),
    ("DIVIDE(" + BLANK + ", SUM(s[a]), 5)", None),
    ("DIVIDE(COUNTROWS(s), 0, 7)", D(7)),
    ("DIVIDE(SUM(s[a]), " + BLANK + ", 0.5)", D("0.5")),
    ("DIVIDE(SUM(s[a]), " + BLANK + ")", None),
    ('DIVIDE(CALCULATE(SUM(s[a]), s[r] = "East"), SUM(s[a]))', D("0.2531645569620253164556962025")),  # 5 / 19.75 = 20 / 79
    ("DIVIDE(COUNTROWS(s), 7)", D("1.714285714285714285714285714")),  # the exact quotient, not the double of COUNTROWS(s) / 7
    ("DIVIDE(SUM(s[q]) - COUNTROWS(s) * 7, SUM(s[q]))", D("0.06666666666666666666666666667")),  # 6 / 90
]


@pytest.mark.parametrize("expression,expected", SCALARS, ids=[e for e, _ in SCALARS])
def test_scalar_value_is_the_hand_worked_one(world: World, expression: str, expected: Decimal | None) -> None:
    same(world.value(expression), expected)


def test_division_by_zero_cases_and_signs(world: World) -> None:
    # 0 / 0 is the negative NaN inside an expression; the measure shows an unsigned NaN
    nan = world.value("SUM(s[q]) * 0 / 0")
    assert nan.is_nan() and not nan.is_signed()
    # a zero of the double type keeps its minus sign inside the expression: 1 / -0.0 is -Infinity ...
    same(world.value("1 / (SUM(s[a]) * 0 * -1)"), D("-Infinity"))
    # ... and the measure shows zero without a sign
    zero = world.value("SUM(s[a]) * 0 * -1")
    assert zero == 0 and not zero.is_signed()
    same(world.value("0 * SUM(s[q]) * -1"), D(0))
    # Infinity minus Infinity is NaN
    assert world.value("SUM(s[q]) / 0 - SUM(s[q]) / 0").is_nan()


# ---------------------------------------------------------------------------------------------------
# measure references have no static type in the engine: exact Decimal arithmetic, no wrap
# ---------------------------------------------------------------------------------------------------
REFS = {
    "Total": "SUM(s[a])", "Rows": "COUNTROWS(s)", "Qty": "SUM(s[q])", "A": "SUM(s[q])", "B": "[A]", "C": "[B]",
    "East": 'CALCULATE(SUM(s[a]), s[r] = "East")', "Half": "SUM(s[q]) / COUNTROWS(s)",
}
REFERENCES: list[tuple[str, Decimal | None]] = [
    ("[Total] / 7", D("2.821428571428571428571428571")),  # 19.75 / 7 in 28 digits (the double of SUM(a) / 7 differs)
    ("[Rows] / 7", D("1.714285714285714285714285714")),   # 12 / 7 in 28 digits; COUNTROWS(s) / 7 is the double above
    ("[Rows] * 2305843009213693952", D(27670116110564327424)),  # no wrap through a reference
    ("[C] / 7", D("12.85714285714285714285714286")),
    ("[Qty] * [Qty]", D(8100)),
    ("[Total] + [Total]", D("39.5")),
    ("[East] + 1", D(6)),
    ("[Half] * 2", D(15)),
    ("[Half] + [Half]", D(15)),
    ("DIVIDE([Total], [Rows])", D("1.645833333333333333333333333")),  # 19.75 / 12 = 1.6458333...
    ("DIVIDE([Qty] - [Rows], [Qty])", D("0.8666666666666666666666666667")),  # 78 / 90
    # CALCULATE of a measure has the (missing) static type of the measure: untyped, so the quotient is the exact one.
    # g = x: a = 1.5 + 0.5 + 1 + 3 + 0.75 = 6.75 (row 3 is blank); 6.75 / 7 in 28 digits
    ('CALCULATE([Total], s[g] = "x") / 7', D("0.9642857142857142857142857143")),
    ("-[Total]", D("-19.75")),
    ("CALCULATE([Half]) * 2", D(15)),
    ("[Total] * 0 * -1", D(0)),
    # a zero of an untyped operator has no sign (the double version above gives -Infinity)
    ("1 / ([Total] * 0 * -1)", D("Infinity")),
    ("-[Rows]", D(-12)),
]


@pytest.mark.parametrize("expression,expected", REFERENCES, ids=[e for e, _ in REFERENCES])
def test_measure_references_are_exact_and_unwrapped(world: World, expression: str, expected: Decimal | None) -> None:
    plan = world.plan(expression, measures=REFS)
    assert isinstance(plan, ArithPlan), (expression, plan)
    same(plan.execute(world.store), expected)


def test_reference_to_filtered_measure_keeps_its_own_filter(world: World) -> None:
    # East a = 1.5 + 2.25 + 1 + 0.25 = 5; under a slicer on another column it is the East rows with g = x: 1.5 + 1 = 2.5
    out = world.value("[East] * 2", measures=REFS, filter_context=('s[g] = "x"',))
    same(out, D(5))


def test_slicer_applies_to_every_total(world: World) -> None:
    # g = x: rows 1, 3, 5, 7, 9, 11: q = 10 + 30 + 5 + 7 + 9 + 2 = 63, 6 rows
    same(world.value("SUM(s[q]) / COUNTROWS(s)", filter_context=('s[g] = "x"',)), D("10.5"))
    same(world.value("SUM(s[q]) - COUNTROWS(s)", filter_context=('s[g] = "x"',)), D(57))
    # rows removed by a slicer: both totals blank
    same(world.value("SUM(s[q]) + 1", filter_context=('s[g] = "zzz"',)), D(1))


def test_slicer_on_the_column_of_an_own_filter_is_refused(world: World) -> None:
    out = world.plan('CALCULATE(SUM(s[q]), s[g] = "y") + 1', filter_context=('s[g] = "x"',))
    assert isinstance(out, Refusal) and dax_whitelist.REASON_SLICER_SAME_COLUMN in out.reason


def test_own_filter_inside_a_referenced_measure_counts_for_the_same_column_rule(world: World) -> None:
    out = world.plan("[Y] + 1", measures={"Y": 'CALCULATE(SUM(s[q]), s[g] = "y")'}, filter_context=('s[g] = "x"',))
    assert isinstance(out, Refusal) and dax_whitelist.REASON_SLICER_SAME_COLUMN in out.reason


# ---------------------------------------------------------------------------------------------------
# what is refused, by name
# ---------------------------------------------------------------------------------------------------
def balanced(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    middle = len(items) // 2
    return f"({balanced(items[:middle])} + {balanced(items[middle:])})"


REFUSALS: list[tuple[str, str]] = [
    ("SUM(s[q]) ^ 2", dax_whitelist.REASON_ARITHMETIC),
    ("+SUM(s[q])", dax_whitelist.REASON_ARITHMETIC),
    ("MAX(s[d]) - MIN(s[d])", dax_whitelist.REASON_ARITH_DATE),
    ("MIN(s[d]) + 1", dax_whitelist.REASON_ARITH_DATE),
    ("SUM(s[q]) + 9223372036854775808", dax_whitelist.REASON_ARITH_LITERAL),
    ("SUM(s[q]) * 1e400", dax_whitelist.REASON_ARITH_LITERAL),
    ("DIVIDE(SUM(s[q]), 0, BLANK())", dax_whitelist.REASON_ARITH_DIVIDE_ALT),
    ("ROUND(SUM(s[a]), 1) + 1", "function ROUND is not on the store whitelist"),
    ("SUM(s[q]) + SUMX(s, s[q])", "function SUMX is not on the store whitelist"),
    ("SUM(s[q]) + SUM(s[r])", "SUM not supported on text column"),
    ("1 + 2", dax_whitelist.REASON_NO_TABLES),
    ('CALCULATE(SUM(s[q]) + 1, s[g] = "x")', dax_whitelist.REASON_ARITHMETIC),
    (balanced([f"CALCULATE(SUM(s[q]), s[n] > {n})" for n in range(9)]), dax_whitelist.REASON_ARITH_CAP_LEAVES),
    ("+".join(["1"] * 9) + " + SUM(s[q])", dax_whitelist.REASON_ARITH_CAP_DEPTH),
    (balanced(["1"] * 13) + " + SUM(s[q])", dax_whitelist.REASON_ARITH_CAP_NODES),
]


@pytest.mark.parametrize("expression,reason", REFUSALS, ids=[e[:60] for e, _ in REFUSALS])
def test_refused_with_a_named_reason_at_plan_time(world: World, expression: str, reason: str) -> None:
    # the planner builds no query (the route test runs the same expressions with a spy reader that records any call)
    out = world.plan(expression)
    assert isinstance(out, Refusal) and reason in out.reason, (expression, out)


def test_every_new_reason_has_a_sentence_in_the_route() -> None:
    for name in dir(dax_whitelist):
        if name.startswith("REASON_ARITH_"):
            text = getattr(dax_whitelist, name)
            assert dax_route.reason_is_mapped(text), name
            sentence = dax_route.message_for_reason("M", text)
            assert sentence.endswith(".") and " - " not in sentence, (name, sentence)


def test_calculate_over_an_arithmetic_measure_is_refused(world: World) -> None:
    out = world.plan('CALCULATE([Half], s[g] = "x") + 1', measures=REFS)
    assert isinstance(out, Refusal) and dax_arith.REASON_ARITH_IN_CALCULATE in out.reason
    out = world.plan('CALCULATE([Half], s[g] = "x")', measures=REFS)
    assert isinstance(out, Refusal) and dax_arith.REASON_ARITH_IN_CALCULATE in out.reason


def test_unknown_names_and_cycles_keep_their_reasons(world: World) -> None:
    out = world.plan("[Nope] + 1", measures=REFS)
    assert isinstance(out, Refusal) and "unknown column or measure 'Nope'" in out.reason
    out = world.plan("[P] + 1", measures={"P": "[Q] * 2", "Q": "[P] - 1"})
    assert isinstance(out, Refusal) and "cycle detected in measure reference" in out.reason


def test_parquet_source_refuses_arithmetic_with_the_plan_reason(world: World) -> None:
    out = world.plan("SUM(s[q]) + 1", source_kind="parquet")
    assert isinstance(out, Refusal) and out.reason == dax_sql.PARQUET_PLAN_REASON


def test_a_text_total_leaf_in_the_arithmetic_refuses_with_the_leaf_reason(world: World) -> None:
    out = world.plan("COUNTA(s[r]) + DISTINCTCOUNT(s[q])")
    assert isinstance(out, Refusal) and dax_whitelist.REASON_DISTINCTCOUNT_NUMERIC in out.reason


# ---------------------------------------------------------------------------------------------------
# execute: guards, stale plans, the 64 bit range
# ---------------------------------------------------------------------------------------------------
def test_each_total_runs_its_own_guards_decimal_scale(fresh: World) -> None:
    plan = fresh.plan("COUNTROWS(s) + SUM(s[a])")
    assert isinstance(plan, ArithPlan)
    same(plan.execute(fresh.store), D("31.75"))
    fresh.store.append_rows("s_csv", [["13", "1", "1.123456789", "East", "x", "2024-01-09"]])
    out = plan.execute(fresh.store)
    assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_PLAN_STALE, out


def test_each_total_runs_its_own_guards_date_cells(fresh: World) -> None:
    plan = fresh.plan("CALCULATE(SUM(s[q]), s[d] >= DATE(2024, 1, 2)) + 1")
    assert isinstance(plan, ArithPlan)
    assert not isinstance(plan.execute(fresh.store), Refusal)
    fresh.store.append_rows("s_csv", [["13", "1", "1.5", "East", "x", "20260105"]])
    out = plan.execute(fresh.store)
    assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_DATE_UNREADABLE, out


def test_a_dropped_table_is_a_stale_plan_not_an_error(fresh: World) -> None:
    plan = fresh.plan("SUM(s[a]) + COUNTROWS(s)")  # a decimal total has the stamp guard that notices the missing table
    assert isinstance(plan, ArithPlan)
    fresh.store.drop_table("s_csv")
    out = plan.execute(fresh.store)
    assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_PLAN_STALE, out


class RecordingLeaf:
    """A leaf plan that answers with a fixed value or Refusal and records its name when it runs."""

    def __init__(self, answer: Any, ran: list[str], name: str) -> None:
        self.answer, self.ran, self.name, self.num_kind = answer, ran, name, "double"

    def execute(self, store: Any) -> Any:
        self.ran.append(self.name)
        return self.answer


def test_the_first_refusal_wins_and_later_totals_do_not_run(world: World) -> None:
    plan = world.plan("SUM(s[q]) + COUNTROWS(s)")
    assert isinstance(plan, ArithPlan)
    ran: list[str] = []
    first, second = Refusal("the first total said no"), Refusal("the second total said no")
    broken = dataclasses.replace(
        plan, leaf_plans=(RecordingLeaf(first, ran, "first"), RecordingLeaf(second, ran, "second")),
    )
    assert broken.execute(world.store) is first  # the first Refusal is the answer
    assert ran == ["first"]  # the second total never runs


class StubPlan:
    """A leaf plan that returns a fixed value (to reach values a small table cannot hold)."""

    def __init__(self, value: Any, kind: str) -> None:
        self.value, self.num_kind = value, kind

    def execute(self, store: Any) -> Any:
        return self.value


def test_a_whole_number_total_beyond_64_bit_is_refused(world: World) -> None:
    plan = world.plan("SUM(s[q]) + COUNTROWS(s)")
    assert isinstance(plan, ArithPlan)
    for value in (D(2**63), D(-(2**63) - 1), D(2**70)):
        stub = dataclasses.replace(plan, leaf_plans=(StubPlan(value, "int"), plan.leaf_plans[1]))
        out = stub.execute(world.store)
        assert isinstance(out, Refusal) and out.reason == dax_arith.REASON_ARITH_WHOLE_BEYOND_64, value
    inside = dataclasses.replace(plan, leaf_plans=(StubPlan(D(2**63 - 1), "int"), plan.leaf_plans[1]))
    assert inside.execute(world.store) == D(2**63 - 1 + 12 - 2**64)  # wraps
    inside = dataclasses.replace(plan, leaf_plans=(StubPlan(D(-(2**63)), "int"), plan.leaf_plans[1]))
    assert inside.execute(world.store) == D(-(2**63) + 12)
    # a Double total has no such limit
    dbl = dataclasses.replace(plan, leaf_plans=(StubPlan(D(2**70), "double"), plan.leaf_plans[1]))
    assert dbl.execute(world.store) == D(2**70)  # the double sum: 12 is below one unit of 2**70


def test_divide_of_a_number_that_is_not_finite_is_refused_at_execute(world: World) -> None:
    out = world.value("DIVIDE(SUM(s[q]) / 0, 2)")
    assert isinstance(out, Refusal) and out.reason == dax_arith.REASON_ARITH_DIVIDE_NON_FINITE


def test_leaf_kinds_follow_the_engine(world: World) -> None:
    kinds = {
        "SUM(s[q])": "int", "MIN(s[q])": "int", "MAX(s[q])": "int", "COUNT(s[a])": "int", "COUNTA(s[r])": "int",
        "COUNTBLANK(s[a])": "int", "COUNTROWS(s)": "int", "DISTINCTCOUNT(s[r])": "int",
        "SUM(s[a])": "double", "MIN(s[a])": "double", "MAX(s[a])": "double", "AVERAGE(s[q])": "double",
        "AVERAGE(s[a])": "double",
    }
    for expression, kind in kinds.items():
        plan = world.plan(f"{expression} + 1")
        assert isinstance(plan, ArithPlan), expression
        assert plan.leaf_plans[0].num_kind == kind, (expression, plan.leaf_plans[0].num_kind)


def test_leaves_with_the_same_text_run_once(world: World) -> None:
    plan = world.plan("SUM(s[q]) * SUM(s[q]) - SUM(s[q])")
    assert isinstance(plan, ArithPlan) and len(plan.leaf_plans) == 1
    same(plan.execute(world.store), D(8010))
    plan = world.plan('CALCULATE(SUM(s[q]), s[g] = "x") + SUM(s[q])')
    assert isinstance(plan, ArithPlan) and len(plan.leaf_plans) == 2  # the same total with another filter is another leaf


def test_the_plan_types(world: World) -> None:
    assert isinstance(world.plan("SUM(s[q])"), MeasurePlan) and not world.plan("SUM(s[q])").grouped
    assert not world.plan("SUM(s[q]) + 1").grouped
    assert isinstance(world.group_plan("SUM(s[q])", "r"), GroupByPlan) and world.group_plan("SUM(s[q])", "r").grouped
    assert world.group_plan("SUM(s[q]) + 1", "r").grouped


# ---------------------------------------------------------------------------------------------------
# grouped
# ---------------------------------------------------------------------------------------------------
GROUPED: list[tuple[str, str, list[tuple[str, Decimal | None]]]] = [
    ("SUM(s[q]) - COUNTROWS(s) * 2", "r", [("East", D(30)), ("West", D(27)), ("North", D(9))]),
    ("DIVIDE(SUM(s[a]), COUNTROWS(s))", "r", [("East", D("1.25")), ("West", D("1.6875")), ("North", D(2))]),
    ("SUM(s[a]) / COUNTROWS(s)", "r", [("East", D("1.25")), ("West", D("1.6875")), ("North", D(2))]),
    ("-SUM(s[q])", "r", [("East", D(-38)), ("West", D(-35)), ("North", D(-17))]),
    ("SUM(s[q]) + SUM(s[q])", "g", [("x", D(126)), ("y", D(54))]),  # x: 63, y: 27
    ("SUM(s[q]) / 0", "g", [("x", D("Infinity")), ("y", D("Infinity"))]),
    ("SUM(s[q]) - SUM(s[q])", "r", [("East", D(0)), ("West", D(0)), ("North", D(0))]),
    # every group has a row for the own filter: x rows of East 1, 7 (a 2.5), West 3, 11 (0.75), North 5, 9 (3.5)
    ('DIVIDE(CALCULATE(SUM(s[a]), s[g] = "x"), SUM(s[a]))', "r",
     [("East", D("0.5")), ("West", D("0.1111111111111111111111111111")), ("North", D("0.4375"))]),
    # no group has a row for the own filter: every group is blank + 5 = 5, and DIVIDE of a blank is blank
    ('CALCULATE(SUM(s[a]), s[g] = "zzz") + 5', "r", [("East", D(5)), ("West", D(5)), ("North", D(5))]),
    ('DIVIDE(CALCULATE(SUM(s[a]), s[g] = "zzz"), SUM(s[a]))', "r", [("East", None), ("West", None), ("North", None)]),
    # only West has the row n = 3: the other groups have no row for the own filter
    ("CALCULATE(SUM(s[q]), s[n] = 3) + 1", "r", [("East", D(1)), ("West", D(31)), ("North", D(1))]),
    ("CALCULATE(SUM(s[q]), s[n] = 3) * 2", "r", [("East", None), ("West", D(60)), ("North", None)]),
    ("SUM(s[q]) - CALCULATE(SUM(s[q]), s[n] = 3)", "r", [("East", D(38)), ("West", D(5)), ("North", D(17))]),
    ("DIVIDE(CALCULATE(SUM(s[q]), s[n] = 3), 4, 9)", "r", [("East", None), ("West", D("7.5")), ("North", None)]),
    # 6 rows: 6 * 2**61 = 3 * 2**62 wraps to -2**62; 4 rows: 4 * 2**62 = 2**64 wraps to 0
    ("COUNTROWS(s) * 2305843009213693952", "g", [("x", D(-(2**62))), ("y", D(-(2**62)))]),
    ("COUNTROWS(s) * 4611686018427387904", "r", [("East", D(0)), ("West", D(0)), ("North", D(0))]),
]


@pytest.mark.parametrize("expression,column,expected", GROUPED, ids=[f"{e[:50]} by {c}" for e, c, _ in GROUPED])
def test_grouped_values_and_order(world: World, expression: str, column: str, expected: list[Any]) -> None:
    rows = world.groups(expression, column)
    assert [key for key, _ in rows] == [key for key, _ in expected], rows
    for (key, value), (_, want) in zip(rows, expected):
        same(value, want)


def test_grouped_reference_measures_are_typed_like_the_scalar(world: World) -> None:
    rows = world.groups("[Rows] / 7 + [Qty] * 0", "r", measures=REFS)
    assert [key for key, _ in rows] == ["East", "West", "North"]
    # 4 rows each: 4 / 7 in 28 digits, no double conversion
    for _, value in rows:
        same(value, D("0.5714285714285714285714285714"))


def test_grouped_under_a_slicer_keeps_only_the_groups_that_remain(world: World) -> None:
    rows = world.groups("SUM(s[q]) * 2", "r", filter_context=("s[n] <= 3",))
    assert rows == [("East", D(60)), ("West", D(60))]
    # a slicer that leaves no row at all: the universe is empty too
    assert world.groups("SUM(s[q]) + 1", "r", filter_context=("s[n] > 100",)) == []


def test_grouped_keys_come_from_the_whole_group_column_not_from_the_totals(world: World) -> None:
    # the filtered total exists for West only, a plain total for every group: all three groups are listed
    rows = world.groups("CALCULATE(SUM(s[q]), s[n] = 3) + COUNTROWS(s)", "r")
    assert rows == [("East", D(4)), ("West", D(34)), ("North", D(4))]


def test_grouped_by_date_and_boolean_like_columns(world: World) -> None:
    rows = world.groups("COUNTROWS(s) * 2", "d")
    # dates ascending with the blank first, m/d/yyyy keys: 8 different dates and the blank row (n = 5)
    keys = [key for key, _ in rows]
    assert keys[0] == "" and keys[1] == "1/1/2024" and keys[-1] == "1/8/2024", keys
    assert dict(rows)["1/1/2024"] == D(4) and dict(rows)[""] == D(2)  # 2 rows on 1/1: n = 1, 4


def test_grouped_own_filter_on_the_group_column_is_refused(world: World) -> None:
    out = world.group_plan('DIVIDE(CALCULATE(SUM(s[a]), s[r] = "East"), SUM(s[a]))', "r")
    assert isinstance(out, Refusal) and dax_sql.REASON_GROUP_OWN_FILTER in out.reason


def test_grouped_numeric_column_and_other_table_keep_their_refusals(world: World) -> None:
    out = world.group_plan("SUM(s[q]) + 1", "q")
    assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_GROUP_BY_TYPE
    out = plan_group_by("SUM(s[q]) + 1", group_by=("other", "r"), **world.kwargs())
    assert isinstance(out, Refusal)


def test_grouped_total_with_a_key_the_group_list_lacks_is_stale(world: World) -> None:
    plan = world.group_plan("SUM(s[q]) + COUNTROWS(s)", "r")
    assert isinstance(plan, GroupedArithPlan)
    for rows in ([("East", D(1)), ("Mars", D(2))], [("East", D(1)), ("East", D(2))]):
        broken = dataclasses.replace(plan, leaf_plans=(StubGroup(rows, "int"), plan.leaf_plans[1]))
        out = broken.execute(world.store)
        assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_PLAN_STALE, rows


def test_grouped_universe_with_a_repeated_key_is_stale(world: World) -> None:
    plan = world.group_plan("SUM(s[q]) + COUNTROWS(s)", "r")
    broken = dataclasses.replace(plan, universe=StubGroup([("East", D(1)), ("East", D(1))], "int"))
    out = broken.execute(world.store)
    assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_PLAN_STALE


class StubGroup:
    def __init__(self, rows: Any, kind: str) -> None:
        self.rows, self.num_kind = rows, kind

    def execute(self, store: Any) -> Any:
        return self.rows


def test_grouped_refusals_of_a_total_come_back_unchanged(world: World) -> None:
    plan = world.group_plan("SUM(s[q]) + COUNTROWS(s)", "r")
    refusal = Refusal("a total said no")
    for broken in (
        dataclasses.replace(plan, universe=StubGroup(refusal, "int")),
        dataclasses.replace(plan, leaf_plans=(StubGroup(refusal, "int"), plan.leaf_plans[1])),
        dataclasses.replace(plan, leaf_plans=(plan.leaf_plans[0], StubGroup(refusal, "int"))),
    ):
        assert broken.execute(world.store) is refusal


def test_grouped_whole_total_beyond_64_bit_is_refused(world: World) -> None:
    plan = world.group_plan("SUM(s[q]) + COUNTROWS(s)", "r")
    huge = [("East", D(2**63)), ("West", D(1)), ("North", D(1))]
    out = dataclasses.replace(plan, leaf_plans=(StubGroup(huge, "int"), plan.leaf_plans[1])).execute(world.store)
    assert isinstance(out, Refusal) and out.reason == dax_arith.REASON_ARITH_WHOLE_BEYOND_64


def test_grouped_guard_refusals_from_the_group_column(fresh: World) -> None:
    plan = fresh.group_plan("SUM(s[q]) + 1", "r")
    fresh.store.append_rows("s_csv", [["13", "1", "1.5", "Ea st", "x", "2024-01-09"]])
    out = plan.execute(fresh.store)
    assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_GROUP_NON_ASCII_SPACE


def test_grouped_stale_decimal_scale(fresh: World) -> None:
    plan = fresh.group_plan("SUM(s[a]) / COUNTROWS(s)", "r")
    fresh.store.append_rows("s_csv", [["13", "1", "1.123456789", "East", "x", "2024-01-09"]])
    out = plan.execute(fresh.store)
    assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_PLAN_STALE


def test_a_date_value_is_never_an_arithmetic_leaf(world: World) -> None:
    out = world.plan("MAX(s[d]) + 1")
    assert isinstance(out, Refusal) and dax_arith.REASON_ARITH_DATE in out.reason
    today = dax_dates.from_datetime(dt.datetime(2024, 1, 1))
    assert today is not None  # (a DaxDateTime is never combined: the whitelist refuses before)


# ---------------------------------------------------------------------------------------------------
# C4b fix 1: minus zeros, the table version between two statements, underflow, overflow, grouped signs
# ---------------------------------------------------------------------------------------------------
MINUS_ZERO_CSV = "n,w,d\n1,-0,-0.00\n2,-0,-0.00\n3,-0,-0.00\n"  # three rows whose MIN and MAX are minus zeros
MINUS_ZERO_TYPES = {"n": "whole_number", "w": "whole_number", "d": "decimal_number"}


@pytest.fixture()
def minus_zero(tmp_path: Path) -> Any:
    path = tmp_path / "z.csv"
    path.write_text(MINUS_ZERO_CSV, encoding="utf-8")
    store = DuckStore(str(tmp_path / "z.db"))
    import_csv_to_store(store, "z_csv", path, {})
    meta = {("z", c): m for c, m in column_decimal_meta(store, "z_csv", list(MINUS_ZERO_TYPES)).items()}
    yield store, dict(home_table="z", tables={"z": MINUS_ZERO_TYPES}, store_tables={"z": "z_csv"}, column_meta=meta)
    store.close()


@pytest.mark.parametrize("expression", [
    "COUNTROWS(z) / MIN(z[w])", "COUNTROWS(z) / MAX(z[w])", "COUNTROWS(z) / MIN(z[d])", "COUNTROWS(z) / MAX(z[d])",
    "DIVIDE(COUNTROWS(z), MIN(z[d]))", "-1 / (MIN(z[w]) * 1)", "1 / (MIN(z[d]) + 0)",
])
def test_division_by_min_or_max_of_a_column_is_refused_by_name(minus_zero: Any, expression: str) -> None:
    store, kwargs = minus_zero
    out = plan_measure(expression, **kwargs)
    assert isinstance(out, Refusal) and out.reason == dax_arith.REASON_ARITH_SIGNED_ZERO_DIVISOR, (expression, out)


def test_division_by_sum_and_by_a_literal_zero_still_plan_and_give_the_engine_value(minus_zero: Any) -> None:
    # hand values on 3 rows: COUNTROWS = 3; SUM of the minus zeros is +0; a literal 0 is +0
    store, kwargs = minus_zero
    for expression in ("COUNTROWS(z) / SUM(z[w])", "COUNTROWS(z) / SUM(z[d])", "COUNTROWS(z) / 0"):
        plan = plan_measure(expression, **kwargs)
        assert isinstance(plan, ArithPlan), (expression, plan)
        same(plan.execute(store), D("Infinity"))
    same(plan_measure("DIVIDE(COUNTROWS(z), 0)", **kwargs).execute(store), None)  # no alternate: blank
    same(plan_measure("DIVIDE(COUNTROWS(z), 0, 7)", **kwargs).execute(store), D(7))
    # a minus zero that is not a divisor shows as 0
    same(plan_measure("MIN(z[w]) - 0", **kwargs).execute(store), D(0))


# -- a table that changes between two statements of one arithmetic measure ------------------------
def _append_row(world: World) -> Any:
    def append() -> None:
        world.store.append_rows("s_csv", [["13", "1", "1.123456789", "East", "x", "2024-01-09"]])
    return append


def test_a_change_between_two_leaf_queries_is_stale_not_a_mixed_value(fresh: World, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = fresh.plan("SUM(s[q]) / COUNTROWS(s)")
    assert isinstance(plan, ArithPlan)
    monkeypatch.setattr(dax_sql, "ARITH_BETWEEN_LEAF_QUERIES", _append_row(fresh))
    out = plan.execute(fresh.store)
    assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_PLAN_STALE, out  # never 90/12 or 91/13 mixed
    monkeypatch.setattr(dax_sql, "ARITH_BETWEEN_LEAF_QUERIES", None)
    same(plan.execute(fresh.store), D(7))  # the plan runs again on the table as it is now: 91 / 13


def test_a_change_between_two_grouped_queries_is_stale(fresh: World, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = fresh.group_plan("SUM(s[q]) / COUNTROWS(s)", "r")
    assert isinstance(plan, GroupedArithPlan)
    monkeypatch.setattr(dax_sql, "ARITH_BETWEEN_LEAF_QUERIES", _append_row(fresh))
    out = plan.execute(fresh.store)
    assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_PLAN_STALE, out


def test_the_seam_is_inert_by_default(fresh: World) -> None:
    assert dax_sql.ARITH_BETWEEN_LEAF_QUERIES is None
    plan = fresh.plan("SUM(s[q]) / COUNTROWS(s)")
    same(plan.execute(fresh.store), D(90) / D(12))


# -- the exact Decimal path of a measure reference: underflow, overflow, DIVIDE overflow ----------
def test_a_measure_reference_product_that_underflows_is_zero(world: World) -> None:
    same(world.value("[B] * 1E-200 * 1E-200", measures={"B": "SUM(s[a])"}), D(0))  # 19.75 * 1e-400


def test_a_measure_reference_product_that_overflows_is_infinity(world: World) -> None:
    same(world.value("[B] * 1E300 * 1E300", measures={"B": "SUM(s[a])"}), D("Infinity"))  # 19.75 * 1e600


def test_divide_whose_quotient_overflows_is_infinity(world: World) -> None:
    same(world.value("DIVIDE(COUNTROWS(s) * 1E300, 1E-100)"), D("Infinity"))  # 12e300 / 1e-100


def test_grouped_values_go_through_bare_result(world: World) -> None:
    # -(SUM * 0) is a minus zero inside the engine; a group shows 0 (unsigned), never -0
    rows = dict(world.groups("-(SUM(s[a]) * 0)", "r"))
    assert sorted(rows) == ["East", "North", "West"], rows
    for value in rows.values():
        same(value, D(0))
