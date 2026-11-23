"""Streaming CSV importer into DuckStore.

This module parses delimited text (CSV, TSV, etc.) into DuckStore using a
dedicated in-memory DuckDB reader session and PyArrow batches. Python performs
no per-cell work on the data rows.

Where this importer differs from the normal importer (``file_import._parse_csv``):

* It refuses a file that has a space directly before an opening quote
  (``1, "x,y",3``): the normal importer keeps the quote as text, DuckDB would
  treat it as a quote, so the two cannot agree.
* It refuses a file that mixes a lone carriage return with quotes or with
  other line endings, and a file that contains the internal NULL marker bytes.
* It refuses header names the store cannot hold (names that differ only by
  letter case, control characters, a leading ``__``).
* It reads two malformed-quote classes leniently and says so in
  ``CsvImportSummary.notices``: an unterminated quote at end of file, and text
  directly after a closing quote (``"abc"def``). The normal importer refuses
  both.

Everything else must match the normal importer cell for cell, or refuse.

All byte scans (line endings, marker bytes, quote check) carry their state
across chunk boundaries, never look ahead past the chunk and never seek back, so
the answer does not depend on the chunk size.
"""

from __future__ import annotations

import codecs
import csv
from dataclasses import dataclass
import io
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Any, BinaryIO, Callable, Optional

import duckdb
import pyarrow as pa
import pyarrow.compute as pc

from analytics_studio import file_import as _fi
from analytics_studio.file_import import (
    FileImportError,
    ImportCancelledError,
    ImportCandidate,
    _check_column_limit,
    _is_empty_record,
    _normalize_headers,
)
from analytics_studio.store.base import Store
from analytics_studio.store.duck_store import _ascii_lower

_NULL_SENTINEL = "\x01NULL\x01"
_NC = 513  # MAX_COLUMNS + 1, to detect over-limit column counts
_WIDTH_TIERS = (17, 65, _NC)  # schema sizes for the width pre-pass, last one is the full size
_BATCH_SIZE = 50_000
_8MB = 8 * 1024 * 1024
_1MB = 1024 * 1024
_SCAN_SUBBLOCK = 64 * 1024  # exact quote scan checks Cancel at least this often
_FAST_CHUNK = _1MB  # vectorised quote check works on pieces this size: keeps its memory small
_UTF8_BOM = b"\xef\xbb\xbf"


@dataclass
class CsvImportSummary:
    headers: list[str]
    row_count: int
    source_id: str
    notices: list[str]


