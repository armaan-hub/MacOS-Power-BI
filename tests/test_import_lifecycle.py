"""Preview, commit, save, reopen, and refresh behavior for file imports."""

from __future__ import annotations

import copy
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from typing import Any
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QToolButton

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCancelledError, parse_file
from analytics_studio.import_preview_dialog import FileImportPreviewDialog
from analytics_studio.local_table_dialogs import TransformDataDialog


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
        self.settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )

    def new_controller(self) -> StudioController:
        return StudioController(self.app, self.settings)

    def wait_for_preview(self, dialog: FileImportPreviewDialog) -> None:
        deadline = time.monotonic() + 5
        while not dialog.import_button.isEnabled() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(dialog.import_button.isEnabled())

    def wait_for_acceptance(self, dialog: FileImportPreviewDialog) -> None:
        deadline = time.monotonic() + 5
        while (
            dialog.result() != QDialog.DialogCode.Accepted
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

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

    def write_xlsx_with_header_preamble(self, path: Path) -> None:
        workbook = '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="VAT 5%" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''
        relationships = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''

        def cell(reference: str, value: object) -> str:
            if value is None:
                return ""
            if isinstance(value, int):
                return f'<c r="{reference}"><v>{value}</v></c>'
            return f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'

        rows = [
            f'<row r="{row}">{cell(f"A{row}", f"Report title {row}")}</row>'
            for row in range(1, 12)
        ]
        rows.extend((
            '<row r="12">'
            f'{cell("A12", "Date")}{cell("B12", "Particulars")}{cell("C12", "Value")}'
            '</row>',
            '<row r="13">'
            f'{cell("A13", "2026-08-01")}{cell("B13", "Sale")}{cell("C13", 100)}'
            '</row>',
            # Row 14 is omitted; auto mode drops this internal gap and the
            # trailing empty rows, while an accidental manual reparse retains
            # them and changes the row count.
            '<row r="15">'
            f'{cell("B15", "Grand Total")}{cell("C15", 100)}'
            '</row>',
            '<row r="16"></row>',
            '<row r="17"></row>',
            '<row r="18"></row>',
        ))
        sheet = (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(rows)}</sheetData></worksheet>'
        )
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", relationships)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)

    def write_two_sheet_xlsx(self, path: Path) -> None:
        workbook = '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="Data" sheetId="1" r:id="rId1"/>
 <sheet name="Archive" sheetId="2" r:id="rId2"/></sheets>
