"""Contract tests for linked-source project-format migrations."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from analytics_studio.project import (
    FORMAT_ID,
    FORMAT_VERSION,
    ProjectFileError,
    load_project,
    new_project,
    validate_project,
)


def make_v1_project() -> dict:
    document = new_project("Migration fixture")
    document["format"] = FORMAT_ID
    document["format_version"] = 1
    document.pop("active_source_id", None)
    document["data_sources"] = [
        {"id": "online", "name": "Online source", "kind": "service", "path": "service://source"},
        {"id": "json", "name": "JSON file", "kind": "json", "path": "records.json"},
        {"id": "excel", "name": "Workbook", "kind": "excel", "path": "book.xlsx"},
        {"id": "csv", "name": "CSV file", "kind": "csv", "path": "table.csv"},
    ]
    for source in document["data_sources"]:
        source.pop("parser_options", None)
    return document


class ProjectMigrationTests(unittest.TestCase):
    def test_v63_projects_migrate_to_calculated_table_format(self) -> None:
        document = new_project("v63 migration")
        document["format_version"] = 63

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)

    def test_v64_projects_gain_empty_date_table_metadata(self) -> None:
        document = new_project("v64 migration")
        document["format_version"] = 64
        document["model"]["tables"] = [{
            "id": "calendar",
            "source_id": "calendar",
            "name": "Calendar",
            "column_types": {"Date": "date"},
        }]

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertIsNone(migrated["model"]["tables"][0]["date_column"])

    def test_v65_projects_migrate_to_calendar_query_format(self) -> None:
        document = new_project("v65 migration")
        document["format_version"] = 65

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], 66)

    def test_marked_date_column_must_have_a_date_model_type(self) -> None:
        document = new_project("invalid date-table metadata")
        document["model"]["tables"] = [{
            "id": "calendar",
            "source_id": "calendar",
            "name": "Calendar",
            "column_types": {"Date": "text"},
            "date_column": "Date",
        }]

        with self.assertRaisesRegex(ProjectFileError, "date or datetime"):
            validate_project(document)

    def test_v62_projects_gain_empty_calculated_column_lists(self) -> None:
        document = new_project("v62 migration")
        document["format_version"] = 62
        document["model"]["tables"] = [{
            "id": "orders",
            "source_id": "orders",
            "name": "Orders",
            "column_types": {"Amount": "decimal_number"},
        }]

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(
            migrated["model"]["tables"][0]["calculated_columns"], []
        )

    def test_v1_validation_selects_first_v1_supported_source_and_adds_defaults(self) -> None:
        migrated = validate_project(make_v1_project())

        self.assertEqual(FORMAT_VERSION, 66)
        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(migrated["active_source_id"], "excel")
        self.assertEqual(migrated["data_sources"][2]["parser_options"], {
            "sheet_name": None, "header_row": None,
        })
        self.assertEqual(migrated["data_sources"][3]["parser_options"], {
            "delimiter": ",", "encoding": "utf-8-sig", "has_header": True,
        })
        # Migration is a value conversion; it must not mutate the caller's v1 object.
        original = make_v1_project()
        snapshot = copy.deepcopy(original)
        validate_project(original)
        self.assertEqual(original, snapshot)

    def test_v1_project_load_migrates_without_requiring_source_files_to_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.npa"
            path.write_text(json.dumps(make_v1_project()), encoding="utf-8")

            document, recovered = load_project(path)

        self.assertFalse(recovered)
        self.assertEqual(document["format_version"], FORMAT_VERSION)
        self.assertEqual(document["active_source_id"], "excel")
        self.assertEqual(document["data_sources"][2]["path"], "book.xlsx")

    def test_v1_without_csv_or_excel_has_no_active_source(self) -> None:
        document = make_v1_project()
        document["data_sources"] = document["data_sources"][:2]

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertIsNone(migrated["active_source_id"])

    def test_v2_rejects_an_active_source_id_that_does_not_resolve(self) -> None:
        document = new_project()
        document["format_version"] = 2
        document["active_source_id"] = "missing"

        with self.assertRaises(ProjectFileError):
            validate_project(document)

    def test_v2_rejects_duplicate_data_source_ids(self) -> None:
        document = new_project()
        document["format_version"] = 2
        document["data_sources"] = [
            {"id": "duplicate", "name": "First", "kind": "csv", "path": "one.csv"},
            {"id": "duplicate", "name": "Second", "kind": "csv", "path": "two.csv"},
        ]
        document["active_source_id"] = "duplicate"

        with self.assertRaisesRegex(ProjectFileError, "ID 'duplicate' is duplicated"):
            validate_project(document)

    def test_v2_validation_adds_defaults_without_mutating_input(self) -> None:
        document = new_project()
        document["format_version"] = 2
        document["data_sources"] = [
            {"id": "csv", "name": "CSV", "kind": "csv", "path": "table.csv"},
        ]
        document["active_source_id"] = "csv"
        original = copy.deepcopy(document)

        migrated = validate_project(document)

        self.assertEqual(document, original)
        self.assertEqual(migrated["data_sources"][0]["parser_options"], {
            "delimiter": ",", "encoding": "utf-8-sig", "has_header": True,
        })

    def test_v2_rejects_invalid_persisted_csv_options(self) -> None:
        document = new_project()
        document["format_version"] = 2
        document["data_sources"] = [{
            "id": "csv", "name": "CSV", "kind": "csv", "path": "table.csv",
            "parser_options": {
                "delimiter": "::", "encoding": "utf-8-sig", "has_header": True,
            },
        }]
        document["active_source_id"] = "csv"

        with self.assertRaises(ProjectFileError):
            validate_project(document)


if __name__ == "__main__":
    unittest.main()
