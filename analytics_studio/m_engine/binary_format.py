"""M engine BinaryFormat family of functions.

BinaryFormat functions read structured binary data according to specified formats.
"""

from __future__ import annotations

import codecs
import math
import struct
import threading
from decimal import Decimal
from typing import Callable, Optional, Tuple, Any

from . import values as V
from .number import (
    INT32_MIN,
    INT32_MAX,
    INT64_MIN,
    INT64_MAX,
    _range,
    _is_special,
)
from .table_fns import _unsupported
from .text import (
    _encoding_page,
    _check_page,
    _decode,
    INVALID_ENCODING,
    BOM_MISMATCH,
)
from .values import MError, MValue

_FORMAT_FLAG = "_m_is_binary_format"
_FORMAT_KIND = "_m_binary_format_kind"

# Endianness constants matching ByteOrder enum:
# ByteOrder.LittleEndian = 0.0
# ByteOrder.BigEndian = 1.0
_BYTE_ORDER_LITTLE = 0
_BYTE_ORDER_BIG = 1

_BYTE_ORDER_ERR = (
    "The value for a 'ByteOrder.Type' enumeration was not one of the allowed values: "
    "'ByteOrder.LittleEndian, ByteOrder.BigEndian'."
)


def _eof_error(pos: int) -> MError:
    return MError(
        "DataFormat.Error",
        f"There was a problem reading the binary format at position {pos}.  "
        "The end of the input was reached before the value could be read.",
    )


def _check_binary(arg: MValue) -> bytes:
    if not isinstance(arg, V.Binary):
        raise V.convert_error(arg, V.TypeValue("binary"))
    return arg.value


def _check_int32_len(val: MValue) -> int:
    if isinstance(val, V.Null):
        raise V.convert_error(val, V.TypeValue("number"))
    if not isinstance(val, V.Number):
        raise V.convert_error(val, V.TypeValue("number"))
    x = val.value
    if _is_special(x) or x != math.floor(x) or not INT32_MIN <= x <= INT32_MAX:
        raise _range("a 32 bit integer value")
    k = int(x)
    if k < 0:
        raise V.generic_error("The length cannot be negative.")
    return k


def _check_int64_len(val: MValue, param_name: str = "length") -> int:
    if isinstance(val, V.Null):
        raise V.convert_error(val, V.TypeValue("number"))
    if not isinstance(val, V.Number):
        raise V.convert_error(val, V.TypeValue("number"))
    x = val.value
    if _is_special(x) or x != math.floor(x) or not INT64_MIN <= x <= INT64_MAX:
        raise _range("a 64 bit integer value")
    k = int(x)
    if k < 0:
        if param_name == "count":
            raise V.generic_error("The 'count' parameter cannot be negative.")
        raise V.generic_error("The length cannot be negative.")
    return k


def _is_format_fn(fn: Any) -> bool:
    return isinstance(fn, V.Function) and getattr(fn, _FORMAT_FLAG, False)


_CONTEXT_STATE = threading.local()


class _FormatContext:
    def __init__(self, limit: int = 1_000_000):
        self.limit = limit
        self.item_count = 0

    def record_items(self, count: int = 1):
        self.item_count += count
        if self.item_count > self.limit:
            raise _unsupported("binary format result too large")


def _get_format_context() -> Optional[_FormatContext]:
    return getattr(_CONTEXT_STATE, "current", None)


def _make_format(reader_fn: Callable[[bytes, int, int], Tuple[MValue, int]], kind: str = "primitive") -> V.Function:
    """Creates a binary format function that takes one binary argument."""
    def invoke(bound: list) -> MValue:
        b_val = _check_binary(V.force(bound[0]))
        top_level = getattr(_CONTEXT_STATE, "current", None) is None
        if top_level:
            _CONTEXT_STATE.current = _FormatContext()
        try:
            val, _ = reader_fn(b_val, 0, _BYTE_ORDER_BIG)
            return val
        finally:
            if top_level:
                _CONTEXT_STATE.current = None

    fn = V.Function((V.ParamSpec("binary", None, False),), invoke)
    object.__setattr__(fn, _FORMAT_FLAG, True)
    object.__setattr__(fn, _FORMAT_KIND, kind)
    object.__setattr__(fn, "_reader_fn", reader_fn)
    return fn


