"""End-to-end controller checks for the Home and File data workflows."""

from __future__ import annotations

import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.import_preview_dialog import FileImportPreviewDialog
from analytics_studio.inline_data import parse_pasted_table, sample_candidate
from analytics_studio.local_table_dialogs import EnterDataDialog, TransformDataDialog
from analytics_studio.project import FORMAT_VERSION
from analytics_studio.transformations import apply_transformations

QQuickStyle.setStyle("Basic")


class HomeFileWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self) -> StudioController:
        return StudioController(self.app, self.settings)

    def test_enter_data_dialog_previews_accepts_and_cancels_without_side_effects(self) -> None:
        dialog = EnterDataDialog(
            replacing=True,
            initial_text="Name\tRevenue\nAda\t12\nLin\t20",
        )
        self.assertTrue(dialog.create_button.isEnabled())
        self.assertEqual(dialog.preview.model().rowCount(), 2)
        self.assertFalse(dialog.replacement_label.isHidden())

        dialog._accept_candidate()

        self.assertEqual(dialog.candidate.kind, "inline")
        self.assertEqual(dialog.candidate.headers, ["Name", "Revenue"])
        self.assertEqual(dialog.candidate.row_count, 2)

        canceled = EnterDataDialog(replacing=False, initial_text="Name\nAda")
        canceled.reject()
        self.assertIsNone(canceled.candidate)

    def test_inline_and_sample_tables_save_reopen_and_do_not_offer_refresh(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(sample_candidate()))
        self.assertTrue(controller.sourceLoaded)
        self.assertFalse(controller.canRefreshSource)
        self.assertEqual(controller._active_source_kind, "inline")
        self.assertEqual(controller.rowCount, sample_candidate().row_count)
        expected_rows = copy.deepcopy(controller._rows)

        path = self.root / "sample.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        self.assertTrue(reopened.sourceLoaded)
        self.assertFalse(reopened.canRefreshSource)
        self.assertEqual(reopened._rows, expected_rows)
        self.assertEqual(reopened._project["format_version"], FORMAT_VERSION)

        pasted = parse_pasted_table("Name,Revenue\nAda,12", name="Manual table")
        self.assertTrue(reopened._commit_inline(pasted))
        self.assertEqual(reopened.sourceName, "Manual table")
        self.assertFalse(reopened.canRefreshSource)

    def test_sample_data_is_deterministic(self) -> None:
        first = sample_candidate()
        second = sample_candidate()
        self.assertEqual(first, second)
        controller = self.controller()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(controller._commit_inline(first))
            self.assertTrue(controller._commit_inline(second))
        self.assertEqual(controller._rows, first.rows)

    def test_home_commands_route_to_their_local_workflows(self) -> None:
        controller = self.controller()
        with (
            patch.object(controller, "enter_data_dialog") as enter,
            patch.object(controller, "load_sample_data") as sample,
            patch.object(controller, "transform_data_dialog") as transform,
            patch.object(controller, "new_measure_dialog") as new_measure,
            patch.object(controller, "quick_measure_dialog") as quick_measure,
            patch.object(controller, "export_data_dialog") as export,
        ):
            controller.executeCommand("enterData")
            controller.executeCommand("pasteData")
            controller.executeCommand("sampleData")
            controller.executeCommand("transformData")
            controller.executeCommand("newMeasure")
            controller.executeCommand("quickMeasure")
            controller.executeCommand("exportData")

        enter.assert_any_call()
        enter.assert_any_call(use_clipboard=True)
        sample.assert_called_once_with()
        transform.assert_called_once_with()
        new_measure.assert_called_once_with()
        quick_measure.assert_called_once_with()
        export.assert_called_once_with()

    def test_transform_data_qml_command_reaches_dialog_and_commits_step(self) -> None:
        controller = self.controller()
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(
            str(Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml")
        ))
        self.assertFalse(component.isError(), "\n".join(
            error.toString() for error in component.errors()
        ))
        window = component.createWithInitialProperties({"studioController": controller})
        self.assertIsNotNone(window, "\n".join(
            error.toString() for error in component.errors()
        ))

        controller.setCurrentView("Data")
        self.app.processEvents()
        self.assertFalse(window.commandAvailable("data.transform"))
        self.assertEqual(
            window.commandUnavailableReason("data.transform"),
            "Load a table before transforming data.",
        )

        source = self.root / "regions.csv"
        source.write_text("Region,Revenue\n East ,12\n West ,20\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        self.app.processEvents()
        self.assertTrue(window.commandAvailable("data.transform"))
        self.assertEqual(window.commandUnavailableReason("data.transform"), "")

        def accept_trim_step(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.operation_combo.setCurrentIndex(
                dialog.operation_combo.findData("trim_text")
            )
            dialog.column_combo.setCurrentText("Region")
            dialog._add_step()
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_trim_step):
            window.runCommand("data.transform")

        self.assertEqual(controller._rows, [
            {"Region": "East", "Revenue": "12"},
            {"Region": "West", "Revenue": "20"},
        ])
        source_record = next(
            item for item in controller._project["data_sources"]
            if item["id"] == controller.activeTableId
        )
        self.assertEqual(source_record["transform_steps"], [
            {"op": "trim_text", "column": "Region"},
        ])

        project = self.root / "transformed.npa"
        self.assertTrue(controller._save_to(project))
        source.write_text(
            "Region,Revenue\n East ,12\n West ,20\n North ,30\n", encoding="utf-8"
        )
        reopened = StudioController(
            self.app,
            QSettings(str(self.root / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        self.assertTrue(reopened.open_project_path(project))
        self.assertEqual(reopened._rows, [
            {"Region": "East", "Revenue": "12"},
            {"Region": "West", "Revenue": "20"},
            {"Region": "North", "Revenue": "30"},
        ])

        window.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_transform_dialog_previews_step_order_and_returns_only_after_accept(self) -> None:
        raw = parse_pasted_table("Region,Revenue\nEast,12\nWest,20")
        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("convert_type")
        )
        dialog.column_combo.setCurrentText("Revenue")
        dialog.option_combo.setCurrentIndex(
            dialog.option_combo.findData("whole_number")
        )
        dialog._add_step()

        self.assertEqual(dialog.preview.model().data(dialog.preview.model().index(0, 1)), "12")
        self.assertEqual(dialog.step_list.count(), 1)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("rename_column")
        )
        dialog.column_combo.setCurrentText("Revenue")
        dialog.value_edit.setText("Sales")
        dialog._add_step()
        self.assertIn("Sales", dialog._preview_candidate.headers)
        dialog._remove_step()
        self.assertIn("Revenue", dialog._preview_candidate.headers)
        dialog._accept_candidate()
        self.assertEqual(
            dialog.steps,
            [{"op": "convert_type", "column": "Revenue", "type": "whole_number"}],
        )
        self.assertEqual(dialog.candidate.rows[0]["Revenue"], "12")

        canceled = TransformDataDialog(raw)
        canceled.reject()
        self.assertIsNone(canceled.candidate)
        self.assertIsNone(canceled.steps)

    def test_transform_steps_persist_replay_on_open_and_refresh(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("Region,Revenue\nEast,12\nWest,20\n", encoding="utf-8")
        controller = self.controller()
        raw = parse_file(source)
        self.assertTrue(controller._commit_import(source, raw))
        steps = [
            {"op": "convert_type", "column": "Revenue", "type": "number"},
            {"op": "filter_rows", "column": "Revenue", "operator": "greater_than", "value": "10"},
            {"op": "sort_rows", "column": "Revenue", "direction": "desc"},
        ]
        transformed = apply_transformations(raw, steps)
        source_id = controller._active_source_id
        self.assertTrue(controller._commit_transform_steps(source_id, steps, transformed))
        self.assertEqual([row["Revenue"] for row in controller._rows], ["20", "12"])

        project_path = self.root / "report.npa"
        self.assertTrue(controller._save_to(project_path))
        source.write_text(
            "Region,Revenue\nEast,12\nWest,20\nNorth,30\nSouth,5\n", encoding="utf-8"
        )
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Revenue"] for row in reopened._rows], ["30", "20", "12"])
        reopened.refresh_source()
        self.assertEqual([row["Revenue"] for row in reopened._rows], ["30", "20", "12"])

    def test_extended_transform_steps_save_reopen_and_replay_after_refresh(self) -> None:
        source = self.root / "sales.csv"
        source.write_text(
            "Name,Region,Sales\nAlice, East ,10\nBob,East,20\nBob,East,20\n",
            encoding="utf-8",
        )
        controller = self.controller()
        raw = parse_file(source)
        self.assertTrue(controller._commit_import(source, raw))
        steps = [
            {"op": "trim_text", "column": "Region"},
            {"op": "replace_value", "column": "Region", "value": "East", "replacement": "Eastern"},
            {"op": "remove_duplicates"},
            {"op": "keep_columns", "columns": ["Region", "Sales"]},
            {"op": "sort_rows", "column": "Sales", "direction": "desc"},
        ]
        transformed = apply_transformations(raw, steps)
        self.assertTrue(controller._commit_transform_steps(
            controller._active_source_id, steps, transformed
        ))
        self.assertEqual(controller._headers, ["Region", "Sales"])
        self.assertEqual(controller._rows, [
            {"Region": "Eastern", "Sales": "20"},
            {"Region": "Eastern", "Sales": "10"},
        ])

        project = self.root / "extended-transform.npa"
        self.assertTrue(controller._save_to(project))
        source.write_text(
            "Name,Region,Sales\nAlice, East ,10\nBob,East,20\nBob,East,20\nCara,West,30\n",
            encoding="utf-8",
        )
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project))
        self.assertEqual(reopened._headers, ["Region", "Sales"])
        self.assertEqual(reopened._rows[0], {"Region": "West", "Sales": "30"})
        reopened.refresh_source()
        self.assertEqual(reopened.rowCount, 3)

    def test_failed_transform_replay_preserves_last_good_state(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("Revenue\n12\n", encoding="utf-8")
        controller = self.controller()
        raw = parse_file(source)
        self.assertTrue(controller._commit_import(source, raw))
        steps = [{"op": "convert_type", "column": "Revenue", "type": "number"}]
        self.assertTrue(controller._commit_transform_steps(
            controller._active_source_id, steps, apply_transformations(raw, steps)
        ))
        rows_before = copy.deepcopy(controller._rows)
        project_before = copy.deepcopy(controller._project)
        dirty_before = controller.dirty
        source.write_text("Revenue\nnot-a-number\n", encoding="utf-8")

        with patch.object(QMessageBox, "critical"):
            controller.refresh_source()

        self.assertEqual(controller._rows, rows_before)
        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller.dirty, dirty_before)
        self.assertIn("Could not refresh", controller.sourceWarning)

    def test_transform_rejects_source_changed_after_preview(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("Revenue\n12\n", encoding="utf-8")
        controller = self.controller()
        previewed = parse_file(source)
        self.assertTrue(controller._commit_import(source, previewed))
        steps = [{"op": "convert_type", "column": "Revenue", "type": "number"}]
        transformed = apply_transformations(previewed, steps)
        rows_before = copy.deepcopy(controller._rows)
        project_before = copy.deepcopy(controller._project)
        dirty_before = controller.dirty
        source.write_text("Revenue\n999\n", encoding="utf-8")

        self.assertFalse(controller._commit_transform_steps(
            controller._active_source_id,
            steps,
            transformed,
            previewed_source=previewed,
        ))

        self.assertEqual(controller._rows, rows_before)
        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller.dirty, dirty_before)
        self.assertIn("source changed", controller.statusMessage)

    def test_recent_source_reopens_preview_and_cancel_preserves_active_data(self) -> None:
        active = self.root / "active.csv"
        recent = self.root / "recent.csv"
        active.write_text("Id\n1\n", encoding="utf-8")
        recent.write_text("Name;Value\nAda;12\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(active, parse_file(active)))
        controller._recent_source_store.add(
            recent, "csv", {"delimiter": ";", "encoding": "utf-8-sig", "has_header": True}
        )
        rows_before = copy.deepcopy(controller._rows)
        source_before = controller._active_source_path

        with patch.object(FileImportPreviewDialog, "exec", return_value=0):
            self.assertFalse(controller.openRecentSource(0))

        self.assertEqual(controller._rows, rows_before)
        self.assertEqual(controller._active_source_path, source_before)
        self.assertEqual(controller.recentSources[0]["path"], str(recent.resolve()))

    def test_missing_recent_source_is_reported_without_replacing_loaded_data(self) -> None:
        active = self.root / "active.csv"
        missing = self.root / "missing.csv"
        active.write_text("Id\n1\n", encoding="utf-8")
        missing.write_text("Id\n2\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(active, parse_file(active)))
        controller._recent_source_store.add(missing, "csv")
        missing.unlink()
        rows_before = copy.deepcopy(controller._rows)

        self.assertFalse(controller.openRecentSource(0))

        self.assertEqual(controller._rows, rows_before)
        self.assertIn("missing", controller.statusMessage.casefold())
        self.assertFalse(controller.recentSources[0]["exists"])

    def test_export_active_transformed_table_to_csv_without_mutating_project(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Name,Revenue\nAda,12\nLin,20", name="Sales")
        ))
        project_before = copy.deepcopy(controller._project)
        dirty_before = controller.dirty
        target = self.root / "exported.csv"

        self.assertTrue(controller.export_data_path(target))

        self.assertEqual(parse_file(target).headers, ["Name", "Revenue"])
        self.assertEqual(parse_file(target).rows, controller._rows)
        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller.dirty, dirty_before)

    def test_save_as_keeps_relative_links_inside_project_and_absolute_links_outside(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("Revenue\n12\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        first_project = self.root / "first.npa"
        self.assertTrue(controller._save_to(first_project))
        self.assertEqual(controller._project["data_sources"][0]["path"], "sales.csv")

        second_project = self.root / "nested" / "second.npa"
        self.assertTrue(controller._save_to(second_project))
        self.assertEqual(
            controller._project["data_sources"][0]["path"], str(source.resolve())
        )
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(second_project))
        self.assertEqual(reopened._rows, [{"Revenue": "12"}])


if __name__ == "__main__":
    unittest.main()
