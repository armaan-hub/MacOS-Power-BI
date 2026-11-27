"""DAX whitelist classifier for the store SQL path (Stage C1a).

Decides, for one measure expression, whether the store SQL path may evaluate it.
Default answer is REFUSE. The whitelist is a safety gate: a wrongly allowed shape
is a silent wrong answer on a large table, so every admitted form is one the rules
tool (tools/store_engine_diff.py, build_formula_catalog) compares AND whose mapped
status is "same". Forms the catalog does not compare are refused.

classify_measure never raises: a parse error, a too deeply nested expression or any
other unexpected error comes back as a refusal.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Collection, Mapping, Sequence

from analytics_studio.measures import MeasureError, Token, parse_expression, tokenize
from analytics_studio.store import dax_arith
from analytics_studio.store.dax_arith import is_arithmetic_node, parse_arith

# Canonical column types the whitelist knows. The store has two vocabularies:
# store/base.py COLUMN_TYPES (whole, decimal, fixed, datetime, text, boolean) and
# store/type_detect.py detect_column_types (whole_number, decimal_number, date,
# datetime, time, boolean, text). Only the names below are mapped; everything else
# is refused with a reason naming the type.
_KNOWN_TYPE_NAMES: dict[str, str] = {
    "whole": "whole_number",
    "whole_number": "whole_number",
    "decimal": "decimal_number",
    "decimal_number": "decimal_number",
    "date": "date",
    "boolean": "boolean",
    "text": "text",
}
# Types the store can hold but the rules tool catalog has no column of: refused.
_UNCATALOGUED_TYPE_NAMES: frozenset[str] = frozenset({"datetime", "fixed"})

# Admitted aggregate functions and the canonical column types they support on the store mapped path
ALLOWED_AGGREGATES: dict[str, frozenset[str]] = {
    "SUM": frozenset({"whole_number", "decimal_number"}),
    "AVERAGE": frozenset({"whole_number", "decimal_number"}),
    "MIN": frozenset({"whole_number", "decimal_number", "date"}),
    "MAX": frozenset({"whole_number", "decimal_number", "date"}),
    "COUNT": frozenset({"whole_number", "decimal_number", "date"}),
    "COUNTA": frozenset({"whole_number", "decimal_number", "date", "text", "boolean"}),
    "COUNTBLANK": frozenset({"whole_number", "decimal_number", "date", "text", "boolean"}),
    # Numeric DISTINCTCOUNT differs from the engine in the rules tool (class
    # distinct_numeric_text_variants), so only text, date and boolean are admitted.
    "DISTINCTCOUNT": frozenset({"date", "text", "boolean"}),
}

# Comparison operators admitted in a predicate, per canonical column type, taken from
# what the catalog compares. The literal must be on the RIGHT of the operator.
#   text:    "=" only (catalog: cat/t/id equality). DAX text ordering is locale collation,
#            DuckDB's is binary, so <>, <, <=, >, >= are refused.
#   whole:   = < <= > >= <> (catalog w_zero, w_lt, w_lte, w_gt, w_gte, w_neq).
#   decimal: >= < <> (catalog d_gte, d_lt, d_neq).
#   date:    >= > <= < <> (catalog dt_range, dt_gt, dt_lte, dt_lt, dt_neq).
#   boolean: no predicates.
PREDICATE_OPS_BY_TYPE: dict[str, frozenset[str]] = {
    "text": frozenset({"="}),
    "whole_number": frozenset({"=", "<", "<=", ">", ">=", "<>"}),
    "decimal_number": frozenset({">=", "<", "<>"}),
    "date": frozenset({">=", ">", "<=", "<", "<>"}),
    "boolean": frozenset(),
}
# Column types that admit IN over a table constructor of string literals (catalog cat_in).
IN_COLUMN_TYPES: frozenset[str] = frozenset({"text"})
# NOT(...) and || are admitted only over "=" comparisons on these column types (catalog
# w_not, w_or); all operands of one || must be on the same column.
COMPOSITE_COLUMN_TYPES: frozenset[str] = frozenset({"whole_number"})
COMPOSITE_OPS: frozenset[str] = frozenset({"="})

# Every comparison operator the parser can hand to a predicate (the global gate).
ALLOWED_PREDICATE_OPS: set[str] = {"=", "<>", "<", "<=", ">", ">="}
_TEXT_ORDER_OPS: frozenset[str] = frozenset({"<>", "<", "<=", ">", ">="})

# Shape caps, checked on the token list BEFORE parse_expression runs. The parser is recursive (about 10 Python
# frames per open bracket, 2 per operator of a chain), so an unbounded input would be refused or admitted
# depending on sys.getrecursionlimit(). Every cap below is a stable refusal. Measured worst admitted input:
# a measure chain 32 deep whose last expression holds MAX_NESTING open brackets and a MAX_OR_TERMS chain.
MAX_OR_TERMS = 50      # operands of one || (or &&) chain
MAX_PREDICATES = 50    # filter arguments of one CALCULATE
MAX_IN_ITEMS = 200     # items of one {...} table constructor
MAX_NESTING = 20       # open ( and { at the same time
MAX_TOKENS = 1500      # tokens of one expression

# Literal ranges
WHOLE_MIN = -(2**63)
WHOLE_MAX = 2**63 - 1
MAX_DECIMAL_DIGITS = 38
DATE_MIN_YEAR = 1900
DATE_MAX_YEAR = 9999

# Known node kinds that can be evaluated or refused
KNOWN_NODE_KINDS: set[str] = {
    "call", "reference", "table", "comparison", "logical", "in", "number",
    "string", "boolean", "blank", "binary", "unary", "let", "var", "strict_equal",
}

SOURCE_KINDS: frozenset[str] = frozenset({"csv", "parquet"})

# Standard refusal reasons
REASON_DEFAULT_REFUSE = "Default answer is refuse."
REASON_MAX_DEPTH_EXCEEDED = "measure reference chain too deep"
REASON_NESTED_CALCULATE = "nested CALCULATE filters are not on the store whitelist"
REASON_DISTINCTCOUNTNOBLANK = "DISTINCTCOUNTNOBLANK not supported on store"
REASON_LOGICAL_AND = "logical && filter not supported on store"
REASON_ARITHMETIC = "arithmetic is not on the store whitelist"
REASON_LET = "VAR/RETURN syntax is not on the store whitelist"
REASON_TWO_COLUMNS = "comparison between two columns is not supported"
REASON_BLANK_COMPARISON = "BLANK() comparisons are not supported"
REASON_BOOLEAN_LITERAL = "boolean literals are not supported in predicates"
REASON_NO_TABLES = "measure references no tables"
REASON_LITERAL_LEFT = "the literal must be on the right side of the comparison"
REASON_TEXT_ORDERING = (
    "text comparison other than = is not on the store whitelist "
    "(DAX text ordering is locale collation, store ordering is binary; open Power BI answer check)"
)
REASON_COMPOSITE = (
    "NOT and || are only on the store whitelist over whole-number = comparisons"
)
REASON_OR_SAME_COLUMN = "all operands of || must be on the same column"
REASON_TOO_DEEP = "expression is too deeply nested for the store whitelist"
REASON_CAP_OR_TERMS = f"a || chain with more than {MAX_OR_TERMS} operands is not on the store whitelist"
REASON_CAP_PREDICATES = f"a CALCULATE with more than {MAX_PREDICATES} filter arguments is not on the store whitelist"
REASON_CAP_IN_ITEMS = f"an IN list with more than {MAX_IN_ITEMS} items is not on the store whitelist"
REASON_CAP_NESTING = f"brackets nested more than {MAX_NESTING} deep are not on the store whitelist"
REASON_CAP_TOKENS = f"an expression with more than {MAX_TOKENS} tokens is not on the store whitelist"
REASON_TEXT_IN_FOLD = (
    "text IN with non-ASCII items or items containing ss is not on the store whitelist: "
    "the engine folds those differently"
)
REASON_TEXT_NON_ASCII_SPACE = (
    "text literal with a non-ASCII whitespace character is not on the store whitelist: "
    "the engine trims and compares those differently"
)
REASON_FILTER_CONTEXT_OTHER_TABLE = "a filter context predicate must be on the measure's own table"
REASON_FILTER_CONTEXT_EMPTY = "a filter context predicate must not be empty"
REASON_SLICER_SAME_COLUMN = (
    "same-column filter and slicer: DAX replaces the outer filter, not checked yet"
)
REASON_IN_NUMERIC_MIX = (
    "a text IN together with a comparison on a numeric column in one CALCULATE is not on the store whitelist: "
    "the engine raises a type error on blank numeric cells (rules tool refusal B1)"
)
REASON_IN_FOLD_EQ_MIX = (
    "a text IN together with a text equality on a non-ASCII literal or a literal containing ss in one CALCULATE "
    "is not on the store whitelist: the engine ignores the IN (measured by the C1b2 sweep)"
)
REASON_UNEXPECTED = "unexpected error while classifying"
# Arithmetic over totals (Stage C4b): the texts live with the combiner (dax_arith) and are part of this reason table
REASON_ARITH_LEAF = dax_arith.REASON_ARITH_LEAF
REASON_ARITH_DATE = dax_arith.REASON_ARITH_DATE
REASON_ARITH_LITERAL = dax_arith.REASON_ARITH_LITERAL
REASON_ARITH_DIVIDE_ALT = dax_arith.REASON_ARITH_DIVIDE_ALT
REASON_ARITH_CAP_LEAVES = dax_arith.REASON_ARITH_CAP_LEAVES
REASON_ARITH_CAP_NODES = dax_arith.REASON_ARITH_CAP_NODES
REASON_ARITH_CAP_DEPTH = dax_arith.REASON_ARITH_CAP_DEPTH
REASON_ARITH_IN_CALCULATE = dax_arith.REASON_ARITH_IN_CALCULATE
REASON_ARITH_WHOLE_BEYOND_64 = dax_arith.REASON_ARITH_WHOLE_BEYOND_64
REASON_ARITH_DIVIDE_NON_FINITE = dax_arith.REASON_ARITH_DIVIDE_NON_FINITE
REASON_ARITH_SIGNED_ZERO_DIVISOR = dax_arith.REASON_ARITH_SIGNED_ZERO_DIVISOR
REASON_ARITH_DIVIDE_SUBNORMAL = dax_arith.REASON_ARITH_DIVIDE_SUBNORMAL


def _in_item_folds_differently(text: str) -> bool:
    """True for an IN item the engine casefolds differently from the store's ASCII-only fold."""
    return not text.isascii() or "ss" in text.lower()
