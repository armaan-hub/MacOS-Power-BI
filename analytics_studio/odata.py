"""Bounded anonymous OData v4 service-document and entity-set reads."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import math
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    HTTPSHandler,
    build_opener,
)

from analytics_studio.file_import import (
    MAX_CELLS,
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    MAX_SQLITE_TEXT_BYTES,
    ImportCandidate,
    _normalize_headers,
)


REQUEST_TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_RESPONSE_BYTES = 100 * 1024 * 1024
MAX_PAGE_COUNT = 2000
MAX_URL_LENGTH = 2048
MAX_CELL_BYTES = 1024 * 1024


class ODataError(ValueError):
    """An invalid OData endpoint or a bounded-read failure."""


def validate_service_root(value: Any) -> str:
    """Return a normalized HTTPS service root without credentials or query data."""
    if not isinstance(value, str):
        raise ODataError("Enter an OData service root URL.")
    value = value.strip()
    if (
        not value
        or len(value) > MAX_URL_LENGTH
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise ODataError(f"The OData service root must be a URL under {MAX_URL_LENGTH} characters.")
    parts = urlsplit(value)
    _validate_https_parts(parts, "service root")
    if parts.query or parts.fragment:
        raise ODataError("The OData service root must not include a query or fragment.")
    path = parts.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urlunsplit(("https", parts.netloc, path, "", ""))


def validate_odata_source(
    connection: Any, options: Any
) -> tuple[dict[str, str], dict[str, str]]:
    """Validate the small, credential-free OData source record persisted in projects."""
    if not isinstance(connection, dict) or set(connection) != {"service_root"}:
        raise ODataError("The OData connection settings are invalid.")
    service_root = validate_service_root(connection.get("service_root"))
    if not isinstance(options, dict) or set(options) != {"entity_set_name", "entity_url"}:
        raise ODataError("Choose a valid OData entity set.")
    name = options.get("entity_set_name")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 256
        or any(ord(char) < 32 for char in name)
    ):
        raise ODataError("The OData entity set needs a valid name.")
    entity_url = _validate_same_origin_url(options.get("entity_url"), service_root)
    if urlsplit(entity_url).query:
        raise ODataError("The selected OData entity set URL must not include a query.")
    return {"service_root": service_root}, {
        "entity_set_name": name.strip(),
        "entity_url": entity_url,
    }


def list_odata_entity_sets(service_root: str) -> list[dict[str, str]]:
    """Read an OData service document and return its entity-set navigation targets."""
    root = validate_service_root(service_root)
    document, final_url, _response_bytes = _read_json(root, root)
    if urlsplit(final_url).query or urlsplit(final_url).fragment:
        raise ODataError("The OData service root redirected to a URL with a query or fragment.")
    root_for_links = _with_trailing_slash(final_url)
    items = document.get("value") if isinstance(document, dict) else None
    if not isinstance(items, list):
        raise ODataError("The OData service document has no entity-set list.")

    entity_sets: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind is not None and (not isinstance(kind, str) or kind.casefold() != "entityset"):
            continue
        name = item.get("name")
        relative_url = item.get("url")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 256
            or not isinstance(relative_url, str)
            or not relative_url.strip()
        ):
            continue
        entity_url = _validate_same_origin_url(urljoin(root_for_links, relative_url), root)
        if urlsplit(entity_url).query:
            continue
        key = (name.strip().casefold(), entity_url)
        if key in seen:
            continue
        seen.add(key)
        entity_sets.append({"entity_set_name": name.strip(), "entity_url": entity_url})
    return sorted(entity_sets, key=lambda item: item["entity_set_name"].casefold())


def read_odata_entity_set(
    connection: dict[str, Any],
    options: dict[str, Any],
    *,
    row_limit: int = MAX_DATA_ROWS,
) -> ImportCandidate:
    """Read one flat OData entity set, following only same-origin next links."""
    if (
        not isinstance(row_limit, int)
        or isinstance(row_limit, bool)
        or not 1 <= row_limit <= MAX_DATA_ROWS
    ):
        raise ODataError("The OData row limit is invalid.")
    preview_only = row_limit < MAX_DATA_ROWS
    normalized_connection, normalized_options = validate_odata_source(connection, options)
    service_root = normalized_connection["service_root"]
    entity_url = normalized_options["entity_url"]
    request_url = entity_url
    visited: set[str] = set()
    total_response_bytes = 0
    raw_rows: list[dict[str, str]] = []
    raw_headers: list[str] = []
    header_set: set[str] = set()
    text_bytes = 0
    truncated = False

    for _page in range(MAX_PAGE_COUNT):
        safe_url = _validate_same_origin_url(request_url, service_root, allow_query=True)
        if safe_url in visited:
            raise ODataError("The OData service returned a repeated pagination link.")
        visited.add(safe_url)
        page, _final_url, response_bytes = _read_json(safe_url, service_root)
        total_response_bytes += response_bytes
        if total_response_bytes > MAX_TOTAL_RESPONSE_BYTES:
            raise ODataError("The OData result exceeds the 100 MiB response limit.")
        values = page.get("value") if isinstance(page, dict) else None
        if not isinstance(values, list):
            raise ODataError("The OData response does not contain an entity list.")

        for record in values:
            if len(raw_rows) >= row_limit:
                truncated = True
                break
            if not isinstance(record, dict):
                raise ODataError("The OData entity list contains a non-object row.")
            row: dict[str, str] = {}
            for key, value in record.items():
                if key.startswith("@odata.") or key.startswith("odata."):
                    continue
                try:
                    key_bytes = key.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise ODataError("An OData property name contains invalid Unicode.") from exc
                if len(key_bytes) > MAX_CELL_BYTES or any(ord(char) < 32 for char in key):
                    raise ODataError("An OData property name is invalid or exceeds the 1 MiB limit.")
                if key not in header_set:
                    raw_headers.append(key)
                    header_set.add(key)
                    if len(raw_headers) > MAX_COLUMNS:
                        raise ODataError(f"The selected entity set has more than {MAX_COLUMNS} columns.")
                    row_limit = min(row_limit, MAX_CELLS // len(raw_headers))
                    if len(raw_rows) > row_limit:
                        raw_rows = raw_rows[:row_limit]
                        truncated = True
                text = _cell_text(value, key)
                try:
                    encoded_size = len(text.encode("utf-8"))
                except UnicodeEncodeError as exc:
                    raise ODataError(
                        f"OData property {key!r} contains invalid Unicode."
                    ) from exc
                if encoded_size > MAX_CELL_BYTES:
                    raise ODataError("An OData value exceeds the 1 MiB per-cell text limit.")
                text_bytes += encoded_size
                if text_bytes > MAX_SQLITE_TEXT_BYTES:
                    raise ODataError("The OData result exceeds the 80 MiB rendered text limit.")
                row[key] = text
            if len(raw_rows) < row_limit:
                raw_rows.append(row)
            else:
                truncated = True
                break

        if truncated:
            break
        next_link = _next_link(page)
        if next_link is None:
            break
        request_url = urljoin(safe_url, next_link)
        _validate_same_origin_url(request_url, service_root, allow_query=True)
    else:
        raise ODataError(f"The OData result exceeded the {MAX_PAGE_COUNT:,}-page limit.")

    if not raw_headers:
        raise ODataError(
            "The selected OData entity set returned no rows, so its columns could not be identified."
        )
    headers = _normalize_headers(raw_headers, len(raw_headers))
    header_map = dict(zip(raw_headers, headers))
    rows = [
        {header_map[key]: row.get(key, "") for key in raw_headers}
        for row in raw_rows
    ]
    notices = []
    if truncated:
        if preview_only:
            notices.append(f"Preview is limited to {row_limit:,} rows or the local cell limit.")
        else:
            notices.append(f"Import was capped at {len(rows):,} rows by the row or cell limit.")
    return ImportCandidate(
        "odata",
        headers,
        rows,
        normalized_options,
        notices,
    )


def _read_json(url: str, same_origin_as: str) -> tuple[dict[str, Any], str, int]:
    safe_url = _validate_same_origin_url(url, same_origin_as, allow_query=True)
    opener = build_opener(
        _SameOriginRedirectHandler(same_origin_as),
        HTTPSHandler(context=ssl.create_default_context()),
    )
    request = Request(
        safe_url,
        headers={
            "Accept": "application/json;odata.metadata=minimal, application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "AnalyticsStudio/1.0 OData import",
        },
    )
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            final_url = _validate_same_origin_url(
                response.geturl(), same_origin_as, allow_query=True
            )
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise ODataError(f"The OData service returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise ODataError(
            "Could not reach the OData service. Check the HTTPS URL, network, and server certificate."
        ) from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise ODataError("An OData response exceeds the 10 MiB per-response limit.")
    try:
        document = json.loads(
            body.decode("utf-8-sig"),
            parse_float=Decimal,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeError, json.JSONDecodeError, InvalidOperation, ValueError) as exc:
        raise ODataError("The OData service returned invalid UTF-8 JSON.") from exc
    if not isinstance(document, dict):
        raise ODataError("The OData service response must be a JSON object.")
    return document, final_url, len(body)


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    def __init__(self, origin_url: str) -> None:
        super().__init__()
        self.origin_url = origin_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            _validate_same_origin_url(newurl, self.origin_url, allow_query=True)
        except ODataError as exc:
            raise ODataError(
                "The OData service redirected to a different or insecure URL."
            ) from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_https_parts(parts, label: str) -> None:
    if (
        parts.scheme.casefold() != "https"
        or not parts.netloc
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise ODataError(f"The OData {label} must use HTTPS and must not contain credentials.")
    try:
        port = parts.port
    except ValueError as exc:
        raise ODataError(f"The OData {label} has an invalid port.") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ODataError(f"The OData {label} has an invalid port.")


def _validate_same_origin_url(
    value: Any,
    origin_url: str,
    *,
    allow_query: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_URL_LENGTH
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise ODataError("The OData service returned an invalid URL.")
    parts = urlsplit(value)
    _validate_https_parts(parts, "URL")
    if parts.fragment or (parts.query and not allow_query):
        raise ODataError("The OData service returned a URL with unsupported query or fragment data.")
    if _origin(parts) != _origin(urlsplit(origin_url)):
        raise ODataError("The OData service returned a link outside its HTTPS origin.")
    return urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, ""))


def _origin(parts) -> tuple[str, str, int]:
    host = parts.hostname
    if not host:
        return "", "", 0
    try:
        port = parts.port or 443
    except ValueError as exc:
        raise ODataError("The OData service returned a URL with an invalid port.") from exc
    return parts.scheme.casefold(), host.casefold(), port


def _with_trailing_slash(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _next_link(page: dict[str, Any]) -> str | None:
    for key in ("@odata.nextLink", "odata.nextLink"):
        if key in page:
            value = page[key]
            if not isinstance(value, str) or not value:
                raise ODataError("The OData service returned an invalid next-page link.")
            return value
    return None


def _cell_text(value: Any, property_name: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (str, int, Decimal)):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return str(value)
    if isinstance(value, (dict, list)):
        raise ODataError(
            f"OData property {property_name!r} is nested; this importer supports scalar fields only."
        )
    raise ODataError(f"OData property {property_name!r} has an unsupported value type.")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON numeric constant {value}.")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("OData JSON objects must not contain duplicate property names.")
        result[key] = value
    return result
