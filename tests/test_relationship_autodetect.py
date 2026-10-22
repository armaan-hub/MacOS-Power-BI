"""Regression checks for the REA-guided relationship suggestion port."""

from __future__ import annotations

import unittest

from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.relationships import detect_relationship_candidates


def make_table(
    table_id: str,
    name: str,
    columns: dict[str, list[object]],
    *,
    column_types: dict[str, str] | None = None,
    **metadata,
) -> dict:
    headers = list(columns)
    row_count = len(next(iter(columns.values()), []))
    if any(len(values) != row_count for values in columns.values()):
        raise ValueError("All test columns must have the same row count.")
    return {
        "id": table_id,
        "name": name,
        "headers": headers,
        "rows": [
            {header: columns[header][row_index] for header in headers}
            for row_index in range(row_count)
        ],
        "column_types": column_types or {header: "text" for header in headers},
        **metadata,
    }


def saved_relationship(
    from_id: str,
    to_id: str,
    *,
    cardinality: str = "many_to_one",
    direction: str = "single",
    active: bool = True,
) -> dict:
    return {
        "relationship_version": 1,
        "id": f"{from_id}-{to_id}",
        "from": f"{from_id}[Key]",
        "to": f"{to_id}[Key]",
        "from_table_id": from_id,
        "from_column": "Key",
        "to_table_id": to_id,
        "to_column": "Key",
        "cardinality": cardinality,
        "cross_filter_direction": direction,
        "is_active": active,
    }


def summarize(proposals: list[dict]) -> list[tuple]:
    return [
        (
            item["from_table_id"],
            item["from_column"],
            item["to_table_id"],
            item["to_column"],
            item["cardinality"],
            item["cross_filter_direction"],
            item["is_active"],
        )
        for item in proposals
    ]


