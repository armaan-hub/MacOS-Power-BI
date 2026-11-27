"""Stage D1b: convert_type (Part A step 1) hand-checked rows, named refusals, shapes and mutants.

Every expected row below is written by hand from the engine's rules (`_convert_value`, `_decimal_number_text`,
`_int64_number_text`, `_conversion_diagnostics_error`). The engine must produce them (the reference), the tool must
agree (status same), and each mutant of the tool must make the run differ (status differs, exit 1).
"""

from __future__ import annotations

import pytest

from tests.test_pq_store_diff_tool import _by_id, _engine_rows, _run_items
from tests.test_pq_store_diff_tool_d1a import _tab
from tools.pq_store_diff import (
    D1B_HEADERS,
    _d1b_catalog,
    evaluate_exit_policy,
    run_pq_step_diff_many,
)


def _convert(column: str, target: str, item_id: str | None = None) -> dict:
    return {"id": item_id or f"conv_{target}", "step": {"op": "convert_type", "column": column, "type": target}}


def _err(value: str, row: int, column: str, target: str) -> str:
    return f"Error: Cannot convert value '{value}' in row {row} of column '{column}' to {target}."


def _assert_hand_rows(dataset: dict, item: dict, expected: list[list[str | None]]) -> None:
    """The engine returns `expected` (hand check), the tool agrees (status same, no refusal)."""
    assert _engine_rows(dataset, item) == expected
    data = _run_items(dataset, [item])
    row = _by_id(data, item["id"])
    assert row["status"] == "same" and row["refusal"] is None, row
    code, _ = evaluate_exit_policy(data, {"classes": []})
    assert code == 0


def _assert_named_refusal(dataset: dict, item: dict, reason_part: str) -> None:
    """The engine accepts the step, the tool refuses by name (a named limit, not a hidden skip)."""
    data = _run_items(dataset, [item])
    row = _by_id(data, item["id"])
    assert row["status"] == "refused", row
    assert row["refusal_reason"] and reason_part in row["refusal_reason"], row


def _assert_mutant_differs_and_exits_1(dataset: dict, item: dict, mutant: str) -> None:
    # One tool call with two override sets (clean, mutant): one database build, the same comparison as two runs.
    clean, data = run_pq_step_diff_many(0, 42, [{}, {mutant: True}], dataset=dataset, items=[item])
    assert _by_id(clean, item["id"])["status"] == "same", _by_id(clean, item["id"])
    assert _by_id(data, item["id"])["status"] == "differs", f"{mutant} survived"
    code, msgs = evaluate_exit_policy(data, {"classes": []})
    assert code == 1 and any("unclassified differences" in m for m in msgs)


# ------------------------------------------------------------------ hand-checked rows (6 to 10 rows each)
# A one-column CSV drops a blank line (the engine reads an empty line as no row), so every table keeps a second
# column "k" (row label) and the blank cells sit next to it.

def _col(values: list[str]) -> dict:
    return _tab(["n", "k"], [[v, f"r{i}"] for i, v in enumerate(values, 1)])


def _col_out(outs: list[str | None]) -> list[list[str | None]]:
    return [[o, f"r{i}"] for i, o in enumerate(outs, 1)]


NUMBER_TEXT = _col([" 12 ", "1_000", "+5", "007", "-0", "1.50", "1.", ".5", "-0.50", "0.0"])
NUMBER_TEXT_OUT = _col_out(["12", "1000", "5", "7", "-0", "1.50", "1", "0.5", "-0.50", "0"])

WHOLE_TEXT = _col(["2.5", "3.5", "-2.5", "-0.5", "0.5", "1.5", "9223372036854775807", "-9223372036854775808"])
WHOLE_TEXT_OUT = _col_out(["2", "4", "-2", "0", "0", "2", "9223372036854775807", "-9223372036854775808"])

ERROR_NUMBERS = _col(["1", "", "NaN", "1,000", "12abc", " 2 ", "3"])
ERROR_NUMBERS_OUT = _col_out([
    "1", _err("", 2, "n", "decimal_number"), _err("NaN", 3, "n", "decimal_number"),
    _err("1,000", 4, "n", "decimal_number"), _err("12abc", 5, "n", "decimal_number"), "2", "3",
])

