"""Task 175: IntelliSense lists qualified columns for a bare name."""

from __future__ import annotations

import unittest

from analytics_studio.dax_intellisense import complete

MODEL = {
    "home_table": "ZB_Cal",
    "tables": [
        {"name": "ZB_Cal", "columns": [
            {"name": "Date", "type": "date"},
            {"name": "Year", "type": "number"},
            {"name": "MonthNo", "type": "number"},
            {"name": "Day", "type": "number"},
        ]},
        {"name": "Sales Data", "columns": [
            {"name": "Quantity", "type": "number"},
            {"name": "Region", "type": "text"},
        ]},
        {"name": "Dates", "columns": [{"name": "When", "type": "date"}]},
    ],
    "measures": [
        {"name": "Total Sales", "table": "Sales Data", "type": "number"},
        {"name": "Day Count", "table": "ZB_Cal", "type": "number"},
    ],
}


def labels(items: list[dict]) -> list[str]:
    return [item["label"] for item in items]


class BareNameColumnTests(unittest.TestCase):
    def test_bare_prefix_lists_matching_columns_fully_qualified(self) -> None:
        items = complete("Qua", 3, MODEL)
        self.assertIn("'Sales Data'[Quantity]", labels(items))
        by_label = {item["label"]: item for item in items}
        self.assertEqual(by_label["'Sales Data'[Quantity]"]["insertText"], "'Sales Data'[Quantity]")

    def test_bare_prefix_matches_columns_of_every_table(self) -> None:
        self.assertIn("Dates[When]", labels(complete("whe", 3, MODEL)))

    def test_empty_prefix_is_unchanged(self) -> None:
        self.assertEqual(complete("", 0, MODEL), [])


class TableBracketMeasureTests(unittest.TestCase):
    def test_table_without_measures_lists_only_columns(self) -> None:
        self.assertEqual(labels(complete("Dates[", 6, MODEL)), ["When"])


if __name__ == "__main__":
    unittest.main()