REASON_DISTINCTCOUNT_NUMERIC = (
    "DISTINCTCOUNT on a numeric column differs from the engine "
    "(open Power BI answer check: distinct_numeric_text_variants)"
)
# Wording of the rules tool refusals (tools/store_engine_diff.py)
REASON_PARQUET_COUNTA = "COUNTA on Parquet typed columns differs from CSV store"
REASON_DECIMAL_DIGITS = "Decimal value exceeds 38 total digits"


@dataclass(frozen=True)
class WhitelistDecision:
    """Decision on whether a measure expression is allowed on the store SQL path."""
    allowed: bool
    table: str | None
    shape: str | None
    reasons: tuple[str, ...]


def _canonical_type(raw_type: Any) -> tuple[str | None, str | None]:
    """Map a store / model type name to a canonical type.

    Returns (canonical, None) for a known name, (None, reason) for anything else:
    unknown names, None, typos, "time", and the uncatalogued "datetime" and "fixed".
    """
    if isinstance(raw_type, str):
        if raw_type in _KNOWN_TYPE_NAMES:
            return _KNOWN_TYPE_NAMES[raw_type], None
        if raw_type in _UNCATALOGUED_TYPE_NAMES:
            return None, (
                f"column type '{raw_type}' is not on the store whitelist "
                "(the rules tool catalog has no such column)"
            )
    return None, f"unknown column type '{raw_type}' is not on the store whitelist"


def _check_shape_caps(tokens: list[Token]) -> str | None:
    """Refusal reason when the token list breaks a shape cap, else None. One pass, no recursion."""
    if len(tokens) > MAX_TOKENS:
        return REASON_CAP_TOKENS
    # One frame per open bracket (plus the outermost level): [is_brace, is_calculate, commas, logical operators]
    frames: list[list[Any]] = [[False, False, 0, 0]]
    for position, token in enumerate(tokens):
        kind = token.kind
        if kind in ("(", "{"):
            previous = tokens[position - 1] if position else None
            is_calculate = (
                kind == "(" and previous is not None
                and previous.kind == "identifier" and previous.value == "CALCULATE"
            )
            frames.append([kind == "{", is_calculate, 0, 0])
            if len(frames) - 1 > MAX_NESTING:
                return REASON_CAP_NESTING
        elif kind in (")", "}"):
            if len(frames) > 1:
                frames.pop()
        elif kind == ",":
            frame = frames[-1]
            frame[2] += 1
            frame[3] = 0
            if frame[0] and frame[2] + 1 > MAX_IN_ITEMS:
                return REASON_CAP_IN_ITEMS
            if frame[1] and frame[2] > MAX_PREDICATES:
                return REASON_CAP_PREDICATES
        elif kind in ("||", "&&"):
            frame = frames[-1]
            frame[3] += 1
            if frame[3] + 1 > MAX_OR_TERMS:
                return REASON_CAP_OR_TERMS
    return None


def _type_error_reason(agg: str, col_type: str) -> str:
    """Return refusal reason wording mirroring the rules tool."""
    c_norm, _ = _canonical_type(col_type)
    return f"{agg} not supported on {c_norm or col_type} column"


def _number_value(node: Any) -> Decimal | None:
    """Exact signed value of a number literal or a unary minus over one, else None."""
    sign = 1
    if isinstance(node, tuple) and node and node[0] == "unary" and node[1] == "-":
        sign = -1
        node = node[2]
    if not (isinstance(node, tuple) and node and node[0] == "number"):
        return None
    text = node[2] if len(node) > 2 and isinstance(node[2], str) else str(node[1])
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return -value if sign < 0 else value


