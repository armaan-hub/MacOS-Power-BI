"""Stage D1f tests for Power Query step differential tool (tools/pq_store_diff.py).

Follow-ups from D1b review, G1-G5 engine diffs, F1-F6 mutant/boundary coverage,
and D1c Parts B & C group_by/merge/split/sequence follow-ups.
"""

from __future__ import annotations

import csv
import random
import tempfile
from pathlib import Path

from unittest.mock import patch

from analytics_studio.file_import import parse_file
from analytics_studio.store import DuckStore
from tests.test_pq_store_diff_tool import (
    _by_id,
    _engine_rows,
    _run_items,
)
from tests.test_pq_store_diff_tool_d1a import _tab
from tools import pq_store_diff


# ------------------------------------------------------------------ Part 1: F1 datetime 24:00:00 & 23:59:60


def test_f1_datetime_24_and_leap_second_are_refused() -> None:
    """Datetime 24:00:00 and leap second 23:59:60 are refused uniformly across Python versions."""
    t24 = _tab(["dt"], [["2024-02-29 24:00:00"], ["2024-02-29 10:00:00"]])
    item_dt24 = {"id": "dt24", "step": {"op": "convert_type", "column": "dt", "type": "datetime"}}
    res24 = _run_items(t24, [item_dt24])
    row24 = _by_id(res24, "dt24")
    assert row24["status"] == "refused", row24
    assert "datetimes other than yyyy-mm-dd" in row24["refusal_reason"].lower()

    t60 = _tab(["dt"], [["2024-02-29 23:59:60"], ["2024-02-29 10:00:00"]])
    item_dt60 = {"id": "dt60", "step": {"op": "convert_type", "column": "dt", "type": "datetime"}}
    res60 = _run_items(t60, [item_dt60])
    row60 = _by_id(res60, "dt60")
    assert row60["status"] == "refused", row60
    assert "datetimes other than yyyy-mm-dd" in row60["refusal_reason"].lower()

    ttime24 = _tab(["tm"], [["24:00:00"], ["10:00:00"]])
    item_time24 = {"id": "tm24", "step": {"op": "convert_type", "column": "tm", "type": "time"}}
    res_tm24 = _run_items(ttime24, [item_time24])
    row_tm24 = _by_id(res_tm24, "tm24")
    assert row_tm24["status"] == "refused", row_tm24


# ------------------------------------------------------------------ Part 1: F2 Mutant & Boundary Tests


def test_f2_mutant_m28_null_stays_null() -> None:
    """M28: NULL cell stays NULL through convert_type and does not become '' (kills B04)."""
    t = _tab(["val", "other"], [["", "x"], ["123", "y"], ["456", "z"]])
    t["nulls"] = [[0, "val"]]
    item = {"id": "m28_item", "step": {"op": "convert_type", "column": "val", "type": "whole_number"}}
    res = _run_items(t, [item])
    row = _by_id(res, "m28_item")
    assert row["status"] == "same", row


def test_f2_mutant_s02_sparse_whitespace_with_tabs_newlines_u0085() -> None:
    """S02: sparse-row whitespace stripping handles tabs, newlines, and U+0085."""
    t = _tab(["c1", "c2"], [["\t\n", " \u0085"], ["1", "2"], ["3", "4"], ["5", "6"], ["7", "8"], ["9", "10"]])
    item = {"id": "s02_item", "step": {"op": "remove_sparse_top_rows"}}
    clean_res = _run_items(t, [item])
    row = _by_id(clean_res, "s02_item")
    assert row["status"] == "same", row
    assert _engine_rows(t, item) == [["1", "2"], ["3", "4"], ["5", "6"], ["7", "8"], ["9", "10"]]


def test_f2_mutant_m16_whole_number_half_even_ties() -> None:
    """M16: whole_number half-even ties for 1.45, -1.45, 0.5, 1.5, 2.5, -0.5, -1.5."""
    vals = ["1.45", "-1.45", "0.5", "1.5", "2.5", "-0.5", "-1.5"]
    t = _tab(["num"], [[v] for v in vals])
    item = {"id": "m16_item", "step": {"op": "convert_type", "column": "num", "type": "whole_number"}}
    clean_res = _run_items(t, [item])
    row = _by_id(clean_res, "m16_item")
    assert row["status"] == "same"
    engine_rows = _engine_rows(t, item)
    # Check exact tie roundings: 1.45 -> 1, -1.45 -> -1, 0.5 -> 0, 1.5 -> 2, 2.5 -> 2, -0.5 -> 0, -1.5 -> -2
    assert engine_rows == [["1"], ["-1"], ["0"], ["2"], ["2"], ["0"], ["-2"]]


