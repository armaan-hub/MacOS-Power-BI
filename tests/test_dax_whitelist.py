"""Tests for DAX whitelist classifier for the store SQL path (Stage C1a).

Covers:
(i) Differential test against formula catalog and generate_sql (Rule A and Rule B).
(ii) Hand-written negative table of at least 30 expressions (one per refusal reason).
(iii) Hand-written positive table of at least 20 expressions (shape & table check).
(iv) Safety mutants (7 mutants monkeypatched, each failing by behaviour).
(v) Fuzz generator of 300 AST expressions.
"""

from __future__ import annotations

import csv
import random
import tempfile
from pathlib import Path
from typing import Any

import pytest

from analytics_studio.store import DuckStore
from analytics_studio.store.dax_whitelist import (
    REASON_ARITHMETIC,
    REASON_ARITH_DATE,
    REASON_ARITH_DIVIDE_ALT,
    REASON_ARITH_IN_CALCULATE,
    REASON_ARITH_LITERAL,
    REASON_BLANK_COMPARISON,
    REASON_BOOLEAN_LITERAL,
    REASON_DISTINCTCOUNTNOBLANK,
    REASON_LET,
    REASON_LOGICAL_AND,
    REASON_MAX_DEPTH_EXCEEDED,
    REASON_NESTED_CALCULATE,
    REASON_TWO_COLUMNS,
    WhitelistDecision,
    classify_measure,
)
from analytics_studio.store.type_detect import detect_column_types
from tools.store_engine_diff import build_formula_catalog, generate_dataset, generate_sql


