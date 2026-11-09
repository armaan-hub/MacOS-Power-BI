"""Power Query Splitter.*, Combiner.*, Comparer.*, Value.*, Type.* and small families (Task 108, m-value-98).

Every answer is computed from the arguments. Messages are copied from the spec (a message pattern is generalised
only where the spec shows it). A case whose answer is not measured raises ``_unsupported``: an explicit ERR, never a
guessed value. Text is handled in UTF-16 code units, as .NET does (``text._units``).

Measured rules used here (see the notes in the Task 108 report):
  * a splitter given null gives an empty list, except SplitByNothing which gives [null];
  * the default quote style of the delimiter and white-space splitters is Csv (quotes are removed, a doubled quote
    is one quote); startAtEnd runs the same rule on the reversed text and reverses the result;
  * a Lengths/Positions/Ranges combiner writes each item at its slot over the template (default empty text),
    cutting it to the slot length, filling a gap with spaces; items beyond the slots are ignored, missing items
    are empty;
  * Comparer.OrdinalIgnoreCase raises the operator error for mixed kinds; Value.Compare orders null before any
    value and text after numbers.
"""

from __future__ import annotations

import decimal as _decimal
import math
from dataclasses import replace as _dc_replace
from typing import Callable, Optional

from . import values as V
from .number import _decimal_of as _number_decimal_of
from .text import _from_units, _fold, _is_space, _units, COMPARER_ORDINAL, COMPARER_ORDINAL_IGNORE_CASE
from .list_fns import _key as _list_key
from .table_fns import _unsupported
from .return_types import RETURN_TYPES
from .values import MError, MValue

_MAX_SLOT = 10_000_000


# ---- helpers -----------------------------------------------------------------

_LIBRARY_NAMES: dict = {}


def _library_name(fn: V.Function) -> Optional[str]:
    if not _LIBRARY_NAMES:
        from .stdlib import GLOBALS  # local import: the stdlib imports this module

        for name, value in GLOBALS.items():
            if isinstance(value, V.Function):
                _LIBRARY_NAMES.setdefault(id(value), name)
    return _LIBRARY_NAMES.get(id(fn))


_SPEC_PRIMITIVES = {
    "Any.Type": "any",
    "Binary.Type": "binary",
    "Date.Type": "date",
    "DateTime.Type": "datetime",
    "DateTimeZone.Type": "datetimezone",
    "Duration.Type": "duration",
    "Function.Type": "function",
    "List.Type": "list",
    "Logical.Type": "logical",
    "Number.Type": "number",
    "Record.Type": "record",
    "Table.Type": "table",
    "Text.Type": "text",
    "Time.Type": "time",
    "Type.Type": "type",
}


def _type_from_spec(type_name: str, nullable: bool) -> V.TypeValue:
    if type_name in _SPEC_PRIMITIVES:
        return V.TypeValue(_SPEC_PRIMITIVES[type_name], nullable=nullable)
    if type_name == "Character.Type":
        return V.TypeValue("text", nullable=nullable, label="Character.Type")
    return V.TypeValue("number", nullable=nullable, label=type_name)

def _native(params: tuple, fn: Callable[..., MValue], return_type: Optional[V.TypeValue] = None) -> V.Function:
    specs = tuple(V.ParamSpec(name, None, optional) for name, optional in params)

    def invoke(bound: list) -> MValue:
        return fn(*[V.force(item) for item in bound])

    return V.Function(specs, invoke, return_type)


def _text_arg(value: MValue) -> str:
    if isinstance(value, V.Text):
        return value.value
    raise V.convert_error(value, V.TypeValue("text"))


def _whole(cell: MValue, low: int) -> int:
    """A whole number at least ``low`` (a length, a position, a count); anything else is not measured."""
    if not isinstance(cell, V.Number):
        raise _unsupported("argument that is not a number")
    x = cell.value
    if x != x or x != math.floor(x) or x < low or x > _MAX_SLOT:
        raise _unsupported("argument that is not a whole number in range")
    return int(x)


def _list_items(value: MValue) -> list:
    if isinstance(value, V.List):
        return [V.force(item) for item in value.items]
    raise V.convert_error(value, V.TypeValue("list"))


def _text_list_units(value: MValue) -> list:
    """A list of text values as UTF-16 unit strings; a non-text item is not measured."""
    out = []
    for cell in _list_items(value):
        if not isinstance(cell, V.Text):
            raise _unsupported("list item that is not text")
        out.append(_units(cell.value))
    return out


# ---- Splitter ----------------------------------------------------------------

_INT32 = 2 ** 31
_QUOTE_NONE = 0
_QUOTE_CSV = 1


def _int32_number(cell: V.Number) -> int:
    """A number as a 32 bit integer; a fraction, NaN, infinity or a value out of range is the measured error."""
    x = cell.value
    if not math.isfinite(x) or x != int(x) or not -_INT32 <= x < _INT32:
        raise V.generic_error("The number is out of range of a 32 bit integer value.")
    return int(x)


def _list_arg(value: MValue) -> list:
    return _list_items(value)


def _logical_arg(value: MValue) -> bool:
    """An optional logical (startAtEnd): null is false, anything but a logical is a conversion error."""
    if isinstance(value, V.Null):
        return False
    if isinstance(value, V.Logical):
        return value.value
    raise V.convert_error(value, V.TypeValue("logical"))


def _number_or_null(value: MValue) -> Optional[V.Number]:
    """An optional number argument (quoteStyle, csvStyle): null gives None, a non-number is a conversion error."""
    if isinstance(value, V.Null):
        return None
    if isinstance(value, V.Number):
        return value
    raise V.convert_error(value, V.TypeValue("number"))


def _quote_style(value: Optional[V.Number]) -> int:
    """null is QuoteStyle.Csv; the only other valid value is 0 (None)."""
    if value is None:
        return _QUOTE_CSV
    if value.value in (0.0, 1.0):
        return int(value.value)
    raise V.generic_error("The specified QuoteStyle is invalid.")


def _length_list(value: MValue) -> list:
    out = []
    for cell in _list_arg(value):
        if not isinstance(cell, V.Number):
            raise V.generic_error("A length must be greater than or equal to zero.")
        size = _int32_number(cell)
        if size < 0:
            raise V.generic_error("A length must be greater than or equal to zero.")
        out.append(size)
    return out


def _position_list(value: MValue) -> list:
    out, previous = [], 0
    for cell in _list_arg(value):
        message = "A position must be numeric and greater than or equal to the previous position."
        if not isinstance(cell, V.Number):
            raise V.generic_error(message)
        spot = _int32_number(cell)
        if spot < previous:
            raise V.generic_error(message)
        out.append(spot)
        previous = spot
    return out


def _range_list(value: MValue) -> list:
    """{offset, length} pairs; a null length means the rest of the text (None)."""
    out = []
    for cell in _list_arg(value):
        if not isinstance(cell, V.List) or len(cell.items) != 2:
            raise V.generic_error("A range must consist of an offset and a length.")
        offset, length = (V.force(item) for item in cell.items)
        if not isinstance(offset, V.Number):
            raise V.convert_error(offset, V.TypeValue("number"))
        start = _int32_number(offset)
        if start < 0:
            raise V.generic_error("A range offset cannot be negative.")
        count = None
        if not isinstance(length, V.Null):
            if not isinstance(length, V.Number):
                raise V.convert_error(length, V.TypeValue("number"))
            count = _int32_number(length)
            if count < 0:
                raise V.generic_error("A range length cannot be negative.")
        out.append((start, count))
    return out


def _delimiter_list(value: MValue) -> list:
    out = []
    for cell in _list_arg(value):
        if not isinstance(cell, V.Text) or not cell.value:
            raise V.generic_error("A delimiter must be text at least 1 character in length.")
        out.append(_units(cell.value))
    return out


def _splitter(parts_of: Callable[[str], list]) -> V.Function:
    """A splitter: null gives an empty list; text is split into parts (UTF-16 unit strings)."""
    def run(value: MValue) -> MValue:
        if isinstance(value, V.Null):
            return V.List(())
        units = _units(_text_arg(value))
        return V.List(tuple(V.Text(_from_units(part)) for part in parts_of(units)))

    return _native((("text", False),), run, V.TypeValue("list"))


def _scan(units: str, delims: list, *, each: bool, quoted: bool, after_delimiter: bool = False,
          whitespace: bool = False) -> list:
    """Cut ``units`` at the delimiters that are outside double quotes.

    Measured rules: with a quote style of Csv a double quote starts or ends a quoted section (after_delimiter:
    only a quote at the start of a field starts one), a doubled quote inside a section is one quote, the quote
    characters are removed and a section left open runs to the end of the text. Any: at each position the first
    delimiter of the list that matches cuts. Each: the delimiters are used in order, each once; a text without
    the delimiter in force ends there. Whitespace: a run of white space cuts once."""
    out, cur = [], []
    n = len(units)
    i = k = 0
    in_quote = False
    field_start = True
    while i < n:
        ch = units[i]
        if in_quote:
            if ch == '"':
                if i + 1 < n and units[i + 1] == '"':
                    cur.append('"')
                    i += 2
                    continue
                in_quote = False
                i += 1
                continue
            cur.append(ch)
            i += 1
            continue
        if whitespace:
            if _is_space(ch):
                j = i
                while j < n and _is_space(units[j]):
                    j += 1
                out.append("".join(cur))
                cur, field_start, i = [], True, j
                continue
        else:
            hit = None
            for d in (delims[k:k + 1] if each else delims):
                if units.startswith(d, i):
                    hit = d
                    break
            if hit is not None:
                out.append("".join(cur))
                cur, field_start = [], True
                i += len(hit)
                k += 1
                continue
        if quoted and ch == '"' and (field_start or not after_delimiter):
            in_quote = True
            field_start = False
            i += 1
            continue
        cur.append(ch)
        field_start = False
        i += 1
    out.append("".join(cur))
    return out


def _delimiter_splitter(delims: list, *, each: bool, quote: int, from_end: bool, after_delimiter: bool = False,
                        whitespace: bool = False) -> MValue:
    quoted = quote == _QUOTE_CSV

    def parts(units: str) -> list:
        if from_end:
            found = _scan(units[::-1], [d[::-1] for d in delims], each=each, quoted=quoted,
                          after_delimiter=after_delimiter)
            return [part[::-1] for part in reversed(found)]
        return _scan(units, delims, each=each, quoted=quoted, after_delimiter=after_delimiter,
                     whitespace=whitespace)

    return _splitter(parts)


