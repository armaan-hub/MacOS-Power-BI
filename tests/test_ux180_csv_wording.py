from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

from PySide6.QtWidgets import QApplication, QFormLayout

from analytics_studio.import_preview_dialog import FileImportPreviewDialog


class CsvWordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.path = self.root / "sample-semicolon.csv"
        self.path.write_text("Name;Amount\nAlice;10\nBob;20\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def wait_for_preview(self, dialog: FileImportPreviewDialog) -> None:
        deadline = time.monotonic() + 10
        while not dialog.import_button.isEnabled() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(dialog.import_button.isEnabled())

    def test_encoding_row_uses_file_origin_wording(self) -> None:
        dialog = FileImportPreviewDialog(self.path, replacing=False)
        self.addCleanup(dialog.deleteLater)
        self.wait_for_preview(dialog)

        # The encoding combo is labelled "File Origin", and no form row says "Encoding".
        self.assertEqual(
            dialog.options_form.labelForField(dialog.encoding_combo).text(),
            "File Origin",
        )
        row_labels = []
        for row in range(dialog.options_form.rowCount()):
            item = dialog.options_form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item is None:
                continue
            label = item.widget()
            if label is not None and hasattr(label, "text"):
                row_labels.append(label.text())
        self.assertNotIn("Encoding", row_labels)

        # The first encoding option carries Power BI's code-page wording.
        self.assertEqual(
            dialog.encoding_combo.itemText(0), "65001: Unicode (UTF-8)"
        )
        self.assertEqual(dialog.encoding_combo.currentData(), "utf-8-sig")

        dialog.reject()

    def test_delimiter_options_include_colon(self) -> None:
        dialog = FileImportPreviewDialog(self.path, replacing=False)
        self.addCleanup(dialog.deleteLater)
        self.wait_for_preview(dialog)

        delimiter_labels = [
            dialog.delimiter_combo.itemText(i)
            for i in range(dialog.delimiter_combo.count())
        ]
        for expected in ("Comma", "Semicolon", "Tab", "Colon"):
            self.assertIn(expected, delimiter_labels)

        dialog.reject()

    def test_semicolon_selection_splits_preview_into_two_columns(self) -> None:
        dialog = FileImportPreviewDialog(self.path, replacing=False)
        self.addCleanup(dialog.deleteLater)
        self.wait_for_preview(dialog)

        self.assertEqual(dialog.table.model().columnCount(), 1)

        dialog.delimiter_combo.setCurrentIndex(
            dialog.delimiter_combo.findData(";")
        )
        self.app.processEvents()
        self.wait_for_preview(dialog)

        self.assertEqual(dialog.table.model().columnCount(), 2)

        dialog.reject()


if __name__ == "__main__":
    unittest.main()
