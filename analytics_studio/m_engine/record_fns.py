"""Power Query ``Record.*`` functions, the MissingField enumeration, ``#table``, ``Record.Type`` and ``Type.RecordFields``
(Task 105, m-record-95). ``#table`` is not defined here yet (see the report: a table literal would make an
existing text test answer a value where it asserts ERR).

Every answer is computed from the arguments. Measured messages are copied from the spec; a message pattern is
generalised only where the spec shows the pattern (a missing field, an existing field, a conversion to Record, a
count mismatch). A case whose answer is not measured raises ``_unsupported``: an explicit ERR, never a guessed value.

Fields keep their order. Field values stay lazy (a Thunk) except where the answer is a list of values or a table of
values: there a field that fails is refused, since its Power BI answer is not measured.
"""

from __future__ import annotations

from typing import Optional

from . import values as V
from .values import MError, MValue

MISSING_ERROR, MISSING_IGNORE, MISSING_USE_NULL = 0, 1, 2  # MissingField.Error, MissingField.Ignore, MissingField.UseNull


# ---- helpers ----------------------------------------------------------------

def _native(params: tuple, fn) -> V.Function:
    specs = tuple(V.ParamSpec(name, None, optional) for name, optional in params)

    def invoke(bound: list) -> MValue:
        return fn(*[V.force(item) for item in bound])

    return V.Function(specs, invoke)


def _unsupported(what: str) -> MError:
    """Not a Power BI answer this engine has measured: an explicit ERR, never a guessed value."""
    return V.generic_error(f"The {what} is not supported by this engine yet.")


def _record(value: MValue) -> V.Record:
    if isinstance(value, V.Record):
        return value
    raise V.convert_error(value, V.TypeValue("record"))


def _text(value: MValue) -> str:
    if isinstance(value, V.Text):
        return value.value
    raise V.convert_error(value, V.TypeValue("text"))


def _list(value: MValue) -> tuple:
    if isinstance(value, V.List):
        return tuple(V.force(item) for item in value.items)
    raise V.convert_error(value, V.TypeValue("list"))


def _missing(name: str, record: Optional[V.Record] = None) -> MError:
    return MError("Expression.Error", f"The field '{name}' of the record wasn't found.", detail=record,
                  fmt="The field '#{0}' of the record wasn't found.", params=(V.Text(name),), code="10071")


def _exists(name: str) -> MError:
    return MError("Expression.Error", f"The field '{name}' already exists in the record.",
                  fmt="The field '#{0}' already exists in the record.", params=(V.Text(name),))


def _names(selector: MValue) -> list:
    """A FieldsSelector: one field name, or a list of field names."""
    if isinstance(selector, V.Text):
        return [selector.value]
    if isinstance(selector, V.List):
        return [_text(item) for item in _list(selector)]
    raise MError("Expression.Error", "We expected a FieldsSelector value.")


def _no_repeats(names: list, what: str) -> None:
    if len(set(names)) != len(names):
        raise _unsupported(f"{what} with a repeated field name")


def _missing_option(value: MValue) -> int:
    """A MissingField value; the default (an omitted argument arrives as null) is MissingField.Error."""
    if isinstance(value, V.Null):
        return MISSING_ERROR
    if isinstance(value, V.Number) and value.value in (0.0, 1.0, 2.0):
        return int(value.value)
    raise _unsupported("MissingField option")


def _raw(record: V.Record, name: str):
    """The field's stored item (value or Thunk), not forced."""
    for field_name, item in record.fields:
        if field_name == name:
            return item
    raise KeyError(name)


def _forced_values(record: V.Record) -> tuple:
    """Every field value forced. A field that fails has no measured list answer, so it is refused."""
    out = []
    for name, item in record.fields:
        try:
            out.append(V.force(item))
        except MError:
            raise _unsupported(f"list of the values of a record with a failing field ('{name}')")
    return tuple(out)


# ---- inspection -------------------------------------------------------------

def _has_fields(record: MValue, selector: MValue) -> MValue:
    rec = _record(record)
    names = _names(selector)
    seen = set()
    for name in names:
        if name in seen:
            raise _exists(name)
        seen.add(name)
    return V.Logical(all(rec.has(name) for name in names))


def _field(record: MValue, name: MValue) -> MValue:
    rec = _record(record)
    key = _text(name)
    if not rec.has(key):
        raise _missing(key, rec)
    return rec.get(key)


def _field_or_default(record: MValue, name: MValue, default: MValue) -> MValue:
    rec = _record(record)
    key = _text(name)
    if rec.has(key):
        return rec.get(key)
    return default


def _field_names(record: MValue) -> MValue:
    rec = _record(record)
    return V.List(tuple(V.Text(name) for name in rec.names()))


def _field_values(record: MValue) -> MValue:
    rec = _record(record)
    return V.List(_forced_values(rec))


def _field_count(record: MValue) -> MValue:
    return V.Number(float(len(_record(record).fields)))


def _to_table(record: MValue) -> MValue:
    rec = _record(record)
    values = _forced_values(rec)
    rows = tuple((V.Text(name), value) for name, value in zip(rec.names(), values))
    return V.Table((("Name", "text"), ("Value", "any")), rows)