def _split_by_delimiter(delimiter: MValue, quote: MValue, csv_style: MValue) -> MValue:
    text = _text_arg(delimiter)
    quote_number = _number_or_null(quote)
    style_number = _number_or_null(csv_style)
    if not text:
        raise V.generic_error("A delimiter must be text at least 1 character in length.")
    style = _quote_style(quote_number)
    after_delimiter = False
    if style_number is not None:
        if style == _QUOTE_NONE:
            raise V.generic_error("'QuoteStyle.None' and 'CsvStyle' can't be used together.")
        if style_number.value not in (0.0, 1.0):
            raise V.generic_error("The specified CsvStyle is invalid.")
        after_delimiter = style_number.value == 0.0
        if after_delimiter and len(_units(text)) != 1:
            raise V.generic_error("The value isn't a single-character string.")
    return _delimiter_splitter([_units(text)], each=False, quote=style, from_end=False,
                               after_delimiter=after_delimiter)


def _split_any_delimiter(delimiters: MValue, quote: MValue, at_end: MValue) -> MValue:
    items = _list_arg(delimiters)
    quote_number = _number_or_null(quote)
    from_end = _logical_arg(at_end)
    delims = _delimiter_list(V.List(tuple(items)))
    style = _quote_style(quote_number)
    return _delimiter_splitter(delims, each=False, quote=style, from_end=from_end)


def _split_each_delimiter(delimiters: MValue, quote: MValue, at_end: MValue) -> MValue:
    items = _list_arg(delimiters)
    quote_number = _number_or_null(quote)
    from_end = _logical_arg(at_end)
    delims = _delimiter_list(V.List(tuple(items)))
    style = _quote_style(quote_number)
    return _delimiter_splitter(delims, each=True, quote=style, from_end=from_end)


def _split_lengths(lengths: MValue, at_end: MValue) -> MValue:
    _list_arg(lengths)
    from_end = _logical_arg(at_end)
    sizes = _length_list(lengths)

    def parts(units: str) -> list:
        out = []
        if from_end:
            pos = len(units)
            for size in sizes:
                start = max(0, pos - size)
                out.append(units[start:pos])
                pos = start
            return out[::-1]
        pos = 0
        for size in sizes:
            out.append(units[pos:pos + size])
            pos += size
        return out

    return _splitter(parts)


def _split_positions(positions: MValue, at_end: MValue) -> MValue:
    _list_arg(positions)
    from_end = _logical_arg(at_end)
    spots = _position_list(positions)

    def parts(units: str) -> list:
        n = len(units)
        if from_end:
            cuts = [max(0, n - spot) for spot in spots]
            out = [units[cuts[k + 1] if k + 1 < len(cuts) else 0:cuts[k]] for k in range(len(cuts))]
            return out[::-1]
        cuts = [min(spot, n) for spot in spots] + [n]
        return [units[cuts[k]:cuts[k + 1]] for k in range(len(spots))]

    return _splitter(parts)


def _split_ranges(ranges: MValue, at_end: MValue) -> MValue:
    _list_arg(ranges)
    from_end = _logical_arg(at_end)
    pairs = _range_list(ranges)

    def parts(units: str) -> list:
        n = len(units)
        if from_end:
            out = []
            for start, count in pairs:
                hi = max(0, n - start)
                lo = 0 if count is None else max(0, n - start - count)
                out.append(units[lo:hi])
            return out[::-1]
        return [units[min(start, n):(n if count is None else min(start + count, n))] for start, count in pairs]

    return _splitter(parts)


def _split_repeated(length: MValue, at_end: MValue) -> MValue:
    if not isinstance(length, V.Number):
        raise V.convert_error(length, V.TypeValue("number"))
    from_end = _logical_arg(at_end)
    size = _int32_number(length)
    if size < 0:
        raise V.generic_error("A length must be greater than or equal to zero.")

    def parts(units: str) -> list:
        if size == 0:
            return [""]
        if from_end:
            return [units[max(0, hi - size):hi] for hi in range(len(units), 0, -size)][::-1]
        return [units[i:i + size] for i in range(0, len(units), size)]

    return _splitter(parts)


def _split_whitespace(quote: MValue) -> MValue:
    style = _quote_style(_number_or_null(quote))
    return _delimiter_splitter([], each=False, quote=style, from_end=False, whitespace=True)


def _split_by_nothing() -> MValue:
    def run(value: MValue) -> MValue:
        if isinstance(value, V.Null):
            return V.List((V.Null(),))
        if isinstance(value, V.Text):
            return V.List((V.Text(value.value),))
        raise _unsupported("SplitByNothing of a value that is not text")

    return _native((("text", False),), run, V.TypeValue("list"))


def _transition_test(value: MValue) -> Callable[[str], bool]:
    """A character test for CharacterTransition: a function of one character (logical result) or a list of
    single characters."""
    if isinstance(value, V.Function):
        from .evaluator import apply_function  # local import: the evaluator imports this module

        def test(ch: str) -> bool:
            result = apply_function(value, [V.Text(_from_units(ch))])
            if not isinstance(result, V.Logical):
                raise _unsupported("transition function that does not return a logical")
            return result.value

        return test
    if isinstance(value, V.List):
        members = frozenset(_text_list_units(value))
        return lambda ch: ch in members
    raise _unsupported("transition argument")


def _split_transition(before: MValue, after: MValue) -> MValue:
    first = _transition_test(before)
    second = _transition_test(after)

    def parts(units: str) -> list:
        cuts = [i + 1 for i in range(len(units) - 1) if first(units[i]) and second(units[i + 1])]
        bounds = [0] + cuts + [len(units)]
        return [units[bounds[k]:bounds[k + 1]] for k in range(len(bounds) - 1)]

    return _splitter(parts)


# ---- Combiner ----------------------------------------------------------------

def _template_arg(value: MValue) -> str:
    """The optional template text the pieces are written over (null is empty)."""
    if isinstance(value, V.Null):
        return ""
    return _units(_text_arg(value))


def _combine_slots(slots: list, template: MValue) -> V.Function:
    """Write each item at its slot over the template: an item is cut to the slot length (None: whole), it
    replaces the characters it covers, and a start past the end of the text is filled with spaces. A missing item
    is empty and items beyond the slots are ignored."""
    base = _template_arg(template)

    def run(texts: MValue) -> MValue:
        cells = _list_items(texts)
        buffer = base
        for index, (start, width) in enumerate(slots):
            cell = cells[index] if index < len(cells) else V.Null()
            piece = "" if isinstance(cell, V.Null) else _units(_text_arg(cell))
            if width is not None:
                piece = piece[:width]
            if start > len(buffer):
                buffer += " " * (start - len(buffer))
            buffer = buffer[:start] + piece + buffer[start + len(piece):]
        return V.Text(_from_units(buffer))

    return _native((("texts", False),), run, V.TypeValue("text"))


def _combine_lengths(lengths: MValue, template: MValue) -> MValue:
    _list_arg(lengths)
    _template_arg(template)
    sizes = _length_list(lengths)
    starts = [sum(sizes[:i]) for i in range(len(sizes))]
    return _combine_slots(list(zip(starts, sizes)), template)


def _combine_positions(positions: MValue, template: MValue) -> MValue:
    _list_arg(positions)
    _template_arg(template)
    spots = _position_list(positions)
    widths = [b - a for a, b in zip(spots, spots[1:])] + [None]
    return _combine_slots(list(zip(spots, widths)), template)


def _combine_ranges(ranges: MValue, template: MValue) -> MValue:
    _list_arg(ranges)
    _template_arg(template)
    return _combine_slots(_range_list(ranges), template)


def _combine_each(delimiters: MValue, quote: MValue) -> MValue:
    items = _list_arg(delimiters)
    quote_number = _number_or_null(quote)
    delims = _delimiter_list(V.List(tuple(items)))
    quoted = _quote_style(quote_number) == _QUOTE_CSV

    def run(texts: MValue) -> MValue:
        out = []
        for index, cell in enumerate(_list_items(texts)):
            text = "" if isinstance(cell, V.Null) else _units(_text_arg(cell))
            if quoted and (any(c in text for c in '"\r\n') or (index < len(delims) and delims[index] in text)):
                text = '"' + text.replace('"', '""') + '"'
            if index and index - 1 < len(delims):
                out.append(delims[index - 1])
            out.append(text)
        return V.Text(_from_units("".join(out)))

    return _native((("texts", False),), run, V.TypeValue("text"))


# ---- Comparer ----------------------------------------------------------------

_CULTURE = "en-US"


def _alnum_key(units: str) -> list:
    """Primary collation keys for ASCII letters and digits: digits before letters, case ignored."""
    keys = []
    for ch in units:
        if "0" <= ch <= "9":
            keys.append((0, ch))
        elif "a" <= ch <= "z" or "A" <= ch <= "Z":
            keys.append((1, ch.lower()))
        else:
            raise _unsupported("culture comparison of characters other than ASCII letters and digits")
    return keys


def _culture_text(x: str, y: str, ignore_case: bool) -> int:
    kx, ky = _alnum_key(_units(x)), _alnum_key(_units(y))
    if kx != ky:
        return -1 if kx < ky else 1
    if ignore_case:
        return 0
    for a, b in zip(x, y):
        if a != b:  # same letter, other case: lower case sorts first
            return -1 if a.islower() else 1
    return 0


_NATURAL_KINDS = frozenset({"number", "text", "logical", "date", "time", "datetime", "datetimezone", "duration",
                            "binary"})
# Value.Compare orders the kinds: null, time, date, datetime, datetimezone, duration, number, logical, text,
# binary, then the kinds that cannot be ordered at all (type, list, record, function, table), which are an
# error as the left operand but sort after the others as the right one (measured).
_KIND_RANK = {"null": 0, "time": 1, "date": 2, "datetime": 3, "datetimezone": 4, "duration": 5, "number": 6,
              "logical": 7, "text": 8, "binary": 9}
_UNORDERED_RANK = 10


def _natural_order(a: MValue, b: MValue, fold: bool = False) -> int:
    """Two values of one kind in their natural order (NaN is the lowest number, text is ordinal, binary is by
    bytes); any other pair is the operator error of ``<``, naming the types in call order."""
    kind = V.kind_of(a)
    if kind != V.kind_of(b) or kind not in _NATURAL_KINDS:
        raise V.operator_error("<", a, b)
    if kind == "number":
        x, y = a.value, b.value
        if x != x or y != y:
            return (y != y) - (x != x) if (x != x) != (y != y) else 0
        return (x > y) - (x < y)
    if kind == "text":
        x, y = _units(a.value), _units(b.value)
        if fold:
            x, y = _fold(x), _fold(y)
    elif kind == "binary":
        x, y = a.value, b.value
    else:
        x, y = _list_key(a), _list_key(b)
    return (x > y) - (x < y)


