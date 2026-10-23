"""Pure tests for the DAX completion and parameter-hint engine (no Qt)."""

from __future__ import annotations

import unittest

from analytics_studio import measures
from analytics_studio.dax_intellisense import (
    FUNCTION_NAMES,
    complete,
    complete_formula,
    signature_help,
    signature_help_formula,
    split_formula,
)

MODEL = {
    "home_table": "ZB_Cal",
    "tables": [
        {"name": "ZB_Cal", "columns": [
            {"name": "Date", "type": "date"},
            {"name": "Year", "type": "number"},
            {"name": "MonthNo", "type": "number"},
            {"name": "Day", "type": "number"},
        ]},
        {"name": "Sales Data", "columns": [
            {"name": "Quantity", "type": "number"},
            {"name": "Region", "type": "text"},
        ]},
        {"name": "Dates", "columns": [{"name": "When", "type": "date"}]},
    ],
    "measures": [
        {"name": "Total Sales", "table": "Sales Data", "type": "number"},
        {"name": "Day Count", "table": "ZB_Cal", "type": "number"},
    ],
}


def labels(items: list[dict]) -> list[str]:
    return [item["label"] for item in items]


class FunctionCompletionTests(unittest.TestCase):
    def test_d_lists_date_functions_in_power_bi_order(self) -> None:
        items = complete("d", 1, MODEL)
        function_labels = [item["label"] for item in items if item["kind"] == "function"]
        self.assertEqual(function_labels[:12], [
            "DATATABLE", "DATE", "DATEADD", "DATEDIFF", "DATESBETWEEN",
            "DATESINPERIOD", "DATESMTD", "DATESQTD", "DATESWTD", "DATESYTD",
            "DATEVALUE", "DAY",
        ])
        self.assertTrue(all(item["signature"].startswith(item["label"] + "(")
                            for item in items if item["kind"] == "function"))
        date = next(item for item in items if item["label"] == "DATE")
        self.assertEqual(date["insertText"], "DATE(")
        self.assertEqual((date["replaceStart"], date["replaceEnd"]), (0, 1))
        self.assertIn("date", date["doc"].lower())

    def test_prefix_matches_come_before_contains_matches(self) -> None:
        items = complete("ear", 3, MODEL)
        names = labels(items)
        self.assertEqual(names[:2], ["EARLIER", "EARLIEST"])
        self.assertIn("YEAR", names)
        self.assertGreater(names.index("YEAR"), names.index("EARLIEST"))
        self.assertIn("NEXTYEAR", names)

    def test_matching_is_case_insensitive_and_dotted_names_work(self) -> None:
        self.assertEqual(labels(complete("sum", 3, MODEL))[:4],
                         ["SUM", "SUMMARIZE", "SUMMARIZECOLUMNS", "SUMX"])
        self.assertEqual(labels(complete("stdev.", 6, MODEL))[:2], ["STDEV.P", "STDEV.S"])

    def test_unsupported_functions_are_flagged_and_never_insert_text(self) -> None:
        items = {item["label"]: item for item in complete("dateswtd", 8, MODEL)}
        wtd = items["DATESWTD"]
        self.assertFalse(wtd["supported"])
        self.assertEqual(wtd["insertText"], "")
        self.assertIn("not supported", wtd["detail"].lower())
        supported = {item["label"]: item for item in complete("datesytd", 8, MODEL)}
        self.assertTrue(supported["DATESYTD"]["supported"])

    def test_every_function_the_engine_evaluates_is_listed_as_supported(self) -> None:
        missing = [name for name in measures.DAX_FUNCTION_NAMES if name not in FUNCTION_NAMES]
        self.assertEqual(missing, [])
        listed = {item["label"]: item for item in complete("", 0, MODEL, invoked=True)
                  if item["kind"] == "function"}
        for name in ("SUM", "CALCULATE", "ALL", "ABS", "ADDCOLUMNS"):
            self.assertTrue(listed[name]["supported"], name)

    def test_tables_and_measures_join_the_identifier_list(self) -> None:
        items = {item["label"]: item for item in complete("da", 2, MODEL)}
        self.assertEqual(items["Dates"]["kind"], "table")
        self.assertEqual(items["Dates"]["insertText"], "Dates")
        self.assertEqual(items["Day Count"]["kind"], "measure")
        self.assertEqual(items["Day Count"]["insertText"], "[Day Count]")
        self.assertIn("ZB_Cal", items["Day Count"]["detail"])
        sales = {item["label"]: item for item in complete("sal", 3, MODEL)}
        self.assertEqual(sales["Sales Data"]["insertText"], "'Sales Data'")

    def test_empty_prefix_needs_an_explicit_invocation(self) -> None:
        self.assertEqual(complete("SUM(", 4, MODEL), [])
        self.assertEqual(complete("", 0, MODEL), [])
        explicit = complete("SUM(", 4, MODEL, invoked=True)
        self.assertIn("CALCULATE", labels(explicit))
        self.assertIn("ZB_Cal", labels(explicit))

    def test_numbers_are_not_completed(self) -> None:
        self.assertEqual(complete("12", 2, MODEL), [])
        self.assertEqual(complete("1 + 2d", 6, MODEL), [])

    def test_keywords_are_offered(self) -> None:
        items = {item["label"]: item for item in complete("var", 3, MODEL)}
        self.assertEqual(items["VAR"]["kind"], "keyword")


