"""Bounded, standard-library importers for local tabular files.

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
import threading
from typing import Any, Mapping
import zipfile
import zlib
from xml.etree import ElementTree


MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_WORKBOOK_EXPANDED_BYTES = 80 * 1024 * 1024
MAX_WORKBOOK_XML_PART_BYTES = 80 * 1024 * 1024
MAX_DATA_ROWS = 100_000
MAX_COLUMNS = 512
MAX_CELLS = 500_000

EXCEL_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
EXCEL_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORKSHEET_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"


class FileImportError(ValueError):
    """An unsupported, malformed, or over-limit source file."""


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
    if suffix in {".xlsx", ".xlsm"}:
        return "excel"
    if suffix == ".json":
        return "json"
    if suffix == ".xml":
        return "xml"
    if suffix == ".xls":
        raise FileImportError("Legacy .xls workbooks are not supported. Save the file as .xlsx.")
    raise FileImportError(f"Unsupported file type {suffix or '(no extension)'!r}.")


def default_options(kind: str) -> dict[str, Any]:
    """Return fresh, JSON-serializable defaults for a source kind."""
    if kind == "csv":
        return {"delimiter": ",", "encoding": "utf-8-sig", "has_header": True}
    if kind == "excel":
        # ``None`` means first worksheet / first non-empty row. ``parse_file``
        # resolves these to the actual sheet and one-based row in its candidate.
        return {"sheet_name": None, "header_row": None}
    if kind in {"json", "xml"}:
        return {}
    raise FileImportError(f"Unsupported file import kind {kind!r}.")


def normalize_options(kind: str, options: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate options and return canonical values suitable for persistence."""
    if kind not in {"csv", "excel", "json", "xml"}:
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
    return result


def parse_file(
    path: str | Path,
    options: Mapping[str, Any] | None = None,
    expected_kind: str | None = None,
) -> ImportCandidate:
    """Parse a supported file completely without changing application state."""
    source_path = Path(path).expanduser()
    kind = kind_for_path(source_path)
    if expected_kind is not None and expected_kind != kind:
        if expected_kind not in {"csv", "excel", "json", "xml"}:
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

    if kind == "csv":
        return _parse_csv(source_path, normalized)
    if kind == "excel":
        return _parse_excel(source_path, normalized)
    if kind == "json":
        return _parse_json(source_path, normalized)
    return _parse_xml(source_path, normalized)


def list_excel_sheets(path: str | Path) -> list[str]:
    """List readable worksheet names for the import-options dialog."""
    source_path = Path(path).expanduser()
    if kind_for_path(source_path) != "excel":
        raise FileImportError("Choose an .xlsx or .xlsm workbook.")
    if _source_size(source_path) > MAX_SOURCE_BYTES:
        raise FileImportError(
            f"{source_path.name} is larger than the {MAX_SOURCE_BYTES // (1024 * 1024)} MiB import limit."
        )
    try:
        with zipfile.ZipFile(source_path) as workbook:
            names = _validate_workbook_archive(workbook, source_path.name)
            if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
                raise FileImportError("This ZIP file is not a readable Excel workbook.")
            main_ns = f"{{{EXCEL_MAIN_NS}}}"
            relation_id_attr = f"{{{EXCEL_REL_NS}}}id"
            workbook_root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
            relationship_root = ElementTree.fromstring(
                workbook.read("xl/_rels/workbook.xml.rels")
            )
            relationships = {
                item.attrib.get("Id", ""): item
                for item in relationship_root.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
            }
            result = []
            for sheet in workbook_root.findall(f"{main_ns}sheets/{main_ns}sheet"):
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
                    result.append(name)
            if not result:
                raise FileImportError("The workbook does not contain a readable worksheet.")
            if len(set(result)) != len(result):
                raise FileImportError("The workbook has duplicate worksheet names.")
            return result
    except FileImportError:
        raise
    except (
        zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError, RuntimeError,
        ValueError, IndexError, EOFError, zlib.error, NotImplementedError,
    ) as exc:
        raise FileImportError("This is not a readable Excel .xlsx/.xlsm workbook.") from exc


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


def _parse_csv(path: Path, options: dict[str, Any]) -> ImportCandidate:
    content = _read_source_bytes(path)
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
    for record in data_records:
        values = record + [""] * (width - len(record))
        rows.append(dict(zip(headers, values)))
    return ImportCandidate("csv", headers, rows, options, [])


_CSV_FIELD_LIMIT_LOCK = threading.RLock()


def _parse_json(path: Path, options: dict[str, Any]) -> ImportCandidate:
    content = _read_source_bytes(path)
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
    for row in rows:
        for header in headers:
            row.setdefault(header, "")
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


def _parse_xml(path: Path, options: dict[str, Any]) -> ImportCandidate:
    content = _read_source_bytes(path)
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
        rows = [{new: row[old] for old, new in zip(headers, normalized_headers)} for row in rows]
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


