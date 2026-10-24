"""The function counts and name table in DAX_COMPATIBILITY_CONTRACT.md are generated from the code."""

from __future__ import annotations

import unittest

from analytics_studio import measures
from tools import sync_dax_contract


class ContractSyncTests(unittest.TestCase):
    def test_contract_is_up_to_date_with_the_evaluator(self) -> None:
        current = sync_dax_contract.CONTRACT.read_text(encoding="utf-8")
        self.assertEqual(
            sync_dax_contract.render(current), current,
            "run: PYTHONPATH=. python tools/sync_dax_contract.py",
        )

    def test_every_recognized_name_is_listed_exactly_once(self) -> None:
        listed = [name for _title, names in sync_dax_contract.families() for name in names]
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(set(listed), set(measures._FUNCTIONS))

    def test_no_stale_hand_typed_counts_remain(self) -> None:
        text = sync_dax_contract.CONTRACT.read_text(encoding="utf-8")
        self.assertNotIn("these 69 names", text)
        self.assertNotIn("69 names", text)
        self.assertNotIn("53-name", text)


if __name__ == "__main__":
    unittest.main()
