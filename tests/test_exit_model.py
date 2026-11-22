"""Unit tests for exit-test model generator, local build, and compare runner.

No guest VM connection required.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools import exit_check
from tools import exit_model


class TestExitModel(unittest.TestCase):
    def test_generator_determinism(self) -> None:
        """Two independent runs with the same seed generate identical rows."""
        data_a = exit_model.generate_data(exit_model.MODEL_SEED)
        data_b = exit_model.generate_data(exit_model.MODEL_SEED)
        self.assertEqual(data_a, data_b)

    def test_row_counts_and_key_ranges(self) -> None:
        """Row counts and primary/foreign key ranges conform exactly to spec."""
        data = exit_model.generate_data(exit_model.MODEL_SEED)

        # XT_Date: 2023-01-01 to 2025-12-31 = 1096 days (leap year in 2024: 365 + 366 + 365)
        date_rows = data["XT_Date"]
        self.assertEqual(len(date_rows), 1096)
        self.assertEqual(date_rows[0]["Date"], "2023-01-01")
        self.assertEqual(date_rows[-1]["Date"], "2025-12-31")

        # XT_Region: 5 rows, keys 1..5
        reg_rows = data["XT_Region"]
        self.assertEqual(len(reg_rows), 5)
        self.assertEqual({r["RegionKey"] for r in reg_rows}, set(range(1, 6)))

        # XT_Product: 60 rows, keys 1..60, 6 categories, 15 subcategories
        prod_rows = data["XT_Product"]
        self.assertEqual(len(prod_rows), 60)
        self.assertEqual({r["ProductKey"] for r in prod_rows}, set(range(1, 61)))
        cats = {r["Category"] for r in prod_rows}
        self.assertEqual(len(cats), 6)
        subcats = {r["Subcategory"] for r in prod_rows}
        self.assertEqual(len(subcats), 15)
        self.assertTrue(any(r["Color"] is None for r in prod_rows))

        # XT_Customer: 800 rows, keys 1..800, 4 segments
        cust_rows = data["XT_Customer"]
        self.assertEqual(len(cust_rows), 800)
        self.assertEqual({r["CustomerKey"] for r in cust_rows}, set(range(1, 801)))
        self.assertEqual(len({r["Segment"] for r in cust_rows}), 4)
        self.assertTrue(any(r["FirstOrderDate"] is None for r in cust_rows))

        # XT_CustomerRegion: each customer in 1-3 regions
        bridge_rows = data["XT_CustomerRegion"]
        cust_region_counts: dict[int, int] = {}
        for r in bridge_rows:
            cust_region_counts[r["CustomerKey"]] = cust_region_counts.get(r["CustomerKey"], 0) + 1
            self.assertIn(r["RegionKey"], set(range(1, 6)))
        self.assertEqual(len(cust_region_counts), 800)
        for ck, count in cust_region_counts.items():
            self.assertTrue(1 <= count <= 3, f"Customer {ck} has {count} regions")

        # XT_Sales: 12,000 rows
        sales_rows = data["XT_Sales"]
        self.assertEqual(len(sales_rows), 12000)
        unknown_prods = [r for r in sales_rows if r["ProductKey"] == 999]
        self.assertTrue(len(unknown_prods) > 0, "Expected ~1% unknown product rows")
        blank_custs = [r for r in sales_rows if r["CustomerKey"] is None]
        self.assertTrue(len(blank_custs) > 0, "Expected ~1% blank customer rows")
        blank_ships = [r for r in sales_rows if r["ShipDate"] is None]
        self.assertTrue(len(blank_ships) > 0, "Expected blank ship dates")

        # XT_Budget: 36 months * 6 categories = 216 rows
        budget_rows = data["XT_Budget"]
        self.assertEqual(len(budget_rows), 216)

    def test_relationship_list_well_formed(self) -> None:
        """Relationships in local_context match spec tables, columns, and cardinalities."""
        data = exit_model.generate_data(exit_model.MODEL_SEED)
        tables, rels = exit_model.local_context(data)
        table_ids = {t["id"] for t in tables}

        expected_ids = {
            "XT_rel_sales_date_order", "XT_rel_sales_date_ship", "XT_rel_sales_product",
            "XT_rel_sales_customer", "XT_rel_sales_region", "XT_rel_custreg_customer", "XT_rel_custreg_region",
        }
        self.assertEqual({r["id"] for r in rels}, expected_ids)

        for r in rels:
            self.assertIn(r["from_table_id"], table_ids)
            self.assertIn(r["to_table_id"], table_ids)
            self.assertIn(r["cardinality"], {"many_to_one", "one_to_one", "many_to_many", "one_to_many"})
            self.assertIsInstance(r["is_active"], bool)

        # Check ship date is inactive
        ship_rel = [r for r in rels if r["id"] == "XT_rel_sales_date_ship"][0]
        self.assertFalse(ship_rel["is_active"])

    def test_column_type_mappings(self) -> None:
        """Fixed decimal columns map to 'currency' and Discount maps to 'decimal_number'."""
        data = exit_model.generate_data(exit_model.MODEL_SEED)
        tables, _ = exit_model.local_context(data)
        table_map = {t["name"]: t["column_types"] for t in tables}

        # Fixed decimal columns map to currency
        self.assertEqual(table_map["XT_Product"]["ListPrice"], "currency")
        self.assertEqual(table_map["XT_Sales"]["UnitPrice"], "currency")
        self.assertEqual(table_map["XT_Sales"]["SalesAmount"], "currency")
        self.assertEqual(table_map["XT_Budget"]["BudgetAmount"], "currency")

        # Discount is double -> decimal_number
        self.assertEqual(table_map["XT_Sales"]["Discount"], "decimal_number")

    def test_local_aggregate_checks_equal_python(self) -> None:
        """Local evaluator produces aggregate values matching expected Python metrics."""
        data = exit_model.generate_data(exit_model.MODEL_SEED)
        res = exit_model.verify_local(data)
        self.assertTrue(res["all_match"], f"Local verification failed: {[r for r in res['results'] if not r['match']]}")

    def test_compare_counts_on_synthetic_pair(self) -> None:
        """exit_check.compare_results correctly tallies right, wrong, refused, crash and slowest items."""
        file_a_items = [
            {"id": "item1", "expr": "1+1", "powerbi": "2"},
            {"id": "item2", "expr": "2*2", "powerbi": "4"},
            {"id": "item3", "expr": "3*3", "powerbi": "9"},
            {"id": "item4", "expr": "4/0", "powerbi": "ERR:Division by zero"},
        ]
        file_b_items = [
            {"id": "item1", "expr": "1+1", "local": "2", "time_ms": 10.5},
            {"id": "item2", "expr": "2*2", "local": "5", "time_ms": 25.0},
            {"id": "item3", "expr": "3*3", "local": "LOCAL-CRASH:ValueError:boom", "time_ms": 5.0},
            {"id": "item4", "expr": "4/0", "local": "LOCAL-REJECT:DivideByZero", "time_ms": 1.2},
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            path_a = str(Path(tmp_dir) / "pbi.json")
            path_b = str(Path(tmp_dir) / "local.json")
            Path(path_a).write_text(json.dumps(file_a_items), encoding="utf-8")
            Path(path_b).write_text(json.dumps(file_b_items), encoding="utf-8")

            stats = exit_check.compare_results(path_a, path_b)
            self.assertEqual(stats["right"], 1)  # item1
            self.assertEqual(stats["wrong"], 1)  # item2
            self.assertEqual(stats["crash"], 1)  # item3
            self.assertEqual(stats["refused"], 0)  # item4 is LOCAL-REJECT vs Power BI ERR: -> both_error
            self.assertEqual(stats["both_error"], 1)  # item4
            self.assertEqual(len(stats["slowest_20"]), 4)
            self.assertEqual(stats["slowest_20"][0]["id"], "item2")
            self.assertEqual(stats["only_in_a_count"], 0)
            self.assertEqual(stats["only_in_b_count"], 0)

    def test_compare_counts_disjoint_ids(self) -> None:
        """exit_check.compare_results counts and lists ids present in only one file."""
        file_a_items = [
            {"id": "item1", "expr": "1+1", "powerbi": "2"},
            {"id": "item_only_a", "expr": "5+5", "powerbi": "10"},
        ]
        file_b_items = [
            {"id": "item1", "expr": "1+1", "local": "2", "time_ms": 1.0},
            {"id": "item_only_b", "expr": "6+6", "local": "12", "time_ms": 1.0},
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            path_a = str(Path(tmp_dir) / "pbi.json")
            path_b = str(Path(tmp_dir) / "local.json")
            Path(path_a).write_text(json.dumps(file_a_items), encoding="utf-8")
            Path(path_b).write_text(json.dumps(file_b_items), encoding="utf-8")

            stats = exit_check.compare_results(path_a, path_b)
            self.assertEqual(stats["right"], 1)
            self.assertEqual(stats["only_in_a_count"], 1)
            self.assertEqual(stats["only_in_b_count"], 1)
            self.assertEqual(stats["only_in_a"], ["item_only_a"])
            self.assertEqual(stats["only_in_b"], ["item_only_b"])

    def test_tmsl_shape_no_database_replace_and_xt_prefix(self) -> None:
        """TMSL commands never replace the database and all created/deleted objects start with XT_."""
        data = exit_model.generate_data(exit_model.MODEL_SEED)
        cmds = exit_model.tmsl_table_commands(data)
        self.assertGreater(len(cmds), 0)
        for cmd in cmds:
            self.assertIn("createOrReplace", cmd)
            cor = cmd["createOrReplace"]
            obj = cor["object"]
            # Must NOT be a bare database replace
            self.assertIn("table", obj)
            tbl_name = obj["table"]
            self.assertTrue(tbl_name.startswith("XT_"), f"Table {tbl_name} must start with XT_")
            self.assertEqual(cor["table"]["name"], tbl_name)

        # Check relationship specs all start with XT_
        for spec in exit_model.RELATIONSHIP_SPECS:
            rel_name = spec[0]
            self.assertTrue(rel_name.startswith("XT_"), f"Relationship {rel_name} must start with XT_")

    def test_mocked_install_failure_calls_drop(self) -> None:
        """A failure during install inside run_power_bi still invokes drop_guest_model."""
        from unittest.mock import patch

        dropped = False

        def mock_drop(port: str) -> None:
            nonlocal dropped
            dropped = True

        def mock_install(port: str, data: dict) -> None:
            raise RuntimeError("Simulated install failure midway")

        with patch("tools.exit_model.install_guest_model", side_effect=mock_install), \
             patch("tools.exit_model.drop_guest_model", side_effect=mock_drop):
            with self.assertRaises(RuntimeError):
                exit_check.run_power_bi([{"id": "1", "expr": "1"}], "12345")

        self.assertTrue(dropped, "drop_guest_model was not called after install failure")


if __name__ == "__main__":
    unittest.main()