def compare_non_text(a: MValue, b: MValue, fold: bool) -> MValue:
    """The Comparer.Ordinal / OrdinalIgnoreCase comparison of values that are not both text (called from text.py):
    null with null is 0; otherwise the natural order of one kind, or the operator error."""
    if isinstance(a, V.Null) and isinstance(b, V.Null):
        return V.Number(0.0)
    return V.Number(float(_natural_order(a, b, fold)))


def _value_order(a: MValue, b: MValue) -> int:
    """Value.Compare: the natural order within a kind, the kind rank across kinds (null first)."""
    ra = _KIND_RANK.get(V.kind_of(a), _UNORDERED_RANK)
    rb = _KIND_RANK.get(V.kind_of(b), _UNORDERED_RANK)
    if ra == _UNORDERED_RANK:  # measured: a left operand that cannot be ordered is an error whatever the right
        raise V.operator_error("<", a, b)
    if ra != rb:
        return (ra > rb) - (ra < rb)
    if ra == 0:
        return 0
    return _natural_order(a, b)


def _culture_order(a: MValue, b: MValue, ignore_case: bool) -> int:
    if isinstance(a, V.Text) and isinstance(b, V.Text):
        return _culture_text(a.value, b.value, ignore_case)
    return _value_order(a, b)


def _comparer_from_culture(culture: MValue, ignore_case: MValue) -> MValue:
    if not isinstance(culture, V.Text) or culture.value != _CULTURE:
        raise _unsupported("culture other than en-US")
    if isinstance(ignore_case, V.Null):
        fold = False
    elif isinstance(ignore_case, V.Logical):
        fold = ignore_case.value
    else:
        raise _unsupported("ignoreCase argument")

    def compare(x: MValue, y: MValue) -> MValue:
        return V.Number(float(_culture_order(x, y, fold)))

    return _native((("x", False), ("y", False)), compare)


_DECIMAL_LIMIT = 7.9228162514264337593543950335e28
_DECIMAL_CONTEXT = _decimal.Context(prec=80, rounding=_decimal.ROUND_HALF_EVEN)


def _precision_arg(value: MValue) -> bool:
    """Precision.Double (0, also null) or Precision.Decimal (1); True means decimal."""
    if isinstance(value, V.Null):
        return False
    if not isinstance(value, V.Number):
        raise V.convert_error(value, V.TypeValue("number"))
    if value.value not in (0.0, 1.0):
        raise V.generic_error("The value for a 'Precision.Type' enumeration was not one of the allowed values: "
                              "'Precision.Double, Precision.Decimal'.")
    return value.value == 1.0


def _to_decimal(number: V.Number) -> _decimal.Decimal:
    """A number as a .NET decimal: a literal keeps its digits, a computed double its 15 significant digits;
    28 decimal places at most, and nothing beyond the decimal range (NaN and infinity included)."""
    x = number.value
    if not math.isfinite(x) or abs(x) >= _DECIMAL_LIMIT:
        raise V.generic_error("The number is out of range of a decimal value.")
    return _number_decimal_of(number).quantize(_decimal.Decimal(1).scaleb(-28), context=_DECIMAL_CONTEXT)


def _equal(x: MValue, y: MValue, fold: bool = False, decimal: bool = False) -> bool:
    """Equality of two values: kinds must match, lists and records compare their items, text folds its case when
    ``fold``, numbers compare as decimals when ``decimal`` (null equals null)."""
    if isinstance(x, V.Null) or isinstance(y, V.Null):
        return isinstance(x, V.Null) and isinstance(y, V.Null)
    kind = V.kind_of(x)
    if kind != V.kind_of(y):
        return False
    if kind == "number" and decimal:
        return _to_decimal(x) == _to_decimal(y)
    if kind == "text" and fold:
        return _fold(_units(x.value)) == _fold(_units(y.value))
    if kind == "list":
        return len(x.items) == len(y.items) and all(
            _equal(V.force(p), V.force(q), fold, decimal) for p, q in zip(x.items, y.items))
    if kind == "record":
        if sorted(x.names()) != sorted(y.names()):
            return False
        return all(_equal(x.get(n), y.get(n), fold, decimal) for n in x.names())
    if (fold or decimal) and kind == "table":
        raise _unsupported("table equality with a comparer or precision")
    from .evaluator import equals  # local import: the evaluator imports this module
    return equals(x, y)


def _equal_for(comparer: MValue) -> Callable[[MValue, MValue], bool]:
    """Comparer.Equals: Ordinal is exact equality, OrdinalIgnoreCase folds the case of text."""
    if comparer is COMPARER_ORDINAL:
        return lambda x, y: _equal(x, y, False)
    if comparer is COMPARER_ORDINAL_IGNORE_CASE:
        return lambda x, y: _equal(x, y, True)
    raise _unsupported("comparer for Comparer.Equals")


def _comparer_equals(comparer: MValue, x: MValue, y: MValue) -> MValue:
    if not isinstance(comparer, V.Function):
        raise V.convert_error(comparer, V.TypeValue("function"))
    return V.Logical(_equal_for(comparer)(x, y))


# ---- Value -------------------------------------------------------------------

def _value_compare(a: MValue, b: MValue, precision: MValue) -> MValue:
    decimal = _precision_arg(precision)
    if decimal and isinstance(a, V.Number) and isinstance(b, V.Number):
        x, y = _to_decimal(a), _to_decimal(b)
        return V.Number(float((x > y) - (x < y)))
    return V.Number(float(_value_order(a, b)))


def _value_equals(a: MValue, b: MValue, precision: MValue) -> MValue:
    return V.Logical(_equal(a, b, False, _precision_arg(precision)))


def _value_nullable_equals(a: MValue, b: MValue, precision: MValue) -> MValue:
    decimal = _precision_arg(precision)
    if isinstance(a, V.Null) or isinstance(b, V.Null):
        return V.Null()
    return V.Logical(_equal(a, b, False, decimal))


def _arith(op: str) -> Callable[[MValue, MValue], MValue]:
    def run(a: MValue, b: MValue) -> MValue:
        from .evaluator import arithmetic  # local import: the evaluator imports this module

        return arithmetic(op, a, b)

    return run


def _value_type(value: MValue) -> MValue:
    if isinstance(value, V.Number) and value.subtype is not None:
        # Power BI's Value.Type of an Int64 cell is not a value this engine has measured (the saved answer for
        # Value.Type([Units]) = Int64.Type is false, the plain number type gives true): refuse, never guess.
        raise _unsupported(f"Value.Type of a {value.subtype} value")
    if isinstance(value, V.Function):
        if value.origin is None:
            # Library function: use measured return type from RETURN_TYPES
            name = _library_name(value)
            ret_type = None
            if name and name in RETURN_TYPES:
                ret_type = _type_from_spec(*RETURN_TYPES[name])
            elif value.return_type is not None:
                ret_type = value.return_type
            params = tuple((spec.name, spec.type_, spec.optional) for spec in value.params)
            return V.TypeValue("function", signature=(params, ret_type), library_name=name)
        else:
            # M-written function: reports its own declared signature
            params = tuple((spec.name, spec.type_ if spec.type_ is not None else V.TypeValue("any"), spec.optional)
                           for spec in value.params)
            ret = value.return_type
            return V.TypeValue("function", signature=(params, ret))
    return V.TypeValue(V.kind_of(value))


def _value_metadata(value: MValue) -> MValue:
    meta = getattr(value, "meta", None)
    return meta if meta is not None else V.Record(())


def _value_replace_metadata(value: MValue, meta: MValue) -> MValue:
    if not isinstance(meta, V.Record):
        raise V.convert_error(meta, V.TypeValue("record"))
    return V.with_meta(value, meta)


def _value_remove_metadata(value: MValue) -> MValue:
    return V.with_meta(value, None)


_US_DATE = r"[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}"
_US_CLOCK = r"[0-9]{1,2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,7})?)? (AM|PM)"


def _us_clock(text: str) -> tuple:
    """(local ticks of the time of day, text after the clock) for h:mm[:ss[.fraction]] AM|PM."""
    import re

    match = re.match(r"([0-9]{1,2}):([0-9]{2})(?::([0-9]{2})(?:\.([0-9]{1,7}))?)? (AM|PM)", text)
    hour, minute = int(match.group(1)), int(match.group(2))
    second = int(match.group(3) or 0)
    fraction = match.group(4) or ""
    if not 1 <= hour <= 12:
        raise _unsupported("clock hour that is not measured")
    if match.group(5) == "PM" and hour != 12:
        hour += 12
    if match.group(5) == "AM" and hour == 12:
        hour = 0
    ticks = V.time_ticks(hour, minute, second) + int(fraction.ljust(7, "0") or 0)
    return ticks, text[match.end():]


def _us_day(text: str) -> tuple:
    import datetime as dt
    import re

    match = re.match(r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})", text)
    try:
        day = dt.date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
    except ValueError:
        raise _unsupported("date that is not valid")
    return V.date_ticks(day), text[match.end():]


def _us_time(text: str) -> MValue:
    ticks, rest = _us_clock(text)
    if rest:
        raise _unsupported("time text with trailing characters")
    return V.make_time(ticks)


def _us_datetime(text: str) -> MValue:
    day_ticks, rest = _us_day(text)
    clock_ticks, rest = _us_clock(rest.lstrip(" "))
    if rest:
        raise _unsupported("datetime text with trailing characters")
    return V.make_datetime(day_ticks + clock_ticks)


def _us_datetimezone(text: str) -> MValue:
    import re

    day_ticks, rest = _us_day(text)
    clock_ticks, rest = _us_clock(rest.lstrip(" "))
    match = re.fullmatch(r" ([+-])([0-9]{2}):([0-9]{2})", rest)
    if match is None:
        raise _unsupported("datetimezone text with an offset that is not measured")
    minutes = int(match.group(2)) * 60 + int(match.group(3))
    offset = -minutes if match.group(1) == "-" else minutes
    return V.make_datetimezone(day_ticks + clock_ticks, offset)


_ISO_DATE = r"[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}"
_ISO_CLOCK = r"[0-9]{1,2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,7})?)?"