def _raise_if_cancelled(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ImportCancelledError("Import canceled.")


def _read_error(name: str, exc: OSError) -> FileImportError:
    return FileImportError(f"Could not read {name}: {exc.strerror or exc}.")


def _clean_old_temp_folders() -> None:
    """Delete leftover temporary CSV transcode folders older than 1 day owned by current user."""
    try:
        tmp_base = tempfile.gettempdir()
        cutoff = time.time() - 86400
        my_uid = os.getuid()
        for name in os.listdir(tmp_base):
            if name.startswith("analytics_studio_csv_"):
                folder = os.path.join(tmp_base, name)
                try:
                    st = os.stat(folder)
                    if os.path.isdir(folder) and st.st_uid == my_uid and st.st_mtime < cutoff:
                        shutil.rmtree(folder, ignore_errors=True)
                except Exception:
                    pass
    except Exception:
        pass


def _check_line_endings_and_sentinel(
    path: Path,
    sentinel_bytes: bytes,
    cancel_event: Optional[threading.Event] = None,
    chunk_size: int = _8MB,
) -> tuple[int, int, int, int]:
    """Scan raw bytes in chunks to count EOL markers and quotes, and check the sentinel.

    The sentinel check keeps the last len(sentinel) - 1 bytes of every chunk, so
    a sentinel that straddles a chunk boundary is found as well.
    """
    crlf = 0
    cr = 0
    lf = 0
    quotes = 0
    prev_last_byte = b""
    tail = b""
    keep = max(len(sentinel_bytes) - 1, 0)

    try:
        with open(path, "rb") as f:
            while True:
                _raise_if_cancelled(cancel_event)
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                window = tail + chunk
                if sentinel_bytes in window:
                    raise FileImportError(
                        f"The file {path.name} contains internal sentinel byte sequences that cannot be preserved."
                    )
                tail = window[-keep:] if keep else b""
                quotes += chunk.count(b'"')
                cr += chunk.count(b"\r")
                lf += chunk.count(b"\n")
                crlf += chunk.count(b"\r\n")
                if prev_last_byte == b"\r" and chunk.startswith(b"\n"):
                    crlf += 1
                prev_last_byte = chunk[-1:]
    except OSError as exc:
        raise _read_error(path.name, exc) from exc

    lone_cr = cr - crlf
    lone_lf = lf - crlf
    return crlf, lone_cr, lone_lf, quotes


def _open_after_bom(path: Path) -> BinaryIO:
    """Open a file for the quote scans, positioned after a leading UTF-8 BOM (DuckDB strips it)."""
    f = open(path, "rb")
    try:
        if f.read(3) != _UTF8_BOM:
            f.seek(0)
    except BaseException:
        f.close()
        raise
    return f


class _QuoteScanner:
    """Exact quote state machine. All state lives here, so it can be fed in any chunking.

    States: 0 field start, 1 only spaces so far in the field, 2 unquoted field,
    3 quoted field, 4 right after a closing quote, 5 saw a quote inside a quoted
    field (escaped pair or closing quote: decided by the next byte).
    A quote only opens a quoted field at the start of a field.
    """

    def __init__(self, delimiter: str) -> None:
        self.delim = ord(delimiter.encode("utf-8"))
        self.state = 0
        self.line = 1
        self.prev = -1
        self.text_after_quote = False

    def feed(self, block: bytes) -> None:
        delim = self.delim
        state = self.state
        line = self.line
        prev = self.prev
        text_after = self.text_after_quote
        for b in block:
            if b == 10:
                if prev != 13:
                    line += 1
            elif b == 13:
                line += 1

            if state == 5:
                if b == 34:
                    state = 3  # escaped quote pair
                else:  # the quote before was the closing quote
                    if b == delim or b == 10 or b == 13:
                        state = 0
                    else:
                        text_after = True
                        state = 2
            elif state == 2:
                if b == delim or b == 10 or b == 13:
                    state = 0
            elif state == 3:
                if b == 34:
                    state = 5
            elif state == 0:
                if b == 32:
                    state = 1
                elif b == 34:
                    state = 3
                elif b == delim or b == 10 or b == 13:
                    pass
                else:
                    state = 2
            elif state == 1:
                if b == 32:
                    pass
                elif b == 34:
                    self.state = state
                    self.line = line
                    self.prev = prev
                    self.text_after_quote = text_after
                    raise FileImportError(
                        f"Line {line} has a space before a quote; "
                        f"the large-file importer cannot read it the same way as the normal importer. "
                        f"Remove the space or the quote."
                    )
                elif b == delim or b == 10 or b == 13:
                    state = 0
                else:
                    state = 2
            else:  # state 4
                if b == delim or b == 10 or b == 13:
                    state = 0
                else:
                    text_after = True
                    state = 2
            prev = b

        self.state = state
        self.line = line
        self.prev = prev
        self.text_after_quote = text_after

    def finish(self, name: str) -> list[str]:
        notices: list[str] = []
        if self.state == 3:
            notices.append(
                f"The file {name} contains an unterminated quote at end of file; parsed leniently."
            )
        if self.text_after_quote:
            notices.append(
                f"The file {name} contains unescaped text following a closing quote; parsed leniently."
            )
        return notices


def _exact_quote_scan(
    path: Path,
    delimiter: str,
    cancel_event: Optional[threading.Event] = None,
    chunk_size: int = _8MB,
) -> list[str]:
    """Exact byte-by-byte scan: refuse a space before a quote, collect lenient-parse notices."""
    scanner = _QuoteScanner(delimiter)
    try:
        with _open_after_bom(path) as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                for off in range(0, len(chunk), _SCAN_SUBBLOCK):
                    _raise_if_cancelled(cancel_event)
                    scanner.feed(chunk[off:off + _SCAN_SUBBLOCK])
    except OSError as exc:
        raise _read_error(path.name, exc) from exc
    return scanner.finish(path.name)


def _all_true(mask: Any) -> bool:
    value = pc.all(mask, min_count=0).as_py()
    return True if value is None else bool(value)


def _fast_quote_check(
    path: Path,
    delimiter: str,
    cancel_event: Optional[threading.Event] = None,
    chunk_size: int = _8MB,
) -> bool:
    """Vectorised proof that the exact scan would find nothing (no refusal, no notice).

    Returns True only when the file is provably clean. Returns False when it is
    dirty or when this check cannot tell (for example a quote inside an unquoted
    field): the caller then runs the exact scan. It never answers True for a
    file the exact scan would refuse or give a notice for.

    Method: every run of consecutive quote bytes flips the "inside a quoted
    field" state when the run length is odd. A run that starts outside a quoted
    field must follow a delimiter or line end (a quote that opens a field); a run
    that ends outside a quoted field must be followed by a delimiter, a line
    end or the end of the file. Runs are never split across chunks: a chunk that
    ends in a quote is extended with the next read before it is checked.
    """
    chunk_size = min(chunk_size, _FAST_CHUNK)
    delim_byte = ord(delimiter.encode("utf-8"))
    boundary_values = pa.array([delim_byte, 10, 13], pa.uint8())
    inside = 0  # parity of quote runs so far: 1 = inside a quoted field
    prev = 10  # byte before the current chunk (start of file counts as a line end)
    try:
        with _open_after_bom(path) as f:
            while True:
                _raise_if_cancelled(cancel_event)
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                while chunk[-1] == 34:
                    more = f.read(chunk_size)
                    if not more:
                        break
                    chunk += more
                n = len(chunk)
                arr = pa.Array.from_buffers(pa.uint8(), n, [None, pa.py_buffer(chunk)])
                q = pc.indices_nonzero(pc.equal(arr, 34))
                m = len(q)
                if m:
                    if m > 1:
                        new_run = pc.not_equal(pc.subtract(q[1:], q[:-1]), 1)
                        starts_mask = pa.concat_arrays([pa.array([True]), new_run])
                        ends_mask = pa.concat_arrays([new_run, pa.array([True])])
                    else:
                        starts_mask = ends_mask = pa.array([True])
                    starts = pc.filter(q, starts_mask)
                    ends = pc.filter(q, ends_mask)
                    lengths = pc.add(pc.subtract(ends, starts), 1)
                    cumulative = pc.cumulative_sum(lengths)
                    before = pc.bit_wise_and(
                        pc.add(pc.subtract(cumulative, lengths), pa.scalar(inside, pa.uint64())), 1
                    )
                    after = pc.bit_wise_and(pc.add(before, lengths), 1)

                    # Runs that start outside a quoted field must start a field.
                    openers = pc.filter(starts, pc.equal(before, 0))
                    if len(openers):
                        if openers[0].as_py() == 0:
                            if prev not in (delim_byte, 10, 13):
                                return False
                            openers = openers[1:]
                        if len(openers):
                            preceding = pc.take(arr, pc.subtract(openers, 1))
                            if not _all_true(pc.is_in(preceding, value_set=boundary_values)):
                                return False

                    # Runs that end outside a quoted field must end a field.
                    closers = pc.filter(ends, pc.equal(after, 0))
                    closers = pc.filter(closers, pc.less(closers, n - 1))
                    if len(closers):
                        following = pc.take(arr, pc.add(closers, 1))
                        if not _all_true(pc.is_in(following, value_set=boundary_values)):
                            return False

                    inside = int(after[len(after) - 1].as_py())
                prev = chunk[-1]
    except OSError as exc:
        raise _read_error(path.name, exc) from exc
    finally:
        pa.default_memory_pool().release_unused()
    return inside == 0


def _scan_quote_structure(
    path: Path,
    delimiter: str,
    cancel_event: Optional[threading.Event] = None,
    chunk_size: int = _8MB,
) -> tuple[list[str], bool]:
    """Quote check: (notices, line_structure_is_exact).

    The second value is True when the vectorised check proved the file clean. Then
    a record ends exactly at a line end that has an even number of quote bytes
    before it, so record starts can be found without parsing.
    """
    if _fast_quote_check(path, delimiter, cancel_event=cancel_event, chunk_size=chunk_size):
        return [], True
    return _exact_quote_scan(path, delimiter, cancel_event=cancel_event, chunk_size=chunk_size), False


def _detect_malformed_quotes_and_space_before_quote(
    path: Path,
    delimiter: str,
    cancel_event: Optional[threading.Event] = None,
    chunk_size: int = _8MB,
) -> list[str]:
    """Detect space-before-quote (refusal) and malformed quotes (lenient notices).

    A vectorised check proves most files clean. Anything it cannot prove goes to
    the exact scan, so the result is always the exact scan's result.
    """
    return _scan_quote_structure(path, delimiter, cancel_event, chunk_size)[0]


def _transcode_to_utf8(
    src_path: Path,
    dest_path: Path,
    encoding: str,
    cancel_event: Optional[threading.Event] = None,
    chunk_size: int = _1MB,
    prepend_bom: bool = False,
    display_encoding: Optional[str] = None,
) -> None:
    """Stream chunks through an incremental decoder into a UTF-8 temp file."""
    shown = display_encoding or encoding
    try:
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    except LookupError as exc:
        raise FileImportError(f"Unsupported text encoding {encoding!r}.") from exc

    try:
        with open(src_path, "rb") as f_in, open(dest_path, "wb") as f_out:
            if prepend_bom:
                f_out.write(_UTF8_BOM)
            while True:
                _raise_if_cancelled(cancel_event)
                chunk = f_in.read(chunk_size)
                if not chunk:
                    final_text = decoder.decode(b"", final=True)
                    if final_text:
                        f_out.write(final_text.encode("utf-8"))
                    break
                text_chunk = decoder.decode(chunk, final=False)
                if text_chunk:
                    f_out.write(text_chunk.encode("utf-8"))
    except UnicodeDecodeError as exc:
        raise FileImportError(f"Could not decode {src_path.name} as {shown}.") from exc
    except OSError as exc:
        raise _read_error(src_path.name, exc) from exc


def _validate_headers_for_store(headers: list[str]) -> None:
    """Validate headers before transaction starts per Store rules."""
    seen_ci: set[str] = set()
    for h in headers:
        h_ci = _ascii_lower(h)  # the store folds only ASCII letters
        if (
            h.startswith("__")
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in h)
            or h_ci in seen_ci
        ):
            raise FileImportError(
                f"Column name {h!r} cannot be used by the large-file store: "
                f"names must be unique ignoring letter case, must not contain "
                f"control characters (such as a line break) and must not start with '__'."
            )
        seen_ci.add(h_ci)