def _total_digits(value: Decimal) -> int | None:
    """Digits needed to write the value out in full; None when not finite."""
    _, digits, exp = value.as_tuple()
    if not isinstance(exp, int):
        return None
    return len(digits) + exp if exp >= 0 else max(len(digits), -exp)


def _check_number_fits(value: Decimal | None, col_type: str) -> str | None:
    """Refusal reason when a numeric literal does not fit the column type, else None."""
    if value is None:
        return "numeric literal is not valid"
    total = _total_digits(value)
    if total is None or total > MAX_DECIMAL_DIGITS:
        return f"numeric literal exceeds {MAX_DECIMAL_DIGITS} total digits"
    if col_type == "whole_number":
        if value != value.to_integral_value():
            return "whole-number column needs an integer-valued literal"
        if not (WHOLE_MIN <= int(value) <= WHOLE_MAX):
            return "whole-number literal is outside the 64-bit range"
    return None


def _check_date_call(node: tuple[Any, ...]) -> str | None:
    """Refusal reason for a DATE(y, m, d) literal that is not a valid calendar date, else None."""
    args = node[2]
    if len(args) != 3:
        return "DATE function must have 3 arguments"
    parts: list[int] = []
    for a in args:
        if not (isinstance(a, tuple) and a and a[0] == "number"):
            return "DATE arguments must be integer literals"
        text = a[2] if len(a) > 2 and isinstance(a[2], str) else str(a[1])
        if not text.isascii() or not text.isdigit() or len(text) > 6:
            return "DATE arguments must be integer literals"
        parts.append(int(text))
    year, month, day = parts
    if not (DATE_MIN_YEAR <= year <= DATE_MAX_YEAR):
        return f"DATE year must be between {DATE_MIN_YEAR} and {DATE_MAX_YEAR}"
    try:
        _dt.date(year, month, day)
    except ValueError:
        return "DATE arguments are not a valid calendar date"
    return None


def _check_literal_type(node: tuple[Any, ...]) -> tuple[str | None, str | None]:
    """Check literal node and return (type_name, error_reason)."""
    if not isinstance(node, tuple):
        return None, "invalid literal node"
    kind = node[0]
    if kind == "number":
        return "number", None
    if kind == "string":
        return "string", None
    if kind == "unary" and node[1] == "-":
        sub = node[2]
        if isinstance(sub, tuple) and sub[0] == "number":
            return "number", None
        return None, "unary operator on non-number literal is not supported"
    if kind == "call" and node[1] == "DATE":
        err = _check_date_call(node)
        if err:
            return None, err
        return "date", None
    if kind == "blank":
        return None, REASON_BLANK_COMPARISON
    if kind == "boolean":
        return None, REASON_BOOLEAN_LITERAL
    return None, f"node kind {kind} is not a valid literal"


def _check_comparison(
    node: tuple[Any, ...],
    tables_norm: dict[str, dict[str, str]],
    tables_orig: dict[str, str],
    home_table_norm: str,
    measures_norm: dict[str, str],
    reasons: list[str],
    referenced_tables: set[str],
) -> tuple[tuple[str, str], str, str] | None:
    """Validate one comparison predicate against the per-type operator table.

    Appends refusal reasons. Returns ((table, column), canonical type, operator) when the
    comparison is fully admitted, else None.
    """
    n_before = len(reasons)
    op, left, right = node[1], node[2], node[3]
    if op not in ALLOWED_PREDICATE_OPS:
        reasons.append(f"operator {op} is not on the store whitelist")
        return None

    left_is_ref = isinstance(left, tuple) and left[0] == "reference"
    right_is_ref = isinstance(right, tuple) and right[0] == "reference"

    if left_is_ref and right_is_ref:
        reasons.append(REASON_TWO_COLUMNS)
        return None
    if not left_is_ref and not right_is_ref:
        reasons.append("comparison must involve a column reference")
        return None
    if right_is_ref:
        reasons.append(REASON_LITERAL_LEFT)
        return None

    _, t_name, col_name = left
    resolved_t, col_type, err = _resolve_column(
        t_name, col_name, tables_norm, tables_orig, home_table_norm, measures_norm
    )
    if err:
        reasons.append(err)
        return None
    if resolved_t:
        referenced_tables.add(resolved_t)

    col_norm_type, type_err = _canonical_type(col_type)
    if type_err or col_norm_type is None:
        reasons.append(type_err or "unknown column type")
        return None

    lit_type, lit_err = _check_literal_type(right)
    if lit_err:
        reasons.append(lit_err)
        return None

    if col_norm_type in ("whole_number", "decimal_number"):
        if lit_type != "number":
            reasons.append(f"literal type {lit_type} does not fit {col_norm_type} column")
            return None
    elif col_norm_type == "text":
        if lit_type != "string":
            reasons.append(f"literal type {lit_type} does not fit text column")
            return None
        if any(ch.isspace() and not ch.isascii() for ch in str(right[1])):
            reasons.append(REASON_TEXT_NON_ASCII_SPACE)
            return None
    elif col_norm_type == "date":
        if lit_type != "date":
            reasons.append(f"literal type {lit_type} does not fit date column")
            return None
    elif col_norm_type == "boolean":
        reasons.append("boolean column comparison not supported on store")
        return None

    if op not in PREDICATE_OPS_BY_TYPE.get(col_norm_type, frozenset()):
        if col_norm_type == "text" and op in _TEXT_ORDER_OPS:
            reasons.append(REASON_TEXT_ORDERING)
        else:
            reasons.append(f"operator {op} is not on the store whitelist for {col_norm_type} columns")
        return None

    if col_norm_type in ("whole_number", "decimal_number"):
        fit_err = _check_number_fits(_number_value(right), col_norm_type)
        if fit_err:
            reasons.append(fit_err)
            return None

    if len(reasons) != n_before:
        return None
    return (resolved_t or "", col_name.casefold()), col_norm_type, op