@pytest.fixture(scope="module")
def dataset_and_catalog() -> tuple[dict[str, str], list[dict[str, Any]], list[str]]:
    """Build dataset, detect column types and build formula catalog once."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        csv_p = p / "data.csv"
        pq_p = p / "data.parquet"
        db_p = str(p / "store.duckdb")

        generate_dataset(csv_p, pq_p, rows=100, seed=42)
        with open(csv_p, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
            rows = list(reader)

        store = DuckStore(db_p)
        try:
            store.create_table("t", [(h, "text") for h in headers])
            store.append_rows("t", rows)
            col_types = detect_column_types(store, "t")
        finally:
            store.close()

        catalog = build_formula_catalog(headers)
        return col_types, catalog, headers


# ---------------------------------------------------------------------------
# (i) Differential Test: Catalog vs Whitelist (Rule A & Rule B)
# ---------------------------------------------------------------------------

def test_differential_catalog_rules(dataset_and_catalog, rules_runs):
    col_types, catalog, headers = dataset_and_catalog
    tables = {"t": col_types}
    # Rule A uses the cached rules tool run at 2000 rows, seed 42 (same as the test below).
    by_id = rules_runs[(2000, 42)]

    allowed_count = 0
    refused_count = 0
    skipped_count = 0
    rule_b_by_shape: dict[str, int] = {}

    for f in catalog:
        dax = f.get("dax")
        # Skip group_by pseudo-DAX, and formulas the rules tool does not run (forced_wrong_formula)
        if not dax or f.get("group_col") or dax.startswith("group_by(") or f["id"] not in by_id:
            skipped_count += 1
            continue

        decision = classify_measure(dax, home_table="t", tables=tables)

        if decision.allowed:
            allowed_count += 1
            # Rule A (safety): if allowed, the rules tool mapped status must be 'same' with no refusal
            r = by_id[f["id"]]
            assert r["mapped_status"] == "same" and r["mapped_refusal"] is None, (
                f"Rule A violated for {f['id']} ({dax}): mapped {r['mapped_status']} {r['mapped_refusal']}"
            )
            # Verify shape matches catalog shape
            assert decision.shape == f["shape"], (
                f"Shape mismatch for {f['id']}: whitelist {decision.shape} != catalog {f['shape']}"
            )
            assert decision.table == "t"
        else:
            refused_count += 1
            # Rule B (completeness): count formulas refused that mapped generate_sql can produce
            sql = generate_sql(f, "t_csv", col_types, mode="mapped")
            if isinstance(sql, str):
                shape = f["shape"]
                rule_b_by_shape[shape] = rule_b_by_shape.get(shape, 0) + 1

    # Assert catalog numbers
    assert skipped_count == 29
    assert allowed_count == 575  # (C4b) the five arithmetic formulas over totals are allowed now (570 before)
    assert refused_count == 239
    assert len(catalog) == 843

    # Rule B counts: formulas the mapped store can do that whitelist refuses. The 61 DISTINCTCOUNT
    # ones are refused on purpose (numeric DISTINCTCOUNT differs from the engine); the SUMX iterators stay refused.
    expected_rule_b = {"SUMX": 2, "DISTINCTCOUNT": 3, "DISTINCTCOUNT_filtered": 58}
    assert rule_b_by_shape == expected_rule_b


# ---------------------------------------------------------------------------
# (ii) Hand-written negative table of at least 30 expressions (one per reason)
# ---------------------------------------------------------------------------

NEGATIVE_CASES = [
    # 1-3. (C4b) + - / over totals are allowed now (POSITIVE_CASES); these are the arithmetic forms still refused
    ("SUM(t[w]) ^ 2", "t", REASON_ARITHMETIC),
    ("SUM(t[w]) & 1", "t", "node kind concat is not on the store whitelist"),
    ("+SUM(t[w])", "t", REASON_ARITHMETIC),
    ("MAX(t[dt]) - MIN(t[dt])", "t", REASON_ARITH_DATE),
    ("MIN(t[dt]) + 1", "t", REASON_ARITH_DATE),
    ("ROUND(SUM(t[w]), 2) + 1", "t", "function ROUND is not on the store whitelist"),
    ("SUM(t[w]) + SUMX(t, t[w])", "t", "function SUMX is not on the store whitelist"),
    ("SUM(t[w]) + 9223372036854775808", "t", REASON_ARITH_LITERAL),
    ("SUM(t[w]) * 1e400", "t", REASON_ARITH_LITERAL),
    ("DIVIDE(SUM(t[w]), 0, BLANK())", "t", REASON_ARITH_DIVIDE_ALT),
    ("DIVIDE(SUM(t[w]), 0, SUM(t[d]))", "t", "DIVIDE alternate result must be a constant numeric value or BLANK()"),
    ("SUM(t[w]) + SUM(t[cat])", "t", "SUM not supported on text column"),
    ("SUM(t[w]) + COUNTROWS(s)", "t", "multiple tables"),
    ("1 + 2", "t", "measure references no tables"),
    ("IF(SUM(t[w]) > 1, 1, 2) + 1", "t", "function IF is not on the store whitelist"),
    ('CALCULATE(SUM(t[w]) + 1, t[cat] = "A")', "t", REASON_ARITHMETIC),
    ("CALCULATE([ArithM], t[cat] = \"A\") + 1", "t", REASON_ARITH_IN_CALCULATE),
    ("[ArithM] + [CycleA]", "t", "cycle detected in measure reference"),
    ("[ArithM] + [NoSuchMeasure]", "t", "unknown column or measure 'NoSuchMeasure'"),
    # 4. SUMX iterator
    ("SUMX(t, t[w])", "t", "function SUMX is not on the store whitelist"),
    # 5. FILTER iterator
    ("CALCULATE(COUNTROWS(t), FILTER(t, t[w] > 0))", "t", "function FILTER is not on the store whitelist"),
    # 6. ALL table modifier
    ("CALCULATE(SUM(t[w]), ALL(t))", "t", "function ALL is not on the store whitelist"),
    # 7. ALLEXCEPT modifier
    ("CALCULATE(SUM(t[w]), ALLEXCEPT(t, t[cat]))", "t", "function ALLEXCEPT is not on the store whitelist"),
    # 8. VAR / RETURN ('let')
    ("VAR x = 1 RETURN SUM(t[w])", "t", REASON_LET),
    # 9. (C4b) DIVIDE over totals is allowed now (POSITIVE_CASES); a computed alternate is a parse error
    ("DIVIDE(SUM(t[w]), 2, SUM(t[d]) + 1)", "t", "DIVIDE alternate result must be a constant numeric value or BLANK()"),
    # 10. Logical && in predicate
    ('CALCULATE(COUNTROWS(t), t[w] > 5 && t[cat] = "A")', "t", REASON_LOGICAL_AND),
    # 11. Numeric IN predicate
    ("CALCULATE(SUM(t[w]), t[w] IN {1, 2})", "t", "IN filter not supported on whole_number column"),
    # 12. Decimal IN predicate
    ("CALCULATE(SUM(t[w]), t[d] IN {1.0, 2.0})", "t", "IN filter not supported on decimal_number column"),
    # 13. Date IN predicate
    ("CALCULATE(SUM(t[w]), t[dt] IN {DATE(2026, 1, 1)})", "t", "IN filter not supported on date column"),
    # 14. COUNT of text column
    ("COUNT(t[cat])", "t", "COUNT not supported on text column"),
    # 15. COUNT of boolean column
    ("COUNT(t[flag])", "t", "COUNT not supported on boolean column"),
    # 16. SUM of text column
    ("SUM(t[cat])", "t", "SUM not supported on text column"),
    # 17. SUM of boolean column
    ("SUM(t[flag])", "t", "SUM not supported on boolean column"),
    # 18. SUM of date column
    ("SUM(t[dt])", "t", "SUM not supported on date column"),
    # 19. AVERAGE of text column
    ("AVERAGE(t[cat])", "t", "AVERAGE not supported on text column"),
    # 20. AVERAGE of boolean column
    ("AVERAGE(t[flag])", "t", "AVERAGE not supported on boolean column"),
    # 21. AVERAGE of date column
    ("AVERAGE(t[dt])", "t", "AVERAGE not supported on date column"),
    # 22. MIN of text column
    ("MIN(t[cat])", "t", "MIN not supported on text column"),
    # 23. MIN of boolean column
    ("MIN(t[flag])", "t", "MIN not supported on boolean column"),
    # 24. MAX of text column
    ("MAX(t[cat])", "t", "MAX not supported on text column"),
    # 25. MAX of boolean column
    ("MAX(t[flag])", "t", "MAX not supported on boolean column"),
    # 26. DISTINCTCOUNTNOBLANK
    ("DISTINCTCOUNTNOBLANK(t[w])", "t", REASON_DISTINCTCOUNTNOBLANK),
    # 27. Two tables in one expression
    ("CALCULATE(SUM(t[w]), s[val] = 1)", "t", "measure references multiple tables: s, t"),
    # 28. Unknown table
    ("SUM(nosuchtable[w])", "t", "unknown table 'nosuchtable'"),
    # 29. Unknown column in known table
    ("SUM(t[nosuchcol])", "t", "unknown column 'nosuchcol' in table 't'"),
    # 30. Unknown column in home table via unqualified reference
    ("SUM([nosuchcol])", "t", "unknown column or measure 'nosuchcol'"),
    # 31. Cycle in measure references: A -> B -> A
    ("[CycleA]", "t", "cycle detected in measure reference 'CycleA'"),
    # 32. Unknown measure name
    ("[NoSuchMeasure]", "t", "unknown column or measure 'NoSuchMeasure'"),
    # 33. Parse error (invalid DAX syntax)
    ("SUM(t[w] +++", "t", "parse error"),
    # 34. Nested CALCULATE filters
    ("CALCULATE([FilteredMeasure], t[cat] = \"B\")", "t", REASON_NESTED_CALCULATE),
    # 35. Time intelligence function (desugars to CALCULATE(..., DATESYTD(...)))
    ("TOTALYTD(SUM(t[w]), t[dt])", "t", "function DATESYTD is not on the store whitelist"),
    # 36. BLANK() comparison in predicate
    ("CALCULATE(SUM(t[w]), t[w] = BLANK())", "t", REASON_BLANK_COMPARISON),
    # 37. Boolean literal in predicate
    ("CALCULATE(SUM(t[w]), t[flag] = TRUE)", "t", REASON_BOOLEAN_LITERAL),
    # 38. Column-to-column comparison in predicate
    ("CALCULATE(SUM(t[w]), t[w] = t[d])", "t", REASON_TWO_COLUMNS),
    # 39. Literal type mismatch: string against number column
    ("CALCULATE(SUM(t[w]), t[w] = \"hello\")", "t", "literal type string does not fit whole_number column"),
    # 40. Literal type mismatch: number against text column
    ("CALCULATE(SUM(t[w]), t[cat] = 123)", "t", "literal type number does not fit text column"),
    # 41. Literal type mismatch: number against date column
    ("CALCULATE(SUM(t[w]), t[dt] = 2026)", "t", "literal type number does not fit date column"),
    # 42. IF conditional function
    ("IF(SUM(t[w]) > 0, 1, 0)", "t", "function IF is not on the store whitelist"),
    # 43. SWITCH conditional function
    ("SWITCH(t[cat], \"A\", 1, 0)", "t", "function SWITCH is not on the store whitelist"),
    # 44. NOT over a text column (moved from positive table; NOT is whole-number = only)
    ('CALCULATE(MAX(t[w]), NOT(t[cat] = "A"))', "t",
     "NOT and || are only on the store whitelist over whole-number = comparisons"),
    # 45. || over a text column (moved from positive table; || is whole-number = only)
    ('CALCULATE(COUNTA(t[cat]), t[cat] = "A" || t[cat] = "B")', "t",
     "NOT and || are only on the store whitelist over whole-number = comparisons"),
    # 46. Numeric DISTINCTCOUNT under a text IN filter (moved from positive table)
    ('CALCULATE(DISTINCTCOUNT(t[w]), t[cat] IN {"A", "B", "C"})', "t",
     "DISTINCTCOUNT on a numeric column differs from the engine "
     "(open Power BI answer check: distinct_numeric_text_variants)"),
    # 47. NOT over a text column, lowercase with extra whitespace (moved from positive table)
    ('  calculate(  sum( t[w] ),   not( t[cat] = "A" ) )  ', "t",
     "NOT and || are only on the store whitelist over whole-number = comparisons"),
]


@pytest.mark.parametrize("dax, home_table, expected_reason", NEGATIVE_CASES)
def test_negative_expressions(dax, home_table, expected_reason):
    tables = {
        "t": {
            "w": "whole_number",
            "d": "decimal_number",
            "dt": "date",
            "cat": "text",
            "flag": "boolean",
        },
        "s": {
            "val": "whole_number",
        },
    }
    measures = {
        "cyclea": "[CycleB]",
        "cycleb": "[CycleA]",
        "filteredmeasure": 'CALCULATE(SUM(t[w]), t[cat] = "A")',
        "arithm": "SUM(t[w]) / COUNTROWS(t)",
    }

    decision = classify_measure(dax, home_table=home_table, tables=tables, measures=measures)
    assert not decision.allowed, f"Expected {dax} to be refused, but was allowed"
    if expected_reason == "parse error":
        assert len(decision.reasons) > 0
    else:
        assert any(expected_reason in r for r in decision.reasons), (
            f"Expected reason containing {expected_reason!r}, got {decision.reasons}"
        )


# ---------------------------------------------------------------------------
# (iii) Hand-written positive table of at least 20 expressions
# ---------------------------------------------------------------------------

POSITIVE_CASES = [
    # 1. Base SUM on whole_number
    ("SUM(t[w])", "t", "SUM", "t"),
    # 2. Base SUM on decimal_number
    ("SUM(t[d])", "t", "SUM", "t"),
    # 3. Base AVERAGE on whole_number
    ("AVERAGE(t[w])", "t", "AVERAGE", "t"),
    # 4. Base AVERAGE on decimal_number
    ("AVERAGE(t[d])", "t", "AVERAGE", "t"),
    # 5. Base MIN on whole_number
    ("MIN(t[w])", "t", "MIN", "t"),
    # 6. Base MIN on date
    ("MIN(t[dt])", "t", "MIN", "t"),
    # 7. Base MAX on decimal_number
    ("MAX(t[d])", "t", "MAX", "t"),
    # 8. Base MAX on date
    ("MAX(t[dt])", "t", "MAX", "t"),
    # 9. Base COUNT on whole_number
    ("COUNT(t[w])", "t", "COUNT", "t"),
    # 10. Base COUNT on date
    ("COUNT(t[dt])", "t", "COUNT", "t"),
    # 11. Base COUNTA on text
    ("COUNTA(t[cat])", "t", "COUNTA", "t"),
    # 12. Base COUNTA on boolean
    ("COUNTA(t[flag])", "t", "COUNTA", "t"),
    # 13. Base COUNTBLANK on whole_number
    ("COUNTBLANK(t[w])", "t", "COUNTBLANK", "t"),
    # 14. Base COUNTBLANK on text
    ("COUNTBLANK(t[cat])", "t", "COUNTBLANK", "t"),
    # 15. Base DISTINCTCOUNT on text
    ("DISTINCTCOUNT(t[cat])", "t", "DISTINCTCOUNT", "t"),
    # 16. Base DISTINCTCOUNT on date
    ("DISTINCTCOUNT(t[dt])", "t", "DISTINCTCOUNT", "t"),
    # 17. Base COUNTROWS
    ("COUNTROWS(t)", "t", "COUNTROWS", "t"),
    # 18. CALCULATE SUM with equality filter
    ('CALCULATE(SUM(t[w]), t[cat] = "A")', "t", "SUM_filtered", "t"),
    # 19. CALCULATE COUNTROWS with inequality filter
    ("CALCULATE(COUNTROWS(t), t[w] <> 100)", "t", "COUNTROWS_filtered", "t"),
    # 20. CALCULATE AVERAGE with comparison operators (<, >=)
    ("CALCULATE(AVERAGE(t[d]), t[d] >= 0, t[d] < 100.5)", "t", "AVERAGE_filtered", "t"),
    # 21. CALCULATE with DATE literal
    ("CALCULATE(COUNT(t[w]), t[dt] >= DATE(2026, 6, 1))", "t", "COUNT_filtered", "t"),
    # 22. CALCULATE with unary minus on number
    ("CALCULATE(MIN(t[w]), t[w] > -10)", "t", "MIN_filtered", "t"),
    # 23. Case-insensitive table and column names
    ('CALCULATE(SUM(T[W]), T[CAT] = "A")', "t", "SUM_filtered", "t"),
    # 24. Transitive measure reference (bare [BaseSum])
    ("[BaseSum]", "t", "SUM", "t"),
    # 25. Transitive measure in CALCULATE with filter
    ('CALCULATE([BaseSum], t[cat] = "A")', "t", "SUM_filtered", "t"),
    # 26. Unqualified column in home table inside AGG
    ("SUM([w])", "t", "SUM", "t"),
    # 27-35. (C4b) arithmetic over totals: shape ARITH on the table of the totals
    ("SUM(t[w]) + 1", "t", "ARITH", "t"),
    ("AVERAGE(t[w]) - MIN(t[w])", "t", "ARITH", "t"),
    ("SUM(t[d]) / COUNT(t[d])", "t", "ARITH", "t"),
    ("DIVIDE(SUM(t[w]), 2)", "t", "ARITH", "t"),
    ("DIVIDE(SUM(t[w]), COUNTROWS(t), -1)", "t", "ARITH", "t"),
    ("-SUM(t[d])", "t", "ARITH", "t"),
    ("(SUM(t[w]) + 1) * 2 - COUNTROWS(t) / 3", "t", "ARITH", "t"),
    ('DIVIDE(CALCULATE(SUM(t[d]), t[cat] = "A"), SUM(t[d]))', "t", "ARITH", "t"),
    ("[BaseSum] / COUNTROWS(t)", "t", "ARITH", "t"),
    ("CALCULATE([BaseSum], t[cat] = \"A\") - [BaseSum]", "t", "ARITH", "t"),
]


@pytest.mark.parametrize("dax, home_table, expected_shape, expected_table", POSITIVE_CASES)
def test_positive_expressions(dax, home_table, expected_shape, expected_table):
    tables = {
        "t": {
            "w": "whole_number",
            "d": "decimal_number",
            "dt": "date",
            "cat": "text",
            "flag": "boolean",
        }
    }
    measures = {
        "basesum": "SUM(t[w])",
    }
    decision = classify_measure(dax, home_table=home_table, tables=tables, measures=measures)
    assert decision.allowed, f"Expected {dax} to be allowed, reasons: {decision.reasons}"
    assert decision.shape == expected_shape, f"Expected shape {expected_shape}, got {decision.shape}"
    assert decision.table == expected_table, f"Expected table {expected_table}, got {decision.table}"
    assert decision.reasons == ()


# ---------------------------------------------------------------------------
# (iv) Safety Mutants (7 mutants monkeypatched, each failing by behaviour)
# ---------------------------------------------------------------------------

def test_mutant_1_allow_logical_and(monkeypatch):
    """Mutant 1: add '&&' to admitted predicate operators. Must allow && filter which Rule A refuses."""
    from analytics_studio.store import dax_whitelist
    tables = {"t": {"w": "whole_number", "cat": "text"}}
    dax = 'CALCULATE(COUNTROWS(t), t[w] > 5 && t[cat] = "A")'

    # Baseline check: normally refused
    assert not classify_measure(dax, home_table="t", tables=tables).allowed

    # Apply mutant: monkeypatch _check_predicate to treat && as allowed logical op
    orig_check_predicate = dax_whitelist._check_predicate
    def mutant_check_predicate(node, t_norm, t_orig, h_norm, m_norm, reasons, ref_tables):
        if node[0] == "logical" and node[1] == "&&":
            mutant_check_predicate(node[2], t_norm, t_orig, h_norm, m_norm, reasons, ref_tables)
            mutant_check_predicate(node[3], t_norm, t_orig, h_norm, m_norm, reasons, ref_tables)
            return
        orig_check_predicate(node, t_norm, t_orig, h_norm, m_norm, reasons, ref_tables)

    monkeypatch.setattr(dax_whitelist, "_check_predicate", mutant_check_predicate)
    decision = classify_measure(dax, home_table="t", tables=tables)
    assert decision.allowed, "Mutant 1 should have caused && to be allowed"

    # Confirm Rule A failure: mapped generate_sql refuses this formula
    f = {"agg": "COUNTROWS", "col": None, "filter_type": "filter_two_cols"}
    sql = generate_sql(f, "t_csv", {"w": "whole_number", "cat": "text"}, mode="mapped")
    assert not isinstance(sql, str), "generate_sql must refuse filter_two_cols (Rule A fails under mutant 1)"


def test_mutant_2_allow_numeric_in(monkeypatch):
    """Mutant 2: allow IN on numeric columns. Must allow numeric IN which Rule A refuses."""
    from analytics_studio.store import dax_whitelist
    tables = {"t": {"w": "whole_number"}}
    dax = "CALCULATE(SUM(t[w]), t[w] IN {1, 2})"

    # Baseline check: normally refused
    assert not classify_measure(dax, home_table="t", tables=tables).allowed

    # Apply mutant: monkeypatch to accept numeric IN
    orig_check_predicate = dax_whitelist._check_predicate
    def mutant_check_predicate(node, t_norm, t_orig, h_norm, m_norm, reasons, ref_tables):
        if node[0] == "in":
            ref_tables.add("t")
            return
        orig_check_predicate(node, t_norm, t_orig, h_norm, m_norm, reasons, ref_tables)

    monkeypatch.setattr(dax_whitelist, "_check_predicate", mutant_check_predicate)
    decision = classify_measure(dax, home_table="t", tables=tables)
    assert decision.allowed, "Mutant 2 should have caused numeric IN to be allowed"

    # Confirm Rule A failure: mapped generate_sql refuses numeric IN
    f = {"agg": "SUM", "col": "w", "filter_type": "w_in"}
    sql = generate_sql(f, "t_csv", {"w": "whole_number"}, mode="mapped")
    assert not isinstance(sql, str), "generate_sql must refuse w_in (Rule A fails under mutant 2)"


def test_mutant_3_allow_sum_on_text(monkeypatch):
    """Mutant 3: allow SUM on text columns. Must allow SUM(t[cat]) which Rule A refuses."""
    from analytics_studio.store import dax_whitelist
    tables = {"t": {"cat": "text"}}
    dax = "SUM(t[cat])"

    # Baseline check: normally refused
    assert not classify_measure(dax, home_table="t", tables=tables).allowed

    # Apply mutant: monkeypatch ALLOWED_AGGREGATES to include 'text' for SUM
    mutant_aggs = dict(dax_whitelist.ALLOWED_AGGREGATES)
    mutant_aggs["SUM"] = mutant_aggs["SUM"] | {"text"}
    monkeypatch.setattr(dax_whitelist, "ALLOWED_AGGREGATES", mutant_aggs)

    decision = classify_measure(dax, home_table="t", tables=tables)
    assert decision.allowed, "Mutant 3 should have allowed SUM on text"

    # Confirm Rule A failure: mapped generate_sql refuses SUM on text
    f = {"agg": "SUM", "col": "cat", "filter_type": None}
    sql = generate_sql(f, "t_csv", {"cat": "text"}, mode="mapped")
    assert not isinstance(sql, str), "generate_sql must refuse SUM on text (Rule A fails under mutant 3)"


def test_mutant_4_allow_distinctcountnoblank(monkeypatch):
    """Mutant 4: allow DISTINCTCOUNTNOBLANK. Must allow it, but store mapped path refuses it."""
    from analytics_studio.store import dax_whitelist
    tables = {"t": {"w": "whole_number"}}
    dax = "DISTINCTCOUNTNOBLANK(t[w])"

    # Baseline check: normally refused
    assert not classify_measure(dax, home_table="t", tables=tables).allowed

    # Apply mutant: monkeypatch ALLOWED_AGGREGATES to include DISTINCTCOUNTNOBLANK and drop refusal
    mutant_aggs = dict(dax_whitelist.ALLOWED_AGGREGATES)
    mutant_aggs["DISTINCTCOUNTNOBLANK"] = frozenset({"whole_number", "text"})
    monkeypatch.setattr(dax_whitelist, "ALLOWED_AGGREGATES", mutant_aggs)
    orig_classify_base = dax_whitelist._classify_base_aggregate

    def mutant_classify_base(node, t_norm, t_orig, h_norm, m_norm):
        if node[0] == "call" and node[1] == "DISTINCTCOUNTNOBLANK":
            return WhitelistDecision(True, "t", "DISTINCTCOUNTNOBLANK", ())
        return orig_classify_base(node, t_norm, t_orig, h_norm, m_norm)

    monkeypatch.setattr(dax_whitelist, "_classify_base_aggregate", mutant_classify_base)

    decision = classify_measure(dax, home_table="t", tables=tables)
    assert decision.allowed, "Mutant 4 should have allowed DISTINCTCOUNTNOBLANK"

    # Confirm Rule A failure: mapped generate_sql refuses DISTINCTCOUNTNOBLANK
    f = {"agg": "DISTINCTCOUNTNOBLANK", "col": "w", "filter_type": None}
    sql = generate_sql(f, "t_csv", {"w": "whole_number"}, mode="mapped")
    assert not isinstance(sql, str), "generate_sql must refuse DISTINCTCOUNTNOBLANK (Rule A fails under mutant 4)"


def test_mutant_5_drop_one_table_check(monkeypatch):
    """Mutant 5: drop the one-table check in CALCULATE. Must allow multi-table expression."""
    from analytics_studio.store import dax_whitelist
    tables = {"t": {"w": "whole_number"}, "s": {"val": "whole_number"}}
    dax = "CALCULATE(SUM(t[w]), s[val] = 1)"

    # Baseline check: normally refused
    assert not classify_measure(dax, home_table="t", tables=tables).allowed

    orig_classify = dax_whitelist.classify_measure
    def mutant_classify(expr, *, home_table, tables, measures=None, _depth=0, _visited=None):
        dec = orig_classify(expr, home_table=home_table, tables=tables, measures=measures, _depth=_depth, _visited=_visited)
        # Filter out multiple tables reason
        new_reasons = tuple(r for r in dec.reasons if "measure references multiple tables" not in r)
        return WhitelistDecision(
            allowed=len(new_reasons) == 0,
            table="t",
            shape=dec.shape or "SUM_filtered",
            reasons=new_reasons,
        )

    monkeypatch.setattr(dax_whitelist, "classify_measure", mutant_classify)
    decision = dax_whitelist.classify_measure(dax, home_table="t", tables=tables)
    assert decision.allowed, "Mutant 5 should have dropped the multi-table refusal"


def test_mutant_6_drop_cycle_check(monkeypatch):
    """Mutant 6: drop the cycle check. Must recurse or hit depth cap instead of catching cycle."""
    from analytics_studio.store import dax_whitelist
    tables = {"t": {"w": "whole_number"}}
    measures = {"cyclea": "[CycleB]", "cycleb": "[CycleA]"}
    dax = "[CycleA]"

    # Baseline check: catches cycle
    dec = classify_measure(dax, home_table="t", tables=tables, measures=measures)
    assert not dec.allowed
    assert "cycle detected" in dec.reasons[0]

    # Mutant: bypass visited set check
    orig_classify = dax_whitelist.classify_measure
    def mutant_classify(expr, *, home_table, tables, measures=None, _depth=0, _visited=None):
        return orig_classify(expr, home_table=home_table, tables=tables, measures=measures, _depth=_depth, _visited=frozenset())

    monkeypatch.setattr(dax_whitelist, "classify_measure", mutant_classify)
    decision = dax_whitelist.classify_measure(dax, home_table="t", tables=tables, measures=measures)
    # The cycle check did not fire; it hit the depth cap instead
    assert not any("cycle detected" in r for r in decision.reasons)
    assert REASON_MAX_DEPTH_EXCEEDED in decision.reasons


def test_mutant_7_default_allow_unknown_nodes(monkeypatch):
    """Mutant 7: make default ALLOW for unknown node kinds."""
    from analytics_studio.store import dax_whitelist
    tables = {"t": {"w": "whole_number"}}
    dax = "VAR x = 1 RETURN SUM(t[w])"

    # Baseline check: let is refused
    assert not classify_measure(dax, home_table="t", tables=tables).allowed

    orig_classify_base = dax_whitelist._classify_base_aggregate
    def mutant_classify_base(node, t_norm, t_orig, h_norm, m_norm):
        if node[0] == "let":
            return WhitelistDecision(True, "t", "LET", ())
        return orig_classify_base(node, t_norm, t_orig, h_norm, m_norm)

    monkeypatch.setattr(dax_whitelist, "_classify_base_aggregate", mutant_classify_base)
    decision = classify_measure(dax, home_table="t", tables=tables)
    assert decision.allowed, "Mutant 7 should have allowed unknown/let node"


# ---------------------------------------------------------------------------
# (v) Fuzz: 300 random AST expressions
# ---------------------------------------------------------------------------

def test_fuzz_ast_classifier(dataset_and_catalog):
    """Generate 300 random expressions from AST grammar; assert classify never raises and Rule A holds."""
    col_types, catalog, headers = dataset_and_catalog
    tables = {"t": col_types}

    rnd = random.Random(1337)
    aggs = ["SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "COUNTBLANK", "DISTINCTCOUNT", "COUNTROWS", "DISTINCTCOUNTNOBLANK", "SUMX", "DIVIDE"]
    cols = headers + ["missing_col"]
    ops = ["=", "<>", "<", "<=", ">", ">=", "&&", "||", "+", "-", "*", "/"]
    lit_vals = ["1", "0", "-5", '"A"', '"west"', "DATE(2026, 6, 1)", "BLANK()", "TRUE", "FALSE"]

    catalog_by_dax = {f.get("dax"): f for f in catalog if f.get("dax")}

    for i in range(300):
        # Pick random structure
        choice = rnd.randint(0, 4)
        if choice == 0:
            agg = rnd.choice(aggs)
            if agg == "COUNTROWS":
                expr = "COUNTROWS(t)"
            else:
                c = rnd.choice(cols)
                expr = f"{agg}(t[{c}])"
        elif choice == 1:
            agg = rnd.choice(aggs)
            c = rnd.choice(cols)
            op = rnd.choice(ops)
            lit = rnd.choice(lit_vals)
            expr = f"CALCULATE({agg}(t[{c}]), t[{c}] {op} {lit})"
        elif choice == 2:
            agg = rnd.choice(aggs)
            c1 = rnd.choice(cols)
            c2 = rnd.choice(cols)
            op1 = rnd.choice(["=", "<", ">"])
            op2 = rnd.choice(["=", "<", ">"])
            lit1 = rnd.choice(lit_vals)
            lit2 = rnd.choice(lit_vals)
            conn = rnd.choice(["&&", "||", ", "])
            if conn == ", ":
                expr = f"CALCULATE({agg}(t[{c1}]), t[{c1}] {op1} {lit1}, t[{c2}] {op2} {lit2})"
            else:
                expr = f"CALCULATE({agg}(t[{c1}]), t[{c1}] {op1} {lit1} {conn} t[{c2}] {op2} {lit2})"
        elif choice == 3:
            c = rnd.choice(cols)
            lit_set = ", ".join(rnd.choice(['"A"', '"B"', '1', '2']) for _ in range(rnd.randint(1, 3)))
            expr = f"CALCULATE(SUM(t[{c}]), t[{c}] IN {{{lit_set}}})"
        else:
            expr = f"VAR v = 1 RETURN SUM(t[{rnd.choice(cols)}])"

        # Assert classify_measure never raises
        decision = classify_measure(expr, home_table="t", tables=tables)
        assert isinstance(decision, WhitelistDecision)

        # If it happens to be allowed and matches a catalog formula, assert Rule A
        if decision.allowed and expr in catalog_by_dax:
            f = catalog_by_dax[expr]
            sql = generate_sql(f, "t_csv", col_types, mode="mapped")
            assert isinstance(sql, str), f"Fuzzed expression {expr} allowed but violated Rule A"


# ===========================================================================
# Stage C1a2: review fixes (per-type operator table, literal validation, never
# raise, numeric DISTINCTCOUNT, strict types, source-dependent refusals, name
# collisions) and the tests that kill the surviving mutants.
# The five tests above that this section supersedes are
# test_differential_catalog_rules (old counts and old Rule A) and four rows of
# test_positive_expressions (NOT / || over text, numeric DISTINCTCOUNT).
# ===========================================================================

import collections  # noqa: E402

from analytics_studio.store import dax_whitelist as _wl  # noqa: E402
from analytics_studio.store.dax_whitelist import (  # noqa: E402
    PREDICATE_OPS_BY_TYPE,
    REASON_COMPOSITE,
    REASON_DECIMAL_DIGITS,
    REASON_DISTINCTCOUNT_NUMERIC,
    REASON_LITERAL_LEFT,
    REASON_OR_SAME_COLUMN,
    REASON_PARQUET_COUNTA,
    REASON_TEXT_ORDERING,
    REASON_TOO_DEEP,
    REASON_UNEXPECTED,
    _canonical_type,
    _check_predicate,
)
from tools.store_engine_diff import Refusal, run_comparison  # noqa: E402

# (rows, seed) of the rules tool runs that give the mapped status of every formula.
RULES_RUNS = ((400, 1), (400, 7), (2000, 42), (2000, 1))


@pytest.fixture(scope="module")
def rules_runs() -> dict[tuple[int, int], dict[str, dict[str, Any]]]:
    """One rules tool run per (rows, seed), cached for the whole module."""
    out: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}
    for rows, seed in RULES_RUNS:
        res = run_comparison(
            rows=rows, seed=seed, skip_naive=True, skip_parquet=True, skip_group_by=True
        )
        out[(rows, seed)] = {r["id"]: r for r in res["results"]}
    return out


def test_rule_a_allowed_means_mapped_status_same(dataset_and_catalog, rules_runs):
    """Rule A: every formula the whitelist allows has mapped_status 'same' and no mapped
    refusal in every rules tool run. Counts are the measured ones (allowed / refused /
    skipped / catalog)."""
    col_types, catalog, _ = dataset_and_catalog
    tables = {"t": col_types}
    # Formulas the store can do but the whitelist refuses (Rule B). Numeric DISTINCTCOUNT is
    # refused on purpose (it differs in some seeds); (C4b) arithmetic over totals is allowed, the SUMX iterators are not.
    expected_gap_shapes = {"DISTINCTCOUNT", "DISTINCTCOUNT_filtered"}
    for key, by_id in rules_runs.items():
        allowed = refused = skipped = 0
        violations: list[Any] = []
        gaps: collections.Counter[str] = collections.Counter()
        for f in catalog:
            if f.get("group_col") or f["dax"].startswith("group_by(") or f["id"] not in by_id:
                skipped += 1
                continue
            decision = classify_measure(f["dax"], home_table="t", tables=tables)
            r = by_id[f["id"]]
            if decision.allowed:
                allowed += 1
                if r["mapped_status"] != "same" or r["mapped_refusal"] is not None:
                    violations.append((f["id"], r["mapped_status"], r["mapped_refusal"]))
                assert decision.shape == f["shape"], f["id"]
                assert decision.table == "t", f["id"]
            else:
                refused += 1
                if r["mapped_status"] == "same" and r["mapped_refusal"] is None:
                    gaps[f["shape"] if f["category"] != "arithmetic" else "arithmetic"] += 1
        assert violations == [], f"Rule A violated at {key}: {violations}"
        assert (allowed, refused, skipped, len(catalog)) == (575, 239, 29, 843), key
        assert set(gaps) <= expected_gap_shapes | {"arithmetic"}, f"unexpected Rule B gaps at {key}: {gaps}"
        assert gaps["arithmetic"] == 2, key  # (C4b) only the two SUMX iterators (7 before)


def test_rule_a_source_parquet_counta(dataset_and_catalog):
    """With source_kind='parquet' every COUNTA is refused, as the rules tool does, and every
    formula still allowed has a mapped SQL on the Parquet path."""
    col_types, catalog, _ = dataset_and_catalog
    tables = {"t": col_types}
    counta_seen = 0
    for f in catalog:
        if f.get("group_col") or f["dax"].startswith("group_by("):
            continue
        csv_dec = classify_measure(f["dax"], home_table="t", tables=tables)
        pq_dec = classify_measure(f["dax"], home_table="t", tables=tables, source_kind="parquet")
        if pq_dec.allowed:
            sql = generate_sql(f, "t_pq", col_types, mode="mapped", is_parquet=True)
            assert isinstance(sql, str), f"{f['id']} allowed on parquet but the rules tool refuses"
        if f["agg"] == "COUNTA" and csv_dec.allowed:
            counta_seen += 1
            assert not pq_dec.allowed, f["id"]
            assert REASON_PARQUET_COUNTA in pq_dec.reasons, pq_dec.reasons
            ref = generate_sql(f, "t_pq", col_types, mode="mapped", is_parquet=True)
            assert isinstance(ref, Refusal) and ref.reason == REASON_PARQUET_COUNTA
    assert counta_seen > 0


def test_rule_a_max_digits_matches_rules_tool(dataset_and_catalog):
    """A column with more than 38 digits refuses with the rules tool wording."""
    col_types, catalog, _ = dataset_and_catalog
    tables = {"t": col_types}
    meta = {"max_digits": {"d": 39}}
    f = next(x for x in catalog if x["dax"] == "SUM(t[d])")
    ref = generate_sql(f, "t_csv", col_types, mode="mapped", store_meta=meta)
    assert isinstance(ref, Refusal)
    dec = classify_measure("SUM(t[d])", home_table="t", tables=tables, max_digits={"d": 39})
    assert not dec.allowed and dec.reasons == (ref.reason,) == (REASON_DECIMAL_DIGITS,)
    # 38 digits is still fine; the key is case-insensitive; other columns are not affected
    assert classify_measure("SUM(t[d])", home_table="t", tables=tables, max_digits={"d": 38}).allowed
    assert not classify_measure("AVERAGE(t[d])", home_table="t", tables=tables, max_digits={"D": 40}).allowed
    assert classify_measure("SUM(t[w])", home_table="t", tables=tables, max_digits={"d": 40}).allowed
    # a predicate on such a column and a measure that expands to it refuse as well
    assert not classify_measure(
        "CALCULATE(COUNTROWS(t), t[d] >= 1)", home_table="t", tables=tables, max_digits={"d": 39}
    ).allowed
    assert not classify_measure(
        "[M]", home_table="t", tables=tables, measures={"M": "SUM(t[d])"}, max_digits={"d": 39}
    ).allowed
    # bad values refuse instead of raising
    assert not classify_measure("SUM(t[d])", home_table="t", tables=tables, max_digits={"d": "x"}).allowed


def test_source_kind_unknown_refuses():
    tables = {"t": {"cat": "text"}}
    for kind in ("CSV", "xlsx", "", None):
        dec = classify_measure("COUNTA(t[cat])", home_table="t", tables=tables, source_kind=kind)
        assert not dec.allowed and "unknown source kind" in dec.reasons[0]
    assert classify_measure("COUNTA(t[cat])", home_table="t", tables=tables, source_kind="csv").allowed
    assert not classify_measure("COUNTA(t[cat])", home_table="t", tables=tables, source_kind="parquet").allowed
    # COUNTA through a measure and under CALCULATE refuses on parquet too
    for expr in ("[M]", 'CALCULATE([M], t[cat] = "A")', 'CALCULATE(COUNTA(t[cat]), t[cat] = "A")'):
        assert classify_measure(expr, home_table="t", tables=tables, measures={"M": "COUNTA(t[cat])"}).allowed
        assert not classify_measure(
            expr, home_table="t", tables=tables, measures={"M": "COUNTA(t[cat])"}, source_kind="parquet"
        ).allowed
    # SUM on parquet is unaffected
    assert classify_measure("COUNT(t[w])", home_table="t", tables={"t": {"w": "whole_number"}}, source_kind="parquet").allowed


T2 = {
    "t": {
        "w": "whole_number", "w2": "whole_number", "d": "decimal_number", "dt": "date",
        "cat": "text", "id": "text", "flag": "boolean",
        "ts": "datetime", "tm": "time", "fx": "fixed",
        "wh": "whole", "dc": "decimal", "ty": "whol", "nt": None,
    },
    "s": {"val": "whole_number"},
}
M2 = {
    "BaseSum": "SUM(t[w])",
    "Filt": 'CALCULATE(SUM(t[w]), t[cat] = "A")',
    "M2": "[BaseSum]",
    "CycA": "[CycB]",
    "CycB": "[CycA]",
    "Arith": "SUM(t[w]) + 1",
    "TextSum": "SUM(t[cat])",
    "OtherSum": "SUM(s[val])",
}


def _cw(pred: str, agg: str = "SUM(t[w])") -> str:
    return f"CALCULATE({agg}, {pred})"


# (expression, expected): None = allowed; str = a substring of one refusal reason
C1A2_ROWS: list[tuple[str, str | None]] = [
    # ---- operators per column type -------------------------------------------------
    (_cw('t[cat] = "A"'), None),
    (_cw('t[cat] <> "A"'), REASON_TEXT_ORDERING),
    (_cw('t[cat] < "A"'), REASON_TEXT_ORDERING),
    (_cw('t[cat] <= "A"'), REASON_TEXT_ORDERING),
    (_cw('t[cat] > "A"'), REASON_TEXT_ORDERING),
    (_cw('t[cat] >= "A"'), REASON_TEXT_ORDERING),
    (_cw('t[cat] IN {"A", "B"}'), None),
    (_cw("t[cat] IN {}"), "IN needs a table or at least one value"),
    (_cw('t[cat] IN {"A", 1}'), "IN values must be string literals"),
    (_cw("t[cat] IN {1}"), "IN values must be string literals"),
    (_cw("t[w] = 1"), None),
    (_cw("t[w] < 1"), None),
    (_cw("t[w] <= 1"), None),
    (_cw("t[w] > 1"), None),
    (_cw("t[w] >= 1"), None),
    (_cw("t[w] <> 1"), None),
    (_cw("t[w] >= -10"), None),
    (_cw("t[d] >= 0"), None),
    (_cw("t[d] < 100.5"), None),
    (_cw("t[d] <> 0"), None),
    (_cw("t[d] = 1.5"), "operator = is not on the store whitelist for decimal_number"),
    (_cw("t[d] > 1.5"), "operator > is not on the store whitelist for decimal_number"),
    (_cw("t[d] <= 1.5"), "operator <= is not on the store whitelist for decimal_number"),
    (_cw("t[dt] >= DATE(2026, 6, 1)"), None),
    (_cw("t[dt] > DATE(2026, 6, 1)"), None),
    (_cw("t[dt] <= DATE(2026, 6, 1)"), None),
    (_cw("t[dt] < DATE(2026, 6, 1)"), None),
    (_cw("t[dt] <> DATE(2026, 6, 1)"), None),
    (_cw("t[dt] = DATE(2026, 6, 1)"), "operator = is not on the store whitelist for date"),
    (_cw("t[dt] IN {DATE(2026, 6, 1)}"), "IN filter not supported on date column"),
    (_cw("t[flag] = 1"), "boolean column comparison not supported"),
    (_cw("t[flag] = TRUE"), "boolean literals are not supported"),
    (_cw("t[flag] <> FALSE"), "boolean literals are not supported"),
    # ---- the literal must be on the right ------------------------------------------
    (_cw("5 < t[w]"), REASON_LITERAL_LEFT),
    (_cw("1 = t[w]"), REASON_LITERAL_LEFT),
    (_cw('"A" = t[cat]'), REASON_LITERAL_LEFT),
    (_cw("DATE(2026, 1, 1) <= t[dt]"), REASON_LITERAL_LEFT),
    (_cw("t[w] = t[w2]"), "comparison between two columns"),
    (_cw("1 = 1"), "comparison must involve a column reference"),
    # ---- NOT and || ----------------------------------------------------------------
    (_cw("NOT(t[w] = 100)"), None),
    (_cw("t[w] = 100 || t[w] = 200"), None),
    (_cw("t[w] = 1 || t[w] = 2 || t[w] = 3 || t[w] = 4"), None),
    (_cw('NOT(t[cat] = "A")'), REASON_COMPOSITE),
    (_cw('t[cat] = "A" || t[cat] = "B"'), REASON_COMPOSITE),
    (_cw("NOT(t[w] < 1)"), REASON_COMPOSITE),
    (_cw("NOT(t[d] >= 1)"), REASON_COMPOSITE),
    (_cw("t[w] < 1 || t[w] = 2"), REASON_COMPOSITE),
    (_cw("t[w] = 1 || t[w2] = 2"), REASON_OR_SAME_COLUMN),
    (_cw("t[w] = 1 || t[d] >= 2"), REASON_COMPOSITE),
    (_cw("NOT(NOT(t[w] = 1))"), REASON_COMPOSITE),
    (_cw("NOT(t[w] = 1 || t[w] = 2)"), REASON_COMPOSITE),
    (_cw("NOT(t[w] = 1 && t[w] = 2)"), REASON_LOGICAL_AND),
    (_cw("t[w] = 1 || t[w] = 2 && t[w] = 3"), REASON_LOGICAL_AND),
    (_cw("t[w] = 1 || t[flag]"), REASON_COMPOSITE),
    (_cw("t[w] = 1 || BLANK()"), REASON_COMPOSITE),
    # ---- DATE literal validity -----------------------------------------------------
    (_cw("t[dt] >= DATE(2026, 13, 45)"), "valid calendar date"),
    (_cw("t[dt] >= DATE(2026, 0, 0)"), "valid calendar date"),
    (_cw("t[dt] >= DATE(0, 1, 1)"), "DATE year must be between 1900 and 9999"),
    (_cw("t[dt] >= DATE(99999, 1, 1)"), "DATE year must be between 1900 and 9999"),
    (_cw("t[dt] >= DATE(1899, 12, 31)"), "DATE year must be between 1900 and 9999"),
    (_cw("t[dt] >= DATE(1900, 1, 1)"), None),
    (_cw("t[dt] >= DATE(9999, 12, 31)"), None),
    (_cw("t[dt] >= DATE(2024, 2, 29)"), None),
    (_cw("t[dt] >= DATE(2023, 2, 29)"), "valid calendar date"),
    (_cw("t[dt] >= DATE(2026, 2, 30)"), "valid calendar date"),
    (_cw("t[dt] >= DATE(-1, 1, 1)"), "DATE arguments must be integer literals"),
    (_cw("t[dt] >= DATE(2026.5, 1, 1)"), "DATE arguments must be integer literals"),
    (_cw("t[dt] >= DATE(2026, 1)"), "DATE"),
    (_cw("t[dt] >= DATE(2026, 1, 1, 1)"), "DATE"),
    (_cw('t[dt] >= DATE("a", 1, 1)'), "DATE arguments must be integer literals"),
    (_cw('t[dt] >= DATE("2026", 1, 1)'), "DATE arguments must be integer literals"),
    (_cw("t[dt] >= DATE(YEAR(TODAY()), 1, 1)"), "DATE arguments must be integer literals"),
    (_cw("t[dt] >= TODAY()"), "not a valid literal"),
    # ---- numeric literal validity --------------------------------------------------
    (_cw("t[w] = 1.5"), "integer-valued"),
    (_cw("t[w] = 1.0"), None),
    (_cw("t[w] = 1e400"), "exceeds 38 total digits"),
    (_cw("t[w] = 9223372036854775807"), None),
    (_cw("t[w] = -9223372036854775808"), None),
    (_cw("t[w] = 9223372036854775808"), "64-bit range"),
    (_cw("t[w] = -9223372036854775809"), "64-bit range"),
    (_cw("t[w] = 99999999999999999999999999999999999999"), "64-bit range"),
    (_cw("t[w] = 12345678901234567890123456789012345678901"), "exceeds 38 total digits"),
    (_cw("t[d] >= 12345678901234567890123456789012345678"), None),
    (_cw("t[d] >= 123456789012345678901234567890123456789"), "exceeds 38 total digits"),
    (_cw("t[d] >= 1e400"), "exceeds 38 total digits"),
    (_cw("t[d] >= 0.0000000000000000000000000000000000000001"), "exceeds 38 total digits"),
    (_cw('t[w] = "5"'), "literal type string does not fit whole_number column"),
    (_cw("t[w] = DATE(2026, 1, 1)"), "literal type date does not fit whole_number column"),
    (_cw("t[w] = +1"), "not a valid literal"),
    (_cw("t[w] = - -1"), "unary operator"),
    (_cw("t[w] = BLANK()"), REASON_BLANK_COMPARISON),
    # ---- column types: known names only --------------------------------------------
    ("SUM(t[w])", None),
    ("SUM(t[wh])", None),
    ("SUM(t[dc])", None),
    ("SUM(t[ts])", "column type 'datetime' is not on the store whitelist"),
    ("COUNTA(t[ts])", "no such column"),
    ("MIN(t[ts])", "column type 'datetime'"),
    ("SUM(t[fx])", "column type 'fixed' is not on the store whitelist"),
    ("SUM(t[tm])", "unknown column type 'time'"),
    ("SUM(t[ty])", "unknown column type 'whol'"),
    ("COUNT(t[nt])", "unknown column type 'None'"),
    (_cw("t[ts] >= DATE(2026, 1, 1)"), "column type 'datetime'"),
    (_cw("t[nt] = 1"), "unknown column type 'None'"),
    (_cw('t[ty] IN {"A"}'), "unknown column type 'whol'"),
    # ---- DISTINCTCOUNT on numeric columns --------------------------------------------
    ("DISTINCTCOUNT(t[w])", REASON_DISTINCTCOUNT_NUMERIC),
    ("DISTINCTCOUNT(t[d])", REASON_DISTINCTCOUNT_NUMERIC),
    (_cw('t[cat] IN {"A", "B"}', "DISTINCTCOUNT(t[w])"), REASON_DISTINCTCOUNT_NUMERIC),
    ("DISTINCTCOUNT(t[cat])", None),
    ("DISTINCTCOUNT(t[dt])", None),
    ("DISTINCTCOUNT(t[flag])", None),
    (_cw("t[w] > 1", "DISTINCTCOUNT(t[dt])"), None),
    # ---- surviving mutants of the C1a review ----------------------------------------
    (_cw("1"), "CALCULATE filters must be column comparisons"),
    (_cw("t[w]"), "node kind reference is not on the store whitelist"),
    (_cw('"x"'), "CALCULATE filters must be column comparisons"),
    (_cw("TRUE()"), "CALCULATE filters must be column comparisons"),
    (_cw("t[w] == 1"), "node kind strict_equal is not on the store whitelist"),
    (_cw("t[w] + 1 = 2"), "comparison must involve a column reference"),
    (_cw("t[w] = 1 + 1"), "node kind binary is not a valid literal"),
    # ---- shapes and measures ---------------------------------------------------------
    ("[BaseSum]", None),
    ("[M2]", None),
    ("CALCULATE([BaseSum], t[w] > 1)", None),
    ("CALCULATE([Filt], t[w] > 1)", REASON_NESTED_CALCULATE),
    ("[CycA]", "cycle detected"),
    ("[Arith]", None),  # (C4b) SUM(t[w]) + 1 is allowed now
    ("[TextSum]", "SUM not supported on text column"),
    ("[NoSuch]", "unknown column or measure"),
    ("CALCULATE(SUM(t[w]), s[val] = 1)", "multiple tables"),
    ("CALCULATE([OtherSum], t[w] = 1)", "multiple tables"),
    ("SUM(t[nosuch])", "unknown column 'nosuch'"),
    ("SUM(nosuch[w])", "unknown table 'nosuch'"),
    ("SUM(t[w]) // trailing comment", None),
    ("SUMX(t, t[w])", "function SUMX"),
    ("DIVIDE(SUM(t[w]), 2)", None),  # (C4b) DIVIDE over totals is allowed now
    ("CALCULATE(SUM(t[w]), ALL(t))", "function ALL"),
    ("CALCULATE(SUM(t[w]), KEEPFILTERS(t[cat] = \"A\"))", "is not on the store whitelist"),
    ("VAR x = 1 RETURN SUM(t[w])", REASON_LET),
    ("", None),
]


@pytest.mark.parametrize("expr, expected", C1A2_ROWS)
def test_c1a2_rows(expr, expected):
    dec = classify_measure(expr, home_table="t", tables=T2, measures=M2)
    if expr == "":
        assert not dec.allowed and dec.reasons
        return
    if expected is None:
        assert dec.allowed, f"{expr!r} should be allowed, reasons: {dec.reasons}"
        assert dec.reasons == () and dec.table == "t" and dec.shape
    else:
        assert not dec.allowed, f"{expr!r} should be refused"
        assert dec.table is None and dec.shape is None
        assert any(expected in r for r in dec.reasons), f"{expected!r} not in {dec.reasons}"


def test_operator_table_is_exactly_the_catalog():
    """The per-type operator table equals what the rules tool catalog compares."""
    assert PREDICATE_OPS_BY_TYPE == {
        "text": frozenset({"="}),
        "whole_number": frozenset({"=", "<", "<=", ">", ">=", "<>"}),
        "decimal_number": frozenset({">=", "<", "<>"}),
        "date": frozenset({">=", ">", "<=", "<", "<>"}),
        "boolean": frozenset(),
    }
    # every type x operator pair is decided by the table, nothing else
    literal = {"text": '"A"', "whole_number": "1", "decimal_number": "1", "date": "DATE(2026, 1, 1)"}
    column = {"text": "t[cat]", "whole_number": "t[w]", "decimal_number": "t[d]", "date": "t[dt]"}
    for ctype, ops in PREDICATE_OPS_BY_TYPE.items():
        if ctype == "boolean":
            continue
        for op in ("=", "<>", "<", "<=", ">", ">="):
            dec = classify_measure(
                _cw(f"{column[ctype]} {op} {literal[ctype]}"), home_table="t", tables=T2
            )
            assert dec.allowed == (op in ops), (ctype, op, dec.reasons)


# ---- never raise ------------------------------------------------------------------------

def test_deep_expressions_refuse_instead_of_raising():
    """NOT depth 150, a 1200-term OR and 200 nested CALCULATE never raise. Since Stage C1b1 the
    shape caps (checked on the tokens before the parser runs) refuse them with a stable reason that
    does not depend on the recursion limit."""
    import sys

    from analytics_studio.store.dax_whitelist import REASON_CAP_NESTING, REASON_CAP_TOKENS

    not_150 = "CALCULATE(SUM(t[w]), " + "NOT(" * 150 + "t[w] = 1" + ")" * 150 + ")"
    or_1200 = "CALCULATE(SUM(t[w]), " + " || ".join("t[w] = 1" for _ in range(1200)) + ")"
    calc_200 = "CALCULATE(" * 200 + "SUM(t[w])" + ")" * 200
    wanted = {not_150: REASON_CAP_NESTING, or_1200: REASON_CAP_TOKENS, calc_200: REASON_CAP_NESTING}
    for expr, reason in wanted.items():
        dec = classify_measure(expr, home_table="t", tables=T2)
        assert not dec.allowed and dec.reasons == (reason,), dec.reasons
    previous = sys.getrecursionlimit()
    sys.setrecursionlimit(1000)
    try:
        for expr, reason in wanted.items():
            dec = classify_measure(expr, home_table="t", tables=T2)
            assert not dec.allowed
            assert dec.reasons == (reason,), dec.reasons
    finally:
        sys.setrecursionlimit(previous)


def test_long_or_chain_is_flattened_not_recursed():
    """The classifier walks a || chain with a loop. A chain of MAX_OR_TERMS operands over one
    column is allowed, one over two columns refuses for the same-column rule, one operand more
    or 300 operands is the OR cap, and a 400-term chain (over 1500 tokens) is the token cap."""
    from analytics_studio.store.dax_whitelist import MAX_OR_TERMS, REASON_CAP_OR_TERMS, REASON_CAP_TOKENS

    def chain(n: int, two_columns: bool) -> str:
        return "CALCULATE(SUM(t[w]), " + " || ".join(
            f"t[w{'2' if two_columns and i % 2 else ''}] = {i}" for i in range(n)
        ) + ")"

    assert classify_measure(chain(MAX_OR_TERMS, False), home_table="t", tables=T2).allowed
    dec = classify_measure(chain(MAX_OR_TERMS, True), home_table="t", tables=T2)
    assert not dec.allowed and REASON_OR_SAME_COLUMN in dec.reasons
    for two in (False, True):
        for terms, reason in ((MAX_OR_TERMS + 1, REASON_CAP_OR_TERMS), (300, REASON_CAP_OR_TERMS), (400, REASON_CAP_TOKENS)):
            dec = classify_measure(chain(terms, two), home_table="t", tables=T2)
            assert not dec.allowed and dec.reasons == (reason,), (terms, dec.reasons)


def test_recursion_error_and_unexpected_error_refuse(monkeypatch):
    def boom_recursion(_expr):
        raise RecursionError("x")

    monkeypatch.setattr(_wl, "parse_expression", boom_recursion)
    dec = classify_measure("SUM(t[w])", home_table="t", tables=T2)
    assert not dec.allowed and dec.reasons == (REASON_TOO_DEEP,)

    def boom_value(_expr):
        raise ValueError("secret details must not leak")

    monkeypatch.setattr(_wl, "parse_expression", boom_value)
    dec = classify_measure("SUM(t[w])", home_table="t", tables=T2)
    assert not dec.allowed and dec.reasons == (f"{REASON_UNEXPECTED}: ValueError",)


def test_odd_inputs_refuse_instead_of_raising():
    for expr in (None, 5, b"SUM(t[w])"):
        dec = classify_measure(expr, home_table="t", tables=T2)  # type: ignore[arg-type]
        assert not dec.allowed and dec.reasons == ("Enter a DAX expression.",)
    # a bad tables mapping reaches the last guard and names only the exception type
    dec = classify_measure("SUM(t[w])", home_table="t", tables={"t": None})  # type: ignore[dict-item]
    assert not dec.allowed and dec.reasons == (f"{REASON_UNEXPECTED}: AttributeError",)
    # an unknown home table matters only for unqualified [column] references
    assert classify_measure("SUM(t[w])", home_table="nosuch", tables=T2).allowed
    dec = classify_measure("SUM([w])", home_table="nosuch", tables=T2)
    assert not dec.allowed and dec.reasons == ("unknown home table 'nosuch'",)


# ---- types ----------------------------------------------------------------------------------

def test_canonical_type_maps_only_known_names():
    for raw, want in (
        ("whole", "whole_number"), ("whole_number", "whole_number"),
        ("decimal", "decimal_number"), ("decimal_number", "decimal_number"),
        ("date", "date"), ("boolean", "boolean"), ("text", "text"),
    ):
        assert _canonical_type(raw) == (want, None)
    for raw in ("datetime", "fixed"):
        canon, why = _canonical_type(raw)
        assert canon is None and raw in why and "no such column" in why
    for raw in (None, "", "time", "Text", "TEXT", "whol", "int64", "integer", "float", "double", "currency", "bool", "fixed_decimal", 5):
        canon, why = _canonical_type(raw)  # type: ignore[arg-type]
        assert canon is None and str(raw) in why, (raw, why)


# ---- names that collide after case folding --------------------------------------------------

def test_case_colliding_names_refuse():
    cases = [
        ({"t": {"a": "text", "A": "whole_number"}}, None, "column names"),
        ({"t": {"w": "whole_number"}, "T": {"w": "whole_number"}}, None, "table names"),
        ({"t": {"w": "whole_number"}}, {"M": "SUM(t[w])", "m": "SUM(t[w])"}, "measure names"),
    ]
    for tables, measures, word in cases:
        dec = classify_measure("SUM(t[w])", home_table="t", tables=tables, measures=measures)
        assert not dec.allowed
        assert word in dec.reasons[0] and "collide" in dec.reasons[0]
    # without a collision the same shapes pass
    assert classify_measure("SUM(t[w])", home_table="t", tables={"t": {"w": "whole_number", "a": "text"}}).allowed


# ---- depth cap boundary (32 allowed, 33 refused) --------------------------------------------

def _chain(n: int) -> dict[str, str]:
    m = {f"C{i}": f"[C{i + 1}]" for i in range(1, n)}
    m[f"C{n}"] = "SUM(t[w])"
    return m


def test_measure_chain_depth_boundary():
    tables = {"t": {"w": "whole_number"}}
    assert classify_measure("[C1]", home_table="t", tables=tables, measures=_chain(32)).allowed
    dec = classify_measure("[C1]", home_table="t", tables=tables, measures=_chain(33))
    assert not dec.allowed and dec.reasons == (REASON_MAX_DEPTH_EXCEEDED,)
    assert not classify_measure("[C1]", home_table="t", tables=tables, measures=_chain(200)).allowed


# ---- NOT arity (the parser stops it first, so the guard is tested directly) ------------------

def test_not_arity_guard_direct():
    tables_norm = {"t": {"w": "whole_number"}}
    node = (
        "call", "NOT",
        (
            ("comparison", "=", ("reference", "t", "w"), ("number", 1, "1")),
            ("comparison", "=", ("reference", "t", "w"), ("number", 2, "2")),
        ),
    )
    reasons: list[str] = []
    _check_predicate(node, tables_norm, {"t": "t"}, "t", {}, reasons, set())
    assert reasons == ["call NOT requires exactly one argument"]
    reasons = []
    _check_predicate(("call", "NOT", ()), tables_norm, {"t": "t"}, "t", {}, reasons, set())
    assert reasons == ["call NOT requires exactly one argument"]


# ---- unqualified references: measure first for [x], column for the aggregate rule ----------

def test_unqualified_reference_rule_is_pinned():
    """A measure named like a column. [w] returns the MEASURE. SUM([w]) is refused: the engine
    takes the COLUMN there, so the two readings could differ and the whitelist does not guess
    (stricter than the engine on purpose)."""
    tables = {"t": {"w": "whole_number", "d": "decimal_number"}}
    measures = {"w": "SUM(t[d])"}
    bare = classify_measure("[w]", home_table="t", tables=tables, measures=measures)
    assert bare.allowed and bare.shape == "SUM" and bare.table == "t"
    wrapped = classify_measure("SUM([w])", home_table="t", tables=tables, measures=measures)
    assert not wrapped.allowed
    assert wrapped.reasons == ("measure reference 'w' not expected in column context",)
    # a predicate on [w] refuses the same way
    pred = classify_measure("CALCULATE(SUM(t[d]), [w] > 1)", home_table="t", tables=tables, measures=measures)
    assert not pred.allowed
    # without a measure of that name the unqualified name is the home table column
    assert classify_measure("SUM([w])", home_table="t", tables=tables).allowed
    assert classify_measure("CALCULATE(SUM(t[d]), [w] > 1)", home_table="t", tables=tables).allowed


# ---- the rules the reviewer's 258-expression sweep found; typed in by hand ------------------

SWEEP_REFUSED = [
    "SUM(t[w]) ^ 1", "1 ^ SUM(t[w])", "SUM(t[w]) & 1", "SUM(t[w]) = 1",  # (C4b) + - * / and unary minus are allowed now
    "SUM()", "SUM(t[w], t[w])", "SUM(t)", "SUM(1)", '"x"', "1", "BLANK()", "TRUE()", "{1, 2}",
    "CALCULATE()", "CALCULATE(SUM(t[w]), )", "SUM(t[w]", "SUM(t[w]]",
    "SUM(t[w ])", "SUM(t[ w])", "SUM(t[ｗ])",
    "CALCULATE(CALCULATE(SUM(t[w]), t[w] = 1), t[cat] = \"A\")",
    "CALCULATE(CALCULATE(SUM(t[w])), t[cat] = \"A\")",
    "CALCULATE(SUM(t[w]), CALCULATE(t[w] = 1))",
    "CALCULATE(SUM(t[w]), t[w])", "CALCULATE(SUM(t[w]), 1)", "CALCULATE(SUM(t[w]), TRUE())",
    "CALCULATE(SUM(t[w]), t[flag])", "CALCULATE(SUM(t[w]), NOT(t[flag]))",
    "CALCULATE(SUM(t[w]), t[w] <> BLANK())", "CALCULATE(SUM(t[w]), BLANK() = t[w])",
    "CALCULATE(SUM(t[w]), ISBLANK(t[w]))", "CALCULATE(SUM(t[w]), t[w] = t[d])",
    "CALCULATE(SUM(t[w]), t[w] = 1 && t[d] >= 2)", "CALCULATE(SUM(t[w]), t[w] IN {1, 2})",
    "CALCULATE(SUM(t[w]), t[cat] IN VALUES(t[cat]))", "CALCULATE(SUM(t[w]), t[cat] IN t[cat])",
    "CALCULATE(SUM(t[w]), t[w] = -\"1\")", "CALCULATE(SUM(t[w]), t[dt] = \"2026-01-01\")",
    "CALCULATE(SUM(t[w]), t[dt] >= 5)", "CALCULATE(SUM(t[w]), t[cat] = 1)",
    "CALCULATE(SUM(t[w]), \"A\" > t[cat])", "CALCULATE(SUM(t[w]), \"\" = t[cat])",
    "CALCULATE(SUM(t[w]), DATE(2026, 1, 1) < t[dt])", "CALCULATE(SUM(t[w]), 5 > t[w])",
    "CALCULATE(COUNTROWS(t), t)", "COUNTROWS(t[w])", "COUNTROWS(t, t)", "COUNTROWS()", "COUNTROWS(nosuch)",
    "DISTINCTCOUNT(t)", "DISTINCTCOUNTNOBLANK(t[cat])", "DISTINCTCOUNT(t[w])",
    "SUM(t[cat])", "SUM(t[id])", "SUM(t[dt])", "SUM(t[flag])", "AVERAGE(t[cat])", "MIN(t[cat])",
    "MAX(t[flag])", "COUNT(t[cat])", "COUNT(t[flag])", "SUM(t[ts])", "SUM(t[fx])",
    "TOTALYTD(SUM(t[w]), t[dt])", "SELECTEDVALUE(t[cat])", "IF(SUM(t[w]) > 1, 1, 0)",
    "CALCULATE(SUM(t[w]), FILTER(t, t[w] > 1))", "CALCULATE(SUM(t[w]), ALLEXCEPT(t, t[cat]))",
]


@pytest.mark.parametrize("expr", SWEEP_REFUSED)
def test_sweep_refused(expr):
    dec = classify_measure(expr, home_table="t", tables=T2, measures=M2)
    assert not dec.allowed, f"{expr!r} was allowed"
    assert dec.reasons and dec.table is None and dec.shape is None


SWEEP_ALLOWED = [
    ("SUM(t[w])", "SUM"), ("sum(t[w])", "SUM"), ("  SUM ( t[w] )  ", "SUM"), ("SUM('t'[w])", "SUM"),
    ("SUM(T[W])", "SUM"), ("COUNTROWS(t)", "COUNTROWS"), ("COUNTROWS(T)", "COUNTROWS"),
    ("COUNTROWS('t')", "COUNTROWS"), ("AVERAGE(t[d])", "AVERAGE"), ("MIN(t[dt])", "MIN"),
    ("COUNTA(t[cat])", "COUNTA"), ("COUNTBLANK(t[id])", "COUNTBLANK"),
    ("SUM(t[w]) /* comment */", "SUM"), ("/* c */ SUM(t[w])", "SUM"), ("SUM(t\n[w])", "SUM"),
    ('CALCULATE(SUM(t[w]), t[cat] = "it\'s")', "SUM_filtered"),
    ('CALCULATE(SUM(t[w]), t[cat] = "say ""hi""")', "SUM_filtered"),
    ('CALCULATE(SUM(t[w]), t[cat] = "")', "SUM_filtered"),
    ('CALCULATE(SUM(t[w]), t[cat] = "SUM(t[w])")', "SUM_filtered"),
    ("CALCULATE(SUM(t[w]), t[w] > 5, t[w] < 15)", "SUM_filtered"),
    ("CALCULATE(COUNTROWS(t), t[dt] >= DATE(2026, 6, 1))", "COUNTROWS_filtered"),
    ("[m2]", "SUM"),
    # (C4b) arithmetic over totals
    ("SUM(t[w]) + 1", "ARITH"), ("1 + SUM(t[w])", "ARITH"), ("-SUM(t[w])", "ARITH"), ("[Arith]", "ARITH"),
    ("sum(t[w]) /* c */ * 2", "ARITH"), ("DIVIDE(sum(t[w]), 0, -1)", "ARITH"),
]


