"""Evaluator for Power Query M expressions (values in ``values.py``, library in ``stdlib.py``).

Lazy by design: ``let`` bindings, record fields and function arguments are thunks that
run at most once, when read. Errors are ``MError`` exceptions; ``try`` catches them.
Operator rules and messages follow Power BI's answers (see the battery in the tests).
"""

from __future__ import annotations

import math
import sys
from typing import Any, Optional

from . import ast as A
from . import values as V
from .canonical import to_canonical
from .lexer import MSyntaxError
from .parser import parse
from .stdlib import GLOBALS
from .values import MError, MValue, Thunk, force


class Env:
    """A scope. ``hidden`` is set on the scope a binding's own initializer runs in: a plain reference to
    the binding's own name skips the enclosing scope (``let x = x in x`` fails), ``@x`` does not."""
    __slots__ = ("vars", "parent", "hidden")

    def __init__(self, variables: dict, parent: Optional["Env"] = None, hidden: Optional[str] = None):
        self.vars = variables
        self.parent = parent
        self.hidden = hidden

    def lookup(self, name: str, inclusive: bool = False) -> MValue:
        env: Optional[Env] = self
        while env is not None:
            if env.hidden == name and not inclusive:
                env = env.parent.parent if env.parent is not None else None
                continue
            if name in env.vars:
                return force(env.vars[name])
            env = env.parent
        if name == "_":
            raise MError("Expression.Error", "There is an unknown identifier. "
                         "Did you use the [field] shorthand for a _[field] outside of an 'each' expression?")
        raise MError("Expression.Error", f"The import {name} matches no exports. Did you miss a module reference?")


# ---- type nodes -------------------------------------------------------------

def type_of_node(node: A.Node) -> V.TypeValue:
    if isinstance(node, A.PrimitiveType):
        return V.TypeValue(node.name)
    if isinstance(node, A.NullableType):
        inner = type_of_node(node.inner)
        return V.TypeValue(inner.name, True)
    if isinstance(node, A.ListType):
        return V.TypeValue("list")
    if isinstance(node, A.RecordType):
        return V.TypeValue("record")
    if isinstance(node, A.TableType):
        return V.TypeValue("table")
    if isinstance(node, A.FunctionType):
        return V.TypeValue("function")
    raise MError("Expression.Error", "unknown type expression")


# ---- records, errors and functions -----------------------------------------

def _not_found_field(name: str, record: V.Record) -> MError:
    return MError("Expression.Error", f"The field '{name}' of the record wasn't found.", detail=record,
                  fmt="The field '#{0}' of the record wasn't found.", params=(V.Text(name),), code="10071")


def error_record(err: MError) -> V.Record:
    """The record that ``try`` puts in its Error field."""
    message = V.Text(err.message) if err.message is not None else V.Null()
    fmt = V.Text(err.fmt) if err.fmt is not None else V.Null()
    params = V.List(tuple(err.params)) if err.params is not None else V.Null()
    code = V.Text(err.code) if err.code is not None else V.Null()
    detail = err.detail if err.detail is not None else V.Null()
    return V.Record((
        ("Reason", V.Text(err.reason)), ("Message", message), ("Detail", detail),
        ("Message.Format", fmt), ("Message.Parameters", params), ("ErrorCode", code),
    ))


def _optional_text(record: V.Record, name: str) -> Optional[str]:
    item = record.get(name)
    if item is None or isinstance(item, V.Null):
        return None
    if isinstance(item, V.Text):
        return item.value
    raise V.convert_error(item, V.TypeValue("text"))


