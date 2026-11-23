"""Format v85: optional large-data store settings on csv/parquet data sources."""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any

from analytics_studio.project import (
    FORMAT_VERSION,
    ProjectFileError,
    UnsupportedProjectVersion,
    new_project,
    validate_project,
)

HASH = "a" * 64


def _store() -> dict[str, Any]:
    return {
        "table": "sales_table",
        "row_count": 250_000,
        "headers": ["Region", "Sales"],
        "physical_types": ["text", "decimal"],
        "column_types": {"Region": "Text", "Sales": "Decimal"},
        "source_id": "src-1",
        "data_file": "sales_src-1.npa.data",
        "fingerprint": {"size": 1234, "mtime_ns": 5678, "head_tail_sha256": HASH},
        "generation": 1,
        "duckdb_version": "1.4.0",
        "notices": ["Rows beyond the first 100,000 went to the store."],
        "source_arrow_types": ["string", "decimal128(18, 2)"],
    }


def _document(store: Any = None, kind: str = "csv") -> dict[str, Any]:
    document = new_project("store source")
    source: dict[str, Any] = {
        "id": "src-1",
        "name": "Sales",
        "kind": kind,
        "path": "/data/sales.csv",
    }
    if store is not None:
        source["store"] = store
    document["data_sources"] = [source]
    return document


def _v84_document() -> dict[str, Any]:
    document = _document()
    document["format_version"] = 84
    return document


def _validated_store_source() -> dict[str, Any]:
    return validate_project(_document(_store()))["data_sources"][0]


