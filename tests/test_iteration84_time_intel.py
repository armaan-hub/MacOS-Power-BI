"""Iteration 84 (Executor A2): time intelligence in iterators and odd contexts, DATEADD / DATESINPERIOD windows, TOTAL*TD forms,
USERELATIONSHIP + FILTER(Cal), empty date sets, ZS shortest path.  Expected values are live Power BI Desktop 2.157.879.0 answers
(Thinker A/B probe reports of iteration 84) on the Critic-3 models ZO / ZB / ZS.

Every fixture item carries `expect`: "match" (the Power BI answer is reproduced), "gap" (we still refuse; the test only checks that
we never answer differently) or "known-difference" (none remain: shapes we cannot answer like Power BI are refused)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio import measures
from tests.critic3_models import ours_for
from tools.parity_check import status

ITEMS = json.loads((Path(__file__).parent / "fixtures_iter84_time_intel.json").read_text())["items"]

def answer(item: dict) -> str:
    try:
        return ours_for(item["model"], item["expr"])
    except Exception as error:  # a crash is a failure, not an abort
        return f"LOCAL-CRASH {error!r}"


_CACHE: dict[int, tuple[str, str]] = {}


def judged(index: int) -> tuple[str, str]:
    if index not in _CACHE:
        item = ITEMS[index]
        got = answer(item)
        _CACHE[index] = (got, status(item["powerbi"], got))
    return _CACHE[index]


def failures_in(cluster: str, expect: str) -> list[tuple[str, str, str, str]]:
    bad = []
    for index, item in enumerate(ITEMS):
        if item["cluster"] != cluster or item["expect"] != expect:
            continue
        got, verdict = judged(index)
        if expect == "match" and verdict != "match":
            bad.append((item["model"], item["expr"], item["powerbi"], got))
        if expect == "gap" and verdict not in {"match", "gap-reject"}:
            bad.append((item["model"], item["expr"], item["powerbi"], got))
    return bad


class Iteration84Tests(unittest.TestCase):
    def check(self, cluster: str) -> None:
        bad = failures_in(cluster, "match")
        total = sum(1 for item in ITEMS if item["cluster"] == cluster and item["expect"] == "match")
        self.assertEqual([], bad[:4], f"{cluster}: {len(bad)} of {total} differ from Power BI")
        self.assertEqual([], failures_in(cluster, "gap")[:4], f"{cluster}: a refused shape now answers differently from Power BI")

    def test_d1_total_td_on_an_empty_date_set(self) -> None:
        self.check("D1")

    def test_d2_userelationship_row_transition_filter_calendar(self) -> None:
        self.check("D2")

    def test_d3_dateadd_month_end_fill(self) -> None:
        self.check("D3")

    def test_d4_total_ytd_omitted_third_argument(self) -> None:
        self.check("D4")
        with self.assertRaisesRegex(measures.MeasureError, "Argument '3' in TOTALYTD function is required"):
            measures.normalize_measure("x", 'TOTALYTD(SUM(T[A]), C[Date],, "6/30")')

    def test_scalar_typing_and_date_pivot(self) -> None:
        self.check("F")

    def test_argument_timing_and_date_key_wipe(self) -> None:
        self.check("B23")

    def test_gate_time_intelligence_inside_iterators(self) -> None:
        self.check("GATE")

    def test_datesinperiod_scalar_start(self) -> None:
        self.check("DIP")

    def test_total_td_argument_forms(self) -> None:
        self.check("TYTD")

    def test_filter_all_beside_other_filters(self) -> None:
        self.check("G5")

    def test_time_intelligence_tables_in_countrows_and_iterators(self) -> None:
        self.check("G6")

    def test_datesbetween_and_fact_date_columns(self) -> None:
        self.check("G4")

    def test_zs_shortest_path(self) -> None:
        self.check("ZS")

    def test_other_shapes_never_answer_differently(self) -> None:
        self.check("OTHER")

    def test_guard_sample_still_matches(self) -> None:
        self.check("GUARD")

    def test_no_known_differences_remain(self) -> None:
        """Every remaining difference is a refusal (tests/test_iteration84_refusals.py guards the ones that used to answer)."""
        self.assertEqual([], [item for item in ITEMS if item["expect"] == "known-difference"])


class DatesInPeriodWindowTests(unittest.TestCase):
    """DATESINPERIOD month arithmetic keeps the last day of a month (live Power BI, 903 of 903 windows)."""

    def test_shift_keeps_month_end(self) -> None:
        from datetime import date
        shift = measures._shift_date
        self.assertEqual(date(2024, 3, 31), shift(date(2024, 2, 29), 1, "MONTH", keep_month_end=True))
        self.assertEqual(date(2023, 5, 31), shift(date(2023, 4, 30), 1, "MONTH", keep_month_end=True))
        self.assertEqual(date(2023, 4, 30), shift(date(2023, 1, 31), 3, "MONTH", keep_month_end=True))
        self.assertEqual(date(2023, 11, 30), shift(date(2024, 2, 29), -1, "QUARTER", keep_month_end=True))
        self.assertEqual(date(2023, 2, 28), shift(date(2024, 1, 28), -11, "MONTH", keep_month_end=False))


if __name__ == "__main__":
    unittest.main()
