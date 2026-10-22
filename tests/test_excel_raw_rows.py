from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QToolButton

from analytics_studio.controller import StudioController
from analytics_studio.file_import import FileImportError, normalize_options, parse_file
from analytics_studio.import_preview_dialog import FileImportPreviewDialog
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.power_query_m import m_script_matches_steps, steps_to_m_script
from analytics_studio.transformations import apply_transformations


HEADERS = [
    "Date", "Particulars", "Address", "Emirates", "Voucher Type",
    "Voucher No.", "Voucher Ref.", "TRN", "Quantity", "Value",
    "Gross Total", "Sales", "VAT-5%", "Discount",
]


class ExcelRawRowsParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.path = self.root / "vat-worksheet.xlsx"
        self._write_workbook()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def wait_for_preview(self, dialog: FileImportPreviewDialog) -> None:
        deadline = time.monotonic() + 10
        while not dialog.import_button.isEnabled() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(dialog.import_button.isEnabled())

    def wait_for_acceptance(self, dialog: FileImportPreviewDialog) -> None:
        deadline = time.monotonic() + 10
        while (
            dialog.result() != QDialog.DialogCode.Accepted
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)

    def test_raw_rows_option_rejects_conflicting_or_non_boolean_header_settings(self) -> None:
        with self.assertRaisesRegex(FileImportError, "cannot be combined"):
            normalize_options(
                "excel", {"header_row": 1, "raw_rows": True}
            )
        with self.assertRaisesRegex(FileImportError, "must be true or false"):
            normalize_options("excel", {"raw_rows": 1})

    def test_automatic_load_ignores_inflated_declared_dimensions(self) -> None:
        inflated_path = self.root / "inflated-dimension.xlsx"
        with ZipFile(self.path) as source, ZipFile(
            inflated_path, "w", ZIP_DEFLATED
        ) as target:
            for name in source.namelist():
                contents = source.read(name)
                if name == "xl/worksheets/sheet1.xml":
                    contents = contents.replace(
                        b'<dimension ref="A1:N623"/>',
                        b'<dimension ref="A1:SZ100001"/>',
                    )
                target.writestr(name, contents)

        automatic = parse_file(
            inflated_path, options={"sheet_name": "VAT 5%", "header_row": None}
        )
        self.assertEqual(automatic.row_count, 573)
        self.assertEqual(automatic.headers, HEADERS)
        manual = parse_file(
            inflated_path, options={"sheet_name": "VAT 5%", "header_row": 1}
        )
        self.assertEqual(manual.row_count, 584)
        self.assertEqual(len(manual.headers), len(HEADERS))
        with self.assertRaisesRegex(FileImportError, "100,000-row import limit"):
            parse_file(
                inflated_path,
                options={
                    "sheet_name": "VAT 5%",
                    "header_row": None,
                    "raw_rows": True,
                },
            )

    def _write_workbook(self) -> None:
        workbook = '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="VAT 5%" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''
        relationships = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''

        def inline_cell(column: str, row: int, value: str) -> str:
            return f'<c r="{column}{row}" t="inlineStr"><is><t>{value}</t></is></c>'

        def number_cell(column: str, row: int, value: str) -> str:
            return f'<c r="{column}{row}"><v>{value}</v></c>'

        column_letters = [
            "A", "B", "C", "D", "E", "F", "G",
            "H", "I", "J", "K", "L", "M", "N",
        ]
        row_parts: list[str] = []
        row_parts.append(f'<row r="1">{inline_cell("A", 1, "VAT report title")}</row>')
        for row_number in range(2, 12):
            row_parts.append(
                f'<row r="{row_number}">{inline_cell("A", row_number, f"Preamble {row_number}")}</row>'
            )
        header_cells = "".join(
            inline_cell(column, 12, header)
            for column, header in zip(column_letters, HEADERS)
        )
        row_parts.append(f'<row r="12">{header_cells}</row>')

        detail_values: list[tuple[int, int, int, int, int]] = []
        amount_cents = [
            131_000 + ((index * 37) % 201 - 100)
            for index in range(572)
        ]
        amount_cents[-1] += 74_915_363 - sum(amount_cents)
        for index, row_number in enumerate(range(13, 585)):
            value_cents = amount_cents[index]
            vat_cents = (value_cents + 10) // 20
            gross_cents = value_cents + vat_cents
            sales_cents = value_cents
            discount_cents = index % 11
            detail_values.append(
                (value_cents, vat_cents, gross_cents, sales_cents, discount_cents)
            )
            cells = (
                inline_cell("A", row_number, f"2026-08-{index % 28 + 1:02d}")
                + inline_cell("B", row_number, f"Sale {index + 1:04d}")
                + inline_cell("C", row_number, f"Address {index % 19 + 1}")
                + inline_cell("D", row_number, "Dubai")
                + inline_cell("E", row_number, "Sales")
                + inline_cell("F", row_number, f"INV-{index + 1:05d}")
                + inline_cell("G", row_number, f"REF-{index + 1:05d}")
                + number_cell("H", row_number, str(1000000000 + index))
                + number_cell("I", row_number, str(index % 3 + 1))
                + number_cell("J", row_number, f"{value_cents / 100:.2f}")
                + number_cell("K", row_number, f"{gross_cents / 100:.2f}")
                + number_cell("L", row_number, f"{sales_cents / 100:.2f}")
                + number_cell("M", row_number, f"{vat_cents / 100:.2f}")
                + number_cell("N", row_number, f"{discount_cents / 100:.2f}")
            )
            row_parts.append(f'<row r="{row_number}">{cells}</row>')
        totals = [sum(values[index] for values in detail_values) for index in range(5)]
        footer = (
            inline_cell("B", 585, "Grand Total")
            + number_cell("J", 585, f"{totals[0] / 100:.2f}")
            + number_cell("K", 585, f"{totals[2] / 100:.2f}")
            + number_cell("L", 585, f"{totals[3] / 100:.2f}")
            + number_cell("M", 585, f"{totals[1] / 100:.2f}")
            + number_cell("N", 585, f"{totals[4] / 100:.2f}")
        )
        row_parts.append(f'<row r="585">{footer}</row>')
        sheet = (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<dimension ref="A1:N623"/><sheetData>'
            + "".join(row_parts)
            + "</sheetData></worksheet>"
        )
        with ZipFile(self.path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", relationships)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)

    def test_raw_worksheet_source_replays_power_bi_sparse_trim_and_promotion(self) -> None:
        raw = parse_file(
            self.path, options={"sheet_name": "VAT 5%", "header_row": None, "raw_rows": True}
        )

        self.assertEqual(raw.row_count, 623)
        self.assertEqual(raw.headers, [f"Column{index}" for index in range(1, 15)])
        self.assertEqual(raw.rows[0]["Column1"], "VAT report title")
        self.assertEqual(raw.rows[11]["Column1"], "Date")
        self.assertTrue(all(value is None for value in raw.rows[-1].values()))
        self.assertEqual(raw.options["raw_rows"], True)

        automatic = parse_file(
            self.path, options={"sheet_name": "VAT 5%", "header_row": None}
        )
        first_row_headers = parse_file(
            self.path, options={"sheet_name": "VAT 5%", "header_row": 1}
        )
        self.assertEqual(automatic.row_count, 573)
        self.assertEqual(automatic.headers, HEADERS)
        self.assertEqual(first_row_headers.row_count, 584)
        self.assertEqual(first_row_headers.headers[0], "VAT report title")

        steps = [
            {"op": "m_sparse_boundary_helper", "name": "FilterNullAndWhitespace"},
            {"op": "remove_sparse_bottom_rows"},
            {"op": "remove_sparse_top_rows"},
            {"op": "promote_headers", "promote_all_scalars": True},
            {"op": "convert_type", "column": "Date", "type": "date"},
            *[
                {"op": "convert_type", "column": column, "type": "text"}
                for column in HEADERS[1:7]
            ],
            {"op": "convert_type", "column": "TRN", "type": "whole_number"},
            {"op": "convert_type", "column": "Quantity", "type": "whole_number"},
            *[
                {"op": "convert_type", "column": column, "type": "decimal_number"}
                for column in HEADERS[9:]
            ],
        ]
        bottom_trimmed = apply_transformations(raw, steps[:2])
        self.assertEqual(bottom_trimmed.row_count, 585)
        top_trimmed = apply_transformations(raw, steps[:3])
        self.assertEqual(top_trimmed.row_count, 574)
        promoted = apply_transformations(raw, steps[:4])
        self.assertEqual(promoted.row_count, 573)
        self.assertEqual(promoted.headers, HEADERS)
        self.assertEqual(promoted.rows[-1]["Particulars"], "Grand Total")

        typed = apply_transformations(raw, steps)
        self.assertEqual(typed.row_count, 573)
        self.assertTrue(all(isinstance(row["Value"], Decimal) for row in typed.rows))
        self.assertTrue(all(isinstance(row["TRN"], int) for row in typed.rows[:-1]))
        self.assertTrue(all(isinstance(row["Quantity"], int) for row in typed.rows[:-1]))
        self.assertTrue(all(
            isinstance(row[column], Decimal)
            for row in typed.rows
            for column in HEADERS[9:]
        ))
        self.assertEqual(typed.rows[0]["Particulars"], "Sale 0001")
        self.assertEqual(typed.rows[0]["Address"], "Address 1")
        self.assertEqual(typed.rows[0]["Emirates"], "Dubai")
        self.assertEqual(typed.rows[0]["Voucher Type"], "Sales")
        self.assertEqual(typed.rows[0]["Voucher No."], "INV-00001")
        self.assertEqual(typed.rows[0]["Voucher Ref."], "REF-00001")
        self.assertEqual(typed.rows[0]["TRN"], 1000000000)
        self.assertEqual(typed.rows[0]["Quantity"], 1)
        self.assertEqual(typed.rows[0]["Date"], date(2026, 8, 1))
        self.assertEqual(
            sum((row["Value"] for row in typed.rows), Decimal(0)),
            Decimal("1498307.26"),
        )
        details = [row for row in typed.rows if row["Particulars"] != "Grand Total"]
        self.assertEqual(len(details), 572)
        self.assertEqual(
            sum((row["Value"] for row in details), Decimal(0)),
            Decimal("749153.63"),
        )

    def test_xlsx_xstring_escapes_decode_once_for_shared_inline_and_cached_text(self) -> None:
        path = self.root / "escaped-text.xlsx"
        workbook = '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="Escaped" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''
        relationships = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''
        shared_strings = '''<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
 <si><t>before_x000D_after</t></si>
 <si><t>literal _x005F_x0041_</t></si>
 <si><t>malformed _x0G0D_</t></si>
 <si><r><t>joined _x000</t></r><r><t>D_after</t></r></si>
</sst>'''
        sheet = '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
 <dimension ref="A1:G1"/><sheetData><row r="1">
 <c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>
 <c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c>
 <c r="E1" t="inlineStr"><is><t>inline_x000D_after</t></is></c>
 <c r="F1" t="str"><v>cached_x000D_text</v></c>
 <c r="G1" t="s"><v>1</v></c>
 </row></sheetData></worksheet>'''
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", relationships)
            archive.writestr("xl/sharedStrings.xml", shared_strings)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)
        original_bytes = path.read_bytes()

        parsed = parse_file(
            path,
            options={"sheet_name": "Escaped", "header_row": None, "raw_rows": True},
        )

        self.assertEqual(
            list(parsed.rows[0].values()),
            [
                "before\rafter",
                "literal _x0041_",
                "malformed _x0G0D_",
                "joined \rafter",
                "inline\rafter",
                "cached\rtext",
                "literal _x0041_",
            ],
        )
        self.assertEqual(path.read_bytes(), original_bytes)

    def test_raw_excel_steps_survive_project_reopen_and_refresh(self) -> None:
        raw = parse_file(
            self.path, options={"sheet_name": "VAT 5%", "header_row": None, "raw_rows": True}
        )
        steps = [
            {"op": "remove_sparse_bottom_rows"},
            {"op": "remove_sparse_top_rows"},
            {"op": "promote_headers"},
            {"op": "convert_type", "column": "Date", "type": "date"},
            {"op": "convert_type", "column": "Value", "type": "decimal_number"},
        ]
        settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )
        controller = StudioController(self.app, settings)

        accepted_preview: dict[str, object] = {}

        def choose_transform(dialog: FileImportPreviewDialog) -> int:
            self.wait_for_preview(dialog)
            row_one = parse_file(
                self.path,
                options={"sheet_name": "VAT 5%", "header_row": 1},
            )
            self.assertEqual(dialog._preview_candidate.row_count, row_one.row_count)
            self.assertEqual(
                dialog._preview_candidate.options,
                {"sheet_name": "VAT 5%", "header_row": 1},
            )
            self.assertTrue(dialog.transform_raw_rows_checkbox.isEnabled())
            self.assertTrue(dialog.transform_raw_rows_checkbox.isChecked())
            dialog.transform_button.click()
            self.wait_for_acceptance(dialog)
            accepted_preview["candidate"] = dialog.candidate
            return dialog.result()

        def close_and_load(dialog: TransformDataDialog) -> int:
            self.assertEqual(len(dialog._query_states), 1)
            staged = next(iter(dialog._query_states.values()))
            self.assertTrue(staged["is_new_source"])
            self.assertEqual(staged["source_candidate"].row_count, 623)
            self.assertEqual(staged["source_candidate"].headers, raw.headers)
            self.assertEqual(staged["source_candidate"].rows, raw.rows)
            dialog.show()
            self.app.processEvents()

            def add_step(
                step: dict[str, str], *, expected_rows: int,
                expected_headers: list[str] | None = None,
            ) -> None:
                if dialog.step_list.currentRow() >= 0:
                    self.assertEqual(dialog.add_button.text(), "New step")
                    dialog.add_button.click()
                    self.assertEqual(dialog.step_list.currentRow(), -1)
                operation_index = dialog.operation_combo.findData(step["op"])
                self.assertGreaterEqual(operation_index, 0)
                dialog.operation_combo.setCurrentIndex(operation_index)
                if "column" in step:
                    column_index = dialog.column_combo.findText(step["column"])
                    self.assertGreaterEqual(column_index, 0)
                    dialog.column_combo.setCurrentIndex(column_index)
                if "type" in step:
                    type_index = dialog.option_combo.findData(step["type"])
                    self.assertGreaterEqual(type_index, 0)
                    dialog.option_combo.setCurrentIndex(type_index)
                self.assertEqual(dialog._create_step(), step)
                dialog.add_button.click()
                self.assertEqual(dialog._steps, steps[: len(dialog._steps)])
                self.assertEqual(dialog._steps[-1], step)
                self.assertEqual(dialog._preview_candidate.row_count, expected_rows)
                if expected_headers is not None:
                    self.assertEqual(dialog._preview_candidate.headers, expected_headers)

            self.assertEqual(dialog._preview_candidate.row_count, 623)
            add_step(steps[0], expected_rows=585)
            add_step(steps[1], expected_rows=574)
            add_step(steps[2], expected_rows=573, expected_headers=HEADERS)
            add_step(steps[3], expected_rows=573)
            self.assertEqual(
                dialog._preview_candidate.rows[0]["Date"], date(2026, 8, 1)
            )
            self.assertTrue(
                all(
                    type(row["Date"]) is date
                    for row in dialog._preview_candidate.rows[:-1]
                )
            )
            self.assertIsNone(dialog._preview_candidate.rows[-1]["Date"])
            add_step(steps[4], expected_rows=573)
            self.assertTrue(
                all(isinstance(row["Value"], Decimal)
                    for row in dialog._preview_candidate.rows)
            )
            self.assertEqual(
                sum((row["Value"] for row in dialog._preview_candidate.rows), Decimal(0)),
                Decimal("1498307.26"),
            )

            m_query_name = dialog.query_name_edit.text().strip()
            script = steps_to_m_script(dialog._steps, m_query_name)
            self.assertEqual(script.count("FilterNullAndWhitespace ="), 1)
            self.assertIn('{"Date", type date}', script)
            self.assertTrue(m_script_matches_steps(script, m_query_name, steps))
            self.assertEqual(dialog.step_list.count(), len(steps))
            button = dialog.findChild(QToolButton, "powerQueryCloseApplyButton")
            self.assertIsNotNone(button)
            self.app.processEvents()
            assert button is not None
            self.assertTrue(button.isEnabled())
            button.click()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            self.assertIsNotNone(dialog.accepted_queries)
            return dialog.result()

        with (
            patch.object(FileImportPreviewDialog, "exec", new=choose_transform),
            patch.object(TransformDataDialog, "exec", new=close_and_load),
        ):
            self.assertTrue(controller.import_excel_path(self.path))

        accepted_candidate = accepted_preview["candidate"]
        self.assertEqual(accepted_candidate.options, raw.options)
        self.assertEqual(accepted_candidate.row_count, 623)
        self.assertEqual(accepted_candidate.rows, raw.rows)
        source_id = controller._active_source_id
        self.assertIsNotNone(source_id)
        source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == source_id
        )
        source_candidate = controller._raw_candidates[source_id]
        raw_source_row_count = source_candidate.row_count
        self.assertEqual(source["parser_options"], raw.options)
        self.assertEqual(source["transform_steps"], steps)
        self.assertNotIn(
            "m_sparse_boundary_helper",
            [step["op"] for step in source["transform_steps"]],
        )
        transformed = controller._loaded_candidates[source_id]
        self.assertEqual(transformed.headers, HEADERS)
        self.assertEqual(transformed.row_count, 573)
        self.assertEqual(transformed.rows[0]["Date"], date(2026, 8, 1))
        self.assertTrue(
            all(type(row["Date"]) is date for row in transformed.rows[:-1])
        )
        self.assertIsNone(transformed.rows[-1]["Date"])
        self.assertEqual(
            sum((row["Value"] for row in transformed.rows), Decimal(0)),
            Decimal("1498307.26"),
        )
        project_path = self.root / "vat-raw-query.npa"
        self.assertTrue(controller._save_to(project_path))

        reopened = StudioController(self.app, settings)
        self.assertTrue(reopened.open_project_path(project_path))
        reopened_source = next(
            item for item in reopened._project["data_sources"]
            if item["id"] == source_id
        )
        self.assertEqual(reopened_source["parser_options"], raw.options)
        self.assertEqual(reopened_source["transform_steps"], steps)
        self.assertEqual(reopened._raw_candidates[source_id].row_count, raw_source_row_count)
        reopened_candidate = reopened._loaded_candidates[source_id]
        self.assertEqual(reopened_candidate.row_count, 573)
        self.assertEqual(reopened_candidate.headers, HEADERS)
        self.assertEqual(reopened_candidate.rows, transformed.rows)
        reopened_table = next(
            item for item in reopened._project["model"]["tables"]
            if item.get("source_id") == source_id
        )
        self.assertEqual(
            reopened_table["column_types"]["Value"], "decimal_number"
        )
        self.assertEqual(reopened_table["column_types"]["Date"], "date")
        reopened_script = steps_to_m_script(
            reopened_source["transform_steps"], reopened_source["query_name"]
        )
        self.assertEqual(reopened_script.count("FilterNullAndWhitespace ="), 1)
        self.assertTrue(m_script_matches_steps(
            reopened_script, reopened_source["query_name"], steps
        ))

        reopened.refresh_source()
        refreshed = reopened._loaded_candidates[source_id]
        self.assertEqual(refreshed.row_count, 573)
        self.assertEqual(refreshed.headers, HEADERS)
        self.assertEqual(refreshed.rows[0]["Date"], date(2026, 8, 1))
        self.assertTrue(
            all(type(row["Date"]) is date for row in refreshed.rows[:-1])
        )
        self.assertIsNone(refreshed.rows[-1]["Date"])
        self.assertEqual(refreshed.rows[-1]["Particulars"], "Grand Total")
        self.assertEqual(
            sum((row["Value"] for row in refreshed.rows), Decimal(0)),
            Decimal("1498307.26"),
        )
        self.assertEqual(refreshed.rows, transformed.rows)
        table = next(
            item for item in reopened._project["model"]["tables"]
            if item.get("source_id") == source_id
        )
        self.assertEqual(table["column_types"]["Value"], "decimal_number")
        self.assertEqual(table["column_types"]["Date"], "date")


if __name__ == "__main__":
    unittest.main()