BIG_WHOLE = _col(["9223372036854775808", "-9223372036854775809", "7", "1.0", "-0.0", "0"])
BIG_WHOLE_OUT = _col_out([
    _err("9223372036854775808", 1, "n", "whole_number"),
    _err("-9223372036854775809", 2, "n", "whole_number"),
    "7", "1", "0", "0",
])

BOOLEAN_TEXT = _col(["true", " FALSE ", "TRUE", "yes", "", "1"])
BOOLEAN_TEXT_OUT = _col_out([
    "True", "False", "True", _err("yes", 4, "n", "boolean"), _err("", 5, "n", "boolean"), _err("1", 6, "n", "boolean"),
])

DATE_TEXT = _col(["2024-02-29", "2024-02-30", "0001-01-01", "9999-12-31", "", "2023-12-31"])
DATE_TEXT_OUT = _col_out([
    "2024-02-29", _err("2024-02-30", 2, "n", "date"), "0001-01-01", "9999-12-31",
    _err("", 5, "n", "date"), "2023-12-31",
])

DATETIME_TEXT = _col(["2024-02-29 10:00:00", "2024-02-29T23:59:59", "2024-02-29", "2024-02-30 10:00:00", "", "0001-01-01 00:00:00"])
DATETIME_TEXT_OUT = _col_out([
    "2024-02-29 10:00:00", "2024-02-29 23:59:59", "2024-02-29 00:00:00",
    _err("2024-02-30 10:00:00", 4, "n", "datetime"), _err("", 5, "n", "datetime"), "0001-01-01 00:00:00",
])

TIME_TEXT = _col(["10:30:15", "00:00:00", "23:59:59", "", "12:00:00"])
TIME_TEXT_OUT = _col_out(["10:30:15", "00:00:00", "23:59:59", _err("", 4, "n", "time"), "12:00:00"])


@pytest.mark.parametrize("dataset,target,expected", [
    (NUMBER_TEXT, "decimal_number", NUMBER_TEXT_OUT),
    (WHOLE_TEXT, "whole_number", WHOLE_TEXT_OUT),
    (ERROR_NUMBERS, "decimal_number", ERROR_NUMBERS_OUT),
    (BIG_WHOLE, "whole_number", BIG_WHOLE_OUT),
    (BOOLEAN_TEXT, "boolean", BOOLEAN_TEXT_OUT),
    (DATE_TEXT, "date", DATE_TEXT_OUT),
    (DATETIME_TEXT, "datetime", DATETIME_TEXT_OUT),
    (TIME_TEXT, "time", TIME_TEXT_OUT),
])
def test_convert_hand_checked_rows(dataset: dict, target: str, expected: list) -> None:
    _assert_hand_rows(dataset, _convert("n", target), expected)


def test_convert_number_precision_and_number_alias_hand_checked() -> None:
    # "number" is the engine's alias for decimal_number; the same rows come out of both.
    _assert_hand_rows(NUMBER_TEXT, _convert("n", "number"), NUMBER_TEXT_OUT)


def test_convert_identity_types_hand_checked() -> None:
    # text and any keep every cell as it is (blank stays blank, not an error).
    t = _col([" pad ", "", "a'b", "x"])
    _assert_hand_rows(t, _convert("n", "text"), _col_out([" pad ", "", "a'b", "x"]))
    _assert_hand_rows(t, _convert("n", "any"), _col_out([" pad ", "", "a'b", "x"]))


# ------------------------------------------------------------------ named refusals (the engine accepts the step)

def test_convert_exponent_text_is_a_named_refusal() -> None:
    t = _tab(["n"], [["1e3"], ["7"], ["2.5E-1"]])
    _assert_named_refusal(t, _convert("n", "decimal_number"), "Exponent number text")


def test_convert_long_digits_are_a_named_refusal() -> None:
    t = _tab(["n"], [["123456789012345678901234567890"], ["5"]])
    _assert_named_refusal(t, _convert("n", "whole_number"), "DECIMAL(38,18)")


def test_convert_decimal_below_1e6_is_a_named_refusal_but_whole_is_mapped() -> None:
    t = _tab(["n"], [["0.0000001"], ["5"], ["0.5"]])
    _assert_named_refusal(t, _convert("n", "decimal_number"), "exponent form")
    _assert_hand_rows(t, _convert("n", "whole_number"), [["0"], ["5"], ["0"]])


