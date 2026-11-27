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
    # a blank "=" is guarded too: on this column it is refused (REASON_IN_NON_ASCII_COLUMN), not answered as 5
    plan = env.plan('CALCULATE(SUM(s[n]), s[c] = "")')
    assert isinstance(plan, MeasurePlan), plan
    out = plan.execute(env.store)
    assert isinstance(out, Refusal) and out.reason == dax_sql.REASON_IN_NON_ASCII_COLUMN, out


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
    assert plan.execute(spy) == got and len(spy.calls) == 4  # no cache: the guard runs again, so each execute costs 2
    other = case.plan(expression)
    assert isinstance(other, MeasurePlan) and not hasattr(other, "guard_cache")  # the guard cache is gone
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


# ===========================================================================
# C1b2 first items: guard on every execute, blank/whitespace text equality, quoted table name
# ===========================================================================

NON_ASCII_SPACES = [" ", "\u0085", "　", " "]


def _fresh_case(base: Path, cells: list[str]) -> EngineCase:
    return EngineCase(base, ["n", "cat"], [[str(i), c] for i, c in enumerate(cells, 1)])


def test_in_guard_runs_on_every_execute_and_sees_a_row_added_between_two_executes(tmp_path: Path) -> None:
    case = _fresh_case(tmp_path, ["A", "a", "B", "b", "C", ""] * 4)
    try:
        plan = case.plan('CALCULATE(COUNTROWS(t), t[cat] IN {"A", "B"})')
        assert isinstance(plan, MeasurePlan)
        spy = SpyStore(case.store)
        first = plan.execute(spy)
        assert isinstance(first, Decimal) and len(spy.calls) == 2  # the guard, then the aggregate
        case.store.append_rows("t_csv", [["99", "ß"]])  # the store gains a non-ASCII cell
        second = plan.execute(spy)
        assert isinstance(second, Refusal) and second.reason == REASON_IN_NON_ASCII_COLUMN, second
        assert len(spy.calls) == 3 and "SELECT EXISTS" in spy.calls[2]  # only the guard ran, not the aggregate
        fresh = case.plan('CALCULATE(COUNTROWS(t), t[cat] IN {"A", "B"})')
        assert isinstance(fresh, MeasurePlan) and isinstance(fresh.execute(case.store), Refusal)
        assert not hasattr(plan, "guard_cache")
    finally:
        case.store.close()


@pytest.fixture(scope="module")
def space_case(tmp_path_factory: pytest.TempPathFactory) -> EngineCase:
    cells = ["", " ", "\t", "A", "a", "x y"] + NON_ASCII_SPACES + [" A", "A "]
    case = _fresh_case(tmp_path_factory.mktemp("sp"), cells * 3)
    yield case
    case.store.close()


@pytest.mark.parametrize("literal", ['""', '" "', '"  "', '"\t"'])
def test_blank_or_space_equality_is_refused_on_a_column_with_non_ascii_spaces(
    space_case: EngineCase, literal: str
) -> None:
    expression = f"CALCULATE(COUNTROWS(t), t[cat] = {literal})"
    plan = space_case.plan(expression)
    assert isinstance(plan, MeasurePlan) and plan.in_guards == (("t_csv", "cat"),), (expression, plan)
    spy = SpyStore(space_case.store)
    out = plan.execute(spy)
    assert isinstance(out, Refusal) and out.reason == REASON_IN_NON_ASCII_COLUMN, (expression, out)
    assert len(spy.calls) == 1 and "COUNT(" not in spy.calls[0], spy.calls
    # the unguarded SQL really differs from the engine on this column (the guard is needed)
    if literal == '""':
        unguarded = Decimal(space_case.store.execute(plan.sql)[0][0])
        assert unguarded != space_case.engine(expression), (expression, unguarded)


@pytest.mark.parametrize("char", NON_ASCII_SPACES)
def test_whitelist_refuses_a_non_ascii_whitespace_text_literal(char: str) -> None:
    from analytics_studio.store.dax_whitelist import REASON_TEXT_NON_ASCII_SPACE

    for literal in (char, f"A{char}", f"{char}{char}"):
        decision = _decide(f'CALCULATE(COUNTROWS(t), t[cat] = "{literal}")')
        assert not decision.allowed and decision.reasons == (REASON_TEXT_NON_ASCII_SPACE,), (literal, decision)
    assert _decide('CALCULATE(COUNTROWS(t), t[cat] = "ünï")').allowed  # other non-ASCII stays allowed


def test_blank_equality_on_an_ascii_column_matches_the_engine_with_two_queries(tmp_path: Path) -> None:
    case = _fresh_case(tmp_path, ["", " ", "\t", "A", "a", "x y"] * 3)
    try:
        for literal in ('""', '" "', '"\t"'):
            expression = f"CALCULATE(COUNTROWS(t), t[cat] = {literal})"
            plan = case.plan(expression)
            assert isinstance(plan, MeasurePlan)
            spy = SpyStore(case.store)
            got = plan.execute(spy)
            assert len(spy.calls) == 2, (expression, spy.calls)
            want = case.engine(expression)
            assert type(got) is type(want) and got == want, (expression, got, want)
        plan = case.plan('CALCULATE(COUNTROWS(t), t[cat] = "a")')
        spy = SpyStore(case.store)
        plan.execute(spy)
        assert len(spy.calls) == 1  # a non-blank literal needs no guard
    finally:
        case.store.close()


