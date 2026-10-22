"""Contract tests for linked-source project-format migrations."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

import analytics_studio.project as project_module
from analytics_studio.project import (
    FORMAT_ID,
    FORMAT_VERSION,
    ProjectFileError,
    UnsupportedProjectVersion,
    load_project,
    new_project,
    save_project,
    validate_project,
)


def add_legacy_starter_visuals(document: dict) -> dict:
    """Build the old version-73 starter report for migration fixtures."""
    layouts = (
        ("card", "Revenue KPI", 14, 14, 120, 80),
        ("card", "Cost KPI", 148, 14, 120, 80),
        ("card", "Margin KPI", 282, 14, 120, 80),
        ("card", "Units KPI", 416, 14, 120, 80),
        ("card", "Orders KPI", 550, 14, 120, 80),
        ("column", "Monthly revenue", 14, 108, 330, 248),
        ("bar", "Region revenue", 358, 108, 330, 248),
    )
    document["report"]["pages"][0]["visuals"] = [
        {
            "id": f"starter-{index}", "type": kind, "title": title,
            "x": x, "y": y, "width": width, "height": height,
            "show_data_labels": False, "show_legend": False,
        }
        for index, (kind, title, x, y, width, height) in enumerate(layouts)
    ]
    return document


def make_v1_project() -> dict:
    document = add_legacy_starter_visuals(new_project("Migration fixture"))
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
    def test_every_supported_version_entrypoint_migrates_to_current_format(self) -> None:
        document = make_v1_project()
        historical_versions: dict[int, dict] = {}

        for version in range(1, FORMAT_VERSION):
            self.assertEqual(document["format_version"], version)
            historical_versions[version] = copy.deepcopy(document)
            migrate = getattr(
                project_module, f"_migrate_v{version}_to_v{version + 1}"
            )
            document = migrate(document)

        for version, historical in historical_versions.items():
            with self.subTest(starting_version=version):
                migrated = validate_project(historical)
                self.assertEqual(migrated["format_version"], FORMAT_VERSION)

    def test_v63_projects_migrate_to_calculated_table_format(self) -> None:
        document = new_project("v63 migration")
        document["format_version"] = 63

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)

    def test_new_projects_start_with_a_blank_report(self) -> None:
        document = new_project()

        self.assertEqual(document["report"]["pages"][0]["visuals"], [])

    def test_v73_starter_report_visuals_are_migrated_out(self) -> None:
        document = add_legacy_starter_visuals(new_project("old starter report"))
        document["format_version"] = 73

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(migrated["report"]["pages"][0]["visuals"], [])

    def test_v74_projects_migrate_to_saved_m_text_schema(self) -> None:
        document = new_project("v74 migration")
        document["format_version"] = 74

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)

    def test_v76_projects_migrate_and_preserve_measure_metadata(self) -> None:
        document = new_project("v76 measure metadata")
        document["format_version"] = 76
        document["model"]["measures"] = [{
            "name": "Sales total",
            "expression": "SUM([Sales])",
            "description": "Sales after discount",
            "display_folder": "Finance/Sales",
            "is_hidden": True,
        }]

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(migrated["model"]["measures"], document["model"]["measures"])

    def test_v78_migration_adds_empty_column_defaults_without_changing_visuals(self) -> None:
        document = add_legacy_starter_visuals(new_project("v78 model defaults"))
        document["format_version"] = 78
        document["model"]["tables"] = [{
            "id": "orders-catalog-id",
            "source_id": "orders-source-id",
            "name": "Orders",
            "column_types": {"Amount": "decimal_number"},
            "calculated_columns": [],
        }]
        visuals = document["report"]["pages"][0]["visuals"]
        visuals[0]["fields"] = {"Fields": ["Amount"]}
        visuals[0]["field_aggregations"] = {"Amount": "average"}
        visuals[5]["fields"] = {"X-axis": ["Month"], "Y-axis": ["Amount"]}
        visuals[5]["field_aggregations"] = {"Amount": "count"}
        original_aggregations = [
            copy.deepcopy(visual.get("field_aggregations", {}))
            for visual in visuals
        ]

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(
            migrated["model"]["tables"][0]["column_summarizations"], {}
        )
        self.assertEqual(
            [
                visual.get("field_aggregations", {})
                for visual in migrated["report"]["pages"][0]["visuals"]
            ],
            original_aggregations,
        )

    def test_v79_migration_adds_model_sort_maps_without_changing_existing_metadata(self) -> None:
        document = new_project("v79 model sorting")
        document["format_version"] = 79
        document["model"]["tables"] = [
            {
                "id": "orders-catalog",
                "source_id": "orders-source",
                "name": "Orders",
                "column_types": {"Month": "text", "MonthNumber": "whole_number"},
                "column_summarizations": {"MonthNumber": "sum"},
                "calculated_columns": [],
            },
            {
                "id": "calendar-catalog",
                "source_id": "calendar-source",
                "name": "Calendar",
                "column_types": {"Date": "date"},
                "column_summarizations": {},
                "calculated_columns": [],
            },
        ]
        document["model"]["measures"] = [{
            "name": "Revenue", "expression": "SUM([MonthNumber])",
        }]
        document["report"]["pages"][0]["visuals"] = [{
            "id": "orders-chart", "type": "column", "title": "Orders by month",
            "x": 10, "y": 10, "width": 400, "height": 250,
            "show_data_labels": False, "show_legend": False,
            "fields": {"X-axis": ["Month"], "Y-axis": ["Revenue"]},
        }]
        original_visuals = copy.deepcopy(document["report"]["pages"][0]["visuals"])
        original_measures = copy.deepcopy(document["model"]["measures"])

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(
            [table["column_sort_by"] for table in migrated["model"]["tables"]],
            [{}, {}],
        )
        self.assertEqual(migrated["model"]["tables"][0]["column_summarizations"], {
            "MonthNumber": "sum",
        })
        self.assertEqual(migrated["model"]["measures"], original_measures)
        self.assertEqual(
            migrated["report"]["pages"][0]["visuals"], original_visuals
        )

    def test_v80_and_v81_migrations_add_relationship_key_metadata_defaults(self) -> None:
        v80 = new_project("v80 group-by metadata")
        v80["format_version"] = 80
        v80["model"]["tables"] = [{
            "id": "regions",
            "source_id": "regions-source",
            "name": "Regions",
            "column_types": {"Region": "text", "RegionID": "whole_number"},
            "column_summarizations": {},
            "column_sort_by": {"Region": "RegionID"},
            "calculated_columns": [],
        }]

        migrated_v80 = validate_project(v80)

        self.assertEqual(migrated_v80["format_version"], FORMAT_VERSION)
        self.assertEqual(
            migrated_v80["model"]["tables"][0]["group_by_columns"], {}
        )
        self.assertIsNone(migrated_v80["model"]["tables"][0]["key_column"])
        self.assertEqual(
            migrated_v80["model"]["tables"][0]["column_sort_by"],
            {"Region": "RegionID"},
        )

        v81 = new_project("v81 key metadata")
        v81["format_version"] = 81
        v81["model"]["tables"] = [{
            "id": "regions",
            "source_id": "regions-source",
            "name": "Regions",
            "column_types": {"Region": "text", "RegionID": "whole_number"},
            "column_summarizations": {},
            "column_sort_by": {},
            "group_by_columns": {"Region": ["RegionID"]},
            "calculated_columns": [],
        }]

        migrated_v81 = validate_project(v81)

        self.assertEqual(migrated_v81["format_version"], FORMAT_VERSION)
        self.assertIsNone(migrated_v81["model"]["tables"][0]["key_column"])
        self.assertEqual(
            migrated_v81["model"]["tables"][0]["group_by_columns"],
            {"Region": ["RegionID"]},
        )

    def test_v82_project_migrates_to_v83_without_rewriting_existing_data(self) -> None:
        document = new_project("v82 sparse-boundary migration")
        document["format_version"] = 82
        document["report"]["pages"][0]["name"] = "Existing page"
        before = copy.deepcopy(document)

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(FORMAT_VERSION, 83)
        self.assertEqual(
            migrated["report"]["pages"][0]["name"],
            before["report"]["pages"][0]["name"],
        )
        self.assertEqual(migrated["data_sources"], before["data_sources"])
        self.assertEqual(document["format_version"], 82)

    def test_model_sort_maps_validate_shape_and_preserve_stale_names(self) -> None:
        document = new_project("sort map validation")
        document["model"]["tables"] = [{
            "id": "orders",
            "source_id": "orders",
            "name": "Orders",
            "column_types": {"Month": "text", "Month Number": "whole_number"},
            "column_sort_by": {
                "Removed category": "Removed sort key",
                "Month": "Month Number",
            },
        }]

        validated = validate_project(document)

        self.assertEqual(
            validated["model"]["tables"][0]["column_sort_by"],
            {"Removed category": "Removed sort key", "Month": "Month Number"},
        )

        for invalid_map in (
            [], None, "Month=Month Number", {" ": "Month Number"},
            {"Month": " "}, {"Month": 2}, {2: "Month Number"},
        ):
            invalid = copy.deepcopy(document)
            invalid["model"]["tables"][0]["column_sort_by"] = invalid_map
            with self.subTest(invalid_map=invalid_map):
                with self.assertRaisesRegex(ProjectFileError, "sort"):
                    validate_project(invalid)

    def test_column_summarization_values_and_dormant_keys_are_validated(self) -> None:
        for value in ("auto", "sum", "average", "count"):
            document = new_project(f"valid column summarization {value}")
            document["model"]["tables"] = [{
                "id": "orders",
                "source_id": "orders",
                "name": "Orders",
                "column_types": {"Amount": "decimal_number"},
                "column_summarizations": {"Amount": value},
            }]
            with self.subTest(value=value):
                validated = validate_project(document)
                self.assertEqual(
                    validated["model"]["tables"][0]["column_summarizations"],
                    {"Amount": value},
                )

        dormant = new_project("dormant column summarization")
        dormant["model"]["tables"] = [{
            "id": "orders",
            "source_id": "orders",
            "name": "Orders",
            "column_types": {"Amount": "decimal_number"},
            "column_summarizations": {
                "Removed amount": "average",
                "Amount": "count",
            },
        }]
        validated = validate_project(dormant)
        self.assertEqual(
            validated["model"]["tables"][0]["column_summarizations"],
            {"Removed amount": "average", "Amount": "count"},
        )

    def test_malformed_column_summarization_maps_are_rejected(self) -> None:
        malformed_maps = (
            [],
            None,
            "Amount=sum",
            {" ": "sum"},
            {"Amount": "median"},
            {"Amount": None},
            {"Amount": 1},
            {1: "sum"},
        )
        for invalid_map in malformed_maps:
            document = new_project("invalid column summarization")
            document["model"]["tables"] = [{
                "id": "orders",
                "source_id": "orders",
                "name": "Orders",
                "column_types": {"Amount": "decimal_number"},
                "column_summarizations": invalid_map,
            }]
            with self.subTest(value=invalid_map):
                with self.assertRaisesRegex(ProjectFileError, "summarization"):
                    validate_project(document)

    def test_saved_m_text_is_bounded_and_rejects_nulls(self) -> None:
        document = new_project("M text")
        document["data_sources"] = [{
            "id": "local",
            "name": "Sales",
            "kind": "inline",
            "headers": ["Region"],
            "rows": [{"Region": "East"}],
            "m_script": 'let\n    Source = #"Sales"\nin\n    Source',
        }]
        document["active_source_id"] = "local"

        validated = validate_project(document)

        self.assertEqual(validated["data_sources"][0]["m_script"], document["data_sources"][0]["m_script"])
        for invalid_script in (None, "\x00", "x" * 32_001):
            invalid = copy.deepcopy(document)
            invalid["data_sources"][0]["m_script"] = invalid_script
            with self.subTest(value_type=type(invalid_script).__name__, length=len(invalid_script or "")):
                with self.assertRaisesRegex(ProjectFileError, "saved M script"):
                    validate_project(invalid)

    def test_v73_customized_starter_visuals_are_preserved(self) -> None:
        document = add_legacy_starter_visuals(new_project("customized starter report"))
        document["format_version"] = 73
        document["report"]["pages"][0]["visuals"][0]["fields"] = {"Y-axis": ["Sales"]}

        migrated = validate_project(document)

        self.assertEqual(len(migrated["report"]["pages"][0]["visuals"]), 7)

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

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)

    def test_v68_projects_migrate_without_changing_visual_bindings(self) -> None:
        document = add_legacy_starter_visuals(new_project("v68 visual aggregation migration"))
        document["format_version"] = 68
        visuals = document["report"]["pages"][0]["visuals"]
        visuals[0]["fields"] = {"Y-axis": ["Revenue"]}

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(
            migrated["report"]["pages"][0]["visuals"][0]["fields"],
            {"Y-axis": ["Revenue"]},
        )
        self.assertNotIn(
            "field_aggregations", migrated["report"]["pages"][0]["visuals"][0]
        )
        self.assertFalse(migrated["report"]["pages"][0]["visuals"][0]["show_data_labels"])
        self.assertFalse(migrated["report"]["pages"][0]["visuals"][0]["show_legend"])

    def test_v70_projects_gain_default_data_label_and_legend_settings(self) -> None:
        document = add_legacy_starter_visuals(new_project("v70 visual formatting migration"))
        document["format_version"] = 70
        visual = document["report"]["pages"][0]["visuals"][0]
        visual["show_data_labels"] = True

        migrated = validate_project(document)

        migrated_visual = migrated["report"]["pages"][0]["visuals"][0]
        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertTrue(migrated_visual["show_data_labels"])
        self.assertFalse(migrated_visual["show_legend"])

    def test_v71_projects_migrate_to_visual_group_format_without_grouping_old_visuals(self) -> None:
        document = add_legacy_starter_visuals(new_project("v71 visual grouping migration"))
        document["format_version"] = 71
        document["report"]["pages"][0]["visuals"][0]["fields"] = {"Y-axis": ["Revenue"]}
        document["report"]["pages"][0]["visuals"][0].pop("group_id", None)

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertNotIn("group_id", migrated["report"]["pages"][0]["visuals"][0])

    def test_v72_projects_receive_the_default_report_theme(self) -> None:
        document = new_project("v72 theme migration")
        document["format_version"] = 72
        document["report"].pop("theme", None)

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(migrated["report"]["theme"], "Default")

    def test_report_theme_is_validated(self) -> None:
        document = new_project("invalid report theme")
        document["report"]["theme"] = "Neon"

        with self.assertRaisesRegex(ProjectFileError, "report theme must be"):
            validate_project(document)

    def test_v69_projects_gain_empty_visual_interaction_settings(self) -> None:
        document = add_legacy_starter_visuals(new_project("v69 visual interaction migration"))
        document["format_version"] = 69
        page = document["report"]["pages"][0]
        page.pop("visual_interactions", None)

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(migrated["report"]["pages"][0]["visual_interactions"], [])

    def test_visual_interaction_entries_are_validated(self) -> None:
        document = new_project("invalid visual interaction")
        document["report"]["pages"][0]["visual_interactions"] = [{
            "source_visual_id": "source",
            "target_visual_id": "target",
            "mode": "emphasize",
        }]

        with self.assertRaisesRegex(ProjectFileError, "filter, highlight, or none"):
            validate_project(document)

    def test_visual_format_flags_must_be_booleans(self) -> None:
        document = add_legacy_starter_visuals(new_project("invalid visual format flags"))
        document["report"]["pages"][0]["visuals"][0]["show_legend"] = "yes"

        with self.assertRaisesRegex(ProjectFileError, "show_legend must be a boolean"):
            validate_project(document)

    def test_visual_groups_require_two_visuals_and_non_empty_ids(self) -> None:
        document = add_legacy_starter_visuals(new_project("valid visual group"))
        visuals = document["report"]["pages"][0]["visuals"]
        visuals[0]["group_id"] = "group-1"
        visuals[1]["group_id"] = "group-1"
        self.assertEqual(validate_project(document)["report"]["pages"][0]["visuals"][0]["group_id"], "group-1")

        visuals[1].pop("group_id")
        with self.assertRaisesRegex(ProjectFileError, "at least two visuals"):
            validate_project(document)

        visuals[1]["group_id"] = "group-1"
        visuals[0]["group_id"] = " "
        with self.assertRaisesRegex(ProjectFileError, "group_id must be a non-empty string"):
            validate_project(document)

    def test_visual_interaction_entries_must_reference_page_visuals(self) -> None:
        document = add_legacy_starter_visuals(new_project("dangling visual interaction"))
        target_id = document["report"]["pages"][0]["visuals"][0]["id"]
        document["report"]["pages"][0]["visual_interactions"] = [{
            "source_visual_id": "missing-source",
            "target_visual_id": target_id,
            "mode": "highlight",
        }]

        with self.assertRaisesRegex(ProjectFileError, "unique source/target IDs"):
            validate_project(document)

    def test_visual_aggregation_names_are_validated(self) -> None:
        document = add_legacy_starter_visuals(new_project("invalid visual aggregation"))
        document["report"]["pages"][0]["visuals"][0]["field_aggregations"] = {
            "Revenue": "median",
        }

        with self.assertRaisesRegex(ProjectFileError, "sum, count, or average"):
            validate_project(document)

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

    def test_corrupt_primary_recovers_the_last_good_project_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recovery.npa"
            save_project(path, new_project("Last good"))
            save_project(path, new_project("Current"))
            path.write_text("{broken json", encoding="utf-8")

            recovered, used_backup = load_project(path)

        self.assertTrue(used_backup)
        self.assertEqual(recovered["name"], "Last good")

    def test_project_load_reports_when_primary_and_backup_are_both_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.npa"
            path.write_text("{broken primary", encoding="utf-8")
            Path(f"{path}.bak").write_text("{broken backup", encoding="utf-8")

            with self.assertRaisesRegex(ProjectFileError, "recovery copy also failed"):
                load_project(path)

    def test_newer_primary_version_does_not_fall_back_to_older_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "newer.npa"
            newer = new_project("Written by a newer app")
            newer["format_version"] = FORMAT_VERSION + 1
            path.write_text(json.dumps(newer), encoding="utf-8")
            save_project(Path(f"{path}.bak"), new_project("Older backup"))

            with self.assertRaises(UnsupportedProjectVersion):
                load_project(path)


if __name__ == "__main__":
    unittest.main()
