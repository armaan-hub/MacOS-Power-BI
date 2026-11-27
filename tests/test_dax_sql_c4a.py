"""Stage C4a: a grouped measure with its own CALCULATE filter on ANOTHER column, and the C1 guard findings F1 to F4.

Every expectation is the real engine (evaluate_measures) or a hand-worked value. Every test builds its own tables
under tmp_path (no shared module state), so the tests run in any order and on any xdist worker. The mutants of the
review (each rule switched off in the source) are named in HANDOFF.md with the test that fails by a value, a refusal
text or a count.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.measures import evaluate_measures, normalize_measure, parse_expression
from analytics_studio.store import DuckStore, import_csv_to_store
from analytics_studio.store import dax_route, dax_sql
from analytics_studio.store.base import StoreError
from analytics_studio.store.dax_sql import (
    REASON_DATE_BEFORE_1900,
    REASON_DATE_UNREADABLE,
    REASON_GROUP_OWN_FILTER,
    REASON_IN_NON_ASCII_COLUMN,
    REASON_PLAN_STALE,
    ColumnMeta,
    GroupByPlan,
    MeasurePlan,
    Refusal,
    column_decimal_meta,
    own_predicate_columns,
    plan_group_by,
    plan_measure,
)
from analytics_studio.store.dax_whitelist import REASON_SLICER_SAME_COLUMN
from tools.store_engine_diff import _engine_key_filter, _parse_engine_keys, with_filter_context


class Case:
    """A CSV table "t" loaded in the real engine and in a store (table "t_csv") with decimal metadata."""

    def __init__(self, base: Path, header: list[str], rows: list[list[str]]) -> None:
        csv_path = base / "t.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        self.header = header
        self.controller = StudioController()
        self.controller._effective_app_data_dir = lambda: str(base / "app")
        assert self.controller._commit_import(csv_path, parse_file(csv_path))
        self.context = self.controller._measure_table_context()
        self.table_id = self.controller._active_model_table_id()
        self.rows = self.controller._loaded_candidates[self.controller._active_source_id].rows
        self.headers = self.controller._headers
        self.types: dict[str, str] = self.controller._project["model"]["tables"][0]["column_types"]
        self.store = DuckStore(str(base / "t.db"))
        import_csv_to_store(self.store, "t_csv", csv_path, {})
        self.meta = {("t", c): m for c, m in column_decimal_meta(self.store, "t_csv", header).items()}

    def engine(self, expression: str, measures: dict[str, str] | None = None) -> Any:
        names = [*(measures or {}), "M"]
        bodies = [*(measures or {}).values(), expression]
        built = [normalize_measure(n, b, home_table_id=self.table_id) for n, b in zip(names, bodies)]
        return evaluate_measures(
            built, self.rows, self.headers, "t", measure_names=names, table_context=self.context,
            relationships=[], filter_table_ids=[], active_table_id=self.table_id,
        )["M"]

    def kw(self, **extra: Any) -> dict[str, Any]:
        return dict(home_table="t", tables={"t": self.types}, store_tables={"t": "t_csv"}, column_meta=self.meta, **extra)

    def plan(self, expression: str, **extra: Any) -> Any:
        return plan_measure(expression, **self.kw(**extra))

    def group(self, expression: str, group: str, **extra: Any) -> Any:
        return plan_group_by(expression, group_by=("t", group), **self.kw(**extra))

    def run_group(self, expression: str, group: str, **extra: Any) -> Any:
        plan = self.group(expression, group, **extra)
        return plan if isinstance(plan, Refusal) else plan.execute(self.store)

    def close(self) -> None:
        self.store.close()


def same(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b


# ---------------------------------------------------------------------------------------------------------
# Item 1: own CALCULATE filter on ANOTHER column
# ---------------------------------------------------------------------------------------------------------

OWN_HEADER = ["n", "d", "dt", "cat", "flag", "g"]
_CATS = ["A", "a", "B", "", "C", "b ", "D"]
_GS = ["x", "y", "", "z", "x"]
_DATES = ["2024-02-29", "", "2026-06-01", "2023-01-15", "2024-03-01"]


def own_rows() -> list[list[str]]:
    rows = []
    for i in range(1, 31):
        rows.append([
            "" if i % 11 == 0 else str(i % 9),
            "" if i % 7 == 0 else ["1.5", "2.25", "0", "10.5", "-3.125"][i % 5],
            _DATES[i % 5],
            _CATS[i % 7],
            ["TRUE", "FALSE", ""][i % 3],
            _GS[i % 5],
        ])
    return rows


@pytest.fixture
def case(tmp_path: Path) -> Any:
    made = Case(tmp_path, OWN_HEADER, own_rows())
    assert made.types["n"] == "whole_number" and made.types["d"] == "decimal_number", made.types
    assert made.types["dt"] == "date" and made.types["flag"] == "boolean", made.types
    yield made
    made.close()


def engine_pairs(case: Case, agg: str, own: tuple[str, ...], group: str, ctx: tuple[str, ...] = ()) -> list[tuple[str, Any]]:
    """What the engine shows per group key: a group with no row under the own filter has a blank value and is dropped."""
    g_type = case.types[group]
    keys_dax = f"VALUES(t[{group}])" if not ctx else f"CALCULATETABLE(VALUES(t[{group}]), {', '.join(ctx)})"
    keys_text = case.engine(f"TOCSV({keys_dax}, 100000)") or ""
    head, sep, rest = keys_text.partition("\n")
    counted = case.engine(with_filter_context("COUNTROWS(t)", ctx)) if (head and sep and rest == "") else None
    keys = _parse_engine_keys(keys_text, 0 if counted is None and head and sep and rest == "" else counted)
    dax = f"CALCULATE({agg}, {', '.join(own)})" if own else agg
    out: list[tuple[str, Any]] = []
    for key in keys:
        key_filter = _engine_key_filter(group, g_type, key)
        if own and not case.engine(with_filter_context("COUNTROWS(t)", (*own, key_filter, *ctx))):
            continue
        out.append((key, case.engine(with_filter_context(dax, (key_filter, *ctx)))))
    return out


OWN_COMBOS = [
    ("COUNTROWS(t)", ("t[n] > 3",), "cat"),
    ("SUM(t[n])", ("t[n] = 5",), "cat"),
    ("AVERAGE(t[d])", ("t[n] <> 0",), "g"),
    ("SUM(t[d])", ("t[d] >= 0",), "flag"),
    ("MIN(t[dt])", ("t[n] < 6",), "cat"),
    ("MAX(t[dt])", ("t[n] >= 1", "t[d] < 3"), "g"),
    ("COUNT(t[n])", ('t[cat] = "A"',), "g"),
    ("COUNTA(t[cat])", ("t[dt] >= DATE(2024,1,1)",), "flag"),
    ("DISTINCTCOUNT(t[cat])", ("t[dt] < DATE(2024,3,1)",), "g"),
    ("COUNTROWS(t)", ("t[dt] >= DATE(2024,1,1)",), "cat"),
    ("SUM(t[n])", ('t[cat] IN {"A", "B"}',), "dt"),
    ("COUNTROWS(t)", ("t[n] = 0 || t[n] = 1",), "dt"),
    ("COUNTROWS(t)", ("t[n] = 99",), "cat"),  # matches no row at all
    ("SUM(t[n])", ("t[n] = 8",), "g"),  # matches only some groups
]


@pytest.mark.parametrize("agg,own,group", OWN_COMBOS, ids=[f"{a}|{','.join(o)}|{g}" for a, o, g in OWN_COMBOS])
def test_own_filter_on_another_column_equals_the_engine_group_by_group(
    case: Case, agg: str, own: tuple[str, ...], group: str
) -> None:
    got = case.run_group(f"CALCULATE({agg}, {', '.join(own)})", group)
    assert isinstance(got, list), got
    want = engine_pairs(case, agg, own, group)
    assert [k for k, _ in got] == [k for k, _ in want], (got, want)
    for (key, value), (_, expected) in zip(got, want):
        assert same(value, expected), (key, value, expected)


def test_own_filter_hand_computed_values_and_dropped_groups(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "cat", "v"], [
        ["1", "A", "10"], ["2", "A", "20"], ["3", "B", "30"], ["4", "", "40"], ["5", "C", "50"], ["6", "", "60"],
    ])
    try:
        assert case.run_group("CALCULATE(SUM(t[v]), t[n] > 3)", "cat") == [
            ("", Decimal(100)), ("C", Decimal(50)),
        ]  # A and B have no row with n > 3: dropped; the blank key keeps its place and value
        assert case.run_group("CALCULATE(COUNTROWS(t), t[n] >= 2)", "cat") == [
            ("A", Decimal(1)), ("B", Decimal(1)), ("", Decimal(2)), ("C", Decimal(1)),
        ]
        assert case.run_group("CALCULATE(COUNTROWS(t), t[n] > 99)", "cat") == []
    finally:
        case.close()


def test_own_filter_on_the_group_column_is_refused_by_name(case: Case) -> None:
    for expression, group in (
        ('CALCULATE(COUNTROWS(t), t[cat] = "A")', "cat"),
        ('CALCULATE(COUNTROWS(t), t[cat] IN {"A", "B"})', "cat"),
        ("CALCULATE(COUNTROWS(t), t[dt] >= DATE(2024,1,1))", "dt"),
        ("CALCULATE(SUM(t[n]), t[n] > 1, t[g] = \"x\")", "g"),
        ("CALCULATE(SUM(t[n]), t[n] > 1, t[CAT] = \"A\")", "cat"),  # the column name is compared case-folded
    ):
        out = case.run_group(expression, group)
        assert isinstance(out, Refusal) and out.reason == REASON_GROUP_OWN_FILTER, (expression, out)
    ok = case.run_group('CALCULATE(COUNTROWS(t), t[cat] = "A")', "g")  # the same predicate, another group column
    assert isinstance(ok, list) and ok, ok


def test_own_filter_on_the_group_column_is_matched_by_column_name_case_folded(tmp_path: Path) -> None:
    """The group column is spelled Cat in the table and cat in the measure (and the other way round)."""
    case = Case(tmp_path, ["n", "Cat"], [["1", "A"], ["2", "B"], ["3", "A"]])
    try:
        for expression, group in (
            ('CALCULATE(SUM(t[n]), t[cat] = "A")', "Cat"),
            ('CALCULATE(SUM(t[n]), t[CAT] = "A")', "cat"),
        ):
            out = case.run_group(expression, group)
            assert isinstance(out, Refusal) and out.reason == REASON_GROUP_OWN_FILTER, (expression, group, out)
        ok = case.run_group('CALCULATE(COUNTROWS(t), t[n] > 1)', "Cat")
        assert ok == [("A", Decimal(1)), ("B", Decimal(1))], ok
    finally:
        case.close()


def test_own_filter_on_the_group_column_through_an_alias_chain_is_refused(case: Case) -> None:
    chain = {"A": 'CALCULATE(SUM(t[n]), t[cat] = "A")', "B": "[A]"}
    refused = case.run_group("[B]", "cat", measures=chain)
    assert isinstance(refused, Refusal) and refused.reason == REASON_GROUP_OWN_FILTER, refused
    allowed = case.run_group("[B]", "g", measures=chain)
    want = engine_pairs(case, "SUM(t[n])", ('t[cat] = "A"',), "g")
    assert isinstance(allowed, list) and [k for k, _ in allowed] == [k for k, _ in want]
    assert all(same(v, w) for (_, v), (_, w) in zip(allowed, want)), (allowed, want)


def test_own_predicate_columns_walks_not_or_and_in(case: Case) -> None:
    planner = dax_sql._Planner("t", {"t": case.types}, case.meta, {})
    nodes = [
        parse_expression("NOT(t[n] = 1)"),
        parse_expression('t[cat] = "A" || t[g] = "x"'),
        parse_expression('t[flag] IN {"TRUE"}'),
    ]
    found = own_predicate_columns(tuple(nodes), planner)
    assert sorted(set(found)) == [("t", "cat"), ("t", "flag"), ("t", "g"), ("t", "n")], found
    assert own_predicate_columns((), planner) == []


def test_own_filter_with_a_slicer_on_another_column_both_go_to_the_where(case: Case) -> None:
    got = case.run_group("CALCULATE(SUM(t[n]), t[n] > 1)", "cat", filter_context=("t[d] >= 0",))
    want = engine_pairs(case, "SUM(t[n])", ("t[n] > 1",), "cat", ctx=("t[d] >= 0",))
    assert isinstance(got, list) and got, got
    assert [k for k, _ in got] == [k for k, _ in want]
    assert all(same(v, w) for (_, v), (_, w) in zip(got, want)), (got, want)
    # each of the two filters changes the answer (so a plan that dropped either one would differ)
    own_only = case.run_group("CALCULATE(SUM(t[n]), t[n] > 1)", "cat")
    slicer_only = case.run_group("SUM(t[n])", "cat", filter_context=("t[d] >= 0",))
    assert got != own_only and got != slicer_only, (got, own_only, slicer_only)


def test_own_filter_with_a_slicer_on_the_same_column_is_refused_with_the_slicer_sentence(case: Case) -> None:
    out = case.run_group("CALCULATE(SUM(t[n]), t[n] > 1)", "cat", filter_context=("t[n] < 6",))
    assert isinstance(out, Refusal) and out.reason == REASON_SLICER_SAME_COLUMN, out


def test_alias_chain_with_an_own_filter_grouped_decides_like_the_scalar_path(case: Case) -> None:
    chain = {"A": "CALCULATE(SUM(t[n]), t[n] > 1)", "B": "[A]"}
    got = case.run_group("[B]", "cat", measures=chain)
    want = engine_pairs(case, "SUM(t[n])", ("t[n] > 1",), "cat")
    assert isinstance(got, list) and [k for k, _ in got] == [k for k, _ in want]
    assert all(same(v, w) for (_, v), (_, w) in zip(got, want)), (got, want)
    for ctx in (("t[n] < 6",),):
        scalar = case.plan("[B]", measures=chain, filter_context=ctx)
        grouped = case.run_group("[B]", "cat", measures=chain, filter_context=ctx)
        assert isinstance(scalar, Refusal) and isinstance(grouped, Refusal), (scalar, grouped)
        assert grouped.reason == scalar.reason == REASON_SLICER_SAME_COLUMN
    other = ("t[d] >= 0",)
    assert isinstance(case.plan("[B]", measures=chain, filter_context=other), MeasurePlan)
    assert isinstance(case.run_group("[B]", "cat", measures=chain, filter_context=other), list)


def test_guards_of_the_own_predicates_reach_the_group_plan_text_in(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "cat", "g"], [[str(i), c, "x"] for i, c in enumerate(["A", "a", "B", "b", "C", ""] * 3, 1)])
    try:
        plan = case.group('CALCULATE(COUNTROWS(t), t[cat] IN {"A", "B"})', "g")
        assert isinstance(plan, GroupByPlan) and plan.in_guards == (("t_csv", "cat"),), plan
        assert isinstance(plan.execute(case.store), list)
        case.store.append_rows("t_csv", [["99", "ß", "x"]])  # a non-ASCII cell in the IN column
        out = plan.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_IN_NON_ASCII_COLUMN, out
    finally:
        case.close()


def test_guards_of_the_own_predicates_reach_the_group_plan_date(tmp_path: Path) -> None:
    rows = [[str(i), d, "x" if i % 2 else "y"] for i, d in enumerate(["2024-01-05", "2025-03-04", "", "2023-02-01"] * 3, 1)]
    case = Case(tmp_path, ["n", "dd", "g"], rows)
    try:
        plan = case.group("CALCULATE(COUNTROWS(t), t[dd] >= DATE(2024,1,1))", "g")
        assert isinstance(plan, GroupByPlan) and plan.date_guards == (("t_csv", "dd"),), plan
        assert isinstance(plan.execute(case.store), list)
        case.store.append_rows("t_csv", [["99", "20260101", "x"]])  # compact text the store cannot read the engine's way
        out = plan.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_DATE_UNREADABLE, out
    finally:
        case.close()


def test_guards_of_the_own_predicates_reach_the_group_plan_decimal(tmp_path: Path) -> None:
    rows = [[str(i), ["1.5", "2.25", "10.5", "0"][i % 4], ["x", "y"][i % 2]] for i in range(1, 9)]
    case = Case(tmp_path, ["n", "d", "g"], rows)
    try:
        plan = case.group("CALCULATE(COUNTROWS(t), t[d] >= 2)", "g")
        assert isinstance(plan, GroupByPlan) and [s[:2] for s in plan.decimal_stamps] == [("t_csv", "d")], plan
        assert isinstance(plan.execute(case.store), list)
        case.store.append_rows("t_csv", [["99", "1.123456789", "x"]])  # a new scale: the plan is stale
        out = plan.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_PLAN_STALE, out
    finally:
        case.close()


def test_blank_group_key_is_kept_under_an_own_filter(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "g"], [["1", "x"], ["2", ""], ["3", ""], ["4", "x"], ["5", "y"]])
    try:
        out = case.run_group("CALCULATE(COUNTROWS(t), t[n] >= 2)", "g")
        assert out == [("x", Decimal(1)), ("", Decimal(2)), ("y", Decimal(1))], out
    finally:
        case.close()


def test_group_own_reasons_have_plain_sentences() -> None:
    sentence = dax_route.fragment_for_reason(REASON_GROUP_OWN_FILTER)
    assert sentence and "CALCULATE filter of its own" in sentence and "grouped by" in sentence
    old = dax_route.fragment_for_reason(REASON_DATE_BEFORE_1900)
    assert old and "1900" in old and "date" in old
    assert dax_route._code_for_reason(REASON_DATE_BEFORE_1900) == dax_route.CODE_PLAN


# ---------------------------------------------------------------------------------------------------------
# Item 2, F1: dates before 1900
# ---------------------------------------------------------------------------------------------------------

def old_rows(cells: list[str]) -> list[list[str]]:
    return [[str(i), c, "x" if i % 2 else "y"] for i, c in enumerate(cells, 1)]


@pytest.mark.parametrize("old_cell", ["1899-12-30", "0001-01-01", "0100-05-05", "1899-12-31"])
def test_a_date_column_with_a_cell_before_1900_is_refused_for_every_plan_kind(tmp_path: Path, old_cell: str) -> None:
    case = Case(tmp_path, ["n", "dd", "g"], old_rows(["2024-01-05", old_cell, "", "2025-03-04"] * 2))
    try:
        assert case.types["dd"] == "date", case.types
        for plan in (
            case.plan("MIN(t[dd])"),
            case.plan("COUNT(t[dd])"),
            case.plan("CALCULATE(COUNTROWS(t), t[dd] >= DATE(2024,1,1))"),
            case.group("COUNTROWS(t)", "dd"),
            case.group("MAX(t[dd])", "g"),
        ):
            assert not isinstance(plan, Refusal), plan
            out = plan.execute(case.store)
            assert isinstance(out, Refusal) and out.reason == REASON_DATE_BEFORE_1900, (plan.shape, out)
    finally:
        case.close()


def test_a_date_column_from_1900_on_still_equals_the_engine(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "dd", "g"], old_rows(["1900-01-01", "2024-01-05", "", "9999-12-31", "1900-01-02"] * 2))
    try:
        for expression in ("MIN(t[dd])", "MAX(t[dd])", "COUNT(t[dd])", "CALCULATE(COUNTROWS(t), t[dd] >= DATE(1900,1,2))"):
            plan = case.plan(expression)
            assert isinstance(plan, MeasurePlan)
            assert same(plan.execute(case.store), case.engine(expression)), expression
        got = case.run_group("COUNTROWS(t)", "dd")
        want = engine_pairs(case, "COUNTROWS(t)", (), "dd")
        assert got == want, (got, want)
    finally:
        case.close()


def test_the_date_guard_is_one_query_per_date_column(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "dd", "g"], old_rows(["2024-01-05", "", "2025-03-04"] * 2))
    try:
        plan = case.plan("MIN(t[dd])")
        calls: list[str] = []

        class Spy:
            def execute(self, sql: str, params: Any = ()) -> Any:
                calls.append(sql)
                return case.store.execute(sql, params)

        assert isinstance(plan, MeasurePlan) and isinstance(plan.execute(Spy()), dax_sql.dax_dates.DaxDateTime)
        assert len(calls) == 2, calls  # the one guard scan, then the aggregate
    finally:
        case.close()


def test_a_date_column_gaining_an_old_cell_later_is_refused_on_the_next_execute(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "dd", "g"], old_rows(["2024-01-05", "", "2025-03-04"] * 2))
    try:
        plan = case.plan("MIN(t[dd])")
        assert isinstance(plan, MeasurePlan) and not isinstance(plan.execute(case.store), Refusal)
        case.store.append_rows("t_csv", [["99", "1899-12-30", "x"]])
        out = plan.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_DATE_BEFORE_1900, out
    finally:
        case.close()


# ---------------------------------------------------------------------------------------------------------
# Item 2, F2: the stamp compares scale and the presence of the column
# ---------------------------------------------------------------------------------------------------------

def test_stamp_notices_a_scale_only_change_at_equal_digits(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "d"], [["1", "123.12345"], ["2", "2.5"]])
    try:
        assert case.meta[("t", "d")] == ColumnMeta(5, 8)
        plan = case.plan("SUM(t[d])")
        assert isinstance(plan, MeasurePlan) and plan.execute(case.store) == Decimal("125.62345")
        case.store.append_rows("t_csv", [["3", "1.123456"]])
        now = column_decimal_meta(case.store, "t_csv", ["d"])["d"]
        assert now == ColumnMeta(6, 8), now  # the scale changed, the digit count did not
        out = plan.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_PLAN_STALE, out
    finally:
        case.close()


def test_stamp_of_a_column_dropped_from_the_table_is_stale_not_a_crash(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "d"], [["1", "1.5"], ["2", "2.25"]])
    try:
        plans = [case.plan("SUM(t[d])"), case.group("SUM(t[d])", "n")]
        scalar = plans[0]
        assert isinstance(scalar, MeasurePlan) and scalar.execute(case.store) == Decimal("3.75")
        case.store.drop_table("t_csv")
        case.store.create_table("t_csv", [("n", "text")])  # rebuilt without column d
        case.store.append_rows("t_csv", [["1"]])
        out = scalar.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_PLAN_STALE, out
    finally:
        case.close()


# ---------------------------------------------------------------------------------------------------------
# Item 2, F3: a dropped table is a stale plan; any other store error propagates
# ---------------------------------------------------------------------------------------------------------

def guard_plans(case: Case) -> list[Any]:
    return [
        case.plan('CALCULATE(COUNTROWS(t), t[cat] IN {"A", "B"})'),  # scalar without a decimal stamp: IN guard
        case.plan("SUM(t[d])"),  # scalar with a stamp
        case.plan("MIN(t[dt])"),  # date guard
        case.group("COUNTROWS(t)", "cat"),  # text group-by: the space guard
        case.group("COUNTROWS(t)", "dt"),  # date group-by: the date guard
    ]


def test_every_plan_kind_returns_the_stale_refusal_after_the_table_is_dropped(case: Case) -> None:
    plans = guard_plans(case)
    assert all(isinstance(p, (MeasurePlan, GroupByPlan)) for p in plans), plans
    for plan in plans:
        assert not isinstance(plan.execute(case.store), Refusal), plan.shape
    case.store.drop_table("t_csv")
    for plan in plans:
        out = plan.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_PLAN_STALE, (plan.shape, out)


class RaisingStore:
    """The store, except that every query raises the given StoreError."""

    def __init__(self, error: StoreError) -> None:
        self.error = error
        self.calls = 0

    def execute(self, sql: str, params: Any = ()) -> Any:
        self.calls += 1
        raise self.error


@pytest.mark.parametrize(
    "message",
    ["Query execution failed: INTERRUPT Error: Interrupted!", "Store is closed.", "Query execution failed: Binder Error: no"],
    ids=["interrupt", "closed", "other"],
)
def test_an_interrupted_or_closed_guard_is_never_turned_into_stale(case: Case, message: str) -> None:
    # SUM(t[d]) is left out: the decimal stamp read (column_decimal_meta) has always swallowed every error as "no
    # metadata"; the route turns that into the timeout when its budget fired (see route_measure).
    plans = guard_plans(case)
    del plans[1]
    assert len(plans) == 4
    for plan in plans:
        store = RaisingStore(StoreError(message))
        with pytest.raises(StoreError, match="Interrupted|closed|Binder"):
            plan.execute(store)
        assert store.calls >= 1, plan.shape


def test_is_missing_table_error_only_says_yes_to_a_missing_table() -> None:
    assert dax_sql.is_missing_table_error(StoreError("Query execution failed: Catalog Error: Table with name x does not exist!"))
    assert dax_sql.is_missing_table_error(StoreError("Table \"x\" does not exist"))
    assert not dax_sql.is_missing_table_error(StoreError("Query execution failed: INTERRUPT Error: Interrupted!"))
    assert not dax_sql.is_missing_table_error(StoreError("Store is closed."))


# ---------------------------------------------------------------------------------------------------------
# Item 2, F4: a plan does not outlive a data change that changes a column TYPE
# ---------------------------------------------------------------------------------------------------------

def test_contract_a_column_that_gains_decimals_needs_a_rebuilt_plan(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "w"], [["1", "10"], ["2", "20"], ["3", "30"]])
    try:
        assert case.types["w"] == "whole_number"
        first = case.plan("SUM(t[w])")
        assert isinstance(first, MeasurePlan) and first.execute(case.store) == Decimal(60)
        case.store.append_rows("t_csv", [["4", "1.5"]])  # the whole column gains a decimal
        meta = {("t", c): m for c, m in column_decimal_meta(case.store, "t_csv", case.header).items()}
        rebuilt = plan_measure(
            "SUM(t[w])", home_table="t", tables={"t": {**case.types, "w": "decimal_number"}},
            store_tables={"t": "t_csv"}, column_meta=meta,
        )
        assert isinstance(rebuilt, MeasurePlan)
        assert rebuilt.execute(case.store) == Decimal("61.5")
    finally:
        case.close()


# ---------------------------------------------------------------------------------------------------------
# The rules tool: the new sweep families against the real engine
# ---------------------------------------------------------------------------------------------------------

def _crc_slice(row_id: str, parts: int, which: int) -> bool:
    import zlib

    return zlib.crc32(row_id.encode("utf-8")) % parts == which


def test_the_sweep_catalog_holds_the_new_families() -> None:
    from tools.store_engine_diff import build_sweep_catalog

    rows = build_sweep_catalog()
    by_shape: dict[str, int] = {}
    for row in rows:
        by_shape[row["shape"]] = by_shape.get(row["shape"], 0) + 1
    assert by_shape["group_own"] == 632 and by_shape["group_own_column"] == 10, by_shape
    assert by_shape["group_own_context"] == 4 and by_shape["date_old"] == 9, by_shape
    assert not any(r["shape"] == "group" and r["dax"] == "CALCULATE(SUM(t[sw]), t[sd] >= 0)" for r in rows)
    own = [r for r in rows if r["shape"] == "group_own"]
    assert all(r["own_predicates"] and r["group_by"] for r in own)
    # an own filter on the group column never appears in the allowed family
    assert not any(f"t[{r['group_by'][1]}]" in " ".join(r["own_predicates"]) for r in own)


@pytest.mark.parametrize("which", [0, 1])
def test_sweep_slice_of_the_own_filter_family_is_same_or_a_named_refusal(which: int) -> None:
    from tools.store_engine_diff import run_sweep

    data = run_sweep(
        rows=300, seed=3 + which,
        row_filter=lambda r: r["shape"] in ("group_own", "group_own_context") and _crc_slice(r["id"], 12, which),
    )
    results = data["sweep_results"]
    assert len(results) >= 40, len(results)
    assert not [(r["id"], r["status"], r["error"]) for r in results if r["status"] in ("differs", "sql-error", "crash")]
    assert sum(1 for r in results if r["status"] == "same") >= 20, data["sweep_counts"]
    for r in results:
        if r["status"] != "same":
            assert r["status"] in ("refused-guard", "refused-planner"), r


def test_sweep_date_before_1900_and_own_filter_on_the_group_column_are_refused_by_name() -> None:
    from tools.store_engine_diff import run_sweep

    data = run_sweep(rows=300, seed=1, row_filter=lambda r: r["shape"] in ("date_old", "group_own_column"))
    results = data["sweep_results"]
    old = [r for r in results if r["shape"] == "date_old"]
    assert len(old) == 9
    kept = [r for r in old if r["status"] == "same"]
    assert [r["id"] for r in kept] == ["date_old: COUNTROWS(t) | by scat"], kept  # a column without old cells stays same
    refused = [r for r in old if r["status"] != "same"]
    assert len(refused) == 8 and all(
        r["status"] == "refused-guard" and REASON_DATE_BEFORE_1900 in r["reason"] for r in refused
    ), refused
    column = [r for r in results if r["shape"] == "group_own_column"]
    assert len(column) == 10 and not [r for r in column if r["status"] in ("same", "differs", "sql-error", "crash")], column
    planner = [r for r in column if r["status"] == "refused-planner"]
    assert planner and all(REASON_GROUP_OWN_FILTER in r["reason"] for r in planner)
    assert not [r for r in column if r["status"] == "refused-whitelist" and "group-by column" in (r["reason"] or "")]