def _value_from_text(value: MValue, options: MValue = V.Null()) -> MValue:
    """Value.FromText: a value that is not text is returned as it is; text is read as null (blank, or exactly
    ``null``), a number (Number.FromText, en-US or culture), a logical, a date, time, datetime, datetimezone or duration in
    the forms measured, and any other text stays text."""
    import re
    from .date_fns import DATE_TIME_GLOBALS, DATE_GLOBALS, TIME_GLOBALS, DATETIMEZONE_GLOBALS  # local import: date_fns is loaded by the stdlib
    from .number import NUMBER_GLOBALS

    if not isinstance(options, V.Null):
        if not isinstance(options, V.Text):
            raise V.convert_error(options, V.TypeValue("text"))
        if options.value not in ("en-US", "de-DE", "de"):
            raise _unsupported(f"Value.FromText culture '{options.value}'")
    if not isinstance(value, (V.Text, V.Null)):
        return value
    if isinstance(value, V.Null):
        return V.Null()
    text = value.value
    stripped = "".join(text).strip()
    if not stripped or stripped == "null":
        return V.Null()
    try:
        num_opts = options if isinstance(options, V.Text) else V.Null()
        return NUMBER_GLOBALS["Number.FromText"].invoke([V.Text(text), num_opts])
    except MError:
        pass
    if stripped.lower() in ("true", "false"):
        return V.Logical(stripped.lower() == "true")

    # Explicit clock/machine time zone refusals:
    if text.endswith(("+00:00", "-00:00", "Z", "z")):
        raise _unsupported("zero UTC offset, which Power BI turns into a local datetime")
    if re.fullmatch(r"\d{1,2}[\s/.-]\d{1,2}", text):
        raise _unsupported("date without year (clock dependent)")
    if re.fullmatch(r"(\d{1,2}[\s/.-]+[A-Za-z]+|[A-Za-z]+[\s/.-]+\d{1,2})", text):
        raise _unsupported("date without year (clock dependent)")
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        raise _unsupported("time without date (clock dependent)")

    if re.fullmatch(_US_DATE, text):
        route = "Date.FromText"
    elif re.fullmatch(_US_DATE + " " + _US_CLOCK + r" [+-][0-9]{2}:[0-9]{2}", text):
        return _us_datetimezone(text)
    elif re.fullmatch(_US_DATE + " " + _US_CLOCK, text):
        return _us_datetime(text)
    elif re.fullmatch(_US_CLOCK, text):
        return _us_time(text)
    elif re.fullmatch(_ISO_DATE, text):
        route = "Date.FromText"
    elif re.fullmatch(_ISO_DATE + "[T ]" + _ISO_CLOCK, text):
        route = "DateTime.FromText"
    elif re.fullmatch(_ISO_DATE + "[T ]" + _ISO_CLOCK + r" ?[+-][0-9]{2}:[0-9]{2}", text):
        route = "DateTimeZone.FromText"
    elif re.fullmatch(_ISO_CLOCK, text):
        route = "Time.FromText"
    elif re.fullmatch(r"-?([0-9]+\.)?" + _ISO_CLOCK, text):
        route = "Duration.FromText"
    else:
        try:
            return DATE_GLOBALS["Date.FromText"].invoke([V.Text(text)])
        except MError:
            pass
        try:
            return TIME_GLOBALS["Time.FromText"].invoke([V.Text(text)])
        except MError:
            pass
        try:
            if re.search(r"[+-]\d{2}:\d{2}$", text):
                return DATETIMEZONE_GLOBALS["DateTimeZone.FromText"].invoke([V.Text(text)])
        except MError:
            pass
        if not any(c.isdigit() for c in text):
            return V.Text(text)
        raise _unsupported(f"Value.FromText text '{text}'")
    try:
        return DATE_TIME_GLOBALS[route].invoke([V.Text(text)])
    except MError:
        if not any(c.isdigit() for c in text):
            return V.Text(text)
        raise _unsupported(f"Value.FromText text '{text}'")


# ---- Type --------------------------------------------------------------------

_FACET_NAMES = ("NumericPrecisionBase", "NumericPrecision", "NumericScale", "IsSigned", "DateTimePrecision",
                "MaxLength", "IsVariableLength", "NativeTypeName", "NativeDefaultExpression", "NativeExpression")
_COMPOSITE = ("list", "record", "table", "function")


def _type_arg(value: MValue) -> V.TypeValue:
    if isinstance(value, V.TypeValue):
        return value
    raise V.convert_error(value, V.TypeValue("type"))


def _structured(t: V.TypeValue) -> bool:
    """A type with a shape written out: a record or table with fields, a list with an item type, a function
    with parameters."""
    return (t.fields is not None or t.item is not None or t.signature is not None or t.raw_fields is not None)


def _type_is(a: MValue, b: MValue) -> MValue:
    """Type.Is(x, y): x is y when every value of x is a value of y (measured). any accepts everything and
    anynonnull everything but null and nullable types; null fits any nullable type; a nullable type does not fit
    its non-nullable one, except for the list, record, table and function kinds, where nullability does not
    matter; a type with a shape written out (a field list, an item type, parameters) fits only itself and the
    plain kind."""
    x, y = _type_arg(a), _type_arg(b)
    if y.name == "any":
        return V.Logical(True)
    if y.name == "anynonnull":
        if x.name == "any" or x.name == "null":
            return V.Logical(False)
        return V.Logical(x.name in ("anynonnull",) + _COMPOSITE or not x.nullable)
    if x.name in ("any", "anynonnull"):
        return V.Logical(False)
    if x.name == "null":
        return V.Logical(y.nullable or y.name == "null")
    if x.name != y.name:
        return V.Logical(False)
    if x.name in _COMPOSITE:
        return V.Logical(x is y or not _structured(y))
    return V.Logical(not x.nullable or y.nullable)


def _type_is_nullable(t: MValue) -> MValue:
    x = _type_arg(t)
    return V.Logical(x.nullable or x.name in ("null", "any"))


def _type_non_nullable(t: MValue) -> MValue:
    x = _type_arg(t)
    if x.name == "any":
        return V.TypeValue("anynonnull")
    return _dc_replace(x, nullable=False, meta=None)


def _record_type(t: MValue, is_open: bool) -> MValue:
    x = _type_arg(t)
    if x.name != "record" or x.fields is None:
        raise _unsupported("open or closed record of a type that is not a record type")
    return V.TypeValue("record", fields=x.fields, open_record=is_open)


def _is_open_record(t: MValue) -> MValue:
    x = _type_arg(t)
    if x.name != "record" or x.fields is None:
        raise _unsupported("Type.IsOpenRecord of a type that is not a record type")
    return V.Logical(x.open_record)


def _function_signature(t: MValue) -> tuple:
    """The (parameters, return type) of a function type; a type that is not a function type or is the abstract
    ``type function`` is the measured error."""
    x = _type_arg(t)
    if x.name != "function":
        raise V.generic_error("We cannot convert Type to Function type.")
    if x.signature is None:
        raise V.generic_error("Function.Type is abstract and has no defined parameters.")
    return x.signature


def _signature(t: MValue) -> tuple:
    return _function_signature(t)


def _function_return(t: MValue) -> MValue:
    x = _type_arg(t)
    if x.name != "function":
        raise V.generic_error("We cannot convert Type to Function type.")
    if x.signature is None:
        raise V.generic_error("Function.Type is abstract and has no defined parameters.")
    _params, ret = x.signature
    if ret is not None:
        return ret
    if x.library_name is not None:
        raise _unsupported(f"Type.FunctionReturn of library function '{x.library_name}'")
    raise _unsupported("Type.FunctionReturn of a function without declared return type")


def _function_required_parameters(t: MValue) -> MValue:
    params, _ret = _function_signature(t)
    return V.Number(float(sum(1 for _name, _type, optional in params if not optional)))


def _function_parameters(t: MValue) -> MValue:
    x = _type_arg(t)
    if x.name != "function":
        raise V.generic_error("We cannot convert Type to Function type.")
    if x.signature is None:
        raise V.generic_error("Function.Type is abstract and has no defined parameters.")
    if x.library_name is not None:
        raise _unsupported(f"Type.FunctionParameters of library function '{x.library_name}'")
    params, _ret = x.signature
    seen = set()
    out = []
    for name, ptype, optional in params:
        if name in seen:
            raise V.generic_error(f"Duplicate parameter named '{name}'.")
        seen.add(name)
        if ptype is None:
            ptype = V.TypeValue("any")
        out.append((name, _dc_replace(ptype, nullable=True) if optional else ptype))
    return V.Record(tuple(out))


def _add_table_key(table_type: MValue, columns: MValue, is_primary: MValue) -> MValue:
    t = _type_arg(table_type)
    if t.name != "table":
        raise _unsupported("Type.AddTableKey of a type that is not a table type")
    if not isinstance(columns, V.List):
        raise V.convert_error(columns, V.TypeValue("list"))
    if not isinstance(is_primary, V.Logical):
        raise V.convert_error(is_primary, V.TypeValue("logical"))
    return t


def _for_function(signature: MValue, min_count: MValue) -> MValue:
    if not isinstance(signature, V.Record):
        raise V.convert_error(signature, V.TypeValue("record"))
    if not isinstance(min_count, V.Number):
        raise V.convert_error(min_count, V.TypeValue("number"))
    ret_val = signature.get("ReturnType")
    ret_type = _type_arg(ret_val) if ret_val is not None else V.TypeValue("any")
    params_val = signature.get("Parameters")
    params_list = []
    if isinstance(params_val, V.Record):
        for name in params_val.names():
            pt = _type_arg(params_val.get(name))
            params_list.append((name, pt, False))
    return V.TypeValue("function", signature=(tuple(params_list), ret_type))


def _list_item(t: MValue) -> MValue:
    x = _type_arg(t)
    if x.name != "list":
        raise V.generic_error("We cannot convert Type to List type.")
    return x.item if x.item is not None else V.TypeValue("any")


def _type_for_record(fields: MValue, is_open: MValue) -> MValue:
    """Type.ForRecord: the field record is kept as given (its values are not checked until read back by
    Type.RecordFields); the shape used by other functions takes the entries that are well formed."""
    if not isinstance(fields, V.Record):
        raise V.convert_error(fields, V.TypeValue("record"))
    if not isinstance(is_open, V.Logical):
        raise V.convert_error(is_open, V.TypeValue("logical"))
    shape = []
    for name in fields.names():
        try:
            entry = V.force(fields.get(name))
            if isinstance(entry, V.Record) and "Type" in entry.names():
                ftype = V.force(entry.get("Type"))
                optional = V.force(entry.get("Optional")) if "Optional" in entry.names() else V.Logical(False)
                if isinstance(ftype, V.TypeValue) and isinstance(optional, V.Logical):
                    shape.append((name, ftype, optional.value))
        except MError:
            pass
    return V.TypeValue("record", fields=tuple(shape), open_record=is_open.value, raw_fields=fields)


