"""Task 142: subnormal doubles (0 < |x| < DBL_MIN) as arguments of the scalar functions and operators of the measured table.

Power BI reads a subnormal number as a Double, and for most functions only its sign matters. A subnormal may come from a literal, from
a text ("3e-320", VALUE("-9e-316")) or from arithmetic. Each function or argument position below follows the measured rule; anything
not listed is refused (``function_answer`` returns NOT_SUBNORMAL for functions outside the table, and the refusal guards elsewhere stay).
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

from . import dax_math, dax_typed

NOT_SUBNORMAL = object()  # no argument is subnormal here: the caller runs its normal path
OPERATORS = frozenset({"/", "^"})  # + - * keep the existing double path: it already answers the measured sign-preserving rules (x+0, x+x, x*0, x*1E300)
DBL_MIN = dax_typed.DBL_MIN

# Functions with a measured subnormal rule. A function outside this set keeps its existing behaviour (refusal where it refused before).
HANDLED = frozenset({
    "ABS", "TRUNC", "ROUND", "ROUNDUP", "ROUNDDOWN", "SIN", "COS", "EXP", "LN", "LOG10", "LOG", "SQRT", "POWER", "FACT",
    "EVEN", "ODD", "ISEVEN", "ISODD", "NOT", "IF", "CONVERT", "DEGREES", "RADIANS", "VALUE", "SIGN", "FORMAT", "MOD",
    "MROUND", "CEILING", "FLOOR", "ISO.CEILING", "QUOTIENT", "DIVIDE", "INT", "CURRENCY", "FIXED", "LCM", "GCD",
})

SIGN_ONLY_MAX = Decimal("5.1E-310")  # the largest value measured to follow the sign-only rule of SIGN, INT and ROUND (INT(-5E-309/10) is 0, measured)
READS_NORMAL_MIN = Decimal("4.9E-309")  # from here SIGN, INT and ROUND answer as for an ordinary number (-5E-309 and 6E-309 measured); between the two is unmeasured
POWER_SUB_MAX = Decimal("5.1E-309")  # POWER and ^ keep the sign-only rule up to -5E-309 (measured) ...
POWER_NORMAL_MIN = Decimal("5.9E-309")  # ... and read 6E-309 as an ordinary number (POWER(6E-309,0) is 1 and POWER(6E-309,-0.25) is 1.1362193664675E+77, measured)
_THRESHOLD_FUNCTIONS = frozenset({"SIGN", "INT", "ROUND"})  # the only functions measured to switch earlier than DBL_MIN (every other one keeps the sign-only rule up to 6E-309)

_FORMAT_TEXT = "0.00E+00"  # the one FORMAT pattern with a measured subnormal answer


class Rewrite:
    """The call reads the same with these argument nodes (a subnormal argument replaced by a zero literal): the caller evaluates it again."""

    def __init__(self, arguments: tuple) -> None:
        self.arguments = arguments


class Substitute:
    """The subnormal argument reads as zero in this function (INT, FIXED, ...): the caller runs its normal path with these values."""

    def __init__(self, values: list[object]) -> None:
        self.values = values


def is_subnormal(value: object) -> bool:
    """A plain Decimal that is non-zero and below the smallest normal double (dates are Decimal subclasses and never count)."""
    return type(value) is Decimal and value.is_finite() and value != 0 and abs(value) < DBL_MIN


def as_subnormal_text(text: object) -> Decimal | None:
    """The double of a text that reads as a subnormal number, else None (a normal tiny text or a non-number is not this rule's)."""
    if not isinstance(text, str):
        return None
    try:
        with dax_typed.subnormal_text_allowed():
            number = dax_typed.text_to_number(text)
    except Exception:  # a text that is not a number is left to the caller's own rule
        return None
    return number if is_subnormal(number) else None


def operand(value: object) -> object:
    """An operator operand: a text that reads as a subnormal becomes that number, anything else is returned as it was."""
    if isinstance(value, str):
        sub = as_subnormal_text(value)
        return value if sub is None else sub
    return value


def _double(value: float) -> Decimal:
    """A double result as Power BI shows a Double: 15 significant digits (9.99999999999997E-311), zero as 0."""
    if value == 0:
        return Decimal(0)
    return Decimal(f"{value:.15G}")


def _arg_error(function: str) -> Exception:
    return dax_math._fail(function)


def _div0(function: str) -> Exception:
    return dax_typed._error(f"Division by zero has occurred when evaluating function '{function}'.")


class Unlisted(Exception):
    """A subnormal combination the measured table does not cover: the existing path answers or refuses it, as before this task."""


class Fallthrough(Exception):
    """The ordinary number path answers this call (a value that Power BI reads as an ordinary number, or an error it raises as for any number)."""


def _refuse(function: str) -> Exception:
    return Unlisted(function)


def unmeasured(function: str) -> Exception:
    """The refusal of a subnormal combination that the measured table does not cover (never a guess)."""
    return dax_typed.refusal(f"{function} with this subnormal argument is not modelled by the local engine.")


def _sqrt(x: Decimal) -> Decimal:
    return Decimal(f"{math.sqrt(float(x)):.15G}")  # the engine's SQRT of a subnormal (see measures._scalar_math_value)


def _log(x: Decimal, base: Decimal | None) -> Decimal:
    """LN, LOG10 and LOG of a positive subnormal: the true logarithm (LOG and LOG10 snap a whole result as the engine does)."""
    if base is None:
        return _double(math.log10(float(x)))
    value = math.log(float(x)) / math.log(float(base))
    return _double(round(value, 12) if abs(value - round(value)) < 1e-12 else value)


def _format_exponent(x: Decimal) -> str:
    """FORMAT(x, "0.00E+00"): the sign, a mantissa of two decimals and at least two exponent digits (1.00E-310)."""
    magnitude = Decimal(f"{abs(float(x)):.15G}")
    exponent = magnitude.adjusted()
    mantissa = magnitude.scaleb(-exponent).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if mantissa >= 10:
        mantissa, exponent = mantissa / 10, exponent + 1
    sign = "-" if x < 0 else ""
    exp_sign = "-" if exponent < 0 else "+"
    return f"{sign}{mantissa:.2f}E{exp_sign}{abs(exponent):02d}"


def _power(base: Decimal, exponent: Decimal, function: str = "POWER") -> Decimal | None:
    """base ^ exponent where one of them is subnormal (the table: POWER and the ^ operator alike)."""
    if type(base) is not Decimal or type(exponent) is not Decimal or not base.is_finite() or not exponent.is_finite():
        raise _refuse(function)
    if is_subnormal(base) and is_subnormal(exponent):
        raise _refuse(function)
    if is_subnormal(base):
        if abs(base) >= POWER_NORMAL_MIN:
            raise Fallthrough(function)  # 6E-309 reads as an ordinary number here
        if abs(base) > POWER_SUB_MAX:
            raise _refuse(function)  # between -5E-309 and 6E-309 is unmeasured
        positive = base > 0
        if exponent == 0:
            if positive:
                raise _arg_error(function)
            return Decimal(1)
        if exponent == 1:
            return Decimal(0)
        if exponent == exponent.to_integral_value() and exponent >= 2:
            return Decimal(0)
        if exponent < 0:
            if positive or exponent == -1:
                raise _div0(function)  # the subnormal base acts as a zero: 0 to a negative power (measured for -1, and -0.25 with a positive base)
            raise _arg_error(function)  # a negative subnormal to a negative fraction: an error (the message is not measured)
        if exponent == Decimal("0.5"):
            if positive:
                return _sqrt(base)
            raise _arg_error(function)
        raise _refuse(function)
    # the subnormal is the exponent
    if base == 0:
        if exponent > 0:
            return Decimal(0)
        raise _div0(function)  # a zero base with a subnormal exponent: zero when the exponent is positive, Division by zero when negative (measured)
    if base > 0:
        return Decimal(1)  # any positive base to a subnormal power is 1 (measured for 2, 0.5, 1, 3, 10 and 400)
    raise _arg_error(function)  # a negative base to a subnormal (fractional) power is the error (measured for -2 and -0.25)


def _subnormal_positions(function: str, values: list[object]) -> dict[int, Decimal]:
    """The arguments that are subnormal (a Decimal, or a text that reads as one), by position."""
    if function in {"IF", "FORMAT"}:
        positions = (0,)  # IF's branches and FORMAT's pattern are not numbers that the rule reads
    else:
        positions = tuple(range(len(values)))
    found: dict[int, Decimal] = {}
    for index in positions:
        value = values[index]
        sub = value if is_subnormal(value) else as_subnormal_text(value)
        if sub is not None:
            found[index] = sub
    return found


def function_answer(function: str, values: list[object], interval: str | None = None) -> object:
    """The answer of a scalar function that has a subnormal argument, or Substitute (zero in its place), or NOT_SUBNORMAL.

    NOT_SUBNORMAL also covers a combination outside the table, which the existing path keeps answering or refusing as before.
    """
    if function not in HANDLED:
        return NOT_SUBNORMAL
    subs = _subnormal_positions(function, values)
    if not subs:
        return NOT_SUBNORMAL
    try:
        return _table_answer(function, values, subs, interval)
    except Unlisted:
        if function == "POWER":
            raise unmeasured(function) from None  # the ordinary power would compute an unmeasured answer for a subnormal base or exponent
        return NOT_SUBNORMAL  # any other combination outside the table keeps its existing path (it refuses, or answers as before this task)
    except Fallthrough:
        return NOT_SUBNORMAL


def _reads_normal(function: str, args: list[object], digits_ok) -> object:
    """SIGN, INT and ROUND of a value from 5E-309 up answer as for an ordinary number (SIGN(6E-309) is 1, INT(-5E-309) is -1, ROUND(6E-309,2) is 0)."""
    first = args[0]
    if function == "SIGN":
        return Decimal(1) if first > 0 else Decimal(-1)
    if function == "INT":
        return Decimal(0) if first > 0 else Decimal(-1)
    if len(args) > 1 and (type(args[1]) is not Decimal or not args[1].is_finite() or args[1] > 15):
        raise unmeasured(function)  # ROUND at many digits is not measured for these values
    return Decimal(0)


def _table_answer(function: str, values: list[object], subs: dict[int, Decimal], interval: str | None) -> object:
    args = [subs.get(index, value) for index, value in enumerate(values)]
    keys = set(subs)
    first = args[0] if args else None

    def only(*positions: int) -> None:
        if keys != set(positions):
            raise _refuse(function)

    def digits_ok(index: int) -> bool:
        return len(args) <= index or args[index] is None or (type(args[index]) is Decimal and args[index].is_finite())

    if function in {"ABS", "TRUNC", "ROUNDUP", "ROUNDDOWN", "ROUND", "SIN", "VALUE", "SIGN", "DEGREES", "RADIANS", "COS", "EXP",
                     "LN", "LOG10", "LOG", "SQRT", "FACT", "EVEN", "ODD", "ISEVEN", "ISODD", "NOT", "IF", "CONVERT", "FORMAT"}:
        only(0)

    if function in _THRESHOLD_FUNCTIONS:
        only(0)
        if abs(first) > SIGN_ONLY_MAX:
            if abs(first) < READS_NORMAL_MIN:
                raise unmeasured(function)  # between 2E-310 and 5E-309 SIGN, INT and ROUND are not measured
            return _reads_normal(function, args, digits_ok)

    if function == "ABS":
        return _double(abs(float(first)))
    if function in {"TRUNC", "ROUNDUP", "ROUNDDOWN", "SIN", "VALUE"}:
        if not digits_ok(1):
            raise _refuse(function)
        return _double(float(first))
    if function == "ROUND":
        if not digits_ok(1):
            raise _refuse(function)
        return _double(float(first)) if first > 0 else Decimal(0)
    if function in {"COS", "EXP"}:
        return Decimal(1)
    if function in {"LN", "LOG10", "LOG"}:
        if first < 0:
            raise _arg_error(function)
        if function == "LN":
            return _double(math.log(float(first)))
        if function == "LOG" and len(args) > 1:
            base = args[1]
            if base is None or type(base) is not Decimal or not base.is_finite():
                raise _refuse(function)
            if base <= 0:
                raise _arg_error(function)  # a base that is zero or negative is the error
            if base == 1:
                raise _refuse(function)
            return _log(first, base)
        return _log(first, None)  # LOG10, and LOG with its default base 10
    if function == "SQRT":
        if first < 0:
            raise _arg_error(function)
        return _sqrt(first)
    if function == "FACT":
        if first < 0:
            raise _arg_error(function)
        return Decimal(1)
    if function == "EVEN":
        return Decimal(2) if first > 0 else Decimal(-2)
    if function == "ODD":
        return Decimal(1) if first > 0 else Decimal(-1)
    if function == "ISEVEN":
        return True
    if function == "ISODD":
        return False
    if function == "NOT":
        return False
    if function == "IF":
        if len(args) < 3:
            raise _refuse(function)
        return args[1]  # a subnormal condition is true, so the true branch (measured for both signs)
    if function == "CONVERT":
        if interval == "DOUBLE":
            return _double(float(first))
        if interval in {"INTEGER", "CURRENCY"}:
            return Substitute([Decimal(0)])
        if interval == "BOOLEAN":
            return True
        raise _refuse(function)
    if function in {"DEGREES", "RADIANS"}:
        result = float(first) * (180.0 / math.pi if function == "DEGREES" else math.pi / 180.0)
        if abs(result) < dax_typed.DBL_MIN_FLOAT:
            return Decimal(0)  # a subnormal result is 0 (measured); DEGREES(-5E-309) is the ordinary -2.86478897565412E-307
        return _double(result)
    if function == "SIGN":
        return Decimal(0) if first > 0 else Decimal(-1)
    if function == "FORMAT":
        if args[1] != _FORMAT_TEXT:
            raise _refuse(function)
        return _format_exponent(first)

    if function == "MOD":
        if keys == {0}:
            divisor = args[1]
            if type(divisor) is not Decimal or not divisor.is_finite():
                raise _refuse(function)
            if divisor == 0:
                raise _div0("MOD")  # measured
            if divisor > 0:
                if first > 0:
                    raise _arg_error(function)
                return Decimal(0)
            if first > 0:
                return Decimal(0)
            raise _arg_error(function)
        only(1)  # MOD(n, x): the subnormal is the divisor
        number, divisor = args[0], args[1]
        if type(number) is not Decimal or not number.is_finite():
            raise _refuse(function)
        if divisor > 0:
            raise _div0("MOD")
        if number == 0:
            return Decimal(0)
        raise _arg_error(function)
    if function == "MROUND":
        only(0)
        multiple = args[1]
        if type(multiple) is not Decimal or not multiple.is_finite():
            raise _refuse(function)
        if multiple == 0:
            return Decimal(0)
        if multiple > 0:  # a positive multiple: zero for a positive x, the error for a negative one (measured)
            if first < 0:
                raise _arg_error(function)
            return Decimal(0)
        if first > 0:  # a negative multiple: the error for a positive x, zero for a negative one (measured)
            raise _arg_error(function)
        return Decimal(0)
    if function in {"CEILING", "FLOOR", "ISO.CEILING"}:
        only(0)
        significance = Decimal(1) if len(args) < 2 else args[1]
        if type(significance) is not Decimal or not significance.is_finite():
            raise _refuse(function)
        if function == "ISO.CEILING":
            return Decimal(0)  # the sign of the significance is ignored (measured): zero for either sign of x
        if significance >= 0:
            if function == "FLOOR" and significance == 0:
                raise _div0("FLOOR")
            return Decimal(0)  # CEILING of a subnormal with a positive or zero step is zero (FLOOR likewise)
        if first > 0:
            raise _arg_error(function)
        return Decimal(0)
    if function == "QUOTIENT":
        if keys == {0}:
            divisor = args[1]
            if type(divisor) is not Decimal or not divisor.is_finite():
                raise _refuse(function)
            if divisor == 0:
                raise _div0("QUOTIENT")  # measured
            return Substitute([Decimal(0), divisor])
        only(1)
        if type(args[0]) is not Decimal or not args[0].is_finite():
            raise _refuse(function)
        raise _arg_error(function)
    if function in {"INT", "CURRENCY", "FIXED"}:
        only(0)
        if function == "FIXED" and len(args) > 1 and type(args[1]) is not Decimal:
            raise _refuse(function)
        if function == "FIXED" and len(args) > 1 and args[1] > 127:
            raise dax_typed._error("An argument of function 'FIXED' has the wrong data type or has an invalid value.")  # more than 127 decimals (measured)
        return Substitute([Decimal(0)] + list(args[1:]))
    if function == "LCM":
        only(0)
        return Substitute([Decimal(0)] + list(args[1:]))
    if function == "GCD":
        only(0)
        if len(args) < 2 or type(args[1]) is not Decimal or not args[1].is_finite():
            raise _refuse(function)
        return Substitute([Decimal(0), args[1]])  # the subnormal reads as zero: GCD(0, n) is n (a negative n is the usual error)
    if function == "POWER":
        if len(args) != 2:
            raise _refuse(function)
        if keys == {0}:
            return _power(first, args[1])
        only(1)
        return _power(args[0], args[1])
    if function == "DIVIDE":
        if 1 in keys:
            numerator, divisor = args[0], args[1]
            if type(numerator) is not Decimal or not numerator.is_finite():
                raise _refuse(function)
            inverse = 1.0 / float(divisor)
            if math.isinf(inverse):
                return None  # 1/b beyond the Double range is BLANK, whatever the numerator (measured below about 5.56E-309)
            if 0 in keys:
                raise _refuse(function)  # a subnormal numerator over a divisor with a finite inverse is not measured
            return _double(float(numerator) * inverse)
        only(0)
        divisor = args[1]
        if divisor is None or type(divisor) is not Decimal or not divisor.is_finite():
            raise _refuse(function)
        if divisor == 0:
            return None
        return _double(float(first) / float(divisor))
    raise _refuse(function)


def binary_answer(operator: str, left: object, right: object) -> object:
    """The answer of a binary operator with a subnormal operand (both already numbers), or NOT_SUBNORMAL for a combination outside the table."""
    try:
        return _table_binary(operator, left, right)
    except Unlisted:
        if operator == "^":
            raise unmeasured(operator) from None
        return NOT_SUBNORMAL
    except Fallthrough:
        return NOT_SUBNORMAL


def _table_binary(operator: str, left: object, right: object) -> object:
    if type(left) is not Decimal or type(right) is not Decimal or not left.is_finite() or not right.is_finite():
        raise _refuse(operator)
    if operator == "/":
        if right == 0:
            raise Fallthrough(operator)  # the ordinary division-by-zero error of the operator
        if left == 0:
            return Decimal(0)
        return _double(float(left) / float(right))  # a/x beyond the Double range is Infinity with the sign of the quotient (measured)
    if operator == "^":
        return _power(left, right)
    raise _refuse(operator)


def holds_subnormal(node: object) -> bool:
    """True when a number or text literal in the tree is subnormal (a static check: only literals are read, never a computed value)."""
    if isinstance(node, tuple):
        if node and node[0] == "number" and len(node) > 1 and is_subnormal(node[1]):
            return True
        if node and node[0] == "string" and len(node) > 1 and isinstance(node[1], str) and ("e" in node[1] or "E" in node[1]):
            return as_subnormal_text(node[1]) is not None
        return any(holds_subnormal(child) for child in node)
    if isinstance(node, list):
        return any(holds_subnormal(child) for child in node)
    return False


def call(evaluate_argument, function: str, arguments: tuple) -> object:
    """A scalar call with a subnormal argument: its answer, a Rewrite (zero in place of the subnormal), or NOT_SUBNORMAL (the normal path runs).

    evaluate_argument(node) gives an argument's value. An argument that fails to evaluate leaves the call to the normal path, which raises as before.
    """
    interval = None
    if function == "CONVERT" and arguments and arguments[-1][0] == "table":
        interval = str(arguments[-1][1]).upper()
        arguments = arguments[:-1]
    try:
        values = [evaluate_argument(argument) for argument in arguments]
    except Exception:  # the normal path evaluates the same arguments and raises the same error
        return NOT_SUBNORMAL
    answer = function_answer(function, values, interval)
    if not isinstance(answer, Substitute):
        return answer
    positions = _subnormal_positions(function, values)
    new_arguments = tuple(
        ("number", Decimal(0), "0") if index in positions else argument for index, argument in enumerate(arguments)
    )
    if interval is not None:
        new_arguments = new_arguments + (("table", interval),)
    return Rewrite(new_arguments)
