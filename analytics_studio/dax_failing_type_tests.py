"""Task 235: a type test (ISNUMBER, ISTEXT, ISLOGICAL, ...) of an expression that fails when it is evaluated, decided by the static type.

Power BI decides ISxxx(<expression>) from the static type of the expression when the answer does not depend on the value it would have at
run time.  The evaluation error of a part that is only reached lazily then never shows.  This module holds that rule and only the shapes
that the saved Power BI answers support (tools/parity/dax_battery_*.json: 539 answers that the local engine refused before, 13,936
expressions Power BI answers with an error, and 68,496 other type tests that Power BI answers).  Every other shape keeps its refusal.

THE RULE TABLE (static type T of the argument, can it be BLANK):

    answer is the same for a BLANK and for a value  ->  answered from T alone, the failing part is never evaluated
    answer differs for a BLANK and for a value      ->  Power BI evaluates the value and raises the failure: refused here

    T (static type)     ISNUMBER            ISNUMERIC        ISTEXT/ISSTRING  ISLOGICAL/ISBOOLEAN  ISNONTEXT
    int64               True if never BLANK  same             False            False                True
    double / currency   True if never BLANK  same             False            False                True
    datetime            True if never BLANK  False (no match) False            False                True
    text                False               False            True if never BLANK  False            False if never BLANK
    bool                False               False            False            True if never BLANK  True
    (ISINTEGER / ISINT64 / ISDOUBLE / ISDECIMAL / ISCURRENCY / ISDATETIME are True only for their own T, and then only if never BLANK;
    every other T answers False.  "True if never BLANK" means: when the expression can be BLANK the answer is refused.)

    "Never BLANK" is analytics_studio.measures._never_blank (a number / text / True-False literal, a comparison or logical operator, a sum
    with one never-BLANK side, a product with two, a concatenation with one, ...).  A VAR is not followed, so a bare VAR that holds a
    failing value is never "never BLANK".  The static type T is analytics_studio.measures._static_numeric_type.

THE HIDING GRAMMAR (what may stand inside the argument for the failure not to show):

    lazy parts, hidden wherever they stand      text beside + - * (the failing text conversion), ^ of any operands, INT ABS ROUND TRUNC SIGN EXP
                                                POWER MOD FACT CEILING CURRENCY CONVERT of a failing value, UPPER, CONCATENATE
    folded parts, hidden only when a VAR holds them or they are a SWITCH result
                                                VALUE DATEVALUE TIMEVALUE DATE TIME EDATE WEEKDAY SQRT LN DIVIDE of a failing value
    shapes that Power BI raised for in the saved answers, so they are never answered
                                                a division / DIVIDE of a failing value anywhere in the argument, a folded part outside a VAR or a
                                                SWITCH result, a column read outside an aggregate, SELECTEDVALUE, LOG, LOG10, ERROR, FORMAT,
                                                LEFT, SIN, iterators, comparison operators outside an IF / SWITCH condition, IFERROR,
                                                SUM of a text column
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

TYPE_TESTS = frozenset({
    "ISNUMBER", "ISNUMERIC", "ISTEXT", "ISSTRING", "ISNONTEXT", "ISLOGICAL", "ISBOOLEAN", "ISINTEGER", "ISINT64", "ISDOUBLE", "ISDECIMAL",
    "ISCURRENCY", "ISDATETIME",
})
_STATIC_TYPES = frozenset({"int64", "double", "currency", "decimal", "text", "bool", "datetime"})
_MATCHING_TYPES: dict[str, frozenset[str]] = {  # the static types a type test answers True for
    "ISNUMBER": frozenset({"int64", "double", "currency", "decimal", "datetime"}),
    "ISNUMERIC": frozenset({"int64", "double", "currency", "decimal"}),
    "ISTEXT": frozenset({"text"}), "ISSTRING": frozenset({"text"}),
    "ISLOGICAL": frozenset({"bool"}), "ISBOOLEAN": frozenset({"bool"}),
    "ISINTEGER": frozenset({"int64"}), "ISINT64": frozenset({"int64"}),
    "ISDOUBLE": frozenset({"double"}),
    "ISDATETIME": frozenset({"datetime"}),
    "ISDECIMAL": frozenset({"currency", "decimal"}), "ISCURRENCY": frozenset({"currency", "decimal"}),
}
_ARITHMETIC = frozenset({"+", "-", "*", "^"})  # "/" is never hidden: Power BI raised for every division of a failing value in the saved answers
_LAZY_CALLS = frozenset({"INT", "ABS", "ROUND", "TRUNC", "SIGN", "EXP", "POWER", "MOD", "FACT", "CEILING", "CURRENCY", "CONVERT", "UPPER", "CONCATENATE"})
_FOLDED_CALLS = frozenset({"VALUE", "DATEVALUE", "TIMEVALUE", "DATE", "TIME", "EDATE", "WEEKDAY", "SQRT", "LN", "DIVIDE"})
_AGGREGATES = frozenset({"MAX", "MIN", "SUM"})
_LITERALS = frozenset({"number", "string", "boolean", "blank", "blank_comment", "var"})
_CONVERT_KEYWORDS = frozenset({"INTEGER", "INT64", "DOUBLE", "CURRENCY", "DECIMAL", "BOOLEAN", "STRING", "DATETIME"})
_NUMERIC = frozenset({"int64", "double", "currency", "decimal"})
_OVERFLOW_FAILURE = "The result of a conversion or arithmetic operation is either too large or too small."
_ANSWERABLE_FAILURES = ("Cannot convert value", "An argument of function", "A type test of a failing value", "A type test of arithmetic around a failing power", _OVERFLOW_FAILURE)
_TEXT_DIVIDE_TESTS = frozenset({"ISINTEGER", "ISINT64", "ISNONTEXT", "ISBOOLEAN", "ISLOGICAL", "ISDATETIME", "ISDECIMAL", "ISCURRENCY", "ISTEXT", "ISSTRING"})


def _column_type(node: Any, columns: dict[str, dict[str, str]]) -> str | None:
    """The type of a column read of a loaded table, None when the table or the column is not known."""
    table = str(node[1] or "").casefold()
    column = str(node[2]).casefold()
    if not table:
        return None
    return columns.get(table, {}).get(column) or None


def _numeric_column(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    kind = (_column_type(node, columns) or "").casefold()
    return kind in {"whole_number", "integer", "int64", "int", "decimal_number", "double", "float", "number", "currency", "fixed_decimal", "decimal"}


def _aggregate(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """MAX / MIN of a column, SUM of a numeric column (SUM of text raises in Power BI)."""
    if not (node[0] == "call" and str(node[1]).upper() in _AGGREGATES and len(node[2]) == 1):
        return False
    argument = node[2][0]
    if not (isinstance(argument, tuple) and argument and argument[0] == "reference" and _column_type(argument, columns) is not None):
        return False
    return str(node[1]).upper() != "SUM" or _numeric_column(argument, columns)


def _literal_number(node: Any) -> bool:
    return isinstance(node, tuple) and bool(node) and (node[0] == "number" or (node[0] == "unary" and node[1] in {"+", "-"} and _literal_number(node[2])))


def _benign_call(node: Any) -> bool:
    """A folded call that cannot fail: DATE / TIME of whole-number literals in an ordinary range, DIVIDE of number / BLANK literals."""
    name = str(node[1]).upper()
    arguments = node[2]
    if name in {"DATE", "TIME"}:
        if len(arguments) != 3 or not all(argument[0] == "number" for argument in arguments):
            return False
        values = [argument[1] for argument in arguments]
        if any(value != value.to_integral_value() or abs(value) > 10000 for value in values):
            return False
        return name == "TIME" or Decimal(1900) <= values[0] <= Decimal(9999)
    if name == "DIVIDE":
        return len(arguments) == 2 and all(isinstance(a, tuple) and (a[0] in {"number", "blank", "blank_comment"}) for a in arguments)
    return False


def _condition(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """The condition of an IF / SWITCH(TRUE(), ...): a True/False literal, or a comparison of numbers and numeric aggregates."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "boolean":
        return True
    if node[0] != "comparison":
        return False
    return all(
        _literal_number(operand) or (operand[0] == "call" and _aggregate(operand, columns) and _numeric_column(operand[2][0], columns))
        for operand in (node[2], node[3])
    )


