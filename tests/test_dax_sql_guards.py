"""Tests for the C1b2b review fixes of analytics_studio/store/dax_sql.py.

Every expectation is checked against the REAL engine (evaluate_measures) or a hand-worked value, and each rule
is killed by a mutant (a module constant is patched, or the source of dax_sql is changed in a temporary copy by
the review run). This file is separate from tests/test_dax_sql.py to keep that file inside its time budget.

F1: a text IN plus a text equality: the engine's answer depends on the DATA of the equality column.
F2: a date column holding text the store cannot read (compact 20260105) must be refused, not read as blank.
F3: a plan keeps decimal metadata from plan time: a changed store makes the plan stale.
F4: group-by guards: non-ASCII whitespace classes, and a group column on another table.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.measures import evaluate_measures, normalize_measure
from analytics_studio.store import DuckStore, import_csv_to_store
from analytics_studio.store import dax_sql
from analytics_studio.store.dax_sql import (
    REASON_DATE_UNREADABLE,
    REASON_GROUP_NON_ASCII_SPACE,
    REASON_IN_NON_ASCII_COLUMN,
    REASON_PLAN_STALE,
    GroupByPlan,
    MeasurePlan,
    Refusal,
    column_decimal_meta,
    plan_group_by,
    plan_measure,
)


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

    def close(self) -> None:
        self.store.close()


def _same(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b


def _engine_value_or_error(case: Case, expression: str, measures: dict[str, str] | None = None) -> Any:
    try:
        return case.engine(expression, measures)
    except Exception as exc:  # the engine raising is an answer too
        return exc


# ---------------------------------------------------------------------------------------------------------
# F1: text equality beside a text IN
# ---------------------------------------------------------------------------------------------------------

# (character in column u, the equality literal): the engine folds or rejects these, the store does not
F1_CASES = [
    ("K", "k"),  # Kelvin sign
    ("ﬁ", "fi"),  # ligature fi
    ("ﬃ", "ffi"),  # ligature ffi
    ("ŉ", "n"),  # n preceded by apostrophe
    ("µ", "u"),  # micro sign (engine raises a composed/decomposed error)
    ("Ａ", "a"),  # fullwidth Latin letter (engine raises a full-width error)
]
F1_IDS = ["kelvin", "fi", "ffi", "napos", "micro", "fullwidth"]


def _f1_rows(special: str) -> list[list[str]]:
    return [[str(i), ["A", "B", "C", "a"][i % 4], special if i % 3 == 0 else "k", ["g1", "g2"][i % 2]] for i in range(1, 13)]


@pytest.fixture(scope="module")
def ascii_u_case(tmp_path_factory: pytest.TempPathFactory) -> Any:
    case = Case(tmp_path_factory.mktemp("f1ascii"), ["n", "cat", "u", "g"], _f1_rows("x"))
    yield case
    case.close()


def _f1_paths(literal: str) -> list[tuple[str, str, dict[str, Any], dict[str, str] | None, str]]:
    """(path name, plan expression, extra plan kwargs, measures, engine expression) for the same question."""
    both = f'CALCULATE(COUNTROWS(t), t[u] = "{literal}", t[cat] IN {{"A", "B"}})'
    return [
        ("scalar", both, {}, None, both),
        (
            "filter_context",
            f'CALCULATE(COUNTROWS(t), t[u] = "{literal}")',
            {"filter_context": ('t[cat] IN {"A", "B"}',)},
            None,
            both,
        ),
        (
            "filter_context_in_measure",
            'CALCULATE(COUNTROWS(t), t[cat] IN {"A", "B"})',
            {"filter_context": (f't[u] = "{literal}"',)},
            None,
            both,
        ),
        (
            "measure_reference",
            "[Outer]",
            {"measures": {"Both": both, "Outer": "[Both]"}},
            {"Both": both, "Outer": "[Both]"},
            "[Outer]",
        ),
    ]


@pytest.mark.parametrize("char,literal", F1_CASES, ids=F1_IDS)
def test_text_equality_beside_in_is_refused_when_the_equality_column_holds_special_text(
    tmp_path: Path, char: str, literal: str
) -> None:
    case = Case(tmp_path, ["n", "cat", "u", "g"], _f1_rows(char))
    try:
        for name, expression, extra, measures, engine_expression in _f1_paths(literal):
            plan = case.plan(expression, **extra)
            assert isinstance(plan, MeasurePlan), (name, plan)
            assert len(plan.in_guards) >= 1 and ("t_csv", "u") in plan.in_guards, (name, plan.in_guards)
            out = plan.execute(case.store)
            assert isinstance(out, Refusal) and out.reason == REASON_IN_NON_ASCII_COLUMN, (name, out)
            # the guard is needed: the unguarded SQL is not the engine's answer (the engine raises or differs)
            want = _engine_value_or_error(case, engine_expression, measures)
            raw = case.store.execute(plan.sql)[0][0]
            assert isinstance(want, Exception) or raw is None or not _same(Decimal(raw), want), (name, raw, want)
    finally:
        case.close()


@pytest.mark.parametrize("char,literal", F1_CASES[:1], ids=F1_IDS[:1])
def test_group_by_with_text_equality_beside_in_is_refused_on_special_text(tmp_path: Path, char: str, literal: str) -> None:
    case = Case(tmp_path, ["n", "cat", "u", "g"], _f1_rows(char))
    try:
        plan = case.group("COUNTROWS(t)", "g", filter_context=(f't[u] = "{literal}"', 't[cat] IN {"A", "B"}'))
        assert isinstance(plan, GroupByPlan) and ("t_csv", "u") in plan.in_guards
        out = plan.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_IN_NON_ASCII_COLUMN, out
    finally:
        case.close()


def test_text_equality_beside_in_on_an_ascii_column_is_the_engine_answer(ascii_u_case: Any) -> None:
    case = ascii_u_case
    for name, expression, extra, measures, engine_expression in _f1_paths("k"):
        plan = case.plan(expression, **extra)
        assert isinstance(plan, MeasurePlan), (name, plan)
        got = plan.execute(case.store)
        want = case.engine(engine_expression, measures)
        assert _same(got, want) and got > 0, (name, got, want)


def test_a_single_equality_without_in_is_not_guarded(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "cat", "u", "g"], _f1_rows("K"))
    try:
        expression = 'CALCULATE(COUNTROWS(t), t[u] = "k")'
        plan = case.plan(expression)
        assert isinstance(plan, MeasurePlan) and plan.in_guards == ()
        got = plan.execute(case.store)
        assert not isinstance(got, Refusal)
        want = case.engine(expression)
        assert _same(got, want), (got, want)  # same as the engine, so no refusal is needed
    finally:
        case.close()


# ---------------------------------------------------------------------------------------------------------
# F2: a date column the store cannot read the way the engine does
# ---------------------------------------------------------------------------------------------------------

def _date_rows(cells: list[str]) -> list[list[str]]:
    return [[str(i), cells[i % len(cells)], f"g{i % 3}"] for i in range(1, 13)]


COMPACT = ["20260105", "20251231", "20260615", ""]
ISO = ["2026-01-05", "2025-12-31", "2026-06-15", ""]
PADDED_ISO = [" 2026-01-05 ", "2025-12-31", "2026-06-15", ""]
DATE_EXPRESSIONS = ["MIN(t[dd])", "MAX(t[dd])", "CALCULATE(COUNTROWS(t), t[dd] >= DATE(2026, 1, 1))",
                    "CALCULATE(COUNTROWS(t), t[dd] < DATE(2026, 6, 1))"]


def test_compact_dates_are_refused_for_aggregate_predicate_and_group_by(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "dd", "g"], _date_rows(COMPACT))
    try:
        assert case.types["dd"] == "date"
        for expression in DATE_EXPRESSIONS:
            plan = case.plan(expression)
            assert isinstance(plan, MeasurePlan) and ("t_csv", "dd") in plan.date_guards, expression
            out = plan.execute(case.store)
            assert isinstance(out, Refusal) and out.reason == REASON_DATE_UNREADABLE, (expression, out)
            raw = case.store.execute(plan.sql)[0][0]  # the guard is needed: the unguarded SQL is not the engine's
            assert raw is None or not _same(dax_sql.convert_result(raw, plan.value_type), case.engine(expression)), expression
        grouped = case.group("COUNTROWS(t)", "dd")
        assert isinstance(grouped, GroupByPlan) and ("t_csv", "dd") in grouped.date_guards
        out = grouped.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_DATE_UNREADABLE, out
        # a plan that does not touch the date column is not refused
        plain = case.plan("COUNTROWS(t)")
        assert isinstance(plain, MeasurePlan) and plain.execute(case.store) == Decimal(12)
    finally:
        case.close()


@pytest.mark.parametrize("cells", [ISO, PADDED_ISO], ids=["iso", "padded_iso"])
def test_iso_and_padded_iso_dates_still_match_the_engine(tmp_path: Path, cells: list[str]) -> None:
    case = Case(tmp_path, ["n", "dd", "g"], _date_rows(cells))
    try:
        assert case.types["dd"] == "date"
        for expression in DATE_EXPRESSIONS:
            plan = case.plan(expression)
            assert isinstance(plan, MeasurePlan)
            got, want = plan.execute(case.store), case.engine(expression)
            assert not isinstance(got, Refusal) and _same(got, want), (expression, got, want)
        grouped = case.group("COUNTROWS(t)", "dd")
        assert isinstance(grouped, GroupByPlan)
        got_keys = grouped.execute(case.store)
        assert got_keys == [("", Decimal(3)), ("12/31/2025", Decimal(3)), ("1/5/2026", Decimal(3)), ("6/15/2026", Decimal(3))]
    finally:
        case.close()


def test_date_guard_runs_on_every_execute_and_sees_a_cell_added_later(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "dd", "g"], _date_rows(ISO))
    try:
        plan = case.plan("MIN(t[dd])")
        assert isinstance(plan, MeasurePlan) and not isinstance(plan.execute(case.store), Refusal)
        case.store.append_rows("t_csv", [["99", "20260101", "g1"]])
        out = plan.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_DATE_UNREADABLE, out
    finally:
        case.close()


# ---------------------------------------------------------------------------------------------------------
# F3: a plan is a snapshot of the decimal metadata
# ---------------------------------------------------------------------------------------------------------

def _decimal_rows() -> list[list[str]]:
    return [[str(i), ["1.5", "2.25", "10.5", ""][i % 4], ["a", "b"][i % 2]] for i in range(1, 9)]


def test_plan_is_stale_after_an_append_that_changes_decimal_scale(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "d", "g"], _decimal_rows())
    try:
        plans = [
            case.plan("SUM(t[d])"),
            case.plan("AVERAGE(t[d])"),
            case.plan("CALCULATE(COUNTROWS(t), t[d] >= 2)"),
            case.group("SUM(t[d])", "g"),
        ]
        assert all(isinstance(p, (MeasurePlan, GroupByPlan)) for p in plans), plans
        before = [p.execute(case.store) for p in plans]
        assert not any(isinstance(v, Refusal) for v in before)
        case.store.append_rows("t_csv", [["99", "1.123456789", "a"]])
        for plan in plans:
            out = plan.execute(case.store)
            assert isinstance(out, Refusal) and out.reason == REASON_PLAN_STALE, (plan.shape, out)
        meta = {("t", c): m for c, m in column_decimal_meta(case.store, "t_csv", case.header).items()}
        fresh = plan_measure("SUM(t[d])", **{**case.kw(), "column_meta": meta})
        assert isinstance(fresh, MeasurePlan)
        assert fresh.execute(case.store) == Decimal("29.623456789")  # hand sum: 2 * (2.25 + 10.5 + 1.5) + 1.123456789
    finally:
        case.close()


def test_plan_stays_valid_after_an_append_that_keeps_scale_and_digits(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "d", "g"], _decimal_rows())
    try:
        plan = case.plan("SUM(t[d])")
        assert isinstance(plan, MeasurePlan)
        first = plan.execute(case.store)
        case.store.append_rows("t_csv", [["99", "1.5", "a"]])
        second = plan.execute(case.store)
        assert isinstance(first, Decimal) and second == first + Decimal("1.5"), (first, second)
    finally:
        case.close()


def test_plan_is_stale_after_an_append_that_adds_digits(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "d", "g"], _decimal_rows())
    try:
        plan = case.plan("SUM(t[d])")
        case.store.append_rows("t_csv", [["99", "123456789012345678901234567890.5", "a"]])
        out = plan.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_PLAN_STALE, out
    finally:
        case.close()


# ---------------------------------------------------------------------------------------------------------
# F4: group-by guard coverage
# ---------------------------------------------------------------------------------------------------------

NON_ASCII_SPACE_CELLS = [("NEL", "\u0085"), ("ideographic", "　"), ("em space", " "), ("nbsp", " ")]


@pytest.mark.parametrize("label,char", NON_ASCII_SPACE_CELLS, ids=[c[0] for c in NON_ASCII_SPACE_CELLS])
def test_group_by_refuses_every_non_ascii_whitespace_class(tmp_path: Path, label: str, char: str) -> None:
    rows = [[str(i), ["A", "b", "C", char][i % 4]] for i in range(1, 13)]
    case = Case(tmp_path, ["n", "cat"], rows)
    try:
        plan = case.group("COUNTROWS(t)", "cat")
        assert isinstance(plan, GroupByPlan)
        out = plan.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_GROUP_NON_ASCII_SPACE, (label, out)
    finally:
        case.close()


def test_group_by_ascii_cells_still_pass_the_space_guard(tmp_path: Path) -> None:
    rows = [[str(i), ["A", "b", "C", " "][i % 4]] for i in range(1, 13)]
    case = Case(tmp_path, ["n", "cat"], rows)
    try:
        plan = case.group("COUNTROWS(t)", "cat")
        assert isinstance(plan, GroupByPlan) and not isinstance(plan.execute(case.store), Refusal)
    finally:
        case.close()


def test_mutant_space_class_nbsp_only_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dax_sql, "NON_ASCII_SPACE_CLASS", "\\x{A0}")
    with pytest.raises(AssertionError):
        test_group_by_refuses_every_non_ascii_whitespace_class(tmp_path, "NEL", "\u0085")


def test_group_column_on_another_table_is_refused(tmp_path: Path) -> None:
    case = Case(tmp_path, ["n", "cat"], [[str(i), ["A", "b"][i % 2]] for i in range(1, 9)])
    try:
        other_csv = tmp_path / "o.csv"
        other_csv.write_text("m,cat\n1,x\n2,y\n3,z\n", encoding="utf-8")
        import_csv_to_store(case.store, "o_csv", other_csv, {})
        other_types = {"m": "whole_number", "cat": "text"}
        plan = plan_group_by(
            "COUNTROWS(t)", group_by=("o", "cat"), home_table="t", tables={"t": case.types, "o": other_types},
            store_tables={"t": "t_csv", "o": "o_csv"}, column_meta=case.meta,
        )
        assert isinstance(plan, Refusal) and "o" in plan.reason and "'t'" in plan.reason, plan
        same_table = plan_group_by(
            "COUNTROWS(t)", group_by=("t", "cat"), home_table="t", tables={"t": case.types, "o": other_types},
            store_tables={"t": "t_csv", "o": "o_csv"}, column_meta=case.meta,
        )
        assert isinstance(same_table, GroupByPlan) and not isinstance(same_table.execute(case.store), Refusal)
    finally:
        case.close()


# ---------------------------------------------------------------------------------------------------------
# F6: the tool tells an empty table from a blank-only key list
# ---------------------------------------------------------------------------------------------------------

def test_parse_engine_keys_uses_the_row_count_for_a_header_only_text() -> None:
    from tools.store_engine_diff import _parse_engine_keys

    assert _parse_engine_keys("'t'[x]\n", 0) == []  # empty table
    assert _parse_engine_keys("'t'[x]\n", Decimal(0)) == []
    assert _parse_engine_keys("'t'[x]\n", 3) == [""]  # rows exist and the only key is blank
    assert _parse_engine_keys("'t'[x]\n") == [""]  # no count given: the old reading
    assert _parse_engine_keys("'t'[x]\nA\nB\n", 0) == ["A", "B", ""]  # a count never overrides a keys list
    assert _parse_engine_keys("", 0) == []


def test_sweep_rows_with_a_context_that_removes_all_rows_are_empty_on_both_sides() -> None:
    from tools.store_engine_diff import run_sweep

    wanted = {"sg", "sdt", "sf"}
    data = run_sweep(rows=60, seed=1, row_filter=lambda r: r["shape"] == "group_empty" and r["group_by"][1] in wanted)
    results = data["sweep_results"]
    assert len(results) == 3 * len(wanted), [r["id"] for r in results]
    for record in results:
        assert record["status"] == "same" and record["engine_text"] == "" and record["plan_text"] == "", record


def test_mutant_parser_ignoring_the_row_count_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.store_engine_diff as tool
    from tools.store_engine_diff import run_sweep

    original = tool._parse_engine_keys
    monkeypatch.setattr(tool, "_parse_engine_keys", lambda text, row_count=None: original(text))
    data = run_sweep(rows=60, seed=1, row_filter=lambda r: r["shape"] == "group_empty" and r["group_by"][1] == "sg")
    assert {r["status"] for r in data["sweep_results"]} == {"differs"}  # the old parser reads [""] against []
