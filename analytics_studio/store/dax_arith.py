"""Arithmetic over the store's totals (Stage C4b): the pure combiner and the parser of an arithmetic measure.

A large table never does arithmetic in SQL. Every total of an arithmetic measure (SUM, COUNTROWS, a filtered
CALCULATE ...) is computed by the planner's own plan, with its own guards and refusals, and the totals are then
combined here by the rules of the in-memory engine. The rules below are the engine's, quoted from
analytics_studio/measures.py (the engine wins where a brief and the engine disagree):

* `_binary_value(operator, left, right)`: blank rules and the Decimal result in `dax_typed.QUIET` (28 digits, half even):
  `+ -`: both blank is blank, `blank - x` is `-x` (`_checked_double(right.copy_negate())`), a lone blank counts as 0;
  `*`: a blank on either side is blank; `/`: a blank left is blank, a blank or zero divisor gives NaN (0/0, sign "-NaN")
  or an Infinity whose sign is `left.is_signed() != divisor.is_signed()`; `_invalid_nan` and `_checked_double` follow.
* `double_operation(node, left, right)` (nested in `evaluate`): when the static type of the node is Double the result is
  `Decimal(float(left) op float(right))`, the exact binary value; an Infinity stays, a result below the smallest
  normal double is `Decimal(f"{value:.15G}")`.
* `typed_zero`: a zero keeps its minus sign only when the static type of the node is Double.
* `_int64_wrap(operator, left, right)`: `+ - *` of two Int64 operands is exact and then wrapped to a signed 64 bit
  integer (`(exact + 2**63) % 2**64 - 2**63`). Only when both operands are present.
* The static type (`_static_numeric_type`, `_arithmetic_result_type`): COUNT-like totals and a whole-number SUM, MIN,
  MAX and an integer literal are Int64, AVERAGE, a decimal total, a literal with a point or an exponent, the result
  of `/` and of DIVIDE are Double. A REFERENCE to a measure has no static type (the engine types a name by its
  columns only): an operator with such an operand is typed "unknown", is computed in exact 28-digit Decimals (no
  double conversion, no Int64 wrap) and drops the sign of a zero. `CALCULATE([measure], filters)` is untyped too.
* Unary minus: `copy_negate` (exact), the Int64 minimum stays as it is, `typed_zero` on the result.
* The value a measure SHOWS is `_bare_result(value)`: a zero of either sign is 0, a NaN of either sign is NaN
  (`bare_result` here). Inside the expression the signs are kept (1 / -0.0 is -Infinity).
* `DIVIDE(a, b, alt)`: a blank numerator is blank (the alternate is not used); a denominator of zero, blank or smaller
  than `_DBL_MIN` gives the alternate (blank when omitted); otherwise the exact Decimal quotient (28 digits, half
  even), an Infinity when its double is infinite.

Types: `Num(kind, value)` with kind "int", "double" or "unknown" and value a Decimal or None (blank). The kind of a blank is the
kind of its total (it decides the type of the next operator, as the engine's static type does).

`parse_arith` turns the parsed AST of an arithmetic measure into a small tree plus the list of distinct leaves (each
leaf is the DAX text of one total, handed to the planner). Brackets are not in the AST; measure references are expanded
inline. Nothing in this module reads a store.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from analytics_studio import dax_typed
from analytics_studio.measures import MeasureError, parse_expression

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
_INT64_RANGE = Decimal(2) ** 63
_DOUBLE_MAX = Decimal("1.7976931348623157E+308")
_UNDERFLOW_DOUBLE = Decimal("2.5E-324")
_DBL_MIN = dax_typed.DBL_MIN
_DBL_MIN_FLOAT = dax_typed.DBL_MIN_FLOAT
_QUIET = dax_typed.QUIET

MAX_ARITH_LEAVES = 8   # distinct totals in one arithmetic measure
MAX_ARITH_NODES = 24   # numbers, totals (each occurrence), operators and DIVIDE calls in the expanded tree
MAX_ARITH_DEPTH = 8    # depth of the expanded tree (a total or a number is depth 1)
MAX_REFERENCE_DEPTH = 32

# Parse-time and execute-time refusals (stable plain sentences; dax_route maps every one)
REASON_ARITH_LEAF = "an operand of the arithmetic is not a total, count or number that large tables can compute"
REASON_ARITH_DATE = "arithmetic on a date total (MIN or MAX of a date column) is not on the store whitelist"
REASON_ARITH_LITERAL = "a number in the arithmetic is beyond the 64-bit whole-number range or the double range"
REASON_ARITH_DIVIDE_ALT = "the third argument of DIVIDE must be a number"
REASON_ARITH_CAP_LEAVES = f"arithmetic over more than {MAX_ARITH_LEAVES} different totals is not on the store whitelist"
REASON_ARITH_CAP_NODES = f"arithmetic with more than {MAX_ARITH_NODES} parts is not on the store whitelist"
REASON_ARITH_CAP_DEPTH = f"arithmetic nested more than {MAX_ARITH_DEPTH} levels deep is not on the store whitelist"
REASON_ARITH_IN_CALCULATE = "CALCULATE over an arithmetic measure is not on the store whitelist"
REASON_ARITH_WHOLE_BEYOND_64 = "a whole-number total is beyond the 64-bit range, which arithmetic on large tables does not handle"
REASON_ARITH_DIVIDE_NON_FINITE = "DIVIDE of a number that is infinite or not a number is not on the store whitelist"
MEASURE_CHAIN_TOO_DEEP = "measure reference chain too deep"  # the same text as dax_whitelist.REASON_MAX_DEPTH_EXCEEDED
REASON_ARITH_OPERATOR = "arithmetic is not on the store whitelist"  # the same text as dax_whitelist.REASON_ARITHMETIC


class ArithUnsupported(Exception):
    """A value the combiner will not answer (a refusal at execute time); `reason` is a stable reason text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Num:
    """One operand: kind "int" (Int64) or "double", value a Decimal or None (blank)."""

    kind: str
    value: Decimal | None


