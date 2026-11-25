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

def test_differential_catalog_rules(dataset_and_catalog):
    col_types, catalog, headers = dataset_and_catalog
    tables = {"t": col_types}

    allowed_count = 0
    refused_count = 0
    skipped_count = 0
    rule_b_by_shape: dict[str, int] = {}

    for f in catalog:
        dax = f.get("dax")
        # Skip group_by pseudo-DAX
        if not dax or f.get("group_col") or dax.startswith("group_by("):
            skipped_count += 1
            continue

        decision = classify_measure(dax, home_table="t", tables=tables)

        if decision.allowed:
            allowed_count += 1
            # Rule A (safety): if allowed, mapped generate_sql must return a str, not a Refusal
            sql = generate_sql(f, "t_csv", col_types, mode="mapped")
            assert isinstance(sql, str), (
                f"Rule A violated for {f['id']} ({dax}): generate_sql returned {sql}"
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
    assert skipped_count == 28
    assert allowed_count == 632
    assert refused_count == 183
    assert len(catalog) == 843

    # Rule B counts: 7 formulas the mapped store can do (arithmetic and SUMX) that whitelist refuses
    expected_rule_b = {"SUM": 2, "RATIO": 1, "DIVIDE": 1, "ARITH": 1, "SUMX": 2}
    assert rule_b_by_shape == expected_rule_b


# ---------------------------------------------------------------------------
# (ii) Hand-written negative table of at least 30 expressions (one per reason)
# ---------------------------------------------------------------------------

NEGATIVE_CASES = [
    # 1. Arithmetic binary '+'
    ("SUM(t[w]) + 1", "t", REASON_ARITHMETIC),
    # 2. Arithmetic binary '-'
    ("AVERAGE(t[w]) - MIN(t[w])", "t", REASON_ARITHMETIC),
    # 3. Arithmetic binary '/'
    ("SUM(t[d]) / COUNT(t[d])", "t", REASON_ARITHMETIC),
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
    # 9. DIVIDE function
    ("DIVIDE(SUM(t[w]), 2)", "t", "function DIVIDE is not on the store whitelist"),
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
    # 23. CALCULATE with NOT predicate
    ('CALCULATE(MAX(t[w]), NOT(t[cat] = "A"))', "t", "MAX_filtered", "t"),
    # 24. CALCULATE with || OR predicate
    ('CALCULATE(COUNTA(t[cat]), t[cat] = "A" || t[cat] = "B")', "t", "COUNTA_filtered", "t"),
    # 25. CALCULATE with text IN tableconstructor
    ('CALCULATE(DISTINCTCOUNT(t[w]), t[cat] IN {"A", "B", "C"})', "t", "DISTINCTCOUNT_filtered", "t"),
    # 26. Lowercase function names and extra whitespace
    ('  calculate(  sum( t[w] ),   not( t[cat] = "A" ) )  ', "t", "SUM_filtered", "t"),
    # 27. Case-insensitive table and column names
    ('CALCULATE(SUM(T[W]), T[CAT] = "A")', "t", "SUM_filtered", "t"),
    # 28. Transitive measure reference (bare [BaseSum])
    ("[BaseSum]", "t", "SUM", "t"),
    # 29. Transitive measure in CALCULATE with filter
    ('CALCULATE([BaseSum], t[cat] = "A")', "t", "SUM_filtered", "t"),
    # 30. Unqualified column in home table inside AGG
    ("SUM([w])", "t", "SUM", "t"),
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
