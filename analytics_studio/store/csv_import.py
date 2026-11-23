"""Streaming CSV importer into DuckStore.

This module parses delimited text (CSV, TSV, etc.) into DuckStore using a
dedicated in-memory DuckDB reader session and PyArrow batches. Python performs
no per-cell work on the data rows.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass
import glob
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
    """Delete leftover temporary CSV transcode folders older than 1 day."""
    try:
        tmp_base = tempfile.gettempdir()
        cutoff = time.time() - 86400
        for folder in glob.glob(os.path.join(tmp_base, "analytics_studio_csv_*")):
            try:
                if os.path.isdir(folder) and os.path.getmtime(folder) < cutoff:
                    shutil.rmtree(folder, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass


def _check_line_endings_and_sentinel(
    path: Path, sentinel_bytes: bytes, chunk_size: int = _8MB
) -> tuple[int, int, int, int]:
    """Scan raw bytes in 8 MB chunks to count EOL markers, quotes, and check sentinel."""
    crlf = 0
    cr = 0
    lf = 0
    quotes = 0
    prev_last_byte = b""

    with open(path, "rb") as f:
        while True:
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

    lone_cr = cr - crlf
    lone_lf = lf - crlf
    return crlf, lone_cr, lone_lf, quotes


def _detect_malformed_quotes(
    path: Path, delimiter: str, chunk_size: int = _1MB
) -> list[str]:
    """Detect unterminated EOF quote or text immediately following a closing quote."""
    delim_bytes = delimiter.encode("utf-8")
    in_quotes = False
    just_closed = False
    has_unterminated = False
    has_text_after_quote = False

    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            i = 0
            n = len(chunk)
            while i < n:
                b = chunk[i : i + 1]
                if b == b'"':
                    if in_quotes:
                        if i + 1 < n:
                            next_b = chunk[i + 1 : i + 2]
                        else:
                            pos = f.tell()
                            next_b = f.read(1)
                            f.seek(pos)
                        if next_b == b'"':
                            i += 2
                            continue
                        else:
                            in_quotes = False
                            just_closed = True
                            i += 1
                            continue
                    else:
                        in_quotes = True
                        just_closed = False
                        i += 1
                        continue
                else:
                    if just_closed:
                        if b in (delim_bytes, b"\r", b"\n"):
                            just_closed = False
                        else:
                            has_text_after_quote = True
                            just_closed = False
                    i += 1

    if in_quotes:
        has_unterminated = True

    notices: list[str] = []
    if has_unterminated:
        notices.append(f"The file {path.name} contains an unterminated quote at end of file; parsed leniently.")
    if has_text_after_quote:
        notices.append(f"The file {path.name} contains unescaped text following a closing quote; parsed leniently.")
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
    if not src_path.is_file():
        raise FileImportError(f"File not found: {src_path}")

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
        if encoding in {"utf-8-sig", "utf-8"}:
            with open(src_path, "rb") as f_peek:
                header_bytes = f_peek.read(3)
            has_bom = header_bytes == b"\xef\xbb\xbf"
            if encoding == "utf-8" and has_bom:
                needs_transcode = True
                prepend_bom = True
            elif encoding == "utf-8-sig" and has_bom:
                needs_transcode = False
            else:
                needs_transcode = False
        else:
            needs_transcode = True

        if needs_transcode:
            temp_folder = tempfile.mkdtemp(prefix="analytics_studio_csv_")
            temp_file = Path(temp_folder) / "transcoded.csv"
            _transcode_to_utf8(
                src_path,
                temp_file,
                encoding,
                cancel_event=cancel_event,
                chunk_size=chunk_size_transcode,
                prepend_bom=prepend_bom,
            )
            parse_path = temp_file

        # Check line endings and sentinel on parse_path
        crlf, lone_cr, lone_lf, quotes = _check_line_endings_and_sentinel(
            parse_path, sentinel_bytes
        )

        if lone_cr > 0 and (quotes > 0 or lone_lf > 0 or crlf > 0):
            raise FileImportError(
                f"The file {src_path.name} contains mixed or unquoted carriage-return line endings."
            )

        # Detect malformed quotes
        notices = _detect_malformed_quotes(parse_path, delimiter)

        # Create dedicated in-memory DuckDB connection for parsing
        cpu_count = os.cpu_count() or 4
        threads = min(4, cpu_count)

        src_conn = duckdb.connect()
        src_conn.execute("SET memory_limit = '1GB'")
        src_conn.execute(f"SET threads = {threads}")

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

            col_defs = "{" + ",".join(f"'c{i}':'VARCHAR'" for i in range(_NC)) + "}"
            escaped_path = str(parse_path).replace("'", "''")
            escaped_delim = delimiter.replace("'", "''")

            # 1. Inspect first batch to find first kept record
            sql_head = (
                f"SELECT * FROM read_csv('{escaped_path}', all_varchar=true, header=false, "
                f"delim='{escaped_delim}', quote='\"', escape='\"', strict_mode=false, "
                f"null_padding=true, auto_detect=false, parallel=false, "
                f"nullstr='{_NULL_SENTINEL}', encoding='utf-8', max_line_size=16000000, "
                f"columns={col_defs}) LIMIT 100"
            )

            try:
                head_rows = src_conn.execute(sql_head).fetchall()
            except Exception as exc:
                if cancel_event is not None and cancel_event.is_set():
                    raise ImportCancelledError("Import canceled.") from exc
                raise FileImportError(f"Could not parse {src_path.name} as CSV: {exc}") from exc

            first_kept_rec: Optional[list[str]] = None
            first_kept_is_blank_header = False

            for r in head_rows:
                non_nulls = [i + 1 for i, v in enumerate(r) if v is not None]
                w = max(non_nulls, default=0)
                rec = list(r[:w])
                is_empty = all(v == "" for v in rec)
                if has_header and len(rec) > 1 and is_empty:
                    first_kept_rec = rec
                    first_kept_is_blank_header = True
                    break
                elif not is_empty:
                    first_kept_rec = rec
                    break

            # 2. Width pre-pass query over the file
            all_empty_cond = " AND ".join(f"(c{i} IS NULL OR c{i} = '')" for i in range(_NC))
            w_cases = " ".join(f"WHEN c{i} IS NOT NULL THEN {i + 1}" for i in range(_NC - 1, -1, -1))

            sql_width = (
                f"SELECT max(CASE {w_cases} ELSE 0 END) "
                f"FROM read_csv('{escaped_path}', all_varchar=true, header=false, "
                f"delim='{escaped_delim}', quote='\"', escape='\"', strict_mode=false, "
                f"null_padding=true, auto_detect=false, parallel=false, "
                f"nullstr='{_NULL_SENTINEL}', encoding='utf-8', max_line_size=16000000, "
                f"columns={col_defs}) WHERE NOT ({all_empty_cond})"
            )

            try:
                max_w_res = src_conn.execute(sql_width).fetchone()
                max_w = (max_w_res[0] if max_w_res and max_w_res[0] is not None else 0)
            except Exception as exc:
                if cancel_event is not None and cancel_event.is_set():
                    raise ImportCancelledError("Import canceled.") from exc
                raise FileImportError(f"Could not parse {src_path.name} as CSV: {exc}") from exc

            if first_kept_is_blank_header:
                max_w = max(max_w, len(first_kept_rec))

            if max_w == 0:
                raise FileImportError(f"{src_path.name} is empty and has no header row.")

            if max_w > MAX_COLUMNS:
                _check_column_limit(max_w)

            raw_headers = (first_kept_rec if first_kept_rec is not None else []) if has_header else []
            headers = _normalize_headers(raw_headers, max_w)
            table_col_defs = [(h, "text") for h in headers]

            # 3. Stream data rows using to_arrow_reader(50_000)
            select_cols = ", ".join(f"coalesce(c{i}, '') as c{i}" for i in range(max_w))

            if has_header:
                if first_kept_is_blank_header:
                    sql_data = f"""
                    WITH raw_rows AS (
                      SELECT row_number() OVER () as __file_rn, *
                      FROM read_csv('{escaped_path}', all_varchar=true, header=false,
                                    delim='{escaped_delim}', quote='\"', escape='\"', strict_mode=false,
                                    null_padding=true, auto_detect=false, parallel=false,
                                    nullstr='{_NULL_SENTINEL}', encoding='utf-8', max_line_size=16000000,
                                    columns={col_defs})
                    )
                    SELECT {select_cols}
                    FROM raw_rows
                    WHERE __file_rn > 1 AND NOT ({all_empty_cond})
                    """
                else:
                    sql_data = f"""
                    WITH raw_rows AS (
                      SELECT *
                      FROM read_csv('{escaped_path}', all_varchar=true, header=false,
                                    delim='{escaped_delim}', quote='\"', escape='\"', strict_mode=false,
                                    null_padding=true, auto_detect=false, parallel=false,
                                    nullstr='{_NULL_SENTINEL}', encoding='utf-8', max_line_size=16000000,
                                    columns={col_defs})
                    ),
                    filtered_numbered AS (
                      SELECT row_number() OVER () as __kept_rn, *
                      FROM raw_rows
                      WHERE NOT ({all_empty_cond})
                    )
                    SELECT {select_cols}
                    FROM filtered_numbered
                    WHERE __kept_rn > 1
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
                if cancel_event is not None and cancel_event.is_set():
                    raise ImportCancelledError("Import canceled.") from exc
                raise FileImportError(f"Could not parse {src_path.name} as CSV: {exc}") from exc

            def batch_generator():
                try:
                    for batch in reader:
                        if cancel_event is not None and cancel_event.is_set():
                            raise ImportCancelledError("Import canceled.")
                        # Rename batch column names from c0..c(N-1) to final headers
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
