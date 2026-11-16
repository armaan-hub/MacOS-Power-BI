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

        ws_third = wb.create_sheet("Third")
        ws_third.append(["ColA"])
        ws_third.append(["Val1"])

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

        # The tree children are ["Sales", "Regions", "Third"], in the workbook's sheet order.
        child_names = [root.child(i).text(0) for i in range(root.childCount())]
        self.assertEqual(child_names, ["Sales", "Regions", "Third"])

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

        self.assertEqual(set(dialog.checked_sheets), {"Sales", "Regions", "Third"})
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
        self.assertEqual(table_names, ["Sales", "Regions", "Third"])

    def test_multi_select_loads_only_checked_sheets_not_uncheck_previewed(self) -> None:
        controller = StudioController()

        def select_regions_check_sales_and_third(dialog: FileImportPreviewDialog) -> int:
            self.wait_for_preview(dialog)
            root = dialog.navigator_tree.topLevelItem(0)
            self.assertIsNotNone(root)
            # Select "Regions" to preview it
            regions_item = root.child(1)
            dialog.navigator_tree.itemClicked.emit(regions_item, 0)
            self.wait_for_preview(dialog)

            # Turn multi-select on, check only "Sales" and "Third"
            dialog.navigator_select_multiple.setChecked(True)
            for i in range(root.childCount()):
                item = root.child(i)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if item.text(0) in {"Sales", "Third"}
                    else Qt.CheckState.Unchecked,
                )
            dialog.import_button.click()
            return QDialog.DialogCode.Accepted

        with patch.object(FileImportPreviewDialog, "exec", new=select_regions_check_sales_and_third):
            success = controller.import_excel_path(self.path)
            self.assertTrue(success)

        table_names = [table["name"] for table in controller._project["model"]["tables"]]
        self.assertEqual(table_names, ["Sales", "Third"])

    def test_multi_select_failure_shows_warning_and_returns_false(self) -> None:
        controller = StudioController()

        def select_regions_check_sales_and_third(dialog: FileImportPreviewDialog) -> int:
            self.wait_for_preview(dialog)
            root = dialog.navigator_tree.topLevelItem(0)
            self.assertIsNotNone(root)
            dialog.navigator_select_multiple.setChecked(True)
            for i in range(root.childCount()):
                item = root.child(i)
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if item.text(0) in {"Sales", "Third"}
                    else Qt.CheckState.Unchecked,
                )
            dialog.import_button.click()
            return QDialog.DialogCode.Accepted

        from analytics_studio import controller as controller_module
        orig_parse_file = controller_module.parse_file

        def failing_parse(path, options=None):
            if options and options.get("sheet_name") == "Third":
                raise RuntimeError("Corrupt sheet data")
            return orig_parse_file(path, options=options)

        with (
            patch.object(FileImportPreviewDialog, "exec", new=select_regions_check_sales_and_third),
            patch("analytics_studio.controller.parse_file", side_effect=failing_parse),
            patch("analytics_studio.controller.QMessageBox.warning") as mock_warning,
        ):
            success = controller.import_excel_path(self.path)
            self.assertFalse(success)
            mock_warning.assert_called_once()
            args, _ = mock_warning.call_args
            self.assertEqual(args[1], "Some items were not loaded")
            self.assertIn("Third", args[2])
            self.assertIn("Corrupt sheet data", args[2])

        table_names = [table["name"] for table in controller._project["model"]["tables"]]
        self.assertEqual(table_names, ["Sales"])

    def test_options_frame_hidden_for_excel_and_visible_for_csv(self) -> None:
        excel_dialog = FileImportPreviewDialog(self.path, replacing=False)
        self.wait_for_preview(excel_dialog)
        excel_dialog.show()
        self.app.processEvents()
        self.assertFalse(excel_dialog.options_group.isVisible())
        self.assertTrue(excel_dialog.options_group.isHidden())
        excel_dialog.reject()

        csv_path = self.root / "sample.csv"
        csv_path.write_text("A,B\n1,2\n", encoding="utf-8")
        csv_dialog = FileImportPreviewDialog(csv_path, replacing=False)
        self.wait_for_preview(csv_dialog)
        csv_dialog.show()
        self.app.processEvents()
        self.assertTrue(csv_dialog.options_group.isVisible())
        self.assertFalse(csv_dialog.options_group.isHidden())
        csv_dialog.reject()
