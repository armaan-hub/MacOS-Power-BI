"""Tests for Stage C1b1: analytics_studio/store/dax_sql.py (DAX to DuckDB SQL for the store).

Values are checked against literal expected Decimal / DaxDateTime / None values worked out by hand from the
small tables below, and against the real engine through the rules tool (Rule A+). Every rule is killed by a
mutant: a module-level function, table or constant is patched, and the behaviour check that guards the rule
must fail. No test asserts on the text of generated SQL.
"""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest

from analytics_studio import dax_dates
from analytics_studio.store import DuckStore, import_csv_to_store
from analytics_studio.store.base import StoreError
from analytics_studio.store import dax_sql, dax_whitelist
from analytics_studio.store.dax_sql import (
    PARQUET_PLAN_REASON,
    ColumnMeta,
    MeasurePlan,
    Refusal,
    StoreResultLayer,
    column_decimal_meta,
    first_spelling_query,
    plan_measure,
)
from analytics_studio.store.dax_whitelist import (
    MAX_IN_ITEMS,
    MAX_NESTING,
    MAX_OR_TERMS,
    MAX_PREDICATES,
    MAX_TOKENS,
    REASON_CAP_IN_ITEMS,
    REASON_CAP_NESTING,
    REASON_CAP_OR_TERMS,
    REASON_CAP_PREDICATES,
    REASON_CAP_TOKENS,
    classify_measure,
)
from tools.store_engine_diff import build_formula_catalog, evaluate_exit_policy, plan_counts, run_comparison

# ---------------------------------------------------------------------------
# Small hand-checked table
#   n  x    d       dt          c       f
#   1  5    1.50    2024-02-29  "Ab "   TRUE
#   2  ''   0.25    ''          it's    FALSE
#   3  -2   ''      2026-06-01  ÄB      ''
#   4  7    -3.5    2023-01-15  ab      TRUE
#   5  100  10.125  2024-03-01  ''      FALSE
# ---------------------------------------------------------------------------
SMALL_CSV = (
    "n,x,d,dt,c,f\n"
    '1,5,1.50,2024-02-29,"Ab ",TRUE\n'
    "2,,0.25,,it's,FALSE\n"
    "3,-2,,2026-06-01,ÄB,\n"
    "4,7,-3.5,2023-01-15,ab,TRUE\n"
    "5,100,10.125,2024-03-01,,FALSE\n"
)
SMALL_TYPES = {
    "n": "whole_number", "x": "whole_number", "d": "decimal_number", "dt": "date", "c": "text", "f": "boolean",
}
TABLES = {"s": SMALL_TYPES}
STORE_TABLES = {"s": "s_csv"}


class Env:
    """A store holding SMALL_CSV plus the arguments plan_measure needs."""

    def __init__(self, base: Path, csv_text: str = SMALL_CSV, types: dict[str, str] | None = None) -> None:
        csv_path = base / "s.csv"
        csv_path.write_text(csv_text, encoding="utf-8")
        self.store = DuckStore(str(base / "s.db"))
        import_csv_to_store(self.store, "s_csv", csv_path, {})
        self.types = types or SMALL_TYPES
        columns = list(self.types)
        self.meta = {("s", c): m for c, m in column_decimal_meta(self.store, "s_csv", columns).items()}

    def plan(self, expression: str, **kwargs: Any) -> MeasurePlan | Refusal:
        return plan_measure(
            expression,
            home_table="s",
            tables={"s": self.types},
            store_tables=STORE_TABLES,
            column_meta=kwargs.pop("column_meta", self.meta),
            **kwargs,
        )

    def value(self, expression: str, **kwargs: Any) -> Any:
        plan = self.plan(expression, **kwargs)
        assert isinstance(plan, MeasurePlan), plan
        return plan.execute(self.store)


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Env:
    e = Env(tmp_path_factory.mktemp("small"))
    yield e
    e.store.close()


def _date(y: int, m: int, d: int) -> dax_dates.DaxDateTime:
    return dax_dates.from_datetime(dt.datetime(y, m, d))


def _is(value: Any, expected: Any) -> None:
    """Exact value, same Python class (Decimal, DaxDateTime or NoneType)."""
    assert type(value) is type(expected), (value, expected)
    assert value == expected, (value, expected)
    assert not isinstance(value, float)


def sum_n(env: Env, predicate: str) -> Any:
    return env.value(f"CALCULATE(SUM(s[n]), {predicate})")


# ---------------------------------------------------------------------------
# (b) hand-checked behaviour. Each check_* is used by a plain test and by the mutant tests.
# ---------------------------------------------------------------------------

def check_aggregates(env: Env) -> None:
    _is(env.value("SUM(s[x])"), Decimal(110))
    _is(env.value("SUM(s[d])"), Decimal("8.375"))
    _is(env.value("AVERAGE(s[x])"), Decimal("27.5"))
    _is(env.value("AVERAGE(s[d])"), Decimal("2.09375"))
    _is(env.value("MIN(s[x])"), Decimal(-2))
    _is(env.value("MAX(s[x])"), Decimal(100))
    _is(env.value("MIN(s[d])"), Decimal("-3.5"))
    _is(env.value("MAX(s[d])"), Decimal("10.125"))
    _is(env.value("COUNT(s[x])"), Decimal(4))
    _is(env.value("COUNT(s[dt])"), Decimal(4))
    _is(env.value("COUNTA(s[x])"), Decimal(5))
    _is(env.value("COUNTBLANK(s[x])"), Decimal(1))
    _is(env.value("COUNTBLANK(s[c])"), Decimal(1))
    _is(env.value("COUNTROWS(s)"), Decimal(5))
    _is(env.value("DISTINCTCOUNT(s[c])"), Decimal(4))  # ab, it's, Äb and the blank
    _is(env.value("DISTINCTCOUNT(s[dt])"), Decimal(5))  # four dates and the blank
    _is(env.value("DISTINCTCOUNT(s[f])"), Decimal(3))  # TRUE, FALSE and the blank


def test_aggregates_on_the_small_table(env: Env) -> None:
    check_aggregates(env)