def test_convert_non_ascii_digits_are_a_named_refusal() -> None:
    t = _col(["٣", "5"])
    _assert_named_refusal(t, _convert("n", "decimal_number"), "printable ASCII")


def test_convert_non_iso_dates_are_a_named_refusal() -> None:
    t = _tab(["n"], [["2024-02-29"], ["20240229"]])
    _assert_named_refusal(t, _convert("n", "date"), "yyyy-mm-dd")


def test_convert_earlier_error_text_is_a_named_refusal() -> None:
    t = _tab(["n"], [["Error: x"], ["yes"]])
    _assert_named_refusal(t, _convert("n", "boolean"), "error prefix")


def test_convert_quote_in_value_is_a_named_refusal_for_error_text() -> None:
    t = _tab(["n"], [["a'b"], ["5"]])
    _assert_named_refusal(t, _convert("n", "decimal_number"), "printable ASCII")


# ------------------------------------------------------------------ shapes: missing column, bad type, extra field

def test_convert_missing_column_and_bad_type_use_the_engine_text() -> None:
    t = _tab(["n"], [["1"], ["2"]])
    for item, engine_text in [
        (_convert("zz", "whole_number", "miss"), "Column 'zz' does not exist."),
        ({"id": "bad", "step": {"op": "convert_type", "column": "n", "type": "bogus"}}, "has an unsupported column type."),
    ]:
        data = _run_items(t, [item])
        row = _by_id(data, item["id"])
        assert row["status"] == "same" and row["refusal_reason"] and engine_text in row["refusal_reason"], row


def test_convert_extra_field_is_refused_with_the_engine_shape_text() -> None:
    t = _tab(["n"], [["1"]])
    item = {"id": "extra", "step": {"op": "convert_type", "column": "n", "type": "whole_number", "culture": "en-US"}}
    row = _by_id(_run_items(t, [item]), "extra")
    assert row["status"] == "same" and "has missing or unsupported fields." in (row["refusal_reason"] or ""), row


def test_convert_shapes_empty_one_row_and_all_blank() -> None:
    empty = _tab(["n"], [])
    _assert_hand_rows(empty, _convert("n", "decimal_number"), [])
    one = _tab(["n"], [["7 "]])
    _assert_hand_rows(one, _convert("n", "whole_number"), [["7"]])
    blank = _tab(["n", "d"], [["", "x"], ["", "y"], ["", "z"]])
    _assert_hand_rows(blank, _convert("n", "decimal_number"), [[_err("", i, "n", "decimal_number"), v] for i, v in ((1, "x"), (2, "y"), (3, "z"))])


# ------------------------------------------------------------------ mutants (one rule each, behaviour on hand tables)

CONVERT_MUTANTS = [
    ("mutant_convert_no_trim", NUMBER_TEXT, "decimal_number"),
    ("mutant_convert_no_underscore", NUMBER_TEXT, "decimal_number"),
    ("mutant_convert_keep_leading_zeros", NUMBER_TEXT, "decimal_number"),
    ("mutant_convert_strip_fraction_zeros", NUMBER_TEXT, "decimal_number"),
    ("mutant_convert_zero_unsigned", NUMBER_TEXT, "decimal_number"),
    ("mutant_convert_whole_half_up", WHOLE_TEXT, "whole_number"),
    ("mutant_convert_whole_no_range", BIG_WHOLE, "whole_number"),
    ("mutant_convert_bool_case_sensitive", BOOLEAN_TEXT, "boolean"),
    ("mutant_convert_date_no_validity", DATE_TEXT, "date"),
    ("mutant_convert_blank_is_null", ERROR_NUMBERS, "decimal_number"),
    ("mutant_convert_error_row_plus_one", ERROR_NUMBERS, "decimal_number"),
    ("mutant_convert_error_column_unquoted", ERROR_NUMBERS, "decimal_number"),
]


@pytest.mark.parametrize("mutant,dataset,target", CONVERT_MUTANTS, ids=[m for m, _, _ in CONVERT_MUTANTS])
def test_convert_mutant_differs_and_exits_1(mutant: str, dataset: dict, target: str) -> None:
    _assert_mutant_differs_and_exits_1(dataset, _convert("n", target), mutant)


