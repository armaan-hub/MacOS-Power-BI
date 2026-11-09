"""Power Query ``Table.*`` functions, the ``#table`` literal, table item and column access, ``Table.Type``,
``Type.TableSchema``, JoinKind, Splitter and Combiner (Task 107, m-table-97).

A table is ``V.Table(columns, rows)``: columns are ``(name, kind)`` pairs (kind "any", "number" or "text" here) and
rows are tuples of cells (values or Thunks). Cells stay lazy where a function keeps them lazy and are forced where a
function reads them.

Every answer is computed from the arguments. Messages are copied from the spec; a message pattern is generalised
only where the spec shows it (a column that is not in the table). A case whose answer is not measured raises
``_unsupported``: an explicit ERR, never a guessed value.
"""

from __future__ import annotations

import math
from functools import cmp_to_key
from typing import Callable, Optional

from . import values as V
from .canonical import number_text
from .list_fns import _hash_key, _order, compare
from .record_fns import MISSING_ERROR, MISSING_IGNORE, MISSING_USE_NULL, _exists, _missing, _missing_option
from .return_types import RETURN_TYPES
from .values import MError, MValue

_MAX_ROWS = 100_000  # longer results are not computed: no measured answer that large
_JOIN_INNER, _JOIN_LEFT_OUTER, _JOIN_LEFT_ANTI = 0, 1, 4


# ---- helpers ----------------------------------------------------------------

def _native(params: tuple, fn: Callable[..., MValue], return_type: Optional[V.TypeValue] = None) -> V.Function:
    specs = tuple(V.ParamSpec(name, None, optional) for name, optional in params)

    def invoke(bound: list) -> MValue:
        return fn(*[V.force(item) for item in bound])

    return V.Function(specs, invoke, return_type)


def _unsupported(what: str) -> MError:
    """Not a Power BI answer this engine has measured: an explicit ERR, never a guessed value."""
    return V.generic_error(f"The {what} is not supported by this engine yet.")


# ---- column types -------------------------------------------------------------
#
# A column's kind is a string. "any", "number" and "text" are the plain kinds: Any.Type (nullable), Number.Type and
# Text.Type (not nullable), exactly what ``#table(type table [c = number], ...)`` gives. Every other column type is
# written ``<kind>~<TypeName>~<1 or 0 for nullable>``, for example "text~Text.Type~1" or "number~Int32.Type~1".
# Table.Schema prints the TypeName and IsNullable, the table value prints the kind.

_PRIMITIVES = ("any", "anynonnull", "number", "text", "logical", "date", "time", "datetime", "datetimezone",
               "duration", "binary", "list", "record", "table", "function", "type", "null")
_NUMBER_TYPE_NAMES = ("Number", "Int8", "Int16", "Int32", "Int64", "Byte", "Double", "Decimal", "Currency",
                      "Percentage", "Single")
_PRIMITIVE_TYPE_NAMES = {"any": "Any", "number": "Number", "text": "Text", "logical": "Logical", "date": "Date",
                         "time": "Time", "datetime": "DateTime", "datetimezone": "DateTimeZone",
                         "duration": "Duration", "binary": "Binary", "list": "List", "record": "Record",
                         "table": "Table", "function": "Function", "type": "Type", "null": "Null"}
_KIND_OF_TYPE_NAME = {name + ".Type": kind for kind, name in _PRIMITIVE_TYPE_NAMES.items()}
_KIND_OF_TYPE_NAME.update({name + ".Type": "number" for name in _NUMBER_TYPE_NAMES})
_KIND_OF_TYPE_NAME["Character.Type"] = "text"
_NULLABLE_BY_DEFAULT = ("any", "null")


def _col(type_name: str, nullable: bool) -> str:
    """The kind string of a column with this Table.Schema TypeName and nullability."""
    base = _KIND_OF_TYPE_NAME.get(type_name)
    if base is None:
        raise _unsupported("column type " + type_name)
    if type_name == _PRIMITIVE_TYPE_NAMES[base] + ".Type" and nullable == (base in _NULLABLE_BY_DEFAULT):
        return base
    return f"{base}~{type_name}~{int(nullable)}"


def _parts(kind: str) -> tuple:
    """(base kind, TypeName, nullable) of a column kind string."""
    if "~" in kind:
        base, type_name, nullable = kind.split("~")
        return base, type_name, nullable == "1"
    return kind, _PRIMITIVE_TYPE_NAMES[kind] + ".Type", kind in _NULLABLE_BY_DEFAULT


def _base(kind: str) -> str:
    return kind.split("~")[0]


def _plain(kind: str) -> str:
    """A kind that the caller's rule was measured with: refuse the richer column types."""
    if "~" in kind:
        raise _unsupported("column of type " + kind.split("~")[1] + " here")
    return kind


def _type_spec(type_value: MValue) -> str:
    """The column kind a type value ascribes: ``type nullable text`` is a nullable Text.Type column."""
    if not isinstance(type_value, V.TypeValue) or type_value.name not in _PRIMITIVES:
        raise _unsupported("column type")
    if type_value.name == "anynonnull":
        return _col("Any.Type", False)
    nullable = type_value.nullable or type_value.name in _NULLABLE_BY_DEFAULT
    if type_value.label is not None:  # a subtype constant such as Int64.Type keeps its own TypeName
        return _col(type_value.label, nullable)
    return _col(_PRIMITIVE_TYPE_NAMES[type_value.name] + ".Type", nullable)


def _type_argument(value: MValue) -> Optional[str]:
    """An optional columnType argument: null means "not given", a type gives its kind, anything else is Power BI's
    conversion error."""
    if isinstance(value, V.Null):
        return None
    if not isinstance(value, V.TypeValue):
        raise V.convert_error(value, V.TypeValue("type"))
    return _type_spec(value)


_LIBRARY_NAMES: dict = {}


def _library_name(fn: V.Function) -> Optional[str]:
    if not _LIBRARY_NAMES:
        from .stdlib import GLOBALS  # local import: the stdlib imports this module

        for name, value in GLOBALS.items():
            if isinstance(value, V.Function):
                _LIBRARY_NAMES.setdefault(id(value), name)
    return _LIBRARY_NAMES.get(id(fn))


def _function_spec(fn: V.Function) -> str:
    """The column kind Power BI gives to a column that this function produces: the function's declared return type.
    A function written in M without a return type (``each ...``) is any. A library function uses the type measured
    for it. A function whose type is not known is refused."""
    if fn.origin is not None:
        return _type_spec(fn.return_type) if fn.return_type is not None else "any"
    name = _library_name(fn)
    if name in RETURN_TYPES:
        return _col(*RETURN_TYPES[name])
    if fn.return_type is not None:  # a combiner made by Combiner.CombineTextByDelimiter
        return _type_spec(fn.return_type)
    raise _unsupported("column type of this function")


def _is_library(fn: MValue, name: str) -> bool:
    return isinstance(fn, V.Function) and fn.origin is None and _library_name(fn) == name


def _apply(fn: MValue, *args) -> MValue:
    from .evaluator import apply_function  # local import: the evaluator imports the stdlib

    return apply_function(fn, list(args))


def _equals(a: MValue, b: MValue) -> bool:
    from .evaluator import equals  # local import: the evaluator imports the stdlib

    return equals(a, b)


def _column_missing(name: str) -> MError:
    return MError("Expression.Error", f"The column '{name}' of the table wasn't found.",
                  fmt="The column '#{0}' of the table wasn't found.", params=(V.Text(name),))


def _sort_invalid() -> MError:
    return MError("Expression.Error", "The specified sort criteria is invalid.",
                  fmt="The specified sort criteria is invalid.")


def _distinct_invalid() -> MError:
    return MError("Expression.Error", "The specified distinct criteria is invalid.",
                  fmt="The specified distinct criteria is invalid.")


def _table(value: MValue) -> V.Table:
    if isinstance(value, V.Table):
        return value
    raise V.convert_error(value, V.TypeValue("table"))


def _text(value: MValue) -> str:
    if isinstance(value, V.Text):
        return value.value
    raise V.convert_error(value, V.TypeValue("text"))


def _items(value: MValue) -> list:
    if isinstance(value, V.List):
        return [V.force(item) for item in value.items]
    raise V.convert_error(value, V.TypeValue("list"))


def _count(value: MValue) -> int:
    """A whole, non-negative number (a count or an offset)."""
    if not isinstance(value, V.Number):
        raise V.convert_error(value, V.TypeValue("number"))
    x = value.value
    if math.isfinite(x) and x == math.floor(x) and 0 <= x < 2 ** 31:
        return int(x)
    raise _unsupported("count that is not a whole number")


def _count_or(value: MValue, default: int) -> int:
    return default if isinstance(value, V.Null) else _count(value)


def _integer(value: MValue, default: int) -> int:
    """A whole number that may be negative (an index start or increment)."""
    if isinstance(value, V.Null):
        return default
    if isinstance(value, V.Number) and math.isfinite(value.value) and value.value == math.floor(value.value) \
            and abs(value.value) < 2 ** 31:
        return int(value.value)
    raise _unsupported("number that is not a whole number")


def _names(value: MValue) -> list:
    """A column name, or a list of column names."""
    if isinstance(value, V.Text):
        return [value.value]
    return [_text(item) for item in _items(value)]


