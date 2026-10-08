"""A bounded, safe evaluator for common Power Query custom-column formulas.

This is intentionally a small M expression subset, not an M runtime. It never
executes Python or user-provided code; formulas are parsed into an AST and
evaluated against one row at a time.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
import re
from typing import Any


MAX_EXPRESSION_LENGTH = 2_000
MAX_EXPRESSION_TOKENS = 512
MAX_EXPRESSION_OUTPUT_BYTES = 80 * 1024 * 1024


class ExpressionError(ValueError):
    """Invalid or unsupported custom-column expression or value."""


_NUMBER_PATTERN = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")
_FUNCTION_ARITY: dict[str, tuple[int, int]] = {
    "Text.From": (1, 1),
    "Text.Upper": (1, 1),
    "Text.Lower": (1, 1),
    "Text.Trim": (1, 1),
    "Text.Length": (1, 1),
    "Text.Contains": (2, 2),
    "Text.StartsWith": (2, 2),
    "Text.EndsWith": (2, 2),
    "Text.Replace": (3, 3),
    "Number.From": (1, 1),
    "Number.Abs": (1, 1),
    "Number.Round": (1, 2),
    "Date.From": (1, 1),
    "Date.Year": (1, 1),
    "Date.Month": (1, 1),
    "Date.Day": (1, 1),
}


def compile_expression(expression: Any) -> tuple[Any, ...]:
    """Parse one expression and reject syntax outside the supported subset."""
    if not isinstance(expression, str) or not expression.strip():
        raise ExpressionError("Enter a custom-column formula.")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(
            f"A custom-column formula may contain at most {MAX_EXPRESSION_LENGTH:,} characters."
        )
    tokens = _tokenize(expression)
    if len(tokens) > MAX_EXPRESSION_TOKENS:
        raise ExpressionError(
            f"A custom-column formula may contain at most {MAX_EXPRESSION_TOKENS} tokens."
        )
    parser = _Parser(tokens)
    tree = parser.parse_expression()
    if parser.position != len(tokens):
        token = tokens[parser.position]
        raise ExpressionError(f"Unexpected token {token[1]!r} at position {token[2] + 1}.")
    return tree


def referenced_columns(expression: tuple[Any, ...]) -> set[str]:
    """Return the row fields referenced by a parsed formula."""
    result: set[str] = set()

    def visit(node: tuple[Any, ...]) -> None:
        kind = node[0]
        if kind == "field":
            result.add(node[1])
        elif kind == "call":
            for child in node[2]:
                visit(child)
        elif kind == "if":
            visit(node[1])
            visit(node[2])
            visit(node[3])
        elif kind == "unary":
            visit(node[2])
        elif kind == "coalesce":
            visit(node[1])
            visit(node[2])
        elif kind == "binary":
            visit(node[2])
            visit(node[3])

    visit(expression)
    return result


def evaluate_expression(expression: tuple[Any, ...], row: dict[str, str]) -> Any:
    """Evaluate a parsed formula against one normalized-text table row."""
    try:
        return _evaluate(expression, row)
    except ExpressionError:
        raise
    except (ArithmeticError, DecimalException, OverflowError, TypeError, ValueError) as exc:
        raise ExpressionError(str(exc) or "The formula could not be evaluated.") from exc


def expression_value_to_text(value: Any) -> str:
    """Convert a formula result to the app's normalized-text cell format."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return _decimal_to_text(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        _check_text_size(value)
        return value
    raise ExpressionError("The formula returned a value this table model cannot store.")


