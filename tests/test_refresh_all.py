"""Acceptance checks for transactional Refresh All and saved-query dependencies."""

from __future__ import annotations

import copy
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.folder_import import default_folder_options, parse_folder
from analytics_studio.inline_data import sample_candidate
from analytics_studio.query_engine import append_candidates
from analytics_studio.sql_server import SUPPORTED_DRIVERS

QQuickStyle.setStyle("Basic")


class RefreshAllTests(unittest.TestCase):
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

    def add_file(self, controller: StudioController, name: str, text: str) -> str:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        self.assertTrue(controller._commit_import(path, parse_file(path)))
        return controller.activeTableId

    def add_append_query(
        self,
        controller: StudioController,
        name: str,
        source_ids: list[str],
    ) -> str:
        candidate = append_candidates([
            controller._loaded_candidates[source_id]
            for source_id in source_ids
        ])
        definition = {"operation": "append", "source_ids": source_ids}
        self.assertTrue(controller._create_saved_query(
            name,
            source_ids,
            candidate,
            definition,
            {header: "text" for header in candidate.headers},
        ))
        return controller.activeTableId

    @staticmethod
    def write_xlsx(path: Path, rows: list[tuple[str, str]]) -> None:
        workbook = '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''
        relationships = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''
        sheet_rows = [
            '<row r="1"><c r="A1" t="inlineStr"><is><t>id</t></is></c><c r="B1" t="inlineStr"><is><t>value</t></is></c></row>'
        ]
        for index, (identifier, value) in enumerate(rows, 2):
            sheet_rows.append(
                f'<row r="{index}"><c r="A{index}" t="inlineStr"><is><t>{identifier}</t></is></c>'
                f'<c r="B{index}" t="inlineStr"><is><t>{value}</t></is></c></row>'
            )
        sheet = (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData>" + "".join(sheet_rows) + "</sheetData></worksheet>"
        )
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", relationships)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)

    @staticmethod
    def write_xml(path: Path, rows: list[tuple[str, str]]) -> None:
        records = "".join(
            f"<record><id>{identifier}</id><value>{value}</value></record>"
            for identifier, value in rows
        )
        path.write_text(f"<root>{records}</root>", encoding="utf-8")

    def test_refresh_all_replays_mixed_source_query_chain_and_keeps_excluded_cache(self) -> None:
        controller = self.controller()
        self.assertFalse(controller.canRefreshAllSources)
        sales_id = self.add_file(controller, "sales.csv", "id,value\nA,1\n")
        orders_id = self.add_file(controller, "orders.json", '[{"id":"B","value":2}]')

        branch_dir = self.root / "branch_folder"
        branch_dir.mkdir()
        branch_path = branch_dir / "branch.csv"
        branch_path.write_text("id,value\nC,3\n", encoding="utf-8")
        folder_options = default_folder_options()
        folder_options["sample_file"] = "branch.csv"
        folder_options["include_source_name"] = False
        branch_candidate = parse_folder(branch_dir, options=folder_options)
        self.assertTrue(controller._commit_import(branch_dir, branch_candidate))
        branch_id = controller.activeTableId

        first_query_id = self.add_append_query(
            controller, "Sales and orders", [sales_id, orders_id]
        )
        report_query_id = self.add_append_query(
            controller, "Report rows", [first_query_id, branch_id]
        )
        self.assertTrue(controller.canRefreshAllSources)

        (self.root / "sales.csv").write_text("id,value\nA,10\n", encoding="utf-8")
        (self.root / "orders.json").write_text(
            '[{"id":"B","value":20}]', encoding="utf-8"
        )
        branch_path.write_text("id,value\nC,30\n", encoding="utf-8")
        controller.refresh_all_sources()

        expected_current = [
            {"id": "A", "value": "10"},
            {"id": "B", "value": "20"},
            {"id": "C", "value": "30"},
        ]
        self.assertEqual(controller._loaded_candidates[first_query_id].rows, expected_current[:2])
        self.assertEqual(controller._loaded_candidates[report_query_id].rows, expected_current)
        self.assertEqual(controller._rows, expected_current)
        self.assertIn("Refreshed all supported linked sources", controller.statusMessage)

        self.assertTrue(controller.setQueryRefreshIncluded(first_query_id, False))
        cached_rows = copy.deepcopy(controller._loaded_candidates[first_query_id].rows)
        (self.root / "sales.csv").write_text("id,value\nA,11\n", encoding="utf-8")
        (self.root / "orders.json").write_text(
            '[{"id":"B","value":21}]', encoding="utf-8"
        )
        branch_path.write_text("id,value\nC,31\n", encoding="utf-8")
        controller.refresh_all_sources()

        self.assertEqual(controller._loaded_candidates[first_query_id].rows, cached_rows)
        self.assertEqual(controller._loaded_candidates[report_query_id].rows, [
            *cached_rows,
            {"id": "C", "value": "31"},
        ])

    def test_refresh_all_failure_keeps_all_previous_results_and_names_source(self) -> None:
        controller = self.controller()
        first_id = self.add_file(controller, "sales.csv", "id,value\nA,1\n")
        failed_path = self.root / "regions.json"
        failed_path.write_text('[{"id":"B","value":2}]', encoding="utf-8")
        self.assertTrue(controller._commit_import(failed_path, parse_file(failed_path)))
        failed_id = controller.activeTableId

        project_path = self.root / "project.npa"
        self.assertTrue(controller._save_to(project_path))
        prior_project = copy.deepcopy(controller._project)
        prior_candidates = copy.deepcopy(controller._loaded_candidates)
        prior_rows = copy.deepcopy(controller._rows)
        prior_dirty = controller._dirty

        (self.root / "sales.csv").write_text("id,value\nA,100\n", encoding="utf-8")
        failed_path.unlink()
        with patch.object(QMessageBox, "critical") as show_error:
            controller.refresh_all_sources()

        self.assertEqual(controller._project, prior_project)
        self.assertEqual(controller._loaded_candidates, prior_candidates)
        self.assertEqual(controller._rows, prior_rows)
        self.assertEqual(controller._dirty, prior_dirty)
        self.assertIn(failed_id, controller._source_load_errors)
        self.assertIn("regions.json", controller.sourceWarning)
        self.assertEqual(show_error.call_args.args[1], "Could not refresh all sources")
        self.assertIn("regions.json", show_error.call_args.args[2])
        self.assertIn(first_id, controller._loaded_candidates)

    def test_refresh_all_command_requires_a_linked_source_and_routes_to_controller(self) -> None:
        controller = self.controller()
        self.assertFalse(controller.canRefreshAllSources)
        self.assertTrue(controller._commit_inline(sample_candidate()))
        self.assertFalse(controller.canRefreshAllSources)

        self.add_file(controller, "sales.csv", "id,value\nA,1\n")
        self.assertTrue(controller.canRefreshAllSources)
        with patch.object(controller, "refresh_all_sources") as refresh_all:
            controller.executeCommand("refreshAllSources")
        refresh_all.assert_called_once_with()

    def test_qml_refresh_all_command_runs_from_the_data_view(self) -> None:
        controller = self.controller()
        self.assertFalse(controller.canRefreshAllSources)
        source_id = self.add_file(controller, "sales.csv", "id,value\nA,1\n")
        source_path = self.root / "sales.csv"

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
        self.assertTrue(window.commandAvailable("data.refreshAll"))
        self.assertEqual(window.commandUnavailableReason("data.refreshAll"), "")

        source_path.write_text("id,value\nA,2\n", encoding="utf-8")
        window.runCommand("data.refreshAll")
        self.app.processEvents()

        self.assertEqual(controller.activeTableId, source_id)
        self.assertEqual(controller._rows, [{"id": "A", "value": "2"}])
        window.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_refresh_all_refreshes_sqlite_and_pathless_connector_sources(self) -> None:
        controller = self.controller()
        database_path = self.root / "metrics.sqlite"
        with closing(sqlite3.connect(database_path)) as database:
            with database:
                database.execute("CREATE TABLE metrics (id INTEGER, value INTEGER)")
                database.execute("INSERT INTO metrics VALUES (1, 10)")
        sqlite_candidate = parse_file(
            database_path,
            options={"table_name": "metrics"},
            expected_kind="sqlite",
        )
        self.assertTrue(controller._commit_import(database_path, sqlite_candidate))
        sqlite_id = controller.activeTableId

        odata_candidate = ImportCandidate(
            "odata",
            ["id", "value"],
            [{"id": "O", "value": "1"}],
            {
                "entity_set_name": "Metrics",
                "entity_url": "https://example.test/odata/Metrics",
            },
            [],
        )
        self.assertTrue(controller._commit_odata_import(
            {"service_root": "https://example.test/odata/"}, odata_candidate
        ))
        odata_id = controller.activeTableId

        web_candidate = ImportCandidate(
            "web",
            ["id", "value"],
            [{"id": "W", "value": "1"}],
            {
                "resource_type": "csv",
                "delimiter": ",",
                "encoding": "utf-8",
                "has_header": True,
            },
            [],
        )
        self.assertTrue(controller._commit_web_import(
            {"url": "https://example.test/metrics.csv"}, web_candidate
        ))
        web_id = controller.activeTableId

        sql_candidate = ImportCandidate(
            "sql_server",
            ["id", "value"],
            [{"id": "S", "value": "1"}],
            {"schema": "dbo", "table_name": "Metrics", "object_type": "TABLE"},
            [],
        )
        sql_settings = {
            "server": "sql.example.test",
            "port": 1433,
            "database": "Analytics",
            "username": "reader",
            "driver": SUPPORTED_DRIVERS[0],
            "encrypt": True,
        }
        with patch("analytics_studio.controller.set_sql_server_password"):
            self.assertTrue(controller._commit_sql_server_import(
                sql_settings, "test-password", sql_candidate
            ))
        sql_id = controller.activeTableId

        with closing(sqlite3.connect(database_path)) as database:
            with database:
                database.execute("UPDATE metrics SET value = 20 WHERE id = 1")
                database.execute("INSERT INTO metrics VALUES (2, 30)")

        refreshed_odata = ImportCandidate(
            "odata", ["id", "value"], [{"id": "O", "value": "2"}], {}, []
        )
        refreshed_web = ImportCandidate(
            "web", ["id", "value"], [{"id": "W", "value": "2"}], {}, []
        )
        refreshed_sql = ImportCandidate(
            "sql_server", ["id", "value"], [{"id": "S", "value": "2"}], {}, []
        )
        with (
            patch.object(controller, "_odata_candidate_for_source", return_value=refreshed_odata) as odata_read,
            patch.object(controller, "_web_candidate_for_source", return_value=refreshed_web) as web_read,
            patch.object(controller, "_sql_server_candidate_for_source", return_value=refreshed_sql) as sql_read,
        ):
            controller.refresh_all_sources()

        self.assertEqual(odata_read.call_count, 1)
        self.assertEqual(web_read.call_count, 1)
        self.assertEqual(sql_read.call_count, 1)
        self.assertEqual(controller._loaded_candidates[sqlite_id].rows, [
            {"id": "1", "value": "20"},
            {"id": "2", "value": "30"},
        ])
        self.assertEqual(controller._loaded_candidates[odata_id].rows, [{"id": "O", "value": "2"}])
        self.assertEqual(controller._loaded_candidates[web_id].rows, [{"id": "W", "value": "2"}])
        self.assertEqual(controller._loaded_candidates[sql_id].rows, [{"id": "S", "value": "2"}])

    def test_refresh_all_reparses_excel_xml_and_parquet_files(self) -> None:
        import pyarrow as pa
        import pyarrow.parquet as parquet

        controller = self.controller()
        excel_path = self.root / "sheet.xlsx"
        xml_path = self.root / "records.xml"
        parquet_path = self.root / "records.parquet"

        self.write_xlsx(excel_path, [("X", "1")])
        self.write_xml(xml_path, [("M", "1")])
        parquet.write_table(
            pa.Table.from_pylist([{"id": "P", "value": "1"}]), parquet_path
        )
        self.assertTrue(controller._commit_import(excel_path, parse_file(excel_path)))
        excel_id = controller.activeTableId
        self.assertTrue(controller._commit_import(xml_path, parse_file(xml_path)))
        xml_id = controller.activeTableId
        self.assertTrue(controller._commit_import(parquet_path, parse_file(parquet_path)))
        parquet_id = controller.activeTableId

        self.write_xlsx(excel_path, [("X", "2"), ("Y", "3")])
        self.write_xml(xml_path, [("M", "2"), ("N", "3")])
        parquet.write_table(
            pa.Table.from_pylist([
                {"id": "P", "value": "2"},
                {"id": "Q", "value": "3"},
            ]),
            parquet_path,
        )
        controller.refresh_all_sources()

        self.assertEqual(controller._loaded_candidates[excel_id].rows, [
            {"id": "X", "value": "2"},
            {"id": "Y", "value": "3"},
        ])
        self.assertEqual(controller._loaded_candidates[xml_id].rows, [
            {"id": "M", "value": "2"},
            {"id": "N", "value": "3"},
        ])
        self.assertEqual(controller._loaded_candidates[parquet_id].rows, [
            {"id": "P", "value": "2"},
            {"id": "Q", "value": "3"},
        ])


if __name__ == "__main__":
    unittest.main()