def _names_of(table: V.Table) -> list:
    return [name for name, _ in table.columns]


def _index(table: V.Table, name: str) -> int:
    names = _names_of(table)
    if name not in names:
        raise _column_missing(name)
    return names.index(name)


def _no_repeat(names: list) -> None:
    if len(set(names)) != len(names):
        raise _unsupported("column list with a repeated name")


def _unique_or_refuse(names: list) -> None:
    if len(set(names)) != len(names):
        raise _unsupported("result with a repeated column name")


def _record(names: list, row: tuple) -> V.Record:
    return V.Record(tuple(zip(names, row)))


def _truth(value: MValue) -> bool:
    if isinstance(value, V.Logical):
        return value.value
    raise V.convert_error(value, V.TypeValue("logical"))


def _record_arg(value: MValue) -> V.Record:
    if isinstance(value, V.Record):
        return value
    raise V.convert_error(value, V.TypeValue("record"))


def _missing_mode(value: MValue, allowed: tuple) -> int:
    mode = _missing_option(value)
    if mode not in allowed:
        raise _unsupported("MissingField option")
    return mode


def _no_option(value: MValue, what: str) -> None:
    """An optional argument this module does not model: given (not null) means refused."""
    if not isinstance(value, V.Null):
        raise _unsupported(what)


def _key(values: tuple) -> tuple:
    keys = tuple(_hash_key(value) for value in values)
    if any(key is None for key in keys):
        raise _unsupported("value without an equality key")
    return keys


def _cell_text(value: MValue):
    """Text of a cell for FindText: None for null, the text, "true"/"false", or a whole number's text."""
    if isinstance(value, V.Null):
        return None
    if isinstance(value, V.Text):
        return value.value
    if isinstance(value, V.Logical):
        return "true" if value.value else "false"
    if isinstance(value, V.Number) and math.isfinite(value.value) and value.value == math.floor(value.value) \
            and abs(value.value) < 2 ** 53:
        return number_text(value.value)
    raise _unsupported("cell that is not text, a whole number or a logical value in FindText")


def _projection_matches(names: list, row: tuple, criteria: V.Record) -> bool:
    """A row matches a record when every field of the record is a column whose cell equals the field value."""
    for field, item in criteria.fields:
        if field not in names:
            return False
        if not _equals(V.force(row[names.index(field)]), V.force(item)):
            return False
    return True


def _check_cell(value: MValue, kind: str) -> None:
    base, _type_name, nullable = _parts(kind)
    if isinstance(value, V.Null):
        if not nullable:
            raise _unsupported(f"{base} column with a null cell")
    elif base != "any" and V.kind_of(value) != base:
        raise _unsupported(f"{base} column with a cell of another type")


def _row_has_error(row: tuple) -> bool:
    for cell in row:
        try:
            V.force(cell)
        except MError:
            return True
    return False


# ---- the #table literal, the table type and schema -----------------------------

def _literal_columns(columns: MValue) -> list:
    if isinstance(columns, V.Number):
        return [(f"Column{i}", "any") for i in range(1, _count(columns) + 1)]
    if isinstance(columns, V.TypeValue) and columns.name == "table":
        if not columns.fields:
            raise _unsupported("table type without columns")
        out = []
        for name, field_type, optional in columns.fields:
            if optional:
                raise _unsupported("optional column in a table type")
            out.append((name, _type_spec(field_type)))
        return out
    return [(name, "any") for name in _names(columns)]


def _table_literal(columns: MValue, rows: MValue) -> V.Table:
    cols = _literal_columns(columns)
    seen = set()
    for name, _kind in cols:
        if name in seen:
            raise _exists(name)
        seen.add(name)
    out = []
    for row in _items(rows):
        cells = _items(row)
        if len(cells) != len(cols):
            raise _unsupported("table row whose length differs from the column count")
        for (_name, kind), cell in zip(cols, cells):
            _check_cell(cell, kind)
        out.append(tuple(cells))
    return V.Table(tuple(cols), tuple(out))


_SCHEMA_COLUMNS = (
    ("Name", "text"), ("Position", "number"), ("TypeName", "text"), ("Kind", "text"), ("IsNullable", "logical"),
    ("NumericPrecisionBase", "number"), ("NumericPrecision", "number"), ("NumericScale", "number"),
    ("IsSigned", "logical"), ("DateTimePrecision", "number"), ("MaxLength", "number"),
    ("IsVariableLength", "logical"), ("NativeTypeName", "text"), ("NativeDefaultExpression", "text"),
    ("NativeExpression", "text"), ("Description", "text"), ("IsWritable", "logical"), ("FieldCaption", "text"),
)


def _schema_of(entries: list) -> V.Table:
    rows = []
    for position, (name, spec) in enumerate(entries):
        base, type_name, nullable = _parts(spec)
        cells = [V.Text(name), V.Number(float(position)), V.Text(type_name), V.Text(base), V.Logical(nullable)]
        cells += [V.Null()] * (len(_SCHEMA_COLUMNS) - len(cells))
        rows.append(tuple(cells))
    return V.Table(_SCHEMA_COLUMNS, tuple(rows))


def _type_table_schema(value: MValue) -> V.Table:
    if not (isinstance(value, V.TypeValue) and value.name == "table" and value.fields is not None):
        raise _unsupported("schema of this type")
    entries = []
    for name, field_type, optional in value.fields:
        if optional:
            raise _unsupported("optional column in a table type")
        entries.append((name, _type_spec(field_type)))
    return _schema_of(entries)


# ---- counting, access and conversion of rows and columns ----------------------

def _row_count(table: MValue) -> MValue:
    return V.Number(float(len(_table(table).rows)))


def _column_count(table: MValue) -> MValue:
    return V.Number(float(len(_table(table).columns)))


def _column_names(table: MValue) -> MValue:
    return V.List(tuple(V.Text(name) for name in _names_of(_table(table))))


def _to_records(table: MValue) -> MValue:
    t = _table(table)
    names = _names_of(t)
    return V.List(tuple(_record(names, row) for row in t.rows))


def _to_rows(table: MValue) -> MValue:
    t = _table(table)
    return V.List(tuple(V.List(tuple(row)) for row in t.rows))


def _to_columns(table: MValue) -> MValue:
    t = _table(table)
    return V.List(tuple(V.List(tuple(row[i] for row in t.rows), None, False, t.columns[i][1])
                        for i in range(len(t.columns))))


def _to_list(table: MValue, combiner: MValue) -> MValue:
    t = _table(table)
    if isinstance(combiner, V.Null):
        combiner = _combine_by_delimiter(V.Text(","), V.Null())
    elif not isinstance(combiner, V.Function):
        raise V.convert_error(combiner, V.TypeValue("function"))
    return V.List(tuple(V.Thunk(lambda row=row: _apply(combiner, V.List(tuple(row)))) for row in t.rows))


def _first(table: MValue, default: MValue) -> MValue:
    t = _table(table)
    if t.rows:
        return _record(_names_of(t), t.rows[0])
    return default


def _last(table: MValue, default: MValue) -> MValue:
    t = _table(table)
    if t.rows:
        return _record(_names_of(t), t.rows[-1])
    return default


def _is_empty(table: MValue) -> MValue:
    return V.Logical(not _table(table).rows)


def _column(table: MValue, name: MValue) -> MValue:
    t = _table(table)
    i = _index(t, _text(name))
    return V.List(tuple(row[i] for row in t.rows), None, False, t.columns[i][1])


def _keys(table: MValue) -> MValue:
    _table(table)
    return V.List(())


def _has_columns(table: MValue, names: MValue) -> MValue:
    t = _table(table)
    current = _names_of(t)
    return V.Logical(all(name in current for name in _names(names)))


def _transpose(table: MValue) -> MValue:
    t = _table(table)
    if not t.rows:
        return V.Table((), ())
    if not t.columns:
        raise _unsupported("transpose of a table with rows and no columns")
    columns = tuple((f"Column{i}", "any") for i in range(1, len(t.rows) + 1))
    rows = tuple(tuple(row[i] for row in t.rows) for i in range(len(t.columns)))
    return V.Table(columns, rows)


def _schema(table: MValue) -> MValue:
    t = _table(table)
    return _schema_of([(name, kind) for name, kind in t.columns])


def _buffer(table: MValue) -> MValue:
    return _table(table)


def _demote_headers(table: MValue) -> MValue:
    t = _table(table)
    names = _names_of(t)
    if not names:
        raise _unsupported("demoted headers of a table without columns")
    header = tuple(V.Text(name) for name in names)
    columns = tuple((f"Column{i}", "any") for i in range(1, len(names) + 1))
    return V.Table(columns, (header,) + t.rows)


def _promote_headers(table: MValue, options: MValue) -> MValue:
    _no_option(options, "PromoteHeaders option")
    t = _table(table)
    if not t.rows:
        return V.Table(t.columns, ())
    names = []
    for i, cell in enumerate(t.rows[0]):
        value = V.force(cell)
        if isinstance(value, V.Null):
            names.append(f"Column{i + 1}")
        elif isinstance(value, V.Text):
            names.append(value.value)
        elif isinstance(value, V.Number) and math.isfinite(value.value) and value.value == math.floor(value.value) \
                and abs(value.value) < 2 ** 53:
            names.append(number_text(value.value))
        else:
            raise _unsupported("header that is not text")
    _unique_or_refuse(names)
    columns = tuple((name, kind) for name, (_, kind) in zip(names, t.columns))
    return V.Table(columns, t.rows[1:])