# ----------------------------------------------------------------------------------------------------------
# The combiner (the engine's rules)
# ----------------------------------------------------------------------------------------------------------
def _checked_double(result: Decimal) -> Decimal:
    """measures._checked_double: beyond the double range is an Infinity, below it a zero of the same sign."""
    if not result.is_finite():
        return result
    if abs(result) < _UNDERFLOW_DOUBLE:
        return Decimal("-0") if result.is_signed() else Decimal(0)
    if abs(result) > _DOUBLE_MAX:
        return Decimal("Infinity") if result > 0 else Decimal("-Infinity")
    return result


def _invalid_nan(result: Decimal, left: Decimal, right: Decimal) -> Decimal:
    """measures._invalid_nan: an invalid operation is the negative NaN; a NaN operand keeps its own sign."""
    if result.is_nan() and not (left.is_nan() or right.is_nan()):
        return Decimal("-NaN")
    return result


def _binary_value(operator: str, left: Decimal | None, right: Decimal | None) -> Decimal | None:
    """measures._binary_value: + - * / with the blank and IEEE rules, in the 28-digit quiet context."""
    quiet = _QUIET
    if operator in {"+", "-"}:
        if left is None and right is None:
            return None
        if left is None and operator == "-":
            assert right is not None
            return _checked_double(right.copy_negate())
        left_value = Decimal(0) if left is None else left
        right_value = Decimal(0) if right is None else right
        result = quiet.add(left_value, right_value) if operator == "+" else quiet.subtract(left_value, right_value)
        return _checked_double(_invalid_nan(result, left_value, right_value))
    if left is None:
        return None
    if operator == "*":
        return None if right is None else _checked_double(_invalid_nan(quiet.multiply(left, right), left, right))
    divisor = Decimal(0) if right is None else right
    if divisor == 0:
        if left.is_nan():
            return left
        if left == 0:
            return Decimal("-NaN")
        return Decimal("-Infinity") if left.is_signed() != divisor.is_signed() else Decimal("Infinity")
    return _checked_double(_invalid_nan(quiet.divide(left, divisor), left, divisor))


def _double_operation(operator: str, left: Decimal, right: Decimal) -> Decimal | None:
    """The body of the engine's double_operation for a node whose static type is Double (None: keep the Decimal result)."""
    if operator == "/" and right == 0:
        return None
    a, b = float(left), float(right)
    if operator == "+":
        value = a + b
    elif operator == "-":
        value = a - b
    elif operator == "*":
        value = a * b
    else:
        value = a / b
    if value != value:  # NaN
        return None
    if value in (float("inf"), float("-inf")):
        return Decimal("Infinity") if value > 0 else Decimal("-Infinity")
    if 0 < abs(value) < _DBL_MIN_FLOAT:
        return Decimal(f"{value:.15G}")
    return Decimal(value)


