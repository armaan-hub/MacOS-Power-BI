"""Every answer saved from Power BI Desktop is replayed against the local engine on each test run.

``tools/parity_check.py`` owns the replay and the baseline of locked items (``tools/parity/baseline.json``).  A locked
item that stops matching, any difference from Power BI, or an engine crash fails the suite; items Power BI answers but
the engine still refuses are the work list in ``PARITY_LEDGER.md`` and do not fail it.  A difference listed in
``tools/parity/known_diffs.json`` with the app's recorded answer is a known-diff and does not fail it either; an unlisted difference,
a listed one whose answer changed, and a crash do.
"""

from __future__ import annotations

import unittest

from tools import parity_check


class ParityLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = parity_check.load_baseline()
        dax_rows = parity_check.replay_dax()
        table_rows, cls.digests, _notes = parity_check.replay_tables()
        cls.results = dax_rows + table_rows

    def test_every_battery_has_saved_power_bi_answers(self) -> None:
        self.assertEqual([r for r in self.results if r["status"] == "NOT-FROZEN"], [])

    def test_no_difference_from_power_bi_and_no_crash(self) -> None:
        bad = [f"{r['id']}: Power BI {r['powerbi'][:40]} vs app {r['ours'][:60]}" for r in self.results if r["status"] in {"DIFF", "CRASH"}]
        self.assertEqual(bad, [])

    def test_known_diffs_listed_rows_exist_and_are_never_locked(self) -> None:
        known = parity_check.load_known_diffs()
        ids = {r["id"] for r in self.results}
        self.assertEqual([i for i in known if i not in ids], [])
        self.assertEqual([i for i in known if i in set(self.baseline["locked"])], [])

    def test_locked_items_still_match(self) -> None:
        locked = set(self.baseline["locked"])
        regressions = [f"{r['id']} ({r['status']})" for r in self.results if r["id"] in locked and r["status"] not in {"match", "error-vs-refusal"}]
        self.assertEqual(regressions, [])

    def test_imported_tables_are_unchanged(self) -> None:
        for name, digest in self.digests.items():
            self.assertEqual(self.baseline.get("import_digests", {}).get(name, digest), digest, name)


if __name__ == "__main__":
    unittest.main()
