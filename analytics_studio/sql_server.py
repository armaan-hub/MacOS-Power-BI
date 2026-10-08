"""Bounded SQL Server table reads over the installed Microsoft ODBC driver."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import math
from typing import Any
from uuid import UUID

from analytics_studio.file_import import (
    MAX_CELLS,
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    MAX_SQLITE_TEXT_BYTES,
    ImportCandidate,
    _normalize_headers,
)


SUPPORTED_DRIVERS = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
)
CONNECT_TIMEOUT_SECONDS = 8
QUERY_TIMEOUT_SECONDS = 10
FETCH_BATCH_SIZE = 512


class SQLServerError(ValueError):
    """A missing driver, invalid SQL source, or bounded-read failure."""


def available_sql_server_drivers() -> list[str]:
    """Return supported Microsoft SQL Server drivers installed through ODBC."""
    try:
        import pyodbc
    except ImportError as exc:
        raise SQLServerError(
            "SQL Server import requires pyodbc and Microsoft's SQL Server ODBC driver. "
            "Install the application dependencies and Microsoft ODBC Driver 18."
        ) from exc
    try:
        installed = set(pyodbc.drivers())
    except Exception as exc:
        raise SQLServerError("Could not read the installed ODBC driver list.") from exc
    return [driver for driver in SUPPORTED_DRIVERS if driver in installed]


def validate_connection_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Normalize connection fields before they are saved or sent to ODBC."""
    if not isinstance(settings, dict):
        raise SQLServerError("SQL Server connection settings are invalid.")
    server = _required_text(settings, "server", 255)
    if not all(char.isalnum() or char in "_.:%[]-" for char in server):
        raise SQLServerError(
            "Enter a server host name or IP address without an instance name or port."
        )
    database = _required_text(settings, "database", 128)
    username = _required_text(settings, "username", 128)
    driver = _required_text(settings, "driver", 80)
    if driver not in SUPPORTED_DRIVERS:
        raise SQLServerError("Choose Microsoft ODBC Driver 17 or 18 for SQL Server.")
    port = settings.get("port", 1433)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise SQLServerError("The SQL Server port must be between 1 and 65535.")
    return {
        "server": server,
        "port": port,
        "database": database,
        "username": username,
        "driver": driver,
        "encrypt": True,
    }


def list_sql_server_objects(
    settings: dict[str, Any], password: str
) -> list[dict[str, str]]:
    """List user tables and views available to the supplied SQL login."""
    connection = _connect(settings, password)
    try:
        cursor = connection.cursor()
        cursor.timeout = QUERY_TIMEOUT_SECONDS
        rows = cursor.tables(tableType="TABLE,VIEW").fetchall()
        objects = []
        for row in rows:
            table_type = str(row[3] or "").upper()
            schema = str(row[1] or "")
            table_name = str(row[2] or "")
            if table_type not in {"TABLE", "VIEW"} or not schema or not table_name:
                continue
            objects.append({"schema": schema, "table_name": table_name, "table_type": table_type})
        cursor.close()
    except SQLServerError:
        raise
    except Exception as exc:
        raise SQLServerError(
            "Could not list SQL Server tables. Check the database name, permissions, and connection."
        ) from exc
    finally:
        connection.close()
    return sorted(objects, key=lambda item: (item["schema"].casefold(), item["table_name"].casefold()))


