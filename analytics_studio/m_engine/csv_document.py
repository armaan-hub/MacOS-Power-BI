import math
from typing import Optional, List, Tuple
from . import values as V
from .values import MValue, MError, TypeValue
from .table_fns import _unsupported, _type_spec, _col, _PRIMITIVES
from .csv_codepages import CODEPAGES

_KNOWN_FIELDS = ('Delimiter', 'Columns', 'Encoding', 'CsvStyle', 'QuoteStyle', 'ExtraValues')
_VALID_ENCODING_IDS = frozenset([
    0, 37, 437, 500, 708, 720, 737, 775, 850, 852, 855, 857, 858, 860, 861, 862, 863, 864, 865, 866,
    869, 870, 874, 875, 932, 936, 949, 950, 1026, 1047, 1140, 1141, 1142, 1143, 1144, 1145, 1146,
    1147, 1148, 1149, 1200, 1201, 1250, 1251, 1252, 1253, 1254, 1255, 1256, 1257, 1258, 1361, 10000,
    10001, 10002, 10003, 10004, 10005, 10006, 10007, 10008, 10010, 10017, 10021, 10029, 10079, 10081,
    10082, 12000, 12001, 20000, 20001, 20002, 20003, 20004, 20005, 20105, 20106, 20107, 20108, 20127,
    20261, 20269, 20273, 20277, 20278, 20280, 20284, 20285, 20290, 20297, 20420, 20423, 20424, 20833,
    20838, 20866, 20871, 20880, 20905, 20924, 20932, 20936, 20949, 21025, 21866, 28591, 28592, 28593,
    28594, 28595, 28596, 28597, 28598, 28599, 28603, 28605, 29001, 38598, 50220, 50221, 50222, 50225,
    50227, 51932, 51936, 51949, 52936, 54936, 57002, 57003, 57004, 57005, 57006, 57007, 57008, 57009,
    57010, 57011, 65000, 65001
])
_KNOWN_SINGLE_BYTE = CODEPAGES

def _validate_delimiter_record(val: MValue) -> str:
    if isinstance(val, V.Text):
        s = val.value
        utf16_len = len(s) + sum(1 for c in s if ord(c) > 0xFFFF)
        if utf16_len == 1:
            return s
        raise V.generic_error("The value isn't a single-character string.")
    elif isinstance(val, V.Number):
        v = val.value
        num_str = str(int(v)) if v.is_integer() else str(v)
        raise V.generic_error(f"We cannot convert the value {num_str} to type Text.")
    elif isinstance(val, V.Null):
        raise V.generic_error("We cannot convert the value null to type Text.")
    elif isinstance(val, V.List):
        raise V.generic_error("We cannot convert a value of type List to type Text.")
    else:
        raise _unsupported("Csv.Document delimiter of unexpected type")


def _validate_source(source: MValue) -> Tuple[bool, any]:
    if isinstance(source, V.Text):
        return True, source.value
    elif isinstance(source, V.Binary):
        return False, source.value
    else:
        raise V.generic_error("The parameter is expected to be of type Text.Type or Binary.Type.")


def _validate_encoding(encoding: Optional[MValue], is_text: bool) -> Optional[int]:
    if is_text or encoding is None or isinstance(encoding, V.Null):
        return None
    if isinstance(encoding, V.Text):
        raise V.generic_error(f'We cannot convert the value "{encoding.value}" to type Number.')
    if isinstance(encoding, V.Number):
        val = encoding.value
        if math.isnan(val) or math.isinf(val) or not val.is_integer() or val >= 2147483648:
            raise V.generic_error("The number is out of range of a 32 bit integer value.")
        enc_id = int(val)
        if enc_id in _VALID_ENCODING_IDS:
            return enc_id
        if enc_id == 2147483647:
            raise _unsupported("Csv.Document encoding 2147483647")
        raise V.generic_error("The text encoding is invalid.")
    raise _unsupported("Csv.Document encoding of unexpected type")


def _check_duplicate_names(names: List[str]):
    seen = set()
    for name in names:
        if name in seen:
            raise V.generic_error(f"The field '{name}' already exists in the record.")
        seen.add(name)