@pytest.mark.parametrize("expr, shape", SWEEP_ALLOWED)
def test_sweep_allowed(expr, shape):
    dec = classify_measure(expr, home_table="t", tables=T2, measures=M2)
    assert dec.allowed, f"{expr!r}: {dec.reasons}"
    assert dec.shape == shape and dec.table == "t"


# ---- guards the parser cannot reach, tested with hand-built nodes ---------------------------

def test_predicate_default_refusals_direct():
    """Kinds the parser never hands to a predicate (it refuses a bare literal first) still end in
    a refusal in _check_predicate: removing the default refusal must fail here."""
    tables_norm = {"t": {"w": "whole_number", "cat": "text"}}
    nodes = [
        ("number", 1, "1"),
        ("string", "x"),
        ("boolean", True),
        ("reference", "t", "w"),
        ("table", "t"),
        ("binary", "+", ("number", 1, "1"), ("number", 2, "2")),
        ("let", (), ("number", 1, "1")),
        ("strict_equal", ("reference", "t", "w"), ("number", 1, "1")),
        ("mystery_kind", 1),
    ]
    for node in nodes:
        reasons: list[str] = []
        _check_predicate(node, tables_norm, {"t": "t"}, "t", {}, reasons, set())
        assert reasons, f"{node[0]} was admitted as a predicate"
    reasons = []
    _check_predicate(("call", "FILTER", ()), tables_norm, {"t": "t"}, "t", {}, reasons, set())
    assert reasons == ["function FILTER is not on the store whitelist"]