def in_mix_reason(
    nodes: Sequence[Any],
    tables: Mapping[str, Mapping[str, str]],
    home_table: str,
) -> str | None:
    """A refusal reason when the predicate nodes mix a text IN with a form the engine mishandles, else None.

    (1) IN with a comparison on a whole or decimal column: the engine raises "Cannot convert value '' of type
    Text to type Number." whenever the numeric column has a blank cell (REASON_IN_NUMERIC_MIX).
    (2) IN with a text equality on a literal that is non-ASCII or contains "ss": the engine returns the count of
    the equality alone, as if the IN were not there (REASON_IN_FOLD_EQ_MIX). Both measured by the C1b2 sweep.
    """
    tables_norm, _, _, collision = _normalize_inputs(tables, None)
    if collision:
        return None
    home_norm = home_table.casefold()
    has_in = False
    has_numeric = False
    has_fold_eq = False
    stack: list[Any] = list(nodes)
    while stack:
        node = stack.pop()
        if not (isinstance(node, tuple) and node):
            continue
        if node[0] == "in":
            has_in = True
        elif node[0] == "comparison" and len(node) >= 4:
            ref = node[2] if isinstance(node[2], tuple) and node[2] and node[2][0] == "reference" else node[3]
            lit = node[3] if ref is node[2] else node[2]
            if isinstance(ref, tuple) and len(ref) == 3 and ref[0] == "reference":
                columns = tables_norm.get((ref[1] or "").casefold() or home_norm, {})
                col_type, _ = _canonical_type(columns.get(ref[2].casefold()))
                if col_type in ("whole_number", "decimal_number"):
                    has_numeric = True
                elif col_type == "text" and isinstance(lit, tuple) and lit and lit[0] == "string":
                    if _in_item_folds_differently(lit[1]):
                        has_fold_eq = True
        elif node[0] == "logical":
            stack.extend(node[2:])
        elif node[0] == "call" and node[1] == "NOT":
            stack.extend(node[2])
    if has_in and has_numeric:
        return REASON_IN_NUMERIC_MIX
    if has_in and has_fold_eq:
        return REASON_IN_FOLD_EQ_MIX
    return None


def _check_composite(
    leaves: list[Any],
    tables_norm: dict[str, dict[str, str]],
    tables_orig: dict[str, str],
    home_table_norm: str,
    measures_norm: dict[str, str],
    reasons: list[str],
    referenced_tables: set[str],
) -> None:
    """NOT / || operands: only whole-number = comparisons, all on one column."""
    columns: set[tuple[str, str]] = set()
    for leaf in leaves:
        if isinstance(leaf, tuple) and leaf and leaf[0] == "logical" and leaf[1] == "&&":
            reasons.append(REASON_LOGICAL_AND)
            continue
        if not (isinstance(leaf, tuple) and leaf and leaf[0] == "comparison"):
            reasons.append(REASON_COMPOSITE)
            continue
        res = _check_comparison(
            leaf, tables_norm, tables_orig, home_table_norm, measures_norm, reasons, referenced_tables
        )
        if res is None:
            continue
        column, col_type, op = res
        if col_type not in COMPOSITE_COLUMN_TYPES or op not in COMPOSITE_OPS:
            reasons.append(REASON_COMPOSITE)
            continue
        columns.add(column)
    if len(columns) > 1:
        reasons.append(REASON_OR_SAME_COLUMN)


def _check_predicate(
    node: tuple[Any, ...],
    tables_norm: dict[str, dict[str, str]],
    tables_orig: dict[str, str],
    home_table_norm: str,
    measures_norm: dict[str, str],
    reasons: list[str],
    referenced_tables: set[str],
) -> None:
    """Validate a filter predicate node. Collects refusal reasons."""
    kind = node[0]

    # Check known node kind
    if kind not in KNOWN_NODE_KINDS:
        reasons.append(f"node kind {kind} is not on the store whitelist")
        return

    # NOT(...) call: one whole-number "=" comparison
    if kind == "call" and node[1] == "NOT":
        args = node[2]
        if len(args) != 1:
            reasons.append("call NOT requires exactly one argument")
            return
        _check_composite(
            [args[0]], tables_norm, tables_orig, home_table_norm, measures_norm, reasons, referenced_tables
        )
        return

    # || logical OR: flattened iteratively so a long chain cannot recurse
    if kind == "logical" and node[1] == "||":
        leaves: list[Any] = []
        stack: list[Any] = [node]
        while stack:
            current = stack.pop()
            if isinstance(current, tuple) and current and current[0] == "logical" and current[1] == "||":
                stack.append(current[3])
                stack.append(current[2])
            else:
                leaves.append(current)
        _check_composite(
            leaves, tables_norm, tables_orig, home_table_norm, measures_norm, reasons, referenced_tables
        )
        return

    # && logical AND
    if kind == "logical" and node[1] == "&&":
        reasons.append(REASON_LOGICAL_AND)
        return

    # IN predicate
    if kind == "in":
        ref_node, table_ctor = node[1], node[2]
        if not isinstance(ref_node, tuple) or ref_node[0] != "reference":
            reasons.append("left side of IN must be a column reference")
            return
        _, t_name, col_name = ref_node
        resolved_t, col_type, err = _resolve_column(
            t_name, col_name, tables_norm, tables_orig, home_table_norm, measures_norm
        )
        if err:
            reasons.append(err)
            return
        if resolved_t:
            referenced_tables.add(resolved_t)

        col_norm_type, type_err = _canonical_type(col_type)
        if type_err or col_norm_type is None:
            reasons.append(type_err or "unknown column type")
            return
        if col_norm_type not in IN_COLUMN_TYPES:
            reasons.append(f"IN filter not supported on {col_norm_type} column")
            return

        if not isinstance(table_ctor, tuple) or table_ctor[0] != "tableconstructor":
            reasons.append("right side of IN must be a table constructor of string literals")
            return

        items = table_ctor[1]
        if not items:
            reasons.append("IN needs at least one string literal")
            return
        for item in items:
            if not isinstance(item, tuple) or item[0] != "string":
                reasons.append("IN values must be string literals")
                return
        if any(_in_item_folds_differently(item[1]) for item in items):
            reasons.append(REASON_TEXT_IN_FOLD)
        return

    # Comparison predicate
    if kind == "comparison":
        _check_comparison(
            node, tables_norm, tables_orig, home_table_norm, measures_norm, reasons, referenced_tables
        )
        return

    if kind == "call":
        reasons.append(f"function {node[1]} is not on the store whitelist")
        return

    reasons.append(f"node kind {kind} is not on the store whitelist")


def _resolve_column(
    table_name: str,
    column_name: str,
    tables_norm: dict[str, dict[str, str]],
    tables_orig: dict[str, str],
    home_table_norm: str,
    measures_norm: dict[str, str],
) -> tuple[str | None, str | None, str | None]:
    """Resolve column or unqualified reference to (orig_table_name, col_type, error_str)."""
    c_fold = column_name.casefold()
    if table_name:
        t_fold = table_name.casefold()
        if t_fold not in tables_norm:
            return None, None, f"unknown table '{table_name}'"
        cols = tables_norm[t_fold]
        if c_fold not in cols:
            return None, None, f"unknown column '{column_name}' in table '{table_name}'"
        return tables_orig[t_fold], cols[c_fold], None

    # Unqualified reference: [Name]
    # A measure named like a column wins here: the whitelist refuses SUM([w]) when a measure
    # w exists, although the engine takes the COLUMN in that case. Stricter on purpose: the
    # two readings can differ, so the store path does not guess.
    if c_fold in measures_norm:
        # It is a measure reference, not a column
        return None, None, f"measure reference '{column_name}' not expected in column context"

    # Otherwise resolves to column of home table
    if home_table_norm not in tables_norm:
        return None, None, f"unknown home table '{home_table_norm}'"
    cols = tables_norm[home_table_norm]
    if c_fold not in cols:
        return None, None, f"unknown column or measure '{column_name}'"
    return tables_orig[home_table_norm], cols[c_fold], None


