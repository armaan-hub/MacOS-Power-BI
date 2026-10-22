"""Boundary checks for bounded folder, SQLite, and Parquet imports."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as parquet

from analytics_studio.file_import import FileImportError, list_sqlite_tables, parse_file
from analytics_studio.folder_import import discover_folder_files, parse_folder


class ImportBoundaryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_folder_rejects_file_count_and_combined_source_size_limits(self) -> None:
        folder = self.root / "folder"
        folder.mkdir()
        (folder / "one.csv").write_text("id\n1\n", encoding="utf-8")
        (folder / "two.csv").write_text("id\n2\n", encoding="utf-8")

        with patch("analytics_studio.folder_import.MAX_FOLDER_FILES", 1):
            with self.assertRaisesRegex(FileImportError, "more than 1 files"):
                discover_folder_files(folder, file_kind="csv")

        with patch("analytics_studio.folder_import.MAX_FOLDER_SOURCE_BYTES", 4):
            with self.assertRaisesRegex(FileImportError, "combined folder import limit"):
                discover_folder_files(folder, file_kind="csv")

    def test_folder_rejects_schema_mismatch_against_the_selected_sample(self) -> None:
        folder = self.root / "schema"
        folder.mkdir()
        (folder / "a.csv").write_text("id,amount\n1,10\n", encoding="utf-8")
        (folder / "b.csv").write_text("amount,id\n20,2\n", encoding="utf-8")

        with self.assertRaisesRegex(FileImportError, "Schema mismatch in b.csv"):
            parse_folder(folder, {"sample_file": "a.csv"})

    def test_folder_rejects_combined_row_and_cell_limits(self) -> None:
        folder = self.root / "combined-limits"
        folder.mkdir()
        (folder / "a.csv").write_text("id\n1\n", encoding="utf-8")
        (folder / "b.csv").write_text("id\n2\n", encoding="utf-8")

        with patch("analytics_studio.folder_import.MAX_DATA_ROWS", 1):
            with self.assertRaisesRegex(FileImportError, "Combined folder data exceeds the 1-row"):
                parse_folder(folder, {"sample_file": "a.csv"})

        single_file = self.root / "single-file"
        single_file.mkdir()
        (single_file / "a.csv").write_text("id,name\n1,A\n", encoding="utf-8")
        with patch("analytics_studio.folder_import.MAX_CELLS", 2):
            with self.assertRaisesRegex(FileImportError, "Combined folder data exceeds the 2-cell"):
                parse_folder(single_file, {"sample_file": "a.csv"})

    def create_sqlite(self, filename: str, schema: str, rows: list[tuple]) -> Path:
        path = self.root / filename
        with closing(sqlite3.connect(path)) as database:
            with database:
                database.execute(schema)
                if rows:
                    placeholders = ",".join("?" for _ in rows[0])
                    database.executemany(
                        f"INSERT INTO records VALUES ({placeholders})", rows
                    )
        return path

    def test_sqlite_rejects_blob_and_rendered_text_limit(self) -> None:
        blob_path = self.create_sqlite(
            "blob.sqlite", "CREATE TABLE records (value BLOB)", [(b"binary",)]
        )
        with self.assertRaisesRegex(FileImportError, "BLOB columns are not supported"):
            parse_file(blob_path)

        text_path = self.create_sqlite(
            "text.sqlite", "CREATE TABLE records (value TEXT)", [("large",)]
        )
        with patch("analytics_studio.file_import.MAX_SQLITE_TEXT_BYTES", 2):
            with self.assertRaisesRegex(FileImportError, "rendered-text import limit"):
                parse_file(text_path)

    def test_sqlite_rejects_source_row_column_cell_and_non_finite_limits(self) -> None:
        multi_path = self.create_sqlite(
            "multi.sqlite",
            "CREATE TABLE records (first INTEGER, second INTEGER)",
            [(1, 2), (3, 4)],
        )
        with patch("analytics_studio.file_import.MAX_SOURCE_BYTES", 1):
            with self.assertRaisesRegex(FileImportError, "import limit"):
                parse_file(multi_path)
        with patch("analytics_studio.file_import.MAX_DATA_ROWS", 1):
            with self.assertRaisesRegex(FileImportError, "row import limit"):
                parse_file(multi_path)
        with patch("analytics_studio.file_import.MAX_COLUMNS", 1):
            with self.assertRaisesRegex(FileImportError, "column import limit"):
                parse_file(multi_path)
        with patch("analytics_studio.file_import.MAX_CELLS", 1):
            with self.assertRaisesRegex(FileImportError, "cell import limit"):
                parse_file(multi_path)

        with (
            patch("analytics_studio.file_import.MAX_SOURCE_BYTES", 1),
            patch("analytics_studio.file_import._source_size", return_value=0),
        ):
            with self.assertRaisesRegex(FileImportError, "SQLite import limit"):
                list_sqlite_tables(multi_path)

        non_finite_path = self.create_sqlite(
            "non-finite.sqlite", "CREATE TABLE records (value REAL)", [(float("inf"),)]
        )
        with self.assertRaisesRegex(FileImportError, "non-finite number"):
            parse_file(non_finite_path)

    def test_sqlite_query_deadline_interrupts_a_large_scan(self) -> None:
        path = self.create_sqlite(
            "scan.sqlite",
            "CREATE TABLE records (value INTEGER)",
            [(value,) for value in range(25_000)],
        )
        clock_calls = 0

        def expired_clock() -> float:
            nonlocal clock_calls
            clock_calls += 1
            # list_sqlite_tables and the row reader each open a protected
            # connection; advance beyond the second connection's deadline.
            return float((clock_calls - 1) * 11)

        with patch("analytics_studio.file_import.time.monotonic", side_effect=expired_clock):
            with self.assertRaisesRegex(FileImportError, "Could not read SQLite table"):
                parse_file(path)

        self.assertGreaterEqual(clock_calls, 2)

    def write_parquet(self, name: str, table: pa.Table) -> Path:
        path = self.root / name
        parquet.write_table(table, path)
        return path

    def test_parquet_rejects_nested_types_non_finite_numbers_and_expansion(self) -> None:
        nested_path = self.write_parquet(
            "nested.parquet", pa.table({"items": [[1, 2]]})
        )
        with self.assertRaisesRegex(FileImportError, "nested and binary types"):
            parse_file(nested_path)

        non_finite_path = self.write_parquet(
            "non-finite.parquet", pa.table({"value": [float("nan")]})
        )
        with self.assertRaisesRegex(FileImportError, "non-finite number"):
            parse_file(non_finite_path)

        expanded_path = self.write_parquet(
            "expanded.parquet", pa.table({"value": ["payload"]})
        )
        with patch("analytics_studio.file_import.MAX_PARQUET_UNCOMPRESSED_BYTES", 0):
            with self.assertRaisesRegex(FileImportError, "Parquet data limit"):
                parse_file(expanded_path)

        binary_path = self.write_parquet(
            "binary.parquet", pa.table({"value": [b"binary"]})
        )
        with self.assertRaisesRegex(FileImportError, "nested and binary types"):
            parse_file(binary_path)

    def test_parquet_source_row_column_and_cell_caps_are_enforced(self) -> None:
        path = self.write_parquet(
            "limits.parquet", pa.table({"left": [1, 2], "right": [3, 4]})
        )
        with patch("analytics_studio.file_import.MAX_SOURCE_BYTES", 1):
            with self.assertRaisesRegex(FileImportError, "import limit"):
                parse_file(path)
        with patch("analytics_studio.file_import.MAX_DATA_ROWS", 1):
            with self.assertRaisesRegex(FileImportError, "row import limit"):
                parse_file(path)
        with patch("analytics_studio.file_import.MAX_COLUMNS", 1):
            with self.assertRaisesRegex(FileImportError, "column import limit"):
                parse_file(path)
        cell_path = self.write_parquet(
            "cell-limit.parquet", pa.table({"value": list(range(101))})
        )
        with patch("analytics_studio.file_import.MAX_CELLS", 100):
            with self.assertRaisesRegex(FileImportError, "cell import limit"):
                parse_file(cell_path)

    def test_parquet_rejects_over_limit_converted_text(self) -> None:
        path = self.write_parquet(
            "text-limit.parquet", pa.table({"x": ["long payload"]})
        )
        with patch("analytics_studio.file_import.MAX_PARQUET_TEXT_BYTES", 5):
            with self.assertRaisesRegex(FileImportError, "Converted Parquet text"):
                parse_file(path)


if __name__ == "__main__":
    unittest.main()