def _data_source(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """COUNTROWS(Facts), COUNTROWS(FILTER(Facts, FALSE())) and CALCULATE(SUM(column), column = text) of a loaded table."""
    if node[0] != "call":
        return False
    name = str(node[1]).upper()
    arguments = node[2]
    if name == "COUNTROWS" and len(arguments) == 1:
        source = arguments[0]
        if source[0] == "table" and str(source[1]).casefold() in columns:
            return True
        return (
            source[0] == "call" and str(source[1]).upper() == "FILTER" and len(source[2]) == 2 and source[2][0][0] == "table"
            and str(source[2][0][1]).casefold() in columns and source[2][1] == ("boolean", False)
        )
    if name == "CALCULATE" and len(arguments) == 2:
        value, condition = arguments
        if not _aggregate(value, columns) or condition[0] != "comparison" or condition[1] != "=":
            return False
        column, literal = condition[2], condition[3]
        return column[0] == "reference" and _column_type(column, columns) is not None and literal[0] == "string"
    return False


def hides(node: Any, columns: dict[str, dict[str, str]], folded_allowed: bool = False) -> bool:
    """True when every part of node is in the hiding grammar (see the module text): a failure inside it never shows through a type test."""
    if not isinstance(node, tuple) or not node:
        return False
    kind = node[0]
    if kind in _LITERALS:
        return True
    if kind == "let":
        return all(hides(bound, columns, True) for _, bound in node[1]) and hides(node[2], columns, False)
    if kind == "unary":
        return node[1] in {"+", "-", "not"} and hides(node[2], columns)
    if kind == "binary":
        return node[1] in _ARITHMETIC and hides(node[2], columns) and hides(node[3], columns)
    if kind == "logical":
        return hides(node[2], columns) and hides(node[3], columns)
    if kind == "concat":
        return hides(node[1], columns) and hides(node[2], columns)
    if kind != "call":
        return False
    name = str(node[1]).upper()
    arguments = node[2]
    if _data_source(node, columns) or _aggregate(node, columns):
        return True
    if name in {"AND", "OR"} and len(arguments) == 2 or name == "NOT" and len(arguments) == 1 or name in {"UPPER", "CONCATENATE", "COALESCE"}:
        return all(hides(argument, columns) for argument in arguments)
    if name in _LAZY_CALLS:
        if name == "CONVERT":
            if len(arguments) != 2 or arguments[1][0] != "table" or str(arguments[1][1]).upper() not in _CONVERT_KEYWORDS:
                return False
            return hides(arguments[0], columns)
        return bool(arguments) and all(hides(argument, columns) for argument in arguments)
    if name in _FOLDED_CALLS:
        if folded_allowed:
            return all(hides(argument, columns, True) for argument in arguments)
        return _benign_call(node)
    if name == "TRIM":
        return len(arguments) == 1 and arguments[0][0] == "string"
    if name == "IF" and len(arguments) in {2, 3}:
        return _condition(arguments[0], columns) and all(hides(argument, columns) for argument in arguments[1:])
    if name == "SWITCH" and len(arguments) >= 3:
        subject = arguments[0]
        if not (subject[0] == "boolean" or _literal_number(subject)):
            return False
        pairs = arguments[1:]
        tail = len(pairs) % 2  # an odd number after the subject leaves a default
        for index in range(0, len(pairs) - tail, 2):
            case, result = pairs[index], pairs[index + 1]
            if not (_literal_number(case) or _condition(case, columns) or case[0] == "boolean"):
                return False
            if not hides(result, columns, True):
                return False
        return not tail or hides(pairs[-1], columns)
    return False


def _reads_column(node: Any) -> bool:
    return isinstance(node, tuple) and bool(node) and (node[0] == "reference" or any(_reads_column(child) for child in _children(node)))


def _children(node: Any) -> list[Any]:
    kind = node[0]
    if kind == "call":
        return list(node[2])
    if kind in {"binary", "logical", "comparison"}:
        return [node[2], node[3]]
    if kind == "concat":
        return [node[1], node[2]]
    if kind == "unary":
        return [node[2]]
    if kind == "let":
        return [bound for _, bound in node[1]] + [node[2]]
    return []


def _walk(node: Any):
    if isinstance(node, tuple) and node:
        yield node
        for child in _children(node):
            yield from _walk(child)


def _without_saved_answer(function: str, argument: Any, columns: dict[str, dict[str, str]]) -> bool:
    """Shapes Power BI raises for or that were not measured, so they keep their refusal:
    a number literal multiplied by a power of a column aggregate (ISNUMBER(MIN(Facts[Sales])^0.5*2) is an error in Power BI for ISNUMBER, ISNUMERIC and
    ISDOUBLE; the other tests are not answered either), and ISDOUBLE of a column aggregate of a whole-number column multiplied by a text literal
    (Task 238: with + or - Power BI answers True, with * it raises, with / it raises).  Plus and minus of the same shapes are answered by the static type."""
    if argument[0] != "binary" or argument[1] not in {"+", "-", "*"}:
        return False
    left, right = argument[2], argument[3]
    for a, b in ((left, right), (right, left)):
        if argument[1] == "*" and _literal_number(b) and a[0] == "binary" and a[1] == "^" and a[2][0] == "call" and _aggregate(a[2], columns) and _literal_number(a[3]):
            return True
        if argument[1] == "*" and function.upper() == "ISDOUBLE" and b[0] == "string" and a[0] == "call" and _aggregate(a, columns):
            if (_column_type(a[2][0], columns) or "").casefold() in {"whole_number", "integer", "int64", "int"}:
                return True
    return False


def _text_divide(node: Any) -> bool:
    """DIVIDE of two or three literals of which at least one is a text literal (inline, not held by a VAR)."""
    if not (isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and str(node[1]).upper() == "DIVIDE" and len(node[2]) in {2, 3}):
        return False
    arguments = node[2]
    if not all(isinstance(a, tuple) and a and a[0] in {"number", "string", "blank", "blank_comment"} for a in arguments):
        return False
    if len(arguments) == 3 and arguments[2][0] == "string":
        return False  # a text alternate result raises in Power BI (ISINT64(DIVIDE("zz",3,"q")) is an error)
    return any(a[0] == "string" for a in arguments[:2])


def _without_text_divide(function: str, argument: Any) -> Any:
    """Task 238: ISINTEGER(DIVIDE(1,"zz")) and ABS(DIVIDE("zz",2)) in a type test whose answer does not depend on the value are decided by the type of DIVIDE
    (double), so the failing text is replaced by a number DIVIDE of the same type.  ISNUMBER / ISNUMERIC / ISDOUBLE of it are errors in Power BI and stay refused."""
    from . import measures

    if function not in _TEXT_DIVIDE_TESTS:
        return argument
    inner = argument
    if isinstance(argument, tuple) and len(argument) == 3 and argument[0] == "call" and str(argument[1]).upper() == "ABS" and len(argument[2]) == 1:
        inner = argument[2][0]
    if not _text_divide(inner):
        return argument
    plain = measures.parse_expression("DIVIDE(1,2)")
    return plain if inner is argument else (argument[0], argument[1], [plain])


def _literal_only(node: Any) -> bool:
    """Number / text literals with + - * & and CURRENCY / ABS of them: no column, no aggregate, no VAR, no division."""
    if not isinstance(node, tuple) or not node:
        return False
    kind = node[0]
    if kind in {"number", "string"}:
        return True
    if kind == "unary":
        return node[1] in {"+", "-"} and _literal_only(node[2])
    if kind == "binary":
        return node[1] in {"+", "-", "*"} and _literal_only(node[2]) and _literal_only(node[3])
    if kind == "concat":
        return _literal_only(node[1]) and _literal_only(node[2])
    if kind == "call":
        return str(node[1]).upper() in {"CURRENCY", "ABS"} and bool(node[2]) and all(_literal_only(a) for a in node[2])
    return False


def answer(function: str, argument: Any, columns: dict[str, dict[str, str]]) -> bool | None:
    """The answer of the type test of argument, decided by its static type, or None when it is not settled here (the caller keeps its refusal)."""
    from . import measures  # imported late: measures imports this module

    function = function.upper()
    if function not in TYPE_TESTS or not isinstance(argument, tuple) or not argument:
        return None
    argument = _without_text_divide(function, argument)
    if not hides(argument, columns):
        return None
    if _without_saved_answer(function, argument, columns):
        return None
    static_type = measures._static_numeric_type(argument, columns, {})
    if static_type not in _STATIC_TYPES:
        return None
    if function == "ISNONTEXT":
        result = static_type != "text"
        depends_on_blank = static_type == "text"
    else:
        result = static_type in _MATCHING_TYPES[function]
        depends_on_blank = result
    if depends_on_blank and not measures._never_blank(argument):
        return None  # a BLANK would answer the other way, so Power BI evaluates the value and the failure shows
    return result


def answer_measures(measures_list: list[dict[str, str]], measure_names: list[str] | None, table_context: list[dict[str, Any]] | None, failure: str = "") -> dict[str, bool] | None:
    """The result of evaluate_measures for one measure whose whole expression is a type test that the evaluation refused or raised for; None otherwise."""
    from . import measures

    if len(measures_list) != 1 or not table_context:
        return None
    if failure and not failure.startswith(_ANSWERABLE_FAILURES):
        return None  # only the failures of the saved answers are hidden (a text conversion, a POWER / FACT range, an older refusal of these shapes)
    item = measures_list[0]
    name = item.get("name", "")
    if measure_names is not None and [str(n).casefold() for n in measure_names] != [str(name).casefold()]:
        return None
    try:
        node = measures.parse_expression(item["expression"])
    except Exception:
        return None
    if not (isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and str(node[1]).upper() in TYPE_TESTS and len(node[2]) == 1):
        return None
    if failure.startswith(_OVERFLOW_FAILURE) and not _literal_only(node[2][0]):
        return None  # Task 238: only the overflow of literals; the overflow of a Currency product that reads rows shows through ISCURRENCY / ISNUMBER, a division raises
    columns = measures._normalize_model_column_types(table_context)
    result = answer(str(node[1]), node[2][0], columns)
    return None if result is None else {name: result}