def _typed_zero(value: Decimal, kind: str) -> Decimal:
    """measures typed_zero: a zero keeps its minus sign only when the static type is Double."""
    if value.is_zero() and value.is_signed() and kind != "double":
        return Decimal(0)
    return value


def _int64_wrap(operator: str, left: Decimal, right: Decimal) -> Decimal:
    """measures._int64_wrap: + - * of two Int64 values, exact and then wrapped to a signed 64 bit integer."""
    if left != left.to_integral_value() or right != right.to_integral_value():
        return _binary_value(operator, left, right) or Decimal(0)
    a, b = int(left), int(right)
    exact = a + b if operator == "+" else a - b if operator == "-" else a * b
    return Decimal((exact + 2**63) % 2**64 - 2**63)


_KNOWN_KINDS = frozenset({"int", "double"})


def _result_kind(op: str, left: str, right: str) -> str:
    """The static type of `left op right` (measures._arithmetic_result_type); an untyped operand makes it "unknown"."""
    if left not in _KNOWN_KINDS or right not in _KNOWN_KINDS:
        return "unknown"
    if op == "/":
        return "double"
    return "int" if left == "int" and right == "int" else "double"


def combine(op: str, left: Num, right: Num) -> Num:
    """`left op right` for + - * / by the engine's rules (see the module docstring)."""
    if op not in {"+", "-", "*", "/"}:
        raise ValueError(f"unknown operator {op!r}")
    kind = _result_kind(op, left.kind, right.kind)
    l_value, r_value = left.value, right.value
    result = _binary_value(op, l_value, r_value)
    if (
        kind == "double" and l_value is not None and r_value is not None and result is not None and result.is_finite()
    ):
        doubled = _double_operation(op, l_value, r_value)
        if doubled is not None:
            result = doubled
    if result is not None:
        result = _typed_zero(result, kind)
    if (
        op in {"+", "-", "*"} and kind == "int" and l_value is not None and r_value is not None
        and result is not None and result.is_finite()
    ):
        result = _int64_wrap(op, l_value, r_value)
    return Num(kind, result)


def negate(operand: Num) -> Num:
    """Unary minus: exact, the Int64 minimum stays as it is, a zero loses its sign unless the type is Double."""
    value = operand.value
    if value is None:
        return operand
    if operand.kind == "int" and value == -_INT64_RANGE:
        return operand
    return Num(operand.kind, _typed_zero(value.copy_negate(), operand.kind))


def divide(numerator: Num, denominator: Num, alternate: Num | None = None) -> Num:
    """DIVIDE(a, b, alt): the exact quotient in 28 digits; blank numerator is blank; zero or blank denominator the alternate."""
    top, bottom = numerator.value, denominator.value
    kind = _result_kind("/", numerator.kind, denominator.kind)  # the static type of DIVIDE is that of the quotient
    if top is None:
        return Num(kind, None)
    if not top.is_finite() or (bottom is not None and not bottom.is_finite()):
        raise ArithUnsupported(REASON_ARITH_DIVIDE_NON_FINITE)
    if bottom is None or bottom == 0 or 0 < abs(bottom) < _DBL_MIN:
        return Num(kind, None if alternate is None else alternate.value)
    quotient = _QUIET.divide(top, bottom)
    if quotient.is_finite() and float(quotient) in (float("inf"), float("-inf")):
        quotient = Decimal("Infinity") if quotient > 0 else Decimal("-Infinity")
    return Num(kind, quotient)


# Tree nodes: ("leaf", index) ("num", Num) ("neg", node) ("bin", op, left, right) ("divide", a, b, Num | None)
# and ("ref", node): the value of an expanded measure reference, typed "unknown"
ArithTree = tuple[Any, ...]


