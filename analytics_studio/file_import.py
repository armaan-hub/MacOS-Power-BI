"""Bounded importers for local tabular files.

Parsing is deliberately independent of Qt. ``parse_file`` returns a complete
candidate; callers can show a limited preview and only install the candidate
after the user confirms it.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import io
import json
import posixpath
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any, Callable, Mapping
import zipfile
import zlib
from xml.etree import ElementTree


MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_WORKBOOK_EXPANDED_BYTES = 80 * 1024 * 1024
MAX_WORKBOOK_XML_PART_BYTES = 80 * 1024 * 1024
MAX_PARQUET_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
MAX_PARQUET_TEXT_BYTES = 80 * 1024 * 1024
MAX_SQLITE_TEXT_BYTES = 80 * 1024 * 1024
PARQUET_BATCH_SIZE = 1024
MAX_DATA_ROWS = 100_000
MAX_COLUMNS = 512
MAX_CELLS = 500_000
AUTO_HEADER_PREFIX_ROWS = 64

EXCEL_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
EXCEL_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORKSHEET_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"


class FileImportError(ValueError):
    """An unsupported, malformed, or over-limit source file."""


class ImportCancelledError(FileImportError):
    """A caller canceled a local import before its candidate was complete."""


@dataclass(frozen=True)
class _ImportControl:
    cancel_event: threading.Event | None = None
    progress_callback: Callable[[str], None] | None = None

    def check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise ImportCancelledError("Import canceled.")

    def report(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)


_PROGRESS_ROW_INTERVAL = 5_000


@dataclass
class ImportCandidate:
    """A fully parsed table that has not yet been committed to the project."""

    kind: str
    headers: list[str]
    rows: list[dict[str, str]]
    options: dict[str, Any]
    notices: list[str]

    @property
    def row_count(self) -> int:
        return len(self.rows)


def kind_for_path(path: str | Path) -> str:
    """Return the importer kind for a supported suffix, case-insensitively."""
    suffix = Path(path).suffix.casefold()
    if suffix == ".csv":
        return "csv"
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return "excel"
    if suffix == ".parquet":
        return "parquet"
    if suffix in {".db", ".sqlite", ".sqlite3"}:
        return "sqlite"
    if suffix == ".json":
        return "json"
    if suffix == ".xml":
        return "xml"
    raise FileImportError(f"Unsupported file type {suffix or '(no extension)'!r}.")


def default_options(kind: str) -> dict[str, Any]:
    """Return fresh, JSON-serializable defaults for a source kind."""
    if kind == "csv":
        return {"delimiter": ",", "encoding": "utf-8-sig", "has_header": True}
    if kind == "excel":
        # ``None`` means first worksheet / first non-empty row. ``parse_file``
        # resolves these to the actual sheet and one-based row in its candidate.
        return {"sheet_name": None, "header_row": None}
    if kind in {"json", "xml", "parquet"}:
        return {}
    if kind == "sqlite":
        return {"table_name": None}
    raise FileImportError(f"Unsupported file import kind {kind!r}.")


def normalize_options(kind: str, options: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate options and return canonical values suitable for persistence."""
    if kind not in {"csv", "excel", "json", "xml", "parquet", "sqlite"}:
        raise FileImportError(f"Unsupported file import kind {kind!r}.")
    if options is None:
        supplied: dict[str, Any] = {}
    elif isinstance(options, Mapping):
        supplied = dict(options)
    else:
        raise FileImportError("Import options must be an object.")

    defaults = default_options(kind)
    unknown = sorted(map(str, set(supplied) - set(defaults)))
    if unknown:
        raise FileImportError(f"Unsupported {kind.upper()} import option(s): {', '.join(map(str, unknown))}.")
    result = {**defaults, **supplied}

    if kind == "csv":
        delimiter = result["delimiter"]
        if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter not in {",", ";", "\t", "|"}:
            raise FileImportError("Choose comma, semicolon, tab, or pipe as the CSV delimiter.")
        if not isinstance(result["encoding"], str):
            raise FileImportError("Choose a supported CSV text encoding.")
        encoding_aliases = {
            "utf-8-sig": "utf-8-sig",
            "utf-8": "utf-8",
            "utf-16": "utf-16",
            "cp1252": "cp1252",
            "windows-1252": "cp1252",
        }
        encoding = encoding_aliases.get(result["encoding"].casefold())
        if encoding is None:
            raise FileImportError("Choose UTF-8, UTF-8 with BOM, UTF-16, or Windows-1252 encoding.")
        result["encoding"] = encoding
        if not isinstance(result["has_header"], bool):
            raise FileImportError("The CSV header option must be true or false.")
    elif kind == "excel":
        sheet_name = result["sheet_name"]
        if sheet_name is not None and not isinstance(sheet_name, str):
            raise FileImportError("Choose an Excel worksheet by name.")
        header_row = result["header_row"]
        if header_row is not None and (
            not isinstance(header_row, int) or isinstance(header_row, bool) or header_row < 1
        ):
            raise FileImportError("The Excel header row must be a positive row number or automatic selection.")
    elif kind == "sqlite":
        table_name = result["table_name"]
        if table_name is not None and (
            not isinstance(table_name, str) or not table_name.strip() or "\x00" in table_name
        ):
            raise FileImportError("Choose a valid SQLite table or view name.")
    return result


def list_sqlite_tables(
    path: str | Path,
    *,
    cancel_event: threading.Event | None = None,
) -> list[str]:
    """Return user tables and views from a bounded SQLite database opened read-only."""
    control = _ImportControl(cancel_event)
    control.check_cancelled()
    source_path = Path(path).expanduser().resolve()
    database_size = _sqlite_source_size(source_path)
    if database_size > MAX_SOURCE_BYTES:
        raise FileImportError(
            f"{source_path.name} and its write-ahead log exceed the "
            f"{MAX_SOURCE_BYTES // (1024 * 1024)} MiB SQLite import limit."
        )
    connection = _open_sqlite_readonly(source_path, cancel_event)
    try:
        control.check_cancelled()
        rows = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name COLLATE NOCASE, name"
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        if cancel_event is not None and cancel_event.is_set():
            raise ImportCancelledError("Import canceled.") from exc
        raise FileImportError(f"Could not read SQLite tables from {source_path.name}: {exc}") from exc
    finally:
        connection.close()
    control.check_cancelled()
    return [str(row[0]) for row in rows]


def _sqlite_source_size(path: Path) -> int:
    """Count the database and its optional WAL file against one input limit."""
    _source_size(path)
    total = path.stat().st_size
    wal_path = Path(f"{path}-wal")
    try:
        total += wal_path.stat().st_size
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise FileImportError(f"Could not read SQLite write-ahead log {wal_path.name}: {exc}") from exc
    return total


def parse_file(
    path: str | Path,
    options: Mapping[str, Any] | None = None,
    expected_kind: str | None = None,
    *,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> ImportCandidate:
    """Parse a supported file completely without changing application state."""
    source_path = Path(path).expanduser()
    control = _ImportControl(cancel_event, progress_callback)
    control.check_cancelled()
    kind = kind_for_path(source_path)
    if expected_kind is not None and expected_kind != kind:
        if expected_kind not in {"csv", "excel", "json", "xml", "parquet", "sqlite"}:
            raise FileImportError(f"Unsupported expected file kind {expected_kind!r}.")
        raise FileImportError(
            f"The selected file is {kind.upper()}, but this action expects {expected_kind.upper()}."
        )
    normalized = normalize_options(kind, options)
    size = _source_size(source_path)
    if size > MAX_SOURCE_BYTES:
        raise FileImportError(
            f"{source_path.name} is larger than the {MAX_SOURCE_BYTES // (1024 * 1024)} MiB import limit."
        )

    control.report(f"Reading {source_path.name}…")
    control.check_cancelled()
    if kind == "csv":
        return _parse_csv(source_path, normalized, control)
    if kind == "excel":
        return _parse_excel(source_path, normalized, control)
    if kind == "json":
        return _parse_json(source_path, normalized, control)
    if kind == "parquet":
        return _parse_parquet(source_path, normalized, control)
    if kind == "sqlite":
        return _parse_sqlite(source_path, normalized, control)
    return _parse_xml(source_path, normalized, control)


def _open_sqlite_readonly(
    path: Path,
    cancel_event: threading.Event | None = None,
) -> sqlite3.Connection:
    """Open one SQLite file with writes disabled and extension loading unavailable."""
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro",
            uri=True,
            timeout=5,
        )
        connection.execute("PRAGMA query_only = ON")
        deadline = time.monotonic() + 10
        connection.set_progress_handler(
            lambda: int(
                time.monotonic() > deadline
                or (cancel_event is not None and cancel_event.is_set())
            ),
            10_000,
        )
        return connection
    except (OSError, sqlite3.DatabaseError) as exc:
        if connection is not None:
            connection.close()
        raise FileImportError(f"Could not open {path.name} as a SQLite database: {exc}") from exc


