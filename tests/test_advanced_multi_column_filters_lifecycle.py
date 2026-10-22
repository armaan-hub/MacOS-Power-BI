"""Acceptance checks for advanced multi-column filters."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QToolButton,
)
from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.power_query_m import parse_m_script, steps_to_m_script
from analytics_studio.transformations import MAX_FILTER_CLAUSES, apply_transformations


class AdvancedMultiColumnFiltersLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "sales.csv"
        self.source_path.write_text(
            "Region,Amount,Status,Id\n"
            "East,100,Open,1\nEast,50,Closed,2\nWest,100,Closed,3\n"
            "North,80,Open,4\nEast,80,Closed,5\nSouth,120,Open,6\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def add_clause(
        dialog: TransformDataDialog,
        column: str,
        operator: str,
        value: str,
        join: str,
    ) -> None:
        dialog.column_combo.setCurrentText(column)
        dialog.option_combo.setCurrentIndex(dialog.option_combo.findData(operator))
        dialog.value_edit.setText(value)
        dialog.advanced_filter_join_combo.setCurrentIndex(
            dialog.advanced_filter_join_combo.findData(join)
        )
        dialog._add_advanced_filter_clause()

    def test_and_binds_before_or_across_columns_and_replays(self) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("filter_rows_advanced")
        )
        self.add_clause(dialog, "Region", "equals", "East", "and")
        self.add_clause(dialog, "Amount", "greater_than_or_equal", "80", "and")
        self.add_clause(dialog, "Status", "equals", "Open", "or")
        dialog._add_step()
        self.assertEqual([row["Id"] for row in dialog._preview_candidate.rows], [
            "1", "4", "5", "6",
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "advanced-filter-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Region,Amount,Status,Id\n"
            "East,50,Closed,7\nEast,80,Closed,8\nWest,120,Open,9\n"
            "West,75,Closed,10\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Id"] for row in reopened._rows], ["8", "9"])

        self.source_path.write_text(
            "Region,Amount,Status,Id\n"
            "North,80,Open,11\nEast,70,Closed,12\nSouth,90,Closed,13\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual([row["Id"] for row in reopened._rows], ["11"])

    def test_header_value_filter_inserts_after_selected_step_and_replays_after_refresh(
        self,
    ) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = str(controller.activeTableId)
        base_steps = [
            {
                "op": "filter_rows",
                "column": "Status",
                "operator": "equals",
                "value": "Open",
            },
            {
                "op": "rename_column",
                "column": "Region",
                "new_name": "Territory",
            },
            {
                "op": "filter_rows",
                "column": "Territory",
                "operator": "equals",
                "value": "East",
            },
        ]
        initial_candidate = apply_transformations(raw, base_steps)
        self.assertTrue(controller._commit_transform_steps(
            source_id, base_steps, initial_candidate, previewed_source=raw
        ))
        modal_state: dict[str, TransformDataDialog] = {}
        callback_errors: list[Exception] = []
        expected_step = {
            "op": "filter_rows_advanced",
            "clauses": [
                {
                    "column": "Region",
                    "operator": "equals",
                    "value": "East",
                    "join": "and",
                },
                {
                    "column": "Region",
                    "operator": "equals",
                    "value": "North",
                    "join": "or",
                },
            ],
        }
        original_metadata = [
            {
                "name": "Open rows",
                "description": "Keep rows whose status is open.",
            },
            {
                "name": "Region to territory",
                "description": "Rename the selected region for reporting.",
            },
            {
                "name": "East territory only",
                "description": "Keep the East territory in the final output.",
            },
        ]
        expected_steps = [base_steps[0], expected_step, *base_steps[1:]]
        expected_metadata = [
            original_metadata[0], {}, original_metadata[1], original_metadata[2]
        ]

        def abort_modal() -> None:
            popup = QApplication.activePopupWidget()
            if popup is not None:
                popup.close()
            visible_dialogs = [
                widget for widget in QApplication.topLevelWidgets()
                if isinstance(widget, QDialog) and widget.isVisible()
            ]
            for dialog in reversed(visible_dialogs):
                dialog.reject()

        def guarded(callback) -> None:
            try:
                callback()
            except Exception as exc:
                callback_errors.append(exc)
                abort_modal()

        def drive_value_filter() -> None:
            value_dialogs = [
                widget for widget in QApplication.topLevelWidgets()
                if isinstance(widget, QDialog)
                and widget.isVisible()
                and widget.objectName() == "powerQueryValueFilterDialog"
            ]
            self.assertEqual(len(value_dialogs), 1)
            value_dialog = value_dialogs[0]
            self.assertIsInstance(value_dialog, QDialog)
            assert isinstance(value_dialog, QDialog)

            select_all = value_dialog.findChild(
                QCheckBox, "powerQueryValueFilterSelectAll"
            )
            search_edit = value_dialog.findChild(
                QLineEdit, "powerQueryValueFilterSearch"
            )
            value_list = value_dialog.findChild(
                QListWidget, "powerQueryValueFilterList"
            )
            apply_button = value_dialog.findChild(
                QPushButton, "applyPowerQueryValueFilterButton"
            )
            self.assertIsNotNone(select_all)
            self.assertIsNotNone(search_edit)
            self.assertIsNotNone(value_list)
            self.assertIsNotNone(apply_button)
            assert select_all is not None
            assert search_edit is not None
            assert value_list is not None
            assert apply_button is not None
            self.assertEqual(
                [value_list.item(index).text() for index in range(value_list.count())],
                ["East", "North", "South"],
            )
            self.assertEqual(
                select_all.checkState(), Qt.CheckState.Checked,
                "the fixture has fewer than 64 distinct Region values",
            )

            # Search narrows Select All to visible values; hidden selections survive.
            search_edit.setText("East")
            self.app.processEvents()
            self.assertFalse(value_list.findItems(
                "East", Qt.MatchFlag.MatchExactly
            )[0].isHidden())
            self.assertTrue(value_list.findItems(
                "North", Qt.MatchFlag.MatchExactly
            )[0].isHidden())
            self.assertTrue(value_list.findItems(
                "South", Qt.MatchFlag.MatchExactly
            )[0].isHidden())
            QTest.mouseClick(
                select_all,
                Qt.MouseButton.LeftButton,
                pos=QPoint(8, select_all.height() // 2),
            )
            self.assertEqual(
                value_dialog.selected_values(), ["North", "South"]
            )
            self.assertEqual(select_all.checkState(), Qt.CheckState.Unchecked)

            search_edit.clear()
            self.app.processEvents()
            self.assertEqual(
                value_dialog.selected_values(), ["North", "South"]
            )
            self.assertEqual(select_all.checkState(), Qt.CheckState.PartiallyChecked)

            # Partial selection restores all visible values; the next click clears them.
            QTest.mouseClick(
                select_all,
                Qt.MouseButton.LeftButton,
                pos=QPoint(8, select_all.height() // 2),
            )
            self.assertEqual(
                value_dialog.selected_values(), ["East", "North", "South"]
            )
            self.assertEqual(select_all.checkState(), Qt.CheckState.Checked)
            QTest.mouseClick(
                select_all,
                Qt.MouseButton.LeftButton,
                pos=QPoint(8, select_all.height() // 2),
            )
            self.assertEqual(value_dialog.selected_values(), [])
            self.assertEqual(select_all.checkState(), Qt.CheckState.Unchecked)

            # Clicking from the unchecked state selects every visible value.
            QTest.mouseClick(
                select_all,
                Qt.MouseButton.LeftButton,
                pos=QPoint(8, select_all.height() // 2),
            )
            self.assertEqual(
                value_dialog.selected_values(), ["East", "North", "South"]
            )
            self.assertEqual(select_all.checkState(), Qt.CheckState.Checked)
            QTest.mouseClick(
                select_all,
                Qt.MouseButton.LeftButton,
                pos=QPoint(8, select_all.height() // 2),
            )
            self.assertEqual(value_dialog.selected_values(), [])
            self.assertEqual(select_all.checkState(), Qt.CheckState.Unchecked)

            for value in ("East", "North"):
                items = value_list.findItems(value, Qt.MatchFlag.MatchExactly)
                self.assertEqual(len(items), 1)
                item = items[0]
                value_list.setCurrentItem(item)
                value_list.setFocus()
                QTest.keyClick(value_list, Qt.Key.Key_Space)
                self.assertEqual(item.checkState(), Qt.CheckState.Checked)

            self.assertEqual(select_all.checkState(), Qt.CheckState.PartiallyChecked)
            QTest.mouseClick(
                select_all,
                Qt.MouseButton.LeftButton,
                pos=QPoint(8, select_all.height() // 2),
            )
            self.assertEqual(
                value_dialog.selected_values(), ["East", "North", "South"]
            )
            self.assertEqual(select_all.checkState(), Qt.CheckState.Checked)
            QTest.mouseClick(
                select_all,
                Qt.MouseButton.LeftButton,
                pos=QPoint(8, select_all.height() // 2),
            )
            self.assertEqual(value_dialog.selected_values(), [])
            self.assertEqual(select_all.checkState(), Qt.CheckState.Unchecked)
            for value in ("East", "North"):
                item = value_list.findItems(value, Qt.MatchFlag.MatchExactly)[0]
                value_list.setCurrentItem(item)
                value_list.setFocus()
                QTest.keyClick(value_list, Qt.Key.Key_Space)
                self.assertEqual(item.checkState(), Qt.CheckState.Checked)

            self.assertEqual(value_dialog.selected_values(), ["East", "North"])
            self.assertTrue(apply_button.isEnabled())
            QTest.mouseClick(apply_button, Qt.MouseButton.LeftButton)

        class DeterministicPreviewMenu(QMenu):
            def exec(self, *args, **kwargs):
                matching = [
                    action for action in self.actions()
                    if action.text() == "Filter by values…"
                ]
                if len(matching) != 1:
                    return super().exec(*args, **kwargs)
                QTimer.singleShot(0, lambda: guarded(drive_value_filter))
                return matching[0]

        def drive_session() -> None:
            sessions = [
                widget for widget in QApplication.topLevelWidgets()
                if isinstance(widget, TransformDataDialog) and widget.isVisible()
            ]
            self.assertEqual(len(sessions), 1)
            session = sessions[0]
            self.assertIsInstance(session, TransformDataDialog)
            assert isinstance(session, TransformDataDialog)
            modal_state["session"] = session
            session.show()
            self.app.processEvents()
            for index, metadata in enumerate(original_metadata):
                session._edit_selected_step_metadata(
                    index,
                    name=metadata["name"],
                    description=metadata["description"],
                )
            session.step_list.setCurrentRow(0)
            self.app.processEvents()
            self.assertEqual(
                [row["Id"] for row in session._selected_preview_candidate().rows],
                ["1", "4", "6"],
            )
            region_buttons = [
                button
                for button in session.preview_header._filter_buttons
                if button.isVisible()
                and button.property("logicalIndex") == 0
                and button.accessibleName() == "Sort and filter Region"
            ]
            self.assertEqual(len(region_buttons), 1)
            QTest.mouseClick(
                region_buttons[0],
                Qt.MouseButton.LeftButton,
                pos=region_buttons[0].rect().center(),
            )

            if callback_errors or not session.isVisible():
                return
            self.assertTrue(session._steps)
            self.assertEqual(session._steps, expected_steps)
            self.assertEqual(session._step_metadata, expected_metadata)
            self.assertEqual(session.step_list.currentRow(), 1)
            self.assertEqual(
                [row["Id"] for row in session._preview_candidate.rows],
                ["1"],
            )
            self.assertEqual(
                session._preview_candidate.headers,
                ["Territory", "Amount", "Status", "Id"],
            )
            selected_candidate = session._selected_preview_candidate()
            self.assertIn("Region", selected_candidate.headers)
            self.assertEqual(
                [row["Id"] for row in selected_candidate.rows], ["1", "4"]
            )
            preview_model = session.preview.model()
            visible_headers = [
                preview_model.headerData(index, Qt.Orientation.Horizontal)
                for index in range(preview_model.columnCount())
            ]
            self.assertEqual(visible_headers, selected_candidate.headers)
            id_column = visible_headers.index("Id")
            visible_ids = [
                preview_model.data(preview_model.index(row, id_column))
                for row in range(preview_model.rowCount())
            ]
            self.assertEqual(visible_ids, ["1", "4"])
            close_and_load = session.findChild(
                QToolButton, "powerQueryCloseApplyButton"
            )
            self.assertIsNotNone(close_and_load)
            assert close_and_load is not None
            self.assertTrue(close_and_load.isVisible())
            self.assertTrue(close_and_load.isEnabled())
            QTest.mouseClick(
                close_and_load,
                Qt.MouseButton.LeftButton,
                pos=QPoint(8, close_and_load.height() // 2),
            )

        QTimer.singleShot(0, lambda: guarded(drive_session))

        def close_stuck_dialogs() -> None:
            visible_dialogs = [
                widget for widget in QApplication.topLevelWidgets()
                if isinstance(widget, QDialog) and widget.isVisible()
            ]
            if visible_dialogs:
                callback_errors.append(AssertionError(
                    "The Power Query modal flow did not finish within five seconds; "
                    f"dialogs={[(type(widget).__name__, widget.objectName(), widget.windowTitle()) for widget in visible_dialogs]!r}; "
                    f"popup={None if QApplication.activePopupWidget() is None else QApplication.activePopupWidget().objectName()!r}"
                ))
                abort_modal()

        watchdog_timer = QTimer(self.app)
        watchdog_timer.setSingleShot(True)
        watchdog_timer.timeout.connect(close_stuck_dialogs)
        watchdog_timer.start(5000)
        with patch(
            "analytics_studio.local_table_dialogs.QMenu",
            DeterministicPreviewMenu,
        ):
            try:
                accepted = controller.transform_data_dialog()
            finally:
                watchdog_timer.stop()

        self.assertEqual(callback_errors, [])
        self.assertTrue(accepted, controller.statusMessage)
        session = modal_state["session"]
        self.assertEqual(session.steps, expected_steps)
        source_record = next(
            item for item in controller._project["data_sources"]
            if item.get("id") == source_id
        )
        self.assertEqual(source_record["transform_steps"], expected_steps)
        self.assertEqual(source_record["step_metadata"], expected_metadata)
        self.assertEqual([row["Id"] for row in controller._rows], ["1"])
        self.assertEqual(
            list(controller._rows[0]), ["Territory", "Amount", "Status", "Id"]
        )
        m_script = steps_to_m_script(expected_steps, "sales")
        self.assertEqual(parse_m_script(m_script, "sales"), expected_steps)

        project_path = self.root / "header-value-filter-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Region,Amount,Status,Id\n"
            "East,50,Open,7\nNorth,45,Open,8\nEast,60,Closed,9\n"
            "West,35,Open,10\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        reopened_source = next(
            item for item in reopened._project["data_sources"]
            if item.get("id") == source_id
        )
        self.assertEqual(reopened_source["transform_steps"], expected_steps)
        self.assertEqual(reopened_source["step_metadata"], expected_metadata)
        self.assertEqual([row["Id"] for row in reopened._rows], ["7"])

        self.source_path.write_text(
            "Region,Amount,Status,Id\n"
            "North,45,Open,11\nEast,55,Open,12\nEast,70,Closed,13\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        refreshed_source = next(
            item for item in reopened._project["data_sources"]
            if item.get("id") == source_id
        )
        self.assertEqual(refreshed_source["transform_steps"], expected_steps)
        self.assertEqual(refreshed_source["step_metadata"], expected_metadata)
        self.assertEqual([row["Id"] for row in reopened._rows], ["12"])

    def test_ui_enforces_the_64_clause_limit(self) -> None:
        raw = parse_file(self.source_path)
        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("filter_rows_advanced")
        )
        for index in range(MAX_FILTER_CLAUSES):
            self.add_clause(
                dialog,
                "Region",
                "equals",
                "East",
                "and" if index == 0 else "or",
            )
        self.assertEqual(len(dialog._filter_clauses), 64)

        self.add_clause(dialog, "Region", "equals", "East", "or")

        self.assertEqual(len(dialog._filter_clauses), 64)
        self.assertIn("at most 64 clauses", dialog.error_label.text())
        dialog._add_step()
        self.assertEqual([row["Id"] for row in dialog._preview_candidate.rows], [
            "1", "2", "5",
        ])
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
