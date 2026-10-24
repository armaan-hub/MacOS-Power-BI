"""Critic I9: an unsaved formula-bar draft is never dropped silently."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file

SAVE = QMessageBox.StandardButton.Save
DISCARD = QMessageBox.StandardButton.Discard
CANCEL = QMessageBox.StandardButton.Cancel


class DraftGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        source = self.root / "Orders.csv"
        source.write_text("Quantity,Unit price\n2,12.5\n3,8\n", encoding="utf-8")
        settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.controller = StudioController(self.app, settings)
        self.assertTrue(self.controller._commit_import(source, parse_file(source)))
        self.assertTrue(self.controller.create_measure("Other", "SUM(Orders[Quantity])"))
        self.bar = self.controller.formulaBar

    def tearDown(self) -> None:
        self.controller._dirty = False
        self.temp_dir.cleanup()

    def dirty_draft(self) -> None:
        self.assertTrue(self.bar.beginNewMeasure())
        self.bar.setText("Draft = SUM(Orders[Unit price])")
        self.assertTrue(self.bar.dirty)

    def ask(self, *answers):
        return patch.object(QMessageBox, "question", side_effect=list(answers))

    # ------------------------------------------------------------ switching

    def test_cancel_keeps_the_draft_when_editing_another_measure(self) -> None:
        self.dirty_draft()
        with self.ask(CANCEL) as ask:
            self.assertFalse(self.bar.beginEditMeasure("Other"))
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(self.bar.text, "Draft = SUM(Orders[Unit price])")
        self.assertTrue(self.bar.dirty)

    def test_escape_asks_and_keeps_a_dirty_draft(self) -> None:
        """Escape and the X button call cancel(): a dirty draft is kept on Cancel, dropped on Discard, committed on Save."""
        self.dirty_draft()
        with self.ask(CANCEL) as ask:
            self.bar.cancel()
        self.assertEqual(ask.call_count, 1)
        self.assertTrue(self.bar.active)
        self.assertEqual(self.bar.text, "Draft = SUM(Orders[Unit price])")
        with self.ask(DISCARD):
            self.bar.cancel()
        self.assertFalse(self.bar.active)
        self.dirty_draft()
        with self.ask(SAVE):
            self.bar.cancel()
        self.assertIn("Draft", [m["name"] for m in self.controller.modelMeasures])

    def test_escape_closes_a_clean_bar_without_asking(self) -> None:
        self.assertTrue(self.bar.beginNewMeasure())
        self.assertFalse(self.bar.dirty)
        with self.ask() as ask:
            self.bar.cancel()
        self.assertEqual(ask.call_count, 0)
        self.assertFalse(self.bar.active)

    def test_discard_opens_the_other_measure(self) -> None:
        self.dirty_draft()
        with self.ask(DISCARD):
            self.assertTrue(self.bar.beginEditMeasure("Other"))
        self.assertEqual(self.bar.originalName, "Other")
        self.assertFalse(self.bar.dirty)

    def test_save_commits_the_draft_then_switches(self) -> None:
        self.dirty_draft()
        with self.ask(SAVE):
            self.assertTrue(self.bar.beginEditMeasure("Other"))
        names = [m["name"] for m in self.controller.modelMeasures]
        self.assertIn("Draft", names)
        self.assertEqual(self.bar.originalName, "Other")

    def test_save_of_an_invalid_draft_keeps_it_open_with_the_error(self) -> None:
        self.assertTrue(self.bar.beginNewMeasure())
        self.bar.setText("Bad = SUM(Orders[Nope])")
        with self.ask(SAVE):
            self.assertFalse(self.bar.beginEditMeasure("Other"))
        self.assertEqual(self.bar.text, "Bad = SUM(Orders[Nope])")
        self.assertNotEqual(self.bar.error, "")

    def test_new_measure_and_new_column_also_ask(self) -> None:
        self.dirty_draft()
        with self.ask(CANCEL, CANCEL) as ask:
            self.assertFalse(self.bar.beginNewMeasure())
            self.assertFalse(self.bar.beginNewColumn())
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(self.bar.mode, "measure")
        self.assertTrue(self.bar.dirty)

    def test_edit_column_while_dirty_asks(self) -> None:
        self.assertEqual(
            self.controller.save_calculated_column("Dbl", "Orders[Quantity]*2", ""), "")
        self.dirty_draft()
        with self.ask(CANCEL) as ask:
            self.assertFalse(self.bar.beginEditColumn("Dbl"))
        self.assertEqual(ask.call_count, 1)
        self.assertTrue(self.bar.dirty)

    def test_a_clean_bar_never_asks(self) -> None:
        self.assertTrue(self.bar.beginNewMeasure())  # untouched default text is not dirty
        with self.ask() as ask:
            self.assertTrue(self.bar.beginEditMeasure("Other"))
            self.assertTrue(self.bar.beginNewColumn())
        ask.assert_not_called()

    def test_preview_never_replaces_a_dirty_draft(self) -> None:
        self.dirty_draft()
        with self.ask() as ask:
            self.assertFalse(self.bar.previewMeasure("Other"))
        ask.assert_not_called()
        self.assertEqual(self.bar.text, "Draft = SUM(Orders[Unit price])")

    # ------------------------------------------------------------ project level

    def test_new_project_asks_and_cancel_keeps_project_and_draft(self) -> None:
        self.controller._dirty = False
        self.dirty_draft()
        with self.ask(CANCEL) as ask:
            self.controller.new_project_dialog()
        self.assertEqual(ask.call_count, 1)
        self.assertTrue(self.bar.dirty)
        self.assertTrue(self.controller.sourceLoaded)

    def test_new_project_discard_resets_the_bar(self) -> None:
        self.controller._dirty = False
        self.dirty_draft()
        with self.ask(DISCARD):
            self.controller.new_project_dialog()
        self.assertFalse(self.bar.active)
        self.assertEqual(self.bar.text, "")
        self.assertFalse(self.bar.commit())

    def test_replace_with_new_project_always_resets_the_bar(self) -> None:
        self.dirty_draft()
        self.controller._replace_with_new_project()
        self.assertFalse(self.bar.active)
        self.assertEqual(self.bar.text, "")
        self.assertFalse(self.bar.dirty)

    def test_quit_and_close_ask_about_the_draft(self) -> None:
        self.controller._dirty = False
        self.dirty_draft()
        with self.ask(CANCEL) as ask:
            self.assertFalse(self.controller.confirmClose())
        self.assertEqual(ask.call_count, 1)
        self.assertTrue(self.bar.dirty)
        with self.ask(DISCARD):
            self.assertTrue(self.controller.confirmClose())

    def test_open_project_asks_about_the_draft(self) -> None:
        self.controller._dirty = False
        self.dirty_draft()
        with self.ask(CANCEL) as ask:
            self.assertFalse(self.controller.open_project_path(self.root / "x.npa"))
        self.assertEqual(ask.call_count, 1)
        self.assertTrue(self.bar.dirty)

    # ------------------------------------------------------------ name box / home table

    def test_name_box_refuses_an_equals_sign(self) -> None:
        self.assertTrue(self.bar.beginNewMeasure())
        before = self.bar.text
        self.bar.setName("A = B")
        self.assertEqual(self.bar.text, before)
        self.assertIn("equals sign", self.bar.error)

    def test_refused_home_table_move_keeps_the_old_home(self) -> None:
        second = self.root / "Regions.csv"
        second.write_text("Region,Target\nEast,5\n", encoding="utf-8")
        self.assertTrue(self.controller._commit_import(second, parse_file(second)))
        self.assertTrue(self.bar.beginEditMeasure("Other"))
        old = self.bar.homeTableId
        tables = [t for t in self.controller._table_catalog if str(t.get("id")) != old]
        self.assertTrue(tables)
        with patch.object(self.controller, "update_measure", return_value=False):
            self.bar.setHomeTable(str(tables[0]["id"]))
        self.assertEqual(self.bar.homeTableId, old)


if __name__ == "__main__":
    unittest.main()
