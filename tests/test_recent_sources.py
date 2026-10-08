"""Tests for user-level recent local data-source history."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QSettings

from analytics_studio.recent_sources import RecentSourcesStore, SETTINGS_KEY


class RecentSourcesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.settings_path = self.root / "settings.ini"
        self.settings = QSettings(str(self.settings_path), QSettings.Format.IniFormat)
        self.store = RecentSourcesStore(self.settings, limit=3)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_add_normalizes_path_and_exposes_source_metadata(self) -> None:
        source_path = self.root / "sales.csv"
        source_path.write_text("name,amount\nAda,12\n", encoding="utf-8")
        relative_path = Path(os.path.relpath(source_path, Path.cwd()))

        self.store.add(relative_path, "csv", {
            "delimiter": ";", "encoding": "utf-8", "has_header": False,
        })

        [source] = self.store.sources
        self.assertEqual(source.path, str(source_path.resolve()))
        self.assertEqual(source.kind, "csv")
        self.assertEqual(source.parser_options, {
            "delimiter": ";", "encoding": "utf-8", "has_header": False,
        })
        self.assertEqual(source.display_name, "sales.csv")
        self.assertTrue(source.exists)

    def test_add_deduplicates_and_moves_existing_path_to_front(self) -> None:
        first = self.root / "first.csv"
        second = self.root / "second.json"
        first.write_text("id\n1\n", encoding="utf-8")
        second.write_text('[{"id":1}]', encoding="utf-8")

        self.store.add(first, "csv")
        self.store.add(second, "json")
        self.store.add(first.parent / "." / first.name, "csv", {
            "delimiter": ",", "encoding": "utf-8-sig", "has_header": True,
        })

        self.assertEqual([source.path for source in self.store.sources], [
            str(first.resolve()), str(second.resolve()),
        ])

    def test_case_aliases_deduplicate_on_case_insensitive_filesystems(self) -> None:
        source_path = self.root / "Sales.csv"
        case_alias = self.root / "sales.csv"
        source_path.write_text("id\n1\n", encoding="utf-8")
        if not case_alias.exists() or not os.path.samefile(source_path, case_alias):
            self.skipTest("This filesystem treats case-variant paths as distinct.")

        self.store.add(source_path, "csv")
        self.store.add(case_alias, "csv")

        self.assertEqual(len(self.store.sources), 1)

    def test_add_is_bounded_and_options_follow_the_most_recent_import(self) -> None:
        paths = [self.root / f"{index}.csv" for index in range(4)]
        for path in paths:
            path.write_text("id\n1\n", encoding="utf-8")
            self.store.add(path, "csv")

        self.store.add(paths[0], "csv", {
            "delimiter": ";", "encoding": "utf-8", "has_header": False,
        })

        sources = self.store.sources
        self.assertEqual(len(sources), 3)
        self.assertEqual(sources[0].path, str(paths[0].resolve()))
        self.assertEqual(sources[0].parser_options, {
            "delimiter": ";", "encoding": "utf-8", "has_header": False,
        })
        self.assertNotIn(str(paths[1].resolve()), [source.path for source in sources])

    def test_missing_paths_remain_in_history_with_exists_false(self) -> None:
        source_path = self.root / "records.json"
        source_path.write_text('[{"id":1}]', encoding="utf-8")
        self.store.add(source_path, "json")
        source_path.unlink()

        [source] = self.store.sources

        self.assertEqual(source.path, str(source_path.resolve()))
        self.assertFalse(source.exists)

    def test_entries_persist_across_store_instances(self) -> None:
        source_path = self.root / "book.xlsx"
        source_path.write_bytes(b"workbook")
        self.store.add(source_path, "excel", {
            "sheet_name": "Data", "header_row": 2,
        })

        reopened = RecentSourcesStore(
            QSettings(str(self.settings_path), QSettings.Format.IniFormat), limit=3,
        )

        [source] = reopened.sources
        self.assertEqual(source.path, str(source_path.resolve()))
        self.assertEqual(source.kind, "excel")
        self.assertEqual(source.parser_options, {"sheet_name": "Data", "header_row": 2})

    def test_unsupported_kind_and_invalid_options_are_rejected(self) -> None:
        source_path = self.root / "records.csv"
        source_path.write_text("id\n1\n", encoding="utf-8")

        with self.assertRaises(ValueError):
            self.store.add(source_path, "service")
        with self.assertRaises(ValueError):
            self.store.add(source_path, "csv", {"delimiter": "::"})

        self.assertEqual(self.store.sources, [])

    def test_malformed_settings_records_are_ignored(self) -> None:
        self.settings.setValue(SETTINGS_KEY, json.dumps([{
            "path": str(self.root / "file.csv"),
            "kind": [],
            "display_name": "file.csv",
            "parser_options": {},
        }]))

        self.assertEqual(self.store.sources, [])


if __name__ == "__main__":
    unittest.main()