def read_sql_server_object(
    settings: dict[str, Any],
    object_options: dict[str, Any],
    password: str,
    *,
    row_limit: int = MAX_DATA_ROWS,
) -> ImportCandidate:
    """Read one selected table or view using a bounded, identifier-quoted SELECT."""
    if not isinstance(object_options, dict):
        raise SQLServerError("Choose a SQL Server table or view.")
    schema = _required_identifier(object_options, "schema", 128)
    table_name = _required_identifier(object_options, "table_name", 128)
    object_type = object_options.get("object_type")
    if object_type not in {"TABLE", "VIEW"}:
        raise SQLServerError("The selected SQL Server object type is invalid.")
    if not isinstance(row_limit, int) or isinstance(row_limit, bool) or not 1 <= row_limit <= MAX_DATA_ROWS:
        raise SQLServerError("The SQL Server row limit is invalid.")
    connection = _connect(settings, password)
    try:
        cursor = connection.cursor()
        cursor.timeout = QUERY_TIMEOUT_SECONDS
        metadata_column_names = _reject_unbounded_object_columns(cursor, schema, table_name)
        cursor.execute(
            f"SELECT TOP ({row_limit + 1}) * FROM "
            f"{_quote_identifier(schema)}.{_quote_identifier(table_name)}"
        )
        description = cursor.description
        if not description:
            raise SQLServerError("The selected SQL Server object has no readable columns.")
        result_column_names = {str(item[0] or "") for item in description}
        if result_column_names != metadata_column_names:
            raise SQLServerError(
                "SQL Server returned incomplete column metadata; the selected object can't be imported safely."
            )
        _reject_binary_result_columns(description)
        headers = _normalize_headers([str(item[0] or "") for item in description], len(description))
        width = len(headers)
        if width > MAX_COLUMNS:
            raise SQLServerError(f"The selected table has more than {MAX_COLUMNS} columns.")
        effective_row_limit = min(row_limit, MAX_CELLS // max(width, 1))
        rows: list[dict[str, str]] = []
        text_size = 0
        truncated = False
        while True:
            batch = cursor.fetchmany(FETCH_BATCH_SIZE)
            if not batch:
                break
            for record in batch:
                if len(rows) >= effective_row_limit:
                    truncated = True
                    break
                values: dict[str, str] = {}
                for header, value in zip(headers, record):
                    text = _cell_text(value)
                    encoded_size = len(text.encode("utf-8"))
                    if encoded_size > 1024 * 1024:
                        raise SQLServerError("A SQL Server value exceeds the 1 MiB per-cell text limit.")
                    text_size += encoded_size
                    if text_size > MAX_SQLITE_TEXT_BYTES:
                        raise SQLServerError(
                            f"The SQL Server result exceeds the {MAX_SQLITE_TEXT_BYTES // (1024 * 1024)} MiB text limit."
                        )
                    values[header] = text
                rows.append(values)
            if truncated:
                break
        cursor.close()
    except SQLServerError:
        raise
    except Exception as exc:
        raise SQLServerError(
            "Could not read the selected SQL Server table. Check object permissions and query limits."
        ) from exc
    finally:
        connection.close()

    notices = []
    if truncated:
        if row_limit < MAX_DATA_ROWS:
            notices.append(f"Preview is limited to {row_limit:,} rows.")
        else:
            notices.append(
                f"Import was capped at {effective_row_limit:,} rows by the row or cell limit."
            )
    return ImportCandidate(
        "sql_server",
        headers,
        rows,
        {"schema": schema, "table_name": table_name, "object_type": object_type},
        notices,
    )


def _connect(settings: dict[str, Any], password: str) -> Any:
    normalized = validate_connection_settings(settings)
    if not isinstance(password, str) or not password:
        raise SQLServerError("Enter the SQL Server password.")
    try:
        import pyodbc
    except ImportError as exc:
        raise SQLServerError(
            "SQL Server import requires pyodbc and Microsoft's SQL Server ODBC driver. "
            "Install the application dependencies and Microsoft ODBC Driver 18."
        ) from exc
    try:
        installed = set(pyodbc.drivers())
    except Exception as exc:
        raise SQLServerError("Could not read the installed ODBC driver list.") from exc
    driver = normalized["driver"]
    if driver not in installed:
        raise SQLServerError(
            f"{driver} is not installed. Install Microsoft's SQL Server ODBC driver and try again."
        )
    server_address = f"tcp:{normalized['server']},{normalized['port']}"
    connection_string = ";".join((
        f"DRIVER={_odbc_value(driver)}",
        f"SERVER={_odbc_value(server_address)}",
        f"DATABASE={_odbc_value(normalized['database'])}",
        f"UID={_odbc_value(normalized['username'])}",
        f"PWD={_odbc_value(password)}",
        "Encrypt=yes",
        "TrustServerCertificate=no",
    ))
    try:
        return pyodbc.connect(connection_string, timeout=CONNECT_TIMEOUT_SECONDS)
    except Exception as exc:
        # ODBC errors can echo the connection string, so never expose driver text here.
        raise SQLServerError(
            "SQL Server connection failed. Check the host, port, database, credentials, network, and TLS certificate."
        ) from exc


def _quote_identifier(value: str) -> str:
    escaped = value.replace("]", "]]")
    return f"[{escaped}]"


def _odbc_value(value: str) -> str:
    """Brace-quote ODBC values and double closing braces per ODBC syntax."""
    return "{" + value.replace("}", "}}") + "}"


def _required_text(settings: dict[str, Any], key: str, maximum: int) -> str:
    value = settings.get(key)
    if not isinstance(value, str):
        raise SQLServerError(f"SQL Server {key.replace('_', ' ')} is required.")
    value = value.strip()
    if not value or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise SQLServerError(f"SQL Server {key.replace('_', ' ')} must be 1–{maximum} valid characters.")
    return value


def _required_identifier(settings: dict[str, Any], key: str, maximum: int) -> str:
    value = settings.get(key)
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise SQLServerError(f"SQL Server {key.replace('_', ' ')} must be 1–{maximum} valid characters.")
    return value


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise SQLServerError("Binary SQL Server columns can't be imported as table text.")
    if isinstance(value, float) and not math.isfinite(value):
        raise SQLServerError("The SQL Server result contains a non-finite number.")
    if isinstance(value, Decimal) and not value.is_finite():
        raise SQLServerError("The SQL Server result contains a non-finite number.")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (str, int, float, Decimal)):
        return str(value)
    raise SQLServerError(f"SQL Server returned an unsupported value type: {type(value).__name__}.")


