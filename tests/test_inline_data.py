"""Schema and helper tests for bounded, embedded inline tables."""

from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analytics_studio import inline_data
from analytics_studio.project import (
    FORMAT_VERSION,
    ProjectFileError,
    load_project,
    new_project,
    save_project,
    validate_project,
)


def inline_project(*, headers=None, rows=None, **source_fields):
    document = new_project("Inline fixture")
    source = {
        "id": "inline-1",
        "name": "Pasted data",
        "kind": "inline",
        "headers": headers if headers is not None else ["Name", "Value"],
        "rows": rows if rows is not None else [{"Name": "Ada", "Value": "12"}],
        **source_fields,
    }
    document["data_sources"] = [source]
    document["active_source_id"] = source["id"]
    return document


class InlineDataHelperTests(unittest.TestCase):
    def test_sample_candidate_is_deterministic_and_uses_inline_kind(self) -> None:
        first = inline_data.sample_candidate()
        second = inline_data.sample_candidate()

        self.assertEqual(first, second)
        self.assertEqual(first.kind, "inline")
        self.assertEqual(first.headers, ["Order Date", "Region", "Revenue", "Cost", "Margin", "Units"])
        self.assertGreater(first.row_count, 0)
        self.assertEqual(first.options["name"], "Sample data")

    def test_candidate_creates_a_pathless_source_record(self) -> None:
        source = inline_data.source_from_candidate(inline_data.sample_candidate(), "sample-1")

        self.assertEqual(source["id"], "sample-1")
        self.assertEqual(source["kind"], "inline")
        self.assertNotIn("path", source)
        self.assertEqual(source["headers"], inline_data.sample_candidate().headers)

    def test_parse_pasted_csv_normalizes_headers_and_pads_ragged_rows(self) -> None:
        candidate = inline_data.parse_pasted_table("Name,,Name\nAda,12\nLin,7,8\n")

        self.assertEqual(candidate.kind, "inline")
        self.assertEqual(candidate.headers, ["Name", "Column 2", "Name_2"])
        self.assertEqual(candidate.rows, [
            {"Name": "Ada", "Column 2": "12", "Name_2": ""},
            {"Name": "Lin", "Column 2": "7", "Name_2": "8"},
        ])
        self.assertEqual(candidate.options["delimiter"], ",")

    def test_parse_pasted_tsv_is_selected_deterministically(self) -> None:
        candidate = inline_data.parse_pasted_table("Name\tValue\nAda\t12\n")

        self.assertEqual(candidate.options["delimiter"], "\t")
        self.assertEqual(candidate.headers, ["Name", "Value"])
        self.assertEqual(candidate.rows, [{"Name": "Ada", "Value": "12"}])

    def test_parse_pasted_text_rejects_empty_and_malformed_csv(self) -> None:
        for text in ("", "\n\n", 'Name,Value\n"unterminated,12\n'):
            with self.subTest(text=text), self.assertRaises(inline_data.InlineDataError):
                inline_data.parse_pasted_table(text)

    def test_parse_pasted_text_enforces_limits(self) -> None:
        with patch.object(inline_data, "MAX_INLINE_ROWS", 1):
            with self.assertRaises(inline_data.InlineDataError):
                inline_data.parse_pasted_table("Name\nAda\nLin\n")

        with patch.object(inline_data, "MAX_INLINE_COLUMNS", 1):
            with self.assertRaises(inline_data.InlineDataError):
                inline_data.parse_pasted_table("A,B\n1,2\n")

        with patch.object(inline_data, "MAX_INLINE_SERIALIZED_BYTES", 5):
            with self.assertRaises(inline_data.InlineDataError):
                inline_data.parse_pasted_table("Name\nAda\n")


class InlineSourceSchemaTests(unittest.TestCase):
    def test_new_projects_use_current_version_and_accept_pathless_inline_source(self) -> None:
        self.assertEqual(FORMAT_VERSION, 66)
        document = inline_project()

        validated = validate_project(document)

        self.assertEqual(validated["format_version"], FORMAT_VERSION)
        self.assertNotIn("path", validated["data_sources"][0])
        self.assertEqual(validated["data_sources"][0]["headers"], ["Name", "Value"])

    def test_inline_source_validation_does_not_mutate_input(self) -> None:
        document = inline_project()
        original = copy.deepcopy(document)

        validate_project(document)

        self.assertEqual(document, original)

    def test_inline_source_survives_project_save_and_reopen(self) -> None:
        document = inline_project()
        source = inline_data.source_from_candidate(inline_data.sample_candidate(), "sample-1")
        document["data_sources"] = [source]
        document["active_source_id"] = "sample-1"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inline.npa"
            saved = save_project(path, document)
            reopened, recovered = load_project(path)

        self.assertFalse(recovered)
        self.assertEqual(saved["format_version"], FORMAT_VERSION)
        self.assertEqual(reopened["data_sources"], [{**source, "transform_steps": []}])
        self.assertNotIn("path", reopened["data_sources"][0])

    def test_inline_source_accepts_json_scalar_and_null_values(self) -> None:
        document = inline_project(
            headers=["Text", "Boolean", "Integer", "Float", "Null"],
            rows=[{"Text": "x", "Boolean": True, "Integer": 0, "Float": 1.5, "Null": None}],
        )

        validated = validate_project(document)

        self.assertEqual(validated["data_sources"][0]["rows"][0], document["data_sources"][0]["rows"][0])

    def test_inline_source_rejects_fake_paths_bad_headers_and_nested_values(self) -> None:
        bad_documents = [
            inline_project(path="fake.csv"),
            inline_project(headers=["A", "A"]),
            inline_project(headers=["A", " "]),
            inline_project(rows=[{"Name": ["nested"], "Value": "12"}]),
            inline_project(rows=[{"Name": "Ada"}]),
            inline_project(rows=[{"Name": "Ada", "Value": float("nan")}]),
        ]

        for document in bad_documents:
            with self.subTest(source=document["data_sources"][0]), self.assertRaises(ProjectFileError):
                validate_project(document)

    def test_inline_source_enforces_rows_columns_cells_and_serialized_limit(self) -> None:
        with patch.object(inline_data, "MAX_INLINE_ROWS", 1):
            with self.assertRaises(ProjectFileError):
                validate_project(inline_project(rows=[
                    {"Name": "Ada", "Value": "1"},
                    {"Name": "Lin", "Value": "2"},
                ]))

        with patch.object(inline_data, "MAX_INLINE_COLUMNS", 1):
            with self.assertRaises(ProjectFileError):
                validate_project(inline_project())

        with patch.object(inline_data, "MAX_INLINE_CELLS", 1):
            with self.assertRaises(ProjectFileError):
                validate_project(inline_project())

        with patch.object(inline_data, "MAX_INLINE_SERIALIZED_BYTES", 5):
            with self.assertRaises(ProjectFileError):
                validate_project(inline_project())

    def test_v2_file_source_migrates_to_current_version_without_changing_file_rules(self) -> None:
        document = new_project("V2 fixture")
        document["format_version"] = 2
        document["data_sources"] = [{
            "id": "csv-1",
            "name": "Sales CSV",
            "kind": "csv",
            "path": "sales.csv",
        }]
        document["active_source_id"] = "csv-1"

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(migrated["data_sources"][0]["path"], "sales.csv")
        self.assertEqual(migrated["data_sources"][0]["parser_options"], {
            "delimiter": ",", "encoding": "utf-8-sig", "has_header": True,
        })


if __name__ == "__main__":
    unittest.main()