def _read_csv_sql(escaped_path: str, escaped_delim: str, ncols: int) -> str:
    """The read_csv(...) call with an exact schema of ncols VARCHAR columns."""
    col_defs = "{" + ",".join(f"'c{i}':'VARCHAR'" for i in range(ncols)) + "}"
    return (
        f"read_csv('{escaped_path}', all_varchar=true, header=false, "
        f"delim='{escaped_delim}', quote='\"', escape='\"', strict_mode=false, "
        f"null_padding=true, auto_detect=false, parallel=false, "
        f"nullstr='{_NULL_SENTINEL}', encoding='utf-8', max_line_size=16000000, "
        f"columns={col_defs})"
    )


def _empty_cells_sql(ncols: int) -> str:
    return " AND ".join(f"(c{i} IS NULL OR c{i} = '')" for i in range(ncols))


def _python_kept_width(
    path: Path,
    delimiter: str,
    cancel_event: Optional[threading.Event],
) -> int:
    """Exact widest kept record by streaming the whole file through Python's csv module.

    Only used when a record fills the last schema column while every cell the
    schema shows is empty, so DuckDB cannot tell whether later cells hold data.
    """
    widest = 0
    with _fi._CSV_FIELD_LIMIT_LOCK:
        old_limit = csv.field_size_limit()
        csv.field_size_limit(_fi.MAX_SOURCE_BYTES)
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as stream:
                for index, record in enumerate(csv.reader(stream, delimiter=delimiter)):
                    if index % 10_000 == 0:
                        _raise_if_cancelled(cancel_event)
                    if _is_empty_record(record):
                        continue
                    _check_column_limit(len(record))
                    widest = max(widest, len(record))
        except csv.Error as exc:
            raise FileImportError(f"Could not parse {path.name} as CSV: {exc}") from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise FileImportError(f"Could not read {path.name}: {exc}.") from exc
        finally:
            csv.field_size_limit(old_limit)
    return widest


