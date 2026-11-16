from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import openpyxl
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import StudioController
from analytics_studio.import_preview_dialog import FileImportPreviewDialog


class NavigatorExcelImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.path = self.root / "sample-workbook.xlsx"
        self._write_workbook()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_workbook(self) -> None:
        wb = openpyxl.Workbook()
        ws_sales = wb.active
        ws_sales.title = "Sales"
        ws_sales.append(["Name", "Amount"])
        ws_sales.append(["Alice", 100])
        ws_sales.append(["Bob", 200])

        ws_regions = wb.create_sheet("Regions")
        ws_regions.append(["Region"])
        ws_regions.append(["North"])
        ws_regions.append(["South"])

        wb.save(self.path)

    def wait_for_preview(self, dialog: FileImportPreviewDialog) -> None:
        deadline = time.monotonic() + 10
        while not dialog.import_button.isEnabled() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(dialog.import_button.isEnabled())

    def test_navigator_window_title_tree_and_preview_selection(self) -> None:
        dialog = FileImportPreviewDialog(self.path, replacing=False)
        self.wait_for_preview(dialog)

        # The window title is "Navigator", and the tree root text starts with the file name.
        self.assertEqual(dialog.windowTitle(), "Navigator")
        root = dialog.navigator_tree.topLevelItem(0)
        self.assertIsNotNone(root)
        self.assertTrue(root.text(0).startswith(self.path.name))

        # The tree children are ["Sales", "Regions"], or in the workbook's sheet order.
        child_names = [root.child(i).text(0) for i in range(root.childCount())]
        self.assertEqual(child_names, ["Sales", "Regions"])

        # Clicking "Regions" sets the navigatorItemTitle text to "Regions", and the preview header contains "Region".
        regions_item = root.child(1)
        self.assertEqual(regions_item.text(0), "Regions")
        dialog.navigator_tree.itemClicked.emit(regions_item, 0)
        self.wait_for_preview(dialog)

        self.assertEqual(dialog.navigator_item_title.text(), "Regions")
        headers = [
            str(dialog.table.model().headerData(c, Qt.Orientation.Horizontal))
            for c in range(dialog.table.model().columnCount())
        ]
        self.assertTrue(any("Region" in h for h in headers), f"Headers {headers} missing 'Region'")

        # The button order is Load, Transform Data, Cancel (by x position).
        dialog.show()
        self.app.processEvents()
        self.assertLess(dialog.import_button.x(), dialog.transform_button.x())
        self.assertLess(dialog.transform_button.x(), dialog.cancel_button.x())

        dialog.reject()

    def test_multi_select_checked_sheets_and_transform_data_disabled(self) -> None:
        dialog = FileImportPreviewDialog(self.path, replacing=False)
        self.wait_for_preview(dialog)

        # With multi-select on and both checked, checked_sheets == both names and Transform Data is disabled.
        dialog.navigator_select_multiple.setChecked(True)
        root = dialog.navigator_tree.topLevelItem(0)
        self.assertIsNotNone(root)
        for i in range(root.childCount()):
            root.child(i).setCheckState(0, Qt.CheckState.Checked)

        self.assertEqual(set(dialog.checked_sheets), {"Sales", "Regions"})
        self.assertFalse(dialog.transform_button.isEnabled())
        self.assertEqual(dialog.transform_button.toolTip(), "Select one item to transform it")

        dialog.reject()

    def test_controller_loading_with_both_checked_creates_two_tables(self) -> None:
        controller = StudioController()

        def accept_multi(dialog: FileImportPreviewDialog) -> int:
            self.wait_for_preview(dialog)
            dialog.navigator_select_multiple.setChecked(True)
            root = dialog.navigator_tree.topLevelItem(0)
            self.assertIsNotNone(root)
            for i in range(root.childCount()):
                root.child(i).setCheckState(0, Qt.CheckState.Checked)
            dialog.import_button.click()
            return QDialog.DialogCode.Accepted

        with patch.object(FileImportPreviewDialog, "exec", new=accept_multi):
            success = controller.import_excel_path(self.path)
            self.assertTrue(success)

        table_names = [table["name"] for table in controller._project["model"]["tables"]]
        self.assertIn("Sales", table_names)
        self.assertIn("Regions", table_names)
        self.assertGreaterEqual(len(table_names), 2)