def test_in_guards_direct():
    tables_norm = {"t": {"w": "whole_number", "cat": "text"}}
    ref = ("reference", "t", "cat")
    cases = [
        (("in", ref, ("tableconstructor", ())), "IN needs at least one string literal"),
        (("in", ref, ("tableconstructor", (("string", "A"), ("number", 1, "1")))), "IN values must be string literals"),
        (("in", ref, ("number", 1, "1")), "right side of IN must be a table constructor"),
        (("in", ("number", 1, "1"), ("tableconstructor", (("string", "A"),))), "left side of IN must be a column reference"),
        (("in", ("reference", "t", "w"), ("tableconstructor", (("string", "A"),))), "IN filter not supported on whole_number column"),
    ]
    for node, want in cases:
        reasons: list[str] = []
        _check_predicate(node, tables_norm, {"t": "t"}, "t", {}, reasons, set())
        assert any(want in r for r in reasons), (node, reasons)
    reasons = []
    _check_predicate(("in", ref, ("tableconstructor", (("string", "A"),))), tables_norm, {"t": "t"}, "t", {}, reasons, set())
    assert reasons == []


# ===========================================================================
# C1b2: refusals the literal sweep proved necessary, and "allowed means same" over the sweep
# ===========================================================================

from analytics_studio.store.dax_whitelist import (  # noqa: E402
    REASON_FILTER_CONTEXT_EMPTY,
    REASON_FILTER_CONTEXT_OTHER_TABLE,
    REASON_IN_FOLD_EQ_MIX,
    REASON_IN_NUMERIC_MIX,
    REASON_SLICER_SAME_COLUMN,
    REASON_TEXT_NON_ASCII_SPACE,
    classify_filter_context,
    in_mix_reason,
)