# ---- construction -----------------------------------------------------------

def _add_field(record: MValue, name: MValue, value: MValue, delayed: MValue) -> MValue:
    rec = _record(record)
    key = _text(name)
    if rec.has(key):
        raise _exists(key)
    if isinstance(delayed, V.Null) or (isinstance(delayed, V.Logical) and not delayed.value):
        item = value
    elif isinstance(delayed, V.Logical):
        if not isinstance(value, V.Function):
            raise _unsupported("delayed field value that is not a function")
        from .evaluator import apply_function  # local import: the evaluator imports this module

        item = V.Thunk(lambda: apply_function(value, []))
    else:
        raise _unsupported("AddField option that is not a logical value")
    return V.Record(rec.fields + ((key, item),))


def _combine(records: MValue) -> MValue:
    order: list = []
    items: dict = {}
    for item in _list(records):
        rec = _record(item)
        for name, field_item in rec.fields:
            if name not in items:
                order.append(name)
            items[name] = field_item
    return V.Record(tuple((name, items[name]) for name in order))


def _from_list(values: MValue, keys: MValue, converter: MValue) -> MValue:
    if not isinstance(converter, V.Null):
        raise _unsupported("FromList with a field converter")
    value_items = _list(values)
    names = [_text(key) for key in _list(keys)]
    if len(names) != len(value_items):
        raise MError("Expression.Error",
                     f"{len(names)} keys were specified, but {len(value_items)} values were provided.")
    seen = set()
    fields = []
    for name, item in zip(names, values.items):
        if name in seen:
            raise _exists(name)
        seen.add(name)
        fields.append((name, item))
    return V.Record(tuple(fields))


def _from_table(table: MValue, default: MValue) -> MValue:
    if not isinstance(default, V.Null):
        raise _unsupported("FromTable with a default value")
    if not isinstance(table, V.Table):
        raise V.convert_error(table, V.TypeValue("table"))
    columns = [name for name, _ in table.columns]
    for needed in ("Name", "Value"):
        if needed not in columns:
            if table.rows:
                raise _missing(needed)
            raise _unsupported("FromTable of a table without a Name or Value column")
    name_at, value_at = columns.index("Name"), columns.index("Value")
    seen = set()
    fields = []
    for row in table.rows:
        name = _text(V.force(row[name_at]))
        if name in seen:
            raise _exists(name)
        seen.add(name)
        fields.append((name, row[value_at]))
    return V.Record(tuple(fields))


# ---- selection and reshaping -------------------------------------------------

def _select_fields(record: MValue, selector: MValue, missing: MValue) -> MValue:
    rec = _record(record)
    names = _names(selector)
    mode = _missing_option(missing)
    _no_repeats(names, "SelectFields")
    fields = []
    for name in names:
        if rec.has(name):
            fields.append((name, _raw(rec, name)))
        elif mode == MISSING_ERROR:
            raise _missing(name, rec)
        elif mode == MISSING_USE_NULL:
            fields.append((name, V.Null()))
    return V.Record(tuple(fields))


def _remove_fields(record: MValue, selector: MValue, missing: MValue) -> MValue:
    rec = _record(record)
    names = _names(selector)
    mode = _missing_option(missing)
    _no_repeats(names, "RemoveFields")
    if mode == MISSING_USE_NULL:
        raise _unsupported("RemoveFields with MissingField.UseNull")
    for name in names:
        if not rec.has(name) and mode == MISSING_ERROR:
            raise _missing(name, rec)
    removed = set(names)
    return V.Record(tuple((name, item) for name, item in rec.fields if name not in removed))


def _reorder_fields(record: MValue, selector: MValue, missing: MValue) -> MValue:
    """Listed fields take the positions the listed fields already hold, in the listed order; the other fields keep
    their places. A listed field that is missing is ignored, an error, or (UseNull) appended with null."""
    rec = _record(record)
    names = _names(selector)
    mode = _missing_option(missing)
    _no_repeats(names, "ReorderFields")
    present = []
    absent = []
    for name in names:
        if rec.has(name):
            present.append(name)
        elif mode == MISSING_ERROR:
            raise _missing(name, rec)
        elif mode == MISSING_USE_NULL:
            absent.append(name)
    if len(absent) > 1:
        raise _unsupported("ReorderFields with several missing fields under MissingField.UseNull")
    listed = set(present)
    positions = [index for index, (name, _) in enumerate(rec.fields) if name in listed]
    slots = list(rec.fields)
    for index, name in zip(positions, present):
        slots[index] = (name, _raw(rec, name))
    fields = slots + [(name, V.Null()) for name in absent]
    return V.Record(tuple(fields))


def _rename_pairs(renames: MValue) -> list:
    """Either one pair ``{old, new}`` or a list of pairs ``{{old, new}, ...}``."""
    items = _list(renames)
    if len(items) == 2 and all(isinstance(item, V.Text) for item in items):
        return [(items[0].value, items[1].value)]
    pairs = []
    for item in items:
        if not (isinstance(item, V.List) and len(item.items) == 2):
            raise _unsupported("RenameFields argument")
        old, new = _list(item)
        pairs.append((_text(old), _text(new)))
    return pairs