def test_mutant_blank_equality_guard_off_is_caught(space_case: EngineCase, monkeypatch: pytest.MonkeyPatch) -> None:
    def check() -> None:
        plan = space_case.plan('CALCULATE(COUNTROWS(t), t[cat] = "")')
        assert isinstance(plan, MeasurePlan)
        assert isinstance(plan.execute(space_case.store), Refusal)

    check()
    monkeypatch.setattr(MeasurePlan, "_in_column_has_non_ascii", lambda self, store, guard: False)
    _fails(check)


def test_column_decimal_meta_quotes_a_table_name_with_a_quote_and_a_space(tmp_path: Path) -> None:
    csv_path = tmp_path / "q.csv"
    csv_path.write_text("id,amt\n1,1.123456\n2,10.5\n3,\n", encoding="utf-8")
    table = 'my "t" x'
    store = DuckStore(str(tmp_path / "q.db"))
    try:
        import_csv_to_store(store, table, csv_path, {})
        physical = store.resolve_table_name(table)
        meta = column_decimal_meta(store, physical, ["amt"])
        assert meta["amt"].scale == 6, meta
    finally:
        store.close()


# ===========================================================================
# C1b2: group-by planner, filter context, literal sweep
# ===========================================================================

from analytics_studio.store.dax_sql import (  # noqa: E402
    REASON_GROUP_BY_TYPE,
    REASON_GROUP_NON_ASCII_SPACE,
    REASON_GROUP_OWN_FILTER,
    GroupByPlan,
    plan_group_by,
)
from analytics_studio.store.dax_whitelist import (  # noqa: E402
    REASON_SLICER_SAME_COLUMN,
    classify_filter_context,
)
from analytics_studio.store.text_rules import trim_sql  # noqa: E402
from tools.store_engine_diff import (  # noqa: E402
    _parse_engine_keys,
    build_sweep_catalog,
    evaluate_sweep_policy,
    run_sweep,
    with_filter_context,
)

GB_HEADER = ["n", "cat", "dt", "flag", "v"]
GB_ROWS = [
    ["1", "Ab ", "2024-02-29", "TRUE", "1.5"],
    ["2", "ab", "", "FALSE", "0.25"],
    ["3", "B", "2026-06-01", "", ""],
    ["4", "", "2023-01-15", "TRUE", "2"],
    ["5", "AB", "", "FALSE", "3"],
    ["6", " ", "2024-02-29", "TRUE", ""],
    ["7", "b", "2026-06-01", "TRUE", "1"],
    ["8", "C", "2024-03-01", "FALSE", "0"],
    ["9", "ab\t", "2024-02-29", "", "0.5"],
    ["10", "", "", "TRUE", "4"],
    ["11", "B ", "2023-01-15", "FALSE", "0"],
    ["12", "c", "2026-06-01", "TRUE", "1.25"],
]


@pytest.fixture(scope="module")
def gb_case(tmp_path_factory: pytest.TempPathFactory) -> EngineCase:
    case = EngineCase(tmp_path_factory.mktemp("gb"), GB_HEADER, GB_ROWS)
    yield case
    case.store.close()


def gb(case: EngineCase, expression: str, group: str, ctx: tuple[str, ...] = (), overrides: Any = None, **kw: Any) -> Any:
    """plan_group_by on the case table, executed: [(key, value)] or a Refusal."""
    plan = plan_group_by(
        expression, group_by=("t", group), filter_context=ctx, home_table="t", tables={"t": case.types},
        store_tables=kw.pop("store_tables", {"t": "t_csv"}), column_meta=case.meta, overrides=overrides, **kw,
    )
    if isinstance(plan, Refusal):
        return plan
    assert isinstance(plan, GroupByPlan)
    return plan.execute(case.store)


def D(*values: Any) -> list[Any]:
    return [Decimal(v) if v is not None else None for v in values]


# (a) hand-checked group-by results --------------------------------------------------------------

TEXT_KEYS = ["Ab", "B", "", "C"]
DATE_KEYS = ["", "1/15/2023", "2/29/2024", "3/1/2024", "6/1/2026"]


def check_text_group(case: EngineCase, overrides: Any = None) -> None:
    assert gb(case, "SUM(t[n])", "cat", overrides=overrides) == list(zip(TEXT_KEYS, D(17, 21, 20, 20)))
    assert gb(case, "COUNTROWS(t)", "cat", overrides=overrides) == list(zip(TEXT_KEYS, D(4, 3, 3, 2)))


