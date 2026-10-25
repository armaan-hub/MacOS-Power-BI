"""Iteration 85: SWITCH over a text subject inside an iterator, and mixed-type (variant) ADDCOLUMNS columns.

fixtures_iter85_switch_text_subject.json: 617 saved live Power BI answers (tools/parity) that the local engine used to refuse because the
SWITCH subject was a text column ("Column 'Region' contains a non-numeric value"); they must now match Power BI exactly.

fixtures_iter85_fresh.json: new live probes written for the fix (never in any battery).  Every row must match Power BI or be refused:
a wrong answer is worse than a refusal.  The variant-column rows pin the other half of the change: ADDCOLUMNS(.., "v", IF/SWITCH with a
text branch beside a number branch) makes a Variant column in Power BI whose MAXX / MINX / SUMX / AVERAGEX / COUNTX read only the numbers;
the local engine used to answer them from the values of the rows (wrong or crashing), so they are refused."""
from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

HERE = Path(__file__).parent
SAVED = json.loads((HERE / "fixtures_iter85_switch_text_subject.json").read_text())
FRESH = json.loads((HERE / "fixtures_iter85_fresh.json").read_text())["items"]


class SwitchTextSubject(unittest.TestCase):
    def test_saved_power_bi_answers_now_match(self) -> None:
        wrong = []
        for row in SAVED:
            ours = dax.local(row["expr"])
            if status(row["powerbi"], ours) != "match":
                wrong.append((row["expr"], row["powerbi"][:60], ours[:60]))
        self.assertEqual([], wrong[:5], f"{len(wrong)} of {len(SAVED)} saved answers do not match")

    def test_fresh_probes_match_or_are_refused(self) -> None:
        wrong = []
        for _model, expr, powerbi, _old, _state in FRESH:
            ours = dax.local(expr)
            state = status(powerbi, ours)
            if state not in {"match", "gap-reject"}:
                wrong.append((state, expr, powerbi[:60], ours[:60]))
        self.assertEqual([], wrong[:5], f"{len(wrong)} of {len(FRESH)} fresh probes answered wrongly ({dict(Counter(w[0] for w in wrong))})")

    def test_text_subject_cases_are_answered(self) -> None:
        """The core of the rule, spelled out (live Power BI): blank only equals blank, text ignores case, rows keep their own result type."""
        facts = lambda expr: dax.local(expr)  # noqa: E731
        self.assertEqual("Paid|Paid|Paid|FALSE|FALSE|FALSE",
                         facts('CONCATENATEX(Facts,SWITCH(Facts[Note],"Paid",Facts[Note],FALSE()),"|",Facts[Quantity])'))
        self.assertEqual("2|2|2|2|2|2", facts('CONCATENATEX(Facts,SWITCH(Facts[Note],"",1,2),"|",Facts[Quantity])'))
        self.assertEqual("FALSE|Paid|FALSE|TRUE|FALSE|TRUE",
                         facts('CONCATENATEX(Facts,SWITCH(Facts[Quantity]+0,1,Facts[Note],ISBLANK(Facts[Note])),"|",Facts[Quantity])'))

    def test_variant_column_aggregates_are_refused_not_guessed(self) -> None:
        for aggregate in ("MAXX", "MINX", "COUNTX", "SUMX", "AVERAGEX"):
            for column in ('SWITCH(Facts[Quantity],9,0,"a")', 'IF(Facts[Quantity]>2,Facts[Sales],Facts[Region]&"!")',
                           'SWITCH(Facts[Note],"zz",Facts[Sales],Facts[Region])'):
                answer = dax.local(f'{aggregate}(ADDCOLUMNS(Facts,"v",{column}),[v])')
                self.assertTrue(answer.startswith("LOCAL-REJECT"), f"{aggregate} over {column}: {answer}")


if __name__ == "__main__":
    unittest.main()