def _reverse_rows(table: MValue) -> MValue:
    t = _table(table)
    return V.Table(t.columns, tuple(reversed(t.rows)))


def _first_n(table: MValue, count: MValue) -> MValue:
    t = _table(table)
    return V.Table(t.columns, t.rows[:_count(count)])


def _last_n(table: MValue, count: MValue) -> MValue:
    t = _table(table)
    n = _count(count)
    return V.Table(t.columns, t.rows[max(0, len(t.rows) - n):])


def _remove_first_n(table: MValue, count: MValue) -> MValue:
    t = _table(table)
    return V.Table(t.columns, t.rows[_count_or(count, 1):])


def _remove_last_n(table: MValue, count: MValue) -> MValue:
    t = _table(table)
    n = _count_or(count, 1)
    return V.Table(t.columns, t.rows[:max(0, len(t.rows) - n)])


def _range(table: MValue, offset: MValue, count: MValue) -> MValue:
    t = _table(table)
    start = _count(offset)
    if isinstance(count, V.Null):
        return V.Table(t.columns, t.rows[start:])
    return V.Table(t.columns, t.rows[start:start + _count(count)])


def _repeat(table: MValue, count: MValue) -> MValue:
    t = _table(table)
    n = _count(count)
    if len(t.rows) * n > _MAX_ROWS:
        raise _unsupported("repeat of this size")
    return V.Table(t.columns, t.rows * n)


# ---- columns ----------------------------------------------------------------

def _select_columns(table: MValue, names: MValue, missing: MValue) -> MValue:
    t = _table(table)
    mode = _missing_mode(missing, (MISSING_ERROR, MISSING_USE_NULL))
    wanted = _names(names)
    _no_repeat(wanted)
    current = _names_of(t)
    columns, picks = [], []
    for name in wanted:
        if name in current:
            i = current.index(name)
            columns.append((name, t.columns[i][1]))
            picks.append(i)
        elif mode == MISSING_ERROR:
            raise _column_missing(name)
        else:
            columns.append((name, "null"))
            picks.append(None)
    rows = tuple(tuple(row[i] if i is not None else V.Null() for i in picks) for row in t.rows)
    return V.Table(tuple(columns), rows)


def _remove_columns(table: MValue, names: MValue, missing: MValue) -> MValue:
    t = _table(table)
    _missing_mode(missing, (MISSING_ERROR,))
    wanted = _names(names)
    _no_repeat(wanted)
    current = _names_of(t)
    for name in wanted:
        if name not in current:
            raise _column_missing(name)
    keep = [i for i, (name, _) in enumerate(t.columns) if name not in wanted]
    if not keep and t.rows:
        raise _unsupported("table without columns but with rows")
    return V.Table(tuple(t.columns[i] for i in keep), tuple(tuple(row[i] for i in keep) for row in t.rows))


def _reorder_columns(table: MValue, names: MValue, missing: MValue) -> MValue:
    t = _table(table)
    _missing_mode(missing, (MISSING_ERROR,))
    wanted = _names(names)
    _no_repeat(wanted)
    current = _names_of(t)
    for name in wanted:
        if name not in current:
            raise _column_missing(name)
    order = [current.index(name) for name in wanted] + [i for i, name in enumerate(current) if name not in wanted]
    return V.Table(tuple(t.columns[i] for i in order), tuple(tuple(row[i] for i in order) for row in t.rows))


def _rename_pairs(renames: MValue) -> list:
    items = _items(renames)
    if items and isinstance(items[0], V.Text):  # one flat pair: {old, new}
        if len(items) != 2 or not isinstance(items[1], V.Text):
            raise _unsupported("rename list")
        return [(items[0].value, items[1].value)]
    pairs = []
    for item in items:
        pair = _items(item)
        if len(pair) != 2:
            raise _unsupported("rename pair")
        pairs.append((_text(pair[0]), _text(pair[1])))
    return pairs


def _rename_columns(table: MValue, renames: MValue, missing: MValue) -> MValue:
    t = _table(table)
    _missing_mode(missing, (MISSING_ERROR,))
    pairs = _rename_pairs(renames)
    olds = [old for old, _ in pairs]
    _no_repeat(olds)
    for old, new in pairs:
        if old == new or new in olds:
            raise _unsupported("rename that chains or does nothing")
    names = _names_of(t)
    for old, new in pairs:
        if old not in names:
            raise _column_missing(old)
        if new in names:
            raise _exists(new)
        names[names.index(old)] = new
    return V.Table(tuple((name, kind) for name, (_, kind) in zip(names, t.columns)), t.rows)


def _transform_pairs(transforms: MValue) -> list:
    """The ``{name, function}`` or ``{name, function, type}`` entries as (name, function, kind or None)."""
    items = _items(transforms)
    entries = [items] if items and isinstance(items[0], V.Text) else [_items(item) for item in items]
    pairs = []
    for entry in entries:
        if len(entry) not in (2, 3):
            raise _unsupported("transform list")
        explicit = None
        if len(entry) == 3:
            if not isinstance(entry[2], V.TypeValue):
                raise _unsupported("column type of a transform")
            explicit = _type_spec(entry[2])
        pairs.append((_text(entry[0]), entry[1], explicit))
    return pairs


def _transformed_kind(fn: V.Function, explicit: Optional[str], old: str) -> str:
    """The kind of a column rewritten by ``fn``. A function that only returns its argument (``each _``) leaves the
    column as it is. Otherwise an explicit type wins, then the function's declared return type."""
    if fn.origin == "identity":
        return old
    return explicit if explicit is not None else _function_spec(fn)


def _transform_columns(table: MValue, transforms: MValue, default: MValue, missing: MValue) -> MValue:
    t = _table(table)
    mode = _missing_mode(missing, (MISSING_ERROR, MISSING_IGNORE))
    if not isinstance(default, V.Null) and not isinstance(default, V.Function):
        raise _unsupported("defaultTransformation argument that is not a function")
    fns: dict = {}
    for name, fn, explicit in _transform_pairs(transforms):
        if name not in _names_of(t) and mode == MISSING_IGNORE:
            continue
        i = _index(t, name)
        if i in fns:
            raise _unsupported("column transformed twice")
        if not isinstance(fn, V.Function):
            raise V.convert_error(fn, V.TypeValue("function"))
        fns[i] = (fn, explicit)
    if isinstance(default, V.Function):
        for i in range(len(t.columns)):
            fns.setdefault(i, (default, None))
    rows = []
    for row in t.rows:
        cells = list(row)
        for i, (fn, _explicit) in fns.items():
            if fn.origin == "identity":
                continue
            cells[i] = V.Thunk(lambda cell=row[i], fn=fn: _apply(fn, cell))
        rows.append(tuple(cells))
    columns = tuple((name, _transformed_kind(fns[i][0], fns[i][1], kind) if i in fns else kind)
                    for i, (name, kind) in enumerate(t.columns))
    return V.Table(columns, tuple(rows))


def _convert_cell(value: MValue, type_name: str) -> MValue:
    if isinstance(value, V.Null):
        return value
    if type_name == "text":
        if isinstance(value, V.Text):
            return value
        if isinstance(value, V.Number):
            return V.Text(number_text(value.value))
        raise _unsupported("conversion to text of this value")
    if type_name == "number" and isinstance(value, V.Number):
        return value
    raise _unsupported("column type conversion")


def _transform_column_types(table: MValue, transforms: MValue, culture: MValue) -> MValue:
    t = _table(table)
    _no_option(culture, "culture argument")
    changes: dict = {}
    for item in _items(transforms):
        pair = _items(item)
        if len(pair) != 2 or not isinstance(pair[1], V.TypeValue):
            raise _unsupported("column type transform")
        i = _index(t, _text(pair[0]))
        type_value = pair[1]
        if type_value.nullable or type_value.name not in ("text", "number") or i in changes:
            raise _unsupported("column type transform")
        changes[i] = type_value.name
    kinds = {i: _col(_PRIMITIVE_TYPE_NAMES[name] + ".Type", True) for i, name in changes.items()}
    rows = []
    for row in t.rows:
        cells = list(row)
        for i, type_name in changes.items():
            cells[i] = _convert_cell(V.force(row[i]), type_name)
        rows.append(tuple(cells))
    columns = tuple((name, kinds.get(i, kind)) for i, (name, kind) in enumerate(t.columns))
    return V.Table(columns, tuple(rows))


def _replaced_kind(replacer: V.Function, old_kind: str, new: MValue) -> str:
    """The kind of a column after Table.ReplaceValue. Replacer.ReplaceValue keeps the column's type when the new
    value fits it, makes it nullable for a null, and otherwise turns it into any; any other replacer gives the
    column its declared return type."""
    if not _is_library(replacer, "Replacer.ReplaceValue"):
        return _function_spec(replacer)
    base, type_name, _nullable = _parts(old_kind)
    if base not in ("any", "number", "text"):
        raise _unsupported("replacement in a " + base + " column")
    if base == "any":
        return old_kind
    if isinstance(new, V.Null):
        return _col(type_name, True)
    return old_kind if V.kind_of(new) == base else "any"