def test_f2_mutant_l03_locale_plain_plus() -> None:
    """L03: locale plain number with plus sign like '+5' is accepted and converted."""
    t = _tab(["num"], [["+5"], ["-12"], ["3.14"]])
    item = {
        "id": "l03_item",
        "step": {"op": "convert_type_using_locale", "column": "num", "type": "decimal_number", "culture": "en-US"},
    }
    clean_res = _run_items(t, [item])
    row = _by_id(clean_res, "l03_item")
    assert row["status"] == "same"
    assert _engine_rows(t, item)[0] == ["5"]


def test_f2_mutant_m05_exponent_detection_e_and_E() -> None:
    """M05: exponent detection catches both '1e3' and '1E3' and refuses decimal conversion."""
    t_lower = _tab(["num"], [["1e3"], ["10"]])
    item_lower = {"id": "m05_lower", "step": {"op": "convert_type", "column": "num", "type": "decimal_number"}}
    res_lower = _run_items(t_lower, [item_lower])
    assert _by_id(res_lower, "m05_lower")["status"] == "refused"

    t_upper = _tab(["num"], [["1E3"], ["10"]])
    item_upper = {"id": "m05_upper", "step": {"op": "convert_type", "column": "num", "type": "decimal_number"}}
    res_upper = _run_items(t_upper, [item_upper])
    assert _by_id(res_upper, "m05_upper")["status"] == "refused"


def test_f2_mutant_m29_m30_shape_checks() -> None:
    """M29 and M30: shape checks for non-string values and blank column names."""
    # M29: non-string values
    item_m29 = {"id": "m29", "step": {"op": "convert_type", "column": 123, "type": "text"}}
    t = _tab(["col"], [["val1"], ["val2"]])
    res_m29 = _run_items(t, [item_m29])
    row_m29 = _by_id(res_m29, "m29")
    assert row_m29["refusal_reason"] != ""
    assert "values must be strings" in row_m29["refusal_reason"].lower()

    # M30: blank column name
    item_m30 = {"id": "m30", "step": {"op": "convert_type", "column": "   ", "type": "text"}}
    res_m30 = _run_items(t, [item_m30])
    row_m30 = _by_id(res_m30, "m30")
    assert row_m30["refusal_reason"] != ""
    assert "needs a column name" in row_m30["refusal_reason"].lower()


def _engine_error(dataset: dict, item: dict) -> str:
    """The step engine's error text for one item (hand-check helper): the item must make the engine raise."""
    with tempfile.TemporaryDirectory() as td:
        paths = []
        for name, body in (("t.csv", dataset["rows"]), ("t2.csv", dataset.get("rows_2", []))):
            path = Path(td) / name
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(dataset["headers"])
                writer.writerows(body)
            paths.append(path)
        res = pq_store_diff.execute_engine_step(item, parse_file(paths[0]), parse_file(paths[1]))
        assert isinstance(res, str), "the engine was expected to raise"
        return res


def _assert_engine_error_matched(t: dict, item: dict, engine_text: str) -> None:
    """The engine raises `engine_text` (hand-copied from the engine) and the store side answers `same` by refusing."""
    assert engine_text in _engine_error(t, item)
    row = _by_id(_run_items(t, [item]), item["id"])
    assert row["status"] == "same", row
    assert row["refusal_reason"], row


def _assert_ran_same(t: dict, item: dict) -> None:
    """The engine succeeds and the store runs the step and matches it (not a refusal)."""
    row = _by_id(_run_items(t, [item]), item["id"])
    assert row["status"] == "same", row
    assert not row["refusal_reason"], row


def _seq(item_id: str, steps: list[dict]) -> dict:
    return {"id": item_id, "step": {"op": "sequence"}, "sequence": steps}


def _convert(column: str, kind: str) -> dict:
    return {"op": "convert_type", "column": column, "type": kind}


