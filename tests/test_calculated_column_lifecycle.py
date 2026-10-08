"""Acceptance checks for calculated-column authoring, persistence, and refresh."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.calculated_column_dialog import CalculatedColumnDialog
from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file


class CalculatedColumnLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "Orders.csv"
        self.source_path.write_text(
            "Quantity,Unit price\n2,12.5\n3,8\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def save_dialog(
        self,
        controller: StudioController,
        name: str,
        expression: str,
        *,
        selected_name: str = "",
        delete: bool = False,
    ) -> bool:
        table = controller._model_table_for_source(
            controller._project, controller.activeTableId
        )
        dialog = CalculatedColumnDialog(table.get("calculated_columns", []))
        if selected_name:
            dialog.saved_combo.setCurrentIndex(
                dialog.saved_combo.findData(selected_name)
            )
        dialog.name_edit.setText(name)
        dialog.expression_edit.setPlainText(expression)

        def accept_dialog() -> QDialog.DialogCode:
            if delete:
                dialog._delete_column()
            else:
                dialog._accept_column()
            return dialog.result()

        with (
            patch("analytics_studio.controller.CalculatedColumnDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=accept_dialog),
            patch("analytics_studio.controller.QMessageBox.warning"),
        ):
            return controller.calculated_column_dialog()

    def test_create_edit_refresh_reopen_and_delete_calculated_column(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))

        self.assertTrue(self.save_dialog(controller, "Line total", "[Quantity] * [Unit price]"))
        self.assertEqual(controller._headers, ["Quantity", "Unit price", "Line total"])
        self.assertEqual([row["Line total"] for row in controller._rows], ["25.0", "24"])
        model_table = controller._model_table_for_source(
            controller._project, controller.activeTableId
        )
        self.assertEqual(model_table["column_types"]["Line total"], "decimal_number")

        project_path = self.root / "calculated.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Line total"] for row in reopened._rows], ["25.0", "24"])

        self.assertTrue(self.save_dialog(
            reopened,
            "Line total",
            "[Quantity] * [Unit price] + 1",
            selected_name="Line total",
        ))
        self.assertEqual([row["Line total"] for row in reopened._rows], ["26.0", "25"])

        self.source_path.write_text(
            "Quantity,Unit price\n4,10\n1,2\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual([row["Line total"] for row in reopened._rows], ["41", "3"])

        self.assertTrue(self.save_dialog(
            reopened,
            "Line total",
            "[Quantity] * [Unit price] + 1",
            selected_name="Line total",
            delete=True,
        ))
        self.assertEqual(reopened._headers, ["Quantity", "Unit price"])
        self.assertEqual(
            self._model_columns(reopened),
            [],
        )

        self.assertTrue(reopened._save_to(project_path))
        final = self.controller("final.ini")
        self.assertTrue(final.open_project_path(project_path))
        self.assertEqual(self._model_columns(final), [])

    @staticmethod
    def _model_columns(controller: StudioController) -> list[dict[str, str]]:
        table = controller._model_table_for_source(
            controller._project, controller.activeTableId
        )
        return list(table.get("calculated_columns", []))
