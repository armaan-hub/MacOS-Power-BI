"""ALLSELECTED inside an iterator sees the iterated table as a shadow filter and never the context transition.

Expected values are live Power BI Desktop 2.157.879.0 answers (tests/fixtures_allselected_shadow.json): Facts, plus the
scratch tables AS_A (text/int, duplicate rows, blanks) and AS_D (dates, text, int) loaded together as the model.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio import dax_dates
from analytics_studio.measures import MeasureError, evaluate_measures
from tools.dax_oracle_diff import HEADERS, LOCAL_ROWS, same

FIXTURE = json.loads((Path(__file__).parent / "fixtures_allselected_shadow.json").read_text())


def model() -> list[dict]:
    def rows(spec: dict, names: list[str]) -> list[dict]:
        return [{name: None if value is None else (f"{value[0]:04d}-{value[1]:02d}-{value[2]:02d}" if isinstance(value, list) else str(value))
                 for name, value in zip(names, row)} for row in spec["rows"]]
    a, d = FIXTURE["tables"]["AS_A"], FIXTURE["tables"]["AS_D"]
    a_names, d_names = [c[0] for c in a["cols"]], [c[0] for c in d["cols"]]
    return [
        {"id": "facts", "name": "Facts", "headers": HEADERS, "rows": LOCAL_ROWS,
         "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"}},
        {"id": "as_a", "name": "AS_A", "headers": a_names, "rows": rows(a, a_names),
         "column_types": {"g": "text", "h": "whole_number", "v": "whole_number"}},
        {"id": "as_d", "name": "AS_D", "headers": d_names, "rows": rows(d, d_names),
         "column_types": {"d": "date", "t": "text", "n": "whole_number"}},
    ]


def ours(expression: str) -> str:
    tables = model()
    try:
        value = evaluate_measures(
            [{"name": "P__", "expression": expression}], tables[0]["rows"], tables[0]["headers"], "Facts",
            measure_names=["P__"], table_context=tables, active_table_id="facts",
        )["P__"]
    except MeasureError as error:
        return f"LOCAL-REJECT:{error}"
    if isinstance(value, dax_dates.DaxDateTime):
        return dax_dates.oracle_text(value)
    return "BLANK" if value is None else str(value)


class AllSelectedShadowTests(unittest.TestCase):
    def test_every_answer_matches_power_bi(self) -> None:
        for item in FIXTURE["items"]:
            with self.subTest(expression=item["expr"]):
                answer = ours(item["expr"])
                if item["powerbi"].startswith("ERR"):
                    self.assertTrue(answer.startswith("LOCAL-REJECT"), answer)
                else:
                    self.assertTrue(same(item["powerbi"], answer), f"Power BI {item['powerbi']!r}, app {answer!r}")


if __name__ == "__main__":
    unittest.main()