# (expression, expected): None = allowed; str = a substring of one refusal reason
C1B2_ROWS: list[tuple[str, str | None]] = [
    # text equality with a non-ASCII whitespace literal (NBSP, NEL, U+3000, U+2003): the engine trims it
    (_cw('t[cat] = " "'), REASON_TEXT_NON_ASCII_SPACE),
    (_cw('t[cat] = "\u0085"'), REASON_TEXT_NON_ASCII_SPACE),
    (_cw('t[cat] = "　"'), REASON_TEXT_NON_ASCII_SPACE),
    (_cw('t[cat] = " "'), REASON_TEXT_NON_ASCII_SPACE),
    (_cw('t[cat] = "A "'), REASON_TEXT_NON_ASCII_SPACE),
    (_cw('t[cat] = ""'), None),
    (_cw('t[cat] = " "'), None),
    (_cw('t[cat] = "ünï"'), None),
    # a text IN with a numeric comparison in one CALCULATE: the engine raises a type error on blank cells
    (_cw('t[cat] IN {"A"}, t[w] > 5'), REASON_IN_NUMERIC_MIX),
    (_cw('t[w] = 5, t[cat] IN {"A", "B"}'), REASON_IN_NUMERIC_MIX),
    (_cw('t[cat] IN {"A"}, t[d] >= 0'), REASON_IN_NUMERIC_MIX),
    (_cw('t[cat] IN {"A"}, NOT(t[w] = 5)'), REASON_IN_NUMERIC_MIX),
    (_cw('t[cat] IN {"A"}, t[w] = 5 || t[w] = 6'), REASON_IN_NUMERIC_MIX),
    (_cw('t[cat] IN {"A"}, t[dt] >= DATE(2026, 1, 1)'), None),
    (_cw('t[cat] IN {"A"}, t[id] = "x"'), None),
    # a text IN with a text equality on a literal that is non-ASCII or contains ss: the engine ignores the IN
    (_cw('t[cat] IN {"A"}, t[id] = "ünï"'), REASON_IN_FOLD_EQ_MIX),
    (_cw('t[cat] IN {"A"}, t[id] = "ss"'), REASON_IN_FOLD_EQ_MIX),
    (_cw('t[cat] IN {"A"}, t[id] = "ß"'), REASON_IN_FOLD_EQ_MIX),
    (_cw('t[id] = "SS", t[cat] IN {"A"}'), REASON_IN_FOLD_EQ_MIX),
]