def test_f2_boundaries_m34_m01_m12_m11() -> None:
    """Boundaries run engine against store: 0.000001 vs 0.0000001 (M34, M11), 120 vs 121 chars (M01), 300 vs 301 digit exponent facts (M12)."""
    item = {"id": "b", "step": {"op": "convert_type", "column": "num", "type": "decimal_number"}}
    # M34 / M11: 0.000001 has adjusted exponent -6 and runs; 0.0000001 has -7 and is refused.
    assert _by_id(_run_items(_tab(["num"], [["0.000001"], ["1.0"]]), [item]), "b")["status"] == "same"
    assert not _by_id(_run_items(_tab(["num"], [["0.000001"], ["1.0"]]), [item]), "b")["refusal_reason"]
    assert _by_id(_run_items(_tab(["num"], [["0.0000001"], ["1.0"]]), [item]), "b")["status"] == "refused"

    # M01: an error message quoting a 120-character value matches the engine; a 121-character value is refused.
    item_conv = {"id": "c", "step": {"op": "convert_type", "column": "val", "type": "whole_number"}}
    row120 = _by_id(_run_items(_tab(["val"], [["x" * 120], ["abc"]]), [item_conv]), "c")
    assert row120["status"] == "same" and not row120["refusal_reason"], row120
    assert _by_id(_run_items(_tab(["val"], [["x" * 121], ["abc"]]), [item_conv]), "c")["status"] == "refused"

    # M12: the exponent fact of a 300-digit and of a 301-digit number, hand-counted (299 and 300). The refusal
    # threshold (CONVERT_DECIMAL_MAX_ADJUSTED) cannot be reached end to end: a value that long is refused earlier
    # (more than 120 characters), so only the fact is checked here.
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "store.duckdb"))
        for name, digits, adjusted in (("t300_digits", 300, 299), ("t301_digits", 301, 300)):
            store.create_table(name, [("c", "text")])
            store.append_rows(name, [["1" * digits], ["2"]])
            assert pq_store_diff._convert_column_facts(store, name, "c")["max_adjusted"] == adjusted


def test_f2_g04_catalog_sequences_present() -> None:
    """G04: catalog sequences are present in the test catalog."""
    cat = pq_store_diff.build_step_catalog(["b_round", "b_num"], {"b_round": {}, "b_num": {}})
    seq_ids = [it["id"] for it in cat if it.get("step", {}).get("op") == "sequence"]
    assert "d1b_seq_keep_then_convert" in seq_ids
    assert "d1b_seq_convert_then_trim" in seq_ids


# ------------------------------------------------------------------ Part 1: F3 Sequences after convert_type

# The engine's text steps (`column_types_after_steps` in transformations.py, around line 2047) and its error text.
F3_TEXT_STEPS = {
    "clean_text": ({"op": "clean_text", "column": "a"}, "Clean Text requires a text-typed column. Place it before a type conversion."),
    "lowercase_text": ({"op": "lowercase_text", "column": "a"}, "Lowercase Text requires a text-typed column. Place it before a type conversion."),
    "uppercase_text": ({"op": "uppercase_text", "column": "a"}, "Uppercase Text requires a text-typed column. Place it before a type conversion."),
    "proper_case_text": ({"op": "proper_case_text", "column": "a"}, "Capitalize Each Word requires a text-typed column. Place it before a type conversion."),
    "reverse_text": ({"op": "reverse_text", "column": "a"}, "Reverse Text requires a text-typed column. Place it before a type conversion."),
    "extract_text_by_delimiter": (
        {"op": "extract_text_by_delimiter", "column": "a", "delimiter": "-", "side": "before", "occurrence": 0},
        "Extract Text Before/After Delimiter requires a text-typed column. Place it before a type conversion.",
    ),
    "extract_text_between_delimiters": (
        {"op": "extract_text_between_delimiters", "column": "a", "start_delimiter": "-", "end_delimiter": "-", "start_occurrence": 0, "end_occurrence": 0},
        "Extract Text Between Delimiters requires a text-typed column. Place it before a type conversion.",
    ),
}
F3_TABLE = _tab(["a", "b"], [["1-2-3", "x"], ["4-5-6", "y"], ["7-8-9", "z"], ["1-1-1", "w"], ["2-4-6", "v"], ["9-8-7", "u"]])


