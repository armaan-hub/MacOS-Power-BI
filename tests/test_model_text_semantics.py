"""How loaded text and Excel numbers behave, read from Power BI Desktop 2.157.879.0.

Every expectation comes from a live comparison (``tools/table_oracle_diff.py`` and ad-hoc probes through
ADOMD) of tables that Power BI's own Power Query engine loaded:

* the model drops trailing characters U+0000-U+0020 from text it loads (tab, LF, CR, VT, FF and control
  characters included) but keeps non-breaking and ideographic spaces and leading spaces;
* ASCII letters compare case-insensitively, every spelling of a value is stored as the first one seen, and
  non-ASCII letters (``é``/``É``, ``σ``/``Σ``, ``ß``/``ss``) stay distinct;
* Excel stores doubles with 17 digits (``66.150000000000006``) and Power Query reads the double (66.15).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from analytics_studio.controller import _model_candidate_with_format_errors_as_blank
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.measures import evaluate_measures
from analytics_studio.power_query_values import PowerQueryCellError, ascii_fold, model_text_normalizer


def load(values: list[object]) -> list[object]:
    normalize = model_text_normalizer()
    return [normalize(value) for value in values]


class ModelTextNormalizerTests(unittest.TestCase):
    def test_trailing_spaces_and_control_characters_are_dropped(self) -> None:
        for raw, expected in (
            ("PREPAID CARDS ", "PREPAID CARDS"),
            ("two  ", "two"),
            ("tab\t", "tab"),
            ("lf\n", "lf"),
            ("cr\r", "cr"),
            ("vt\x0b", "vt"),
            ("ff\x0c", "ff"),
            ("nul\x01", "nul"),
            ("us\x1f", "us"),
            ("  ", ""),
            ("", ""),
            ("a \t\r\n ", "a"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(load([raw]), [expected])

    def test_other_whitespace_and_leading_spaces_are_kept(self) -> None:
        for raw in (" y", "nb ", "ideographic　", "nel\u0085", "zero​", "ls ", "em ", "del\x7f",
                    "inner\tspace", "space  "):
            with self.subTest(raw=raw):
                self.assertEqual(load([raw]), [raw])

    def test_non_text_values_pass_through(self) -> None:
        self.assertEqual(load([None, 5, Decimal("1.5"), date(2026, 1, 1)]), [None, 5, Decimal("1.5"), date(2026, 1, 1)])

    def test_ascii_case_variants_share_the_first_spelling(self) -> None:
        self.assertEqual(load(["case", "Case", "CASE"]), ["case", "case", "case"])
        self.assertEqual(load(["Zeta", "zeta", "ZETA", "Alpha"]), ["Zeta", "Zeta", "Zeta", "Alpha"])
        self.assertEqual(load(["b", "B", "b "]), ["b", "b", "b"])

    def test_non_ascii_letters_stay_distinct(self) -> None:
        for pair in (("Café", "CAFÉ"), ("σ", "Σ"), ("д", "Д"), ("à", "À"), ("ö", "Ö"), ("straße", "strasse"),
                     ("Ａ", "A")):
            with self.subTest(pair=pair):
                self.assertEqual(load(list(pair)), list(pair))
        self.assertEqual(load(["straße", "STRASSE", "strasse"]), ["straße", "STRASSE", "STRASSE"])

    def test_ascii_fold_only_touches_ascii_letters(self) -> None:
        self.assertEqual(ascii_fold("AbC É ß Σ"), "abc É ß Σ")


class ModelCandidateTests(unittest.TestCase):
    def candidate(self, rows: list[dict[str, object]]) -> ImportCandidate:
        return ImportCandidate(
            kind="csv", headers=list(rows[0]), rows=rows, options={"source_id": "t"}, notices=[],
        )

    def test_each_text_column_is_normalized_on_its_own(self) -> None:
        model = _model_candidate_with_format_errors_as_blank(self.candidate([
            {"Party": "CASH IN HAND ", "Other": "Case"},
            {"Party": "cash in hand", "Other": "CASE"},
            {"Party": "PREPAID CARDS\t", "Other": "case"},
        ]))
        self.assertEqual([row["Party"] for row in model.rows], ["CASH IN HAND", "CASH IN HAND", "PREPAID CARDS"])
        self.assertEqual([row["Other"] for row in model.rows], ["Case", "Case", "Case"])

    def test_query_candidate_is_left_untouched(self) -> None:
        source = self.candidate([{"Party": "A "}, {"Party": "a"}])
        _model_candidate_with_format_errors_as_blank(source)
        self.assertEqual([row["Party"] for row in source.rows], ["A ", "a"])

    def test_format_errors_still_load_as_blank_next_to_text(self) -> None:
        error = PowerQueryCellError(reason="DataFormat.Error", message="bad", value="x")
        model = _model_candidate_with_format_errors_as_blank(self.candidate([
            {"Amount": error, "Party": "A "},
        ]))
        self.assertEqual(model.rows[0]["Amount"], None)
        self.assertEqual(model.rows[0]["Party"], "A")


class ModelTextMeasureTests(unittest.TestCase):
    ROWS = [
        {"Color": "Blue", "Amount": "20"},
        {"Color": "blue", "Amount": "10"},
        {"Color": "Red", "Amount": "5"},
        {"Color": "Café", "Amount": "1"},
    ]
    CONTEXT = [{
        "id": "t", "name": "T", "headers": ["Color", "Amount"], "rows": ROWS,
        "column_types": {"Color": "text", "Amount": "whole_number"},
    }]

    def measure(self, expression: str) -> Decimal | None:
        return evaluate_measures(
            [{"name": "M", "expression": expression}], self.ROWS, ["Color", "Amount"], "T",
            measure_names=["M"], table_context=self.CONTEXT, active_table_id="t",
        )["M"]

    def test_text_filters_ignore_ascii_case(self) -> None:
        self.assertEqual(self.measure('CALCULATE(SUM(T[Amount]),T[Color]="BLUE")'), 30)
        self.assertEqual(self.measure('CALCULATE(SUM(T[Amount]),T[Color]<>"blue")'), 6)

    def test_non_ascii_letters_are_still_case_sensitive_in_filters(self) -> None:
        self.assertEqual(self.measure('CALCULATE(SUM(T[Amount]),T[Color]="Café")'), 1)
        self.assertIsNone(self.measure('CALCULATE(SUM(T[Amount]),T[Color]="CAFÉ")'))

    def test_trailing_space_in_a_literal_does_not_match(self) -> None:
        # Verified live: CALCULATE(COUNTROWS(T),T[s]="BB ") is blank although "bb" is stored.
        self.assertIsNone(self.measure('CALCULATE(SUM(T[Amount]),T[Color]="Red ")'))

    def test_distinct_count_merges_ascii_case_variants(self) -> None:
        self.assertEqual(self.measure("DISTINCTCOUNT(T[Color])"), 3)


class ExcelDoubleTests(unittest.TestCase):
    def workbook(self, path: Path, cells: list[str]) -> None:
        sheet = (
            '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Amount</t></is></c></row>'
            + "".join(f'<row r="{i}"><c r="A{i}"><v>{value}</v></c></row>' for i, value in enumerate(cells, 2))
            + "</sheetData></worksheet>"
        )
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/></Types>')
            archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
            archive.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>')
            archive.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
            archive.writestr("xl/worksheets/sheet1.xml", sheet)

    def test_seventeen_digit_excel_numbers_read_as_the_shortest_double(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "doubles.xlsx"
            self.workbook(path, [
                "66.150000000000006", "75.599999999999994", "10.199999999999999", "214.2", "7", "0.1",
                "1.0000000000000001E-3",
            ])
            values = [row["Amount"] for row in parse_file(path).rows]
        self.assertEqual(values, [
            Decimal("66.15"), Decimal("75.6"), Decimal("10.2"), Decimal("214.2"), 7, Decimal("0.1"),
            Decimal("0.001"),
        ])
        self.assertIsInstance(values[4], int)


if __name__ == "__main__":
    unittest.main()
