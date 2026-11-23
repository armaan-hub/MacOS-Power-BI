"""propagate_relationship_filters: filtered tables start from their filter rows, results are fresh lists."""

from __future__ import annotations

import unittest

from analytics_studio.relationships import propagate_relationship_filters


def _table(table_id: str, rows: list[dict], **extra) -> dict:
    return {"id": table_id, "name": table_id.upper(), "headers": ["k", "v"], "rows": rows,
            "column_types": {"k": "text", "v": "text"}, **extra}


def _link() -> dict:
    return {"relationship_version": 1, "id": "r", "from": "k", "to": "k", "from_table_id": "f", "from_column": "k",
            "to_table_id": "d", "to_column": "k", "cardinality": "many_to_one", "is_active": True,
            "cross_filter_direction": "single"}


class FilterRowsStartTests(unittest.TestCase):
    def test_filtered_table_returns_a_copy_of_its_filter_rows(self) -> None:
        rows = [{"k": str(i), "v": "x"} for i in range(5)]
        filter_rows = rows[1:3]
        table = _table("f", rows, filter_rows=filter_rows)
        result = propagate_relationship_filters([table], [], {"f"})
        self.assertEqual(result["f"], filter_rows)
        self.assertIsNot(result["f"], filter_rows)
        self.assertIsNot(result["f"], rows)
        result["f"].append({"k": "z"})
        self.assertEqual(len(filter_rows), 2)
        self.assertEqual(len(rows), 5)

    def test_unfiltered_table_returns_a_copy_of_all_rows(self) -> None:
        rows = [{"k": "1", "v": "x"}, {"k": "2", "v": "y"}]
        result = propagate_relationship_filters([_table("f", rows)], [], set())
        self.assertEqual(result["f"], rows)
        self.assertIsNot(result["f"], rows)

    def test_filter_rows_of_a_table_that_is_not_a_filter_root_are_ignored(self) -> None:
        rows = [{"k": "1", "v": "x"}, {"k": "2", "v": "y"}]
        table = _table("f", rows, filter_rows=rows[:1])
        result = propagate_relationship_filters([table], [], set())
        self.assertEqual(result["f"], rows)

    def test_filter_reaches_the_related_table(self) -> None:
        facts = [{"k": "a", "v": "1"}, {"k": "b", "v": "2"}, {"k": "c", "v": "3"}]
        dim = [{"k": "a", "v": "A"}, {"k": "b", "v": "B"}, {"k": "c", "v": "C"}]
        tables = [_table("f", facts), _table("d", dim, filter_rows=dim[:1])]
        result = propagate_relationship_filters(tables, [_link()], {"d"})
        self.assertEqual(result["d"], dim[:1])
        self.assertEqual(result["f"], facts[:1])


if __name__ == "__main__":
    unittest.main()