def _parse_excel(path: Path, options: dict[str, Any]) -> ImportCandidate:
    if path.suffix.casefold() not in {".xlsx", ".xlsm"}:
        raise FileImportError("Choose an .xlsx or .xlsm workbook. Legacy .xls files are not supported.")
    notices: list[str] = []
    try:
        with zipfile.ZipFile(path) as workbook:
            names = _validate_workbook_archive(workbook, path.name)
            if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
                raise FileImportError("This ZIP file is not a readable Excel workbook.")

            main_ns = f"{{{EXCEL_MAIN_NS}}}"
            relationship_id_attr = f"{{{EXCEL_REL_NS}}}id"
            workbook_root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
            sheet_elements = workbook_root.findall(f"{main_ns}sheets/{main_ns}sheet")
            if not sheet_elements:
                raise FileImportError("The workbook does not contain a worksheet.")

            rel_root = ElementTree.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
            relationships = {
                relation.attrib.get("Id", ""): relation
                for relation in rel_root.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
            }
            sheets: list[tuple[str, str]] = []
            for element in sheet_elements:
                name = element.attrib.get("name", "")
                relation = relationships.get(element.attrib.get(relationship_id_attr, ""))
                if not name or relation is None or relation.attrib.get("Type") != WORKSHEET_REL:
                    continue
                if relation.attrib.get("TargetMode", "Internal").casefold() == "external":
                    continue
                target = relation.attrib.get("Target", "")
                if target.startswith("/"):
                    sheet_path = posixpath.normpath(target.lstrip("/"))
                else:
                    sheet_path = posixpath.normpath(posixpath.join("xl", target))
                if sheet_path.startswith("../") or sheet_path not in names:
                    continue
                sheets.append((name, sheet_path))

            if not sheets:
                raise FileImportError("The workbook does not contain a readable worksheet.")
            sheet_names = [name for name, _ in sheets]
            if len(set(sheet_names)) != len(sheet_names):
                raise FileImportError("The workbook has duplicate worksheet names and cannot be selected unambiguously.")
            requested_sheet = options["sheet_name"]
            sheet_name = requested_sheet or sheets[0][0]
            selected_sheet = next((item for item in sheets if item[0] == sheet_name), None)
            if selected_sheet is None:
                raise FileImportError(f"Worksheet {sheet_name!r} was not found in {path.name}.")
            sheet_path = selected_sheet[1]

            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in names:
                shared_root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(node.text or "" for node in item.iter(f"{main_ns}t"))
                    for item in shared_root.findall(f"{main_ns}si")
                ]
            date_styles, time_styles = _read_excel_styles(workbook, main_ns, names)
            workbook_properties = workbook_root.find(f"{main_ns}workbookPr")
            date_1904 = bool(
                workbook_properties is not None
                and workbook_properties.attrib.get("date1904", "0").casefold() in {"1", "true"}
            )
            header_row = options["header_row"]
            raw_headers: list[str] | None = None
            data_records: list[list[str]] = []
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
            with workbook.open(sheet_path) as sheet_stream:
                for event, element in ElementTree.iterparse(
                    sheet_stream, events=("start", "end")
                ):
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
                            if raw_headers is None:
                                if header_row is None or current_row_number == header_row:
                                    raw_headers = row_values
                                    header_row = current_row_number
                            elif current_row_number > header_row:
                                data_records.append(row_values)
                                _check_row_limit(len(data_records))
                                data_width = max(
                                    data_width, len(raw_headers), len(row_values)
                                )
                                _check_column_limit(data_width)
                                _check_cell_limit(len(data_records), data_width)
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
    for record in data_records:
        padded = record + [""] * (width - len(record))
        rows.append(dict(zip(headers, padded)))

    normalized_options = {"sheet_name": sheet_name, "header_row": header_row}
    return ImportCandidate("excel", headers, rows, normalized_options, notices)


def _excel_cell_position(reference: str, fallback_column: int, fallback_row: int) -> tuple[int, int]:
    match = re.fullmatch(r"\$?([A-Z]+)\$?(\d+)", reference.upper()) if reference else None
    if not match:
        return fallback_column, fallback_row
    column = 0
    for letter in match.group(1):
        column = column * 26 + ord(letter) - ord("A") + 1
    return column - 1, int(match.group(2))


def _validate_workbook_archive(workbook: zipfile.ZipFile, display_name: str) -> set[str]:
    infos = workbook.infolist()
    expanded_size = sum(info.file_size for info in infos)
    if expanded_size > MAX_WORKBOOK_EXPANDED_BYTES:
        raise FileImportError(
            f"The workbook expands beyond the {MAX_WORKBOOK_EXPANDED_BYTES // (1024 * 1024)} MiB workbook limit."
        )
    names = {info.filename for info in infos}
    for info in infos:
        if not info.filename.casefold().endswith((".xml", ".rels")):
            continue
        if info.file_size > MAX_WORKBOOK_XML_PART_BYTES:
            raise FileImportError(
                f"Workbook part {info.filename!r} exceeds the {MAX_WORKBOOK_XML_PART_BYTES // (1024 * 1024)} MiB XML-part limit."
            )
        _reject_unsafe_xml_markup(
            _read_zip_part_bounded(workbook, info), f"Workbook part {info.filename!r}"
        )
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
) -> tuple[set[int], set[int]]:
    if "xl/styles.xml" not in names:
        return set(), set()
    root = ElementTree.fromstring(workbook.read("xl/styles.xml"))
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
