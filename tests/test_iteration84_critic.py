"""Iteration 84, Critic findings: every row of tests/fixtures_critic84.json (the 1,187 expressions where the local engine answered differently
from live Power BI Desktop) must now either match Power BI or be refused (LOCAL-REJECT).  A wrong answer is worse than a refusal.

tests/fixtures_critic84_fresh.json holds new live probes written for the fixes (never in any other fixture): same rule."""
from __future__ import annotations

import json
import re
import unittest
from collections import Counter
from datetime import date
from pathlib import Path

from tests.critic3_models import ours_for
from tools.parity_check import status

HERE = Path(__file__).parent
ROWS = json.loads((HERE / "fixtures_critic84.json").read_text())
FRESH = json.loads((HERE / "fixtures_critic84_fresh.json").read_text()) if (HERE / "fixtures_critic84_fresh.json").exists() else []


CLOCK = re.compile(r"\b(?:TODAY|NOW|UTCTODAY|UTCNOW)\s*\(", re.I)


def clock_dependent(row: dict) -> bool:
    """A saved Power BI value that reads the clock is only right on the day it was captured (the rows were captured on different days),
    so its value cannot be replayed later; an error answer does not depend on the day and stays compared."""
    return bool(CLOCK.search(row["expr"])) and not row["powerbi"].startswith("ERR")


def wrong_answers(rows: list[dict]) -> list[tuple[str, str, str, str, str]]:
    out = []
    for row in rows:
        if clock_dependent(row):
            continue
        answer = ours_for(row["model"], row["expr"])
        state = status(row["powerbi"], answer)
        if state not in {"match", "gap-reject"}:
            out.append((row["model"], row["expr"], row["powerbi"][:80], answer[:80], state))
    return out


import pytest

CHUNK_SIZE = 100
FRESH_CHUNKS = [FRESH[i:i + CHUNK_SIZE] for i in range(0, len(FRESH), CHUNK_SIZE)]


@pytest.mark.parametrize("chunk", FRESH_CHUNKS)
def test_fresh_probes_match_or_are_refused(chunk: list[dict]) -> None:
    wrong = wrong_answers(chunk)
    shown = "\n".join(f"{m} {e}\n   power bi: {p}\n   ours: {a} [{s}]" for m, e, p, a, s in wrong[:5])
    assert wrong == [], f"{len(wrong)} of {len(chunk)} fresh probes answered wrongly\n{shown}"


ROWS_CHUNKS = [ROWS[i:i + 150] for i in range(0, len(ROWS), 150)]


@pytest.mark.parametrize("chunk", ROWS_CHUNKS)
def test_critic_rows_match_or_are_refused(chunk: list[dict]) -> None:
    wrong = wrong_answers(chunk)
    shown = "\n".join(f"{m} {e}\n   power bi: {p}\n   ours: {a} [{s}]" for m, e, p, a, s in wrong[:5])
    assert wrong == [], f"{len(wrong)} of {len(chunk)} critic rows answered wrongly ({dict(Counter(w[4] for w in wrong))})\n{shown}"


class CriticFindings(unittest.TestCase):
    def test_clock_functions_follow_the_system_date(self) -> None:
        """The clock-dependent rows skipped above: TODAY() is today's serial number and moves with plain date arithmetic."""
        today = date.today()
        self.assertEqual(str((today - date(1899, 12, 30)).days), ours_for("ZO", "INT(TODAY())"))
        self.assertEqual(today.isoformat(), ours_for("ZO", 'FORMAT(TODAY(),"yyyy-mm-dd")'))
        self.assertEqual("1", str(int(ours_for("ZO", "INT(TODAY())")) - int(ours_for("ZO", "INT(TODAY()-1)"))))


if __name__ == "__main__":
    unittest.main()
