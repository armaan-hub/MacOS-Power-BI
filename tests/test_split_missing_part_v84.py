"""Task 209b: saved projects from before Task 209 keep the old "" missing part (format v83 -> v84 migration)."""

from __future__ import annotations

import copy
import unittest

from analytics_studio.file_import import ImportCandidate
from analytics_studio.project import FORMAT_VERSION, new_project, validate_project
from analytics_studio.transformations import apply_transformations


def _v83_document(steps: list[dict]) -> dict:
    document = new_project("v83 split missing part")
    document["format_version"] = 83
    document["data_sources"] = [{
        "id": "split_src",
        "name": "Split source",
        "kind": "inline",
        "headers": ["A"],
        "rows": [{"A": "x,y"}, {"A": "z"}],
        "transform_steps": steps,
    }]
    return document


class V84MissingPartMigrationTests(unittest.TestCase):
    def test_format_version_is_84(self) -> None:
        self.assertEqual(FORMAT_VERSION, 84)

    def test_v83_split_step_loads_and_replays_blank_missing_part(self) -> None:
        document = _v83_document([{"op": "split_column", "column": "A", "delimiter": ","}])
        before = copy.deepcopy(document)

        migrated = validate_project(document)

        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        source = migrated["data_sources"][0]
        self.assertEqual(source["transform_steps"][0]["missing_part"], "")
        self.assertEqual(document, before)
        result = apply_transformations(
            ImportCandidate("inline", source["headers"], source["rows"], {}, []),
            source["transform_steps"],
        )
        self.assertEqual(result.rows[0], {"A.1": "x", "A.2": "y"})
        self.assertEqual(result.rows[1], {"A.1": "z", "A.2": ""})

    def test_v83_each_delimiter_step_gets_blank_missing_part(self) -> None:
        document = _v83_document([
            {"op": "split_column_by_each_delimiter", "column": "A", "delimiter": ","},
            {"op": "split_column_by_positions", "column": "A", "positions": [0, 2]},
        ])

        migrated = validate_project(document)

        steps = migrated["data_sources"][0]["transform_steps"]
        self.assertEqual(steps[0]["missing_part"], "")
        self.assertNotIn("missing_part", steps[1])

    def test_v84_keyless_split_step_stays_null(self) -> None:
        document = _v83_document([{"op": "split_column", "column": "A", "delimiter": ","}])
        document["format_version"] = FORMAT_VERSION
        document["data_sources"][0]["transform_steps"][0].pop("missing_part", None)

        migrated = validate_project(document)

        self.assertNotIn("missing_part", migrated["data_sources"][0]["transform_steps"][0])


if __name__ == "__main__":
    unittest.main()