def _replace_value_table(table: MValue, old: MValue, new: MValue, replacer: MValue, columns: MValue) -> MValue:
    t = _table(table)
    names = _names_of(t) if isinstance(columns, V.Null) else _names(columns)
    _no_repeat(names)
    targets = [_index(t, name) for name in names]
    if not isinstance(replacer, V.Function):
        raise V.convert_error(replacer, V.TypeValue("function"))
    rows = []
    for row in t.rows:
        cells = list(row)
        for i in targets:
            cells[i] = V.Thunk(lambda cell=row[i]: _apply(replacer, V.force(cell), old, new))
        rows.append(tuple(cells))
    kinds = {i: _replaced_kind(replacer, t.columns[i][1], new) for i in targets}
    return V.Table(tuple((name, kinds.get(i, kind)) for i, (name, kind) in enumerate(t.columns)), tuple(rows))


def _fill(table: MValue, columns: MValue, down: bool) -> MValue:
    t = _table(table)
    names = _names(columns)
    _no_repeat(names)
    targets = [_index(t, name) for name in names]
    rows = [list(row) for row in t.rows]
    order = list(range(len(rows))) if down else list(range(len(rows) - 1, -1, -1))
    for i in targets:
        last = None
        for r in order:
            value = V.force(rows[r][i])
            if isinstance(value, V.Null):
                if last is not None:
                    rows[r][i] = last
            else:
                last = value
                rows[r][i] = value
    return V.Table(t.columns, tuple(tuple(row) for row in rows))


def _add_column(table: MValue, name: MValue, selector: MValue, kind: MValue) -> MValue:
    t = _table(table)
    new = _text(name)
    names = _names_of(t)
    if new in names:
        raise _exists(new)
    if not isinstance(selector, V.Function):
        raise V.convert_error(selector, V.TypeValue("function"))
    explicit = _type_argument(kind)
    new_kind = explicit if explicit is not None else _function_spec(selector)
    rows = []
    for row in t.rows:
        cell = V.Thunk(lambda row=row: _apply(selector, _record(names, row)))
        rows.append(tuple(row) + (cell,))
    return V.Table(t.columns + ((new, new_kind),), tuple(rows))


def _add_index_column(table: MValue, name: MValue, start: MValue, step: MValue, kind: MValue) -> MValue:
    t = _table(table)
    new = _text(name)
    explicit = _type_argument(kind)
    if new in _names_of(t):
        raise _unsupported("index column over an existing column name")
    first = _integer(start, 0)
    increment = _integer(step, 1)
    rows = tuple(tuple(row) + (V.Number(float(first + i * increment)),) for i, row in enumerate(t.rows))
    return V.Table(t.columns + ((new, explicit if explicit is not None else "number"),), rows)


def _duplicate_column(table: MValue, source: MValue, name: MValue, kind: MValue) -> MValue:
    t = _table(table)
    i = _index(t, _text(source))
    new = _text(name)
    explicit = _type_argument(kind)
    if new in _names_of(t):
        raise _unsupported("duplicate onto an existing column name")
    rows = tuple(tuple(row) + (row[i],) for row in t.rows)
    return V.Table(t.columns + ((new, explicit if explicit is not None else t.columns[i][1]),), rows)


_EXTRA_LIST, _EXTRA_ERROR, _EXTRA_IGNORE = 0, 1, 2
_SPLIT_MAX_COLUMNS = 1000


def _split_column(table: MValue, column: MValue, splitter: MValue, names_arg: MValue, default: MValue,
                  extra: MValue) -> MValue:
    """Table.SplitColumn with a splitter made by the Splitter functions. Without columnNamesOrNumber the number of
    new columns is the number of parts of the FIRST row (none if that cell is null); later rows are padded with
    the default (null) or cut (ExtraValues.Ignore, the default). ExtraValues.List puts the parts from the last
    new column on into that column as a list."""
    t = _table(table)
    name = _text(column)
    names = _names_of(t)
    if name not in names:
        raise _missing(name)
    i = names.index(name)
    if not isinstance(splitter, V.Function):
        raise V.convert_error(splitter, V.TypeValue("function"))
    if splitter.origin is not None:
        raise _unsupported("column type of a splitter written in M")
    if isinstance(extra, V.Null):
        mode = _EXTRA_IGNORE
    elif isinstance(extra, V.Number) and extra.value in (_EXTRA_LIST, _EXTRA_ERROR, _EXTRA_IGNORE):
        mode = int(extra.value)
    else:
        raise _unsupported("extraColumns argument")

    def parts_of(cell: MValue):
        cell = V.force(cell)
        if isinstance(cell, V.Null):
            return None
        return [_text(part) for part in _items(_apply(splitter, cell))]

    new_names = None
    if isinstance(names_arg, V.Null):
        count = None
    elif isinstance(names_arg, V.List):
        new_names = []
        for item in _items(names_arg):
            if isinstance(item, V.Null):
                raise V.convert_error(item, V.TypeValue("text"))
            if not isinstance(item, V.Text):
                raise _unsupported("column name that is not text")
            new_names.append(item.value)
        if len(set(new_names)) != len(new_names):
            raise _unsupported("repeated new column name")
        count = len(new_names)
    elif isinstance(names_arg, V.Number):
        if names_arg.value < 0:
            raise _split_argument_invalid()
        if names_arg.value != math.floor(names_arg.value) or names_arg.value > _SPLIT_MAX_COLUMNS:
            raise _unsupported("number of columns that is not a small whole number")
        count = int(names_arg.value)
    elif isinstance(names_arg, (V.Text, V.Logical)):
        raise _split_argument_invalid()
    else:
        raise _unsupported("columnNamesOrNumberOfColumns argument")
    first = None
    if count is None:
        first = parts_of(t.rows[0][i]) if t.rows else None
        count = len(first) if first is not None else 0
        if count > _SPLIT_MAX_COLUMNS:
            raise _unsupported("split into this many columns")
    if new_names is None:
        new_names = [f"{name}.{k}" for k in range(1, count + 1)]
    for new in new_names:
        if new != name and new in names:
            raise _exists(new)
    parts_per_row = [first if (r == 0 and first is not None) else parts_of(row[i]) for r, row in enumerate(t.rows)] \
        if count else [None] * len(t.rows)
    if mode == _EXTRA_ERROR and any(parts is not None and len(parts) > count for parts in parts_per_row):
        raise _unsupported("extra values that are an error")
    columns = []
    for j, (cname, kind) in enumerate(t.columns):
        if j == i:
            columns += [(new, _col("Text.Type", True)) for new in new_names]
        else:
            columns.append((cname, kind))
    rows = []
    for row, parts in zip(t.rows, parts_per_row):
        cells = []
        for j, cell in enumerate(row):
            if j != i:
                cells.append(cell)
                continue
            for k in range(count):
                if mode == _EXTRA_LIST and k == count - 1:
                    cells.append(V.List(tuple(V.Text(part) for part in (parts or [])[k:])))
                elif parts is not None and k < len(parts):
                    cells.append(V.Text(parts[k]))
                else:
                    cells.append(default)
        rows.append(tuple(cells))
    return V.Table(tuple(columns), tuple(rows))


def _split_argument_invalid() -> MError:
    message = "The argument 'columnNamesOrNumber' should be a list or a non-negative number."
    return MError("Expression.Error", message, fmt=message)


def _combine_columns(table: MValue, columns: MValue, combiner: MValue, name: MValue) -> MValue:
    """The combined column goes where the last listed column was (among the columns that stay) and has the
    combiner's declared return type."""
    t = _table(table)
    if not isinstance(columns, V.List):
        raise V.convert_error(columns, V.TypeValue("list"))
    selected = _names(columns)
    for k, column in enumerate(selected):
        if column in selected[:k]:
            raise _exists(column)
    indexes = [_index(t, column) for column in selected]
    new = _text(name)
    if not isinstance(combiner, V.Function):
        raise V.convert_error(combiner, V.TypeValue("function"))
    if not indexes:
        raise _unsupported("combination of no columns")
    kept = [j for j in range(len(t.columns)) if j not in indexes]
    if new in [t.columns[j][0] for j in kept]:
        raise _exists(new)
    new_kind = _function_spec(combiner)
    position = sum(1 for j in kept if j < indexes[-1])
    columns_out = [t.columns[j] for j in kept]
    columns_out.insert(position, (new, new_kind))
    rows = []
    for row in t.rows:
        cells = [row[j] for j in kept]
        cells.insert(position, V.Thunk(lambda row=row: _apply(combiner, V.List(tuple(row[j] for j in indexes)))))
        rows.append(tuple(cells))
    return V.Table(tuple(columns_out), tuple(rows))


