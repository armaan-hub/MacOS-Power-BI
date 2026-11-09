"""Power Query ``Text.*`` functions (Task 102, m-text-92) and the library values they take.

Power BI counts text in UTF-16 code units (``"𝔘nicode"`` has length 8). A text is therefore worked on as a
"unit string": a Python str with one character per UTF-16 code unit (a lone surrogate is allowed). Results go
back to ordinary text with ``_from_units``. A result that holds half of a surrogate pair is rejected by the
canonical serializer (UNREPRESENTABLE), which is what Power BI answers.

Every error message is copied from Power BI's answers (the spec, held-out and probe sets under docs/plans). What
Power BI does that this engine does not model (best-fit tables of single-byte code pages, other cultures, results
too large) raises ``_unpinned``: an explicit ERR naming the case, never a guessed value.
"""

from __future__ import annotations

import decimal
import re
import struct
import unicodedata
import uuid
from typing import Callable

from . import values as V
from .values import MError, MValue

SINGLE_CHARACTER = "The value isn't a single-character string."
ARGUMENT_OUT_OF_RANGE = "The '{}' argument is out of range."
INDEX_OUTSIDE = "The index is outside the bounds of the text value."
MAX_REPEAT_UNITS = 1 << 26

_FIRST, _LAST, _ALL = 0, 1, 2  # Occurrence.First / Last / All
_FROM_END = 1  # RelativePosition.FromEnd
_SPACE_CONTROLS = frozenset("\t\n\x0b\x0c\r\x85\xa0")


# ---- helpers -------------------------------------------------------------------

def _native(params: tuple, fn: Callable[..., MValue]) -> V.Function:
    specs = tuple(V.ParamSpec(name, None, optional) for name, optional in params)

    def invoke(bound: list) -> MValue:
        return fn(*[V.force(item) for item in bound])

    return V.Function(specs, invoke)