def error_from_value(value: MValue) -> MError:
    """What ``error <value>`` raises: text is the message; a record gives Reason, Message, Detail."""
    if isinstance(value, V.Text):
        return MError("Expression.Error", value.value, fmt=value.value)
    if isinstance(value, V.Record):
        if value.has("Reason"):
            reason_item = value.get("Reason")
            if not isinstance(reason_item, V.Text):
                raise V.convert_error(reason_item, V.TypeValue("text"))
            reason = reason_item.value
        else:
            reason = "Expression.Error"
        message = _optional_text(value, "Message")
        detail_item = value.get("Detail")
        detail = None if detail_item is None or isinstance(detail_item, V.Null) else detail_item
        fmt = _optional_text(value, "Message.Format")
        params_item = value.get("Message.Parameters")
        params = None
        if isinstance(params_item, V.List):
            params = tuple(force(item) for item in params_item.items)
        code = _optional_text(value, "ErrorCode")
        if fmt is not None:
            message = _format_message(fmt, params or ())
        return MError(reason, message, detail, fmt, params, code)
    raise V.convert_error(value, V.TypeValue("record"))


def _format_message(fmt: str, params: tuple) -> str:
    """Fill ``#{0}``-style placeholders of a Message.Format with the parameters' text."""
    out = fmt
    for index, item in enumerate(params):
        out = out.replace("#{%d}" % index, item.value if isinstance(item, V.Text) else V.describe_value(item))
    return out


def apply_function(fn: MValue, items: list) -> MValue:
    """Call a function value with lazy argument items (Thunk or MValue)."""
    if not isinstance(fn, V.Function):
        raise V.convert_error(fn, V.TypeValue("function"))
    specs = fn.params
    required = sum(1 for spec in specs if not spec.optional)
    if len(items) < required or len(items) > len(specs):
        expects = str(len(specs)) if required == len(specs) else f"between {required} and {len(specs)}"
        raise MError("Expression.Error",
                     f"{len(items)} arguments were passed to a function which expects {expects}.")
    bound: list = []
    for index, spec in enumerate(specs):
        if index < len(items):
            raw = items[index]
            if spec.type_ is not None:
                bound.append(Thunk(lambda raw=raw, t=spec.type_: V.check_type(force(raw), t)))
            else:
                bound.append(raw)
        else:
            bound.append(V.Null())
    result = fn.invoke(bound)
    if fn.return_type is not None:
        result = V.check_type(result, fn.return_type)
    return result


def _closure(params: tuple, return_type: Optional[V.TypeValue], body: A.Node, env: Env) -> V.Function:
    seen: set = set()
    for p in params:
        if p.name in seen:
            raise MError("Expression.Error", f"Duplicate parameter named '{p.name}'.")
        seen.add(p.name)
    specs = tuple(V.ParamSpec(p.name, type_of_node(p.type_) if p.type_ is not None else None, p.optional)
                  for p in params)

    def invoke(bound: list) -> MValue:
        scope = Env({spec.name: item for spec, item in zip(specs, bound)}, env)
        return evaluate(body, scope)

    return V.Function(specs, invoke, return_type)


# ---- logical -----------------------------------------------------------------

def _truth(value: MValue, op: str, left: MValue, right: MValue) -> Optional[bool]:
    if isinstance(value, V.Logical):
        return value.value
    if isinstance(value, V.Null):
        return None
    raise V.convert_error(value, V.TypeValue("logical"))


def _or_value(left: MValue, right_node: A.Node, env: Env) -> MValue:
    if isinstance(left, V.Logical) and left.value:
        return V.Logical(True)
    right = evaluate(right_node, env)
    l, r = _truth(left, "or", left, right), _truth(right, "or", left, right)
    if l is False:
        return right if isinstance(right, V.Logical) else V.Null()
    return V.Logical(True) if r is True else V.Null()


def _and_value(left: MValue, right_node: A.Node, env: Env) -> MValue:
    if isinstance(left, V.Logical) and not left.value:
        return V.Logical(False)
    right = evaluate(right_node, env)
    l, r = _truth(left, "and", left, right), _truth(right, "and", left, right)
    if r is False:
        return V.Logical(False)
    if l is True:
        return right if isinstance(right, V.Logical) else V.Null()
    return V.Null()


# ---- equality and comparison ------------------------------------------------