def _parse_sqlite(
    path: Path,
    options: dict[str, Any],
    control: _ImportControl | None = None,
) -> ImportCandidate:
    """Read one flat SQLite table into the text-backed local table model."""
    table_names = list_sqlite_tables(
        path, cancel_event=control.cancel_event if control is not None else None
    )
    table_name = options.get("table_name")
    if table_name is None:
        table_name = table_names[0] if table_names else None
    if table_name not in table_names:
        if not table_names:
            raise FileImportError(f"{path.name} does not contain any user tables or views.")
        raise FileImportError(f"The SQLite table or view {table_name!r} is not present in {path.name}.")

    connection = _open_sqlite_readonly(
        path, control.cancel_event if control is not None else None
    )
    try:
        escaped_table = table_name.replace('"', '""')
        cursor = connection.execute(
            f'SELECT * FROM "{escaped_table}" LIMIT ?',
            (MAX_DATA_ROWS + 1,),
        )
        description = cursor.description or ()
        raw_headers = [str(item[0]) if item[0] is not None else "" for item in description]
        width = len(raw_headers)
        if width == 0:
            raise FileImportError(f"SQLite object {table_name!r} has no columns.")
        headers = _normalize_headers(raw_headers, width)
        rows: list[dict[str, str]] = []
        rendered_bytes = 0
        for values in cursor:
            if control is not None:
                control.check_cancelled()
            row_number = len(rows) + 1
            _check_row_limit(row_number)
            _check_cell_limit(row_number, width)
            normalized_values: list[str] = []
            for value in values:
                if value is None:
                    rendered = ""
                elif isinstance(value, bytes):
                    raise FileImportError(
                        f"SQLite table {table_name!r} contains binary data; BLOB columns are not supported."
                    )
                else:
                    rendered = str(value)
                rendered_bytes += len(rendered.encode("utf-8"))
                if rendered_bytes > MAX_SQLITE_TEXT_BYTES:
                    raise FileImportError(
                        "The SQLite object exceeds the 80 MiB rendered-text import limit."
                    )
                normalized_values.append(rendered)
            rows.append(dict(zip(headers, normalized_values)))
            if control is not None and row_number % _PROGRESS_ROW_INTERVAL == 0:
                control.report(f"Read {row_number:,} SQLite rows…")
        return ImportCandidate(
            "sqlite",
            headers,
            rows,
            {"table_name": table_name},
            [],
        )
    except sqlite3.DatabaseError as exc:
        if control is not None:
            control.check_cancelled()
        raise FileImportError(f"Could not read SQLite table {table_name!r}: {exc}") from exc
    finally:
        connection.close()