def _read_byte(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    if pos >= len(b):
        raise _eof_error(pos)
    return V.Number(float(b[pos])), pos + 1


def _read_uint16(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    if pos + 2 > len(b):
        raise _eof_error(len(b))
    fmt = "<H" if byte_order == _BYTE_ORDER_LITTLE else ">H"
    return V.Number(float(struct.unpack_from(fmt, b, pos)[0])), pos + 2


def _read_sint16(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    if pos + 2 > len(b):
        raise _eof_error(len(b))
    fmt = "<h" if byte_order == _BYTE_ORDER_LITTLE else ">h"
    return V.Number(float(struct.unpack_from(fmt, b, pos)[0])), pos + 2


def _read_uint32(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    if pos + 4 > len(b):
        raise _eof_error(len(b))
    fmt = "<I" if byte_order == _BYTE_ORDER_LITTLE else ">I"
    return V.Number(float(struct.unpack_from(fmt, b, pos)[0])), pos + 4


def _read_sint32(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    if pos + 4 > len(b):
        raise _eof_error(len(b))
    fmt = "<i" if byte_order == _BYTE_ORDER_LITTLE else ">i"
    return V.Number(float(struct.unpack_from(fmt, b, pos)[0])), pos + 4


def _read_uint64(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    if pos + 8 > len(b):
        raise _eof_error(len(b))
    fmt = "<Q" if byte_order == _BYTE_ORDER_LITTLE else ">Q"
    val = struct.unpack_from(fmt, b, pos)[0]
    return V.Number(float(val), exact=str(val)), pos + 8


def _read_sint64(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    if pos + 8 > len(b):
        raise _eof_error(len(b))
    fmt = "<q" if byte_order == _BYTE_ORDER_LITTLE else ">q"
    val = struct.unpack_from(fmt, b, pos)[0]
    return V.Number(float(val), exact=str(val)), pos + 8


def _read_single(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    if pos + 4 > len(b):
        raise _eof_error(len(b))
    fmt = "<f" if byte_order == _BYTE_ORDER_LITTLE else ">f"
    val = struct.unpack_from(fmt, b, pos)[0]
    return V.Number(float(val)), pos + 4


def _read_double(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    if pos + 8 > len(b):
        raise _eof_error(len(b))
    fmt = "<d" if byte_order == _BYTE_ORDER_LITTLE else ">d"
    val = struct.unpack_from(fmt, b, pos)[0]
    return V.Number(float(val)), pos + 8


def _read_decimal(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    if pos + 16 > len(b):
        raise _eof_error(len(b))
    # 16 bytes: 12 bytes unsigned 96-bit int (little-endian), 2 bytes reserved, 1 byte scale, 1 byte sign
    lo_int = int.from_bytes(b[pos:pos + 12], "little")
    scale = b[pos + 14]
    sign_byte = b[pos + 15]
    is_neg = bool(sign_byte & 0x80)
    d = Decimal(lo_int)
    if scale > 0:
        d = d / (Decimal(10) ** scale)
    if is_neg:
        d = -d
    return V.Number(float(d)), pos + 16


def _read_7bit_uint(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    result = 0
    shift = 0
    curr = pos
    while True:
        if curr >= len(b):
            raise _eof_error(curr)
        byte_val = b[curr]
        curr += 1
        if shift > 63 or (shift == 63 and (byte_val & 0x7E) != 0):
            raise MError(
                "DataFormat.Error",
                "There was a problem reading the binary format.  The 7-bit encoded integer was greater than 63 bits.",
            )
        result |= (byte_val & 0x7F) << shift
        if not (byte_val & 0x80):
            break
        shift += 7
        if shift > 63:
            if curr < len(b) and (b[curr] & 0x80 or b[curr] > 1):
                raise MError(
                    "DataFormat.Error",
                    "There was a problem reading the binary format.  The 7-bit encoded integer was greater than 63 bits.",
                )
    return V.Number(float(result), exact=str(result)), curr


def _read_7bit_sint(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    uint_val, next_pos = _read_7bit_uint(b, pos, byte_order)
    raw = int(uint_val.exact if uint_val.exact is not None else uint_val.value)
    # Zigzag decode: (n >> 1) ^ -(n & 1)
    if raw & 1:
        sint = -((raw + 1) >> 1)
    else:
        sint = raw >> 1
    return V.Number(float(sint), exact=str(sint)), next_pos


def _read_null(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
    return V.Null(), pos


# ---- Constructors for parameterized formats ----------------------------------

def _binary_format_binary(length: MValue = V.Null()) -> V.Function:
    if isinstance(length, V.Null):
        # Reads whole input
        def read_whole(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
            return V.Binary(b[pos:]), len(b)
        return _make_format(read_whole, kind="binary")

    if _is_format_fn(length):
        sub_reader = getattr(length, "_reader_fn")
        kind = getattr(length, _FORMAT_KIND, "")
        if kind in ("text", "record", "null"):
            raise _unsupported("binary format binary length format of unsupported kind")
        if kind not in ("primitive", "transform"):
            raise V.generic_error("The specified binary format value cannot be used to read a length.")

        def read_fmt_len(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
            try:
                len_val, next_pos = sub_reader(b, pos, byte_order)
            except MError:
                raise
            if not isinstance(len_val, V.Number):
                raise V.generic_error("The specified binary format value cannot be used to read a length.")
            k = int(len_val.value)
            if k < 0:
                raise V.generic_error("The specified binary format value cannot be used to read a length.")
            if next_pos + k > len(b):
                raise _unsupported("binary format reading past end of input")
            return V.Binary(b[next_pos:next_pos + k]), next_pos + k

        return _make_format(read_fmt_len, kind="binary")

    # Length is a number
    n = _check_int32_len(length)

    def read_fixed(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
        if pos + n > len(b):
            raise _unsupported("binary format reading past end of input")
        return V.Binary(b[pos:pos + n]), pos + n

    return _make_format(read_fixed, kind="binary")


def _binary_format_length(binaryFormat: MValue, length: MValue) -> V.Function:
    if not isinstance(binaryFormat, V.Function):
        raise V.convert_error(binaryFormat, V.TypeValue("function"))
    if not _is_format_fn(binaryFormat):
        raise V.generic_error("The value isn't a binary format value.")

    sub_reader = getattr(binaryFormat, "_reader_fn")

    if _is_format_fn(length):
        len_reader = getattr(length, "_reader_fn")
        def read_dynamic_length(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
            len_val, p2 = len_reader(b, pos, byte_order)
            n = _check_int64_len(len_val, param_name="length")
            if p2 + n > len(b):
                raise _eof_error(len(b))
            sub_b = b[p2:p2 + n]
            val, _ = sub_reader(sub_b, 0, byte_order)
            return val, p2 + n
        return _make_format(read_dynamic_length, kind="length")

    n = _check_int64_len(length, param_name="length")

    def read_length(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
        sub_b = b[pos:pos + n]
        val, _ = sub_reader(sub_b, 0, byte_order)
        return val, pos + min(n, len(b) - pos)

    return _make_format(read_length, kind="length")


def _decode_binary_format_text(slice_b: bytes, page: int) -> str:
    if page == 850:
        return slice_b.decode("cp850")
    return _decode(slice_b, page)


def _binary_format_text(length: MValue, encoding: MValue = V.Null()) -> V.Function:
    page = _encoding_page(encoding)
    if page == 0:
        page = 1252
    if page != 850:
        _check_page(page)

    if _is_format_fn(length):
        len_reader = getattr(length, "_reader_fn")
        def read_dynamic_text(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
            len_val, p2 = len_reader(b, pos, byte_order)
            n = _check_int32_len(len_val)
            if p2 + n > len(b):
                raise _unsupported("binary format reading past end of input")
            slice_b = b[p2:p2 + n]
            s = _decode_binary_format_text(slice_b, page)
            return V.Text(s), p2 + n
        return _make_format(read_dynamic_text, kind="text")

    n = _check_int32_len(length)

    def read_text(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
        if pos + n > len(b):
            raise _eof_error(len(b))
        slice_b = b[pos:pos + n]
        s = _decode_binary_format_text(slice_b, page)
        return V.Text(s), pos + n

    return _make_format(read_text, kind="text")


def _binary_format_list(binaryFormat: MValue, countOrCondition: MValue = V.Null()) -> V.Function:
    if not isinstance(binaryFormat, V.Function):
        raise V.convert_error(binaryFormat, V.TypeValue("function"))
    if not _is_format_fn(binaryFormat):
        raise V.generic_error("The value isn't a binary format value.")

    sub_reader = getattr(binaryFormat, "_reader_fn")

    if isinstance(countOrCondition, V.Null):
        # Read until end of input
        def read_until_eof(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
            items = []
            curr = pos
            while curr < len(b):
                try:
                    val, next_pos = sub_reader(b, curr, byte_order)
                except MError:
                    raise _unsupported("binary format reading past end of input")
                if next_pos <= curr:
                    raise _unsupported("zero-width binary format list item")
                curr = next_pos
                items.append(val)
            return V.List(tuple(items)), curr
        return _make_format(read_until_eof, kind="list")

    if _is_format_fn(countOrCondition):
        count_kind = getattr(countOrCondition, _FORMAT_KIND, "")
        if count_kind in ("text", "record", "null"):
            raise _unsupported("binary format list count format of unsupported kind")
        count_reader = getattr(countOrCondition, "_reader_fn")
        def read_dynamic_count(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
            c_val, curr = count_reader(b, pos, byte_order)
            count = _check_int64_len(c_val, param_name="count")
            if count > 10_000_000:
                raise _unsupported("binary format list count exceeds limit")
            ctx = _get_format_context()
            if ctx is not None:
                ctx.record_items(count)
            items = []
            for _ in range(count):
                try:
                    val, next_pos = sub_reader(b, curr, byte_order)
                except MError as err:
                    if err.reason == "DataFormat.Error" and "The end of the input was reached before the value could be read" in err.message:
                        raise _unsupported("binary format reading past end of input")
                    raise
                curr = next_pos
                items.append(val)
            return V.List(tuple(items)), curr
        return _make_format(read_dynamic_count, kind="list")

    if isinstance(countOrCondition, V.Number):
        count = _check_int64_len(countOrCondition, param_name="count")
        if count > 10_000_000:
            raise _unsupported("binary format list count exceeds limit")
        def read_fixed_count(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
            ctx = _get_format_context()
            if ctx is not None:
                ctx.record_items(count)
            curr = pos
            items = []
            for _ in range(count):
                try:
                    val, next_pos = sub_reader(b, curr, byte_order)
                except MError as err:
                    if err.reason == "DataFormat.Error" and "The end of the input was reached before the value could be read" in err.message:
                        raise _unsupported("binary format reading past end of input")
                    raise
                curr = next_pos
                items.append(val)
            return V.List(tuple(items)), curr
        return _make_format(read_fixed_count, kind="list")

    if isinstance(countOrCondition, V.Function):
        # Condition function: read item, test cond(item). If false, stop (item included).
        from .evaluator import apply_function
        def read_while_cond(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
            curr = pos
            items = []
            stopped = False
            while curr < len(b):
                val, next_pos = sub_reader(b, curr, byte_order)
                if next_pos <= curr:
                    raise _unsupported("zero-width binary format list item")
                curr = next_pos
                items.append(val)
                cond_res = apply_function(countOrCondition, [val])
                if isinstance(cond_res, V.Logical) and not cond_res.value:
                    stopped = True
                    break
                if not isinstance(cond_res, V.Logical) or cond_res.value is True:
                    pass
            if not stopped:
                raise _unsupported("binary format predicate never turned false")
            return V.List(tuple(items)), curr
        return _make_format(read_while_cond, kind="list")

    raise V.generic_error("The 'countOrCondition' parameter must be either a number or function.")


def _binary_format_transform(binaryFormat: MValue, function: MValue) -> V.Function:
    if not isinstance(binaryFormat, V.Function):
        raise V.convert_error(binaryFormat, V.TypeValue("function"))
    if not _is_format_fn(binaryFormat):
        raise V.generic_error("The value isn't a binary format value.")
    if not isinstance(function, V.Function):
        raise V.convert_error(function, V.TypeValue("function"))

    from .evaluator import apply_function
    sub_reader = getattr(binaryFormat, "_reader_fn")

    def read_transform(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
        val, next_pos = sub_reader(b, pos, byte_order)
        transformed = apply_function(function, [val])
        return transformed, next_pos

    return _make_format(read_transform, kind="transform")


def _binary_format_byte_order(binaryFormat: MValue, byteOrder: MValue) -> V.Function:
    if not isinstance(binaryFormat, V.Function):
        raise V.convert_error(binaryFormat, V.TypeValue("function"))
    if not _is_format_fn(binaryFormat):
        raise V.generic_error("The value isn't a binary format value.")
    if isinstance(byteOrder, V.Null):
        raise V.convert_error(byteOrder, V.TypeValue("number"))
    if not isinstance(byteOrder, V.Number):
        raise V.convert_error(byteOrder, V.TypeValue("number"))

    bo_num = byteOrder.value
    if bo_num == 0.0:
        order = _BYTE_ORDER_LITTLE
    elif bo_num == 1.0:
        order = _BYTE_ORDER_BIG
    else:
        raise V.generic_error(_BYTE_ORDER_ERR)

    sub_reader = getattr(binaryFormat, "_reader_fn")

    def read_with_order(b: bytes, pos: int, current_order: int) -> Tuple[MValue, int]:
        # byteOrder parameter overrides current_order
        return sub_reader(b, pos, order)

    return _make_format(read_with_order, kind=getattr(binaryFormat, _FORMAT_KIND, "byteorder"))


def _binary_format_record(record: MValue) -> V.Function:
    if isinstance(record, V.Null):
        raise V.convert_error(record, V.TypeValue("record"))
    if not isinstance(record, V.Record):
        raise V.convert_error(record, V.TypeValue("record"))

    fields = list(record.fields)
    for name, field_val in fields:
        val = V.force(field_val)
        if isinstance(val, V.Function) and not _is_format_fn(val):
            raise _unsupported("binary format function in record")

    def read_record(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
        curr = pos
        out_fields = []
        for name, field_val in fields:
            val = V.force(field_val)
            if _is_format_fn(val):
                sub_r = getattr(val, "_reader_fn")
                res, curr = sub_r(b, curr, byte_order)
                out_fields.append((name, res))
            else:
                out_fields.append((name, val))
        return V.Record(tuple(out_fields)), curr

    return _make_format(read_record, kind="record")


def _binary_format_choice(
    length: MValue,
    binaryFormat: MValue,
    type_: MValue = V.Null(),
    externalLength: MValue = V.Null(),
) -> V.Function:
    if not isinstance(length, V.Function):
        raise V.convert_error(length, V.TypeValue("function"))
    if not _is_format_fn(length):
        raise V.generic_error("The value isn't a binary format value.")
    len_kind = getattr(length, _FORMAT_KIND, "")
    if len_kind in ("text", "record", "null"):
        raise _unsupported("binary format choice length format of unsupported kind")
    if not isinstance(binaryFormat, V.Function):
        raise V.convert_error(binaryFormat, V.TypeValue("function"))

    if not isinstance(type_, V.Null):
        if not isinstance(type_, V.TypeValue) or type_.name not in ("list", "binary", "any"):
            raise V.generic_error("We expected type List, Binary, or Any.")

    from .evaluator import apply_function
    len_reader = getattr(length, "_reader_fn")

    def read_choice(b: bytes, pos: int, byte_order: int) -> Tuple[MValue, int]:
        val, curr = len_reader(b, pos, byte_order)
        chosen_fmt = apply_function(binaryFormat, [val])
        if not _is_format_fn(chosen_fmt):
            raise V.generic_error("The value isn't a binary format value.")
        sub_reader = getattr(chosen_fmt, "_reader_fn")
        res, curr2 = sub_reader(b, curr, byte_order)
        return res, curr2

    return _make_format(read_choice, kind="choice")


def _binary_format_group(*args) -> MValue:
    raise _unsupported("binary format group")


# ---- Format singletons and table ---------------------------------------------

def _make_primitive_format(reader_fn) -> V.Function:
    return _make_format(reader_fn, kind="primitive")


BINARY_FORMAT_GLOBALS: dict[str, MValue] = {
    # ByteOrder Enum
    "ByteOrder.LittleEndian": V.Number(0.0),
    "ByteOrder.BigEndian": V.Number(1.0),

    # Primitive formats
    "BinaryFormat.Byte": _make_primitive_format(_read_byte),
    "BinaryFormat.UnsignedInteger16": _make_primitive_format(_read_uint16),
    "BinaryFormat.SignedInteger16": _make_primitive_format(_read_sint16),
    "BinaryFormat.UnsignedInteger32": _make_primitive_format(_read_uint32),
    "BinaryFormat.SignedInteger32": _make_primitive_format(_read_sint32),
    "BinaryFormat.UnsignedInteger64": _make_primitive_format(_read_uint64),
    "BinaryFormat.SignedInteger64": _make_primitive_format(_read_sint64),
    "BinaryFormat.Single": _make_primitive_format(_read_single),
    "BinaryFormat.Double": _make_primitive_format(_read_double),
    "BinaryFormat.Decimal": _make_primitive_format(_read_decimal),
    "BinaryFormat.7BitEncodedUnsignedInteger": _make_primitive_format(_read_7bit_uint),
    "BinaryFormat.7BitEncodedSignedInteger": _make_primitive_format(_read_7bit_sint),
    "BinaryFormat.Null": _make_format(_read_null, kind="null"),

    # Constructors
    "BinaryFormat.Binary": V.Function(
        (V.ParamSpec("length", None, True),),
        lambda bound: _binary_format_binary(V.force(bound[0])),
    ),
    "BinaryFormat.Length": V.Function(
        (V.ParamSpec("binaryFormat", None, False), V.ParamSpec("length", None, False)),
        lambda bound: _binary_format_length(V.force(bound[0]), V.force(bound[1])),
    ),
    "BinaryFormat.Text": V.Function(
        (V.ParamSpec("length", None, False), V.ParamSpec("encoding", None, True)),
        lambda bound: _binary_format_text(V.force(bound[0]), V.force(bound[1])),
    ),
    "BinaryFormat.List": V.Function(
        (V.ParamSpec("binaryFormat", None, False), V.ParamSpec("countOrCondition", None, True)),
        lambda bound: _binary_format_list(V.force(bound[0]), V.force(bound[1])),
    ),
    "BinaryFormat.Transform": V.Function(
        (V.ParamSpec("binaryFormat", None, False), V.ParamSpec("function", None, False)),
        lambda bound: _binary_format_transform(V.force(bound[0]), V.force(bound[1])),
    ),
    "BinaryFormat.ByteOrder": V.Function(
        (V.ParamSpec("binaryFormat", None, False), V.ParamSpec("byteOrder", None, False)),
        lambda bound: _binary_format_byte_order(V.force(bound[0]), V.force(bound[1])),
    ),
    "BinaryFormat.Record": V.Function(
        (V.ParamSpec("record", None, False),),
        lambda bound: _binary_format_record(V.force(bound[0])),
    ),
    "BinaryFormat.Choice": V.Function(
        (
            V.ParamSpec("length", None, False),
            V.ParamSpec("binaryFormat", None, False),
            V.ParamSpec("type", None, True),
            V.ParamSpec("externalLength", None, True),
        ),
        lambda bound: _binary_format_choice(
            V.force(bound[0]), V.force(bound[1]), V.force(bound[2]), V.force(bound[3])
        ),
    ),
    "BinaryFormat.Group": V.Function(
        (
            V.ParamSpec("binaryFormat", None, False),
            V.ParamSpec("group", None, False),
            V.ParamSpec("item", None, True),
            V.ParamSpec("count", None, True),
        ),
        lambda bound: _binary_format_group(*bound),
    ),
}
