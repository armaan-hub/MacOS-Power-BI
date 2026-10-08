"""Acceptance checks for bounded anonymous Web table import."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import StudioController
from analytics_studio.date_table_dialog import DateTableDialog
from analytics_studio.file_import import ImportCandidate
from analytics_studio.project import load_project
from analytics_studio.web_import import (
    WebImportError,
    WebPayload,
    discover_web_objects,
    parse_web_payload,
    validate_web_url,
)
from analytics_studio.web_import_dialog import WebImportDialog


URL = "https://data.example.test/metrics.json"


class WebImportLifecycleTests(unittest.TestCase):
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
            "web",
            ["id", "amount"],
            [{"id": "1", "amount": value}],
            {"resource_type": "json", "json_path": ["data"]},
            [],
        )

    def test_html_json_csv_parsing_and_anonymous_https_rules(self) -> None:
        html = WebPayload(
            "https://data.example.test/page",
            "https://data.example.test/page",
            "text/html",
            "utf-8",
            b"<html><table><tr><th>Id</th><th>Label</th></tr>"
            b"<tr><td>1</td><td> Alpha </td></tr></table></html>",
        )
        html_objects = discover_web_objects(html)
        html_result = parse_web_payload(html, html_objects[0]["options"])
        self.assertEqual(html_result.rows, [{"Id": "1", "Label": "Alpha"}])

        json_payload = WebPayload(
            URL, URL, "application/json", "utf-8",
            b'{"data":[{"id":1,"amount":12.5,"note":null},{"id":2,"amount":20,"active":true}]}',
        )
        json_objects = discover_web_objects(json_payload)
        self.assertEqual(json_objects[0]["options"]["json_path"], ["data"])
        json_result = parse_web_payload(json_payload, json_objects[0]["options"])
        self.assertEqual(json_result.headers, ["id", "amount", "note", "active"])
        self.assertEqual(json_result.rows, [
            {"id": "1", "amount": "12.5", "note": "", "active": ""},
            {"id": "2", "amount": "20", "note": "", "active": "TRUE"},
        ])

        csv_payload = WebPayload(
            "https://data.example.test/metrics.csv",
            "https://data.example.test/metrics.csv",
            "text/csv",
            "utf-8",
            b"Id;Amount\n1;10\n2;20\n",
        )
        csv_options = discover_web_objects(csv_payload)[0]["options"]
        csv_options.update({"delimiter": ";", "has_header": True})
        csv_result = parse_web_payload(csv_payload, csv_options)
        self.assertEqual(csv_result.rows, [
            {"Id": "1", "Amount": "10"}, {"Id": "2", "Amount": "20"}
        ])

        with self.assertRaisesRegex(WebImportError, "HTTPS"):
            validate_web_url("http://data.example.test/metrics.csv")
        with self.assertRaisesRegex(WebImportError, "embedded credentials"):
            validate_web_url("https://user:secret@data.example.test/metrics.csv")

    def test_dialog_discovers_previews_and_accepts_selected_json_table(self) -> None:
        payload = WebPayload(
            URL, URL, "application/json", "utf-8",
            b'{"data":[{"id":1,"amount":10},{"id":2,"amount":20}]}',
        )
        dialog = WebImportDialog()
        dialog.url_edit.setText(URL)
        with (
            patch("analytics_studio.web_import_dialog.fetch_web_payload", return_value=payload),
            patch(
                "analytics_studio.web_import_dialog.read_web_source",
                side_effect=lambda connection, options: parse_web_payload(payload, options),
            ) as read_source,
        ):
            dialog._connect()
            self.assertEqual(dialog.object_combo.count(), 1)
            self.assertEqual(dialog.preview_model.rowCount(), 2)
            self.assertEqual(dialog.preview_model.columnCount(), 2)
            dialog._accept_import()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.url, URL)
        self.assertEqual(dialog.candidate.options["json_path"], ["data"])
        self.assertEqual(read_source.call_args.args[0], {"url": URL})
        dialog.deleteLater()

    def test_pathless_url_source_reopens_and_refreshes(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_web_import({"url": URL}, self.candidate("10")))
        source_id = controller.activeTableId

        project_path = self.root / "web-project.npa"
        self.assertTrue(controller._save_to(project_path))
        saved_project, _ = load_project(project_path)
        saved_source = saved_project["data_sources"][0]
        self.assertEqual(saved_source["connection"], {"url": URL})
        self.assertEqual(saved_source["parser_options"], {
            "resource_type": "json", "json_path": ["data"]
        })

        reopened = self.controller("reopened-settings.ini")
        with patch(
            "analytics_studio.controller.read_web_source",
            side_effect=[self.candidate("20"), self.candidate("30")],
        ) as read_source:
            self.assertTrue(reopened.open_project_path(project_path))
            self.assertEqual(reopened._rows, [{"id": "1", "amount": "20"}])
            reopened.refresh_source()

        self.assertEqual(reopened._active_source_id, source_id)
        self.assertEqual(reopened._rows, [{"id": "1", "amount": "30"}])
        self.assertEqual(read_source.call_count, 2)
        self.assertEqual(read_source.call_args_list[0].args, (
            {"url": URL}, {"resource_type": "json", "json_path": ["data"]}
        ))

    def test_reimport_preserves_marked_date_table_and_typed_column(self) -> None:
        controller = self.controller("settings.ini")
        date_options = {"resource_type": "json", "json_path": ["data"]}
        initial = ImportCandidate(
            "web", ["Date", "label"],
            [
                {"Date": "2024-01-01", "label": "One"},
                {"Date": "2024-01-02", "label": "Two"},
            ], date_options, [],
        )
        self.assertTrue(controller._commit_web_import({"url": URL}, initial))
        with patch("analytics_studio.controller.read_web_source", return_value=initial):
            self.assertTrue(controller.setColumnType("Date", "date"), controller.statusMessage)

        tables = [
            dict(table) for table in controller.tableCatalog
            if table.get("loaded") and table.get("loadEnabled")
        ]
        candidates = {
            str(table["sourceId"]): controller._loaded_candidates[str(table["sourceId"])]
            for table in tables
        }
        dialog = DateTableDialog(tables, candidates)
        dialog.column_combo.setCurrentText("Date")

        def accept_dialog() -> QDialog.DialogCode:
            dialog._accept_mark()
            return dialog.result()

        with (
            patch("analytics_studio.controller.DateTableDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=accept_dialog),
        ):
            self.assertTrue(controller.mark_date_table_dialog(), controller.statusMessage)
        dialog.deleteLater()

        refreshed = ImportCandidate(
            "web", ["Date", "label"],
            [
                {"Date": "2024-02-01", "label": "New one"},
                {"Date": "2024-02-02", "label": "New two"},
            ], date_options, [],
        )
        self.assertTrue(controller._commit_web_import({"url": URL}, refreshed))

        table = controller._project["model"]["tables"][0]
        self.assertEqual(table["date_column"], "Date")
        self.assertEqual(table["column_types"]["Date"], "date")
        self.assertEqual(controller._rows[0]["Date"], "2024-02-01")


if __name__ == "__main__":
    unittest.main()
