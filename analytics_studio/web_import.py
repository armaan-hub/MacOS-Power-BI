"""Bounded anonymous HTTPS reads for common Power Query Web responses."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler
import ssl

from analytics_studio.file_import import (
    MAX_CELLS,
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    MAX_SOURCE_BYTES,
    MAX_SQLITE_TEXT_BYTES,
    ImportCandidate,
    _normalize_headers,
    parse_file,
)


REQUEST_TIMEOUT_SECONDS = 10
MAX_URL_LENGTH = 2048
MAX_HTML_TABLES = 200
MAX_JSON_DEPTH = 12


class WebImportError(ValueError):
    """An invalid web source or a bounded response parsing failure."""


@dataclass(frozen=True)
class WebPayload:
    """One bounded HTTP response, retained while the user previews its tables."""

    requested_url: str
    response_url: str
    media_type: str
    charset: str | None
    body: bytes


def validate_web_url(value: Any) -> str:
    """Normalize an anonymous HTTPS URL while keeping its query parameters."""
    if not isinstance(value, str):
        raise WebImportError("Enter an HTTPS web address.")
    value = value.strip()
    if (
        not value
        or len(value) > MAX_URL_LENGTH
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise WebImportError(f"The web address must be a URL under {MAX_URL_LENGTH} characters.")
    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise WebImportError("The web address is malformed.") from exc
    _validate_https_url(parts)
    if parts.fragment:
        raise WebImportError("Remove the fragment after # from the web address.")
    return urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, ""))


def validate_web_source(
    connection: Any,
    options: Any,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Validate and normalize the pathless URL and navigation settings in a project."""
    if not isinstance(connection, dict) or set(connection) != {"url"}:
        raise WebImportError("The Web connection settings are invalid.")
    url = validate_web_url(connection.get("url"))
    if not isinstance(options, dict):
        raise WebImportError("The Web navigation settings are invalid.")
    resource_type = options.get("resource_type")
    if resource_type == "html_table":
        if set(options) != {"resource_type", "table_index", "has_header"}:
            raise WebImportError("Choose a valid Web page table.")
        table_index = options.get("table_index")
        has_header = options.get("has_header")
        if (
            not isinstance(table_index, int)
            or isinstance(table_index, bool)
            or not 0 <= table_index < MAX_HTML_TABLES
            or not isinstance(has_header, bool)
        ):
            raise WebImportError("The selected Web page table is invalid.")
        normalized = {
            "resource_type": "html_table",
            "table_index": table_index,
            "has_header": has_header,
        }
    elif resource_type == "json":
        if set(options) != {"resource_type", "json_path"}:
            raise WebImportError("Choose a valid JSON table.")
        json_path = options.get("json_path")
        if (
            not isinstance(json_path, list)
            or len(json_path) > MAX_JSON_DEPTH
            or any(
                not (
                    isinstance(part, str)
                    and part
                    and len(part) <= 256
                    and not any(ord(char) < 32 for char in part)
                    or isinstance(part, int)
                    and not isinstance(part, bool)
                    and part >= 0
                )
                for part in json_path
            )
        ):
            raise WebImportError("The selected JSON table path is invalid.")
        normalized = {"resource_type": "json", "json_path": list(json_path)}
    elif resource_type == "csv":
        if set(options) != {"resource_type", "delimiter", "encoding", "has_header"}:
            raise WebImportError("The Web CSV parsing options are invalid.")
        delimiter = options.get("delimiter")
        encoding = options.get("encoding")
        has_header = options.get("has_header")
        if delimiter not in {",", ";", "\t", "|"}:
            raise WebImportError("Choose comma, semicolon, tab, or pipe as the Web CSV delimiter.")
        if encoding not in {"utf-8-sig", "utf-8", "utf-16", "cp1252"}:
            raise WebImportError("The Web CSV character encoding is unsupported.")
        if not isinstance(has_header, bool):
            raise WebImportError("The Web CSV header option must be true or false.")
        normalized = {
            "resource_type": "csv",
            "delimiter": delimiter,
            "encoding": encoding,
            "has_header": has_header,
        }
    elif resource_type in {"xml", "excel", "parquet"}:
        if set(options) != {"resource_type"}:
            raise WebImportError("The Web source navigation settings are invalid.")
        normalized = {"resource_type": resource_type}
    else:
        raise WebImportError("The Web URL does not point to a supported tabular format or table page.")
    return {"url": url}, normalized