def test_f3_every_text_step_after_convert_to_non_text_mirrors_the_engine_error() -> None:
    """After a convert to whole_number or any, each of the seven text steps raises in the engine; the tool matches the text."""
    for op, (step, engine_text) in F3_TEXT_STEPS.items():
        for kind in ("whole_number", "any"):
            item = _seq(f"f3_{op}_{kind}", [_convert("a", kind), step])
            _assert_engine_error_matched(F3_TABLE, item, engine_text)


def test_f3_text_convert_then_text_step_runs() -> None:
    """Control: after a convert to text the text steps run in the engine and the store matches them."""
    for op, (step, _text) in F3_TEXT_STEPS.items():
        _assert_ran_same(F3_TABLE, _seq(f"f3_text_{op}", [_convert("a", "text"), step]))


def test_f3_index_column_is_whole_number_for_text_steps() -> None:
    """add_index_column makes a whole_number column in the engine: lowercase_text on it raises (probe g3)."""
    steps = [{"op": "add_index_column", "new_name": "idx", "start": 1, "increment": 1}, {"op": "lowercase_text", "column": "idx"}]
    _assert_engine_error_matched(F3_TABLE, _seq("f3_idx", steps), F3_TEXT_STEPS["lowercase_text"][1])


def test_f3_rename_carries_the_non_text_type_to_the_text_step() -> None:
    """[convert a whole_number, rename a to c, lowercase_text c]: the engine renames the type too, so it raises."""
    steps = [_convert("a", "whole_number"), {"op": "rename_column", "column": "a", "new_name": "c"}, {"op": "lowercase_text", "column": "c"}]
    _assert_engine_error_matched(F3_TABLE, _seq("f3_ren", steps), F3_TEXT_STEPS["lowercase_text"][1])


def test_f3_step_with_bad_fields_keeps_the_field_error() -> None:
    """The engine validates the fields of every step before it tracks types: a bad field beats the type error."""
    steps = [_convert("a", "whole_number"), {"op": "lowercase_text", "column": "a", "bogus": "1"}]
    _assert_engine_error_matched(F3_TABLE, _seq("f3_bogus", steps), "has missing or unsupported fields.")


COND_ERR_TABLE = _tab(["a", "b"], [["1", "x"], ["zz", "y"], ["2", "x"], ["3", "y"], ["4", "x"], ["5", "y"]])


def _cond(clause_column: str, output: str = "Y", output_kind: str = "value", else_value: str = "N", else_kind: str = "value") -> dict:
    clause = {"column": clause_column, "operator": "equals", "test_value": "x" if clause_column == "b" else "1",
              "test_value_kind": "value", "output": output, "output_kind": output_kind}
    return {"op": "conditional_column", "name": "c", "clauses": [clause], "else_value": else_value, "else_kind": else_kind}


def test_f3_error_cells_split_merge_conditional_are_refused_by_name() -> None:
    """A column converted to whole_number holds an error cell (`zz`): the engine runs, the store cannot match, so the
    split, merge and conditional steps that read it are refused by name (status refused, not a mismatch)."""
    cases = {
        "split": {"op": "split_column", "column": "a", "delimiter": "-"},
        "split_to_rows": {"op": "split_column_to_rows", "column": "a", "delimiter": "-"},
        "split_positions": {"op": "split_column_by_positions", "column": "a", "positions": [0, 1]},
        "split_each_delimiter": {"op": "split_column_by_each_delimiter", "column": "a", "delimiter": "-"},
        "merge": {"op": "merge_columns", "columns": ["a", "b"], "separator": "-", "new_name": "m"},
        "cond_clause_column": _cond("a"),
        "cond_output_column": _cond("b", output="a", output_kind="column"),
        "cond_else_column": _cond("b", else_value="a", else_kind="column"),
    }
    for name, step in cases.items():
        item = _seq(f"f3_err_{name}", [_convert("a", "whole_number"), step])
        row = _by_id(_run_items(COND_ERR_TABLE, [item]), item["id"])
        assert row["status"] == "refused", (name, row)
        assert "error cells" in row["refusal_reason"], (name, row)