# ------------------------------------------------------------------ mutants at tool level (generated D1b table)

CONVERT_TOOL_MUTANTS = [
    "mutant_convert_no_trim", "mutant_convert_no_underscore", "mutant_convert_keep_leading_zeros",
    "mutant_convert_strip_fraction_zeros", "mutant_convert_zero_unsigned", "mutant_convert_whole_half_up",
    "mutant_convert_whole_no_range", "mutant_convert_bool_case_sensitive", "mutant_convert_date_no_validity",
    "mutant_convert_blank_is_null", "mutant_convert_error_row_plus_one", "mutant_convert_error_column_unquoted",
]
CONVERT_TOOL_ITEM_IDS = [
    "d1b_conv_b_num_decimal_number", "d1b_conv_b_num_whole_number", "d1b_conv_b_round_whole_number",
    "d1b_conv_b_tiny_whole_number", "d1b_conv_b_bool_boolean", "d1b_conv_b_date_date", "d1b_conv_b_dt_datetime",
    "d1b_conv_b_time_time", "d1b_conv_blank_cells_number",
]


@pytest.mark.parametrize("rows,seed", [(50, 42), (400, 1), (2000, 7)])
def test_d1b_convert_tool_level_mutants_exit_1_on_generated_data(rows: int, seed: int) -> None:
    items = [i for i in _d1b_catalog() if i["id"] in set(CONVERT_TOOL_ITEM_IDS)]
    clean_run, *mutant_runs = run_pq_step_diff_many(rows, seed, [{}] + [{m: True} for m in CONVERT_TOOL_MUTANTS], items=items)
    refusals = [r["id"] for r in clean_run["results"] if r["refusal"]]
    code, _ = evaluate_exit_policy(clean_run, {"classes": [], "refused": refusals})
    assert code == 0, f"clean D1b convert run failed at {rows}/{seed}"
    assert all(_by_id(clean_run, i)["status"] == "same" for i in CONVERT_TOOL_ITEM_IDS), f"clean not same at {rows}/{seed}"
    for mutant, data in zip(CONVERT_TOOL_MUTANTS, mutant_runs):
        code, _ = evaluate_exit_policy(data, {"classes": [], "refused": refusals})
        assert code == 1, f"{mutant} did not exit 1 at {rows}/{seed}"


def test_d1b_headers_are_the_generated_columns() -> None:
    assert D1B_HEADERS[0] == "b_num" and D1B_HEADERS[-1] == "b_grp" and len(D1B_HEADERS) == 13


# ------------------------------------------------------------------ convert_type_using_locale (en-US numbers)

def _err_us(value: str, row: int, column: str, target: str) -> str:
    return f"Error: Cannot convert value '{value}' in row {row} of column '{column}' to {target} using culture en-US."


def _locale(column: str, target: str, culture: str = "en-US") -> dict:
    return {"id": f"loc_{target}", "step": {"op": "convert_type_using_locale", "column": column, "type": target, "culture": culture}}


LOCALE_NUMBERS = _col(["1,000", "12,345.50", "-1,234,567", "1,0000", "+1,000", "1.", " 007 ", "1,000,000.25", "1,000.", "2.5"])
LOCALE_DECIMAL_OUT = _col_out([
    "1000", "12345.50", "-1234567", _err_us("1,0000", 4, "n", "decimal_number"), _err_us("+1,000", 5, "n", "decimal_number"),
    "1", "7", "1000000.25", _err_us("1,000.", 9, "n", "decimal_number"), "2.5",
])
LOCALE_WHOLE_OUT = _col_out([
    "1000", "12346", "-1234567", _err_us("1,0000", 4, "n", "whole_number"), _err_us("+1,000", 5, "n", "whole_number"),
    "1", "7", "1000000", _err_us("1,000.", 9, "n", "whole_number"), "2",
])


def test_locale_en_us_decimal_and_whole_hand_checked() -> None:
    _assert_hand_rows(LOCALE_NUMBERS, _locale("n", "decimal_number"), LOCALE_DECIMAL_OUT)
    _assert_hand_rows(LOCALE_NUMBERS, _locale("n", "whole_number"), LOCALE_WHOLE_OUT)