def check_date_group(case: EngineCase, overrides: Any = None) -> None:
    assert gb(case, "SUM(t[n])", "dt", overrides=overrides) == list(zip(DATE_KEYS, D(17, 15, 16, 8, 22)))
    assert gb(case, "COUNTROWS(t)", "dt", overrides=overrides) == list(zip(DATE_KEYS, D(3, 2, 3, 1, 3)))


def check_bool_group(case: EngineCase, overrides: Any = None) -> None:
    assert gb(case, "SUM(t[n])", "flag", overrides=overrides) == [("FALSE", Decimal(38)), ("TRUE", Decimal(40))]
    assert gb(case, "COUNTROWS(t)", "flag", overrides=overrides) == [("FALSE", Decimal(6)), ("TRUE", Decimal(6))]


def check_average_group(case: EngineCase, overrides: Any = None) -> None:
    got = gb(case, "AVERAGE(t[n])", "cat", overrides=overrides)
    assert got == [("Ab", Decimal("4.25")), ("B", Decimal(7)), ("", Decimal(20) / Decimal(3)), ("C", Decimal(10))]
    assert all(type(v) is Decimal for _, v in got)


def check_distinct_group(case: EngineCase, overrides: Any = None) -> None:
    assert gb(case, "DISTINCTCOUNT(t[cat])", "dt", overrides=overrides) == list(zip(DATE_KEYS, D(2, 2, 2, 1, 2)))


def test_group_by_text_merges_case_and_trailing_space_shows_first_spelling_and_blank_at_first_seen_place(
    gb_case: EngineCase,
) -> None:
    check_text_group(gb_case)
    # the engine shows the same keys in the same order (the rule the planner reproduces)
    assert _parse_engine_keys(gb_case.engine("TOCSV(VALUES(t[cat]), 100000)")) == TEXT_KEYS
    assert _parse_engine_keys(gb_case.engine("TOCSV(VALUES(t[dt]), 100000)")) == DATE_KEYS
    assert _parse_engine_keys(gb_case.engine("TOCSV(VALUES(t[flag]), 100000)")) == ["FALSE", "TRUE"]


def test_group_by_date_blank_key_first_and_m_d_yyyy_text(gb_case: EngineCase) -> None:
    check_date_group(gb_case)


def test_group_by_boolean_false_before_true_and_blank_counts_as_false(gb_case: EngineCase) -> None:
    check_bool_group(gb_case)


def test_group_by_average_is_the_exact_quotient_and_distinctcount_adds_the_blank(gb_case: EngineCase) -> None:
    check_average_group(gb_case)
    check_distinct_group(gb_case)


def test_group_by_values_equal_the_engine_per_key(gb_case: EngineCase) -> None:
    for expression in ("SUM(t[n])", "COUNTROWS(t)", "AVERAGE(t[v])", "MIN(t[dt])", "COUNTBLANK(t[cat])"):
        for group, keyed in (("cat", ['t[cat] = "Ab"', 't[cat] = "B"', 't[cat] = ""', 't[cat] = "C"']),
                             ("flag", ["t[flag] = FALSE()", "t[flag] = TRUE()"])):
            got = gb(gb_case, expression, group)
            assert isinstance(got, list) and len(got) == len(keyed)
            for (_, value), predicate in zip(got, keyed):
                want = gb_case.engine(with_filter_context(expression, (predicate,)))
                assert type(value) is type(want) and value == want, (expression, predicate, value, want)


def test_group_by_refusals_have_stable_reasons(gb_case: EngineCase) -> None:
    case = gb_case
    kinds = {
        "numeric key": gb(case, "SUM(t[v])", "n"),
        "own filter on the group column": gb(case, 'CALCULATE(SUM(t[v]), t[cat] = "B")', "cat"),
        "numeric distinct": gb(case, "DISTINCTCOUNT(t[n])", "cat"),
        "unknown column": gb(case, "SUM(t[v])", "nope"),
    }
    assert all(isinstance(r, Refusal) for r in kinds.values()), kinds
    assert kinds["numeric key"].reason == REASON_GROUP_BY_TYPE
    assert kinds["own filter on the group column"].reason == REASON_GROUP_OWN_FILTER
    assert "also filtered" in kinds["own filter on the group column"].reason
    for bad in (("t",), ("t", "cat", "dt"), "cat", None):
        out = plan_group_by(
            "SUM(t[v])", group_by=bad, home_table="t", tables={"t": case.types}, store_tables={"t": "t_csv"},
            column_meta=case.meta,
        )
        assert isinstance(out, Refusal), bad
    other = plan_group_by(
        "SUM(t[v])", group_by=("u", "cat"), home_table="t", tables={"t": case.types}, store_tables={"t": "t_csv"},
        column_meta=case.meta,
    )
    assert isinstance(other, Refusal)
    assert gb(case, "SUM(t[v])", "cat", ctx=('t[cat] = "A"',)).reason == REASON_SLICER_SAME_COLUMN