def _function_from(t: MValue, impl: MValue) -> MValue:
    """Function.From(function type, implementation): the implementation receives the arguments that were passed
    as a list; neither their number nor their types nor the result is checked (measured)."""
    from .evaluator import apply_function  # local import: the evaluator imports this module

    x = _type_arg(t)
    if x.name != "function":
        raise V.generic_error("We cannot convert Type to Function type.")
    params, ret = x.signature if x.signature is not None else ((), None)
    if not isinstance(impl, V.Function):
        raise V.convert_error(impl, V.TypeValue("function"))
    specs = tuple(V.ParamSpec(name, ptype, optional) for name, ptype, optional in params)

    def invoke(items: list) -> MValue:
        return apply_function(impl, [V.List(tuple(items))])

    return V.Function(specs, invoke, ret, None, "from", True)


def _function_is_data_source(fn: MValue) -> MValue:
    """Function.IsDataSource: a function written in M is not a data source (measured); a library function is not
    measured."""
    if not isinstance(fn, V.Function) or fn.origin is None:
        raise _unsupported("Function.IsDataSource of a value that is not a function written in M")
    return V.Logical(False)


def _function_invoke_after(fn: MValue, delay: MValue) -> MValue:
    """Function.InvokeAfter: calls the function without arguments (the waiting is not simulated)."""
    from .evaluator import apply_function  # local import: the evaluator imports this module

    if not isinstance(fn, V.Function):
        raise V.convert_error(fn, V.TypeValue("function"))
    if not isinstance(delay, V.Duration):
        raise V.convert_error(delay, V.TypeValue("duration"))
    if delay.ticks < 0:
        raise V.generic_error("The Duration operation failed because the resulting duration falls outside the "
                              "range of allowed values.")
    return apply_function(fn, [])


_FACET_TEXT = ("NativeTypeName", "NativeDefaultExpression", "NativeExpression")
_NON_NEGATIVE = "The NumericPrecisionBase, NumericPrecision, NumericScale, DateTimePrecision, and MaxLength " \
                "facets must have non-negative values."


def _type_facets(t: MValue) -> MValue:
    x = _type_arg(t)
    values = x.facets if x.facets is not None else (V.Null(),) * len(_FACET_NAMES)
    return V.Record(tuple(zip(_FACET_NAMES, values)))


def _int_facet(value: MValue, bits: int) -> MValue:
    """A numeric facet: null, or a whole number that fits ``bits`` bits and is not negative."""
    if isinstance(value, V.Null):
        return value
    if not isinstance(value, V.Number):
        raise V.convert_error(value, V.TypeValue("number"))
    x = value.value
    if not math.isfinite(x) or x != int(x) or not -(2 ** (bits - 1)) <= x < 2 ** (bits - 1):
        raise V.generic_error(f"The number is out of range of a {bits} bit integer value.")
    if x < 0:
        raise V.generic_error(_NON_NEGATIVE)
    return V.Number(float(int(x)))


def _type_replace_facets(t: MValue, facets: MValue) -> MValue:
    """Type.ReplaceFacets: the facets given replace all the facets of the type (the others are null)."""
    x = _type_arg(t)
    if not isinstance(facets, V.Record):
        raise V.convert_error(facets, V.TypeValue("record"))
    for name in facets.names():
        if name not in _FACET_NAMES:
            raise V.generic_error(f"The facet '{name}' is not supported.")
    given = {name: V.force(facets.get(name)) for name in facets.names()}
    out = {name: V.Null() for name in _FACET_NAMES}
    for name in _FACET_NAMES[:3]:  # the numeric group is checked first, then the others in order
        out[name] = _int_facet(given.get(name, V.Null()), 32)
    if (not isinstance(out["NumericPrecision"], V.Null) or not isinstance(out["NumericScale"], V.Null)) \
            and isinstance(out["NumericPrecisionBase"], V.Null):
        raise V.generic_error("The NumericPrecisionBase facet must be specified when either of the "
                              "NumericPrecision or NumericScale facets are specified.")
    for name in _FACET_NAMES[3:]:
        value = given.get(name, V.Null())
        if name in ("IsSigned", "IsVariableLength"):
            out[name] = V.Null() if isinstance(value, V.Null) else _logical_facet(value)
        elif name == "DateTimePrecision":
            out[name] = _int_facet(value, 32)
        elif name == "MaxLength":
            out[name] = _int_facet(value, 64)
        else:
            out[name] = value if isinstance(value, (V.Null, V.Text)) else _raise(
                V.convert_error(value, V.TypeValue("text")))
    return _dc_replace(x, facets=tuple(out[name] for name in _FACET_NAMES), meta=None)


def _logical_facet(value: MValue) -> MValue:
    if isinstance(value, V.Logical):
        return value
    raise V.convert_error(value, V.TypeValue("logical"))


def _raise(error: Exception):
    raise error


def _type_union(types: MValue) -> MValue:
    items = [_type_arg(cell) for cell in _list_items(types)]
    if not items:
        raise _unsupported("Type.Union of no types")
    if any(t.name in _COMPOSITE or t.fields is not None for t in items):
        raise _unsupported("Type.Union of composite types")
    names = {t.name for t in items}
    nullable = any(t.nullable or t.name in ("null", "any") for t in items)
    if len(names) == 1:
        name = names.pop()
        return V.TypeValue(name, nullable and name not in ("null",))
    return V.TypeValue("any", True)


def _table_row(t: MValue) -> MValue:
    x = _type_arg(t)
    if x.name != "table" or x.fields is None:
        raise _unsupported("Type.TableRow of a type that is not a table type")
    return V.TypeValue("record", fields=x.fields)


def _table_column(t: MValue, name: MValue) -> MValue:
    x = _type_arg(t)
    if x.name != "table" or x.fields is None:
        raise _unsupported("Type.TableColumn of a type that is not a table type")
    column = _text_arg(name)
    for field_name, field_type, _optional in x.fields:
        if field_name == column:
            return field_type
    raise _unsupported("Type.TableColumn of a column that is not in the table type")


def _table_keys(t: MValue) -> MValue:
    x = _type_arg(t)
    if x.name != "table" or x.fields is None:
        raise _unsupported("Type.TableKeys of a type that is not a table type")
    return V.List(())


# ---- registration ------------------------------------------------------------

VALUE_GLOBALS: dict = {
    "Splitter.SplitTextByDelimiter": _native((("delimiter", False), ("quoteStyle", True), ("csvStyle", True)),
                                             _split_by_delimiter),
    "Splitter.SplitTextByAnyDelimiter": _native((("delimiters", False), ("quoteStyle", True), ("startAtEnd", True)),
                                                _split_any_delimiter),
    "Splitter.SplitTextByEachDelimiter": _native((("delimiters", False), ("quoteStyle", True), ("startAtEnd", True)),
                                                 _split_each_delimiter),
    "Splitter.SplitTextByLengths": _native((("lengths", False), ("startAtEnd", True)), _split_lengths),
    "Splitter.SplitTextByPositions": _native((("positions", False), ("startAtEnd", True)), _split_positions),
    "Splitter.SplitTextByRanges": _native((("ranges", False), ("startAtEnd", True)), _split_ranges),
    "Splitter.SplitTextByRepeatedLengths": _native((("length", False), ("startAtEnd", True)), _split_repeated),
    "Splitter.SplitTextByWhitespace": _native((("quoteStyle", True),), _split_whitespace),
    "Splitter.SplitByNothing": _native((), lambda: _split_by_nothing()),
    "Splitter.SplitTextByCharacterTransition": _native((("before", False), ("after", False)), _split_transition),
    "Combiner.CombineTextByEachDelimiter": _native((("delimiters", False), ("quoteStyle", True)), _combine_each),
    "Combiner.CombineTextByLengths": _native((("lengths", False), ("template", True)), _combine_lengths),
    "Combiner.CombineTextByPositions": _native((("positions", False), ("template", True)), _combine_positions),
    "Combiner.CombineTextByRanges": _native((("ranges", False), ("template", True)), _combine_ranges),
    "Comparer.Ordinal": COMPARER_ORDINAL,
    "Comparer.OrdinalIgnoreCase": COMPARER_ORDINAL_IGNORE_CASE,
    "Comparer.FromCulture": _native((("culture", False), ("ignoreCase", True)), _comparer_from_culture),
    "Comparer.Equals": _native((("comparer", False), ("x", False), ("y", False)), _comparer_equals),
    "Value.Compare": _native((("x", False), ("y", False), ("precision", True)), _value_compare),
    "Value.Equals": _native((("x", False), ("y", False), ("precision", True)), _value_equals),
    "Value.NullableEquals": _native((("x", False), ("y", False), ("precision", True)), _value_nullable_equals),
    "Precision.Double": V.Number(0.0),
    "Precision.Decimal": V.Number(1.0),
    "Value.Add": _native((("x", False), ("y", False)), _arith("+")),
    "Value.Subtract": _native((("x", False), ("y", False)), _arith("-")),
    "Value.Multiply": _native((("x", False), ("y", False)), _arith("*")),
    "Value.Divide": _native((("x", False), ("y", False)), _arith("/")),
    "Value.Type": _native((("value", False),), _value_type),
    "Value.Metadata": _native((("value", False),), _value_metadata),
    "Value.ReplaceMetadata": _native((("value", False), ("metadata", False)), _value_replace_metadata),
    "Value.RemoveMetadata": _native((("value", False),), _value_remove_metadata),
    "Value.FromText": _native((("text", False), ("options", True)), _value_from_text),
    "Type.Is": _native((("type", False), ("targetType", False)), _type_is),
    "Type.IsNullable": _native((("type", False),), _type_is_nullable),
    "Type.NonNullable": _native((("type", False),), _type_non_nullable),
    "Type.Facets": _native((("type", False),), _type_facets),
    "Type.Union": _native((("types", False),), _type_union),
    "Type.TableRow": _native((("tableType", False),), _table_row),
    "Type.TableColumn": _native((("tableType", False), ("column", False)), _table_column),
    "Type.TableKeys": _native((("tableType", False),), _table_keys),
    "Type.IsOpenRecord": _native((("type", False),), _is_open_record),
    "Type.OpenRecord": _native((("type", False),), lambda t: _record_type(t, True)),
    "Type.ClosedRecord": _native((("type", False),), lambda t: _record_type(t, False)),
    "Type.FunctionReturn": _native((("type", False),), _function_return),
    "Type.FunctionRequiredParameters": _native((("type", False),), _function_required_parameters),
    "Type.FunctionParameters": _native((("type", False),), _function_parameters),
    "Type.ListItem": _native((("type", False),), _list_item),
    "Type.ForRecord": _native((("fields", False), ("isOpen", False)), _type_for_record),
    "Type.ReplaceFacets": _native((("type", False), ("facets", False)), _type_replace_facets),
    "Function.From": _native((("type", False), ("implementation", False)), _function_from),
    "Function.IsDataSource": _native((("function", False),), _function_is_data_source),
    "Function.InvokeAfter": _native((("function", False), ("delay", False)), _function_invoke_after),
}


