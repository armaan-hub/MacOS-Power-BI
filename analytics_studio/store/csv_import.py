"""Streaming CSV importer into DuckStore.

This module parses delimited text (CSV, TSV, etc.) into DuckStore using a
dedicated in-memory DuckDB reader session and PyArrow batches. Python performs
no per-cell work on the data rows.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Any, Callable, Optional

import duckdb
import pyarrow as pa

from analytics_studio.file_import import (
    FileImportError,
    ImportCancelledError,
    ImportCandidate,
    MAX_COLUMNS,
    _check_column_limit,
    _normalize_headers,
)
from analytics_studio.store.base import Store

_NULL_SENTINEL = "\x01NULL\x01"
_NC = 513  # 512 + 1 to detect over-limit column counts
_BATCH_SIZE = 50_000
_8MB = 8 * 1024 * 1024
_1MB = 1024 * 1024


@dataclass
class CsvImportSummary:
    headers: list[str]
    row_count: int
    source_id: str
    notices: list[str]


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
    """Scan raw bytes in 8 MB chunks to count EOL markers, quotes, and check sentinel."""
    crlf = 0
    cr = 0
    lf = 0
    quotes = 0
    prev_last_byte = b""

    try:
        with open(path, "rb") as f:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ImportCancelledError("Import canceled.")
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                if sentinel_bytes in chunk:
                    raise FileImportError(
                        f"The file {path.name} contains internal sentinel byte sequences that cannot be preserved."
                    )
                quotes += chunk.count(b'"')
                cr += chunk.count(b"\r")
                lf += chunk.count(b"\n")
                crlf += chunk.count(b"\r\n")
                if prev_last_byte == b"\r" and chunk.startswith(b"\n"):
                    crlf += 1
                prev_last_byte = chunk[-1:]
    except OSError as exc:
        raise FileImportError(f"Could not read {path.name}: {exc.strerror or exc}.") from exc

    lone_cr = cr - crlf
    lone_lf = lf - crlf
    return crlf, lone_cr, lone_lf, quotes


def _detect_malformed_quotes_and_space_before_quote(
    path: Path,
    delimiter: str,
    cancel_event: Optional[threading.Event] = None,
    chunk_size: int = _8MB,
) -> list[str]:
    """Detect space-before-quote (refusal) and malformed quotes (lenient notices)."""
    delim_byte = ord(delimiter.encode("utf-8"))
    quote_byte = ord('"')
    cr_byte = ord("\r")
    lf_byte = ord("\n")
    space_byte = ord(" ")

    # States:
    # 0 = AT_FIELD_START
    # 1 = IN_FIELD_LEADING_SPACES
    # 2 = IN_UNQUOTED_FIELD
    # 3 = IN_QUOTED_FIELD
    # 4 = AFTER_CLOSING_QUOTE
    state = 0

    has_unterminated = False
    has_text_after_quote = False

    line_number = 1
    prev_b = None

    try:
        with open(path, "rb") as f:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ImportCancelledError("Import canceled.")
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                i = 0
                n = len(chunk)
                while i < n:
                    b = chunk[i]
                    if b == lf_byte:
                        if prev_b != cr_byte:
                            line_number += 1
                    elif b == cr_byte:
                        line_number += 1

                    if state == 0:  # AT_FIELD_START
                        if b == space_byte:
                            state = 1
                        elif b == quote_byte:
                            state = 3
                        elif b == delim_byte or b in (cr_byte, lf_byte):
                            state = 0
                        else:
                            state = 2
                    elif state == 1:  # IN_FIELD_LEADING_SPACES
                        if b == space_byte:
                            pass
                        elif b == quote_byte:
                            raise FileImportError(
                                f"Line {line_number} has a space before a quote; "
                                f"the large-file importer cannot read it the same way as the normal importer. "
                                f"Remove the space or the quote."
                            )
                        elif b == delim_byte or b in (cr_byte, lf_byte):
                            state = 0
                        else:
                            state = 2
                    elif state == 2:  # IN_UNQUOTED_FIELD
                        if b == delim_byte or b in (cr_byte, lf_byte):
                            state = 0
                    elif state == 3:  # IN_QUOTED_FIELD
                        if b == quote_byte:
                            if i + 1 < n:
                                next_b = chunk[i + 1]
                            else:
                                pos = f.tell()
                                next_bytes = f.read(1)
                                f.seek(pos)
                                next_b = next_bytes[0] if next_bytes else None
                            if next_b == quote_byte:
                                i += 1  # Skip escaped quote
                            else:
                                state = 4
                    elif state == 4:  # AFTER_CLOSING_QUOTE
                        if b == delim_byte or b in (cr_byte, lf_byte):
                            state = 0
                        else:
                            has_text_after_quote = True
                            state = 2

                    prev_b = b
                    i += 1
    except OSError as exc:
        raise FileImportError(f"Could not read {path.name}: {exc.strerror or exc}.") from exc

    if state == 3:
        has_unterminated = True

    notices: list[str] = []
    if has_unterminated:
        notices.append(
            f"The file {path.name} contains an unterminated quote at end of file; parsed leniently."
        )
    if has_text_after_quote:
        notices.append(
            f"The file {path.name} contains unescaped text following a closing quote; parsed leniently."
        )
    return notices


def _transcode_to_utf8(
    src_path: Path,
    dest_path: Path,
    encoding: str,
    cancel_event: Optional[threading.Event] = None,
    chunk_size: int = _1MB,
    prepend_bom: bool = False,
) -> None:
    """Stream chunks through an incremental decoder into a UTF-8 temp file."""
    try:
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    except LookupError as exc:
        raise FileImportError(f"Unsupported text encoding {encoding!r}.") from exc

    try:
        with open(src_path, "rb") as f_in, open(dest_path, "wb") as f_out:
            if prepend_bom:
                f_out.write(b"\xef\xbb\xbf")
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise ImportCancelledError("Import canceled.")
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
        raise FileImportError(f"Could not decode {src_path.name} as {encoding}.") from exc
    except OSError as exc:
        raise FileImportError(f"Could not read {src_path.name}: {exc.strerror or exc}.") from exc


def _validate_headers_for_store(headers: list[str]) -> None:
    """Validate headers before transaction starts per Store rules."""
    seen_ci: set[str] = set()
    for h in headers:
        if (
            h.startswith("__")
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in h)
        ):
            raise FileImportError(
                f"Column name {h!r} cannot be used by the large-file store: "
                f"names must be unique ignoring letter case, must not contain "
                f"control characters (such as a line break) and must not start with '__'."
            )
        h_ci = h.lower()
        if h_ci in seen_ci:
            raise FileImportError(
                f"Column name {h!r} cannot be used by the large-file store: "
                f"names must be unique ignoring letter case, must not contain "
                f"control characters (such as a line break) and must not start with '__'."
            )
        seen_ci.add(h_ci)


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
    """
    _clean_old_temp_folders()

    src_path = Path(path).resolve()
    try:
        src_path.stat()
    except OSError as exc:
        raise FileImportError(f"Could not read {src_path.name}: {exc.strerror or exc}.") from exc

    if not src_path.is_file():
        raise FileImportError(f"{src_path.name} is not a regular file.")

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
                raise FileImportError(f"Could not read {src_path.name}: {exc.strerror or exc}.") from exc
            has_bom = header_bytes == b"\xef\xbb\xbf"
            if encoding == "utf-8" and has_bom:
                needs_transcode = True
                prepend_bom = True
            elif encoding == "utf-8-sig" and has_bom:
                needs_transcode = False
            else:
                needs_transcode = False
        elif encoding == "utf-16":
            try:
                with open(src_path, "rb") as f_peek:
                    header_bytes = f_peek.read(2)
            except OSError as exc:
                raise FileImportError(f"Could not read {src_path.name}: {exc.strerror or exc}.") from exc
            if header_bytes in (b"\xff\xfe", b"\xfe\xff"):
                actual_encoding = "utf-16"
            else:
                actual_encoding = "utf-16-le"
            needs_transcode = True
        else:
            needs_transcode = True

        if needs_transcode:
            temp_folder = tempfile.mkdtemp(prefix="analytics_studio_csv_")
            temp_file = Path(temp_folder) / "transcoded.csv"
            _transcode_to_utf8(
                src_path,
                temp_file,
                actual_encoding,
                cancel_event=cancel_event,
                chunk_size=chunk_size_transcode,
                prepend_bom=prepend_bom,
            )
            parse_path = temp_file

        # Check line endings and sentinel on parse_path
        crlf, lone_cr, lone_lf, quotes = _check_line_endings_and_sentinel(
            parse_path, sentinel_bytes, cancel_event=cancel_event
        )

        if lone_cr > 0 and (quotes > 0 or lone_lf > 0 or crlf > 0):
            raise FileImportError(
                f"The file {src_path.name} contains mixed or unquoted carriage-return line endings."
            )

        # Detect malformed quotes and space-before-quote
        if quotes > 0:
            notices = _detect_malformed_quotes_and_space_before_quote(
                parse_path, delimiter, cancel_event=cancel_event
            )
        else:
            notices = []

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
                while not stop_watcher.is_set():
                    if cancel_event.is_set():
                        try:
                            src_conn.interrupt()
                        except Exception:
                            pass
                        break
                    time.sleep(0.05)

            watcher_thread = threading.Thread(target=_watch_cancel, daemon=True)
            watcher_thread.start()

        try:
            if cancel_event is not None and cancel_event.is_set():
                raise ImportCancelledError("Import canceled.")

            escaped_path = str(parse_path).replace("'", "''")
            escaped_delim = delimiter.replace("'", "''")

            # 1. Tiered Width Pre-pass
            def _width(n: int) -> int:
                cd = "{" + ",".join(f"'c{i}':'VARCHAR'" for i in range(n)) + "}"
                ae = " AND ".join(f"(c{i} IS NULL OR c{i} = '')" for i in range(n))
                wc = " ".join(f"WHEN c{i} IS NOT NULL THEN {i + 1}" for i in range(n - 1, -1, -1))
                q = (
                    f"SELECT max(CASE {wc} ELSE 0 END) "
                    f"FROM read_csv('{escaped_path}', all_varchar=true, header=false, "
                    f"delim='{escaped_delim}', quote='\"', escape='\"', strict_mode=false, "
                    f"null_padding=true, auto_detect=false, parallel=false, "
                    f"nullstr='{_NULL_SENTINEL}', encoding='utf-8', max_line_size=16000000, "
                    f"columns={cd}) WHERE NOT ({ae})"
                )
                r = src_conn.execute(q).fetchone()
                return r[0] if r and r[0] is not None else 0

            def _handle_csv_error(exc: Exception) -> None:
                if cancel_event is not None and cancel_event.is_set():
                    raise ImportCancelledError("Import canceled.") from exc
                msg = str(exc)
                if "Invalid unicode" in msg or "not utf-8 encoded" in msg:
                    raise FileImportError(f"Could not decode {src_path.name} as {encoding}.") from exc
                first_line = msg.splitlines()[0] if msg else ""
                raise FileImportError(f"Could not parse {src_path.name} as CSV: {first_line}") from exc

            try:
                max_w = _width(17)
                if max_w >= 17:
                    max_w = _width(_NC)
            except Exception as exc:
                _handle_csv_error(exc)

            # 2. Inspect first kept records using Arrow reader stream
            def _get_head_info():
                def _try_read_head(num_cols: int):
                    cd = "{" + ",".join(f"'c{i}':'VARCHAR'" for i in range(num_cols)) + "}"
                    sql_head = (
                        f"SELECT * FROM read_csv('{escaped_path}', all_varchar=true, header=false, "
                        f"delim='{escaped_delim}', quote='\"', escape='\"', strict_mode=false, "
                        f"null_padding=true, auto_detect=false, parallel=false, "
                        f"nullstr='{_NULL_SENTINEL}', encoding='utf-8', max_line_size=16000000, "
                        f"columns={cd})"
                    )
                    rdr = src_conn.execute(sql_head).to_arrow_reader(1024)
                    file_rn = 0
                    first_rec = None
                    first_rn = None
                    first_is_bh = False
                    second_rn = None
                    needs_wider = False

                    try:
                        for batch in rdr:
                            if cancel_event is not None and cancel_event.is_set():
                                raise ImportCancelledError("Import canceled.")
                            cols_data = [batch.column(c).to_pylist() for c in range(batch.num_columns)]
                            batch_len = batch.num_rows
                            for row_idx in range(batch_len):
                                file_rn += 1
                                r = [cols_data[c][row_idx] for c in range(batch.num_columns)]
                                w = 0
                                for col_idx in range(len(r) - 1, -1, -1):
                                    if r[col_idx] is not None:
                                        w = col_idx + 1
                                        break
                                rec = r[:w]
                                if w == num_cols and num_cols < _NC:
                                    needs_wider = True
                                    break
                                is_empty = all(v == "" for v in rec)

                                if first_rec is None:
                                    if has_header and len(rec) > 1 and is_empty:
                                        first_rec = rec
                                        first_rn = file_rn
                                        first_is_bh = True
                                    elif not is_empty:
                                        first_rec = rec
                                        first_rn = file_rn
                                else:
                                    if not is_empty:
                                        second_rn = file_rn
                                        break
                            if needs_wider or (first_rec is not None and (second_rn is not None or not has_header)):
                                break
                    finally:
                        rdr.close()
                    return first_rec, first_rn, first_is_bh, second_rn, needs_wider

                first_rec, first_rn, first_is_bh, second_rn, needs_wider = _try_read_head(17)
                if needs_wider:
                    first_rec, first_rn, first_is_bh, second_rn, _ = _try_read_head(_NC)
                return first_rec, first_rn, first_is_bh, second_rn

            try:
                first_kept_rec, first_kept_rn, first_kept_is_blank_header, second_kept_rn = _get_head_info()
            except Exception as exc:
                _handle_csv_error(exc)

            if first_kept_is_blank_header:
                max_w = max(max_w, len(first_kept_rec))

            if max_w == 0:
                raise FileImportError(f"{src_path.name} is empty and has no header row.")

            if max_w > MAX_COLUMNS:
                _check_column_limit(max_w)

            raw_headers = (first_kept_rec if first_kept_rec is not None else []) if has_header else []
            headers = _normalize_headers(raw_headers, max_w)
            _validate_headers_for_store(headers)
            table_col_defs = [(h, "text") for h in headers]

            # 3. Stream data rows using exact width columns and no window functions
            col_defs = "{" + ",".join(f"'c{i}':'VARCHAR'" for i in range(max_w)) + "}"
            all_empty_cond = " AND ".join(f"(c{i} IS NULL OR c{i} = '')" for i in range(max_w))
            select_cols = ", ".join(f"coalesce(c{i}, '') as c{i}" for i in range(max_w))

            if has_header:
                min_rn = second_kept_rn if second_kept_rn is not None else (first_kept_rn + 1)
                sql_data = f"""
                WITH raw_rows AS (
                    SELECT row_number() OVER () AS __file_rn, *
                    FROM read_csv('{escaped_path}', all_varchar=true, header=false,
                                  delim='{escaped_delim}', quote='\"', escape='\"', strict_mode=false,
                                  null_padding=true, auto_detect=false, parallel=false,
                                  nullstr='{_NULL_SENTINEL}', encoding='utf-8', max_line_size=16000000,
                                  columns={col_defs})
                )
                SELECT {select_cols}
                FROM raw_rows
                WHERE __file_rn >= {min_rn} AND NOT ({all_empty_cond})
                """
            else:
                sql_data = f"""
                SELECT {select_cols}
                FROM read_csv('{escaped_path}', all_varchar=true, header=false,
                              delim='{escaped_delim}', quote='\"', escape='\"', strict_mode=false,
                              null_padding=true, auto_detect=false, parallel=false,
                              nullstr='{_NULL_SENTINEL}', encoding='utf-8', max_line_size=16000000,
                              columns={col_defs})
                WHERE NOT ({all_empty_cond})
                """

            try:
                reader = src_conn.execute(sql_data).to_arrow_reader(_BATCH_SIZE)
            except Exception as exc:
                _handle_csv_error(exc)

            def batch_generator():
                try:
                    for batch in reader:
                        if cancel_event is not None and cancel_event.is_set():
                            raise ImportCancelledError("Import canceled.")
                        renamed = pa.RecordBatch.from_arrays(batch.columns, names=headers)
                        yield renamed
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