def check_dates(env: Env) -> None:
    _is(env.value("MIN(s[dt])"), _date(2023, 1, 15))
    _is(env.value("MAX(s[dt])"), _date(2026, 6, 1))
    # leap day and the blank date (counts as 1899-12-30 in comparisons)
    _is(sum_n(env, "s[dt] >= DATE(2024, 2, 29)"), Decimal(9))   # rows 1, 3, 5
    _is(sum_n(env, "s[dt] > DATE(2024, 2, 29)"), Decimal(8))    # rows 3, 5
    _is(sum_n(env, "s[dt] <= DATE(2024, 2, 29)"), Decimal(7))   # rows 1, 2 (blank), 4
    _is(sum_n(env, "s[dt] < DATE(2024, 2, 29)"), Decimal(6))    # rows 2 (blank), 4
    _is(sum_n(env, "s[dt] <> DATE(2024, 2, 29)"), Decimal(14))  # all but row 1
    _is(env.value("CALCULATE(MIN(s[dt]), s[n] > 3)"), _date(2023, 1, 15))


def test_date_predicates_and_results(env: Env) -> None:
    check_dates(env)


def check_whole_predicates(env: Env) -> None:
    _is(sum_n(env, "s[x] = 0"), Decimal(2))       # the blank cell is 0
    _is(sum_n(env, "s[x] > -5"), Decimal(15))     # negative literal: the blank (0) and -2 are inside
    _is(sum_n(env, "s[x] < 0"), Decimal(3))
    _is(sum_n(env, "s[x] <= 0"), Decimal(5))
    _is(sum_n(env, "s[x] <> 5"), Decimal(14))
    _is(sum_n(env, "s[x] >= 7"), Decimal(9))
    _is(sum_n(env, "s[x] > 5"), Decimal(9))


def test_whole_number_predicates(env: Env) -> None:
    check_whole_predicates(env)


def check_not(env: Env) -> None:
    _is(sum_n(env, "NOT(s[x] = 5)"), Decimal(14))  # the blank row stays in: 0 <> 5


def test_not_over_whole_equality(env: Env) -> None:
    check_not(env)


def check_or(env: Env) -> None:
    _is(sum_n(env, "s[x] = 5 || s[x] = 0"), Decimal(3))  # rows 1 and 2 (blank)


def test_or_over_one_column(env: Env) -> None:
    check_or(env)


def check_decimal_predicates(env: Env) -> None:
    _is(sum_n(env, "s[d] >= 0"), Decimal(11))        # rows 1, 2, 3 (blank = 0), 5
    _is(sum_n(env, "s[d] < 0"), Decimal(4))
    _is(sum_n(env, "s[d] <> 0"), Decimal(12))        # rows 1, 2, 4, 5
    _is(sum_n(env, "s[d] >= 0.25"), Decimal(8))      # rows 1, 2, 5
    _is(sum_n(env, "s[d] < 0.00001"), Decimal(7))    # literal scale 5 beats column scale 4: rows 3 (0) and 4


def test_decimal_predicates(env: Env) -> None:
    check_decimal_predicates(env)


def test_decimal_literal_that_does_not_fit_is_refused(env: Env) -> None:
    wide = {**env.meta, ("s", "d"): ColumnMeta(scale=4, digits=36)}
    out = env.plan("CALCULATE(SUM(s[n]), s[d] >= 0.5)", column_meta=wide)
    assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_DECIMAL_LITERAL_FIT
    # a decimal column with no metadata is refused too (the scale is unknown)
    out = env.plan("SUM(s[d])", column_meta={})
    assert isinstance(out, Refusal)


def check_text_predicates(env: Env) -> None:
    _is(sum_n(env, 's[c] = "AB"'), Decimal(5))       # "Ab " folds to ab, and ab
    _is(sum_n(env, 's[c] = "ab "'), None)            # the literal is not trimmed
    _is(sum_n(env, 's[c] = "ÄB"'), Decimal(3))       # only A-Z fold: Ä stays, B becomes b
    _is(sum_n(env, 's[c] = "äb"'), None)             # ä is not Ä
    _is(sum_n(env, 's[c] = "IT\'S"'), Decimal(2))    # single quote inside the literal
    # the column holds the non-ASCII cell "ÄB": a text IN is refused (REASON_IN_NON_ASCII_COLUMN)
    plan = env.plan('CALCULATE(SUM(s[n]), s[c] IN {"AB", "it\'s"})')
    assert isinstance(plan, MeasurePlan), plan
    out = plan.execute(env.store)
    assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_IN_NON_ASCII_COLUMN, out
    _is(sum_n(env, 's[c] = ""'), Decimal(5))         # the blank cell


def test_text_predicates(env: Env) -> None:
    check_text_predicates(env)


def check_several_predicates_and_measures(env: Env) -> None:
    _is(env.value('CALCULATE(COUNTROWS(s), s[x] > 0, s[c] = "ab")'), Decimal(2))
    measures = {"Base": "SUM(s[x])", "Filt": 'CALCULATE(SUM(s[x]), s[c] = "ab")', "Twice": "[Base]"}
    _is(env.value("[Base]", measures=measures), Decimal(110))
    _is(env.value("[Twice]", measures=measures), Decimal(110))
    _is(env.value("CALCULATE([Base], s[n] > 2)", measures=measures), Decimal(105))
    _is(env.value("[Filt]", measures=measures), Decimal(12))
    out = env.plan("CALCULATE([Filt], s[n] > 2)", measures=measures)
    assert isinstance(out, Refusal)  # nested filters stay refused


def test_several_predicates_and_measure_references(env: Env) -> None:
    check_several_predicates_and_measures(env)


def check_empty_sets(env: Env) -> None:
    for expr in ("COUNTROWS(s)", "SUM(s[x])", "AVERAGE(s[x])", "COUNT(s[x])", "MAX(s[x])", "DISTINCTCOUNT(s[c])"):
        # filter every row away
        _is(env.value(f"CALCULATE({expr}, s[n] = 999)"), None)
    _is(env.value("CALCULATE(MIN(s[dt]), s[n] = 999)"), None)
    _is(env.value("CALCULATE(COUNTROWS(s), s[n] = 999)"), None)


def test_empty_filtered_set_is_blank(env: Env) -> None:
    check_empty_sets(env)


