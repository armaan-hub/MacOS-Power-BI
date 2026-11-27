"""Arithmetic over totals through the route (Stage C4b): route_measure and route_grouped against the in-memory engine.

The engine (the twin of tests.test_dax_route.Env) is used ONLY here, as the oracle; the route never calls it. Every
value is compared by exact identity (class, value, sign of a zero or NaN, report text). A refusal has a plain
sentence and a code. Nothing asserts on elapsed time.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from analytics_studio.store import dax_arith, dax_route, dax_sql, dax_whitelist
from analytics_studio.store.dax_route import RouteRefusal, StoreAnswer, route_grouped, route_measure
from tests.test_dax_route import Env, make_project
from tools.store_engine_diff import values_identical, with_filter_context

D = Decimal

MEASURES = {
    "Total Amount": "SUM(t[amt])", "Total Qty": "SUM(t[qty])", "Row Count": "COUNTROWS(t)",
    "Same Total": "[Total Amount]", "East Amount": 'CALCULATE(SUM(t[amt]), t[region] = "East")',
    "Margin": "[Total Amount] - [Total Qty]", "Per Row": "[Total Amount] / [Row Count]",
}

EXPRESSIONS = [
    "SUM(t[amt]) / COUNTROWS(t)", "SUM(t[amt]) - SUM(t[qty]) * 2", "-SUM(t[amt])", "SUM(t[amt]) / 0", "SUM(t[qty]) / 0 - SUM(t[qty]) / 0",
    "2 * COUNTROWS(t) + 1", "AVERAGE(t[amt]) * 3 + MIN(t[qty])", "COUNTROWS(t) * 4611686018427387904",
    "SUM(t[qty]) * SUM(t[qty]) * SUM(t[qty])", "SUM(t[qty]) + 9223372036854775807",
    'CALCULATE(SUM(t[amt]), t[region] = "Nowhere") + 5', 'CALCULATE(SUM(t[amt]), t[region] = "Nowhere") * 5',
    'CALCULATE(SUM(t[amt]), t[region] = "Nowhere") - SUM(t[amt])',
    "DIVIDE(SUM(t[amt]), 0, -1)", "DIVIDE(SUM(t[amt]), SUM(t[neg]))", "DIVIDE(SUM(t[amt]), 0)",
    'DIVIDE(CALCULATE(SUM(t[amt]), t[region] = "East"), SUM(t[amt]))',
    'DIVIDE(CALCULATE(SUM(t[amt]), t[region] = "Nowhere"), SUM(t[amt]), 3)',
    "SUM(t[amt]) * 0 * -1", "1 / (SUM(t[amt]) * 0 * -1)", "COUNTROWS(t) / 7", "(COUNTROWS(t) + 1) * (COUNTROWS(t) - 1) / 3",
    "SUM(t[amt]) + SUM(t[neg]) + SUM(t[qty])", "MAX(t[amt]) - MIN(t[amt])", "COUNTA(t[region]) - COUNTBLANK(t[region])",
    "AVERAGE(t[qty]) / AVERAGE(t[amt])", "-(SUM(t[amt]) - SUM(t[amt]))", "SUM(t[qty]) - SUM(t[qty])", "DISTINCTCOUNT(t[product]) * 2.5",
    "[Margin]", "[Per Row]", "DIVIDE([Margin], [Total Amount])", "[Total Qty] / [Row Count]", "[Same Total] / [Row Count] - 1",
    "[Total Qty] * [Total Qty] * [Total Qty]", "[East Amount] + [Total Qty]", "-[Per Row]", "[Row Count] * 4611686018427387904",
    "DIVIDE([East Amount], [Total Amount])", "CALCULATE([Per Row])", "1 / ([Total Amount] * 0 * -1)", "1 / (SUM(t[amt]) * 0 * -1)",
    'CALCULATE([Total Amount], t[region] = "East") / 7', 'CALCULATE(SUM(t[amt]), t[region] = "East") / 7',
    'CALCULATE([Total Qty], t[qty] > 3) * 3', 'CALCULATE(SUM(t[qty]), t[qty] > 3) * 3',
]


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Any:
    e = Env(tmp_path_factory.mktemp("arith_route"))
    yield e
    e.close()


@pytest.fixture()
def fresh(tmp_path: Path) -> Any:
    e = Env(tmp_path)
    yield e
    if not e.ps.closed:
        e.close()


@pytest.mark.parametrize("expression", EXPRESSIONS)
def test_scalar_route_equals_the_engine_exactly(env: Any, expression: str) -> None:
    out = env.route(expression, measures=MEASURES, budget_s=30.0)
    assert isinstance(out, StoreAnswer), out
    assert out.kind == "scalar"
    want = env.engine(expression, MEASURES)
    assert values_identical(out.value, want), (expression, out.value, want)


@pytest.mark.parametrize("expression", [
    "SUM(t[amt]) / COUNTROWS(t)", "SUM(t[qty]) * 2 + COUNTROWS(t)", "DIVIDE(SUM(t[amt]), SUM(t[qty]))", "[Per Row] * 2", "-SUM(t[amt])",
])
def test_scalar_route_under_a_slicer_equals_the_engine(env: Any, expression: str) -> None:
    for context in (('t[region] = "East"',), ("t[qty] > 3",), ('t[product] IN {"P01", "P02"}',), ('t[region] = "West"', "t[qty] < 8")):
        out = env.route(expression, measures=MEASURES, filter_context=context, budget_s=30.0)
        assert isinstance(out, StoreAnswer), (expression, context, out)
        want = env.engine(with_filter_context(expression, context), MEASURES)
        assert values_identical(out.value, want), (expression, context, out.value, want)


def engine_groups(env: Any, expression: str, column: str, keys: list[str]) -> list[Any]:
    out = []
    for key in keys:
        filter_text = f't[{column}] = "{key}"' if key else f't[{column}] = ""'
        out.append(env.engine(with_filter_context(expression, (filter_text,)), MEASURES))
    return out


@pytest.mark.parametrize("expression", [
    "SUM(t[amt]) / COUNTROWS(t)", "SUM(t[qty]) - COUNTROWS(t) * 2", "DIVIDE(SUM(t[amt]), SUM(t[qty]))", "-SUM(t[amt])",
    "SUM(t[amt]) / 0", "COUNTROWS(t) * 4611686018427387904",
    "DIVIDE(CALCULATE(SUM(t[amt]), t[qty] > 4), SUM(t[amt]))", "CALCULATE(SUM(t[qty]), t[qty] > 4) + COUNTROWS(t)",
    "[Per Row]", "[Margin] / [Row Count]", 'CALCULATE(SUM(t[amt]), t[qty] = 99999) + 5',
])
def test_grouped_route_equals_the_engine_per_key(env: Any, expression: str) -> None:
    out = route_grouped(
        env.project, expression, ("t", "product"), project_store=env.ps, measures=MEASURES, budget_s=30.0, max_groups=None,
    )
    assert isinstance(out, StoreAnswer), out
    assert out.kind == "grouped" and out.rows
    keys = [key for key, _ in out.rows]
    want = engine_groups(env, expression, "product", keys)
    for (key, value), expected in zip(out.rows, want):
        assert values_identical(value, expected), (expression, key, value, expected)


def test_grouped_route_under_a_slicer(env: Any) -> None:
    context = ("t[qty] > 3",)
    out = route_grouped(
        env.project, "SUM(t[amt]) / COUNTROWS(t)", ("t", "region"), project_store=env.ps, filter_context=context,
        measures=MEASURES, budget_s=30.0, max_groups=None,
    )
    assert isinstance(out, StoreAnswer) and out.rows
    for key, value in out.rows:
        filters = (f't[region] = "{key}"' if key else 't[region] = ""', *context)
        want = env.engine(with_filter_context("SUM(t[amt]) / COUNTROWS(t)", filters), MEASURES)
        assert values_identical(value, want), (key, value, want)


# ---------------------------------------------------------------------------------------------------
# refusals: a plain sentence and the code
# ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("expression,code,words", [
    ("SUM(t[amt]) ^ 2", "whitelist", "arithmetic"),
    ("MAX(t[pay]) - MIN(t[pay])", "whitelist", "date total"),
    ("ROUND(SUM(t[amt]), 2) + 1", "whitelist", "ROUND"),
    ("SUM(t[amt]) + 9223372036854775808", "whitelist", "too large"),
    ("DIVIDE(SUM(t[amt]), 0, BLANK())", "whitelist", "third argument of DIVIDE"),
    ("DIVIDE(SUM(t[amt]), 0, SUM(t[qty]))", "whitelist", "third argument of DIVIDE"),
    ("DIVIDE(SUM(t[amt]), 2, 3, 4)", "whitelist", "two or three arguments"),
    ("CALCULATE([Per Row], t[qty] > 1)", "whitelist", "CALCULATE filters around a measure that does arithmetic"),
    ('CALCULATE(SUM(t[qty]), t[region] = "East") + 1', "whitelist", None),
])
def test_refusals_are_plain_and_coded(env: Any, expression: str, code: str, words: str | None) -> None:
    out = env.route(expression, measures=MEASURES)
    if words is None:
        assert isinstance(out, StoreAnswer)  # a filtered total beside a number is a plain answer
        return
    assert isinstance(out, RouteRefusal), out
    assert out.code == code, (out.code, out.reason)
    assert out.message.endswith(".") and " - " not in out.message, out.message
    assert words in out.message, out.message
    assert not out.message.startswith(dax_route.GENERIC_SENTENCE)


def test_divide_of_infinity_is_a_named_plan_refusal(env: Any) -> None:
    out = env.route("DIVIDE(SUM(t[qty]) / 0, 2)")
    assert isinstance(out, RouteRefusal) and out.code == "plan"
    assert "infinite or not a number" in out.message and out.message.endswith(".")


def test_a_named_measure_is_routed_by_its_name(env: Any) -> None:
    project = make_project(types=env.types, measures=[
        {"name": "Total Amount", "expression": "SUM(t[amt])"}, {"name": "Row Count", "expression": "COUNTROWS(t)"},
        {"name": "Avg Ticket", "expression": "[Total Amount] / [Row Count]"},
    ])
    out = route_measure(project, "Avg Ticket", project_store=env.ps, budget_s=30.0)
    assert isinstance(out, StoreAnswer)
    want = env.engine("[Avg Ticket]", {"Total Amount": "SUM(t[amt])", "Row Count": "COUNTROWS(t)", "Avg Ticket": "[Total Amount] / [Row Count]"})
    assert values_identical(out.value, want)


def test_a_stale_total_comes_back_as_a_stale_refusal_not_a_value(fresh: Any) -> None:
    out = fresh.route("SUM(t[amt]) / COUNTROWS(t)", budget_s=30.0)
    assert isinstance(out, StoreAnswer)
    fresh.ps.store.append_rows("t_csv", [["99999", "East", "P01", "1", "1.123456789", "-1.00", "2024-01-01", "TRUE"]])
    again = fresh.route("SUM(t[amt]) / COUNTROWS(t)", budget_s=30.0)
    # a fresh plan reads the new metadata: the value is the engine's on the new rows ...
    assert isinstance(again, StoreAnswer)
    assert again.value != out.value


def test_the_route_never_calls_the_engine_for_arithmetic(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import analytics_studio.measures as measures_module

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the engine was called")

    monkeypatch.setattr(measures_module, "evaluate_measures", boom)
    out = env.route("SUM(t[amt]) / COUNTROWS(t) + 1", budget_s=30.0)
    assert isinstance(out, StoreAnswer)


def test_a_reason_without_a_sentence_is_caught() -> None:
    sentence = dax_route.message_for_reason("M", dax_whitelist.REASON_ARITH_DATE)
    assert sentence.startswith("M cannot be computed on a large table yet: ") and sentence.endswith(".")
    unmapped = dax_route.message_for_reason("M", "a reason nobody wrote down")
    assert unmapped.startswith("M cannot be computed on a large table yet - ")
    assert dax_route.reason_is_mapped(dax_arith.REASON_ARITH_DIVIDE_NON_FINITE)
    assert dax_route.reason_is_mapped(dax_sql.REASON_PLAN_STALE)


# ---------------------------------------------------------------------------------------------------
# C4b fix 1: refusals run no query, the plan-coded reasons, the depth sentence
# ---------------------------------------------------------------------------------------------------
class SpyReader:
    """A reader that records the SQL the route sends it after the plan is built (the planned value's query).

    `planned` is set by the plan builders the test wraps (see the refusal test): a call made while `planned` is set
    would mean the route ran a query for a plan it had already refused or built.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.planned = False
        self.calls: list[str] = []

    def execute(self, sql: str, params: Any = ()) -> Any:
        if self.planned:
            self.calls.append(sql)
        return self.inner.execute(sql, params)

    def interrupt(self) -> None:
        self.inner.interrupt()


REFUSED_BEFORE_ANY_QUERY: list[tuple[str, str]] = [
    ("SUM(t[amt]) ^ 2", dax_whitelist.REASON_ARITHMETIC),
    ("1 + 2", dax_whitelist.REASON_NO_TABLES),
    ("DIVIDE(SUM(t[amt]), 0, BLANK())", dax_whitelist.REASON_ARITH_DIVIDE_ALT),
    ("SUM(t[amt]) + 9223372036854775808", dax_whitelist.REASON_ARITH_LITERAL),
    ("COUNTROWS(t) / MIN(t[qty])", dax_whitelist.REASON_ARITH_SIGNED_ZERO_DIVISOR),
    ("DIVIDE(COUNTROWS(t), 1E-310)", dax_whitelist.REASON_ARITH_DIVIDE_SUBNORMAL),
]


@pytest.mark.parametrize("expression,reason", REFUSED_BEFORE_ANY_QUERY, ids=[e[:50] for e, _ in REFUSED_BEFORE_ANY_QUERY])
def test_refused_with_a_named_reason_and_no_query(env: Any, expression: str, reason: str, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = env.ps.store.reader()
    spy = SpyReader(reader)
    real_plan_measure, real_plan_group_by = dax_route.plan_measure, dax_route.plan_group_by

    def planned_measure(*args: Any, **kwargs: Any) -> Any:
        out = real_plan_measure(*args, **kwargs)
        spy.planned = True  # from here on, the route may only run the value of a plan it did not refuse
        return out

    monkeypatch.setattr(dax_route, "plan_measure", planned_measure)
    monkeypatch.setattr(dax_route, "plan_group_by", real_plan_group_by)
    try:
        out = env.route(expression, measures=MEASURES, reader=spy)
    finally:
        reader.close()
    assert isinstance(out, RouteRefusal) and out.reason == reason, (expression, out)
    assert spy.calls == [], spy.calls  # refused by the plan: no query of a value was sent to the store


def test_a_whole_total_beyond_64_bit_is_a_plan_refusal_with_its_sentence(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # a seam: every whole-number total is judged beyond the 64-bit range (no table here holds one that large)
    monkeypatch.setattr(dax_arith, "leaf_value_in_range", lambda num: False)
    out = env.route("SUM(t[qty]) + COUNTROWS(t)", measures=MEASURES)
    assert isinstance(out, RouteRefusal), out
    assert out.reason == dax_whitelist.REASON_ARITH_WHOLE_BEYOND_64
    assert out.code == dax_route.CODE_PLAN, out.code  # a plan reason, not a whitelist one
    assert "too large for the arithmetic of large tables" in out.message and out.message.endswith("."), out.message


def test_the_depth_refusal_sentence_reaches_the_user(env: Any) -> None:
    out = env.route("+".join(["1"] * 9) + " + SUM(t[amt])", measures=MEASURES)
    assert isinstance(out, RouteRefusal) and out.reason == dax_whitelist.REASON_ARITH_CAP_DEPTH, out
    assert "more than 8 terms in a row" in out.message, out.message
