"""Acceptance checks for Use Headers as First Row through project lifecycle."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog


class DemoteHeadersLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "records.csv"
        self.source_path.write_text(
            "Name,Amount\nAda,0012\nLin,3\n", encoding="utf-8"
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

    def test_demote_headers_replays_and_resets_output_types(self) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("convert_type")
        )
        dialog.column_combo.setCurrentText("Amount")
        dialog.option_combo.setCurrentIndex(
            dialog.option_combo.findData("whole_number")
        )
        dialog._add_step()

        dialog._add_or_start_new_step()
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("demote_headers")
        )
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.headers, ["Column1", "Column2"])
        self.assertEqual(dialog._preview_candidate.rows, [
            {"Column1": "Name", "Column2": "Amount"},
            {"Column1": "Ada", "Column2": "12"},
            {"Column1": "Lin", "Column2": "3"},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        self.assertEqual(
            self.table_for(controller, source_id)["column_types"],
            {"Column1": "text", "Column2": "text"},
        )
        dialog.deleteLater()

        project_path = self.root / "demote-headers-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Name,Amount\nMia,004\nNoah,8\n", encoding="utf-8"
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [
            {"Column1": "Name", "Column2": "Amount"},
            {"Column1": "Mia", "Column2": "4"},
            {"Column1": "Noah", "Column2": "8"},
        ])
        self.assertEqual(
            self.table_for(reopened, source_id)["column_types"],
            {"Column1": "text", "Column2": "text"},
        )

        self.source_path.write_text("Name,Amount\nOmar,9\n", encoding="utf-8")
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"Column1": "Name", "Column2": "Amount"},
            {"Column1": "Omar", "Column2": "9"},
        ])


if __name__ == "__main__":
    unittest.main()
