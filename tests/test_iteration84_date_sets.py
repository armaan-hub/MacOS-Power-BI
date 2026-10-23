"""Iteration 84, date-set functions (FIRSTDATE, LASTDATE, STARTOF*, ENDOF*, NEXT*, PREVIOUS*, OPENING/CLOSINGBALANCE*, FIRST/LASTNONBLANK).

tests/fixtures_iter84_date_sets.json holds the live Power BI Desktop 2.157.879.0 answers measured by Thinker A on the Critic-3 models
(ZO orphan/blank keys, ZB bidirectional star, ZS snowflake): [model, expression, power bi answer, cluster].

C01 FIRSTDATE/LASTDATE/STARTOF*/ENDOF*   C04 OPENING/CLOSINGBALANCE*   C05 NEXT*/PREVIOUS* (table, nested, bare)
C07 date function on a fact date column   C08 FIRST/LASTNONBLANK(+VALUE)   C11 date overflow saturates at 12/31/9999 23:59:59
"""
from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

from tests.critic3_models import ours_for
from tools.parity_check import status

ITEMS = json.loads((Path(__file__).parent / "fixtures_iter84_date_sets.json").read_text())["items"]


def failures(cluster: str | None = None) -> list[tuple[str, str, str, str, str]]:
    out = []
    for model, expression, powerbi, tag in ITEMS:
        if cluster is not None and tag != cluster:
            continue
        answer = ours_for(model, expression)
        state = status(powerbi, answer)
        if state != "match":
            out.append((tag, model, expression, powerbi, answer, state))
    return out


class SavedPowerBiAnswers(unittest.TestCase):
    def check(self, cluster: str) -> None:
        bad = failures(cluster)
        total = sum(1 for item in ITEMS if item[3] == cluster)
        shown = "\n".join(f"{m} {e}\n   power bi: {p}\n   ours: {a[:100]} [{s}]" for _t, m, e, p, a, s in bad[:5])
        self.assertEqual([], bad, f"{cluster}: {len(bad)} of {total} differ from Power BI ({dict(Counter(b[5] for b in bad))})\n{shown}")

    def test_c01_first_last_start_end(self) -> None:
        self.check("C01")

    def test_c04_opening_closing_balances(self) -> None:
        self.check("C04")

    def test_c05_next_previous(self) -> None:
        self.check("C05")

    def test_c07_fact_date_columns(self) -> None:
        self.check("C07")

    def test_c08_first_last_nonblank(self) -> None:
        self.check("C08")

    def test_c11_date_overflow_saturates(self) -> None:
        self.check("C11")


if __name__ == "__main__":
    unittest.main()
