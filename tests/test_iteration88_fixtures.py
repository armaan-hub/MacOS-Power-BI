"""Iteration 88: the saved and fresh live Power BI answers behind the engine changes of this iteration (compared with Power BI Desktop 2.157.879.0).

fixtures_iter88_saved.json: saved live Power BI answers (tools/parity) that the local engine used to refuse (the 194 remaining refusals of iteration 87:
CALCULATETABLE in True/False filters inside iterators and under an outer CALCULATE, columns of an enclosing row context, EARLIER / EARLIEST, comments,
==, text as True/False, time-only text ...); they must now match Power BI exactly.

fixtures_iter88_fresh.json: fresh live probes (headless guest path) on Facts, the ZO / ZB / ZS relationship models and the TT scratch table (text,
number and Boolean columns): hand-built matrices and samples of random expressions.  Every row must match Power BI or be refused: a wrong answer
is worse than a refusal.  items = [model, expr, powerbi, old_status, new_state] (old_status is the state of the iteration-87 engine, new_state the
state when written; the test only requires match or gap-reject)."""
from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

from analytics_studio.measures import MeasureError, evaluate_measures
from tests.critic3_models import _FACTS, HEADERS, LOCAL_ROWS, ours_for
from tools import dax_oracle_diff as dax
from tools.parity_check import status

HERE = Path(__file__).parent
SAVED = json.loads((HERE / "fixtures_iter88_saved.json").read_text())
FRESH = json.loads((HERE / "fixtures_iter88_fresh.json").read_text())["items"]

_TT = {"id": "tt", "name": "TT", "headers": ["T", "N", "Bo"], "column_types": {"T": "text", "N": "decimal_number", "Bo": "boolean"}, "rows": [
    {"T": "5", "N": "5", "Bo": "True"}, {"T": "3.5", "N": "3.5", "Bo": "False"}, {"T": "abc", "N": "0", "Bo": "True"}, {"T": "", "N": "-2", "Bo": "False"},
    {"T": None, "N": "7", "Bo": "True"}, {"T": "TRUE", "N": None, "Bo": "True"}]}
_TX = {"id": "tx", "name": "TX", "headers": ["T"], "column_types": {"T": "text"}, "rows": [{"T": "5"}, {"T": "3"}]}
_TY = {"id": "ty", "name": "TY", "headers": ["T"], "column_types": {"T": "text"}, "rows": [{"T": "abc"}, {"T": "3"}]}
_TZ = {"id": "tz", "name": "TZ", "headers": ["T"], "column_types": {"T": "text"}, "rows": [{"T": None}, {"T": None}]}
_TB = {"id": "tb", "name": "TB", "headers": ["Bo"], "column_types": {"Bo": "boolean"}, "rows": [{"Bo": "True"}, {"Bo": "False"}, {"Bo": "True"}]}


def _ours_tt(expression: str) -> str:
    """TT: text 5 / 3.5 / abc / empty / BLANK / TRUE, numbers 5 / 3.5 / 0 / -2 / 7 / BLANK and True / False columns; TX, TY, TZ, TB: small text and Boolean tables."""
    try:
        value = evaluate_measures(
            [{"name": "P", "expression": expression, "home_table_id": "tt"}], LOCAL_ROWS, HEADERS, "Facts", measure_names=["P"],
            table_context=[_FACTS, _TT, _TX, _TY, _TZ, _TB], active_table_id="facts",
        )["P"]
    except MeasureError as error:
        return f"LOCAL-REJECT:{error}"
    return "BLANK" if value is None else str(value)


def _ours(model: str, expression: str) -> str:
    if model == "Facts":
        return dax.local(expression)
    if model == "TT":
        return _ours_tt(expression)
    return ours_for(model, expression)


_STATES: list[tuple[str, str, str, str, str, str]] | None = None


def fresh_states() -> list[tuple[str, str, str, str, str, str]]:
    """(model, expr, powerbi, old status, ours, state) of every fresh row, evaluated once."""
    global _STATES
    if _STATES is None:
        _STATES = []
        for model, expr, powerbi, old, _state in FRESH:
            ours = _ours(model, expr)
            _STATES.append((model, expr, powerbi, old, ours, status(powerbi, ours)))
    return _STATES


class Iteration88Answers(unittest.TestCase):
    def test_saved_power_bi_answers_now_match(self) -> None:
        wrong = []
        for row in SAVED:
            ours = dax.local(row["expr"])
            if status(row["powerbi"], ours) != "match":
                wrong.append((row["expr"], row["powerbi"][:60], ours[:60]))
        self.assertEqual([], wrong[:5], f"{len(wrong)} of {len(SAVED)} saved answers do not match")

    def test_fresh_probes_match_or_are_refused(self) -> None:
        wrong = [(state, model, expr[:160], powerbi[:40], ours[:60]) for model, expr, powerbi, _old, ours, state in fresh_states()
                 if state not in {"match", "gap-reject"}]
        self.assertEqual([], wrong[:5], f"{len(wrong)} of {len(FRESH)} fresh probes answered wrongly ({dict(Counter(w[0] for w in wrong))})")

    def test_most_fresh_probes_are_answered(self) -> None:
        answered = sum(1 for *_rest, state in fresh_states() if state == "match")
        self.assertGreater(answered / len(FRESH), 0.7)

    def test_what_the_old_engine_got_wrong_is_no_longer_wrong(self) -> None:
        """Rows the iteration-87 engine answered wrongly (DIFF) are now right or refused, never wrong."""
        for model, expr, _powerbi, old, _ours, state in fresh_states():
            if old in {"DIFF", "CRASH"}:
                self.assertIn(state, {"match", "gap-reject"}, expr)


if __name__ == "__main__":
    unittest.main()
