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
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from analytics_studio import dax_dates
from analytics_studio.file_import import parse_file
from analytics_studio.measures import evaluate_measures, normalize_measure
from analytics_studio.store import DuckStore, ProjectStore, dax_route, dax_sql, dax_whitelist, import_csv_to_store
from analytics_studio.store.base import StoreBusyError, StoreError
from analytics_studio.store.duck_store import StoreReader
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
    ("SUM(t[amt]) ^ 2", None),
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
# A query duckdb cannot fold to a constant: it runs for 10 s or more until an interrupt stops it
# (the older `SELECT count(*) FROM range(10000000000)` is answered in about 0.5 s by duckdb 1.5.5).
SLOW_SQL = "SELECT sum(hash(a)) FROM range(3000000000) r(a)"


# The same kind of query with an end of its own (about 1 s), for a mutant that switches the budget off.
BOUNDED_SLOW_SQL = "SELECT sum(hash(a)) FROM range(200000000) r(a)"


def _slow_execute(self: Any, store: Any) -> Any:
    return store.execute(SLOW_SQL)


def _bounded_slow_execute(self: Any, store: Any) -> Any:
    return store.execute(BOUNDED_SLOW_SQL)


def record_interrupts(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """An event that is set when any StoreReader gets an interrupt (the budget has fired)."""
    seen = threading.Event()
    real = StoreReader.interrupt

    def spy(self: Any) -> None:
        seen.set()
        real(self)

    monkeypatch.setattr(StoreReader, "interrupt", spy)
    return seen


def test_slow_plan_times_out_and_store_still_works(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(dax_sql.MeasurePlan, "execute", _slow_execute)
        out = fresh.route("COUNTROWS(t)", budget_s=0.2)
    assert isinstance(out, RouteRefusal) and out.code == "timeout", out  # a plan that finished would be an answer
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
    out = fresh.route("COUNTROWS(t)", budget_s=30.0, deadline=time.monotonic() + 3.0)
    assert isinstance(out, RouteRefusal) and out.code == "timeout"
    match = re.match(r"This measure took longer than ([0-9.]+) seconds", out.message)
    assert match is not None and 0.0 < float(match.group(1)) <= 3.0, out.message  # the capped budget, not 30 s


def test_duckstore_interrupt_then_normal_query(tmp_path: Path) -> None:
    import threading

    store = DuckStore(str(tmp_path / "i.db"))
    try:
        timer = threading.Timer(0.2, store.interrupt)
        timer.start()
        with pytest.raises(StoreError, match="(?i)interrupt"):
            store.execute(SLOW_SQL)
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
    """The busy policy is now the lease's: a lease that does not look at the busy flag is the mutant."""
    import contextlib

    check_busy_policy(fresh)

    @contextlib.contextmanager
    def no_busy_check(self: Any) -> Any:
        with self.store.reader() as reader:
            yield reader

    # The route runs although a job is open: the check sees a value, not the refusal.
    outer = fresh.ps.job
    with outer():
        monkeypatch.setattr(ProjectStore, "read_lease", no_busy_check)
        with pytest.raises(AssertionError):
            out = fresh.route("COUNTROWS(t)")
            assert isinstance(out, RouteRefusal) and out.code == "busy"


def check_timeout(fresh: Env) -> None:
    out = fresh.route("COUNTROWS(t)", budget_s=0.2)
    assert isinstance(out, RouteRefusal) and out.code == "timeout", out
    assert out.message.startswith("This measure took longer than 0.2 seconds"), out.message


def test_mutant_budget_never_fires(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", _slow_execute)
    check_timeout(fresh)
    # (the mutant run uses a slow query that ends by itself, because nothing stops it)
    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", _bounded_slow_execute)
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

    real_reader = StoreReader.execute

    def spy(self: Any, sql: str, params: Any = ()) -> Any:
        if "regexp_extract" in sql or "regexp_replace" in sql:
            seen.update(re.findall(r'"(d[1-8])"', sql))
        return real(self, sql, params)

    def spy_reader(self: Any, sql: str, params: Any = ()) -> Any:
        if "regexp_extract" in sql or "regexp_replace" in sql:
            seen.update(re.findall(r'"(d[1-8])"', sql))
        return real_reader(self, sql, params)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DuckStore, "execute", spy)
        patch.setattr(StoreReader, "execute", spy_reader)  # the route runs on a reader since C3a
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
        assert kind in ("answer", "timeout"), (kind, out)  # which of the two depends on speed; nothing else may show
    assert fresh.ps.busy is False
    assert isinstance(fresh.route("SUM(t[amt])"), StoreAnswer)


def test_an_interrupt_inside_a_guard_query_is_a_timeout_not_a_stale_or_metadata_refusal(
    fresh: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Speed-independent twin: the first statement of the call fails with an interrupt AFTER the budget has fired,
    as an interrupt landing inside a guard query does; the guard swallows it into a refusal, the route says timeout."""
    interrupted = record_interrupts(monkeypatch)
    real = StoreReader.execute
    state = {"failed": False}

    def execute(self: Any, sql: str, params: Any = ()) -> Any:
        if not state["failed"]:
            state["failed"] = True
            assert interrupted.wait(GUARD_S), "the budget never fired"
            raise StoreError("Query execution failed: INTERRUPT Error: Interrupted!")
        return real(self, sql, params)

    monkeypatch.setattr(StoreReader, "execute", execute)
    out = fresh.route("SUM(t[amt])", budget_s=0.05)
    assert isinstance(out, RouteRefusal) and out.code == "timeout", out
    assert state["failed"] is True


def test_decimal_metadata_work_runs_inside_the_budget(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow_meta(store: Any, table: str, columns: list[str]) -> Any:
        store.execute(SLOW_SQL)  # runs until the budget stops it
        return {}

    monkeypatch.setattr(dax_route, "column_decimal_meta", slow_meta)
    out = fresh.route("SUM(t[amt])", budget_s=0.15)
    assert isinstance(out, RouteRefusal) and out.code == "timeout", out
    assert out.message.startswith("This measure took longer than 0.15 seconds"), out.message


def test_interrupt_between_two_queries_still_stops_the_next_one(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    interrupted = record_interrupts(monkeypatch)

    def two_steps(self: Any, store: Any) -> Any:
        store.execute("SELECT 1")
        # The budget fires here, with no query running: that first interrupt stops nothing. Wait for it (an event,
        # not a sleep); the budget re-fires and the next one lands in the slow query.
        assert interrupted.wait(30.0), "the budget never fired"
        return store.execute(SLOW_SQL)

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", two_steps)
    out = fresh.route("COUNTROWS(t)", budget_s=0.05)
    assert isinstance(out, RouteRefusal) and out.code == "timeout", out
    assert out.message.startswith("This measure took longer than 0.05 seconds"), out.message


def test_unrelated_store_error_is_not_called_a_timeout(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    interrupted = record_interrupts(monkeypatch)

    def unrelated(self: Any, store: Any) -> Any:
        if store is not None and getattr(unrelated, "wait_for_budget", False):
            assert interrupted.wait(30.0), "the budget never fired"  # the budget (0.05 s) has fired by now
        raise StoreError("Query execution failed: Catalog Error: Table with name x does not exist")

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", unrelated)
    unrelated.wait_for_budget = True  # type: ignore[attr-defined]
    fired = fresh.route("COUNTROWS(t)", budget_s=0.05)
    unrelated.wait_for_budget = False  # type: ignore[attr-defined]
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
        # arithmetic (C4b): the forms that stay refused, each with its own sentence
        ("SUM(t[qty]) ^ 2", None), ("SUM(t[qty]) & 1", None), ("+SUM(t[qty])", None), ("MAX(t[pay]) - MIN(t[pay])", None),
        ("MIN(t[pay]) + 1", None), ("ROUND(SUM(t[amt]), 2) + 1", None), ("SUM(t[qty]) + SUMX(t, t[qty])", None),
        ("SUM(t[qty]) + 9223372036854775808", None), ("SUM(t[qty]) * 1e400", None), ("1 + 2", None), ("-(1)", None),
        ("DIVIDE(SUM(t[qty]), 0, BLANK())", None), ("DIVIDE(SUM(t[qty]), 0, SUM(t[amt]))", None),
        ("DIVIDE(SUM(t[qty]), 0, \"x\")", None), ("SUM(t[qty]) + SUM(t[region])", None), ("SUM(t[qty]) + COUNTROWS(u)", None),
        ("CALCULATE(SUM(t[qty]) + 1, t[qty] > 2)", None), ("IF(SUM(t[qty]) > 1, 1, 2) + 1", None),
        ("SUM(t[qty]) + SUM(u[x])", None), ("SUM(t[qty]) + [Nope]", None), ("DIVIDE(SUM(t[qty]), 2, 3, 4)", None),
        ("SUM(t[qty]) / CALCULATE(SUM(t[qty]), t[qty] = 1 && t[amt] > 2)", None),
        ("SUM(t[qty]) / CALCULATE(SUM(t[amt]), t[region] IN {\"a\"}, t[qty] > 1)", None),
        ("+".join(f"CALCULATE(SUM(t[qty]), t[qty] > {n})" for n in range(9)), None),  # nine different totals
        ("+".join(["1"] * 9), None), ("+".join(["(1+1)"] * 14), None),  # nine levels deep, more than 24 parts
        ("SUM(t[qty]) + COUNTROWS(t) * (1 + (2 + (3 + (4 + (5 + (6 + (7 + (8 + 9)))))))", None),
    ]
    chains: list[dict[str, str]] = [
        {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "[A]", "C": "[B]"},
        {"A": "SUM(t[qty])", "B": "[A] + 1"}, {"A": "[B]", "B": "[A]"}, {"A": "[A]"}, {"A": "SUMX(t, t[qty])", "B": "[A]"},
        {"A": "SUM(u[x])", "B": "[A]"}, {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "CALCULATE([A], t[qty] < 5)"},
        {"A": "CALCULATE(SUM(t[qty]), t[region] = \"East\")", "B": "[A]", "C": "CALCULATE([B], t[qty] > 3)", "D": "[C]"},
        {"A": "SUM(t[nope])", "B": "[A]"}, {"A": "SUM(t[qty]", "B": "[A]"},
        {"A": "SUM(t[qty]) / COUNTROWS(t)", "B": "CALCULATE([A], t[qty] > 2)"},
        {"A": "SUM(t[qty]) / COUNTROWS(t)", "B": "[A] * 2", "C": "CALCULATE([B], t[region] = \"East\")"},
        {"A": "[B] + 1", "B": "[A] * 2"}, {"A": "SUMX(t, t[qty])", "B": "[A] + 1"}, {"A": "SUM(t[qty])", "B": "[A] + [Nope]"},
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
    # C2b: the same expressions grouped by a text and by a number column, with and without a filter context, and
    # every filter shape through route_filter_context (a refusal of the whitelist carries its reason).
    contexts: list[tuple[str, ...]] = [(), ('t[product] = "P01"',), ('t[region] IN {"East", "West"}',), ("t[qty] > 3",)]
    for index, (expression, measures) in enumerate(battery):
        for offset, column in enumerate(("region", "qty")):
            out = dax_route.route_grouped(
                env.project, expression, ("t", column), project_store=env.ps, measures=measures,
                filter_context=contexts[(index + offset) % 4],
            )
            if isinstance(out, RouteRefusal):
                if out.code in ("whitelist", "plan", "stale"):
                    for part in dax_route._split_reasons(out.reason):
                        reasons.setdefault(part, f"route_grouped({expression!r}, {column})")
                if out.message.startswith(GENERIC_SENTENCE) or " - " in out.message:
                    generic.append(f"grouped {expression!r}: {out.message}")
    for filter_item in _filter_battery():
        out = dax_route.route_filter_context(env.project, [filter_item])
        if isinstance(out, RouteRefusal):
            if out.code == "whitelist":
                for part in dax_route._split_reasons(out.reason):
                    reasons.setdefault(part, f"route_filter_context({filter_item!r})")
            if out.message.startswith(GENERIC_SENTENCE) or " - " in out.message:
                generic.append(f"filter {filter_item!r}: {out.message}")
    parquet = make_project(types=env.types, kind="parquet")
    out = route_measure(parquet, "COUNTROWS(t)", project_store=env.ps)
    reasons.setdefault(out.reason, "route_measure(parquet)")
    two = make_project(types=env.types, extra_tables=[{"id": "s2", "source_id": "s2", "name": "u", "column_types": {}}])
    out = route_measure(two, "COUNTROWS(t)", project_store=env.ps)
    assert out.code == "shape"
    return reasons, len(battery) * 3 + 2, generic


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


# ---------------------------------------------------------------------------------------------------
# C2b: route_grouped, route_filter_context, route_distinct_values
# ---------------------------------------------------------------------------------------------------
def _flt(column: str, operator: str, value: Any = None, values: list[str] | None = None, logic: str = "and",
         table: str = "s1") -> dict[str, Any]:
    clause: dict[str, Any] = {"operator": operator}
    if values is not None:
        clause["values"] = values
    else:
        clause["value"] = "" if value is None else value
    return {"table_id": table, "column": column, "clauses": [clause], "logic": logic}


def _filter_battery() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for column in TYPES:
        for operator in dax_route._OPERATOR_LABELS:
            out.append(_flt(column, operator, "East"))
            out.append(_flt(column, operator, "4"))
            out.append(_flt(column, operator, values=["East", "West"]))
    out += [
        _flt("region", "equals", "a b"), _flt("region", "is_any_of", values=["Ünï", "ss"]),
        _flt("region", "is_any_of", values=[f"v{i}" for i in range(400)]),
        _flt("qty", "is_any_of", values=[str(i) for i in range(1, 60)]), _flt("qty", "equals", "1.5"),
        _flt("qty", "equals", "99999999999999999999999"), _flt("qty", "equals", "x"), _flt("nope", "equals", "1"),
        _flt("region", "equals", "East", table="other"), _flt("region", "is_any_of", values=[]),
        {"table_id": "s1", "column": "region", "clauses": [], "logic": "and"},
        {"table_id": "s1", "column": "region", "logic": "and"},
        {"table_id": "s1", "column": "qty", "logic": "and",
         "clauses": [{"operator": "greater_than", "value": "1"}, {"operator": "less_than", "value": "9"}]},
        {"table_id": "s1", "column": "qty", "logic": "or",
         "clauses": [{"operator": "greater_than", "value": "1"}, {"operator": "less_than", "value": "9"}]},
    ]
    return out


def _decimal_meta_for(env: Env) -> dict[tuple[str, str], Any]:
    wanted = [c for c, kind in env.types.items() if kind == "decimal_number"]
    found = dax_sql.column_decimal_meta(env.ps.store, "t_csv", wanted)
    return {("t", column): meta for column, meta in found.items()}


GROUPED_SHAPES: list[tuple[str, str, tuple[str, ...]]] = [
    ("SUM(t[qty])", "region", ()),
    ("SUM(t[amt])", "product", ()),
    ("COUNTROWS(t)", "pay", ()),
    ("AVERAGE(t[amt])", "region", ()),
    ("MIN(t[qty])", "paid", ()),
    ("COUNTROWS(t)", "region", ('t[product] = "P01"',)),
    ("SUM(t[qty])", "product", ('t[region] IN {"East", "West"}',)),
    ("DISTINCTCOUNT(t[product])", "region", ("t[qty] > 3",)),
    ("MAX(t[pay])", "region", ()),
    ("[Base]", "product", ('t[region] = "North"',)),
]


@pytest.mark.parametrize("expression,column,context", GROUPED_SHAPES)
def test_route_grouped_equals_the_group_by_plan(env: Env, expression: str, column: str, context: tuple[str, ...]) -> None:
    answer = dax_route.route_grouped(
        env.project, expression, ("t", column), project_store=env.ps, measures=MEASURES, filter_context=context
    )
    assert isinstance(answer, StoreAnswer) and answer.kind == "grouped", answer
    plan = dax_sql.plan_group_by(
        expression, group_by=("t", column), home_table="t", tables={"t": env.types}, store_tables={"t": "t_csv"},
        column_meta=_decimal_meta_for(env), measures=MEASURES, filter_context=context,
    )
    assert not isinstance(plan, dax_sql.Refusal), plan
    want = plan.execute(env.ps.store)
    assert answer.rows == want and answer.rows
    keys = [key for key, _ in answer.rows]
    assert len({key.casefold() for key in keys}) == len(keys)  # the planner folds keys: no two differ only by case


def test_route_grouped_cap_refuses_instead_of_cutting(env: Env) -> None:
    cut = dax_route.route_grouped(env.project, "COUNTROWS(t)", ("t", "id"), project_store=env.ps)
    assert isinstance(cut, RouteRefusal) and cut.code == "too_many"
    assert cut.message == "id has more than 2,000 groups; choose a column with fewer groups or filter first."
    exact = dax_route.route_grouped(env.project, "COUNTROWS(t)", ("t", "product"), project_store=env.ps, max_groups=20)
    assert isinstance(exact, StoreAnswer) and len(exact.rows) == 20  # exactly at the cap is allowed
    over = dax_route.route_grouped(env.project, "COUNTROWS(t)", ("t", "product"), project_store=env.ps, max_groups=19)
    assert isinstance(over, RouteRefusal) and over.message.startswith("product has more than 19 groups")


def test_route_grouped_own_sentences_and_no_type_names(env: Env) -> None:
    by_number = dax_route.route_grouped(env.project, "SUM(t[qty])", ("t", "qty"), project_store=env.ps)
    assert isinstance(by_number, RouteRefusal)
    assert by_number.message == "Large tables can only group by text, date or yes/no columns for now."
    slicer = dax_route.route_grouped(
        env.project, "SUM(t[qty])", ("t", "region"), project_store=env.ps, filter_context=('t[region] = "East"',)
    )
    assert isinstance(slicer, RouteRefusal)
    assert slicer.message == (
        "A slicer on region cannot be used with a visual grouped by the same column on a large table yet."
    )
    own = dax_route.route_grouped(
        env.project, 'CALCULATE(SUM(t[qty]), t[region] = "East")', ("t", "region"), project_store=env.ps
    )
    assert isinstance(own, RouteRefusal) and "CALCULATE filter of its own" in own.message
    for refusal in (by_number, slicer, own):
        assert not re.search(r"whole_number|decimal_number|string|group_by|plan", refusal.message), refusal.message


def test_route_grouped_wrong_arguments_raise(env: Env) -> None:
    with pytest.raises(TypeError):
        dax_route.route_grouped(env.project, "COUNTROWS(t)", "region", project_store=env.ps)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        dax_route.route_grouped(env.project, "COUNTROWS(t)", ("t", "region"), project_store=None)
    with pytest.raises(TypeError):
        dax_route.route_grouped(env.project, "COUNTROWS(t)", ("t", "region"), project_store=env.ps, filter_context=[])  # type: ignore[arg-type]


def test_label_for_key_gives_the_in_memory_text() -> None:
    assert dax_route.label_for_key("1/5/2022", "date") == "2022-01-05"
    assert dax_route.label_for_key("12/31/2024", "date") == "2024-12-31"
    assert dax_route.label_for_key("", "date") == ""
    assert dax_route.label_for_key("not a date", "date") == "not a date"
    assert dax_route.label_for_key("1/5/2022", "text") == "1/5/2022"  # only a date column is rewritten


def test_route_grouped_date_keys_read_like_the_in_memory_labels(env: Env) -> None:
    answer = dax_route.route_grouped(env.project, "COUNTROWS(t)", ("t", "pay"), project_store=env.ps)
    assert isinstance(answer, StoreAnswer)
    assert "/" in answer.rows[1][0]  # the planner's key is m/d/yyyy; the controller turns it into the label
    labels = [dax_route.label_for_key(key, "date") for key, _ in answer.rows]
    assert labels[0] == "" and all(re.fullmatch(r"\d{4}-\d\d-\d\d", label) for label in labels[1:])


def test_route_grouped_timeout_and_busy(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    with fresh.ps.job():
        busy = dax_route.route_grouped(fresh.project, "COUNTROWS(t)", ("t", "region"), project_store=fresh.ps)
    assert isinstance(busy, RouteRefusal) and busy.code == "busy" and busy.message == dax_route.BUSY_MESSAGE
    monkeypatch.setattr(dax_sql.GroupByPlan, "execute", _slow_execute)
    slow = dax_route.route_grouped(
        fresh.project, "COUNTROWS(t)", ("t", "region"), project_store=fresh.ps, budget_s=0.2
    )
    assert isinstance(slow, RouteRefusal) and slow.code == "timeout" and "took longer than 0.2 seconds" in slow.message
    expired = dax_route.route_grouped(
        fresh.project, "COUNTROWS(t)", ("t", "region"), project_store=fresh.ps, deadline=time.monotonic() - 1.0
    )
    assert isinstance(expired, RouteRefusal) and expired.message == dax_route.DEADLINE_MESSAGE
    monkeypatch.undo()
    again = dax_route.route_grouped(fresh.project, "COUNTROWS(t)", ("t", "region"), project_store=fresh.ps)
    assert isinstance(again, StoreAnswer)


# --- route_filter_context ---------------------------------------------------------------------------
ALLOWED_FILTERS: list[tuple[dict[str, Any], tuple[str, ...]]] = [
    (_flt("region", "equals", "East"), ("'t'[region] = \"East\"",)),
    (_flt("REGION", "equals", "East"), ("'t'[region] = \"East\"",)),  # the column is found whatever its case
    (_flt("Qty", "greater_than", "3"), ("'t'[qty] > 3",)),
    (_flt("region", "is_any_of", values=["East", "West"]), ("'t'[region] IN {\"East\", \"West\"}",)),
    (_flt("region", "is_any_of", values=["East", "East"]), ("'t'[region] = \"East\"",)),
    (_flt("region", "equals", 'say "hi"'), ("'t'[region] = \"say \"\"hi\"\"\"",)),
    (_flt("qty", "equals", "4"), ("'t'[qty] = 4",)),
    (_flt("qty", "greater_than", "3"), ("'t'[qty] > 3",)),
    (_flt("qty", "greater_than_or_equal", "1"), ("'t'[qty] >= 1",)),
    (_flt("qty", "less_than", "-1"), ("'t'[qty] < -1",)),
    (_flt("qty", "less_than_or_equal", "-2"), ("'t'[qty] <= -2",)),
    (_flt("qty", "is_any_of", values=["1", "2"]), ("'t'[qty] = 1 || 't'[qty] = 2",)),
    ({"table_id": "s1", "column": "qty", "logic": "and",
      "clauses": [{"operator": "greater_than", "value": "1"}, {"operator": "less_than", "value": "-1"}]},
     ("'t'[qty] > 1", "'t'[qty] < -1")),
]


@pytest.mark.parametrize("item,expected", ALLOWED_FILTERS)
def test_route_filter_context_allowed_shapes(env: Env, item: dict[str, Any], expected: tuple[str, ...]) -> None:
    out = dax_route.route_filter_context(env.project, [item])
    assert out == expected, out


def test_route_filter_context_joins_several_filters_and_accepts_none(env: Env) -> None:
    assert dax_route.route_filter_context(env.project, []) == ()
    out = dax_route.route_filter_context(
        env.project, [_flt("region", "equals", "East"), _flt("qty", "greater_than", "3")]
    )
    assert out == ("'t'[region] = \"East\"", "'t'[qty] > 3")


def test_route_filter_context_round_trips_the_apps_value_tokens(env: Env) -> None:
    from analytics_studio.controller import _encode_report_filter_value

    out = dax_route.route_filter_context(env.project, [
        _flt("region", "is_any_of", values=[_encode_report_filter_value("East"), _encode_report_filter_value("West")]),
        _flt("qty", "is_any_of", values=[_encode_report_filter_value("4"), _encode_report_filter_value(5)]),
        _flt("product", "equals", _encode_report_filter_value("__npa_pqv1__:odd")),
    ])
    assert out == (
        "'t'[region] IN {\"East\", \"West\"}", "'t'[qty] = 4 || 't'[qty] = 5", "'t'[product] = \"__npa_pqv1__:odd\"",
    )
    for blank in (_encode_report_filter_value(""), _encode_report_filter_value(None), ""):
        refused = dax_route.route_filter_context(env.project, [_flt("region", "is_any_of", values=["East", blank])])
        assert isinstance(refused, RouteRefusal) and "a blank value cannot be chosen" in refused.message
    mismatch = dax_route.route_filter_context(env.project, [_flt("region", "equals", _encode_report_filter_value(5))])
    assert isinstance(mismatch, RouteRefusal) and "not plain text" in mismatch.message
    bad = dax_route.route_filter_context(env.project, [_flt("region", "equals", "__npa_pqv1__:value:!!")])
    assert isinstance(bad, RouteRefusal) and "not plain text" in bad.message


REFUSED_FILTERS: list[tuple[dict[str, Any], str]] = [
    (_flt("region", "not_equals", "East"),
     "The filter on region (is not) cannot be used on a large table yet: only 'is' and 'is any of' work on a text column."),
    (_flt("region", "is_none_of", values=["East"]),
     "The filter on region (is none of) cannot be used on a large table yet: only 'is' and 'is any of' work on a text column."),
    (_flt("region", "contains", "Ea"), "The filter on region (contains) cannot be used on a large table yet"),
    (_flt("region", "begins_with", "Ea"), "The filter on region (begins with) cannot be used on a large table yet"),
    (_flt("region", "is_blank"), "The filter on region (is blank) cannot be used on a large table yet"),
    (_flt("region", "equals", ""), "a blank value cannot be chosen"),
    (_flt("region", "is_any_of", values=[]), "no value is chosen"),
    (_flt("qty", "not_equals", "3"), "The filter on qty (is not) cannot be used on a large table yet: this kind of filter does not work on a number column."),
    (_flt("qty", "is_none_of", values=["3"]), "The filter on qty (is none of) cannot be used on a large table yet"),
    (_flt("qty", "is_not_blank"), "The filter on qty (is not blank) cannot be used on a large table yet"),
    (_flt("qty", "less_than", "5"), "it would also select blank cells, which a large table counts as 0"),
    (_flt("qty", "less_than_or_equal", "0"), "it would also select blank cells"),
    (_flt("qty", "greater_than_or_equal", "0"), "it would also select blank cells"),
    (_flt("qty", "greater_than", "-1"), "it would also select blank cells"),
    (_flt("qty", "equals", "0"), "it would also select blank cells"),
    (_flt("qty", "is_any_of", values=["3", "0"]), "it would also select blank cells"),
    (_flt("qty", "equals", "x"), "a chosen value is not a number"),
    (_flt("qty", "equals", "NaN"), "a chosen value is not a number"),
    (_flt("qty", "greater_than", "Infinity"), "a chosen value is not a number"),
    (_flt("qty", "less_than", "-Infinity"), "a chosen value is not a number"),
    (_flt("qty", "is_any_of", values=["3", "sNaN"]), "a chosen value is not a number"),
    (_flt("qty", "equals", "1.5"), "The filter on qty (is) cannot be computed on a large table yet: a number in a filter does not fit"),
    (_flt("amt", "equals", "1"), "a decimal number column cannot be filtered yet"),
    (_flt("pay", "greater_than", "2024-01-01"), "a date column cannot be filtered yet"),
    (_flt("pay", "relative_date"), "The filter on pay (relative date) cannot be used on a large table yet"),
    (_flt("pay", "relative_time"), "The filter on pay (relative time) cannot be used on a large table yet"),
    (_flt("region", "top_n"), "The filter on region (Top N) cannot be used on a large table yet"),
    (_flt("region", "report_month", "2024-01"), "The filter on region (month is) cannot be used on a large table yet"),
    (_flt("region", "equals", "East", table="other"), "it belongs to another table"),
    (_flt("nope", "equals", "East"), "Column 'nope' was not found in table t."),
    (_flt("qty", "greater_than", "1", logic="or") | {"clauses": [
        {"operator": "greater_than", "value": "1"}, {"operator": "less_than", "value": "-9"}]},
     "two conditions joined by OR are not available"),
    (_flt("region", "equals", "a b"), "special space character"),
    (_flt("region", "is_any_of", values=[f"v{i}" for i in range(400)]), "holds too many items"),
]


@pytest.mark.parametrize("item,text", REFUSED_FILTERS)
def test_route_filter_context_refused_shapes_name_the_field_and_the_type(env: Env, item: dict[str, Any], text: str) -> None:
    out = dax_route.route_filter_context(env.project, [item])
    assert isinstance(out, RouteRefusal), out
    assert text in out.message, out.message
    assert item["column"] in out.message
    assert not re.search(r"whole_number|decimal_number|\bstring\b|plan|duckdb", out.message), out.message
    assert out.message.endswith(".")


def test_route_filter_context_refuses_what_the_whitelist_refuses_even_when_the_shape_is_allowed(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = _flt("region", "equals", "a b")
    assert isinstance(dax_route.route_filter_context(env.project, [item]), RouteRefusal)
    monkeypatch.setattr(
        dax_whitelist, "classify_filter_context",
        lambda *a, **k: dax_whitelist.WhitelistDecision(True, "t", "filter_context", ()),
    )
    assert dax_route.route_filter_context(env.project, [item]) == ('\'t\'[region] = "a b"',)


def test_route_filter_context_shape_gate(env: Env) -> None:
    mixed = make_project(types=env.types, extra_tables=[{"id": "s2", "source_id": "s2", "name": "u", "column_types": {}}])
    out = dax_route.route_filter_context(mixed, [_flt("region", "equals", "East")])
    assert isinstance(out, RouteRefusal) and out.code == "shape" and out.message == dax_route.MIXED_MODEL_REASON
    with pytest.raises(TypeError):
        dax_route.route_filter_context([], [])  # type: ignore[arg-type]


def test_filter_context_with_an_alias_chain_equals_the_engine_or_is_refused(env: Env) -> None:
    """A slicer or report filter with an alias chain of measures: DAX replaces, never ANDs, the inner filter."""
    chain = {
        "A": 'CALCULATE(SUM(t[qty]), t[region] = "East")', "B": "[A]", "C": "[B]",
        "D": "CALCULATE([C], t[qty] > 3)", "Plain": "SUM(t[qty])",
    }
    other_column = ('t[product] = "P01"',)
    for name in ("B", "C", "D", "Plain"):
        answer = env.route(name, measures=chain, filter_context=other_column)
        assert isinstance(answer, StoreAnswer), (name, answer)
        want = env.engine(f"CALCULATE([{name}], t[product] = \"P01\")", chain)
        assert same(answer.value, want), (name, answer.value, want)
    for name in ("A", "B", "C", "D"):
        for same_column in (('t[region] = "West"',), ('t[region] IN {"West", "North"}',)):
            answer = env.route(name, measures=chain, filter_context=same_column)
            assert isinstance(answer, RouteRefusal), (name, same_column, answer)
            assert "a slicer filters the same column as the formula" in answer.message
    # The silent wrong value the refusal prevents: the engine REPLACES the inner East filter by West.
    replaced = env.engine('CALCULATE([B], t[region] = "West")', chain)
    anded = env.route("Plain", measures=chain, filter_context=('t[region] = "East"', 't[region] = "West"'))
    assert not same(replaced, anded.value if isinstance(anded, StoreAnswer) else None)
    # The same alias chain grouped by the column its CALCULATE filter is on: refused (DAX replaces the group filter)
    grouped = dax_route.route_grouped(
        env.project, "C", ("t", "region"), project_store=env.ps, measures=chain, filter_context=other_column
    )
    assert isinstance(grouped, RouteRefusal) and "CALCULATE filter of its own" in grouped.message
    # Grouped by ANOTHER column the chain's filter is simply ANDed: equal to the engine group by group.
    by_pay = dax_route.route_grouped(
        env.project, "C", ("t", "pay"), project_store=env.ps, measures=chain, filter_context=other_column
    )
    assert isinstance(by_pay, StoreAnswer) and by_pay.rows
    for key, value in by_pay.rows:
        month, day, year = key.split("/") if key else ("", "", "")
        key_filter = f"t[pay] = DATE({year}, {int(month)}, {int(day)})" if key else "t[pay] = BLANK()"  # pay is a date
        want = env.engine(f"CALCULATE([C], t[product] = \"P01\", {key_filter})", chain)
        assert same(value, want), (key, value, want)
    # A plain measure, grouped, with a slicer on another column equals the engine group by group.
    plain = dax_route.route_grouped(
        env.project, "Plain", ("t", "region"), project_store=env.ps, measures=chain, filter_context=other_column
    )
    assert isinstance(plain, StoreAnswer)
    for key, value in plain.rows:
        want = env.engine(f"CALCULATE([Plain], t[product] = \"P01\", t[region] = \"{key}\")", chain)
        assert same(value, want), (key, value, want)


def test_slicer_on_the_group_column_is_refused_for_every_filter_form(env: Env) -> None:
    for predicate in ('t[region] = "East"', 't[region] IN {"East", "West"}'):
        out = dax_route.route_grouped(
            env.project, "SUM(t[qty])", ("t", "region"), project_store=env.ps, filter_context=(predicate,)
        )
        assert isinstance(out, RouteRefusal) and out.message.startswith("A slicer on region cannot be used")
    ok = dax_route.route_grouped(
        env.project, "SUM(t[qty])", ("t", "region"), project_store=env.ps, filter_context=('t[product] = "P01"',)
    )
    assert isinstance(ok, StoreAnswer)


# --- route_distinct_values ---------------------------------------------------------------------------
def test_route_distinct_values_first_spelling_once_in_first_seen_order(env: Env) -> None:
    values = dax_route.route_distinct_values(env.project, "t", "region", project_store=env.ps)
    assert isinstance(values, list)
    assert [v.casefold() for v in values].count("east") == 1  # East, east, EAST are one value
    assert len(values) == len({v.casefold() for v in values}) == 5
    assert "" in values  # the blank cells are one value, the empty text
    assert values == [key for key, _ in dax_route.route_grouped(
        env.project, "COUNTROWS(t)", ("t", "region"), project_store=env.ps).rows]


def test_route_distinct_values_search_limit_and_empty(env: Env) -> None:
    found = dax_route.route_distinct_values(env.project, "t", "product", project_store=env.ps, search="p1")
    assert found == sorted(found, key=lambda v: 0) and all("p1" in v.lower() for v in found) and len(found) == 10
    assert dax_route.route_distinct_values(env.project, "t", "product", project_store=env.ps, search="  P0  ")
    assert dax_route.route_distinct_values(env.project, "t", "product", project_store=env.ps, search="zzz") == []
    # the search text never reaches the SQL: quotes and SQL words are only text
    for hostile in ("'; DROP TABLE t_csv; --", '" OR 1=1 --', "%", "\\", "\x00"):
        assert dax_route.route_distinct_values(env.project, "t", "product", project_store=env.ps, search=hostile) == []
    assert dax_route.route_distinct_values(env.project, "t", "id", project_store=env.ps, limit=5000)  # 3,000 values
    many = dax_route.route_distinct_values(env.project, "t", "id", project_store=env.ps)
    assert isinstance(many, RouteRefusal) and many.code == "too_many"
    assert many.message == "id has more than 1,000 different values; choose a column with fewer values."
    narrow = dax_route.route_distinct_values(env.project, "t", "id", project_store=env.ps, search="99", limit=1000)
    assert isinstance(narrow, list) and len(narrow) < 1000  # the limit counts the matches
    number = dax_route.route_distinct_values(env.project, "t", "qty", project_store=env.ps)
    assert isinstance(number, RouteRefusal)
    assert number.message == "Large tables can only list the values of text, date or yes/no columns for now."
    narrow_context = ('t[region] = "North"', "t[qty] = 4")
    with_filter = dax_route.route_distinct_values(
        env.project, "t", "product", project_store=env.ps, filter_context=narrow_context
    )
    every = dax_route.route_distinct_values(env.project, "t", "product", project_store=env.ps)
    assert isinstance(with_filter, list) and isinstance(every, list)
    assert 0 < len(with_filter) < len(every) == 20  # only the values that still have rows
    assert env.route("COUNTROWS(t)", filter_context=narrow_context, group_by=("t", "product")).rows
    assert with_filter == [k for k, _ in env.route("COUNTROWS(t)", filter_context=narrow_context, group_by=("t", "product")).rows]


def test_route_distinct_values_empty_table_and_null_cells(tmp_path: Path) -> None:
    import pyarrow as pa

    ps = ProjectStore.open(str(tmp_path / "x.npa.data"))
    try:
        empty = pa.RecordBatch.from_arrays([pa.array([], type=pa.string()), pa.array([], type=pa.string())], names=["region", "qty"])
        ps.store.create_table_from_arrow("t_csv", [("region", "text"), ("qty", "text")], [empty])
        project = make_project(types={"region": "text", "qty": "whole_number"})
        assert dax_route.route_distinct_values(project, "t", "region", project_store=ps) == []
    finally:
        ps.close()
    ps = ProjectStore.open(str(tmp_path / "y.npa.data"))
    try:
        batch = pa.RecordBatch.from_arrays(
            [pa.array(["a", None, "", "b", None, "a"]), pa.array(["1", "2", "3", "4", "5", "6"])], names=["region", "qty"]
        )
        ps.store.create_table_from_arrow("t_csv", [("region", "text"), ("qty", "text")], [batch])
        project = make_project(types={"region": "text", "qty": "whole_number"})
        # blank, NULL and the empty text are ONE value, listed as the empty text where it is first seen
        assert dax_route.route_distinct_values(project, "t", "region", project_store=ps) == ["a", "", "b"]
    finally:
        ps.close()


def test_route_distinct_values_wrong_types_raise(env: Env) -> None:
    with pytest.raises(TypeError):
        dax_route.route_distinct_values(env.project, "t", "region", project_store=env.ps, search=None)  # type: ignore[arg-type]


def test_route_distinct_values_busy_and_timeout(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    with fresh.ps.job():
        busy = dax_route.route_distinct_values(fresh.project, "t", "region", project_store=fresh.ps)
    assert isinstance(busy, RouteRefusal) and busy.code == "busy"
    monkeypatch.setattr(dax_sql.GroupByPlan, "execute", _slow_execute)
    slow = dax_route.route_distinct_values(fresh.project, "t", "region", project_store=fresh.ps, budget_s=0.2)
    assert isinstance(slow, RouteRefusal) and slow.code == "timeout"


# --- the app's order, applied after the store returns -------------------------------------------------------
def _ordering_controller() -> Any:
    from PySide6.QtWidgets import QApplication

    from analytics_studio.controller import StudioController

    QApplication.instance() or QApplication(["dax_route_order"])
    return StudioController()


def test_store_rows_get_the_app_order_and_lose_blank_values() -> None:
    controller = _ordering_controller()
    rows: list[tuple[str, Any]] = [
        ("b", Decimal(2)), ("B2", Decimal(3)), ("", Decimal(1)), ("A", Decimal(4)), ("c", None), ("a1", Decimal("0.5")),
    ]
    out = controller._store_ordered_rows(rows, "tid", "region", "tid")
    # case-folded label order, the blank key first, the key whose value is None dropped
    assert [item["label"] for item in out] == ["", "A", "a1", "b", "B2"]
    assert [item["value"] for item in out] == [1.0, 4.0, 0.5, 2.0, 3.0]
    assert all(isinstance(item["value"], float) for item in out)


def test_store_rows_with_equal_folded_labels_are_ordered_by_the_exact_label() -> None:
    """The store never returns two keys that differ only by case (it folds them), but the helper must still be total."""
    controller = _ordering_controller()
    out = controller._store_ordered_rows([("north", Decimal(1)), ("North", Decimal(2))], "tid", "region", "tid")
    assert [item["label"] for item in out] == ["North", "north"]


def test_store_rows_follow_the_model_sort_order_when_it_is_complete_and_fall_back_when_a_key_is_missing() -> None:
    from analytics_studio.power_query_values import cell_key

    controller = _ordering_controller()
    rows: list[tuple[str, Any]] = [("A", Decimal(1)), ("B", Decimal(2)), ("C", Decimal(3))]
    controller._column_sort_orders[("tid", "region")] = {
        cell_key("A"): ("3", ()), cell_key("B"): ("1", ()), cell_key("C"): ("2", ()),
    }
    assert [i["label"] for i in controller._store_ordered_rows(rows, "tid", "region", "tid")] == ["B", "C", "A"]
    # an order that lacks one of the keys is not used (as _active_model_column_sort_order does today)
    del controller._column_sort_orders[("tid", "region")][cell_key("C")]
    assert [i["label"] for i in controller._store_ordered_rows(rows, "tid", "region", "tid")] == ["A", "B", "C"]
    # an order of another table is not used either
    controller._column_sort_orders[("other", "region")] = {cell_key("A"): ("9", ()), cell_key("B"): ("1", ()), cell_key("C"): ("2", ())}
    assert [i["label"] for i in controller._store_ordered_rows(rows, "other", "region", "tid")] == ["A", "B", "C"]


def test_mutant_order_helper_keeps_the_store_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from analytics_studio.controller import StudioController

    monkeypatch.setattr(StudioController, "_ordered_category_keys", staticmethod(lambda keys, order, fallback: list(keys)))
    with pytest.raises(AssertionError):
        test_store_rows_get_the_app_order_and_lose_blank_values()


def test_mutant_model_order_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    from analytics_studio.controller import StudioController

    monkeypatch.setattr(StudioController, "_active_model_column_sort_order", lambda *a, **k: None)
    with pytest.raises(AssertionError):
        test_store_rows_follow_the_model_sort_order_when_it_is_complete_and_fall_back_when_a_key_is_missing()


class _Candidate:
    is_store_backed = True
    kind = "csv"
    store_table = "t_csv"


def test_grouped_filter_and_distinct_routes_take_the_controllers_candidates(env: Env) -> None:
    project = make_project(types=env.types)
    project["data_sources"] = [{"id": "s1", "kind": "csv"}]  # no `store` entry: only the candidates say it is a store table
    assert isinstance(dax_route.route_grouped(project, "COUNTROWS(t)", ("t", "region"), project_store=env.ps), RouteRefusal)
    candidates = {"s1": _Candidate()}
    answer = dax_route.route_grouped(project, "COUNTROWS(t)", ("t", "region"), project_store=env.ps, candidates=candidates)
    assert isinstance(answer, StoreAnswer) and answer.rows
    values = dax_route.route_distinct_values(project, "t", "region", project_store=env.ps, candidates=candidates)
    assert isinstance(values, list) and values
    assert isinstance(dax_route.route_distinct_values(project, "t", "region", project_store=env.ps), RouteRefusal)
    assert dax_route.route_filter_context(project, [_flt("region", "equals", "East")], candidates=candidates) == (
        "'t'[region] = \"East\"",
    )
    assert isinstance(dax_route.route_filter_context(project, [_flt("region", "equals", "East")]), RouteRefusal)


def test_a_quote_in_a_table_name_and_a_bracket_in_a_column_name_are_escaped_in_the_predicates() -> None:
    project = {
        "model": {"tables": [{"id": "s1", "source_id": "s1", "name": "o'brien sales",
                              "column_types": {"Reg]ion": "text", "qty": "whole_number"}}], "measures": [], "relationships": []},
        "data_sources": [{"id": "s1", "kind": "csv", "store": {"table": "t_csv"}}],
    }
    out = dax_route.route_filter_context(project, [
        _flt("Reg]ion", "is_any_of", values=["East", "West"]), _flt("qty", "greater_than", "3"),
    ])
    assert out == ("'o''brien sales'[Reg]]ion] IN {\"East\", \"West\"}", "'o''brien sales'[qty] > 3"), out
    assert dax_route._dax_name("a'b") == "'a''b'" and dax_route._dax_column("a'b", "c]d") == "'a''b'[c]]d]"


def test_slicer_message_finds_the_group_column_whatever_its_case(env: Env) -> None:
    out = dax_route.route_grouped(
        env.project, "SUM(t[qty])", ("T", "REGION"), project_store=env.ps, filter_context=('t[region] = "East"',)
    )
    assert isinstance(out, RouteRefusal)
    assert out.message == "A slicer on REGION cannot be used with a visual grouped by the same column on a large table yet."


# ===================================================================================================
# Stage C3a: the route runs on a read cursor under a read lease, can be canceled, and takes plain data
# ===================================================================================================
GUARD_S = 30.0  # hang guard for Event.wait / Thread.join only; an elapsed time is never asserted


def run_in_thread(fn: Any) -> tuple[threading.Thread, dict[str, Any]]:
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - the test reads it
            box["error"] = exc

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread, box


def finish(thread: threading.Thread, box: dict[str, Any]) -> Any:
    thread.join(GUARD_S)
    assert not thread.is_alive(), "the route call did not end"
    assert "error" not in box, box.get("error")
    return box["result"]


def make_slow_plan() -> tuple[Any, threading.Event, list[bool]]:
    """A MeasurePlan.execute that signals `started`, then runs a query that only an interrupt ends."""
    started = threading.Event()
    finished: list[bool] = []

    def execute(self: Any, store: Any) -> Any:
        started.set()
        out = store.execute(SLOW_SQL)
        finished.append(True)  # reached only when nothing stopped the query
        return out

    return execute, started, finished


def test_route_runs_on_a_reader_under_a_lease_and_never_sets_busy(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def spy(self: Any, store: Any) -> Any:
        seen["is_reader"] = isinstance(store, StoreReader)
        seen["readers"] = fresh.ps._readers
        seen["busy"] = fresh.ps.busy
        seen["open_readers"] = len(fresh.ps.store._readers)
        return store.execute("SELECT count(*) FROM t_csv")

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", spy)
    out = fresh.route("COUNTROWS(t)")
    assert isinstance(out, StoreAnswer)
    assert seen == {"is_reader": True, "readers": 1, "busy": False, "open_readers": 1}
    assert fresh.ps._readers == 0 and fresh.ps.store._readers == set()  # lease and cursor are closed again


def test_route_never_touches_the_main_connection(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the route used the main connection")

    monkeypatch.setattr(DuckStore, "execute", forbidden)
    monkeypatch.setattr(ProjectStore, "job", forbidden)
    monkeypatch.setattr(ProjectStore, "store", property(forbidden))
    for expression in ("COUNTROWS(t)", "SUM(t[qty])", "CALCULATE(SUM(t[amt]), t[region] = \"East\")"):
        assert isinstance(fresh.route(expression), StoreAnswer)
    assert isinstance(dax_route.route_grouped(fresh.project, "COUNTROWS(t)", ("t", "region"), project_store=fresh.ps), StoreAnswer)
    assert isinstance(dax_route.route_distinct_values(fresh.project, "t", "region", project_store=fresh.ps), list)


def test_the_grid_connection_is_free_while_the_route_runs(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """A route query on a reader and a data-grid call on the main connection run at the same time."""
    slow, started, finished = make_slow_plan()
    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", slow)
    thread, box = run_in_thread(lambda: fresh.route("COUNTROWS(t)", budget_s=GUARD_S))
    try:
        assert started.wait(GUARD_S)
        assert fresh.ps.store.execute("SELECT count(*) FROM t_csv") == [(len(fresh.rows),)]  # no "store is busy"
        assert len(fresh.ps.store.read_page("t_csv", 0, 5)) == 5
    finally:
        for _ in range(int(GUARD_S / 0.05)):  # the shutdown path's interrupt ends the slow query (sent again: one may be early)
            fresh.ps.request_cancel_readers()
            thread.join(0.05)
            if not thread.is_alive():
                break
    out = finish(thread, box)
    assert finished == []
    assert isinstance(out, RouteRefusal) and out.code not in ("timeout", "canceled"), out


def test_lease_held_twin_job_is_refused_and_the_route_still_answers(fresh: Env) -> None:
    with fresh.ps.read_lease():
        with pytest.raises(StoreBusyError):
            with fresh.ps.job():
                pass
        out = fresh.route("COUNTROWS(t)")  # two leases at once are allowed
        assert isinstance(out, StoreAnswer) and out.value == Decimal(len(fresh.rows))
        assert fresh.ps.busy is False
    assert fresh.ps._readers == 0
    with fresh.ps.job():
        pass


def test_route_with_a_reader_takes_no_lease_and_no_job(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the route took its own lease or job")

    with fresh.ps.read_lease() as reader:
        monkeypatch.setattr(ProjectStore, "read_lease", forbidden)
        monkeypatch.setattr(ProjectStore, "job", forbidden)
        out = fresh.route("SUM(t[qty])", reader=reader)
        grouped = dax_route.route_grouped(
            fresh.project, "COUNTROWS(t)", ("t", "region"), project_store=fresh.ps, reader=reader
        )
        values = dax_route.route_distinct_values(fresh.project, "t", "region", project_store=fresh.ps, reader=reader)
        assert isinstance(out, StoreAnswer) and isinstance(grouped, StoreAnswer) and isinstance(values, list)
        assert not reader.closed  # the lease is the caller's: the route does not close the reader
        assert fresh.ps._readers == 1


def test_route_with_a_reader_works_while_a_job_is_busy_is_the_callers_lease_policy(fresh: Env) -> None:
    """With a reader the route does not look at the busy flag: the caller leased it, a job cannot start under it."""
    with fresh.ps.read_lease() as reader:
        with pytest.raises(StoreBusyError):
            with fresh.ps.job():
                pass
        assert isinstance(fresh.route("COUNTROWS(t)", reader=reader), StoreAnswer)


def test_route_rejects_wrong_reader_and_cancel_types(env: Env) -> None:
    with pytest.raises(TypeError):
        route_measure(env.project, "COUNTROWS(t)", project_store=env.ps, reader=object())
    with pytest.raises(TypeError):
        route_measure(env.project, "COUNTROWS(t)", project_store=env.ps, cancel=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        route_measure(env.project, "COUNTROWS(t)", project_store=object())


# --- cancel ---------------------------------------------------------------------------------------------
def check_canceled(out: Any) -> None:
    assert isinstance(out, RouteRefusal), out
    assert out.code == dax_route.CODE_CANCELED == "canceled"
    assert out.message == "Canceled." and out.reason == "canceled by the user"


def test_cancel_set_before_the_call_gives_canceled_and_runs_nothing(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[bool] = []

    def never(self: Any, store: Any) -> Any:
        ran.append(True)  # (an error raised here would be swallowed by the route: record it instead)
        raise AssertionError("must not run after cancel")

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", never)
    monkeypatch.setattr(dax_sql.GroupByPlan, "execute", never)
    cancel = threading.Event()
    cancel.set()
    check_canceled(fresh.route("COUNTROWS(t)", cancel=cancel))
    assert ran == []
    check_canceled(dax_route.route_grouped(
        fresh.project, "COUNTROWS(t)", ("t", "region"), project_store=fresh.ps, cancel=cancel))
    check_canceled(dax_route.route_distinct_values(fresh.project, "t", "region", project_store=fresh.ps, cancel=cancel))
    assert ran == []
    assert fresh.ps._readers == 0 and fresh.ps.busy is False


def test_cancel_during_a_slow_query_stops_it_and_gives_canceled(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    slow, started, finished = make_slow_plan()
    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", slow)
    cancel = threading.Event()
    thread, box = run_in_thread(lambda: fresh.route("COUNTROWS(t)", budget_s=GUARD_S, cancel=cancel))
    assert started.wait(GUARD_S)
    cancel.set()
    check_canceled(finish(thread, box))
    assert finished == []  # the query did not end by itself
    assert fresh.ps._readers == 0 and fresh.ps.busy is False
    monkeypatch.undo()  # the store is usable again
    assert fresh.route("COUNTROWS(t)").value == Decimal(len(fresh.rows))


def test_cancel_during_a_grouped_query_with_a_leased_reader(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()
    finished: list[bool] = []

    def slow(self: Any, store: Any) -> Any:
        started.set()
        out = store.execute(SLOW_SQL)
        finished.append(True)
        return out

    monkeypatch.setattr(dax_sql.GroupByPlan, "execute", slow)
    cancel = threading.Event()
    with fresh.ps.read_lease() as reader:
        thread, box = run_in_thread(lambda: dax_route.route_grouped(
            fresh.project, "COUNTROWS(t)", ("t", "region"), project_store=fresh.ps, budget_s=GUARD_S, cancel=cancel,
            reader=reader))
        assert started.wait(GUARD_S)
        cancel.set()
        check_canceled(finish(thread, box))
        assert finished == []
        assert reader.execute("SELECT 5") == [(5,)]  # the leased reader is still usable after the interrupt


def test_canceled_beats_timeout(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """Budget and cancel both fired: the answer is the cancel."""
    interrupted = record_interrupts(monkeypatch)
    cancel = threading.Event()

    def both(self: Any, store: Any) -> Any:
        assert interrupted.wait(GUARD_S), "the budget never fired"  # the budget (0.05 s) has fired
        cancel.set()
        return store.execute(SLOW_SQL)  # stopped by the re-fired interrupt: a timeout AND a cancel

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", both)
    out = fresh.route("COUNTROWS(t)", budget_s=0.05, cancel=cancel)
    check_canceled(out)


def test_timeout_still_wins_when_no_cancel_is_set(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", _slow_execute)
    cancel = threading.Event()
    out = fresh.route("COUNTROWS(t)", budget_s=0.1, cancel=cancel)
    assert isinstance(out, RouteRefusal) and out.code == "timeout", out
    assert not cancel.is_set()


def test_canceled_beats_stale(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    cancel = threading.Event()

    def stale(self: Any, store: Any) -> Any:
        cancel.set()
        return dax_sql.Refusal(dax_sql.REASON_PLAN_STALE)

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", stale)
    check_canceled(fresh.route("COUNTROWS(t)", cancel=cancel))

    def stale_alone(self: Any, store: Any) -> Any:
        return dax_sql.Refusal(dax_sql.REASON_PLAN_STALE)

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", stale_alone)
    out = fresh.route("COUNTROWS(t)", cancel=threading.Event())  # no cancel: the stale reason still shows
    assert isinstance(out, RouteRefusal) and out.code == "stale"


def test_cancel_set_after_the_answer_was_computed_never_returns_a_value(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    cancel = threading.Event()
    real = dax_sql.MeasurePlan.execute

    def late(self: Any, store: Any) -> Any:
        value = real(self, store)
        cancel.set()  # the user cancels just as the answer is ready
        return value

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", late)
    check_canceled(fresh.route("COUNTROWS(t)", cancel=cancel))


def test_cancel_set_while_the_budget_is_closing_never_returns_a_value(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """The cancel arrives after the answer was checked and before the route returns (inside the budget's own close)."""
    cancel = threading.Event()
    real_cancel = dax_route._Budget.cancel

    def cancel_then_close(self: Any) -> None:
        cancel.set()
        real_cancel(self)

    monkeypatch.setattr(dax_route._Budget, "cancel", cancel_then_close)
    check_canceled(fresh.route("COUNTROWS(t)", cancel=cancel))


def test_cancel_with_an_error_inside_the_plan_is_still_canceled(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    cancel = threading.Event()

    def boom(self: Any, store: Any) -> Any:
        cancel.set()
        raise StoreError("Query execution failed: INTERRUPT Error: Interrupted!")

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", boom)
    check_canceled(fresh.route("COUNTROWS(t)", cancel=cancel))


def test_an_interrupt_from_another_source_is_not_a_cancel_and_not_a_timeout(fresh: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def other(self: Any, store: Any) -> Any:
        stop = threading.Event()

        def pump() -> None:  # e.g. a shutdown: neither the budget nor the cancel event interrupts
            while not stop.wait(0.05):
                store.interrupt()

        pumper = threading.Thread(target=pump, daemon=True)
        pumper.start()
        try:
            return store.execute(SLOW_SQL)
        finally:
            stop.set()
            pumper.join(GUARD_S)

    monkeypatch.setattr(dax_sql.MeasurePlan, "execute", other)
    cancel = threading.Event()
    out = fresh.route("COUNTROWS(t)", budget_s=GUARD_S, cancel=cancel)
    assert isinstance(out, RouteRefusal) and out.code not in ("timeout", "canceled"), out
    assert "interrupt" in out.reason.casefold()


def test_the_battery_with_an_unset_cancel_event_changes_nothing_and_a_set_one_is_always_canceled(env_small: Env) -> None:
    battery = _battery()[:60]
    unset, is_set = threading.Event(), threading.Event()
    is_set.set()
    for expression, measures in battery:
        plain = env_small.route(expression, measures=measures)
        guarded = env_small.route(expression, measures=measures, cancel=unset)
        assert type(plain) is type(guarded)
        if isinstance(plain, RouteRefusal):
            assert (plain.code, plain.reason, plain.message) == (guarded.code, guarded.reason, guarded.message)
        else:
            assert plain.value == guarded.value
        canceled = env_small.route(expression, measures=measures, cancel=is_set)
        check_canceled(canceled)
        assert dax_route.reason_is_mapped(canceled.reason)  # the reason has its plain sentence in the reason map


# --- the budget -----------------------------------------------------------------------------------------
def test_budget_fires_at_the_budget_and_refires_until_cancelled() -> None:
    calls = threading.Semaphore(0)
    count = [0]

    def interrupt() -> None:
        count[0] += 1
        calls.release()

    budget = dax_route._Budget(interrupt, 0.01)
    budget.start()
    assert calls.acquire(timeout=GUARD_S) and calls.acquire(timeout=GUARD_S) and calls.acquire(timeout=GUARD_S)
    assert budget.fired.is_set() and not budget.canceled.is_set()
    budget.cancel()
    after = count[0]
    budget._thread.join(GUARD_S)  # type: ignore[union-attr]
    assert not budget._thread.is_alive()  # type: ignore[union-attr]
    assert count[0] == after  # nothing arrives after cancel() returned


def test_budget_without_cancel_event_does_not_fire_before_its_budget_and_ends_with_cancel() -> None:
    fired: list[int] = []
    budget = dax_route._Budget(lambda: fired.append(1), 3600.0)
    budget.start()
    budget.cancel()
    budget._thread.join(GUARD_S)  # type: ignore[union-attr]
    assert not budget._thread.is_alive()  # a budget of an hour ended at once: it waits on an event, not on a clock
    assert fired == [] and not budget.fired.is_set()


def test_budget_fires_when_the_cancel_event_is_set_long_before_the_budget() -> None:
    cancel = threading.Event()
    hit = threading.Event()
    budget = dax_route._Budget(hit.set, 3600.0, cancel)
    budget.start()
    cancel.set()
    assert hit.wait(GUARD_S)
    budget.cancel()
    assert budget.canceled.is_set() and not budget.fired.is_set()
    budget._thread.join(GUARD_S)  # type: ignore[union-attr]
    assert not budget._thread.is_alive()


def test_time_caps_are_the_planners_numbers() -> None:
    assert dax_route.DEFAULT_BUDGET_S == 0.5
    assert dax_route.GUI_LIST_BUDGET_S == 2.0
    assert dax_route.VALIDATE_BUDGET_S == 5.0
    assert dax_route.BACKGROUND_BUDGET_S == 30.0
    assert dax_route.DEFAULT_REFRESH_BUDGET_S == 1.5 and dax_route.DEFAULT_VISUAL_REFRESH_BUDGET_S == 2.0
    assert dax_route.MAX_GROUPS == 2000 and dax_route.DISTINCT_LIMIT == 1000


# --- reader twins of the two main-connection interrupt tests ----------------------------------------------
def test_reader_interrupt_then_normal_query(tmp_path: Path) -> None:
    store = DuckStore(str(tmp_path / "ri.db"))
    try:
        with store.reader() as reader:
            done = threading.Event()
            errors: list[BaseException] = []

            def run() -> None:
                try:
                    reader.execute(SLOW_SQL)
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)
                finally:
                    done.set()

            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            while not done.wait(0.05):  # an interrupt before the query starts is lost: send it again
                reader.interrupt()
            worker.join(GUARD_S)
            assert len(errors) == 1 and isinstance(errors[0], StoreError) and "interrupt" in str(errors[0]).casefold()
            assert reader.execute("SELECT 41 + 1") == [(42,)]
            reader.interrupt()  # idle interrupt does nothing
            assert reader.execute("SELECT 7") == [(7,)]
    finally:
        store.close()


def test_reader_interrupt_does_not_take_the_store_lock(tmp_path: Path) -> None:
    store = DuckStore(str(tmp_path / "rl.db"))
    try:
        with store.reader() as reader:
            with store._lock:  # another thread holds the lock, as a running main-connection query does
                done = threading.Event()
                worker = threading.Thread(target=lambda: (reader.interrupt(), store.interrupt_all_readers(), done.set()))
                worker.start()
                assert done.wait(GUARD_S), "reader.interrupt() waited for the store lock"
                worker.join()
    finally:
        store.close()


# --- snapshots ------------------------------------------------------------------------------------------
SNAPSHOT_EXPRESSIONS = ["COUNTROWS(t)", "SUM(t[qty])", "CALCULATE(SUM(t[amt]), t[region] = \"East\")", "[Base]", "[EastBase]"]


def snapshot_project(env: Env) -> dict[str, Any]:
    return make_project(types=env.types, measures=[
        {"name": "Base", "expression": "SUM(t[amt])"}, {"name": "EastBase", "expression": "CALCULATE([Base], t[region] = \"East\")"},
    ])


def answers(env: Env, project: Any, candidates: Any = None) -> list[Any]:
    out: list[Any] = []
    for expression in SNAPSHOT_EXPRESSIONS:
        a = route_measure(project, expression, project_store=env.ps, candidates=candidates)
        out.append((a.value if isinstance(a, StoreAnswer) else (a.code, a.reason)))
    g = dax_route.route_grouped(project, "SUM(t[qty])", ("t", "region"), project_store=env.ps, candidates=candidates)
    out.append(g.rows if isinstance(g, StoreAnswer) else (g.code, g.reason))
    d = dax_route.route_distinct_values(project, "t", "region", project_store=env.ps, candidates=candidates)
    out.append(d if isinstance(d, list) else (d.code, d.reason))
    f = dax_route.route_filter_context(project, [_flt("region", "equals", "East")], candidates=candidates)
    out.append(f if isinstance(f, tuple) else (f.code, f.reason))
    return out


def test_snapshot_gives_the_same_answers_as_the_live_project(env: Env) -> None:
    project = snapshot_project(env)
    live = answers(env, project)
    assert all(not (isinstance(item, tuple) and item and item[0] in ("shape", "plan", "closed")) for item in live[:5]), live
    snapshot = dax_route.snapshot_for_route(project)
    assert answers(env, snapshot) == live
    assert dax_route.store_shape(snapshot) == dax_route.store_shape(project)
    assert dax_route.route_is_available(snapshot) is True


def test_snapshot_with_candidates_gives_the_same_answers(env: Env) -> None:
    project = snapshot_project(env)
    project["data_sources"] = [{"id": "s1", "kind": "csv"}]  # only the candidates say it is a store table
    candidates = {"s1": _Candidate()}
    live = answers(env, project, candidates)
    assert isinstance(live[0], Decimal)
    snapshot = dax_route.snapshot_for_route(project, candidates)
    assert answers(env, snapshot) == live
    with pytest.raises(TypeError):
        route_measure(snapshot, "COUNTROWS(t)", project_store=env.ps, candidates=candidates)
    with pytest.raises(TypeError):
        dax_route.route_filter_context(snapshot, [], candidates=candidates)


def deep_modify(project: dict[str, Any]) -> None:
    model = project["model"]
    model["tables"][0]["name"] = "renamed"
    model["tables"][0]["column_types"].clear()
    model["tables"][0]["calculated_columns"] = [{"name": "x", "expression": "1"}]
    model["tables"].append({"id": "s2", "source_id": "s2", "name": "u", "column_types": {}})
    model["measures"].clear()
    model["relationships"].append({"id": "r"})
    project["data_sources"][0]["kind"] = "parquet"
    project["data_sources"][0]["store"]["table"] = "gone"


def test_deep_modifying_the_live_project_after_the_snapshot_does_not_change_the_answer(env: Env) -> None:
    project = snapshot_project(env)
    live = answers(env, project)
    snapshot = dax_route.snapshot_for_route(project)
    deep_modify(project)
    assert answers(env, project) != live  # the live project really changed
    assert answers(env, snapshot) == live


def walk_ids(node: Any, found: set[int]) -> None:
    if isinstance(node, (dict, list)):
        found.add(id(node))
        for part in (node.values() if isinstance(node, dict) else node):
            walk_ids(part, found)


def check_snapshot_isolated(project: dict[str, Any], snapshot: Any) -> None:
    before = dict(snapshot.measures)
    project["model"]["measures"][0]["expression"] = "changed"
    project["model"]["measures"].append({"name": "Extra", "expression": "COUNTROWS(t)"})
    assert dict(snapshot.measures) == before
    assert "Extra" not in snapshot.measures
    live_ids: set[int] = set()
    walk_ids(project, live_ids)
    view_ids: set[int] = set()
    walk_ids(snapshot.project_view(), view_ids)
    assert not (live_ids & view_ids)  # no dict or list of the live project is reachable from the snapshot


def test_snapshot_shares_nothing_with_the_live_project(env: Env) -> None:
    project = snapshot_project(env)
    project["model"]["relationships"] = []
    snapshot = dax_route.snapshot_for_route(project)
    check_snapshot_isolated(project, snapshot)
    with pytest.raises(TypeError):
        snapshot.measures["New"] = "COUNTROWS(t)"  # type: ignore[index]
    with pytest.raises(Exception):
        snapshot.tables = ()  # type: ignore[misc]
    first, second = snapshot.project_view(), snapshot.project_view()
    first["model"]["measures"].clear()
    first["model"]["tables"][0]["column_types"].clear()
    assert second["model"]["measures"] and second["model"]["tables"][0]["column_types"]  # a view is a fresh copy
    assert snapshot.project_view()["model"]["measures"]


def test_mutant_snapshot_shares_the_live_measures(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    project = snapshot_project(env)
    live = {m["name"]: m["expression"] for m in project["model"]["measures"]}
    check_snapshot_isolated(project, dax_route.snapshot_for_route(project))
    project = snapshot_project(env)
    live = project["model"]
    monkeypatch.setattr(dax_route, "_measure_map", lambda p, o: live.setdefault("map", {"Base": "SUM(t[amt])"}))
    snapshot = dax_route.snapshot_for_route(project)
    live["map"]["Base"] = "changed"
    assert snapshot.measures["Base"] == "changed"  # the shared mutant is visible to the isolation check
    with pytest.raises(AssertionError):
        project["model"]["measures"][0]["expression"] = "x"
        assert snapshot.measures["Base"] != "changed"


def test_route_snapshot_is_what_a_worker_thread_gets(env: Env) -> None:
    project = snapshot_project(env)
    snapshot = dax_route.snapshot_for_route(project)
    expected = env.route("SUM(t[qty])")
    deep_modify(project)  # the GUI thread keeps changing the live project while the worker runs
    thread, box = run_in_thread(lambda: route_measure(snapshot, "SUM(t[qty])", project_store=env.ps))
    out = finish(thread, box)
    assert isinstance(out, StoreAnswer) and out.value == expected.value


# --- F2: a table cannot be reloaded under a route that reads it ------------------------------------------
class _PausingReader:
    """Wraps a reader; the first statement that contains `marker` waits (the route is paused between statements)."""

    def __init__(self, reader: Any, marker: str, hit: threading.Event, go: threading.Event) -> None:
        self._reader, self._marker, self.hit, self.go = reader, marker, hit, go

    def execute(self, sql: str, params: Any = ()) -> Any:
        if self._marker in sql and not self.hit.is_set():
            self.hit.set()
            assert self.go.wait(GUARD_S), "the test never released the route"
        return self._reader.execute(sql, params)

    def interrupt(self) -> None:
        self._reader.interrupt()


def test_a_reload_under_a_running_route_is_refused_and_the_route_returns_the_old_correct_answer(fresh: Env) -> None:
    baseline = fresh.route("SUM(t[amt])")
    assert isinstance(baseline, StoreAnswer)
    rows2 = [list(r) for r in fresh.rows]
    for r in rows2:
        if r[4]:
            r[4] = f"{float(r[4]) + 0.000123:.6f}"
    csv2 = write_csv(fresh.base / "t2.csv", rows2)
    hit, go = threading.Event(), threading.Event()
    refused: list[BaseException] = []

    def reload_table(store: Any) -> None:
        store.drop_table("t_csv")
        import_csv_to_store(store, "t_csv", csv2, {})

    with fresh.ps.read_lease() as reader:
        paused = _PausingReader(reader, "SUM(TRY_CAST", hit, go)
        thread, box = run_in_thread(lambda: route_measure(
            fresh.project, "SUM(t[amt])", project_store=fresh.ps, reader=paused, budget_s=GUARD_S))
        try:
            assert hit.wait(GUARD_S), "the route never reached its main SUM"
            try:
                fresh.ps.call(reload_table)
            except StoreBusyError as exc:
                refused.append(exc)
        finally:
            go.set()
        out = finish(thread, box)
    assert len(refused) == 1  # the reload was refused
    assert isinstance(out, StoreAnswer) and out.value == baseline.value  # the OLD, correct answer
    assert fresh.ps.store.has_table("t_csv")
    reload_table(fresh.ps.store)  # no reader now: the reload goes through, and a fresh route sees the new data
    after = fresh.route("SUM(t[amt])")
    assert isinstance(after, StoreAnswer) and after.value != baseline.value


def test_a_refused_orphan_drop_leaves_the_table_and_does_not_raise(fresh: Env) -> None:
    from analytics_studio.controller import StudioController

    with fresh.ps.read_lease():
        StudioController._drop_orphan_table(None, fresh.ps, "t_csv")  # type: ignore[arg-type]
        assert fresh.ps.store.has_table("t_csv")  # left for the next cleanup, nothing lost
    StudioController._drop_orphan_table(None, fresh.ps, "t_csv")  # type: ignore[arg-type]
    assert not fresh.ps.store.has_table("t_csv")


def test_snapshot_keeps_calculated_columns_so_the_route_refuses_like_the_live_project(env: Env) -> None:
    project = make_project(types=env.types, calculated=True)
    live = route_measure(project, "COUNTROWS(t)", project_store=env.ps)
    assert isinstance(live, RouteRefusal) and live.code == "shape"
    snapshot = dax_route.snapshot_for_route(project)
    assert snapshot.tables[0].has_calculated_columns is True
    again = route_measure(snapshot, "COUNTROWS(t)", project_store=env.ps)
    assert isinstance(again, RouteRefusal) and (again.code, again.message) == (live.code, live.message)
    assert dax_route.store_shape(snapshot) == dax_route.store_shape(project)


# ---------------------------------------------------------------------------------------------------
# C4a: the runtime sentences of the two new refusals (a date before 1900, an own filter on the group column)
# ---------------------------------------------------------------------------------------------------
def test_runtime_old_date_and_own_group_filter_reasons_have_plain_sentences(tmp_path: Path) -> None:
    rows = make_rows(300, seed=5)
    pay_index = HEADERS.index("pay")
    rows[3][pay_index] = "1899-12-30"
    e = Env(tmp_path, rows)
    try:
        assert e.types["pay"] == "date", e.types
        answers = [
            e.route("MIN(t[pay])"),
            e.route('CALCULATE(COUNTROWS(t), t[pay] >= DATE(2024,1,1))'),
            dax_route.route_grouped(e.project, "COUNTROWS(t)", ("t", "pay"), project_store=e.ps),
        ]
        for out in answers:
            assert isinstance(out, RouteRefusal) and out.code == "plan", out
            assert "date before the year 1900" in out.message and dax_route.reason_is_mapped(out.reason), out
            assert not re.search(r"plan|guard|fold|duckdb", out.message, re.I), out.message
        own = dax_route.route_grouped(
            e.project, 'CALCULATE(SUM(t[qty]), t[region] = "East")', ("t", "region"), project_store=e.ps
        )
        assert isinstance(own, RouteRefusal) and own.code == "plan" and dax_route.reason_is_mapped(own.reason), own
        assert "on the column the results are grouped by" in own.message
        other = dax_route.route_grouped(
            e.project, 'CALCULATE(SUM(t[qty]), t[region] = "East")', ("t", "product"), project_store=e.ps
        )
        assert isinstance(other, StoreAnswer) and other.rows, other
    finally:
        e.close()