def _wide_candidate_offsets(
    path: Path,
    delimiter: str,
    n: int,
    has_quotes: bool,
    cancel_event: Optional[threading.Event],
    chunk_size: int,
) -> list[int]:
    """Byte offsets of records that may start with n empty cells followed by more cells.

    Such a record begins with n delimiters, each cell before them being empty or an
    empty quoted pair, so its first min(n, 16) bytes are all delimiter or quote bytes.
    Only the records that pass this test are looked at by Python. Needs a file whose
    line structure is exact: a line start counts as a record start when the number of
    quote bytes before it is even.
    """
    delim = ord(delimiter.encode("utf-8"))
    k = min(n, 16)
    wanted = pa.array([delim, 34], pa.uint8())
    ends = pa.array([10, 13], pa.uint8())
    offsets: list[int] = []
    inside = 0
    carry = b""
    try:
        with _open_after_bom(path) as f:
            base = f.tell()
            at_eof = False
            while not at_eof:
                _raise_if_cancelled(cancel_event)
                chunk = f.read(chunk_size)
                if chunk:
                    data = carry + chunk
                elif carry:
                    data = carry + b"\n"  # the last line has no line end
                    at_eof = True
                else:
                    break
                size = len(data)
                arr = pa.Array.from_buffers(pa.uint8(), size, [None, pa.py_buffer(data)])
                line_ends = pc.indices_nonzero(pc.is_in(arr, value_set=ends))
                if len(line_ends) == 0:
                    carry = data
                    continue
                starts = pa.concat_arrays(
                    [pa.array([0], pa.uint64()), pc.add(line_ends[:-1], pa.scalar(1, pa.uint64()))]
                )
                lengths = pc.subtract(line_ends, starts)
                idx = pc.filter(starts, pc.greater_equal(lengths, k))
                for j in range(k):
                    if len(idx) == 0:
                        break
                    idx = pc.filter(idx, pc.is_in(pc.take(arr, pc.add(idx, pa.scalar(j, pa.uint64()))), value_set=wanted))
                complete = line_ends[len(line_ends) - 1].as_py() + 1
                if has_quotes:
                    pos = 0
                    quote_count = inside
                    for s in idx.to_pylist():
                        quote_count += data.count(b'"', pos, s)
                        pos = s
                        if quote_count % 2 == 0:
                            offsets.append(base + s)
                    inside = (inside + data.count(b'"', 0, complete)) % 2
                else:
                    offsets.extend(base + s for s in idx.to_pylist())
                base += complete
                carry = data[complete:]
    except OSError as exc:
        raise _read_error(path.name, exc) from exc
    return offsets