def _expand_record_column(table: MValue, column: MValue, fields: MValue, new_names: MValue) -> MValue:
    t = _table(table)
    names = _names_of(t)
    i = _index(t, _text(column))
    field_names = _names(fields)
    _no_repeat(field_names)
    out_names = field_names if isinstance(new_names, V.Null) else _names(new_names)
    if len(out_names) != len(field_names):
        raise _unsupported("expansion with a different number of new names")
    rest = [name for j, name in enumerate(names) if j != i]
    _unique_or_refuse(rest + out_names)
    columns = list(t.columns[:i]) + [(name, "any") for name in out_names] + list(t.columns[i + 1:])
    rows = []
    for row in t.rows:
        cell = V.force(row[i])
        if not isinstance(cell, V.Record):
            raise V.convert_error(cell, V.TypeValue("record"))
        values = []
        for field in field_names:
            if not cell.has(field):
                raise _unsupported("expanded field that the record lacks")
            values.append(cell.get(field))
        rows.append(tuple(row[:i]) + tuple(values) + tuple(row[i + 1:]))
    return V.Table(tuple(columns), tuple(rows))


def _expand_table_column(table: MValue, column: MValue, names_arg: MValue, new_arg: MValue) -> MValue:
    t = _table(table)
    names = _names_of(t)
    i = _index(t, _text(column))
    field_names = _names(names_arg)
    _no_repeat(field_names)
    out_names = field_names if isinstance(new_arg, V.Null) else _names(new_arg)
    if len(out_names) != len(field_names):
        raise _unsupported("expansion with a different number of new names")
    rest = [name for j, name in enumerate(names) if j != i]
    _unique_or_refuse(rest + out_names)
    columns = tuple(t.columns[:i]) + tuple((name, "any") for name in out_names) + tuple(t.columns[i + 1:])
    rows = []
    for row in t.rows:
        cell = V.force(row[i])
        if not isinstance(cell, V.Table):
            raise V.convert_error(cell, V.TypeValue("table"))
        picks = [_index(cell, name) for name in field_names]
        for k in picks:
            if cell.columns[k][1] != "any":
                raise _unsupported("expansion of a typed nested column")
        if not cell.rows:
            rows.append(tuple(row[:i]) + (V.Null(),) * len(field_names) + tuple(row[i + 1:]))
            continue
        for nested in cell.rows:
            rows.append(tuple(row[:i]) + tuple(nested[k] for k in picks) + tuple(row[i + 1:]))
    return V.Table(columns, tuple(rows))


# ---- rows: selection, order, search ---------------------------------------------

def _criteria_indexes(table: V.Table, criteria: MValue) -> list:
    if isinstance(criteria, V.Null):
        return list(range(len(table.columns)))
    current = _names_of(table)
    out = []
    for name in _names(criteria):
        if name not in current:
            raise _distinct_invalid()
        out.append(current.index(name))
    return out


def _distinct(table: MValue, criteria: MValue) -> MValue:
    t = _table(table)
    indexes = _criteria_indexes(t, criteria)
    seen, rows = set(), []
    for row in t.rows:
        key = _key(tuple(V.force(row[i]) for i in indexes))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return V.Table(t.columns, tuple(rows))


def _is_distinct(table: MValue, criteria: MValue) -> MValue:
    t = _table(table)
    indexes = _criteria_indexes(t, criteria)
    seen = set()
    for row in t.rows:
        key = _key(tuple(V.force(row[i]) for i in indexes))
        if key in seen:
            return V.Logical(False)
        seen.add(key)
    return V.Logical(True)


def _sort_specs(table: V.Table, criteria: MValue) -> list:
    names = _names_of(table)
    specs = []
    for item in _items(criteria):
        if isinstance(item, V.Text):
            name, descending = item.value, False
        else:
            pair = _items(item)
            if len(pair) != 2 or not isinstance(pair[0], V.Text):
                raise _unsupported("sort criteria")
            name, descending = pair[0].value, _order(pair[1])
        if name not in names:
            raise _sort_invalid()
        specs.append((names.index(name), descending))
    return specs


def _sorted_rows(rows: list, specs: list) -> list:
    rows = list(rows)
    for index, descending in reversed(specs):
        rows.sort(key=cmp_to_key(lambda a, b, index=index: compare(V.force(a[index]), V.force(b[index]))),
                  reverse=descending)
    return rows


def _sort(table: MValue, criteria: MValue) -> MValue:
    t = _table(table)
    return V.Table(t.columns, tuple(_sorted_rows(t.rows, _sort_specs(t, criteria))))


def _extreme_rows(table: V.Table, column: MValue, descending: bool) -> list:
    name = _text(column)
    names = _names_of(table)
    if name not in names:
        raise _sort_invalid()
    # among equal values Power BI answers the last row (and lists the later rows first)
    return _sorted_rows(list(reversed(table.rows)), [(names.index(name), descending)])


def _max(table: MValue, column: MValue, default: MValue) -> MValue:
    t = _table(table)
    rows = _extreme_rows(t, column, True)
    return _record(_names_of(t), rows[0]) if rows else default


def _min(table: MValue, column: MValue, default: MValue) -> MValue:
    t = _table(table)
    rows = _extreme_rows(t, column, False)
    return _record(_names_of(t), rows[0]) if rows else default


def _max_n(table: MValue, column: MValue, count: MValue) -> MValue:
    t = _table(table)
    rows = _extreme_rows(t, column, True)[:_count(count)]
    return V.Table(t.columns, tuple(rows))


def _min_n(table: MValue, column: MValue, count: MValue) -> MValue:
    t = _table(table)
    rows = _extreme_rows(t, column, False)[:_count(count)]
    return V.Table(t.columns, tuple(rows))


def _contains(table: MValue, record: MValue) -> MValue:
    t = _table(table)
    criteria = _record_arg(record)
    names = _names_of(t)
    return V.Logical(any(_projection_matches(names, row, criteria) for row in t.rows))


def _contains_any(table: MValue, records: MValue) -> MValue:
    t = _table(table)
    names = _names_of(t)
    criteria = [_record_arg(item) for item in _items(records)]
    return V.Logical(any(_projection_matches(names, row, c) for row in t.rows for c in criteria))


def _position_of(table: MValue, record: MValue, occurrence: MValue, criteria_fn: MValue) -> MValue:
    _no_option(occurrence, "occurrence argument")
    _no_option(criteria_fn, "equationCriteria argument")
    t = _table(table)
    criteria = _record_arg(record)
    names = _names_of(t)
    for position, row in enumerate(t.rows):
        if _projection_matches(names, row, criteria):
            return V.Number(float(position))
    return V.Number(-1.0)


def _matches_all_rows(table: MValue, predicate: MValue) -> MValue:
    t = _table(table)
    names = _names_of(t)
    for row in t.rows:
        if not _truth(_apply(predicate, _record(names, row))):
            return V.Logical(False)
    return V.Logical(True)


def _matches_any_rows(table: MValue, predicate: MValue) -> MValue:
    t = _table(table)
    names = _names_of(t)
    for row in t.rows:
        if _truth(_apply(predicate, _record(names, row))):
            return V.Logical(True)
    return V.Logical(False)


def _row_has_text(row: tuple, needle: str) -> bool:
    for cell in row:
        text = _cell_text(V.force(cell))
        if text is not None and needle in text:
            return True
    return False


def _find_text(table: MValue, text: MValue) -> MValue:
    t = _table(table)
    needle = _text(text)
    return V.Table(t.columns, tuple(row for row in t.rows if _row_has_text(row, needle)))


def _select_rows(table: MValue, predicate: MValue) -> MValue:
    t = _table(table)
    names = _names_of(t)
    return V.Table(t.columns, tuple(row for row in t.rows if _truth(_apply(predicate, _record(names, row)))))


def _remove_rows(table: MValue, offset: MValue, count: MValue) -> MValue:
    t = _table(table)
    start = _count(offset)
    n = _count_or(count, 1)
    if start + n > len(t.rows):
        raise _unsupported("removal past the last row")
    return V.Table(t.columns, t.rows[:start] + t.rows[start + n:])


def _insert_rows(table: MValue, offset: MValue, records: MValue) -> MValue:
    t = _table(table)
    start = _count(offset)
    if start > len(t.rows):
        raise _unsupported("insertion past the last row")
    names = _names_of(t)
    new_rows = []
    for item in _items(records):
        record = _record_arg(item)
        if sorted(record.names()) != sorted(names):
            raise _unsupported("inserted record whose fields differ from the columns")
        cells = tuple(record.get(name) for name in names)
        for (_name, kind), cell in zip(t.columns, cells):
            _check_cell(cell, kind)
        new_rows.append(cells)
    return V.Table(t.columns, t.rows[:start] + tuple(new_rows) + t.rows[start:])


def _remove_matching_rows(table: MValue, records: MValue, criteria_fn: MValue) -> MValue:
    _no_option(criteria_fn, "equationCriteria argument")
    t = _table(table)
    names = _names_of(t)
    criteria = [_record_arg(item) for item in _items(records)]

    def matches(row: tuple) -> bool:
        for record in criteria:
            if sorted(record.names()) != sorted(names):
                continue
            if all(_equals(V.force(row[names.index(name)]), record.get(name)) for name in names):
                return True
        return False

    return V.Table(t.columns, tuple(row for row in t.rows if not matches(row)))


def _select_rows_with_errors(table: MValue, columns: MValue) -> MValue:
    _no_option(columns, "columns argument")
    t = _table(table)
    return V.Table(t.columns, tuple(row for row in t.rows if _row_has_error(row)))


def _remove_rows_with_errors(table: MValue, columns: MValue) -> MValue:
    _no_option(columns, "columns argument")
    t = _table(table)
    return V.Table(t.columns, tuple(row for row in t.rows if not _row_has_error(row)))