def check_average_is_exact() -> None:
    with tempfile.TemporaryDirectory() as td:
        e = Env(Path(td), "n,x,d,dt,c,f\n1,1,0.1,2024-01-01,a,TRUE\n2,2,0.2,2024-01-02,b,TRUE\n", SMALL_TYPES)
        try:
            _is(e.value("AVERAGE(s[d])"), Decimal("0.15"))  # float division gives 0.1499999999999999944...
        finally:
            e.store.close()


def test_average_is_exact_decimal_division() -> None:
    check_average_is_exact()


def test_result_classes(env: Env) -> None:
    assert type(env.value("SUM(s[x])")) is Decimal
    assert type(env.value("COUNTROWS(s)")) is Decimal
    assert type(env.value("MIN(s[dt])")) is dax_dates.DaxDateTime
    assert type(env.value("CALCULATE(SUM(s[x]), s[n] = 999)")) is type(None)
    assert not isinstance(env.value("AVERAGE(s[d])"), float)


# ---------------------------------------------------------------------------
# (d) refusals: no SQL for a refused expression, and nothing reaches the store
# ---------------------------------------------------------------------------

class SpyStore:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.calls: list[str] = []

    def execute(self, sql: str, params: Any = ()) -> Any:
        self.calls.append(sql)
        return self.store.execute(sql, params)


def test_refusals_return_refusal_and_run_no_query(env: Env) -> None:
    spy = SpyStore(env.store)
    cases = [
        "SUM(s[c])",                                  # text column
        "SUM(s[x]) + 1",                              # arithmetic
        "DISTINCTCOUNT(s[x])",                        # numeric DISTINCTCOUNT
        'CALCULATE(SUM(s[x]), s[c] > "a")',           # text ordering
        "CALCULATE(SUM(s[x]), s[x] IN {1, 2})",       # numeric IN
        "CALCULATE(SUM(s[x]), s[x] > 1 && s[n] > 1)",  # &&
        "SUM(s[nosuch])",
        "this is not dax",
    ]
    for expr in cases:
        out = env.plan(expr)
        assert isinstance(out, Refusal) and out.reason and out.expected_error is None, expr
    out = env.plan("SUM(s[x])", source_kind="parquet")
    assert isinstance(out, Refusal) and out.reason == PARQUET_PLAN_REASON
    out = env.plan("COUNTA(s[x])", source_kind="parquet")
    assert isinstance(out, Refusal)
    assert spy.calls == []
    # the allowed form really does run a query through the public execute
    plan = env.plan("SUM(s[x])")
    assert isinstance(plan, MeasurePlan)
    assert plan.execute(spy) == Decimal(110) and len(spy.calls) == 1


def test_plan_fields(env: Env) -> None:
    plan = env.plan('CALCULATE(AVERAGE(s[x]), s[c] = "ab")')
    assert isinstance(plan, MeasurePlan)
    assert (plan.kind, plan.table, plan.shape, plan.value_type) == ("average", "s", "AVERAGE_filtered", "number")
    plan = env.plan("MIN(s[dt])")
    assert isinstance(plan, MeasurePlan) and (plan.kind, plan.value_type) == ("scalar", "date")
    with pytest.raises(Exception):
        plan.kind = "x"  # type: ignore[misc]  # frozen


# ---------------------------------------------------------------------------
# (e) mutants: ONE rule changed in a module-level function, table or constant; the check must fail
# ---------------------------------------------------------------------------

def _fails(check: Any, *args: Any) -> None:
    """The check fails by behaviour: a wrong value (AssertionError) or an SQL error from the store, never a
    mistake of the mutant itself (TypeError, AttributeError, NameError)."""
    with pytest.raises((AssertionError, StoreError)):
        check(*args)