class StoreSourceValidationTests(unittest.TestCase):
    def test_format_version_is_85(self) -> None:
        self.assertEqual(FORMAT_VERSION, 85)

    def test_valid_store_source_validates(self) -> None:
        migrated = validate_project(_document(_store()))

        self.assertEqual(migrated["format_version"], 85)
        self.assertEqual(migrated["data_sources"][0]["store"], _store())

    def test_csv_and_parquet_both_accept_store(self) -> None:
        for kind in ("csv", "parquet"):
            with self.subTest(kind=kind):
                migrated = validate_project(_document(_store(), kind=kind))
                self.assertIn("store", migrated["data_sources"][0])

    def test_optional_keys_may_be_absent(self) -> None:
        store = _store()
        for key in ("column_types", "notices", "source_arrow_types"):
            store.pop(key)
        migrated = validate_project(_document(store))
        self.assertNotIn("notices", migrated["data_sources"][0]["store"])

    def test_each_required_key_is_needed(self) -> None:
        for key in ("table", "row_count", "headers", "physical_types", "source_id",
                    "data_file", "fingerprint", "generation", "duckdb_version"):
            with self.subTest(key=key):
                store = _store()
                store.pop(key)
                with self.assertRaises(ProjectFileError) as caught:
                    validate_project(_document(store))
                self.assertIn(repr(key), str(caught.exception))

    def test_bad_table_name_rejected(self) -> None:
        for bad in ("", "   ", 3):
            with self.subTest(table=bad):
                store = _store()
                store["table"] = bad
                with self.assertRaises(ProjectFileError):
                    validate_project(_document(store))

    def test_row_count_must_be_non_negative_int_not_bool(self) -> None:
        for bad in (-1, True, "5", 1.5):
            with self.subTest(row_count=bad):
                store = _store()
                store["row_count"] = bad
                with self.assertRaises(ProjectFileError):
                    validate_project(_document(store))

    def test_row_count_zero_is_valid(self) -> None:
        store = _store()
        store["row_count"] = 0
        validate_project(_document(store))

    def test_headers_rules(self) -> None:
        cases = {
            "too many": [f"c{i}" for i in range(513)],
            "duplicate": ["A", "A"],
            "empty name": ["A", ""],
            "not a list": "A,B",
        }
        for label, headers in cases.items():
            with self.subTest(case=label):
                store = _store()
                store["headers"] = headers
                store["physical_types"] = ["text"] * 2
                with self.assertRaises(ProjectFileError):
                    validate_project(_document(store))

    def test_512_headers_is_the_limit(self) -> None:
        store = _store()
        store["headers"] = [f"c{i}" for i in range(512)]
        store["physical_types"] = ["text"] * 512
        store.pop("column_types")
        store.pop("source_arrow_types", None)
        validate_project(_document(store))

    def test_physical_types_rules(self) -> None:
        store = _store()
        store["physical_types"] = ["text"]
        with self.assertRaises(ProjectFileError):
            validate_project(_document(store))

        store = _store()
        store["physical_types"] = ["text", "float"]
        with self.assertRaises(ProjectFileError) as caught:
            validate_project(_document(store))
        self.assertIn("physical_types", str(caught.exception))

    def test_every_store_type_name_is_accepted(self) -> None:
        store = _store()
        store["headers"] = ["a", "b", "c", "d", "e", "f"]
        store["physical_types"] = ["whole", "decimal", "fixed", "datetime", "text", "boolean"]
        store.pop("column_types")
        store.pop("source_arrow_types", None)
        validate_project(_document(store))

    def test_column_types_must_map_text_to_text(self) -> None:
        store = _store()
        store["column_types"] = {"Region": 3}
        with self.assertRaises(ProjectFileError):
            validate_project(_document(store))

    def test_source_id_must_be_non_empty(self) -> None:
        store = _store()
        store["source_id"] = ""
        with self.assertRaises(ProjectFileError):
            validate_project(_document(store))

    def test_data_file_must_be_bare_name(self) -> None:
        for bad in ("", "sub/file.data", "sub\\file.data", "../file.data", "a..b.data", "x\x00y"):
            with self.subTest(data_file=bad):
                store = _store()
                store["data_file"] = bad
                with self.assertRaises(ProjectFileError):
                    validate_project(_document(store))

    def test_fingerprint_rules(self) -> None:
        cases: dict[str, Any] = {
            "missing sha": {"size": 1, "mtime_ns": 1},
            "missing size": {"mtime_ns": 1, "head_tail_sha256": HASH},
            "short sha": {"size": 1, "mtime_ns": 1, "head_tail_sha256": "a" * 63},
            "non-hex sha": {"size": 1, "mtime_ns": 1, "head_tail_sha256": "g" * 64},
            "negative size": {"size": -1, "mtime_ns": 1, "head_tail_sha256": HASH},
            "bool mtime": {"size": 1, "mtime_ns": True, "head_tail_sha256": HASH},
            "unknown fingerprint key": {"size": 1, "mtime_ns": 1, "head_tail_sha256": HASH, "x": 1},
        }
        for label, fingerprint in cases.items():
            with self.subTest(case=label):
                store = _store()
                store["fingerprint"] = fingerprint
                with self.assertRaises(ProjectFileError):
                    validate_project(_document(store))

    def test_generation_must_be_at_least_one(self) -> None:
        for bad in (0, True, -3):
            with self.subTest(generation=bad):
                store = _store()
                store["generation"] = bad
                with self.assertRaises(ProjectFileError):
                    validate_project(_document(store))

    def test_duckdb_version_must_be_non_empty(self) -> None:
        store = _store()
        store["duckdb_version"] = " "
        with self.assertRaises(ProjectFileError):
            validate_project(_document(store))

    def test_notices_must_be_text_list(self) -> None:
        store = _store()
        store["notices"] = "one notice"
        with self.assertRaises(ProjectFileError):
            validate_project(_document(store))

    def test_source_arrow_types_length_must_match_headers(self) -> None:
        store = _store()
        store["source_arrow_types"] = ["string"]
        with self.assertRaises(ProjectFileError):
            validate_project(_document(store))

    def test_unknown_store_key_is_rejected_by_name(self) -> None:
        store = _store()
        store["extra_setting"] = True
        with self.assertRaises(ProjectFileError) as caught:
            validate_project(_document(store))
        self.assertIn("'extra_setting'", str(caught.exception))

    def test_store_on_other_kinds_is_rejected(self) -> None:
        for kind in ("excel", "json", "xml", "sqlite", "inline"):
            with self.subTest(kind=kind):
                document = _document(_store(), kind=kind)
                if kind == "inline":
                    document["data_sources"][0].pop("path")
                    document["data_sources"][0]["headers"] = ["A"]
                    document["data_sources"][0]["rows"] = [{"A": "x"}]
                with self.assertRaises(ProjectFileError) as caught:
                    validate_project(document)
                self.assertIn("CSV and Parquet", str(caught.exception))

    def test_store_must_be_an_object(self) -> None:
        with self.assertRaises(ProjectFileError):
            validate_project(_document(["not", "an", "object"]))

    def test_transform_steps_must_be_empty_or_absent(self) -> None:
        document = _document(_store())
        document["data_sources"][0]["transform_steps"] = []
        validate_project(document)

        document = _document(_store())
        document["data_sources"][0]["transform_steps"] = [
            {"op": "split_column", "column": "Region", "delimiter": ","}
        ]
        with self.assertRaises(ProjectFileError):
            validate_project(document)

    def test_rows_on_a_store_source_are_rejected(self) -> None:
        document = _document(_store())
        document["data_sources"][0]["rows"] = [{"Region": "x"}]
        with self.assertRaises(ProjectFileError) as caught:
            validate_project(document)
        self.assertIn("must not contain rows", str(caught.exception))

    def test_path_is_required_for_store_source(self) -> None:
        document = _document(_store())
        document["data_sources"][0].pop("path")
        with self.assertRaises(ProjectFileError):
            validate_project(document)

    def test_empty_path_is_rejected_for_store_source(self) -> None:
        document = _document(_store())
        document["data_sources"][0]["path"] = "  "
        with self.assertRaises(ProjectFileError):
            validate_project(document)


    def test_integer_fields_accept_2_63_minus_1_and_refuse_2_63(self) -> None:
        limit = 2**63 - 1
        for field in ("row_count", "generation", "size", "mtime_ns"):
            with self.subTest(field=field, value="limit"):
                store = _store()
                if field in ("size", "mtime_ns"):
                    store["fingerprint"][field] = limit
                else:
                    store[field] = limit
                validate_project(_document(store))
            with self.subTest(field=field, value="over"):
                store = _store()
                if field in ("size", "mtime_ns"):
                    store["fingerprint"][field] = limit + 1
                else:
                    store[field] = limit + 1
                with self.assertRaises(ProjectFileError):
                    validate_project(_document(store))

    def test_bool_refused_for_every_integer_field(self) -> None:
        for field in ("row_count", "generation"):
            with self.subTest(field=field):
                store = _store()
                store[field] = True
                with self.assertRaises(ProjectFileError):
                    validate_project(_document(store))
        for field in ("size", "mtime_ns"):
            with self.subTest(field=field):
                store = _store()
                store["fingerprint"][field] = True
                with self.assertRaises(ProjectFileError):
                    validate_project(_document(store))

    def test_uppercase_sha256_is_refused(self) -> None:
        store = _store()
        store["fingerprint"]["head_tail_sha256"] = "A" * 64
        with self.assertRaises(ProjectFileError):
            validate_project(_document(store))

    def test_lowercase_sha256_is_accepted(self) -> None:
        store = _store()
        store["fingerprint"]["head_tail_sha256"] = "0123456789abcdef" * 4
        validate_project(_document(store))

    def test_headers_differing_only_by_ascii_case_are_refused(self) -> None:
        store = _store()
        store["headers"] = ["A", "a"]
        store["physical_types"] = ["text", "text"]
        with self.assertRaises(ProjectFileError) as caught:
            validate_project(_document(store))
        self.assertIn("ASCII letter case", str(caught.exception))

    def test_non_ascii_case_variants_are_distinct_headers(self) -> None:
        store = _store()
        store["headers"] = ["\u00c9", "\u00e9"]
        store["physical_types"] = ["text", "text"]
        store.pop("column_types")
        store.pop("source_arrow_types", None)
        validate_project(_document(store))

    def test_513_headers_are_refused(self) -> None:
        store = _store()
        store["headers"] = [f"c{i}" for i in range(513)]
        store["physical_types"] = ["text"] * 513
        store.pop("column_types")
        store.pop("source_arrow_types", None)
        with self.assertRaises(ProjectFileError):
            validate_project(_document(store))

    def test_physical_types_match_store_column_types(self) -> None:
        from analytics_studio.project import STORE_PHYSICAL_TYPES
        from analytics_studio.store.base import COLUMN_TYPES

        self.assertEqual(tuple(STORE_PHYSICAL_TYPES), tuple(COLUMN_TYPES))