# ---- grouping, pivoting and reshaping -------------------------------------------

def _aggregates(value: MValue) -> list:
    out = []
    for item in _items(value):
        pair = _items(item)
        if len(pair) not in (2, 3) or not isinstance(pair[0], V.Text):
            raise _unsupported("aggregate list")
        if not isinstance(pair[1], V.Function):
            raise V.convert_error(pair[1], V.TypeValue("function"))
        explicit = None
        if len(pair) == 3:
            if not isinstance(pair[2], V.TypeValue):
                raise _unsupported("column type of an aggregate")
            explicit = _type_spec(pair[2])
        out.append((pair[0].value, pair[1], explicit))
    return out


def _group(table: MValue, keys: MValue, aggregates: MValue, kind: MValue, comparer: MValue) -> MValue:
    _no_option(kind, "groupKind argument")
    _no_option(comparer, "comparer argument")
    t = _table(table)
    key_names = _names(keys)
    if not key_names:
        raise _unsupported("grouping without key columns")
    _no_repeat(key_names)
    key_indexes = [_index(t, name) for name in key_names]
    aggs = _aggregates(aggregates)
    _unique_or_refuse(key_names + [name for name, _fn, _kind in aggs])
    groups: dict = {}
    order = []
    for row in t.rows:
        key = _key(tuple(V.force(row[i]) for i in key_indexes))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    rows = []
    for key in order:
        members = groups[key]
        key_cells = tuple(members[0][i] for i in key_indexes)
        group_table = V.Table(t.columns, tuple(members))
        rows.append(key_cells + tuple(V.Thunk(lambda fn=fn, g=group_table: _apply(fn, g)) for _name, fn, _kind in aggs))
    columns = tuple((name, t.columns[i][1]) for name, i in zip(key_names, key_indexes))
    columns += tuple((name, kind if kind is not None else _function_spec(fn)) for name, fn, kind in aggs)
    return V.Table(columns, tuple(rows))


def _pivot(table: MValue, values: MValue, attribute: MValue, value_column: MValue, aggregate: MValue) -> MValue:
    _no_option(aggregate, "aggregationFunction argument")
    t = _table(table)
    pivots = _names(values)
    _no_repeat(pivots)
    ai = _index(t, _text(attribute))
    vi = _index(t, _text(value_column))
    if ai == vi:
        raise _unsupported("pivot over the value column")
    others = [j for j in range(len(t.columns)) if j not in (ai, vi)]
    if any(t.columns[j][0] in pivots for j in others):
        raise _unsupported("pivot value that is also a column name")
    _base_kind, value_type, _nullable = _parts(t.columns[vi][1])
    value_kind = _col(value_type, True)  # a pivot cell is null where there is no row
    groups: dict = {}
    order = []
    for row in t.rows:
        key = _key(tuple(V.force(row[j]) for j in others))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    columns = tuple(t.columns[j] for j in others) + tuple((p, value_kind) for p in pivots)
    rows = []
    for key in order:
        members = groups[key]
        cells = [members[0][j] for j in others]
        for p in pivots:
            hits = [row for row in members
                    if isinstance(V.force(row[ai]), V.Text) and V.force(row[ai]).value == p]
            if len(hits) > 1:
                raise _unsupported("pivot with a repeated attribute value")
            cells.append(hits[0][vi] if hits else V.Null())
        rows.append(tuple(cells))
    return V.Table(columns, tuple(rows))


def _unpivot_table(t: V.Table, unpivot: list, others: list, attr: str, value_name: str) -> V.Table:
    other_names = [t.columns[j][0] for j in others]
    if attr in other_names or value_name in other_names or attr == value_name:
        raise _unsupported("unpivot name that is already a column")
    kinds = {t.columns[j][1] for j in unpivot}
    if len(kinds) > 1:
        raise _unsupported("unpivot of columns with different types")
    if not kinds:
        raise _unsupported("unpivot of no columns")
    value_kind = _col(_parts(kinds.pop())[1], False)  # unpivoted nulls are dropped: the column is never null
    columns = tuple(t.columns[j] for j in others) + ((attr, "text"), (value_name, value_kind))
    rows = []
    for row in t.rows:
        for j in unpivot:
            cell = V.force(row[j])
            if isinstance(cell, V.Null):
                continue
            rows.append(tuple(row[k] for k in others) + (V.Text(t.columns[j][0]), cell))
    return V.Table(columns, tuple(rows))


def _unpivot(table: MValue, columns: MValue, attr: MValue, value_name: MValue) -> MValue:
    t = _table(table)
    names = _names(columns)
    _no_repeat(names)
    unpivot = sorted(_index(t, name) for name in names)
    others = [j for j in range(len(t.columns)) if j not in unpivot]
    return _unpivot_table(t, unpivot, others, _text(attr), _text(value_name))


def _unpivot_other_columns(table: MValue, keep: MValue, attr: MValue, value_name: MValue) -> MValue:
    t = _table(table)
    names = _names(keep)
    _no_repeat(names)
    others = sorted(_index(t, name) for name in names)
    unpivot = [j for j in range(len(t.columns)) if j not in others]
    return _unpivot_table(t, unpivot, others, _text(attr), _text(value_name))


def combine_tables(parts: list) -> V.Table:
    """Table.Combine and the & operator on tables: the columns of all tables by first appearance, a missing cell is
    null. A column keeps its type when every table has it with the same type (it is nullable if any table has it
    nullable or lacks it); tables that disagree on the type give any."""
    if not parts:
        return V.Table((), ())
    names: list = []
    kinds: dict = {}
    for part in parts:
        for name, kind in part.columns:
            if name not in kinds:
                names.append(name)
                kinds[name] = []
            kinds[name].append(kind)
    columns = []
    for name in names:
        present = kinds[name]
        full = len(present) == len(parts)
        details = {_parts(kind)[:2] for kind in present}
        if len(details) > 1 and len({base for base, _ in details}) == 1:
            raise _unsupported("combined column of different types of the same kind")
        if len(details) > 1:
            columns.append((name, "any"))
            continue
        base, type_name = next(iter(details))
        nullable = (not full) or any(_parts(kind)[2] for kind in present)
        columns.append((name, _col(type_name, nullable)))
    rows = []
    for part in parts:
        current = _names_of(part)
        for row in part.rows:
            rows.append(tuple(row[current.index(name)] if name in current else V.Null() for name in names))
    return V.Table(tuple(columns), tuple(rows))


def _combine(tables: MValue) -> MValue:
    return combine_tables([_table(item) for item in _items(tables)])


def _join_key_indexes(table: V.Table, keys: MValue) -> list:
    names = _names(keys)
    _no_repeat(names)
    return [_index(table, name) for name in names]


def _join_key(row: tuple, indexes: list) -> tuple:
    return _key(tuple(V.force(row[i]) for i in indexes))


def _join_index(table: V.Table, indexes: list) -> dict:
    index: dict = {}
    for row in table.rows:
        index.setdefault(_join_key(row, indexes), []).append(row)
    return index


def _join_kind(value: MValue, default: int) -> int:
    if isinstance(value, V.Null):
        return default
    return _count(value)


def _join(table1: MValue, key1: MValue, table2: MValue, key2: MValue, kind: MValue) -> MValue:
    """Inner, LeftOuter and LeftAnti joins. When several left rows appear in the result, Power BI lists them in an
    order that depends on the hash of the keys (neither the left order nor the right order), which this engine does
    not reproduce: such a join is not computed. The answers it does compute are an Inner join in which at most one
    left row matches (its right rows in right order), a LeftOuter join with no match or a single left row, and a
    LeftAnti join (the unmatched left rows in left order)."""
    join_kind = _JOIN_INNER if isinstance(kind, V.Null) else _count(kind)
    if join_kind not in (_JOIN_INNER, _JOIN_LEFT_OUTER, _JOIN_LEFT_ANTI):
        raise _unsupported("join kind other than Inner, LeftOuter or LeftAnti")
    left, right = _table(table1), _table(table2)
    left_idx = _join_key_indexes(left, key1)
    right_idx = _join_key_indexes(right, key2)
    if len(left_idx) != len(right_idx):
        raise _unsupported("join keys of different lengths")
    for _name, kind_ in left.columns + right.columns:
        if kind_ != "any" and (join_kind != _JOIN_INNER or "~" in kind_):
            raise _unsupported("join of typed columns")
    if len(set(_names_of(left) + _names_of(right))) != len(left.columns) + len(right.columns):
        raise _unsupported("join with a repeated column name")
    index = _join_index(right, right_idx)
    left_keys = [_join_key(row, left_idx) for row in left.rows]
    matched = sum(1 for key in left_keys if key in index)
    if (join_kind == _JOIN_INNER and matched > 1) or \
            (join_kind == _JOIN_LEFT_OUTER and matched > 0 and len(left_keys) > 1):
        raise _unsupported("join that lists several left rows in a hash order")
    absent = (V.Null(),) * len(right.columns)
    rows = []
    for row, key in zip(left.rows, left_keys):
        matches = index.get(key, [])
        if join_kind == _JOIN_LEFT_ANTI:
            if not matches:
                rows.append(tuple(row) + absent)
        elif matches:
            rows += [tuple(row) + tuple(match) for match in matches]
        elif join_kind == _JOIN_LEFT_OUTER:
            rows.append(tuple(row) + absent)
    return V.Table(left.columns + right.columns, tuple(rows))