def _units(text: str) -> str:
    """The UTF-16 code units of a text, one character per unit."""
    data = text.encode("utf-16-le", "surrogatepass")
    return "".join(map(chr, struct.unpack("<%dH" % (len(data) // 2), data)))


def _from_units(units: str) -> str:
    """Back to ordinary text: valid pairs join into one character; lone surrogates stay (unrepresentable)."""
    return struct.pack("<%dH" % len(units), *map(ord, units)).decode("utf-16-le", "surrogatepass")


def _text(value: MValue) -> str:
    if isinstance(value, V.Text):
        return value.value
    raise V.convert_error(value, V.TypeValue("text"))


def _int(value: MValue) -> int:
    return V.to_int32(value)


def _unpinned(what: str) -> MError:
    """Not a Power BI answer we have measured: an explicit ERR, never a guessed value."""
    return V.generic_error(f"The {what} is not supported by this engine yet.")


def _range_error(name: str) -> MError:
    return V.generic_error(ARGUMENT_OUT_OF_RANGE.format(name))


def _single(value: MValue) -> str:
    """A one-character text (one UTF-16 unit) as a unit string."""
    units = _units(_text(value))
    if len(units) != 1:
        raise V.generic_error(SINGLE_CHARACTER)
    return units


def _is_space(ch: str) -> bool:
    """.NET Char.IsWhiteSpace: the controls above plus the Zs, Zl and Zp categories."""
    return ch in _SPACE_CONTROLS or unicodedata.category(ch) in ("Zs", "Zl", "Zp")


ARGUMENT_INVALID = "The argument value isn't valid."
CULTURE_COMPARER = "The specified comparer does not support culture sensitive comparisons."


def _char_set(value: MValue) -> Callable[[str], bool]:
    """Text.Trim/Remove/Select characters: one single-character text or a list of them (measured: a longer
    text is an error, and so is any other value)."""
    if isinstance(value, V.Text):
        return frozenset((_single(value),)).__contains__
    if isinstance(value, V.List):
        return _char_list(value)
    raise V.generic_error(ARGUMENT_INVALID)


def _char_list(value: MValue) -> Callable[[str], bool]:
    """Text.PositionOfAny characters: a list of single-character texts only."""
    if not isinstance(value, V.List):
        raise V.convert_error(value, V.TypeValue("list"))
    found = set()
    for item in value.items:
        found.add(_single(V.force(item)))
    return frozenset(found).__contains__


def _case_turkic(culture: MValue) -> bool:
    """Culture check for the case functions (en-US and friends, tr and az); anything else is an ERR."""
    from .stdlib import _EN_US, _culture_name, _unsupported_culture  # local: stdlib imports this module

    name = _culture_name(culture)
    if name not in _EN_US and not name.startswith(("tr", "az")):
        raise _unsupported_culture(name)
    return name.startswith(("tr", "az"))


def _lower_unit(ch: str, turkic: bool) -> str:
    """Simple lower-casing of one unit (.NET invariant): İ gives i, the Turkish I gives dotless ı."""
    if turkic and ch == "I":
        return "ı"
    if ch == "İ":
        return "i"
    low = ch.lower()
    return low if len(low) == 1 else ch


def _upper_unit(ch: str, turkic: bool) -> str:
    from .stdlib import _upper_unit as upper  # local: stdlib imports this module

    return upper(ch, turkic)


def _fold(units: str) -> str:
    """OrdinalIgnoreCase: each unit upper-cased the same way as Text.Upper."""
    return "".join(_upper_unit(ch, False) for ch in units)


def _check_comparer(comparer: MValue) -> None:
    """A comparer argument has to be a function (or null); the conversion error comes before anything else."""
    if not isinstance(comparer, (V.Null, V.Function)):
        raise V.convert_error(comparer, V.TypeValue("function"))


def _comparer_folds(comparer: MValue) -> bool:
    _check_comparer(comparer)
    if isinstance(comparer, V.Null) or comparer is COMPARER_ORDINAL:
        return False
    if comparer is COMPARER_ORDINAL_IGNORE_CASE:
        return True
    raise V.generic_error(CULTURE_COMPARER)  # measured for every other function


def _occurrence(value: MValue) -> int:
    if isinstance(value, V.Null):
        return _FIRST
    if not isinstance(value, V.Number):
        raise V.convert_error(value, V.TypeValue("number"))
    if value.value == 0.0:
        return _FIRST
    return _LAST if value.value == 1.0 else _ALL  # measured: any other number (3, -1, 1.5) means Occurrence.All


def _all_starts(haystack: str, needle: str) -> list:
    """Every start of ``needle`` in ``haystack``, overlapping ones included."""
    starts = []
    index = haystack.find(needle)
    while index != -1:
        starts.append(index)
        index = haystack.find(needle, index + 1)
    return starts


def _delimiter_starts(haystack: str, delimiter: str) -> list:
    """Starts of a delimiter read left to right without overlap (measured: ``aaa`` holds one ``aa``)."""
    starts, index = [], haystack.find(delimiter)
    while index != -1:
        starts.append(index)
        index = haystack.find(delimiter, index + len(delimiter))
    return starts


def _position_result(starts: list, occurrence: int) -> MValue:
    """``starts`` are the overlapping starts. First and Last read them as they are (Last of ``aa`` in ``aaa`` is 1);
    All keeps only the left-to-right non-overlapping ones (measured: [0])."""
    if occurrence == _ALL:
        return V.List(tuple(V.Number(float(start)) for start in starts))
    if not starts:
        return V.Number(-1.0)
    return V.Number(float(starts[0] if occurrence == _FIRST else starts[-1]))


def _non_overlapping(starts: list, width: int) -> list:
    kept = []
    for start in starts:
        if not kept or start >= kept[-1] + width:
            kept.append(start)
    return kept


INVALID_INDEX = "The specified index parameter is invalid."
NOT_ENOUGH_ELEMENTS = ("There weren't enough elements in the enumeration to complete the operation.")
EMPTY_DELIMITER = "A delimiter must be text at least 1 character in length."


def _delimiter_index(value: MValue) -> tuple:
    """An occurrence index: a number counts from the start; {n, RelativePosition.FromEnd} counts from the end."""
    if isinstance(value, V.Null):
        return 0, False
    if isinstance(value, V.Number):
        number = _int(value)
        if number == -2147483648:  # measured
            raise _range_error("count")
        return number, False
    if isinstance(value, V.List):
        items = [V.force(item) for item in value.items]
        if len(items) < 2:
            raise V.generic_error(NOT_ENOUGH_ELEMENTS)
        if len(items) > 2 or not isinstance(items[0], V.Number) or not isinstance(items[1], V.Number) \
                or items[1].value not in (0.0, 1.0):
            raise V.generic_error(INVALID_INDEX)
        return _int(items[0]), items[1].value == 1.0
    raise V.convert_error(value, V.TypeValue("list"))


def _delimiter_text(value: MValue) -> str:
    units = _units(_text(value))
    if not units:
        raise V.generic_error(EMPTY_DELIMITER)
    return units


def _locate(hay: str, delim: str, index: int, from_end: bool) -> tuple:
    """(start, end) of the chosen delimiter. An index before the first occurrence gives (0, 0) and one past the
    last gives (len, len): the text is clamped, never an error (measured)."""
    starts = _delimiter_starts(hay, delim)
    k = len(starts) - 1 - index if from_end else index
    if k < 0:
        return 0, 0
    if k >= len(starts):
        return len(hay), len(hay)
    return starts[k], starts[k] + len(delim)


# ---- Comparer, Occurrence, RelativePosition, TextEncoding ------------------------

def _compare(a: MValue, b: MValue, fold: bool) -> MValue:
    x, y = _units(_text(a)), _units(_text(b))
    if fold:
        x, y = _fold(x), _fold(y)
    return V.Number(float((x > y) - (x < y)))


COMPARER_ORDINAL = _native((("x", False), ("y", False)), lambda a, b: _compare(a, b, False))
COMPARER_ORDINAL_IGNORE_CASE = _native((("x", False), ("y", False)), lambda a, b: _compare(a, b, True))


# ---- functions -----------------------------------------------------------------

def _trim(value: MValue, chars: MValue, left: bool, right: bool) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    predicate = _is_space if isinstance(chars, V.Null) else _char_set(chars)
    units = _units(_text(value))
    start, end = 0, len(units)
    if left:
        while start < end and predicate(units[start]):
            start += 1
    if right:
        while end > start and predicate(units[end - 1]):
            end -= 1
    return V.Text(_from_units(units[start:end]))


def _text_trim(value: MValue, chars: MValue = V.Null()) -> MValue:
    return _trim(value, chars, True, True)


def _text_trim_start(value: MValue, chars: MValue = V.Null()) -> MValue:
    return _trim(value, chars, True, False)


def _text_trim_end(value: MValue, chars: MValue = V.Null()) -> MValue:
    return _trim(value, chars, False, True)


def _text_clean(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    kept = [ch for ch in _units(_text(value)) if unicodedata.category(ch) != "Cc"]  # NBSP is kept (measured)
    return V.Text(_from_units("".join(kept)))


def _text_reverse(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    return V.Text(_from_units(_units(_text(value))[::-1]))


def _text_to_list(value: MValue) -> MValue:
    return V.List(tuple(V.Text(_from_units(ch)) for ch in _units(_text(value))))


def _text_lower(value: MValue, culture: MValue = V.Null()) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()  # measured: a null text wins over an unsupported culture
    turkic = _case_turkic(culture)
    return V.Text(_from_units("".join(_lower_unit(ch, turkic) for ch in _units(_text(value)))))


def _text_proper(value: MValue, culture: MValue = V.Null()) -> MValue:
    """Each word's first letter upper-cased, the rest lower-cased; a word starts after any non-letter."""
    if isinstance(value, V.Null):
        return V.Null()
    turkic = _case_turkic(culture)
    out = []
    after_letter = False
    for ch in _units(_text(value)):
        if ch.isalpha():
            out.append(_lower_unit(ch, turkic) if after_letter else _upper_unit(ch, turkic))
            after_letter = True
        else:
            out.append(ch)
            after_letter = False
    return V.Text(_from_units("".join(out)))


def _text_start(value: MValue, count: MValue) -> MValue:
    n = _int(count)
    if isinstance(value, V.Null):
        return V.Null()
    if n < 0:
        raise _range_error("count")
    return V.Text(_from_units(_units(_text(value))[:n]))


def _text_end(value: MValue, count: MValue) -> MValue:
    n = _int(count)
    if isinstance(value, V.Null):
        return V.Null()
    if n < 0:
        raise _range_error("count")
    units = _units(_text(value))
    return V.Text(_from_units(units[max(0, len(units) - n):]))


def _text_middle(value: MValue, start: MValue, count: MValue = V.Null()) -> MValue:
    begin = _int(start)
    length = None if isinstance(count, V.Null) else _int(count)
    if isinstance(value, V.Null):
        return V.Null()
    if begin < 0:
        raise _range_error("start")
    if length is not None and length < 0:
        raise _range_error("count")
    units = _units(_text(value))
    if begin > len(units):
        return V.Text("")
    end = len(units) if length is None else min(len(units), begin + length)
    return V.Text(_from_units(units[begin:end]))


def _text_range(value: MValue, offset: MValue, count: MValue = V.Null()) -> MValue:
    begin = _int(offset)
    length = None if isinstance(count, V.Null) else _int(count)
    if isinstance(value, V.Null):
        return V.Null()
    units = _units(_text(value))
    if begin < 0 or begin > len(units):
        raise _range_error("offset")
    if length is None:
        length = len(units) - begin
    if length < 0:
        raise _range_error("count")
    if begin + length > len(units):
        raise _range_error("count")
    return V.Text(_from_units(units[begin:begin + length]))


def _text_at(value: MValue, index: MValue) -> MValue:
    position = _int(index)
    if isinstance(value, V.Null):
        return V.Null()
    units = _units(_text(value))
    if not 0 <= position < len(units):
        raise V.generic_error(INDEX_OUTSIDE)
    return V.Text(_from_units(units[position]))


def _text_insert(value: MValue, offset: MValue, new: MValue) -> MValue:
    position = _int(offset)
    addition = _units(_text(new))
    if isinstance(value, V.Null):
        return V.Null()
    units = _units(_text(value))
    if not 0 <= position <= len(units):
        raise _range_error("offset")
    return V.Text(_from_units(units[:position] + addition + units[position:]))


def _text_replace_range(value: MValue, offset: MValue, count: MValue, new: MValue) -> MValue:
    position, length = _int(offset), _int(count)
    addition = _units(_text(new))
    if isinstance(value, V.Null):
        return V.Null()
    units = _units(_text(value))
    if position < 0:
        raise _range_error("offset")
    if length < 0:
        raise _range_error("count")
    return V.Text(_from_units(units[:position] + addition + units[position + length:]))


def _text_remove_range(value: MValue, offset: MValue, count: MValue = V.Null()) -> MValue:
    position = _int(offset)
    length = 1 if isinstance(count, V.Null) else _int(count)
    if isinstance(value, V.Null):
        return V.Null()
    units = _units(_text(value))
    if not 0 <= position <= len(units):
        raise _range_error("offset")
    if length < 0 or position + length > len(units):
        raise _range_error("count")
    return V.Text(_from_units(units[:position] + units[position + length:]))


def _text_repeat(value: MValue, count: MValue) -> MValue:
    n = _int(count)
    if isinstance(value, V.Null):
        return V.Null()
    if n < 0:
        raise _range_error("count")
    units = _units(_text(value))
    if len(units) * n > MAX_REPEAT_UNITS:
        raise _unpinned("Text.Repeat result this large")
    return V.Text(_from_units(units * n))


def _pad(value: MValue, width: MValue, pad: MValue, left: bool) -> MValue:
    target = _int(width)
    if not isinstance(pad, V.Null):
        _text(pad)
    if isinstance(value, V.Null):
        return V.Null()
    if target < 0:
        raise _range_error("count")
    fill = " " if isinstance(pad, V.Null) else _single(pad)
    units = _units(_text(value))
    missing = max(0, target - len(units))
    padding = fill * missing
    return V.Text(_from_units(padding + units if left else units + padding))


def _text_pad_start(value: MValue, width: MValue, pad: MValue = V.Null()) -> MValue:
    return _pad(value, width, pad, True)


def _text_pad_end(value: MValue, width: MValue, pad: MValue = V.Null()) -> MValue:
    return _pad(value, width, pad, False)


def _substring_test(value: MValue, sub: MValue, comparer: MValue, how: str) -> MValue:
    if how == "contains" and isinstance(value, V.Null):
        return V.Null()  # measured: Contains answers null before looking at its other arguments
    needle = _units(_text(sub))
    _check_comparer(comparer)
    if isinstance(value, V.Null):
        return V.Null()
    fold = _comparer_folds(comparer)
    hay = _units(_text(value))
    if fold:
        hay, needle = _fold(hay), _fold(needle)
    if how == "contains":
        return V.Logical(needle in hay)
    if how == "starts":
        return V.Logical(hay.startswith(needle))
    return V.Logical(hay.endswith(needle))


def _text_contains(value: MValue, sub: MValue, comparer: MValue = V.Null()) -> MValue:
    return _substring_test(value, sub, comparer, "contains")


def _text_starts_with(value: MValue, sub: MValue, comparer: MValue = V.Null()) -> MValue:
    return _substring_test(value, sub, comparer, "starts")


def _text_ends_with(value: MValue, sub: MValue, comparer: MValue = V.Null()) -> MValue:
    return _substring_test(value, sub, comparer, "ends")


def _text_position_of(value: MValue, sub: MValue, occurrence: MValue = V.Null(),
                      comparer: MValue = V.Null()) -> MValue:
    hay = _units(_text(value))  # measured: a null text is an error here, unlike the other Text functions
    needle = _units(_text(sub))
    which = _occurrence(occurrence)
    fold = _comparer_folds(comparer)
    if fold:
        hay, needle = _fold(hay), _fold(needle)
    if not needle:
        # measured: an empty search text matches at every position, but the last one of an empty text is 0
        starts = list(range(len(hay))) or ([0] if which != _ALL else [])
        return _position_result(starts if which != _FIRST else [0], which)
    starts = _all_starts(hay, needle)
    if which == _ALL:
        starts = _non_overlapping(starts, len(needle))
    return _position_result(starts, which)


def _text_position_of_any(value: MValue, chars: MValue, occurrence: MValue = V.Null()) -> MValue:
    hay = _units(_text(value))
    predicate = _char_list(chars)
    which = _occurrence(occurrence)
    return _position_result([i for i, ch in enumerate(hay) if predicate(ch)], which)


def _text_split(value: MValue, delimiter: MValue) -> MValue:
    hay = _text(value)
    delim = _units(_text(delimiter))
    if not delim:
        return V.List((V.Text(hay),))
    return V.List(tuple(V.Text(_from_units(part)) for part in _units(hay).split(delim)))


def _text_split_any(value: MValue, separators: MValue) -> MValue:
    units = _units(_text(value))
    chars = frozenset(_units(_text(separators)))  # measured: the separators are one text, not a list
    pieces, current = [], []
    for ch in units:
        if ch in chars:
            pieces.append(current)
            current = []
        else:
            current.append(ch)
    pieces.append(current)
    return V.List(tuple(V.Text(_from_units("".join(part))) for part in pieces))


def _text_combine(values: MValue, separator: MValue = V.Null()) -> MValue:
    if not isinstance(values, V.List):
        raise V.convert_error(values, V.TypeValue("list"))
    glue = "" if isinstance(separator, V.Null) else _units(_text(separator))
    items = [V.force(item) for item in values.items]
    parts = [_units(_text(item)) for item in items if not isinstance(item, V.Null)]  # measured: nulls are skipped
    return V.Text(_from_units(glue.join(parts)))


def _text_replace(value: MValue, old: MValue, new: MValue) -> MValue:
    needle = _units(_text(old))
    replacement = _units(_text(new))
    if isinstance(value, V.Null):
        return V.Null()
    if not needle:
        return V.Text(_from_units(_units(_text(value))))  # measured: an empty search text changes nothing
    return V.Text(_from_units(_units(_text(value)).replace(needle, replacement)))


def _text_remove(value: MValue, chars: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    predicate = _char_set(chars)
    return V.Text(_from_units("".join(ch for ch in _units(_text(value)) if not predicate(ch))))


def _text_select(value: MValue, chars: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    predicate = _char_set(chars)
    return V.Text(_from_units("".join(ch for ch in _units(_text(value)) if predicate(ch))))


def _before(hay: str, delim: str, index: tuple) -> str:
    return hay[:_locate(hay, delim, *index)[0]]


def _after(hay: str, delim: str, index: tuple) -> str:
    return hay[_locate(hay, delim, *index)[1]:]


def _text_before_delimiter(value: MValue, delimiter: MValue, index: MValue = V.Null()) -> MValue:
    text_value = value if isinstance(value, V.Null) else V.Text(_text(value))
    delim = _delimiter_text(delimiter)
    where = _delimiter_index(index)
    if isinstance(text_value, V.Null):
        return V.Text("")  # measured: a null text gives an empty text here
    return V.Text(_from_units(_before(_units(text_value.value), delim, where)))


def _text_after_delimiter(value: MValue, delimiter: MValue, index: MValue = V.Null()) -> MValue:
    text_value = value if isinstance(value, V.Null) else V.Text(_text(value))
    delim = _delimiter_text(delimiter)
    where = _delimiter_index(index)
    if isinstance(text_value, V.Null):
        return V.Text("")
    return V.Text(_from_units(_after(_units(text_value.value), delim, where)))


def _text_between_delimiters(value: MValue, opening: MValue, closing: MValue, index: MValue = V.Null(),
                             end_index: MValue = V.Null()) -> MValue:
    """Measured: the end delimiter is looked for after the start delimiter (counting forward) or, with
    RelativePosition.FromEnd, before it (counting back from it)."""
    text_value = value if isinstance(value, V.Null) else V.Text(_text(value))
    start_delim = _delimiter_text(opening)
    end_delim = _delimiter_text(closing)
    first = _delimiter_index(index)
    last = _delimiter_index(end_index)
    if isinstance(text_value, V.Null):
        return V.Text("")
    hay = _units(text_value.value)
    if last[1]:
        return V.Text(_from_units(_after(_before(hay, start_delim, first), end_delim, last)))
    return V.Text(_from_units(_before(_after(hay, start_delim, first), end_delim, last)))


FORMAT_ARGUMENTS = "We expect Text.Format arguments to be of type Record or type List."
FORMAT_CLOSED = "Text format placeholders must be closed."
_INTEGER = re.compile(r"[+-]?[0-9]+")


def _placeholder_error(message: str) -> MError:
    return MError("Expression.Error", "Invalid placeholder or value in format string. Underlying error "
                  "message: " + message)


def _format_index(key: str) -> int:
    text = key.strip()
    if not _INTEGER.fullmatch(text):
        raise _placeholder_error("We expected an integer value.")
    number = int(text)
    if number < 0 and number != 0:
        raise _placeholder_error("The index cannot be negative.")
    if number > 2147483647:
        raise _placeholder_error("We expected an integer value.")
    return number


def _format_fetch(arguments: MValue, key: str, is_index: bool) -> MValue:
    """The value a placeholder names. An error inside the value or the lookup is wrapped like Power BI does."""
    try:
        if isinstance(arguments, V.List):
            if not is_index:
                raise _placeholder_error("We cannot apply field access to the type List.")
            position = _format_index(key)
            if position >= len(arguments.items):
                raise _placeholder_error(NOT_ENOUGH_ELEMENTS)
            return V.force(arguments.items[position])
        if is_index:
            position = _format_index(key)
            if position >= len(arguments.fields):
                raise _placeholder_error("The index is outside the bounds of the record.")
            return V.force(arguments.fields[position][1])
        if not arguments.has(key):
            raise _placeholder_error(f"The field '{key}' of the record wasn't found.")
        return arguments.get(key)
    except MError as error:
        if error.message.startswith("Invalid placeholder or value in format string."):
            raise
        raise _placeholder_error(error.message) from None


_KIND_WORDS = ((V.List, "list"), (V.Record, "record"), (V.Function, "function"), (V.Table, "table"),
               (V.TypeValue, "type"))


def _text_format(format_string: MValue, arguments: MValue, culture: MValue = V.Null()) -> MValue:
    from .stdlib import _text_from  # local: stdlib imports this module

    template = _text(format_string)
    if not isinstance(arguments, (V.List, V.Record)):
        raise V.generic_error(FORMAT_ARGUMENTS)
    pieces, last, at = [], 0, 0
    while True:
        at = template.find("#", at)
        if at == -1 or at + 1 >= len(template):
            break
        opener = template[at + 1]
        if opener not in "{[":
            at += 1
            continue
        end = template.find("}" if opener == "{" else "]", at + 2)
        if end == -1:
            raise MError("DataFormat.Error", FORMAT_CLOSED)
        fetched = _format_fetch(arguments, template[at + 2:end], opener == "{")
        word = next((name for kind, name in _KIND_WORDS if isinstance(fetched, kind)), None)
        if word is not None:
            converted = V.Text(word)
        elif isinstance(fetched, V.Null):
            converted = V.Text("null")
        else:
            converted = _text_from(fetched, culture)
        pieces.append(template[last:at])
        pieces.append(converted.value)
        last = at = end + 1
    pieces.append(template[last:])
    return V.Text("".join(pieces))


INVALID_ENCODING = "The text encoding is invalid."
BOM_MISMATCH = "The unicode byte order marks didn't match the specified encoding."
_SINGLE_BYTE = {0: "cp1252", 1252: "cp1252", 28591: "latin-1", 437: "cp437"}  # 0 is this machine's ANSI page
_UNICODE_PAGES = (65001, 1200, 1201, 12000, 12001)
_ASCII_PAGE = 20127
_CP1252_PASS_THROUGH = (0x81, 0x8D, 0x8F, 0x90, 0x9D)  # .NET maps these bytes to the same code point
_BOMS = ((b"\xef\xbb\xbf", 65001), (b"\xff\xfe", 1200), (b"\xfe\xff", 1201))


def _encoding_page(encoding: MValue):
    """The code page number (None for no encoding); a page that is not modelled is an explicit ERR."""
    if isinstance(encoding, V.Null):
        return None
    if not isinstance(encoding, V.Number):
        raise V.convert_error(encoding, V.TypeValue("number"))
    return _int(encoding)


def _check_page(page) -> None:
    if page is None or page in _SINGLE_BYTE or page in _UNICODE_PAGES or page == _ASCII_PAGE:
        return
    if page < 0 or page > 65535 or page in (1, 5, 65002):
        raise V.generic_error(INVALID_ENCODING)  # measured
    raise _unpinned("text encoding")


def _text_from_binary(value: MValue, encoding: MValue = V.Null()) -> MValue:
    page = _encoding_page(encoding)
    if isinstance(value, V.Null):
        return V.Null()
    if not isinstance(value, V.Binary):
        raise V.convert_error(value, V.TypeValue("binary"))
    _check_page(page)
    return V.Text(_decode(value.value, page))


def _decode(data: bytes, page) -> str:
    if page is None:  # measured: a byte order mark chooses the encoding, otherwise UTF-8
        if data[:4] == b"\xff\xfe\x00\x00":
            return data[4:].decode("utf-32-le", "replace")
        if data[:4] == b"\x00\x00\xfe\xff":
            return data[4:].decode("utf-32-be", "replace")
        for mark, code in _BOMS:
            if data.startswith(mark):
                body = data[len(mark):]
                if code == 65001:
                    return _decode_utf8(body)
                return body.decode("utf-16-le" if code == 1200 else "utf-16-be", "replace")
        return _decode_utf8(data)
    if page in (65001, 1200, 1201):
        for mark, code in _BOMS:
            if data.startswith(mark):
                if code != page:
                    raise MError("DataFormat.Error", BOM_MISMATCH)
                data = data[len(mark):]
                break
        if page == 65001:
            return _decode_utf8(data)
        return data.decode("utf-16-le" if page == 1200 else "utf-16-be", "replace")
    if page == 12000:
        return data.decode("utf-32-le", "replace")
    if page == 12001:
        return data.decode("utf-32-be", "replace")
    if page == _ASCII_PAGE:
        return "".join(chr(b) if b < 128 else "?" for b in data)
    codec = _SINGLE_BYTE[page]
    out = []
    for byte in data:
        try:
            out.append(bytes((byte,)).decode(codec))
        except UnicodeDecodeError:
            out.append(chr(byte))  # cp1252's undefined bytes keep their own code point (measured)
    return "".join(out)


def _decode_utf8(data: bytes) -> str:
    """UTF-8 as .NET Framework reads it: a bad lead byte is one U+FFFD; a good lead byte plus the continuation
    byte after it are one U+FFFD when that pair cannot start a valid sequence or the sequence is cut short."""
    out, i, n = [], 0, len(data)
    while i < n:
        lead = data[i]
        if lead < 0x80:
            out.append(chr(lead))
            i += 1
            continue
        if 0xC2 <= lead <= 0xDF:
            need = 1
        elif 0xE0 <= lead <= 0xEF:
            need = 2
        elif 0xF0 <= lead <= 0xF4:
            need = 3
        else:
            out.append("\ufffd")
            i += 1
            continue
        j = i + 1
        if j >= n or not 0x80 <= data[j] <= 0xBF:
            out.append("\ufffd")
            i = j
            continue
        low, high = {0xE0: (0xA0, 0xBF), 0xED: (0x80, 0x9F), 0xF0: (0x90, 0xBF), 0xF4: (0x80, 0x8F)}.get(
            lead, (0x80, 0xBF))
        if not low <= data[j] <= high:
            out.append("\ufffd")
            i = j + 1
            continue
        j += 1
        while j < i + 1 + need and j < n and 0x80 <= data[j] <= 0xBF:
            j += 1
        if j == i + 1 + need:
            out.append(data[i:j].decode("utf-8"))
        else:
            out.append("\ufffd")
        i = j
    return "".join(out)


def _text_to_binary(value: MValue, encoding: MValue = V.Null()) -> MValue:
    page = _encoding_page(encoding)
    if isinstance(value, V.Null):
        return V.Null()
    text = _text(value)
    _check_page(page)
    return V.Binary(_encode(text, page))


def _encode(text: str, page) -> bytes:
    whole = re.sub("[\ud800-\udfff]", "\ufffd", text)  # a lone surrogate becomes U+FFFD in the Unicode pages
    if page is None or page == 65001:
        return whole.encode("utf-8")
    if page == 1200:
        return whole.encode("utf-16-le")
    if page == 1201:
        return whole.encode("utf-16-be")
    if page == 12000:
        return b"\xff\xfe\x00\x00" + whole.encode("utf-32-le")  # measured: this page writes its mark
    if page == 12001:
        return b"\x00\x00\xfe\xff" + whole.encode("utf-32-be")
    codec = _SINGLE_BYTE.get(page)
    out = bytearray()
    for unit in _units(text):
        code = ord(unit)
        if code < 128:
            out.append(code)
        elif 0xD800 <= code <= 0xDFFF:
            out.append(0x3F)  # each half of a pair, and a lone surrogate, is one question mark (measured)
        elif page == _ASCII_PAGE:
            out.append(0x3F)
        else:
            try:
                out += unit.encode(codec)
            except UnicodeEncodeError:
                if codec == "cp1252" and code in _CP1252_PASS_THROUGH:
                    out.append(code)
                else:
                    raise _unpinned("character that has no exact match in this code page")
    return bytes(out)


DECIMAL_RANGE = "The number is out of range of a decimal value."
_DECIMAL_MAX = decimal.Decimal("79228162514264337593543950335")
_NUMBER_CORE = re.compile(r"(?:[0-9]+(?:,+[0-9]+)*,*(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def _scan_number(text: str):
    """(has a percent sign, digits without commas) when Power BI reads ``text`` as a number (en-US), else None.
    A .NET-style scan: spaces, one sign, one dollar
    sign, one percent sign and one pair of parentheses around the digits, in the orders measured (a percent
    sign between the dollar sign and the digits is refused)."""
    sign = paren = closed = currency = percent = percent_after = False
    n, i = len(text), 0
    while i < n:  # before the digits
        ch = text[i]
        if ch.isspace() and (not sign or currency):
            pass
        elif ch in "+-" and not sign:
            sign = True
        elif ch == "(" and not sign:
            sign = paren = True
        elif ch == "$" and not currency:
            currency = True
        elif ch == "%" and not percent:
            if currency:
                return None
            percent = True
        else:
            break
        i += 1
    core = _NUMBER_CORE.match(text, i)
    if core is None:
        return None
    i = core.end()
    while i < n:  # after the digits
        ch = text[i]
        if ch.isspace():
            pass
        elif ch in "+-" and not sign:
            sign = True
        elif ch == "$" and not currency:
            if percent_after:
                return None
            currency = True
        elif ch == "%" and not percent:
            percent = percent_after = True
        elif ch == ")" and paren and not closed:
            closed = True
        else:
            return None
        i += 1
    if paren and not closed:
        return None
    return percent, core.group().replace(",", "")


def _infer_number_type(value: MValue, culture: MValue = V.Null()) -> MValue:
    from .stdlib import _EN_US, _culture_name, _unsupported_culture  # local: stdlib imports this module

    text = _text(value)
    name = _culture_name(culture)
    if name not in _EN_US:
        raise _unsupported_culture(name)
    trimmed = text.strip()
    special = trimmed.removeprefix("%") if trimmed.startswith("%") else trimmed.removesuffix("%")
    if special in ("NaN", "\u221e", "-\u221e"):
        if special != trimmed:
            raise MError("Expression.Error", DECIMAL_RANGE)  # measured: a percent sign makes it a decimal
        return V.TypeValue("number")
    scanned = _scan_number(text)
    if scanned is None:
        raise MError("DataFormat.Error", f"We couldn't match '{text}' with any known number pattern.")
    percent, digits = scanned
    if percent:  # measured: a percent value is read as a decimal, which stops at 79228162514264337593543950335
        try:
            too_big = decimal.Decimal(digits).copy_abs() > _DECIMAL_MAX  # exact, no context rounding
        except decimal.InvalidOperation:
            too_big = True
        if too_big:
            raise MError("Expression.Error", DECIMAL_RANGE)
    return V.TypeValue("number")


def _new_guid() -> MValue:
    return V.Text(str(uuid.uuid4()))


# ---- the table added to the stdlib ----------------------------------------------

TEXT_GLOBALS: dict = {
    "Comparer.Ordinal": COMPARER_ORDINAL,
    "Comparer.OrdinalIgnoreCase": COMPARER_ORDINAL_IGNORE_CASE,
    "Occurrence.First": V.Number(0.0),
    "Occurrence.Last": V.Number(1.0),
    "Occurrence.All": V.Number(2.0),
    "RelativePosition.FromStart": V.Number(0.0),
    "RelativePosition.FromEnd": V.Number(1.0),
    "TextEncoding.Utf8": V.Number(65001.0),
    "TextEncoding.Utf16": V.Number(1200.0),
    "TextEncoding.Unicode": V.Number(1200.0),
    "TextEncoding.BigEndianUnicode": V.Number(1201.0),
    "TextEncoding.Ascii": V.Number(20127.0),
    "TextEncoding.Windows": V.Number(1252.0),
    "Text.Trim": _native((("text", False), ("trimChars", True)), _text_trim),
    "Text.TrimStart": _native((("text", False), ("trimChars", True)), _text_trim_start),
    "Text.TrimEnd": _native((("text", False), ("trimChars", True)), _text_trim_end),
    "Text.Clean": _native((("text", False),), _text_clean),
    "Text.Reverse": _native((("text", False),), _text_reverse),
    "Text.ToList": _native((("text", False),), _text_to_list),
    "Text.Lower": _native((("text", False), ("culture", True)), _text_lower),
    "Text.Proper": _native((("text", False), ("culture", True)), _text_proper),
    "Text.Start": _native((("text", False), ("count", False)), _text_start),
    "Text.End": _native((("text", False), ("count", False)), _text_end),
    "Text.Middle": _native((("text", False), ("start", False), ("count", True)), _text_middle),
    "Text.Range": _native((("text", False), ("offset", False), ("count", True)), _text_range),
    "Text.At": _native((("text", False), ("index", False)), _text_at),
    "Text.Insert": _native((("text", False), ("offset", False), ("newText", False)), _text_insert),
    "Text.ReplaceRange": _native((("text", False), ("offset", False), ("count", False), ("newText", False)),
                                 _text_replace_range),
    "Text.RemoveRange": _native((("text", False), ("offset", False), ("count", True)), _text_remove_range),
    "Text.Repeat": _native((("text", False), ("count", False)), _text_repeat),
    "Text.PadStart": _native((("text", False), ("width", False), ("padChar", True)), _text_pad_start),
    "Text.PadEnd": _native((("text", False), ("width", False), ("padChar", True)), _text_pad_end),
    "Text.Contains": _native((("text", False), ("substring", False), ("comparer", True)), _text_contains),
    "Text.StartsWith": _native((("text", False), ("substring", False), ("comparer", True)), _text_starts_with),
    "Text.EndsWith": _native((("text", False), ("substring", False), ("comparer", True)), _text_ends_with),
    "Text.PositionOf": _native((("text", False), ("substring", False), ("occurrence", True),
                                ("comparer", True)), _text_position_of),
    "Text.PositionOfAny": _native((("text", False), ("characters", False), ("occurrence", True)),
                                  _text_position_of_any),
    "Text.Split": _native((("text", False), ("delimiter", False)), _text_split),
    "Text.SplitAny": _native((("text", False), ("separators", False)), _text_split_any),
    "Text.Combine": _native((("texts", False), ("separator", True)), _text_combine),
    "Text.Replace": _native((("text", False), ("oldValue", False), ("newValue", False)), _text_replace),
    "Text.Remove": _native((("text", False), ("removeChars", False)), _text_remove),
    "Text.Select": _native((("text", False), ("selectChars", False)), _text_select),
    "Text.BeforeDelimiter": _native((("text", False), ("delimiter", False), ("index", True)),
                                    _text_before_delimiter),
    "Text.AfterDelimiter": _native((("text", False), ("delimiter", False), ("index", True)),
                                   _text_after_delimiter),
    "Text.BetweenDelimiters": _native((("text", False), ("startDelimiter", False), ("endDelimiter", False),
                                       ("startIndex", True), ("endIndex", True)), _text_between_delimiters),
    "Text.Format": _native((("formatString", False), ("arguments", False), ("culture", True)), _text_format),
    "Text.FromBinary": _native((("binary", False), ("encoding", True)), _text_from_binary),
    "Text.ToBinary": _native((("text", False), ("encoding", True)), _text_to_binary),
    "Text.InferNumberType": _native((("text", False), ("options", True)), _infer_number_type),
    "Text.NewGuid": _native((), lambda: _new_guid()),
}


def _text_first(function: V.Function) -> V.Function:
    """Measured: a first argument that is neither text nor null is refused before any other argument is looked at."""
    inner = function.invoke

    def invoke(bound: list) -> MValue:
        first = V.force(bound[0])
        if not isinstance(first, (V.Null, V.Text)):
            raise V.convert_error(first, V.TypeValue("text"))
        return inner(bound)

    return V.Function(function.params, invoke)


for _name in ("Text.Trim", "Text.TrimStart", "Text.TrimEnd", "Text.Clean", "Text.Reverse", "Text.ToList", "Text.Lower",
              "Text.Proper", "Text.Start", "Text.End", "Text.Middle", "Text.Range", "Text.At", "Text.Insert",
              "Text.ReplaceRange", "Text.RemoveRange", "Text.Repeat", "Text.PadStart", "Text.PadEnd", "Text.Contains",
              "Text.StartsWith", "Text.EndsWith", "Text.PositionOf", "Text.PositionOfAny", "Text.Split",
              "Text.SplitAny", "Text.Replace", "Text.Remove", "Text.Select", "Text.BeforeDelimiter",
              "Text.AfterDelimiter", "Text.BetweenDelimiters", "Text.ToBinary", "Text.InferNumberType"):
    TEXT_GLOBALS[_name] = _text_first(TEXT_GLOBALS[_name])
