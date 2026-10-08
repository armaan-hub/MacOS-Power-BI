"""Acceptance checks for keeping multiple linked local tables in one project."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file


class MultipleLocalTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self) -> StudioController:
        return StudioController(self.app, self.settings)

    def test_multiple_sources_switch_save_as_refresh_independently_and_reopen(self) -> None:
        sales_path = self.sources / "sales.csv"
        sales_path.write_text("id,revenue\n1,10\n", encoding="utf-8")
        regions_path = self.sources / "regions.csv"
        regions_path.write_text("region,count\nNorth,2\n", encoding="utf-8")

        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        sales_id = controller.activeTableId
        self.assertTrue(controller._commit_import(regions_path, parse_file(regions_path)))
        regions_id = controller.activeTableId

        self.assertNotEqual(sales_id, regions_id)
        self.assertEqual(len(controller._project["data_sources"]), 2)
        self.assertEqual(len(controller._project["model"]["tables"]), 2)
        self.assertEqual(controller._rows, [{"region": "North", "count": "2"}])
        self.assertTrue(controller.selectTable(sales_id))
        self.assertEqual(controller._rows, [{"id": "1", "revenue": "10"}])

        first_save = self.root / "projects" / "working.npa"
        first_save.parent.mkdir()
        self.assertTrue(controller._save_to(first_save))
        save_as = self.root / "archive" / "copy.npa"
        save_as.parent.mkdir()
        self.assertTrue(controller._save_to(save_as))

        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(save_as))
        self.assertEqual(reopened.activeTableId, sales_id)
        self.assertEqual(set(reopened._loaded_candidates), {sales_id, regions_id})
        self.assertEqual(len(reopened.tableCatalog), 2)

        sales_path.write_text("id,revenue\n1,15\n2,20\n", encoding="utf-8")
        regions_path.write_text("region,count\nNorth,3\nSouth,4\n", encoding="utf-8")

        # Refreshing the selected source leaves the other source's last result intact.
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"id": "1", "revenue": "15"},
            {"id": "2", "revenue": "20"},
        ])
        self.assertEqual(
            reopened._loaded_candidates[regions_id].rows,
            [{"region": "North", "count": "2"}],
        )

        self.assertTrue(reopened.selectTable(regions_id))
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"region": "North", "count": "3"},
            {"region": "South", "count": "4"},
        ])
        self.assertEqual(
            reopened._loaded_candidates[sales_id].rows,
            [{"id": "1", "revenue": "15"}, {"id": "2", "revenue": "20"}],
        )

        # Importing the same linked path updates its existing table record.
        self.assertTrue(reopened._commit_import(regions_path, parse_file(regions_path)))
        self.assertEqual(reopened.activeTableId, regions_id)
        self.assertEqual(len(reopened._project["data_sources"]), 2)
        self.assertEqual(len(reopened._project["model"]["tables"]), 2)

        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            self.assertTrue(reopened.removeTable(regions_id))
        self.assertTrue(regions_path.exists())
        self.assertNotIn(regions_id, [
            source["id"] for source in reopened._project["data_sources"]
        ])
        self.assertEqual(reopened.activeTableId, sales_id)

        # A project with one missing linked source still opens its available table.
        regions_path.unlink()
        partial = self.controller()
        with patch.object(QMessageBox, "warning"):
            self.assertTrue(partial.open_project_path(save_as))
        self.assertEqual(partial.activeTableId, sales_id)
        self.assertTrue(partial.sourceLoaded)
        self.assertTrue(any(
            table["sourceId"] == regions_id and not table["loaded"]
            for table in partial.tableCatalog
        ))
        self.assertIn("regions.csv", partial.sourceWarning)


if __name__ == "__main__":
    unittest.main()