def _nested_join(table1: MValue, key1: MValue, table2: MValue, key2: MValue, new_name: MValue,
                 kind: MValue) -> MValue:
    if _join_kind(kind, _JOIN_LEFT_OUTER) != _JOIN_LEFT_OUTER:
        raise _unsupported("nested join kind other than LeftOuter")
    left, right = _table(table1), _table(table2)
    left_idx = _join_key_indexes(left, key1)
    right_idx = _join_key_indexes(right, key2)
    if len(left_idx) != len(right_idx):
        raise _unsupported("join keys of different lengths")
    new = _text(new_name)
    if new in _names_of(left):
        raise _unsupported("nested column over an existing column name")
    if any(kind_ != "any" for _, kind_ in right.columns):
        raise _unsupported("nested join of typed columns")
    index = _join_index(right, right_idx)
    rows = []
    for row in left.rows:
        matches = tuple(index.get(_join_key(row, left_idx), []))
        rows.append(tuple(row) + (V.Table(right.columns, matches),))
    return V.Table(left.columns + ((new, "table"),), tuple(rows))


# ---- constructors -----------------------------------------------------------

def _from_rows(rows: MValue, columns: MValue) -> MValue:
    lists = [_items(row) for row in _items(rows)]
    if isinstance(columns, V.Null):
        if not lists:
            raise _unsupported("table of no rows and no column names")
        names = [f"Column{k}" for k in range(1, len(lists[0]) + 1)]
    else:
        names = _names(columns)
    _no_repeat(names)
    for cells in lists:
        if len(cells) != len(names):
            raise _unsupported("row whose length differs from the column count")
    return V.Table(tuple((name, "any") for name in names), tuple(tuple(cells) for cells in lists))


def _list_column_kind(lst: V.List) -> str:
    """The kind Table.FromColumns gives a column made from this list: its item type, always nullable."""
    if lst.literal:
        return "any"
    if lst.item_kind is not None:
        base, type_name, _nullable = _parts(_plain(lst.item_kind))
        return "any" if base == "any" else _col(type_name, True)
    raise _unsupported("column type of a list that is computed")


def _from_columns(lists: MValue, columns: MValue) -> MValue:
    for item in _items(lists):
        if not isinstance(item, V.List):
            raise V.convert_error(item, V.TypeValue("list"))
    kinds = [_list_column_kind(item) for item in _items(lists)]
    cols = [_items(item) for item in _items(lists)]
    if not cols:
        return V.Table((), ())
    height = max(len(col) for col in cols)
    if len(cols[0]) != height:
        raise _unsupported("first column shorter than a later column")
    names = [f"Column{k}" for k in range(1, len(cols) + 1)] if isinstance(columns, V.Null) else _names(columns)
    if len(names) != len(cols):
        raise _unsupported("column names that differ in number from the columns")
    _no_repeat(names)
    rows = tuple(tuple(col[r] if r < len(col) else V.Null() for col in cols) for r in range(height))
    return V.Table(tuple(zip(names, kinds)), rows)


def _from_list(items: MValue, splitter: MValue, columns: MValue, default: MValue) -> MValue:
    _no_option(columns, "columns argument")
    _no_option(default, "default argument")
    values = _items(items)
    if isinstance(splitter, V.Null):
        for value in values:
            if not isinstance(value, V.Text):
                raise V.convert_error(value, V.TypeValue("text"))
        raise _unsupported("list of text without a splitter")
    if not values:
        raise _unsupported("list of no items")
    split_rows = [[_text(part) for part in _items(_apply(splitter, value))] for value in values]
    width = len(split_rows[0])
    if width == 0 or any(len(parts) != width for parts in split_rows):
        raise _unsupported("split items that differ in number of parts")
    names = [f"Column{k}" for k in range(1, width + 1)]
    return V.Table(tuple((name, "text") for name in names),
                   tuple(tuple(V.Text(part) for part in parts) for parts in split_rows))


def _from_value(value: MValue, options: MValue) -> MValue:
    name = "Value"
    if not isinstance(options, V.Null):
        record = _record_arg(options)
        for field in record.names():
            if field != "DefaultColumnName":
                raise _unsupported("option of Table.FromValue")
            name = _text(record.get(field))
    if isinstance(value, V.Table):
        return value
    if isinstance(value, V.Record):
        if name != "Value":
            raise _unsupported("record with a column name")
        rows = tuple((V.Text(field), value.get(field)) for field in value.names())
        return V.Table((("Name", "text"), ("Value", "any")), rows)
    if isinstance(value, V.List):
        return V.Table(((name, "any"),), tuple((item,) for item in value.items))
    if isinstance(value, V.Null):
        return V.Table(((name, _col("Null.Type", True)),), ((value,),))
    kind = V.kind_of(value)
    if kind in ("number", "text"):
        return V.Table(((name, kind),), ((value,),))
    if kind in ("logical", "date", "time", "datetime", "datetimezone", "duration", "binary", "function", "type"):
        return V.Table(((name, _col(_PRIMITIVE_TYPE_NAMES[kind] + ".Type", False)),), ((value,),))
    raise _unsupported("table from this value")


def _ordinal_min_max(values: list) -> tuple:
    ordered = sorted(values, key=cmp_to_key(compare))
    return ordered[0], ordered[-1]


def _profile(table: MValue) -> MValue:
    t = _table(table)
    rows = []
    for i, (name, kind) in enumerate(t.columns):
        cells = [V.force(row[i]) for row in t.rows]
        count = len(cells)
        nulls = sum(1 for cell in cells if isinstance(cell, V.Null))
        values = [cell for cell in cells if not isinstance(cell, V.Null)]
        if kind == "any":
            rows.append((V.Text(name), V.Null(), V.Null(), V.Null(), V.Null(),
                         V.Number(float(count)), V.Number(float(nulls)), V.Null()))
            continue
        if nulls or not values:
            raise _unsupported("profile of a typed column with nulls or no values")
        distinct = len({_key((cell,)) for cell in values})
        if kind == "number":
            xs = [cell.value for cell in values]
            if len(xs) < 2 or any(math.isnan(x) for x in xs):
                raise _unsupported("profile of this number column")
            mean = sum(xs) / len(xs)
            deviation = math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1))
            rows.append((V.Text(name), V.Number(min(xs)), V.Number(max(xs)), V.Number(mean), V.Number(deviation),
                         V.Number(float(count)), V.Number(0.0), V.Number(float(distinct))))
        elif kind == "text":
            low, high = _ordinal_min_max(values)
            rows.append((V.Text(name), low, high, V.Null(), V.Null(),
                         V.Number(float(count)), V.Number(0.0), V.Number(float(distinct))))
        else:
            raise _unsupported("profile of this column type")
    columns = (("Column", "text"), ("Min", "any"), ("Max", "any"), ("Average", "any"),
               ("StandardDeviation", _col("Number.Type", True)), ("Count", "number"), ("NullCount", "any"), ("DistinctCount", "any"))
    return V.Table(columns, tuple(rows))


def _columns_of_type(table: MValue, types: MValue) -> MValue:
    t = _table(table)
    wanted = []
    for type_value in _items(types):
        if not isinstance(type_value, V.TypeValue) or type_value.name in ("any", "anynonnull"):
            raise _unsupported("column type filter")
        wanted.append(type_value.name)
    return V.List(tuple(V.Text(name) for name, kind in t.columns if _plain(kind) in wanted))


# ---- cell access used by the evaluator ----------------------------------------

def table_field(table: V.Table, name: str, optional: bool) -> MValue:
    """``table[name]``: the column as a list."""
    if optional:
        raise _unsupported("optional column access on a table")
    i = _index(table, name)
    return V.List(tuple(row[i] for row in table.rows))


def table_item(table: V.Table, index: MValue, optional: bool) -> MValue:
    """``table{n}``: the row as a record; ``table{n}?`` is null past the last row."""
    if not isinstance(index, V.Number):
        raise _unsupported("table index that is not a number")
    k = index.value
    if not (math.isfinite(k) and k == math.floor(k) and k >= 0):
        raise _unsupported("table index that is not a whole number")
    if k < len(table.rows):
        return _record(_names_of(table), table.rows[int(k)])
    if optional:
        return V.Null()
    raise _unsupported("table index past the last row")


# ---- Splitter and Combiner ------------------------------------------------------

_QUOTE_NONE, _QUOTE_CSV = 0, 1


def _combine_by_delimiter(delimiter: MValue, quote: MValue) -> MValue:
    """Combiner.CombineTextByDelimiter: null items count as empty text; with QuoteStyle.Csv (the default) an item
    that holds the delimiter, a double quote or a line break is wrapped in double quotes, its quotes doubled."""
    delim = _text(delimiter)
    if isinstance(quote, V.Null):
        style = _QUOTE_CSV
    elif isinstance(quote, V.Number):
        if quote.value not in (_QUOTE_NONE, _QUOTE_CSV):
            raise MError("Expression.Error", "The specified QuoteStyle is invalid.",
                         fmt="The specified QuoteStyle is invalid.")
        style = int(quote.value)
    else:
        raise _unsupported("quoteStyle argument that is not a number")

    def combine(items: MValue) -> MValue:
        parts = []
        for item in _items(items):
            text = "" if isinstance(item, V.Null) else _text(item)
            if style == _QUOTE_CSV and any(c in text for c in '"\r\n'):
                text = '"' + text.replace('"', '""') + '"'
            elif style == _QUOTE_CSV and delim and delim in text:
                text = '"' + text.replace('"', '""') + '"'
            parts.append(text)
        return V.Text(delim.join(parts))

    return _native((("texts", False),), combine, V.TypeValue("text"))