class StoreMigrationTests(unittest.TestCase):
    def test_v84_project_migrates_to_v85_unchanged(self) -> None:
        document = _v84_document()
        before = copy.deepcopy(document)

        migrated = validate_project(document)

        # The migration only moves the version: the result equals the same content saved as v85.
        as_v85 = copy.deepcopy(before)
        as_v85["format_version"] = 85
        self.assertEqual(migrated, validate_project(as_v85))
        self.assertEqual(migrated["format_version"], 85)
        self.assertNotIn("store", migrated["data_sources"][0])
        self.assertEqual(document, before)

    def test_v84_project_with_no_sources_migrates(self) -> None:
        document = new_project("v84 no sources")
        document["format_version"] = 84
        migrated = validate_project(document)
        self.assertEqual(migrated["format_version"], 85)
        self.assertEqual(migrated["data_sources"], [])

    def test_version_above_85_is_still_refused(self) -> None:
        document = _document(_store())
        document["format_version"] = 86
        with self.assertRaises(UnsupportedProjectVersion):
            validate_project(document)


class StoreRoundTripTests(unittest.TestCase):
    def test_store_block_survives_the_save_merge(self) -> None:
        # Reproduces controller.py:14096-14102 (_document_for_save): the saved source is
        # {**source, **source_record}, and source_record has no "store" key.
        source = _validated_store_source()
        source_record = {
            "id": "src-1",
            "name": "Sales",
            "kind": "csv",
            "path": "/data/sales.csv",
            "parser_options": {"delimiter": ","},
            "transform_steps": [],
        }
        document = _document(_store())
        document["data_sources"][0] = {**source, **source_record}

        migrated = validate_project(document)

        self.assertEqual(migrated["data_sources"][0]["store"], _store())
        self.assertNotIn("rows", migrated["data_sources"][0])

    def test_round_trip_through_json_keeps_store(self) -> None:
        first = validate_project(_document(_store()))
        text = json.dumps(first, sort_keys=True)
        second = validate_project(json.loads(text))

        self.assertEqual(second["data_sources"][0]["store"], _store())
        self.assertEqual(second["format_version"], 85)
        self.assertEqual(json.dumps(second, sort_keys=True), text)


if __name__ == "__main__":
    unittest.main()