@pytest.mark.parametrize("expr, expected", C1B2_ROWS)
def test_c1b2_rows(expr, expected):
    dec = classify_measure(expr, home_table="t", tables=T2, measures=M2)
    if expected is None:
        assert dec.allowed, f"{expr!r} should be allowed, reasons: {dec.reasons}"
        assert dec.reasons == () and dec.table == "t" and dec.shape
    else:
        assert not dec.allowed, f"{expr!r} should be refused"
        assert dec.table is None and dec.shape is None
        assert any(expected in r for r in dec.reasons), f"{expected!r} not in {dec.reasons}"


def test_in_mix_reason_direct():
    from analytics_studio.measures import parse_expression

    nodes = [parse_expression(text) for text in ('t[cat] IN {"A"}', "t[w] > 1")]
    assert in_mix_reason(nodes, T2, "t") == REASON_IN_NUMERIC_MIX
    assert in_mix_reason(nodes[:1], T2, "t") is None and in_mix_reason(nodes[1:], T2, "t") is None
    assert in_mix_reason([], T2, "t") is None and in_mix_reason(["x", None, ()], T2, "t") is None


# (filter context predicates, expected): None = allowed; str = a substring of one refusal reason
FILTER_CONTEXT_ROWS: list[tuple[tuple[str, ...], str | None]] = [
    ((), None),
    (("t[w] > 5",), None),
    (("t[w] > 5", "t[w] < 15"), None),
    (('t[cat] IN {"A", "B"}',), None),
    (("t[w] = 1 || t[w] = 2",), None),
    (("NOT(t[w] = 1)",), None),
    (("t[dt] >= DATE(2026, 1, 1)", "t[d] < 0"), None),
    (("",), REASON_FILTER_CONTEXT_EMPTY),
    (("   ",), REASON_FILTER_CONTEXT_EMPTY),
    (("s[val] > 1",), REASON_FILTER_CONTEXT_OTHER_TABLE),
    (("t[w] > 5", "s[val] > 1"), REASON_FILTER_CONTEXT_OTHER_TABLE),
    (("t[cat] IN {}",), "IN"),
    (("t[w] >",), ""),
    (("t[nosuch] = 1",), "unknown column"),
    (("t[w] = BLANK()",), REASON_BLANK_COMPARISON),
    (("t[flag] = TRUE()",), REASON_BOOLEAN_LITERAL),
    (('t[cat] = "A"', 't[cat] <> "B"'), REASON_TEXT_ORDERING),
    (("t[w] > 5 && t[w] < 9",), REASON_LOGICAL_AND),
    (("SUM(t[w])",), "function SUM"),
    (("t[d] >= 12345678901234567890123456789012345678901",), "38"),
    ((f"t[w] > {'1'}",) * 51, "filter arguments"),
]