def _validate_columns(cols: Optional[MValue]) -> Tuple[Optional[int], Optional[List[str]], Optional[List[str]]]:
    if cols is None or isinstance(cols, V.Null):
        return None, None, None
    if isinstance(cols, V.Number):
        v = cols.value
        if not v.is_integer() or v < -2147483648 or v > 2147483647:
            raise V.generic_error("The number is out of range of a 32 bit integer value.")
        int_v = int(v)
        if int_v < 0:
            raise V.generic_error("The columns parameter must be null, specify the number of columns, specify a list of column names, or specify a table type.")
        if int_v > 1000000:
            raise _unsupported("columns number above 1,000,000")
        return int_v, None, None
    if isinstance(cols, V.List):
        names = []
        for item in cols.items:
            forced = V.force(item)
            if not isinstance(forced, V.Text):
                raise V.generic_error("The columns parameter must be null, specify the number of columns, specify a list of column names, or specify a table type.")
            names.append(forced.value)
        _check_duplicate_names(names)
        if len(names) > 1000000:
            raise _unsupported("columns number above 1,000,000")
        return len(names), names, None
    if isinstance(cols, TypeValue):
        if cols.name != 'table':
            raise V.generic_error("The columns parameter must be null, specify the number of columns, specify a list of column names, or specify a table type.")
        if cols.fields is None:
            return 0, [], []
        names = []
        types = []
        seen = set()
        for fname, ftype, optional in cols.fields:
            if optional:
                raise _unsupported("Csv.Document with a malformed table type")
            if fname in seen:
                raise _unsupported("Csv.Document with a malformed table type")
            seen.add(fname)
            names.append(fname)
            types.append(_type_spec(ftype))
        return len(names), names, types
    raise V.generic_error("The columns parameter must be null, specify the number of columns, specify a list of column names, or specify a table type.")


def _split_row(row_str: str, delim: str) -> List[str]:
    if delim == '':
        return [row_str]
    return row_str.split(delim)


