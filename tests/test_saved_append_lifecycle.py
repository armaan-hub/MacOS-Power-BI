"""Acceptance checks for append-query preview, persistence, and refresh."""

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
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.local_table_dialogs import AppendQueriesDialog
from analytics_studio.query_engine import append_candidates


class SavedAppendLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.left_path = self.root / "north.csv"
        self.right_path = self.root / "south.csv"
        self.left_path.write_text("id,amount\nN1,10\n", encoding="utf-8")
        self.right_path.write_text("id,amount\nS1,20\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def add_source_tables(self, controller: StudioController) -> list[str]:
        ids = []
        for path in (self.left_path, self.right_path):
            self.assertTrue(controller._commit_import(path, parse_file(path)))
            ids.append(controller.activeTableId)
        return ids

    def test_append_dialog_previews_schema_checked_rows_before_accept(self) -> None:
        candidates = {
            "left": ImportCandidate("csv", ["id", "amount"], [
                {"id": "N1", "amount": "10"},
            ], {}, []),
            "right": ImportCandidate("csv", ["id", "amount"], [
                {"id": "S1", "amount": "20"},
            ], {}, []),
        }
        tables = [
            {"sourceId": "left", "displayName": "North"},
            {"sourceId": "right", "displayName": "South"},
        ]
        dialog = AppendQueriesDialog(tables, candidates)
        self.assertIsNone(dialog.candidate)
        self.assertTrue(dialog.create_button.isEnabled())
        self.assertEqual(dialog.preview.model().rowCount(), 2)
        self.assertIn("2 rows after append", dialog.count_label.text())

        dialog.query_name_edit.setText("Combined sales")
        dialog._accept_query()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.query_name, "Combined sales")
        self.assertEqual(dialog.source_ids, ["left", "right"])
        self.assertEqual(dialog.candidate.rows, [
            {"id": "N1", "amount": "10"},
            {"id": "S1", "amount": "20"},
        ])
        dialog.deleteLater()

        mismatched = dict(candidates)
        mismatched["right"] = ImportCandidate(
            "csv", ["amount", "id"], [{"amount": "20", "id": "S1"}], {}, []
        )
        rejected = AppendQueriesDialog(tables, mismatched)
        self.assertFalse(rejected.create_button.isEnabled())
        self.assertIsNone(rejected.candidate)
        self.assertIn("different ordered column schema", rejected.error_label.text())
        rejected.deleteLater()

    def test_saved_append_reopens_and_refreshes_after_both_inputs_change(self) -> None:
        controller = self.controller("settings.ini")
        source_ids = self.add_source_tables(controller)
        candidates = {
            source_id: controller._loaded_candidates[source_id]
            for source_id in source_ids
        }
        appended = append_candidates([candidates[source_id] for source_id in source_ids])
        dialog = unittest.mock.Mock()
        dialog.exec.return_value = QDialog.DialogCode.Accepted
        dialog.candidate = appended
        dialog.source_ids = source_ids
        dialog.query_name = "Combined sales"

        with patch("analytics_studio.controller.AppendQueriesDialog", return_value=dialog):
            self.assertTrue(controller.append_queries_dialog())

        query_source = next(
            source for source in controller._project["data_sources"]
            if source.get("kind") == "query"
        )
        query_id = query_source["id"]
        self.assertEqual(query_source["query_definition"], {
            "operation": "append", "source_ids": source_ids,
        })
        self.assertEqual(controller._loaded_candidates[query_id].rows, [
            {"id": "N1", "amount": "10"},
            {"id": "S1", "amount": "20"},
        ])

        project_path = self.root / "append-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.left_path.write_text(
            "id,amount\nN1,100\nN2,110\n", encoding="utf-8"
        )
        self.right_path.write_text("id,amount\nS1,200\n", encoding="utf-8")

        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.activeTableId, query_id)
        self.assertEqual(reopened._loaded_candidates[query_id].rows, [
            {"id": "N1", "amount": "100"},
            {"id": "N2", "amount": "110"},
            {"id": "S1", "amount": "200"},
        ])

        self.left_path.write_text(
            "id,amount\nN1,101\nN2,111\n", encoding="utf-8"
        )
        self.right_path.write_text(
            "id,amount\nS1,201\nS2,210\n", encoding="utf-8"
        )
        reopened.refresh_all_sources()
        self.assertEqual(reopened._loaded_candidates[query_id].rows, [
            {"id": "N1", "amount": "101"},
            {"id": "N2", "amount": "111"},
            {"id": "S1", "amount": "201"},
            {"id": "S2", "amount": "210"},
        ])


if __name__ == "__main__":
    unittest.main()