def test_f3_text_or_any_column_holding_error_prefix_text_runs() -> None:
    """A column converted to text or any holds the plain text "Error: raw" as a value: the engine runs split and
    merge on it and the store must match (status same, not refused)."""
    t = _tab(["a", "b"], [["Error: raw", "x"], ["q-r", "y"], ["s-t", "z"], ["u-v", "w"], ["1-2", "v"], ["3-4", "u"]])
    for kind in ("text", "any"):
        _assert_ran_same(t, _seq(f"f3_raw_split_{kind}", [_convert("a", kind), {"op": "split_column", "column": "a", "delimiter": "-"}]))
        _assert_ran_same(t, _seq(f"f3_raw_merge_{kind}", [_convert("a", kind), {"op": "merge_columns", "columns": ["a", "b"], "separator": "-", "new_name": "m"}]))


# ------------------------------------------------------------------ Part 1: F4 Named refusal reporting


def test_f4_g5_row_step_limit_hole_stays_loud_in_a_sequence() -> None:
    """G5: the engine raises at keep_top_rows 1,000,001 (step 1), the store runs it. The hole must stay loud: a named
    refusal at step 2 (add_custom_column) must NOT hide it as `refused`, and it is not `same`."""
    seq_steps = [
        {"op": "keep_top_rows", "count": 1000001},
        {"op": "add_custom_column", "name": "c", "expression": "1"},
    ]
    t = _tab(["a", "b"], [["1", "x"], ["2", "y"]])
    res = _run_items(t, [_seq("seq_g5", seq_steps)])
    row = _by_id(res, "seq_g5")
    assert row["status"] not in ("refused", "same"), row
    assert row["status"] == "refusal-reason-mismatch", row


# ------------------------------------------------------------------ Part 1: F6 Reviewer 20,000-string test


def test_f6_wider_alphabet_20000_strings() -> None:
    """F6: 20,000 strings (signs, padding, integer and fraction parts, empty fractions) converted three ways run and match."""
    rnd = random.Random(42)
    signs = ["", "", "-", "+"]
    int_parts = ["0", "1", "12", "123", "999", "1000", "123456789"]
    frac_parts = ["", "5", "50", "49", "25", "123456", "999999"]
    pads = ["", " ", "  "]
    vals = [
        f"{rnd.choice(pads)}{rnd.choice(signs)}{rnd.choice(int_parts)}.{rnd.choice(frac_parts)}{rnd.choice(pads)}"
        for _ in range(20000)
    ]
    assert len(vals) == 20000
    t = _tab(["x"], [[v] for v in vals])
    for target in ("decimal_number", "whole_number", "number"):
        row = _by_id(_run_items(t, [{"id": "f6", "step": {"op": "convert_type", "column": "x", "type": target}}]), "f6")
        assert row["status"] == "same" and not row["refusal_reason"], (target, row)


# ------------------------------------------------------------------ Part 0: G1 - G4 Engine Diffs

G_PIVOT = {"op": "pivot_column", "attribute_column": "attr", "value_column": "val", "aggregation": "count_all"}


def test_g1_pivot_attribute_type_survives_an_intervening_row_step() -> None:
    """G1: a datetime attribute column converted two steps before the pivot (keep_top_rows between) is still datetime
    for the engine, whose headers use 'T'; the store would use a space, so the pivot is refused by name (kills A03)."""
    t = _tab(["k", "attr", "val"], [["a", "2024-01-02 03:04:05", "1"], ["b", "2024-01-03", "2"], ["c", "2024-01-04", "3"]])
    item = _seq("g1_seq", [_convert("attr", "datetime"), {"op": "keep_top_rows", "count": 9}, G_PIVOT])
    assert len(_engine_rows(t, item)) == 3
    row = _by_id(_run_items(t, [item]), "g1_seq")
    assert row["status"] == "refused", row
    assert "Datetime attribute" in row["refusal_reason"]


G2_TABLE = _tab(["k", "attr", "val"], [["1.0", "a", "1"], ["1.00", "b", "2"], ["2", "a", "3"], ["2.0", "b", "4"], ["3", "a", "5"], ["3", "b", "6"]])


def test_g2_rename_and_duplicate_carry_the_decimal_type_to_the_pivot() -> None:
    """G2: the engine groups the decimal keys 1.0 and 1.00 (and 2 and 2.0) as one key each, giving 3 rows; the store
    groups the key texts apart. With the type carried through rename or duplicate the pivot is refused by name
    (kills A04, A05)."""
    rename = _seq("g2_rename", [_convert("k", "decimal_number"), {"op": "rename_column", "column": "k", "new_name": "k2"}, G_PIVOT])
    duplicate = _seq("g2_dup", [
        _convert("k", "decimal_number"), {"op": "duplicate_column", "column": "k", "new_name": "k2"},
        {"op": "remove_column", "column": "k"}, G_PIVOT,
    ])
    for item in (rename, duplicate):
        assert len(_engine_rows(G2_TABLE, item)) == 3  # keys 1, 2, 3
        row = _by_id(_run_items(G2_TABLE, [item]), item["id"])
        assert row["status"] == "refused", row
        assert "holds decimal values whose text forms differ" in row["refusal_reason"]