# ---- Value.As, Logical.From, Function, Expression, Character, Occurrence -----------

_DATA_FORMAT_KINDS = (V.Record, V.Table, V.Date, V.Duration, V.DateTimeZone, V.TypeValue)


def _value_as(value: MValue, t: MValue) -> MValue:
    return V.check_type(value, _type_arg(t))


def _logical_from(value: MValue) -> MValue:
    """Logical.From: null, logical, number and text are the existing conversion (blank text is null); every
    other kind raises the DataFormat error."""
    from .number import NOT_LOGICAL_TEXT, _logical_from as number_logical_from  # local import: number is a sibling

    if isinstance(value, (V.Null, V.Logical, V.Number, V.Text)):
        return number_logical_from(value)
    raise MError("DataFormat.Error", NOT_LOGICAL_TEXT, fmt=NOT_LOGICAL_TEXT)  # every other kind (measured)


def _function_invoke(fn: MValue, args: MValue) -> MValue:
    from .evaluator import apply_function  # local import: the evaluator imports this module

    if not isinstance(args, V.List):
        raise V.convert_error(args, V.TypeValue("list"))
    return apply_function(fn, list(args.items))


_CONSTANT_KINDS = (V.Null, V.Logical, V.Number, V.Text, V.Date, V.Time, V.DateTime, V.DateTimeZone, V.Duration)


def _expression_constant(value: MValue) -> MValue:
    if isinstance(value, V.List):
        raise V.generic_error("Expected a constant value. List is not a constant.")
    if isinstance(value, _CONSTANT_KINDS):
        return V.Text(V.describe_value(value))
    raise _unsupported("Expression.Constant of this kind")


_M_KEYWORDS = frozenset({"and", "as", "each", "else", "error", "false", "if", "in", "is", "let", "meta", "not",
                         "null", "or", "otherwise", "section", "shared", "then", "true", "try", "type"})


def _expression_identifier(name: MValue) -> MValue:
    import re

    text = _text_arg(name)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text) and text not in _M_KEYWORDS:
        return V.Text(text)
    return V.Text('#"' + text.replace('"', '""') + '"')


def _expression_evaluate(source: MValue, env: MValue) -> MValue:
    from .evaluator import Env, evaluate, root_env  # local import: the evaluator imports this module
    from .lexer import MSyntaxError
    from .parser import parse

    text = _text_arg(source)
    variables: dict = {}
    if not isinstance(env, V.Null):
        if not isinstance(env, V.Record):
            raise _unsupported("environment that is not a record")
        for name, item in env.fields:
            variables[name] = item
    try:
        node = parse(text)
    except MSyntaxError:
        raise _unsupported("expression that does not parse")
    return evaluate(node, Env(variables, root_env()))


def _character_from_number(value: MValue) -> MValue:
    if not isinstance(value, V.Number):
        raise _unsupported("Character.FromNumber of a value that is not a number")
    x = value.value
    if x != x or x != math.floor(x):
        raise _unsupported("Character.FromNumber of a value that is not whole")
    if x < 0 or x > 0x10FFFF:
        raise MError("Expression.Error", "We couldn't convert to Character.",
                     fmt="We couldn't convert to Character.")
    code = int(x)
    if code <= 0xFFFF:
        if 0xD800 <= code <= 0xDFFF:
            raise _unsupported("lone surrogate character")
        return V.Text(chr(code))
    rest = code - 0x10000
    # a character outside the BMP is two UTF-16 units; Power BI cannot print the pair (UNREPRESENTABLE)
    return V.Text(chr(0xD800 + (rest >> 10)) + chr(0xDC00 + (rest & 0x3FF)))


# ---- Binary ------------------------------------------------------------------

_BASE64, _HEX = 0, 1


def _encoding(value: MValue) -> int:
    """BinaryEncoding.Base64 (0, also null) or BinaryEncoding.Hex (1); any other number is an invalid encoding."""
    if isinstance(value, V.Null):
        return _BASE64
    if not isinstance(value, V.Number):
        raise V.convert_error(value, V.TypeValue("number"))
    if value.value in (0.0, 1.0):
        return int(value.value)
    raise V.generic_error("Invalid binary encoding.")


def _binary_of(value: MValue) -> V.Binary:
    if isinstance(value, V.Binary):
        if value.bad:
            raise _unsupported("binary that Power BI cannot serialize")
        return value
    raise V.convert_error(value, V.TypeValue("binary"))


_BASE64_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")


def _decode_text(source: str, encoding: int) -> V.Binary:
    """Base64 or hex text as bytes. Base64 ignores spaces, tabs and line breaks, needs a multiple of four
    characters with '=' only as the last one or two; hex needs an even number of hex digits."""
    import base64

    if encoding == _HEX:
        if len(source) % 2:
            raise MError("DataFormat.Error", "Hex string must contain an even number of characters.",
                         fmt="Hex string must contain an even number of characters.")
        if any(c not in "0123456789abcdefABCDEF" for c in source):
            raise MError("DataFormat.Error", "Invalid hex digit.", fmt="Invalid hex digit.")
        return V.Binary(bytes.fromhex(source))
    text = "".join(c for c in source if c not in " \t\r\n")
    body = text.rstrip("=")
    padding = len(text) - len(body)
    if len(text) % 4 and padding == 2 and len(text) % 4 == 1:
        return V.Binary(base64.b64decode(text[-4:]))
    if (any(c not in _BASE64_CHARS for c in body) or padding > 2 or len(text) % 4
            or (padding and not body)):
        raise V.generic_error("Invalid binary encoding.")
    return V.Binary(base64.b64decode(text) if text else b"")


def _binary_from_text(text: MValue, encoding: MValue) -> MValue:
    if isinstance(text, V.Null):
        _encoding(encoding)
        return V.Null()
    return _decode_text(_text_arg(text), _encoding(encoding))


def _binary_to_text(value: MValue, encoding: MValue) -> MValue:
    import base64

    data = _binary_of(value).value
    if _encoding(encoding) == _HEX:
        return V.Text(data.hex())
    return V.Text(base64.b64encode(data).decode("ascii"))


def _binary_to_list(value: MValue) -> MValue:
    return V.List(tuple(V.Number(float(b)) for b in _binary_of(value).value))


def _binary_from_list(value: MValue) -> MValue:
    from .stdlib import _binary as binary_from_list  # local import: the stdlib imports this module

    if not isinstance(value, V.List):
        raise V.convert_error(value, V.TypeValue("list"))
    built = binary_from_list(value)
    if built.bad:
        raise _unsupported("list of values that are not bytes")
    return built


def _binary_length(value: MValue) -> MValue:
    return V.Number(float(len(_binary_of(value).value)))


def _binary_range(value: MValue, offset: MValue, count: MValue) -> MValue:
    data = _binary_of(value).value
    start = _whole(offset, 0)
    if isinstance(count, V.Null):
        end = len(data)
    else:
        end = start + _whole(count, 0)
    if start > len(data) or end > len(data):
        raise _unsupported("binary range past the end")
    return V.Binary(data[start:end])


def _binary_split(value: MValue, page: MValue) -> MValue:
    data = _binary_of(value).value
    size = _whole(page, 1)
    return V.List(tuple(V.Binary(data[i:i + size]) for i in range(0, len(data), size)))


def _binary_from(value: MValue, encoding: MValue) -> MValue:
    """Binary.From: null and binary stay, text is decoded (base64 unless the encoding says hex), every other
    kind is the DataFormat error."""
    if isinstance(value, V.Null):
        _encoding(encoding)
        return value
    if isinstance(value, V.Binary):
        return value
    if isinstance(value, V.Text):
        return _decode_text(value.value, _encoding(encoding))
    raise MError("DataFormat.Error", "We couldn't convert to Binary.", fmt="We couldn't convert to Binary.")


def _binary_combine(binaries: MValue) -> MValue:
    out = b""
    for cell in _list_items(binaries):
        if not isinstance(cell, V.Binary) or cell.bad:
            raise _unsupported("Binary.Combine of a value that is not a binary")
        out += cell.value
    return V.Binary(out)


# ---- Json, Lines, Uri --------------------------------------------------------

_JSON_START = frozenset('[{"-0123456789tfn')


def _json_error(message: str) -> MError:
    return MError("DataFormat.Error", message, fmt=message)