TABLE_GLOBALS: dict = {
    "#table": _native((("columns", False), ("rows", False)), _table_literal),
    "Table.Type": V.TypeValue("table"),
    "Type.TableSchema": _native((("type", False),), _type_table_schema),
    "ExtraValues.List": V.Number(0.0),
    "ExtraValues.Error": V.Number(1.0),
    "ExtraValues.Ignore": V.Number(2.0),
    "QuoteStyle.None": V.Number(0.0),
    "QuoteStyle.Csv": V.Number(1.0),
    "JoinKind.Inner": V.Number(0.0),
    "JoinKind.LeftOuter": V.Number(1.0),
    "JoinKind.RightOuter": V.Number(2.0),
    "JoinKind.FullOuter": V.Number(3.0),
    "JoinKind.LeftAnti": V.Number(4.0),
    "JoinKind.RightAnti": V.Number(5.0),
    "Combiner.CombineTextByDelimiter": _native((("delimiter", False), ("quoteStyle", True)),
                                               _combine_by_delimiter),
    "Table.RowCount": _native((("table", False),), _row_count),
    "Table.ColumnCount": _native((("table", False),), _column_count),
    "Table.ColumnNames": _native((("table", False),), _column_names),
    "Table.ToRecords": _native((("table", False),), _to_records),
    "Table.ToRows": _native((("table", False),), _to_rows),
    "Table.ToColumns": _native((("table", False),), _to_columns),
    "Table.ToList": _native((("table", False), ("combiner", True)), _to_list),
    "Table.First": _native((("table", False), ("default", True)), _first),
    "Table.Last": _native((("table", False), ("default", True)), _last),
    "Table.IsEmpty": _native((("table", False),), _is_empty),
    "Table.Column": _native((("table", False), ("column", False)), _column),
    "Table.Keys": _native((("table", False),), _keys),
    "Table.HasColumns": _native((("table", False), ("columns", False)), _has_columns),
    "Table.Contains": _native((("table", False), ("row", False)), _contains),
    "Table.ContainsAny": _native((("table", False), ("rows", False)), _contains_any),
    "Table.PositionOf": _native((("table", False), ("row", False), ("occurrence", True),
                                 ("equationCriteria", True)), _position_of),
    "Table.MatchesAllRows": _native((("table", False), ("condition", False)), _matches_all_rows),
    "Table.MatchesAnyRows": _native((("table", False), ("condition", False)), _matches_any_rows),
    "Table.FindText": _native((("table", False), ("text", False)), _find_text),
    "Table.Transpose": _native((("table", False),), _transpose),
    "Table.Schema": _native((("table", False),), _schema),
    "Table.Buffer": _native((("table", False),), _buffer),
    "Table.DemoteHeaders": _native((("table", False),), _demote_headers),
    "Table.PromoteHeaders": _native((("table", False), ("options", True)), _promote_headers),
    "Table.ReverseRows": _native((("table", False),), _reverse_rows),
    "Table.FirstN": _native((("table", False), ("countOrCondition", False)), _first_n),
    "Table.LastN": _native((("table", False), ("countOrCondition", False)), _last_n),
    "Table.Skip": _native((("table", False), ("countOrCondition", True)), _remove_first_n),
    "Table.RemoveFirstN": _native((("table", False), ("countOrCondition", True)), _remove_first_n),
    "Table.RemoveLastN": _native((("table", False), ("countOrCondition", True)), _remove_last_n),
    "Table.Range": _native((("table", False), ("offset", False), ("count", True)), _range),
    "Table.Repeat": _native((("table", False), ("count", False)), _repeat),
    "Table.SelectColumns": _native((("table", False), ("columns", False), ("missingField", True)),
                                   _select_columns),
    "Table.RemoveColumns": _native((("table", False), ("columns", False), ("missingField", True)),
                                   _remove_columns),
    "Table.ReorderColumns": _native((("table", False), ("columnOrder", False), ("missingField", True)),
                                    _reorder_columns),
    "Table.RenameColumns": _native((("table", False), ("renames", False), ("missingField", True)),
                                   _rename_columns),
    "Table.TransformColumns": _native((("table", False), ("transforms", False),
                                       ("defaultTransformation", True), ("missingField", True)),
                                      _transform_columns),
    "Table.TransformColumnTypes": _native((("table", False), ("typeTransformations", False),
                                           ("culture", True)), _transform_column_types),
    "Table.ReplaceValue": _native((("table", False), ("oldValue", False), ("newValue", False),
                                   ("replacer", False), ("columns", True)), _replace_value_table),
    "Table.FillDown": _native((("table", False), ("columns", False)), lambda t, c: _fill(t, c, True)),
    "Table.FillUp": _native((("table", False), ("columns", False)), lambda t, c: _fill(t, c, False)),
    "Table.Distinct": _native((("table", False), ("equationCriteria", True)), _distinct),
    "Table.IsDistinct": _native((("table", False), ("equationCriteria", True)), _is_distinct),
    "Table.Sort": _native((("table", False), ("comparisonCriteria", False)), _sort),
    "Table.Max": _native((("table", False), ("column", False), ("default", True)), _max),
    "Table.Min": _native((("table", False), ("column", False), ("default", True)), _min),
    "Table.MaxN": _native((("table", False), ("column", False), ("countOrCondition", False)), _max_n),
    "Table.MinN": _native((("table", False), ("column", False), ("countOrCondition", False)), _min_n),
    "Table.Group": _native((("table", False), ("key", False), ("aggregatedColumns", False),
                            ("groupKind", True), ("comparer", True)), _group),
    "Table.AddColumn": _native((("table", False), ("newColumnName", False), ("columnGenerator", False),
                                ("columnType", True)), _add_column),
    "Table.AddIndexColumn": _native((("table", False), ("newColumnName", False), ("initialValue", True),
                                     ("increment", True), ("columnType", True)), _add_index_column),
    "Table.DuplicateColumn": _native((("table", False), ("columnName", False), ("newColumnName", False),
                                      ("columnType", True)), _duplicate_column),
    "Table.SelectRows": _native((("table", False), ("condition", False)), _select_rows),
    "Table.RemoveRows": _native((("table", False), ("offset", False), ("count", True)), _remove_rows),
    "Table.InsertRows": _native((("table", False), ("offset", False), ("rows", False)), _insert_rows),
    "Table.RemoveMatchingRows": _native((("table", False), ("rows", False), ("equationCriteria", True)),
                                        _remove_matching_rows),
    "Table.SelectRowsWithErrors": _native((("table", False), ("columns", True)), _select_rows_with_errors),
    "Table.RemoveRowsWithErrors": _native((("table", False), ("columns", True)), _remove_rows_with_errors),
    "Table.SplitColumn": _native((("table", False), ("sourceColumn", False), ("splitter", False),
                                  ("columnNamesOrNumberOfColumns", True), ("default", True), ("extraColumns", True)),
                                 _split_column),
    "Table.CombineColumns": _native((("table", False), ("sourceColumns", False), ("combiner", False),
                                     ("column", False)), _combine_columns),
    "Table.ExpandRecordColumn": _native((("table", False), ("column", False), ("fieldNames", False),
                                         ("newColumnNames", True)), _expand_record_column),
    "Table.ExpandTableColumn": _native((("table", False), ("column", False), ("columnNames", False),
                                        ("newColumnNames", True)), _expand_table_column),
    "Table.Pivot": _native((("table", False), ("pivotValues", False), ("attributeColumn", False),
                            ("valueColumn", False), ("aggregationFunction", True)), _pivot),
    "Table.Unpivot": _native((("table", False), ("pivotColumns", False), ("attributeColumn", False),
                              ("valueColumn", False)), _unpivot),
    "Table.UnpivotOtherColumns": _native((("table", False), ("pivotColumns", False), ("attributeColumn", False),
                                          ("valueColumn", False)), _unpivot_other_columns),
    "Table.ColumnsOfType": _native((("table", False), ("columnTypes", False)), _columns_of_type),
    "Table.Combine": _native((("tables", False),), _combine),
    "Table.Join": _native((("table1", False), ("key1", False), ("table2", False), ("key2", False),
                           ("joinKind", True)), _join),
    "Table.NestedJoin": _native((("table1", False), ("key1", False), ("table2", False), ("key2", False),
                                 ("newColumnName", False), ("joinKind", True)), _nested_join),
    "Table.FromRows": _native((("rows", False), ("columns", True)), _from_rows),
    "Table.FromColumns": _native((("lists", False), ("columns", True)), _from_columns),
    "Table.FromList": _native((("list", False), ("splitter", True), ("columns", True), ("default", True)),
                              _from_list),
    "Table.FromValue": _native((("value", False), ("options", True)), _from_value),
    "Table.Profile": _native((("table", False),), _profile),
}
