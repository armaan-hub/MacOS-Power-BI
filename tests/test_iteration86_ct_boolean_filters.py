"""Iteration 86: a CALCULATETABLE inside the scalar side of a Boolean CALCULATE filter.

fixtures_iter86_ct_boolean_filters.json: 170 saved live Power BI answers (tools/parity, Facts scratch table) that the local engine used to refuse
("A CALCULATETABLE inside a True/False filter is supported only on the right of a comparison at the top level, with Boolean filters.").  They
must now match Power BI exactly.  The rule (analytics_studio/dax_ct_filters.py): per scalar, Power BI either evaluates it once (HOIST) or runs the
filter as FILTER(ALL(columns), test) so the CALCULATETABLE sees each value as a row context (TRANSITION).

fixtures_iter86_fresh.json: new live probes written for this rule, never in any battery.  Every row must match Power BI or be refused: a wrong
answer is worse than a refusal."""
from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

from analytics_studio import dax_ct_filters
from analytics_studio.measures import parse_expression
from tests.critic3_models import ours_for
from tools import dax_oracle_diff as dax
from tools.parity_check import status

HERE = Path(__file__).parent
SAVED = json.loads((HERE / "fixtures_iter86_ct_boolean_filters.json").read_text())
FRESH_FILE = HERE / "fixtures_iter86_fresh.json"
FRESH = json.loads(FRESH_FILE.read_text())["items"] if FRESH_FILE.exists() else []


def _direct(node):  # the engine's own notion of "a column the filter picks"
    from analytics_studio.measures import _direct_column_references
    return _direct_column_references(node)


def _plan(expression: str):
    call = parse_expression(expression)
    return [dax_ct_filters.plan(argument, _direct) for argument in call[2][1:]]


class CalculateTableInBooleanFilter(unittest.TestCase):
    def test_saved_power_bi_answers_now_match(self) -> None:
        wrong = []
        for row in SAVED:
            ours = dax.local(row["expr"])
            if status(row["powerbi"], ours) != "match":
                wrong.append((row["expr"], row["powerbi"][:40], ours[:60]))
        self.assertEqual([], wrong[:5], f"{len(wrong)} of {len(SAVED)} saved answers do not match")

    def test_fresh_probes_match_or_are_refused(self) -> None:
        wrong = []
        for model, expr, powerbi, _old, _state in FRESH:
            ours = dax.local(expr) if model == "Facts" else ours_for(model, expr)  # ZO / ZB: the Critic-3 relationship models
            state = status(powerbi, ours)
            if state not in {"match", "gap-reject"}:
                wrong.append((state, expr, powerbi[:60], ours[:60]))
        self.assertEqual([], wrong[:5], f"{len(wrong)} of {len(FRESH)} fresh probes answered wrongly ({dict(Counter(w[0] for w in wrong))})")

    def test_the_two_readings_are_told_apart(self) -> None:
        """Live Power BI on the six-row Facts table: the same predicate mirrored gives different answers, and an X-iterator never transitions."""
        facts = dax.local
        # HOIST: the scalar is evaluated once (3 East rows), so Quantity > 3 keeps quantities 4 and 5
        self.assertEqual("2", facts('CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East")))'))
        # TRANSITION: the scalar comes first, every quantity q is a row context: East rows with Quantity = q are fewer than q for 2, 3, 4 and 5
        self.assertEqual("4", facts('CALCULATE(COUNTROWS(Facts),COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))<Facts[Quantity])'))
        # no Boolean filter inside the CALCULATETABLE: always a transition (one row per quantity), so only Quantity = 0 is below 1
        self.assertEqual("1", facts("CALCULATE(COUNTROWS(Facts),Facts[Quantity]<COUNTROWS(CALCULATETABLE(Facts)))"))
        self.assertEqual("4", facts("CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts)))"))
        # an X-iterator over a CALCULATETABLE is evaluated once, even with no filter at all
        self.assertEqual("5", facts("CALCULATE(COUNTROWS(Facts),Facts[Quantity]<MAXX(CALCULATETABLE(Facts),Facts[Quantity]))"))

    def test_classification(self) -> None:
        h, t = dax_ct_filters.HOIST, dax_ct_filters.TRANSITION
        self.assertEqual(h, _plan('CALCULATE(1,Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East")))')[0][0])
        self.assertEqual(t, _plan('CALCULATE(1,COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))<Facts[Quantity])')[0][0])
        self.assertEqual(t, _plan("CALCULATE(1,Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,ALL(Facts[Region]))))")[0][0])
        self.assertIsNone(_plan("CALCULATE(1,COUNTROWS(CALCULATETABLE(Facts,ALL(Facts[Region])))<MAXX(CALCULATETABLE(Facts),Facts[Quantity])+Facts[Quantity])")[0])  # one scalar hoists, the other transitions
        self.assertEqual(h, _plan("CALCULATE(1,MAXX(CALCULATETABLE(Facts),Facts[Quantity])<Facts[Quantity])")[0][0])
        # a scalar that is not the first thing the whole filter reads stays HOIST even when its own comparison starts with it (fresh probes)
        self.assertEqual(h, _plan('CALCULATE(1,Facts[Region]<>"North"&&COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))<Facts[Quantity])')[0][0])
        # shapes whose Power BI answer was not established are not planned: KEEPFILTERS / ALLSELECTED / FILTER among the filters, nested
        # CALCULATETABLE, and scalars of different readings in one filter
        # iteration 88 (12,500 fresh probes): KEEPFILTERS(test) reads like the plain test, and the columns inside the CALCULATETABLE tests are cleared
        # with the filter column (the plan carries them as extra_columns)
        planned = _plan('CALCULATE(1,Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,KEEPFILTERS(Facts[Region]="East"))))')[0]
        self.assertEqual(t, planned.mode)
        self.assertEqual([("reference", "Facts", "Region")], list(planned.extra_columns))
        self.assertIsNone(_plan("CALCULATE(1,Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,ALLSELECTED(Facts[Quantity]))))")[0])
        self.assertIsNone(_plan('CALCULATE(1,Facts[Quantity]>COUNTROWS(CALCULATETABLE(CALCULATETABLE(Facts,Facts[Region]="East"),Facts[Note]="Paid")))')[0])
        self.assertIsNone(_plan("CALCULATE(1,Facts[Quantity]=COUNTROWS(CALCULATETABLE(Facts,ALL(Facts[Quantity])))+COUNTROWS(CALCULATETABLE(Facts,NOT(Facts[Region]=\"East\"))))")[0])
        self.assertIsNone(_plan("CALCULATE(1,Facts[Quantity]>ABS(COUNTROWS(CALCULATETABLE(Facts))))")[0])
        self.assertIsNone(_plan("CALCULATE(1,Facts[Quantity]<IF(ISEMPTY(CALCULATETABLE(Facts,Facts[Region]=\"East\")),1,4))")[0])

    def test_row_contexts_are_answered_and_several_scalars_stay_refused(self) -> None:
        # iteration 88 (live Power BI): inside an iterator row context and under a CALCULATE that already filters the scalar is read the same way
        self.assertEqual("4", dax.local('SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))))'))
        self.assertEqual("2", dax.local('CALCULATE(CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))),Facts[Region]="East")'))
        # several scalars in one filter inside a row context are not established
        self.assertTrue(dax.local(
            'SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))+COUNTROWS(CALCULATETABLE(Facts,Facts[Note]="Paid"))))'
        ).startswith("LOCAL-REJECT"))


if __name__ == "__main__":
    unittest.main()