def test_locale_culture_is_canonicalised_before_the_message() -> None:
    # "en_us" is the engine's canonical en-US: the same rows, with the canonical name in the error text.
    _assert_hand_rows(LOCALE_NUMBERS, _locale("n", "decimal_number", "en_us"), LOCALE_DECIMAL_OUT)


def test_locale_padded_column_name_is_stripped_by_the_engine() -> None:
    t = _col(["1,000"])
    t["headers"] = [" n ", "k"]
    _assert_hand_rows(t, _locale(" n ", "decimal_number"), _col_out(["1000"]))


def test_locale_shapes_and_culture_errors_use_the_engine_text() -> None:
    t = _col(["1"])
    for item, engine_text in [
        (_locale("zz", "whole_number"), "Column 'zz' does not exist."),
        (_locale("n", "decimal_number", "bogus"), "is not recognized."),
        (_locale("n", "text"), "has an unsupported locale-aware column type."),
    ]:
        row = _by_id(_run_items(t, [item]), item["id"])
        assert row["status"] == "same" and engine_text in (row["refusal_reason"] or ""), row


def test_locale_other_cultures_and_types_are_named_refusals() -> None:
    t = _col(["1", "2"])
    _assert_named_refusal(t, _locale("n", "decimal_number", "de-DE"), "en-US only")
    _assert_named_refusal(t, _locale("n", "date", "en-US"), "numbers only")
    t_exp = _col(["1e3", "2"])
    _assert_named_refusal(t_exp, _locale("n", "decimal_number"), "Exponent or underscore")


LOCALE_MUTANTS = [
    ("mutant_locale_keeps_commas", LOCALE_NUMBERS, "decimal_number"),
    ("mutant_locale_message_no_culture", LOCALE_NUMBERS, "decimal_number"),
    ("mutant_convert_whole_half_up", LOCALE_NUMBERS, "whole_number"),
]


@pytest.mark.parametrize("mutant,dataset,target", LOCALE_MUTANTS, ids=[m for m, _, _ in LOCALE_MUTANTS])
def test_locale_mutant_differs_and_exits_1(mutant: str, dataset: dict, target: str) -> None:
    _assert_mutant_differs_and_exits_1(dataset, _locale("n", target), mutant)


@pytest.mark.parametrize("rows,seed", [(50, 42), (400, 1), (2000, 7)])
def test_d1b_locale_tool_level_mutants_exit_1_on_generated_data(rows: int, seed: int) -> None:
    ids = ["d1b_loc_b_grp_decimal_number", "d1b_loc_b_grp_whole_number"]
    mutants = ["mutant_locale_keeps_commas", "mutant_locale_message_no_culture", "mutant_convert_whole_half_up"]
    items = [i for i in _d1b_catalog() if i["id"] in set(ids)]
    clean_run, *mutant_runs = run_pq_step_diff_many(rows, seed, [{}] + [{m: True} for m in mutants], items=items)
    refusals = [r["id"] for r in clean_run["results"] if r["refusal"]]
    code, _ = evaluate_exit_policy(clean_run, {"classes": [], "refused": refusals})
    assert code == 0, f"clean D1b locale run failed at {rows}/{seed}"
    assert all(_by_id(clean_run, i)["status"] == "same" for i in ids), f"locale clean not same at {rows}/{seed}"
    for mutant, data in zip(mutants, mutant_runs):
        code, _ = evaluate_exit_policy(data, {"classes": [], "refused": refusals})
        assert code == 1, f"{mutant} did not exit 1 at {rows}/{seed}"


# ------------------------------------------------------------------ sparse rows (Part A step 5) and pass-through (step 6)

# A row whose cells are all "" is dropped on import (the engine's CSV rule), so the table holds no all-blank row:
# sparse rows are one-value rows and whitespace-only rows.
SPARSE_ROWS = _tab(["a", "b", "c"], [
    ["x", "", ""], [" ", "  ", ""], ["1", "2", "3"], ["q", "", ""], ["4", "5", ""], [" ", "", "w"], ["", "r", ""],
])
SPARSE_TOP_OUT = [["1", "2", "3"], ["q", "", ""], ["4", "5", ""], [" ", "", "w"], ["", "r", ""]]
SPARSE_BOTTOM_OUT = [["x", "", ""], [" ", "  ", ""], ["1", "2", "3"], ["q", "", ""], ["4", "5", ""]]


