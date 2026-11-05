"""Iteration 148: Task 58 missing-functions-48.

The ten DAX functions APPROXIMATEDISTINCTCOUNT, CALENDARAUTO, DATESWTD, TOTALWTD, DETAILROWS, PATH, SELECTEDMEASURE,
SELECTEDMEASURENAME, ISSELECTEDMEASURE and USEROBJECTID. The error messages are the live Power BI answers recorded in
docs/plans/2026-11-05-missing-functions-48.md (guest model: one table Facts, no date column, import mode). Anything the
plan does not measure is refused (a MeasureError with 'not modelled by the local engine'), never answered.

The model-date CALENDARAUTO and parent-child PATH results below are documented DAX behaviour, not yet measured in Power BI.
"""
import unittest
from decimal import Decimal

from analytics_studio import dax_intellisense
from analytics_studio import measures
from tools import dax_oracle_diff as dax

NAMES = (
    "APPROXIMATEDISTINCTCOUNT", "CALENDARAUTO", "DATESWTD", "TOTALWTD", "DETAILROWS", "PATH",
    "SELECTEDMEASURE", "SELECTEDMEASURENAME", "ISSELECTEDMEASURE", "USEROBJECTID",
)
CALENDARAUTO_MISSING = "CALENDARAUTO function can not find a base column of DateTime type in the model."
STORAGE_MODE = "The function APPROXIMATEDISTINCTCOUNT isn't supported for this storage mode."
NO_SELECTED_MEASURE = "There is no measure reference in the current context to be applied as SELECTEDMEASURE."
NO_SELECTED_MEASURE_NAME = "There is no measure reference in the current context that can be used by SELECTEDMEASURENAME."
BAD_ISSELECTED = "Invalid input arguments for ISSELECTEDMEASURE."
PATH_TYPES = (
    "The columns specified in the PATH function must be from the same table, have the same data type and that type must be Integer or Text."
)
DATESWTD_PARAMETER = "DATESWTD's parameter 1 must be a calendar reference."
TOTALWTD_PARAMETER = "TOTALWTD's parameter 2 must be a calendar reference."
DETAILROWS_MEASURE = "The input parameter for the DETAILROWS function is not a valid measure reference."


def evaluate_model(expression: str, tables: list[dict]):
    """Evaluate one measure over explicit loaded tables (the first table is the measure's home table)."""
    home = tables[0]
    return measures.evaluate_measures(
        [{"name": "Probe__", "expression": expression}], home["rows"], home["headers"], home["name"],
        measure_names=["Probe__"], table_context=tables, active_table_id=home["id"],
    )["Probe__"]


def date_model() -> list[dict]:
    return [{
        "id": "facts", "name": "Facts", "headers": ["Day"],
        "rows": [{"Day": "2020-03-15"}, {"Day": "2021-02-10"}], "column_types": {"Day": "date"},
    }]


def parent_child_model(column_type: str = "whole_number") -> list[dict]:
    rows = [{"Id": "1", "Parent": None}, {"Id": "2", "Parent": "1"}, {"Id": "3", "Parent": "2"}]
    if column_type == "text":
        rows = [{"Id": "1", "Parent": None}, {"Id": "2", "Parent": "1"}, {"Id": "3", "Parent": "2"}]
    return [{
        "id": "t", "name": "T", "headers": ["Id", "Parent"], "rows": rows,
        "column_types": {"Id": column_type, "Parent": column_type},
    }]