@pytest.mark.parametrize("predicates, expected", FILTER_CONTEXT_ROWS)
def test_classify_filter_context_rows(predicates, expected):
    dec = classify_filter_context(predicates, home_table="t", tables=T2)
    if expected is None:
        assert dec.allowed and dec.reasons == () and dec.table == "t" and dec.shape == "filter_context"
    else:
        assert not dec.allowed and dec.table is None and dec.shape is None and dec.reasons
        assert any(expected in r for r in dec.reasons), (predicates, dec.reasons)


def test_classify_filter_context_same_column_blocked_and_never_raises():
    dec = classify_filter_context(("t[w] > 5",), home_table="t", tables=T2, blocked_columns=[("T", "W")])
    assert not dec.allowed and dec.reasons == (REASON_SLICER_SAME_COLUMN,)
    ok = classify_filter_context(("t[w] > 5",), home_table="t", tables=T2, blocked_columns=[("t", "w2")])
    assert ok.allowed
    for weird in (None, "t[w] > 5", (1, 2), ("t[w] > 5", None)):
        dec = classify_filter_context(weird, home_table="t", tables=T2)  # type: ignore[arg-type]
        assert isinstance(dec, WhitelistDecision) and not dec.allowed
    assert not classify_filter_context(("t[w] > 5",), home_table="nosuch", tables=T2).allowed
    assert not classify_filter_context(("t[w] > 5",), home_table="t", tables=T2, source_kind="orc").allowed


