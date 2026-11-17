"""Task 209: a missing part from Table.SplitColumn is null, not "" (Power BI answers taken 2026-11-17 from the live
Power BI, headless M answer check). Scripts that still pass the old explicit "" default keep their blank text."""

from __future__ import annotations

import unittest

from analytics_studio.file_import import ImportCandidate
from analytics_studio.m_engine import evaluate_to_text
from analytics_studio.power_query_m import parse_m_script, steps_to_m_script
from analytics_studio.transformations import apply_transformations

POWER_BI_FIRST = (
    'table:cols=["A.1":"text","A.2":"text"];rows=[list:[text:"x",text:"y"],list:[text:"z",null]]'
)
POWER_BI_EACH = 'table:cols=["A.1":"text","A.2":"text"];rows=[list:[text:"abc",null]]'


def _cand(headers: list[str], rows: list[dict[str, str]]) -> ImportCandidate:
    return ImportCandidate("inline", headers, rows, {}, [])


class MissingPartReplayTests(unittest.TestCase):
    def test_first_delimiter_missing_second_part_is_none(self) -> None:
        result = apply_transformations(
            _cand(["A"], [{"A": "x,y"}, {"A": "z"}]),
            [{"op": "split_column", "column": "A", "delimiter": ","}],
        )
        self.assertEqual(result.rows[0], {"A.1": "x", "A.2": "y"})
        self.assertEqual(result.rows[1], {"A.1": "z", "A.2": None})

    def test_each_delimiter_padding_is_none(self) -> None:
        result = apply_transformations(
            _cand(["A"], [{"A": "abc"}]),
            [{"op": "split_column_by_each_delimiter", "column": "A", "delimiter": ","}],
        )
        self.assertEqual(result.rows[0], {"A.1": "abc", "A.2": None})

    def test_real_empty_part_stays_blank(self) -> None:
        result = apply_transformations(
            _cand(["A"], [{"A": "x,"}]),
            [{"op": "split_column", "column": "A", "delimiter": ","}],
        )
        self.assertEqual(result.rows[0], {"A.1": "x", "A.2": ""})


class EmittedMTests(unittest.TestCase):
    def test_emitted_split_calls_have_no_default_argument(self) -> None:
        steps = [
            {"op": "split_column", "column": "A", "delimiter": ","},
            {"op": "split_column_by_each_delimiter", "column": "A", "delimiter": ","},
            {"op": "split_column_by_positions", "column": "A", "positions": [0, 2]},
        ]
        script = steps_to_m_script(steps, "Q")
        split_lines = [line for line in script.splitlines() if "Table.SplitColumn" in line]
        self.assertEqual(len(split_lines), 3)
        for line in split_lines:
            self.assertFalse(line.rstrip().endswith(', "")'), line)

    def test_emitted_first_delimiter_matches_power_bi_answer(self) -> None:
        script = steps_to_m_script(
            [{"op": "split_column", "column": "A", "delimiter": ","}], "Q"
        ).replace('Source = #"Q"', 'Source = #table({"A"}, {{"x,y"}, {"z"}})')
        self.assertEqual(evaluate_to_text(script), "V:" + POWER_BI_FIRST)

    def test_emitted_each_delimiter_matches_power_bi_answer(self) -> None:
        script = steps_to_m_script(
            [{"op": "split_column_by_each_delimiter", "column": "A", "delimiter": ","}], "Q"
        ).replace('Source = #"Q"', 'Source = #table({"A"}, {{"abc"}})')
        self.assertEqual(evaluate_to_text(script), "V:" + POWER_BI_EACH)

    def test_power_bi_expressions_evaluate_to_power_bi_answers(self) -> None:
        # Verbatim Power BI expressions (QuoteStyle.Csv as Power BI was asked), local engine output.
        first = (
            'Table.SplitColumn(#table({"A"},{{"x,y"},{"z"}}), "A", '
            'Splitter.SplitTextByDelimiter(",", QuoteStyle.Csv), {"A.1","A.2"})'
        )
        each = (
            'Table.SplitColumn(#table({"A"},{{"abc"}}), "A", '
            'Splitter.SplitTextByEachDelimiter({","}, QuoteStyle.Csv, true), {"A.1","A.2"})'
        )
        self.assertEqual(evaluate_to_text(first), "V:" + POWER_BI_FIRST)
        self.assertEqual(evaluate_to_text(each), "V:" + POWER_BI_EACH)


class LegacyScriptTests(unittest.TestCase):
    def test_old_blank_default_script_still_loads_as_blank(self) -> None:
        script = (
            "let\n"
            '    Source = #"Q",\n'
            '    Split = Table.SplitColumn(Source, "A", '
            'Splitter.SplitTextByEachDelimiter({","}, QuoteStyle.None), {"A.1", "A.2"}, "")\n'
            "in\n"
            "    Split"
        )
        steps = parse_m_script(script, "Q")
        self.assertEqual(steps[0].get("missing_part"), "")
        result = apply_transformations(_cand(["A"], [{"A": "z"}]), steps)
        self.assertEqual(result.rows[0], {"A.1": "z", "A.2": ""})

    def test_new_script_without_default_loads_as_null(self) -> None:
        script = steps_to_m_script(
            [{"op": "split_column", "column": "A", "delimiter": ","}], "Q"
        )
        steps = parse_m_script(script, "Q")
        self.assertNotIn("missing_part", steps[0])
        result = apply_transformations(_cand(["A"], [{"A": "z"}]), steps)
        self.assertEqual(result.rows[0], {"A.1": "z", "A.2": None})


if __name__ == "__main__":
    unittest.main()