class ColumnCompletionTests(unittest.TestCase):
    def test_table_bracket_lists_that_tables_columns(self) -> None:
        items = complete("ZB_Cal[", 7, MODEL)
        self.assertEqual(sorted(labels(items)), ["Date", "Day", "MonthNo", "Year"])
        self.assertTrue(all(item["kind"] == "column" for item in items))
        by_name = {item["label"]: item for item in items}
        self.assertIn("date", by_name["Date"]["detail"].lower())
        self.assertEqual(by_name["Year"]["insertText"], "Year]")
        self.assertEqual((by_name["Year"]["replaceStart"], by_name["Year"]["replaceEnd"]), (7, 7))

    def test_quoted_table_bracket_and_prefix_filter(self) -> None:
        text = "SUM('Sales Data'[Qu"
        items = complete(text, len(text), MODEL)
        self.assertEqual(labels(items), ["Quantity"])
        self.assertEqual((items[0]["replaceStart"], items[0]["replaceEnd"]), (len(text) - 2, len(text)))

    def test_table_match_is_case_insensitive_and_unknown_tables_list_nothing(self) -> None:
        self.assertEqual(sorted(labels(complete("zb_cal[", 7, MODEL))), ["Date", "Day", "MonthNo", "Year"])
        self.assertEqual(complete("Nope[", 5, MODEL), [])

    def test_existing_closing_bracket_is_not_duplicated(self) -> None:
        items = complete("ZB_Cal[Ye]", 9, MODEL)
        self.assertEqual(labels(items), ["Year"])
        self.assertEqual(items[0]["insertText"], "Year")

    def test_bare_bracket_lists_measures_and_home_table_columns(self) -> None:
        items = complete("[", 1, MODEL)
        by_label = {item["label"]: item for item in items}
        self.assertEqual(by_label["Total Sales"]["kind"], "measure")
        self.assertEqual(by_label["Year"]["kind"], "column")
        self.assertNotIn("Quantity", by_label)
        self.assertEqual(by_label["Total Sales"]["insertText"], "Total Sales]")

    def test_apostrophe_lists_tables_only(self) -> None:
        text = "SUM('Sa"
        items = complete(text, len(text), MODEL)
        self.assertEqual(labels(items), ["Sales Data"])
        self.assertEqual(items[0]["kind"], "table")
        self.assertEqual(items[0]["insertText"], "'Sales Data'")
        self.assertEqual(items[0]["replaceStart"], 4)
        self.assertEqual(labels(complete("'", 1, MODEL)), ["Dates", "Sales Data", "ZB_Cal"])


class NoPopupTests(unittest.TestCase):
    def test_nothing_inside_string_literals(self) -> None:
        self.assertEqual(complete('"d', 2, MODEL), [])
        self.assertEqual(complete('IF(a, "da', 9, MODEL), [])
        self.assertEqual(complete('"x""d', 5, MODEL), [])

    def test_a_closed_string_gives_nothing_but_later_identifiers_work(self) -> None:
        self.assertEqual(complete('"abc"', 5, MODEL), [])
        self.assertIn("DATE", labels(complete('"abc" & d', 9, MODEL)))

    def test_nothing_inside_comments(self) -> None:
        self.assertEqual(complete("// d", 4, MODEL), [])
        self.assertEqual(complete("-- da", 5, MODEL), [])
        self.assertEqual(complete("/* da", 5, MODEL), [])
        self.assertIn("DATE", labels(complete("// c\nd", 6, MODEL)))
        self.assertIn("DATE", labels(complete("/* c */ d", 9, MODEL)))

    def test_bracket_context_inside_string_is_ignored(self) -> None:
        self.assertEqual(complete('"ZB_Cal[', 8, MODEL), [])