def _normalize_inputs(
    tables: Mapping[str, Mapping[str, str]],
    measures: Mapping[str, str] | None,
) -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str], str | None]:
    """Case-fold table, column and measure names. The last item is a refusal reason when two
    names collide after folding (a silent merge would change which column is meant)."""
    tables_norm: dict[str, dict[str, str]] = {}
    tables_orig: dict[str, str] = {}
    for t_name, cols in tables.items():
        t_fold = t_name.casefold()
        if t_fold in tables_orig:
            return {}, {}, {}, (
                f"table names '{tables_orig[t_fold]}' and '{t_name}' collide when compared "
                "case-insensitively"
            )
        tables_orig[t_fold] = t_name
        cols_norm: dict[str, str] = {}
        col_orig: dict[str, str] = {}
        for c_name, c_type in cols.items():
            c_fold = c_name.casefold()
            if c_fold in cols_norm:
                return {}, {}, {}, (
                    f"column names '{col_orig[c_fold]}' and '{c_name}' in table '{t_name}' "
                    "collide when compared case-insensitively"
                )
            cols_norm[c_fold] = c_type
            col_orig[c_fold] = c_name
        tables_norm[t_fold] = cols_norm
    measures_norm: dict[str, str] = {}
    measure_orig: dict[str, str] = {}
    for m_name, expr in (measures or {}).items():
        m_fold = m_name.casefold()
        if m_fold in measures_norm:
            return {}, {}, {}, (
                f"measure names '{measure_orig[m_fold]}' and '{m_name}' collide when compared "
                "case-insensitively"
            )
        measures_norm[m_fold] = expr
        measure_orig[m_fold] = m_name
    return tables_norm, tables_orig, measures_norm, None


def _collect_references(nodes: Any) -> list[tuple[str, str]]:
    """All (table, column) reference nodes below the given nodes, found iteratively."""
    found: list[tuple[str, str]] = []
    stack: list[Any] = [nodes]
    while stack:
        current = stack.pop()
        if isinstance(current, tuple):
            if len(current) == 3 and current[0] == "reference" and isinstance(current[1], str) and isinstance(current[2], str):
                found.append((current[1], current[2]))
            else:
                stack.extend(current)
        elif isinstance(current, list):
            stack.extend(current)
    return found


def _alias_chain_columns(body: str, measures_norm: dict[str, str]) -> set[str]:
    """The columns (case-folded) that ANY link of an alias chain filters.

    The chain is followed through the whole way: a measure whose body is a bare [X], and a CALCULATE([X], filters)
    link (its filters are collected and its first argument is followed). It ends at a measure that is not a
    reference to another measure. A cycle ends the walk.
    """
    seen: set[str] = set()
    columns: set[str] = set()
    current = body
    while True:
        try:
            node = parse_expression(current)
        except Exception:
            return columns
        target: str | None = None
        if node[0] == "reference" and not node[1]:
            target = str(node[2]).casefold()
        elif node[0] == "call" and node[1] == "CALCULATE" and node[2]:
            columns |= _filter_columns(tuple(node[2][1:]))
            first = node[2][0]
            if isinstance(first, tuple) and first[0] == "reference" and not first[1]:
                target = str(first[2]).casefold()
        if target is None or target in seen or target not in measures_norm:
            return columns
        seen.add(target)
        current = measures_norm[target]


def _filter_columns(nodes: Any) -> set[str]:
    return {column.casefold() for _, column in _collect_references(nodes)}


def _source_reasons(
    base_node: Any,
    predicates: tuple[Any, ...],
    tables_norm: dict[str, dict[str, str]],
    tables_orig: dict[str, str],
    home_table_norm: str,
    measures_norm: dict[str, str],
    source_kind: str,
    digits_norm: dict[str, int],
) -> list[str]:
    """Source-dependent refusals (Parquet COUNTA; more than 38 decimal digits) for one base
    aggregate and its predicate columns. Wording follows the rules tool."""
    out: list[str] = []
    refs: list[tuple[str, str]] = []
    if isinstance(base_node, tuple) and base_node and base_node[0] == "call":
        if base_node[1] == "COUNTA" and source_kind == "parquet":
            out.append(REASON_PARQUET_COUNTA)
        if base_node[1] in ALLOWED_AGGREGATES:
            refs.extend(_collect_references(base_node[2]))
    refs.extend(_collect_references(predicates))
    for t_name, c_name in refs:
        _, _, err = _resolve_column(
            t_name, c_name, tables_norm, tables_orig, home_table_norm, measures_norm
        )
        if err:
            continue
        if digits_norm.get(c_name.casefold(), 0) > MAX_DECIMAL_DIGITS:
            out.append(REASON_DECIMAL_DIGITS)
            break
    return out


def _source_kwargs(
    source_kind: str, max_digits: Mapping[str, int] | None
) -> dict[str, Any]:
    """Keyword arguments to hand on to a recursive classify_measure call. Defaults are left
    out so a stand-in for classify_measure with the older signature keeps working."""
    out: dict[str, Any] = {}
    if source_kind != "csv":
        out["source_kind"] = source_kind
    if max_digits:
        out["max_digits"] = max_digits
    return out


def classify_measure(
    expression: str,
    *,
    home_table: str,
    tables: Mapping[str, Mapping[str, str]],
    measures: Mapping[str, str] | None = None,
    source_kind: str = "csv",
    max_digits: Mapping[str, int] | None = None,
    _depth: int = 0,
    _visited: frozenset[str] | None = None,
) -> WhitelistDecision:
    """Classify whether a DAX measure expression is allowed on the store SQL path.

    source_kind is "csv" or "parquet" (anything else refuses). max_digits maps a column
    name to its decimal digit count; an aggregate or predicate on a column with more than
    38 digits refuses. Never raises.
    """
    try:
        return _classify_measure(
            expression,
            home_table=home_table,
            tables=tables,
            measures=measures,
            source_kind=source_kind,
            max_digits=max_digits,
            _depth=_depth,
            _visited=_visited,
        )
    except RecursionError:
        return WhitelistDecision(False, None, None, (REASON_TOO_DEEP,))
    except Exception as exc:  # last guard: the gate must refuse, never raise
        return WhitelistDecision(
            False, None, None, (f"{REASON_UNEXPECTED}: {type(exc).__name__}",)
        )


