from typing import Optional, List, Tuple
from . import values as V
from .values import MValue, MError, TypeValue
from .table_fns import _unsupported, _type_spec, _col, _PRIMITIVES
from .csv_codepages import CODEPAGES

_KNOWN_FIELDS = ('Delimiter', 'Columns', 'Encoding', 'CsvStyle', 'QuoteStyle', 'ExtraValues')
_INVALID_ENCODINGS = frozenset([2, 3, 4, 5, 10, 100, 300, 1000, 1199, 1202, 12002, 28600, 28604, 65002, 99999])
_KNOWN_SINGLE_BYTE = CODEPAGES

def _csv_document(source: MValue, columns: Optional[MValue] = None, delimiter: Optional[MValue] = None, extraValues: Optional[MValue] = None, encoding: Optional[MValue] = None) -> MValue:
    # Check if record form or positional form
    is_record_form = isinstance(columns, V.Record)

    if is_record_form:
        rec = columns
        if delimiter is not None and not isinstance(delimiter, V.Null):
            _validate_delimiter(delimiter)
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
            delim_char = _validate_delimiter(d_val)
        else:
            delim_char = ','

        # 5. source
        is_text, src_data = _validate_source(source)

        # 6. Encoding
        enc_val = rec.get('Encoding')
        enc_id = _validate_encoding(enc_val, is_text)

        # ExtraValues in record
        ev_val = rec.get('ExtraValues')
        if ev_val is not None:
            if not (isinstance(ev_val, V.Null) or isinstance(ev_val, V.Number)):
                raise _unsupported("Csv.Document record form with non-number ExtraValues")

        # Columns
        cols_val = rec.get('Columns')
        col_count, col_names, col_types = _validate_columns(cols_val)

        # Mode determination for record form
        if cs_val is not None and isinstance(cs_val, V.Number) and cs_val.value == 1.0:
            mode = 1  # Error
            is_default_mode = False
        else:
            mode = 2  # Ignore
            is_default_mode = True

    else:
        # Positional form
        # Pairwise measurements: delimiter error takes precedence over source error (b66_pos_SD).
        if delimiter is not None and not isinstance(delimiter, V.Null):
            delim_char = _validate_delimiter(delimiter)
        else:
            delim_char = ','

        # source
        is_text, src_data = _validate_source(source)

        # 3. encoding
        enc_id = _validate_encoding(encoding, is_text)

        # 4. extraValues
        if extraValues is None or isinstance(extraValues, V.Null):
            mode = 1  # default Error
            is_default_mode = True
        elif isinstance(extraValues, V.Number):
            ev_num = extraValues.value
            if ev_num == 0.0:
                mode = 0  # List
                is_default_mode = False
            elif ev_num == 1.0:
                mode = 1  # Error
                is_default_mode = False
            elif ev_num == 2.0:
                mode = 2  # Ignore
                is_default_mode = False
            else:
                raise V.generic_error("The value for a 'ExtraValues.Type' enumeration was not one of the allowed values: 'ExtraValues.List, ExtraValues.Error, ExtraValues.Ignore'.")
        elif isinstance(extraValues, V.Text):
            raise V.generic_error(f'We cannot convert the value "{extraValues.value}" to type Number.')
        else:
            raise _unsupported("Csv.Document positional extraValues of unexpected type")

        # 5. columns
        col_count, col_names, col_types = _validate_columns(columns)

    # Decode source to text
    text_str = _decode_source(is_text, src_data, enc_id)

    # Quote check
    if '"' in text_str:
        raise _unsupported("Csv.Document over text that contains a double quote")

    # Check empty binary source refusal
    if not is_text and len(src_data) == 0:
        raise _unsupported("Csv.Document over empty binary")

    # Delimiter refusal
    if delim_char in ('\r', '\n', '"'):
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
            n = len(rows_data[0].split(delim_char))
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
            raise _unsupported("Csv.Document ExtraValues.List with 0 columns")
        final_types[-1] = "list"

    # Mode Error row check
    has_row_read_error = False
    if mode == 1:
        for r_str in rows_data:
            flds = r_str.split(delim_char)
            if len(flds) > n:
                has_row_read_error = True
                break

    # Build rows
    out_rows = []
    for r_str in rows_data:
        fields = r_str.split(delim_char)
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
    row_err = _unsupported("Csv.Document ExtraValues.Error with row having more fields than expected") if has_row_read_error else None
    res_tbl = V.Table(col_specs, tuple(out_rows), meta=meta_rec, row_error=row_err)
    return res_tbl


def _validate_delimiter(val: MValue) -> str:
    if isinstance(val, V.Text):
        s = val.value
        # exactly one UTF-16 code unit
        if len(s.encode('utf-16-le')) == 2:
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
        return 0
    if isinstance(encoding, V.Text):
        raise V.generic_error(f'We cannot convert the value "{encoding.value}" to type Number.')
    if isinstance(encoding, V.Number):
        val = encoding.value
        if not val.is_integer():
            raise _unsupported("Csv.Document non-integer encoding")
        enc_id = int(val)
        if enc_id < 0 or enc_id == 1 or enc_id in _INVALID_ENCODINGS:
            raise V.generic_error("The text encoding is invalid.")
        return enc_id
    raise _unsupported("Csv.Document encoding of unexpected type")


def _validate_columns(cols: Optional[MValue]) -> Tuple[Optional[int], Optional[List[str]], Optional[List[str]]]:
    if cols is None or isinstance(cols, V.Null):
        return None, None, None
    if isinstance(cols, V.Number):
        v = cols.value
        if not v.is_integer():
            raise V.generic_error("The number is out of range of a 32 bit integer value.")
        int_v = int(v)
        if int_v < 0 or int_v > 2147483647:
            raise V.generic_error("The columns parameter must be null, specify the number of columns, specify a list of column names, or specify a table type.")
        return int_v, None, None
    if isinstance(cols, V.List):
        names = []
        for item in cols.items:
            forced = V.force(item)
            if not isinstance(forced, V.Text):
                raise V.generic_error("The columns parameter must be null, specify the number of columns, specify a list of column names, or specify a table type.")
            names.append(forced.value)
        _check_duplicate_names(names)
        return len(names), names, None
    if isinstance(cols, TypeValue):
        if cols.name != 'table':
            raise V.generic_error("The columns parameter must be null, specify the number of columns, specify a list of column names, or specify a table type.")
        if cols.fields is None:
            return 0, [], []
        names = []
        types = []
        for fname, ftype, _ in cols.fields:
            names.append(fname)
            types.append(_type_spec(ftype))
        _check_duplicate_names(names)
        return len(names), names, types
    raise V.generic_error("The columns parameter must be null, specify the number of columns, specify a list of column names, or specify a table type.")


def _check_duplicate_names(names: List[str]):
    seen = set()
    for name in names:
        if name in seen:
            raise V.generic_error(f"The field '{name}' already exists in the record.")
        seen.add(name)


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
    enc = 65001 if (enc_id is None or enc_id == 0) else enc_id
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

