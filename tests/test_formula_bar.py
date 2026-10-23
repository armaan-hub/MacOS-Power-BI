"""Formula bar lifecycle (Python side): draft, validate, commit, cancel for measures and columns."""

from __future__ import annotations

import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.dax_intellisense import apply_completion, complete_formula
from analytics_studio.file_import import parse_file


class FormulaBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "Orders.csv"
        self.source_path.write_text("Quantity,Unit price\n2,12.5\n3,8\n", encoding="utf-8")
        settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.controller = StudioController(self.app, settings)
        self.assertTrue(self.controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        self.bar = self.controller.formulaBar

    def tearDown(self) -> None:
        self.controller._dirty = False
        self.temp_dir.cleanup()

    def measure(self, name: str) -> dict | None:
        return next((item for item in self.controller.modelMeasures if item["name"] == name), None)

    # ---------------------------------------------------------------- new measure

    def test_new_measure_opens_a_draft_with_the_name_selected(self) -> None:
        self.assertFalse(self.bar.active)
        self.assertTrue(self.bar.beginNewMeasure())
        self.assertTrue(self.bar.active)
        self.assertEqual(self.bar.mode, "measure")
        self.assertEqual(self.bar.text, "Measure = ")
        self.assertEqual((self.bar.selectionStart, self.bar.selectionEnd), (0, 7))
        self.assertEqual(self.bar.error, "")
        self.assertEqual(self.bar.tableName, "Orders")
        self.assertIsNone(self.measure("Measure"), "the draft is not in the model until committed")

    def test_default_name_skips_existing_measures(self) -> None:
        self.assertTrue(self.controller.create_measure("Measure", "SUM(Orders[Quantity])"))
        self.bar.beginNewMeasure()
        self.assertEqual(self.bar.text, "Measure 2 = ")
        self.assertEqual((self.bar.selectionStart, self.bar.selectionEnd), (0, 9))

    def test_commit_creates_the_measure_and_it_evaluates(self) -> None:
        self.bar.beginNewMeasure()
        self.bar.setText("Total qty = SUM(Orders[Quantity])")
        self.assertEqual(self.bar.validate(), "")
        self.assertTrue(self.bar.commit())
        self.assertFalse(self.bar.active)
        created = self.measure("Total qty")
        self.assertIsNotNone(created)
        self.assertEqual(created["expression"], "SUM(Orders[Quantity])")
        self.assertEqual(created["value"], "5")
        self.assertEqual(self.bar.lastBinding, "__dax_measure__:Total qty")

    def test_commit_accepts_a_multi_line_formula(self) -> None:
        self.bar.beginNewMeasure()
        self.bar.setText("Total qty =\nVAR q = SUM(Orders[Quantity])\nRETURN q * 2")
        self.assertTrue(self.bar.commit(), self.bar.error)
        self.assertEqual(self.measure("Total qty")["value"], "10")

    def test_engine_error_shows_in_the_banner_and_nothing_is_committed(self) -> None:
        self.bar.beginNewMeasure()
        self.bar.setText("Bad = SUM(Orders[Nope])")
        self.assertFalse(self.bar.commit())
        self.assertTrue(self.bar.active, "a failed commit keeps the formula bar open")
        self.assertIn("Nope", self.bar.error)
        self.assertIsNone(self.measure("Bad"))

    def test_unknown_function_error_is_the_engines_text(self) -> None:
        self.bar.beginNewMeasure()
        self.bar.setText("Bad = DATESWTD(Orders[Quantity])")
        self.assertFalse(self.bar.commit())
        self.assertIn("DATESWTD", self.bar.error)
        self.assertIsNone(self.measure("Bad"))

    def test_text_without_an_equals_sign_is_rejected_with_help(self) -> None:
        self.bar.beginNewMeasure()
        self.bar.setText("SUM(Orders[Quantity])")
        self.assertFalse(self.bar.commit())
        self.assertIn("=", self.bar.error)
        self.assertTrue(self.bar.active)

    def test_empty_expression_is_rejected(self) -> None:
        self.bar.beginNewMeasure()
        self.assertFalse(self.bar.commit())
        self.assertNotEqual(self.bar.error, "")
        self.assertEqual(self.controller.modelMeasures, [])

    def test_duplicate_measure_name_is_rejected(self) -> None:
        self.assertTrue(self.controller.create_measure("Total qty", "SUM(Orders[Quantity])"))
        self.bar.beginNewMeasure()
        self.bar.setText("Total qty = SUM(Orders[Quantity])")
        self.assertFalse(self.bar.commit())
        self.assertIn("already exists", self.bar.error)

    def test_live_validation_sets_and_clears_the_error(self) -> None:
        self.bar.beginNewMeasure()
        self.bar.setText("Total = SUM(Orders[Nope])")
        self.assertIn("Nope", self.bar.validate())
        self.assertIn("Nope", self.bar.error)
        self.bar.setText("Total = SUM(Orders[Quantity])")
        self.assertEqual(self.bar.validate(), "")
        self.assertEqual(self.bar.error, "")
        self.assertIsNone(self.measure("Total"), "validating never changes the model")

    def test_cancel_discards_the_draft(self) -> None:
        self.bar.beginNewMeasure()
        self.bar.setText("Total = SUM(Orders[Quantity])")
        self.bar.cancel()
        self.assertFalse(self.bar.active)
        self.assertEqual(self.bar.text, "")
        self.assertIsNone(self.measure("Total"))

    def test_cannot_begin_without_a_loaded_table(self) -> None:
        controller = StudioController(
            self.app, QSettings(str(self.root / "empty.ini"), QSettings.Format.IniFormat))
        self.assertFalse(controller.formulaBar.beginNewMeasure())
        self.assertFalse(controller.formulaBar.active)
        self.assertIn("table", controller.statusMessage.lower())

    # ---------------------------------------------------------------- edit measure

    def test_edit_existing_measure_renames_and_updates_in_place(self) -> None:
        self.assertTrue(self.controller.create_measure("Total qty", "SUM(Orders[Quantity])"))
        self.assertTrue(self.bar.beginEditMeasure("Total qty"))
        self.assertEqual(self.bar.text, "Total qty = SUM(Orders[Quantity])")
        self.assertFalse(self.bar.isNew)
        self.bar.setText("Quantity sum = SUM(Orders[Quantity]) + 1")
        self.assertTrue(self.bar.commit(), self.bar.error)
        self.assertIsNone(self.measure("Total qty"))
        self.assertEqual(self.measure("Quantity sum")["value"], "6")
        self.assertEqual(len(self.controller.modelMeasures), 1)

    def test_edit_missing_measure_fails(self) -> None:
        self.assertFalse(self.bar.beginEditMeasure("Nope"))
        self.assertFalse(self.bar.active)

    def test_name_box_rewrites_only_the_name(self) -> None:
        self.bar.beginNewMeasure()
        self.bar.setText("Measure = SUM(Orders[Quantity])")
        self.bar.setName("Total qty")
        self.assertEqual(self.bar.text, "Total qty = SUM(Orders[Quantity])")
        self.assertEqual(self.bar.name, "Total qty")

    # ---------------------------------------------------------------- columns

    def test_new_column_commit_adds_a_calculated_column(self) -> None:
        self.assertTrue(self.bar.beginNewColumn())
        self.assertEqual(self.bar.mode, "column")
        self.assertEqual(self.bar.text, "Column = ")
        self.bar.setText("Line total = [Quantity] * [Unit price]")
        self.assertEqual(self.bar.validate(), "")
        self.assertTrue(self.bar.commit(), self.bar.error)
        self.assertFalse(self.bar.active)
        self.assertEqual(self.controller._headers, ["Quantity", "Unit price", "Line total"])
        self.assertEqual([row["Line total"] for row in self.controller._rows],
                         [Decimal("25.0"), Decimal("24")])
        self.assertEqual(self.bar.lastBinding, "Line total")

    def test_bad_column_formula_shows_the_error_and_keeps_the_table(self) -> None:
        self.bar.beginNewColumn()
        self.bar.setText("Bad = [Nope] * 2")
        self.assertFalse(self.bar.commit())
        self.assertTrue(self.bar.active)
        self.assertIn("Nope", self.bar.error)
        self.assertEqual(self.controller._headers, ["Quantity", "Unit price"])

    def test_column_live_validation_does_not_change_the_table(self) -> None:
        self.bar.beginNewColumn()
        self.bar.setText("Line total = [Quantity] * 2")
        self.assertEqual(self.bar.validate(), "")
        self.assertEqual(self.controller._headers, ["Quantity", "Unit price"])

    def test_edit_existing_calculated_column(self) -> None:
        self.bar.beginNewColumn()
        self.bar.setText("Line total = [Quantity] * [Unit price]")
        self.assertTrue(self.bar.commit(), self.bar.error)
        self.assertTrue(self.bar.beginEditColumn("Line total"))
        self.assertEqual(self.bar.text, "Line total = [Quantity] * [Unit price]")
        self.bar.setText("Line total = [Quantity] * [Unit price] + 1")
        self.assertTrue(self.bar.commit(), self.bar.error)
        self.assertEqual([row["Line total"] for row in self.controller._rows],
                         [Decimal("26.0"), Decimal("25")])
        table = self.controller._model_table_for_source(
            self.controller._project, self.controller.activeTableId)
        self.assertEqual(len(table["calculated_columns"]), 1)

    def test_duplicate_column_name_is_rejected(self) -> None:
        self.bar.beginNewColumn()
        self.bar.setText("Line total = [Quantity]")
        self.assertTrue(self.bar.commit())
        self.bar.beginNewColumn()
        self.bar.setText("Line total = [Quantity] + 1")
        self.assertFalse(self.bar.commit())
        self.assertIn("already exists", self.bar.error)

    def test_default_column_name_skips_existing_columns(self) -> None:
        self.bar.beginNewColumn()
        self.bar.setText("Column = [Quantity]")
        self.assertTrue(self.bar.commit())
        self.bar.beginNewColumn()
        self.assertEqual(self.bar.text, "Column 2 = ")

    # ---------------------------------------------------------------- IntelliSense wiring

    def test_completions_use_the_loaded_model(self) -> None:
        self.assertTrue(self.controller.create_measure("Total qty", "SUM(Orders[Quantity])"))
        self.bar.beginNewMeasure()
        text = "Measure = SUM(Orders[Q"
        items = self.bar.completions(text, len(text), False)
        self.assertEqual([item["label"] for item in items], ["Quantity"])
        self.assertEqual(items[0]["kind"], "column")
        types = {item["label"]: item["detail"] for item in self.bar.completions(
            "Measure = Orders[", len("Measure = Orders["), False)}
        self.assertIn("whole", types["Quantity"].lower())
        names = [item["label"] for item in self.bar.completions("Measure = T", 11, False)]
        self.assertIn("Total qty", names)
        self.assertIn("TOTALYTD", names)

    def test_signature_slot_returns_the_active_parameter(self) -> None:
        self.bar.beginNewMeasure()
        text = "Measure = CALCULATE(SUM(Orders[Quantity]), "
        hint = self.bar.signature(text, len(text))
        self.assertEqual(hint["function"], "CALCULATE")
        self.assertEqual(hint["activeParameter"], 1)
        self.assertEqual(self.bar.signature("Measure = 1", 11), {})

    def test_apply_completion_inserts_and_moves_the_caret(self) -> None:
        text = "Measure = d"
        items = complete_formula(text, len(text), {})
        date = next(item for item in items if item["label"] == "DATE")
        self.assertEqual(apply_completion(text, date), ("Measure = DATE(", 15))
        wtd = next(item for item in items if item["label"] == "DATESWTD")
        self.assertIsNone(apply_completion(text, wtd))
        model = {"home_table": "T", "tables": [{"name": "T", "columns": [{"name": "Year", "type": "number"}]}]}
        text = "Measure = SUM(T[Ye"
        column = complete_formula(text, len(text), model)[0]
        self.assertEqual(apply_completion(text, column), ("Measure = SUM(T[Year]", 21))

    def test_apply_completion_slot_refuses_unsupported_functions_with_a_message(self) -> None:
        self.bar.beginNewMeasure()
        text = "Measure = dateswtd"
        item = next(i for i in self.bar.completions(text, len(text), False) if i["label"] == "DATESWTD")
        result = self.bar.applyCompletion(text, item)
        self.assertEqual(result["text"], text)
        self.assertIn("not supported", result["message"].lower())
        ok = next(i for i in self.bar.completions("Measure = datesytd", 18, False)
                  if i["label"] == "DATESYTD")
        accepted = self.bar.applyCompletion("Measure = datesytd", ok)
        self.assertEqual(accepted["text"], "Measure = DATESYTD(")
        self.assertEqual(accepted["caret"], 19)
        self.assertEqual(accepted["message"], "")


if __name__ == "__main__":
    unittest.main()
