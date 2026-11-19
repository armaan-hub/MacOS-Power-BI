import re
from typing import Tuple

from . import values as V
from .values import MValue, MError


DELIMITERS: Tuple[str, ...] = (",", "\t", ";", ":", "|", "\x01", "W")

_BINARY_CHARS = frozenset(
    [chr(c) for c in range(2, 9)] +
    ["\x0c"] +
    [chr(c) for c in range(0x0e, 0x20)]
)

_W_CHARS = frozenset([" ", "\t", "\x0b"])

_CSV_COLUMNS = (
    ("PotentialDelimiter", "any"),
    ("QuoteStyle", "any"),
    ("MaxColumns", "any"),
    ("NonEmptyColumns", "any"),
    ("MaxRows", "any"),
    ("NonEmptyRows", "any"),
)


def _unsupported(what: str) -> MError:
    return V.generic_error(f"The {what} is not supported by this engine yet.")


def _binary_infer_content_type(binary: MValue) -> MValue:
    from .value_fns import _binary_of
    b_val = _binary_of(binary)
    data = b_val.value

    # 1. Window: only first 65536 bytes
    window = data[:65536]
    is_truncated = len(data) >= 65536

    # Detect BOM (check UTF-32 LE before UTF-16 LE because FF FE is prefix of FF FE 00 00)
    has_bom = False
    encoding = None
    bom_len = 0

    if window.startswith(b"\xef\xbb\xbf"):
        has_bom = True
        encoding = "utf-8"
        bom_len = 3
    elif window.startswith(b"\xff\xfe\x00\x00"):
        has_bom = True
        encoding = "utf-32-le"
        bom_len = 4
    elif window.startswith(b"\xff\xfe"):
        has_bom = True
        encoding = "utf-16-le"
        bom_len = 2
    elif window.startswith(b"\xfe\xff"):
        has_bom = True
        encoding = "utf-16-be"
        bom_len = 2

    # Refusals:
    # 1) Raw window contains NUL and no BOM. Encoding detection from a stray
    # NUL is only partly measured for short input (measured: short inputs with
    # a NUL behave differently), so refuse when the first 1024 bytes -- the
    # prefix detection can settle itself from -- contain a NUL. With a long
    # NUL-free prefix the encoding is settled and the content is not text:
    # measured (5000 x "a") + {0,1,2} => [Content.Type = null], returned
    # after the quote check below.
    nul_no_bom = (not has_bom) and (0x00 in window)
    if nul_no_bom and (0x00 in window[:1024]):
        raise _unsupported("Binary.InferContentType over raw binary containing NUL")

    # 2) Truncated input with UTF-16/UTF-32 BOM or any input >= 65536 with byte >= 0x80
    if is_truncated:
        if has_bom and encoding in ("utf-16-le", "utf-16-be", "utf-32-le"):
            raise _unsupported("Binary.InferContentType over truncated UTF-16/UTF-32 binary")
        if any(b >= 0x80 for b in window):
            raise _unsupported("Binary.InferContentType over truncated multi-byte binary")

    # Decode
    payload = window[bom_len:]
    if encoding == "utf-8" or not has_bom:
        text = payload.decode("utf-8", errors="replace")
    elif encoding == "utf-16-le":
        if len(payload) % 2 != 0:
            text = payload[:-1].decode("utf-16-le", errors="replace") + "\ufffd"
        else:
            text = payload.decode("utf-16-le", errors="replace")
    elif encoding == "utf-16-be":
        if len(payload) % 2 != 0:
            text = payload[:-1].decode("utf-16-be", errors="replace") + "\ufffd"
        else:
            text = payload.decode("utf-16-be", errors="replace")
    elif encoding == "utf-32-le":
        rem = len(payload) % 4
        if rem != 0:
            text = payload[:-rem].decode("utf-32-le", errors="replace") + ("\ufffd" * rem)
        else:
            text = payload.decode("utf-32-le", errors="replace")
    else:
        text = payload.decode("utf-8", errors="replace")

    # Refusal: decoded window contains a double quote that could affect the
    # parse (checked before binary control chars). A quote is inert, and the
    # answer computable, when it cannot change any count: the window has no
    # line break and no delimiter character and does not open with a quote
    # (measured: A"B => text/csv). Once structure is present the quote rule
    # is only partly measured, so refuse rather than guess.
    if '"' in text:
        if text[:1] == '"' or any(c in text for c in "\r\n,;:|\t\x01"):
            raise _unsupported("Binary.InferContentType over text that contains a double quote")

    # NUL past a settled (NUL-free) prefix: the content is not text
    # (measured: Content.Type = null).
    if nul_no_bom:
        return V.Record((("Content.Type", V.Null()),))

    # Refusal: decoded text contains U+0000 after BOM decode
    if has_bom and "\x00" in text:
        raise _unsupported("Binary.InferContentType over decoded text containing NUL")

    # Binary check: U+0002..U+0008, U+000C, U+000E..U+001F
    if any(c in _BINARY_CHARS for c in text):
        return V.Record((("Content.Type", V.Null()),))

    # Parse rows: line breaks are LF, CR, or CRLF
    raw_lines = re.split(r"\r\n|[\r\n]", text)
    rows = [line for line in raw_lines if line != ""]
    if is_truncated and rows:
        rows.pop()

    if not rows:
        return V.Record((("Content.Type", V.Null()),))

    # Compute statistics per delimiter
    table_rows = []
    for d in DELIMITERS:
        if d != "W":
            field_counts = [row.count(d) + 1 for row in rows]
        else:
            field_counts = []
            for row in rows:
                runs = 0
                in_run = False
                for ch in row:
                    if ch in _W_CHARS:
                        if not in_run:
                            runs += 1
                            in_run = True
                    elif ch == "\x85":
                        # NEL does not start a whitespace run and does not interrupt an ongoing whitespace run
                        pass
                    else:
                        in_run = False
                field_counts.append(runs + 1)

        max_cols = max(field_counts)
        max_rows = len(field_counts)
        counts = {}
        best_fc = 0
        best_cnt = 0
        for fc in field_counts:
            c = counts.get(fc, 0) + 1
            counts[fc] = c
            if c > best_cnt:
                best_cnt = c
                best_fc = fc

        d_val = V.Text(d)
        r0 = (d_val, V.Number(0.0), V.Number(float(max_cols)), V.Number(float(best_fc)),
              V.Number(float(max_rows)), V.Number(float(best_cnt)))
        r1 = (d_val, V.Number(1.0), V.Number(float(max_cols)), V.Number(float(best_fc)),
              V.Number(float(max_rows)), V.Number(float(best_cnt)))
        table_rows.append(r0)
        table_rows.append(r1)

    t = V.Table(_CSV_COLUMNS, tuple(table_rows))
    return V.Record((
        ("Content.Type", V.Text("text/csv")),
        ("Csv.PotentialDelimiters", t),
    ))
