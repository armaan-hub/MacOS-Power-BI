"""Every answer saved from Power BI Desktop is replayed against the local engine on each test run.

``tools/parity_check.py`` owns the replay and the baseline of locked items (``tools/parity/baseline.json``).  A locked
item that stops matching, any difference from Power BI, or an engine crash fails the suite; items Power BI answers but
the engine still refuses are the work list in ``PARITY_LEDGER.md`` and do not fail it.
"""

from __future__ import annotations

import json
import unittest

from tools import parity_check


class ParityLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = json.loads(parity_check.BASELINE.read_text())
        dax_rows = parity_check.replay_dax()
        table_rows, cls.digests, _notes = parity_check.replay_tables()
        cls.results = dax_rows + table_rows

    def test_every_battery_has_saved_power_bi_answers(self) -> None:
        self.assertEqual([r for r in self.results if r["status"] == "NOT-FROZEN"], [])

    def test_no_difference_from_power_bi_and_no_crash(self) -> None:
        bad = [f"{r['id']}: Power BI {r['powerbi'][:40]} vs app {r['ours'][:60]}" for r in self.results if r["status"] in {"DIFF", "CRASH"}]
        self.assertEqual(bad, [])

    def test_locked_items_still_match(self) -> None:
        locked = set(self.baseline["locked"])
        regressions = [f"{r['id']} ({r['status']})" for r in self.results if r["id"] in locked and r["status"] != "match"]
        self.assertEqual(regressions, [])

    def test_imported_tables_are_unchanged(self) -> None:
        for name, digest in self.digests.items():
            self.assertEqual(self.baseline.get("import_digests", {}).get(name, digest), digest, name)


if __name__ == "__main__":
    unittest.main()