def fetch_web_payload(url: str) -> WebPayload:
    """Fetch one anonymous HTTPS response without cookies, auth, or request bodies."""
    normalized_url = validate_web_url(url)
    opener = build_opener(
        _HttpsOnlyRedirectHandler(),
        HTTPSHandler(context=ssl.create_default_context()),
    )
    request = Request(
        normalized_url,
        headers={
            "Accept": "text/html, application/json, text/csv, application/xml, text/xml, "
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, */*;q=0.5",
            "Accept-Encoding": "identity",
            "User-Agent": "AnalyticsStudio/1.0 Web import",
        },
    )
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response_url = validate_web_url(response.geturl())
            body = response.read(MAX_SOURCE_BYTES + 1)
            content_type = response.headers.get("Content-Type", "")
    except HTTPError as exc:
        raise WebImportError(f"The web server returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise WebImportError(
            "Could not read the HTTPS source. Check the URL, network, and server certificate."
        ) from exc
    if len(body) > MAX_SOURCE_BYTES:
        raise WebImportError(
            f"The web response exceeds the {MAX_SOURCE_BYTES // (1024 * 1024)} MiB limit."
        )
    media_type, charset = _content_type_parts(content_type)
    return WebPayload(normalized_url, response_url, media_type, charset, body)


def discover_web_objects(payload: WebPayload) -> list[dict[str, Any]]:
    """Return selectable HTML tables, flat JSON collections, or one file resource."""
    resource_type = _resource_type(payload)
    if resource_type == "html_table":
        tables = _HTMLTables()
        try:
            tables.feed(_decode_text(payload.body, payload.charset))
            tables.close()
        except (UnicodeError, ValueError) as exc:
            raise WebImportError("The web page could not be decoded as HTML.") from exc
        result = []
        for index, table in enumerate(tables.tables[:MAX_HTML_TABLES]):
            if not table.rows or not table.supported:
                continue
            data_rows = table.rows[1:] if table.has_header else table.rows
            row_count = len(data_rows)
            column_count = max((len(row) for row in table.rows), default=0)
            label = f"Table {index + 1} · {row_count:,} rows · {column_count:,} columns"
            result.append({
                "label": label,
                "options": {
                    "resource_type": "html_table",
                    "table_index": index,
                    "has_header": table.has_header,
                },
            })
        if not result:
            raise WebImportError("No readable HTML tables were found at this address.")
        return result
    if resource_type == "json":
        document = _decode_json(payload.body)
        result = []
        for json_path, rows in _json_tables(document):
            label_path = "root" if not json_path else "root." + ".".join(map(str, json_path))
            column_count = len(_json_columns(rows))
            result.append({
                "label": f"{label_path} · {len(rows):,} rows · {column_count:,} columns",
                "options": {"resource_type": "json", "json_path": json_path},
            })
            if len(result) >= MAX_HTML_TABLES:
                break
        if not result:
            raise WebImportError(
                "The JSON response has no flat array of records or scalar record to import."
            )
        return result
    labels = {
        "csv": "CSV data",
        "xml": "XML table",
        "excel": "Excel workbook (recommended worksheet)",
        "parquet": "Parquet table",
    }
    options: dict[str, Any] = {"resource_type": resource_type}
    if resource_type == "csv":
        options.update({
            "delimiter": ",",
            "encoding": _csv_encoding(payload.charset),
            "has_header": True,
        })
    return [{"label": labels[resource_type], "options": options}]


def parse_web_payload(
    payload: WebPayload,
    options: dict[str, Any],
    *,
    row_limit: int = MAX_DATA_ROWS,
) -> ImportCandidate:
    """Parse a selected web object using the same local format readers where possible."""
    if (
        not isinstance(row_limit, int)
        or isinstance(row_limit, bool)
        or not 1 <= row_limit <= MAX_DATA_ROWS
    ):
        raise WebImportError("The Web import row limit is invalid.")
    _, normalized_options = validate_web_source({"url": payload.requested_url}, options)
    resource_type = normalized_options["resource_type"]
    detected_type = _resource_type(payload)
    if resource_type == "html_table":
        if detected_type != "html_table":
            raise WebImportError("The web response changed from an HTML page since it was selected.")
        return _parse_html_table(payload, normalized_options, row_limit)
    if resource_type == "json":
        if detected_type != "json":
            raise WebImportError("The web response changed from JSON since it was selected.")
        return _parse_json_table(payload, normalized_options, row_limit)
    if detected_type != resource_type:
        raise WebImportError(
            f"The web response changed from {resource_type.upper()} to {detected_type.upper()} since it was selected."
        )
    expected_suffix = {
        "csv": ".csv",
        "xml": ".xml",
        "excel": _excel_suffix(payload),
        "parquet": ".parquet",
    }[resource_type]
    file_options: dict[str, Any]
    if resource_type == "csv":
        file_options = {
            "delimiter": normalized_options["delimiter"],
            "encoding": normalized_options["encoding"],
            "has_header": normalized_options["has_header"],
        }
    elif resource_type == "excel":
        file_options = {"sheet_name": None, "header_row": None}
    else:
        file_options = {}
    parsed = _parse_via_local_reader(payload.body, expected_suffix, resource_type, file_options)
    return ImportCandidate(
        "web",
        parsed.headers,
        parsed.rows,
        normalized_options,
        parsed.notices,
    )


def read_web_source(
    connection: dict[str, Any],
    options: dict[str, Any],
    *,
    row_limit: int = MAX_DATA_ROWS,
) -> ImportCandidate:
    """Fetch and parse one saved Web source for project open or Refresh."""
    normalized_connection, normalized_options = validate_web_source(connection, options)
    payload = fetch_web_payload(normalized_connection["url"])
    return parse_web_payload(payload, normalized_options, row_limit=row_limit)


def _parse_via_local_reader(
    body: bytes,
    suffix: str,
    resource_type: str,
    options: dict[str, Any],
) -> ImportCandidate:
    kind = "excel" if resource_type == "excel" else resource_type
    try:
        with tempfile.TemporaryDirectory(prefix="analytics-studio-web-") as directory:
            path = Path(directory) / f"download{suffix}"
            path.write_bytes(body)
            return parse_file(path, options, expected_kind=kind)
    except OSError as exc:
        raise WebImportError("Could not prepare the bounded web response for import.") from exc
    except ValueError as exc:
        raise WebImportError(str(exc)) from exc


def _parse_html_table(
    payload: WebPayload,
    options: dict[str, Any],
    row_limit: int,
) -> ImportCandidate:
    parser = _HTMLTables()
    try:
        parser.feed(_decode_text(payload.body, payload.charset))
        parser.close()
    except (UnicodeError, ValueError) as exc:
        raise WebImportError("The web page could not be decoded as HTML.") from exc
    table_index = options["table_index"]
    if table_index >= len(parser.tables):
        raise WebImportError("The selected HTML table is no longer present on this page.")
    table = parser.tables[table_index]
    if not table.rows:
        raise WebImportError("The selected HTML table has no rows.")
    if not table.supported:
        raise WebImportError("The selected HTML table uses merged cells, which are not supported.")
    has_header = options["has_header"]
    raw_headers = table.rows[0] if has_header else []
    data_rows = table.rows[1:] if has_header else table.rows
    width = max(
        len(raw_headers),
        max((len(row) for row in data_rows), default=0),
    )
    if width < 1:
        raise WebImportError("The selected HTML table has no columns.")
    if width > MAX_COLUMNS:
        raise WebImportError(f"The selected HTML table has more than {MAX_COLUMNS} columns.")
    headers = _normalize_headers(raw_headers, width)
    effective_row_limit = min(row_limit, MAX_DATA_ROWS, MAX_CELLS // width)
    truncated = len(data_rows) > effective_row_limit
    data_rows = data_rows[:effective_row_limit]
    rendered_bytes = 0
    rows = []
    for values in data_rows:
        padded = [*values[:width], *("" for _ in range(max(0, width - len(values))))]
        rendered = [str(value).strip() for value in padded]
        rendered_bytes += sum(len(value.encode("utf-8")) for value in rendered)
        if rendered_bytes > MAX_SQLITE_TEXT_BYTES:
            raise WebImportError("The HTML table exceeds the 80 MiB rendered-text limit.")
        rows.append(dict(zip(headers, rendered)))
    notices = []
    if truncated:
        notices.append(f"Web import was capped at {effective_row_limit:,} rows by the row or cell limit.")
    return ImportCandidate("web", headers, rows, options, notices)


def _parse_json_table(
    payload: WebPayload,
    options: dict[str, Any],
    row_limit: int,
) -> ImportCandidate:
    document = _decode_json(payload.body)
    selected = _get_json_path(document, options["json_path"])
    if isinstance(selected, dict) and _is_scalar_record(selected):
        records = [selected]
    elif isinstance(selected, list) and _is_flat_record_list(selected):
        records = selected
    else:
        raise WebImportError("The selected JSON value is no longer a flat table of scalar records.")
    raw_headers = _json_raw_columns(records)
    if not raw_headers:
        raise WebImportError("The selected JSON table has no columns.")
    if len(raw_headers) > MAX_COLUMNS:
        raise WebImportError(f"The selected JSON table has more than {MAX_COLUMNS} columns.")
    headers = _normalize_headers(raw_headers, len(raw_headers))
    header_map = dict(zip(raw_headers, headers))
    effective_row_limit = min(row_limit, MAX_DATA_ROWS, MAX_CELLS // len(headers))
    truncated = len(records) > effective_row_limit
    rows = []
    rendered_bytes = 0
    for record in records[:effective_row_limit]:
        row = {}
        for raw_header in raw_headers:
            header = header_map[raw_header]
            value = _json_cell_text(record.get(raw_header))
            rendered_bytes += len(value.encode("utf-8"))
            if rendered_bytes > MAX_SQLITE_TEXT_BYTES:
                raise WebImportError("The JSON table exceeds the 80 MiB rendered-text limit.")
            row[header] = value
        rows.append(row)
    notices = []
    if truncated:
        notices.append(f"Web import was capped at {effective_row_limit:,} rows by the row or cell limit.")
    return ImportCandidate("web", headers, rows, options, notices)


def _json_tables(document: Any) -> list[tuple[list[str | int], Any]]:
    result: list[tuple[list[str | int], Any]] = []

    def visit(value: Any, path: list[str | int], depth: int) -> None:
        if depth > MAX_JSON_DEPTH or len(result) >= MAX_HTML_TABLES:
            return
        if isinstance(value, list):
            if _is_flat_record_list(value):
                result.append((list(path), value))
            return
        if isinstance(value, dict):
            if _is_scalar_record(value):
                result.append((list(path), [value]))
                return
            for key, child in value.items():
                visit(child, [*path, key], depth + 1)

    visit(document, [], 0)
    return result


def _json_columns(records: list[dict[str, Any]]) -> list[str]:
    columns = _json_raw_columns(records)
    return _normalize_headers(columns, len(columns))


def _json_raw_columns(records: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record:
            if key not in seen:
                seen.add(key)
                columns.append(key)
                if len(columns) > MAX_COLUMNS:
                    return columns
    return columns


def _is_scalar_record(value: dict[str, Any]) -> bool:
    return bool(value) and all(
        item is None or isinstance(item, (str, int, float, Decimal, bool))
        for item in value.values()
    )


def _is_flat_record_list(value: list[Any]) -> bool:
    return bool(value) and all(isinstance(item, dict) and _is_scalar_record(item) for item in value)


def _get_json_path(document: Any, path: list[str | int]) -> Any:
    value = document
    try:
        for part in path:
            value = value[part]
    except (KeyError, IndexError, TypeError) as exc:
        raise WebImportError("The selected JSON table path is no longer available.") from exc
    return value


def _decode_json(body: bytes) -> Any:
    try:
        return json.loads(
            body.decode("utf-8-sig"),
            parse_float=Decimal,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise WebImportError("The web server returned invalid UTF-8 JSON.") from exc


def _json_cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (str, int, Decimal)):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return str(value)
    raise WebImportError("The selected JSON table contains an unsupported scalar value.")


@dataclass
class _HTMLTable:
    rows: list[list[str]]
    has_header: bool
    supported: bool


class _HTMLTables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_HTMLTable] = []
        self._depth = 0
        self._rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._row_has_header = False
        self._table_has_header = False
        self._table_supported = True
        self._ignore_data = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "table":
            if self._depth == 0:
                self._rows = []
                self._table_has_header = False
                self._table_supported = True
            self._depth += 1
            return
        if tag in {"script", "style"} and self._depth == 1:
            self._ignore_data = True
            return
        if self._depth != 1:
            return
        if tag == "tr":
            self._finish_row()
            self._row = []
            self._row_has_header = False
        elif tag in {"td", "th"} and self._row is not None:
            spans = {name: value for name, value in attrs}
            if any(spans.get(name) not in {None, "1"} for name in ("rowspan", "colspan")):
                self._table_supported = False
            self._cell = []
            self._row_has_header = self._row_has_header or tag == "th"
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "table":
            if self._depth == 1:
                self._finish_row()
                if self._rows:
                    self.tables.append(_HTMLTable(
                        self._rows, self._table_has_header, self._table_supported
                    ))
            if self._depth:
                self._depth -= 1
            return
        if self._depth != 1:
            return
        if tag in {"script", "style"} and self._ignore_data:
            self._ignore_data = False
            return
        if tag in {"td", "th"}:
            self._finish_cell()
        elif tag == "tr":
            self._finish_row()

    def handle_data(self, data: str) -> None:
        if self._depth == 1 and self._cell is not None and not self._ignore_data:
            self._cell.append(data)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def _finish_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
        self._cell = None

    def _finish_row(self) -> None:
        self._finish_cell()
        if self._row:
            if any(value for value in self._row):
                self._rows.append(self._row)
                if len(self._rows) == 1:
                    self._table_has_header = self._row_has_header
            self._row = None
            self._row_has_header = False


class _HttpsOnlyRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            parts = urlsplit(newurl)
            _validate_https_url(parts)
        except WebImportError as exc:
            raise WebImportError("The web source redirected to an insecure or invalid URL.") from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _resource_type(payload: WebPayload) -> str:
    media = payload.media_type.casefold()
    path = urlsplit(payload.response_url).path.casefold()
    leading = payload.body.lstrip()[:256].lower()
    if leading.startswith((b"<!doctype html", b"<html", b"<table", b"<body", b"<head")) or any(
        marker in leading for marker in (b"<html", b"<table")
    ):
        return "html_table"
    if media in {"text/html", "application/xhtml+xml"}:
        return "html_table"
    if media in {"application/json", "text/json"} or media.endswith("+json"):
        return "json"
    if "spreadsheetml.sheet" in media or path.endswith((".xlsx", ".xlsm", ".xls")):
        return "excel"
    if media == "application/vnd.ms-excel":
        return "excel"
    if media in {"text/csv", "application/csv"} or path.endswith(".csv"):
        return "csv"
    if media in {"application/xml", "text/xml"} or media.endswith("+xml") or path.endswith(".xml"):
        return "xml"
    if "parquet" in media or path.endswith(".parquet"):
        return "parquet"
    if leading[:1] in {b"{", b"["}:
        return "json"
    if leading.startswith((b"<?xml", b"<")):
        return "xml"
    if media == "text/plain":
        return "csv"
    raise WebImportError(
        "The web response is not a supported HTML table, CSV, JSON, XML, Excel, or Parquet resource."
    )


def _excel_suffix(payload: WebPayload) -> str:
    """Preserve legacy BIFF `.xls` parsing when a URL or MIME type identifies it."""
    path = urlsplit(payload.response_url).path.casefold()
    if path.endswith(".xls") or payload.media_type.casefold() == "application/vnd.ms-excel":
        return ".xls"
    if path.endswith(".xlsm"):
        return ".xlsm"
    return ".xlsx"


def _content_type_parts(value: str) -> tuple[str, str | None]:
    media = ""
    charset = None
    for index, part in enumerate(value.split(";")):
        field = part.strip()
        if index == 0:
            media = field.casefold()
        elif field.casefold().startswith("charset="):
            charset = field.split("=", 1)[1].strip().strip('"\'')
    return media, charset


def _decode_text(body: bytes, charset: str | None) -> str:
    encoding = charset or "utf-8-sig"
    try:
        return body.decode(encoding)
    except (LookupError, UnicodeError) as exc:
        if charset:
            try:
                return body.decode("utf-8-sig")
            except UnicodeError:
                pass
        raise WebImportError("The web response uses an unsupported or invalid character encoding.") from exc


def _csv_encoding(charset: str | None) -> str:
    if charset is None:
        return "utf-8-sig"
    value = charset.casefold().replace("_", "-")
    return {
        "utf-8": "utf-8",
        "utf-8-sig": "utf-8-sig",
        "utf-16": "utf-16",
        "windows-1252": "cp1252",
        "cp1252": "cp1252",
    }.get(value, "utf-8-sig")


def _validate_https_url(parts) -> None:
    if (
        parts.scheme.casefold() != "https"
        or not parts.netloc
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise WebImportError("The Web connector supports HTTPS URLs without embedded credentials.")
    try:
        port = parts.port
    except ValueError as exc:
        raise WebImportError("The web address has an invalid port.") from exc
    if port is not None and not 1 <= port <= 65535:
        raise WebImportError("The web address has an invalid port.")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON numeric constant {value}.")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Web JSON objects must not contain duplicate property names.")
        result[key] = value
    return result