def test_sparse_top_and_bottom_hand_checked() -> None:
    _assert_hand_rows(SPARSE_ROWS, {"id": "top", "step": {"op": "remove_sparse_top_rows"}}, SPARSE_TOP_OUT)
    _assert_hand_rows(SPARSE_ROWS, {"id": "bottom", "step": {"op": "remove_sparse_bottom_rows"}}, SPARSE_BOTTOM_OUT)


def test_sparse_all_none_and_one_row_hand_checked() -> None:
    all_sparse = _tab(["a", "b"], [["x", ""], ["", " "]])
    _assert_hand_rows(all_sparse, {"id": "top", "step": {"op": "remove_sparse_top_rows"}}, [])
    _assert_hand_rows(all_sparse, {"id": "bottom", "step": {"op": "remove_sparse_bottom_rows"}}, [])
    full = _tab(["a", "b"], [["1", "2"], ["3", "4"]])
    _assert_hand_rows(full, {"id": "top", "step": {"op": "remove_sparse_top_rows"}}, [["1", "2"], ["3", "4"]])
    _assert_hand_rows(full, {"id": "bottom", "step": {"op": "remove_sparse_bottom_rows"}}, [["1", "2"], ["3", "4"]])
    one = _tab(["a", "b"], [["1", ""]])
    _assert_hand_rows(one, {"id": "top", "step": {"op": "remove_sparse_top_rows"}}, [])


def test_sparse_extra_field_is_refused_with_the_engine_shape_text() -> None:
    row = _by_id(_run_items(SPARSE_ROWS, [{"id": "x", "step": {"op": "remove_sparse_top_rows", "column": "a"}}]), "x")
    assert row["status"] == "same" and "has missing or unsupported fields." in (row["refusal_reason"] or ""), row


def test_pass_through_hand_checked_and_extra_fields_ignored() -> None:
    _assert_hand_rows(SPARSE_ROWS, {"id": "p", "step": {"op": "table_pass_through"}}, SPARSE_ROWS["rows"])
    _assert_hand_rows(SPARSE_ROWS, {"id": "p", "step": {"op": "table_pass_through", "column": "zz"}}, SPARSE_ROWS["rows"])


SPARSE_MUTANTS = [
    ("mutant_sparse_at_most_zero", SPARSE_ROWS, {"id": "top", "step": {"op": "remove_sparse_top_rows"}}),
    ("mutant_sparse_drops_first", SPARSE_ROWS, {"id": "top", "step": {"op": "remove_sparse_top_rows"}}),
]


@pytest.mark.parametrize("mutant,dataset,item", SPARSE_MUTANTS, ids=[m for m, _, _ in SPARSE_MUTANTS])
def test_sparse_mutant_differs_and_exits_1(mutant: str, dataset: dict, item: dict) -> None:
    _assert_mutant_differs_and_exits_1(dataset, item, mutant)


@pytest.mark.parametrize("rows,seed", [(50, 42), (400, 1), (2000, 7)])
def test_d1b_sparse_tool_level_mutants_exit_1_on_generated_data(rows: int, seed: int) -> None:
    ids = ["d1b_sparse_top_generated", "d1b_sparse_bottom_generated"]
    mutants = ["mutant_sparse_at_most_zero", "mutant_sparse_drops_first"]
    items = [i for i in _d1b_catalog() if i["id"] in set(ids)]
    clean_run, *mutant_runs = run_pq_step_diff_many(rows, seed, [{}] + [{m: True} for m in mutants], items=items)
    refusals = [r["id"] for r in clean_run["results"] if r["refusal"]]
    code, _ = evaluate_exit_policy(clean_run, {"classes": [], "refused": refusals})
    assert code == 0, f"clean D1b sparse run failed at {rows}/{seed}"
    for mutant, data in zip(mutants, mutant_runs):
        code, _ = evaluate_exit_policy(data, {"classes": [], "refused": refusals})
        assert code == 1, f"{mutant} did not exit 1 at {rows}/{seed}"
