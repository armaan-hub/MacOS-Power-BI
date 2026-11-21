"""A saved Power BI answer may name its own Facts table; Power BI errors answered by an app refusal are counted on their own."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import parity_check


def _battery(items: list[dict], tables: dict[str, list[list[str]]]) -> dict:
    return {"powerbi_version": "test", "frozen": "2000-01-01", "facts_tables": tables, "items": items}


class FactsPerItemTests(unittest.TestCase):
    def _replay(self, battery: dict) -> list[dict]:
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "dax_battery_hunt_tiny.json").write_text(json.dumps(battery))
            with mock.patch.object(parity_check, "PARITY", Path(folder)), \
                    mock.patch.object(parity_check, "DAX_BATTERIES", ["dax_battery_hunt_tiny"]):
                return parity_check.replay_dax()

    def test_item_with_a_facts_table_is_evaluated_on_that_table(self) -> None:
        tiny = [["1", "2", "East", ""], ["2", "3", "West", "Paid"]]
        rows = self._replay(_battery([
            {"expr": "SUM(Facts[Sales])", "powerbi": "3", "facts": "t"},
            {"expr": "COUNTROWS(Facts)", "powerbi": "2", "facts": "t"},
            {"expr": "SUM(Facts[Quantity])", "powerbi": "5", "facts": "t"},
        ], {"t": tiny}))
        self.assertEqual([r["ours"] for r in rows], ["3", "2", "5"])
        self.assertEqual({r["status"] for r in rows}, {"match"})

    def test_item_without_facts_uses_the_default_table(self) -> None:
        rows = self._replay(_battery([{"expr": "SUM(Facts[Sales])", "powerbi": "31.5"}], {}))
        self.assertEqual(rows[0]["ours"], "31.5")
        self.assertEqual(rows[0]["status"], "match")

    def test_same_expression_on_two_tables_gets_two_ids(self) -> None:
        tables = {"a": [["1", "1", "East", ""]], "b": [["4", "1", "East", ""], ["5", "1", "East", ""]]}
        rows = self._replay(_battery([
            {"expr": "SUM(Facts[Sales])", "powerbi": "1", "facts": "a"},
            {"expr": "SUM(Facts[Sales])", "powerbi": "9", "facts": "b"},
        ], tables))
        self.assertEqual([r["status"] for r in rows], ["match", "match"])
        self.assertEqual(len({r["id"] for r in rows}), 2)

    def test_a_wrong_answer_on_a_facts_table_is_a_difference(self) -> None:
        rows = self._replay(_battery([{"expr": "SUM(Facts[Sales])", "powerbi": "99", "facts": "t"}], {"t": [["1", "1", "East", ""]]}))
        self.assertEqual(rows[0]["status"], "DIFF")


class StatusTests(unittest.TestCase):
    def test_power_bi_error_and_app_refusal_is_its_own_status(self) -> None:
        self.assertEqual(parity_check.status('ERR:Exception calling "Read"', "LOCAL-REJECT:Cannot convert"), "error-vs-refusal")

    def test_other_statuses_are_unchanged(self) -> None:
        self.assertEqual(parity_check.status("1", "1"), "match")
        self.assertEqual(parity_check.status("1", "LOCAL-REJECT:not modelled"), "gap-reject")
        self.assertEqual(parity_check.status("1", "2"), "DIFF")
        self.assertEqual(parity_check.status("ERR:boom", "5"), "DIFF")
        self.assertEqual(parity_check.status("1", "LOCAL-CRASH:ValueError:x"), "CRASH")

    def test_ledger_shows_error_vs_refusal_in_its_own_column(self) -> None:
        results = [
            {"group": "g", "expr": "a", "powerbi": "ERR:x", "ours": "LOCAL-REJECT:y", "status": "error-vs-refusal", "id": "g:a"},
            {"group": "g", "expr": "b", "powerbi": "1", "ours": "1", "status": "match", "id": "g:b"},
        ]
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder) / "PARITY_LEDGER.md"
            with mock.patch.object(parity_check, "LEDGER", ledger):
                parity_check.write_ledger(results, {"locked": ["g:a", "g:b"]}, [], [])
            text = ledger.read_text()
        self.assertIn("| Error vs refusal |", text)
        self.assertIn("| g | 1 | 0 | 1 | 0 | 0 | 0 |", text)


if __name__ == "__main__":
    unittest.main()