def equals(a: MValue, b: MValue) -> bool:
    if isinstance(a, V.Null) or isinstance(b, V.Null):
        return isinstance(a, V.Null) and isinstance(b, V.Null)
    kind = V.kind_of(a)
    if kind != V.kind_of(b):
        return False
    if kind in ("logical", "number", "text", "date", "binary"):
        return a.value == b.value
    if kind in ("time", "datetime", "duration"):
        return a.ticks == b.ticks
    if kind == "datetimezone":
        return V.utc_ticks(a) == V.utc_ticks(b)
    if kind == "list":
        return len(a.items) == len(b.items) and all(
            equals(force(x), force(y)) for x, y in zip(a.items, b.items))
    if kind == "record":
        if sorted(a.names()) != sorted(b.names()):
            return False
        return all(equals(a.get(name), b.get(name)) for name in a.names())
    if kind == "table":
        return a.columns == b.columns and len(a.rows) == len(b.rows) and all(
            all(equals(x, y) for x, y in zip(ra, rb)) for ra, rb in zip(a.rows, b.rows))
    if kind == "type":
        return a.name == b.name and a.nullable == b.nullable
    return a is b


_COMPARABLE = frozenset({"logical", "number", "text", "date", "time", "datetime", "datetimezone",
                         "duration", "binary"})


def _sort_key(value: MValue) -> Any:
    kind = V.kind_of(value)
    if kind == "logical":
        return int(value.value)
    if kind in ("number", "text", "date", "binary"):
        return value.value
    if kind == "datetimezone":
        return V.utc_ticks(value)
    return value.ticks  # time, datetime, duration


def _less(x: Any, y: Any) -> bool:
    """x < y; a NaN sorts below every number (and ``#nan < #nan`` is false), as in .NET's CompareTo."""
    if isinstance(x, float) and math.isnan(x):
        return not (isinstance(y, float) and math.isnan(y))
    if isinstance(y, float) and math.isnan(y):
        return False
    return x < y


# What null may be combined with (measured against Power BI): the other operand's kinds for which the result
# is null. Any other kind is an operator error that names the other operand first and null second.
_NULL_ARITHMETIC = {
    "+": frozenset({"number", "date", "time", "datetime", "datetimezone", "duration"}),
    "-": frozenset({"number", "date", "time", "datetime", "datetimezone", "duration"}),
    "*": frozenset({"number", "duration"}),
    "/": frozenset({"number", "duration"}),
    "&": frozenset({"text", "date", "time"}),
}
_SWAPPED_RELATION = {"<": ">", ">": "<", "<=": ">=", ">=": "<="}


def _null_operand(op: str, a: MValue, b: MValue, allowed: frozenset) -> MValue:
    """The result of ``a op b`` when at least one operand is null."""
    a_null, b_null = isinstance(a, V.Null), isinstance(b, V.Null)
    if a_null and b_null:
        return V.Null()
    other = b if a_null else a
    if V.kind_of(other) in allowed:
        return V.Null()
    if op in _SWAPPED_RELATION and a_null:
        op = _SWAPPED_RELATION[op]
    raise V.operator_error(op, other, V.Null())


def relational(op: str, a: MValue, b: MValue) -> MValue:
    """< <= > >=. Power BI names the types right to left for mixed kinds; copied from the battery."""
    if isinstance(a, V.Null) or isinstance(b, V.Null):
        return _null_operand(op, a, b, _COMPARABLE)
    ka, kb = V.kind_of(a), V.kind_of(b)
    if ka in _COMPARABLE and ka == kb:
        x, y = _sort_key(a), _sort_key(b)
        if op == "<":
            return V.Logical(_less(x, y))
        if op == ">":
            return V.Logical(_less(y, x))
        if op == ">=":
            return V.Logical(not _less(x, y))
        return V.Logical(not _less(y, x))  # <=
    if ka in _COMPARABLE:  # measured: a comparable left operand with any other kind reports ``<`` (b, a)
        raise V.operator_error("<", b, a)
    raise V.operator_error(op, a, b)


# ---- arithmetic -------------------------------------------------------------