def _reject_unbounded_object_columns(
    cursor: Any, schema: str, table_name: str
) -> set[str]:
    """Reject binary, XML, and LOB SQL types before selecting any row values."""
    try:
        import pyodbc
        unsupported = {
            value for name in (
                "SQL_BINARY", "SQL_VARBINARY", "SQL_LONGVARBINARY",
                "SQL_LONGVARCHAR", "SQL_WLONGVARCHAR", "SQL_SS_XML", "SQL_SS_UDT",
            ) if (value := getattr(pyodbc, name, None)) is not None
        }
    except ImportError as exc:
        raise SQLServerError("SQL Server import requires pyodbc.") from exc

    try:
        columns = cursor.columns(table=table_name, schema=schema).fetchall()
    except Exception as exc:
        raise SQLServerError(
            "Could not inspect SQL Server column types before reading the selected object."
        ) from exc
    selected_columns = [
        column for column in columns
        if len(column) > 4
        and str(column[1] or "") == schema
        and str(column[2] or "") == table_name
    ]
    if not selected_columns:
        raise SQLServerError(
            "SQL Server did not return column metadata for the selected table or view."
        )
    column_names = {str(column[3] or "") for column in selected_columns}
    for column in selected_columns:
        type_name = str(column[5] or "").strip().casefold() if len(column) > 5 else ""
        column_size = column[6] if len(column) > 6 else None
        unbounded_text = (
            type_name in {"varchar", "nvarchar"}
            and (
                not isinstance(column_size, int)
                or isinstance(column_size, bool)
                or column_size <= 0
                or column_size > (8000 if type_name == "varchar" else 4000)
            )
        )
        if column[4] in unsupported or unbounded_text:
            name = str(column[3] or "(unnamed)")
            raise SQLServerError(
                f"Column {name!r} is binary, XML, or unbounded text and can't be imported."
            )
    return column_names


def _reject_binary_result_columns(description: Any) -> None:
    """Reject binary Python result types as a second guard before fetching rows."""
    for column in description:
        if len(column) > 1 and column[1] in {bytes, bytearray, memoryview}:
            name = str(column[0] or "(unnamed)")
            raise SQLServerError(f"Column {name!r} is binary and can't be imported as table text.")