def _classify_measure(
    expression: str,
    *,
    home_table: str,
    tables: Mapping[str, Mapping[str, str]],
    measures: Mapping[str, str] | None,
    source_kind: str,
    max_digits: Mapping[str, int] | None,
    _depth: int,
    _visited: frozenset[str] | None,
) -> WhitelistDecision:
    if _depth > 32:
        return WhitelistDecision(
            allowed=False,
            table=None,
            shape=None,
            reasons=(REASON_MAX_DEPTH_EXCEEDED,),
        )

    if source_kind not in SOURCE_KINDS:
        return WhitelistDecision(
            False, None, None, (f"unknown source kind '{source_kind}' is not on the store whitelist",)
        )

    digits_norm: dict[str, int] = {}
    for c_name, n_digits in (max_digits or {}).items():
        if not isinstance(n_digits, int) or isinstance(n_digits, bool):
            return WhitelistDecision(
                False, None, None, (f"max_digits for '{c_name}' must be an integer",)
            )
        digits_norm[c_name.casefold()] = max(n_digits, digits_norm.get(c_name.casefold(), 0))

    # Shape caps first: tokenize is iterative, and the parser (recursive) only runs on an expression within the caps
    try:
        cap_reason = _check_shape_caps(tokenize(expression))
    except MeasureError as exc:
        return WhitelistDecision(allowed=False, table=None, shape=None, reasons=(str(exc),))
    if cap_reason:
        return WhitelistDecision(allowed=False, table=None, shape=None, reasons=(cap_reason,))

    try:
        ast = parse_expression(expression)
    except MeasureError as exc:
        return WhitelistDecision(
            allowed=False,
            table=None,
            shape=None,
            reasons=(str(exc),),
        )

    # Normalize tables and measures mapping (refuses names that collide when case-folded)
    tables_norm, tables_orig, measures_norm, collision = _normalize_inputs(tables, measures)
    if collision:
        return WhitelistDecision(False, None, None, (collision,))

    home_table_norm = home_table.casefold()

    visited_set = set(_visited or ())

    reasons: list[str] = []
    referenced_tables: set[str] = set()

    # Outer forms:
    # 1. Bare measure reference: [Measure]
    # 2. CALCULATE([Measure], <predicates>)
    # 3. Base aggregate AGG(T[col])
    # 4. COUNTROWS(T)
    # 5. CALCULATE(<form 3 or 4>, <predicates>)

    kind = ast[0]

    # Arithmetic over totals (Stage C4b): every total is classified by this same function, the combiner is pure
    if is_arithmetic_node(ast):
        return _classify_arith(
            ast, home_table=home_table, tables=tables, measures=measures, source_kind=source_kind,
            max_digits=max_digits, depth=_depth, visited=frozenset(visited_set),
            tables_norm=tables_norm, tables_orig=tables_orig, home_table_norm=home_table_norm,
            measures_norm=measures_norm,
        )

    # Check known node kinds
    if kind not in KNOWN_NODE_KINDS:
        return WhitelistDecision(
            False, None, None, (f"node kind {kind} is not on the store whitelist",)
        )

    # Handle bare reference
    if kind == "reference":
        _, t_name, name = ast
        name_fold = name.casefold()
        if not t_name and name_fold in measures_norm:
            # Cycle detection
            if name_fold in visited_set:
                return WhitelistDecision(
                    False, None, None, (f"cycle detected in measure reference '{name}'",)
                )
            visited_set.add(name_fold)

            # Transitive measure expansion
            sub_expr = measures_norm[name_fold]
            sub_res = classify_measure(
                sub_expr,
                home_table=home_table,
                tables=tables,
                measures=measures,
                **_source_kwargs(source_kind, max_digits),
                _depth=_depth + 1,
                _visited=frozenset(visited_set),
            )
            return sub_res
        elif not t_name:
            reasons.append(f"unknown column or measure '{name}'")
            return WhitelistDecision(False, None, None, tuple(reasons))
        else:
            reasons.append(f"reference to '{t_name}[{name}]' is not a valid measure expression")
            return WhitelistDecision(False, None, None, tuple(reasons))

    # Handle CALCULATE
    if kind == "call" and ast[1] == "CALCULATE":
        args = ast[2]
        if not args:
            reasons.append("CALCULATE requires at least one argument")
            return WhitelistDecision(False, None, None, tuple(reasons))

        first_arg = args[0]
        predicate_args = args[1:]

        # Check if first_arg is an unqualified reference [Name]
        if isinstance(first_arg, tuple) and first_arg[0] == "reference" and not first_arg[1]:
            meas_name = first_arg[2].casefold()
            if meas_name in measures_norm:
                if meas_name in visited_set:
                    return WhitelistDecision(
                        False, None, None, (f"cycle detected in measure reference '{first_arg[2]}'",)
                    )
                visited_set.add(meas_name)

                # Bare measure reference inside CALCULATE
                sub_expr = measures_norm[meas_name]
                sub_res = classify_measure(
                    sub_expr,
                    home_table=home_table,
                    tables=tables,
                    measures=measures,
                    **_source_kwargs(source_kind, max_digits),
                    _depth=_depth + 1,
                    _visited=frozenset(visited_set),
                )
                if not sub_res.allowed:
                    return sub_res
                if sub_res.shape == "ARITH" and predicate_args:
                    return WhitelistDecision(False, None, None, (REASON_ARITH_IN_CALCULATE,))
                # If the referenced measure already has filters (CALCULATE with predicates), refuse nested CALCULATE
                sub_ast = parse_expression(sub_expr)
                if sub_ast[0] == "call" and sub_ast[1] == "CALCULATE" and len(sub_ast[2]) > 1:
                    return WhitelistDecision(False, None, None, (REASON_NESTED_CALCULATE,))
                # An alias hides the same thing: B = [A], A = CALCULATE(..., filters). DAX replaces an inner filter
                # on a column the outer filter also names (the engine keeps only the outer one), so refuse that;
                # filters on different columns are ANDed, which the store does the same way.
                if predicate_args:
                    if _alias_chain_columns(sub_expr, measures_norm) & _filter_columns(tuple(predicate_args)):
                        return WhitelistDecision(False, None, None, (REASON_NESTED_CALCULATE,))

                if not predicate_args:
                    # No extra predicates
                    return sub_res

                # Validate outer predicates
                if sub_res.table:
                    referenced_tables.add(sub_res.table)

                for pred in predicate_args:
                    _check_predicate(
                        pred, tables_norm, tables_orig, home_table_norm, measures_norm, reasons, referenced_tables
                    )
                mix = in_mix_reason(predicate_args, tables, home_table)
                if mix:
                    reasons.append(mix)
                reasons.extend(
                    _source_reasons(
                        None, predicate_args, tables_norm, tables_orig, home_table_norm,
                        measures_norm, source_kind, digits_norm,
                    )
                )

                # Check single table
                if len(referenced_tables) > 1:
                    t_names = sorted(referenced_tables)
                    reasons.append(f"measure references multiple tables: {', '.join(t_names)}")
                elif len(referenced_tables) == 0:
                    reasons.append(REASON_NO_TABLES)

                final_t = next(iter(referenced_tables)) if len(referenced_tables) == 1 else None
                base_shape = sub_res.shape or ""
                shape = base_shape if base_shape.endswith("_filtered") else f"{base_shape}_filtered"
                return WhitelistDecision(
                    allowed=len(reasons) == 0,
                    table=final_t if len(reasons) == 0 else None,
                    shape=shape if len(reasons) == 0 else None,
                    reasons=tuple(reasons),
                )
            else:
                reasons.append(f"unknown column or measure '{first_arg[2]}'")
                return WhitelistDecision(False, None, None, tuple(reasons))

        # First argument is not a measure reference, so it must be form (a) or (b)
        base_decision = _classify_base_aggregate(
            first_arg, tables_norm, tables_orig, home_table_norm, measures_norm
        )
        if not base_decision.allowed:
            reasons.extend(base_decision.reasons)
        else:
            reasons.extend(
                _source_reasons(
                    first_arg, (), tables_norm, tables_orig, home_table_norm,
                    measures_norm, source_kind, digits_norm,
                )
            )
        if base_decision.table:
            referenced_tables.add(base_decision.table)

        if not predicate_args:
            # CALCULATE with no predicates
            if reasons:
                return WhitelistDecision(False, None, None, tuple(reasons))
            return base_decision

        for pred in predicate_args:
            _check_predicate(
                pred, tables_norm, tables_orig, home_table_norm, measures_norm, reasons, referenced_tables
            )
        mix = in_mix_reason(predicate_args, tables, home_table)
        if mix:
            reasons.append(mix)
        reasons.extend(
            _source_reasons(
                None, predicate_args, tables_norm, tables_orig, home_table_norm,
                measures_norm, source_kind, digits_norm,
            )
        )

        if len(referenced_tables) > 1:
            t_names = sorted(referenced_tables)
            reasons.append(f"measure references multiple tables: {', '.join(t_names)}")
        elif len(referenced_tables) == 0:
            reasons.append(REASON_NO_TABLES)

        final_t = next(iter(referenced_tables)) if len(referenced_tables) == 1 else None
        base_shape = base_decision.shape or ""
        shape = f"{base_shape}_filtered" if base_shape else None
        return WhitelistDecision(
            allowed=len(reasons) == 0,
            table=final_t if len(reasons) == 0 else None,
            shape=shape if len(reasons) == 0 else None,
            reasons=tuple(reasons),
        )

    # Base forms (a) or (b) without CALCULATE
    base_decision = _classify_base_aggregate(
        ast, tables_norm, tables_orig, home_table_norm, measures_norm
    )
    if base_decision.allowed:
        src = _source_reasons(
            ast, (), tables_norm, tables_orig, home_table_norm,
            measures_norm, source_kind, digits_norm,
        )
        if src:
            return WhitelistDecision(False, None, None, tuple(src))
    return base_decision


