"""Acceptance tests for Append and Merge from the Power Query session."""

from __future__ import annotations

import copy
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QToolButton

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.folder_import import default_folder_options, parse_folder
from analytics_studio.local_table_dialogs import (
    AppendQueriesDialog,
    ManageQueryParametersDialog,
    MergeQueriesDialog,
    TransformDataDialog,
)
from analytics_studio.power_query_m import (
    PowerQueryMEditorDialog,
    parse_m_script,
    steps_to_m_script,
)
from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.project import validate_project
from analytics_studio.sql_server_credentials import CredentialStoreError, credential_account
from analytics_studio.query_engine import append_candidates, merge_candidates
from analytics_studio.transformations import apply_transformations


class PowerQuerySessionCombineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str = "settings.ini") -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def add_file_sources(self, controller: StudioController) -> list[str]:
        paths = [self.root / "north.csv", self.root / "south.csv"]
        paths[0].write_text(
            "id,Region,Amount\n1,North,10\n2,West,20\n", encoding="utf-8"
        )
        paths[1].write_text(
            "id,Region,Amount\n1,South,30\n3,South,40\n", encoding="utf-8"
        )
        source_ids: list[str] = []
        for path in paths:
            self.assertTrue(controller._commit_import(path, parse_file(path)))
            source_ids.append(controller.activeTableId)
        return source_ids

    def staged_file_source(
        self, path: Path, candidate: ImportCandidate, name: str
    ) -> tuple[ImportCandidate, dict[str, object]]:
        return candidate, {
            "id": f"staged-{name.casefold().replace(' ', '-')}",
            "name": path.name,
            "query_name": name,
            "kind": candidate.kind,
            "path": str(path.resolve()),
            "parser_options": dict(candidate.options),
            "transform_steps": [],
        }

    def trigger_source_menu_item(
        self, dialog: TransformDataDialog, label: str
    ) -> None:
        button = dialog.findChild(QToolButton, "powerQueryNewSourceButton")
        self.assertIsNotNone(button)
        action = next(
            (item for item in button.menu().actions() if item.text() == label),
            None,
        )
        self.assertIsNotNone(action, f"Missing Power Query source action: {label}")
        self.assertTrue(action.isEnabled())
        action.trigger()

    def root_with_reference(self) -> tuple[
        StudioController, Path, str, str, list[dict[str, str]]
    ]:
        controller = self.controller()
        path = self.root / "source-settings.csv"
        path.write_text("Region,Amount\n East ,10\nWest,20\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(path, parse_file(path)))
        root_id = str(controller._active_source_id)
        steps = [{"op": "trim_text", "column": "Region"}]
        raw = controller._raw_candidates[root_id]
        transformed = apply_transformations(raw, steps)
        self.assertTrue(controller._commit_transform_steps(
            root_id, steps, transformed, previewed_source=raw
        ), controller.statusMessage)
        root_types = next(
            table["column_types"]
            for table in controller._project["model"]["tables"]
            if table.get("source_id") == root_id
        )
        self.assertTrue(controller._create_saved_query(
            "Source reference",
            [root_id],
            controller._loaded_candidates[root_id],
            {"operation": "reference", "source_ids": [root_id]},
            root_types,
        ), controller.statusMessage)
        return controller, path, root_id, str(controller._active_source_id), steps

    def test_edit_source_settings_replays_steps_and_dependents_then_persists(self) -> None:
        controller, _old_path, root_id, reference_id, steps = self.root_with_reference()
        new_path = self.root / "replacement.csv"
        new_path.write_text("Region;Amount\n South ;15\nNorth;25\n", encoding="utf-8")
        candidate = parse_file(new_path, options={"delimiter": ";"})
        original_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        )
        edited_source = copy.deepcopy(original_source)
        edited_source["path"] = str(new_path.resolve())
        edited_source["parser_options"] = dict(candidate.options)
        project_before = copy.deepcopy(controller._project)

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(root_id))
            button = dialog.findChild(QToolButton, "powerQueryEditSourceSettingsButton")
            self.assertIsNotNone(button)
            self.assertTrue(button.isEnabled())
            button.click()
            root_state = dialog._query_states[root_id]
            self.assertEqual(root_state["source_record"]["id"], root_id)
            self.assertEqual(root_state["source_record"]["kind"], "csv")
            self.assertEqual(root_state["source_candidate"].source_id, root_id)
            self.assertEqual(root_state["source_candidate"].rows, candidate.rows)
            self.assertEqual(root_state["steps"], steps)
            reference = dialog._query_states[reference_id]
            self.assertEqual(reference["preview_candidate"].rows, [
                {"Region": "South", "Amount": 15},
                {"Region": "North", "Amount": 25},
            ])
            self.assertEqual(controller._project, project_before)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(candidate, edited_source),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        saved_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        )
        self.assertEqual(saved_source["path"], str(new_path.resolve()))
        self.assertEqual(saved_source["parser_options"]["delimiter"], ";")
        self.assertEqual(saved_source["transform_steps"], steps)
        self.assertEqual(controller._raw_candidates[root_id].source_id, root_id)
        self.assertEqual(controller._raw_candidates[root_id].rows, candidate.rows)
        self.assertEqual(controller._loaded_candidates[root_id].rows, [
            {"Region": "South", "Amount": "15"},
            {"Region": "North", "Amount": "25"},
        ])
        self.assertEqual(controller._loaded_candidates[reference_id].rows, [
            {"Region": "South", "Amount": 15},
            {"Region": "North", "Amount": 25},
        ])

        project_path = self.root / "source-settings-session.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        reopened_source = next(
            item for item in reopened._project["data_sources"]
            if item["id"] == root_id
        )
        self.assertEqual(reopened_source["path"], str(new_path.resolve()))
        self.assertEqual(reopened_source["parser_options"]["delimiter"], ";")
        new_path.write_text("Region;Amount\nDubai;35\n", encoding="utf-8")
        reopened.refresh_source()
        self.assertEqual(reopened._loaded_candidates[root_id].rows, [
            {"Region": "Dubai", "Amount": "35"},
        ])
        self.assertEqual(reopened._loaded_candidates[reference_id].rows, [
            {"Region": "Dubai", "Amount": 35},
        ])

    def test_session_apply_keeps_query_errors_and_blanks_them_in_the_model(self) -> None:
        controller, path, root_id, reference_id, _steps = self.root_with_reference()
        path.write_text("Region,Amount\n East ,10\nWest,bad\n", encoding="utf-8")
        controller.refresh_source()
        convert = {"op": "convert_type", "column": "Amount", "type": "whole_number"}

        def add_conversion(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(root_id))
            dialog.operation_combo.setCurrentIndex(
                dialog.operation_combo.findData("convert_type")
            )
            dialog.column_combo.setCurrentText("Amount")
            dialog.option_combo.setCurrentIndex(
                dialog.option_combo.findData(convert["type"])
            )
            dialog._add_step()
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=add_conversion):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        for source_id in (root_id, reference_id):
            query_value = controller._query_candidates[source_id].rows[1]["Amount"]
            self.assertIsInstance(query_value, PowerQueryCellError, source_id)
            self.assertEqual(query_value.reason, "DataFormat.Error")
            model_rows = controller._loaded_candidates[source_id].rows
            self.assertEqual(
                [row["Amount"] for row in model_rows], [10, None], source_id
            )

        # A session delete must drop the query-facing cache with the model one.
        self.assertIn(reference_id, controller._query_candidates)
        self.assertTrue(controller._commit_transform_session(
            {}, deleted_query_ids={reference_id}
        ), controller.statusMessage)
        self.assertNotIn(reference_id, controller._query_candidates)
        self.assertNotIn(reference_id, controller._loaded_candidates)

    def test_refresh_keeps_query_errors_blanks_model_and_refreshes_dependents(self) -> None:
        controller, path, root_id, reference_id, trim = self.root_with_reference()
        steps = [*trim, {"op": "convert_type", "column": "Amount", "type": "whole_number"}]
        raw = controller._raw_candidates[root_id]
        self.assertTrue(controller._commit_transform_steps(
            root_id, steps, apply_transformations(raw, steps), previewed_source=raw
        ), controller.statusMessage)
        stale = controller._query_candidates[root_id]
        self.assertEqual([row["Amount"] for row in stale.rows], [10, 20])

        path.write_text("Region,Amount\n East ,10\nWest,bad\nNorth,7\n", encoding="utf-8")
        controller._refresh_sources([root_id], refresh_all=True)

        for source_id in (root_id, reference_id):
            query_rows = controller._query_candidates[source_id].rows
            self.assertEqual(len(query_rows), 3, source_id)
            error = query_rows[1]["Amount"]
            self.assertIsInstance(error, PowerQueryCellError, source_id)
            self.assertEqual(error.reason, "DataFormat.Error")
            self.assertEqual(
                [row["Amount"] for row in controller._loaded_candidates[source_id].rows],
                [10, None, 7],
                source_id,
            )

    def test_reimporting_a_source_refreshes_query_cache_for_it_and_dependents(self) -> None:
        controller, path, root_id, reference_id, _steps = self.root_with_reference()
        path.write_text("Region,Amount\nEast,99\n", encoding="utf-8")

        self.assertTrue(controller._commit_import(path, parse_file(path)), controller.statusMessage)

        self.assertEqual(controller._source_id_for_path(path), root_id)
        # Query results are fresh (not the stale 10/20 rows) and match the model
        # for these error-free sources; the reference query carries typed values.
        for source_id, expected in ((root_id, "99"), (reference_id, 99)):
            self.assertEqual(
                [row["Amount"] for row in controller._query_candidates[source_id].rows],
                [expected], source_id,
            )
            self.assertEqual(
                [row["Amount"] for row in controller._loaded_candidates[source_id].rows],
                [expected], source_id,
            )

    def test_new_saved_query_blanks_format_errors_in_model_but_keeps_them_in_query(self) -> None:
        controller, _path, root_id, _reference_id, _steps = self.root_with_reference()
        bad = PowerQueryCellError("DataFormat.Error", "bad", "bad", "whole_number", row=1)
        candidate = ImportCandidate(
            "query", ["Region", "Amount"],
            [{"Region": "East", "Amount": 5}, {"Region": "West", "Amount": bad}],
            {}, [],
        )
        self.assertTrue(controller._create_saved_query(
            "Errors", [root_id], candidate,
            {"operation": "reference", "source_ids": [root_id]},
            {"Region": "text", "Amount": "whole_number"},
        ), controller.statusMessage)
        source_id = str(controller._active_source_id)

        self.assertIsInstance(
            controller._query_candidates[source_id].rows[1]["Amount"], PowerQueryCellError
        )
        self.assertEqual(
            [row["Amount"] for row in controller._loaded_candidates[source_id].rows],
            [5, None],
        )
        self.assertEqual([row["Amount"] for row in controller._rows], [5, None])

    def test_folder_source_settings_replays_dependencies_and_persists_recipe(self) -> None:
        controller = self.controller()
        old_folder = self.root / "old-folder"
        old_folder.mkdir()
        (old_folder / "records.csv").write_text(
            "Region,Amount\n East ,10\n", encoding="utf-8"
        )
        old_candidate = parse_folder(old_folder)
        self.assertTrue(controller._commit_import(old_folder, old_candidate))
        root_id = str(controller._active_source_id)
        root_source = copy.deepcopy(next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        ))
        steps = [{"op": "trim_text", "column": "Region"}]
        transformed = apply_transformations(old_candidate, steps)
        self.assertTrue(controller._commit_transform_steps(
            root_id,
            steps,
            transformed,
            previewed_source=old_candidate,
        ), controller.statusMessage)
        root_source = copy.deepcopy(next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        ))
        root_types = next(
            table["column_types"]
            for table in controller._project["model"]["tables"]
            if table.get("source_id") == root_id
        )
        self.assertTrue(controller._create_saved_query(
            "Folder reference",
            [root_id],
            controller._loaded_candidates[root_id],
            {"operation": "reference", "source_ids": [root_id]},
            root_types,
        ), controller.statusMessage)
        reference_id = str(controller._active_source_id)

        new_folder = self.root / "new-folder"
        archive = new_folder / "archive"
        archive.mkdir(parents=True)
        (new_folder / "records.csv").write_text(
            "Region,Amount\n Dubai ,25\n", encoding="utf-8"
        )
        (archive / "records-extra.csv").write_text(
            "Region,Amount\n Abu Dhabi ,35\n", encoding="utf-8"
        )
        options = default_folder_options()
        options.update(
            recursive=True,
            name_contains="records",
            sample_file="archive/records-extra.csv",
        )
        candidate = parse_folder(new_folder, options)
        edited_source = copy.deepcopy(root_source)
        edited_source["path"] = str(new_folder.resolve())
        edited_source["parser_options"] = dict(candidate.options)
        project_before = copy.deepcopy(controller._project)

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(root_id))
            button = dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            )
            self.assertIsNotNone(button)
            self.assertTrue(button.isEnabled())
            button.click()
            root_state = dialog._query_states[root_id]
            self.assertEqual(root_state["source_record"]["id"], root_id)
            self.assertEqual(root_state["source_record"]["kind"], "folder")
            self.assertEqual(root_state["source_record"]["parser_options"], candidate.options)
            self.assertEqual(root_state["steps"], steps)
            self.assertEqual(
                root_state["preview_candidate"].rows,
                [
                    {
                        "Source.Name": "archive/records-extra.csv",
                        "Region": "Abu Dhabi",
                        "Amount": "35",
                    },
                    {"Source.Name": "records.csv", "Region": "Dubai", "Amount": "25"},
                ],
            )
            self.assertEqual(
                dialog._query_states[reference_id]["preview_candidate"].rows,
                [
                    {
                        "Source.Name": "archive/records-extra.csv",
                        "Region": "Abu Dhabi",
                        "Amount": 35,
                    },
                    {"Source.Name": "records.csv", "Region": "Dubai", "Amount": 25},
                ],
            )
            self.assertEqual(controller._project, project_before)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(candidate, edited_source),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        saved_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        )
        self.assertEqual(saved_source["path"], str(new_folder.resolve()))
        self.assertEqual(saved_source["parser_options"], candidate.options)
        self.assertEqual(saved_source["transform_steps"], steps)
        self.assertEqual(controller._loaded_candidates[reference_id].rows, [
            {
                "Source.Name": "archive/records-extra.csv",
                "Region": "Abu Dhabi",
                "Amount": 35,
            },
            {"Source.Name": "records.csv", "Region": "Dubai", "Amount": 25},
        ])

        project_path = self.root / "folder-source-settings.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("folder-reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        reopened_source = next(
            item for item in reopened._project["data_sources"]
            if item["id"] == root_id
        )
        self.assertEqual(reopened_source["parser_options"], candidate.options)
        (archive / "records-extra.csv").write_text(
            "Region,Amount\nAbu Dhabi,45\n", encoding="utf-8"
        )
        reopened.refresh_all_sources()
        self.assertEqual(
            reopened._loaded_candidates[root_id].rows,
            [
                {
                    "Source.Name": "archive/records-extra.csv",
                    "Region": "Abu Dhabi",
                    "Amount": "45",
                },
                {"Source.Name": "records.csv", "Region": "Dubai", "Amount": "25"},
            ],
        )
        self.assertEqual(reopened._loaded_candidates[reference_id].rows, [
            {
                "Source.Name": "archive/records-extra.csv",
                "Region": "Abu Dhabi",
                "Amount": 45,
            },
            {"Source.Name": "records.csv", "Region": "Dubai", "Amount": 25},
        ])

    def test_folder_source_settings_are_available_in_query_context_menu(self) -> None:
        candidate = ImportCandidate(
            "folder", ["Region"], [{"Region": "Dubai"}], {}, []
        )
        source_record = {
            "id": "folder-source",
            "name": "Monthly folder",
            "query_name": "Monthly folder",
            "kind": "folder",
            "path": str(self.root),
            "parser_options": {},
            "transform_steps": [],
        }
        edit_source_candidate = MagicMock(return_value=None)
        dialog = TransformDataDialog(
            candidate,
            queries=[{
                "id": "folder-source",
                "name": "Monthly folder",
                "candidate": candidate,
                "source_candidate": candidate,
                "source_record": source_record,
            }],
            active_query_id="folder-source",
            edit_source_candidate=edit_source_candidate,
        )
        dialog.show()
        self.app.processEvents()
        item = dialog.query_list.item(0)
        self.assertIsNotNone(item)
        position = dialog.query_list.visualItemRect(item).center()
        self.assertIs(dialog.query_list.itemAt(position), item)
        actions = [MagicMock(), MagicMock(), MagicMock()]

        with patch("analytics_studio.local_table_dialogs.QMenu") as menu_type:
            menu = menu_type.return_value
            menu.addAction.side_effect = actions
            menu.exec.return_value = actions[1]
            dialog._show_query_context_menu(position)

        actions[1].setEnabled.assert_called_once_with(True)
        edit_source_candidate.assert_called_once_with(source_record)
        dialog.deleteLater()

    def test_folder_source_drift_after_preview_rejects_apply_atomically(self) -> None:
        controller = self.controller()
        old_folder = self.root / "old-folder"
        old_folder.mkdir()
        (old_folder / "records.csv").write_text(
            "Region\nOld\n", encoding="utf-8"
        )
        self.assertTrue(controller._commit_import(
            old_folder, parse_folder(old_folder)
        ))
        root_id = str(controller._active_source_id)
        current_source = copy.deepcopy(next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        ))

        new_folder = self.root / "new-folder"
        new_folder.mkdir()
        records = new_folder / "records.csv"
        records.write_text("Region\nPreview value\n", encoding="utf-8")
        candidate = parse_folder(new_folder)
        edited_source = copy.deepcopy(current_source)
        edited_source["path"] = str(new_folder.resolve())
        edited_source["parser_options"] = dict(candidate.options)
        project_before = copy.deepcopy(controller._project)
        raw_before = copy.deepcopy(controller._raw_candidates)
        loaded_before = copy.deepcopy(controller._loaded_candidates)

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            button = dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            )
            self.assertIsNotNone(button)
            button.click()
            records.write_text("Region\nChanged after preview\n", encoding="utf-8")
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(candidate, edited_source),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertFalse(controller.transform_data_dialog())

        self.assertIn("changed during the Power Query session", controller.statusMessage)
        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller._raw_candidates, raw_before)
        self.assertEqual(controller._loaded_candidates, loaded_before)

    def test_sqlite_source_settings_are_available_and_apply_in_session(self) -> None:
        controller = self.controller()
        old_path = self.root / "old.sqlite"
        new_path = self.root / "new.sqlite"
        for path, rows in (
            (old_path, [("Dubai", "10")]),
            (new_path, [("Abu Dhabi", "20")]),
        ):
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "CREATE TABLE Sales (Region TEXT, Amount TEXT)"
                )
                connection.executemany(
                    "INSERT INTO Sales VALUES (?, ?)", rows
                )
                connection.execute(
                    "CREATE VIEW SalesView AS SELECT Region, Amount FROM Sales"
                )
        old_candidate = parse_file(old_path, options={"table_name": "Sales"})
        self.assertTrue(controller._commit_import(old_path, old_candidate))
        root_id = str(controller._active_source_id)
        root_types = next(
            table["column_types"]
            for table in controller._project["model"]["tables"]
            if table.get("source_id") == root_id
        )
        self.assertTrue(controller._create_saved_query(
            "Sales reference",
            [root_id],
            controller._loaded_candidates[root_id],
            {"operation": "reference", "source_ids": [root_id]},
            root_types,
        ), controller.statusMessage)
        reference_id = str(controller._active_source_id)
        old_source = copy.deepcopy(next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        ))
        new_candidate = parse_file(new_path, options={"table_name": "SalesView"})
        edited_source = copy.deepcopy(old_source)
        edited_source["path"] = str(new_path.resolve())
        edited_source["parser_options"] = dict(new_candidate.options)
        project_before = copy.deepcopy(controller._project)

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(root_id))
            button = dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            )
            self.assertIsNotNone(button)
            self.assertTrue(button.isEnabled())
            button.click()
            staged = dialog._query_states[root_id]
            self.assertEqual(staged["source_record"]["kind"], "sqlite")
            self.assertEqual(staged["source_candidate"].source_id, root_id)
            self.assertEqual(staged["source_candidate"].rows, new_candidate.rows)
            self.assertEqual(staged["source_record"]["parser_options"], {
                "table_name": "SalesView",
            })
            self.assertEqual(
                dialog._query_states[reference_id]["preview_candidate"].rows,
                [{"Region": "Abu Dhabi", "Amount": 20}],
            )
            self.assertEqual(controller._project, project_before)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(new_candidate, edited_source),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertTrue(
                controller.transform_data_dialog(), controller.statusMessage
            )

        saved_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        )
        self.assertEqual(saved_source["path"], str(new_path.resolve()))
        self.assertEqual(saved_source["parser_options"]["table_name"], "SalesView")
        self.assertEqual(controller._raw_candidates[root_id].source_id, root_id)
        self.assertEqual(controller._raw_candidates[root_id].rows, new_candidate.rows)
        self.assertEqual(controller._loaded_candidates[root_id].rows, [
            {"Region": "Abu Dhabi", "Amount": "20"},
        ])
        self.assertEqual(controller._loaded_candidates[reference_id].rows, [
            {"Region": "Abu Dhabi", "Amount": 20},
        ])

        project_path = self.root / "sqlite-source-settings.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("reopened-sqlite-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        reopened_source = next(
            source for source in reopened._project["data_sources"]
            if source["id"] == root_id
        )
        self.assertEqual(reopened_source["path"], str(new_path.resolve()))
        self.assertEqual(
            reopened_source["parser_options"]["table_name"], "SalesView"
        )
        with closing(sqlite3.connect(new_path)) as connection, connection:
            connection.execute(
                "UPDATE Sales SET Amount = '35' WHERE Region = 'Abu Dhabi'"
            )
        reopened.refresh_all_sources()
        self.assertIn("Refreshed all", reopened.statusMessage)
        self.assertEqual(
            reopened._loaded_candidates[root_id].rows[0]["Amount"], "35"
        )
        self.assertEqual(
            reopened._loaded_candidates[reference_id].rows[0]["Amount"], 35
        )

    def test_sqlite_source_settings_reject_duplicate_binding_atomically(self) -> None:
        controller = self.controller()
        first_path = self.root / "first.sqlite"
        second_path = self.root / "second.sqlite"
        for path, region in ((first_path, "Dubai"), (second_path, "Abu Dhabi")):
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "CREATE TABLE Sales (Region TEXT, Amount TEXT)"
                )
                connection.execute(
                    "INSERT INTO Sales VALUES (?, '10')", (region,)
                )
            self.assertTrue(controller._commit_import(
                path,
                parse_file(path, options={"table_name": "Sales"}),
            ))
        first_source = copy.deepcopy(next(
            source for source in controller._project["data_sources"]
            if source["path"] == str(first_path.resolve())
        ))
        first_id = str(first_source["id"])
        second_id = str(next(
            source for source in controller._project["data_sources"]
            if source["path"] == str(second_path.resolve())
        )["id"])
        staged_candidate = controller._raw_candidates[second_id]
        edited_source = copy.deepcopy(first_source)
        edited_source["path"] = str(second_path.resolve())
        edited_source["parser_options"] = dict(staged_candidate.options)
        before = (
            copy.deepcopy(controller._project),
            copy.deepcopy(controller._raw_candidates),
            copy.deepcopy(controller._loaded_candidates),
        )

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(first_id))
            button = dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            )
            self.assertIsNotNone(button)
            self.assertTrue(button.isEnabled())
            button.click()
            self.assertEqual(
                dialog._query_states[first_id]["source_record"]["path"],
                str(second_path.resolve()),
            )
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(staged_candidate, edited_source),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertFalse(
                controller.transform_data_dialog(), controller.statusMessage
            )

        self.assertIn("already linked", controller.statusMessage)
        self.assertEqual(controller._project, before[0])
        self.assertEqual(controller._raw_candidates, before[1])
        self.assertEqual(controller._loaded_candidates, before[2])

    def test_sqlite_source_settings_reject_a_new_source_collision_in_same_session(self) -> None:
        controller = self.controller()
        original_path = self.root / "original.sqlite"
        target_path = self.root / "target.sqlite"
        for path, region in (
            (original_path, "Dubai"),
            (target_path, "Abu Dhabi"),
        ):
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "CREATE TABLE Sales (Region TEXT, Amount TEXT)"
                )
                connection.execute(
                    "INSERT INTO Sales VALUES (?, '10')", (region,)
                )
        original_candidate = parse_file(
            original_path, options={"table_name": "Sales"}
        )
        self.assertTrue(controller._commit_import(original_path, original_candidate))
        root_id = str(controller._active_source_id)
        target_candidate = parse_file(
            target_path, options={"table_name": "Sales"}
        )
        staged_candidate, staged_source = self.staged_file_source(
            target_path, target_candidate, "Sales"
        )
        edited_source = copy.deepcopy(next(
            source for source in controller._project["data_sources"]
            if source["id"] == root_id
        ))
        edited_source["path"] = str(target_path.resolve())
        edited_source["parser_options"] = dict(target_candidate.options)
        before = (
            copy.deepcopy(controller._project),
            copy.deepcopy(controller._raw_candidates),
            copy.deepcopy(controller._loaded_candidates),
        )

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            new_source_button = dialog.findChild(
                QToolButton, "powerQueryNewSourceButton"
            )
            self.assertIsNotNone(new_source_button)
            next(
                action for action in new_source_button.menu().actions()
                if action.text() == "From File…"
            ).trigger()
            staged_id = dialog._query_order[-1]
            self.assertEqual(
                dialog._query_states[staged_id]["source_record"]["path"],
                str(target_path.resolve()),
            )
            dialog.query_list.setCurrentRow(dialog._query_order.index(root_id))
            edit_button = dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            )
            self.assertIsNotNone(edit_button)
            self.assertTrue(edit_button.isEnabled())
            edit_button.click()
            self.assertEqual(
                dialog._query_states[root_id]["source_record"]["path"],
                str(target_path.resolve()),
            )
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_new_power_query_source_candidate",
                return_value=(staged_candidate, staged_source),
            ),
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(target_candidate, edited_source),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertFalse(controller.transform_data_dialog())

        self.assertIn("already linked", controller.statusMessage)
        self.assertEqual(controller._project, before[0])
        self.assertEqual(controller._raw_candidates, before[1])
        self.assertEqual(controller._loaded_candidates, before[2])

    def test_sqlite_source_settings_allow_reusing_a_binding_after_it_moves_away(self) -> None:
        controller = self.controller()
        first_path = self.root / "first.sqlite"
        second_path = self.root / "second.sqlite"
        third_path = self.root / "third.sqlite"
        paths = (first_path, second_path, third_path)
        for path, region in zip(paths, ("Dubai", "Abu Dhabi", "Sharjah")):
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "CREATE TABLE Sales (Region TEXT, Amount TEXT)"
                )
                connection.execute(
                    "INSERT INTO Sales VALUES (?, '10')", (region,)
                )
        for path in paths[:2]:
            self.assertTrue(controller._commit_import(
                path, parse_file(path, options={"table_name": "Sales"})
            ))
        first_source, second_source = controller._project["data_sources"]
        first_id = str(first_source["id"])
        second_id = str(second_source["id"])
        second_candidate = parse_file(
            second_path, options={"table_name": "Sales"}
        )
        third_candidate = parse_file(
            third_path, options={"table_name": "Sales"}
        )
        edited_first = copy.deepcopy(first_source)
        edited_first["path"] = str(second_path.resolve())
        edited_first["parser_options"] = dict(second_candidate.options)
        edited_second = copy.deepcopy(second_source)
        edited_second["path"] = str(third_path.resolve())
        edited_second["parser_options"] = dict(third_candidate.options)
        replacement_by_id = {
            first_id: (second_candidate, edited_first),
            second_id: (third_candidate, edited_second),
        }

        def edit_selected_source(dialog: TransformDataDialog) -> None:
            dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            ).click()

        def provide_replacement(source: dict[str, object]):
            return replacement_by_id[str(source["id"])]

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(first_id))
            edit_selected_source(dialog)
            dialog.query_list.setCurrentRow(dialog._query_order.index(second_id))
            edit_selected_source(dialog)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                side_effect=provide_replacement,
            ),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        saved_first, saved_second = controller._project["data_sources"]
        self.assertEqual(saved_first["path"], str(second_path.resolve()))
        self.assertEqual(saved_second["path"], str(third_path.resolve()))
        self.assertEqual(
            controller._loaded_candidates[first_id].rows,
            [{"Region": "Abu Dhabi", "Amount": "10"}],
        )
        self.assertEqual(
            controller._loaded_candidates[second_id].rows,
            [{"Region": "Sharjah", "Amount": "10"}],
        )

    def test_sqlite_binding_check_preserves_distinct_quoted_object_names(self) -> None:
        controller = self.controller()
        path = self.root / "unicode-identifiers.sqlite"
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute('CREATE TABLE "Straße" (Value TEXT)')
            connection.execute('CREATE TABLE "STRASSE" (Value TEXT)')
            connection.execute('CREATE TABLE "Sales" (Value TEXT)')
            connection.execute('CREATE TABLE " Sales " (Value TEXT)')
        sources = [
            {
                "id": "unicode-lower",
                "kind": "sqlite",
                "path": str(path.resolve()),
                "parser_options": {"table_name": "Straße"},
            },
            {
                "id": "unicode-upper",
                "kind": "sqlite",
                "path": str(path.resolve()),
                "parser_options": {"table_name": "STRASSE"},
            },
            {
                "id": "plain-sales",
                "kind": "sqlite",
                "path": str(path.resolve()),
                "parser_options": {"table_name": "Sales"},
            },
            {
                "id": "space-sales",
                "kind": "sqlite",
                "path": str(path.resolve()),
                "parser_options": {"table_name": " Sales "},
            },
        ]

        self.assertFalse(controller._sqlite_binding_conflict(
            sources, {source["id"] for source in sources}
        ))

    def test_canceling_source_settings_edit_leaves_project_and_caches_unchanged(self) -> None:
        controller, _old_path, root_id, _reference_id, _steps = self.root_with_reference()
        new_path = self.root / "cancelled.csv"
        new_path.write_text("Region,Amount\nSouth,15\n", encoding="utf-8")
        candidate = parse_file(new_path)
        edited_source = copy.deepcopy(next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        ))
        edited_source["path"] = str(new_path.resolve())
        edited_source["parser_options"] = dict(candidate.options)
        before = (
            copy.deepcopy(controller._project),
            copy.deepcopy(controller._raw_candidates),
            copy.deepcopy(controller._loaded_candidates),
        )

        def cancel_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(root_id))
            dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            ).click()
            return QDialog.DialogCode.Rejected

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(candidate, edited_source),
            ),
            patch.object(TransformDataDialog, "exec", new=cancel_editor),
        ):
            self.assertFalse(controller.transform_data_dialog())

        self.assertEqual(controller._project, before[0])
        self.assertEqual(controller._raw_candidates, before[1])
        self.assertEqual(controller._loaded_candidates, before[2])

    def test_source_settings_refreshes_reference_append_and_merge_chain(self) -> None:
        controller, _old_path, root_id, reference_id, _steps = self.root_with_reference()
        other_path = self.root / "lookup.csv"
        other_path.write_text(
            "Region,Amount\nEast,30\nSouth,40\n", encoding="utf-8"
        )
        self.assertTrue(controller._commit_import(other_path, parse_file(other_path)))
        other_id = str(controller._active_source_id)
        reference_candidate = controller._loaded_candidates[reference_id]
        other_candidate = controller._loaded_candidates[other_id]
        append_candidate = append_candidates([reference_candidate, other_candidate])
        reference_types = next(
            table["column_types"]
            for table in controller._project["model"]["tables"]
            if table.get("source_id") == reference_id
        )
        other_types = next(
            table["column_types"]
            for table in controller._project["model"]["tables"]
            if table.get("source_id") == other_id
        )
        append_types = {
            header: reference_types.get(header, "text")
            if reference_types.get(header, "text") == other_types.get(header, "text")
            else "text"
            for header in append_candidate.headers
        }
        # Use the controller's saved-query path so the model graph is valid.
        self.assertTrue(controller._create_saved_query(
            "Appended dependent",
            [reference_id, other_id],
            append_candidate,
            {"operation": "append", "source_ids": [reference_id, other_id]},
            append_types,
        ), controller.statusMessage)
        append_id = str(controller._active_source_id)
        merge_candidate = merge_candidates(
            controller._loaded_candidates[append_id],
            controller._loaded_candidates[other_id],
            left_keys=["Region"],
            right_keys=["Region"],
            join_kind="left_outer",
            right_name="Lookup",
        )
        merge_types = {
            output_header: (
                append_types.get(origin.get("column", ""), "text")
                if origin.get("side") == "left"
                else other_types.get(origin.get("column", ""), "text")
            )
            for output_header, origin in merge_candidate.options["column_sources"].items()
        }
        self.assertTrue(controller._create_saved_query(
            "Merged dependent",
            [append_id, other_id],
            merge_candidate,
            {
                "operation": "merge",
                "source_ids": [append_id, other_id],
                "left_keys": ["Region"],
                "right_keys": ["Region"],
                "join_kind": "left_outer",
                "right_name": "Lookup",
            },
            merge_types,
        ), controller.statusMessage)
        merge_id = str(controller._active_source_id)

        replacement = self.root / "replacement-chain.csv"
        replacement.write_text("Region,Amount\nSouth,15\nNorth,25\n", encoding="utf-8")
        candidate = parse_file(replacement)
        edited_source = copy.deepcopy(next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        ))
        edited_source["path"] = str(replacement.resolve())
        edited_source["parser_options"] = dict(candidate.options)

        def accept_chain(dialog: TransformDataDialog) -> QDialog.DialogCode:
            for query_id in (reference_id, append_id, merge_id):
                state = dialog._query_states[query_id]
                table = next(
                    item for item in controller._project["model"]["tables"]
                    if item.get("source_id") == query_id
                )
                self.assertEqual(
                    state["column_types"],
                    table["column_types"],
                    f"{state['name']}: {state['column_types']} != {table['column_types']}",
                )
            dialog.query_list.setCurrentRow(dialog._query_order.index(root_id))
            dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            ).click()
            for query_id in (reference_id, append_id, merge_id):
                result = dialog._query_states[query_id]["preview_candidate"]
            self.assertTrue(any(row.get("Amount") == 15 for row in result.rows))
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(candidate, edited_source),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_chain),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)
        for query_id in (reference_id, append_id, merge_id):
            self.assertTrue(any(
                row.get("Amount") == 15
                for row in controller._loaded_candidates[query_id].rows
            ))

    def test_source_settings_preserves_excluded_reference_cache(self) -> None:
        controller, _old_path, root_id, reference_id, _steps = self.root_with_reference()
        self.assertTrue(controller.setQueryRefreshIncluded(reference_id, False))
        cached_rows = copy.deepcopy(controller._loaded_candidates[reference_id].rows)
        replacement = self.root / "replacement-excluded.csv"
        replacement.write_text("Region,Amount\nSouth,15\n", encoding="utf-8")
        candidate = parse_file(replacement)
        edited_source = copy.deepcopy(next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        ))
        edited_source["path"] = str(replacement.resolve())
        edited_source["parser_options"] = dict(candidate.options)

        def accept_with_excluded_reference(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(root_id))
            dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            ).click()
            self.assertEqual(
                dialog._query_states[reference_id]["preview_candidate"].rows,
                cached_rows,
            )
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(candidate, edited_source),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_with_excluded_reference),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)
        self.assertEqual(controller._loaded_candidates[reference_id].rows, cached_rows)

    def test_source_settings_reject_schema_changes_without_staging_them(self) -> None:
        controller, _old_path, root_id, _reference_id, _steps = self.root_with_reference()
        changed = ImportCandidate(
            "csv", ["Region", "NetSales"],
            [{"Region": "South", "NetSales": "15"}], {}, [],
        )
        edited_source = copy.deepcopy(next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        ))
        edited_source["path"] = str((self.root / "schema.csv").resolve())
        before = copy.deepcopy(controller._project)

        def inspect_rejection(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(root_id))
            dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            ).click()
            state = dialog._query_states[root_id]
            self.assertEqual(state["source_candidate"].headers, ["Region", "Amount"])
            self.assertEqual(state["source_record"]["path"], str(
                next(item for item in before["data_sources"] if item["id"] == root_id)["path"]
            ))
            self.assertIn("column names or data types", dialog.error_label.text())
            return QDialog.DialogCode.Rejected

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(changed, edited_source),
            ),
            patch.object(TransformDataDialog, "exec", new=inspect_rejection),
        ):
            self.assertFalse(controller.transform_data_dialog())
        self.assertEqual(controller._project, before)

    def test_source_settings_reject_type_changes_without_staging_them(self) -> None:
        controller, _old_path, root_id, _reference_id, _steps = self.root_with_reference()
        changed = ImportCandidate(
            "csv", ["Region", "Amount"],
            [{"Region": "South", "Amount": "not-a-number"}], {}, [],
        )
        edited_source = copy.deepcopy(next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        ))
        edited_source["path"] = str((self.root / "changed-type.csv").resolve())
        before = copy.deepcopy(controller._project)
        before_raw = copy.deepcopy(controller._raw_candidates)
        before_loaded = copy.deepcopy(controller._loaded_candidates)

        def inspect_rejection(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(root_id))
            dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            ).click()
            state = dialog._query_states[root_id]
            self.assertEqual(state["source_candidate"].headers, ["Region", "Amount"])
            self.assertEqual(state["source_column_types"]["Amount"], "whole_number")
            self.assertIn("column names or data types", dialog.error_label.text())
            return QDialog.DialogCode.Rejected

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(changed, edited_source),
            ),
            patch.object(TransformDataDialog, "exec", new=inspect_rejection),
        ):
            self.assertFalse(controller.transform_data_dialog())
        self.assertEqual(controller._project, before)
        self.assertEqual(controller._raw_candidates, before_raw)
        self.assertEqual(controller._loaded_candidates, before_loaded)

    def test_source_settings_rejects_duplicate_relationship_one_side_atomically(self) -> None:
        controller, _old_path, root_id, _reference_id, _steps = self.root_with_reference()
        lookup_path = self.root / "lookup-regions.csv"
        lookup_path.write_text("Region\nEast\nSouth\nWest\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(lookup_path, parse_file(lookup_path)))
        lookup_id = str(controller._active_source_id)
        relationships = controller._validate_relationship_candidate([{
            "relationship_version": 1,
            "id": "source-settings-region-link",
            "from": "Sales[Region]",
            "to": "Regions[Region]",
            "from_table_id": root_id,
            "from_column": "Region",
            "to_table_id": lookup_id,
            "to_column": "Region",
            "cardinality": "one_to_many",
            "cross_filter_direction": "single",
            "is_active": True,
        }])
        controller._project["model"]["relationships"] = relationships
        controller._project = validate_project(controller._project)

        replacement = self.root / "duplicate-region.csv"
        replacement.write_text(
            "Region,Amount\n South ,15\nSouth,25\n", encoding="utf-8"
        )
        candidate = parse_file(replacement)
        edited_source = copy.deepcopy(next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        ))
        edited_source["path"] = str(replacement.resolve())
        edited_source["parser_options"] = dict(candidate.options)
        before = (
            copy.deepcopy(controller._project),
            copy.deepcopy(controller._raw_candidates),
            copy.deepcopy(controller._loaded_candidates),
        )

        def accept_invalid_relationship_data(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(root_id))
            dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            ).click()
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(candidate, edited_source),
            ),
            patch.object(
                TransformDataDialog, "exec", new=accept_invalid_relationship_data
            ),
        ):
            self.assertFalse(controller.transform_data_dialog())

        self.assertIn("unique values", controller.statusMessage)
        self.assertEqual(controller._project, before[0])
        self.assertEqual(controller._raw_candidates, before[1])
        self.assertEqual(controller._loaded_candidates, before[2])

    def test_apply_rejects_source_settings_file_drift_atomically(self) -> None:
        controller, _old_path, root_id, _reference_id, _steps = self.root_with_reference()
        new_path = self.root / "drifting.csv"
        new_path.write_text("Region,Amount\nSouth,15\n", encoding="utf-8")
        candidate = parse_file(new_path)
        edited_source = copy.deepcopy(next(
            item for item in controller._project["data_sources"]
            if item["id"] == root_id
        ))
        edited_source["path"] = str(new_path.resolve())
        edited_source["parser_options"] = dict(candidate.options)
        before = (
            copy.deepcopy(controller._project),
            copy.deepcopy(controller._raw_candidates),
            copy.deepcopy(controller._loaded_candidates),
        )

        def accept_after_drift(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(root_id))
            dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            ).click()
            new_path.write_text("Region,Amount\nDubai,35\n", encoding="utf-8")
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_edit_power_query_source_candidate",
                return_value=(candidate, edited_source),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_after_drift),
        ):
            self.assertFalse(controller.transform_data_dialog())

        self.assertEqual(controller._project, before[0])
        self.assertEqual(controller._raw_candidates, before[1])
        self.assertEqual(controller._loaded_candidates, before[2])
        self.assertIn("changed during the Power Query session", controller.statusMessage)

    def test_new_source_is_staged_then_applied_with_model_table_and_refresh(self) -> None:
        controller = self.controller()
        existing_path = self.root / "existing.csv"
        existing_path.write_text("Region\nEast\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(existing_path, parse_file(existing_path)))

        new_path = self.root / "new-source.csv"
        new_path.write_text("Customer,Region\nAda, East \nLin,West\n", encoding="utf-8")
        candidate = parse_file(new_path)
        staged_candidate, source_record = self.staged_file_source(
            new_path, candidate, "New Source"
        )
        project_before = copy.deepcopy(controller._project)
        raw_before = copy.deepcopy(controller._raw_candidates)
        loaded_before = copy.deepcopy(controller._loaded_candidates)

        def accept_with_new_source(dialog: TransformDataDialog) -> QDialog.DialogCode:
            button = dialog.findChild(QToolButton, "powerQueryNewSourceButton")
            self.assertIsNotNone(button)
            self.assertTrue(button.isEnabled())
            next(
                action for action in button.menu().actions()
                if action.text() == "From File…"
            ).trigger()
            new_id = dialog._query_order[-1]
            staged = dialog._query_states[new_id]
            self.assertTrue(staged["is_new_source"])
            self.assertEqual(staged["source_record"]["path"], str(new_path.resolve()))
            self.assertEqual(controller._project, project_before)
            self.assertEqual(controller._raw_candidates, raw_before)
            self.assertEqual(controller._loaded_candidates, loaded_before)
            dialog._duplicate_selected_query()
            duplicate_id = dialog._active_query_id
            self.assertNotEqual(duplicate_id, source_record["id"])
            self.assertEqual(
                dialog._query_states[duplicate_id]["source_record"]["id"],
                duplicate_id,
            )
            dialog.query_list.setCurrentRow(
                dialog._query_order.index(source_record["id"])
            )
            dialog._create_reference_query()
            reference_id = dialog._active_query_id
            self.assertEqual(
                dialog._query_states[reference_id]["query_definition"]["source_ids"],
                [source_record["id"]],
            )
            dialog.query_list.setCurrentRow(
                dialog._query_order.index(source_record["id"])
            )
            new_path.write_text(
                "Customer,Region\nAda, North \nLin,West\n", encoding="utf-8"
            )
            refresh_button = dialog.findChild(
                QToolButton, "powerQueryRefreshPreviewButton"
            )
            self.assertIsNotNone(refresh_button)
            refresh_button.click()
            self.assertEqual(
                dialog._source_candidate.rows,
                [
                    {"Customer": "Ada", "Region": " North "},
                    {"Customer": "Lin", "Region": "West"},
                ],
            )
            dialog.query_name_edit.setText("Imported Customers")
            dialog.operation_combo.setCurrentIndex(
                dialog.operation_combo.findData("trim_text")
            )
            dialog.column_combo.setCurrentText("Region")
            dialog._add_step()
            dialog.query_list.setCurrentRow(
                dialog._query_order.index(source_record["id"])
            )
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_new_power_query_source_candidate",
                return_value=(staged_candidate, source_record),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_with_new_source),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        source_id = source_record["id"]
        saved_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == source_id
        )
        saved_table = next(
            item for item in controller._project["model"]["tables"]
            if item.get("source_id") == source_id
        )
        self.assertEqual(saved_source["query_name"], "Imported Customers")
        self.assertEqual(saved_source["transform_steps"], [
            {"op": "trim_text", "column": "Region"},
        ])
        self.assertEqual(saved_table["name"], "Imported Customers")
        self.assertEqual(controller._loaded_candidates[source_id].rows, [
            {"Customer": "Ada", "Region": "North"},
            {"Customer": "Lin", "Region": "West"},
        ])
        self.assertEqual(controller.activeTableId, source_id)
        duplicate_source = next(
            item for item in controller._project["data_sources"]
            if item.get("path") == str(new_path.resolve())
            and item["id"] != source_id
        )
        self.assertEqual(
            controller._loaded_candidates[duplicate_source["id"]].row_count,
            candidate.row_count,
        )
        reference_source = next(
            item for item in controller._project["data_sources"]
            if item.get("query_definition", {}).get("source_ids") == [source_id]
        )
        self.assertEqual(
            controller._loaded_candidates[reference_source["id"]].rows,
            controller._loaded_candidates[source_id].rows,
        )

        project_path = self.root / "new-source-session.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = StudioController(
            self.app,
            QSettings(str(self.root / "new-source-reopened.ini"), QSettings.Format.IniFormat),
        )
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.activeTableId, source_id)
        self.assertEqual(
            next(
                item for item in reopened._project["data_sources"]
                if item["id"] == source_id
            )["parser_options"],
            candidate.options,
        )
        new_path.write_text(
            "Customer,Region\nAda, South \nLin,Dubai\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._loaded_candidates[source_id].rows, [
            {"Customer": "Ada", "Region": "South"},
            {"Customer": "Lin", "Region": "Dubai"},
        ])

    def test_canceling_power_query_discards_a_staged_new_source(self) -> None:
        controller = self.controller()
        existing_path = self.root / "existing.csv"
        existing_path.write_text("Region\nEast\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(existing_path, parse_file(existing_path)))
        new_path = self.root / "cancelled.csv"
        new_path.write_text("Region\nWest\n", encoding="utf-8")
        candidate = parse_file(new_path)
        staged_candidate, source_record = self.staged_file_source(
            new_path, candidate, "Cancelled Source"
        )
        project_before = copy.deepcopy(controller._project)
        raw_before = copy.deepcopy(controller._raw_candidates)
        loaded_before = copy.deepcopy(controller._loaded_candidates)

        def cancel_with_new_source(dialog: TransformDataDialog) -> QDialog.DialogCode:
            button = dialog.findChild(QToolButton, "powerQueryNewSourceButton")
            self.assertIsNotNone(button)
            next(
                action for action in button.menu().actions()
                if action.text() == "From File…"
            ).trigger()
            self.assertTrue(dialog._query_states[source_record["id"]]["is_new_source"])
            return QDialog.DialogCode.Rejected

        with (
            patch.object(
                controller,
                "_new_power_query_source_candidate",
                return_value=(staged_candidate, source_record),
            ),
            patch.object(TransformDataDialog, "exec", new=cancel_with_new_source),
        ):
            self.assertFalse(controller.transform_data_dialog())

        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller._raw_candidates, raw_before)
        self.assertEqual(controller._loaded_candidates, loaded_before)

    def test_folder_source_can_be_staged_and_refreshed_from_the_editor(self) -> None:
        controller = self.controller()
        existing_path = self.root / "existing.csv"
        existing_path.write_text("Region\nEast\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(existing_path, parse_file(existing_path)))
        folder = self.root / "monthly"
        folder.mkdir()
        (folder / "one.csv").write_text("Region,Amount\nEast,10\n", encoding="utf-8")
        (folder / "two.csv").write_text("Region,Amount\nWest,20\n", encoding="utf-8")
        candidate = parse_folder(folder)
        source_record = {
            "id": "staged-folder-source",
            "name": folder.name,
            "query_name": "Monthly Files",
            "kind": "folder",
            "path": str(folder.resolve()),
            "parser_options": dict(candidate.options),
            "transform_steps": [],
        }

        def accept_folder_source(dialog: TransformDataDialog) -> QDialog.DialogCode:
            self.trigger_source_menu_item(dialog, "From Folder…")
            self.assertTrue(
                dialog._query_states[source_record["id"]]["is_new_source"]
            )
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_new_power_query_folder_candidate",
                return_value=(candidate, source_record),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_folder_source),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        self.assertEqual(
            controller._loaded_candidates[source_record["id"]].rows,
            candidate.rows,
        )
        (folder / "two.csv").write_text(
            "Region,Amount\nWest,20\nNorth,30\n", encoding="utf-8"
        )
        controller.refresh_source()
        self.assertEqual(
            controller._loaded_candidates[source_record["id"]].row_count,
            3,
        )

    def test_web_source_is_staged_in_power_query_then_applied(self) -> None:
        controller = self.controller()
        existing_path = self.root / "existing.csv"
        existing_path.write_text("Region\nEast\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(existing_path, parse_file(existing_path)))
        candidate = ImportCandidate(
            "web",
            ["Region", "Amount"],
            [{"Region": "West", "Amount": "20"}],
            {
                "resource_type": "csv",
                "delimiter": ",",
                "encoding": "utf-8-sig",
                "has_header": True,
            },
            [],
        )
        source_record = {
            "id": "staged-web-source",
            "name": "Web table · Web",
            "query_name": "Web table",
            "kind": "web",
            "connection": {"url": "https://example.com/data.csv"},
            "parser_options": dict(candidate.options),
            "transform_steps": [],
        }

        def accept_web_source(dialog: TransformDataDialog) -> QDialog.DialogCode:
            self.trigger_source_menu_item(dialog, "Web…")
            staged = dialog._query_states[source_record["id"]]
            self.assertTrue(staged["is_new_source"])
            self.assertEqual(staged["source_record"]["connection"], source_record["connection"])
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_new_power_query_web_candidate",
                return_value=(candidate, source_record),
            ),
            patch.object(
                controller,
                "_candidate_for_staged_source",
                return_value=candidate,
            ),
            patch.object(TransformDataDialog, "exec", new=accept_web_source),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        saved_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == source_record["id"]
        )
        self.assertEqual(saved_source["kind"], "web")
        self.assertNotIn("_staged_password", saved_source)
        self.assertEqual(
            controller._loaded_candidates[source_record["id"]].rows,
            candidate.rows,
        )

    def test_staged_web_refresh_applies_the_reviewed_snapshot(self) -> None:
        controller = self.controller()
        existing_path = self.root / "existing.csv"
        existing_path.write_text("Region\nEast\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(existing_path, parse_file(existing_path)))
        initial = ImportCandidate(
            "web", ["Region"], [{"Region": "Initial"}],
            {"resource_type": "csv", "delimiter": ",", "encoding": "utf-8-sig", "has_header": True}, [],
        )
        refreshed = ImportCandidate(
            "web", ["Region"], [{"Region": "Reviewed"}],
            dict(initial.options), [],
        )
        source_record = {
            "id": "staged-refreshed-web",
            "name": "Reviewed Web table",
            "query_name": "Reviewed Web table",
            "kind": "web",
            "connection": {"url": "https://example.com/data.csv"},
            "parser_options": dict(initial.options),
            "transform_steps": [],
        }

        def accept_source(dialog: TransformDataDialog) -> QDialog.DialogCode:
            self.trigger_source_menu_item(dialog, "Web…")
            dialog.findChild(QToolButton, "powerQueryRefreshPreviewButton").click()
            self.assertEqual(dialog._preview_candidate.rows, refreshed.rows)
            self.assertTrue(
                dialog._query_states[source_record["id"]]["preview_refreshed"]
            )
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller, "_new_power_query_web_candidate",
                return_value=(initial, source_record),
            ),
            patch("analytics_studio.controller.read_web_source", return_value=refreshed) as read_web,
            patch.object(
                controller, "_candidate_for_staged_source",
                side_effect=AssertionError("Apply should use the reviewed snapshot"),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_source),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        read_web.assert_called_once()
        self.assertEqual(
            controller._loaded_candidates[source_record["id"]].rows,
            refreshed.rows,
        )

    def test_odata_source_is_staged_and_committed_in_power_query(self) -> None:
        controller = self.controller()
        existing_path = self.root / "existing.csv"
        existing_path.write_text("Region\nEast\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(existing_path, parse_file(existing_path)))
        candidate = ImportCandidate(
            "odata", ["id", "amount"], [{"id": "1", "amount": "22"}],
            {
                "entity_set_name": "Metrics",
                "entity_url": "https://api.example.test/odata/Metrics",
            }, [],
        )
        source_record = {
            "id": "staged-odata-source",
            "name": "Metrics · OData Feed",
            "query_name": "Metrics",
            "kind": "odata",
            "connection": {"service_root": "https://api.example.test/odata/"},
            "parser_options": dict(candidate.options),
            "transform_steps": [],
        }

        def accept_source(dialog: TransformDataDialog) -> QDialog.DialogCode:
            self.trigger_source_menu_item(dialog, "OData Feed…")
            self.assertTrue(dialog._query_states[source_record["id"]]["is_new_source"])
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller, "_new_power_query_odata_candidate",
                return_value=(candidate, source_record),
            ),
            patch.object(
                controller, "_candidate_for_staged_source", return_value=candidate
            ) as reread,
            patch.object(TransformDataDialog, "exec", new=accept_source),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        reread.assert_called_once()
        saved_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == source_record["id"]
        )
        self.assertEqual(saved_source["kind"], "odata")
        self.assertEqual(saved_source["parser_options"], candidate.options)

    def test_staged_sql_credential_writes_roll_back_on_later_failure(self) -> None:
        controller = self.controller()
        existing_path = self.root / "existing.csv"
        existing_path.write_text("Region\nEast\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(existing_path, parse_file(existing_path)))
        candidate = ImportCandidate(
            "sql_server", ["Region"], [{"Region": "West"}],
            {"schema": "dbo", "table_name": "Sales", "object_type": "TABLE"}, [],
        )
        source_records = [
            {
                "id": f"staged-sql-{index}",
                "name": f"Sales {index}",
                "query_name": f"Sales {index}",
                "kind": "sql_server",
                "connection": {
                    "server": "warehouse.example.com",
                    "port": 1433,
                    "database": "Warehouse",
                    "username": "analytics",
                    "driver": "ODBC Driver 18 for SQL Server",
                    "encrypt": True,
                    "credential_ref": f"staged-keychain-ref-{index}",
                },
                "parser_options": dict(candidate.options),
                "transform_steps": [],
                "_staged_password": f"local-secret-{index}",
            }
            for index in (1, 2)
        ]
        project_before = copy.deepcopy(controller._project)
        deletions: list[str] = []

        def save_password(reference, password, _connection):
            if reference.endswith("-2"):
                raise CredentialStoreError("simulated Keychain write failure")

        def delete_password(reference, _connection):
            deletions.append(reference)

        def accept_sources(dialog: TransformDataDialog) -> QDialog.DialogCode:
            for source in source_records:
                self.trigger_source_menu_item(dialog, "SQL Server…")
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_new_power_query_sql_server_candidate",
                side_effect=[(candidate, source) for source in source_records],
            ),
            patch.object(
                controller, "_candidate_for_staged_source", return_value=candidate
            ),
            patch("analytics_studio.controller.set_sql_server_password", side_effect=save_password),
            patch("analytics_studio.controller.delete_sql_server_password", side_effect=delete_password),
            patch.object(TransformDataDialog, "exec", new=accept_sources),
        ):
            self.assertFalse(controller.transform_data_dialog())

        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller._sql_server_passwords, {})
        self.assertCountEqual(
            deletions,
            ["staged-keychain-ref-1", "staged-keychain-ref-2"],
        )

    def test_deleting_sql_source_in_power_query_removes_its_credential(self) -> None:
        controller = self.controller()
        existing_path = self.root / "existing.csv"
        existing_path.write_text("Region\nEast\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(existing_path, parse_file(existing_path)))
        file_source_id = controller._active_source_id
        sql_candidate = ImportCandidate(
            "sql_server", ["Region"], [{"Region": "West"}],
            {"schema": "dbo", "table_name": "Sales", "object_type": "TABLE"}, [],
        )
        settings = {
            "server": "warehouse.example.com",
            "port": 1433,
            "database": "Warehouse",
            "username": "analytics",
            "driver": "ODBC Driver 18 for SQL Server",
            "encrypt": True,
        }
        with patch("analytics_studio.controller.set_sql_server_password"):
            self.assertTrue(
                controller._commit_sql_server_import(settings, "local-secret", sql_candidate)
            )
        source = next(
            item for item in controller._project["data_sources"]
            if item["kind"] == "sql_server"
        )
        controller._loaded_candidates[source["id"]] = sql_candidate
        controller._active_source_id = file_source_id
        controller._project["active_source_id"] = file_source_id
        controller._install_source(
            existing_path,
            str(file_source_id),
            controller._loaded_candidates[str(file_source_id)],
        )
        reference = source["connection"]["credential_ref"]
        credential_cache_key = credential_account(reference, source["connection"])

        def delete_source(dialog: TransformDataDialog) -> QDialog.DialogCode:
            row = next(
                index for index, query_id in enumerate(dialog._query_order)
                if query_id == source["id"]
            )
            dialog.query_list.setCurrentRow(row)
            dialog._delete_selected_query()
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch("analytics_studio.controller.delete_sql_server_password") as delete_password,
            patch("analytics_studio.controller.QMessageBox.critical"),
            patch(
                "analytics_studio.local_table_dialogs.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ),
            patch.object(TransformDataDialog, "exec", new=delete_source),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        delete_password.assert_called_once_with(reference, source["connection"])
        self.assertNotIn(reference, {
            item.get("connection", {}).get("credential_ref")
            for item in controller._project["data_sources"]
        })
        self.assertNotIn(credential_cache_key, controller._sql_server_passwords)

    def test_sql_server_new_source_stores_password_only_after_apply(self) -> None:
        controller = self.controller()
        existing_path = self.root / "existing.csv"
        existing_path.write_text("Region\nEast\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(existing_path, parse_file(existing_path)))
        candidate = ImportCandidate(
            "sql_server",
            ["Region", "Amount"],
            [{"Region": "West", "Amount": "20"}],
            {"schema": "dbo", "table_name": "Sales", "object_type": "TABLE"},
            [],
        )
        source_record = {
            "id": "staged-sql-source",
            "name": "Warehouse.dbo.Sales",
            "query_name": "Sales",
            "kind": "sql_server",
            "connection": {
                "server": "warehouse.example.com",
                "port": 1433,
                "database": "Warehouse",
                "username": "analytics",
                "driver": "ODBC Driver 18 for SQL Server",
                "encrypt": True,
                "credential_ref": "staged-keychain-ref",
            },
            "parser_options": dict(candidate.options),
            "transform_steps": [],
            "_staged_password": "local-only-secret",
        }
        read_source = patch.object(
            controller,
            "_candidate_for_staged_source",
            side_effect=lambda source, *, sql_server_password="": (
                self.assertEqual(sql_server_password, "local-only-secret") or candidate
            ),
        )

        def accept_sql_source(dialog: TransformDataDialog) -> QDialog.DialogCode:
            self.trigger_source_menu_item(dialog, "SQL Server…")
            self.assertEqual(
                dialog._query_states[source_record["id"]]["source_record"]["_staged_password"],
                "local-only-secret",
            )
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_new_power_query_sql_server_candidate",
                return_value=(candidate, source_record),
            ),
            read_source,
            patch("analytics_studio.controller.set_sql_server_password") as save_password,
            patch.object(TransformDataDialog, "exec", new=accept_sql_source),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        save_password.assert_called_once_with(
            "staged-keychain-ref",
            "local-only-secret",
            source_record["connection"],
        )
        saved_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == source_record["id"]
        )
        self.assertNotIn("_staged_password", saved_source)
        self.assertNotIn("local-only-secret", repr(controller._project))
        self.assertEqual(
            controller._sql_server_passwords[
                credential_account(
                    "staged-keychain-ref", source_record["connection"]
                )
            ],
            "local-only-secret",
        )

    def test_apply_rejects_a_new_source_that_changed_after_its_preview(self) -> None:
        controller = self.controller()
        existing_path = self.root / "existing.csv"
        existing_path.write_text("Region\nEast\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(existing_path, parse_file(existing_path)))
        new_path = self.root / "changed.csv"
        new_path.write_text("Region\nWest\n", encoding="utf-8")
        staged_candidate, source_record = self.staged_file_source(
            new_path, parse_file(new_path), "Changed Source"
        )
        project_before = copy.deepcopy(controller._project)

        def accept_after_file_change(dialog: TransformDataDialog) -> QDialog.DialogCode:
            button = dialog.findChild(QToolButton, "powerQueryNewSourceButton")
            self.assertIsNotNone(button)
            add_file_action = next(
                action for action in button.menu().actions()
                if action.text() == "From File…"
            )
            add_file_action.trigger()
            new_path.write_text("Region\nSouth\n", encoding="utf-8")
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                controller,
                "_new_power_query_source_candidate",
                return_value=(staged_candidate, source_record),
            ),
            patch.object(TransformDataDialog, "exec", new=accept_after_file_change),
        ):
            self.assertFalse(controller.transform_data_dialog())

        self.assertEqual(controller._project, project_before)
        self.assertNotIn(source_record["id"], controller._loaded_candidates)
        self.assertIn("changed during the Power Query session", controller.statusMessage)

    @staticmethod
    def accept_append(name: str):
        def accept(dialog: AppendQueriesDialog) -> QDialog.DialogCode:
            dialog.query_name_edit.setText(name)
            dialog._accept_query()
            return QDialog.DialogCode.Accepted

        return accept

    @staticmethod
    def accept_merge(name: str):
        def accept(dialog: MergeQueriesDialog) -> QDialog.DialogCode:
            dialog.query_name_edit.setText(name)
            dialog._accept_query()
            return QDialog.DialogCode.Accepted

        return accept

    def test_home_ribbon_stages_append_and_rebuilds_from_parent_edits(self) -> None:
        first = ImportCandidate(
            "csv",
            ["id", "Region", "Amount"],
            [
                {"id": "1", "Region": "North", "Amount": "10"},
                {"id": "2", "Region": "West", "Amount": "20"},
            ],
            {},
            [],
        )
        second = ImportCandidate(
            "csv",
            ["id", "Region", "Amount"],
            [
                {"id": "3", "Region": "South", "Amount": "30"},
                {"id": "4", "Region": "South", "Amount": "40"},
            ],
            {},
            [],
        )
        queries = [
            {
                "id": "north",
                "name": "North",
                "display_name": "North",
                "candidate": first,
                "steps": [],
                "step_metadata": [],
                "column_types": {"id": "text", "Region": "text", "Amount": "text"},
            },
            {
                "id": "south",
                "name": "South",
                "display_name": "South",
                "candidate": second,
                "steps": [],
                "step_metadata": [],
                "column_types": {"id": "text", "Region": "text", "Amount": "text"},
            },
        ]
        dialog = TransformDataDialog(
            first, queries=queries, active_query_id="north"
        )
        append_button = dialog.findChild(QToolButton, "powerQueryAppendQueriesButton")
        self.assertIsNotNone(append_button)

        with patch.object(AppendQueriesDialog, "exec", new=self.accept_append("Combined")):
            append_button.click()

        self.assertEqual(len(dialog._query_order), 3)
        combined_id = dialog._query_order[-1]
        combined = dialog._query_states[combined_id]
        self.assertEqual(combined["query_definition"], {
            "operation": "append", "source_ids": ["north", "south"]
        })
        self.assertEqual(combined["preview_candidate"].row_count, 4)

        dialog.query_list.setCurrentRow(dialog._query_order.index("north"))
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("filter_rows")
        )
        dialog.column_combo.setCurrentText("Region")
        dialog.option_combo.setCurrentIndex(dialog.option_combo.findData("equals"))
        dialog.value_edit.setText("North")
        dialog._add_step()
        dialog.query_list.setCurrentRow(dialog._query_order.index(combined_id))

        self.assertEqual(
            dialog._query_states[combined_id]["preview_candidate"].rows,
            [
                {"id": "1", "Region": "North", "Amount": "10"},
                {"id": "3", "Region": "South", "Amount": "30"},
                {"id": "4", "Region": "South", "Amount": "40"},
            ],
        )
        dialog._accept_candidate()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(
            dialog.accepted_queries[combined_id]["candidate"].row_count, 3
        )
        dialog.deleteLater()

    def test_controller_apply_commits_append_preview_after_parent_edit(self) -> None:
        controller = self.controller()
        source_ids = self.add_file_sources(controller)
        accepted_preview_rows: list[dict[str, str]] = []
        accepted_query_ids: list[str] = []

        def accept_append(dialog: AppendQueriesDialog) -> QDialog.DialogCode:
            dialog.first_combo.setCurrentIndex(
                dialog.first_combo.findData(source_ids[0])
            )
            dialog.second_combo.setCurrentIndex(
                dialog.second_combo.findData(source_ids[1])
            )
            dialog.query_name_edit.setText("North plus South")
            dialog._accept_query()
            return QDialog.DialogCode.Accepted

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(
                dialog._query_order.index(source_ids[0])
            )
            dialog.operation_combo.setCurrentIndex(
                dialog.operation_combo.findData("filter_rows")
            )
            dialog.column_combo.setCurrentText("Region")
            dialog.option_combo.setCurrentIndex(
                dialog.option_combo.findData("equals")
            )
            dialog.value_edit.setText("North")
            dialog._add_step()

            button = dialog.findChild(
                QToolButton, "powerQueryAppendQueriesButton"
            )
            self.assertIsNotNone(button)
            button.click()
            combined_id = dialog._query_order[-1]
            dialog._accept_candidate()
            accepted_preview_rows.extend(
                dialog.accepted_queries[combined_id]["candidate"].rows
            )
            accepted_query_ids.append(combined_id)
            return QDialog.DialogCode.Accepted

        with (
            patch.object(AppendQueriesDialog, "exec", new=accept_append),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertTrue(
                controller.transform_data_dialog(), controller.statusMessage
            )

        self.assertEqual(len(accepted_preview_rows), 3)
        self.assertEqual(len(accepted_query_ids), 1)
        query_id = accepted_query_ids[0]
        self.assertEqual(
            controller._loaded_candidates[query_id].rows,
            accepted_preview_rows,
        )

    def test_controller_apply_commits_merge_preview_after_parent_edit(self) -> None:
        controller = self.controller()
        source_ids = self.add_file_sources(controller)
        accepted_preview_rows: list[dict[str, str]] = []
        accepted_query_ids: list[str] = []

        def accept_merge(dialog: MergeQueriesDialog) -> QDialog.DialogCode:
            dialog.left_combo.setCurrentIndex(dialog.left_combo.findData(source_ids[0]))
            dialog.right_combo.setCurrentIndex(dialog.right_combo.findData(source_ids[1]))
            dialog.query_name_edit.setText("North region join")
            dialog._accept_query()
            return QDialog.DialogCode.Accepted

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(
                dialog._query_order.index(source_ids[0])
            )
            dialog.operation_combo.setCurrentIndex(
                dialog.operation_combo.findData("filter_rows")
            )
            dialog.column_combo.setCurrentText("Region")
            dialog.option_combo.setCurrentIndex(
                dialog.option_combo.findData("equals")
            )
            dialog.value_edit.setText("North")
            dialog._add_step()

            button = dialog.findChild(QToolButton, "powerQueryMergeQueriesButton")
            self.assertIsNotNone(button)
            button.click()
            combined_id = dialog._query_order[-1]
            dialog._accept_candidate()
            accepted_preview_rows.extend(
                dialog.accepted_queries[combined_id]["candidate"].rows
            )
            accepted_query_ids.append(combined_id)
            return QDialog.DialogCode.Accepted

        with (
            patch.object(MergeQueriesDialog, "exec", new=accept_merge),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertTrue(
                controller.transform_data_dialog(), controller.statusMessage
            )

        self.assertEqual(len(accepted_query_ids), 1)
        query_id = accepted_query_ids[0]
        self.assertEqual(len(accepted_preview_rows), 1)
        self.assertEqual(
            controller._loaded_candidates[query_id].rows,
            accepted_preview_rows,
        )

    def test_combine_ribbon_actions_require_two_available_queries(self) -> None:
        candidate = ImportCandidate(
            "csv", ["id"], [{"id": "1"}], {}, []
        )
        dialog = TransformDataDialog(candidate)
        self.assertFalse(
            dialog.findChild(QToolButton, "powerQueryAppendQueriesButton").isEnabled()
        )
        self.assertFalse(
            dialog.findChild(QToolButton, "powerQueryMergeQueriesButton").isEnabled()
        )
        dialog.deleteLater()

    def test_home_refresh_preview_rereads_active_file_in_editor(self) -> None:
        controller = self.controller()
        source_ids = self.add_file_sources(controller)
        south_path = self.root / "south.csv"
        refreshed_rows: list[dict[str, str]] = []

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            south_path.write_text(
                "id,Region,Amount\n7,South,70\n8,East,80\n", encoding="utf-8"
            )
            refresh_button = dialog.findChild(
                QToolButton, "powerQueryRefreshPreviewButton"
            )
            self.assertIsNotNone(refresh_button)
            self.assertTrue(refresh_button.isEnabled())
            refresh_button.click()
            refreshed_rows.extend(dialog._source_candidate.rows)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_editor):
            self.assertTrue(
                controller.transform_data_dialog(), controller.statusMessage
            )

        self.assertEqual(controller.activeTableId, source_ids[1])
        self.assertEqual(refreshed_rows, [
            {"id": "7", "Region": "South", "Amount": "70"},
            {"id": "8", "Region": "East", "Amount": "80"},
        ])
        self.assertEqual(controller._loaded_candidates[source_ids[1]].rows, refreshed_rows)

    def test_refresh_preview_then_cancel_leaves_project_and_loaded_data_unchanged(self) -> None:
        controller = self.controller()
        source_ids = self.add_file_sources(controller)
        before = {
            "project": copy.deepcopy(controller._project),
            "raw": copy.deepcopy(controller._raw_candidates),
            "loaded": copy.deepcopy(controller._loaded_candidates),
            "active_source_id": controller._active_source_id,
            "active_source_path": controller._active_source_path,
            "active_source_kind": controller._active_source_kind,
            "dirty": controller._dirty,
            "current_view": controller._current_view,
            "active_page_id": controller._active_page_id,
            "current_region": controller._current_region,
            "headers": copy.deepcopy(controller._headers),
            "rows": copy.deepcopy(controller._rows),
            "report_context_cache": copy.deepcopy(
                controller._report_filter_context_cache
            ),
            "source_warning": controller._source_warning,
        }

        def cancel_after_preview(dialog: TransformDataDialog) -> QDialog.DialogCode:
            (self.root / "south.csv").write_text(
                "id,Region,Amount\n7,South,70\n", encoding="utf-8"
            )
            button = dialog.findChild(
                QToolButton, "powerQueryRefreshPreviewButton"
            )
            self.assertIsNotNone(button)
            button.click()
            self.assertEqual(dialog._source_candidate.rows, [
                {"id": "7", "Region": "South", "Amount": "70"},
            ])
            dialog.reject()
            return QDialog.DialogCode.Rejected

        with patch.object(TransformDataDialog, "exec", new=cancel_after_preview):
            self.assertFalse(controller.transform_data_dialog())

        self.assertEqual(controller._project, before["project"])
        self.assertEqual(controller._raw_candidates, before["raw"])
        self.assertEqual(controller._loaded_candidates, before["loaded"])
        self.assertEqual(controller._active_source_id, before["active_source_id"])
        self.assertEqual(controller._active_source_path, before["active_source_path"])
        self.assertEqual(controller._active_source_kind, before["active_source_kind"])
        self.assertEqual(controller._dirty, before["dirty"])
        self.assertEqual(controller._current_view, before["current_view"])
        self.assertEqual(controller._active_page_id, before["active_page_id"])
        self.assertEqual(controller._current_region, before["current_region"])
        self.assertEqual(controller._headers, before["headers"])
        self.assertEqual(controller._rows, before["rows"])
        self.assertEqual(
            controller._report_filter_context_cache,
            before["report_context_cache"],
        )
        self.assertEqual(controller._source_warning, before["source_warning"])
        self.assertIn(source_ids[1], controller._loaded_candidates)

    def test_apply_failure_after_preview_refresh_rolls_back_controller_state(self) -> None:
        controller = self.controller()
        self.add_file_sources(controller)
        original_session_raw = controller._session_raw_candidate_for_source
        before_project = copy.deepcopy(controller._project)
        before_raw = copy.deepcopy(controller._raw_candidates)
        before_loaded = copy.deepcopy(controller._loaded_candidates)
        before_active_id = controller._active_source_id
        before_dirty = controller._dirty
        before_page_id = controller._active_page_id
        before_active_path = controller._active_source_path
        before_active_kind = controller._active_source_kind
        before_current_view = controller._current_view
        before_current_region = controller._current_region
        before_headers = copy.deepcopy(controller._headers)
        before_rows = copy.deepcopy(controller._rows)
        before_report_context = copy.deepcopy(controller._report_filter_context_cache)
        before_source_warning = controller._source_warning

        with patch.object(
            controller,
            "_session_raw_candidate_for_source",
            wraps=original_session_raw,
        ) as session_raw:
            def refresh_then_fail_apply(
                dialog: TransformDataDialog,
            ) -> QDialog.DialogCode:
                (self.root / "south.csv").write_text(
                    "id,Region,Amount\n7,South,70\n", encoding="utf-8"
                )
                button = dialog.findChild(
                    QToolButton, "powerQueryRefreshPreviewButton"
                )
                self.assertIsNotNone(button)
                button.click()
                self.assertEqual(dialog._source_candidate.rows, [
                    {"id": "7", "Region": "South", "Amount": "70"},
                ])
                session_raw.side_effect = OSError("injected apply-time read failure")
                dialog._accept_candidate()
                return QDialog.DialogCode.Accepted

            with patch.object(
                TransformDataDialog, "exec", new=refresh_then_fail_apply
            ):
                self.assertFalse(controller.transform_data_dialog())

        self.assertIn("injected apply-time read failure", controller.statusMessage)
        self.assertEqual(controller._project, before_project)
        self.assertEqual(controller._raw_candidates, before_raw)
        self.assertEqual(controller._loaded_candidates, before_loaded)
        self.assertEqual(controller._active_source_id, before_active_id)
        self.assertEqual(controller._dirty, before_dirty)
        self.assertEqual(controller._active_page_id, before_page_id)
        self.assertEqual(controller._active_source_path, before_active_path)
        self.assertEqual(controller._active_source_kind, before_active_kind)
        self.assertEqual(controller._current_view, before_current_view)
        self.assertEqual(controller._current_region, before_current_region)
        self.assertEqual(controller._headers, before_headers)
        self.assertEqual(controller._rows, before_rows)
        self.assertEqual(controller._report_filter_context_cache, before_report_context)
        self.assertEqual(controller._source_warning, before_source_warning)

    def test_refresh_preview_rebuilds_derived_query_from_refreshed_dependencies(self) -> None:
        controller = self.controller()
        source_ids = self.add_file_sources(controller)
        refreshed_rows: list[dict[str, str]] = []
        parameter = {
            "name": "MinimumAmount",
            "type": "whole_number",
            "current_value": "15",
        }

        def manage_parameters(dialog: TransformDataDialog, value: str) -> None:
            def accept(manager: ManageQueryParametersDialog) -> QDialog.DialogCode:
                manager._parameters = [{**parameter, "current_value": value}]
                manager._accept_parameters()
                return QDialog.DialogCode.Accepted

            with patch.object(ManageQueryParametersDialog, "exec", new=accept):
                dialog._manage_query_parameters()

        def accept_append(dialog: AppendQueriesDialog) -> QDialog.DialogCode:
            dialog.first_combo.setCurrentIndex(
                dialog.first_combo.findData(source_ids[0])
            )
            dialog.second_combo.setCurrentIndex(
                dialog.second_combo.findData(source_ids[1])
            )
            dialog.query_name_edit.setText("All regions")
            dialog._accept_query()
            return QDialog.DialogCode.Accepted

        query_ids: list[str] = []

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(source_ids[0]))
            manage_parameters(dialog, "15")
            dialog.operation_combo.setCurrentIndex(
                dialog.operation_combo.findData("filter_rows")
            )
            dialog.column_combo.setCurrentText("Amount")
            dialog.option_combo.setCurrentIndex(
                dialog.option_combo.findData("greater_than")
            )
            dialog.filter_parameter_combo.setCurrentIndex(
                dialog.filter_parameter_combo.findData("MinimumAmount")
            )
            dialog._add_step()

            append_button = dialog.findChild(
                QToolButton, "powerQueryAppendQueriesButton"
            )
            self.assertIsNotNone(append_button)
            append_button.click()
            query_ids.append(dialog._query_order[-1])

            (self.root / "north.csv").write_text(
                "id,Region,Amount\n5,North,50\n9,West,10\n", encoding="utf-8"
            )
            (self.root / "south.csv").write_text(
                "id,Region,Amount\n6,South,60\n", encoding="utf-8"
            )
            dialog.query_list.setCurrentRow(dialog._query_order.index(query_ids[0]))
            refresh_button = dialog.findChild(
                QToolButton, "powerQueryRefreshPreviewButton"
            )
            self.assertIsNotNone(refresh_button)
            refresh_button.click()
            refreshed_rows.extend(dialog._preview_candidate.rows)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(AppendQueriesDialog, "exec", new=accept_append),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertTrue(
                controller.transform_data_dialog(), controller.statusMessage
            )

        self.assertEqual(refreshed_rows, [
            {"id": "5", "Region": "North", "Amount": 50},
            {"id": "6", "Region": "South", "Amount": 60},
        ])

        (self.root / "north.csv").write_text(
            "id,Region,Amount\n5,North,18\n9,West,28\n", encoding="utf-8"
        )
        refreshed_root_rows: list[dict[str, str]] = []
        refreshed_append_rows: list[dict[str, str]] = []

        def accept_editor_with_changed_parameter(
            dialog: TransformDataDialog,
        ) -> QDialog.DialogCode:
            manage_parameters(dialog, "25")
            refresh_button = dialog.findChild(
                QToolButton, "powerQueryRefreshPreviewButton"
            )
            self.assertIsNotNone(refresh_button)
            refresh_button.click()
            refreshed_root_rows.extend(
                dialog._query_states[source_ids[0]]["preview_candidate"].rows
            )
            refreshed_append_rows.extend(dialog._preview_candidate.rows)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(
            TransformDataDialog,
            "exec",
            new=accept_editor_with_changed_parameter,
        ):
            self.assertTrue(
                controller.transform_data_dialog(), controller.statusMessage
            )

        self.assertEqual(refreshed_root_rows, [
            {"id": "9", "Region": "West", "Amount": "28"},
        ])
        self.assertEqual(refreshed_append_rows, [
            {"id": "9", "Region": "West", "Amount": 28},
            {"id": "6", "Region": "South", "Amount": 60},
        ])
        self.assertEqual(
            controller._project["query_parameters"][0]["current_value"], "25"
        )

    def test_refresh_preview_remote_dependency_applies_the_preview_snapshot(self) -> None:
        controller = self.controller()
        source_ids = self.add_file_sources(controller)
        first = controller._loaded_candidates[source_ids[0]]
        second = controller._loaded_candidates[source_ids[1]]
        combined = ImportCandidate(
            "query", list(first.headers), [*first.rows, *second.rows], {}, []
        )
        self.assertTrue(controller._create_saved_query(
            "All regions",
            source_ids,
            combined,
            {"operation": "append", "source_ids": source_ids},
            {header: "text" for header in combined.headers},
        ))
        target_id = str(controller._active_source_id)
        remote_source = next(
            source for source in controller._project["data_sources"]
            if source["id"] == source_ids[0]
        )
        remote_source.pop("path", None)
        remote_source["kind"] = "web"
        remote_source["connection"] = {"url": "https://example.com/north.csv"}
        remote_source["parser_options"] = {
            "resource_type": "csv",
            "delimiter": ",",
            "encoding": "utf-8",
            "has_header": True,
        }
        controller._project = validate_project(controller._project)
        remote_snapshot = ImportCandidate(
            "csv",
            list(first.headers),
            [{"id": "9", "Region": "New", "Amount": "90"}],
            {},
            [],
        )

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            button = dialog.findChild(
                QToolButton, "powerQueryRefreshPreviewButton"
            )
            self.assertIsNotNone(button)
            button.click()
            self.assertEqual(
                dialog._preview_candidate.rows,
                [*remote_snapshot.rows, *second.rows],
            )
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(
                StudioController,
                "_web_candidate_for_source",
                return_value=remote_snapshot,
            ) as web_reader,
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertTrue(
                controller.transform_data_dialog(), controller.statusMessage
            )

        web_reader.assert_called_once()
        self.assertEqual(controller._loaded_candidates[target_id].rows, [
            *remote_snapshot.rows,
            *second.rows,
        ])

    def test_refresh_preview_keeps_parameterized_excluded_dependency_consistent(self) -> None:
        controller = self.controller()
        source_ids = self.add_file_sources(controller)
        parameter = {
            "name": "MinimumAmount",
            "type": "whole_number",
            "current_value": "15",
        }
        controller._project["query_parameters"] = [parameter]
        controller._project = validate_project(controller._project)
        first = controller._loaded_candidates[source_ids[0]]
        second = controller._loaded_candidates[source_ids[1]]
        parent_raw = append_candidates([first, second])
        self.assertTrue(controller._create_saved_query(
            "Cached parent",
            source_ids,
            parent_raw,
            {"operation": "append", "source_ids": source_ids},
            {header: "text" for header in parent_raw.headers},
        ))
        excluded_id = str(controller._active_source_id)
        parameter_filter = {
            "op": "filter_rows",
            "column": "Amount",
            "operator": "greater_than",
            "parameter": "MinimumAmount",
        }
        filtered = apply_transformations(
            controller._raw_candidates[excluded_id],
            [parameter_filter],
            parameters={"MinimumAmount": "15"},
        )
        self.assertTrue(controller._commit_transform_steps(
            excluded_id,
            [parameter_filter],
            filtered,
            previewed_source=controller._raw_candidates[excluded_id],
        ), controller.statusMessage)
        self.assertTrue(controller.setQueryRefreshIncluded(excluded_id, False))
        excluded_output = controller._loaded_candidates[excluded_id]
        downstream_raw = append_candidates([
            excluded_output, controller._loaded_candidates[source_ids[0]]
        ])
        self.assertTrue(controller._create_saved_query(
            "Included child",
            [excluded_id, source_ids[0]],
            downstream_raw,
            {"operation": "append", "source_ids": [excluded_id, source_ids[0]]},
            {header: "text" for header in downstream_raw.headers},
        ))
        child_id = str(controller._active_source_id)
        def manage_parameters(dialog: TransformDataDialog) -> None:
            def accept(manager: ManageQueryParametersDialog) -> QDialog.DialogCode:
                manager._parameters = [{**parameter, "current_value": "25"}]
                manager._accept_parameters()
                return QDialog.DialogCode.Accepted

            with patch.object(ManageQueryParametersDialog, "exec", new=accept):
                dialog._manage_query_parameters()

        refreshed_excluded_rows: list[dict[str, str]] = []
        refreshed_child_rows: list[dict[str, str]] = []

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            manage_parameters(dialog)
            dialog.findChild(
                QToolButton, "powerQueryRefreshPreviewButton"
            ).click()
            refreshed_excluded_rows.extend(
                dialog._query_states[excluded_id]["preview_candidate"].rows
            )
            refreshed_child_rows.extend(dialog._preview_candidate.rows)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_editor):
            self.assertTrue(
                controller.transform_data_dialog(), controller.statusMessage
            )

        self.assertEqual(refreshed_excluded_rows, [
            {"id": "1", "Region": "South", "Amount": "30"},
            {"id": "3", "Region": "South", "Amount": "40"},
        ])
        self.assertEqual(refreshed_child_rows, [
            {"id": "1", "Region": "South", "Amount": "30"},
            {"id": "3", "Region": "South", "Amount": "40"},
            {"id": "1", "Region": "North", "Amount": "10"},
            {"id": "2", "Region": "West", "Amount": "20"},
        ])
        self.assertEqual(
            controller._loaded_candidates[child_id].rows, refreshed_child_rows
        )

    def test_refresh_preview_applies_edited_excluded_dependency_steps(self) -> None:
        controller = self.controller()
        source_ids = self.add_file_sources(controller)
        first = controller._loaded_candidates[source_ids[0]]
        second = controller._loaded_candidates[source_ids[1]]
        parent_raw = append_candidates([first, second])
        self.assertTrue(controller._create_saved_query(
            "Cached parent",
            source_ids,
            parent_raw,
            {"operation": "append", "source_ids": source_ids},
            {header: "text" for header in parent_raw.headers},
        ))
        excluded_id = str(controller._active_source_id)
        original_filter = {
            "op": "filter_rows",
            "column": "Amount",
            "operator": "greater_than",
            "value": "15",
        }
        original_output = apply_transformations(
            controller._raw_candidates[excluded_id], [original_filter]
        )
        self.assertTrue(controller._commit_transform_steps(
            excluded_id,
            [original_filter],
            original_output,
            previewed_source=controller._raw_candidates[excluded_id],
        ), controller.statusMessage)
        self.assertTrue(controller.setQueryRefreshIncluded(excluded_id, False))
        downstream_raw = append_candidates([
            controller._loaded_candidates[excluded_id],
            controller._loaded_candidates[source_ids[0]],
        ])
        self.assertTrue(controller._create_saved_query(
            "Included child",
            [excluded_id, source_ids[0]],
            downstream_raw,
            {
                "operation": "append",
                "source_ids": [excluded_id, source_ids[0]],
            },
            {header: "text" for header in downstream_raw.headers},
        ))
        child_id = str(controller._active_source_id)
        refreshed_excluded_rows: list[dict[str, str]] = []
        refreshed_child_rows: list[dict[str, str]] = []

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            excluded_row = dialog._query_order.index(excluded_id)
            child_row = dialog._query_order.index(child_id)
            dialog._switch_query(excluded_row)
            edited_filter = {
                "op": "filter_rows",
                "column": "Amount",
                "operator": "greater_than",
                "value": "35",
            }
            dialog._steps = [edited_filter]
            dialog._render_steps()
            dialog._refresh_preview()
            dialog._save_active_query_state()
            dialog._switch_query(child_row)
            dialog.findChild(
                QToolButton, "powerQueryRefreshPreviewButton"
            ).click()
            refreshed_excluded_rows.extend(
                dialog._query_states[excluded_id]["preview_candidate"].rows
            )
            refreshed_child_rows.extend(dialog._preview_candidate.rows)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_editor):
            self.assertTrue(
                controller.transform_data_dialog(), controller.statusMessage
            )

        expected_rows = [
            {"id": "3", "Region": "South", "Amount": "40"},
            {"id": "1", "Region": "North", "Amount": "10"},
            {"id": "2", "Region": "West", "Amount": "20"},
        ]
        self.assertEqual(refreshed_excluded_rows, expected_rows[:1])
        self.assertEqual(refreshed_child_rows, expected_rows)
        self.assertEqual(controller._loaded_candidates[excluded_id].rows, expected_rows[:1])
        self.assertEqual(controller._loaded_candidates[child_id].rows, expected_rows)
        persisted_parent = next(
            source
            for source in controller._project["data_sources"]
            if source["id"] == excluded_id
        )
        self.assertEqual(persisted_parent["transform_steps"], [
            {
                "op": "filter_rows",
                "column": "Amount",
                "operator": "greater_than",
                "value": "35",
            }
        ])
        self.assertFalse(persisted_parent["include_in_report_refresh"])
        self.assertEqual(controller._raw_candidates[excluded_id].rows, parent_raw.rows)

    def test_editor_append_commits_and_refreshes_after_save_and_reopen(self) -> None:
        controller = self.controller()
        source_ids = self.add_file_sources(controller)

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(
                dialog._query_order.index(source_ids[0])
            )
            dialog.query_name_edit.setText("North Renamed")
            dialog._save_active_query_state()
            button = dialog.findChild(QToolButton, "powerQueryAppendQueriesButton")
            self.assertIsNotNone(button)
            button.click()
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(AppendQueriesDialog, "exec", new=self.accept_append("All regions")),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        query = next(
            source for source in controller._project["data_sources"]
            if source.get("kind") == "query"
        )
        query_id = str(query["id"])
        self.assertEqual(query["query_definition"], {
            "operation": "append", "source_ids": source_ids
        })
        self.assertEqual(controller.activeTableId, query_id)
        self.assertEqual(controller._loaded_candidates[query_id].row_count, 4)

        project_path = self.root / "session-append.npa"
        self.assertTrue(controller._save_to(project_path))
        (self.root / "north.csv").write_text(
            "id,Region,Amount\n1,North,100\n5,North,110\n", encoding="utf-8"
        )
        (self.root / "south.csv").write_text(
            "id,Region,Amount\n3,South,300\n", encoding="utf-8"
        )
        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.activeTableId, query_id)
        self.assertEqual(
            reopened._loaded_candidates[query_id].rows,
            [
                {"id": "1", "Region": "North", "Amount": 100},
                {"id": "5", "Region": "North", "Amount": 110},
                {"id": "3", "Region": "South", "Amount": 300},
            ],
        )

    def test_append_advanced_editor_round_trips_and_persists(self) -> None:
        controller = self.controller()
        source_ids = self.add_file_sources(controller)
        observed: dict[str, object] = {}

        def accept_append(dialog: AppendQueriesDialog) -> QDialog.DialogCode:
            dialog.first_combo.setCurrentIndex(
                dialog.first_combo.findData(source_ids[0])
            )
            dialog.second_combo.setCurrentIndex(
                dialog.second_combo.findData(source_ids[1])
            )
            dialog.query_name_edit.setText("North plus South")
            dialog._accept_query()
            return QDialog.DialogCode.Accepted

        def edit_append_m(dialog: PowerQueryMEditorDialog) -> QDialog.DialogCode:
            generated = dialog.editor.toPlainText()
            observed["generated"] = generated
            self.assertIn("Table.Combine({", generated)
            source_binding = generated.splitlines()[1].rstrip().rstrip(",")
            appended_state = next(
                state for state in dialog.parent()._query_states.values()
                if state.get("query_definition", {}).get("operation") == "append"
            )
            self.assertEqual(
                appended_state["source_column_types"].get("Amount"),
                "whole_number",
            )
            unsafe = (
                "let\n"
                + source_binding
                + ',\n    Trimmed = Table.TransformColumns(Source, '
                '{{"Amount", Text.Trim, type text}})\n'
                + "in\n    Trimmed"
            )
            dialog.editor.setPlainText(unsafe)
            dialog._preview_query()
            self.assertIsNone(dialog._candidate)
            self.assertIn("'Amount' to remain text-typed", dialog.error_label.text())
            edited = (
                "let\n"
                + source_binding
                + ',\n    NorthOnly = Table.SelectRows(Source, each [Region] = "North")'
                + "\nin\n    NorthOnly"
            )
            dialog.editor.setPlainText(edited)
            dialog._preview_query()
            self.assertIsNotNone(
                dialog._candidate,
                f"{dialog.error_label.text()}\nScript was:\n{edited}",
            )
            observed["preview_rows"] = copy.deepcopy(dialog._candidate.rows)
            dialog._accept_query()
            observed["saved_script"] = dialog.script
            return QDialog.DialogCode.Accepted

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(
                dialog._query_order.index(source_ids[0])
            )
            dialog.query_name_edit.setText("North Renamed")
            dialog._save_active_query_state()
            button = dialog.findChild(QToolButton, "powerQueryAppendQueriesButton")
            self.assertIsNotNone(button)
            button.click()
            appended_id = dialog._active_query_id
            self.assertEqual(
                dialog._query_states[appended_id]["query_definition"],
                {"operation": "append", "source_ids": source_ids},
            )
            self.assertIn("Table.Combine({", dialog.formula_bar.text())
            dialog._open_advanced_editor()
            self.assertEqual(dialog._steps, [{
                "op": "filter_rows",
                "column": "Region",
                "operator": "equals",
                "value": "North",
            }])
            dialog._accept_candidate()
            accepted_script = dialog.accepted_queries[appended_id]["m_script"]
            self.assertIsNotNone(
                accepted_script,
                f"accepted={dialog.accepted_queries[appended_id]!r}",
            )
            self.assertEqual(accepted_script, observed["saved_script"])
            observed["accepted_script"] = accepted_script
            return QDialog.DialogCode.Accepted

        with (
            patch.object(AppendQueriesDialog, "exec", new=accept_append),
            patch.object(PowerQueryMEditorDialog, "exec", new=edit_append_m),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        query = next(
            source for source in controller._project["data_sources"]
            if source.get("kind") == "query"
            and source.get("query_name") == "North plus South"
        )
        query_id = str(query["id"])
        self.assertIn("Table.Combine({", str(observed["generated"]))
        self.assertIn('#"North Renamed"', str(observed["generated"]))
        self.assertEqual(observed["preview_rows"], [
            {"id": "1", "Region": "North", "Amount": "10"},
        ])
        self.assertEqual(
            query.get("m_script"), observed["accepted_script"],
            f"source names used by M: {observed['generated']!r}",
        )
        self.assertEqual(controller._loaded_candidates[query_id].rows, [
            {"id": "1", "Region": "North", "Amount": "10"},
        ])
        with patch.object(controller, "transform_data_dialog", return_value=True) as session:
            self.assertTrue(controller.power_query_m_editor_dialog())
            session.assert_called_once_with(open_advanced_editor=True)

        project_path = self.root / "append-m.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("append-m.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        reopened_query = next(
            source for source in reopened._project["data_sources"]
            if source.get("id") == query_id
        )
        self.assertEqual(reopened_query["m_script"], observed["accepted_script"])
        self.assertEqual(
            reopened._loaded_candidates[query_id].rows,
            controller._loaded_candidates[query_id].rows,
        )

    def test_canceling_editor_discards_staged_append(self) -> None:
        controller = self.controller()
        self.add_file_sources(controller)
        project_before = copy.deepcopy(controller._project)
        loaded_before = copy.deepcopy(controller._loaded_candidates)

        def cancel_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog._append_queries()
            dialog.reject()
            return QDialog.DialogCode.Rejected

        with (
            patch.object(AppendQueriesDialog, "exec", new=self.accept_append("Staged only")),
            patch.object(TransformDataDialog, "exec", new=cancel_editor),
        ):
            self.assertFalse(controller.transform_data_dialog())

        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller._loaded_candidates, loaded_before)

    def test_editor_merge_commits_join_definition_and_result(self) -> None:
        controller = self.controller()
        source_ids = self.add_file_sources(controller)
        staged_types: dict[str, dict[str, str]] = {}

        def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
            for source_id, type_name in zip(
                source_ids, ("whole_number", "decimal_number")
            ):
                dialog.query_list.setCurrentRow(dialog._query_order.index(source_id))
                dialog.operation_combo.setCurrentIndex(
                    dialog.operation_combo.findData("convert_type")
                )
                dialog.column_combo.setCurrentText("Amount")
                dialog.option_combo.setCurrentIndex(
                    dialog.option_combo.findData(type_name)
                )
                dialog._add_step()
            button = dialog.findChild(QToolButton, "powerQueryMergeQueriesButton")
            self.assertIsNotNone(button)
            button.click()
            merged_id = dialog._active_query_id
            merged_state = dialog._query_states[merged_id]
            self.assertEqual(
                merged_state["source_column_types"]["Amount"], "whole_number"
            )
            right_amount = next(
                output
                for output, origin in merged_state["source_candidate"].options[
                    "column_sources"
                ].items()
                if origin.get("side") == "right" and origin.get("column") == "Amount"
            )
            self.assertEqual(
                merged_state["source_column_types"][right_amount], "decimal_number"
            )
            staged_types.update(merged_state["source_column_types"])
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(MergeQueriesDialog, "exec", new=self.accept_merge("Region join")),
            patch.object(TransformDataDialog, "exec", new=accept_editor),
        ):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)

        query = next(
            source for source in controller._project["data_sources"]
            if source.get("kind") == "query"
        )
        query_id = str(query["id"])
        definition = query["query_definition"]
        self.assertEqual(definition["operation"], "merge")
        self.assertEqual(definition["left_keys"], ["id"])
        self.assertEqual(definition["right_keys"], ["id"])
        self.assertEqual(definition["join_kind"], "left_outer")
        self.assertEqual(staged_types["Amount"], "whole_number")
        self.assertEqual(controller._loaded_candidates[query_id].row_count, 2)
        self.assertIn("south.Region", controller._loaded_candidates[query_id].headers)

        project_path = self.root / "session-merge.npa"
        self.assertTrue(controller._save_to(project_path))
        (self.root / "north.csv").write_text(
            "id,Region,Amount\n1,North,100\n2,West,200\n5,East,500\n",
            encoding="utf-8",
        )
        (self.root / "south.csv").write_text(
            "id,Region,Amount\n1,South,300\n5,South,600\n",
            encoding="utf-8",
        )
        reopened = self.controller("merge-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.activeTableId, query_id)
        self.assertEqual(reopened._loaded_candidates[query_id].row_count, 3)
        merged_rows = reopened._loaded_candidates[query_id].rows
        self.assertEqual(merged_rows[0]["south.Region"], "South")
        self.assertIsNone(merged_rows[1]["south.Region"])
        self.assertEqual(merged_rows[2]["south.Region"], "South")

    def test_m_errors_keep_project_source_rows_through_save_reopen_and_refresh(self) -> None:
        controller = self.controller()
        path = self.root / "lineage.csv"
        path.write_text(
            "ID,Amount\nA,8\nB,broken\nC,10\nD,12\n",
            encoding="utf-8",
        )
        self.assertTrue(controller._commit_import(path, parse_file(path)))
        source_id = controller.activeTableId
        raw = controller._raw_candidates[source_id]
        self.assertEqual(raw.source_id, source_id)
        self.assertEqual(raw.rows[1].source_rows, ((source_id, 2),))
        steps = [
            {"op": "filter_rows", "column": "ID", "operator": "not_equals", "value": "A"},
            {"op": "sort_rows", "column": "ID", "direction": "desc"},
            {"op": "convert_type", "column": "Amount", "type": "whole_number"},
            {"op": "add_custom_column", "name": "Next", "expression": "[Amount] + 1"},
        ]
        script = steps_to_m_script(steps, "Lineage")
        parsed_steps = parse_m_script(
            script,
            "Lineage",
            initial_column_types={"ID": "text", "Amount": "text"},
        )
        transformed = apply_transformations(raw, parsed_steps)
        error = transformed.rows[-1]["Amount"]
        self.assertIsInstance(error, PowerQueryCellError)
        self.assertEqual(error.row, 3)
        self.assertEqual(error.source_rows, ((source_id, 2),))
        self.assertIs(transformed.rows[-1]["Next"], error)
        self.assertTrue(controller._commit_transform_steps(
            source_id,
            parsed_steps,
            transformed,
            previewed_source=raw,
            m_script=script,
        ), controller.statusMessage)

        remove_error_steps = [
            *parsed_steps,
            {"op": "remove_rows_with_errors", "columns": ["Amount"]},
        ]
        remove_error_script = steps_to_m_script(remove_error_steps, "Lineage")
        parsed_remove_steps = parse_m_script(
            remove_error_script,
            "Lineage",
            initial_column_types={"ID": "text", "Amount": "text"},
        )
        self.assertEqual(
            [row["ID"] for row in apply_transformations(raw, parsed_remove_steps).rows],
            ["D", "C"],
        )

        project_path = self.root / "lineage.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("lineage-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        # The model-facing candidate loads DataFormat.Error as blank; the
        # error-bearing query result keeps row lineage across save/reopen.
        self.assertIsNone(reopened._loaded_candidates[source_id].rows[-1]["Amount"])
        reopened_error = reopened._query_candidates[source_id].rows[-1]["Amount"]
        self.assertIsInstance(reopened_error, PowerQueryCellError)
        self.assertEqual(reopened_error.source_rows, ((source_id, 2),))
        self.assertEqual(reopened_error.row, 3)

        path.write_text(
            "ID,Amount\nA,8\nB,2\nC,10\nD,12\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        refreshed_row = next(
            row for row in reopened._loaded_candidates[source_id].rows
            if row["ID"] == "B"
        )
        self.assertEqual(refreshed_row["Amount"], 2)
        self.assertEqual(refreshed_row["Next"], "3")
        self.assertEqual(refreshed_row.source_rows, ((source_id, 2),))

    def test_mixed_unpivot_any_type_persists_and_replays_from_sqlite(self) -> None:
        controller = self.controller()
        path = self.root / "mixed.sqlite"
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                "CREATE TABLE Mixed (Key TEXT, Amount REAL, Note TEXT)"
            )
            connection.executemany(
                "INSERT INTO Mixed VALUES (?, ?, ?)",
                [("A", 1.25, "cash"), ("B", None, "")],
            )
        raw = parse_file(path, options={"table_name": "Mixed"})
        self.assertTrue(controller._commit_import(path, raw))
        source_id = controller.activeTableId
        raw = controller._raw_candidates[source_id]
        steps = [{
            "op": "unpivot_columns",
            "columns": ["Amount", "Note"],
            "attribute_name": "Field",
            "value_name": "Value",
        }]
        script = steps_to_m_script(steps, "Mixed Values")
        types = next(
            table["column_types"] for table in controller._project["model"]["tables"]
            if table.get("source_id") == source_id
        )
        parsed_steps = parse_m_script(
            script, "Mixed Values", initial_column_types=types
        )
        transformed = apply_transformations(raw, parsed_steps)
        self.assertTrue(controller._commit_transform_steps(
            source_id,
            parsed_steps,
            transformed,
            previewed_source=raw,
            m_script=script,
        ), controller.statusMessage)
        table_types = next(
            table["column_types"] for table in controller._project["model"]["tables"]
            if table.get("source_id") == source_id
        )
        self.assertEqual(table_types["Value"], "any")
        self.assertEqual([row["Value"] for row in transformed.rows], [1.25, "cash", ""])

        project_path = self.root / "mixed-unpivot.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("mixed-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        reopened_types = next(
            table["column_types"] for table in reopened._project["model"]["tables"]
            if table.get("source_id") == source_id
        )
        self.assertEqual(reopened_types["Value"], "any")
        self.assertEqual(
            [row["Value"] for row in reopened._loaded_candidates[source_id].rows],
            [1.25, "cash", ""],
        )

    def test_folder_lineage_keeps_file_addresses_when_earlier_file_is_added(self) -> None:
        controller = self.controller()
        folder = self.root / "folder-lineage"
        folder.mkdir()
        (folder / "z-records.csv").write_text(
            "ID,Value\nZ,first\n", encoding="utf-8"
        )
        candidate = parse_folder(folder)
        self.assertTrue(controller._commit_import(folder, candidate))
        source_id = controller.activeTableId
        original = next(
            row.source_rows for row in controller._raw_candidates[source_id].rows
            if row["ID"] == "Z"
        )
        self.assertTrue(original[0][0].startswith(source_id + ":"))

        (folder / "a-records.csv").write_text(
            "ID,Value\nA,earlier\n", encoding="utf-8"
        )
        controller.refresh_all_sources()
        refreshed = next(
            row.source_rows for row in controller._raw_candidates[source_id].rows
            if row["ID"] == "Z"
        )
        self.assertEqual(refreshed, original)


if __name__ == "__main__":
    unittest.main()