def test_mutant_whole_without_coalesce(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_whole_predicates(env)  # clean
    monkeypatch.setattr(
        dax_sql, "whole_predicate_sql",
        lambda col, op, lit: f"TRY_CAST(NULLIF({col}, '') AS HUGEINT) {dax_sql._SQL_OPERATORS[op]} {int(lit)}",
    )
    _fails(check_whole_predicates, env)


def test_mutant_date_without_1899_default(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_dates(env)
    monkeypatch.setattr(
        dax_sql, "date_predicate_sql",
        lambda col, op, day: f"TRY_CAST(NULLIF({col}, '') AS DATE) {dax_sql._SQL_OPERATORS[op]} DATE '{day.isoformat()}'",
    )
    _fails(check_dates, env)


def test_mutant_text_without_fold(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_text_predicates(env)
    monkeypatch.setattr(
        dax_sql, "text_predicate_sql",
        lambda col, op, lit: f"{col} {dax_sql._SQL_OPERATORS[op]} {dax_sql._sql_string(dax_sql._fold_literal(lit))}",
    )
    _fails(check_text_predicates, env)


def test_mutant_literal_folded_with_trim(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_text_predicates(env)
    monkeypatch.setattr(
        dax_sql, "_fold_literal",
        lambda text: text.translate(dax_sql._ASCII_LOWER).rstrip("".join(chr(i) for i in range(33))),
    )
    _fails(check_text_predicates, env)


def test_mutant_single_quote_not_doubled(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_text_predicates(env)
    monkeypatch.setattr(dax_sql, "_sql_string", lambda text: "'" + text + "'")
    _fails(check_text_predicates, env)


def test_mutant_wrong_operator_for_lte(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_whole_predicates(env)
    check_dates(env)
    monkeypatch.setitem(dax_sql._SQL_OPERATORS, "<=", "<")
    _fails(check_whole_predicates, env)
    _fails(check_dates, env)


def test_mutant_not_without_coalesce(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_not(env)
    monkeypatch.setattr(
        dax_sql, "whole_not_predicate_sql",
        lambda col, lit: f"NOT (TRY_CAST(NULLIF({col}, '') AS HUGEINT) = {int(lit)})",
    )
    _fails(check_not, env)


def test_mutant_or_joined_with_and(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_or(env)
    monkeypatch.setattr(dax_sql, "_OR_JOIN", " AND ")
    _fails(check_or, env)


def test_mutant_aggregate_on_wrong_column(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_aggregates(env)
    real = dax_sql.aggregate_sql
    monkeypatch.setattr(
        dax_sql, "aggregate_sql",
        lambda agg, col, *a, **k: real(agg, '"n"' if col else col, *a, **k),
    )
    _fails(check_aggregates, env)


def test_mutant_average_through_float(monkeypatch: pytest.MonkeyPatch) -> None:
    check_average_is_exact()
    monkeypatch.setattr(
        StoreResultLayer, "divide",
        staticmethod(lambda s, c, overrides=None: None if not c else Decimal(float(s) / float(c))),
    )
    _fails(check_average_is_exact)


def test_mutant_empty_count_returned_as_zero(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_empty_sets(env)
    real = dax_sql.convert_result
    monkeypatch.setattr(
        dax_sql, "convert_result",
        lambda cell, value_type: Decimal(0) if cell is None else real(cell, value_type),
    )
    _fails(check_empty_sets, env)


def test_mutant_date_result_as_plain_date(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_dates(env)
    monkeypatch.setattr(dax_sql, "to_dax_date", lambda value: value)
    _fails(check_dates, env)


def test_mutant_int_result_as_int(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    check_aggregates(env)
    real = dax_sql.to_decimal
    monkeypatch.setattr(dax_sql, "to_decimal", lambda value: value if isinstance(value, int) else real(value))
    _fails(check_aggregates, env)


def test_mutant_empty_guard_dropped(env: Env) -> None:
    check_empty_sets(env)
    _fails(lambda e: _is(e.value("CALCULATE(COUNTROWS(s), s[n] = 999)", overrides={"drop_empty_guard": True}), None), env)
    # the same hook switched off is the clean behaviour
    _is(env.value("CALCULATE(COUNTROWS(s), s[n] = 999)", overrides={}), None)


def check_first_spelling_follows_rn(tmp: Path) -> None:
    """The first-seen spelling follows the store's "__rn", not the physical row order."""
    # clean import: rowid and "__rn" are the same order, so both give the same answer
    csv_path = tmp / "o.csv"
    csv_path.write_text("c\nBeta\nbeta\nalpha\n", encoding="utf-8")
    store = DuckStore(str(tmp / "o.db"))
    try:
        import_csv_to_store(store, "o_csv", csv_path, {})
        by_rn = store.execute(first_spelling_query("o_csv", "c"))
        by_rowid = store.execute(dax_sql.first_spelling_sql('"o_csv"', '"c"', rowid="rowid"))
        assert by_rn == by_rowid == [("beta", "Beta"), ("alpha", "alpha")]
    finally:
        store.close()
    # a re-sorted table: the physical order is the reverse of the load order
    con = duckdb.connect()
    con.execute('CREATE TABLE r ("c" VARCHAR, "__rn" BIGINT)')
    con.execute("INSERT INTO r VALUES ('beta', 1), ('Beta', 0)")
    sql = first_spelling_query("r", "c")
    assert con.execute(sql).fetchall() == [("beta", "Beta")]


def test_first_spelling_order_column(tmp_path: Path) -> None:
    check_first_spelling_follows_rn(tmp_path)


def test_mutant_order_by_rowid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dax_sql, "STORE_ORDER_COLUMN", "rowid")
    _fails(check_first_spelling_follows_rn, tmp_path)


# ---------------------------------------------------------------------------
# Whitelist caps (item 6)
# ---------------------------------------------------------------------------

W_TABLES = {"t": {"w": "whole_number", "cat": "text"}}


def _decide(expr: str, **kw: Any) -> Any:
    return classify_measure(expr, home_table="t", tables=W_TABLES, **kw)


def _chain(n: int) -> str:
    return " || ".join(f"t[w] = {i}" for i in range(n))


def _nested(depth: int, inner: str) -> str:
    # CALCULATE( is one open bracket; the rest are plain parentheses around the predicate
    return "CALCULATE(SUM(t[w]), " + "(" * (depth - 1) + inner + ")" * (depth - 1) + ")"


def worst_case_inputs() -> dict[str, tuple[str, dict[str, str] | None]]:
    """The deepest input each cap admits, and one step over it (refused)."""
    preds = ", ".join(f"t[w] > {i}" for i in range(MAX_PREDICATES))
    items = ", ".join(f'"a{i}"' for i in range(MAX_IN_ITEMS))
    chain_measures = {"M0": _nested(MAX_NESTING, _chain(MAX_OR_TERMS))}
    for i in range(1, 32):
        chain_measures[f"M{i}"] = f"[M{i - 1}]"
    return {
        "nesting_and_or_chain": (_nested(MAX_NESTING, _chain(MAX_OR_TERMS)), None),
        "predicates": (f"CALCULATE(SUM(t[w]), {preds})", None),
        "in_items": (f"CALCULATE(SUM(t[w]), t[cat] IN {{{items}}})", None),
        "measure_chain_32_deep": ("[M31]", chain_measures),
        "over_or": (_nested(MAX_NESTING, _chain(MAX_OR_TERMS + 1)), None),
        "over_nesting": (_nested(MAX_NESTING + 1, "t[w] = 1"), None),
        "over_predicates": (
            "CALCULATE(SUM(t[w]), " + ", ".join(f"t[w] > {i}" for i in range(MAX_PREDICATES + 1)) + ")", None),
        "over_in_items": (
            "CALCULATE(SUM(t[w]), t[cat] IN {" + ", ".join(f'"a{i}"' for i in range(MAX_IN_ITEMS + 1)) + "})", None),
        "over_tokens": ("CALCULATE(SUM(t[w]), " + _chain(MAX_TOKENS // 4 + 1) + ")", None),
    }


def test_caps_admit_the_worst_case_and_refuse_one_more() -> None:
    cases = worst_case_inputs()
    for name in ("nesting_and_or_chain", "predicates", "in_items", "measure_chain_32_deep"):
        expr, measures = cases[name]
        dec = _decide(expr, measures=measures)
        assert dec.allowed, (name, dec.reasons)
    wanted = {
        "over_or": REASON_CAP_OR_TERMS, "over_nesting": REASON_CAP_NESTING, "over_predicates": REASON_CAP_PREDICATES,
        "over_in_items": REASON_CAP_IN_ITEMS, "over_tokens": REASON_CAP_TOKENS,
    }
    for name, reason in wanted.items():
        expr, measures = cases[name]
        dec = _decide(expr, measures=measures)
        assert not dec.allowed and dec.reasons == (reason,), (name, dec.reasons)


def test_decision_does_not_depend_on_the_recursion_limit() -> None:
    cases = worst_case_inputs()
    previous = sys.getrecursionlimit()
    results: dict[int, dict[str, Any]] = {}
    try:
        for limit in (500, 1000, 3000, 20000):
            sys.setrecursionlimit(limit)
            results[limit] = {name: _decide(expr, measures=m) for name, (expr, m) in cases.items()}
    finally:
        sys.setrecursionlimit(previous)
    for limit in (500, 1000, 3000):
        assert results[limit] == results[20000], limit
    assert sum(1 for d in results[500].values() if d.allowed) == 4


def test_mutant_or_cap_off_by_one(monkeypatch: pytest.MonkeyPatch) -> None:
    test_caps_admit_the_worst_case_and_refuse_one_more()
    monkeypatch.setattr(dax_whitelist, "MAX_OR_TERMS", MAX_OR_TERMS + 1)
    _fails(test_caps_admit_the_worst_case_and_refuse_one_more)


def test_mutant_nesting_cap_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dax_whitelist, "MAX_NESTING", MAX_NESTING + 1)
    _fails(test_caps_admit_the_worst_case_and_refuse_one_more)


# ---------------------------------------------------------------------------
# (a) Rule A+ against the real engine, through the rules tool
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def full_runs() -> dict[tuple[int, int], dict[str, Any]]:
    out = {}
    for rows, seed in ((2000, 42), (2000, 1)):
        out[(rows, seed)] = run_comparison(
            rows=rows, seed=seed, skip_naive=True, skip_parquet=True, skip_group_by=True, use_plan=True
        )
    return out


def test_rule_a_plus_full_catalog(full_runs: dict[tuple[int, int], dict[str, Any]]) -> None:
    for key, data in full_runs.items():
        counts = plan_counts(data["results"])
        assert counts["allowed"] == 570, (key, counts)
        assert counts["plan-same"] == 570, (key, counts)
        assert counts["plan-differs"] == counts["plan-sql-error"] == counts["plan-crash"] == 0, (key, counts)
        assert counts["plan-refused"] == counts["refused"] == 244, (key, counts)
        assert counts["plan-refused-allowed"] == 0, (key, counts)
        for r in data["results"]:
            if r["plan_allowed"]:
                assert r["plan_status"] == "plan-same", r["id"]


def test_rule_a_plus_seeds_1_to_40_rotating_slice() -> None:
    """Cheaper loop (the engine costs about 2 ms per formula): seeds 1..40 at 400 rows, each seed runs the
    formulas whose catalog index is congruent to the seed modulo 10, so every formula runs on 4 seeds."""
    headers = ["id", "w", "d", "big", "t", "dt", "flag", "cat", "w_blank", "num_dups"]
    catalog = [f for f in build_formula_catalog(headers) if f["id"] != "forced_wrong_formula" and not f.get("group_col")]
    allowed_total = 0
    for seed in range(1, 41):
        ids = [f["id"] for i, f in enumerate(catalog) if i % 10 == seed % 10]
        data = run_comparison(
            rows=400, seed=seed, skip_naive=True, skip_parquet=True, skip_group_by=True, use_plan=True,
            formula_filter=ids,
        )
        counts = plan_counts(data["results"])
        assert counts["plan-differs"] == counts["plan-sql-error"] == counts["plan-crash"] == 0, (seed, counts)
        assert counts["plan-same"] == counts["allowed"], (seed, counts)
        allowed_total += counts["allowed"]
    assert allowed_total > 40 * 40


def test_plan_mode_is_off_by_default() -> None:
    data = run_comparison(rows=50, seed=42, skip_naive=True, skip_parquet=True, skip_group_by=True, formula_filter=["SUM_w"])
    assert data["results"] and all("plan_status" not in r for r in data["results"])


# ---------------------------------------------------------------------------
# (c) a forced wrong plan value makes the tool exit 1
# ---------------------------------------------------------------------------

def test_forced_wrong_plan_value_exits_one() -> None:
    kwargs = dict(rows=100, seed=42, skip_naive=True, skip_parquet=True, skip_group_by=True, use_plan=True, formula_filter=["SUM_w", "COUNTROWS"])
    baseline: dict[str, Any] = {"classes": []}
    clean = run_comparison(**kwargs)
    assert evaluate_exit_policy(clean, baseline)[0] == 0
    wrong = run_comparison(**kwargs, overrides={"forced_wrong_plan_value": "SUM_w"})
    by_id = {r["id"]: r for r in wrong["results"]}
    assert by_id["SUM_w"]["plan_status"] == "plan-differs"
    code, messages = evaluate_exit_policy(wrong, baseline)
    assert code == 1 and "SUM_w" in messages[0]


def test_plan_sql_error_and_crash_exit_one() -> None:
    kwargs = dict(rows=50, seed=42, skip_naive=True, skip_parquet=True, skip_group_by=True, use_plan=True, formula_filter=["SUM_w"])
    data = run_comparison(**kwargs)
    for status in ("plan-sql-error", "plan-crash", "plan-differs"):
        broken = {**data, "results": [{**data["results"][0], "plan_status": status}]}
        assert evaluate_exit_policy(broken, {"classes": []})[0] == 1, status
    refused = {**data, "results": [{**data["results"][0], "plan_status": "plan-refused-allowed"}]}
    assert evaluate_exit_policy(refused, {"classes": []})[0] == 1
    listed = {"classes": [], "plan_refusals_allowed": [data["results"][0]["id"]]}
    assert evaluate_exit_policy(refused, listed)[0] == 0


def test_column_decimal_meta(env: Env) -> None:
    meta = column_decimal_meta(env.store, "s_csv", ["d", "x"])
    assert meta["d"] == ColumnMeta(scale=4, digits=5)
    assert meta["x"].digits == 3


# ===========================================================================
# C1b1b: review fixes. Each case below is compared with the REAL engine (evaluate_measures).
# ===========================================================================

import csv as _csv  # noqa: E402

from analytics_studio.controller import StudioController  # noqa: E402
from analytics_studio.file_import import parse_file  # noqa: E402
from analytics_studio.measures import evaluate_measures, normalize_measure  # noqa: E402
from analytics_studio.store.dax_sql import REASON_IN_NON_ASCII_COLUMN  # noqa: E402
from analytics_studio.store.dax_whitelist import REASON_TEXT_IN_FOLD  # noqa: E402


class EngineCase:
    """A small CSV table named "t" loaded in the real engine AND in a store, with decimal metadata."""

    def __init__(self, base: Path, header: list[str], rows: list[list[str]]) -> None:
        csv_path = base / "t.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as handle:
            writer = _csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        self.controller = StudioController()
        self.controller._effective_app_data_dir = lambda: str(base / "app")
        assert self.controller._commit_import(csv_path, parse_file(csv_path))
        self.context = self.controller._measure_table_context()
        self.table_id = self.controller._active_model_table_id()
        self.table_name = self.controller._active_model_table_name()
        assert self.table_name == "t"
        self.rows = self.controller._loaded_candidates[self.controller._active_source_id].rows
        self.headers = self.controller._headers
        self.types: dict[str, str] = self.controller._project["model"]["tables"][0]["column_types"]
        self.store = DuckStore(str(base / "t.db"))
        import_csv_to_store(self.store, "t_csv", csv_path, {})
        self.meta = {("t", c): m for c, m in column_decimal_meta(self.store, "t_csv", header).items()}

    def engine(self, expression: str) -> Any:
        measure = normalize_measure("M", expression, home_table_id=self.table_id)
        return evaluate_measures(
            [measure], self.rows, self.headers, "t", measure_names=["M"], table_context=self.context,
            relationships=[], filter_table_ids=[], active_table_id=self.table_id,
        )["M"]

    def plan(self, expression: str, meta: Any = None) -> Any:
        return plan_measure(
            expression, home_table="t", tables={"t": self.types}, store_tables={"t": "t_csv"},
            column_meta=self.meta if meta is None else meta,
        )

    def same_as_engine(self, expression: str) -> Any:
        """The plan's value, asserted equal to the engine's (same class, same value)."""
        plan = self.plan(expression)
        assert isinstance(plan, MeasurePlan), (expression, plan)
        got = plan.execute(self.store)
        want = self.engine(expression)
        assert type(got) is type(want) and got == want, (expression, got, want)
        return got


# ---- item 1: decimal columns with names that break unquoted SQL -------------------------------------

ODD_NAMES = ["amt x", 'a"b', "a;b", "select", "c]d"]


def _dax_ref(name: str) -> str:
    return "t[" + name.replace("]", "]]") + "]"


@pytest.fixture(scope="module")
def odd_decimal_case(tmp_path_factory: pytest.TempPathFactory) -> EngineCase:
    rows = [[str(i)] + [f"{i}.123{j}4546" for j in range(len(ODD_NAMES))] for i in range(1, 6)]
    case = EngineCase(tmp_path_factory.mktemp("odd"), ["id"] + ODD_NAMES, rows)
    yield case
    case.store.close()


@pytest.mark.parametrize("name", ODD_NAMES)
def test_decimal_column_with_odd_name_sums_exactly_like_the_engine(odd_decimal_case: EngineCase, name: str) -> None:
    case = odd_decimal_case
    assert case.types[name] == "decimal_number"
    assert case.meta[("t", name)].scale == 8  # not the made-up default of 4
    value = case.same_as_engine(f"SUM({_dax_ref(name)})")
    assert value % Decimal("0.0001") != 0  # a result rounded to 4 decimals would not pass the check above


class FailingMetaStore:
    """Forwards everything but raises on the decimal metadata queries; records every query."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.calls: list[str] = []

    def execute(self, sql: str, params: Any = ()) -> Any:
        self.calls.append(sql)
        if "strpos" in sql or "regexp_replace" in sql:
            raise StoreError("forced metadata failure")
        return self.store.execute(sql, params)


def test_metadata_failure_is_a_refusal_and_runs_no_aggregate_query(odd_decimal_case: EngineCase) -> None:
    case = odd_decimal_case
    failing = FailingMetaStore(case.store)
    meta = column_decimal_meta(failing, "t_csv", ODD_NAMES)
    assert meta == {}  # no made-up ColumnMeta(4, 0)
    column_meta = {("t", c): m for c, m in meta.items()}
    metadata_queries = len(failing.calls)
    assert metadata_queries > 0
    for expression in ("SUM(t[amt x])", 'CALCULATE(COUNTROWS(t), t[amt x] >= 1)', "AVERAGE(t[select])"):
        out = case.plan(expression, meta=column_meta)
        assert isinstance(out, Refusal) and "no decimal metadata for column" in out.reason, (expression, out)
    assert len(failing.calls) == metadata_queries  # the plan step ran no query at all


# ---- item 2: text IN versus the engine ----------------------------------------------------------------

IN_MISMATCH_LITERALS = [['"ünï"'], ['"ß"'], ['"ss"'], ['"ünï"', '"ß"'], ['"A"', '"ünï"'], ['"SS"'], ['"Mississippi"']]


@pytest.mark.parametrize("items", IN_MISMATCH_LITERALS)
def test_whitelist_refuses_in_items_that_fold_differently(items: list[str]) -> None:
    expression = "CALCULATE(COUNTROWS(t), t[cat] IN {" + ", ".join(items) + "})"
    decision = _decide(expression)
    assert not decision.allowed and decision.reasons == (REASON_TEXT_IN_FOLD,), (items, decision)
    assert REASON_TEXT_IN_FOLD == (
        "text IN with non-ASCII items or items containing ss is not on the store whitelist: "
        "the engine folds those differently"
    )


def test_whitelist_still_allows_ascii_in_and_equality() -> None:
    assert _decide('CALCULATE(COUNTROWS(t), t[cat] IN {"A", "B"})').allowed
    assert _decide('CALCULATE(COUNTROWS(t), t[cat] = "ünï")').allowed
    assert _decide('CALCULATE(COUNTROWS(t), t[cat] = "ss")').allowed


@pytest.fixture(scope="module")
def unicode_case(tmp_path_factory: pytest.TempPathFactory) -> EngineCase:
    cells = ["A", "a", "B", "ß", "ünï", "ÜNÏ", "SS", "ss", "K", "K", "k", "x y", ""]
    case = EngineCase(tmp_path_factory.mktemp("uni"), ["n", "cat"], [[str(i), c] for i, c in enumerate(cells * 3, 1)])
    yield case
    case.store.close()


@pytest.fixture(scope="module")
def ascii_case(tmp_path_factory: pytest.TempPathFactory) -> EngineCase:
    cells = ["A", "a", "B", "b", "C", "x y", "", "Kk"]
    case = EngineCase(tmp_path_factory.mktemp("asc"), ["n", "cat"], [[str(i), c] for i, c in enumerate(cells * 4, 1)])
    yield case
    case.store.close()


def test_planner_refuses_in_on_a_column_with_non_ascii_cells(unicode_case: EngineCase) -> None:
    case = unicode_case
    for items in (['"a"'], ['"A"', '"B"'], ['"k"'], ['"x y"']):
        expression = "CALCULATE(COUNTROWS(t), t[cat] IN {" + ", ".join(items) + "})"
        plan = case.plan(expression)
        assert isinstance(plan, MeasurePlan), (expression, plan)
        spy = SpyStore(case.store)
        out = plan.execute(spy)
        assert isinstance(out, Refusal) and out.reason == REASON_IN_NON_ASCII_COLUMN, (expression, out)
        assert len(spy.calls) == 1 and "COUNT(" not in spy.calls[0], spy.calls  # only the guard query ran
    # equality stays on the plan: the engine and the plan agree on it for the same column
    for literal in ('"a"', '"k"', '"ünï"', '"ss"', '"ß"'):
        case.same_as_engine(f"CALCULATE(COUNTROWS(t), t[cat] = {literal})")


def test_the_guard_is_needed_the_engine_folds_kelvin_sign_and_eszett_for_in(unicode_case: EngineCase) -> None:
    case = unicode_case
    expression = 'CALCULATE(COUNTROWS(t), t[cat] IN {"k"})'
    plan = case.plan(expression)
    assert isinstance(plan, MeasurePlan)
    unguarded = Decimal(case.store.execute(plan.sql)[0][0])
    assert unguarded != case.engine(expression)


def test_ascii_in_equals_the_engine_and_costs_two_queries_once(ascii_case: EngineCase) -> None:
    case = ascii_case
    expression = 'CALCULATE(COUNTROWS(t), t[cat] IN {"A", "B"})'
    plan = case.plan(expression)
    assert isinstance(plan, MeasurePlan)
    spy = SpyStore(case.store)
    got = plan.execute(spy)
    assert len(spy.calls) == 2  # the guard, then the aggregate
    assert type(got) is type(case.engine(expression)) and got == case.engine(expression)
    assert plan.execute(spy) == got and len(spy.calls) == 3  # the guard result is cached inside the plan
    other = case.plan(expression)
    assert isinstance(other, MeasurePlan) and other.guard_cache == {}  # never global
    for text in ('CALCULATE(SUM(t[n]), t[cat] IN {"a", "kk", ""})', 'CALCULATE(COUNTROWS(t), t[cat] IN {"x y"})'):
        case.same_as_engine(text)


def test_plans_without_in_run_exactly_one_query(ascii_case: EngineCase) -> None:
    spy = SpyStore(ascii_case.store)
    for expression in ("COUNTROWS(t)", 'CALCULATE(SUM(t[n]), t[cat] = "a")', "SUM(t[n])"):
        plan = ascii_case.plan(expression)
        assert isinstance(plan, MeasurePlan)
        before = len(spy.calls)
        plan.execute(spy)
        assert len(spy.calls) == before + 1, expression


def test_mutant_in_guard_off_is_caught(unicode_case: EngineCase, monkeypatch: pytest.MonkeyPatch) -> None:
    def check() -> None:
        plan = unicode_case.plan('CALCULATE(COUNTROWS(t), t[cat] IN {"k"})')
        assert isinstance(plan, MeasurePlan)
        assert isinstance(plan.execute(unicode_case.store), Refusal)

    check()
    monkeypatch.setattr(MeasurePlan, "_in_column_has_non_ascii", lambda self, store, guard: False)
    _fails(check)


# ---- item 3: whitespace-only text cells in COUNTBLANK and DISTINCTCOUNT ------------------------------

@pytest.fixture(scope="module")
def blank_case(tmp_path_factory: pytest.TempPathFactory) -> EngineCase:
    cells = [
        ("1", " "), ("1", "\t"), ("1", ""), ("1", "   "),      # group 1: only blank-like cells
        ("2", "a"), ("2", "A"), ("2", "b "), ("2", " "),       # group 2: values and one blank-like cell
        ("3", "x"), ("3", "x "), ("3", " x"),                  # group 3: no blank-like cell
    ]
    case = EngineCase(tmp_path_factory.mktemp("blank"), ["g", "cat"], [[g, c] for g, c in cells])
    yield case
    case.store.close()


@pytest.mark.parametrize("expression", [
    "COUNTBLANK(t[cat])",
    "DISTINCTCOUNT(t[cat])",
    "CALCULATE(COUNTBLANK(t[cat]), t[g] = 1)",
    "CALCULATE(DISTINCTCOUNT(t[cat]), t[g] = 1)",
    "CALCULATE(COUNTBLANK(t[cat]), t[g] = 2)",
    "CALCULATE(DISTINCTCOUNT(t[cat]), t[g] = 2)",
    "CALCULATE(COUNTBLANK(t[cat]), t[g] = 3)",
    "CALCULATE(DISTINCTCOUNT(t[cat]), t[g] = 3)",
    "CALCULATE(COUNTROWS(t), t[g] = 1)",
])
def test_whitespace_only_text_cells_count_like_the_engine(blank_case: EngineCase, expression: str) -> None:
    blank_case.same_as_engine(expression)


def test_whitespace_only_values_are_the_expected_numbers(blank_case: EngineCase) -> None:
    # hand count: group 1 has four blank-like cells; the whole table has five; DISTINCTCOUNT = a, b, x, blank
    _is(blank_case.same_as_engine("CALCULATE(COUNTBLANK(t[cat]), t[g] = 1)"), Decimal(4))
    _is(blank_case.same_as_engine("COUNTBLANK(t[cat])"), Decimal(5))
    _is(blank_case.same_as_engine("CALCULATE(DISTINCTCOUNT(t[cat]), t[g] = 1)"), Decimal(1))


def test_mutant_blank_count_back_to_empty_string_is_caught(blank_case: EngineCase, monkeypatch: pytest.MonkeyPatch) -> None:
    def check() -> None:
        blank_case.same_as_engine("COUNTBLANK(t[cat])")
        blank_case.same_as_engine("CALCULATE(DISTINCTCOUNT(t[cat]), t[g] = 1)")

    check()
    monkeypatch.setattr(dax_sql, "trim_sql", lambda expr: f"COALESCE({expr}, '')")
    _fails(check)


# ---- item 5: literal cap numbers, the blank-date boundary --------------------------------------------

def _literal_chain(n: int) -> str:
    return " || ".join(f"t[w] = {i}" for i in range(n))


def test_cap_numbers_are_pinned_to_their_literal_values() -> None:
    assert (dax_whitelist.MAX_OR_TERMS, dax_whitelist.MAX_PREDICATES, dax_whitelist.MAX_IN_ITEMS) == (50, 50, 200)
    assert (dax_whitelist.MAX_NESTING, dax_whitelist.MAX_TOKENS) == (20, 1500)
    assert _decide("CALCULATE(SUM(t[w]), " + _literal_chain(50) + ")").allowed
    over = _decide("CALCULATE(SUM(t[w]), " + _literal_chain(51) + ")")
    assert over.reasons == (dax_whitelist.REASON_CAP_OR_TERMS,)
    assert _decide("CALCULATE(SUM(t[w]), " + ", ".join(f"t[w] > {i}" for i in range(50)) + ")").allowed
    over = _decide("CALCULATE(SUM(t[w]), " + ", ".join(f"t[w] > {i}" for i in range(51)) + ")")
    assert over.reasons == (dax_whitelist.REASON_CAP_PREDICATES,)
    assert _decide("CALCULATE(SUM(t[w]), t[cat] IN {" + ", ".join(f'"a{i}"' for i in range(200)) + "})").allowed
    over = _decide("CALCULATE(SUM(t[w]), t[cat] IN {" + ", ".join(f'"a{i}"' for i in range(201)) + "})")
    assert over.reasons == (dax_whitelist.REASON_CAP_IN_ITEMS,)
    assert _decide("CALCULATE(SUM(t[w]), " + "(" * 19 + "t[w] = 1" + ")" * 19 + ")").allowed
    over = _decide("CALCULATE(SUM(t[w]), " + "(" * 20 + "t[w] = 1" + ")" * 20 + ")")
    assert over.reasons == (dax_whitelist.REASON_CAP_NESTING,)


def _expression_with_tokens(target: int) -> str:
    """CALCULATE with 50 predicates (the cap) made of `||` chains; a leading minus adds one token to a literal."""
    from analytics_studio.measures import tokenize

    def build(minus: int) -> str:
        preds, counter = [], 0
        for _ in range(50):
            terms = []
            for _ in range(6):
                terms.append(f"t[w] = {'-' if counter < minus else ''}{counter % 7}")
                counter += 1
            preds.append(" || ".join(terms))
        return "CALCULATE(SUM(t[w]), " + ", ".join(preds) + ")"

    base = len(tokenize(build(0)))
    assert base <= target <= base + 300
    expression = build(target - base)
    assert len(tokenize(expression)) == target
    return expression


def test_token_cap_is_exactly_1500() -> None:
    assert _decide(_expression_with_tokens(1500)).allowed
    assert _decide(_expression_with_tokens(1501)).reasons == (dax_whitelist.REASON_CAP_TOKENS,)


def test_blank_dates_compare_as_1899_12_30_at_the_1900_boundary(env: Env) -> None:
    # the blank date (row 2, n = 2) is 1899-12-30: below 1900-01-01 (DATE() cannot go lower)
    _is(sum_n(env, "s[dt] < DATE(1900, 1, 1)"), Decimal(2))
    _is(sum_n(env, "s[dt] <= DATE(1900, 1, 1)"), Decimal(2))
    _is(sum_n(env, "s[dt] >= DATE(1900, 1, 1)"), Decimal(13))
    _is(sum_n(env, "s[dt] <> DATE(1900, 1, 1)"), Decimal(15))


def test_mutant_blank_date_default_1900_01_01_is_caught(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def check() -> None:
        _is(sum_n(env, "s[dt] < DATE(1900, 1, 1)"), Decimal(2))
        _is(sum_n(env, "s[dt] <> DATE(1900, 1, 1)"), Decimal(15))

    check()
    original = dax_sql.date_predicate_sql
    monkeypatch.setattr(
        dax_sql, "date_predicate_sql",
        lambda col, op, day: original(col, op, day).replace("DATE '1899-12-30'", "DATE '1900-01-01'"),
    )
    _fails(check)


def test_seed_loop_runs_a_rotating_tenth_of_the_catalog_per_seed() -> None:
    """Names the shape of test_rule_a_plus_seeds_1_to_40_rotating_slice: each seed runs only the formulas whose
    catalog index is congruent to the seed modulo 10 (a tenth), so one formula runs on 4 of the 40 seeds."""
    headers = ["id", "w", "d", "big", "t", "dt", "flag", "cat", "w_blank", "num_dups"]
    catalog = [f for f in build_formula_catalog(headers) if f["id"] != "forced_wrong_formula" and not f.get("group_col")]
    per_seed = [sum(1 for i, _ in enumerate(catalog) if i % 10 == seed % 10) for seed in range(1, 41)]
    assert all(len(catalog) // 10 <= n <= len(catalog) // 10 + 1 for n in per_seed)
    assert sum(per_seed) == 4 * len(catalog)
