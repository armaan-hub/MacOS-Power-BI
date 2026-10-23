"""Iteration 84 (Executor A): time intelligence in iterators and odd contexts, DATEADD/DATESINPERIOD windows, TOTAL*TD forms,
USERELATIONSHIP + FILTER(Cal), empty date sets, ZS shortest path.  Expected values are live Power BI Desktop 2.157.879.0 answers
(Thinker A/B probe reports of iteration 84) on the Critic-3 models ZO / ZB / ZS."""
from __future__ import annotations

import json
import unittest
from collections import defaultdict
from pathlib import Path

from tests.critic3_models import ours_for
from tools.parity_check import status

ITEMS = json.loads((Path(__file__).parent / "fixtures_iter84_time_intel.json").read_text())["items"]


def failures_in(cluster: str) -> list[tuple[str, str, str, str]]:
    bad = []
    for item in ITEMS:
        if item["cluster"] != cluster:
            continue
        try:
            answer = ours_for(item["model"], item["expr"])
        except Exception as error:  # a crash is a failure, not an abort
            answer = f"LOCAL-CRASH {error!r}"
        if status(item["powerbi"], answer) != "match":
            bad.append((item["model"], item["expr"], item["powerbi"], answer))
    return bad


class Iteration84Tests(unittest.TestCase):
    def check(self, cluster: str) -> None:
        bad = failures_in(cluster)
        total = sum(1 for item in ITEMS if item["cluster"] == cluster)
        self.assertEqual([], bad[:4], f"{cluster}: {len(bad)} of {total} differ from Power BI")

    def test_d1_total_td_on_an_empty_date_set(self) -> None:
        self.check("D1")

    def test_d2_userelationship_row_transition_filter_calendar(self) -> None:
        self.check("D2")

    def test_d3_dateadd_month_end_fill(self) -> None:
        self.check("D3")

    def test_d4_total_ytd_omitted_third_argument(self) -> None:
        self.check("D4")

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

    def test_guard_sample_still_matches(self) -> None:
        self.check("GUARD")


if __name__ == "__main__":
    unittest.main()