def _parse_parquet(
    path: Path,
    options: dict[str, Any],
    control: _ImportControl | None = None,
) -> ImportCandidate:
    """Read a bounded, flat Parquet table into the string-based table model."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except (ImportError, OSError) as exc:
        raise FileImportError(
            "Parquet import requires PyArrow. Install the app's listed dependencies and try again."
        ) from exc

    parquet_file = None
    try:
        parquet_file = pq.ParquetFile(
            path,
            thrift_string_size_limit=MAX_SOURCE_BYTES,
            thrift_container_size_limit=MAX_CELLS,
        )
        metadata = parquet_file.metadata
        if metadata is None:
            raise FileImportError(f"{path.name} has no readable Parquet metadata.")

        declared_rows = int(metadata.num_rows)
        if declared_rows < 0:
            raise FileImportError(f"{path.name} has invalid Parquet row metadata.")
        _check_row_limit(declared_rows)
        if metadata.num_row_groups > MAX_DATA_ROWS:
            raise FileImportError(
                f"{path.name} contains more than {MAX_DATA_ROWS:,} Parquet row groups."
            )

        schema = parquet_file.schema_arrow
        raw_headers = list(schema.names)
        _check_column_limit(len(raw_headers))
        if not raw_headers:
            raise FileImportError("Parquet import requires at least one column.")
        headers = _normalize_headers(raw_headers, len(raw_headers))
        _check_cell_limit(declared_rows, len(headers))

        uncompressed_bytes = 0
        for group_index in range(metadata.num_row_groups):
            if control is not None:
                control.check_cancelled()
            group_bytes = int(metadata.row_group(group_index).total_byte_size)
            if group_bytes < 0:
                raise FileImportError(f"{path.name} has invalid Parquet row-group metadata.")
            uncompressed_bytes += group_bytes
            if uncompressed_bytes > MAX_PARQUET_UNCOMPRESSED_BYTES:
                raise FileImportError(
                    f"{path.name} expands beyond the "
                    f"{MAX_PARQUET_UNCOMPRESSED_BYTES // (1024 * 1024)} MiB Parquet data limit."
                )

        supported_type = (
            pa.types.is_null,
            pa.types.is_boolean,
            pa.types.is_integer,
            pa.types.is_floating,
            pa.types.is_decimal,
            pa.types.is_string,
            pa.types.is_large_string,
            pa.types.is_date,
            pa.types.is_time,
            pa.types.is_timestamp,
        )
        field_types = []
        for column_index, field in enumerate(schema):
            if control is not None:
                control.check_cancelled()
            data_type = field.type
            if pa.types.is_dictionary(data_type):
                data_type = data_type.value_type
            if not any(is_type(data_type) for is_type in supported_type):
                raise FileImportError(
                    f"Parquet column {headers[column_index]!r} has unsupported type "
                    f"{field.type}. Supported columns must contain scalar values; "
                    "nested and binary types are not supported."
                )
            field_types.append(data_type)

        rows: list[dict[str, str]] = []
        rendered_text_bytes = sum(len(header.encode("utf-8")) for header in headers)
        if rendered_text_bytes > MAX_PARQUET_TEXT_BYTES:
            raise FileImportError("Parquet column names exceed the converted-text result limit.")
        for batch in parquet_file.iter_batches(
            batch_size=PARQUET_BATCH_SIZE,
            use_threads=False,
        ):
            if control is not None:
                control.check_cancelled()
            if batch.num_columns != len(headers):
                raise FileImportError(f"{path.name} has inconsistent Parquet batch columns.")
            next_count = len(rows) + batch.num_rows
            _check_row_limit(next_count)
            _check_cell_limit(next_count, len(headers))

            values_by_column: list[list[str | None]] = []
            for column_index, field in enumerate(schema):
                array = batch.column(column_index)
                if pa.types.is_dictionary(array.type):
                    array = array.dictionary_decode()
                if pa.types.is_boolean(field_types[column_index]):
                    rendered = [
                        None if value is None else ("TRUE" if value else "FALSE")
                        for value in array.to_pylist()
                    ]
                else:
                    try:
                        rendered = array.cast(pa.string(), safe=True).to_pylist()
                    except Exception as exc:
                        raise FileImportError(
                            f"Could not convert Parquet column {headers[column_index]!r} "
                            f"({field.type}) to text: {exc}"
                        ) from exc

                if pa.types.is_floating(field_types[column_index]):
                    for value in rendered:
                        if value is not None and value.casefold() in {
                            "nan", "+nan", "-nan", "inf", "+inf", "-inf",
                            "infinity", "+infinity", "-infinity",
                        }:
                            raise FileImportError(
                                f"Parquet column {headers[column_index]!r} contains a non-finite number."
                            )
                for value in rendered:
                    if value is not None:
                        rendered_text_bytes += len(value.encode("utf-8"))
                        if rendered_text_bytes > MAX_PARQUET_TEXT_BYTES:
                            raise FileImportError(
                                f"Converted Parquet text exceeds the "
                                f"{MAX_PARQUET_TEXT_BYTES // (1024 * 1024)} MiB result limit."
                            )
                values_by_column.append(rendered)

            for row_index in range(batch.num_rows):
                row_number = len(rows) + 1
                if control is not None:
                    if row_number % _PROGRESS_ROW_INTERVAL == 0:
                        control.report(f"Read {row_number:,} Parquet rows…")
                    control.check_cancelled()
                rows.append({
                    header: ("" if values_by_column[column_index][row_index] is None
                             else values_by_column[column_index][row_index])
                    for column_index, header in enumerate(headers)
                })

        if len(rows) != declared_rows:
            raise FileImportError(
                f"{path.name} declares {declared_rows:,} rows but yielded {len(rows):,}."
            )
        notices = [
            "Parquet scalar values are converted to text; nulls become blank and the source types are not retained."
        ]
        return ImportCandidate("parquet", headers, rows, options, notices)
    except FileImportError:
        raise
    except Exception as exc:
        raise FileImportError(f"Could not read {path.name} as Parquet: {exc}") from exc
    finally:
        if parquet_file is not None:
            parquet_file.close()


def list_excel_sheets(path: str | Path) -> list[str]:
    """List readable worksheet names for the import-options dialog."""
    source_path = Path(path).expanduser()
    if kind_for_path(source_path) != "excel":
        raise FileImportError("Choose an .xls, .xlsx, or .xlsm workbook.")
    if _source_size(source_path) > MAX_SOURCE_BYTES:
        raise FileImportError(
            f"{source_path.name} is larger than the {MAX_SOURCE_BYTES // (1024 * 1024)} MiB import limit."
        )
    if source_path.suffix.casefold() == ".xls":
        xlrd, book = _open_legacy_excel(source_path)
        try:
            sheets = book.sheet_names()
            if not sheets:
                raise FileImportError(f"{source_path.name} does not contain a worksheet.")
            return sheets
        finally:
            book.release_resources()
    try:
        with zipfile.ZipFile(source_path) as workbook:
            _, sheets = _read_excel_sheet_index(workbook, source_path.name)
            return [name for name, _ in sheets]
    except FileImportError:
        raise
    except (
        zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError, RuntimeError,
        ValueError, IndexError, EOFError, zlib.error, NotImplementedError,
    ) as exc:
        raise FileImportError("This is not a readable Excel .xlsx/.xlsm workbook.") from exc


def recommend_excel_sheet(path: str | Path) -> str:
    """Recommend the worksheet with the strongest tabular data for import."""
    source_path = Path(path).expanduser()
    if kind_for_path(source_path) != "excel":
        raise FileImportError("Choose an .xls, .xlsx, or .xlsm workbook.")
    if _source_size(source_path) > MAX_SOURCE_BYTES:
        raise FileImportError(
            f"{source_path.name} is larger than the {MAX_SOURCE_BYTES // (1024 * 1024)} MiB import limit."
        )
    if source_path.suffix.casefold() == ".xls":
        xlrd, book = _open_legacy_excel(source_path)
        try:
            return _recommend_legacy_excel_sheet(xlrd, book)
        finally:
            book.release_resources()
    try:
        with zipfile.ZipFile(source_path) as workbook:
            names, sheets = _read_excel_sheet_index(workbook, source_path.name)
            shared_strings = _read_excel_shared_strings(workbook, names)
            main_ns = f"{{{EXCEL_MAIN_NS}}}"
            date_styles, time_styles = _read_excel_styles(workbook, main_ns, names)
            workbook_root = ElementTree.fromstring(
                _read_zip_part_bounded(workbook, workbook.getinfo("xl/workbook.xml"))
            )
            workbook_properties = workbook_root.find(f"{main_ns}workbookPr")
            date_1904 = bool(
                workbook_properties is not None
                and workbook_properties.attrib.get("date1904", "0").casefold() in {"1", "true"}
            )
            return _recommend_excel_sheet_from_parts(
                workbook, sheets, shared_strings, date_styles, time_styles, date_1904, main_ns
            )
    except FileImportError:
        raise
    except (
        zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError, RuntimeError,
        ValueError, IndexError, EOFError, zlib.error, NotImplementedError,
        ) as exc:
        raise FileImportError("This is not a readable Excel .xlsx/.xlsm workbook.") from exc


def inspect_excel_options(
    path: str | Path,
    preferred_sheet: str | None = None,
    *,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[list[str], str]:
    """Read worksheet choices and a recommendation in one cancellable pass."""
    control = _ImportControl(cancel_event, progress_callback)
    control.check_cancelled()
    source_path = Path(path).expanduser()
    if kind_for_path(source_path) != "excel":
        raise FileImportError("Choose an .xls, .xlsx, or .xlsm workbook.")
    if _source_size(source_path) > MAX_SOURCE_BYTES:
        raise FileImportError(
            f"{source_path.name} is larger than the {MAX_SOURCE_BYTES // (1024 * 1024)} MiB import limit."
        )

    if source_path.suffix.casefold() == ".xls":
        control.report("Opening the legacy Excel workbook…")
        xlrd, book = _open_legacy_excel(source_path, cancel_event)
        try:
            control.check_cancelled()
            sheets = book.sheet_names()
            if not sheets:
                raise FileImportError(f"{source_path.name} does not contain a worksheet.")
            if preferred_sheet in sheets:
                return sheets, preferred_sheet
            control.report("Checking worksheet data to choose a preview…")
            recommendation = _recommend_legacy_excel_sheet(xlrd, book, control)
            control.check_cancelled()
            return sheets, recommendation
        finally:
            book.release_resources()

    try:
        with zipfile.ZipFile(source_path) as workbook:
            control.report("Checking workbook contents…")
            names, sheets = _read_excel_sheet_index(
                workbook, source_path.name, control
            )
            sheet_names = [name for name, _ in sheets]
            if preferred_sheet in sheet_names:
                return sheet_names, preferred_sheet

            control.report("Checking worksheet data to choose a preview…")
            main_ns = f"{{{EXCEL_MAIN_NS}}}"
            shared_strings = _read_excel_shared_strings(workbook, names, control)
            date_styles, time_styles = _read_excel_styles(
                workbook, main_ns, names, control
            )
            workbook_root = ElementTree.fromstring(
                _read_zip_part_bounded(workbook, workbook.getinfo("xl/workbook.xml"))
            )
            control.check_cancelled()
            workbook_properties = workbook_root.find(f"{main_ns}workbookPr")
            date_1904 = bool(
                workbook_properties is not None
                and workbook_properties.attrib.get("date1904", "0").casefold() in {"1", "true"}
            )
            recommendation = _recommend_excel_sheet_from_parts(
                workbook, sheets, shared_strings, date_styles, time_styles,
                date_1904, main_ns, control,
            )
            control.check_cancelled()
            return sheet_names, recommendation
    except FileImportError:
        raise
    except (
        zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError, RuntimeError,
        ValueError, IndexError, EOFError, zlib.error, NotImplementedError,
    ) as exc:
        raise FileImportError("This is not a readable Excel .xlsx/.xlsm workbook.") from exc


def _open_legacy_excel(
    path: Path,
    cancel_event: threading.Event | None = None,
) -> tuple[Any, Any]:
    """Open a capped BIFF workbook with xlrd, loaded one worksheet at a time."""
    if cancel_event is not None and cancel_event.is_set():
        raise ImportCancelledError("Import canceled.")
    try:
        import xlrd
    except (ImportError, OSError) as exc:
        raise FileImportError(
            "Legacy .xls import requires xlrd. Install the app's listed dependencies and try again."
        ) from exc
    try:
        contents = _read_source_bytes(path)
        if cancel_event is not None and cancel_event.is_set():
            raise ImportCancelledError("Import canceled.")
        book = xlrd.open_workbook(
            file_contents=contents,
            on_demand=True,
            ragged_rows=True,
        )
    except FileImportError:
        raise
    except Exception as exc:
        raise FileImportError(f"Could not read {path.name} as a legacy Excel .xls workbook: {exc}") from exc
    if cancel_event is not None and cancel_event.is_set():
        book.release_resources()
        raise ImportCancelledError("Import canceled.")
    if not book.sheet_names():
        book.release_resources()
        raise FileImportError(f"{path.name} does not contain a worksheet.")
    return xlrd, book


def _legacy_excel_sheet_quality(
    xlrd: Any,
    book: Any,
    sheet: Any,
    control: _ImportControl | None = None,
) -> tuple[tuple[int, int, int, int], int] | None:
    records: list[tuple[int, list[str]]] = []
    for row_index in range(sheet.nrows):
        if control is not None:
            control.check_cancelled()
        values = [
            _legacy_excel_cell_text(xlrd, book, sheet, row_index, column_index)
            for column_index in range(sheet.row_len(row_index))
        ]
        if any(value.strip() for value in values):
            records.append((row_index + 1, values))
            if len(records) >= AUTO_HEADER_PREFIX_ROWS:
                break
    return _excel_sheet_quality(records)


def _recommend_legacy_excel_sheet(
    xlrd: Any,
    book: Any,
    control: _ImportControl | None = None,
) -> str:
    best: tuple[tuple[int, int, int, int, int], str] | None = None
    names = book.sheet_names()
    for index, name in enumerate(names):
        if control is not None:
            control.check_cancelled()
            control.report(f"Checking worksheet {index + 1} of {len(names)}: {name}…")
        try:
            sheet = book.sheet_by_index(index)
            quality = _legacy_excel_sheet_quality(xlrd, book, sheet, control)
            if quality is not None:
                score = (*quality[0], -index)
                if best is None or score > best[0]:
                    best = (score, name)
        finally:
            book.unload_sheet(index)
    return best[1] if best is not None else names[0]


def _legacy_excel_cell_text(
    xlrd: Any,
    book: Any,
    sheet: Any,
    row_index: int,
    column_index: int,
) -> str:
    cell_type = sheet.cell_type(row_index, column_index)
    value = sheet.cell_value(row_index, column_index)
    if cell_type in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
        return ""
    if cell_type == xlrd.XL_CELL_TEXT:
        return str(value)
    if cell_type == xlrd.XL_CELL_BOOLEAN:
        return "TRUE" if value else "FALSE"
    if cell_type == xlrd.XL_CELL_ERROR:
        return xlrd.error_text_from_code.get(value, f"#ERROR({value})")
    if cell_type == xlrd.XL_CELL_DATE:
        try:
            year, month, day, hour, minute, second = xlrd.xldate_as_tuple(
                value, book.datemode
            )
            if year == month == day == 0:
                return f"{hour:02d}:{minute:02d}:{second:02d}"
            if hour or minute or second:
                return datetime(year, month, day, hour, minute, second).isoformat(
                    sep=" ", timespec="seconds"
                )
            return datetime(year, month, day).date().isoformat()
        except (OverflowError, ValueError, xlrd.xldate.XLDateError):
            # Preserve ambiguous or out-of-range date serials as their numeric value.
            pass
    if cell_type in {xlrd.XL_CELL_NUMBER, xlrd.XL_CELL_DATE}:
        try:
            number = Decimal(str(value))
        except (ArithmeticError, ValueError) as exc:
            raise FileImportError(
                f"Worksheet {sheet.name!r} contains an unreadable numeric cell."
            ) from exc
        if not number.is_finite():
            raise FileImportError(
                f"Worksheet {sheet.name!r} contains a non-finite numeric cell."
            )
        rendered = format(number, "f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    return str(value) if value is not None else ""


def _read_excel_sheet_index(
    workbook: zipfile.ZipFile,
    display_name: str,
    control: _ImportControl | None = None,
) -> tuple[set[str], list[tuple[str, str]]]:
    if control is not None:
        control.check_cancelled()
    names = _validate_workbook_archive(workbook, display_name, control)
    if control is not None:
        control.check_cancelled()
    if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
        raise FileImportError(f"{display_name} is not a readable Excel workbook.")
    main_ns = f"{{{EXCEL_MAIN_NS}}}"
    relation_id_attr = f"{{{EXCEL_REL_NS}}}id"
    workbook_root = ElementTree.fromstring(
        _read_zip_part_bounded(workbook, workbook.getinfo("xl/workbook.xml"))
    )
    relationship_root = ElementTree.fromstring(
        _read_zip_part_bounded(workbook, workbook.getinfo("xl/_rels/workbook.xml.rels"))
    )
    relationships = {
        item.attrib.get("Id", ""): item
        for item in relationship_root.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
    }
    sheets = []
    for sheet in workbook_root.findall(f"{main_ns}sheets/{main_ns}sheet"):
        if control is not None:
            control.check_cancelled()
        name = sheet.attrib.get("name", "")
        relation = relationships.get(sheet.attrib.get(relation_id_attr, ""))
        if not name or relation is None or relation.attrib.get("Type") != WORKSHEET_REL:
            continue
        if relation.attrib.get("TargetMode", "Internal").casefold() == "external":
            continue
        target = relation.attrib.get("Target", "")
        sheet_path = (
            posixpath.normpath(target.lstrip("/"))
            if target.startswith("/")
            else posixpath.normpath(posixpath.join("xl", target))
        )
        if not sheet_path.startswith("../") and sheet_path in names:
            sheets.append((name, sheet_path))
    if not sheets:
        raise FileImportError("The workbook does not contain a readable worksheet.")
    if len({name for name, _ in sheets}) != len(sheets):
        raise FileImportError("The workbook has duplicate worksheet names.")
    return names, sheets


def _read_excel_shared_strings(
    workbook: zipfile.ZipFile,
    names: set[str],
    control: _ImportControl | None = None,
) -> list[str]:
    if "xl/sharedStrings.xml" not in names:
        return []
    main_ns = f"{{{EXCEL_MAIN_NS}}}"
    strings: list[str] = []
    if control is not None:
        control.check_cancelled()
    with workbook.open("xl/sharedStrings.xml") as stream:
        for event, item in ElementTree.iterparse(stream, events=("end",)):
            if control is not None:
                control.check_cancelled()
            if event == "end" and item.tag == f"{main_ns}si":
                strings.append(
                    "".join(node.text or "" for node in item.iter(f"{main_ns}t"))
                )
                item.clear()
    return strings


def _auto_header_index(
    records: list[tuple[int, list[str]]], minimum_support_rows: int
) -> int | None:
    """Find a broad row whose populated columns recur in following records."""
    best: tuple[tuple[int, int, int, int], int] | None = None
    for index, (_, values) in enumerate(records):
        positions = [column for column, value in enumerate(values) if value.strip()]
        width = len(positions)
        if width < 2:
            continue
        following = records[index + 1:index + 6]
        overlaps = [
            sum(column < len(row) and bool(row[column].strip()) for column in positions)
            for _, row in following
        ]
        supported = [count for count in overlaps if count >= 2]
        if len(supported) < minimum_support_rows:
            continue
        score = (width, len(supported), sum(supported), -index)
        if best is None or score > best[0]:
            best = (score, index)
    return best[1] if best is not None else None


def _excel_prefix_rows(
    workbook: zipfile.ZipFile,
    sheet_path: str,
    shared_strings: list[str],
    date_styles: set[int],
    time_styles: set[int],
    date_1904: bool,
    main_ns: str,
    control: _ImportControl | None = None,
) -> list[tuple[int, list[str]]]:
    """Read a bounded worksheet prefix for header and sheet recommendations."""
    rows: list[tuple[int, list[str]]] = []
    row_tag = f"{main_ns}row"
    cell_tag = f"{main_ns}c"
    sheet_data_tag = f"{main_ns}sheetData"
    stack: list[ElementTree.Element] = []
    current_row_number: int | None = None
    current_values: dict[int, str] | None = None
    implicit_row_number = 0
    next_column = 0
    with workbook.open(sheet_path) as stream:
        for event, element in ElementTree.iterparse(stream, events=("start", "end")):
            if control is not None:
                control.check_cancelled()
            if event == "start":
                parent = stack[-1] if stack else None
                if element.tag == row_tag and parent is not None and parent.tag == sheet_data_tag:
                    implicit_row_number += 1
                    try:
                        current_row_number = int(element.attrib.get("r", implicit_row_number))
                    except (TypeError, ValueError):
                        current_row_number = implicit_row_number
                    if current_row_number <= 0:
                        raise FileImportError("The workbook contains an invalid worksheet row number.")
                    current_values = {}
                    next_column = 0
                stack.append(element)
                continue

            parent = stack[-2] if len(stack) > 1 else None
            if (
                element.tag == cell_tag and parent is not None and parent.tag == row_tag
                and current_values is not None and current_row_number is not None
            ):
                column, referenced_row = _excel_cell_position(
                    element.attrib.get("r", ""), next_column, current_row_number
                )
                if referenced_row != current_row_number:
                    raise FileImportError("The workbook contains a cell outside its worksheet row.")
                _check_column_limit(column + 1)
                next_column = column + 1
                current_values[column] = _excel_cell_text(
                    element, shared_strings, date_styles, time_styles, date_1904, main_ns
                )
                element.clear()
            elif (
                element.tag == row_tag and parent is not None and parent.tag == sheet_data_tag
                and current_values is not None and current_row_number is not None
            ):
                row_width = max(current_values.keys(), default=-1) + 1
                values = [current_values.get(column, "") for column in range(row_width)]
                if any(value.strip() for value in values):
                    rows.append((current_row_number, values))
                    if len(rows) >= AUTO_HEADER_PREFIX_ROWS:
                        break
                element.clear()
                parent.clear()
                current_row_number = None
                current_values = None
            elif (
                element.tag == row_tag and parent is not None and parent.tag == sheet_data_tag
                and current_values is None
            ):
                element.clear()
                parent.clear()
                current_row_number = None

            stack.pop()
    return rows


def _excel_sheet_quality(
    records: list[tuple[int, list[str]]],
) -> tuple[tuple[int, int, int, int], int] | None:
    header_index = _auto_header_index(records, minimum_support_rows=1)
    if header_index is None:
        return None
    raw_headers = records[header_index][1]
    headers = [re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip() for value in raw_headers]

    def has_header_term(*terms: str) -> bool:
        return any(term in header for header in headers for term in terms)

    semantic_score = sum((
        has_header_term("date"),
        has_header_term("emirates", "region", "location", "country", "state"),
        has_header_term("quantity", "qty"),
        has_header_term("sales", "revenue", "turnover"),
        has_header_term("vat", "tax"),
    ))
    data_rows = records[header_index + 1:]
    header_positions = [index for index, value in enumerate(raw_headers) if value.strip()]
    populated_cells = sum(
        sum(column < len(row) and bool(row[column].strip()) for column in header_positions)
        for _, row in data_rows
    )
    density = int(1000 * populated_cells / max(1, len(data_rows) * len(header_positions)))
    # Semantic matches select useful reporting tables; data depth and density
    # break ties, then a wider field set wins. The final index stabilizes ties.
    score = (semantic_score, len(data_rows), density, len(header_positions))
    return score, header_index


def _recommend_excel_sheet_from_parts(
    workbook: zipfile.ZipFile,
    sheets: list[tuple[str, str]],
    shared_strings: list[str],
    date_styles: set[int],
    time_styles: set[int],
    date_1904: bool,
    main_ns: str,
    control: _ImportControl | None = None,
) -> str:
    best: tuple[tuple[int, int, int, int, int], str] | None = None
    for order, (name, sheet_path) in enumerate(sheets):
        if control is not None:
            control.check_cancelled()
            control.report(f"Checking worksheet {order + 1} of {len(sheets)}: {name}…")
        records = _excel_prefix_rows(
            workbook, sheet_path, shared_strings, date_styles, time_styles,
            date_1904, main_ns, control,
        )
        quality = _excel_sheet_quality(records)
        if quality is None:
            continue
        score = (*quality[0], -order)
        if best is None or score > best[0]:
            best = (score, name)
    return best[1] if best is not None else sheets[0][0]


def _source_size(path: Path) -> int:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise FileImportError(f"Could not read {path.name}: {exc.strerror or exc}.") from exc
    if not path.is_file():
        raise FileImportError(f"{path.name} is not a regular file.")
    return size


def _read_source_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as stream:
            contents = stream.read(MAX_SOURCE_BYTES + 1)
    except OSError as exc:
        raise FileImportError(f"Could not read {path.name}: {exc.strerror or exc}.") from exc
    if len(contents) > MAX_SOURCE_BYTES:
        raise FileImportError(
            f"{path.name} is larger than the {MAX_SOURCE_BYTES // (1024 * 1024)} MiB import limit."
        )
    return contents


def _parse_csv(
    path: Path,
    options: dict[str, Any],
    control: _ImportControl | None = None,
) -> ImportCandidate:
    content = _read_source_bytes(path)
    if control is not None:
        control.check_cancelled()
    try:
        text = content.decode(options["encoding"])
    except UnicodeDecodeError as exc:
        raise FileImportError(f"Could not decode {path.name} as {options['encoding']}.") from exc

    raw_rows: list[list[str]] = []
    # csv.field_size_limit is process-global. Guard and restore it so a valid
    # field up to the bounded file size is accepted without leaking settings.
    with _CSV_FIELD_LIMIT_LOCK:
        old_field_limit = csv.field_size_limit()
        csv.field_size_limit(MAX_SOURCE_BYTES)
        try:
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=options["delimiter"], strict=True)
            widest_record = 0
            for record in reader:
                if control is not None:
                    control.check_cancelled()
                # A delimiter-only first record can intentionally supply blank
                # header cells; a physically blank line is still ignored.
                is_blank_header = (
                    options["has_header"] and not raw_rows and len(record) > 1
                )
                if _is_empty_record(record) and not is_blank_header:
                    continue
                _check_column_limit(len(record))
                raw_rows.append(record)
                widest_record = max(widest_record, len(record))
                data_count = len(raw_rows) - (1 if options["has_header"] else 0)
                _check_row_limit(data_count)
                _check_cell_limit(data_count, widest_record)
                if (
                    control is not None
                    and len(raw_rows) % _PROGRESS_ROW_INTERVAL == 0
                ):
                    control.report(f"Read {data_count:,} CSV rows…")
        except csv.Error as exc:
            raise FileImportError(f"Could not parse {path.name} as CSV: {exc}") from exc
        finally:
            csv.field_size_limit(old_field_limit)

    if not raw_rows:
        raise FileImportError(f"{path.name} is empty and has no header row.")

    if options["has_header"]:
        raw_headers = raw_rows[0]
        data_records = raw_rows[1:]
    else:
        raw_headers = []
        data_records = raw_rows

    width = max([len(raw_headers), *(len(record) for record in data_records)], default=0)
    _check_column_limit(width)
    headers = _normalize_headers(raw_headers, width)
    _check_cell_limit(len(data_records), len(headers))

    rows = []
    for row_number, record in enumerate(data_records, 1):
        if control is not None:
            control.check_cancelled()
            if row_number % _PROGRESS_ROW_INTERVAL == 0:
                control.report(f"Preparing {row_number:,} CSV rows…")
        values = record + [""] * (width - len(record))
        rows.append(dict(zip(headers, values)))
    return ImportCandidate("csv", headers, rows, options, [])


_CSV_FIELD_LIMIT_LOCK = threading.RLock()


def _parse_json(
    path: Path,
    options: dict[str, Any],
    control: _ImportControl | None = None,
) -> ImportCandidate:
    content = _read_source_bytes(path)
    if control is not None:
        control.check_cancelled()
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileImportError(f"{path.name} must be UTF-8 encoded JSON.") from exc
    decoder = json.JSONDecoder(
        object_pairs_hook=_unique_object_pairs,
        parse_constant=_reject_json_constant,
        parse_int=_parse_json_int,
        parse_float=_parse_json_float,
    )
    headers: list[str] = []
    header_by_key: dict[str, str] = {}
    used_headers: set[str] = set()
    rows: list[dict[str, str]] = []
    try:
        for row_index, record in enumerate(_iter_json_array(decoded, decoder), 1):
            if control is not None:
                control.check_cancelled()
            _check_row_limit(row_index)
            if not isinstance(record, dict):
                raise FileImportError(f"JSON row {row_index} must be an object with scalar values.")
            for key, value in record.items():
                if not isinstance(key, str):
                    raise FileImportError(f"JSON row {row_index} has an invalid column name.")
                if key not in header_by_key:
                    base = key.strip() or f"Column {len(headers) + 1}"
                    header = base
                    suffix = 2
                    while header in used_headers:
                        header = f"{base}_{suffix}"
                        suffix += 1
                    used_headers.add(header)
                    header_by_key[key] = header
                    headers.append(header)
                    _check_column_limit(len(headers))
                if not _is_json_scalar(value):
                    raise FileImportError(
                        f"JSON row {row_index}, field {key!r} is nested; only scalar values are supported."
                    )
            _check_cell_limit(row_index, len(headers))
            rows.append({
                header_by_key[key]: _json_scalar_text(value)
                for key, value in record.items()
            })
            if control is not None and row_index % _PROGRESS_ROW_INTERVAL == 0:
                control.report(f"Read {row_index:,} JSON rows…")
    except json.JSONDecodeError as exc:
        raise FileImportError(
            f"Could not parse {path.name} as JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}."
        ) from exc
    except RecursionError as exc:
        raise FileImportError(
            "JSON nesting exceeds the supported flat-record structure."
        ) from exc

    if not rows:
        raise FileImportError("JSON import requires a non-empty top-level array of objects.")
    if not headers:
        raise FileImportError("JSON records must contain at least one scalar field.")
    for row_index, row in enumerate(rows, 1):
        if control is not None:
            control.check_cancelled()
        for header in headers:
            row.setdefault(header, "")
        if control is not None and row_index % _PROGRESS_ROW_INTERVAL == 0:
            control.report(f"Preparing {row_index:,} JSON rows…")
    return ImportCandidate("json", headers, rows, options, [])


def _iter_json_array(
    text: str,
    decoder: json.JSONDecoder,
):
    """Decode a top-level array one record at a time, respecting row/cell caps."""
    index = _skip_json_whitespace(text, 0)
    if index >= len(text) or text[index] != "[":
        raise FileImportError("JSON import requires a non-empty top-level array of objects.")
    index += 1
    saw_record = False
    after_comma = False
    while True:
        index = _skip_json_whitespace(text, index)
        if index >= len(text):
            raise json.JSONDecodeError("Expecting value", text, index)
        if text[index] == "]":
            if after_comma:
                raise json.JSONDecodeError("Trailing comma", text, index)
            index += 1
            break
        record, index = decoder.raw_decode(text, index)
        saw_record = True
        after_comma = False
        yield record
        index = _skip_json_whitespace(text, index)
        if index >= len(text):
            raise json.JSONDecodeError("Expecting ',' delimiter", text, index)
        if text[index] == ",":
            index += 1
            after_comma = True
            continue
        if text[index] == "]":
            index += 1
            break
        raise json.JSONDecodeError("Expecting ',' delimiter", text, index)

    if not saw_record:
        return
    index = _skip_json_whitespace(text, index)
    if index != len(text):
        raise json.JSONDecodeError("Extra data", text, index)


def _skip_json_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _unique_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FileImportError(f"JSON object contains duplicate field {key!r}.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise FileImportError(f"JSON value {value} is not supported; use standard JSON numbers.")


def _parse_json_float(value: str) -> Decimal:
    try:
        decimal_value = Decimal(value)
        finite_as_float = float(value)
    except (ArithmeticError, ValueError, OverflowError) as exc:
        raise FileImportError(f"JSON number {value!r} is outside the supported numeric range.") from exc
    if not decimal_value.is_finite() or finite_as_float in {float("inf"), float("-inf")}:
        raise FileImportError(f"JSON number {value!r} is outside the supported numeric range.")
    return decimal_value


def _parse_json_int(value: str) -> int:
    try:
        integer_value = int(value)
        finite_as_float = float(value)
    except (ValueError, OverflowError) as exc:
        raise FileImportError(f"JSON number {value!r} is outside the supported numeric range.") from exc
    if finite_as_float in {float("inf"), float("-inf")}:
        raise FileImportError(f"JSON number {value!r} is outside the supported numeric range.")
    return integer_value


def _is_json_scalar(value: Any) -> bool:
    if isinstance(value, Decimal):
        return value.is_finite()
    return value is None or isinstance(value, (str, bool, int, float))


def _json_scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if value is True:
        return "TRUE"
    if value is False:
        return "FALSE"
    return str(value)


def _parse_xml(
    path: Path,
    options: dict[str, Any],
    control: _ImportControl | None = None,
) -> ImportCandidate:
    content = _read_source_bytes(path)
    if control is not None:
        control.check_cancelled()
    # ElementTree does not resolve external entities, but explicitly disallow
    # DTD/entity declarations (including UTF-16 markup) for a smaller safe subset.
    _reject_unsafe_xml_markup(content, path.name)
    stack: list[ElementTree.Element] = []
    root: ElementTree.Element | None = None
    record_tag: str | None = None
    pending_record: ElementTree.Element | None = None
    headers: list[str] | None = None
    rows: list[dict[str, str]] = []
    try:
        for event, element in ElementTree.iterparse(
            io.BytesIO(content), events=("start", "end")
        ):
            if control is not None:
                control.check_cancelled()
            if pending_record is not None and element is not pending_record:
                if (pending_record.tail or "").strip():
                    raise FileImportError("XML mixed content is not supported between records.")
                if root is not None:
                    root.remove(pending_record)
                pending_record.clear()
                pending_record = None

            if event == "start":
                parent = stack[-1] if stack else None
                if parent is None:
                    root = element
                    if root.attrib:
                        raise FileImportError(
                            "XML attributes are not supported; use scalar child elements for fields."
                        )
                elif parent is root:
                    if record_tag is None:
                        record_tag = element.tag
                    elif element.tag != record_tag:
                        raise FileImportError(
                            "XML contains multiple record groups; use one repeated record tag under the root."
                        )
                    if element.attrib:
                        raise FileImportError(
                            f"XML record {len(rows) + 1} has attributes; attributes are not supported."
                        )
                elif len(stack) == 2:
                    if element.attrib:
                        raise FileImportError(
                            f"XML field {_local_name(element.tag)!r} has attributes; attributes are not supported."
                        )
                else:
                    raise FileImportError(
                        "XML nested fields are not supported; use scalar child elements."
                    )
                stack.append(element)
                continue

            parent = stack[-2] if len(stack) > 1 else None
            if parent is root:
                row_index = len(rows) + 1
                _check_row_limit(row_index)
                fields = list(element)
                if not fields:
                    raise FileImportError(f"XML record {row_index} has no scalar child fields.")
                if (element.text or "").strip() or any((field.tail or "").strip() for field in fields):
                    raise FileImportError(f"XML record {row_index} contains mixed content.")

                field_names = [_local_name(field.tag) for field in fields]
                if len(set(field_names)) != len(field_names):
                    raise FileImportError(
                        f"XML record {row_index} has field names that collide after namespace removal."
                    )
                if headers is None:
                    headers = field_names
                    _check_column_limit(len(headers))
                elif field_names != headers:
                    raise FileImportError(
                        f"XML record {row_index} has a different ordered field structure."
                    )

                values = {
                    header: field.text or "" for header, field in zip(headers, fields)
                }
                rows.append(values)
                _check_cell_limit(len(rows), len(headers))
                if control is not None and row_index % _PROGRESS_ROW_INTERVAL == 0:
                    control.report(f"Read {row_index:,} XML rows…")
                pending_record = element
            elif element is root:
                if (root.text or "").strip():
                    raise FileImportError("XML mixed content is not supported between records.")
            stack.pop()
    except ElementTree.ParseError as exc:
        raise FileImportError(f"Could not parse {path.name} as XML: {exc}.") from exc
    if not rows:
        raise FileImportError("XML must contain a repeated record collection under its root element.")
    if headers is None:
        raise FileImportError("XML contains no tabular records.")
    normalized_headers = _normalize_headers(headers, len(headers))
    if normalized_headers != headers:
        normalized_rows: list[dict[str, str]] = []
        for row_index, row in enumerate(rows, 1):
            if control is not None:
                control.check_cancelled()
            normalized_rows.append({
                new: row[old] for old, new in zip(headers, normalized_headers)
            })
        rows = normalized_rows
    return ImportCandidate("xml", normalized_headers, rows, options, [])


def _reject_unsafe_xml_markup(content: bytes, part_name: str) -> None:
    declaration_scan = content.replace(b"\x00", b"")
    # Ignore comments, CDATA, and processing instructions so a literal marker
    # there is not mistaken for a declaration.
    declaration_scan = re.sub(
        rb"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>",
        b"",
        declaration_scan,
        flags=re.DOTALL,
    )
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", declaration_scan, re.IGNORECASE):
        raise FileImportError(f"{part_name} uses unsupported XML DTD or entity declarations.")


def _local_name(tag: str) -> str:
    if not isinstance(tag, str):
        raise FileImportError("XML comments and processing instructions are not data fields.")
    if tag.startswith("{"):
        _, separator, local = tag.rpartition("}")
        if separator:
            return local
    return tag


def _parse_excel(
    path: Path,
    options: dict[str, Any],
    control: _ImportControl | None = None,
) -> ImportCandidate:
    if path.suffix.casefold() == ".xls":
        return _parse_legacy_excel(path, options, control)
    if path.suffix.casefold() not in {".xlsx", ".xlsm"}:
        raise FileImportError("Choose an .xls, .xlsx, or .xlsm workbook.")
    notices: list[str] = []
    try:
        if control is not None:
            control.check_cancelled()
        with zipfile.ZipFile(path) as workbook:
            main_ns = f"{{{EXCEL_MAIN_NS}}}"
            names, sheets = _read_excel_sheet_index(workbook, path.name, control)
            if control is not None:
                control.check_cancelled()
            workbook_root = ElementTree.fromstring(
                _read_zip_part_bounded(workbook, workbook.getinfo("xl/workbook.xml"))
            )
            shared_strings = _read_excel_shared_strings(workbook, names, control)
            if control is not None:
                control.check_cancelled()
            date_styles, time_styles = _read_excel_styles(
                workbook, main_ns, names, control
            )
            workbook_properties = workbook_root.find(f"{main_ns}workbookPr")
            date_1904 = bool(
                workbook_properties is not None
                and workbook_properties.attrib.get("date1904", "0").casefold() in {"1", "true"}
            )
            requested_sheet = options["sheet_name"]
            sheet_name = requested_sheet or _recommend_excel_sheet_from_parts(
                workbook, sheets, shared_strings, date_styles, time_styles,
                date_1904, main_ns, control,
            )
            selected_sheet = next((item for item in sheets if item[0] == sheet_name), None)
            if selected_sheet is None:
                raise FileImportError(f"Worksheet {sheet_name!r} was not found in {path.name}.")
            sheet_path = selected_sheet[1]
            header_row = options["header_row"]
            raw_headers: list[str] | None = None
            data_records: list[list[str]] = []
            auto_header_records: list[tuple[int, list[str]]] = []
            data_width = 0
            formula_seen = False
            formula_cache_missing = False
            implicit_row_number = 0
            row_tag = f"{main_ns}row"
            cell_tag = f"{main_ns}c"
            sheet_data_tag = f"{main_ns}sheetData"
            stack: list[ElementTree.Element] = []
            current_row_number: int | None = None
            current_values: dict[int, str] | None = None
            next_column = 0

            def append_data_record(values: list[str]) -> None:
                nonlocal data_width
                if control is not None:
                    control.check_cancelled()
                assert raw_headers is not None
                data_records.append(values)
                _check_row_limit(len(data_records))
                data_width = max(data_width, len(raw_headers), len(values))
                _check_column_limit(data_width)
                _check_cell_limit(len(data_records), data_width)
                if control is not None and len(data_records) % _PROGRESS_ROW_INTERVAL == 0:
                    control.report(f"Read {len(data_records):,} Excel rows…")

            def commit_auto_header(index: int) -> None:
                nonlocal raw_headers, header_row
                header_row = auto_header_records[index][0]
                raw_headers = auto_header_records[index][1]
                for _, buffered_values in auto_header_records[index + 1:]:
                    append_data_record(buffered_values)
                auto_header_records.clear()

            with workbook.open(sheet_path) as sheet_stream:
                for event, element in ElementTree.iterparse(
                    sheet_stream, events=("start", "end")
                ):
                    if control is not None:
                        control.check_cancelled()
                    if event == "start":
                        parent = stack[-1] if stack else None
                        if element.tag == row_tag and parent is not None and parent.tag == sheet_data_tag:
                            implicit_row_number += 1
                            try:
                                current_row_number = int(
                                    element.attrib.get("r", implicit_row_number)
                                )
                            except (TypeError, ValueError):
                                current_row_number = implicit_row_number
                            if current_row_number <= 0:
                                raise FileImportError(
                                    f"Worksheet {sheet_name!r} contains an invalid row number."
                                )
                            current_values = (
                                {}
                                if header_row is None or current_row_number >= header_row
                                else None
                            )
                            next_column = 0
                        stack.append(element)
                        continue

                    parent = stack[-2] if len(stack) > 1 else None
                    if (
                        element.tag == cell_tag
                        and parent is not None
                        and parent.tag == row_tag
                        and current_values is not None
                        and current_row_number is not None
                    ):
                        column, referenced_row = _excel_cell_position(
                            element.attrib.get("r", ""), next_column, current_row_number
                        )
                        if referenced_row != current_row_number:
                            raise FileImportError(
                                f"Worksheet {sheet_name!r} contains a cell outside its row."
                            )
                        _check_column_limit(column + 1)
                        next_column = column + 1
                        formula = element.find(f"{main_ns}f")
                        value = element.find(f"{main_ns}v")
                        if formula is not None:
                            formula_seen = True
                            if value is None or value.text is None:
                                formula_cache_missing = True
                        current_values[column] = _excel_cell_text(
                            element, shared_strings, date_styles, time_styles, date_1904, main_ns
                        )
                        element.clear()
                    elif (
                        element.tag == cell_tag
                        and parent is not None
                        and parent.tag == row_tag
                    ):
                        # Rows before an explicitly selected header are not
                        # imported; release their cell XML as the stream passes.
                        element.clear()
                    elif (
                        element.tag == row_tag
                        and parent is not None
                        and parent.tag == sheet_data_tag
                        and current_values is not None
                        and current_row_number is not None
                    ):
                        row_width = max(current_values.keys(), default=-1) + 1
                        row_values = [
                            current_values.get(index, "") for index in range(row_width)
                        ]
                        if any(value.strip() for value in row_values):
                            if options["header_row"] is None and raw_headers is None:
                                auto_header_records.append((current_row_number, row_values))
                                header_index = _auto_header_index(
                                    auto_header_records, minimum_support_rows=2
                                )
                                if header_index is not None:
                                    commit_auto_header(header_index)
                                elif len(auto_header_records) >= AUTO_HEADER_PREFIX_ROWS:
                                    fallback_index = _auto_header_index(
                                        auto_header_records, minimum_support_rows=1
                                    )
                                    commit_auto_header(fallback_index if fallback_index is not None else 0)
                            elif raw_headers is None:
                                if current_row_number == header_row:
                                    raw_headers = row_values
                            elif current_row_number > header_row:
                                append_data_record(row_values)
                        element.clear()
                        parent.clear()
                        current_row_number = None
                        current_values = None
                    elif (
                        element.tag == row_tag
                        and parent is not None
                        and parent.tag == sheet_data_tag
                        and current_values is None
                    ):
                        element.clear()
                        parent.clear()
                        current_row_number = None

                    stack.pop()

            if options["header_row"] is None and raw_headers is None and auto_header_records:
                header_index = _auto_header_index(auto_header_records, minimum_support_rows=1)
                if header_index is None:
                    header_index = 0
                commit_auto_header(header_index)

            if formula_seen:
                notices.append("Excel formulas are not recalculated; saved cached values are imported.")
            if formula_cache_missing:
                notices.append("Some formula cells have no saved value and will import as blank.")

    except FileImportError:
        raise
    except (
        zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError, RuntimeError,
        ValueError, IndexError, EOFError, zlib.error, NotImplementedError,
    ) as exc:
        raise FileImportError("This is not a readable Excel .xlsx/.xlsm workbook.") from exc

    if raw_headers is None:
        if options["header_row"] is None:
            raise FileImportError(f"Worksheet {sheet_name!r} has no non-empty header row.")
        raise FileImportError(f"Header row {options['header_row']} is empty or missing in worksheet {sheet_name!r}.")
    width = max([len(raw_headers), *(len(record) for record in data_records)], default=0)
    _check_column_limit(width)
    _check_row_limit(len(data_records))
    _check_cell_limit(len(data_records), width)
    headers = _normalize_headers(raw_headers, width)
    rows = []
    for row_number, record in enumerate(data_records, 1):
        if control is not None:
            control.check_cancelled()
            if row_number % _PROGRESS_ROW_INTERVAL == 0:
                control.report(f"Preparing {row_number:,} Excel rows…")
        padded = record + [""] * (width - len(record))
        rows.append(dict(zip(headers, padded)))

    normalized_options = {"sheet_name": sheet_name, "header_row": header_row}
    return ImportCandidate("excel", headers, rows, normalized_options, notices)


def _parse_legacy_excel(
    path: Path,
    options: dict[str, Any],
    control: _ImportControl | None = None,
) -> ImportCandidate:
    """Import one worksheet from a bounded legacy BIFF `.xls` workbook."""
    xlrd, book = _open_legacy_excel(
        path, control.cancel_event if control is not None else None
    )
    try:
        requested_sheet = options["sheet_name"]
        sheet_name = requested_sheet or _recommend_legacy_excel_sheet(
            xlrd, book, control
        )
        try:
            sheet = book.sheet_by_name(sheet_name)
        except Exception as exc:
            raise FileImportError(
                f"Worksheet {sheet_name!r} was not found in {path.name}."
            ) from exc
        _check_column_limit(sheet.ncols)
        if sheet.ncols == 0:
            raise FileImportError(f"Worksheet {sheet_name!r} has no tabular columns.")

        header_row = options["header_row"]
        raw_headers: list[str] | None = None
        data_records: list[list[str]] = []
        auto_header_records: list[tuple[int, list[str]]] = []
        data_width = 0

        def append_data_record(values: list[str]) -> None:
            nonlocal data_width
            if control is not None:
                control.check_cancelled()
            assert raw_headers is not None
            data_records.append(values)
            _check_row_limit(len(data_records))
            data_width = max(data_width, len(raw_headers), len(values))
            _check_column_limit(data_width)
            _check_cell_limit(len(data_records), data_width)
            if control is not None and len(data_records) % _PROGRESS_ROW_INTERVAL == 0:
                control.report(f"Read {len(data_records):,} Excel rows…")

        def commit_auto_header(index: int) -> None:
            nonlocal raw_headers, header_row
            header_row = auto_header_records[index][0]
            raw_headers = auto_header_records[index][1]
            for _, buffered_values in auto_header_records[index + 1:]:
                append_data_record(buffered_values)
            auto_header_records.clear()

        for row_index in range(sheet.nrows):
            if control is not None:
                control.check_cancelled()
                if row_index and row_index % _PROGRESS_ROW_INTERVAL == 0:
                    control.report(f"Read worksheet row {row_index:,}…")
            row_number = row_index + 1
            if header_row is not None and row_number < header_row:
                continue
            row_width = sheet.row_len(row_index)
            _check_column_limit(row_width)
            values = [
                _legacy_excel_cell_text(xlrd, book, sheet, row_index, column_index)
                for column_index in range(row_width)
            ]
            is_populated = any(value.strip() for value in values)
            if options["header_row"] is None and raw_headers is None:
                if not is_populated:
                    continue
                auto_header_records.append((row_number, values))
                header_index = _auto_header_index(
                    auto_header_records,
                    minimum_support_rows=2,
                )
                if header_index is not None:
                    commit_auto_header(header_index)
                elif len(auto_header_records) >= AUTO_HEADER_PREFIX_ROWS:
                    fallback_index = _auto_header_index(
                        auto_header_records,
                        minimum_support_rows=1,
                    )
                    commit_auto_header(
                        fallback_index if fallback_index is not None else 0
                    )
            elif header_row is not None and raw_headers is None:
                if row_number == header_row:
                    raw_headers = values
            elif raw_headers is not None and is_populated:
                append_data_record(values)

        if options["header_row"] is None and raw_headers is None and auto_header_records:
            header_index = _auto_header_index(
                auto_header_records,
                minimum_support_rows=1,
            )
            commit_auto_header(header_index if header_index is not None else 0)

        if raw_headers is None or not any(value.strip() for value in raw_headers):
            if options["header_row"] is None:
                raise FileImportError(f"Worksheet {sheet_name!r} has no non-empty header row.")
            raise FileImportError(
                f"Header row {options['header_row']} is empty or missing in worksheet {sheet_name!r}."
            )

        width = max([len(raw_headers), *(len(record) for record in data_records)], default=0)
        _check_column_limit(width)
        _check_row_limit(len(data_records))
        _check_cell_limit(len(data_records), width)
        headers = _normalize_headers(raw_headers, width)
        rows = []
        for row_number, record in enumerate(data_records, 1):
            if control is not None:
                control.check_cancelled()
                if row_number % _PROGRESS_ROW_INTERVAL == 0:
                    control.report(f"Preparing {row_number:,} Excel rows…")
            padded = record + [""] * (width - len(record))
            rows.append(dict(zip(headers, padded)))

        notices = [
            "Formula expressions are not recalculated; saved formula results are imported when present.",
            "Date-formatted numbers use the workbook's 1900 or 1904 date system; ambiguous or invalid date serials remain numeric.",
        ]
        normalized_options = {"sheet_name": sheet_name, "header_row": header_row}
        return ImportCandidate("excel", headers, rows, normalized_options, notices)
    except FileImportError:
        raise
    except Exception as exc:
        raise FileImportError(
            f"Could not read {path.name} as a legacy Excel .xls workbook: {exc}"
        ) from exc
    finally:
        book.release_resources()


def _excel_cell_position(reference: str, fallback_column: int, fallback_row: int) -> tuple[int, int]:
    match = re.fullmatch(r"\$?([A-Z]+)\$?(\d+)", reference.upper()) if reference else None
    if not match:
        return fallback_column, fallback_row
    column = 0
    for letter in match.group(1):
        column = column * 26 + ord(letter) - ord("A") + 1
    return column - 1, int(match.group(2))


def _validate_workbook_archive(
    workbook: zipfile.ZipFile,
    display_name: str,
    control: _ImportControl | None = None,
) -> set[str]:
    infos = workbook.infolist()
    expanded_size = sum(info.file_size for info in infos)
    if expanded_size > MAX_WORKBOOK_EXPANDED_BYTES:
        raise FileImportError(
            f"The workbook expands beyond the {MAX_WORKBOOK_EXPANDED_BYTES // (1024 * 1024)} MiB workbook limit."
        )
    names = {info.filename for info in infos}
    for info in infos:
        if control is not None:
            control.check_cancelled()
        if not info.filename.casefold().endswith((".xml", ".rels")):
            continue
        if info.file_size > MAX_WORKBOOK_XML_PART_BYTES:
            raise FileImportError(
                f"Workbook part {info.filename!r} exceeds the {MAX_WORKBOOK_XML_PART_BYTES // (1024 * 1024)} MiB XML-part limit."
            )
        content = _read_zip_part_bounded(workbook, info)
        if control is not None:
            control.check_cancelled()
        _reject_unsafe_xml_markup(content, f"Workbook part {info.filename!r}")
    if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
        raise FileImportError(f"{display_name} is not a readable Excel workbook.")
    return names


def _read_zip_part_bounded(workbook: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Read one workbook XML part without trusting its declared uncompressed size."""
    if info.file_size > MAX_WORKBOOK_XML_PART_BYTES:
        raise FileImportError(
            f"Workbook part {info.filename!r} exceeds the {MAX_WORKBOOK_XML_PART_BYTES // (1024 * 1024)} MiB XML-part limit."
        )
    with workbook.open(info) as stream:
        content = stream.read(MAX_WORKBOOK_XML_PART_BYTES + 1)
    if len(content) > MAX_WORKBOOK_XML_PART_BYTES:
        raise FileImportError(
            f"Workbook part {info.filename!r} exceeds the {MAX_WORKBOOK_XML_PART_BYTES // (1024 * 1024)} MiB XML-part limit."
        )
    return content