_JSON_END = "We reached the end of the buffer."
_JSON_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class _JsonReader:
    """A JSON reader that accepts what Power BI accepts (a trailing comma, an unquoted object key, a number such
    as ``1.``) and gives its messages for the broken texts measured: the end of the text where a value is due, an
    unexpected first character, extra characters after the value, a bad array, a bad escape, a repeated key. A
    broken text that is not one of these is not measured."""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0

    def skip(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def document(self) -> MValue:
        value = self.value(top=True)
        self.skip()
        if self.pos < len(self.text):
            raise _json_error("We found extra characters at the end of the JSON input.")
        return value

    def value(self, top: bool = False) -> MValue:
        import re

        self.skip()
        c = self.peek()
        if not c:
            raise _json_error(_JSON_END)
        if c == "[":
            return self.array(top)
        if c == "{":
            return self.obj(top)
        if c == '"':
            return V.Text(self.string())
        if c == "-" or c.isdigit() and c.isascii():
            match = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]*)?([eE][+-]?[0-9]+)?").match(self.text, self.pos)
            if match is None:
                if c == "-":  # measured: a minus sign without digits runs into the end of the text
                    raise _json_error(_JSON_END)
                raise _unsupported("JSON number that is not measured")
            self.pos = match.end()
            if self.peek() in ("e", "E"):
                raise _unsupported("JSON exponent without digits")
            number = match.group(0)
            return V.Number(float(number[:-1] if number.endswith(".") else number))
        for word, result in (("true", V.Logical(True)), ("false", V.Logical(False)), ("null", V.Null())):
            if c == word[0]:
                if self.text.startswith(word, self.pos):
                    self.pos += len(word)
                    return result
                if word.startswith(self.text[self.pos:]):
                    raise _json_error(_JSON_END)
                raise _json_error("We found an invalid value in the JSON input. "
                                  "Only 'true', 'false', or 'null' are supported.")
        raise _json_error("We found an unexpected character in the JSON input.")

    def element(self) -> MValue:
        """A value inside an array or object. Where no value can start the container ends and the rest of the
        text is extra (measured), except for a closing bracket, which is an unexpected character."""
        self.skip()
        c = self.peek()
        if not c:
            raise _json_error(_JSON_END)
        if c in '[{"-tfn' or (c.isdigit() and c.isascii()):
            return self.value()
        if c in "}]":
            raise _json_error("We found an unexpected character in the JSON input.")
        if c == ":":
            raise _unsupported("JSON value position that holds a colon")
        raise _json_error("We found extra characters at the end of the JSON input.")

    def string(self) -> str:
        self.pos += 1
        out = []
        while True:
            c = self.peek()
            if not c:
                raise _json_error(_JSON_END)
            self.pos += 1
            if c == '"':
                return "".join(out)
            if c == "\\":
                e = self.peek()
                if not e:
                    raise _json_error(_JSON_END)
                self.pos += 1
                if e in _JSON_ESCAPES:
                    out.append(_JSON_ESCAPES[e])
                elif e == "u":
                    code = self.text[self.pos:self.pos + 4]
                    if len(code) < 4:
                        raise _json_error(_JSON_END)
                    if any(h not in "0123456789abcdefABCDEF" for h in code):
                        raise _unsupported("JSON \\u escape that is not measured")
                    self.pos += 4
                    unit = int(code, 16)
                    if 0xD800 <= unit < 0xE000:
                        raise _unsupported("JSON surrogate escape")
                    out.append(chr(unit))
                else:
                    raise _json_error("We found an invalid escape sequence in the JSON input.")
            elif c < " ":
                raise _unsupported("control character inside a JSON string")
            else:
                out.append(c)

    def array(self, top: bool) -> MValue:
        self.pos += 1
        items = []
        self.skip()
        if not self.peek():
            raise _json_error(_JSON_END)
        if self.peek() == "]":
            self.pos += 1
            return V.List(())
        while True:
            items.append(self.element())
            self.skip()
            c = self.peek()
            if c == ",":
                self.pos += 1
                self.skip()
                if self.peek() == "]":
                    self.pos += 1
                    return V.List(tuple(items))
                continue
            if c == "]":
                self.pos += 1
                return V.List(tuple(items))
            raise _json_error("We found an invalid array in the JSON input.")

    def key(self) -> str:
        import re

        c = self.peek()
        if c == '"':
            try:
                return self.string()
            except MError as error:
                if error.message == "We found an invalid escape sequence in the JSON input.":
                    raise _json_error("We found extra characters at the end of the JSON input.")
                raise
        match = re.compile(r"[A-Za-z0-9_$]+").match(self.text, self.pos)
        if match is None:
            raise _json_error("We found extra characters at the end of the JSON input.")
        self.pos = match.end()
        return match.group(0)

    def obj(self, top: bool) -> MValue:
        self.pos += 1
        fields: list = []
        self.skip()
        if not self.peek():
            raise _json_error(_JSON_END)
        if self.peek() == "}":
            self.pos += 1
            return V.Record(())
        while True:
            self.skip()
            name = self.key()
            self.skip()
            c = self.peek()
            if not c:
                raise _json_error(_JSON_END)
            if c != ":":
                raise _json_error("We found an invalid character between object key and value in the JSON input.")
            self.pos += 1
            value = self.element()
            if any(existing == name for existing, _ in fields):
                raise _json_error(f"Duplicate name '{name}'.")
            fields.append((name, value))
            self.skip()
            c = self.peek()
            if c == ",":
                self.pos += 1
                self.skip()
                if not self.peek():
                    raise _json_error(_JSON_END)
                if self.peek() == "}":
                    self.pos += 1
                    return V.Record(tuple(fields))
                continue
            if c == "}":
                self.pos += 1
                return V.Record(tuple(fields))
            raise _json_error("We found extra characters at the end of the JSON input.")


def _json_document(text: MValue, encoding: MValue) -> MValue:
    """Json.Document of text (or binary, read as UTF-8); null gives null."""
    if not isinstance(encoding, V.Null):
        raise _unsupported("Json.Document encoding argument")
    if isinstance(text, V.Null):
        return V.Null()
    if isinstance(text, V.Binary):
        try:
            source = _binary_of(text).value.decode("utf-8")
        except UnicodeDecodeError:
            raise _unsupported("binary that is not UTF-8")
        if source.startswith("\ufeff"):
            raise _unsupported("binary with a byte order mark")
    elif isinstance(text, V.Text):
        source = text.value
    else:
        raise V.generic_error("The parameter is expected to be of type Text.Type or Binary.Type.")
    return _JsonReader(source).document()


def _json_text(value: MValue) -> str:
    from .canonical import number_text_of

    if isinstance(value, V.Null):
        return "null"
    if isinstance(value, V.Logical):
        return "true" if value.value else "false"
    if isinstance(value, V.Number):
        if value.value != value.value or value.value in (math.inf, -math.inf):
            raise _unsupported("JSON number that is not finite")
        text = number_text_of(value)
        if "E" in text or "e" in text:
            raise _unsupported("JSON number in exponent form")
        return text
    if isinstance(value, V.Text):
        return '"' + _plain_ascii(value.value) + '"'
    if isinstance(value, V.Date):
        return '"' + value.value.isoformat() + '"'
    if isinstance(value, V.List):
        return "[" + ",".join(_json_text(V.force(item)) for item in value.items) + "]"
    if isinstance(value, V.Record):
        return "{" + ",".join('"' + _plain_ascii(name) + '":' + _json_text(V.force(item))
                              for name, item in value.fields) + "}"
    raise _unsupported("Json.FromValue of this kind")


def _plain_ascii(text: str) -> str:
    """Text that needs no JSON escaping (printable ASCII without quotes or backslashes)."""
    if any(not (" " <= ch <= "~") or ch in '"\\' for ch in text):
        raise _unsupported("text that needs JSON escaping")
    return text


def _json_from_value(value: MValue, encoding: MValue) -> MValue:
    if not isinstance(encoding, V.Null):
        raise _unsupported("Json.FromValue encoding argument")
    return V.Binary(_json_text(value).encode("utf-8"))


def _lines_from_text(text: MValue, quote: MValue, include_separators: MValue) -> MValue:
    """Lines.FromText: lines end at CR, LF or CRLF (nothing else); the last line break does not start a new
    line. With QuoteStyle.Csv a line break inside double quotes does not end the line (the quotes stay in the
    text). includeLineSeparators keeps each line's break at its end."""
    source = _text_arg(text)
    if isinstance(quote, V.Null):
        quoted = False
    elif isinstance(quote, V.Number) and quote.value in (0.0, 1.0):
        quoted = quote.value == 1.0
    else:
        raise V.generic_error("The specified QuoteStyle is invalid.")
    keep = _logical_arg(include_separators)
    lines, start, i, in_quote = [], 0, 0, False
    while i < len(source):
        ch = source[i]
        if ch == '"' and quoted:
            in_quote = not in_quote
        elif ch in "\r\n" and not in_quote:
            end = i + 2 if ch == "\r" and source[i + 1:i + 2] == "\n" else i + 1
            lines.append(source[start:end] if keep else source[start:i])
            start = i = end
            continue
        i += 1
    if start < len(source):
        lines.append(source[start:])
    return V.List(tuple(V.Text(line) for line in lines))


def _lines_to_text(lines: MValue, separator: MValue) -> MValue:
    """Lines.ToText: every line is followed by the separator (CRLF unless a text is given)."""
    if not isinstance(lines, V.List):
        raise V.convert_error(lines, V.TypeValue("list"))
    sep = "\r\n" if isinstance(separator, V.Null) else _text_arg(separator)
    return V.Text("".join(_text_arg(V.force(item)) + sep for item in lines.items))


_UNRESERVED = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"


def _escape_data_string(text: MValue) -> str:
    source = _text_arg(text)
    out = []
    for ch in source:
        if ch in _UNRESERVED:
            out.append(ch)
        else:
            try:
                data = ch.encode("utf-8")
            except UnicodeEncodeError:
                raise _unsupported("lone surrogate in a URI")
            out.extend("%%%02X" % byte for byte in data)
    return "".join(out)


def _uri_escape(text: MValue) -> MValue:
    return V.Text(_escape_data_string(text))


_URI_BASE = (r"(https?)://(?:([A-Za-z0-9._~%!$&'()*+,;=:-]*)@)?([A-Za-z0-9.-]+)(?::([0-9]+))?"
             r"(/[^?#]*)?(\?[^#]*)?(#.*)?")
_URI_ALLOWED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~!$&'()*+,;=:@/?%")
_DEFAULT_PORT = {"http": "80", "https": "443"}


