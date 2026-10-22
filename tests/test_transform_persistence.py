"""Schema migration and validation tests for replayable table steps."""

from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from analytics_studio.file_import import ImportCandidate
from analytics_studio.project import (
    FORMAT_VERSION,
    ProjectFileError,
    load_project,
    new_project,
    save_project,
    validate_project,
)
from analytics_studio.transformations import apply_transformations


class TransformPersistenceTests(unittest.TestCase):
    def test_new_project_uses_current_version_and_v3_sources_migrate_with_empty_steps(self) -> None:
        document = new_project("Legacy v3")
        self.assertEqual(document["format_version"], FORMAT_VERSION)
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

    def test_sparse_power_query_steps_survive_project_save_and_reopen(self) -> None:
        steps = [
            {"op": "m_sparse_boundary_helper", "name": "FilterNullAndWhitespace"},
            {"op": "remove_sparse_bottom_rows"},
            {"op": "remove_sparse_top_rows"},
            {"op": "promote_headers", "promote_all_scalars": True},
        ]
        headers = [
            "Date", "Particulars", "Address", "Emirates", "Voucher Type",
            "Voucher No.", "Voucher Ref.", "TRN", "Quantity", "Value",
            "Gross Total", "Sales", "VAT-5%", "Discount",
        ]
        raw_headers = [f"Column{index}" for index in range(1, len(headers) + 1)]
        rows = [
            {header: None for header in raw_headers}
            for _ in range(10)
        ]
        rows.append(dict(zip(raw_headers, headers)))
        for index in range(572):
            values = [
                f"2026-08-{index % 28 + 1:02d}", f"Customer {index + 1}",
                f"Address {index + 1}", "Dubai", "Sales",
                f"V{index + 1:04d}", f"Ref {index + 1:04d}",
                "100000000000000", "1", "1000", "1050", "1000",
                "50", "0",
            ]
            rows.append(dict(zip(raw_headers, values)))
        rows.append(dict(zip(raw_headers, [
            None, "Grand Total", None, None, None, None, None, None, None,
            None, "785000", "749153.63", "37406.97", "0",
        ])))
        rows.extend(
            {header: None for header in raw_headers}
            for _ in range(38)
        )
        self.assertEqual(len(rows), 622)
        document = new_project("Sparse Power Query steps")
        document["data_sources"] = [{
            "id": "inline-1",
            "name": "VAT 5%",
            "kind": "inline",
            "headers": raw_headers,
            "rows": rows,
            "transform_steps": steps,
        }]
        document["active_source_id"] = "inline-1"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sparse-steps.npa"
            save_project(path, document)
            reopened, recovered = load_project(path)

        self.assertFalse(recovered)
        reopened_source = reopened["data_sources"][0]
        self.assertEqual(
            reopened_source["transform_steps"], steps
        )
        candidate = ImportCandidate(
            kind=reopened_source["kind"],
            headers=reopened_source["headers"],
            rows=reopened_source["rows"],
            options=reopened_source.get("options", {}),
            notices=[],
            source_id=reopened_source["id"],
        )
        replayed = apply_transformations(candidate, reopened_source["transform_steps"])
        self.assertEqual(replayed.headers, headers)
        self.assertEqual(len(replayed.rows), 573)
        self.assertEqual(replayed.rows[0]["Date"], "2026-08-01")
        self.assertEqual(replayed.rows[0]["Particulars"], "Customer 1")
        self.assertEqual(
            replayed.rows[-1]["Particulars"], "Grand Total"
        )
        self.assertEqual(replayed.rows[-1]["Sales"], "749153.63")

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
