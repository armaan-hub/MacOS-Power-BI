"""Tests for Stage C2a: analytics_studio/store/dax_route.py, the one door to the large-table DAX path.

Values are compared with the in-memory engine on the same rows (the engine is used ONLY by the tests, never by
the route). Each rule has a mutant proof in the second half of the file: a module-level function or constant is
patched and the behaviour check for the rule must fail.
"""

from __future__ import annotations

import csv
import os
import random
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from analytics_studio import dax_dates
from analytics_studio.file_import import parse_file
from analytics_studio.measures import evaluate_measures, normalize_measure
from analytics_studio.store import DuckStore, ProjectStore, dax_route, dax_sql, dax_whitelist, import_csv_to_store
from analytics_studio.store.base import StoreError
from analytics_studio.store.dax_route import (
    GENERIC_SENTENCE,
    RouteRefusal,
    StoreAnswer,
    message_for_reason,
    route_is_available,
    route_measure,
    store_shape,
)

TYPES = {
    "id": "text", "region": "text", "product": "text", "qty": "whole_number", "amt": "decimal_number",
    "neg": "decimal_number", "pay": "date", "paid": "boolean",
}
HEADERS = list(TYPES)


def make_rows(count: int = 3000, seed: int = 7) -> list[list[str]]:
    rnd = random.Random(seed)
    regions = ["East", "east", "EAST", "West", "North", "", "South", "West "]
    out: list[list[str]] = []
    for i in range(count):
        qty = "" if rnd.random() < 0.08 else str(rnd.randrange(-3, 12))
        amt = "" if rnd.random() < 0.08 else f"{rnd.randrange(-500, 90000) / 100:.2f}"
        neg = f"{-rnd.randrange(1, 5000) / 100:.2f}" if rnd.random() < 0.9 else ""
        day = "" if rnd.random() < 0.1 else (
            f"{rnd.randrange(2022, 2027)}-{rnd.randrange(1, 13):02d}-{rnd.randrange(1, 29):02d}"
        )
        paid = rnd.choice(["TRUE", "FALSE", "TRUE", ""])
        out.append([str(i + 1), rnd.choice(regions), f"P{rnd.randrange(20):02d}", qty, amt, neg, day, paid])
    return out