def _read_excel_styles(
    workbook: zipfile.ZipFile,
    main_ns: str,
    names: set[str],
    control: _ImportControl | None = None,
) -> tuple[set[int], set[int]]:
    if "xl/styles.xml" not in names:
        return set(), set()
    if control is not None:
        control.check_cancelled()
    root = ElementTree.fromstring(workbook.read("xl/styles.xml"))
    if control is not None:
        control.check_cancelled()
    custom_formats = {
        int(item.attrib["numFmtId"]): item.attrib.get("formatCode", "")
        for item in root.findall(f"{main_ns}numFmts/{main_ns}numFmt")
        if "numFmtId" in item.attrib
    }
    cell_xfs = root.find(f"{main_ns}cellXfs")
    if cell_xfs is None:
        return set(), set()

    date_styles: set[int] = set()
    time_styles: set[int] = set()
    built_in_dates = set(range(14, 23)) | {45, 46, 47}
    for style_index, style in enumerate(cell_xfs):
        if control is not None:
            control.check_cancelled()
        number_format = int(style.attrib.get("numFmtId", "0"))
        format_code = custom_formats.get(number_format, "")
        is_elapsed_time = re.search(r"\[(?:h+|m+|s+)\]", format_code, re.IGNORECASE) is not None
        normalized = re.sub(r'"[^"]*"|\\.|\[[^]]+\]', "", format_code).casefold()
        is_date = not is_elapsed_time and (
            number_format in built_in_dates or any(char in normalized for char in "ymd")
        )
        if is_date:
            date_styles.add(style_index)
            if number_format in {18, 19, 20, 21, 22, 45, 46, 47} or any(
                char in normalized for char in "hs"
            ):
                time_styles.add(style_index)
    return date_styles, time_styles


