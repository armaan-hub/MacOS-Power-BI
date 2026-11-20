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
_VAR_TYPE_REFUSAL = "Cannot determine static type for function"  # Task 239: the refusal of a type test whose argument is a VAR (only a VAR block is answered for it)
_ANSWERABLE_FAILURES = ("Cannot convert value", "Iterator DIVIDE argument", "An argument of function", "A type test of a failing value", "A type test of arithmetic around a failing power", _OVERFLOW_FAILURE)


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


_COUNTING = frozenset({"COUNT", "COUNTA", "AVERAGE", "DISTINCTCOUNT"})


def _counting(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """Task 239: COUNT / AVERAGE of a numeric column and COUNTA / DISTINCTCOUNT of any column of a loaded table: a number that cannot fail
    (COUNT or AVERAGE of a text column raises in Power BI and is not accepted)."""
    if not (isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and str(node[1]).upper() in _COUNTING and len(node[2]) == 1):
        return False
    argument = node[2][0]
    if not (isinstance(argument, tuple) and argument and argument[0] == "reference" and _column_type(argument, columns) is not None):
        return False
    return str(node[1]).upper() in {"COUNTA", "DISTINCTCOUNT"} or _numeric_column(argument, columns)


def _literal_number(node: Any) -> bool:
    return isinstance(node, tuple) and bool(node) and (node[0] == "number" or (node[0] == "unary" and node[1] in {"+", "-"} and _literal_number(node[2])))


def _benign_call(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """A folded call that cannot fail: DATE / TIME of whole-number literals in an ordinary range, DIVIDE of number / BLANK literals
    (Task 239: and of aggregates, counts and other such DIVIDEs)."""
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
        return _divide_shape(node, columns) and not any(a[0] == "string" for a in arguments[:2])
    return False


_ARITHMETIC_CALLS = frozenset({"CURRENCY", "ABS", "INT", "ROUND", "TRUNC", "SIGN"})


def _arithmetic_only(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """Task 239: numbers, text literals, + - * ^, CURRENCY / ABS / INT / ROUND / TRUNC / SIGN, DIVIDE, aggregates and counts: no IF, SWITCH, COALESCE, comparison, AND, concatenation or VAR."""
    if not isinstance(node, tuple) or not node:
        return False
    kind = node[0]
    if kind in {"number", "string", "blank", "blank_comment"}:
        return True
    if kind == "unary":
        return node[1] in {"+", "-"} and _arithmetic_only(node[2], columns)
    if kind == "binary":
        return node[1] in {"+", "-", "*", "^"} and _arithmetic_only(node[2], columns) and _arithmetic_only(node[3], columns)
    if kind != "call":
        return False
    name = str(node[1]).upper()
    if _aggregate(node, columns) or _counting(node, columns):
        return True
    if name in _ARITHMETIC_CALLS:
        return bool(node[2]) and all(_arithmetic_only(argument, columns) for argument in node[2])
    return name == "DIVIDE" and len(node[2]) in {2, 3} and all(_arithmetic_only(argument, columns) for argument in node[2])


def _number_operand(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    from . import measures

    return _arithmetic_only(node, columns) and hides(node, columns) and measures._static_numeric_type(node, columns, {}) in _NUMERIC


def _simple_condition(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """A True/False literal, or a comparison of number literals and numeric aggregates (Task 235)."""
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


def _condition(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """The condition of an IF / SWITCH(TRUE(), ...): a True/False literal, or a comparison of numbers and numeric aggregates
    (Task 239: or of numbers that hold a failing part)."""
    if _simple_condition(node, columns):
        return True
    return isinstance(node, tuple) and bool(node) and node[0] == "comparison" and all(_number_operand(operand, columns) for operand in (node[2], node[3]))


def _result_branch(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """Task 239: the branch of an IF / SWITCH whose condition holds a failing part: a number that holds one, or a text literal (measured: IF(O>1,1,2), IF(O>1,O,2), IF(O>1,"a","b"))."""
    return isinstance(node, tuple) and bool(node) and (node[0] == "string" or _number_operand(node, columns))


def _common_type(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """Task 239: the result branches of an IF / SWITCH / COALESCE are all numbers, all text or all Booleans (BLANK literals are neutral)."""
    from . import measures

    name = str(node[1]).upper()
    arguments = list(node[2])
    if name == "IF":
        branches = arguments[1:]
    elif name == "SWITCH":
        pairs = arguments[1:]
        branches = [pairs[index] for index in range(1, len(pairs), 2)] + ([pairs[-1]] if len(pairs) % 2 else [])
    else:
        branches = arguments
    kinds = set()
    for branch in branches:
        if isinstance(branch, tuple) and branch and branch[0] in {"blank", "blank_comment"}:
            continue
        kind = measures._static_numeric_type(branch, columns, {})
        kinds.add("number" if kind in _NUMERIC else kind)
    if None in kinds:
        return False
    return len(kinds) <= 1 or not (kinds & {"bool", "text"})  # a Boolean or a text beside a number / date is a Variant; a date beside a number is the measured Task 235 shape


def _comparisons_placed(node: Any, allowed: bool = True) -> bool:
    """Task 239: a comparison only where a Boolean is read as a Boolean (the argument itself, an IF / SWITCH condition, AND / OR / NOT / && / || / NOT and
    a concatenation operand), never as an operand of arithmetic, a branch of IF / SWITCH / COALESCE or an argument of another call (not measured)."""
    if not isinstance(node, tuple) or not node:
        return True
    kind = node[0]
    if kind == "comparison":
        return allowed and all(_comparisons_placed(operand, False) for operand in (node[2], node[3]))
    if kind in {"logical", "concat"}:
        return all(_comparisons_placed(child, True) for child in _children(node))
    if kind == "unary":
        return _comparisons_placed(node[2], node[1] == "not")
    if kind == "call":
        name = str(node[1]).upper()
        arguments = node[2]
        if name in {"CALCULATE", "COUNTROWS"}:
            return True  # CALCULATE(SUM(column), column = text): the condition is part of the data source that hides() checks
        if name in {"AND", "OR", "NOT"}:
            return all(_comparisons_placed(argument, True) for argument in arguments)
        if name == "IF" and arguments:
            return _comparisons_placed(arguments[0], True) and all(_comparisons_placed(argument, False) for argument in arguments[1:])
        if name == "SWITCH" and arguments:
            cases = {index for index in range(1, len(arguments) - 1, 2)}  # a case is read as a Boolean when SWITCH(TRUE(), ...)
            return _comparisons_placed(arguments[0], False) and all(_comparisons_placed(argument, index in cases) for index, argument in enumerate(arguments) if index)
        return all(_comparisons_placed(argument, False) for argument in arguments)
    return all(_comparisons_placed(child, False) for child in _children(node))


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


def _numeric_comparison(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """Task 239: a comparison of two numbers that hold failing parts (it is a Boolean that is never BLANK)."""
    return all(_number_operand(operand, columns) for operand in (node[2], node[3]))


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
    if kind == "comparison":
        return _numeric_comparison(node, columns)
    if kind != "call":
        return False
    name = str(node[1]).upper()
    arguments = node[2]
    if _data_source(node, columns) or _aggregate(node, columns) or _counting(node, columns):
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
        return _benign_call(node, columns)
    if name == "TRIM":
        return len(arguments) == 1 and arguments[0][0] == "string"
    if name in {"IF", "SWITCH", "COALESCE"} and not _common_type(node, columns):
        return False  # Task 239: branches of different types make a Variant, which was not measured
    if name == "IF" and len(arguments) in {2, 3}:
        if not _condition(arguments[0], columns):
            return False
        if not _simple_condition(arguments[0], columns):
            return all(_result_branch(argument, columns) for argument in arguments[1:])
        return all(hides(argument, columns) for argument in arguments[1:])
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
            if (subject[0] == "boolean") == _literal_number(case):
                return False  # Task 239: SWITCH(TRUE(), 1, ...) and SWITCH(1, TRUE(), ...) compare a number with a Boolean (not measured)
            if not _simple_condition(case, columns) and not _literal_number(case):
                if subject[0] != "boolean" or not _result_branch(result, columns):
                    return False  # a failing part in the case: only SWITCH(TRUE(), failing > n, number, number) was measured
            elif not hides(result, columns, True):
                return False
        if tail and any(not _simple_condition(pairs[i], columns) and not _literal_number(pairs[i]) for i in range(0, len(pairs) - tail, 2)):
            return _result_branch(pairs[-1], columns)
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
        if function.upper() in {"ISNUMBER", "ISNUMERIC", "ISDOUBLE"} and argument[1] == "*" and _literal_number(b) and a[0] == "binary" and a[1] == "^" and a[2][0] == "call" and _aggregate(a[2], columns) and _literal_number(a[3]):
            return True
        if argument[1] == "*" and function.upper() == "ISDOUBLE" and b[0] == "string" and a[0] == "call" and _aggregate(a, columns):
            if (_column_type(a[2][0], columns) or "").casefold() in {"whole_number", "integer", "int64", "int"}:
                return True
    return False


def _divide_argument(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """An argument of a DIVIDE that cannot fail by itself: a number / text / BLANK literal, an aggregate or a count, or another DIVIDE of such arguments."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] in {"number", "string", "blank", "blank_comment"} or _literal_number(node):
        return True
    if node[0] == "call":
        if _aggregate(node, columns) or _counting(node, columns):
            return True
        if str(node[1]).upper() == "DIVIDE":
            return _divide_shape(node, columns)
    return _number_operand(node, columns)  # Task 239: DIVIDE(CURRENCY(3E15)*3,2): a number that holds a failing part


def _divide_shape(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    arguments = node[2]
    if len(arguments) not in {2, 3} or not all(_divide_argument(argument, columns) for argument in arguments):
        return False
    return len(arguments) == 2 or arguments[2][0] in {"number", "blank", "blank_comment"}  # a text alternate result raises in Power BI (ISINT64(DIVIDE("zz",3,"q")))


def _text_divide(node: Any, columns: dict[str, dict[str, str]]) -> bool:
    """DIVIDE with a text literal as numerator or denominator and no other argument that can fail (Task 239: aggregates and DIVIDE as the other argument)."""
    if not (isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and str(node[1]).upper() == "DIVIDE"):
        return False
    return _divide_shape(node, columns) and any(a[0] == "string" for a in node[2][:2])


def _rebuild(node: Any, transform: Any) -> Any:
    """node with transform applied to every direct child (call arguments, operands, VAR bindings and body)."""
    kind = node[0]
    if kind == "call":
        return (kind, node[1], tuple(transform(argument) for argument in node[2]))
    if kind in {"binary", "logical", "comparison"}:
        return (kind, node[1], transform(node[2]), transform(node[3])) + tuple(node[4:])
    if kind == "concat":
        return (kind, transform(node[1]), transform(node[2])) + tuple(node[3:])
    if kind == "unary":
        return (kind, node[1], transform(node[2])) + tuple(node[3:])
    if kind == "let":
        return (kind, tuple((name, transform(bound)) for name, bound in node[1]), transform(node[2]))
    return node


def _without_text_divide(argument: Any, columns: dict[str, dict[str, str]]) -> Any:
    """Task 238 / 239: every DIVIDE with a failing text literal, wherever it stands, is replaced by DIVIDE(1,2): both are a Double that can be BLANK, and a type test
    that does not depend on the value is decided by the type (ISNONTEXT(DIVIDE("zz",2)+1), ISINTEGER(ROUND(DIVIDE("zz",2),0))).  A test that depends on the value
    (ISNUMBER(DIVIDE("zz",2)), ISDOUBLE(ABS(DIVIDE("zz",2)))) is an error in Power BI and keeps its refusal by the BLANK rule of answer()."""
    from . import measures

    if not isinstance(argument, tuple) or not argument:
        return argument
    if _text_divide(argument, columns):
        return measures.parse_expression("DIVIDE(1,2)")
    return _rebuild(argument, lambda child: _without_text_divide(child, columns))


def _inline_variables(node: Any) -> Any:
    """A VAR block whose RETURN is a type test, with every VAR replaced by what it holds (a VAR has the type of its value); None when a VAR is not used."""
    if not (isinstance(node, tuple) and node and node[0] == "let"):
        return node
    held: dict[str, Any] = {}

    def substitute(child: Any) -> Any:
        if not isinstance(child, tuple) or not child:
            return child
        if child[0] == "var":
            return held.get(str(child[1]), child)
        return _rebuild(child, substitute)

    def uses(child: Any, name: str) -> bool:
        return isinstance(child, tuple) and bool(child) and ((child[0] == "var" and str(child[1]) == name) or any(uses(c, name) for c in _children(child)))

    names = [str(name) for name, _ in node[1]]
    if len(set(names)) != len(names):
        return None
    for name, bound in node[1]:
        held[str(name)] = substitute(bound)
    for index, name in enumerate(names):
        if not (uses(node[2], name) or any(uses(bound, name) for _, bound in node[1][index + 1:])):
            return None  # a VAR that nothing reads is not evaluated, so what Power BI does with it was not measured
    return substitute(node[2])


def _literal_text(node: Any) -> str | None:
    """The DAX text of a literal-only expression (the grammar of _literal_only), None for anything else."""
    kind = node[0] if isinstance(node, tuple) and node else None
    if kind == "number":
        return node[2] if len(node) > 2 and isinstance(node[2], str) else format(node[1], "f")
    if kind == "string":
        return '"' + str(node[1]).replace('"', '""') + '"'
    if kind == "unary" and node[1] in {"+", "-"}:
        inner = _literal_text(node[2])
        return None if inner is None else f"{node[1]}({inner})"
    if kind == "binary" and node[1] in {"+", "-", "*"}:
        left, right = _literal_text(node[2]), _literal_text(node[3])
        return None if left is None or right is None else f"({left}){node[1]}({right})"
    if kind == "concat":
        left, right = _literal_text(node[1]), _literal_text(node[2])
        return None if left is None or right is None else f"({left})&({right})"
    if kind == "call" and str(node[1]).upper() in {"CURRENCY", "ABS"} and node[2]:
        parts = [_literal_text(a) for a in node[2]]
        return None if any(p is None for p in parts) else f"{str(node[1]).upper()}({','.join(parts)})"
    return None


def _overflow_in_literals(node: Any) -> bool:
    """Task 239: the overflow comes from a part made of literals only (it is the same for every row), found by evaluating each such part on its own."""
    from . import measures

    for sub in _walk(node):
        if sub[0] in {"number", "string"} or not _literal_only(sub):
            continue
        text = _literal_text(sub)
        if text is None:
            continue
        try:
            measures.evaluate_measures([{"name": "Probe__", "expression": text}], [], [], "T", measure_names=["Probe__"])
        except measures.MeasureError as error:
            if str(error).startswith(_OVERFLOW_FAILURE):
                return True
        except Exception:
            continue
    return False


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
    argument = _without_text_divide(argument, columns)
    if not hides(argument, columns) or not _comparisons_placed(argument):
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
    item = measures_list[0]
    name = item.get("name", "")
    if measure_names is not None and [str(n).casefold() for n in measure_names] != [str(name).casefold()]:
        return None
    try:
        node = measures.parse_expression(item["expression"])
    except Exception:
        return None
    if failure and not (failure.startswith(_ANSWERABLE_FAILURES) or (node[0] == "let" and failure.startswith(_VAR_TYPE_REFUSAL))):
        return None  # only the failures of the saved answers are hidden (a text conversion, a POWER / FACT range, an older refusal of these shapes)
    if isinstance(node, tuple) and node and node[0] == "let":
        function_node = node[2]
        if not (isinstance(function_node, tuple) and len(function_node) == 3 and function_node[0] == "call" and len(function_node[2]) == 1):
            return None
        inlined = _inline_variables(node)  # Task 239: the VAR holds the failing part; the type test reads the type of what it holds
        if inlined is None:
            return None
        node = inlined
    if not (isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and str(node[1]).upper() in TYPE_TESTS and len(node[2]) == 1):
        return None
    if failure.startswith(_OVERFLOW_FAILURE) and not _overflow_in_literals(node[2][0]):
        return None  # Task 238 / 239: only the overflow of a part made of literals; the overflow of a Currency product that reads rows shows through ISCURRENCY / ISNUMBER, a division raises
    columns = measures._normalize_model_column_types(table_context)
    result = answer(str(node[1]), node[2][0], columns)
    return None if result is None else {name: result}