def write_csv(path: Path, rows: list[list[str]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        writer.writerows(rows)
    return path


def make_project(
    *,
    types: dict[str, str] | None = None,
    extra_tables: list[dict[str, Any]] | None = None,
    relationships: list[dict[str, Any]] | None = None,
    measures: list[dict[str, Any]] | None = None,
    calculated: bool = False,
    kind: str = "csv",
) -> dict[str, Any]:
    table: dict[str, Any] = {"id": "s1", "source_id": "s1", "name": "t", "column_types": dict(types or TYPES)}
    if calculated:
        table["calculated_columns"] = [{"name": "x", "expression": "1"}]
    return {
        "model": {
            "tables": [table, *(extra_tables or [])],
            "measures": list(measures or []),
            "relationships": list(relationships or []),
        },
        "data_sources": [{"id": "s1", "kind": kind, "store": {"table": "t_csv"}}],
    }


class Env:
    """A ProjectStore holding the synthetic table, the project dict and the in-memory twin (test oracle only).

    The twin is the app's own import path (a controller): the in-memory import folds and trims text the way
    VertiPaq does, so only that path gives the rows the engine really sees. Its inferred column types are the
    types of the route's project.
    """

    def __init__(self, base: Path, rows: list[list[str]] | None = None) -> None:
        from PySide6.QtWidgets import QApplication

        from analytics_studio.controller import StudioController

        self.base = base
        self.rows = rows if rows is not None else make_rows()
        self.csv = write_csv(base / "t.csv", self.rows)
        self._qapp = QApplication.instance() or QApplication(["dax_route_tests"])
        self._twin = StudioController()
        self._twin._effective_app_data_dir = lambda: str(base / "app_data")  # type: ignore[method-assign]
        assert self._twin._commit_import(self.csv, parse_file(self.csv))
        self.types = dict(self._twin._project["model"]["tables"][0]["column_types"])
        self.ps = ProjectStore.open(str(base / "t.npa.data"))
        import_csv_to_store(self.ps.store, "t_csv", self.csv, {})
        self.project = make_project(types=self.types)

    def route(self, expression: str, **kwargs: Any) -> Any:
        measures = kwargs.pop("measures", None)
        return route_measure(self.project, expression, project_store=self.ps, measures=measures, **kwargs)

    def engine(self, expression: str, measures: dict[str, str] | None = None) -> Any:
        """The in-memory engine on the same rows (test oracle only)."""
        twin = self._twin
        aid = twin._active_model_table_id()
        candidate = twin._loaded_candidates[twin._active_source_id]
        mlist = [normalize_measure(n, e, home_table_id=aid) for n, e in (measures or {}).items()]
        target = normalize_measure("TargetMeasure", expression, home_table_id=aid)
        return evaluate_measures(
            [*mlist, target], candidate.rows, candidate.headers, twin._active_model_table_name(),
            measure_names=["TargetMeasure"], table_context=twin._measure_table_context(), relationships=[],
            filter_table_ids=set(), active_table_id=aid,
        )["TargetMeasure"]

    def reload_twin(self) -> None:
        self.csv = write_csv(self.base / "t.csv", self.rows)
        assert self._twin._commit_import(self.csv, parse_file(self.csv))

    def close(self) -> None:
        self.ps.close()


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Env:
    e = Env(tmp_path_factory.mktemp("route"))
    yield e
    e.close()


@pytest.fixture
def fresh(tmp_path: Path) -> Env:
    e = Env(tmp_path)
    yield e
    if not e.ps.closed:
        e.close()


MEASURES = {
    "Base": "SUM(t[amt])",
    "Twice": "[Base]",
    "EastBase": "CALCULATE([Base], t[region] = \"East\")",
    "QtySum": "SUM(t[qty])",
}

CATALOG: list[str] = [
    "SUM(t[qty])", "SUM(t[amt])", "SUM(t[neg])", "AVERAGE(t[qty])", "AVERAGE(t[amt])", "AVERAGE(t[neg])",
    "MIN(t[qty])", "MAX(t[amt])", "MIN(t[pay])", "MAX(t[pay])", "COUNT(t[qty])", "COUNT(t[pay])",
    "COUNTA(t[region])", "COUNTA(t[qty])", "COUNTROWS(t)", "COUNTBLANK(t[region])", "COUNTBLANK(t[qty])",
    "DISTINCTCOUNT(t[region])", "DISTINCTCOUNT(t[product])", "DISTINCTCOUNT(t[paid])",
    "CALCULATE(SUM(t[amt]), t[region] = \"East\")",
    "CALCULATE(SUM(t[amt]), t[region] IN {\"East\", \"West\"})",
    "CALCULATE(COUNTROWS(t), t[qty] > 5)",
    "CALCULATE(SUM(t[qty]), t[qty] >= 3, t[region] = \"West\")",
    "CALCULATE(SUM(t[amt]), t[amt] >= 100)",
    "CALCULATE(COUNTROWS(t), t[pay] >= DATE(2024, 1, 1))",
    "CALCULATE(MAX(t[pay]), t[qty] = 4)",
    "CALCULATE(AVERAGE(t[neg]), t[neg] < -10)",
    "CALCULATE(COUNTROWS(t), t[qty] <> 3)",
    "CALCULATE(SUM(t[qty]), t[qty] = 3 || t[qty] = 4)",
    "CALCULATE(SUM(t[qty]), t[qty] = 99999)",
    "CALCULATE(DISTINCTCOUNT(t[product]), t[region] = \"West\")",
    "CALCULATE(MIN(t[amt]), t[qty] < 0)",
    "CALCULATE(COUNTBLANK(t[region]), t[qty] > 0)",
    "CALCULATE(COUNTROWS(t), t[product] = \"P03\", t[pay] < DATE(2025, 6, 30))",
    "[Base]", "[Twice]", "[EastBase]", "CALCULATE([Base], t[qty] > 2)", "CALCULATE([QtySum], t[product] IN {\"P01\", \"P02\"})",
]


def same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if dax_dates.is_date(a) or dax_dates.is_date(b):
        return dax_dates.is_date(a) and dax_dates.is_date(b) and a == b
    return isinstance(a, Decimal) and isinstance(b, Decimal) and a == b


# ---------------------------------------------------------------------------------------------------
# (a) route value equals the in-memory engine
# ---------------------------------------------------------------------------------------------------
def test_catalog_has_at_least_30_measures() -> None:
    assert len(CATALOG) >= 30


@pytest.mark.parametrize("expression", CATALOG)
def test_route_equals_engine(env: Env, expression: str) -> None:
    answer = env.route(expression, measures=MEASURES)
    assert isinstance(answer, StoreAnswer), answer
    assert answer.kind == "scalar" and answer.table == "t"
    expected = env.engine(expression, MEASURES)
    assert same(answer.value, expected), (expression, answer.value, expected)


def test_route_by_measure_name(env: Env) -> None:
    project = make_project(types=env.types, measures=[{"name": "Total Amt", "expression": "SUM(t[amt])"}])
    answer = route_measure(project, "total amt", project_store=env.ps)
    assert isinstance(answer, StoreAnswer)
    assert same(answer.value, env.engine("SUM(t[amt])"))


def test_grouped_answer_rows_and_filter_context(env: Env) -> None:
    answer = env.route("SUM(t[qty])", group_by=("t", "region"))
    assert isinstance(answer, StoreAnswer) and answer.kind == "grouped"
    assert answer.rows and all(isinstance(key, str) for key, _ in answer.rows)
    total = sum((v for _, v in answer.rows if v is not None), Decimal(0))
    assert total == env.route("SUM(t[qty])").value
    filtered = env.route("SUM(t[qty])", group_by=("t", "region"), filter_context=("t[product] = \"P01\"",))
    assert isinstance(filtered, StoreAnswer)
    ctx_scalar = env.route("SUM(t[qty])", filter_context=("t[product] = \"P01\"",))
    assert sum((v for _, v in filtered.rows if v is not None), Decimal(0)) == ctx_scalar.value


# ---------------------------------------------------------------------------------------------------
# (b) refusals
# ---------------------------------------------------------------------------------------------------
REFUSED: list[tuple[str, dict[str, str] | None]] = [
    ("CALCULATE(SUM(t[amt]), ALL(t))", None),
    ("SUMX(t, t[amt] * 2)", None),
    ("CALCULATE(SUM(t[amt]), FILTER(t, t[qty] > 1))", None),
    ("SUMX(t, RELATED(u[x]))", None),
    ("TOTALYTD(SUM(t[amt]), t[pay])", None),
    ("SUM(u[x])", None),
    ("MAX(t[region])", None),
    ("DIVIDE(SUM(t[amt]), [Bad])", {"Bad": "SUMX(t, t[amt])"}),
    ("SUM(t[amt]) / SUM(t[qty])", None),
    ("CALCULATE(SUM(t[amt]), t[region] > \"E\")", None),
]


@pytest.mark.parametrize("expression,measures", REFUSED)
def test_refused_shapes_have_plain_messages(env: Env, expression: str, measures: dict[str, str] | None) -> None:
    out = env.route(expression, measures=measures)
    assert isinstance(out, RouteRefusal), out
    assert out.code == "whitelist", (out.code, out.reason)
    assert out.message.endswith(".") and out.message.count(". ") == 0
    assert not out.message.startswith(GENERIC_SENTENCE), out.message
    assert " - " not in out.message, out.message
    assert out.reason and not re.search(r"plan|guard|fold|duckdb", out.message, re.I), out.message


def test_refusal_names_the_measure_and_the_reason(env: Env) -> None:
    project = make_project(types=env.types, measures=[{"name": "Total Sales", "expression": "CALCULATE(SUM(t[amt]), ALL(t))"}])
    out = route_measure(project, "Total Sales", project_store=env.ps)
    assert isinstance(out, RouteRefusal)
    assert out.message.startswith("Total Sales cannot be computed on a large table yet: ")
    assert "ALL" in out.message


# ---------------------------------------------------------------------------------------------------
# (c) every reason constant has a sentence
# ---------------------------------------------------------------------------------------------------
def _reason_constants() -> dict[str, str]:
    out: dict[str, str] = {}
    for module in (dax_sql, dax_whitelist):
        for name in dir(module):
            value = getattr(module, name)
            if isinstance(value, str) and (name.startswith("REASON_") or name in (
                "PARQUET_PLAN_REASON", "PARQUET_COUNTA_REFUSAL_REASON",
            )):
                out[f"{module.__name__}.{name}"] = value
    return out


def test_every_reason_constant_has_a_plain_sentence() -> None:
    constants = _reason_constants()
    assert len(constants) >= 40
    for name, text in constants.items():
        fragment = dax_route.fragment_for_reason(text)
        assert fragment is not None, f"{name} has no entry in dax_route.FRAGMENTS"
        message = message_for_reason("M", text)
        assert not message.startswith("This measure cannot"), name
        assert message.endswith(".") and " - " not in message, (name, message)
        assert not re.search(r"plan|guard|fold|duckdb", message, re.I), (name, message)


def _inline_reason_samples() -> dict[str, str]:
    """Every reason string the whitelist and the planner can return, found by NAME in their source text.

    A reason is a string handed to Refusal(...), WhitelistDecision(...), reasons.append(...), out.append(...) or
    returned by a function annotated `-> str | None`. An f-string placeholder becomes "X" (a module-level reason
    constant is replaced by its text).
    """
    import ast

    out: dict[str, str] = {}
    for module in (dax_whitelist, dax_sql):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

        def texts(node: ast.AST) -> list[str]:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return [node.value]
            if isinstance(node, ast.JoinedStr):
                parts = []
                for piece in node.values:
                    if isinstance(piece, ast.Constant):
                        parts.append(str(piece.value))
                    elif isinstance(piece, ast.FormattedValue) and isinstance(piece.value, ast.Name) and isinstance(
                        getattr(module, piece.value.id, None), str
                    ):
                        parts.append(getattr(module, piece.value.id))
                    else:
                        parts.append("X")
                return ["".join(parts)]
            if isinstance(node, (ast.Tuple, ast.List)):
                return [t for element in node.elts for t in texts(element)]
            if isinstance(node, ast.IfExp):
                return texts(node.body) + texts(node.orelse)
            if isinstance(node, ast.BoolOp):
                return [t for value in node.values for t in texts(value)]
            return []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                holder = func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else ""
                if name in ("Refusal", "WhitelistDecision") or (name in ("append", "extend") and holder in ("reasons", "out")):
                    for argument in node.args:
                        for text in texts(argument):
                            out[text] = module.__name__
            if isinstance(node, ast.FunctionDef) and node.returns is not None and "str | None" in ast.unparse(node.returns):
                for child in ast.walk(node):
                    if isinstance(child, ast.Return) and child.value is not None:
                        for text in texts(child.value):
                            out[text] = module.__name__
    return {text: origin for text, origin in out.items() if " " in text}


def test_every_inline_reason_has_a_plain_sentence() -> None:
    samples = _inline_reason_samples()
    assert len(samples) >= 60, len(samples)
    for text, origin in samples.items():
        assert dax_route.reason_is_mapped(text), f"{origin}: no entry for {text!r}"
        message = message_for_reason("M", text)
        assert not message.startswith("This measure cannot"), text
        assert not re.search(r"plan|guard|fold|duckdb|whole_number|decimal_number|string value", message, re.I), (text, message)
        assert message.endswith("."), message


def test_missing_column_and_syntax_errors_are_not_blamed_on_the_large_table(env: Env) -> None:
    out = env.route("SUM(t[nope])")
    assert isinstance(out, RouteRefusal) and out.message == "Column 'nope' was not found in table t."
    for expression in ("SUM(t[qty]", "SUM(t[qty]))", "SUM(u[qty])", "[Nope]"):
        out = env.route(expression)
        assert isinstance(out, RouteRefusal)
        assert "large table" not in out.message, out.message
    named = route_measure(
        make_project(types=env.types, measures=[{"name": "Bad Col", "expression": "SUM(t[nope])"}]), "Bad Col",
        project_store=env.ps,
    )
    assert named.message == "Bad Col: Column 'nope' was not found in table t."


def test_internal_type_names_never_reach_the_user(env: Env) -> None:
    for expression in (
        "CALCULATE(SUM(t[qty]), t[qty] = \"a\")", "CALCULATE(SUM(t[qty]), t[qty] IN {1, 2})",
        "CALCULATE(SUM(t[amt]), t[amt] = 1.5)", "SUM(t[pay])",
    ):
        out = env.route(expression)
        assert isinstance(out, RouteRefusal)
        assert not re.search(r"whole_number|decimal_number|string|_", out.message), out.message
    assert "whole number" in env.route("CALCULATE(SUM(t[qty]), t[qty] = \"a\")").message


def test_unknown_reason_gets_generic_sentence_and_raw_reason() -> None:
    message = message_for_reason("This measure", "something nobody wrote down")
    assert message == f"{GENERIC_SENTENCE} - something nobody wrote down."


# ---------------------------------------------------------------------------------------------------
# (d) project shapes
# ---------------------------------------------------------------------------------------------------
def test_s1_single_store_table_answers(env: Env) -> None:
    assert store_shape(env.project).ok
    assert isinstance(env.route("COUNTROWS(t)"), StoreAnswer)


def test_store_plus_ordinary_table_refuses(env: Env) -> None:
    project = make_project(extra_tables=[{"id": "s2", "source_id": "s2", "name": "u", "column_types": {"a": "text"}}])
    assert route_is_available(project)
    out = route_measure(project, "COUNTROWS(t)", project_store=env.ps)
    assert isinstance(out, RouteRefusal) and out.code == "shape"
    assert out.message == dax_route.MIXED_MODEL_REASON


def test_store_with_relationship_refuses(env: Env) -> None:
    project = make_project(relationships=[{"id": "r1", "from_table": "t", "to_table": "t"}])
    out = route_measure(project, "COUNTROWS(t)", project_store=env.ps)
    assert isinstance(out, RouteRefusal) and out.code == "shape"


def test_calculated_column_and_unknown_kind_refuse(env: Env) -> None:
    assert not store_shape(make_project(calculated=True)).ok
    assert not store_shape(make_project(kind="xlsx")).ok
    assert isinstance(route_measure(make_project(calculated=True), "COUNTROWS(t)", project_store=env.ps), RouteRefusal)


def test_parquet_kind_is_routed_and_refused_by_the_planner(env: Env) -> None:
    out = route_measure(make_project(kind="parquet"), "COUNTROWS(t)", project_store=env.ps)
    assert isinstance(out, RouteRefusal) and out.code == "plan"
    assert "Parquet" in out.message


def test_ordinary_only_project_never_reaches_the_route() -> None:
    project = {"model": {"tables": [{"id": "x", "source_id": "x", "name": "u", "column_types": {}}]}, "data_sources": [
        {"id": "x", "kind": "csv"}]}
    assert route_is_available(project) is False
    assert route_is_available({}) is False


def test_route_is_available_uses_candidates_when_given() -> None:
    class Cand:
        is_store_backed = True
        store_table = "t_csv"
        kind = "csv"

    project = make_project()
    del project["data_sources"][0]["store"]
    assert route_is_available(project) is False
    assert route_is_available(project, {"s1": Cand()}) is True
    assert store_shape(project, {"s1": Cand()}).ok


def test_wrong_argument_types_raise(env: Env) -> None:
    with pytest.raises(TypeError):
        route_measure("not a project", "COUNTROWS(t)", project_store=env.ps)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        route_measure(env.project, 5, project_store=env.ps)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        route_measure(env.project, "COUNTROWS(t)", project_store=None)
    with pytest.raises(TypeError):
        route_measure(env.project, "COUNTROWS(t)", project_store=env.ps, filter_context=["x"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------------
# (e) busy, closed, dropped
# ---------------------------------------------------------------------------------------------------
def test_busy_store_returns_busy_and_stays_usable(fresh: Env) -> None:
    with fresh.ps.job():
        out = fresh.route("COUNTROWS(t)")
        assert isinstance(out, RouteRefusal) and out.code == "busy"
        assert out.message == dax_route.BUSY_MESSAGE
        assert fresh.ps.busy is True  # still held by the outer job
    assert fresh.ps.busy is False
    assert isinstance(fresh.route("COUNTROWS(t)"), StoreAnswer)
    assert fresh.ps.busy is False


def test_busy_false_after_value_refusal_and_any_exception(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(fresh.route("COUNTROWS(t)"), StoreAnswer) and fresh.ps.busy is False
    assert isinstance(fresh.route("SUMX(t, t[amt])"), RouteRefusal) and fresh.ps.busy is False

    def boom(self: Any, store: Any) -> Any:
        raise RuntimeError("programmer error")

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", boom)
    out = fresh.route("COUNTROWS(t)")
    assert isinstance(out, RouteRefusal) and out.code == "plan" and "RuntimeError" in out.message
    assert out.message.endswith(".") and "could not be computed" in out.message
    assert fresh.ps.busy is False


def test_closed_store_returns_closed(fresh: Env) -> None:
    fresh.ps.close()
    out = fresh.route("COUNTROWS(t)")
    assert isinstance(out, RouteRefusal) and out.code == "closed"


def test_dropped_table_is_a_refusal_not_an_exception(fresh: Env) -> None:
    fresh.ps.store.drop_table("t_csv")
    out = fresh.route("SUM(t[qty])")
    assert isinstance(out, RouteRefusal)
    assert out.code in ("plan", "closed")
    assert fresh.ps.busy is False


# ---------------------------------------------------------------------------------------------------
# (f) timeout
# ---------------------------------------------------------------------------------------------------
def _slow_execute(self: Any, store: Any) -> Any:
    return store.execute("SELECT count(*) FROM range(10000000000)")


def test_slow_plan_times_out_and_store_still_works(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(dax_sql.MeasurePlan, "execute", _slow_execute)
        started = time.monotonic()
        out = fresh.route("COUNTROWS(t)", budget_s=0.2)
        elapsed = time.monotonic() - started
    assert isinstance(out, RouteRefusal) and out.code == "timeout", out
    assert elapsed < 1.0, elapsed
    assert out.message == "This measure took longer than 0.2 seconds on this large table and was stopped."
    assert fresh.ps.busy is False
    again = fresh.route("COUNTROWS(t)")
    assert isinstance(again, StoreAnswer) and again.value == Decimal(len(fresh.rows))
    assert fresh.ps.store.execute("SELECT 1") == [(1,)]


def test_timeout_message_names_the_measure(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(types=fresh.types, measures=[{"name": "Slow One", "expression": "COUNTROWS(t)"}])
    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", _slow_execute)
    out = route_measure(project, "Slow One", project_store=fresh.ps, budget_s=0.2)
    assert isinstance(out, RouteRefusal) and out.code == "timeout"
    assert out.message.startswith("Slow One took longer than 0.2 seconds")


def test_expired_deadline_does_not_run_the_measure(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def never(self: Any, store: Any) -> Any:
        raise AssertionError("must not run after the deadline")

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", never)
    out = fresh.route("COUNTROWS(t)", deadline=time.monotonic() - 1)
    assert isinstance(out, RouteRefusal) and out.code == "timeout"
    assert out.message == dax_route.DEADLINE_MESSAGE
    assert fresh.ps.busy is False


def test_shared_deadline_caps_the_budget(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", _slow_execute)
    started = time.monotonic()
    out = fresh.route("COUNTROWS(t)", budget_s=30.0, deadline=time.monotonic() + 0.3)
    assert isinstance(out, RouteRefusal) and out.code == "timeout"
    assert time.monotonic() - started < 1.5


def test_duckstore_interrupt_then_normal_query(tmp_path: Path) -> None:
    import threading

    store = DuckStore(str(tmp_path / "i.db"))
    try:
        timer = threading.Timer(0.2, store.interrupt)
        timer.start()
        with pytest.raises(StoreError, match="(?i)interrupt"):
            store.execute("SELECT count(*) FROM range(10000000000)")
        timer.join()
        assert store.execute("SELECT 41 + 1") == [(42,)]
        store.interrupt()  # idle interrupt does nothing
        assert store.execute("SELECT 7") == [(7,)]
    finally:
        store.close()


def test_interrupt_does_not_take_the_store_lock(tmp_path: Path) -> None:
    import threading

    store = DuckStore(str(tmp_path / "l.db"))
    try:
        with store._lock:  # another thread holds the lock, as a running query does
            done = threading.Event()
            worker = threading.Thread(target=lambda: (store.interrupt(), done.set()))
            worker.start()
            assert done.wait(2.0), "interrupt() waited for the store lock"
            worker.join()
    finally:
        store.close()


# ---------------------------------------------------------------------------------------------------
# (g) plan lifetime
# ---------------------------------------------------------------------------------------------------
def test_second_route_after_append_reflects_new_data(fresh: Env) -> None:
    before = fresh.route("SUM(t[qty])")
    assert isinstance(before, StoreAnswer)
    fresh.ps.store.append_rows("t_csv", [("90001", "East", "P01", "1000", "1.50", "-1.00", "2024-01-01", "TRUE")])
    after = fresh.route("SUM(t[qty])")
    assert isinstance(after, StoreAnswer)
    assert after.value == before.value + Decimal(1000)
    assert fresh.route("COUNTROWS(t)").value == Decimal(len(fresh.rows) + 1)


def test_second_route_after_reload_with_new_decimal_scale(fresh: Env) -> None:
    first = fresh.route("SUM(t[amt])")
    assert isinstance(first, StoreAnswer)
    rows = [list(r) for r in fresh.rows]
    rows[0][4] = "1.123456"
    fresh.rows = rows
    fresh.reload_twin()
    fresh.ps.store.drop_table("t_csv")
    import_csv_to_store(fresh.ps.store, "t_csv", fresh.csv, {})
    second = fresh.route("SUM(t[amt])")
    assert isinstance(second, StoreAnswer)
    assert second.value != first.value
    assert same(second.value, fresh.engine("SUM(t[amt])"))


def test_old_plan_across_a_reload_is_stale_and_the_route_never_runs_it(fresh: Env) -> None:
    store = fresh.ps.store
    meta = {("t", c): m for c, m in dax_sql.column_decimal_meta(store, "t_csv", ["amt"]).items()}
    old_plan = dax_sql.plan_measure(
        "SUM(t[amt])", home_table="t", tables={"t": fresh.types}, store_tables={"t": "t_csv"}, column_meta=meta,
    )
    assert isinstance(old_plan, dax_sql.MeasurePlan)
    assert isinstance(old_plan.execute(store), Decimal)
    store.append_rows("t_csv", [("90002", "East", "P01", "1", "9.1234567", "-1.00", "2024-01-01", "TRUE")])
    stale = old_plan.execute(store)
    assert isinstance(stale, dax_sql.Refusal) and stale.reason == dax_sql.REASON_PLAN_STALE
    fresh_answer = fresh.route("SUM(t[amt])")
    assert isinstance(fresh_answer, StoreAnswer) and isinstance(fresh_answer.value, Decimal)


def test_route_builds_a_new_plan_every_call(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    real = dax_route.plan_measure

    def counting(*args: Any, **kwargs: Any) -> Any:
        plan = real(*args, **kwargs)
        calls.append(plan)
        return plan

    monkeypatch.setattr(dax_route, "plan_measure", counting)
    fresh.route("SUM(t[qty])")
    fresh.route("SUM(t[qty])")
    assert len(calls) == 2 and calls[0] is not calls[1]
    assert not [n for n in vars(dax_route) if isinstance(vars(dax_route)[n], dict) and n.startswith("_cache")]


# ---------------------------------------------------------------------------------------------------
# (h) no fallback to the in-memory engine
# ---------------------------------------------------------------------------------------------------
def test_route_module_never_touches_the_in_memory_engine() -> None:
    source = Path(dax_route.__file__).read_text(encoding="utf-8")
    assert "evaluate_measure" not in source


def _boom(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("the in-memory engine must not be used for a store table")


def test_cards_for_a_store_project_never_call_the_in_memory_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QApplication

    from analytics_studio import controller as controller_module
    from tests.test_controller_dax_route_app import make_store_controller

    app = QApplication.instance() or QApplication(["dax_route_no_fallback"])
    assert app is not None
    ctrl, ps = make_store_controller(tmp_path, make_rows(2000))
    try:
        assert ctrl.create_measure("Total Qty", "SUM(t[qty])") is True
        monkeypatch.setattr(controller_module, "evaluate_measures", _boom)
        for name in dir(controller_module):
            if name.startswith("evaluate_measure") and callable(getattr(controller_module, name)):
                monkeypatch.setattr(controller_module, name, _boom)
        ctrl._refresh_report()
        assert ctrl._measure_values["Total Qty"] != "—"
        ctrl._refresh_report_async()
        assert ctrl._measure_values["Total Qty"] != "—"
        assert ctrl._measure_errors == {}
    finally:
        ps.close()


# ---------------------------------------------------------------------------------------------------
# Optional 1,000,000-row timing (ANALYTICS_STUDIO_BIG_TESTS=1)
# ---------------------------------------------------------------------------------------------------
@pytest.mark.skipif(os.environ.get("ANALYTICS_STUDIO_BIG_TESTS") != "1", reason="set ANALYTICS_STUDIO_BIG_TESTS=1")
def test_scalar_timing_at_one_million_rows(tmp_path: Path) -> None:
    rnd = random.Random(11)
    path = tmp_path / "big.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        for i in range(1_000_000):
            writer.writerow([
                i, f"R{i % 8}", f"P{i % 200:03d}", rnd.randrange(0, 50) if i % 13 else "",
                f"{rnd.randrange(-1000, 99999) / 100:.2f}" if i % 17 else "", "-1.50",
                f"2024-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}", "TRUE" if i % 2 else "FALSE",
            ])
    ps = ProjectStore.open(str(tmp_path / "big.npa.data"))
    try:
        import_csv_to_store(ps.store, "t_csv", path, {})
        project = make_project()
        timings: dict[str, float] = {}
        for label, expression in {
            "SUM": "SUM(t[amt])", "COUNT": "COUNT(t[qty])", "AVERAGE": "AVERAGE(t[amt])",
            "FILTERED SUM": "CALCULATE(SUM(t[amt]), t[region] = \"R3\")", "DISTINCTCOUNT": "DISTINCTCOUNT(t[product])",
        }.items():
            out = route_measure(project, expression, project_store=ps, budget_s=30.0)
            assert isinstance(out, StoreAnswer), out
            timings[label] = out.elapsed_s
        for label, seconds in timings.items():
            print(f"[measured] 1M rows {label}: {seconds * 1000:.0f} ms{' (over 50 ms)' if seconds > 0.05 else ''}")
        started = time.monotonic()
        for expression in ["SUM(t[amt])", "COUNT(t[qty])", "AVERAGE(t[amt])", "COUNTROWS(t)", "DISTINCTCOUNT(t[product])"] * 2:
            assert isinstance(route_measure(project, expression, project_store=ps, budget_s=30.0), StoreAnswer)
        print(f"[measured] 1M rows, 10 route_measure calls in a row: {time.monotonic() - started:.2f} s")
    finally:
        ps.close()


# ---------------------------------------------------------------------------------------------------
# Mutant proofs: each rule is broken on purpose (a module-level function or constant is patched) and the
# behaviour check for that rule must fail. A check that still passes on the mutant would prove nothing.
# ---------------------------------------------------------------------------------------------------
def check_shape_gate(env: Env) -> None:
    mixed = make_project(types=env.types, extra_tables=[{"id": "s2", "source_id": "s2", "name": "u", "column_types": {}}])
    out = route_measure(mixed, "COUNTROWS(t)", project_store=env.ps)
    assert isinstance(out, RouteRefusal) and out.code == "shape"
    related = make_project(types=env.types, relationships=[{"id": "r"}])
    out = route_measure(related, "COUNTROWS(t)", project_store=env.ps)
    assert isinstance(out, RouteRefusal) and out.code == "shape"
    out = route_measure(make_project(types=env.types, calculated=True), "COUNTROWS(t)", project_store=env.ps)
    assert isinstance(out, RouteRefusal) and out.code == "shape"


def test_mutant_shape_gate_open(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_shape_gate(env)
    monkeypatch.setattr(dax_route, "store_shape", lambda project, candidates=None: dax_route.StoreShape(True, "", "t"))
    with pytest.raises(AssertionError):
        check_shape_gate(env)


def check_busy_policy(fresh: Env) -> None:
    with fresh.ps.job():
        out = fresh.route("COUNTROWS(t)")
        assert isinstance(out, RouteRefusal) and out.code == "busy"


def test_mutant_job_not_taken(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    import contextlib

    check_busy_policy(fresh)

    @contextlib.contextmanager
    def no_job(self: Any) -> Any:
        yield None

    # The route runs without marking the store busy: the check sees a value, not the refusal.
    outer = fresh.ps.job
    with outer():
        monkeypatch.setattr(ProjectStore, "job", no_job)
        with pytest.raises(AssertionError):
            out = fresh.route("COUNTROWS(t)")
            assert isinstance(out, RouteRefusal) and out.code == "busy"


def check_timeout(fresh: Env) -> None:
    started = time.monotonic()
    out = fresh.route("COUNTROWS(t)", budget_s=0.2)
    assert isinstance(out, RouteRefusal) and out.code == "timeout", out
    assert time.monotonic() - started < 1.0


def test_mutant_budget_never_fires(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", _slow_execute)
    check_timeout(fresh)
    # (the slow query is about 0.5 s when nothing stops it, so the mutant run ends by itself)
    monkeypatch.setattr(dax_route._Budget, "start", lambda self: None)
    with pytest.raises(AssertionError):
        check_timeout(fresh)


def check_decimal_rebuild(fresh: Env) -> None:
    first = fresh.route("SUM(t[amt])")
    assert isinstance(first, StoreAnswer)
    rows = [list(r) for r in fresh.rows]
    rows[0][4] = "1.1234567"
    fresh.rows = rows
    fresh.reload_twin()
    fresh.ps.store.drop_table("t_csv")
    import_csv_to_store(fresh.ps.store, "t_csv", fresh.csv, {})
    second = fresh.route("SUM(t[amt])")
    assert isinstance(second, StoreAnswer), second


def test_mutant_plan_cached_across_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a").mkdir()
    clean = Env(tmp_path / "a")
    try:
        check_decimal_rebuild(clean)
    finally:
        clean.close()
    real = dax_route.plan_measure
    cache: dict[str, Any] = {}

    def cached(expression: str, **kwargs: Any) -> Any:
        if expression not in cache:
            cache[expression] = real(expression, **kwargs)
        return cache[expression]

    monkeypatch.setattr(dax_route, "plan_measure", cached)
    (tmp_path / "b").mkdir()
    mutated = Env(tmp_path / "b")
    try:
        with pytest.raises(AssertionError):
            check_decimal_rebuild(mutated)
    finally:
        mutated.close()


def check_reason_map() -> None:
    for name, text in _reason_constants().items():
        assert dax_route.fragment_for_reason(text) is not None, name


def test_mutant_reason_entry_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    check_reason_map()
    trimmed = dict(dax_route.FRAGMENTS)
    del trimmed[dax_whitelist.REASON_NESTED_CALCULATE]
    monkeypatch.setattr(dax_route, "FRAGMENTS", trimmed)
    with pytest.raises(AssertionError):
        check_reason_map()


def check_deadline(fresh: Env) -> None:
    out = fresh.route("COUNTROWS(t)", deadline=time.monotonic() - 1)
    assert isinstance(out, RouteRefusal) and out.code == "timeout" and out.message == dax_route.DEADLINE_MESSAGE


def test_mutant_deadline_ignored(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_deadline(fresh)
    real = dax_route.route_measure

    def ignoring(*args: Any, **kwargs: Any) -> Any:
        kwargs["deadline"] = None
        return real(*args, **kwargs)

    monkeypatch.setattr(Env, "route", lambda self, expression, **kw: ignoring(
        self.project, expression, project_store=self.ps, measures=kw.pop("measures", None), **kw))
    with pytest.raises(AssertionError):
        check_deadline(fresh)


def check_values_match_engine(env: Env) -> None:
    for expression in ("AVERAGE(t[amt])", "SUM(t[amt])", "CALCULATE(SUM(t[amt]), t[region] = \"East\")"):
        answer = env.route(expression)
        assert isinstance(answer, StoreAnswer) and same(answer.value, env.engine(expression)), expression


def test_mutant_wrong_value_is_caught(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_values_match_engine(env)
    real = dax_sql.convert_result
    monkeypatch.setattr(dax_sql, "convert_result", lambda cell, kind: (real(cell, kind) + Decimal(1)) if cell is not None else None)
    with pytest.raises(AssertionError):
        check_values_match_engine(env)


def check_group_total(env: Env) -> None:
    answer = env.route("SUM(t[qty])", group_by=("t", "region"))
    assert isinstance(answer, StoreAnswer)
    assert sum((v for _, v in answer.rows if v is not None), Decimal(0)) == env.route("SUM(t[qty])").value


def test_mutant_group_filter_dropped(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_group_total(env)
    real = dax_route.plan_group_by

    def dropping(expression: str, **kwargs: Any) -> Any:
        kwargs["filter_context"] = ()
        return real(expression, **kwargs)

    def with_filter() -> None:
        filtered = env.route("SUM(t[qty])", group_by=("t", "region"), filter_context=("t[product] = \"P01\"",))
        scalar = env.route("SUM(t[qty])", filter_context=("t[product] = \"P01\"",))
        assert sum((v for _, v in filtered.rows if v is not None), Decimal(0)) == scalar.value

    with_filter()
    monkeypatch.setattr(dax_route, "plan_group_by", dropping)
    with pytest.raises(AssertionError):
        with_filter()


# ---------------------------------------------------------------------------------------------------
# C2a2 item 1: an alias hides a nested CALCULATE
# ---------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def env2000(tmp_path_factory: pytest.TempPathFactory) -> Env:
    e = Env(tmp_path_factory.mktemp("route2000"), make_rows(2000))
    yield e
    e.close()


ALIAS_CASES_REFUSED: list[tuple[str, dict[str, str], int]] = [
    ("CALCULATE([B], t[qty] < 5)", {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "[A]"}, 7687),
    ("CALCULATE([C], t[qty] < 5)", {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "[A]", "C": "[B]"}, 7687),
    ("CALCULATE([B], t[region] = \"West\")", {"A": "CALCULATE(SUM(t[qty]), t[region] = \"East\")", "B": "[A]"}, 2449),
]


@pytest.mark.parametrize("expression,measures,engine_value", ALIAS_CASES_REFUSED)
def test_alias_chain_nested_calculate_is_refused_not_wrong(
    env2000: Env, expression: str, measures: dict[str, str], engine_value: int
) -> None:
    assert env2000.engine(expression, measures) == Decimal(engine_value)  # what the engine answers
    out = env2000.route(expression, measures=measures)
    assert isinstance(out, RouteRefusal) and out.code == "whitelist", out
    assert out.message == "This measure cannot be computed on a large table yet: it nests one CALCULATE inside another."


def test_alias_chain_on_another_column_agrees_with_the_engine(env2000: Env) -> None:
    measures = {"A": "CALCULATE(SUM(t[qty]), t[region] = \"East\")", "B": "[A]"}
    out = env2000.route("CALCULATE([B], t[qty] > 3)", measures=measures)
    assert isinstance(out, StoreAnswer)
    assert out.value == Decimal(2473) == env2000.engine("CALCULATE([B], t[qty] > 3)", measures)


def test_mutant_alias_chain_gate_open_gives_the_silent_wrong_value(env2000: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    expression, measures, engine_value = ALIAS_CASES_REFUSED[0]
    monkeypatch.setattr(dax_whitelist, "_alias_chain_columns", lambda body, measures_norm: set())
    out = env2000.route(expression, measures=measures)
    assert isinstance(out, StoreAnswer) and out.value != Decimal(engine_value)  # the bug the gate prevents


# ---------------------------------------------------------------------------------------------------
# C2a2 item 2: a call pays only for its own measures
# ---------------------------------------------------------------------------------------------------
def _wide_project_and_store(base: Path) -> tuple[ProjectStore, dict[str, Any]]:
    columns = [f"d{i}" for i in range(1, 9)]
    path = base / "w.csv"
    rnd = random.Random(3)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", *columns])
        for i in range(500):
            writer.writerow([i, *(f"{rnd.randrange(1, 99999) / 100:.2f}" for _ in columns)])
    ps = ProjectStore.open(str(base / "w.npa.data"))
    import_csv_to_store(ps.store, "t_csv", path, {})
    project = make_project(types={"id": "text", **{c: "decimal_number" for c in columns}}, measures=[
        {"name": f"M{i}", "expression": f"SUM(t[d{i}])"} for i in range(1, 9)
    ])
    return ps, project


def _columns_read_by_stamp_queries(ps: ProjectStore, project: dict[str, Any], measure: str) -> set[str]:
    seen: set[str] = set()
    real = DuckStore.execute

    def spy(self: Any, sql: str, params: Any = ()) -> Any:
        if "regexp_extract" in sql or "regexp_replace" in sql:
            seen.update(re.findall(r'"(d[1-8])"', sql))
        return real(self, sql, params)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DuckStore, "execute", spy)
        out = route_measure(project, measure, project_store=ps)
    assert isinstance(out, StoreAnswer), out
    return seen


def test_a_call_reads_decimal_stamps_only_for_its_own_measures(tmp_path: Path) -> None:
    ps, project = _wide_project_and_store(tmp_path)
    try:
        assert _columns_read_by_stamp_queries(ps, project, "M3") == {"d3"}
        project["model"]["measures"].append({"name": "Both", "expression": "[M3] + [M4]"})
        project["model"]["measures"].append({"name": "Chain", "expression": "CALCULATE([M5], t[d6] >= 1)"})
        assert _columns_read_by_stamp_queries(ps, project, "Chain") == {"d5", "d6"}
    finally:
        ps.close()


def test_mutant_closure_text_takes_every_measure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ps, project = _wide_project_and_store(tmp_path)
    try:
        assert _columns_read_by_stamp_queries(ps, project, "M3") == {"d3"}
        monkeypatch.setattr(
            dax_route, "_closure_text",
            lambda expression, measures, filter_context: "\n".join([expression, *measures.values()]).casefold(),
        )
        assert _columns_read_by_stamp_queries(ps, project, "M3") != {"d3"}
    finally:
        ps.close()


# ---------------------------------------------------------------------------------------------------
# C2a2 item 3 and 4: the timeout is reported as a timeout
# ---------------------------------------------------------------------------------------------------
def test_tiny_budget_never_shows_the_stale_or_metadata_text(fresh: Env) -> None:
    outcomes: dict[str, int] = {}
    for _ in range(150):
        out = fresh.route("SUM(t[amt])", budget_s=0.0003)
        kind = "answer" if isinstance(out, StoreAnswer) else out.code
        outcomes[kind] = outcomes.get(kind, 0) + 1
        assert kind in ("answer", "timeout"), (kind, out)
    assert outcomes.get("timeout", 0) > 0, outcomes
    assert fresh.ps.busy is False
    assert isinstance(fresh.route("SUM(t[amt])"), StoreAnswer)


def test_decimal_metadata_work_runs_inside_the_budget(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow_meta(store: Any, table: str, columns: list[str]) -> Any:
        store.execute("SELECT count(*) FROM range(10000000000)")  # about 0.5 s when nothing stops it
        return {}

    monkeypatch.setattr(dax_route, "column_decimal_meta", slow_meta)
    started = time.monotonic()
    out = fresh.route("SUM(t[amt])", budget_s=0.15)
    assert isinstance(out, RouteRefusal) and out.code == "timeout", out
    assert time.monotonic() - started < 0.4


def test_interrupt_between_two_queries_still_stops_the_next_one(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def two_steps(self: Any, store: Any) -> Any:
        store.execute("SELECT 1")
        time.sleep(0.2)  # the budget fires here, with no query running: that interrupt stops nothing
        return store.execute("SELECT count(*) FROM range(10000000000)")

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", two_steps)
    started = time.monotonic()
    out = fresh.route("COUNTROWS(t)", budget_s=0.05)
    assert isinstance(out, RouteRefusal) and out.code == "timeout", out
    assert time.monotonic() - started < 0.6


def test_unrelated_store_error_is_not_called_a_timeout(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def unrelated(self: Any, store: Any) -> Any:
        time.sleep(0.15)  # the budget (0.05 s) has fired by now
        raise StoreError("Query execution failed: Catalog Error: Table with name x does not exist")

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", unrelated)
    fired = fresh.route("COUNTROWS(t)", budget_s=0.05)
    quick = fresh.route("COUNTROWS(t)", budget_s=5.0)
    for out in (fired, quick):
        assert isinstance(out, RouteRefusal) and out.code == "plan", out
        assert "could not be read" in out.message


# ---------------------------------------------------------------------------------------------------
# C2a2 item 4 (R2) and 6: shape rule and Parquet
# ---------------------------------------------------------------------------------------------------
def test_two_store_tables_without_a_relationship_are_refused(env: Env) -> None:
    project = make_project(types=env.types, extra_tables=[
        {"id": "s2", "source_id": "s2", "name": "u", "column_types": {"a": "text"}}])
    project["data_sources"].append({"id": "s2", "kind": "csv", "store": {"table": "u_csv"}})
    assert route_is_available(project)
    assert store_shape(project).ok is False
    out = route_measure(project, "COUNTROWS(t)", project_store=env.ps)
    assert isinstance(out, RouteRefusal) and out.code == "shape"


def test_parquet_is_refused_first_with_its_own_sentence(env: Env) -> None:
    project = make_project(types=env.types, kind="parquet", measures=[{"name": "Bad", "expression": "CALCULATE(SUM(t[qty]), ALL(t))"}])
    out = route_measure(project, "Bad", project_store=env.ps)
    assert isinstance(out, RouteRefusal)
    assert out.message == "Bad cannot be computed on a large table yet: tables loaded from Parquet files cannot compute measures yet."
    assert "ALL" not in out.message


# ---------------------------------------------------------------------------------------------------
# C2a3: the whole chain, case variants, partial overlap (cases shared with tests/test_dax_whitelist.py)
# ---------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def env_chain(tmp_path_factory: pytest.TempPathFactory) -> Env:
    e = Env(tmp_path_factory.mktemp("route_chain"), make_rows(1500, seed=2))
    yield e
    e.close()


def _chain_cases() -> list[Any]:
    from tests.test_dax_whitelist import CHAIN_REFUSED

    return CHAIN_REFUSED


@pytest.mark.parametrize("index", range(9))
def test_chain_refused_never_a_different_number(env_chain: Env, index: int) -> None:
    expression, measures = _chain_cases()[index]
    out = env_chain.route(expression, measures=measures)
    assert isinstance(out, RouteRefusal) and out.code == "whitelist", out
    assert out.message == "This measure cannot be computed on a large table yet: it nests one CALCULATE inside another."


def test_chain_gate_open_would_give_a_different_number_on_these_tables(env_chain: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """The mutant (the chain gate open) is a wrong value on every refused case: this is what the refusal prevents."""
    cases = _chain_cases()
    expected = {i: env_chain.engine(expression, measures) for i, (expression, measures) in enumerate(cases)}
    monkeypatch.setattr(dax_whitelist, "_alias_chain_columns", lambda body, measures_norm: set())
    differing = 0
    for i, (expression, measures) in enumerate(cases):
        out = env_chain.route(expression, measures=measures)
        if isinstance(out, StoreAnswer) and not same(out.value, expected[i]):
            differing += 1
    assert differing == len(cases) == 9, differing


def test_chain_on_other_columns_agrees_with_the_engine(env_chain: Env) -> None:
    from tests.test_dax_whitelist import CHAIN_ALLOWED

    for expression, measures in CHAIN_ALLOWED:
        out = env_chain.route(expression, measures=measures)
        assert isinstance(out, StoreAnswer), (expression, out)
        assert same(out.value, env_chain.engine(expression, measures)), expression


# ---------------------------------------------------------------------------------------------------
# C2a3: a RUNTIME battery. Every reason the whitelist and the planner really return must have a plain sentence.
# ---------------------------------------------------------------------------------------------------
def _battery() -> list[tuple[str, dict[str, str] | None]]:
    """At least 150 (expression, measures) pairs from a generator over shapes, operators, types and bad inputs."""
    columns = list(TYPES)
    out: list[tuple[str, dict[str, str] | None]] = []
    aggregates = ["SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "COUNTBLANK", "DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK"]
    out += [(f"{agg}(t[{col}])", None) for agg in aggregates for col in columns]
    literals = ["1", "-1", "1.5", '"a"', '""', "DATE(2024, 1, 1)", "DATE(2024, 13, 40)", "BLANK()", "TRUE()", "TRUE",
                "99999999999999999999999", "0.12345678901234567890123456789012345678901", "t[qty]", "(1 + 1)", "-\"a\""]
    for col in columns:
        for op in ("=", "<>", "<", "<=", ">", ">=", "==", "!="):
            for literal in literals[::3] if op in ("==", "!=") else literals:
                out.append((f"CALCULATE(SUM(t[qty]), t[{col}] {op} {literal})", None))
    out += [(f"CALCULATE(COUNTROWS(t), t[{col}] IN {{{items}}})", None)
            for col in columns for items in ('"a", "b"', "1, 2", "", '"Ünï"', '"ss"', "DATE(2024, 1, 1)", "1, \"a\"")]
    out += [
        ("SUM(t[qty]", None), ("SUM(t[qty]))", None), ("SUM(t[qty]) SUM(t[qty])", None), ("", None), ("   ", None),
        ("SUM(", None), ("SUM()", None), ("SUM(t[qty], t[amt])", None), ("SUM(t)", None), ("COUNTROWS()", None),
        ("COUNTROWS(t, t)", None), ("COUNTROWS(u)", None), ("COUNTROWS(t[qty])", None), ("CALCULATE()", None),
        ("CALCULATE(t[qty])", None), ("CALCULATE(1)", None), ("1", None), ('"abc"', None), ("TRUE()", None), ("BLANK()", None),
        ("SUM(u[qty])", None), ("SUM(t[nope])", None), ("SUM(nope[qty])", None), ("[Nope]", None), ("SUM([qty])", None),
        ("VAR x = 1 RETURN SUM(t[qty])", None), ("SUM(t[qty]) + 1", None), ("SUM(t[qty]) / SUM(t[amt])", None),
        ("-SUM(t[qty])", None), ("DIVIDE(SUM(t[qty]), 2)", None), ("IF(TRUE(), 1, 2)", None),
        ("CALCULATE(SUM(t[qty]), t[qty] = 1 && t[amt] > 2)", None), ("CALCULATE(SUM(t[qty]), t[qty] = 1 || t[amt] > 2)", None),
        ("CALCULATE(SUM(t[qty]), t[qty] = 1 || t[qty] = 2 || t[region] = \"a\")", None),
        ("CALCULATE(SUM(t[qty]), NOT(t[qty] = 1))", None), ("CALCULATE(SUM(t[qty]), NOT(t[region] = \"a\"))", None),
        ("CALCULATE(SUM(t[qty]), NOT(t[qty] = 1, t[qty] = 2))", None), ("CALCULATE(SUM(t[qty]), t[qty] = 1 + 1)", None),
        ("CALCULATE(SUM(t[qty]), \"x\")", None), ("CALCULATE(SUM(t[qty]), TRUE())", None), ("CALCULATE(SUM(t[qty]), t[qty])", None),
        ("CALCULATE(SUM(t[qty]), 1 = t[qty])", None), ("CALCULATE(SUM(t[qty]), s[x] = 1)", None),
        ("CALCULATE(SUM(t[qty]), t[qty] = 1, t[qty] = 2, t[qty] = 3)", None),
        ("CALCULATE(SUM(t[qty]), t[region] = \"a\" || t[region] = \"b\")", None),
        ("CALCULATE(SUM(t[qty]), t[region] = \"a\x00b\")", None), ("CALCULATE(SUM(t[qty]), t[region] = \"a b\")", None),
        ("CALCULATE(SUM(t[qty]), t[region] IN {\"Ünï\"}, t[region] = \"x\")", None),
        ("CALCULATE(SUM(t[amt]), t[region] IN {\"a\"}, t[qty] > 1)", None),
        ("CALCULATE(SUM(t[amt]), t[region] IN {\"a\"}, t[region] = \"ß\")", None),
        ("CALCULATE(SUM(t[amt]), t[pay] IN {\"2024-01-01\"})", None),
        ("CALCULATE(SUM(t[amt]), t[amt] >= 1.00000000000000000000001)", None),
        ("CALCULATE(SUM(t[amt]), t[amt] = 1)", None), ("CALCULATE(SUM(t[qty]), t[qty] = 1.5)", None),
        ("CALCULATE(SUM(t[qty]), t[qty] = 9223372036854775808)", None),
        ("CALCULATE(SUM(t[qty]), t[pay] = DATE(1800, 1, 1))", None), ("CALCULATE(SUM(t[qty]), t[pay] = DATE(2024, 1))", None),
        ("CALCULATE(SUM(t[qty]), t[pay] = DATE(\"a\", 1, 1))", None),
        ("TOTALYTD(SUM(t[qty]), t[pay])", None), ("SAMEPERIODLASTYEAR(t[pay])", None), ("RELATED(u[x])", None),
        ("SUMX(t, t[qty])", None), ("AVERAGEX(t, t[amt])", None), ("COUNTX(t, t[qty])", None), ("MAXX(t, t[qty])", None),
        ("FILTER(t, t[qty] > 1)", None), ("ALL(t)", None), ("VALUES(t[region])", None), ("DISTINCT(t[region])", None),
        ("CALCULATE(SUM(t[qty]), ALL(t))", None), ("CALCULATE(SUM(t[qty]), ALL(t[qty]))", None),
        ("CALCULATE(SUM(t[qty]), FILTER(t, t[qty] > 1))", None), ("CALCULATE(SUM(t[qty]), KEEPFILTERS(t[qty] > 1))", None),
        ("CALCULATE(SUM(t[qty]), REMOVEFILTERS(t))", None), ("CALCULATE(SUM(t[qty]), USERELATIONSHIP(t[a], t[b]))", None),
        ("CALCULATE(CALCULATE(SUM(t[qty]), t[qty] > 1), t[qty] < 5)", None),
        ("CALCULATE(SUM(t[qty]) + 1, t[qty] > 1)", None), ("CALCULATE(DIVIDE(SUM(t[qty]), 1), t[qty] > 1)", None),
        ("CONCATENATEX(t, t[region])", None), ("FORMAT(SUM(t[qty]), \"0\")", None), ("SWITCH(1, 1, 2)", None),
        ("ISBLANK(SUM(t[qty]))", None), ("COUNTROWS(FILTER(t, t[qty] > 1))", None), ("CALCULATE(COUNTROWS(t), t)", None),
        ("MAX(t[region])", None), ("MIN(t[paid])", None), ("MAX(t[qty], t[amt])", None), ("MAX(1, 2)", None),
    ]
    chains: list[dict[str, str]] = [
        {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "[A]", "C": "[B]"},
        {"A": "SUM(t[qty])", "B": "[A] + 1"}, {"A": "[B]", "B": "[A]"}, {"A": "[A]"}, {"A": "SUMX(t, t[qty])", "B": "[A]"},
        {"A": "SUM(u[x])", "B": "[A]"}, {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "CALCULATE([A], t[qty] < 5)"},
        {"A": "CALCULATE(SUM(t[qty]), t[region] = \"East\")", "B": "[A]", "C": "CALCULATE([B], t[qty] > 3)", "D": "[C]"},
        {"A": "SUM(t[nope])", "B": "[A]"}, {"A": "SUM(t[qty]", "B": "[A]"},
    ]
    for chain in chains:
        last = list(chain)[-1]
        out += [(f"[{last}]", chain), (f"CALCULATE([{last}], t[qty] < 5)", chain), (f"CALCULATE([{last}], t[region] = \"West\")", chain),
                (f"CALCULATE([{last}], t[nope] = 1)", chain), (f"CALCULATE([{last}], t[qty] = 1, t[qty] = 2)", chain)]
    out += [("CALCULATE([Missing], t[qty] > 1)", {"A": "SUM(t[qty])"}), ("CALCULATE([A], u[x] = 1)", {"A": "SUM(t[qty])"})]
    return out


def _battery_reasons(env: Env) -> tuple[dict[str, str], int, list[str]]:
    """(reason -> how it was reached, number of expressions run, generic-sentence messages seen)."""
    reasons: dict[str, str] = {}
    generic: list[str] = []
    battery = _battery()
    tables = {"t": env.types}
    for expression, measures in battery:
        for part in dax_whitelist.classify_measure(expression, home_table="t", tables=tables, measures=measures).reasons:
            reasons.setdefault(part, f"classify_measure({expression!r})")
        out = env.route(expression, measures=measures)
        if isinstance(out, RouteRefusal):
            if out.code in ("whitelist", "plan", "stale"):
                for part in dax_route._split_reasons(out.reason):
                    reasons.setdefault(part, f"route_measure({expression!r})")
            if out.message.startswith(GENERIC_SENTENCE) or " - " in out.message:
                generic.append(f"{expression!r}: {out.message}")
    # Parquet kind and two tables go through the route's own gates
    parquet = make_project(types=env.types, kind="parquet")
    out = route_measure(parquet, "COUNTROWS(t)", project_store=env.ps)
    reasons.setdefault(out.reason, "route_measure(parquet)")
    two = make_project(types=env.types, extra_tables=[{"id": "s2", "source_id": "s2", "name": "u", "column_types": {}}])
    out = route_measure(two, "COUNTROWS(t)", project_store=env.ps)
    assert out.code == "shape"
    return reasons, len(battery) + 2, generic


@pytest.fixture(scope="module")
def env_small(tmp_path_factory: pytest.TempPathFactory) -> Env:
    e = Env(tmp_path_factory.mktemp("route_battery"), make_rows(300, seed=5))
    yield e
    e.close()


def test_runtime_battery_every_returned_reason_has_a_plain_sentence(env_small: Env, capsys: pytest.CaptureFixture[str]) -> None:
    reasons, count, generic = _battery_reasons(env_small)
    assert count >= 150, count
    unmapped = sorted(r for r in reasons if not dax_route.reason_is_mapped(r))
    with capsys.disabled():
        print(f"[measured] battery: {count} expressions, {len(reasons)} distinct reasons reached, {len(unmapped)} unmapped")
    assert len(reasons) >= 60, len(reasons)
    assert not unmapped, [(r, reasons[r]) for r in unmapped]
    assert not generic, generic[:5]


def test_mutant_battery_catches_a_missing_entry(env_small: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    kept = [item for item in dax_route._PROBLEMS if "Unsupported character" not in item[0].pattern]
    assert len(kept) == len(dax_route._PROBLEMS) - 1
    monkeypatch.setattr(dax_route, "_PROBLEMS", kept)
    with pytest.raises(AssertionError):
        test_runtime_battery_every_returned_reason_has_a_plain_sentence(env_small, _NoCapture())


class _NoCapture:
    def disabled(self) -> Any:
        import contextlib

        return contextlib.nullcontext()


# ---------------------------------------------------------------------------------------------------
# C2a4: joined reasons ('; '): each distinct reason once, in order, none hides another
# ---------------------------------------------------------------------------------------------------
_ORDERING = dax_whitelist.REASON_TEXT_ORDERING
_NESTED = dax_whitelist.REASON_NESTED_CALCULATE
_MISSING1 = "unknown column 'nope1' in table 't'"
_MISSING2 = "unknown column 'nope2' in table 't'"
_DATE = "DATE arguments are not a valid calendar date"
_BIG = "whole-number literal is outside the 64-bit range"
_ORDER_SENTENCE = "it compares text with < or >, whose order may differ from Power BI"
_LARGE = "M cannot be computed on a large table yet: "
# (joined reason, exact parts, exact final sentence for a measure named M)
SPLIT_CASES: list[tuple[str, list[str], str]] = [
    (f"{_MISSING1}; {_MISSING2}", [_MISSING1, _MISSING2],
     "M: Column 'nope1' was not found in table t. Column 'nope2' was not found in table t."),
    (f"{_DATE}; unknown column 'nope' in table 't'", [_DATE, "unknown column 'nope' in table 't'"],
     f"M: Column 'nope' was not found in table t. {_LARGE}a date in a filter is not a valid date."),
    (f"unknown column 'nope' in table 't'; {_BIG}", ["unknown column 'nope' in table 't'", _BIG],
     f"M: Column 'nope' was not found in table t. {_LARGE}a number in a filter does not fit a whole-number column."),
    # two known constants that hold '; ' themselves, repeated: one sentence
    (f"{_ORDERING}; {_ORDERING}", [_ORDERING, _ORDERING], f"{_LARGE}{_ORDER_SENTENCE}."),
    (f"{_ORDERING}; {_NESTED}; {_ORDERING}", [_ORDERING, _NESTED, _ORDERING],
     f"{_LARGE}{_ORDER_SENTENCE} and it nests one CALCULATE inside another."),
    (f"{_NESTED}; {_ORDERING}; unknown column 'nope' in table 't'", [_NESTED, _ORDERING, "unknown column 'nope' in table 't'"],
     f"M: Column 'nope' was not found in table t. {_LARGE}it nests one CALCULATE inside another and {_ORDER_SENTENCE}."),
    # an engine message that holds '; ' inside: both halves say the same, one sentence
    ("IN needs a table or at least one value; an empty table constructor {} is not accepted.",
     ["IN needs a table or at least one value", "an empty table constructor {} is not accepted."],
     "M: IN needs at least one value; an empty list is not allowed."),
]


@pytest.mark.parametrize("reason,parts,sentence", SPLIT_CASES)
def test_split_reasons_exact_parts_and_sentence(reason: str, parts: list[str], sentence: str) -> None:
    assert dax_route._split_reasons(reason) == parts
    assert message_for_reason("M", reason) == sentence


def test_split_reasons_never_returns_nothing() -> None:
    assert dax_route._split_reasons("") == [""]
    assert dax_route._split_reasons("single reason") == ["single reason"]


def test_message_keeps_two_missing_columns_apart_end_to_end(env: Env) -> None:
    out = env.route("CALCULATE(SUM(t[qty]), t[nope1] = 1, t[nope2] = 2)")
    assert isinstance(out, RouteRefusal)
    assert out.message == "Column 'nope1' was not found in table t. Column 'nope2' was not found in table t."
    out = env.route("CALCULATE(SUM(t[qty]), t[pay] = DATE(2024,13,40), t[nope] = 1)")
    assert "Column 'nope' was not found in table t." in out.message and "not a valid date" in out.message
    out = env.route("CALCULATE(SUM(t[qty]), t[qty] = 99999999999999999999999, t[nope] = 2)")
    assert "Column 'nope' was not found in table t." in out.message and "whole-number column" in out.message
    out = env.route("CALCULATE(SUM(t[qty]), t[region] > \"a\", t[region] < \"z\")")
    assert out.message.count("compares text with < or >") == 1


def test_split_reasons_takes_the_longest_known_text_first(monkeypatch: pytest.MonkeyPatch) -> None:
    short = dax_sql.REASON_PLAN_STALE  # "plan is stale; rebuild it"
    longer = f"{short} now; and again"
    monkeypatch.setattr(dax_route, "FRAGMENTS", {**dax_route.FRAGMENTS, longer: "it is stale for ever"})
    assert dax_route._split_reasons(f"{longer}; {_MISSING1}") == [longer, _MISSING1]
    assert dax_route._split_reasons(f"{short}; {_MISSING1}") == [short, _MISSING1]