def _leaf_total_kind(
    node: Any,
    tables_norm: dict[str, dict[str, str]],
    tables_orig: dict[str, str],
    home_table_norm: str,
    measures_norm: dict[str, str],
) -> str | None:
    """"int", "double" or "date" for the total an allowed leaf computes (None when it cannot be told).

    COUNT-like totals and a whole-number SUM, MIN or MAX are Int64 ("int"), AVERAGE and a decimal total are Double,
    MIN or MAX of a date column is a date. A leaf is followed through measure references and CALCULATE to its
    base aggregate, as the planner's own flattening does.
    """
    for _ in range(40):
        if not (isinstance(node, tuple) and node):
            return None
        if node[0] == "reference" and not node[1]:
            body = measures_norm.get(str(node[2]).casefold())
            if body is None:
                return None
            node = parse_expression(body)
            continue
        if node[0] == "call" and node[1] == "CALCULATE" and node[2]:
            node = node[2][0]
            continue
        break
    if not (isinstance(node, tuple) and node and node[0] == "call"):
        return None
    fn = node[1]
    if fn in {"COUNTROWS", "COUNT", "COUNTA", "COUNTBLANK", "DISTINCTCOUNT"}:
        return "int"
    if fn == "AVERAGE":
        return "double"
    if fn in {"SUM", "MIN", "MAX"} and node[2] and isinstance(node[2][0], tuple) and node[2][0][0] == "reference":
        _, t_name, col_name = node[2][0]
        _, col_type, err = _resolve_column(t_name, col_name, tables_norm, tables_orig, home_table_norm, measures_norm)
        canonical, type_err = _canonical_type(col_type)
        if err or type_err or canonical is None:
            return None
        return {"whole_number": "int", "decimal_number": "double", "date": "date"}.get(canonical)
    return None


def _classify_arith(
    ast: tuple[Any, ...],
    *,
    home_table: str,
    tables: Mapping[str, Mapping[str, str]],
    measures: Mapping[str, str] | None,
    source_kind: str,
    max_digits: Mapping[str, int] | None,
    depth: int,
    visited: frozenset[str],
    tables_norm: dict[str, dict[str, str]],
    tables_orig: dict[str, str],
    home_table_norm: str,
    measures_norm: dict[str, str],
) -> WhitelistDecision:
    """An arithmetic measure: + - * / unary minus and DIVIDE over totals on one table (shape "ARITH").

    Each distinct total (leaf) goes through this module's own classifier with the same table, measures, source kind and
    digit caps, so every leaf rule, alias-chain rule, IN guard and cap is the one of a measure that is that total alone.
    A leaf that is a date total is refused. The combiner itself (dax_arith) is the engine's own rules, proved by the
    rules tool; nothing here is translated to SQL.
    """
    parsed = parse_arith(ast, measures, visited=visited, chain=depth)
    if not parsed.ok:
        return WhitelistDecision(False, None, None, parsed.reasons)
    reasons: list[str] = []
    found_tables: dict[str, str] = {}
    for leaf in parsed.leaves:
        if isinstance(leaf.node, tuple) and leaf.node and leaf.node[0] in {"call", "reference"}:
            sub = classify_measure(
                leaf.text, home_table=home_table, tables=tables, measures=measures,
                **_source_kwargs(source_kind, max_digits), _depth=depth + 1, _visited=visited,
            )
        else:
            sub = _classify_base_aggregate(leaf.node, tables_norm, tables_orig, home_table_norm, measures_norm)
        if not sub.allowed:
            reasons.extend(sub.reasons or (REASON_ARITH_LEAF,))
            continue
        if sub.shape == "ARITH":
            reasons.append(REASON_ARITH_LEAF)
            continue
        if _leaf_total_kind(leaf.node, tables_norm, tables_orig, home_table_norm, measures_norm) == "date":
            reasons.append(REASON_ARITH_DATE)
            continue
        if sub.table:
            found_tables.setdefault(sub.table.casefold(), sub.table)
    if not reasons and len(found_tables) > 1:
        reasons.append(f"measure references multiple tables: {', '.join(sorted(found_tables.values()))}")
    if not reasons and not found_tables:
        reasons.append(REASON_NO_TABLES)
    reasons = list(dict.fromkeys(reasons))
    if reasons:
        return WhitelistDecision(False, None, None, tuple(reasons))
    return WhitelistDecision(True, next(iter(found_tables.values())), "ARITH", ())