def _rename_fields(record: MValue, renames: MValue, missing: MValue) -> MValue:
    rec = _record(record)
    pairs = _rename_pairs(renames)
    mode = _missing_option(missing)
    if mode == MISSING_USE_NULL:
        raise _unsupported("RenameFields with MissingField.UseNull")
    olds = [old for old, _ in pairs]
    news = [new for _, new in pairs]
    _no_repeats(olds, "RenameFields")
    _no_repeats(news, "RenameFields")
    renamed = {}
    for old, new in pairs:
        if rec.has(old):
            renamed[old] = new
        elif mode == MISSING_ERROR:
            raise _missing(old, rec)
    for old, new in pairs:
        if old in renamed and new in rec.names() and new not in renamed:
            raise _exists(new)
    return V.Record(tuple((renamed.get(name, name), item) for name, item in rec.fields))


def _transform_pairs(transforms: MValue) -> list:
    """Either one pair ``{name, function}`` or a list of pairs ``{{name, function}, ...}``."""
    items = _list(transforms)
    if len(items) == 2 and isinstance(items[0], V.Text) and isinstance(items[1], V.Function):
        return [(items[0].value, items[1])]
    pairs = []
    for item in items:
        if not (isinstance(item, V.List) and len(item.items) == 2):
            raise _unsupported("TransformFields argument")
        name, fn = _list(item)
        if not (isinstance(name, V.Text) and isinstance(fn, V.Function)):
            raise _unsupported("TransformFields argument")
        pairs.append((name.value, fn))
    return pairs


def _transform_fields(record: MValue, transforms: MValue, missing: MValue) -> MValue:
    """The transforms run lazily: a field whose transform fails shows only when it is read."""
    from .evaluator import apply_function  # local import: the evaluator imports this module

    rec = _record(record)
    pairs = _transform_pairs(transforms)
    mode = _missing_option(missing)
    if mode == MISSING_USE_NULL:
        raise _unsupported("TransformFields with MissingField.UseNull")
    _no_repeats([name for name, _ in pairs], "TransformFields")
    chosen = {}
    for name, fn in pairs:
        if rec.has(name):
            chosen[name] = fn
        elif mode == MISSING_ERROR:
            raise _missing(name, rec)
    fields = []
    for name, item in rec.fields:
        if name in chosen:
            fn = chosen[name]
            fields.append((name, V.Thunk(lambda item=item, fn=fn: apply_function(fn, [item]))))
        else:
            fields.append((name, item))
    return V.Record(tuple(fields))


# ---- types ------------------------------------------------------------------

def _type_record_fields(type_value: MValue) -> MValue:
    if not isinstance(type_value, V.TypeValue):
        raise V.convert_error(type_value, V.TypeValue("type"))
    if type_value.fields is None:
        raise _unsupported("Type.RecordFields of a type that has no field list")
    return V.Record(tuple(
        (name, V.Record((("Type", field_type), ("Optional", V.Logical(optional)))))
        for name, field_type, optional in type_value.fields))


RECORD_GLOBALS: dict = {
    "Record.AddField": _native((("record", False), ("fieldName", False), ("value", False), ("delayed", True)),
                               _add_field),
    "Record.Combine": _native((("records", False),), _combine),
    "Record.Field": _native((("record", False), ("field", False)), _field),
    "Record.FieldCount": _native((("record", False),), _field_count),
    "Record.FieldNames": _native((("record", False),), _field_names),
    "Record.FieldOrDefault": _native((("record", False), ("field", False), ("defaultValue", True)),
                                     _field_or_default),
    "Record.FieldValues": _native((("record", False),), _field_values),
    "Record.FromList": _native((("list", False), ("fields", False), ("fieldConverter", True)), _from_list),
    "Record.FromTable": _native((("table", False), ("defaultValue", True)), _from_table),
    "Record.HasFields": _native((("record", False), ("fields", False)), _has_fields),
    "Record.RemoveFields": _native((("record", False), ("fields", False), ("missingField", True)), _remove_fields),
    "Record.RenameFields": _native((("record", False), ("renames", False), ("missingField", True)), _rename_fields),
    "Record.ReorderFields": _native((("record", False), ("fieldOrder", False), ("missingField", True)),
                                    _reorder_fields),
    "Record.SelectFields": _native((("record", False), ("fields", False), ("missingField", True)), _select_fields),
    "Record.ToList": _native((("record", False),), _field_values),
    "Record.ToTable": _native((("record", False),), _to_table),
    "Record.TransformFields": _native((("record", False), ("transformOperations", False), ("missingField", True)),
                                      _transform_fields),
    "Record.Type": V.TypeValue("record"),
    "Type.RecordFields": _native((("type", False),), _type_record_fields),
    "MissingField.Error": V.Number(0.0),
    "MissingField.Ignore": V.Number(1.0),
    "MissingField.UseNull": V.Number(2.0),
}