def _num_op(op: str, x: float, y: float) -> float:
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if y == 0:
        if math.isnan(x) or x == 0:
            return math.nan
        return math.copysign(math.inf, x) * math.copysign(1.0, y)
    return x / y


def _scale_duration(ticks: int, factor: float) -> MValue:
    """Duration times a number (truncated to whole ticks); NaN, infinity or an overflow is a range error."""
    if math.isnan(factor) or math.isinf(factor):
        raise V.duration_range_error()
    return V.make_duration(int(ticks * factor))


def _divide_duration(ticks: int, divisor: float) -> MValue:
    if math.isnan(divisor) or divisor == 0:
        raise V.duration_range_error()
    return V.make_duration(int(ticks / divisor))


def arithmetic(op: str, a: MValue, b: MValue) -> MValue:
    if isinstance(a, V.Null) or isinstance(b, V.Null):
        return _null_operand(op, a, b, _NULL_ARITHMETIC[op])
    ka, kb = V.kind_of(a), V.kind_of(b)
    if ka == "number" and kb == "number":
        return V.Number(_num_op(op, a.value, b.value))
    sign = 1 if op == "+" else -1
    if ka == "duration" and kb == "duration":
        if op in "+-":
            return V.make_duration(a.ticks + sign * b.ticks)
        if op == "/":
            return V.Number(_num_op("/", float(a.ticks), float(b.ticks)))
    if ka == "duration" and kb == "number" and op == "*":
        return _scale_duration(a.ticks, b.value)
    if ka == "number" and kb == "duration" and op == "*":
        return _scale_duration(b.ticks, a.value)
    if ka == "duration" and kb == "number" and op == "/":
        return _divide_duration(a.ticks, b.value)
    if ka == "date" and kb == "duration" and op in "+-":
        return V.make_date_from_ticks(_floor_to_day(V.date_ticks(a.value) + sign * b.ticks))
    if ka == "duration" and kb == "date" and op == "+":
        return V.make_date_from_ticks(_floor_to_day(V.date_ticks(b.value) + a.ticks))
    if ka == "date" and kb == "date" and op == "-":
        return V.Duration(V.date_ticks(a.value) - V.date_ticks(b.value))
    if ka == "time" and kb == "duration" and op in "+-":
        return V.make_time(a.ticks + sign * b.ticks)
    if ka == "duration" and kb == "time" and op == "+":
        return V.make_time(b.ticks + a.ticks)
    if ka == "time" and kb == "time" and op == "-":
        return V.Duration(a.ticks - b.ticks)
    if ka == "datetime" and kb == "duration" and op in "+-":
        return V.make_datetime(a.ticks + sign * b.ticks)
    if ka == "duration" and kb == "datetime" and op == "+":
        return V.make_datetime(b.ticks + a.ticks)
    if ka == "datetime" and kb == "datetime" and op == "-":
        return V.Duration(a.ticks - b.ticks)
    if ka == "datetimezone" and kb == "duration" and op in "+-":
        return V.make_datetimezone(a.ticks + sign * b.ticks, a.offset_minutes)
    if ka == "duration" and kb == "datetimezone" and op == "+":
        return V.make_datetimezone(b.ticks + a.ticks, b.offset_minutes)
    if ka == "datetimezone" and kb == "datetimezone" and op == "-":
        return V.Duration(V.utc_ticks(a) - V.utc_ticks(b))
    raise V.operator_error(op, a, b)


def _floor_to_day(ticks: int) -> int:
    return ticks - ticks % V.TICKS_PER_DAY