def _widest_record_at(
    path: Path,
    delimiter: str,
    offsets: list[int],
    cancel_event: Optional[threading.Event],
) -> int:
    """Width of the widest kept record among the records that start at the given offsets.

    Each record is parsed with Python's csv module with the old importer's settings
    (strict) and judged by the old rule: all-empty records are skipped.
    """
    widest = 0
    with _fi._CSV_FIELD_LIMIT_LOCK:
        old_limit = csv.field_size_limit()
        csv.field_size_limit(_fi.MAX_SOURCE_BYTES)
        try:
            with open(path, "rb") as raw:
                for count, offset in enumerate(offsets):
                    if count % 1000 == 0:
                        _raise_if_cancelled(cancel_event)
                    raw.seek(offset)
                    text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
                    try:
                        record = next(csv.reader(text, delimiter=delimiter, strict=True), [])
                    finally:
                        text.detach()
                    if _is_empty_record(record):
                        continue
                    _check_column_limit(len(record))
                    widest = max(widest, len(record))
        except csv.Error as exc:
            raise FileImportError(f"Could not parse {path.name} as CSV: {exc}") from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise FileImportError(f"Could not read {path.name}: {exc}.") from exc
        finally:
            csv.field_size_limit(old_limit)
    return widest


def _measure_width(
    conn: Any,
    escaped_path: str,
    escaped_delim: str,
    tiers: tuple[int, ...],
    path: Path,
    delimiter: str,
    cancel_event: Optional[threading.Event],
    *,
    structure_exact: bool = False,
    has_quotes: bool = True,
    scan_chunk_size: int = _1MB,
) -> int:
    """Widest kept record (a record is kept unless every cell is empty).

    Reads with a small schema first. A schema of n columns shows a record's first
    n cells. If a KEPT record (one with a non-empty visible cell) fills the last
    schema column it may be wider, so the pre-pass repeats with the next, bigger
    schema.

    A record that fills the last schema column while all its visible cells are empty
    (",,,,,,,,,,,,,,,,,x" through a 17 column schema) cannot be judged by DuckDB: it
    is wider than the schema if a later cell holds data. That test does not use the
    all-empty filter. Such records are found from the raw bytes (only records that
    begin with n empty cells) and judged exactly by Python's csv module, which costs
    almost nothing unless the file really has them. A file whose line structure is not
    proven exact is judged by a full Python pass instead.
    """
    last = len(tiers) - 1
    for index, n in enumerate(tiers):
        empty = _empty_cells_sql(n)
        reach = " ".join(f"WHEN c{i} IS NOT NULL THEN {i + 1}" for i in range(n - 1, -1, -1))
        query = (
            f"SELECT max(CASE WHEN NOT ({empty}) THEN CASE {reach} ELSE 0 END END), "
            f"bool_or(c{n - 1} IS NOT NULL), "
            f"bool_or(c{n - 1} IS NOT NULL AND NOT ({empty})) "
            f"FROM {_read_csv_sql(escaped_path, escaped_delim, n)}"
        )
        width, any_full, kept_full = conn.execute(query).fetchone()
        if kept_full:
            if index == last:
                _check_column_limit(n)  # a kept record reaches the limit + 1 column
                raise ValueError("The last width tier must be larger than the column limit.")
            continue
        width = width or 0
        if not any_full:
            return width
        # Only all-empty-looking records reach the last schema column: judge them exactly.
        if structure_exact:
            offsets = _wide_candidate_offsets(
                path, delimiter, n, has_quotes, cancel_event, scan_chunk_size
            )
            return max(width, _widest_record_at(path, delimiter, offsets, cancel_event))
        return max(width, _python_kept_width(path, delimiter, cancel_event))
    return 0


