"""Schema migration and validation tests for replayable table steps."""

from __future__ import annotations

import copy
import unittest

from analytics_studio.project import FORMAT_VERSION, ProjectFileError, new_project, validate_project


class TransformPersistenceTests(unittest.TestCase):
    def test_new_project_uses_current_version_and_v3_sources_migrate_with_empty_steps(self) -> None:
        self.assertEqual(FORMAT_VERSION, 66)
        document = new_project("Legacy v3")
        document["format_version"] = 3
        document["data_sources"] = [{
            "id": "csv-1",
            "name": "Sales.csv",
            "kind": "csv",
            "path": "Sales.csv",
            "parser_options": {"delimiter": ",", "encoding": "utf-8-sig", "has_header": True},
        }]
        document["active_source_id"] = "csv-1"

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(migrated["data_sources"][0]["transform_steps"], [])

    def test_v1_and_v2_migrations_reach_current_version(self) -> None:
        for version in (1, 2):
            with self.subTest(version=version):
                document = new_project(f"v{version}")
                document["format_version"] = version
                document["data_sources"] = [{
                    "id": "csv-1", "name": "Sales.csv", "kind": "csv", "path": "Sales.csv",
                }]

                migrated = validate_project(document)

                self.assertEqual(migrated["format_version"], FORMAT_VERSION)
                self.assertEqual(migrated["data_sources"][0]["transform_steps"], [])

    def test_inline_and_file_sources_validate_ordered_steps(self) -> None:
        document = new_project("Transform steps")
        document["data_sources"] = [{
            "id": "inline-1", "name": "Table", "kind": "inline",
            "headers": ["Revenue"], "rows": [{"Revenue": "12"}],
            "transform_steps": [{
                "op": "convert_type", "column": "Revenue", "type": "number",
            }],
        }]
        document["active_source_id"] = "inline-1"
        original = copy.deepcopy(document)

        validated = validate_project(document)

        self.assertEqual(validated["data_sources"][0]["transform_steps"], document["data_sources"][0]["transform_steps"])
        self.assertEqual(document, original)

    def test_invalid_or_non_json_transform_steps_are_rejected(self) -> None:
        invalid_steps = [
            [{"op": "execute_code", "column": "A"}],
            [{"op": "remove_column", "column": "A", "extra": "no"}],
            [{"op": "rename_column", "column": "A", "new_name": 3}],
            "remove A",
        ]
        for steps in invalid_steps:
            with self.subTest(steps=steps):
                document = new_project("Bad transform")
                document["data_sources"] = [{
                    "id": "csv-1", "name": "Sales.csv", "kind": "csv", "path": "Sales.csv",
                    "transform_steps": steps,
                }]
                document["active_source_id"] = "csv-1"
                with self.assertRaises(ProjectFileError):
                    validate_project(document)


if __name__ == "__main__":
    unittest.main()
