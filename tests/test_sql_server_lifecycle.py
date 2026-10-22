"""Acceptance checks for SQL Server navigation and saved-source lifecycle."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate
from analytics_studio.project import load_project
from analytics_studio import sql_server
from analytics_studio.sql_server import (
    SQLServerError,
    SUPPORTED_DRIVERS,
    list_sql_server_objects,
    read_sql_server_object,
)
from analytics_studio.sql_server_dialog import SQLServerImportDialog
from analytics_studio.sql_server_credentials import credential_account, get_password


CONNECTION = {
    "server": "sql.example.test",
    "port": 1433,
    "database": "Analytics",
    "username": "reader",
    "driver": SUPPORTED_DRIVERS[0],
    "encrypt": True,
}


class _FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.timeout = None
        self.description = None
        self.query = ""
        self._fetched = False

    def tables(self, tableType):
        self.table_type = tableType
        return _FakeResult([
            (None, "sales", "orders", "TABLE"),
            (None, "sales", "order_view", "VIEW"),
            (None, "sys", "internal", "SYSTEM TABLE"),
        ])

    def columns(self, table, schema):
        self.metadata_target = (schema, table)
        return _FakeResult([
            (None, schema, table, "id", 4, "int", 10),
            (None, schema, table, "amount", 3, "decimal", 18),
            (None, schema, table, "active", -7, "bit", 1),
            (None, schema, table, "created", 91, "date", 10),
            (None, schema, table, "note", 12, "varchar", 100),
        ])

    def execute(self, query):
        self.query = query
        self.description = [
            ("id", int, None, None, None, None, True),
            ("amount", Decimal, None, None, None, None, True),
            ("active", bool, None, None, None, None, True),
            ("created", date, None, None, None, None, True),
            ("note", str, None, None, None, None, True),
        ]
        return self

    def fetchmany(self, size):
        if self._fetched:
            return []
        self._fetched = True
        return self.rows

    def close(self):
        pass


class _FakeConnection:
    def __init__(self, rows):
        self._cursor = _FakeCursor(rows)
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class _BoundaryCursor:
    def __init__(self, metadata, description, rows, *, execute_error=None, metadata_error=None):
        self.metadata = metadata
        self.description = description
        self.rows = rows
        self.execute_error = execute_error
        self.metadata_error = metadata_error
        self.timeout = None
        self.query = None
        self.executed = False

    def columns(self, table, schema):
        if self.metadata_error:
            raise self.metadata_error
        return _FakeResult(self.metadata)

    def execute(self, query):
        self.query = query
        if self.execute_error:
            raise self.execute_error
        self.executed = True
        return self

    def fetchmany(self, size):
        rows, self.rows = self.rows, []
        return rows

    def close(self):
        pass


class _BoundaryConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class SQLServerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def candidate(value: str) -> ImportCandidate:
        return ImportCandidate(
            "sql_server",
            ["id", "value"],
            [{"id": "1", "value": value}],
            {"schema": "sales", "table_name": "orders", "object_type": "TABLE"},
            [],
        )

    @staticmethod
    def _read_boundary(rows, *, metadata=None, description=None, row_limit=100_000,
                       execute_error=None, metadata_error=None):
        metadata = metadata or [(None, "sales", "orders", "value", 4, "int", 10)]
        description = description or [("value", str, None, None, None, None, True)]
        cursor = _BoundaryCursor(
            metadata, description, rows,
            execute_error=execute_error, metadata_error=metadata_error,
        )
        connection = _BoundaryConnection(cursor)
        fake_pyodbc = types.SimpleNamespace(
            SQL_BINARY=-2, SQL_VARBINARY=-3, SQL_LONGVARBINARY=-4,
            SQL_LONGVARCHAR=-1, SQL_WLONGVARCHAR=-10,
            SQL_SS_XML=-152, SQL_SS_UDT=-151,
        )
        with (
            patch.dict(sys.modules, {"pyodbc": fake_pyodbc}),
            patch("analytics_studio.sql_server._connect", return_value=connection),
        ):
            result = read_sql_server_object(
                CONNECTION,
                {"schema": "sales", "table_name": "orders", "object_type": "TABLE"},
                "secret",
                row_limit=row_limit,
            )
        return result, cursor, connection

    def test_reader_rejects_binary_xml_lob_and_unbounded_text_metadata(self) -> None:
        unsupported_codes = [-2, -3, -4, -1, -10, -152, -151]
        unsupported_metadata = [
            (None, "sales", "orders", "value", code, "unsupported", 10)
            for code in unsupported_codes
        ] + [
            (None, "sales", "orders", "value", 12, "varchar", 8001),
            (None, "sales", "orders", "value", -9, "nvarchar", 4001),
        ]
        for metadata in unsupported_metadata:
            with self.subTest(sql_type=metadata[5], code=metadata[4], size=metadata[6]):
                with self.assertRaisesRegex(SQLServerError, "binary, XML, or unbounded text"):
                    self._read_boundary([], metadata=[metadata])

    def test_reader_rejects_binary_nonfinite_unsupported_and_oversized_cells(self) -> None:
        cases = [
            ((b"blob",), [("value", bytes)], "binary"),
            ((float("inf"),), [("value", str)], "non-finite"),
            ((Decimal("NaN"),), [("value", str)], "non-finite"),
            ((object(),), [("value", str)], "unsupported value type"),
            (("x" * (1024 * 1024 + 1),), [("value", str)], "1 MiB per-cell"),
        ]
        for row, description, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(SQLServerError, message):
                    self._read_boundary([row], description=description)

    def test_reader_enforces_column_cell_row_and_total_text_limits(self) -> None:
        two_columns = [
            (None, "sales", "orders", "left", 4, "int", 10),
            (None, "sales", "orders", "right", 4, "int", 10),
        ]
        with patch.object(sql_server, "MAX_COLUMNS", 1):
            with self.assertRaisesRegex(SQLServerError, "more than 1 columns"):
                self._read_boundary(
                    [(1, 2)], metadata=two_columns,
                    description=[("left", int), ("right", int)],
                )

        with patch.object(sql_server, "MAX_CELLS", 2):
            result, _, _ = self._read_boundary([("one",), ("two",), ("three",)])
            self.assertEqual(result.rows, [{"value": "one"}, {"value": "two"}])
            self.assertTrue(any("capped at 2 rows" in notice for notice in result.notices))

        result, _, _ = self._read_boundary([("one",), ("two",)], row_limit=1)
        self.assertEqual(result.rows, [{"value": "one"}])
        self.assertIn("Preview is limited to 1 rows.", result.notices)

        with patch.object(sql_server, "MAX_SQLITE_TEXT_BYTES", 3):
            with self.assertRaisesRegex(SQLServerError, "text limit"):
                self._read_boundary([("four",)])

    def test_reader_wraps_query_timeouts_and_closes_the_connection(self) -> None:
        cursor = _BoundaryCursor(
            [(None, "sales", "orders", "value", 4, "int", 10)],
            [("value", str)], [], execute_error=TimeoutError("query timed out"),
        )
        connection = _BoundaryConnection(cursor)
        fake_pyodbc = types.SimpleNamespace(
            SQL_BINARY=-2, SQL_VARBINARY=-3, SQL_LONGVARBINARY=-4,
            SQL_LONGVARCHAR=-1, SQL_WLONGVARCHAR=-10,
            SQL_SS_XML=-152, SQL_SS_UDT=-151,
        )
        with (
            patch.dict(sys.modules, {"pyodbc": fake_pyodbc}),
            patch("analytics_studio.sql_server._connect", return_value=connection),
        ):
            with self.assertRaisesRegex(SQLServerError, "Could not read the selected SQL Server table"):
                read_sql_server_object(
                    CONNECTION,
                    {"schema": "sales", "table_name": "orders", "object_type": "TABLE"},
                    "secret",
                )
        self.assertEqual(cursor.timeout, sql_server.QUERY_TIMEOUT_SECONDS)
        self.assertTrue(connection.closed)

    def test_bounded_reader_lists_objects_quotes_identifiers_and_normalizes_values(self) -> None:
        connection = _FakeConnection([
            (7, Decimal("12.50"), True, date(2026, 10, 8), None),
            (8, Decimal("18.25"), False, date(2026, 10, 9), "next"),
        ])
        connect_calls = []
        fake_pyodbc = types.SimpleNamespace(
            SQL_BINARY=-2,
            SQL_VARBINARY=-3,
            SQL_LONGVARBINARY=-4,
            SQL_LONGVARCHAR=-1,
            SQL_WLONGVARCHAR=-10,
            SQL_SS_XML=-152,
            SQL_SS_UDT=-151,
            drivers=lambda: [SUPPORTED_DRIVERS[0]],
            connect=lambda connection_string, timeout: (
                connect_calls.append((connection_string, timeout)) or connection
            ),
        )
        with patch.dict(sys.modules, {"pyodbc": fake_pyodbc}):
            objects = list_sql_server_objects(CONNECTION, "secret")
            result = read_sql_server_object(
                CONNECTION,
                {"schema": "sales]archive", "table_name": "orders]old", "object_type": "TABLE"},
                "secret",
                row_limit=1,
            )

        self.assertEqual(
            objects,
            [
                {"schema": "sales", "table_name": "order_view", "table_type": "VIEW"},
                {"schema": "sales", "table_name": "orders", "table_type": "TABLE"},
            ],
        )
        self.assertEqual(
            result.rows,
            [{
                "id": 7, "amount": Decimal("12.50"), "active": True,
                "created": date(2026, 10, 8), "note": None,
            }],
        )
        self.assertEqual(result.options["schema"], "sales]archive")
        self.assertIn("[sales]]archive].[orders]]old]", connection._cursor.query)
        self.assertIn("TOP (2)", connection._cursor.query)
        self.assertIn("Preview is limited to 1 rows.", result.notices)
        self.assertTrue(connect_calls)
        self.assertTrue(all(timeout == 8 for _, timeout in connect_calls))
        self.assertTrue(all("TrustServerCertificate=no" in value for value, _ in connect_calls))
        self.assertTrue(all("PWD={secret}" in value for value, _ in connect_calls))

    def test_dialog_connects_navigates_previews_and_accepts_selected_object(self) -> None:
        dialog = SQLServerImportDialog()
        dialog.server_edit.setText(CONNECTION["server"])
        dialog.database_edit.setText(CONNECTION["database"])
        dialog.username_edit.setText(CONNECTION["username"])
        dialog.password_edit.setText("dialog-secret")
        objects = [
            {"schema": "sales", "table_name": "orders", "table_type": "TABLE"},
            {"schema": "sales", "table_name": "order_view", "table_type": "VIEW"},
        ]
        reads = []

        def read_object(settings, options, password, *, row_limit=100_000):
            reads.append((dict(settings), dict(options), password, row_limit))
            return ImportCandidate(
                "sql_server", ["id"], [{"id": options["table_name"]}],
                dict(options), [],
            )

        with (
            patch("analytics_studio.sql_server_dialog.list_sql_server_objects", return_value=objects),
            patch("analytics_studio.sql_server_dialog.read_sql_server_object", side_effect=read_object),
        ):
            dialog._connect()
            self.assertEqual(dialog.object_combo.count(), 2)
            dialog.object_combo.setCurrentIndex(1)
            self.assertEqual(dialog.preview_model.rowCount(), 1)
            self.assertEqual(dialog.preview_model.columnCount(), 1)
            self.assertEqual(dialog.preview_model.data(dialog.preview_model.index(0, 0)), "order_view")
            dialog._accept_import()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.candidate.options["table_name"], "order_view")
        self.assertEqual(dialog.password, "dialog-secret")
        self.assertEqual(dialog.connection_settings["server"], CONNECTION["server"])
        self.assertEqual(reads[-1][3], 100_000)
        self.assertEqual(len(reads), 3)
        dialog.deleteLater()

    def test_pathless_source_keeps_password_out_of_project_and_replays_on_open_refresh(self) -> None:
        controller = self.controller("settings.ini")
        first = self.candidate("10")
        with patch("analytics_studio.controller.set_sql_server_password") as save_password:
            self.assertTrue(controller._commit_sql_server_import(
                CONNECTION, "secret-value", first
            ))
        source_id = controller.activeTableId
        credential_ref = controller._project["data_sources"][0]["connection"]["credential_ref"]
        connection = controller._project["data_sources"][0]["connection"]
        save_password.assert_called_once_with(
            credential_ref, "secret-value", connection
        )

        project_path = self.root / "sql-server-project.npa"
        self.assertTrue(controller._save_to(project_path))
        saved_project, _ = load_project(project_path)
        saved_source = saved_project["data_sources"][0]
        self.assertNotIn("path", saved_source)
        self.assertNotIn("password", saved_source["connection"])
        self.assertEqual(saved_source["connection"]["credential_ref"], credential_ref)

        reopened = self.controller("reopened-settings.ini")
        changed = self.candidate("20")
        with (
            patch("analytics_studio.controller.get_sql_server_password", return_value="secret-value"),
            patch("analytics_studio.controller.read_sql_server_object", return_value=changed) as read,
        ):
            self.assertTrue(reopened.open_project_path(project_path))
            self.assertEqual(reopened._rows, [{"id": "1", "value": "20"}])
            read.assert_called_once()

            refreshed = self.candidate("30")
            read.return_value = refreshed
            reopened.refresh_source()

        self.assertEqual(reopened._active_source_id, source_id)
        self.assertEqual(reopened._rows, [{"id": "1", "value": "30"}])

    def test_keychain_account_is_bound_to_server_identity(self) -> None:
        reference = "local-credential-ref"
        original = {**CONNECTION, "credential_ref": reference}
        redirected = {**original, "server": "attacker.example.test"}
        self.assertNotEqual(
            credential_account(reference, original),
            credential_account(reference, redirected),
        )
        self.assertEqual(
            credential_account(reference, original),
            credential_account(reference, dict(original)),
        )

        class LegacyOnlyKeychain:
            def __init__(self) -> None:
                self.lookups = []

            def get_password(self, service: str, account: str) -> str | None:
                self.lookups.append((service, account))
                return "legacy-secret" if account == reference else None

        keychain = LegacyOnlyKeychain()
        with patch(
            "analytics_studio.sql_server_credentials._macos_keyring",
            return_value=keychain,
        ):
            self.assertIsNone(get_password(reference, redirected))
        self.assertEqual(
            keychain.lookups,
            [("com.analytics-studio.sql-server", credential_account(reference, redirected))],
        )


if __name__ == "__main__":
    unittest.main()