def test_g4_sequence_store_type_casting() -> None:
    """G4: sequence intermediate tables cast non-string values to str for text DuckStore tables."""
    seq_steps = [
        {"op": "add_index_column", "new_name": "idx", "start": 1, "increment": 1},
        {"op": "convert_type", "column": "a", "type": "whole_number"},
    ]
    t = _tab(["a"], [["10"], ["20"]])
    item = {"id": "g4_seq", "step": {"op": "sequence"}, "sequence": seq_steps}
    res = _run_items(t, [item])
    row = _by_id(res, "g4_seq")
    assert row["status"] == "same", row


# ------------------------------------------------------------------ Part 2: D1c Parts B & C Tests

GB_TABLE = _tab(["k", "v"], [["a", "1"], ["b", "2"], ["a", "3"], ["c", "4"], ["b", "5"], ["a", "6"]])
GB_LIMIT = "A grouped result cannot exceed the 512-column import limit."


def _group(item_id: str, aggregations: list[dict], columns: list[str] | None = None) -> dict:
    return {"id": item_id, "step": {"op": "group_by", "columns": columns or ["k"], "aggregations": aggregations}}


def test_part_b_group_by_m_type_follows_the_engine_strip_and_casefold() -> None:
    """The engine strips and case-folds m_type before the lookup: every spelling of its own list runs and matches; an unknown one raises (kills A16)."""
    from analytics_studio.transformations import GROUP_AGGREGATION_M_TYPES

    for number, m_type in enumerate(GROUP_AGGREGATION_M_TYPES):
        for spelling in (m_type, m_type.upper(), m_type.lower(), f"  {m_type.swapcase()}\t"):
            item = _group(f"gb_ok_{number}", [{"operation": "count_rows", "new_name": "n", "m_type": spelling}])
            _assert_ran_same(GB_TABLE, item)
    bad = _group("gb_bad_m", [{"operation": "count_rows", "new_name": "n", "m_type": "bad_type_xyz"}])
    _assert_engine_error_matched(GB_TABLE, bad, "Aggregation 1 in step 1 has an unsupported M type.")


def test_part_b_group_by_blank_output_name_and_error_order() -> None:
    """Blank output name (kills A17) and the engine's order: m_type is checked before the output name; the second aggregation is numbered 2."""
    blank = _group("gb_blank", [{"operation": "count_rows", "new_name": "   "}])
    _assert_engine_error_matched(GB_TABLE, blank, "Aggregation 1 in step 1 needs an output column name.")
    second = _group("gb_blank_2", [{"operation": "count_rows", "new_name": "n"}, {"operation": "count_rows", "new_name": ""}])
    _assert_engine_error_matched(GB_TABLE, second, "Aggregation 2 in step 1 needs an output column name.")
    both = _group("gb_both", [{"operation": "count_rows", "new_name": "", "m_type": "bad_type_xyz"}])
    _assert_engine_error_matched(GB_TABLE, both, "Aggregation 1 in step 1 has an unsupported M type.")


def test_part_b_group_by_512_column_limit() -> None:
    """Keys plus aggregations above 512 raise before anything else (kills the limit mutants); 512 runs."""
    over = _group("gb_513_aggs", [{"operation": "count_rows", "new_name": f"n{i}"} for i in range(513)])
    _assert_engine_error_matched(GB_TABLE, over, GB_LIMIT)
    key_plus = _group("gb_key_plus_512", [{"operation": "count_rows", "new_name": f"n{i}"} for i in range(512)])
    _assert_engine_error_matched(GB_TABLE, key_plus, GB_LIMIT)
    keys_513 = _group("gb_513_keys", [{"operation": "count_rows", "new_name": "n"}], columns=[f"k{i}" for i in range(513)])
    _assert_engine_error_matched(GB_TABLE, keys_513, GB_LIMIT)
    limit_before_shape = _group("gb_limit_first", [{"operation": "bogus", "new_name": f"n{i}"} for i in range(512)])
    _assert_engine_error_matched(GB_TABLE, limit_before_shape, GB_LIMIT)
    exactly = _group("gb_512", [{"operation": "count_rows", "new_name": f"n{i}"} for i in range(511)])
    _assert_ran_same(GB_TABLE, exactly)