def concat(a: MValue, b: MValue) -> MValue:
    if isinstance(a, V.Null) or isinstance(b, V.Null):
        return _null_operand("&", a, b, _NULL_ARITHMETIC["&"])
    if isinstance(a, V.Text) and (isinstance(b, V.Text) or isinstance(b, V.Null)):
        return V.Null() if isinstance(b, V.Null) else V.Text(a.value + b.value)
    if isinstance(a, V.Null) and isinstance(b, V.Text):
        return V.Null()
    if isinstance(a, V.List) and isinstance(b, V.List):
        return V.List(a.items + b.items)
    if isinstance(a, V.Record) and isinstance(b, V.Record):
        merged = list(a.fields)
        for name, item in b.fields:
            for k, (existing, _) in enumerate(merged):
                if existing == name:
                    merged[k] = (name, item)
                    break
            else:
                merged.append((name, item))
        return V.Record(tuple(merged))
    if isinstance(a, V.Date) and isinstance(b, V.Time):
        return V.DateTime(V.date_ticks(a.value) + b.ticks)
    if isinstance(a, V.Time) and isinstance(b, V.Date):
        return V.DateTime(V.date_ticks(b.value) + a.ticks)
    raise V.operator_error("&", a, b)


def _unary(op: str, value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    if op == "not":
        if isinstance(value, V.Logical):
            return V.Logical(not value.value)
        raise V.unary_error("not", value)
    kind = V.kind_of(value)
    if op == "+" and kind in ("number", "duration"):
        return value
    if op == "-" and kind == "number":
        if value.exact is not None:
            return V.Number(-value.value, exact=value.exact[1:] if value.exact[0] == "-" else "-" + value.exact)
        return V.Number(-value.value)
    if op == "-" and kind == "duration":
        return V.make_duration(-value.ticks)
    raise V.unary_error(op, value)


# ---- index, field and projection ------------------------------------------

def _as_number(value: MValue) -> float:
    if isinstance(value, V.Number):
        return value.value
    raise V.convert_error(value, V.TypeValue("number"))


def _field_access(target: MValue, name: str, optional: bool) -> MValue:
    if isinstance(target, V.Null):
        if optional:
            return V.Null()
        raise V.field_access_error(target, name)
    if not isinstance(target, V.Record):
        if optional:  # measured: Power BI reports a list conversion for ``5[a]?``
            raise V.convert_error(target, V.TypeValue("list"))
        raise V.field_access_error(target, name)
    if target.has(name):
        return target.get(name)
    if optional:
        return V.Null()
    raise _not_found_field(name, target)


def _item_access(node: A.ItemAccess, env: Env) -> MValue:
    target = evaluate(node.target, env)
    index = evaluate(node.index, env)
    if isinstance(target, V.Null):
        if node.optional:
            return V.Null()
        raise V.convert_error(target, V.TypeValue("list"))
    if not isinstance(target, V.List):
        raise V.convert_error(target, V.TypeValue("list"))
    if not isinstance(index, V.Number):
        shown = V.type_display(index)
        raise MError("Expression.Error", f"We cannot apply an index of type {shown}.",
                     detail=V.Record((("Value", target), ("Index", index))),
                     fmt="We cannot apply an index of type #{0}.", params=(V.Text(shown),), code="10058")
    k = V.to_int32(index)
    if k < 0:
        raise MError("Expression.Error", "The index cannot be negative.",
                     detail=V.Record((("Value", target), ("Index", index))),
                     fmt="The index cannot be negative.", code="10038")
    if k >= len(target.items):
        if node.optional:
            return V.Null()
        raise MError("Expression.Error",
                     "There weren't enough elements in the enumeration to complete the operation.",
                     detail=target, fmt="There weren't enough elements in the enumeration to complete the operation.",
                     code="10063")
    return force(target.items[k])


def _projection(node: A.Projection, env: Env) -> MValue:
    target = evaluate(node.target, env)
    if isinstance(target, V.Null) and node.optional:
        return V.Null()
    if not isinstance(target, V.Record):
        raise V.convert_error(target, V.TypeValue("record"))
    fields = []
    for name in node.names:
        if not target.has(name):
            if node.optional:
                fields.append((name, V.Null()))
                continue
            raise _not_found_field(name, target)
        fields.append((name, target.get(name)))
    return V.Record(tuple(fields))


def _raise(err: MError) -> MValue:
    raise err


# ---- ranges ---------------------------------------------------------------

_MAX_RANGE_ITEMS = 2_000_000  # this engine builds lists eagerly; refuse absurd ranges instead of exhausting memory


def _single_unit(text: str) -> int:
    """The UTF-16 code unit of a one-character text (the ends of a text range)."""
    if len(text) != 1 or ord(text) > 0xFFFF:
        raise MError("Expression.Error", "The value isn't a single-character string.")
    return ord(text)


def _range_items(start: MValue, end: MValue) -> list:
    if isinstance(start, V.Number) and isinstance(end, V.Number):
        low, high = V.to_int32(start), V.to_int32(end)
        make = lambda k: V.Number(float(k))
    elif isinstance(start, V.Text) and isinstance(end, V.Text):
        low, high = _single_unit(start.value), _single_unit(end.value)
        make = lambda k: V.Text(chr(k))
    else:
        raise V.operator_error("..", start, end)
    if high - low >= _MAX_RANGE_ITEMS:
        raise MError("Expression.Error", "The list range is too large for this engine.")
    return [make(k) for k in range(low, high + 1)]


# ---- the evaluator ----------------------------------------------------------

def evaluate(node: A.Node, env: Env) -> MValue:
    if isinstance(node, A.NumberLiteral):
        return V.number_from_literal(node.text)
    if isinstance(node, A.TextLiteral):
        return V.Text(node.value)
    if isinstance(node, A.LogicalLiteral):
        return V.Logical(node.value)
    if isinstance(node, A.NullLiteral):
        return V.Null()
    if isinstance(node, A.SpecialLiteral):
        return V.Number(math.inf if node.name == "infinity" else math.nan)
    if isinstance(node, A.Identifier):
        return env.lookup(node.name, node.inclusive)
    if isinstance(node, A.FieldSelector):
        return _field_access(env.lookup("_"), node.name, False)
    if isinstance(node, A.RecordExpr):
        scope = Env({}, env)
        for field in node.fields:
            if field.name in scope.vars:
                raise MError("Expression.Error", f"Duplicate field named '{field.name}'.")
            scope.vars[field.name] = Thunk(
                lambda field=field: evaluate(field.value, Env({}, scope, field.name)))
        return V.Record(tuple((field.name, scope.vars[field.name]) for field in node.fields))
    if isinstance(node, A.ListExpr):
        items: list = []
        for item in node.items:
            if isinstance(item, A.ListRange):
                items += _range_items(evaluate(item.start, env), evaluate(item.end, env))
            else:
                items.append(evaluate(item, env))
        return V.List(tuple(items))
    if isinstance(node, A.UnaryOp):
        return _unary(node.op, evaluate(node.operand, env))
    if isinstance(node, A.BinaryOp):
        return _binary(node, env)
    if isinstance(node, A.TypeOp):
        value = evaluate(node.operand, env)
        t = type_of_node(node.type_)
        if node.op == "is":
            return V.Logical(V.is_type(value, t))
        return V.check_type(value, t)
    if isinstance(node, A.TypeLiteral):
        return type_of_node(node.type_)
    if isinstance(node, A.FieldAccess):
        return _field_access(evaluate(node.target, env), node.name, node.optional)
    if isinstance(node, A.ItemAccess):
        return _item_access(node, env)
    if isinstance(node, A.Projection):
        return _projection(node, env)
    if isinstance(node, A.Invocation):
        fn = evaluate(node.target, env)
        items = [Thunk(lambda arg=arg: evaluate(arg, env)) for arg in node.args]
        return apply_function(fn, items)
    if isinstance(node, A.EachExpr):
        return V.Function((V.ParamSpec("_"),), lambda bound: evaluate(node.body, Env({"_": bound[0]}, env)))
    if isinstance(node, A.FunctionLiteral):
        return _closure(node.params, type_of_node(node.return_type) if node.return_type else None,
                        node.body, env)
    if isinstance(node, A.LetExpr):
        scope = Env({}, env)
        for binding in node.bindings:
            if binding.name in scope.vars:
                scope.vars[binding.name] = Thunk(lambda binding=binding: _raise(MError(
                    "Expression.Error", f"Duplicate initializer named '{binding.name}'.")))
                continue
            scope.vars[binding.name] = Thunk(
                lambda binding=binding: evaluate(binding.value, Env({}, scope, binding.name)))
        return evaluate(node.body, scope)
    if isinstance(node, A.IfExpr):
        condition = evaluate(node.condition, env)
        if not isinstance(condition, V.Logical):
            raise V.convert_error(condition, V.TypeValue("logical"))
        return evaluate(node.then_branch if condition.value else node.else_branch, env)
    if isinstance(node, A.ErrorExpr):
        raise error_from_value(evaluate(node.operand, env))
    if isinstance(node, A.TryExpr):
        return _try(node, env)
    raise MError("Expression.Error", f"unsupported expression {type(node).__name__}")


def _binary(node: A.BinaryOp, env: Env) -> MValue:
    op = node.op
    if op == "or":
        return _or_value(evaluate(node.left, env), node.right, env)
    if op == "and":
        return _and_value(evaluate(node.left, env), node.right, env)
    left = evaluate(node.left, env)
    right = evaluate(node.right, env)
    if op == "meta":
        base = left.meta if left.meta is not None else V.Record(())
        if not isinstance(right, V.Record):
            raise V.operator_error("&", base, right)
        return V.with_meta(left, concat(base, right))
    if op in ("=", "<>"):
        same = equals(left, right)
        return V.Logical(same if op == "=" else not same)
    if op in ("<", "<=", ">", ">="):
        return relational(op, left, right)
    if op == "&":
        return concat(left, right)
    return arithmetic(op, left, right)


def _try(node: A.TryExpr, env: Env) -> MValue:
    try:
        value = evaluate(node.operand, env)
    except MError as err:
        if node.otherwise is not None:
            return evaluate(node.otherwise, env)
        if node.catch is not None:
            return apply_function(evaluate(node.catch, env), [error_record(err)])
        return V.Record((("HasError", V.Logical(True)), ("Error", error_record(err))))
    if node.otherwise is not None or node.catch is not None:
        return value
    return V.Record((("HasError", V.Logical(False)), ("Value", value)))


# ---- the entry point used by callers ---------------------------------------

def root_env() -> Env:
    return Env(dict(GLOBALS))


def evaluate_to_text(source: str) -> str:
    """Power BI's answer text for an M expression: V:<canonical>, ERR:<Reason>: <Message>, or ERR:SYNTAX.

    No Python exception escapes: an M error becomes ``ERR:<Reason>: <Message>``; runaway recursion becomes
    ``ERR:Expression.Error: Evaluation stack overflow.`` and any other unexpected exception (an engine bug)
    becomes ``ERR:Expression.Error: Internal evaluation error (<ExceptionType>).``
    """
    previous_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(previous_limit, _RECURSION_LIMIT))
    try:
        return _evaluate_to_text(source)
    finally:
        sys.setrecursionlimit(previous_limit)


_RECURSION_LIMIT = 12000  # about 1500 nested M calls; deeper recursion is reported as a stack overflow


def _evaluate_to_text(source: str) -> str:
    try:
        node = parse(source)
    except MSyntaxError as err:
        return f"ERR:SYNTAX: {err.message}"
    except RecursionError:
        return "ERR:SYNTAX: The expression is nested too deeply."
    try:
        try:
            value = evaluate(node, root_env())
        except MError as err:
            return f"ERR:{err.reason}: {err.message or ''}"
        try:
            return "V:" + to_canonical(value)
        except MError:
            return "UNREPRESENTABLE"
    except RecursionError:
        return "ERR:Expression.Error: Evaluation stack overflow."
    except Exception as err:  # noqa: BLE001 - the contract is that nothing escapes; the type is reported
        return f"ERR:Expression.Error: Internal evaluation error ({type(err).__name__})."
