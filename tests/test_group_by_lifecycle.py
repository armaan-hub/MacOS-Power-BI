"""Acceptance checks for Group By through the saved source lifecycle."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog


class GroupByLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "transactions.csv"
        self.source_path.write_text(
            "Region,Product,Revenue,Units\n"
            "North,A,10,1\n"
            "North,A,10,1\n"
            "North,A,20,2\n"
            "North,A,30,3\n"
            "North,B,,1\n"
            "South,A,4,1\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_group_by_multiple_keys_and_aggregations_reopens_and_refreshes(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("group_by"))
        for index in range(dialog.keep_columns_list.count()):
            item = dialog.keep_columns_list.item(index)
            if item.text() in {"Region", "Product"}:
                item.setCheckState(Qt.CheckState.Checked)

        for operation, column, name in (
            ("sum", "Revenue", "Total revenue"),
            ("average", "Revenue", "Average revenue"),
            ("median", "Revenue", "Median revenue"),
            ("min", "Revenue", "Minimum revenue"),
            ("max", "Revenue", "Maximum revenue"),
            ("count_distinct_values", "Revenue", "Distinct revenue values"),
            ("count_rows", "", "Transaction count"),
            ("count_distinct_rows", "", "Distinct row count"),
        ):
            dialog.group_aggregate_operation_combo.setCurrentIndex(
                dialog.group_aggregate_operation_combo.findData(operation)
            )
            if column:
                dialog.group_aggregate_column_combo.setCurrentText(column)
            dialog.group_aggregate_name_edit.setText(name)
            dialog._add_group_aggregation()

        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.headers, [
            "Region", "Product", "Total revenue", "Average revenue",
            "Median revenue", "Minimum revenue", "Maximum revenue",
            "Distinct revenue values", "Transaction count", "Distinct row count",
        ])
        self.assertEqual(dialog._preview_candidate.rows, [
            {
                "Region": "North", "Product": "A", "Total revenue": "70",
                "Average revenue": "17.5", "Median revenue": "15",
                "Minimum revenue": "10", "Maximum revenue": "30",
                "Distinct revenue values": "3", "Transaction count": "4",
                "Distinct row count": "3",
            },
            {
                "Region": "North", "Product": "B", "Total revenue": "",
                "Average revenue": "", "Median revenue": "",
                "Minimum revenue": "", "Maximum revenue": "",
                "Distinct revenue values": "1", "Transaction count": "1",
                "Distinct row count": "1",
            },
            {
                "Region": "South", "Product": "A", "Total revenue": "4",
                "Average revenue": "4", "Median revenue": "4",
                "Minimum revenue": "4", "Maximum revenue": "4",
                "Distinct revenue values": "1", "Transaction count": "1",
                "Distinct row count": "1",
            },
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "grouped-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Region,Product,Revenue,Units\n"
            "North,A,5,1\nNorth,A,5,1\nNorth,A,15,2\n"
            "North,A,25,3\nNorth,A,35,4\nNorth,B,,1\nSouth,A,2,1\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows[0], {
            "Region": "North", "Product": "A", "Total revenue": "85",
            "Average revenue": "17", "Median revenue": "15",
            "Minimum revenue": "5", "Maximum revenue": "35",
            "Distinct revenue values": "4", "Transaction count": "5",
            "Distinct row count": "4",
        })
        self.assertEqual(reopened._rows[1]["Distinct revenue values"], "1")

        self.source_path.write_text(
            "Region,Product,Revenue,Units\n"
            "East,C,2,1\nEast,C,6,2\nWest,D,9,1\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {
                "Region": "East", "Product": "C", "Total revenue": "8",
                "Average revenue": "4", "Median revenue": "4",
                "Minimum revenue": "2", "Maximum revenue": "6",
                "Distinct revenue values": "2", "Transaction count": "2",
                "Distinct row count": "2",
            },
            {
                "Region": "West", "Product": "D", "Total revenue": "9",
                "Average revenue": "9", "Median revenue": "9",
                "Minimum revenue": "9", "Maximum revenue": "9",
                "Distinct revenue values": "1", "Transaction count": "1",
                "Distinct row count": "1",
            },
        ])


if __name__ == "__main__":
    unittest.main()