def _excel_cell_text(
    cell: ElementTree.Element,
    shared_strings: list[str],
    date_styles: set[int],
    time_styles: set[int],
    date_1904: bool,
    main_ns: str,
) -> str:
    cell_type = cell.attrib.get("t", "")
    try:
        style_index = int(cell.attrib.get("s", "0"))
    except ValueError:
        style_index = 0
    if cell_type == "inlineStr":
        inline = cell.find(f"{main_ns}is")
        return "".join(item.text or "" for item in inline.iter(f"{main_ns}t")) if inline is not None else ""

    value = cell.find(f"{main_ns}v")
    raw = value.text if value is not None and value.text is not None else ""
    if cell_type == "s":
        try:
            shared_string_index = int(raw)
            if shared_string_index < 0:
                raise IndexError
            return shared_strings[shared_string_index]
        except (ValueError, IndexError) as exc:
            reference = cell.attrib.get("r", "unknown")
            raise FileImportError(
                f"Excel cell {reference} points to an invalid shared-string entry."
            ) from exc
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    if cell_type in {"str", "e"} or not raw:
        return raw
    if style_index in date_styles:
        try:
            serial = Decimal(raw)
            epoch = datetime(1904, 1, 1) if date_1904 else datetime(1899, 12, 30)
            value_as_date = epoch + timedelta(days=float(serial))
            if style_index in time_styles:
                return value_as_date.isoformat(sep=" ", timespec="seconds")
            return value_as_date.date().isoformat()
        except (ArithmeticError, ValueError, OverflowError):
            return raw
    try:
        number = Decimal(raw)
        return str(number.quantize(Decimal(1))) if number == number.to_integral_value() else format(number.normalize(), "f")
    except (ArithmeticError, ValueError):
        return raw


