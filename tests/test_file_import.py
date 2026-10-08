"""Contract tests for the bounded From Files v1 importers."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from html import escape
import tempfile
import threading
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from analytics_studio.file_import import (
    ImportCancelledError,
    inspect_excel_options,
    kind_for_path,
    list_sqlite_tables,
    parse_file,
    recommend_excel_sheet,
)


class FileImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_text(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def make_xlsx(self, path: Path) -> None:
        """Create a tiny two-sheet workbook without third-party packages."""
        workbook = '''<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="Intro" sheetId="1" r:id="rId1"/>
 <sheet name="Data" sheetId="2" r:id="rId2"/></sheets>
</workbook>'''
        relationships = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
 <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>'''
        shared_strings = '''<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="5" uniqueCount="5">
 <si><t>Intro</t></si><si><t>metadata</t></si><si><t>ID</t></si>
 <si><t>Value</t></si><si><t>alpha</t></si>
</sst>'''
        first_sheet = '''<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1"><c r="A1" t="s"><v>0</v></c></row>
</sheetData></worksheet>'''
        second_sheet = '''<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1"><c r="A1" t="s"><v>1</v></c></row>
 <row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row>
 <row r="3"><c r="A3"><v>7</v></c><c r="B3" t="s"><v>4</v></c></row>
</sheetData></worksheet>'''
        content_types = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="xml" ContentType="application/xml"/>
</Types>'''
        package_relationships = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", package_relationships)
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", relationships)
            archive.writestr("xl/sharedStrings.xml", shared_strings)
            archive.writestr("xl/worksheets/sheet1.xml", first_sheet)
            archive.writestr("xl/worksheets/sheet2.xml", second_sheet)

    def make_xlsx_with_rows(self, path: Path, sheets: list[tuple[str, list[list[object]]]]) -> None:
        """Write a small inline-string workbook for realistic sheet/header cases."""
        main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        package_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        worksheet_rel = f"{rel_ns}/worksheet"

        def column_name(index: int) -> str:
            result = ""
            while index:
                index, remainder = divmod(index - 1, 26)
                result = chr(ord("A") + remainder) + result
            return result

        workbook_sheets = "".join(
            f'<sheet name="{escape(name, quote=True)}" sheetId="{index}" r:id="rId{index}"/>'
            for index, (name, _) in enumerate(sheets, 1)
        )
        workbook_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{main_ns}" '
            f'xmlns:r="{rel_ns}"><sheets>{workbook_sheets}</sheets></workbook>'
        )
        relationships = "".join(
            f'<Relationship Id="rId{index}" Type="{worksheet_rel}" '
            f'Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, len(sheets) + 1)
        )
        rels_xml = f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{package_ns}">{relationships}</Relationships>'
        content_types = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="xml" ContentType="application/xml"/>
</Types>'''
        package_relationships = f'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{package_ns}">
 <Relationship Id="rId1" Type="{rel_ns}/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
        sheet_parts = []
        for sheet_index, (_, rows) in enumerate(sheets, 1):
            row_xml = []
            for row_number, values in enumerate(rows, 1):
                cells = []
                for column_index, value in enumerate(values, 1):
                    if value is None or value == "":
                        continue
                    reference = f"{column_name(column_index)}{row_number}"
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        cells.append(f'<c r="{reference}"><v>{value}</v></c>')
                    else:
                        cells.append(
                            f'<c r="{reference}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                        )
                row_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')
            sheet_parts.append((f"xl/worksheets/sheet{sheet_index}.xml", (
                f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{main_ns}">'
                f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>'
            )))

        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", package_relationships)
            archive.writestr("xl/workbook.xml", workbook_xml)
            archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
            for part_name, content in sheet_parts:
                archive.writestr(part_name, content)

    def test_kind_routing_is_case_insensitive_for_supported_formats(self) -> None:
        self.assertEqual(kind_for_path("report.CSV"), "csv")
        self.assertEqual(kind_for_path("report.XLSX"), "excel")
        self.assertEqual(kind_for_path("report.xlsm"), "excel")
        self.assertEqual(kind_for_path("report.xls"), "excel")
        self.assertEqual(kind_for_path("report.json"), "json")
        self.assertEqual(kind_for_path("report.xml"), "xml")
        self.assertEqual(kind_for_path("report.parquet"), "parquet")
        for name in ("report.txt",):
            with self.subTest(name=name), self.assertRaises(ValueError):
                kind_for_path(name)

    def test_csv_defaults_cover_bom_quoting_and_embedded_newline(self) -> None:
        path = self.root / "quoted.csv"
        path.write_text(
            '\ufeffName,Note,Amount\r\n"Acme, Inc.","first line\nsecond ""line""",5\r\n',
            encoding="utf-8",
        )

        candidate = parse_file(path)

        self.assertEqual(candidate.kind, "csv")
        self.assertEqual(candidate.headers, ["Name", "Note", "Amount"])
        self.assertEqual(candidate.rows, [{
            "Name": "Acme, Inc.",
            "Note": 'first line\nsecond "line"',
            "Amount": "5",
        }])
        self.assertEqual(candidate.row_count, 1)
        self.assertEqual(candidate.options, {
            "delimiter": ",", "encoding": "utf-8-sig", "has_header": True,
        })

    def test_csv_options_select_delimiter_encoding_and_headerless_mode(self) -> None:
        path = self.root / "semicolon.csv"
        path.write_bytes("café;5\nété;6\n".encode("utf-16"))

        candidate = parse_file(path, options={
            "delimiter": ";", "encoding": "utf-16", "has_header": False,
        })

        self.assertEqual(candidate.options, {
            "delimiter": ";", "encoding": "utf-16", "has_header": False,
        })
        self.assertEqual(candidate.row_count, 2)
        self.assertEqual(len(candidate.headers), 2)
        self.assertEqual(list(candidate.rows[0].values()), ["café", "5"])
        self.assertEqual(list(candidate.rows[1].values()), ["été", "6"])

    def test_csv_blank_duplicate_headers_are_normalized_deterministically(self) -> None:
        path = self.write_text("headers.csv", ",Name,Name\nx,first,second\n")

        first = parse_file(path)
        second = parse_file(path)

        self.assertEqual(first.headers, second.headers)
        self.assertTrue(all(header.strip() for header in first.headers))
        self.assertEqual(len(set(first.headers)), 3)
        self.assertEqual(list(first.rows[0].values()), ["x", "first", "second"])

    def test_csv_ragged_rows_preserve_surplus_cells_and_pad_short_rows(self) -> None:
        path = self.write_text("ragged.csv", "A,B\n1\n2,3,4\n")

        candidate = parse_file(path)

        self.assertEqual(len(candidate.headers), 3)
        self.assertEqual(candidate.row_count, 2)
        self.assertEqual(list(candidate.rows[0].values()), ["1", "", ""])
        self.assertEqual(list(candidate.rows[1].values()), ["2", "3", "4"])

    def test_csv_invalid_options_and_empty_input_are_rejected(self) -> None:
        path = self.write_text("simple.csv", "A,B\n1,2\n")
        empty = self.write_text("empty.csv", "")
        with self.assertRaises(ValueError):
            parse_file(path, options={"delimiter": "::"})
        with self.assertRaises(ValueError):
            parse_file(empty)

    def test_csv_reports_progress_and_cancels_cooperatively(self) -> None:
        path = self.root / "large.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write("id,value\n")
            for row_index in range(6_000):
                stream.write(f"{row_index},{'x' * 40}\n")
        cancel_event = threading.Event()
        progress_messages: list[str] = []

        def cancel_after_progress(message: str) -> None:
            progress_messages.append(message)
            if message.startswith("Read "):
                cancel_event.set()

        with self.assertRaises(ImportCancelledError):
            parse_file(
                path,
                cancel_event=cancel_event,
                progress_callback=cancel_after_progress,
            )
        self.assertTrue(any("CSV rows" in message for message in progress_messages))

    def test_excel_option_discovery_cancels_between_recommended_sheets(self) -> None:
        path = self.root / "cancel-recommendation.xlsx"
        self.make_xlsx(path)
        cancel_event = threading.Event()
        progress_messages: list[str] = []

        def cancel_after_sheet_starts(message: str) -> None:
            progress_messages.append(message)
            if message.startswith("Checking worksheet 1 of"):
                cancel_event.set()

        with self.assertRaises(ImportCancelledError):
            inspect_excel_options(
                path,
                cancel_event=cancel_event,
                progress_callback=cancel_after_sheet_starts,
            )

        self.assertTrue(any(message.startswith("Checking worksheet 1 of") for message in progress_messages))
        self.assertFalse(any(message.startswith("Checking worksheet 2 of") for message in progress_messages))

    def test_sqlite_table_discovery_honors_prior_cancellation(self) -> None:
        import sqlite3

        path = self.root / "cancel-discovery.sqlite"
        with closing(sqlite3.connect(path)) as database:
            with database:
                database.execute("CREATE TABLE metrics (id INTEGER)")
        cancel_event = threading.Event()
        cancel_event.set()

        with self.assertRaises(ImportCancelledError):
            list_sqlite_tables(path, cancel_event=cancel_event)

    def test_excel_can_select_sheet_and_one_based_header_row(self) -> None:
        path = self.root / "two-sheets.xlsx"
        self.make_xlsx(path)

        candidate = parse_file(path, options={"sheet_name": "Data", "header_row": 2})

        self.assertEqual(candidate.kind, "excel")
        self.assertEqual(candidate.headers, ["ID", "Value"])
        self.assertEqual(candidate.rows, [{"ID": "7", "Value": "alpha"}])
        self.assertEqual(candidate.row_count, 1)
        self.assertEqual(candidate.options, {"sheet_name": "Data", "header_row": 2})

    def test_excel_auto_detects_header_after_title_block_and_persists_resolved_row(self) -> None:
        path = self.root / "title-block.xlsx"
        title_rows = [[f"Report title {row}"] for row in range(1, 12)]
        rows = title_rows + [
            ["Date", "Emirates", "Quantity", "Sales", "VAT-5%"],
            ["2026-08-01", "Dubai", 3, 100, 5],
            ["2026-08-02", "Abu Dhabi", 2, 80, 4],
        ]
        self.make_xlsx_with_rows(path, [("VAT 5%", rows)])

        candidate = parse_file(path)

        self.assertEqual(candidate.headers, ["Date", "Emirates", "Quantity", "Sales", "VAT-5%"])
        self.assertEqual(candidate.row_count, 2)
        self.assertEqual(candidate.rows[0]["Emirates"], "Dubai")
        self.assertEqual(candidate.options, {"sheet_name": "VAT 5%", "header_row": 12})

    def test_excel_recommends_best_tabular_sheet_and_keeps_manual_choice(self) -> None:
        path = self.root / "multiple-sheets.xlsx"
        self.make_xlsx_with_rows(path, [
            ("Intro", [["Company VAT report"]]),
            ("Input Vat", [
                ["Date", "Address", "Quantity", "Input Vat"],
                ["2026-08-01", "Dubai", 1, 5], ["2026-08-02", "Abu Dhabi", 2, 10],
            ]),
            ("Sales Reg", [
                ["Date", "Emirates", "Sales", "VAT-5%"],
                ["2026-08-01", "Dubai", 100, 5], ["2026-08-02", "Abu Dhabi", 200, 10],
            ]),
            ("VAT 5%", [
                ["Date", "Emirates", "Quantity", "Sales", "VAT-5%"],
                ["2026-08-01", "Dubai", 1, 100, 5], ["2026-08-02", "Abu Dhabi", 2, 200, 10],
            ]),
        ])

        self.assertEqual(recommend_excel_sheet(path), "VAT 5%")
        automatic = parse_file(path)
        manual = parse_file(path, options={"sheet_name": "Sales Reg", "header_row": 1})

        self.assertEqual(automatic.options, {"sheet_name": "VAT 5%", "header_row": 1})
        self.assertEqual(manual.headers, ["Date", "Emirates", "Sales", "VAT-5%"])
        self.assertEqual(manual.options, {"sheet_name": "Sales Reg", "header_row": 1})

    def test_excel_rejects_unknown_sheet(self) -> None:
        path = self.root / "two-sheets.xlsx"
        self.make_xlsx(path)
        with self.assertRaises(ValueError):
            parse_file(path, options={"sheet_name": "Missing"})

    def test_excel_rejects_invalid_shared_string_references(self) -> None:
        path = self.root / "bad-shared-string.xlsx"
        self.make_xlsx(path)
        with ZipFile(path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        parts["xl/worksheets/sheet2.xml"] = parts["xl/worksheets/sheet2.xml"].replace(
            b'<c r="B3" t="s"><v>4</v></c>',
            b'<c r="B3" t="s"><v>99</v></c>',
        )
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            for name, content in parts.items():
                archive.writestr(name, content)

        with self.assertRaisesRegex(ValueError, "shared-string"):
            parse_file(path, options={"sheet_name": "Data", "header_row": 2})

    def test_excel_rejects_expanded_workbook_and_xml_part_limits(self) -> None:
        path = self.root / "bounded.xlsx"
        self.make_xlsx(path)

        with patch("analytics_studio.file_import.MAX_WORKBOOK_EXPANDED_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "expands beyond"):
                parse_file(path)

        with patch("analytics_studio.file_import.MAX_WORKBOOK_EXPANDED_BYTES", 10_000_000):
            with patch("analytics_studio.file_import.MAX_WORKBOOK_XML_PART_BYTES", 32):
                with self.assertRaisesRegex(ValueError, "XML-part limit"):
                    parse_file(path)

    def test_excel_rejects_dtd_and_entity_declarations_in_workbook_parts(self) -> None:
        path = self.root / "unsafe-workbook.xlsx"
        self.make_xlsx(path)
        with ZipFile(path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        parts["xl/workbook.xml"] = (
            b'<!DOCTYPE workbook [<!ENTITY injected "unsafe">]>'
            + parts["xl/workbook.xml"]
        )
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            for name, content in parts.items():
                archive.writestr(name, content)

        with self.assertRaisesRegex(ValueError, "DTD or entity"):
            parse_file(path)

    def test_excel_boolean_date_and_formula_values_include_clear_notices(self) -> None:
        path = self.root / "typed.xlsx"
        self.make_xlsx(path)
        with ZipFile(path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        parts["xl/sharedStrings.xml"] = b"""<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
 <si><t>Name</t></si><si><t>Amount</t></si><si><t>Active</t></si>
 <si><t>Date</t></si><si><t>Formula</t></si><si><t>Missing</t></si><si><t>Ada</t></si>
</sst>"""
        parts["xl/styles.xml"] = b"""<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
 <cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs>
</styleSheet>"""
        parts["xl/worksheets/sheet2.xml"] = b"""<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c><c r="E1" t="s"><v>4</v></c><c r="F1" t="s"><v>5</v></c></row>
 <row r="2"><c r="A2" t="s"><v>6</v></c><c r="B2"><v>12.5</v></c><c r="C2" t="b"><v>1</v></c><c r="D2" s="1"><v>45292</v></c><c r="E2"><f>B2+1</f><v>13.5</v></c><c r="F2"><f>B2+2</f></c></row>
</sheetData></worksheet>"""
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            for name, content in parts.items():
                archive.writestr(name, content)

        candidate = parse_file(path, options={"sheet_name": "Data", "header_row": 1})

        self.assertEqual(candidate.rows, [{
            "Name": "Ada", "Amount": "12.5", "Active": "TRUE",
            "Date": "2024-01-01", "Formula": "13.5", "Missing": "",
        }])
        self.assertIn("saved cached values are imported", candidate.notices[0])
        self.assertIn("no saved value and will import as blank", candidate.notices[1])

    def test_expected_kind_and_extension_or_contents_must_match(self) -> None:
        path = self.write_text("data.csv", '{"a":1}\n')
        with self.assertRaises(ValueError):
            parse_file(path, expected_kind="json")

        mislabeled = self.write_text("data.json", "a,b\n1,2\n")
        with self.assertRaises(ValueError):
            parse_file(mislabeled)

    def test_json_accepts_flat_records_with_deterministic_union_of_keys(self) -> None:
        path = self.write_text(
            "records.json",
            '[{"id":1,"name":"Ada"},{"name":null,"active":true}]',
        )

        candidate = parse_file(path)
        repeated = parse_file(path)

        self.assertEqual(candidate.kind, "json")
        self.assertEqual(candidate.headers, ["id", "name", "active"])
        self.assertEqual(candidate.headers, repeated.headers)
        self.assertEqual(candidate.rows, [
            {"id": "1", "name": "Ada", "active": ""},
            {"id": "", "name": "", "active": "TRUE"},
        ])

    def test_json_rejects_nested_values_duplicate_keys_and_non_array_root(self) -> None:
        for name, payload in (
            ("nested.json", '[{"id":1,"meta":{"x":2}}]'),
            ("duplicate.json", '[{"id":1,"id":2}]'),
            ("object.json", '{"id":1}'),
            ("mixed.json", '[{"id":1}, 2]'),
        ):
            with self.subTest(name=name):
                path = self.write_text(name, payload)
                with self.assertRaises(ValueError):
                    parse_file(path)

    def test_json_rejects_non_standard_and_out_of_range_numbers(self) -> None:
        for name, payload in (
            ("constant.json", '[{"value":NaN}]'),
            ("overflow.json", '[{"value":1e999}]'),
            ("large-integer.json", '[{"value":' + "9" * 400 + "}]"),
        ):
            with self.subTest(name=name):
                path = self.write_text(name, payload)
                with self.assertRaises(ValueError):
                    parse_file(path)

    def test_json_rejects_nesting_beyond_python_parser_depth_as_import_error(self) -> None:
        path = self.write_text(
            "deeply-nested.json",
            "[" + "[" * 100_000 + "0" + "]" * 100_000 + "]",
        )

        with self.assertRaisesRegex(ValueError, "nesting exceeds"):
            parse_file(path)

    def test_json_row_limit_is_enforced_while_records_are_decoded(self) -> None:
        path = self.write_text("too-many-rows.json", "[" + ",".join(['{"x":1}'] * 100_001) + "]")

        with self.assertRaisesRegex(ValueError, "row import limit"):
            parse_file(path)

    def test_xml_accepts_one_repeated_record_group_of_scalar_fields(self) -> None:
        path = self.write_text(
            "records.xml",
            "<root><record><id>1</id><name>Ada</name></record>"
            "<record><id>2</id><name>Lin</name></record></root>",
        )

        candidate = parse_file(path)

        self.assertEqual(candidate.kind, "xml")
        self.assertEqual(candidate.headers, ["id", "name"])
        self.assertEqual(candidate.rows, [
            {"id": "1", "name": "Ada"}, {"id": "2", "name": "Lin"},
        ])

    def test_xml_rejects_attributes_nested_mixed_irregular_and_ambiguous_groups(self) -> None:
        invalid_xml = {
            "attributes.xml": "<root><record id='1'><name>Ada</name></record></root>",
            "nested.xml": "<root><record><id><value>1</value></id></record></root>",
            "mixed.xml": "<root><record><id>1</id>text</record></root>",
            "irregular.xml": (
                "<root><record><id>1</id><name>A</name></record>"
                "<record><id>2</id><other>B</other></record></root>"
            ),
            "ambiguous.xml": (
                "<root><record><id>1</id></record><record><id>2</id></record>"
                "<item><id>3</id></item><item><id>4</id></item></root>"
            ),
        }
        for name, payload in invalid_xml.items():
            with self.subTest(name=name):
                path = self.write_text(name, payload)
                with self.assertRaises(ValueError):
                    parse_file(path)

    def test_xml_rejects_dtd_and_entity_declarations(self) -> None:
        for name, payload in (
            ("doctype.xml", '<!DOCTYPE root [<!ENTITY name "Ada">]><root><record><name>&name;</name></record></root>'),
            ("external-entity.xml", '<!DOCTYPE root [<!ENTITY ext SYSTEM "file:///etc/passwd">]><root><record><name>&ext;</name></record></root>'),
        ):
            with self.subTest(name=name):
                path = self.write_text(name, payload)
                with self.assertRaisesRegex(ValueError, "DTD or entity"):
                    parse_file(path)

    def test_xml_row_limit_is_enforced_while_records_are_parsed(self) -> None:
        record = "<r><x>1</x></r>"
        path = self.write_text("too-many-rows.xml", "<root>" + record * 100_001 + "</root>")

        with self.assertRaisesRegex(ValueError, "row import limit"):
            parse_file(path)

    def test_source_row_column_and_cell_caps_reject_without_truncating(self) -> None:
        oversized = self.root / "oversized.csv"
        oversized.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
        too_many_rows = self.root / "too-many-rows.csv"
        too_many_rows.write_text("A\n" + "1\n" * 100_001, encoding="utf-8")
        too_many_columns = self.root / "too-many-columns.csv"
        too_many_columns.write_text(",".join(f"c{i}" for i in range(513)) + "\n", encoding="utf-8")
        too_many_cells = self.root / "too-many-cells.csv"
        row = ",".join("x" for _ in range(500))
        too_many_cells.write_text(",".join(f"c{i}" for i in range(500)) + "\n" + (row + "\n") * 1001,
                                  encoding="utf-8")

        for path in (oversized, too_many_rows, too_many_columns, too_many_cells):
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                parse_file(path)


if __name__ == "__main__":
    unittest.main()