MC_TABLE = _tab(["c1", "c2"], [["a", "b"], ["c", "d"], ["e", "f"], ["g", "h"], ["i", "j"], ["k", "l"]])
MC_SEP = "Transformation step 1 needs a text separator."
MC_LONG = "The merge separator may contain at most 32,767 characters."
MC_NAME = "Transformation step 1 needs a new column name."


def _merge(item_id: str, **fields: object) -> dict:
    step = {"op": "merge_columns", "columns": ["c1", "c2"], "new_name": "m", "separator": "-"}
    step.update(fields)
    return {"id": item_id, "step": step}


def test_part_b_merge_columns_validations_and_order() -> None:
    """Blank or non-string new name (kills A18), non-string separator (A19), separator over 32,767 characters (A20)."""
    _assert_engine_error_matched(MC_TABLE, _merge("mc_blank", new_name="  "), MC_NAME)
    _assert_engine_error_matched(MC_TABLE, _merge("mc_name_int", new_name=5), MC_NAME)
    _assert_engine_error_matched(MC_TABLE, _merge("mc_sep_int", separator=123), MC_SEP)
    _assert_engine_error_matched(MC_TABLE, _merge("mc_sep_none", separator=None), MC_SEP)
    _assert_engine_error_matched(MC_TABLE, _merge("mc_sep_long", separator="x" * 32768), MC_LONG)
    _assert_ran_same(MC_TABLE, _merge("mc_sep_edge", separator="x" * 32767))


def test_part_b_merge_columns_error_order_matches_the_engine() -> None:
    """Two faults at once: the engine's text for the one it checks first wins (separator type, then separator length, then new name, then a missing column)."""
    _assert_engine_error_matched(MC_TABLE, _merge("mc_o1", separator=123, new_name="  "), MC_SEP)
    _assert_engine_error_matched(MC_TABLE, _merge("mc_o2", separator="x" * 32768, new_name="  "), MC_LONG)
    _assert_engine_error_matched(MC_TABLE, _merge("mc_o3", columns=["c1", "zz"], separator=5), MC_SEP)
    _assert_engine_error_matched(MC_TABLE, _merge("mc_o4", columns=["c1", "zz"], new_name=" "), MC_NAME)
    _assert_engine_error_matched(MC_TABLE, _merge("mc_o5", columns=["c1", "zz"]), "Column 'zz' does not exist.")


def test_part_b_f5_d1b_tables_grow_with_rows() -> None:
    """F5: above 40 rows the generated D1b table grows with the run's rows (kills A21, A22). The engine side of a run
    on the d1b table is checked for its input row count (40 at rows 30 and 40, then 55 at rows 55)."""
    seen: list[int] = []
    real = pq_store_diff.execute_engine_step

    def spy(item, cand, cand_2):
        if item["id"] == "d1b_scale":
            seen.append(len(cand.rows))
        return real(item, cand, cand_2)

    items = [{"id": "d1b_scale", "step": {"op": "count_rows"}, "table": "d1b"}]
    with patch.object(pq_store_diff, "execute_engine_step", spy):
        for rows in (30, 55):
            res = pq_store_diff.run_pq_step_diff_many(rows=rows, seed=1, override_sets=[{}], item_filter=None, dataset=None, items=items)
            assert res[0]["results"][0]["status"] == "same"
    assert seen == [40, 55], seen


def test_part_b_split_column_from_end() -> None:
    """Part B: split_column with from_end builds and executes in differential tool."""
    t = _tab(["c1"], [["a-b-c"], ["d-e"]])
    item = {
        "id": "sc_fe",
        "step": {"op": "split_column", "column": "c1", "delimiter": "-", "from_end": True},
    }
    res = _run_items(t, [item])
    row = _by_id(res, "sc_fe")
    assert row["status"] == "same", row
    assert _engine_rows(t, item) == [["a-b", "c"], ["d", "e"]]