def test_group_by_own_filter_on_another_column_is_the_engine_value_per_group(gb_case: EngineCase) -> None:
    """The former refusal case: CALCULATE(SUM(v), n > 2) by cat is the per-group sum over the rows with n > 2."""
    got = gb(gb_case, "CALCULATE(SUM(t[v]), t[n] > 2)", "cat")
    # hand sums over rows 3..12 per folded cat key: Ab {5: 3, 9: 0.5}, B {3: blank, 7: 1, 11: 0}, blank {4: 2, 6: blank, 10: 4}, C {8: 0, 12: 1.25}
    assert got == list(zip(TEXT_KEYS, D("3.5", 1, 6, "1.25")))
    for (key, value), predicate in zip(got, ['t[cat] = "Ab"', 't[cat] = "B"', 't[cat] = ""', 't[cat] = "C"']):
        want = gb_case.engine(f"CALCULATE(SUM(t[v]), t[n] > 2, {predicate})")
        assert type(value) is type(want) and value == want, (key, value, want)


def test_group_by_a_text_column_with_a_non_ascii_space_cell_refuses_on_every_execute(tmp_path: Path) -> None:
    case = _fresh_case(tmp_path, ["A", "a", "B", "", "B "])
    try:
        plan = plan_group_by(
            "COUNTROWS(t)", group_by=("t", "cat"), home_table="t", tables={"t": case.types},
            store_tables={"t": "t_csv"}, column_meta=case.meta,
        )
        assert isinstance(plan, GroupByPlan)
        assert plan.execute(case.store) == [("A", Decimal(2)), ("B", Decimal(2)), ("", Decimal(1))]
        case.store.append_rows("t_csv", [["9", " "]])
        out = plan.execute(case.store)
        assert isinstance(out, Refusal) and out.reason == REASON_GROUP_NON_ASCII_SPACE, out
    finally:
        case.store.close()


# (b) filter context ----------------------------------------------------------------------------------

def fc(env: Env, expression: str, *ctx: str) -> Any:
    return env.value(expression, filter_context=tuple(ctx))


def test_filter_context_each_predicate_form_pinned(env: Env) -> None:
    assert fc(env, "COUNTROWS(s)", "s[x] > 5") == Decimal(2)
    assert fc(env, "COUNTROWS(s)", "s[x] > -1") == Decimal(4)  # the blank cell counts as 0
    assert fc(env, "SUM(s[n])", "s[x] = 5") == Decimal(1)
    assert fc(env, "SUM(s[n])", "NOT(s[x] = 5)") == Decimal(14)
    assert fc(env, "SUM(s[n])", "s[x] = 5 || s[x] = 7") == Decimal(5)
    assert fc(env, "COUNTROWS(s)", "s[d] >= 0.25") == Decimal(3)
    assert fc(env, "COUNTROWS(s)", "s[dt] >= DATE(2024, 3, 1)") == Decimal(2)
    assert fc(env, "COUNTROWS(s)", 's[c] = "ab"') == Decimal(2)  # "Ab " and "ab"
    out = fc(env, "COUNTROWS(s)", 's[c] IN {"AB", "it\'s"}')  # column c holds the non-ASCII cell ÄB: guard refusal
    assert isinstance(out, Refusal) and out.reason == REASON_IN_NON_ASCII_COLUMN, out


def test_filter_context_is_anded_with_each_other_and_with_the_measures_own_predicates(env: Env) -> None:
    assert fc(env, "COUNTROWS(s)", "s[x] > 5", "s[d] < 0") == Decimal(1)  # rows 4
    assert fc(env, "CALCULATE(SUM(s[n]), s[d] >= 0)", "s[x] > 5") == Decimal(5)  # row 5 only (row 4 has d < 0)
    assert fc(env, "CALCULATE(SUM(s[n]), s[d] >= 0)", "s[x] > 5", "s[x] < 100") is None
    both = fc(env, "COUNTROWS(s)", "s[x] > 5", "s[x] < 100")
    assert both == Decimal(1)  # two predicates on one column inside the context are intersected
    assert fc(env, "CALCULATE(COUNTROWS(s), s[d] >= 0)", "s[x] >= 5") == Decimal(2)


def test_filter_context_empty_result_is_blank_not_zero(env: Env) -> None:
    for expression in ("COUNTROWS(s)", "SUM(s[n])", "AVERAGE(s[d])", "MIN(s[dt])", "COUNTBLANK(s[c])"):
        assert fc(env, expression, "s[x] > 1000") is None, expression


def test_filter_context_same_column_other_table_and_malformed_are_refused(env: Env) -> None:
    same = env.plan("CALCULATE(SUM(s[n]), s[x] > 5)", filter_context=("s[x] < 100",))
    assert isinstance(same, Refusal) and REASON_SLICER_SAME_COLUMN in same.reason, same
    for bad in ("u[x] > 5", "", "s[x] >", "s[nope] = 1", "s[c] IN {}", "FILTER(s, s[x] > 1)", "s[x] > s[n]"):
        out = env.plan("SUM(s[n])", filter_context=(bad,))
        assert isinstance(out, Refusal), bad
    decision = classify_filter_context(("u[x] > 5",), home_table="s", tables=TABLES)
    assert not decision.allowed and decision.reasons
    assert classify_filter_context((), home_table="s", tables=TABLES).allowed
    assert classify_filter_context(("s[x] > 5",), home_table="s", tables=TABLES).allowed
    blocked = classify_filter_context(("s[x] > 5",), home_table="s", tables=TABLES, blocked_columns=[("S", "X")])
    assert not blocked.allowed and blocked.reasons == (REASON_SLICER_SAME_COLUMN,)


