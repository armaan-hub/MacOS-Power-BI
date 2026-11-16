from __future__ import annotations

import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidget

from analytics_studio.local_table_dialogs import CustomColumnDialog
from analytics_studio.m_intellisense import complete_m


class TestUX178CustomColumnHelp(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_pure_m_intellisense(self) -> None:
        # complete_m("Text.Up", 7, []) labels start with "Text.Upper"
        res1 = complete_m("Text.Up", 7, [])
        labels1 = [x["label"] for x in res1]
        self.assertTrue(len(labels1) > 0)
        self.assertEqual(labels1[0], "Text.Upper")

        # complete_m("if [", 4, ["Sales Region", "Qty"]) labels == ["Qty", "Sales Region"] with insertText "Qty]"
        res2 = complete_m("if [", 4, ["Sales Region", "Qty"])
        labels2 = [x["label"] for x in res2]
        self.assertEqual(labels2, ["Qty", "Sales Region"])
        self.assertEqual(res2[0]["insertText"], "Qty]")

        # complete_m('"Text.Up', 8, []) == []
        self.assertEqual(complete_m('"Text.Up', 8, []), [])

        # complete_m("", 0, []) == []
        self.assertEqual(complete_m("", 0, []), [])

    def test_dialog_syntax_status_and_completion(self) -> None:
        dialog = CustomColumnDialog(["Quantity", "Product", "Qty"])
        dialog.show()
        self.app.processEvents()

        status_label = dialog.syntax_status_label
        self.assertEqual(status_label.objectName(), "customColumnSyntaxStatus")

        # Set the text if [Qty] > 0 then 1 else 0 and check status reads "No syntax errors have been detected."
        dialog.expression_edit.setPlainText("if [Qty] > 0 then 1 else 0")
        self.assertEqual(status_label.text(), "No syntax errors have been detected.")

        # Set if [Qty] > 0 then 1 else and check the status is not that text and is not empty.
        dialog.expression_edit.setPlainText("if [Qty] > 0 then 1 else")
        self.assertNotEqual(status_label.text(), "No syntax errors have been detected.")
        self.assertTrue(bool(status_label.text().strip()))

        # Type Text.Up with QTest.keyClicks into the editor and check completion popup
        dialog.expression_edit.clear()
        dialog.expression_edit.setFocus()
        self.app.processEvents()

        completion_list = dialog.findChild(QListWidget, "customColumnCompletionList")
        self.assertIsNotNone(completion_list)

        QTest.keyClicks(dialog.expression_edit, "Text.Up")
        self.app.processEvents()

        self.assertTrue(completion_list.isVisible())
        self.assertGreater(completion_list.count(), 0)
        self.assertEqual(completion_list.item(0).text(), "Text.Upper")

        # Press Tab and check the editor text ends with "Text.Upper("
        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Tab)
        self.app.processEvents()
        self.assertTrue(dialog.expression_edit.toPlainText().endswith("Text.Upper("))

        # Press Escape with the popup open and check the dialog is still visible
        dialog.expression_edit.clear()
        QTest.keyClicks(dialog.expression_edit, "Text.Up")
        self.app.processEvents()
        self.assertTrue(completion_list.isVisible())

        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertFalse(completion_list.isVisible())
        self.assertTrue(dialog.isVisible())

        dialog.close()
        dialog.deleteLater()
        self.app.processEvents()

    def test_brackets_inside_strings_do_not_open_column_list(self) -> None:
        labels = [x["label"] for x in complete_m('"a[b" & Text.Up', 15, ["b"])]
        self.assertEqual(labels[0], "Text.Upper")

        self.assertEqual(
            [x["label"] for x in complete_m('"x[" & [Q', 9, ["Qty"])],
            ["Qty"],
        )

    def test_completion_hides_on_focus_out(self) -> None:
        dialog = CustomColumnDialog(["Quantity", "Product", "Qty"])
        dialog.show()
        self.app.processEvents()
        dialog.expression_edit.setFocus()
        self.app.processEvents()
        QTest.keyClicks(dialog.expression_edit, "Text.Up")
        self.app.processEvents()

        completion_list = dialog.findChild(QListWidget, "customColumnCompletionList")
        self.assertIsNotNone(completion_list)
        self.assertTrue(completion_list.isVisible())

        dialog.name_edit.setFocus()
        self.app.processEvents()
        self.assertFalse(completion_list.isVisible())

        dialog.close()
        dialog.deleteLater()
        self.app.processEvents()