def evaluate(tree: ArithTree, leaf_values: Sequence[Num]) -> Num:
    """The value of a parsed tree for the given leaf values (index in `leaf_values` = leaf index)."""
    kind = tree[0]
    if kind == "leaf":
        return leaf_values[tree[1]]
    if kind == "num":
        return tree[1]
    if kind == "ref":  # a measure reference: its value, but the engine gives a name no static type
        return Num("unknown", evaluate(tree[1], leaf_values).value)
    if kind == "neg":
        return negate(evaluate(tree[1], leaf_values))
    if kind == "bin":
        return combine(tree[1], evaluate(tree[2], leaf_values), evaluate(tree[3], leaf_values))
    if kind == "divide":
        return divide(evaluate(tree[1], leaf_values), evaluate(tree[2], leaf_values), tree[3])
    raise ValueError(f"unknown tree node {kind!r}")


def bare_result(value: Decimal | None) -> Decimal | None:
    """measures._bare_result: the value a measure shows. A zero of either sign is 0 and a NaN of either sign is NaN."""
    if value is None:
        return None
    if value.is_nan():
        return Decimal("NaN")
    return Decimal(0) if value.is_zero() else value


def leaf_value_in_range(num: Num) -> bool:
    """A whole-number (Int64) total must lie in the signed 64 bit range for the combiner to be the engine's."""
    if num.kind != "int" or num.value is None:
        return True
    return num.value == num.value.to_integral_value() and INT64_MIN <= num.value <= INT64_MAX


# ----------------------------------------------------------------------------------------------------------
# The parser of an arithmetic measure
# ----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ArithLeaf:
    """One distinct total of an arithmetic measure: its DAX text and its AST node."""

    text: str
    node: tuple[Any, ...]
    unknown: bool = False  # CALCULATE([measure], ...): the engine gives it no static type


@dataclass(frozen=True)
class ArithParse:
    """The result of parse_arith: a tree and its leaves, or refusal reasons (no tree)."""

    tree: ArithTree | None
    leaves: tuple[ArithLeaf, ...] = ()
    reasons: tuple[str, ...] = ()
    nodes: int = 0
    depth: int = 0

    @property
    def ok(self) -> bool:
        return self.tree is not None


class _NoText(Exception):
    """A node the leaf writer does not know."""


_SIMPLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ATOMS = frozenset({"reference", "number", "string", "boolean", "blank", "table", "call"})


def quote_table(name: str) -> str:
    """A table name as DAX text (quoted unless it is a plain identifier)."""
    return name if _SIMPLE_NAME.match(name) else "'" + name.replace("'", "''") + "'"


def _wrapped(node: Any) -> str:
    text = _unparse(node)
    return text if isinstance(node, tuple) and node and node[0] in _ATOMS else f"({text})"


def _unparse(node: Any) -> str:
    """DAX text of an AST node. parse_expression of the text must give the node back (checked by the caller)."""
    if not isinstance(node, tuple) or not node:
        raise _NoText()
    kind = node[0]
    if kind == "number":
        return node[2] if len(node) > 2 and isinstance(node[2], str) else str(node[1])
    if kind == "string":
        return '"' + str(node[1]).replace('"', '""') + '"'
    if kind == "boolean":
        return "TRUE()" if node[1] else "FALSE()"
    if kind == "blank" and len(node) == 1:
        return "BLANK()"
    if kind == "reference":
        column = "[" + str(node[2]).replace("]", "]]") + "]"
        return (quote_table(str(node[1])) if node[1] else "") + column
    if kind == "table":
        return quote_table(str(node[1]))
    if kind == "call":
        return f"{node[1]}(" + ", ".join(_unparse(argument) for argument in node[2]) + ")"
    if kind in {"comparison", "logical", "binary"}:
        return f"{_wrapped(node[2])} {node[1]} {_wrapped(node[3])}"
    if kind == "unary":
        return f"{node[1]}{_wrapped(node[2])}"
    if kind == "in" and len(node) == 3:
        return f"{_wrapped(node[1])} IN {_unparse(node[2])}"
    if kind == "tableconstructor":
        return "{" + ", ".join(_unparse(item) for item in node[1]) + "}"
    raise _NoText()


def leaf_text(node: tuple[Any, ...]) -> str | None:
    """DAX text for a leaf node, or None when it cannot be written so that it parses back to the same node."""
    try:
        text = _unparse(node)
        return text if parse_expression(text) == node else None
    except (_NoText, MeasureError, RecursionError, ValueError, TypeError):
        return None