def _normalize_headers(raw_headers: list[str], width: int) -> list[str]:
    _check_column_limit(width)
    headers: list[str] = []
    used: set[str] = set()
    for index in range(width):
        value = raw_headers[index] if index < len(raw_headers) else ""
        base = value.strip() or f"Column {index + 1}"
        name = base
        suffix = 2
        while name in used:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name)
        headers.append(name)
    return headers


def normalize_promoted_headers(raw_headers: list[str], width: int) -> list[str]:
    """Normalize names promoted from the first data row.

    Power Query disambiguates duplicate promoted names with a dot and a
    one-based suffix. Blank names use this app's normal ``Column N`` fallback.
    """
    _check_column_limit(width)
    headers: list[str] = []
    used: set[str] = set()
    for index in range(width):
        value = raw_headers[index] if index < len(raw_headers) else ""
        base = value.strip() or f"Column {index + 1}"
        name = base
        suffix = 1
        while name in used:
            name = f"{base}.{suffix}"
            suffix += 1
        used.add(name)
        headers.append(name)
    return headers


def _is_empty_record(record: list[str]) -> bool:
    return not record or (len(record) == 1 and record[0] == "") or not any(value != "" for value in record)


def _check_row_limit(count: int) -> None:
    if count > MAX_DATA_ROWS:
        raise FileImportError(f"The file exceeds the {MAX_DATA_ROWS:,}-row import limit.")


def _check_column_limit(count: int) -> None:
    if count > MAX_COLUMNS:
        raise FileImportError(f"The file exceeds the {MAX_COLUMNS}-column import limit.")


def _check_cell_limit(row_count: int, column_count: int) -> None:
    if row_count * column_count > MAX_CELLS:
        raise FileImportError(f"The file exceeds the {MAX_CELLS:,}-cell import limit.")
