"""DAX whitelist classifier for the store SQL path (Stage C1a).

Decides, for one measure expression, whether the store SQL path may evaluate it.
Default answer is REFUSE.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from analytics_studio.measures import MeasureError, parse_expression

# Admitted aggregate functions and the column types they support on store mapped path
ALLOWED_AGGREGATES: dict[str, frozenset[str]] = {
    "SUM": frozenset({"whole_number", "decimal_number", "whole", "decimal", "fixed"}),
    "AVERAGE": frozenset({"whole_number", "decimal_number", "whole", "decimal", "fixed"}),
    "MIN": frozenset({"whole_number", "decimal_number", "date", "datetime", "whole", "decimal", "fixed"}),
    "MAX": frozenset({"whole_number", "decimal_number", "date", "datetime", "whole", "decimal", "fixed"}),
    "COUNT": frozenset({"whole_number", "decimal_number", "date", "datetime", "whole", "decimal", "fixed"}),
    "COUNTA": frozenset({"whole_number", "decimal_number", "date", "datetime", "text", "boolean", "whole", "decimal", "fixed"}),
    "COUNTBLANK": frozenset({"whole_number", "decimal_number", "date", "datetime", "text", "boolean", "whole", "decimal", "fixed"}),
    "DISTINCTCOUNT": frozenset({"whole_number", "decimal_number", "date", "datetime", "text", "boolean", "whole", "decimal", "fixed"}),
}

# Comparison operators admitted in predicates
ALLOWED_PREDICATE_OPS: set[str] = {"=", "<>", "<", "<=", ">", ">="}

# Known node kinds that can be evaluated or refused
KNOWN_NODE_KINDS: set[str] = {
    "call", "reference", "table", "comparison", "logical", "in", "number",
    "string", "boolean", "blank", "binary", "unary", "let", "var", "strict_equal",
}

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


@dataclass(frozen=True)
class WhitelistDecision:
    """Decision on whether a measure expression is allowed on the store SQL path."""
    allowed: bool
    table: str | None
    shape: str | None
    reasons: tuple[str, ...]


def _canonical_type(raw_type: str | None) -> str:
    """Normalize store / model type string."""
    if not raw_type:
        return "text"
    t = raw_type.casefold()
    if t in ("whole", "whole_number", "int64", "integer"):
        return "whole_number"
    if t in ("decimal", "decimal_number", "fixed", "fixed_decimal", "currency", "double", "float"):
        return "decimal_number"
    if t in ("date", "datetime"):
        return "date"
    if t in ("boolean", "bool"):
        return "boolean"
    return "text"


def _type_error_reason(agg: str, col_type: str) -> str:
    """Return refusal reason wording mirroring the rules tool."""
    c_norm = _canonical_type(col_type)
    return f"{agg} not supported on {c_norm} column"


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

    # NOT(...) call
    if kind == "call" and node[1] == "NOT":
        args = node[2]
        if len(args) != 1:
            reasons.append("call NOT requires exactly one argument")
            return
        _check_predicate(
            args[0], tables_norm, tables_orig, home_table_norm, measures_norm, reasons, referenced_tables
        )
        return

    # || logical OR
    if kind == "logical" and node[1] == "||":
        _check_predicate(
            node[2], tables_norm, tables_orig, home_table_norm, measures_norm, reasons, referenced_tables
        )
        _check_predicate(
            node[3], tables_norm, tables_orig, home_table_norm, measures_norm, reasons, referenced_tables
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

        col_norm_type = _canonical_type(col_type)
        if col_norm_type != "text":
            reasons.append(f"IN filter not supported on {col_norm_type} column")
            return

        if not isinstance(table_ctor, tuple) or table_ctor[0] != "tableconstructor":
            reasons.append("right side of IN must be a table constructor of string literals")
            return

        items = table_ctor[1]
        for item in items:
            if not isinstance(item, tuple) or item[0] != "string":
                reasons.append("IN values must be string literals")
                break
        return

    # Comparison predicate
    if kind == "comparison":
        op, left, right = node[1], node[2], node[3]
        if op not in ALLOWED_PREDICATE_OPS:
            reasons.append(f"operator {op} is not on the store whitelist")
            return

        # Check column reference and literal sides
        left_is_ref = isinstance(left, tuple) and left[0] == "reference"
        right_is_ref = isinstance(right, tuple) and right[0] == "reference"

        if left_is_ref and right_is_ref:
            reasons.append(REASON_TWO_COLUMNS)
            return
        if not left_is_ref and not right_is_ref:
            reasons.append("comparison must involve a column reference")
            return

        ref_node = left if left_is_ref else right
        lit_node = right if left_is_ref else left

        _, t_name, col_name = ref_node
        resolved_t, col_type, err = _resolve_column(
            t_name, col_name, tables_norm, tables_orig, home_table_norm, measures_norm
        )
        if err:
            reasons.append(err)
            return
        if resolved_t:
            referenced_tables.add(resolved_t)

        col_norm_type = _canonical_type(col_type)
        lit_type, lit_err = _check_literal_type(lit_node)
        if lit_err:
            reasons.append(lit_err)
            return

        if col_norm_type in ("whole_number", "decimal_number"):
            if lit_type != "number":
                reasons.append(f"literal type {lit_type} does not fit {col_norm_type} column")
        elif col_norm_type == "text":
            if lit_type != "string":
                reasons.append(f"literal type {lit_type} does not fit text column")
        elif col_norm_type == "date":
            if lit_type != "date":
                reasons.append(f"literal type {lit_type} does not fit date column")
        elif col_norm_type == "boolean":
            reasons.append("boolean column comparison not supported on store")
        return

    if kind == "call":
        reasons.append(f"function {node[1]} is not on the store whitelist")
        return

    reasons.append(f"node kind {kind} is not on the store whitelist")


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
        args = node[2]
        if len(args) != 3:
            return None, "DATE function must have 3 arguments"
        for a in args:
            if not isinstance(a, tuple):
                return None, "DATE arguments must be numeric literals"
            if a[0] == "number":
                continue
            if a[0] == "unary" and a[1] == "-" and isinstance(a[2], tuple) and a[2][0] == "number":
                continue
            return None, "DATE arguments must be numeric literals"
        return "date", None
    if kind == "blank":
        return None, REASON_BLANK_COMPARISON
    if kind == "boolean":
        return None, REASON_BOOLEAN_LITERAL
    return None, f"node kind {kind} is not a valid literal"


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
    # Check if it is a measure name first
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


def classify_measure(
    expression: str,
    *,
    home_table: str,
    tables: Mapping[str, Mapping[str, str]],
    measures: Mapping[str, str] | None = None,
    _depth: int = 0,
    _visited: frozenset[str] | None = None,
) -> WhitelistDecision:
    """Classify whether a DAX measure expression is allowed on the store SQL path."""
    if _depth > 32:
        return WhitelistDecision(
            allowed=False,
            table=None,
            shape=None,
            reasons=(REASON_MAX_DEPTH_EXCEEDED,),
        )

    try:
        ast = parse_expression(expression)
    except MeasureError as exc:
        return WhitelistDecision(
            allowed=False,
            table=None,
            shape=None,
            reasons=(str(exc),),
        )

    # Normalize tables mapping
    tables_norm: dict[str, dict[str, str]] = {}
    tables_orig: dict[str, str] = {}
    for t_name, cols in tables.items():
        t_fold = t_name.casefold()
        tables_orig[t_fold] = t_name
        tables_norm[t_fold] = {c_name.casefold(): c_type for c_name, c_type in cols.items()}

    home_table_norm = home_table.casefold()
    measures_norm: dict[str, str] = (
        {m_name.casefold(): expr for m_name, expr in measures.items()} if measures else {}
    )

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
                    _depth=_depth + 1,
                    _visited=frozenset(visited_set),
                )
                if not sub_res.allowed:
                    return sub_res
                # If the referenced measure already has filters (CALCULATE with predicates), refuse nested CALCULATE
                sub_ast = parse_expression(sub_expr)
                if sub_ast[0] == "call" and sub_ast[1] == "CALCULATE" and len(sub_ast[2]) > 1:
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
        if base_decision.table:
            referenced_tables.add(base_decision.table)

        if not predicate_args:
            # CALCULATE with no predicates
            return base_decision

        for pred in predicate_args:
            _check_predicate(
                pred, tables_norm, tables_orig, home_table_norm, measures_norm, reasons, referenced_tables
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
    return base_decision


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

        col_norm_type = _canonical_type(col_type)
        allowed_types = ALLOWED_AGGREGATES[fn]
        if col_norm_type not in allowed_types:
            reason = _type_error_reason(fn, col_norm_type)
            return WhitelistDecision(False, None, None, (reason,))

        return WhitelistDecision(True, resolved_t, fn, ())

    # Any other function
    return WhitelistDecision(
        False, None, None, (f"function {fn} is not on the store whitelist",)
    )
