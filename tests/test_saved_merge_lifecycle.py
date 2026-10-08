"""Acceptance checks for saved merge-query dialog, persistence, and refresh."""

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
from analytics_studio.local_table_dialogs import MergeQueriesDialog
from analytics_studio.file_import import ImportCandidate
from analytics_studio.query_engine import merge_candidates


class SavedMergeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sales_path = self.root / "sales.csv"
        self.regions_path = self.root / "regions.csv"
        self.sales_path.write_text(
            "sale_id,region,amount\n1,East,10\n2,West,20\n", encoding="utf-8"
        )
        self.regions_path.write_text(
            "region,manager\nEast,Kim\nSouth,Lee\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def add_source_tables(self, controller: StudioController) -> list[str]:
        ids = []
        for path in (self.sales_path, self.regions_path):
            self.assertTrue(controller._commit_import(path, parse_file(path)))
            ids.append(controller.activeTableId)
        return ids

    def test_merge_kinds_use_ordered_composite_keys_and_never_match_blanks(self) -> None:
        left = ImportCandidate("csv", ["sale", "region", "year"], [
            {"sale": "L1", "region": "East", "year": "2026"},
            {"sale": "L2", "region": "West", "year": "2026"},
            {"sale": "L3", "region": "", "year": "2026"},
            {"sale": "L4", "region": "East", "year": "2027"},
        ], {}, [])
        right = ImportCandidate("csv", ["area", "period", "manager"], [
            {"area": "East", "period": "2026", "manager": "Kim"},
            {"area": "South", "period": "2026", "manager": "Lee"},
            {"area": "", "period": "2026", "manager": "Blank"},
            {"area": "East", "period": "2028", "manager": "Nia"},
        ], {}, [])
        expected_row_counts = {
            "inner": 1,
            "left_outer": 4,
            "right_outer": 4,
            "full_outer": 7,
            "left_anti": 3,
            "right_anti": 3,
        }
        for join_kind, expected_count in expected_row_counts.items():
            with self.subTest(join_kind=join_kind):
                result = merge_candidates(
                    left,
                    right,
                    left_keys=["region", "year"],
                    right_keys=["area", "period"],
                    join_kind=join_kind,
                    right_name="Territory",
                )
                self.assertEqual(result.row_count, expected_count)
                if join_kind == "inner":
                    self.assertEqual(result.rows[0]["manager"], "Kim")
                    self.assertEqual(result.rows[0]["sale"], "L1")
                if join_kind == "left_anti":
                    self.assertEqual(
                        {row["sale"] for row in result.rows}, {"L2", "L3", "L4"}
                    )
                if join_kind == "right_anti":
                    self.assertEqual(
                        {row["manager"] for row in result.rows}, {"Lee", "Blank", "Nia"}
                    )

    def test_merge_dialog_create_save_reopen_and_refresh(self) -> None:
        controller = self.controller("settings.ini")
        source_ids = self.add_source_tables(controller)
        tables = [
            dict(table) for table in controller._table_catalog
            if table.get("sourceId") in source_ids
        ]
        candidates = {
            source_id: controller._loaded_candidates[source_id]
            for source_id in source_ids
        }
        dialog = MergeQueriesDialog(tables, candidates)
        self.assertEqual(len(dialog._key_pair_rows), 1)
        self.assertEqual(dialog._key_pair_rows[0]["left"].currentText(), "region")
        self.assertEqual(dialog._key_pair_rows[0]["right"].currentText(), "region")
        self.assertTrue(dialog.create_button.isEnabled())
        self.assertEqual(dialog.preview.model().rowCount(), 2)

        manager_column = "manager"
        west_column = next(
            header for header in dialog._accepted_candidate.headers
            if header.endswith(".region")
        )
        self.assertEqual(dialog._accepted_candidate.rows[0][manager_column], "Kim")
        self.assertEqual(dialog._accepted_candidate.rows[1][manager_column], "")

        dialog.join_kind_combo.setCurrentIndex(
            dialog.join_kind_combo.findData("inner")
        )
        self.assertEqual(dialog.preview.model().rowCount(), 1)
        dialog.join_kind_combo.setCurrentIndex(
            dialog.join_kind_combo.findData("left_outer")
        )
        dialog.query_name_edit.setText("Sales by region")
        dialog._accept_query()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        definition = dialog.query_definition
        self.assertEqual(definition["operation"], "merge")
        self.assertEqual(definition["source_ids"], source_ids)
        self.assertEqual(definition["left_keys"], ["region"])
        self.assertEqual(definition["right_keys"], ["region"])
        self.assertEqual(definition["join_kind"], "left_outer")

        with (
            patch("analytics_studio.controller.MergeQueriesDialog", return_value=dialog),
            patch.object(dialog, "exec", return_value=QDialog.DialogCode.Accepted),
        ):
            self.assertTrue(controller.merge_queries_dialog())

        query_source = next(
            source for source in controller._project["data_sources"]
            if source.get("kind") == "query"
        )
        query_id = query_source["id"]
        self.assertEqual(query_source["query_definition"], definition)
        self.assertEqual(
            controller._loaded_candidates[query_id].rows[1][manager_column], ""
        )
        self.assertEqual(
            controller._loaded_candidates[query_id].rows[1][west_column], ""
        )

        project_path = self.root / "merge-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.sales_path.write_text(
            "sale_id,region,amount\n1,East,11\n2,West,21\n3,South,31\n",
            encoding="utf-8",
        )
        self.regions_path.write_text(
            "region,manager\nEast,Kira\nWest,Wei\nSouth,Lee\n",
            encoding="utf-8",
        )

        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.activeTableId, query_id)
        reopened_rows = reopened._loaded_candidates[query_id].rows
        self.assertEqual(len(reopened_rows), 3)
        self.assertEqual(reopened_rows[0][manager_column], "Kira")
        self.assertEqual(reopened_rows[1][manager_column], "Wei")

        self.sales_path.write_text(
            "sale_id,region,amount\n1,East,12\n2,West,22\n3,South,32\n",
            encoding="utf-8",
        )
        self.regions_path.write_text(
            "region,manager\nEast,Nia\nWest,Wei\nSouth,Lee\n",
            encoding="utf-8",
        )
        reopened.refresh_all_sources()
        refreshed_rows = reopened._loaded_candidates[query_id].rows
        self.assertEqual(refreshed_rows[0]["amount"], "12")
        self.assertEqual(refreshed_rows[0][manager_column], "Nia")
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