class SignatureHelpTests(unittest.TestCase):
    def test_active_parameter_tracks_the_argument_index(self) -> None:
        hint = signature_help("CALCULATE(SUM(ZB_Cal[Year]), ", 29)
        self.assertEqual(hint["function"], "CALCULATE")
        self.assertEqual(hint["activeParameter"], 1)
        self.assertEqual(hint["parameters"][0], "<expression>")
        self.assertTrue(hint["supported"])
        self.assertTrue(hint["signature"].startswith("CALCULATE("))
        self.assertIn("filter", hint["doc"].lower())

    def test_first_parameter_and_nested_call(self) -> None:
        hint = signature_help("CALCULATE(SUM(", 14)
        self.assertEqual((hint["function"], hint["activeParameter"]), ("SUM", 0))
        hint = signature_help("IF(a, b, ", 9)
        self.assertEqual((hint["function"], hint["activeParameter"]), ("IF", 2))

    def test_after_a_closed_inner_call_the_outer_function_is_current(self) -> None:
        text = "CALCULATE(SUM(ZB_Cal[Year])"
        hint = signature_help(text, len(text))
        self.assertEqual((hint["function"], hint["activeParameter"]), ("CALCULATE", 0))

    def test_grouping_parentheses_do_not_hide_the_function(self) -> None:
        hint = signature_help("ROUND((1 + 2), ", 15)
        self.assertEqual((hint["function"], hint["activeParameter"]), ("ROUND", 1))

    def test_commas_in_strings_brackets_braces_and_comments_are_not_arguments(self) -> None:
        self.assertEqual(signature_help('IF("a,b", ', 10)["activeParameter"], 1)
        self.assertEqual(signature_help("IF(T[a,b], ", 11)["activeParameter"], 1)
        self.assertEqual(signature_help("IF({1,2,3}, ", 12)["activeParameter"], 1)
        self.assertEqual(signature_help("IF(1 /* a, b */, ", 17)["activeParameter"], 1)

    def test_variadic_functions_keep_the_last_parameter_active(self) -> None:
        hint = signature_help("SWITCH(x, 1, 2, 3, 4, 5, 6, ", 28)
        self.assertEqual(hint["function"], "SWITCH")
        self.assertEqual(hint["activeParameter"], len(hint["parameters"]) - 1)

    def test_no_hint_outside_a_call_or_inside_a_string_or_comment(self) -> None:
        self.assertIsNone(signature_help("1 + 2", 5))
        self.assertIsNone(signature_help("SUM(x)", 6))
        self.assertIsNone(signature_help('IF("a(', 6))
        self.assertIsNone(signature_help("IF(// ", 6))

    def test_unsupported_function_hint_is_flagged(self) -> None:
        hint = signature_help("DATESWTD(", 9)
        self.assertEqual(hint["function"], "DATESWTD")
        self.assertFalse(hint["supported"])

    def test_hint_stays_while_typing_inside_a_column_or_table_reference(self) -> None:
        self.assertEqual(signature_help("SUM(T[Q", 7)["function"], "SUM")
        self.assertEqual(signature_help("SUM('Sales Data'[Q", 18)["function"], "SUM")
        hint = signature_help("CALCULATE(SUM(T[Y]), T[Q", 24)
        self.assertEqual((hint["function"], hint["activeParameter"]), ("CALCULATE", 1))

    def test_unknown_function_names_give_no_hint(self) -> None:
        self.assertIsNone(signature_help("MyFunction(", 11))


class FormulaPrefixTests(unittest.TestCase):
    def test_split_formula_finds_the_name_and_expression_offset(self) -> None:
        self.assertEqual(split_formula("Total Sales = SUM(x)"), ("Total Sales", 14))
        self.assertEqual(split_formula("Measure =")[0], "Measure")
        self.assertEqual(split_formula("Measure = a = b")[0], "Measure")
        self.assertIsNone(split_formula("SUM(x)"))

    def test_completion_works_on_the_expression_after_the_name(self) -> None:
        text = "Measure = d"
        items = complete_formula(text, len(text), MODEL)
        self.assertEqual(labels(items)[:3], ["DATATABLE", "DATE", "DATEADD"])
        self.assertEqual((items[0]["replaceStart"], items[0]["replaceEnd"]), (10, 11))

    def test_no_completion_while_typing_the_name(self) -> None:
        self.assertEqual(complete_formula("Meas = d", 4, MODEL), [])
        self.assertEqual(complete_formula("d", 1, MODEL), [])

    def test_signature_help_uses_the_expression_part(self) -> None:
        text = "Total = CALCULATE(SUM(a), "
        hint = signature_help_formula(text, len(text))
        self.assertEqual((hint["function"], hint["activeParameter"]), ("CALCULATE", 1))
        self.assertIsNone(signature_help_formula("Tot", 3))


if __name__ == "__main__":
    unittest.main()