class RelationshipAutodetectTests(unittest.TestCase):
    def test_detects_candidate_to_key_with_native_cardinality_defaults(self) -> None:
        dimension = make_table(
            "customers",
            "Customers",
            {"CustomerID": ["1", "2"], "CustomerName": ["Ada", "Sam"]},
        )
        facts = make_table(
            "orders",
            "Orders",
            {"CustomerID": ["1", "1", "2"], "Amount": ["5", "8", "3"]},
        )

        proposals = detect_relationship_candidates([facts, dimension], [])

        self.assertEqual(
            summarize(proposals),
            [("orders", "CustomerID", "customers", "CustomerID", "many_to_one", "single", True)],
        )

    def test_unique_pair_defaults_to_one_to_one_and_both(self) -> None:
        left = make_table("left", "Left", {"RegionID": ["1", "2"], "Name": ["A", "B"]})
        right = make_table("right", "Right", {"RegionID": ["3", "4"], "Value": ["C", "D"]})

        proposals = detect_relationship_candidates([left, right], [])

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["cardinality"], "one_to_one")
        self.assertEqual(proposals[0]["cross_filter_direction"], "both")
        self.assertTrue(proposals[0]["is_active"])

    def test_uses_name_match_without_requiring_overlapping_values(self) -> None:
        dimension = make_table("d", "Dimension", {"ProductCode": ["A", "B"], "Label": ["x", "y"]})
        facts = make_table("f", "Facts", {"ProductCode": ["X", "X", "Y"], "Amount": ["1", "2", "3"]})

        proposals = detect_relationship_candidates([dimension, facts], [])

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["from_table_id"], "f")
        self.assertEqual(proposals[0]["to_table_id"], "d")

    def test_only_matching_native_relationship_key_types_are_grouped(self) -> None:
        left = make_table(
            "left",
            "Left",
            {
                "MismatchedNumeric": [1, 2],
                "BooleanCode": [True, False],
                "DateCode": ["2026-01-01", "2026-01-02"],
                "TimeCode": ["08:00", "09:00"],
                "AnyCode": ["1", "2"],
                "LeftOnly": ["a", "b"],
            },
            column_types={
                "MismatchedNumeric": "whole_number",
                "BooleanCode": "boolean",
                "DateCode": "date",
                "TimeCode": "time",
                "AnyCode": "any",
                "LeftOnly": "text",
            },
        )
        right = make_table(
            "right",
            "Right",
            {
                "MismatchedNumeric": [1.0, 2.0],
                "BooleanCode": [True, False],
                "DateCode": ["2026-01-01", "2026-01-02"],
                "TimeCode": ["08:00", "09:00"],
                "AnyCode": ["1", "2"],
                "RightOnly": ["c", "d"],
            },
            column_types={
                "MismatchedNumeric": "decimal_number",
                "BooleanCode": "boolean",
                "DateCode": "date",
                "TimeCode": "time",
                "AnyCode": "any",
                "RightOnly": "text",
            },
        )

        self.assertEqual(detect_relationship_candidates([left, right], []), [])

    def test_normalized_id_fallback_matches_table_name_but_literal_id_pair_is_ignored(self) -> None:
        customers = make_table("customers", "Customers", {"ID": ["1", "2"], "Name": ["A", "B"]})
        orders = make_table("orders", "Orders", {"CustomersID": ["1", "1"], "Amount": ["4", "5"]})

        proposals = detect_relationship_candidates([customers, orders], [])

        self.assertEqual(len(proposals), 1)
        self.assertEqual(
            (proposals[0]["from_table_id"], proposals[0]["from_column"], proposals[0]["to_table_id"], proposals[0]["to_column"]),
            ("orders", "CustomersID", "customers", "ID"),
        )
        id_only_left = make_table("one", "One", {"ID": ["1", "2"], "Other": ["a", "b"]})
        id_only_right = make_table("two", "Two", {"ID": ["3", "4"], "Other": ["c", "d"]})
        self.assertEqual(detect_relationship_candidates([id_only_left, id_only_right], []), [])

    def test_normalized_pass_removes_digits_comments_and_noise_from_qualified_names(self) -> None:
        dimension = make_table(
            "dimension",
            "Dimension",
            {"CustomerID": ["1", "2"], "Label": ["a", "b"]},
        )
        facts = make_table(
            "facts",
            "Facts",
            {"Sales.Customer_09Code (legacy)": ["1", "1"], "Amount": ["3", "4"]},
        )

        proposals = detect_relationship_candidates([dimension, facts], [])

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["from_column"], "Sales.Customer_09Code (legacy)")
        self.assertEqual(proposals[0]["to_column"], "CustomerID")

    def test_excludes_calculated_grouped_and_identical_schema_columns(self) -> None:
        left = make_table(
            "left",
            "Left",
            {"AccountID": ["1", "2"], "Shared": ["a", "b"]},
            calculated_columns=["AccountID"],
        )
        right = make_table("right", "Right", {"AccountID": ["1", "2"], "Shared": ["c", "d"]})
        self.assertEqual(detect_relationship_candidates([left, right], []), [])

        left["calculated_columns"] = []
        left["group_by_columns"] = {"AccountID": ["Shared"]}
        self.assertEqual(detect_relationship_candidates([left, right], []), [])

        same_schema_left = make_table("a", "A", {"AccountID": ["1", "2"], "Name": ["a", "b"]})
        same_schema_right = make_table("b", "B", {"AccountID": ["3", "4"], "Name": ["c", "d"]})
        self.assertEqual(detect_relationship_candidates([same_schema_left, same_schema_right], []), [])

    def test_explicit_table_key_is_prioritized_but_relationship_side_still_needs_valid_cardinality(self) -> None:
        keyed = make_table(
            "keyed",
            "Keyed",
            {"CustomerID": ["1", "1"], "Local": ["a", "b"]},
            key_column="CustomerID",
        )
        other = make_table("other", "Other", {"CustomerID": ["1", "2"], "Other": ["c", "d"]})

        proposals = detect_relationship_candidates([keyed, other], [])

        self.assertEqual(len(proposals), 1)
        self.assertEqual(
            (proposals[0]["from_table_id"], proposals[0]["to_table_id"], proposals[0]["cardinality"]),
            ("keyed", "other", "many_to_one"),
        )

        invalid_one_side = make_table(
            "invalid",
            "Invalid",
            {"CustomerID": ["1", "1"], "Local": ["x", "y"]},
            key_column="CustomerID",
        )
        invalid_other = make_table(
            "invalid-other",
            "Invalid Other",
            {"CustomerID": ["2", "2"], "Other": ["x", "y"]},
        )
        self.assertEqual(detect_relationship_candidates([invalid_one_side, invalid_other], []), [])

    def test_blank_profile_disqualifies_one_side_but_can_be_many_side(self) -> None:
        dimension = make_table(
            "dimension",
            "Dimension",
            {"RegionID": ["   ", "north"], "Label": ["blank", "north"]},
        )
        facts = make_table(
            "facts",
            "Facts",
            {"RegionID": ["north", "south", "east"], "Amount": ["1", "2", "3"]},
        )

        proposals = detect_relationship_candidates([dimension, facts], [])

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["from_table_id"], "dimension")
        self.assertEqual(proposals[0]["to_table_id"], "facts")
        self.assertEqual(proposals[0]["cardinality"], "many_to_one")

    def test_empty_tables_do_not_enter_key_groups(self) -> None:
        empty = make_table("empty", "Empty", {"CustomerID": [], "Note": []})
        facts = make_table("facts", "Facts", {"CustomerID": ["1", "1"], "Amount": ["2", "3"]})
        dimension = make_table("dimension", "Dimension", {"CustomerID": ["1", "2"], "Name": ["a", "b"]})

        proposals = detect_relationship_candidates([empty, facts, dimension], [])

        self.assertEqual(len(proposals), 1)
        self.assertEqual((proposals[0]["from_table_id"], proposals[0]["to_table_id"]), ("facts", "dimension"))

    def test_per_table_key_cap_keeps_only_first_29_columns(self) -> None:
        bad = PowerQueryCellError("DataFormat.Error", "bad key", "bad", "text", row=0)
        left_columns = {f"Customer{index}ID": [bad, bad] for index in range(1, 30)}
        left_columns["Customer30ID"] = ["1", "2"]
        left_columns["Local"] = ["a", "b"]
        right = make_table("right", "Right", {"CustomerID": ["1", "2"], "Other": ["c", "d"]})
        left = make_table("left", "Left", left_columns)

        # Only the normalized key pass can match Customer[1..30]ID to CustomerID.
        # The native >=30 gate drops the 30th matching column for the table.
        self.assertEqual(detect_relationship_candidates([left, right], []), [])

    def test_key_group_cap_keeps_only_first_30_groups_for_table_signature(self) -> None:
        bad = PowerQueryCellError("DataFormat.Error", "bad key", "bad", "text", row=0)
        left_columns = {f"Field{index:02d}": [bad, bad] for index in range(1, 30)}
        left_columns["Field30"] = ["1", "2"]
        left_columns["Field31"] = ["3", "4"]
        left_columns["Local"] = ["a", "b"]
        right_columns = {f"Field{index:02d}": ["1", "2"] for index in range(1, 32)}
        right_columns["Other"] = ["c", "d"]

        proposals = detect_relationship_candidates(
            [make_table("left", "Left", left_columns), make_table("right", "Right", right_columns)],
            [],
        )

        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["from_column"], "Field30")

    def test_existing_direct_table_pair_suppresses_another_column_match(self) -> None:
        left = make_table("left", "Left", {"CustomerID": ["1", "2"], "Name": ["a", "b"]})
        right = make_table("right", "Right", {"CustomerID": ["1", "1"], "Other": ["c", "d"]})

        proposals = detect_relationship_candidates(
            [left, right], [saved_relationship("left", "right", active=False)]
        )

        self.assertEqual(proposals, [])

    def test_ambiguous_triangle_is_returned_as_inactive_review_suggestion(self) -> None:
        a = make_table("a", "A", {"AccountID": ["1", "2"], "AExtra": ["a", "b"]})
        b = make_table("b", "B", {"AccountID": ["1", "1"], "BExtra": ["c", "d"]})
        c = make_table("c", "C", {"AccountID": ["1", "1"], "CExtra": ["e", "f"]})

        proposals = detect_relationship_candidates(
            [a, b, c],
            [saved_relationship("b", "a"), saved_relationship("c", "b")],
        )

        self.assertEqual(len(proposals), 1)
        self.assertEqual((proposals[0]["from_table_id"], proposals[0]["to_table_id"]), ("c", "a"))
        self.assertFalse(proposals[0]["is_active"])

    def test_default_retry_order_can_reverse_cardinality_and_keep_both(self) -> None:
        a = make_table("a", "A", {"CustomerID": ["1", "2"], "AExtra": ["a", "b"]})
        b = make_table("b", "B", {"CustomerID": ["3", "4"], "BExtra": ["c", "d"]})
        c = make_table("c", "C", {"CExtra": ["e", "f"]})
        d = make_table("d", "D", {"DExtra": ["g", "h"]})
        relationships = [
            saved_relationship("c", "b", cardinality="one_to_many", direction="single"),
            saved_relationship("a", "d", cardinality="many_to_one", direction="single"),
            saved_relationship("c", "d", cardinality="one_to_many", direction="single"),
        ]

        proposals = detect_relationship_candidates([a, b, c, d], relationships)
        candidate = next(
            item for item in proposals
            if {item["from_table_id"], item["to_table_id"]} == {"a", "b"}
        )

        self.assertEqual(
            (candidate["from_table_id"], candidate["to_table_id"], candidate["cardinality"], candidate["cross_filter_direction"], candidate["is_active"]),
            ("a", "b", "one_to_many", "both", True),
        )

    def test_scoped_filter_selects_pairs_before_graph_retry(self) -> None:
        tables = [
            make_table("a", "A", {"CustomerID": ["1", "2"], "AExtra": ["a", "b"]}),
            make_table("b", "B", {"CustomerID": ["3", "4"], "BExtra": ["c", "d"]}),
            make_table("c", "C", {"CustomerID": ["5", "6"], "CExtra": ["e", "f"]}),
        ]

        global_suggestions = detect_relationship_candidates(tables, [])
        scoped_suggestions = detect_relationship_candidates(tables, [], {"b", "c"})

        direct_global = next(
            item for item in global_suggestions
            if {item["from_table_id"], item["to_table_id"]} == {"b", "c"}
        )
        self.assertFalse(direct_global["is_active"])
        self.assertEqual(len(scoped_suggestions), 1)
        self.assertEqual(
            (scoped_suggestions[0]["from_table_id"], scoped_suggestions[0]["to_table_id"], scoped_suggestions[0]["cardinality"], scoped_suggestions[0]["is_active"]),
            ("c", "b", "one_to_one", True),
        )

    def test_scoped_suggestions_follow_shortest_connection_paths_and_stable_ties(self) -> None:
        a = make_table("a", "A", {"CustomerID": ["1", "2"], "AExtra": ["a", "b"]})
        b = make_table(
            "b",
            "B",
            {"CustomerID": ["1", "1"], "OrderID": ["10", "11"]},
        )
        c = make_table("c", "C", {"OrderID": ["10", "11"], "CExtra": ["c", "d"]})
        unrelated_left = make_table("x", "X", {"ProductCode": ["1", "2"], "XExtra": ["x", "y"]})
        unrelated_right = make_table("y", "Y", {"ProductCode": ["3", "4"], "YExtra": ["p", "q"]})

        proposals = detect_relationship_candidates(
            [a, b, c, unrelated_left, unrelated_right], [], {"a", "c"}
        )

        self.assertEqual(
            [(item["from_table_id"], item["to_table_id"]) for item in proposals],
            [("b", "a"), ("c", "b")],
        )

    def test_one_table_scope_returns_no_relationship_proposals(self) -> None:
        left = make_table("left", "Left", {"CustomerID": ["1", "2"], "Name": ["a", "b"]})
        right = make_table("right", "Right", {"CustomerID": ["1", "1"], "Other": ["c", "d"]})

        self.assertEqual(detect_relationship_candidates([left, right], [], {"left"}), [])


if __name__ == "__main__":
    unittest.main()
