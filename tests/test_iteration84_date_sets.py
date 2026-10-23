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


# Power BI answers that the local engine refuses on purpose (never a wrong number): the open items of the live comparison.
KNOWN_REFUSALS = (
    "with a February 28 year end is not supported",  # fiscal year around a leap day starts on Feb 29 in Power BI
    "KEEPFILTERS over a column of a FILTER table that was combined with other filters",
    "Iterator expressions can reference columns from their iterated table only",
    "The iterated date set has one column",
    "A FIRSTNONBLANK inside a date set under a row context is not supported",
    "Table-valued functions are not supported in measure expressions",  # a bare PREVIOUSMONTH(Date) as a measure: refused since iteration 80
)


class SavedPowerBiAnswers(unittest.TestCase):
    def check(self, cluster: str, allowed_refusals: int) -> None:
        bad = failures(cluster)
        total = sum(1 for item in ITEMS if item[3] == cluster)
        wrong = [b for b in bad if b[5] != "gap-reject" or not any(text in b[4] for text in KNOWN_REFUSALS)]
        shown = "\n".join(f"{m} {e}\n   power bi: {p}\n   ours: {a[:100]} [{s}]" for _t, m, e, p, a, s in wrong[:5])
        self.assertEqual([], wrong, f"{cluster}: {len(wrong)} of {total} differ from Power BI ({dict(Counter(b[5] for b in wrong))})\n{shown}")
        self.assertLessEqual(len(bad), allowed_refusals, f"{cluster}: more refusals than the {allowed_refusals} known ones")

    def test_c01_first_last_start_end(self) -> None:
        self.check("C01", 2)

    def test_c04_opening_closing_balances(self) -> None:
        self.check("C04", 0)

    def test_c05_next_previous(self) -> None:
        self.check("C05", 54)

    def test_c07_fact_date_columns(self) -> None:
        self.check("C07", 3)

    def test_c08_first_last_nonblank(self) -> None:
        self.check("C08", 0)

    def test_c11_date_overflow_saturates(self) -> None:
        self.check("C11", 0)


FRESH = json.loads((Path(__file__).parent / "fixtures_iter84_date_sets_fresh.json").read_text())["items"]


class FreshLiveProbes(unittest.TestCase):
    """Probes written after the engine (random nesting, VAR-held sets, scalar use, iterators): never a wrong number."""

    def test_every_probe_matches_or_is_refused(self) -> None:
        wrong = []
        for model, expression, powerbi, _tag in FRESH:
            answer = ours_for(model, expression)
            if status(powerbi, answer) not in {"match", "gap-reject"}:
                wrong.append((model, expression, powerbi, answer[:80]))
        self.assertEqual([], wrong[:5], f"{len(wrong)} of {len(FRESH)} differ from Power BI")

    def test_known_shapes(self) -> None:
        for model, expression, expected in (
            ("ZO", "CALCULATE(FIRSTDATE(ZO_Cal[Date])+1,ZO_Cal[Year]=2030)", "12/31/1899 00:00:00"),  # a date set with no row is a typed BLANK date
            ("ZO", "CALCULATE(VAR d=DATESMTD(DATESMTD(VALUES(ZO_Cal[Date]))) RETURN CALCULATE(SUM(ZO_Fact[Amt]),DATESYTD(d)),ZO_Cal[Year]=2024,ZO_Cal[MonthNo]=2)", "110"),
            ("ZO", "SUMX(VALUES(ZO_Cal[Year]),CALCULATE(COUNTROWS(ZO_Cal),LASTNONBLANK(ZO_Cal[Date],1)))", "2"),
            ("ZO", "FIRSTNONBLANK(ZO_Cal[Date],CALCULATE(SUM(ZO_Fact[Amt])))", "01/15/2023 00:00:00"),
            ("ZO", "FIRSTNONBLANKVALUE(ZO_Cal[Date],SUM(ZO_Fact[Amt]))", "10"),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours_for(model, expression).removesuffix(".0"))

    def test_invalid_column_reads_are_refused_even_for_an_empty_set(self) -> None:
        for expression in (
            "CALCULATE(CONCATENATEX(NEXTDAY(VALUES(ZO_Fact[Ship])),FORMAT(ZO_Cal[Date],\"yyyy-mm-dd\"),\";\"),ZO_Dim[Cat]=\"B\")",
            "CALCULATE(VAR d=PREVIOUSQUARTER(FILTER(VALUES(ZO_Cal[Date]),ZO_Cal[Day]<=10)) RETURN COUNTROWS(d),ZO_Cal[Year]=2030)",
            "MAXX(NEXTDAY(ZO_Fact[Dt]),ZO_Fact[Ship])",
        ):
            with self.subTest(expression=expression):
                self.assertTrue(ours_for("ZO", expression).startswith("LOCAL-REJECT"))


if __name__ == "__main__":
    unittest.main()