_URI_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _escape_uri_part(text: str, fragment: bool = False) -> str:
    """The way .NET writes a Uri component: a space, '<', '>', '{', '}', '^', a backtick and every non-ASCII
    character are percent-escaped (UTF-8, upper-case hex; '#' too inside a fragment); %XX of an unreserved
    character is decoded and any other %XX stays as written; a '%' that starts no escape is escaped."""
    import re

    out = []
    index = 0
    while index < len(text):
        ch = text[index]
        if ch == "%":
            if re.fullmatch(r"%[0-9A-Fa-f]{2}", text[index:index + 3]):
                decoded = chr(int(text[index + 1:index + 3], 16))
                out.append(decoded if decoded in _URI_UNRESERVED else text[index:index + 3])
                index += 3
                continue
            out.append("%25")
        elif ch in _URI_ALLOWED and ch != "%":
            out.append(ch)
        elif ch in " <>{}^`" or ord(ch) > 127 or (fragment and ch == "#"):
            out.append("".join("%%%02X" % byte for byte in ch.encode("utf-8", "surrogatepass")))
        else:
            raise _unsupported("URI character that is not measured")
        index += 1
    return "".join(out)


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 section 5.2.4: '.' and '..' segments are resolved; '..' above the root is dropped."""
    output = []
    segments = path.split("/")
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == ".":
            if last:
                output.append("")
        elif segment == "..":
            if len(output) > 1:
                output.pop()
            if last:
                output.append("")
        else:
            output.append(segment)
    return "/".join(output)


def _uri_combine(base: MValue, relative: MValue) -> MValue:
    """Uri.Combine: RFC 3986 resolution of the relative URI against an http(s) base, written the way .NET writes
    a Uri (lower-case scheme and host, default port dropped, an empty path is '/', spaces and non-ASCII escaped).
    An absolute relative URI is the measured DataFormat error."""
    import re

    base_text = _text_arg(base)
    relative_text = _text_arg(relative).replace("\\", "/")
    if not base_text:
        raise MError("DataFormat.Error", "Invalid URI: The hostname could not be parsed.",
                     fmt="Invalid URI: The hostname could not be parsed.")
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", base_text):
        base_text = "http://" + base_text

    if base_text.lower().startswith("file:"):
        prefix = "file:///" if base_text.lower().startswith("file:///") else "file://"
        base_path = base_text[len(prefix):]
        if base_path.endswith("/"):
            merged = base_path + relative_text.lstrip("/")
        else:
            merged = base_path[:base_path.rfind("/") + 1] + relative_text.lstrip("/")
        return V.Text(prefix + _remove_dot_segments(merged))

    match = re.fullmatch(_URI_BASE, base_text, re.IGNORECASE)
    if match is None:
        raise _unsupported("base URI that is not measured")
    scheme, user, host, port, path, query, fragment = match.groups()
    scheme = scheme.lower()
    path = path or ""
    if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", relative_text):
        raise MError("DataFormat.Error", "A relative URI cannot be created because the 'uriString' parameter "
                     "represents an absolute URI.",
                     fmt="A relative URI cannot be created because the 'uriString' parameter represents an "
                         "absolute URI.")
    if "|" in relative_text:
        raise _unsupported("bar in a relative URI")
    ref_path, ref_query, ref_fragment = relative_text, None, None
    if "#" in ref_path:
        ref_path, _, ref_fragment = ref_path.partition("#")
    if "?" in ref_path:
        ref_path, _, ref_query = ref_path.partition("?")
    if relative_text.startswith("//"):
        authority = re.fullmatch(r"//([A-Za-z0-9.-]+)(?::([0-9]+))?(/.*)?", ref_path)
        if authority is None:
            raise _unsupported("network-path relative URI that is not measured")
        user, host, port, new_path = None, authority.group(1), authority.group(2), authority.group(3) or ""
        path, query = _remove_dot_segments(new_path) if new_path else "", None
        query = "?" + ref_query if ref_query is not None else None
    elif ref_path.startswith("/"):
        path = _remove_dot_segments(ref_path)
        query = "?" + ref_query if ref_query is not None else None
    elif ref_path:
        merged = (path[:path.rfind("/") + 1] + ref_path) if path else "/" + ref_path
        path = _remove_dot_segments(merged)
        query = "?" + ref_query if ref_query is not None else None
    else:  # no path: the base path stays; a query replaces the base query
        if ref_query is not None:
            query = "?" + ref_query
        elif ref_fragment is None:
            ref_fragment = fragment[1:] if fragment else None  # an empty relative URI keeps the whole base
    if query == "?":
        query = None
    if ref_fragment == "":
        ref_fragment = None
    if not path:
        path = "/"
    authority_text = (user + "@" if user else "") + host.lower() + (
        ":" + port if port and port != _DEFAULT_PORT[scheme] else "")
    result = scheme + "://" + authority_text + _escape_uri_part(path) + (_escape_uri_part(query) if query else "")
    if ref_fragment is not None:
        result += "#" + _escape_uri_part(ref_fragment, True)
    return V.Text(result)


def _uri_build_query(record: MValue) -> MValue:
    if not isinstance(record, V.Record):
        raise V.convert_error(record, V.TypeValue("record"))
    parts = []
    for name, item in record.fields:
        value = V.force(item)
        if not isinstance(value, V.Text):
            raise _unsupported("query value that is not text")
        parts.append(_escape_data_string(V.Text(name)) + "=" + _escape_data_string(value))
    return V.Text("&".join(parts))


_PARTS_PORT = {"http": 80, "https": 443, "ftp": 21}
_QUERY_ERROR = "We couldn't parse your query string because it was improperly formatted."


def _decode_query_text(text: str) -> str:
    """'+' is a space and %XX is a UTF-8 byte; a '%' that starts no escape stays."""
    import re

    out = bytearray()
    index = 0
    while index < len(text):
        ch = text[index]
        if ch == "%" and re.fullmatch(r"%[0-9A-Fa-f]{2}", text[index:index + 3]):
            out.append(int(text[index + 1:index + 3], 16))
            index += 3
            continue
        out.extend(" ".encode() if ch == "+" else ch.encode("utf-8", "surrogatepass"))
        index += 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        raise _unsupported("query text that is not UTF-8")


def _uri_parts(text: MValue) -> MValue:
    """Uri.Parts of an http, https or ftp URI: the parts as .NET writes them (lower-case scheme and host, the
    default port, an escaped and normalised path that is '/' at least); the query is a record of its decoded
    pairs, a repeated key joins its values with a comma, a pair without '=' is an error."""
    import re

    source = _text_arg(text)
    if not source:
        raise MError("DataFormat.Error", "Invalid URI: The hostname could not be parsed.",
                     fmt="Invalid URI: The hostname could not be parsed.")
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", source):
        source = "http://" + source

    if source.startswith("mailto:"):
        body = source[len("mailto:"):]
        user, _, host = body.partition("@")
        return V.Record((
            ("Scheme", V.Text("mailto")),
            ("Host", V.Text(host.lower())),
            ("Port", V.Number(25.0)),
            ("Path", V.Text("")),
            ("Query", V.Record(())),
            ("Fragment", V.Text("")),
            ("UserName", V.Text(user)),
            ("Password", V.Text("")),
        ))

    if source.lower().startswith("file:"):
        m = re.match(r"file:(?:/*)?([a-zA-Z]:.*)", source)
        if m:
            path = m.group(1).replace("\\", "/")
            return V.Record((
                ("Scheme", V.Text("file")),
                ("Host", V.Text("")),
                ("Port", V.Number(-1.0)),
                ("Path", V.Text(path)),
                ("Query", V.Record(())),
                ("Fragment", V.Text("")),
                ("UserName", V.Text("")),
                ("Password", V.Text("")),
            ))

    match = re.fullmatch(r"([A-Za-z][A-Za-z0-9+.-]*)://(?:([A-Za-z0-9._~!$&'()*+,;=-]*)(?::([A-Za-z0-9._~!$&'()*+,;=-]*))?@)?"
                         r"(\[[A-Fa-f0-9:]+\]|[A-Za-z0-9.-]+)(?::([0-9]*))?(/[^?#]*)?(?:\?([^#]*))?(?:#(.*))?", source)
    if match is None or match.group(1).lower() not in _PARTS_PORT:
        raise _unsupported("URI form that is not measured")
    scheme, user, password, host, port, path, query, fragment = match.groups()
    scheme = scheme.lower()
    if "%" in (user or "") + (password or ""):
        raise _unsupported("escaped user information")
    query_fields: list = []
    if query:
        for pair in query.split("&"):
            if "=" not in pair or not pair.partition("=")[0]:
                if "=" not in pair:
                    raise MError("DataFormat.Error", _QUERY_ERROR, fmt=_QUERY_ERROR)
                raise _unsupported("query pair with an empty key")
            key, _, value = pair.partition("=")
            key, value = _decode_query_text(key), _decode_query_text(value)
            for index, (name, old) in enumerate(query_fields):
                if name == key:
                    query_fields[index] = (name, old + "," + value)
                    break
            else:
                query_fields.append((key, value))
    return V.Record((
        ("Scheme", V.Text(scheme)),
        ("Host", V.Text(host.lower())),
        ("Port", V.Number(float(int(port)) if port else float(_PARTS_PORT[scheme]))),
        ("Path", V.Text(_escape_uri_part(_remove_dot_segments(path)) if path else "/")),
        ("Query", V.Record(tuple((k, V.Text(v)) for k, v in query_fields))),
        ("Fragment", V.Text(_escape_uri_part(fragment, True) if fragment else "")),
        ("UserName", V.Text(user or "")),
        ("Password", V.Text(password or "")),
    ))


# ---- Type constants and Type.Union helpers -----------------------------------

_NUMBER_TYPE_CONSTANTS = ("Number", "Int8", "Int16", "Int32", "Int64", "Byte", "Double", "Single", "Decimal",
                          "Currency", "Percentage")
_TYPE_CONSTANTS: dict = {f"{name}.Type": V.TypeValue("number", label=f"{name}.Type")
                      for name in _NUMBER_TYPE_CONSTANTS}
_TYPE_CONSTANTS.update({
    "Any.Type": V.TypeValue("any"),
    "Null.Type": V.TypeValue("null"),
    "Text.Type": V.TypeValue("text"),
    "Logical.Type": V.TypeValue("logical"),
    "Binary.Type": V.TypeValue("binary"),
    "Function.Type": V.TypeValue("function"),
    "Record.Type": V.TypeValue("record"),
    "List.Type": V.TypeValue("list"),
})


_MORE_GLOBALS: dict = {
    "Value.As": _native((("value", False), ("type", False)), _value_as),
    "Logical.From": _native((("value", False),), _logical_from),
    "Function.Invoke": _native((("function", False), ("args", False)), _function_invoke),
    "Expression.Constant": _native((("value", False),), _expression_constant),
    "Expression.Identifier": _native((("identifier", False),), _expression_identifier),
    "Expression.Evaluate": _native((("expression", False), ("environment", True)), _expression_evaluate),
    "Character.FromNumber": _native((("number", False),), _character_from_number),
    "Occurrence.Optional": V.Number(0.0),
    "Occurrence.Required": V.Number(1.0),
    "Occurrence.Repeating": V.Number(2.0),
    "BinaryEncoding.Base64": V.Number(0.0),
    "BinaryEncoding.Hex": V.Number(1.0),
    "Binary.FromText": _native((("text", False), ("encoding", True)), _binary_from_text),
    "Binary.ToText": _native((("binary", False), ("encoding", True)), _binary_to_text),
    "Binary.ToList": _native((("binary", False),), _binary_to_list),
    "Binary.FromList": _native((("list", False),), _binary_from_list),
    "Binary.Length": _native((("binary", False),), _binary_length),
    "Binary.Range": _native((("binary", False), ("offset", False), ("count", True)), _binary_range),
    "Binary.Split": _native((("binary", False), ("pageSize", False)), _binary_split),
    "Binary.From": _native((("value", False), ("encoding", True)), _binary_from),
    "Binary.Combine": _native((("binaries", False),), _binary_combine),
    "Json.Document": _native((("jsonText", False), ("encoding", True)), _json_document),
    "Json.FromValue": _native((("value", False), ("encoding", True)), _json_from_value),
    "Lines.FromText": _native((("text", False), ("quoteStyle", True), ("includeLineSeparators", True)),
                              _lines_from_text),
    "Lines.ToText": _native((("lines", False), ("lineSeparator", True)), _lines_to_text),
    "Uri.EscapeDataString": _native((("data", False),), _uri_escape),
    "Uri.Combine": _native((("baseUri", False), ("relativeUri", False)), _uri_combine),
    "Uri.BuildQueryString": _native((("query", False),), _uri_build_query),
    "Uri.Parts": _native((("url", False),), _uri_parts),
    "Type.AddTableKey": _native((("tableType", False), ("columns", False), ("isPrimary", False)), _add_table_key),
    "Type.ForFunction": _native((("signature", False), ("minCount", False)), _for_function),
    **_TYPE_CONSTANTS,
}
VALUE_GLOBALS.update(_MORE_GLOBALS)