def test_filter_context_with_a_text_in_and_a_numeric_predicate_is_refused(env: Env) -> None:
    out = env.plan('CALCULATE(SUM(s[n]), s[x] > 5)', filter_context=('s[c] IN {"ab"}',))
    assert isinstance(out, Refusal) and "IN" in out.reason, out
    out = env.plan('SUM(s[n])', filter_context=('s[c] IN {"ab"}', "s[x] > 5"))
    assert isinstance(out, Refusal) and "IN" in out.reason, out


def test_filter_context_text_in_pinned_on_an_ascii_column(gb_case: EngineCase) -> None:
    plan = plan_measure(
        "SUM(t[n])", home_table="t", tables={"t": gb_case.types}, store_tables={"t": "t_csv"},
        column_meta=gb_case.meta, filter_context=('t[cat] IN {"AB", "c"}',),
    )
    assert isinstance(plan, MeasurePlan)
    assert plan.execute(gb_case.store) == Decimal(1 + 2 + 5 + 8 + 9 + 12)  # Ab, ab, AB, ab\t, C, c
    assert plan.execute(gb_case.store) == gb_case.engine(with_filter_context("SUM(t[n])", ('t[cat] IN {"AB", "c"}',)))


def test_filter_context_group_by_keeps_the_whole_table_order_and_drops_empty_groups(gb_case: EngineCase) -> None:
    case = gb_case
    # rows 1..5 only (n < 6): groups Ab, B and the blank key survive, C does not; the order is the whole table's
    assert gb(case, "SUM(t[n])", "cat", ctx=("t[n] < 6",)) == [("Ab", Decimal(8)), ("B", Decimal(3)), ("", Decimal(4))]
    # a context that hides row 1 does not move the spelling or the order of the key "Ab"
    got = gb(case, "COUNTROWS(t)", "cat", ctx=("t[n] > 1",))
    assert [k for k, _ in got] == TEXT_KEYS and got[0] == ("Ab", Decimal(3)), got
    # a group whose rows are all removed is gone, not zero or blank
    assert [k for k, _ in gb(case, "COUNTROWS(t)", "dt", ctx=('t[cat] = "B"',))] == ["1/15/2023", "6/1/2026"]
    assert gb(case, "COUNTROWS(t)", "cat", ctx=("t[n] > 100",)) == []
    keys = _parse_engine_keys(case.engine("TOCSV(CALCULATETABLE(VALUES(t[cat]), t[n] < 6), 100000)"))
    assert keys == ["Ab", "B", ""]


def test_filter_context_group_by_on_date_and_boolean_against_the_engine(gb_case: EngineCase) -> None:
    case = gb_case
    for group in ("dt", "flag", "cat"):
        for ctx in (("t[n] > 3",), ("t[v] >= 1",), ('t[cat] = "B"',)):
            if group == "cat" and ctx[0].startswith("t[cat]"):
                continue
            got = gb(case, "SUM(t[n])", group, ctx=ctx)
            keys = _parse_engine_keys(
                case.engine(f"TOCSV(CALCULATETABLE(VALUES(t[{group}]), {', '.join(ctx)}), 100000)")
            )
            assert isinstance(got, list) and [k for k, _ in got] == keys, (group, ctx, got, keys)
            for key, value in got:
                predicate = (
                    f"t[{group}] = {key}()" if group == "flag"
                    else (f"t[{group}] = BLANK()" if key == "" and group == "dt" else (
                        f't[{group}] = ""' if key == "" else (
                            f"t[{group}] = DATE({key.split('/')[2]}, {int(key.split('/')[0])}, {int(key.split('/')[1])})"
                            if group == "dt" else f't[{group}] = "{key}"')))
                )
                want = case.engine(with_filter_context("SUM(t[n])", (predicate, *ctx)))
                assert value == want, (group, ctx, key, value, want)


# (c) the literal sweep ------------------------------------------------------------------------------

import json as _json  # noqa: E402
import zlib as _zlib  # noqa: E402

_BASELINE = _json.loads((Path(__file__).resolve().parent.parent / "tools" / "store_engine_diff_baseline.json").read_text("utf-8"))


def _slice_of(seed: int, parts: int = 40) -> Any:
    """Row filter: the rows whose id hashes to this seed's slice (seeds 1..40 together cover the catalog once)."""
    return lambda row: _zlib.crc32(row["id"].encode("utf-8")) % parts == (seed - 1) % parts