def _literal(node: tuple[Any, ...]) -> Num | str:
    """A number literal as a Num, or a refusal reason."""
    text = node[2] if len(node) > 2 and isinstance(node[2], str) else str(node[1])
    value = node[1]
    if not isinstance(value, Decimal) or not value.is_finite():
        return REASON_ARITH_LITERAL
    if "." in text or "e" in text.lower():
        return Num("double", value) if abs(value) <= _DOUBLE_MAX else REASON_ARITH_LITERAL
    try:
        whole = int(text)
    except ValueError:
        return REASON_ARITH_LITERAL
    if not INT64_MIN <= whole <= INT64_MAX:
        return REASON_ARITH_LITERAL
    return Num("int", Decimal(whole))


class _Stop(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Walker:
    def __init__(self, measures: Mapping[str, str]) -> None:
        self.measures = measures
        self.leaves: list[ArithLeaf] = []
        self.index: dict[str, int] = {}
        self.nodes = 0
        self.max_depth = 0

    def count(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_ARITH_NODES:
            raise _Stop(REASON_ARITH_CAP_NODES)

    def walk(self, node: Any, depth: int, path: frozenset[str], chain: int) -> ArithTree:
        if depth > MAX_ARITH_DEPTH:
            raise _Stop(REASON_ARITH_CAP_DEPTH)
        self.max_depth = max(self.max_depth, depth)
        if not isinstance(node, tuple) or not node:
            raise _Stop(REASON_ARITH_LEAF)
        kind = node[0]
        if kind == "binary":
            if node[1] not in {"+", "-", "*", "/"}:
                raise _Stop(REASON_ARITH_OPERATOR)
            self.count()
            left = self.walk(node[2], depth + 1, path, chain)
            right = self.walk(node[3], depth + 1, path, chain)
            return ("bin", node[1], left, right)
        if kind == "unary":
            if node[1] != "-":
                raise _Stop(REASON_ARITH_OPERATOR)
            self.count()
            return ("neg", self.walk(node[2], depth + 1, path, chain))
        if kind == "number":
            literal = _literal(node)
            if isinstance(literal, str):
                raise _Stop(literal)
            self.count()
            return ("num", literal)
        if kind == "call" and node[1] == "DIVIDE":
            arguments = node[2]
            if len(arguments) not in (2, 3):
                raise _Stop("DIVIDE needs a numerator, denominator, and optional alternate result.")
            self.count()
            alternate: Num | None = None
            if len(arguments) == 3:
                alternate = self.alternate(arguments[2])
                self.count()
            top = self.walk(arguments[0], depth + 1, path, chain)
            bottom = self.walk(arguments[1], depth + 1, path, chain)
            return ("divide", top, bottom, alternate)
        if kind == "reference" and not node[1]:
            name = str(node[2])
            folded = name.casefold()
            body = self.measures.get(folded)
            if body is None:
                raise _Stop(f"unknown column or measure '{name}'")
            if folded in path:
                raise _Stop(f"cycle detected in measure reference '{name}'")
            if chain + 1 > MAX_REFERENCE_DEPTH:
                raise _Stop(MEASURE_CHAIN_TOO_DEEP)
            try:
                inner = parse_expression(body)
            except MeasureError as exc:
                raise _Stop(str(exc)) from exc
            expanded = self.walk(inner, depth, path | {folded}, chain + 1)
            return expanded if expanded[0] == "ref" else ("ref", expanded)
        return self.leaf(node, depth, path, chain)

    def alternate(self, node: Any) -> Num:
        sign = False
        if isinstance(node, tuple) and node and node[0] == "unary" and node[1] == "-":
            sign, node = True, node[2]
        if not (isinstance(node, tuple) and node and node[0] == "number"):
            raise _Stop(REASON_ARITH_DIVIDE_ALT)
        literal = _literal(node)
        if isinstance(literal, str):
            raise _Stop(literal)
        return negate(literal) if sign else literal

    def leaf(self, node: tuple[Any, ...], depth: int = 1, path: frozenset[str] = frozenset(), chain: int = 0) -> ArithTree:
        if node[0] == "call" and node[1] == "CALCULATE" and node[2]:
            first = node[2][0]
            if len(node[2]) == 1 and isinstance(first, tuple) and first and first[0] == "reference" and not first[1]:
                return self.walk(first, depth, path, chain)  # CALCULATE([M]) with no filter is [M]
            if isinstance(first, tuple) and first and first[0] == "reference" and not first[1]:
                target = self.measures.get(str(first[2]).casefold())
                if target is not None and len(node[2]) > 1:
                    # CALCULATE([measure], filters): an arithmetic measure inside is refused here; any other is a leaf
                    try:
                        inner = parse_expression(target)
                    except MeasureError:
                        inner = None
                    if isinstance(inner, tuple) and inner and self._is_arithmetic(inner, frozenset(), 0):
                        raise _Stop(REASON_ARITH_IN_CALCULATE)
        text = leaf_text(node)
        if text is None:
            raise _Stop(_unwritable_reason(node))
        self.count()
        position = self.index.get(text)
        if position is None:
            if len(self.leaves) >= MAX_ARITH_LEAVES:
                raise _Stop(REASON_ARITH_CAP_LEAVES)
            position = len(self.leaves)
            self.index[text] = position
            self.leaves.append(ArithLeaf(text, node, _calculates_a_measure(node)))
        return ("leaf", position)

    def _is_arithmetic(self, node: Any, seen: frozenset[str], depth: int) -> bool:
        """Does this expression, followed through bare measure references, start with arithmetic?"""
        if depth > MAX_REFERENCE_DEPTH or not isinstance(node, tuple) or not node:
            return False
        if node[0] in {"binary", "unary"}:
            return True
        if node[0] == "call" and node[1] == "DIVIDE":
            return True
        target = None
        if node[0] == "reference" and not node[1]:
            target = str(node[2]).casefold()
        elif node[0] == "call" and node[1] == "CALCULATE" and len(node[2]) == 1:
            first = node[2][0]
            if isinstance(first, tuple) and first and first[0] == "reference" and not first[1]:
                target = str(first[2]).casefold()
        if target is None or target in seen or target not in self.measures:
            return False
        try:
            return self._is_arithmetic(parse_expression(self.measures[target]), seen | {target}, depth + 1)
        except MeasureError:
            return False


def _calculates_a_measure(node: tuple[Any, ...]) -> bool:
    """CALCULATE whose first argument is a measure reference: the static type of CALCULATE is that of its first argument."""
    if node[0] == "call" and node[1] == "CALCULATE" and node[2]:
        first = node[2][0]
        return isinstance(first, tuple) and bool(first) and first[0] == "reference" and not first[1]
    return False


def _unwritable_reason(node: tuple[Any, ...]) -> str:
    """The reason for a leaf that cannot be written back as DAX text: its own function name when it has one."""
    if node[0] == "call" and node[1] not in {"CALCULATE"}:
        return f"function {node[1]} is not on the store whitelist"
    return REASON_ARITH_LEAF


def is_arithmetic_node(node: Any) -> bool:
    """A top-level + - * / or unary minus, or DIVIDE: the shapes parse_arith takes."""
    return isinstance(node, tuple) and bool(node) and (
        node[0] in {"binary", "unary"} or (node[0] == "call" and node[1] == "DIVIDE")
    )


def parse_arith(
    ast: tuple[Any, ...],
    measures: Mapping[str, str] | None = None,
    *,
    visited: frozenset[str] = frozenset(),
    chain: int = 0,
) -> ArithParse:
    """Parse the AST of an arithmetic measure: a tree plus its distinct leaves, or the refusal reasons.

    `measures` maps a measure name (any case) to its DAX text; a measure reference is expanded inline (unknown names
    and cycles keep the whitelist's own reason texts). Caps: MAX_ARITH_LEAVES distinct leaves, MAX_ARITH_NODES nodes,
    MAX_ARITH_DEPTH levels; the first cap crossed in a left to right walk is the reason. Never raises.
    `visited` (case-folded measure names already being expanded by the caller) and `chain` (how many references deep
    the caller is) continue the cycle and depth checks of an outer expansion.
    """
    folded = {str(name).casefold(): body for name, body in (measures or {}).items()}
    walker = _Walker(folded)
    try:
        tree = walker.walk(ast, 1, frozenset(visited), chain)
    except _Stop as stop:
        return ArithParse(None, (), (stop.reason,))
    except RecursionError:
        return ArithParse(None, (), (REASON_ARITH_CAP_DEPTH,))
    return ArithParse(tree, tuple(walker.leaves), (), walker.nodes, walker.max_depth)