# every sweep row the whitelist allows is `same` in the sweep (the sweep itself runs the engine)
_SWEEP_RUNS: dict[int, Any] = {}


def _sweep_run(seed: int) -> Any:
    if seed not in _SWEEP_RUNS:
        from tools.store_engine_diff import run_sweep

        _SWEEP_RUNS[seed] = run_sweep(rows=300, seed=seed)
    return _SWEEP_RUNS[seed]


@pytest.mark.parametrize("seed", [1, 7])
def test_sweep_allowed_means_same(seed):
    data = _sweep_run(seed)
    results = data["sweep_results"]
    assert len(results) >= 1200
    statuses = collections.Counter(r["status"] for r in results)
    assert statuses["differs"] == statuses["sql-error"] == statuses["crash"] == 0, statuses
    # a row refused at plan time or at execute time carries a reason; every other row is `same`
    for r in results:
        if r["status"].startswith("refused"):
            assert r["reason"], r["id"]
        else:
            assert r["status"] == "same", (r["id"], r["status"], r["error"])
    # whitelist-refused rows by reason: the table of stable reasons the sweep exercises
    reasons = collections.Counter(
        next((k for k in _SWEEP_WHITELIST_REASONS if k in r["reason"]), "OTHER")
        for r in results
        if r["status"] == "refused-whitelist"
    )
    assert "OTHER" not in reasons, [r["reason"] for r in results if r["status"] == "refused-whitelist" and not any(k in r["reason"] for k in _SWEEP_WHITELIST_REASONS)][:5]
    assert set(reasons) >= {
        REASON_TEXT_NON_ASCII_SPACE, REASON_DISTINCTCOUNT_NUMERIC, "DATE year must be between 1900 and 9999",
        "DATE arguments are not a valid calendar date", "numeric literal exceeds 38 total digits",
        REASON_FILTER_CONTEXT_EMPTY, REASON_BOOLEAN_LITERAL,
    }


_SWEEP_WHITELIST_REASONS = [
    REASON_TEXT_NON_ASCII_SPACE,
    REASON_DISTINCTCOUNT_NUMERIC,
    "DATE year must be between 1900 and 9999",
    "DATE arguments are not a valid calendar date",
    "numeric literal exceeds 38 total digits",
    REASON_FILTER_CONTEXT_EMPTY,
    REASON_BOOLEAN_LITERAL,
    "IN needs a table or at least one value",
    "text IN with non-ASCII items or items containing ss",
    "SUM not supported on text column",
    "literal type number does not fit text column",
]


# ---- C2a2: an alias hides a nested CALCULATE (B = [A], A = CALCULATE(..., filters)) ----------------------------
_ALIAS_TABLES = {"t": {"qty": "whole_number", "region": "text", "amt": "decimal_number", "product": "text", "pay": "date"}}


def _alias(expression: str, measures: dict[str, str]) -> WhitelistDecision:
    return classify_measure(expression, home_table="t", tables=_ALIAS_TABLES, measures=measures)


ALIAS_REFUSED = [
    ("CALCULATE([B], t[qty] < 5)", {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "[A]"}),
    ("CALCULATE([C], t[qty] < 5)", {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "[A]", "C": "[B]"}),
    ("CALCULATE([B], t[region] = \"West\")", {"A": "CALCULATE(SUM(t[qty]), t[region] = \"East\")", "B": "[A]"}),
    ("CALCULATE([B], t[qty] < 5)", {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "CALCULATE([A])"}),
]
ALIAS_ALLOWED = [
    ("CALCULATE([B], t[qty] > 3)", {"A": "SUM(t[qty])", "B": "[A]"}),
    ("CALCULATE([B], t[qty] > 3)", {"A": "CALCULATE(SUM(t[qty]), t[region] = \"East\")", "B": "[A]"}),
    ("[B]", {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "[A]"}),
    ("CALCULATE([B])", {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "[A]"}),
]


@pytest.mark.parametrize("expression, measures", ALIAS_REFUSED)
def test_alias_chain_with_same_column_filter_is_refused(expression, measures):
    decision = _alias(expression, measures)
    assert not decision.allowed
    assert decision.reasons == (REASON_NESTED_CALCULATE,)


@pytest.mark.parametrize("expression, measures", ALIAS_ALLOWED)
def test_alias_chain_on_other_columns_or_without_outer_filter_is_allowed(expression, measures):
    decision = _alias(expression, measures)
    assert decision.allowed, decision.reasons


def test_alias_cycle_does_not_hang_the_chain_walk():
    measures = {"A": "[B]", "B": "[A]"}
    decision = _alias("CALCULATE([A], t[qty] > 1)", measures)
    assert not decision.allowed


def test_mutant_alias_chain_not_followed(monkeypatch):
    from analytics_studio.store import dax_whitelist

    expression, measures = ALIAS_REFUSED[0]
    assert not _alias(expression, measures).allowed
    monkeypatch.setattr(dax_whitelist, "_alias_chain_columns", lambda body, measures_norm: set())
    assert _alias(expression, measures).allowed  # the mutant lets the silent wrong value through


# ---- C2a3: the WHOLE chain counts (a deeper link), case, and partial overlap -------------------------------------
_REGION_QTY_A = 'CALCULATE(SUM(t[qty]), t[region] = "East", t[qty] > 2)'
CHAIN_REFUSED = [
    # a deeper link filters the column the outer filter names (the first filtered link does not)
    ("CALCULATE([D], t[region] = \"West\")", {
        "A": 'CALCULATE(SUM(t[qty]), t[region] = "East")', "B": "[A]", "C": "CALCULATE([B], t[qty] > 3)", "D": "[C]"}),
    ("CALCULATE([D], T[Region] = \"North\")", {
        "A": 'CALCULATE(MAX(t[pay]), T[Region] IN {"East", "North"})', "B": "[A]",
        "C": "CALCULATE([B], t[pay] < DATE(2025, 3, 1))", "D": "[C]"}),
    ("CALCULATE([D], t[product] IN {\"P01\", \"P02\"})", {
        "A": 'CALCULATE(SUM(t[amt]), t[product] = "P03")', "B": "[A]",
        "C": "CALCULATE([B], T[QTY] = 3 || T[QTY] = 4)", "D": "[C]"}),
    # case variants of a column and a table name
    ("CALCULATE([B], t[Qty] < 5)", {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "[A]"}),
    ("CALCULATE([B], T[QTY] < 5)", {"A": "CALCULATE(SUM(t[qty]), t[qty] > 2)", "B": "[A]"}),
    # partial overlap: the outer filter shares ONE column with the chain, in both directions
    ("CALCULATE([B], t[region] = \"North\", t[qty] < 6)", {"A": _REGION_QTY_A, "B": "[A]"}),
    ("CALCULATE([B], t[qty] < 6)", {"A": _REGION_QTY_A, "B": "[A]"}),
    ("CALCULATE([B], t[region] = \"North\", t[qty] < 6, t[product] = \"P01\")", {"A": _REGION_QTY_A, "B": "[A]"}),
    ("CALCULATE([B], t[region] = \"North\")", {"A": _REGION_QTY_A, "B": "[A]"}),
]
CHAIN_ALLOWED = [
    ("CALCULATE([D], t[product] = \"P01\")", {
        "A": 'CALCULATE(SUM(t[qty]), t[region] = "East")', "B": "[A]", "C": "CALCULATE([B], t[qty] > 3)", "D": "[C]"}),
    ("CALCULATE([B], t[pay] > DATE(2024, 1, 1))", {"A": _REGION_QTY_A, "B": "[A]"}),
]


@pytest.mark.parametrize("expression, measures", CHAIN_REFUSED)
def test_whole_alias_chain_is_compared_with_the_outer_filter(expression, measures):
    decision = _alias(expression, measures)
    assert not decision.allowed and decision.reasons == (REASON_NESTED_CALCULATE,), decision


@pytest.mark.parametrize("expression, measures", CHAIN_ALLOWED)
def test_whole_alias_chain_on_other_columns_is_allowed(expression, measures):
    decision = _alias(expression, measures)
    assert decision.allowed, decision.reasons


def test_mutant_chain_columns_compared_case_sensitively(monkeypatch):
    from analytics_studio.store import dax_whitelist

    expression, measures = CHAIN_REFUSED[3]
    assert not _alias(expression, measures).allowed
    real = dax_whitelist._collect_references
    monkeypatch.setattr(dax_whitelist, "_filter_columns", lambda nodes: {column for _, column in real(nodes)})
    assert _alias(expression, measures).allowed  # the mutant: t[Qty] is not t[qty]


def test_mutant_only_the_first_filtered_link_counts(monkeypatch):
    from analytics_studio.store import dax_whitelist

    expression, measures = CHAIN_REFUSED[0]
    assert not _alias(expression, measures).allowed
    real = dax_whitelist._alias_chain_columns

    def first_link_only(body, measures_norm):
        return real(body, {})  # the walk cannot follow a reference: only the first link is seen

    monkeypatch.setattr(dax_whitelist, "_alias_chain_columns", first_link_only)
    assert _alias(expression, measures).allowed