def _csv_document(source: MValue, columns: Optional[MValue] = None, delimiter: Optional[MValue] = None, extraValues: Optional[MValue] = None, encoding: Optional[MValue] = None) -> MValue:
    # A. List as delimiter in positional form raised FIRST before any other validation
    if isinstance(delimiter, V.List):
        raise _unsupported("Csv.Document with a list as the delimiter")

    # Check if record form or positional form
    is_record_form = isinstance(columns, V.Record)

    if is_record_form:
        rec = columns
        if delimiter is not None and not isinstance(delimiter, V.Null):
            _validate_delimiter_record(delimiter)
            raise _unsupported("Csv.Document record form with positional arguments 3..5")
        if not (isinstance(extraValues, (V.Null, type(None))) and isinstance(encoding, (V.Null, type(None)))):
            raise _unsupported("Csv.Document record form with positional arguments 3..5")

        # 1. Unknown field name in record order
        for fname, _ in rec.fields:
            if fname not in _KNOWN_FIELDS:
                raise V.generic_error(f"The Csv.Document parameter '{fname}' is invalid.")

        # 2. QuoteStyle
        qs_val = rec.get('QuoteStyle')
        if qs_val is not None:
            if isinstance(qs_val, V.Null):
                raise _unsupported("Csv.Document with QuoteStyle null")
            elif isinstance(qs_val, V.Number):
                if qs_val.value not in (0.0, 1.0):
                    raise V.generic_error("The specified QuoteStyle is invalid.")
            else:
                raise V.generic_error("The specified QuoteStyle is invalid.")

        # 3. CsvStyle
        cs_val = rec.get('CsvStyle')
        if cs_val is not None:
            if isinstance(cs_val, V.Null):
                raise _unsupported("Csv.Document with CsvStyle null")
            elif isinstance(cs_val, V.Number):
                if cs_val.value not in (0.0, 1.0):
                    raise V.generic_error("The specified CsvStyle is invalid.")
            else:
                raise V.generic_error("The specified CsvStyle is invalid.")

        # 4. Delimiter
        d_val = rec.get('Delimiter')
        if d_val is not None:
            if cs_val is not None and isinstance(cs_val, V.Number) and cs_val.value == 1.0:
                is_single_char = False
                if isinstance(d_val, V.Text):
                    s = d_val.value
                    utf16_len = len(s) + sum(1 for c in s if ord(c) > 0xFFFF)
                    if utf16_len == 1:
                        is_single_char = True
                if not is_single_char:
                    raise _unsupported("Csv.Document record form QuoteAlways with non-single-char delimiter")
            delim_str = _validate_delimiter_record(d_val)
        else:
            delim_str = ','

        # 5. source
        is_text, src_data = _validate_source(source)

        # 6. Encoding
        enc_val = rec.get('Encoding')
        enc_id = _validate_encoding(enc_val, is_text)

        # Columns
        cols_val = rec.get('Columns')
        col_count, col_names, col_types = _validate_columns(cols_val)

        # Mode determination for record form
        if cs_val is not None and isinstance(cs_val, V.Number) and cs_val.value == 1.0:
            mode = 1  # Error
        else:
            mode = 2  # Ignore

    else:
        # Positional form validation order:
        # 1. extraValues number conversion & encoding number conversion
        if extraValues is not None and not isinstance(extraValues, V.Null):
            if isinstance(extraValues, V.Text):
                raise V.generic_error(f'We cannot convert the value "{extraValues.value}" to type Number.')
            elif not isinstance(extraValues, V.Number):
                raise _unsupported("Csv.Document positional extraValues of unexpected type")

        if encoding is not None and not isinstance(encoding, V.Null):
            if isinstance(encoding, V.Text):
                raise V.generic_error(f'We cannot convert the value "{encoding.value}" to type Number.')
            elif not isinstance(encoding, V.Number):
                raise _unsupported("Csv.Document encoding of unexpected type")

        # 2. delimiter text conversion
        if delimiter is not None and not isinstance(delimiter, V.Null):
            if isinstance(delimiter, V.Text):
                delim_str = delimiter.value
            elif isinstance(delimiter, V.Number):
                v = delimiter.value
                num_str = str(int(v)) if v.is_integer() else str(v)
                raise V.generic_error(f"We cannot convert the value {num_str} to type Text.")
            elif isinstance(delimiter, V.Null):
                raise V.generic_error("We cannot convert the value null to type Text.")
            else:
                raise _unsupported("Csv.Document delimiter of unexpected type")
        else:
            delim_str = ','

        # 3. source type check
        is_text, src_data = _validate_source(source)

        # 4. encoding invalid (binary sources only)
        enc_id = _validate_encoding(encoding, is_text)

        # 5. extraValues enum check
        if extraValues is None or isinstance(extraValues, V.Null):
            mode = 1  # default Error
        else:
            ev_num = extraValues.value
            if ev_num == 0.0:
                mode = 0  # List
            elif ev_num == 1.0:
                mode = 1  # Error
            elif ev_num == 2.0:
                mode = 2  # Ignore
            else:
                raise V.generic_error("The value for a 'ExtraValues.Type' enumeration was not one of the allowed values: 'ExtraValues.List, ExtraValues.Error, ExtraValues.Ignore'.")

        # 6. columns check
        col_count, col_names, col_types = _validate_columns(columns)



    if any(0xD800 <= ord(c) <= 0xDFFF for c in delim_str):
        raise _unsupported("Csv.Document with surrogate delimiter")

    # Decode source to text
    text_str = _decode_source(is_text, src_data, enc_id)

    # Quote check
    if '"' in text_str:
        raise _unsupported("Csv.Document over text that contains a double quote")

    # Delimiter refusal
    if any(c in delim_str for c in ('\r', '\n', '"')):
        raise _unsupported("Csv.Document with CR, LF, or quote as delimiter")

    # Parse rows
    if not text_str:
        rows_data = []
    else:
        norm = text_str.replace('\r\n', '\n').replace('\r', '\n')
        if norm.endswith('\n'):
            norm = norm[:-1]
        rows_data = norm.split('\n')

    # Determine final n columns and names/types
    if col_count is None:
        if not rows_data:
            n = 0
        else:
            n = len(_split_row(rows_data[0], delim_str))
        if mode == 0:
            n = n + 1
        final_names = [f"Column{i}" for i in range(1, n + 1)]
        final_types = ["text~Text.Type~1"] * n
    else:
        n = col_count
        if col_names is not None:
            final_names = col_names
        else:
            final_names = [f"Column{i}" for i in range(1, n + 1)]
        if col_types is not None:
            final_types = col_types
        else:
            final_types = ["text~Text.Type~1"] * n

    # Check mode List column constraint
    if mode == 0:
        if n == 0:
            raise V.generic_error("ExtraValues.List requires at least one column.")
        final_types[-1] = "list"

    # Mode Error eager check
    if mode == 1:
        for r_str in rows_data:
            flds = _split_row(r_str, delim_str)
            if len(flds) > n:
                raise _unsupported("Csv.Document with rows that have more values than columns (ExtraValues.Error)")

    # Build rows
    out_rows = []
    for r_str in rows_data:
        fields = _split_row(r_str, delim_str)
        if mode == 0:  # List
            m_count = n - 1
            lead = [V.Text(fields[i]) if i < len(fields) else V.Text("") for i in range(m_count)]
            tail = fields[m_count:]
            lst_items = tuple(V.Text(f) for f in tail)
            row_tuple = tuple(lead) + (V.List(lst_items),)
        else:  # Ignore or Error (fields <= n)
            cells = [V.Text(fields[i]) if i < len(fields) else V.Text("") for i in range(n)]
            row_tuple = tuple(cells)
        out_rows.append(row_tuple)

    meta_rec = V.Record((("FirstRowMayContainHeaders", V.Null()),))
    col_specs = tuple((final_names[i], final_types[i]) for i in range(n))
    return V.Table(col_specs, tuple(out_rows), meta=meta_rec)