def test_sweep_catalog_ids_are_stable_unique_and_built_from_content() -> None:
    first, second = build_sweep_catalog(), build_sweep_catalog()
    assert [r["id"] for r in first] == [r["id"] for r in second]
    assert len({r["id"] for r in first}) == len(first) >= 1200
    assert all(any(c.isalpha() for c in r["id"]) and "seed" not in r["id"] for r in first)
    shapes = {r["shape"] for r in first}
    for needed in ("whole_<>", "whole_not", "whole_or", "decimal_>=", "date_<", "date_bad_>=", "text_eq", "text_in_ascii",
                   "two_same_column", "two_columns", "empty", "context", "group", "big_text"):
        assert needed in shapes, needed
    assert any(r["group_by"] and r["filter_context"] for r in first)


@pytest.mark.parametrize("seed", range(1, 5))
def test_sweep_slice_every_row_is_same_or_a_baselined_refusal(seed: int) -> None:
    data = run_sweep(rows=300, seed=seed, row_filter=_slice_of(seed))
    results = data["sweep_results"]
    assert len(results) >= 20
    failures = [(r["id"], r["status"], r["error"]) for r in results if r["status"] in ("differs", "sql-error", "crash")]
    assert not failures, failures
    refused = {r["id"] for r in results if r["status"].startswith("refused")}
    assert refused <= set(_BASELINE["sweep_refused"]), sorted(refused - set(_BASELINE["sweep_refused"]))
    assert any(r["status"] == "same" for r in results)


def test_sweep_covers_the_unicode_whitespace_cells_and_refuses_what_the_engine_treats_as_blank() -> None:
    wanted = {r["id"] for r in build_sweep_catalog() if " " in r["id"] or "\u0085" in r["id"]}
    data = run_sweep(rows=300, seed=1, row_filter=lambda r: r["id"] in wanted or (r["shape"] == "group" and r["group_by"][1] == "st" and not r["filter_context"] and r["dax"] == "COUNTROWS(t)"))
    by_id = {r["id"]: r for r in data["sweep_results"]}
    assert all(r["status"] in ("same", "refused-whitelist", "refused-guard") for r in by_id.values()), by_id
    st_group = [r for r in by_id.values() if r["group_by"] == "st"]
    assert st_group and all(r["status"] == "refused-guard" and REASON_GROUP_NON_ASCII_SPACE in r["reason"] for r in st_group)
    literal_rows = [r for r in by_id.values() if r["shape"] in ("text_eq", "text_eq_ascii")]
    assert literal_rows and all(r["status"] == "refused-whitelist" for r in literal_rows)


# (d) forced wrong values exit 1, hooks are inert by default ----------------------------------------------

def test_forced_wrong_value_in_the_sweep_and_in_a_sweep_group_exits_1() -> None:
    scalar_id = "plain: SUM(t[sw])"
    group_id = "group: SUM(t[sw]) | by scat"
    keep = {scalar_id, group_id}
    clean = run_sweep(rows=300, seed=1, row_filter=lambda r: r["id"] in keep)
    assert {r["id"]: r["status"] for r in clean["sweep_results"]} == {scalar_id: "same", group_id: "same"}
    for row_id in (scalar_id, group_id):
        data = run_sweep(
            rows=300, seed=1, overrides={"forced_wrong_sweep_row": row_id}, row_filter=lambda r: r["id"] in keep
        )
        status = {r["id"]: r["status"] for r in data["sweep_results"]}
        assert status[row_id] == "differs" and status[next(i for i in keep if i != row_id)] == "same", status
        code, messages = evaluate_sweep_policy(data["sweep_results"], {"sweep_refused": []})
        assert code == 1 and "sweep failures" in messages[0], messages


def test_sweep_policy_refusal_set_must_equal_the_baseline() -> None:
    results = [
        {"id": "a", "status": "same"}, {"id": "b", "status": "refused-whitelist"}, {"id": "c", "status": "refused-guard"},
    ]
    assert evaluate_sweep_policy(results, {"sweep_refused": ["b", "c"]}) == (0, [])
    assert evaluate_sweep_policy(results, {"sweep_refused": ["b"]})[0] == 1  # a new refusal
    assert evaluate_sweep_policy(results, {"sweep_refused": ["b", "c", "a"]})[0] == 1  # a refusal that went away
    assert evaluate_sweep_policy(results, {})[0] == 1  # no baseline list: every refusal is new
    assert evaluate_sweep_policy([{"id": "x", "status": "crash", "error": "boom"}], {"sweep_refused": []})[0] == 1


def test_default_mode_policy_does_not_read_the_sweep_key() -> None:
    data = {"rows": 1, "results": [], "sweep_results": [{"id": "z", "status": "same"}], "sweep_only": True}
    assert evaluate_exit_policy(data, {"sweep_refused": []}) == (0, [])
    assert evaluate_exit_policy({"rows": 1, "results": []}, {"classes": [], "refused": []}) == (0, [])


