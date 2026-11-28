"""Stage D1g fix pass 2: end-to-end tests of the pivot refusals through the real tool run (engine versus store).

Every rule has a hand-checked table of 6 to 10 rows and is run through `run_pq_step_diff` with an explicit dataset, so a
wrong refusal text AND a wrong value both show (a status other than the expected one). Each refusal also has a
"must still run" test: a table the refusal must NOT stop. No test depends on another test, on the order of tests or
on the pytest-xdist worker (every run makes its own temporary store).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pytest

from tools import pq_store_diff
from tools.pq_store_diff import (
    D1E_ROWS,
    TYPE_KEEPING_OPS,
    _follow_column_types,
    generate_d1e_csv,
    run_pq_step_diff,
)

CONVERT_DECIMAL = {"op": "convert_type", "column": "k", "type": "decimal_number"}
KEEP_TOP = {"op": "keep_top_rows", "count": 9}


def _conv(column: str, kind: str) -> dict[str, Any]:
    return {"op": "convert_type", "column": column, "type": kind}


def _piv(attr: str = "attr", value: str = "val", agg: str = "count_all") -> dict[str, Any]:
    return {"op": "pivot_column", "attribute_column": attr, "value_column": value, "aggregation": agg}


def _unpivot(columns: list[str], other: bool = False) -> dict[str, Any]:
    return {
        "op": "unpivot_other_columns" if other else "unpivot_columns",
        "columns": columns, "attribute_name": "at", "value_name": "v",
    }


def _run(headers: list[str], rows: list[list[str]], steps: list[dict[str, Any]]) -> dict[str, Any]:
    """One sequence through the tool; returns the single result."""
    item = {"id": "case", "step": {"op": "sequence"}, "sequence": steps}
    data = run_pq_step_diff(rows=len(rows), seed=1, dataset={"headers": headers, "rows": rows}, items=[item])
    assert len(data["results"]) == 1
    return data["results"][0]


def _outcome(res: dict[str, Any]) -> str:
    """"ran" (both ran, equal), "both-reject: <text>" (both refused or raised the same), else "<status>: <reason>"."""
    if res["status"] == "same":
        text = str(res.get("refusal") or "")
        return "ran" if not text else "both-reject: " + text.removeprefix("REFUSED: ")
    return f"{res['status']}: {res.get('diff_reason')}"


KEY_MERGE = "text forms differ"
ISO_T = "ISO 'T' formatting"
CONFLICT = "distinct typed categories"


# ---------------------------------------------------------------- F1: decimal keys whose text forms differ

ZERO_ROWS = [["0", "a", "1"], ["-0", "b", "2"], ["1", "a", "3"], ["1", "b", "4"], ["2", "a", "5"], ["2", "b", "6"]]
FORMS_ROWS = [["1.0", "a", "1"], ["1.00", "b", "2"], ["2", "a", "3"], ["2", "b", "4"], ["3", "a", "5"], ["3", "b", "6"]]


def test_f1_zero_and_negative_zero_keys_are_one_group_in_the_engine_so_the_store_refuses() -> None:
    # Engine: 0 and -0 are one key (3 rows: 0, 1, 2); the text GROUP BY would give 4 rows.
    out = _outcome(_run(["k", "attr", "val"], ZERO_ROWS, [CONVERT_DECIMAL, _piv()]))
    assert out.startswith("refused") and KEY_MERGE in out, out


@pytest.mark.parametrize("between", [[], [KEEP_TOP], [{"op": "remove_blank_rows"}, KEEP_TOP]], ids=["adjacent", "keep_top", "two_steps"])
def test_f1_decimal_keys_1_0_and_1_00_are_refused_also_when_other_steps_follow_the_convert(between: list[dict[str, Any]]) -> None:
    # Engine: 1.0 and 1.00 are one key, so 3 rows; the text GROUP BY would give 4.
    out = _outcome(_run(["k", "attr", "val"], FORMS_ROWS, [CONVERT_DECIMAL, *between, _piv()]))
    assert out.startswith("refused") and KEY_MERGE in out, out


def test_f1_number_type_name_is_a_decimal_key_too() -> None:
    out = _outcome(_run(["k", "attr", "val"], FORMS_ROWS, [_conv("k", "number"), KEEP_TOP, _piv()]))
    assert out.startswith("refused") and KEY_MERGE in out, out


def test_f1_second_key_column_is_checked_too() -> None:
    rows = [["x", "1.0", "a", "1"], ["x", "1.00", "b", "2"], ["y", "2", "a", "3"], ["y", "2", "b", "4"], ["z", "3", "a", "5"], ["z", "3", "b", "6"]]
    out = _outcome(_run(["k0", "k", "attr", "val"], rows, [CONVERT_DECIMAL, _piv()]))
    assert out.startswith("refused") and KEY_MERGE in out, out


def test_f1_decimal_key_kept_through_an_unpivot_is_checked() -> None:
    rows = [["1.0", "a", "b"], ["1.00", "a", "c"], ["2", "d", "b"], ["2", "d", "c"], ["3", "e", "b"], ["3", "e", "c"]]
    steps = [_conv("id", "decimal_number"), _unpivot(["A", "B"]), _piv("at", "v")]
    out = _outcome(_run(["id", "A", "B"], rows, steps))
    assert out.startswith("refused") and KEY_MERGE in out, out


@pytest.mark.parametrize("between", [[], [KEEP_TOP]], ids=["adjacent", "keep_top"])
def test_f1_decimal_keys_with_one_text_form_per_value_still_run(between: list[dict[str, Any]]) -> None:
    rows = [["7", "a", "1"], ["8", "b", "2"], ["7", "b", "3"], ["8.5", "a", "4"], ["9", "a", "5"], ["8", "a", "6"]]
    assert _outcome(_run(["k", "attr", "val"], rows, [CONVERT_DECIMAL, *between, _piv()])) == "ran"


@pytest.mark.parametrize("between", [[], [KEEP_TOP]], ids=["adjacent", "keep_top"])
def test_f1_engine_key_error_text_wins_over_the_key_refusal(between: list[dict[str, Any]]) -> None:
    rows = [["1.0", "a", "1"], ["abc", "b", "2"], ["1.00", "a", "3"], ["2", "b", "4"], ["2", "a", "5"], ["3", "b", "6"]]
    out = _outcome(_run(["k", "attr", "val"], rows, [CONVERT_DECIMAL, *between, _piv()]))
    assert out == "both-reject: Cannot pivot: row 2 of key column 'k' contains an error.", out


# ---------------------------------------------------------------- F4: typed categories through an unpivot

UNPIVOT_HEADERS = ["id", "A", "B"]


def test_f4_decimal_and_text_with_the_same_text_conflict_like_the_engine() -> None:
    # unpivot rows: (r1,A)=Decimal 1.0, (r1,B)='1.0' text: same output name, two kinds.
    rows = [["r1", "1.0", "1.0"], ["r2", "2", "x"], ["r3", "3", "y"], ["r4", "4", "z"]]
    out = _outcome(_run(UNPIVOT_HEADERS, rows, [_conv("A", "decimal_number"), _unpivot(["A", "B"]), _piv("v", "at")]))
    assert out.startswith("both-reject: Cannot pivot: distinct typed categories") and "'1.0'" in out, out


@pytest.mark.parametrize(
    "kind,rows,convert_b,other",
    [
        ("number", [["r1", "1.0", "1.0"], ["r2", "2", "x"], ["r3", "3", "y"]], False, False),
        ("whole_number", [["r1", "1", "1"], ["r2", "2", "x"], ["r3", "3", "y"]], False, True),
        ("time", [["r1", "01:02:03", "01:02:03"], ["r2", "04:05:06", "x"], ["r3", "07:08:09", "y"]], False, False),
        ("whole_number", [["r1", "1", "1"], ["r2", "2", "x"], ["r3", "3", "y"]], True, False),
    ],
    ids=["number_name", "unpivot_other_columns", "time", "only_B_converted"],
)
def test_f4_typed_and_text_categories_conflict_for_each_type_and_unpivot_form(kind: str, rows: list[list[str]], convert_b: bool, other: bool) -> None:
    converted = "B" if convert_b else "A"
    unpivot = _unpivot(["id"], other=True) if other else _unpivot(["A", "B"])
    out = _outcome(_run(UNPIVOT_HEADERS, rows, [_conv(converted, kind), unpivot, _piv("v", "at")]))
    assert out.startswith("both-reject: Cannot pivot: distinct typed categories"), out


def test_f4_conflict_before_a_later_blank_is_the_error_like_the_engine() -> None:
    # unpivot rows: 1 (r1,A)=1.0 decimal, 2 (r1,B)='1.0' text -> conflict at row 2; row 4 (r2,B) is blank.
    rows = [["r1", "1.0", "1.0"], ["r2", "2", ""], ["r3", "3", "y"], ["r4", "4", "z"]]
    out = _outcome(_run(UNPIVOT_HEADERS, rows, [_conv("A", "decimal_number"), _unpivot(["A", "B"]), _piv("v", "at")]))
    assert out.startswith("both-reject: Cannot pivot: distinct typed categories"), out


def test_f4_blank_before_a_later_conflict_is_the_error_like_the_engine() -> None:
    # row 2 (r1,B) is blank; the conflict '1' decimal versus '1' text comes later at rows 3 and 4.
    rows = [["r1", "5", ""], ["r2", "1", "1"], ["r3", "3", "y"], ["r4", "4", "z"]]
    out = _outcome(_run(UNPIVOT_HEADERS, rows, [_conv("A", "whole_number"), _unpivot(["A", "B"]), _piv("v", "at")]))
    assert out == "both-reject: Cannot pivot: row 2 has a blank value in 'v'.", out


def test_f4_error_cell_before_a_later_conflict_is_the_error_like_the_engine() -> None:
    # (r1,A)='abc' does not convert to a decimal: an error cell at unpivot row 1; the conflict comes at rows 3 and 4.
    rows = [["r1", "abc", "x"], ["r2", "1.0", "1.0"], ["r3", "3", "y"], ["r4", "4", "z"]]
    out = _outcome(_run(UNPIVOT_HEADERS, rows, [_conv("A", "decimal_number"), _unpivot(["A", "B"]), _piv("v", "at")]))
    assert out == "both-reject: Cannot pivot: row 1 of 'v' contains an error.", out


def test_f4_blank_attribute_cell_through_an_unpivot_is_the_engine_error() -> None:
    rows = [["r1", "1", ""], ["r2", "2", "x"], ["r3", "3", "y"], ["r4", "4", "z"]]
    out = _outcome(_run(UNPIVOT_HEADERS, rows, [_conv("A", "whole_number"), _unpivot(["A", "B"]), _piv("v", "at")]))
    assert out == "both-reject: Cannot pivot: row 2 has a blank value in 'v'.", out


@pytest.mark.parametrize(
    "convert,rows",
    [
        # the same decimal value written the same way in two columns is one category, not a conflict
        ([_conv("A", "decimal_number"), _conv("B", "decimal_number")], [["r1", "1.5", "1.5"], ["r2", "2", "3"], ["r3", "4", "5"], ["r4", "6", "7"]]),
        # a decimal and a text with different texts never share an output column
        ([_conv("A", "decimal_number")], [["r1", "1.5", "x"], ["r2", "2", "y"], ["r3", "3", "z"], ["r4", "4", "w"]]),
        # text columns only: equal text is one category
        ([_conv("A", "text")], [["r1", "1", "1"], ["r2", "2", "x"], ["r3", "3", "y"], ["r4", "4", "z"]]),
    ],
    ids=["same_decimal_twice", "different_texts", "text_only"],
)
def test_f4_repeated_categories_that_are_not_a_typed_conflict_still_run(convert: list[dict[str, Any]], rows: list[list[str]]) -> None:
    assert _outcome(_run(UNPIVOT_HEADERS, rows, [*convert, _unpivot(["A", "B"]), _piv("v", "at")])) == "ran"


def test_f4_a_typed_value_column_is_not_a_conflict_when_the_attribute_is_the_unpivot_name() -> None:
    rows = [["r1", "1", "1"], ["r2", "2", "x"], ["r3", "3", "y"], ["r4", "4", "z"]]
    assert _outcome(_run(UNPIVOT_HEADERS, rows, [_conv("A", "whole_number"), _unpivot(["A", "B"]), _piv("at", "v")])) == "ran"


# ---------------------------------------------------------------- F5 and P35: datetime and boolean attributes

DT_OK = [["a", "2024-01-02 03:04:05", "1"], ["b", "2024-01-04", "2"], ["c", "2024-01-02 03:04:05", "3"], ["d", "2024-01-05", "4"], ["e", "2024-01-04", "5"], ["f", "2024-01-05", "6"]]
DT_BAD = [["a", "2024-01-02 03:04:05", "1"], ["b", "2024-13-45 00:00:00", "2"], ["c", "2024-01-03", "3"], ["d", "2024-01-05", "4"], ["e", "2024-01-04", "5"], ["f", "2024-01-05", "6"]]
BOOL_OK = [["a", "true", "1"], ["b", "false", "2"], ["c", "true", "3"], ["d", "false", "4"], ["e", "true", "5"], ["f", "false", "6"]]
BOOL_BAD = [["a", "true", "1"], ["b", "oops", "2"], ["c", "false", "3"], ["d", "true", "4"], ["e", "false", "5"], ["f", "true", "6"]]


def test_f5_datetime_attribute_is_refused_by_name_when_the_engine_would_succeed() -> None:
    out = _outcome(_run(["k", "attr", "val"], DT_OK, [_conv("attr", "datetime"), _piv()]))
    assert out.startswith("refused") and ISO_T in out, out


def test_f5_datetime_attribute_through_an_unpivot_is_refused_by_name() -> None:
    rows = [["r1", "2024-01-02 03:04:05", "x"], ["r2", "2024-01-03", "y"], ["r3", "2024-01-04", "z"], ["r4", "2024-01-05", "w"]]
    out = _outcome(_run(UNPIVOT_HEADERS, rows, [_conv("A", "datetime"), _unpivot(["A", "B"]), _piv("v", "at")]))
    assert out.startswith("refused") and ISO_T in out, out


def test_f5_engine_error_wins_over_the_datetime_refusal() -> None:
    # '2024-13-45 00:00:00' has the strict shape but is no date: an error cell in the attribute, row 2.
    out = _outcome(_run(["k", "attr", "val"], DT_BAD, [_conv("attr", "datetime"), _piv()]))
    assert out == "both-reject: Cannot pivot: row 2 of 'attr' contains an error.", out


def test_f5_engine_error_wins_over_the_datetime_refusal_through_an_unpivot() -> None:
    rows = [["r1", "2024-01-02 03:04:05", "2024-01-03"], ["r2", "2024-13-45 00:00:00", "2024-01-03"], ["r3", "2024-01-04", "2024-01-05"], ["r4", "2024-01-05", "2024-01-06"]]
    out = _outcome(_run(UNPIVOT_HEADERS, rows, [_conv("A", "datetime"), _conv("B", "datetime"), _unpivot(["A", "B"]), _piv("v", "at")]))
    assert out == "both-reject: Cannot pivot: row 3 of 'v' contains an error.", out


def test_p35_boolean_attribute_is_refused_by_name_when_the_engine_would_succeed() -> None:
    out = _outcome(_run(["k", "attr", "val"], BOOL_OK, [_conv("attr", "boolean"), _piv()]))
    assert out.startswith("refused") and "TRUE or FALSE" in out, out


def test_p35_engine_error_wins_over_the_boolean_refusal() -> None:
    out = _outcome(_run(["k", "attr", "val"], BOOL_BAD, [_conv("attr", "boolean"), _piv()]))
    assert out == "both-reject: Cannot pivot: row 2 of 'attr' contains an error.", out


def test_p35_engine_error_wins_over_the_boolean_refusal_through_an_unpivot() -> None:
    rows = [["r1", "true", "x"], ["r2", "oops", "y"], ["r3", "false", "z"], ["r4", "true", "w"]]
    out = _outcome(_run(UNPIVOT_HEADERS, rows, [_conv("A", "boolean"), _unpivot(["A", "B"]), _piv("v", "at")]))
    assert out == "both-reject: Cannot pivot: row 3 of 'v' contains an error.", out


@pytest.mark.parametrize(
    "kind,rows",
    [
        ("date", [["a", "2024-01-02", "1"], ["b", "2024-01-04", "2"], ["c", "2024-01-02", "3"], ["d", "2024-01-05", "4"], ["e", "2024-01-04", "5"], ["f", "2024-01-05", "6"]]),
        ("time", [["a", "01:02:03", "1"], ["b", "04:05:06", "2"], ["c", "01:02:03", "3"], ["d", "07:08:09", "4"], ["e", "04:05:06", "5"], ["f", "07:08:09", "6"]]),
        ("whole_number", [["a", "01", "1"], ["b", "2", "2"], ["c", "1", "3"], ["d", "3", "4"], ["e", "2", "5"], ["f", "3", "6"]]),
        ("text", [["a", "2024-01-02", "1"], ["b", "x", "2"], ["c", "2024-01-02", "3"], ["d", "y", "4"], ["e", "x", "5"], ["f", "y", "6"]]),
    ],
)
def test_attributes_that_are_not_datetime_or_boolean_still_run(kind: str, rows: list[list[str]]) -> None:
    assert _outcome(_run(["k", "attr", "val"], rows, [_conv("attr", kind), _piv()])) == "ran"


def test_date_attribute_through_an_unpivot_still_runs() -> None:
    rows = [["r1", "2024-01-02", "2024-01-03"], ["r2", "2024-01-04", "2024-01-05"], ["r3", "2024-01-02", "2024-01-05"], ["r4", "2024-01-06", "2024-01-03"]]
    steps = [_conv("A", "date"), _conv("B", "date"), _unpivot(["A", "B"]), _piv("v", "at")]
    assert _outcome(_run(UNPIVOT_HEADERS, rows, steps)) == "ran"


def test_f3_text_converted_attribute_with_error_prefix_text_runs() -> None:
    # After convert_type to text the text 'Error: raw' is plain text in the engine (no error cell): the pivot runs.
    rows = [["a", "Error: raw", "1"], ["b", "x", "2"], ["c", "Error: raw", "3"], ["d", "y", "4"], ["e", "x", "5"], ["f", "y", "6"]]
    assert _outcome(_run(["k", "attr", "val"], rows, [_conv("attr", "text"), _piv()])) == "ran"


# ---------------------------------------------------------------- P04, P21, P29: the plain pivot rules end to end

def test_p04_key_columns_keep_the_header_order() -> None:
    rows = [["z1", "a1", "x", "1"], ["z2", "a2", "y", "2"], ["z1", "a1", "y", "3"], ["z2", "a2", "x", "4"], ["z3", "a3", "x", "5"], ["z3", "a3", "y", "6"]]
    assert _outcome(_run(["zk", "ak", "attr", "val"], rows, [_piv()])) == "ran"


def test_p21_non_ascii_first_key_is_refused_by_name() -> None:
    # Python case folding puts 'ß' (folds to 'ss') between 'sr' and 'st'; a SQL lower() puts it last.
    rows = [["ß", "x", "1"], ["sr", "x", "2"], ["st", "y", "3"], ["ß", "y", "4"], ["sr", "y", "5"], ["st", "x", "6"]]
    out = _outcome(_run(["k", "attr", "val"], rows, [_piv()]))
    assert out.startswith("refused") and "non-ASCII" in out, out


def test_p29_category_with_a_double_quote_is_refused_by_name() -> None:
    rows = [["k1", 'q"q', "1"], ["k2", "x", "2"], ["k3", "y", "3"], ["k4", "x", "4"], ["k5", "y", "5"], ["k6", "x", "6"]]
    out = _outcome(_run(["k", "cat", "val"], rows, [_piv("cat", "val")]))
    assert out.startswith("refused") and "double quote" in out.lower(), out


# ---------------------------------------------------------------- following the types across steps

def test_f4_conflict_is_followed_through_a_row_step_after_the_unpivot() -> None:
    rows = [["r1", "1.0", "1.0"], ["r2", "2", "x"], ["r3", "3", "y"], ["r4", "4", "z"]]
    steps = [_conv("A", "decimal_number"), _unpivot(["A", "B"]), KEEP_TOP, _piv("v", "at")]
    out = _outcome(_run(UNPIVOT_HEADERS, rows, steps))
    assert out.startswith("both-reject: Cannot pivot: distinct typed categories"), out


def test_f4_a_text_convert_of_the_value_column_after_the_unpivot_ends_the_conflict() -> None:
    # The engine converts the value column to text: '1.0' (was decimal) and '1.0' (text) are one category now.
    rows = [["r1", "1.0", "1.0"], ["r2", "2", "x"], ["r3", "3", "y"], ["r4", "4", "z"]]
    steps = [_conv("A", "decimal_number"), _unpivot(["A", "B"]), _conv("v", "text"), _piv("v", "at")]
    assert _outcome(_run(UNPIVOT_HEADERS, rows, steps)) == "ran"


def test_type_follow_keeps_types_through_row_steps_and_forgets_them_after_other_steps() -> None:
    types = {"k": "decimal_number", "x": "date"}
    unpivot_step = _unpivot(["A", "B"])
    last = (unpivot_step, {"A": "decimal_number"})
    kept, kept_unpivot = _follow_column_types(KEEP_TOP, types, last, ["k", "x", "at", "v"], ["k", "x", "at", "v"])
    assert kept == types and kept_unpivot == last
    removed, removed_unpivot = _follow_column_types({"op": "remove_column", "column": "v"}, types, last, ["k", "x", "at", "v"], ["k", "x", "at"])
    assert removed == types and removed_unpivot is None
    dropped_column, _ = _follow_column_types({"op": "remove_column", "column": "x"}, types, None, ["k", "x"], ["k"])
    assert dropped_column == {"k": "decimal_number"}
    forgotten, forgotten_unpivot = _follow_column_types({"op": "trim_text", "columns": ["k"]}, types, last, ["k", "x"], ["k", "x"])
    assert forgotten == {} and forgotten_unpivot is None
    renamed, renamed_unpivot = _follow_column_types({"op": "rename_column", "column": "k", "new_name": "k2"}, types, last, ["k", "x"], ["k2", "x"])
    assert renamed == {"k2": "decimal_number", "x": "date"} and renamed_unpivot is None
    assert "pivot_column" not in TYPE_KEEPING_OPS and "trim_text" not in TYPE_KEEPING_OPS


def test_type_follow_unpivot_moves_the_listed_columns_and_keeps_the_others() -> None:
    types = {"id": "decimal_number", "A": "date", "B": "boolean"}
    listed, listed_unpivot = _follow_column_types(_unpivot(["A", "B"]), types, None, ["id", "A", "B"], ["id", "at", "v"])
    assert listed == {"id": "decimal_number"} and listed_unpivot is not None
    assert listed_unpivot[1] == {"A": "date", "B": "boolean"}
    others, others_unpivot = _follow_column_types(_unpivot(["id"], other=True), types, None, ["id", "A", "B"], ["id", "at", "v"])
    assert others == {"id": "decimal_number"} and others_unpivot is not None
    assert others_unpivot[1] == {"A": "date", "B": "boolean"}


# ---------------------------------------------------------------- F7 (D1e tables scale with --rows) and D1a in dataset mode

def _count(path: Path) -> int:
    with open(path, newline="", encoding="utf-8") as f:
        return len(list(csv.reader(f))) - 1


@pytest.mark.parametrize("rows,expected", [(1, 40), (40, 40), (41, 41), (60, 60), (400, 400)])
def test_d1e_table_row_count_follows_rows_above_forty(tmp_path: Path, rows: int, expected: int) -> None:
    path = tmp_path / "d1e.csv"
    generate_d1e_csv(path, 3, "d1e", rows=rows)
    assert D1E_ROWS == 40
    assert _count(path) == expected


def test_d1e_other_shapes_keep_their_fixed_size_with_many_rows(tmp_path: Path) -> None:
    sizes = {"d1e_one_row": 1, "d1e_empty": 0, "d1e_wide": 520}
    for shape, expected in sizes.items():
        path = tmp_path / f"{shape}.csv"
        generate_d1e_csv(path, 3, shape, rows=400)
        assert _count(path) == expected, shape


def test_the_d1a_table_follows_rows_in_a_generated_run_but_not_in_dataset_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int | None] = []
    real = pq_store_diff.generate_d1a_csv

    def spy(csv_file: Path, seed: int, shape: str = "d1a", scale_rows: int | None = None) -> list[str]:
        if shape == "d1a":
            seen.append(scale_rows)
        return real(csv_file, seed, shape, scale_rows=scale_rows)

    monkeypatch.setattr(pq_store_diff, "generate_d1a_csv", spy)
    item = {"id": "q13", "step": {"op": "count_rows"}, "table": "d1a"}
    run_pq_step_diff(rows=300, seed=1, dataset={"headers": ["a", "b"], "rows": [["1", "2"], ["3", "4"]]}, items=[item])
    assert seen == [None]
    seen.clear()
    run_pq_step_diff(rows=300, seed=1, item_filter=["d1a_promote_headers"])
    assert seen == [300]