def _classify_base_aggregate(
    node: tuple[Any, ...],
    tables_norm: dict[str, dict[str, str]],
    tables_orig: dict[str, str],
    home_table_norm: str,
    measures_norm: dict[str, str],
) -> WhitelistDecision:
    """Classify form (a) AGG(T[col]) or (b) COUNTROWS(T)."""
    kind = node[0]

    if kind not in KNOWN_NODE_KINDS:
        return WhitelistDecision(
            False, None, None, (f"node kind {kind} is not on the store whitelist",)
        )

    if kind == "let":
        return WhitelistDecision(False, None, None, (REASON_LET,))
    if kind in ("binary", "unary"):
        return WhitelistDecision(False, None, None, (REASON_ARITHMETIC,))

    if kind != "call":
        return WhitelistDecision(
            False, None, None, (f"node kind {kind} is not on the store whitelist",)
        )

    fn = node[1]
    args = node[2]

    # Explicit refusal for DISTINCTCOUNTNOBLANK
    if fn == "DISTINCTCOUNTNOBLANK":
        return WhitelistDecision(False, None, None, (REASON_DISTINCTCOUNTNOBLANK,))

    # COUNTROWS(T)
    if fn == "COUNTROWS":
        if len(args) != 1:
            return WhitelistDecision(False, None, None, ("COUNTROWS requires exactly one argument",))
        arg = args[0]
        if not isinstance(arg, tuple) or arg[0] != "table":
            return WhitelistDecision(False, None, None, ("COUNTROWS argument must be a table",))
        t_name = arg[1]
        t_fold = t_name.casefold()
        if t_fold not in tables_norm:
            return WhitelistDecision(False, None, None, (f"unknown table '{t_name}'",))
        return WhitelistDecision(True, tables_orig[t_fold], "COUNTROWS", ())

    # Aggregates in ALLOWED_AGGREGATES
    if fn in ALLOWED_AGGREGATES:
        if len(args) != 1:
            return WhitelistDecision(False, None, None, (f"{fn} requires exactly one argument",))
        arg = args[0]
        if not isinstance(arg, tuple) or arg[0] != "reference":
            return WhitelistDecision(False, None, None, (f"{fn} argument must be a column reference",))
        _, t_name, col_name = arg
        resolved_t, col_type, err = _resolve_column(
            t_name, col_name, tables_norm, tables_orig, home_table_norm, measures_norm
        )
        if err:
            return WhitelistDecision(False, None, None, (err,))

        col_norm_type, type_err = _canonical_type(col_type)
        if type_err or col_norm_type is None:
            return WhitelistDecision(False, None, None, (type_err or "unknown column type",))
        allowed_types = ALLOWED_AGGREGATES[fn]
        if col_norm_type not in allowed_types:
            if fn == "DISTINCTCOUNT" and col_norm_type in ("whole_number", "decimal_number"):
                return WhitelistDecision(False, None, None, (REASON_DISTINCTCOUNT_NUMERIC,))
            reason = _type_error_reason(fn, col_norm_type)
            return WhitelistDecision(False, None, None, (reason,))

        return WhitelistDecision(True, resolved_t, fn, ())

    # Any other function
    return WhitelistDecision(
        False, None, None, (f"function {fn} is not on the store whitelist",)
    )


def classify_filter_context(
    predicates: Sequence[str],
    *,
    home_table: str,
    tables: Mapping[str, Mapping[str, str]],
    source_kind: str = "csv",
    max_digits: Mapping[str, int] | None = None,
    blocked_columns: Collection[tuple[str, str]] = (),
) -> WhitelistDecision:
    """Classify a filter context: a tuple of DAX predicate STRINGS (the forms CALCULATE admits).

    The context means CALCULATE(<measure base>, <measure predicates>, <these predicates>): all ANDed. Every
    predicate must be on `home_table` (the measure's table). `blocked_columns` are (table, column) pairs
    (case-insensitive) the measure itself filters or groups by: a predicate on one of them is refused
    (REASON_SLICER_SAME_COLUMN). Never raises. An empty tuple is allowed (no filter).
    """
    try:
        return _classify_filter_context(
            predicates, home_table, tables, source_kind, max_digits, blocked_columns
        )
    except RecursionError:
        return WhitelistDecision(False, None, None, (REASON_TOO_DEEP,))
    except Exception as exc:  # last guard: the gate must refuse, never raise
        return WhitelistDecision(False, None, None, (f"{REASON_UNEXPECTED}: {type(exc).__name__}",))


def _classify_filter_context(
    predicates: Sequence[str],
    home_table: str,
    tables: Mapping[str, Mapping[str, str]],
    source_kind: str,
    max_digits: Mapping[str, int] | None,
    blocked_columns: Collection[tuple[str, str]],
) -> WhitelistDecision:
    if source_kind not in SOURCE_KINDS:
        return WhitelistDecision(False, None, None, (f"unknown source kind '{source_kind}' is not on the store whitelist",))
    if isinstance(predicates, str) or not all(isinstance(p, str) for p in predicates):
        return WhitelistDecision(False, None, None, ("a filter context is a tuple of predicate strings",))
    if len(predicates) > MAX_PREDICATES:
        return WhitelistDecision(False, None, None, (REASON_CAP_PREDICATES,))
    tables_norm, tables_orig, measures_norm, collision = _normalize_inputs(tables, None)
    if collision:
        return WhitelistDecision(False, None, None, (collision,))
    home_norm = home_table.casefold()
    if home_norm not in tables_norm:
        return WhitelistDecision(False, None, None, (f"unknown table '{home_table}'",))
    digits_norm: dict[str, int] = {}
    for c_name, n_digits in (max_digits or {}).items():
        if not isinstance(n_digits, int) or isinstance(n_digits, bool):
            return WhitelistDecision(False, None, None, (f"max_digits for '{c_name}' must be an integer",))
        digits_norm[c_name.casefold()] = max(n_digits, digits_norm.get(c_name.casefold(), 0))
    blocked = {(t.casefold(), c.casefold()) for t, c in blocked_columns}
    reasons: list[str] = []
    nodes: list[Any] = []
    referenced: set[str] = set()
    for text in predicates:
        if not text.strip():
            return WhitelistDecision(False, None, None, (REASON_FILTER_CONTEXT_EMPTY,))
        try:
            cap_reason = _check_shape_caps(tokenize(text))
            if cap_reason:
                return WhitelistDecision(False, None, None, (cap_reason,))
            node = parse_expression(text)
        except MeasureError as exc:
            return WhitelistDecision(False, None, None, (str(exc),))
        nodes.append(node)
        _check_predicate(node, tables_norm, tables_orig, home_norm, measures_norm, reasons, referenced)
    for t_name, c_name in _collect_references(tuple(nodes)):
        t_fold = (t_name or "").casefold() or home_norm
        if t_fold != home_norm:
            reasons.append(REASON_FILTER_CONTEXT_OTHER_TABLE)
        elif (t_fold, c_name.casefold()) in blocked:
            reasons.append(REASON_SLICER_SAME_COLUMN)
    if any(t.casefold() != home_norm for t in referenced):
        reasons.append(REASON_FILTER_CONTEXT_OTHER_TABLE)
    reasons.extend(
        _source_reasons(None, tuple(nodes), tables_norm, tables_orig, home_norm, measures_norm, source_kind, digits_norm)
    )
    unique = tuple(dict.fromkeys(reasons))
    return WhitelistDecision(
        allowed=not unique,
        table=tables_orig[home_norm] if not unique else None,
        shape="filter_context" if not unique else None,
        reasons=unique,
    )
