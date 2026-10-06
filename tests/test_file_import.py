"""Contract tests for the bounded From Files v1 importers."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from analytics_studio.file_import import kind_for_path, parse_file


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

    def test_kind_routing_is_case_insensitive_and_rejects_unknown_and_legacy_xls(self) -> None:
        self.assertEqual(kind_for_path("report.CSV"), "csv")
        self.assertEqual(kind_for_path("report.XLSX"), "excel")
        self.assertEqual(kind_for_path("report.xlsm"), "excel")
        self.assertEqual(kind_for_path("report.json"), "json")
        self.assertEqual(kind_for_path("report.xml"), "xml")
        for name in ("report.xls", "report.txt", "report.parquet"):
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

    def test_excel_can_select_sheet_and_one_based_header_row(self) -> None:
        path = self.root / "two-sheets.xlsx"
        self.make_xlsx(path)

        candidate = parse_file(path, options={"sheet_name": "Data", "header_row": 2})

        self.assertEqual(candidate.kind, "excel")
        self.assertEqual(candidate.headers, ["ID", "Value"])
        self.assertEqual(candidate.rows, [{"ID": "7", "Value": "alpha"}])
        self.assertEqual(candidate.row_count, 1)
        self.assertEqual(candidate.options, {"sheet_name": "Data", "header_row": 2})

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