class MissingFunctions48Tests(unittest.TestCase):
    def assertLocalError(self, expression: str, message: str) -> None:
        self.assertEqual(f"LOCAL-REJECT:{message}", dax.local(expression), expression)

    def assertRefused(self, expression: str) -> None:
        answer = dax.local(expression)
        self.assertTrue(answer.startswith("LOCAL-REJECT:") and "not modelled by the local engine" in answer, f"{expression} -> {answer}")

    def test_all_ten_names_are_supported(self) -> None:
        for name in NAMES:
            self.assertIn(name, dax_intellisense.SUPPORTED_FUNCTIONS, name)
            self.assertIn(name, measures.DAX_FUNCTION_NAMES, name)

    def test_calendarauto_without_a_date_column_is_the_measured_error(self) -> None:
        for expression in ("CALENDARAUTO()", "CALENDARAUTO(3)", "CALENDARAUTO(13)", "CALENDARAUTO(0)", "CALENDARAUTO(Facts[Quantity])"):
            self.assertLocalError(expression, CALENDARAUTO_MISSING)
        self.assertLocalError("COUNTROWS(CALENDARAUTO())", CALENDARAUTO_MISSING)

    def test_calendarauto_over_a_date_column_gives_whole_calendar_years(self) -> None:
        # documented, not yet measured: 2020-03-15 and 2021-02-10 give 2020-01-01 to 2021-12-31 (731 days)
        self.assertEqual(731, int(evaluate_model("COUNTROWS(CALENDARAUTO())", date_model())))
        self.assertIs(True, evaluate_model("MINX(CALENDARAUTO(),[Date]) = DATE(2020,1,1)", date_model()))
        self.assertIs(True, evaluate_model("MAXX(CALENDARAUTO(),[Date]) = DATE(2021,12,31)", date_model()))

    def test_calendarauto_with_a_fiscal_year_end_month_gives_fiscal_years(self) -> None:
        # documented, not yet measured: fiscal_year_end_month 6 gives July to June years, 2019-07-01 to 2021-06-30
        self.assertEqual(731, int(evaluate_model("COUNTROWS(CALENDARAUTO(6))", date_model())))
        self.assertIs(True, evaluate_model("MINX(CALENDARAUTO(6),[Date]) = DATE(2019,7,1)", date_model()))
        self.assertIs(True, evaluate_model("MAXX(CALENDARAUTO(6),[Date]) = DATE(2021,6,30)", date_model()))

    def test_calendarauto_outside_the_range_or_on_a_column_is_refused_over_a_date_model(self) -> None:
        self.assertRefused_model("COUNTROWS(CALENDARAUTO(13))")
        self.assertRefused_model("COUNTROWS(CALENDARAUTO(Facts[Day]))")

    def assertRefused_model(self, expression: str) -> None:
        with self.assertRaises(measures.MeasureError) as context:
            evaluate_model(expression, date_model())
        self.assertIn("not modelled by the local engine", str(context.exception), expression)

    def test_approximatedistinctcount_is_the_storage_mode_error(self) -> None:
        self.assertLocalError("APPROXIMATEDISTINCTCOUNT(Facts[Quantity])", STORAGE_MODE)
        self.assertLocalError("APPROXIMATEDISTINCTCOUNT(Facts[Sales])", STORAGE_MODE)

    def test_userobjectid_is_refused_off_windows(self) -> None:
        # the Windows SID of the process user (S-1-5-18 on the guest is the SYSTEM account): not answered off Windows
        self.assertRefused("USEROBJECTID()")

    def test_selectedmeasure_errors_outside_a_calculation_item(self) -> None:
        self.assertLocalError("SELECTEDMEASURE()", NO_SELECTED_MEASURE)
        self.assertLocalError("SELECTEDMEASURENAME()", NO_SELECTED_MEASURE_NAME)
        self.assertLocalError("ISBLANK(SELECTEDMEASURENAME())", NO_SELECTED_MEASURE_NAME)

    def test_isselectedmeasure_with_a_number_is_the_input_error_and_a_measure_is_refused(self) -> None:
        self.assertLocalError("ISSELECTEDMEASURE(1)", BAD_ISSELECTED)
        self.assertRefused("ISSELECTEDMEASURE([Sales])")

    def test_path_argument_errors(self) -> None:
        self.assertLocalError("PATH(1,BLANK())", "Function Path expects a column reference as argument number 1.")
        self.assertLocalError(
            'ADDCOLUMNS(DATATABLE("id", INTEGER, "p", INTEGER, {{1, BLANK()}, {2, 1}}), "x", PATH([id],[p]))',
            "[id] is not a valid reference to a column in a table.",
        )

    def test_path_over_two_columns_of_the_guest_model_is_the_type_error(self) -> None:
        self.assertLocalError("PATH(Facts[Quantity],Facts[Quantity])", PATH_TYPES)

    def test_calendarauto_and_path_errors_are_not_caught_by_iferror_or_iserror(self) -> None:
        # live Power BI (Task 58 grid): these errors fail the whole query
        cases = ["IFERROR(CALENDARAUTO(),-1)", "IFERROR(CALENDARAUTO(1),-1)", "IFERROR(CALENDARAUTO(12),-1)", "ISERROR(CALENDARAUTO())"]
        cases += [f"ISERROR(CALENDARAUTO({n}))" for n in (-1, 1, 3, 12, 13)]
        cases += [f"IFERROR(PATH(Facts[{a}],Facts[{b}]),-1)" for a, b in (("Quantity", "Quantity"), ("Quantity", "Region"), ("Region", "Sales"), ("Sales", "Sales"))]
        cases += [f"ISERROR(PATH(Facts[{a}],Facts[{b}]))" for a, b in (("Quantity", "Note"), ("Region", "Quantity"), ("Sales", "Region"))]
        for expression in cases:
            answer = dax.local(expression)
            expected = CALENDARAUTO_MISSING if "CALENDARAUTO" in expression else PATH_TYPES
            self.assertEqual(f"LOCAL-REJECT:{expected}", answer, expression)

    def test_path_over_a_parent_child_table(self) -> None:
        # documented, not yet measured: the path from the root to the current row, joined by "|"
        model = parent_child_model()
        self.assertEqual("1;1|2;1|2|3", evaluate_model('CONCATENATEX(T, PATH(T[Id],T[Parent]), ";")', model))
        self.assertEqual(9, int(evaluate_model("SUMX(T, LEN(PATH(T[Id],T[Parent])))", model)))  # 1 + 3 + 5

    def test_path_over_a_text_parent_child_table(self) -> None:
        model = parent_child_model("text")
        self.assertEqual("1;1|2;1|2|3", evaluate_model('CONCATENATEX(T, PATH(T[Id],T[Parent]), ";")', model))

    def test_path_refuses_a_loop_and_a_missing_parent(self) -> None:
        loop = [{
            "id": "t", "name": "T", "headers": ["Id", "Parent"],
            "rows": [{"Id": "1", "Parent": "2"}, {"Id": "2", "Parent": "1"}],
            "column_types": {"Id": "whole_number", "Parent": "whole_number"},
        }]
        missing = [{
            "id": "t", "name": "T", "headers": ["Id", "Parent"],
            "rows": [{"Id": "1", "Parent": "9"}],
            "column_types": {"Id": "whole_number", "Parent": "whole_number"},
        }]
        for model in (loop, missing):
            with self.assertRaises(measures.MeasureError) as context:
                evaluate_model('CONCATENATEX(T, PATH(T[Id],T[Parent]), ";")', model)
            self.assertIn("not modelled by the local engine", str(context.exception))

    def test_path_outside_a_row_context_is_refused(self) -> None:
        with self.assertRaises(measures.MeasureError) as context:
            evaluate_model("PATH(T[Id],T[Parent])", parent_child_model())
        self.assertIn("not modelled by the local engine", str(context.exception))

    def test_datesWTD_always_needs_a_calendar(self) -> None:
        self.assertLocalError("DATESWTD(Facts[Quantity])", DATESWTD_PARAMETER)
        self.assertLocalError("COUNTROWS(DATESWTD(Facts[Sales]))", DATESWTD_PARAMETER)

    def test_totalwtd_needs_a_calendar_in_parameter_two(self) -> None:
        self.assertLocalError("TOTALWTD(SUM(Facts[Sales]),Facts[Quantity])", TOTALWTD_PARAMETER)

    def test_detailrows_argument_errors_and_a_measure_is_refused(self) -> None:
        self.assertLocalError("DETAILROWS(1)", DETAILROWS_MEASURE)
        self.assertLocalError("DETAILROWS(SUM(Facts[Sales]))", DETAILROWS_MEASURE)
        self.assertRefused("DETAILROWS([Sales])")

    def test_wrong_argument_counts_are_refused(self) -> None:
        self.assertRefused("PATH(Facts[Quantity])")
        self.assertRefused("DATESWTD()")
        self.assertRefused("CALENDARAUTO(1,2)")


if __name__ == "__main__":
    unittest.main()