</workbook>'''
        relationships = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
 <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>'''

        def sheet(name: str, amount: int) -> str:
            return f'''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1"><c r="A1" t="inlineStr"><is><t>name</t></is></c><c r="B1" t="inlineStr"><is><t>amount</t></is></c></row>
 <row r="2"><c r="A2" t="inlineStr"><is><t>  {name}  </t></is></c><c r="B2"><v>{amount}</v></c></row>
</sheetData></worksheet>'''

        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", relationships)
            archive.writestr("xl/worksheets/sheet1.xml", sheet("  Ada  ", 12))
            archive.writestr("xl/worksheets/sheet2.xml", sheet("Grace", 8))

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

    def test_excel_preview_notice_and_load_transform_buttons(self) -> None:
        path = self.root / "header-preamble.xlsx"
        self.write_xlsx_with_header_preamble(path)
        notice = (
            "Using worksheet row 12 as column names; rows 1–11 are excluded "
            "from the imported table."
        )
        expected_options = {
            "load": {"sheet_name": "VAT 5%", "header_row": None},
            "transform": {"sheet_name": "VAT 5%", "header_row": None, "raw_rows": True},
        }
        expected_transform = parse_file(path, options=expected_options["transform"])
        accepted_candidates = {}

        for action in ("load", "transform"):
            with self.subTest(action=action):
                dialog = FileImportPreviewDialog(
                    path,
                    replacing=False,
                    initial_options={"header_row": None},
                )
                self.wait_for_preview(dialog)

                candidate = dialog._preview_candidate
                self.assertIsNotNone(candidate)
                assert candidate is not None
                self.assertEqual(candidate.options["sheet_name"], "VAT 5%")
                self.assertIsNone(candidate.options["header_row"])
                self.assertTrue(dialog.header_auto_checkbox.isChecked())
                self.assertIn(notice, candidate.notices)
                self.assertEqual(candidate.headers, ["Date", "Particulars", "Value"])
                self.assertEqual(candidate.row_count, 2)
                self.assertIn("Grand Total", [row["Particulars"] for row in candidate.rows])
                self.assertEqual(dialog.notice_label.text(), notice)
                self.assertTrue(dialog.import_button.isEnabled())
                self.assertFalse(dialog.import_button.isHidden())
                self.assertFalse(dialog.transform_button.isHidden())
                self.assertTrue(dialog.transform_button.isEnabled())
                self.assertTrue(dialog.transform_raw_rows_checkbox.isChecked())

                if action == "load":
                    dialog.import_button.click()
                else:
                    dialog.transform_button.click()
                    self.wait_for_acceptance(dialog)
                self.assertEqual(dialog.selected_action, action)
                accepted_candidates[action] = dialog.candidate
                self.assertIsNotNone(dialog.candidate)
                self.assertEqual(dialog.candidate.options, expected_options[action])

        self.assertEqual(
            accepted_candidates["load"].headers,
            ["Date", "Particulars", "Value"],
        )
        self.assertEqual(
            accepted_candidates["transform"].headers,
            expected_transform.headers,
        )
        self.assertEqual(
            accepted_candidates["transform"].rows,
            expected_transform.rows,
        )

    def test_excel_transform_respects_a_manual_header_row(self) -> None:
        path = self.root / "manual-header.xlsx"
        self.write_xlsx_with_header_preamble(path)
        dialog = FileImportPreviewDialog(
            path,
            replacing=False,
            initial_options={"sheet_name": "VAT 5%", "header_row": 2},
        )
        self.wait_for_preview(dialog)

        self.assertTrue(dialog.transform_raw_rows_checkbox.isChecked())
        self.assertTrue(dialog.transform_raw_rows_checkbox.isEnabled())
        dialog.transform_raw_rows_checkbox.setChecked(False)
        dialog.transform_button.click()
        self.wait_for_acceptance(dialog)

        self.assertEqual(
            dialog.candidate.options,
            {"sheet_name": "VAT 5%", "header_row": 2},
        )

    def test_excel_transform_can_keep_automatic_header_detection(self) -> None:
        path = self.root / "automatic-transform.xlsx"
        self.write_xlsx_with_header_preamble(path)
        dialog = FileImportPreviewDialog(path, replacing=False)
        self.wait_for_preview(dialog)

        self.assertEqual(dialog._preview_candidate.options["header_row"], 1)
        self.assertTrue(dialog.transform_raw_rows_checkbox.isChecked())
        dialog.header_auto_checkbox.setChecked(True)
        self.assertTrue(dialog.transform_raw_rows_checkbox.isChecked())
        self.wait_for_preview(dialog)
        self.assertTrue(dialog.transform_raw_rows_checkbox.isChecked())
        dialog.transform_raw_rows_checkbox.setChecked(False)
        dialog.transform_button.click()

        self.assertEqual(dialog.selected_action, "transform")
        self.assertEqual(
            dialog.candidate.options,
            {"sheet_name": "VAT 5%", "header_row": None},
        )

    def test_cancel_during_excel_transform_reparse_never_accepts_stale_candidate(self) -> None:
        path = self.root / "cancel-transform.xlsx"
        self.write_xlsx_with_header_preamble(path)
        dialog = FileImportPreviewDialog(path, replacing=False)
        self.wait_for_preview(dialog)
        original_parse_file = parse_file
        parse_started = threading.Event()
        release_parse = threading.Event()

        def delayed_raw_rows_parse(
            candidate_path: Path,
            options: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> object:
            if options and options.get("raw_rows") is True:
                parse_started.set()
                release_parse.wait(timeout=5)
            return original_parse_file(candidate_path, options=options, **kwargs)

        with patch(
            "analytics_studio.import_preview_dialog.parse_file",
            side_effect=delayed_raw_rows_parse,
        ):
            dialog.transform_button.click()
            deadline = time.monotonic() + 5
            while not parse_started.is_set() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
            self.assertTrue(parse_started.is_set())
            dialog.reject()
            release_parse.set()

            deadline = time.monotonic() + 5
            while dialog._parse_tasks and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
            self.app.processEvents()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        self.assertIsNone(dialog.candidate)
        self.assertIsNone(dialog.selected_action)

    def test_failed_excel_transform_reparse_does_not_accept_auto_preview(self) -> None:
        path = self.root / "failed-transform.xlsx"
        self.write_xlsx_with_header_preamble(path)
        dialog = FileImportPreviewDialog(path, replacing=False)
        self.wait_for_preview(dialog)
        original_parse_file = parse_file
        fail_next_raw_rows = True

        def fail_raw_rows(candidate_path: Path, options: dict[str, Any] | None = None, **kwargs: Any) -> object:
            nonlocal fail_next_raw_rows
            if options and options.get("raw_rows") is True:
                if fail_next_raw_rows:
                    fail_next_raw_rows = False
                    raise ValueError("raw-row reparse failed")
            return original_parse_file(candidate_path, options=options, **kwargs)

        with patch(
            "analytics_studio.import_preview_dialog.parse_file",
            side_effect=fail_raw_rows,
        ):
            dialog.transform_button.click()
            deadline = time.monotonic() + 5
            while not dialog._last_error and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
            self.app.processEvents()
            self.assertIn("raw-row reparse failed", dialog._last_error)
            self.assertIn("automatic preview is restored", dialog._last_error)
            self.assertEqual(
                dialog._preview_candidate.options,
                {"sheet_name": "VAT 5%", "header_row": 1},
            )
            self.assertTrue(dialog.import_button.isEnabled())
            self.assertTrue(dialog.transform_button.isEnabled())
            dialog.transform_button.click()
            self.wait_for_acceptance(dialog)

        self.assertTrue(dialog.candidate.options["raw_rows"])

    def test_excel_load_and_transform_commit_save_reopen_keep_their_source_modes(self) -> None:
        path = self.root / "header-preamble.xlsx"
        self.write_xlsx_with_header_preamble(path)
        expected_by_action = {
            "load": parse_file(
                path,
                options={"sheet_name": "VAT 5%", "header_row": 1},
            ),
            "transform": parse_file(
                path,
                options={"sheet_name": "VAT 5%", "header_row": None, "raw_rows": True},
            ),
        }

        for action in ("load", "transform"):
            with self.subTest(action=action):
                expected_candidate = expected_by_action[action]
                controller = self.new_controller()
                project_before = copy.deepcopy(controller._project)
                candidates_before = copy.deepcopy(controller._loaded_candidates)
                headers_before = controller.headers
                rows_before = copy.deepcopy(controller._rows)
                accepted_preview = {}

                def choose_preview_action(
                    dialog: FileImportPreviewDialog,
                    selected_action: str = action,
                ) -> int:
                    self.wait_for_preview(dialog)
                    self.assertEqual(
                        dialog._preview_candidate.options,
                        {"sheet_name": "VAT 5%", "header_row": 1},
                    )
                    self.assertTrue(dialog.transform_raw_rows_checkbox.isEnabled())
                    self.assertTrue(dialog.transform_raw_rows_checkbox.isChecked())
                    self.assertEqual(
                        dialog._preview_candidate.row_count,
                        expected_by_action["load"].row_count,
                    )
                    button = (
                        dialog.import_button
                        if selected_action == "load"
                        else dialog.transform_button
                    )
                    dialog.show()
                    self.app.processEvents()
                    self.assertTrue(button.isEnabled())
                    self.assertTrue(button.isVisible())
                    button.click()
                    if selected_action == "transform":
                        self.wait_for_acceptance(dialog)
                    self.assertEqual(dialog.selected_action, selected_action)
                    self.assertIsNotNone(dialog.candidate)
                    accepted_preview["candidate"] = dialog.candidate
                    return QDialog.DialogCode.Accepted

                def close_and_apply(dialog: TransformDataDialog) -> int:
                    self.assertEqual(len(dialog._query_states), 1)
                    staged = next(iter(dialog._query_states.values()))
                    self.assertTrue(staged["is_new_source"])
                    self.assertEqual(
                        staged["source_candidate"].options,
                        expected_candidate.options,
                    )
                    self.assertEqual(
                        staged["source_candidate"].headers,
                        expected_candidate.headers,
                    )
                    self.assertEqual(
                        staged["source_candidate"].rows,
                        expected_candidate.rows,
                    )

                    # A first-import Transform stays staged until the visible
                    # Home ribbon Close & Load command accepts the session.
                    self.assertEqual(controller._project, project_before)
                    self.assertEqual(controller._loaded_candidates, candidates_before)
                    self.assertEqual(controller.headers, headers_before)
                    self.assertEqual(controller._rows, rows_before)
                    self.assertFalse(controller.sourceLoaded)
                    self.assertIsNone(controller._active_source_id)
                    self.assertFalse(controller.dirty)

                    close_load_button = dialog.findChild(
                        QToolButton, "powerQueryCloseApplyButton"
                    )
                    self.assertIsNotNone(close_load_button)
                    dialog.show()
                    self.app.processEvents()
                    assert close_load_button is not None
                    self.assertTrue(dialog.ribbon_tabs.isAncestorOf(close_load_button))
                    self.assertEqual(
                        dialog.ribbon_tabs.tabText(dialog.ribbon_tabs.currentIndex()),
                        "Home",
                    )
                    self.assertEqual(
                        " ".join(close_load_button.text().split()), "Close & Load"
                    )
                    self.assertFalse(dialog.buttons.isVisible())
                    self.assertTrue(close_load_button.isVisible())
                    self.assertTrue(close_load_button.isEnabled())
                    close_load_button.click()
                    self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
                    self.assertIsNotNone(dialog.accepted_queries)
                    return dialog.result()

                with patch.object(
                    FileImportPreviewDialog, "exec", new=choose_preview_action
                ):
                    if action == "transform":
                        with patch.object(
                            TransformDataDialog, "exec", new=close_and_apply
                        ):
                            self.assertTrue(controller.import_excel_path(path))
                    else:
                        self.assertTrue(controller.import_excel_path(path))

                candidate = accepted_preview["candidate"]
                self.assertEqual(candidate.options, expected_candidate.options)
                self.assertEqual(controller.headers, expected_candidate.headers)
                self.assertEqual(controller._rows, expected_candidate.rows)
                self.assertEqual(
                    controller._active_parser_options,
                    expected_candidate.options,
                )
                self.assertEqual(len(controller._project["data_sources"]), 1)
                source = controller._project["data_sources"][0]
                self.assertEqual(source["parser_options"], expected_candidate.options)

                project_path = self.root / f"{action}-header-preamble.npa"
                self.assertTrue(controller._save_to(project_path))
                reopened = self.new_controller()
                self.assertTrue(reopened.open_project_path(project_path))
                self.assertEqual(reopened.headers, expected_candidate.headers)
                self.assertEqual(reopened._rows, expected_candidate.rows)
                self.assertEqual(
                    reopened._active_parser_options,
                    expected_candidate.options,
                )
                reopened.refresh_source()
                self.assertEqual(reopened.headers, expected_candidate.headers)
                self.assertEqual(reopened._rows, expected_candidate.rows)

    def test_excel_header_modes_have_distinct_source_ids_and_refresh_independently(self) -> None:
        path = self.root / "two-header-modes.xlsx"
        self.write_xlsx_with_header_preamble(path)
        auto_candidate = parse_file(
            path,
            options={"sheet_name": "VAT 5%", "header_row": None},
        )
        row_one_candidate = parse_file(
            path,
            options={"sheet_name": "VAT 5%", "header_row": 1},
        )
        self.assertEqual(auto_candidate.header_row_used, 12)
        self.assertEqual(row_one_candidate.header_row_used, 1)
        controller = self.new_controller()

        self.assertTrue(controller._commit_import(path, auto_candidate))
        auto_source_id = controller.activeTableId
        auto_source = next(
            source for source in controller._project["data_sources"]
            if source["id"] == auto_source_id
        )
        self.assertTrue(controller._commit_import(path, row_one_candidate))
        row_one_source_id = controller.activeTableId
        row_one_source = next(
            source for source in controller._project["data_sources"]
            if source["id"] == row_one_source_id
        )
        self.assertNotEqual(auto_source_id, row_one_source_id)
        tables_by_source_id = {
            str(table.get("source_id", table.get("id"))): table
            for table in controller._project["model"]["tables"]
        }
        self.assertNotEqual(
            tables_by_source_id[auto_source_id]["name"],
            tables_by_source_id[row_one_source_id]["name"],
        )
        self.assertEqual(
            controller._source_id_for_path(
                path,
                kind="excel",
                parser_options=auto_candidate.options,
            ),
            auto_source_id,
        )
        self.assertEqual(
            controller._source_id_for_path(
                path,
                kind="excel",
                parser_options=row_one_candidate.options,
            ),
            row_one_source_id,
        )

        row_one_source["transform_steps"] = [
            {"op": "remove_top_rows", "count": 1},
        ]
        self.assertTrue(controller._commit_import(path, auto_candidate))
        self.assertEqual(controller.activeTableId, auto_source_id)
        self.assertEqual(auto_source["transform_steps"], [])
        self.assertEqual(
            row_one_source["transform_steps"],
            [{"op": "remove_top_rows", "count": 1}],
        )

        project_path = self.root / "two-header-modes.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.new_controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            reopened._source_id_for_path(
                path,
                kind="excel",
                parser_options=auto_candidate.options,
            ),
            auto_source_id,
        )
        self.assertEqual(
            reopened._source_id_for_path(
                path,
                kind="excel",
                parser_options=row_one_candidate.options,
            ),
            row_one_source_id,
        )
        reopened.refresh_all_sources()
        self.assertEqual(
            reopened._loaded_candidates[auto_source_id].headers,
            auto_candidate.headers,
        )
        self.assertEqual(
            reopened._loaded_candidates[auto_source_id].rows,
            auto_candidate.rows,
        )
        self.assertEqual(
            reopened._project["data_sources"][1]["transform_steps"],
            [{"op": "remove_top_rows", "count": 1}],
        )

    def test_excel_raw_rows_and_automatic_headers_have_distinct_source_ids(self) -> None:
        path = self.root / "raw-and-automatic.xlsx"
        self.write_xlsx_with_header_preamble(path)
        automatic_candidate = parse_file(
            path,
            options={"sheet_name": "VAT 5%", "header_row": None},
        )
        raw_candidate = parse_file(
            path,
            options={"sheet_name": "VAT 5%", "header_row": None, "raw_rows": True},
        )
        controller = self.new_controller()

        self.assertTrue(controller._commit_import(path, automatic_candidate))
        automatic_source_id = controller.activeTableId
        self.assertTrue(controller._commit_import(path, raw_candidate))
        raw_source_id = controller.activeTableId
        self.assertNotEqual(automatic_source_id, raw_source_id)
        self.assertEqual(len(controller._project["data_sources"]), 2)

        self.assertEqual(
            controller._source_id_for_path(
                path,
                kind="excel",
                parser_options=automatic_candidate.options,
                header_row_used=automatic_candidate.header_row_used,
            ),
            automatic_source_id,
        )
        self.assertEqual(
            controller._source_id_for_path(
                path,
                kind="excel",
                parser_options=raw_candidate.options,
                header_row_used=raw_candidate.header_row_used,
            ),
            raw_source_id,
        )

        project_path = self.root / "raw-and-automatic.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.new_controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            reopened._source_id_for_path(
                path,
                kind="excel",
                parser_options=automatic_candidate.options,
                header_row_used=automatic_candidate.header_row_used,
            ),
            automatic_source_id,
        )
        self.assertEqual(
            reopened._source_id_for_path(
                path,
                kind="excel",
                parser_options=raw_candidate.options,
                header_row_used=raw_candidate.header_row_used,
            ),
            raw_source_id,
        )
        controller = reopened

        replacement_matches: list[str | None] = []

        def replacement_check(candidate: Any) -> bool:
            matched_source_id = controller._source_id_for_path(
                path,
                kind=candidate.kind,
                parser_options=candidate.options,
                header_row_used=candidate.header_row_used,
            )
            replacement_matches.append(matched_source_id)
            return matched_source_id is not None

        dialog = FileImportPreviewDialog(
            path,
            replacing=False,
            initial_options={"sheet_name": "VAT 5%", "header_row": None},
            replacement_check=replacement_check,
        )
        self.wait_for_preview(dialog)
        self.assertEqual(replacement_matches, [automatic_source_id])
        self.assertFalse(dialog.replacement_label.isHidden())

        dialog.transform_button.click()
        self.wait_for_acceptance(dialog)
        self.assertEqual(dialog.candidate.options, raw_candidate.options)
        self.assertEqual(
            replacement_matches,
            [automatic_source_id, raw_source_id],
        )
        self.assertFalse(dialog.replacement_label.isHidden())

    def test_auto_header_reimport_reuses_legacy_numeric_header_source(self) -> None:
        path = self.root / "legacy-auto-header.xlsx"
        self.write_xlsx_with_header_preamble(path)
        legacy_candidate = parse_file(
            path,
            options={"sheet_name": "VAT 5%", "header_row": 12},
        )
        auto_candidate = parse_file(
            path,
            options={"sheet_name": "VAT 5%", "header_row": None},
        )
        self.assertEqual(auto_candidate.header_row_used, 12)
        controller = self.new_controller()
        self.assertTrue(controller._commit_import(path, legacy_candidate))
        legacy_source_id = controller.activeTableId

        project_path = self.root / "legacy-auto-header.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.new_controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            reopened._source_id_for_path(
                path,
                kind="excel",
                parser_options=auto_candidate.options,
                header_row_used=auto_candidate.header_row_used,
            ),
            legacy_source_id,
        )

        self.assertTrue(reopened._commit_import(path, auto_candidate))
        self.assertEqual(reopened.activeTableId, legacy_source_id)
        self.assertEqual(len(reopened._project["data_sources"]), 1)
        self.assertEqual(
            reopened._project["data_sources"][0]["parser_options"],
            {"sheet_name": "VAT 5%", "header_row": None},
        )

    def test_auto_header_reimport_prefers_exact_match_over_legacy_fallback(self) -> None:
        path = self.root / "auto-and-legacy-header.xlsx"
        self.write_xlsx_with_header_preamble(path)
        auto_candidate = parse_file(
            path,
            options={"sheet_name": "VAT 5%", "header_row": None},
        )
        legacy_candidate = parse_file(
            path,
            options={"sheet_name": "VAT 5%", "header_row": 12},
        )
        controller = self.new_controller()
        self.assertTrue(controller._commit_import(path, auto_candidate))
        exact_auto_source_id = controller.activeTableId
        self.assertTrue(controller._commit_import(path, legacy_candidate))
        legacy_source_id = controller.activeTableId
        self.assertNotEqual(legacy_source_id, exact_auto_source_id)

        # Persisted projects can contain both modes in either order. A legacy
        # compatibility match must not shadow the exact automatic source.
        controller._project["data_sources"].reverse()
        self.assertEqual(
            controller._source_id_for_path(
                path,
                kind="excel",
                parser_options=auto_candidate.options,
                header_row_used=auto_candidate.header_row_used,
            ),
            exact_auto_source_id,
        )

    def test_preview_restores_parser_options_for_a_recent_source(self) -> None:
        path = self.root / "sales.csv"
        path.write_text("name;amount\nAda;12\n", encoding="utf-8")

        dialog = FileImportPreviewDialog(
            path, replacing=False, initial_options={"delimiter": ";"}
        )

        self.assertEqual(dialog.table.model().columnCount(), 2)
        self.assertEqual(dialog.table.model().data(dialog.table.model().index(0, 0)), "Ada")

    def test_large_preview_runs_in_background_and_reports_completion(self) -> None:
        path = self.root / "large-preview.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write("id,description\n")
            for row_index in range(6_000):
                stream.write(f"{row_index},{'x' * 60}\n")

        dialog = FileImportPreviewDialog(path, replacing=False)
        self.assertIsNotNone(dialog._active_parse_id)
        self.assertFalse(dialog.import_button.isEnabled())
        self.assertFalse(dialog.progress_widget.isHidden())

        deadline = time.monotonic() + 5
        while dialog._active_parse_id is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()

        self.assertIsNone(dialog._active_parse_id)
        self.assertTrue(dialog.import_button.isEnabled())
        self.assertTrue(dialog.progress_widget.isHidden())
        self.assertEqual(dialog.table.model().rowCount(), 100)
        self.assertIn("6,000 rows total", dialog.count_label.text())
        dialog._accept_candidate()
        self.assertEqual(dialog.candidate.row_count, 6_000)

    def test_cancel_dialog_stops_a_background_preview(self) -> None:
        path = self.root / "large-cancel.csv"
        path.write_bytes(b"x" * (256 * 1024 + 1))
        parser_started = threading.Event()
        cancellation_seen = threading.Event()

        def wait_for_cancel(
            _path: Path,
            *,
            options: dict[str, object],
            cancel_event: threading.Event,
            progress_callback: object,
        ) -> None:
            del options
            assert callable(progress_callback)
            progress_callback("Read 5,000 CSV rows…")
            parser_started.set()
            cancel_event.wait(2)
            if cancel_event.is_set():
                cancellation_seen.set()
            raise ImportCancelledError("Import canceled.")

        with patch(
            "analytics_studio.import_preview_dialog.parse_file",
            side_effect=wait_for_cancel,
        ):
            dialog = FileImportPreviewDialog(path, replacing=False)
            self.assertTrue(parser_started.wait(2))
            self.app.processEvents()
            self.assertIn("5,000 CSV rows", dialog.progress_label.text())
            dialog.reject()
            self.assertTrue(cancellation_seen.wait(2))

        self.assertIsNone(dialog._accepted_candidate)

    def test_excel_options_are_discovered_off_ui_thread_before_preview(self) -> None:
        path = self.root / "async-options.xlsx"
        self.write_xlsx(path)
        discovery_started = threading.Event()
        release_discovery = threading.Event()
        discovery_finished = threading.Event()
        worker_thread_ids: list[int] = []
        parser_thread_ids: list[int] = []

        def blocked_discovery(*_args: object, **_kwargs: object) -> tuple[list[str], str]:
            worker_thread_ids.append(threading.get_ident())
            discovery_started.set()
            release_discovery.wait(2)
            discovery_finished.set()
            return ["Data"], "Data"

        def record_parse(*args: Any, **kwargs: Any) -> object:
            parser_thread_ids.append(threading.get_ident())
            return parse_file(*args, **kwargs)

        with (
            patch(
                "analytics_studio.import_preview_dialog.inspect_excel_options",
                side_effect=blocked_discovery,
            ),
            patch(
                "analytics_studio.import_preview_dialog.parse_file",
                side_effect=record_parse,
            ) as parse_mock,
        ):
            dialog = FileImportPreviewDialog(path, replacing=False)
            self.assertTrue(discovery_started.wait(2))
            self.assertNotEqual(worker_thread_ids[0], threading.get_ident())
            self.assertFalse(dialog.import_button.isEnabled())
            self.assertFalse(dialog.progress_widget.isHidden())
            self.assertEqual(parse_mock.call_count, 0)

            timer_fired: list[bool] = []
            QTimer.singleShot(0, lambda: timer_fired.append(True))
            self.app.processEvents()
            self.assertEqual(timer_fired, [True])
            self.assertEqual(parse_mock.call_count, 0)

            release_discovery.set()
            self.wait_for_preview(dialog)

        self.assertTrue(discovery_finished.is_set())
        self.assertEqual(dialog.sheet_combo.currentText(), "Data")
        self.assertEqual(dialog.table.model().rowCount(), 1)
        self.assertEqual(parse_mock.call_count, 1)
        self.assertNotEqual(parser_thread_ids[0], threading.get_ident())
        dialog.deleteLater()

    def test_excel_replacement_warning_tracks_selected_worksheet(self) -> None:
        path = self.root / "multi-sheet.xlsx"
        self.write_two_sheet_xlsx(path)
        controller = self.new_controller()
        original = parse_file(path, options={"sheet_name": "Data"})
        self.assertTrue(controller._commit_import(path, original))
        data_id = controller.activeTableId
        data_source = next(
            source for source in controller._project["data_sources"]
            if source["id"] == data_id
        )
        data_source["transform_steps"] = [{"op": "trim_text", "column": "name"}]
        replacement_states: list[tuple[str, bool]] = []

        def wait_for_sheet(dialog: FileImportPreviewDialog, sheet_name: str) -> None:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                self.app.processEvents()
                candidate = dialog._preview_candidate
                if candidate is not None and candidate.options.get("sheet_name") == sheet_name:
                    return
                time.sleep(0.005)
            self.fail(f"Preview did not finish for worksheet {sheet_name!r}")

        def accept_selected_sheet(dialog: FileImportPreviewDialog) -> int:
            wait_for_sheet(dialog, "Data")
            self.assertEqual(
                dialog._preview_candidate.options,
                {"sheet_name": "Data", "header_row": None},
            )
            self.assertTrue(dialog.header_auto_checkbox.isChecked())
            self.assertIn("reapplies its saved transformation steps", dialog.replacement_label.text())
            replacement_states.append(("Data", not dialog.replacement_label.isHidden()))
            dialog.sheet_combo.setCurrentText("Archive")
            wait_for_sheet(dialog, "Archive")
            replacement_states.append(("Archive", not dialog.replacement_label.isHidden()))
            dialog.sheet_combo.setCurrentText("Data")
            wait_for_sheet(dialog, "Data")
            replacement_states.append(("Data", not dialog.replacement_label.isHidden()))
            dialog.sheet_combo.setCurrentText("Archive")
            wait_for_sheet(dialog, "Archive")
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(FileImportPreviewDialog, "exec", new=accept_selected_sheet):
            self.assertTrue(controller.import_excel_path(path))

        self.assertEqual(
            replacement_states,
            [("Data", True), ("Archive", False), ("Data", True)],
        )
        self.assertEqual(
            {table["name"] for table in controller._project["model"]["tables"]},
            {"Data", "Archive"},
        )
        self.assertTrue(controller._commit_import(
            path, parse_file(path, options={"sheet_name": "Data"})
        ))
        self.assertEqual(controller.activeTableId, data_id)
        self.assertEqual(
            controller._loaded_candidates[data_id].rows,
            [{"name": "Ada", "amount": 12}],
        )

    def test_canceling_sqlite_options_discovery_ignores_late_results(self) -> None:
        path = self.root / "async-options.sqlite"
        with closing(sqlite3.connect(path)) as database, database:
            database.execute("CREATE TABLE metrics (id INTEGER)")

        discovery_started = threading.Event()
        release_discovery = threading.Event()
        discovery_finished = threading.Event()
        worker_thread_ids: list[int] = []

        def blocked_discovery(*_args: object, **_kwargs: object) -> list[str]:
            worker_thread_ids.append(threading.get_ident())
            discovery_started.set()
            release_discovery.wait(2)
            discovery_finished.set()
            return ["metrics"]

        with (
            patch(
                "analytics_studio.import_preview_dialog.list_sqlite_tables",
                side_effect=blocked_discovery,
            ),
            patch("analytics_studio.import_preview_dialog.parse_file", wraps=parse_file) as parse_mock,
        ):
            dialog = FileImportPreviewDialog(path, replacing=False)
            self.assertTrue(discovery_started.wait(2))
            self.assertNotEqual(worker_thread_ids[0], threading.get_ident())
            self.assertFalse(dialog.import_button.isEnabled())
            self.assertFalse(dialog.progress_widget.isHidden())
            timer_fired: list[bool] = []
            QTimer.singleShot(0, lambda: timer_fired.append(True))
            self.app.processEvents()
            self.assertEqual(timer_fired, [True])
            request_id = dialog._active_options_id
            self.assertIsNotNone(request_id)
            cancel_event = dialog._options_events[request_id]

            dialog.reject()
            self.assertTrue(cancel_event.is_set())
            release_discovery.set()
            self.assertTrue(discovery_finished.wait(2))
            deadline = time.monotonic() + 2
            while dialog._options_tasks and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
            self.app.processEvents()

        self.assertEqual(parse_mock.call_count, 0)
        self.assertIsNone(dialog._preview_candidate)

    def test_sqlite_preview_parsing_runs_in_worker_after_options(self) -> None:
        path = self.root / "async-parse.sqlite"
        with closing(sqlite3.connect(path)) as database:
            with database:
                database.execute("CREATE TABLE metrics (id INTEGER, name TEXT)")
                database.execute("INSERT INTO metrics VALUES (1, 'Ada')")
        parser_thread_ids: list[int] = []

        def record_parse(*args: Any, **kwargs: Any) -> object:
            parser_thread_ids.append(threading.get_ident())
            return parse_file(*args, **kwargs)

        with patch(
            "analytics_studio.import_preview_dialog.parse_file",
            side_effect=record_parse,
        ):
            dialog = FileImportPreviewDialog(path, replacing=False)
            self.wait_for_preview(dialog)

        self.assertEqual(len(parser_thread_ids), 1)
        self.assertNotEqual(parser_thread_ids[0], threading.get_ident())
        self.assertEqual(dialog.table.model().rowCount(), 1)
        self.assertEqual(dialog.table.model().data(dialog.table.model().index(0, 1)), "Ada")
        dialog.deleteLater()

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

        for source_path in (csv_path, excel_path, json_path, xml_path):
            with self.subTest(kind=source_path.suffix):
                expected = {
                    "name": "Ada",
                    "amount": 12 if source_path.suffix in {".xlsx", ".json"} else "12",
                }
                controller = self.new_controller()
                dialog = FileImportPreviewDialog(source_path, replacing=False)
                if source_path.suffix in {".xlsx", ".xlsm", ".xls"}:
                    self.wait_for_preview(dialog)
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
                reopened = self.new_controller()
                self.assertTrue(reopened.open_project_path(project_path))
                self.assertEqual(reopened._rows, [expected])
                self.assertEqual(reopened._active_source_kind, candidate.kind)
                self.assertEqual(reopened._active_parser_options, candidate.options)

    def test_catalog_file_entries_route_to_the_matching_importer(self) -> None:
        controller = self.new_controller()
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

    def test_unavailable_service_connectors_do_not_open_importers(self) -> None:
        controller = self.new_controller()
        original_project = copy.deepcopy(controller._project)
        unavailable_sources = (
            "microsoft_onelake_catalog",
            "microsoft_dataverse",
            "power_bi_power_bi_semantic_models",
        )

        with patch.object(controller, "import_data_dialog") as import_dialog:
            for source_id in unavailable_sources:
                with self.subTest(source_id=source_id):
                    self.assertFalse(controller.connectDataSource(source_id))

        import_dialog.assert_not_called()
        self.assertEqual(controller._project, original_project)

        with patch.object(
            controller, "_import_sql_server_dialog", return_value=False
        ) as sql_server_import:
            self.assertFalse(controller.connectDataSource("microsoft_sql_server"))
        sql_server_import.assert_called_once_with()
        self.assertEqual(controller._project, original_project)

    def test_canceling_file_replacement_preserves_the_loaded_source(self) -> None:
        current_path = self.root / "current.csv"
        current_path.write_text("id\n1\n", encoding="utf-8")
        replacement_path = self.root / "replacement.csv"
        replacement_path.write_text("id\n2\n", encoding="utf-8")
        controller = self.new_controller()
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
        controller = self.new_controller()
        candidate = parse_file(source_path, {"delimiter": ";"})

        self.assertTrue(controller._commit_import(source_path, candidate))
        self.assertTrue(controller._save_to(project_path))

        reopened = self.new_controller()
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
        self.assertIn("Could not refresh sales.csv", reopened.sourceWarning)

    def test_deep_json_parse_error_is_handled_on_refresh_and_project_open(self) -> None:
        source_path = self.root / "records.json"
        source_path.write_text('[{"id":1}]', encoding="utf-8")
        project_path = self.root / "records.npa"
        controller = self.new_controller()
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

        reopened = self.new_controller()
        with patch.object(QMessageBox, "warning"):
            self.assertTrue(reopened.open_project_path(project_path))

        self.assertFalse(reopened.sourceLoaded)
        self.assertIn("nesting exceeds", reopened.sourceWarning)


if __name__ == "__main__":
    unittest.main()