def test_catalog_group_by_goes_through_the_planner_and_a_forced_wrong_group_value_exits_1() -> None:
    ids = ["group_by_cat_SUM_w", "group_by_dt_MIN_dt", "group_by_flag_COUNTROWS_all", "group_by_t_AVERAGE_d"]
    data = run_comparison(rows=400, seed=1, use_plan=True, formula_filter=ids)
    by_id = {r["id"]: r for r in data["results"]}
    assert set(by_id) == set(ids)
    assert {r["plan_status"] for r in by_id.values()} <= {"plan-same", "plan-refused"}
    assert by_id["group_by_cat_SUM_w"]["plan_status"] == "plan-same"
    assert by_id["group_by_dt_MIN_dt"]["plan_status"] == "plan-same"
    assert by_id["group_by_flag_COUNTROWS_all"]["plan_status"] == "plan-same"
    assert plan_counts(data["results"])["plan-skipped"] == 0
    forced = run_comparison(
        rows=400, seed=1, use_plan=True, formula_filter=ids, overrides={"forced_wrong_plan_value": "group_by_cat_SUM_w"}
    )
    row = next(r for r in forced["results"] if r["id"] == "group_by_cat_SUM_w")
    assert row["plan_status"] == "plan-differs" and "key" in row["plan_error"], row
    code, _ = evaluate_exit_policy(forced, _BASELINE)
    assert code == 1


def test_parse_engine_keys_handles_a_trailing_blank_key_quotes_and_duplicates() -> None:
    assert _parse_engine_keys("'t'[x]\nA\nB") == ["A", "B"]
    assert _parse_engine_keys("'t'[x]\nA\nB\n") == ["A", "B", ""]  # the blank key shown last
    assert _parse_engine_keys("'t'[x]\n") == [""]
    assert _parse_engine_keys("'t'[x]\n\nA") == ["", "A"]
    assert _parse_engine_keys("'t'[x]\nFALSE\nFALSE\nTRUE") == ["FALSE", "TRUE"]
    assert _parse_engine_keys('\'t\'[x]\n"say ""hi"""\n"a,b"') == ['say "hi"', "a,b"]
    assert _parse_engine_keys("") == []


# (e) mutants --------------------------------------------------------------------------------------------

def _mutant(check: Any, monkeypatch: pytest.MonkeyPatch, patch: Any) -> None:
    check()  # clean
    patch(monkeypatch)
    _fails(check)


@pytest.mark.parametrize(
    "hook, check",
    [
        ("gb_order_sorted", check_text_group),
        ("gb_blank_last", check_text_group),
        ("gb_blank_last", check_date_group),
        ("gb_last_spelling", check_text_group),
        ("gb_no_fold", check_text_group),
        ("gb_date_zero_pad", check_date_group),
        ("gb_bool_true_first", check_bool_group),
        ("gb_avg_float", check_average_group),
    ],
)
def test_mutant_group_by_rules_are_caught(gb_case: EngineCase, hook: str, check: Any) -> None:
    check(gb_case)
    _fails(check, gb_case, {hook: True})


def test_mutant_distinctcount_per_group_without_the_blank_is_caught(gb_case: EngineCase, monkeypatch: pytest.MonkeyPatch) -> None:
    original = dax_sql.aggregate_sql

    def without_blank(*args: Any, **kwargs: Any) -> Any:
        built = original(*args, **kwargs)
        if isinstance(built, str) and args[0] == "DISTINCTCOUNT" and args[2] == "text":
            return built.replace(f"MAX(CASE WHEN {trim_sql(args[1])} = '' THEN 1 ELSE 0 END)", "0")
        return built

    _mutant(lambda: check_distinct_group(gb_case), monkeypatch, lambda mp: mp.setattr(dax_sql, "aggregate_sql", without_blank))


def test_mutant_group_order_by_rowid_instead_of_load_order_on_a_re_sorted_table_is_caught(gb_case: EngineCase) -> None:
    conn = gb_case.store._check_open()
    conn.execute('CREATE OR REPLACE TABLE "t_sorted" AS SELECT * FROM "t_csv" ORDER BY "cat" DESC, "n" DESC')
    try:
        def check(overrides: Any = None) -> None:
            got = gb(gb_case, "SUM(t[n])", "cat", overrides=overrides, store_tables={"t": "t_sorted"})
            assert got == list(zip(TEXT_KEYS, D(17, 21, 20, 20))), got  # load order (__rn), not physical order

        check()
        _fails(check, {"gb_order_rowid": True})
    finally:
        conn.execute('DROP TABLE IF EXISTS "t_sorted"')


