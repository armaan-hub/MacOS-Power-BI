"""Iteration 84, Testing agent: the 70 expressions where the local engine answered differently from live Power BI Desktop.

Every row of tests/fixtures_testing84.json with status DIFF (and the fresh probes of the fix agent in tests/fixtures_testing84_fresh.json)
must now either match the saved Power BI answer or be refused.  A wrong answer is worse than a refusal.  Saved Power BI answers are never edited."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.critic3_models import ours_for
from tools.parity_check import status

HERE = Path(__file__).parent


def load(name: str, key: str = "items", wanted: tuple[str, ...] | None = None) -> list[list]:
    path = HERE / name
    if not path.exists():
        return []
    items = json.loads(path.read_text())[key]
    return [r for r in items if wanted is None or r[4] in wanted]


class TestingAgentDiffs(unittest.TestCase):
    def check(self, items: list[list]) -> None:
        bad = []
        for model, expr, powerbi, _old, _status in items:
            ours = ours_for(model, expr)
            if status(powerbi, ours) not in ("match", "gap-reject"):
                bad.append((model, expr, powerbi[:80], ours[:80]))
        self.assertEqual([], bad)

    def test_the_seventy_diff_rows_are_match_or_refused(self) -> None:
        items = load("fixtures_testing84.json", wanted=("DIFF",))
        self.assertEqual(70, len(items))
        self.check(items)

    def test_the_minimal_reproducers_are_match_or_refused(self) -> None:
        self.check(load("fixtures_testing84.json", "reproducers"))

    def test_fresh_probes_have_no_wrong_answer(self) -> None:
        self.check(load("fixtures_testing84_fresh.json"))


if __name__ == "__main__":
    unittest.main()