def _read_first_kept_record(
    conn: Any,
    escaped_path: str,
    escaped_delim: str,
    tiers: tuple[int, ...],
) -> Optional[tuple[list[str], bool]]:
    """First kept record when the file has a header: (cells, is_all_empty) or None.

    The first record is kept when it has any non-empty cell or more than one cell
    (a delimiter-only record supplies blank header names). Records before it
    are skipped however many there are.
    """
    sizes: list[int] = []
    for t in tiers:
        size = max(t, 2)
        if size not in sizes:
            sizes.append(size)
    for index, n in enumerate(sizes):
        select = ", ".join(f"c{i}" for i in range(n))
        query = (
            f"SELECT {select} FROM {_read_csv_sql(escaped_path, escaped_delim, n)} "
            f"WHERE c1 IS NOT NULL OR NOT ({_empty_cells_sql(n)}) LIMIT 1"
        )
        row = conn.execute(query).fetchone()
        if row is None:
            return None
        if row[n - 1] is not None:
            if index == len(sizes) - 1:
                _check_column_limit(n)
                raise ValueError("The last width tier must be larger than the column limit.")
            continue
        width = 0
        for i in range(n - 1, -1, -1):
            if row[i] is not None:
                width = i + 1
                break
        record = list(row[:width])
        return record, all(v == "" for v in record)
    return None