class _Parser:
    def __init__(self, tokens: list[tuple[str, str, int]]) -> None:
        self.tokens = tokens
        self.position = 0

    def parse_expression(self) -> tuple[Any, ...]:
        if self._accept("keyword", "if"):
            condition = self._parse_coalesce()
            self._expect("keyword", "then")
            when_true = self.parse_expression()
            self._expect("keyword", "else")
            when_false = self.parse_expression()
            return ("if", condition, when_true, when_false)
        return self._parse_coalesce()

    def _parse_coalesce(self) -> tuple[Any, ...]:
        left = self._parse_or()
        if self._accept("operator", "??"):
            return ("coalesce", left, self._parse_coalesce())
        return left

    def _parse_or(self) -> tuple[Any, ...]:
        node = self._parse_and()
        while self._accept("keyword", "or"):
            node = ("binary", "or", node, self._parse_and())
        return node

    def _parse_and(self) -> tuple[Any, ...]:
        node = self._parse_comparison()
        while self._accept("keyword", "and"):
            node = ("binary", "and", node, self._parse_comparison())
        return node

    def _parse_comparison(self) -> tuple[Any, ...]:
        node = self._parse_concat()
        while self._peek("operator") and self._current()[1] in {"=", "<>", "<", "<=", ">", ">="}:
            operator = self._current()[1]
            self.position += 1
            node = ("binary", operator, node, self._parse_concat())
        return node

    def _parse_concat(self) -> tuple[Any, ...]:
        node = self._parse_additive()
        while self._accept("operator", "&"):
            node = ("binary", "&", node, self._parse_additive())
        return node

    def _parse_additive(self) -> tuple[Any, ...]:
        node = self._parse_multiplicative()
        while self._peek("operator") and self._current()[1] in {"+", "-"}:
            operator = self._current()[1]
            self.position += 1
            node = ("binary", operator, node, self._parse_multiplicative())
        return node

    def _parse_multiplicative(self) -> tuple[Any, ...]:
        node = self._parse_unary()
        while self._peek("operator") and self._current()[1] in {"*", "/"}:
            operator = self._current()[1]
            self.position += 1
            node = ("binary", operator, node, self._parse_unary())
        return node

    def _parse_unary(self) -> tuple[Any, ...]:
        if self._accept("operator", "+"):
            return ("unary", "+", self._parse_unary())
        if self._accept("operator", "-"):
            return ("unary", "-", self._parse_unary())
        if self._accept("keyword", "not"):
            return ("unary", "not", self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> tuple[Any, ...]:
        if self._accept("operator", "("):
            expression = self.parse_expression()
            self._expect("operator", ")")
            return expression
        if self._peek("field"):
            return ("field", self._consume()[1])
        if self._peek("string"):
            return ("literal", self._consume()[1])
        if self._peek("number"):
            token = self._consume()
            try:
                value = Decimal(token[1])
            except DecimalException as exc:
                raise ExpressionError(f"Invalid number at position {token[2] + 1}.") from exc
            if not value.is_finite():
                raise ExpressionError("Formula numbers must be finite.")
            return ("literal", value)
        if self._peek("keyword") and self._current()[1] in {"true", "false", "null"}:
            value = self._consume()[1]
            return ("literal", {"true": True, "false": False, "null": None}[value])
        if self._peek("identifier"):
            token = self._consume()
            function = token[1]
            if function not in _FUNCTION_ARITY:
                raise ExpressionError(f"Unsupported name or function {function!r}.")
            self._expect("operator", "(")
            arguments: list[tuple[Any, ...]] = []
            if not self._accept("operator", ")"):
                while True:
                    arguments.append(self.parse_expression())
                    if self._accept("operator", ")"):
                        break
                    self._expect("operator", ",")
            minimum, maximum = _FUNCTION_ARITY[function]
            if not minimum <= len(arguments) <= maximum:
                raise ExpressionError(
                    f"{function} accepts {minimum} to {maximum} argument(s)."
                )
            return ("call", function, arguments)
        token = self._current() if self.position < len(self.tokens) else None
        if token is None:
            raise ExpressionError("The formula ended before its expression was complete.")
        raise ExpressionError(f"Unexpected token {token[1]!r} at position {token[2] + 1}.")

    def _current(self) -> tuple[str, str, int]:
        return self.tokens[self.position]

    def _peek(self, kind: str) -> bool:
        return self.position < len(self.tokens) and self.tokens[self.position][0] == kind

    def _accept(self, kind: str, value: str) -> bool:
        if self.position < len(self.tokens) and self.tokens[self.position][:2] == (kind, value):
            self.position += 1
            return True
        return False

    def _expect(self, kind: str, value: str) -> None:
        if not self._accept(kind, value):
            actual = self._current()[1] if self.position < len(self.tokens) else "end of formula"
            raise ExpressionError(f"Expected {value!r}, found {actual!r}.")

    def _consume(self) -> tuple[str, str, int]:
        token = self._current()
        self.position += 1
        return token


def _tokenize(expression: str) -> list[tuple[str, str, int]]:
    tokens: list[tuple[str, str, int]] = []
    position = 0
    while position < len(expression):
        character = expression[position]
        if character.isspace():
            position += 1
            continue
        if character == "[":
            token, position = _read_field(expression, position)
            tokens.append(token)
            continue
        if character == '"':
            token, position = _read_string(expression, position)
            tokens.append(token)
            continue
        number = _NUMBER_PATTERN.match(expression, position)
        if number:
            tokens.append(("number", number.group(), position))
            position = number.end()
            continue
        identifier = _IDENTIFIER_PATTERN.match(expression, position)
        if identifier:
            value = identifier.group()
            kind = "keyword" if value in {"if", "then", "else", "true", "false", "null", "and", "or", "not"} else "identifier"
            tokens.append((kind, value, position))
            position = identifier.end()
            continue
        two_character_operator = expression[position:position + 2]
        if two_character_operator in {"<>", "<=", ">=", "??"}:
            tokens.append(("operator", two_character_operator, position))
            position += 2
            continue
        if character in "+-*/&=<>(),":
            tokens.append(("operator", character, position))
            position += 1
            continue
        raise ExpressionError(f"Unsupported character {character!r} at position {position + 1}.")
    return tokens


def _read_field(expression: str, position: int) -> tuple[tuple[str, str, int], int]:
    start = position
    position += 1
    if expression.startswith('#"', position):
        position += 2
        pieces: list[str] = []
        while position < len(expression):
            if expression[position] == '"':
                if expression.startswith('""', position):
                    pieces.append('"')
                    position += 2
                    continue
                if expression.startswith('"]', position):
                    position += 2
                    return ("field", "".join(pieces), start), position
                raise ExpressionError(f"Invalid quoted column reference at position {start + 1}.")
            pieces.append(expression[position])
            position += 1
        raise ExpressionError(f"Unclosed column reference at position {start + 1}.")
    end = expression.find("]", position)
    if end < 0:
        raise ExpressionError(f"Unclosed column reference at position {start + 1}.")
    name = expression[position:end]
    if not name:
        raise ExpressionError(f"Empty column reference at position {start + 1}.")
    return ("field", name, start), end + 1


def _read_string(expression: str, position: int) -> tuple[tuple[str, str, int], int]:
    start = position
    position += 1
    pieces: list[str] = []
    while position < len(expression):
        if expression[position] == '"':
            if expression.startswith('""', position):
                pieces.append('"')
                position += 2
                continue
            return ("string", "".join(pieces), start), position + 1
        pieces.append(expression[position])
        position += 1
    raise ExpressionError(f"Unclosed text literal at position {start + 1}.")


def _evaluate(node: tuple[Any, ...], row: dict[str, str]) -> Any:
    kind = node[0]
    if kind == "literal":
        return node[1]
    if kind == "field":
        name = node[1]
        if name not in row:
            raise ExpressionError(f"Column {name!r} does not exist at this step.")
        return None if row[name] == "" else row[name]
    if kind == "if":
        condition = _evaluate(node[1], row)
        if not isinstance(condition, bool):
            raise ExpressionError("An if condition must evaluate to true or false.")
        return _evaluate(node[2] if condition else node[3], row)
    if kind == "unary":
        value = _evaluate(node[2], row)
        if node[1] == "not":
            if value is None:
                return None
            if not isinstance(value, bool):
                raise ExpressionError("The not operator requires a logical value.")
            return not value
        if value is None:
            return None
        number = _as_number(value)
        return number if node[1] == "+" else -number
    if kind == "coalesce":
        value = _evaluate(node[1], row)
        return _evaluate(node[2], row) if value is None else value
    if kind == "binary":
        operator = node[1]
        left = _evaluate(node[2], row)
        if operator == "and":
            if left is False:
                return False
            if left is not None and not isinstance(left, bool):
                raise ExpressionError("The and operator requires logical values.")
            right = _evaluate(node[3], row)
            if right is not None and not isinstance(right, bool):
                raise ExpressionError("The and operator requires logical values.")
            if right is False:
                return False
            if right is None or left is None:
                return None
            return left and right
        if operator == "or":
            if left is True:
                return True
            if left is not None and not isinstance(left, bool):
                raise ExpressionError("The or operator requires logical values.")
            right = _evaluate(node[3], row)
            if right is not None and not isinstance(right, bool):
                raise ExpressionError("The or operator requires logical values.")
            if right is True:
                return True
            if right is None or left is None:
                return None
            return left or right
        right = _evaluate(node[3], row)
        return _evaluate_binary(operator, left, right)
    if kind == "call":
        arguments = [_evaluate(argument, row) for argument in node[2]]
        return _call_function(node[1], arguments)
    raise ExpressionError("The formula contains an invalid expression node.")


def _evaluate_binary(operator: str, left: Any, right: Any) -> Any:
    if operator == "&":
        if left is None or right is None:
            return None
        left_text, right_text = _value_to_text(left), _value_to_text(right)
        if _text_size(left_text) + _text_size(right_text) > MAX_EXPRESSION_OUTPUT_BYTES:
            raise ExpressionError("A custom-column text result exceeds the 80 MiB output limit.")
        return left_text + right_text
    if operator in {"+", "-", "*", "/"}:
        if left is None or right is None:
            return None
        left_number, right_number = _as_number(left), _as_number(right)
        with localcontext() as context:
            context.prec = 4096
            if operator == "+":
                result = left_number + right_number
            elif operator == "-":
                result = left_number - right_number
            elif operator == "*":
                result = left_number * right_number
            else:
                if not right_number:
                    raise ExpressionError("Division by zero is not allowed in this table.")
                result = left_number / right_number
        if not result.is_finite() or result.adjusted() > 4096:
            raise ExpressionError("The numeric result exceeds the supported range.")
        return result
    if operator in {"=", "<>", "<", "<=", ">", ">="}:
        if operator in {"=", "<>"} and (left is None or right is None):
            equal = left is right
            return equal if operator == "=" else not equal
        if left is None or right is None:
            return None
        left, right = _comparable_values(left, right)
        if operator == "=":
            return left == right
        if operator == "<>":
            return left != right
        try:
            if operator == "<":
                return left < right
            if operator == "<=":
                return left <= right
            if operator == ">":
                return left > right
            return left >= right
        except TypeError as exc:
            raise ExpressionError("The values cannot be compared with this operator.") from exc
    raise ExpressionError(f"Unsupported operator {operator!r}.")


def _comparable_values(left: Any, right: Any) -> tuple[Any, Any]:
    if isinstance(left, (Decimal, bool)) or isinstance(right, (Decimal, bool)):
        return _as_number(left), _as_number(right)
    if isinstance(left, str) and isinstance(right, str):
        left_number = _try_number(left)
        right_number = _try_number(right)
        if left_number is not None and right_number is not None:
            return left_number, right_number
    if type(left) is not type(right):
        raise ExpressionError("The values have different types and cannot be compared.")
    return left, right


def _call_function(name: str, arguments: list[Any]) -> Any:
    if name in {"Text.From", "Number.From", "Date.From"}:
        value = arguments[0]
        if value is None:
            return None
        if name == "Text.From":
            return _value_to_text(value)
        if name == "Number.From":
            return _as_number(value)
        return _as_date(value)
    if name.startswith("Text."):
        if any(value is None for value in arguments):
            return None
        if any(not isinstance(value, str) for value in arguments):
            raise ExpressionError(f"{name} requires text arguments.")
        if name == "Text.Upper":
            return _case_convert(arguments[0], upper=True)
        if name == "Text.Lower":
            return _case_convert(arguments[0], upper=False)
        if name == "Text.Trim":
            return arguments[0].strip()
        if name == "Text.Length":
            return Decimal(len(arguments[0]))
        if name == "Text.Contains":
            return arguments[1] in arguments[0]
        if name == "Text.StartsWith":
            return arguments[0].startswith(arguments[1])
        if name == "Text.EndsWith":
            return arguments[0].endswith(arguments[1])
        if name == "Text.Replace":
            text, old, new = arguments
            count = text.count(old)
            predicted_size = _text_size(text) - count * _text_size(old) + count * _text_size(new)
            if predicted_size > MAX_EXPRESSION_OUTPUT_BYTES:
                raise ExpressionError("A custom-column text result exceeds the 80 MiB output limit.")
            return text.replace(old, new)
    if name == "Number.Abs":
        value = arguments[0]
        return None if value is None else abs(_as_number(value))
    if name == "Number.Round":
        value = arguments[0]
        if value is None:
            return None
        number = _as_number(value)
        digits_value = arguments[1] if len(arguments) == 2 else Decimal(0)
        digits_number = _as_number(digits_value)
        if digits_number != digits_number.to_integral_value() or abs(digits_number) > 12:
            raise ExpressionError("Number.Round digits must be a whole number from -12 to 12.")
        digits = int(digits_number)
        quantum = Decimal(1).scaleb(-digits)
        try:
            with localcontext() as context:
                context.prec = 4096
                return number.quantize(quantum, rounding=ROUND_HALF_EVEN)
        except DecimalException as exc:
            raise ExpressionError("The rounded result exceeds the supported range.") from exc
    if name in {"Date.Year", "Date.Month", "Date.Day"}:
        value = arguments[0]
        if value is None:
            return None
        converted = _as_date(value)
        component = {"Date.Year": converted.year, "Date.Month": converted.month, "Date.Day": converted.day}[name]
        return Decimal(component)
    raise ExpressionError(f"Unsupported function {name!r}.")


def _as_number(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, bool):
        result = Decimal(1 if value else 0)
    elif isinstance(value, (str, int)):
        try:
            result = Decimal(value.strip() if isinstance(value, str) else value)
        except (DecimalException, ValueError):
            raise ExpressionError(f"Value {value!r} is not a valid number.") from None
    else:
        raise ExpressionError(f"Value {value!r} cannot be converted to a number.")
    if not result.is_finite() or (result and abs(result.adjusted()) > 4096):
        raise ExpressionError("Formula numbers must be finite and within the supported range.")
    return result


def _try_number(value: str) -> Decimal | None:
    try:
        return _as_number(value)
    except ExpressionError:
        return None


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            try:
                return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
            except ValueError as exc:
                raise ExpressionError(f"Value {value!r} is not an ISO date or date-time.") from exc
    raise ExpressionError(f"Value {value!r} cannot be converted to a date.")


def _value_to_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return _decimal_to_text(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise ExpressionError(f"Value {value!r} cannot be converted to text.")


def _decimal_to_text(value: Decimal) -> str:
    if not value.is_finite() or (value and abs(value.adjusted()) > 4096):
        raise ExpressionError("The numeric result exceeds the supported range.")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _text_size(value: str) -> int:
    if len(value) > MAX_EXPRESSION_OUTPUT_BYTES:
        raise ExpressionError("A custom-column text result exceeds the 80 MiB output limit.")
    return len(value.encode("utf-8"))


def _check_text_size(value: str) -> None:
    if _text_size(value) > MAX_EXPRESSION_OUTPUT_BYTES:
        raise ExpressionError("A custom-column text result exceeds the 80 MiB output limit.")


def _case_convert(value: str, *, upper: bool) -> str:
    if not value.isascii() and len(value) * 3 > MAX_EXPRESSION_OUTPUT_BYTES:
        raise ExpressionError("A custom-column text result exceeds the 80 MiB output limit.")
    result = value.upper() if upper else value.lower()
    _check_text_size(result)
    return result