def test_mutant_filter_context_or_instead_of_and_is_caught(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def check() -> None:
        assert fc(env, "COUNTROWS(s)", "s[x] > 5", "s[d] < 0") == Decimal(1)
        assert fc(env, "CALCULATE(SUM(s[n]), s[d] >= 0)", "s[x] > 5") == Decimal(5)

    _mutant(check, monkeypatch, lambda mp: mp.setattr(dax_sql, "_AND_JOIN", " OR "))


def test_mutant_filter_dropped_for_group_by_is_caught(gb_case: EngineCase) -> None:
    def check(overrides: Any = None) -> None:
        got = gb(gb_case, "SUM(t[n])", "cat", ctx=("t[n] < 6",), overrides=overrides)
        assert got == [("Ab", Decimal(8)), ("B", Decimal(3)), ("", Decimal(4))], got

    check()
    _fails(check, {"gb_drop_filter": True})


def test_mutant_same_column_check_removed_is_caught(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def check() -> None:
        out = env.plan("CALCULATE(SUM(s[n]), s[x] > 5)", filter_context=("s[x] < 100",))
        assert isinstance(out, Refusal) and REASON_SLICER_SAME_COLUMN in out.reason

    original = dax_sql.classify_filter_context
    _mutant(
        check, monkeypatch,
        lambda mp: mp.setattr(dax_sql, "classify_filter_context", lambda *a, **k: original(*a, **{**k, "blocked_columns": ()})),
    )


@pytest.fixture(scope="module")
def sweep_like_case(tmp_path_factory: pytest.TempPathFactory) -> EngineCase:
    header = ["n", "w", "d", "dt", "c"]
    rows = [
        ["1", "5", "0.000001", "", ""], ["2", "", "0", "1900-01-01", " "], ["3", "-3", "", "1900-01-02", "A"],
        ["4", "0", "0.5", "2024-02-29", "A "], ["5", "7", "-0.25", "", "a b"], ["6", "-0", "123456789012345678.123456", "2026-06-01", ""],
        ["7", "", "0.000001", "9999-12-31", "A"], ["8", "100", "1", "1900-01-01", "  "],
    ]
    case = EngineCase(tmp_path_factory.mktemp("sw"), header, rows)
    yield case
    case.store.close()


def test_mutant_decimal_literal_compared_at_the_column_scale_is_caught(sweep_like_case: EngineCase, monkeypatch: pytest.MonkeyPatch) -> None:
    case = sweep_like_case
    assert case.meta[("t", "d")].scale == 6

    def check() -> None:
        for op in (">=", "<", "<>"):
            case.same_as_engine(f"CALCULATE(COUNTROWS(t), t[d] {op} 0.0000004)")
            case.same_as_engine(f"CALCULATE(COUNTROWS(t), t[d] {op} -0.0000005)")

    original = dax_sql.decimal_predicate_sql
    _mutant(check, monkeypatch, lambda mp: mp.setattr(dax_sql, "decimal_predicate_sql", lambda col, op, lit, scale: original(col, op, lit, min(scale, 6))))


def test_mutant_blank_as_zero_dropped_for_a_negative_whole_literal_is_caught(sweep_like_case: EngineCase, monkeypatch: pytest.MonkeyPatch) -> None:
    def check() -> None:
        for op in (">", ">=", "<>"):
            sweep_like_case.same_as_engine(f"CALCULATE(COUNTROWS(t), t[w] {op} -1)")

    _mutant(
        check, monkeypatch,
        lambda mp: mp.setattr(
            dax_sql, "whole_predicate_sql",
            lambda col, op, lit: f"TRY_CAST(NULLIF({col}, '') AS HUGEINT) {dax_sql._SQL_OPERATORS[op]} {int(lit)}",
        ),
    )


def test_mutant_blank_date_default_dropped_at_the_1900_boundary_is_caught(sweep_like_case: EngineCase, monkeypatch: pytest.MonkeyPatch) -> None:
    def check() -> None:
        for op in ("<", "<=", "<>"):
            sweep_like_case.same_as_engine(f"CALCULATE(COUNTROWS(t), t[dt] {op} DATE(1900, 1, 1))")

    original = dax_sql.date_predicate_sql
    _mutant(
        check, monkeypatch,
        lambda mp: mp.setattr(dax_sql, "date_predicate_sql", lambda c, o, d: original(c, o, d).replace("DATE '1899-12-30'", "DATE '1900-01-01'")),
    )


@pytest.mark.parametrize("literal", ['" "', '"A "', '"  "'])
def test_mutant_text_literal_trimmed_is_caught(sweep_like_case: EngineCase, monkeypatch: pytest.MonkeyPatch, literal: str) -> None:
    def check() -> None:
        sweep_like_case.same_as_engine(f"CALCULATE(COUNTROWS(t), t[c] = {literal})")

    original = dax_sql._fold_literal
    _mutant(check, monkeypatch, lambda mp: mp.setattr(dax_sql, "_fold_literal", lambda text: original(text).strip()))


def test_mutant_38_digit_precision_refusal_removed_is_caught(sweep_like_case: EngineCase, monkeypatch: pytest.MonkeyPatch) -> None:
    case = sweep_like_case

    def check() -> None:
        plan = case.plan("CALCULATE(COUNTROWS(t), t[d] >= 0.123456789012345678901234567890)")
        assert isinstance(plan, Refusal) and plan.reason == dax_sql.REASON_DECIMAL_LITERAL_FIT, plan

    _mutant(check, monkeypatch, lambda mp: mp.setattr(dax_sql, "MAX_DECIMAL_TOTAL", 10**6))
