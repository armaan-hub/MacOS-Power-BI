"""Custom-column formulas read cells as the column types the model really has (Task 110 follow-up).

Power BI keeps a column's type from step to step and from query to query: a referenced query's text column that
holds "2" stays text, so ``[Units] = 2`` is false there. The answers below were measured on Power BI Desktop
(tools/m_oracle_diff.py, 2026-11-09) over ``#table({"Units","Name"}, {{"2","a"},{"0","b"}})``:

    Units as text (also: number first, then set to text)      Units as Int64
    [Units] = 2        -> false, false                         true, false
    [Units] = "2"      -> true, false                          false, false
    [Units] & "x"      -> "2x", "0x"                           error
    [Units] + 1        -> error                                3, 1
"""

from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from analytics_studio.file_import import ImportCandidate
from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.transformations import TransformationError, apply_transformations

PACKAGE = Path(__file__).resolve().parents[1] / "analytics_studio"


def two_rows() -> ImportCandidate:
    return ImportCandidate(
        "inline", ["Units", "Name"], [{"Units": "2", "Name": "a"}, {"Units": "0", "Name": "b"}], {}, []
    )


def custom(expression: str) -> list[dict]:
    return [{"op": "add_custom_column", "name": "X", "expression": expression}]


class EveryCallSitePassesTypesTests(unittest.TestCase):
    def test_every_apply_transformations_call_in_the_app_passes_initial_types(self) -> None:
        missing = []
        for path in sorted(PACKAGE.glob("*.py")):
            if path.name == "transformations.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", getattr(node.func, "attr", None)) == "apply_transformations"
                    # ``**kwargs`` counts: a helper adds ``initial_types`` whenever the types are known.
                    and not {"initial_types", None} & {keyword.arg for keyword in node.keywords}
                ):
                    missing.append(f"{path.name}:{node.lineno}")
        self.assertEqual(missing, [])


class InitialTypesDecideTheCellsTests(unittest.TestCase):
    def cells(self, expression: str, types: dict[str, str] | None) -> list:
        result = apply_transformations(two_rows(), custom(expression), initial_types=types)
        return [row["X"] for row in result.rows]

    def test_a_text_column_holding_digits_stays_text(self) -> None:
        text = {"Units": "text", "Name": "text"}
        self.assertEqual(self.cells("[Units] = 2", text), ["false", "false"])
        self.assertEqual(self.cells('[Units] = "2"', text), ["true", "false"])
        self.assertEqual(self.cells('[Units] & "x"', text), ["2x", "0x"])
        for cell in self.cells("[Units] + 1", text):
            # Power BI: error. The app: an error cell, or the step refused; never a number.
            self.assertIsInstance(cell, PowerQueryCellError)

    def test_a_whole_number_column_is_a_number(self) -> None:
        numbers = {"Units": "whole_number", "Name": "text"}
        self.assertEqual(self.cells("[Units] = 2", numbers), ["true", "false"])
        self.assertEqual(self.cells('[Units] = "2"', numbers), ["false", "false"])
        self.assertEqual(self.cells("[Units] + 1", numbers), ["3", "1"])

    def test_an_empty_type_map_means_all_text_not_a_guess(self) -> None:
        self.assertEqual(self.cells("[Units] = 2", {}), ["false", "false"])

    def test_a_type_step_before_the_column_decides_the_type(self) -> None:
        steps = [
            {"op": "convert_type", "column": "Units", "type": "whole_number"},
            {"op": "convert_type", "column": "Units", "type": "text"},
            *custom("[Units] = 2"),
        ]
        for types in ({"Units": "text"}, {"Units": "whole_number"}):
            result = apply_transformations(two_rows(), steps, initial_types=types)
            self.assertEqual([row["X"] for row in result.rows], ["false", "false"], types)

    def test_direct_calls_without_types_detect_them_as_a_fresh_import_is_typed(self) -> None:
        self.assertEqual(self.cells("[Units] = 2", None), ["true", "false"])


class RealAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        from PySide6.QtCore import QSettings

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def controller(self):
        from analytics_studio.controller import StudioController

        return StudioController(self.app, self.settings)

    def imported(self):
        from analytics_studio.file_import import parse_file

        path = self.root / "units.csv"
        path.write_text("Name,Units\na,2\nb,0\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(path, parse_file(path)))
        return controller, path

    def add_custom_column(self, dialog, name: str, expression: str) -> None:
        dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("add_custom_column"))
        dialog.value_edit.setText(name)
        dialog.custom_expression_edit.setPlainText(expression)
        dialog._add_step()

    def column(self, controller, source_id: str, name: str) -> list:
        return [row[name] for row in controller._loaded_candidates[source_id].rows]

    def test_a_column_the_user_set_to_text_is_text_for_the_formula_and_after_reopen_and_refresh(self) -> None:
        from unittest.mock import patch

        from PySide6.QtWidgets import QDialog

        from analytics_studio.local_table_dialogs import TransformDataDialog

        controller, path = self.imported()
        source_id = controller._active_source_id
        self.assertTrue(controller.setColumnType("Units", "text"), controller._status_message)

        def accept(dialog: TransformDataDialog) -> QDialog.DialogCode:
            self.add_custom_column(dialog, "IsTwo", "[Units] = 2")
            self.add_custom_column(dialog, "IsTwoText", '[Units] = "2"')
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept):
            self.assertTrue(controller.transform_data_dialog(), controller._status_message)
        self.assertEqual(self.column(controller, source_id, "IsTwo"), ["false", "false"])
        self.assertEqual(self.column(controller, source_id, "IsTwoText"), ["true", "false"])

        project = self.root / "text.npa"
        self.assertTrue(controller._save_to(project))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project))
        self.assertEqual(self.column(reopened, source_id, "IsTwo"), ["false", "false"])
        reopened.refresh_source()
        self.assertEqual(self.column(reopened, source_id, "IsTwo"), ["false", "false"])
        self.assertEqual(self.column(reopened, source_id, "IsTwoText"), ["true", "false"])

    def test_a_referenced_query_keeps_the_upstream_text_type(self) -> None:
        from unittest.mock import patch

        from PySide6.QtWidgets import QDialog

        from analytics_studio.local_table_dialogs import TransformDataDialog

        controller, path = self.imported()
        source_id = controller._active_source_id
        # The upstream query turns Units into text, so its output holds "2" as text.
        self.assertTrue(controller.setColumnType("Units", "text"), controller._status_message)
        created: dict[str, str] = {}

        def accept(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog._create_reference_query()
            created["id"] = dialog._active_query_id
            self.assertEqual(dialog._query_states[created["id"]]["source_column_types"]["Units"], "text")
            self.add_custom_column(dialog, "IsTwo", "[Units] = 2")
            self.add_custom_column(dialog, "IsTwoText", '[Units] = "2"')
            self.add_custom_column(dialog, "Joined", '[Units] & "x"')
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept):
            self.assertTrue(controller.transform_data_dialog(), controller._status_message)
        reference_id = created["id"]
        self.assertEqual(self.column(controller, reference_id, "IsTwo"), ["false", "false"])
        self.assertEqual(self.column(controller, reference_id, "IsTwoText"), ["true", "false"])
        self.assertEqual(self.column(controller, reference_id, "Joined"), ["2x", "0x"])

        project = self.root / "reference.npa"
        self.assertTrue(controller._save_to(project))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project))
        self.assertEqual(self.column(reopened, reference_id, "IsTwo"), ["false", "false"])
        path.write_text("Name,Units\na,2\nb,0\nc,5\n", encoding="utf-8")
        reopened.refresh_all_sources()
        self.assertEqual(self.column(reopened, reference_id, "IsTwo"), ["false", "false", "false"])
        self.assertEqual(self.column(reopened, reference_id, "IsTwoText"), ["true", "false", "false"])
        self.assertEqual(self.column(reopened, reference_id, "Joined"), ["2x", "0x", "5x"])

    def test_a_referenced_number_column_stays_a_number(self) -> None:
        from unittest.mock import patch

        from PySide6.QtWidgets import QDialog

        from analytics_studio.local_table_dialogs import TransformDataDialog

        controller, path = self.imported()
        created: dict[str, str] = {}

        def accept(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog._create_reference_query()
            created["id"] = dialog._active_query_id
            self.assertEqual(dialog._query_states[created["id"]]["source_column_types"]["Units"], "whole_number")
            self.add_custom_column(dialog, "IsTwo", "[Units] = 2")
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept):
            self.assertTrue(controller.transform_data_dialog(), controller._status_message)
        self.assertEqual(self.column(controller, created["id"], "IsTwo"), ["true", "false"])


if __name__ == "__main__":
    unittest.main()
