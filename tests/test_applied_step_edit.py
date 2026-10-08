"""Acceptance check for editing and replaying a saved applied step."""

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
from analytics_studio.file_import import parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.transformations import apply_transformations


class AppliedStepEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "sales.csv"
        self.source_path.write_text(
            "Region,Revenue\n East ,10\nWest,20\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_edit_saved_step_and_replay_after_reopen_and_refresh(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId
        initial_steps = [{
            "op": "replace_value",
            "column": "Region",
            "value": "East",
            "replacement": "Eastern",
        }, {"op": "trim_text", "column": "Region"}]
        self.assertTrue(controller._commit_transform_steps(
            source_id, initial_steps, apply_transformations(raw, initial_steps)
        ))

        dialog = TransformDataDialog(raw, initial_steps)
        dialog.step_list.setCurrentRow(0)
        self.assertEqual(dialog.replacement_edit.text(), "Eastern")
        dialog.replacement_edit.setText("East area")
        dialog._update_selected_step()
        self.assertEqual(dialog._steps[0]["replacement"], "East area")
        self.assertEqual(dialog._preview_candidate.rows[0]["Region"], "East")
        dialog.step_list.setCurrentRow(1)
        dialog._move_step(-1)
        self.assertEqual([step["op"] for step in dialog._steps], [
            "trim_text", "replace_value",
        ])
        self.assertEqual(dialog._preview_candidate.rows[0]["Region"], "East area")
        dialog._accept_candidate()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

        with (
            patch("analytics_studio.controller.TransformDataDialog", return_value=dialog),
            patch.object(dialog, "exec", return_value=QDialog.DialogCode.Accepted),
        ):
            self.assertTrue(controller.transform_data_dialog())
        saved_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == source_id
        )
        self.assertEqual(saved_source["transform_steps"][0]["op"], "trim_text")
        self.assertEqual(saved_source["transform_steps"][1]["replacement"], "East area")
        self.assertEqual(controller._rows[0]["Region"], "East area")

        project_path = self.root / "edited-steps.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Region,Revenue\n East ,11\nWest,21\nNorth,30\n", encoding="utf-8"
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows[0]["Region"], "East area")
        self.assertEqual(reopened.rowCount, 3)

        self.source_path.write_text(
            "Region,Revenue\n East ,12\nSouth,40\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"Region": "East area", "Revenue": "12"},
            {"Region": "South", "Revenue": "40"},
        ])
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