def _decode_source(is_text: bool, data: any, enc_id: Optional[int]) -> str:
    if is_text:
        return data

    b = data
    if b.startswith(b'\xef\xbb\xbf'):
        try:
            s = b[3:].decode('utf-8')
            _check_surrogates(s)
            return s
        except UnicodeDecodeError:
            raise _unsupported("invalid UTF-8")
    if b.startswith(b'\xff\xfe\x00\x00'):
        b_sub = b[4:]
        rem = len(b_sub) % 4
        if rem != 0:
            b_sub = b_sub[:-rem]
        try:
            s = b_sub.decode('utf-32-le')
            _check_surrogates(s)
            return s
        except UnicodeDecodeError:
            raise _unsupported("invalid UTF-32 LE")
    if b.startswith(b'\xff\xfe'):
        b_sub = b[2:]
        rem = len(b_sub) % 2
        if rem != 0:
            b_sub = b_sub[:-rem]
        try:
            s = b_sub.decode('utf-16-le')
            _check_surrogates(s)
            return s
        except UnicodeDecodeError:
            raise _unsupported("invalid UTF-16 LE")
    if b.startswith(b'\xfe\xff'):
        b_sub = b[2:]
        rem = len(b_sub) % 2
        if rem != 0:
            b_sub = b_sub[:-rem]
        try:
            s = b_sub.decode('utf-16-be')
            _check_surrogates(s)
            return s
        except UnicodeDecodeError:
            raise _unsupported("invalid UTF-16 BE")
    if b.startswith(b'\x00\x00\xfe\xff'):
        b_sub = b[4:]
        rem = len(b_sub) % 4
        if rem != 0:
            b_sub = b_sub[:-rem]
        try:
            s = b_sub.decode('utf-32-be')
            _check_surrogates(s)
            return s
        except UnicodeDecodeError:
            raise _unsupported("invalid UTF-32 BE")

    # No BOM
    if enc_id == 0 and any(byte >= 0x80 for byte in b):
        raise _unsupported("Csv.Document with Encoding 0 over non-ASCII bytes (the machine's ANSI code page is not modelled)")

    enc = 65001 if enc_id is None else enc_id
    if enc == 65001:
        try:
            s = b.decode('utf-8')
            _check_surrogates(s)
            return s
        except UnicodeDecodeError:
            raise _unsupported("invalid UTF-8 without BOM")
    if enc == 1200:
        rem = len(b) % 2
        b_sub = b[:-rem] if rem != 0 else b
        try:
            s = b_sub.decode('utf-16-le')
            _check_surrogates(s)
            return s
        except UnicodeDecodeError:
            raise _unsupported("invalid UTF-16 LE")
    if enc == 1201:
        rem = len(b) % 2
        b_sub = b[:-rem] if rem != 0 else b
        try:
            s = b_sub.decode('utf-16-be')
            _check_surrogates(s)
            return s
        except UnicodeDecodeError:
            raise _unsupported("invalid UTF-16 BE")
    if enc == 12000:
        rem = len(b) % 4
        b_sub = b[:-rem] if rem != 0 else b
        try:
            s = b_sub.decode('utf-32-le')
            _check_surrogates(s)
            return s
        except UnicodeDecodeError:
            raise _unsupported("invalid UTF-32 LE")
    if enc == 12001:
        rem = len(b) % 4
        b_sub = b[:-rem] if rem != 0 else b
        try:
            s = b_sub.decode('utf-32-be')
            _check_surrogates(s)
            return s
        except UnicodeDecodeError:
            raise _unsupported("invalid UTF-32 BE")

    if enc in _KNOWN_SINGLE_BYTE:
        table = _KNOWN_SINGLE_BYTE[enc]
        chars = [chr(byte) if byte < 128 else table[byte - 128] for byte in b]
        return ''.join(chars)

    raise _unsupported(f"unsupported encoding {enc}")


def _check_surrogates(s: str):
    for ch in s:
        code = ord(ch)
        if 0xd800 <= code <= 0xdfff:
            raise _unsupported("lone surrogate")