def import_csv_to_store(
    store: Store,
    table: str,
    path: str | Path,
    options: dict[str, Any],
    *,
    cancel_event: Optional[threading.Event] = None,
    progress: Optional[Callable[[str], None]] = None,
    max_rows: int = 1_000_000,
    chunk_size_transcode: int = _1MB,
    scan_chunk_size: int = _8MB,
    width_tiers: tuple[int, ...] = _WIDTH_TIERS,
) -> CsvImportSummary:
    """Import a CSV file into the store, streaming rows in Arrow batches.

    Parameters
    ----------
    store:
        DuckStore instance.
    table:
        Target table name.
    path:
        Source CSV file path.
    options:
        Import options (delimiter, encoding, has_header).
    cancel_event:
        Optional threading.Event to signal cooperative cancellation.
    progress:
        Optional callback reporting progress messages.
    max_rows:
        Maximum allowed data rows (default 1,000,000).
    chunk_size_transcode:
        Chunk size for incremental transcoding (default 1 MB; tests may use small values).
    scan_chunk_size:
        Chunk size of the byte scans (line endings, marker bytes, quote check). The
        result must not depend on it; tests use tiny values to prove that.
    width_tiers:
        Increasing schema sizes of the width pre-pass; the last one must be larger
        than the column limit. Tests vary the first value.
    """
    _clean_old_temp_folders()

    display_name = Path(path).name
    src_path = Path(path).resolve()
    try:
        with open(src_path, "rb"):
            pass
    except OSError as exc:
        raise _read_error(display_name, exc) from exc

    delimiter = options.get("delimiter", ",")
    encoding = options.get("encoding", "utf-8-sig")
    has_header = options.get("has_header", True)

    sentinel_bytes = _NULL_SENTINEL.encode("utf-8")
    temp_folder: Optional[str] = None
    parse_path: Path = src_path

    try:
        # Check if transcoding is required
        needs_transcode = False
        prepend_bom = False
        actual_encoding = encoding

        if encoding in {"utf-8-sig", "utf-8"}:
            try:
                with open(src_path, "rb") as f_peek:
                    header_bytes = f_peek.read(3)
            except OSError as exc:
                raise _read_error(display_name, exc) from exc
            if encoding == "utf-8" and header_bytes == _UTF8_BOM:
                needs_transcode = True
                prepend_bom = True
        elif encoding == "utf-16":
            try:
                with open(src_path, "rb") as f_peek:
                    header_bytes = f_peek.read(2)
            except OSError as exc:
                raise _read_error(display_name, exc) from exc
            if header_bytes in (b"\xff\xfe", b"\xfe\xff"):
                actual_encoding = "utf-16"
            else:
                actual_encoding = "utf-16-le"
            needs_transcode = True
        else:
            needs_transcode = True

        if needs_transcode:
            try:
                temp_folder = tempfile.mkdtemp(prefix="analytics_studio_csv_")
            except OSError as exc:
                raise _read_error(display_name, exc) from exc
            temp_file = Path(temp_folder) / "transcoded.csv"
            _transcode_to_utf8(
                src_path,
                temp_file,
                actual_encoding,
                cancel_event=cancel_event,
                chunk_size=chunk_size_transcode,
                prepend_bom=prepend_bom,
                display_encoding=encoding,
            )
            parse_path = temp_file

        # Check line endings and sentinel on parse_path
        crlf, lone_cr, lone_lf, quotes = _check_line_endings_and_sentinel(
            parse_path, sentinel_bytes, cancel_event=cancel_event, chunk_size=scan_chunk_size
        )

        if lone_cr > 0 and (quotes > 0 or lone_lf > 0 or crlf > 0):
            raise FileImportError(
                f"The file {display_name} contains mixed or unquoted carriage-return line endings."
            )

        # Detect malformed quotes and space-before-quote (nothing to look at without a quote)
        if quotes > 0:
            notices, structure_exact = _scan_quote_structure(
                parse_path, delimiter, cancel_event=cancel_event, chunk_size=scan_chunk_size
            )
        else:
            notices, structure_exact = [], True

        # Create dedicated in-memory DuckDB connection for parsing
        cpu_count = os.cpu_count() or 4
        threads = min(4, cpu_count)

        src_conn = duckdb.connect()
        src_conn.execute("SET memory_limit = '1GB'")
        src_conn.execute(f"SET threads = {threads}")
        src_conn.execute("SET enable_progress_bar = false")

        stop_watcher = threading.Event()
        watcher_thread = None

        if cancel_event is not None:
            def _watch_cancel():
                while not stop_watcher.wait(0.05):
                    if cancel_event.is_set():
                        try:
                            src_conn.interrupt()
                        except Exception:
                            pass
                        break

            watcher_thread = threading.Thread(
                target=_watch_cancel, name="csv-import-cancel-watch", daemon=True
            )
            watcher_thread.start()

        try:
            _raise_if_cancelled(cancel_event)

            escaped_path = str(parse_path).replace("'", "''")
            escaped_delim = delimiter.replace("'", "''")

            def _handle_csv_error(exc: Exception) -> None:
                if cancel_event is not None and cancel_event.is_set():
                    raise ImportCancelledError("Import canceled.") from exc
                msg = str(exc)
                if "Invalid unicode" in msg or "not utf-8 encoded" in msg:
                    raise FileImportError(f"Could not decode {display_name} as {encoding}.") from exc
                first_line = msg.splitlines()[0] if msg else ""
                raise FileImportError(f"Could not parse {display_name} as CSV: {first_line}") from exc

            # 1. Width of the widest kept record, then the first kept record (the header).
            first_kept: Optional[tuple[list[str], bool]] = None
            try:
                max_w = _measure_width(
                    src_conn, escaped_path, escaped_delim, width_tiers,
                    parse_path, delimiter, cancel_event,
                    structure_exact=structure_exact,
                    has_quotes=quotes > 0,
                    scan_chunk_size=scan_chunk_size,
                )
                if has_header:
                    first_kept = _read_first_kept_record(
                        src_conn, escaped_path, escaped_delim, width_tiers
                    )
            except duckdb.Error as exc:
                _handle_csv_error(exc)

            header_is_blank = False
            raw_headers: list[str] = []
            if has_header and first_kept is not None:
                raw_headers, header_is_blank = first_kept
                if header_is_blank:
                    # The delimiter-only record is kept only as a header, and it widens the table.
                    max_w = max(max_w, len(raw_headers))

            if max_w == 0:
                raise FileImportError(f"{display_name} is empty and has no header row.")

            _check_column_limit(max_w)

            headers = _normalize_headers(raw_headers, max_w)
            _validate_headers_for_store(headers)
            table_col_defs = [(h, "text") for h in headers]

            # 2. Stream the data rows with a schema of exactly the final width.
            all_empty_cond = _empty_cells_sql(max_w)
            select_cols = ", ".join(f"coalesce(c{i}, '') as c{i}" for i in range(max_w))
            sql_data = (
                f"SELECT {select_cols} FROM {_read_csv_sql(escaped_path, escaped_delim, max_w)} "
                f"WHERE NOT ({all_empty_cond})"
            )
            if has_header and not header_is_blank:
                # The header is the first non-empty record, so it is the first row of this stream.
                sql_data += " OFFSET 1"

            try:
                reader = src_conn.execute(sql_data).to_arrow_reader(_BATCH_SIZE)
            except Exception as exc:
                _handle_csv_error(exc)

            def batch_generator():
                try:
                    for batch in reader:
                        _raise_if_cancelled(cancel_event)
                        renamed = pa.RecordBatch.from_arrays(batch.columns, names=headers)
                        yield renamed
                except duckdb.Error as exc:
                    _handle_csv_error(exc)
                finally:
                    try:
                        reader.close()
                    except Exception:
                        pass

            # create_table_from_arrow into store
            row_count = store.create_table_from_arrow(
                table,
                table_col_defs,
                batch_generator(),
                cancel_event=cancel_event,
                progress=progress,
                max_rows=max_rows,
            )

            # Build source_id using header-only ImportCandidate
            candidate = ImportCandidate("csv", headers, [], options, [])
            source_id = candidate.source_id or ""

            return CsvImportSummary(
                headers=headers,
                row_count=row_count,
                source_id=source_id,
                notices=notices,
            )

        finally:
            stop_watcher.set()
            if watcher_thread is not None:
                watcher_thread.join(timeout=1.0)
            try:
                src_conn.close()
            except Exception:
                pass

    finally:
        if temp_folder is not None and os.path.isdir(temp_folder):
            try:
                shutil.rmtree(temp_folder, ignore_errors=True)
            except Exception:
                pass
