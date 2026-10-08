"""Acceptance checks for Use First Row as Headers through project lifecycle."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog


class PromoteHeadersLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "headerless.csv"
        self.source_path.write_text(
            " Name, ,Name\nAmount,01,Region\nAlice,10,East\nBob,20,West\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def table_for(controller: StudioController, source_id: str) -> dict:
        return next(
            table for table in controller._project["model"]["tables"]
            if table["source_id"] == source_id
        )

    def test_promote_headers_normalizes_names_and_replays_after_refresh(self) -> None:
        raw = parse_file(self.source_path, options={"has_header": False})
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("promote_headers")
        )
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.headers, [
            "Name", "Column 2", "Name.1",
        ])
        self.assertEqual(dialog._preview_candidate.rows[0], {
            "Name": "Amount", "Column 2": "01", "Name.1": "Region",
        })

        # The promoted names are available to later steps in the same query.
        dialog._add_or_start_new_step()
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("convert_type")
        )
        dialog.column_combo.setCurrentText("Column 2")
        dialog.option_combo.setCurrentIndex(
            dialog.option_combo.findData("whole_number")
        )
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.rows[0]["Column 2"], "1")
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        self.assertEqual(
            self.table_for(controller, source_id)["column_types"]["Column 2"],
            "whole_number",
        )
        dialog.deleteLater()

        project_path = self.root / "promote-headers-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            " Name, ,Name\nCount,004,Zone\nCara,8,South\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [
            {"Name": "Count", "Column 2": "4", "Name.1": "Zone"},
            {"Name": "Cara", "Column 2": "8", "Name.1": "South"},
        ])
        self.assertEqual(
            self.table_for(reopened, source_id)["column_types"]["Column 2"],
            "whole_number",
        )

        self.source_path.write_text(
            " Name, ,Name\nCount,7,Zone\nDana,9,North\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"Name": "Count", "Column 2": "7", "Name.1": "Zone"},
            {"Name": "Dana", "Column 2": "9", "Name.1": "North"},
        ])

    def test_promote_headers_reports_an_empty_table(self) -> None:
        empty = ImportCandidate("csv", ["Column1"], [], {}, [])
        dialog = TransformDataDialog(empty)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("promote_headers")
        )

        dialog._add_step()

        self.assertEqual(dialog._steps, [])
        self.assertIn("no data rows", dialog.error_label.text())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
