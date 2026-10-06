"""Preview, commit, save, reopen, and refresh behavior for file imports."""

from __future__ import annotations

import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.import_preview_dialog import FileImportPreviewDialog


class ImportLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])
        families = QFontDatabase.families()
        if families:
            cls.app.setFont(QFont(families[0]))

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_xlsx(self, path: Path) -> None:
        workbook = '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''
        relationships = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''
        sheet = '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1"><c r="A1" t="inlineStr"><is><t>name</t></is></c><c r="B1" t="inlineStr"><is><t>amount</t></is></c></row>
 <row r="2"><c r="A2" t="inlineStr"><is><t>Ada</t></is></c><c r="B2"><v>12</v></c></row>
</sheetData></worksheet>'''
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", relationships)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)

    def test_preview_requires_accept_and_uses_selected_csv_options(self) -> None:
        path = self.root / "sales.csv"
        path.write_text("name;amount\nAda;12\n", encoding="utf-8")

        dialog = FileImportPreviewDialog(path, replacing=False)

        self.assertIsNone(dialog.candidate)
        self.assertEqual(dialog.table.model().columnCount(), 1)
        dialog.delimiter_combo.setCurrentIndex(dialog.delimiter_combo.findData(";"))
        preview = dialog.table.model()
        self.assertEqual(preview.columnCount(), 2)
        self.assertEqual(preview.rowCount(), 1)
        self.assertEqual(preview.data(preview.index(0, 0)), "Ada")

        dialog._accept_candidate()

        self.assertEqual(dialog.candidate.options["delimiter"], ";")
        self.assertEqual(dialog.candidate.rows, [{"name": "Ada", "amount": "12"}])

    def test_preview_commit_and_reopen_work_for_all_supported_file_formats(self) -> None:
        csv_path = self.root / "sales.csv"
        csv_path.write_text("name,amount\nAda,12\n", encoding="utf-8")
        excel_path = self.root / "sales.xlsx"
        self.write_xlsx(excel_path)
        json_path = self.root / "sales.json"
        json_path.write_text('[{"name":"Ada","amount":12}]', encoding="utf-8")
        xml_path = self.root / "sales.xml"
        xml_path.write_text(
            "<root><record><name>Ada</name><amount>12</amount></record></root>",
            encoding="utf-8",
        )

        expected = {"name": "Ada", "amount": "12"}
        for source_path in (csv_path, excel_path, json_path, xml_path):
            with self.subTest(kind=source_path.suffix):
                controller = StudioController(self.app)
                dialog = FileImportPreviewDialog(source_path, replacing=False)
                self.assertIsNone(dialog.candidate)
                self.assertEqual(dialog.table.model().rowCount(), 1)
                self.assertEqual(dialog.table.model().columnCount(), 2)

                dialog._accept_candidate()
                candidate = dialog.candidate
                self.assertEqual(candidate.rows, [expected])
                self.assertTrue(controller._commit_import(source_path, candidate))
                self.assertEqual(controller._rows, [expected])

                project_path = self.root / f"{source_path.stem}.npa"
                self.assertTrue(controller._save_to(project_path))
                reopened = StudioController(self.app)
                self.assertTrue(reopened.open_project_path(project_path))
                self.assertEqual(reopened._rows, [expected])
                self.assertEqual(reopened._active_source_kind, candidate.kind)
                self.assertEqual(reopened._active_parser_options, candidate.options)

    def test_catalog_file_entries_route_to_the_matching_importer(self) -> None:
        controller = StudioController(self.app)
        cases = {
            "file_text_csv": "csv",
            "file_excel_workbook": "excel",
            "file_json": "json",
            "file_xml": "xml",
        }

        with patch.object(controller, "import_data_dialog") as import_dialog:
            for source_id, kind in cases.items():
                with self.subTest(source_id=source_id):
                    self.assertTrue(controller.connectDataSource(source_id))
                    import_dialog.assert_called_with(expected_kind=kind)

    def test_canceling_file_replacement_preserves_the_loaded_source(self) -> None:
        current_path = self.root / "current.csv"
        current_path.write_text("id\n1\n", encoding="utf-8")
        replacement_path = self.root / "replacement.csv"
        replacement_path.write_text("id\n2\n", encoding="utf-8")
        controller = StudioController(self.app)
        self.assertTrue(controller._commit_import(current_path, parse_file(current_path)))
        original_project = copy.deepcopy(controller._project)

        with patch.object(FileImportPreviewDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            committed = controller.import_data_path(replacement_path)

        self.assertFalse(committed)
        self.assertEqual(controller._project, original_project)
        self.assertEqual(controller._source_path, current_path.resolve())
        self.assertEqual(controller._rows, [{"id": "1"}])
        self.assertTrue(controller._dirty)

    def test_save_reopen_refresh_and_failed_refresh_preserve_last_good_rows(self) -> None:
        source_path = self.root / "sales.csv"
        source_path.write_text("name;amount\nAda;12\n", encoding="utf-8")
        project_path = self.root / "sales.npa"
        controller = StudioController(self.app)
        candidate = parse_file(source_path, {"delimiter": ";"})

        self.assertTrue(controller._commit_import(source_path, candidate))
        self.assertTrue(controller._save_to(project_path))

        reopened = StudioController(self.app)
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._active_parser_options["delimiter"], ";")
        self.assertEqual(reopened._rows, [{"name": "Ada", "amount": "12"}])

        source_path.write_text("name;amount\nAda;12\nLin;18\n", encoding="utf-8")
        reopened.refresh_source()
        self.assertEqual(reopened.rowCount, 2)

        reopened.add_page()
        last_good_rows = copy.deepcopy(reopened._rows)
        last_good_project = copy.deepcopy(reopened._project)
        dirty_before = reopened._dirty
        source_path.write_text('name;amount\n"unterminated;25\n', encoding="utf-8")
        with patch.object(QMessageBox, "critical"):
            reopened.refresh_source()

        self.assertEqual(reopened._rows, last_good_rows)
        self.assertEqual(reopened._project, last_good_project)
        self.assertEqual(reopened._dirty, dirty_before)
        self.assertIn("Could not read linked data file", reopened.sourceWarning)

    def test_deep_json_parse_error_is_handled_on_refresh_and_project_open(self) -> None:
        source_path = self.root / "records.json"
        source_path.write_text('[{"id":1}]', encoding="utf-8")
        project_path = self.root / "records.npa"
        controller = StudioController(self.app)
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        self.assertTrue(controller._save_to(project_path))
        good_rows = copy.deepcopy(controller._rows)
        good_project = copy.deepcopy(controller._project)
        source_path.write_text(
            "[" + "[" * 100_000 + "0" + "]" * 100_000 + "]",
            encoding="utf-8",
        )

        with patch.object(QMessageBox, "critical"):
            controller.refresh_source()

        self.assertEqual(controller._rows, good_rows)
        self.assertEqual(controller._project, good_project)
        self.assertIn("nesting exceeds", controller.sourceWarning)

        reopened = StudioController(self.app)
        with patch.object(QMessageBox, "warning"):
            self.assertTrue(reopened.open_project_path(project_path))

        self.assertFalse(reopened.sourceLoaded)
        self.assertIn("nesting exceeds", reopened.sourceWarning)


if __name__ == "__main__":
    unittest.main()
