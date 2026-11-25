"""Stage D0h tests for the Power Query step differential tool (tools/pq_store_diff.py).

Group by, replace, text transforms, merge columns and split column. Shared helpers come from
tests/test_pq_store_diff_tool.py.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Any

import pytest

from analytics_studio.file_import import parse_file
from analytics_studio.store import DuckStore
from tests.test_pq_store_diff_tool import (
    _assert_mutant_differs_and_exits_1,
    _baseline,
    _by_id,
    _engine_rows,
    _run_items,
    _statuses,
)
from tools import pq_store_diff
from tools.pq_store_diff import evaluate_exit_policy, run_pq_step_diff

# ------------------------------------------------------------------ D0h: group by, replace, text, merge, split

import hashlib
import itertools
import unicodedata

from tools.pq_store_diff import run_pq_step_diff_many


def _d0h_baseline(item_ids: list[str]) -> dict[str, Any]:
    """The baseline restricted to a subset of items (a run over a subset has a subset of the refusals)."""
    base = _baseline()
    return {"classes": base["classes"], "refused": [i for i in base["refused"] if i in set(item_ids)]}


def _agg(op: str, column: str | None, name: str) -> dict[str, str]:
    return {"operation": op, "new_name": name, **({"column": column} if column else {})}


def _group_item(item_id: str, keys: list[str], aggs: list[dict[str, str]]) -> dict[str, Any]:
    return {"id": item_id, "step": {"op": "group_by", "columns": keys, "aggregations": aggs}}


# 10 rows: keys b, a, B, 'a ', '', 'b', ' ', '1', '1.0', 'b'. Groups in first-seen order: b a B 'a ' '' ' ' 1 1.0.
G_TABLE = {
    "headers": ["k", "v", "w"],
    "rows": [
        ["b", "1", "x"], ["a", "2", "x"], ["B", "3", "y"], ["a ", "4", "y"], ["", "5", "x"],
        ["b", "2", "x"], [" ", "6", "y"], ["1", "1", "z"], ["1.0", "2", "z"], ["b", "2", ""],
    ],
}
G_ITEM = _group_item("g_all", ["k"], [
    _agg("count_rows", None, "n"), _agg("sum", "v", "s"), _agg("average", "v", "a"), _agg("median", "v", "md"),
    _agg("min", "v", "mn"), _agg("max", "v", "mx"), _agg("count_distinct_values", "w", "cd"),
    _agg("count_distinct_rows", None, "cr"),
])
G_CLEAN = [
    ["b", "3", "5", "1.666666666666666666666666667", "2", "1", "2", "2", "3"],
    ["a", "1", "2", "2", "2", "2", "2", "1", "1"],
    ["B", "1", "3", "3", "3", "3", "3", "1", "1"],
    ["a ", "1", "4", "4", "4", "4", "4", "1", "1"],
    ["", "1", "5", "5", "5", "5", "5", "1", "1"],
    [" ", "1", "6", "6", "6", "6", "6", "1", "1"],
    ["1", "1", "1", "1", "1", "1", "1", "1", "1"],
    ["1.0", "1", "2", "2", "2", "2", "2", "1", "1"],
]


def test_group_by_first_seen_order_exact_keys_and_every_aggregate_hand_checked() -> None:
    """Keys are exact text ('', ' ', 'a', 'a ', 'B', 'b', '1', '1.0' are eight groups), in first-seen order."""
    assert _engine_rows(G_TABLE, G_ITEM) == G_CLEAN
    assert _by_id(_run_items(G_TABLE, [G_ITEM]), "g_all")["status"] == "same"


@pytest.mark.parametrize(
    "mutant",
    ["mutant_group_order_not_first_seen", "mutant_group_blank_key_merged", "mutant_group_key_casefold",
     "mutant_group_average_float", "mutant_group_count_skips_blank"],
)
def test_group_by_mutants_differ_and_exit_1(mutant: str) -> None:
    """One rule changed at a time: order, blank key merged with '', key case folded, AVERAGE as float, COUNT skipping blank."""
    _assert_mutant_differs_and_exits_1(G_TABLE, G_ITEM, mutant, G_CLEAN)


def test_group_by_min_max_numeric_and_text_rules_hand_checked() -> None:
    """All-numeric group: by value, first of equal values; any non-number: Python casefold of the text; blank group: null."""
    table = {
        "headers": ["k", "v"],
        "rows": [
            ["n", "9"], ["n", "10"], ["m", "9"], ["m", "10"], ["m", "x"], ["t", "b"], ["t", "B"], ["t", "a"],
            ["t", "A"], ["e", "7"], ["e", "07"], ["e", "+7"], ["e", "7.0"], ["z", ""],
        ],
    }
    item = _group_item("mm", ["k"], [_agg("min", "v", "mn"), _agg("max", "v", "mx")])
    # equal values (7, 07, +7, 7.0): the first cell in table order wins, '7'
    assert _engine_rows(table, item) == [["n", "9", "10"], ["m", "10", "x"], ["t", "a", "b"], ["e", "7", "7"], ["z", None, None]]
    assert _by_id(_run_items(table, [item]), "mm")["status"] == "same"


def test_group_by_first_non_number_is_the_first_in_group_order_not_table_order() -> None:
    """Group a (rows 1 and 3) is aggregated before group b (row 2), so the engine names row 3 'y', not row 2 'x'."""
    table = {"headers": ["k", "v"], "rows": [["a", "1"], ["b", "x"], ["a", "y"]]}
    item = _group_item("bad", ["k"], [_agg("sum", "v", "s")])
    engine = pq_store_diff.execute_engine_step(item, parse_file(_write_csv(table)))
    assert engine == "Value 'y' in row 3 of column 'v' is not a valid number."
    data = _run_items(table, [item])
    assert _by_id(data, "bad")["status"] == "same"
    assert engine in _by_id(data, "bad")["refusal"]


def _write_csv(table: dict[str, Any]) -> Path:
    path = Path(tempfile.mkdtemp()) / "t.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(table["headers"])
        w.writerows(table["rows"])
    return path


def test_group_by_shapes_empty_one_row_all_blank_key_and_missing_column() -> None:
    """Empty table, one row, all keys blank, a key or aggregate column that does not exist (the engine's text is expected)."""
    aggs = [_agg("count_rows", None, "n"), _agg("sum", "v", "s"), _agg("min", "v", "mn")]
    for table, expect in (
        ({"headers": ["k", "v"], "rows": []}, []),
        ({"headers": ["k", "v"], "rows": [["a", "5"]]}, [["a", "1", "5", "5"]]),
        ({"headers": ["k", "v"], "rows": [["", "1"], ["", "2"], ["", "x"]]}, None),
        # the third row is all blank, which the CSV load drops (measured), so the blank key group has two rows
        ({"headers": ["k", "v"], "rows": [["", "1"], ["", "2"], ["", ""]]}, [["", "2", "3", "1"]]),
    ):
        item = _group_item("shape", ["k"], aggs)
        data = _run_items(table, [item])
        assert _by_id(data, "shape")["status"] == "same", table
        if expect is not None:
            assert _engine_rows(table, item) == expect
    for step in (
        {"op": "group_by", "columns": ["nope"], "aggregations": [_agg("count_rows", None, "n")]},
        {"op": "group_by", "columns": ["k"], "aggregations": [_agg("sum", "nope", "n")]},
    ):
        data = _run_items({"headers": ["k", "v"], "rows": [["a", "1"]]}, [{"id": "miss", "step": step}])
        assert _by_id(data, "miss")["status"] == "same" and "Column 'nope' does not exist." in _by_id(data, "miss")["refusal"]


def test_group_by_named_refusals_say_what_the_sql_cannot_mirror() -> None:
    """Average over numbers whose precision rule needs more than 28 digits, and min of non-ASCII text, are refused by name."""
    table = {
        "headers": ["k", "v", "t"],
        "rows": [["a", "9007199254740993", "é"], ["a", "0.1000000000000001", "z"], ["b", "2", "é"]],
    }
    items = [
        _group_item("avg_big", ["k"], [_agg("average", "v", "a")]),
        _group_item("sum_big", ["k"], [_agg("sum", "v", "a")]),
        _group_item("min_text", ["k"], [_agg("min", "t", "a")]),
    ]
    data = _run_items(table, items)
    assert _by_id(data, "avg_big")["status"] == "refused" and "precision rule needs" in _by_id(data, "avg_big")["refusal"]
    assert _by_id(data, "sum_big")["status"] == "same" and _by_id(data, "sum_big")["refusal"] is None
    assert _by_id(data, "min_text")["status"] == "refused" and "casefold" in _by_id(data, "min_text")["refusal"]


# ---- replace_value

R_TABLE = {
    "headers": ["c", "n"],
    "rows": [[c, str(i)] for i, c in enumerate(
        ["ab", "AB", "xaby", "aab", "ababab", "a%b", "a_b", "a\\b", "it's", "(ab)*", "aaa", " ab ", "a.b", ""], 1)],
}


def _replace_item(item_id: str, value: Any, replacement: Any, replacer: str | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {"op": "replace_value", "column": "c", "value": value, "replacement": replacement}
    if replacer:
        step["replacer"] = replacer
    return {"id": item_id, "step": step}


def _c_column(item: dict[str, Any]) -> list[str | None]:
    return [row[0] for row in _engine_rows(R_TABLE, item)]


R_CASES = [
    # (id, value, replacement, replacer, expected column c)
    ("whole", "ab", "Z", None,
     ["Z", "AB", "xaby", "aab", "ababab", "a%b", "a_b", "a\\b", "it's", "(ab)*", "aaa", " ab ", "a.b", ""]),
    ("blank_target", "", "Z", None,
     ["ab", "AB", "xaby", "aab", "ababab", "a%b", "a_b", "a\\b", "it's", "(ab)*", "aaa", " ab ", "a.b", "Z"]),
    ("null_replacement", "ab", None, None,
     [None, "AB", "xaby", "aab", "ababab", "a%b", "a_b", "a\\b", "it's", "(ab)*", "aaa", " ab ", "a.b", ""]),
    ("int_replacement", "ab", 5, None,
     ["5", "AB", "xaby", "aab", "ababab", "a%b", "a_b", "a\\b", "it's", "(ab)*", "aaa", " ab ", "a.b", ""]),
    ("number_target_matches_no_text_cell", 5, "Z", None,
     ["ab", "AB", "xaby", "aab", "ababab", "a%b", "a_b", "a\\b", "it's", "(ab)*", "aaa", " ab ", "a.b", ""]),
    ("null_target", None, "Z", None,
     ["ab", "AB", "xaby", "aab", "ababab", "a%b", "a_b", "a\\b", "it's", "(ab)*", "aaa", " ab ", "a.b", ""]),
    ("text_sub", "ab", "Z", "text",
     ["Z", "AB", "xZy", "aZ", "ZZZ", "a%b", "a_b", "a\\b", "it's", "(Z)*", "aaa", " Z ", "a.b", ""]),
    ("text_overlap", "aa", "X", "text",
     ["ab", "AB", "xaby", "Xb", "ababab", "a%b", "a_b", "a\\b", "it's", "(ab)*", "Xa", " ab ", "a.b", ""]),
    ("text_empty_replacement", "a", "", "text",
     ["b", "AB", "xby", "b", "bbb", "%b", "_b", "\\b", "it's", "(b)*", "", " b ", ".b", ""]),
    ("text_percent", "%", "p", "text",
     ["ab", "AB", "xaby", "aab", "ababab", "apb", "a_b", "a\\b", "it's", "(ab)*", "aaa", " ab ", "a.b", ""]),
    ("text_underscore", "_", "u", "text",
     ["ab", "AB", "xaby", "aab", "ababab", "a%b", "aub", "a\\b", "it's", "(ab)*", "aaa", " ab ", "a.b", ""]),
    ("text_backslash", "\\", "/", "text",
     ["ab", "AB", "xaby", "aab", "ababab", "a%b", "a_b", "a/b", "it's", "(ab)*", "aaa", " ab ", "a.b", ""]),
    ("text_quote", "'", "''", "text",
     ["ab", "AB", "xaby", "aab", "ababab", "a%b", "a_b", "a\\b", "it''s", "(ab)*", "aaa", " ab ", "a.b", ""]),
    ("text_dot", ".", "!", "text",
     ["ab", "AB", "xaby", "aab", "ababab", "a%b", "a_b", "a\\b", "it's", "(ab)*", "aaa", " ab ", "a!b", ""]),
    ("text_regex", "(ab)*", "R", "text",
     ["ab", "AB", "xaby", "aab", "ababab", "a%b", "a_b", "a\\b", "it's", "R", "aaa", " ab ", "a.b", ""]),
    ("text_case", "AB", "Z", "text",
     ["ab", "Z", "xaby", "aab", "ababab", "a%b", "a_b", "a\\b", "it's", "(ab)*", "aaa", " ab ", "a.b", ""]),
]


@pytest.mark.parametrize("case", R_CASES, ids=[c[0] for c in R_CASES])
def test_replace_value_hand_checked_and_same_as_sql(case: tuple[Any, ...]) -> None:
    """Whole-cell and substring forms, null and empty targets, special characters are literals on both sides."""
    item_id, value, replacement, replacer, expected = case
    item = _replace_item(item_id, value, replacement, replacer)
    assert _c_column(item) == expected
    assert _by_id(_run_items(R_TABLE, [item]), item_id)["status"] == "same"


def test_replace_value_engine_errors_and_named_refusal() -> None:
    """Empty search or a null replacement in the text form, and a missing column, are the engine's own errors."""
    items = [
        _replace_item("empty_search", "", "Z", "text"),
        _replace_item("null_repl", "ab", None, "text"),
        {"id": "missing", "step": {"op": "replace_value", "column": "nope", "value": "a", "replacement": "b"}},
        _replace_item("bool_repl", "ab", True),
    ]
    data = _run_items(R_TABLE, items)
    for item_id in ("empty_search", "null_repl", "missing"):
        assert _by_id(data, item_id)["status"] == "same" and _by_id(data, item_id)["refusal"], item_id
    assert _by_id(data, "bool_repl")["status"] == "refused"


@pytest.mark.parametrize(
    "mutant,case",
    [("mutant_replace_value_substring", "whole"), ("mutant_replace_text_whole_cell", "text_sub"),
     ("mutant_replace_case_insensitive", "whole"), ("mutant_replace_case_insensitive", "text_sub")],
)
def test_replace_mutants_differ_and_exit_1(mutant: str, case: str) -> None:
    """Whole cell versus partial, and case-insensitive matching, each change the result and the exit code."""
    _, value, replacement, replacer, expected = next(c for c in R_CASES if c[0] == case)
    item = _replace_item(case, value, replacement, replacer)
    data = _run_items(R_TABLE, [item], overrides={mutant: True})
    assert _by_id(data, case)["status"] == "differs"
    assert evaluate_exit_policy(data, {"classes": []})[0] == 1


# ---- text transforms

PROBES = [
    "ß", "İ", "ı", "Σ", "ς", "ΑΣ", "é", "éx", "𝐀", "😀a", "𐐨", "日本", " x ", "\tx\t", "ǆ", "ŉ", "ﬁ",
    "🇦🇪x", "x​", " y ", "\x85z\x85", "　q　", "a\x1fb",
]
P_TABLE = {"headers": ["c", "n"], "rows": [[p, str(i)] for i, p in enumerate(PROBES, 1)]}
TEXT_OPS = ["trim_text", "clean_text", "lowercase_text", "uppercase_text", "proper_case_text", "reverse_text"]


def test_text_transforms_on_unicode_probe_table_map_or_are_refused_by_name() -> None:
    """Trim, clean and reverse equal the engine on ß İ ı Σ ς é combining marks, astral, CJK, NBSP, tabs; the three case
    transforms are refused by name on a non-ASCII column, with the probe evidence that the SQL really differs."""
    items = [{"id": op, "step": {"op": op, "column": "c"}} for op in TEXT_OPS]
    data = _run_items(P_TABLE, items)
    for op in ("trim_text", "clean_text", "reverse_text"):
        assert _by_id(data, op)["status"] == "same" and _by_id(data, op)["refusal"] is None, op
    for op in ("lowercase_text", "uppercase_text", "proper_case_text"):
        assert _by_id(data, op)["status"] == "refused" and "Python str case rules" in _by_id(data, op)["refusal"], op
    # probe evidence: DuckDB's own functions differ from Python on exactly these characters
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "s.db"))
        seen = {"lower": [], "upper": [], "reverse": []}
        for probe in PROBES:
            low, up, rev = store.execute(f"SELECT lower({_lit(probe)}), upper({_lit(probe)}), reverse({_lit(probe)})")[0]
            for name, got, want in (("lower", low, probe.lower()), ("upper", up, probe.upper()), ("reverse", rev, probe[::-1])):
                if got != want:
                    seen[name].append(probe)
    assert {"İ", "ΑΣ"} <= set(seen["lower"])
    assert {"ß", "ŉ", "ﬁ"} <= set(seen["upper"])
    assert {"éx", "🇦🇪x"} <= set(seen["reverse"])  # native reverse() works on graphemes: not used


def _lit(text: str) -> str:
    out = pq_store_diff.sql_str(text)
    assert isinstance(out, str)
    return out


def test_trim_and_clean_sets_equal_python_over_every_code_point_below_u20000() -> None:
    """The SQL trim set equals str.strip() and the SQL clean class equals Unicode category Cc, code point by code point."""
    ws = _lit(pq_store_diff.PY_WHITESPACE)
    clean = pq_store_diff.CLEAN_CC_REGEX
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "s.db"))
        span = "i BETWEEN 1 AND 131071 AND i NOT BETWEEN 55296 AND 57343"
        trimmed = {r[0] for r in store.execute(f"SELECT i FROM range(0, 131072) t(i0), LATERAL (SELECT CAST(i0 AS INTEGER) AS i) WHERE {span} AND trim(chr(i), {ws}) = ''")}
        cleaned = {r[0] for r in store.execute(
            f"SELECT i FROM range(0, 131072) t(i0), LATERAL (SELECT CAST(i0 AS INTEGER) AS i) WHERE {span} AND regexp_replace(chr(i), '{clean}', '', 'g') = ''")}
    codes = [i for i in range(1, 131072) if not 0xD800 <= i <= 0xDFFF]
    assert trimmed == {i for i in codes if chr(i).isspace()}
    assert cleaned == {i for i in codes if unicodedata.category(chr(i)) == "Cc"}


def test_all_ascii_strings_of_three_characters_agree_for_all_six_text_steps() -> None:
    """On an ASCII-only column every one of the six steps is compared (not refused) over all strings of up to 3 characters."""
    alphabet = ["a", "Z", "1", "'", "-", "_", " ", "\t", "\x1f"]
    cells = ["".join(p) for n in (1, 2, 3) for p in itertools.product(alphabet, repeat=n)]
    table = {"headers": ["c", "n"], "rows": [[c, str(i)] for i, c in enumerate(cells, 1)]}
    data = _run_items(table, [{"id": op, "step": {"op": op, "column": "c"}} for op in TEXT_OPS])
    assert {r["status"] for r in data["results"]} == {"same"}
    assert all(r["refusal"] is None for r in data["results"])


def test_trim_set_mutant_differs_and_exits_1() -> None:
    """A trim that only removes spaces leaves tabs and the control separators the engine strips."""
    table = {"headers": ["c", "n"], "rows": [["\tx\t", "1"], ["  y ", "2"], ["\x1fz\x1f", "3"]]}
    item = {"id": "trim", "step": {"op": "trim_text", "column": "c"}}
    _assert_mutant_differs_and_exits_1(table, item, "mutant_trim_spaces_only", [["x", "1"], ["y", "2"], ["z", "3"]])


def test_lower_mutant_on_non_ascii_differs_and_clean_run_refuses() -> None:
    """With the ASCII guard the column is refused by name; without it DuckDB lower() differs from the engine on İ."""
    table = {"headers": ["c", "n"], "rows": [["İSTANBUL", "1"], ["ABC", "2"]]}
    item = {"id": "low", "step": {"op": "lowercase_text", "column": "c"}}
    assert _engine_rows(table, item)[0][0] == "i̇stanbul"
    assert _by_id(_run_items(table, [item]), "low")["status"] == "refused"
    data = _run_items(table, [item], overrides={"mutant_lower_non_ascii": True})
    assert _by_id(data, "low")["status"] == "differs"
    assert evaluate_exit_policy(data, {"classes": [], "refused": ["low"]})[0] == 1


# ---- merge_columns and split

M_TABLE = {
    "headers": ["a", "b", "c", "d"],
    "rows": [["x", "y", "", "1"], ["", "", "z", "2"], ["p|q", "%_", "\\", "3"]],
}
M_ITEM = {"id": "merge", "step": {"op": "merge_columns", "columns": ["c", "a"], "separator": "-", "new_name": "m"}}
M_CLEAN = [["-x", "y", "1"], ["z-", "", "2"], ["\\-p|q", "%_", "3"]]


def test_merge_columns_hand_checked_blank_order_position_and_errors() -> None:
    """Join order is the order given, a blank still gets its separator, the merged column takes the leftmost position."""
    assert _engine_rows(M_TABLE, M_ITEM) == M_CLEAN
    other = {"id": "m3", "step": {"op": "merge_columns", "columns": ["a", "b", "c"], "separator": " :: %_' \\", "new_name": "b"}}
    one = {"id": "m1", "step": {"op": "merge_columns", "columns": ["a"], "separator": ",", "new_name": "q"}}
    clash = {"id": "mc", "step": {"op": "merge_columns", "columns": ["a", "b"], "separator": ",", "new_name": "d"}}
    miss = {"id": "mm", "step": {"op": "merge_columns", "columns": ["a", "zz"], "separator": ",", "new_name": "q"}}
    data = _run_items(M_TABLE, [M_ITEM, other, one, clash, miss])
    assert _statuses(data) == {"merge": "same", "m3": "same", "m1": "same", "mc": "same", "mm": "same"}
    assert [_by_id(data, i)["refusal"] is not None for i in ("merge", "m3", "m1", "mc", "mm")] == [False, False, True, True, True]


@pytest.mark.parametrize("mutant", ["mutant_merge_separator_off", "mutant_merge_skip_blank"])
def test_merge_mutants_differ_and_exit_1(mutant: str) -> None:
    """A separator with its first character removed, and a merge that skips blank cells, both change the result."""
    _assert_mutant_differs_and_exits_1(M_TABLE, M_ITEM, mutant, M_CLEAN)


S_TABLE = {
    "headers": ["id", "s"],
    "rows": [
        ["1", "a|b"], ["2", "a|b|c|d"], ["3", ""], ["4", "|"], ["5", "x||y|"], ["6", "|z"], ["7", "plain"], ["8", "a.b"],
    ],
}
S_EACH = {"id": "each", "step": {"op": "split_column_by_each_delimiter", "column": "s", "delimiter": "|"}}
S_EACH_CLEAN = [
    ["1", "a", "b", None, None], ["2", "a", "b", "c", "d"], ["3", "", None, None, None], ["4", "", "", None, None],
    ["5", "x", "", "y", ""], ["6", "", "z", None, None], ["7", "plain", None, None, None], ["8", "a.b", None, None, None],
]


def test_split_by_each_delimiter_width_comes_from_the_data_and_nulls_pad() -> None:
    """Four columns because the longest cell has four parts; ends, consecutive delimiters, blank and no-delimiter cells."""
    assert _engine_rows(S_TABLE, S_EACH) == S_EACH_CLEAN
    data = _run_items(S_TABLE, [S_EACH])
    assert _by_id(data, "each")["status"] == "same"


def test_split_width_mutant_that_reads_only_the_first_row_differs_and_exits_1() -> None:
    _assert_mutant_differs_and_exits_1(S_TABLE, S_EACH, "mutant_split_width_first_row", S_EACH_CLEAN)


def test_split_column_delimiter_forms_and_errors() -> None:
    """Regex characters and multi-character delimiters are literal; from_end scans from the right (overlap 'aa');
    an empty delimiter, a missing column, a name that exists, and more columns than the limit are the engine's errors."""
    table = {"headers": ["s", "n"], "rows": [["a.b.c", "1"], ["aaa", "2"], ["aaaa|aa", "3"], ["x::y::z", "4"], ["", "5"], ["a, b", "6"]]}
    items = []
    for name, delimiter, from_end in (("dot", ".", False), ("aa", "aa", False), ("aa_end", "aa", True), ("colons", "::", False),
                                       ("comma_space", ", ", False), ("pipe_end", "|", True), ("absent", "~", False)):
        step: dict[str, Any] = {"op": "split_column", "column": "s", "delimiter": delimiter}
        if from_end:
            step["from_end"] = True
        items.append({"id": name, "step": step})
        items.append({"id": name + "_each", "step": {"op": "split_column_by_each_delimiter", "column": "s", "delimiter": delimiter}})
    assert _engine_rows(table, next(i for i in items if i["id"] == "aa_end"))[1][:2] == ["a", ""]  # 'aaa'.rpartition('aa')
    data = _run_items(table, items)
    assert {r["status"] for r in data["results"]} == {"same"}
    assert all(r["refusal"] is None for r in data["results"])
    errors = [
        {"id": "empty", "step": {"op": "split_column", "column": "s", "delimiter": ""}},
        {"id": "nope", "step": {"op": "split_column_by_each_delimiter", "column": "zz", "delimiter": "|"}},
    ]
    data = _run_items(table, errors)
    assert _statuses(data) == {"empty": "same", "nope": "same"} and all(r["refusal"] for r in data["results"])
    clash = {"headers": ["s", "s.1"], "rows": [["a|b", "x"]]}
    data = _run_items(clash, [{"id": "c1", "step": {"op": "split_column", "column": "s", "delimiter": "|"}},
                              {"id": "c2", "step": {"op": "split_column_by_each_delimiter", "column": "s", "delimiter": "|"}}])
    assert _statuses(data) == {"c1": "same", "c2": "same"} and all("already exists" in r["refusal"] for r in data["results"])
    wide = {"headers": ["s", "n"], "rows": [["|".join(["a"] * 520), "1"]]}
    data = _run_items(wide, [{"id": "wide", "step": {"op": "split_column_by_each_delimiter", "column": "s", "delimiter": "|"}}])
    assert _by_id(data, "wide")["status"] == "same" and "column import limit" in _by_id(data, "wide")["refusal"]


def test_replace_error_values_is_the_identity_on_csv_and_checks_the_column() -> None:
    items = [
        {"id": "ev_ok", "step": {"op": "replace_error_values", "replacements": [["c", "x"]]}},
        {"id": "ev_missing", "step": {"op": "replace_error_values", "replacements": [["zz", "x"]]}},
    ]
    assert _engine_rows(R_TABLE, items[0]) == [[c, n] for c, n in R_TABLE["rows"]]
    data = _run_items(R_TABLE, items)
    assert _statuses(data) == {"ev_ok": "same", "ev_missing": "same"} and _by_id(data, "ev_missing")["refusal"]


# ---- generated data

def test_d0h_generated_columns_hold_the_planted_shapes_and_old_columns_keep_their_draws(tmp_path: Path) -> None:
    """Key blanks, case variants, trailing spaces; padded, underscore, negative and decimal numbers; delimiters at the
    ends and consecutive; the search text at the start, middle, end, repeated, overlapping and in other case. The seven
    older columns are byte-identical to the D0g generator (digest taken from it). The num_clean column is pinned
    by its own D0h digest: it changed in the planted rows 21 to 24 on purpose in D0h, so it is not in the D0g digest."""
    for rows, seed, digest, clean_digest in (
        (400, 1, "f7323db3927b162c8b3567ca9f8df9da6d1b8ad8a8861f7167a15288233ba5a8",
         "0cb287effc528a1359ed6f356c53d5b74b31866df172dc957f498bfa48b9dd4b"),
        (120, 9, "574a856ca23605f45ffad3d9222248bb14743d48a9fa86ee35ae18d91e9a57fb",
         "52ffec0bd4ec5fc52096164d0b6be4584f9b72245c740b5c66dc012c4b8d18cf"),
    ):
        path = tmp_path / f"d{rows}.csv"
        pq_store_diff.generate_pq_dataset(path, rows=rows, seed=seed)
        with open(path, newline="", encoding="utf-8") as f:
            table = list(csv.reader(f))
        head, body = table[0], table[1:]
        old = ["id", "text_col", "num_col", "date_col", "cat_col", "dt_col", "blank_col"]
        picked = [[r[head.index(k)] for k in old] for r in table]
        assert hashlib.sha256(repr(picked).encode()).hexdigest() == digest
        clean = [[r[head.index("num_clean")]] for r in table]
        assert hashlib.sha256(repr(clean).encode()).hexdigest() == clean_digest
    col = lambda name: [r[head.index(name)] for r in body]
    assert {"", " ", "g1", "G1", "g1 ", "1", "1.0"} <= set(col("grp_key"))
    assert {" 4 ", "1_000", "-5", "-0.50", "1e2", "007", "07"} <= set(col("agg_num"))
    assert {"|a", "a||b|", "x|", "||", "a.b.c", "a, b, c", "a::b::c"} <= set(col("split_col"))
    assert {"ab", "xaby", "xab", "abxab", "ababab", "aab", "AB", "a%b", "a_b", "a\\b", "it's"} <= set(col("rep_col"))
    assert all(c.isascii() for c in col("word_col")) and any("\x1f" in c for c in col("word_col"))


D0H_MUTANT_ITEMS = {
    "mutant_group_order_not_first_seen": ["group_by_count_rows"],
    "mutant_group_blank_key_merged": ["group_by_count_rows"],
    "mutant_group_key_casefold": ["group_by_count_rows"],
    "mutant_group_average_float": ["group_by_average_agg_num"],
    "mutant_group_count_skips_blank": ["group_by_count_distinct_values"],
    "mutant_replace_value_substring": ["replace_value_whole_cell"],
    "mutant_replace_text_whole_cell": ["replace_text_substring"],
    "mutant_replace_case_insensitive": ["replace_value_other_case", "replace_text_other_case"],
    "mutant_split_width_first_row": ["split_column_by_each_delimiter_pipe"],
    "mutant_merge_separator_off": ["merge_columns_two_dash"],
    "mutant_merge_skip_blank": ["merge_columns_two_dash"],
    "mutant_trim_spaces_only": ["trim_text_word_col"],
    "mutant_lower_non_ascii": ["lowercase_text_text_col"],
}


@pytest.mark.parametrize("rows,seed", [(50, 42), (400, 1), (2000, 7)])
def test_d0h_mutants_exit_1_on_generated_data_and_the_clean_run_exits_0(rows: int, seed: int) -> None:
    """Every D0h mutant makes the tool differ and exit 1 at 50, 400 and 2000 rows; the clean run exits 0."""
    ids = sorted({i for items in D0H_MUTANT_ITEMS.values() for i in items})
    mutants = list(D0H_MUTANT_ITEMS)
    sets = run_pq_step_diff_many(rows, seed, [{}] + [{m: True} for m in mutants], item_filter=ids)
    baseline = _d0h_baseline(ids)
    assert evaluate_exit_policy(sets[0], baseline) == (0, [])
    for mutant, data in zip(mutants, sets[1:]):
        code, _ = evaluate_exit_policy(data, baseline)
        assert code == 1, (mutant, rows, seed)
        killed = [r["id"] for r in data["results"] if r["status"] == "differs"]
        assert set(killed) & set(D0H_MUTANT_ITEMS[mutant]), (mutant, killed)


def test_d0h_steps_are_compared_or_refused_by_name_on_generated_data() -> None:
    """The listed items run `same`; the listed refusals carry a named reason; nothing differs."""
    compared = [
        "group_by_all_aggregates", "group_by_two_keys", "group_by_sum_num_clean", "group_by_min_dirty_num_col",
        "replace_text_overlapping", "replace_value_regex_chars", "trim_text_word_col", "proper_case_text_word_col",
        "reverse_text_text_col", "clean_text_text_col", "merge_columns_long_separator", "split_column_by_each_delimiter_pipe",
        "split_column_from_end_double_a",
    ]
    refused = [
        ("group_by_average_num_clean", "precision rule needs"), ("lowercase_text_text_col", "Python str case rules"),
        ("group_by_min_text_col", "casefold"), ("group_by_sum_dirty_num_col", "is not a valid number."),
        ("replace_value_bool_replacement", "keeps its type"),
    ]
    ids = compared + [i for i, _ in refused]
    data = run_pq_step_diff_many(300, 3, [{}], item_filter=ids)[0]
    by_id = {r["id"]: r for r in data["results"]}
    assert set(by_id) == set(ids)
    for item_id in compared:
        assert by_id[item_id]["status"] == "same" and by_id[item_id]["refusal"] is None, item_id
    for item_id, text in refused:
        assert text in by_id[item_id]["refusal"], item_id
    assert not [i for i, r in by_id.items() if r["status"] not in ("same", "refused")]


# ---- D0i: guards, from-end overlap, negative zero, loud-only mirrors

BIG = "9999999999999999999"
ROUNDS = "0.1234567890123456789"


@pytest.mark.parametrize(
    "mutant,cell,count,reason",
    [
        ("mutant_abs_sum_refusal_off", BIG, 20, "could leave DECIMAL(38,18)"),
        ("mutant_cast_agree_refusal_off", ROUNDS, 2, "does not read exactly"),
    ],
)
def test_group_by_sum_guards_refuse_by_name_and_the_mutant_differs_or_errors(
    mutant: str, cell: str, count: int, reason: str
) -> None:
    """Twenty 19-digit cells add up to more than 1.7e20 (the DECIMAL(38,18) sum overflows); a 19-decimal cell is rounded by the
    SQL cast. The clean run refuses each by name; with the guard off the SQL differs from the engine or fails."""
    table = {"headers": ["k", "v"], "rows": [["a", cell] for _ in range(count)]}
    item = _group_item("sum_guard", ["k"], [_agg("sum", "v", "s")])
    clean = _run_items(table, [item])
    assert _by_id(clean, "sum_guard")["status"] == "refused" and reason in _by_id(clean, "sum_guard")["refusal"]
    data = _run_items(table, [item], overrides={mutant: True})
    assert _by_id(data, "sum_guard")["status"] in {"differs", "sql-error"}, _by_id(data, "sum_guard")
    assert evaluate_exit_policy(data, {"classes": []})[0] == 1


def test_split_from_end_with_an_asymmetric_delimiter_reads_the_last_ab_and_the_mutant_exits_1() -> None:
    """'ab' is not its own reverse: the SQL must split the reversed text on 'ba'. 'xabyab', 'ab', 'abab' and 'aab' hand-checked."""
    table = {"headers": ["s", "n"], "rows": [["xabyab", "1"], ["ab", "2"], ["abab", "3"], ["aab", "4"], ["ba", "5"], ["x", "6"]]}
    item = {"id": "end_ab", "step": {"op": "split_column", "column": "s", "delimiter": "ab", "from_end": True}}
    assert _engine_rows(table, item) == [
        ["xaby", "", "1"], ["", "", "2"], ["ab", "", "3"], ["a", "", "4"], ["ba", None, "5"], ["x", None, "6"],
    ]
    assert _by_id(_run_items(table, [item]), "end_ab")["status"] == "same"
    data = _run_items(table, [item], overrides={"mutant_split_from_end_same_delim": True})
    assert _by_id(data, "end_ab")["status"] == "differs"
    assert evaluate_exit_policy(data, {"classes": []})[0] == 1
    ids = ["split_column_from_end_ab"]
    clean = run_pq_step_diff(rows=60, seed=3, item_filter=ids)
    assert _statuses(clean) == {"split_column_from_end_ab": "same"}
    mutant = run_pq_step_diff(rows=60, seed=3, overrides={"mutant_split_from_end_same_delim": True}, item_filter=ids)
    assert _statuses(mutant) == {"split_column_from_end_ab": "differs"}
    assert evaluate_exit_policy(mutant, {"classes": [], "refused": []})[0] == 1


def test_median_of_a_single_negative_zero_is_zero_and_the_keep_zeros_mutant_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine's median of '-0' is Decimal('-0'); the SQL gives 0. Both compare as '0' (`canon_decimal_text`);
    a canon that keeps the sign of zero makes the tool differ and exit 1."""
    table = {"headers": ["k", "v"], "rows": [["a", "-0"], ["b", "-0.00"]]}
    item = _group_item("med_zero", ["k"], [_agg("median", "v", "md"), _agg("sum", "v", "s")])
    assert _by_id(_run_items(table, [item]), "med_zero")["status"] == "same"
    real = pq_store_diff.canon_decimal_text

    def keep_zeros(text: str | None) -> str | None:
        out = real(text)
        return text if out == "0" and text is not None and text.startswith("-") else out

    monkeypatch.setattr(pq_store_diff, "canon_decimal_text", keep_zeros)
    data = _run_items(table, [item])
    assert _by_id(data, "med_zero")["status"] == "differs"
    assert evaluate_exit_policy(data, {"classes": []})[0] == 1


def _engine_error(table: dict[str, Any], item: dict[str, Any]) -> str:
    """The text the real step engine raises for one step on a small table."""
    path = _write_csv(table)
    result = pq_store_diff.execute_engine_step(item, parse_file(path), parse_file(path))
    assert isinstance(result, str), result
    return result


def test_group_by_with_no_columns_or_no_aggregations_names_the_engine_error_in_the_engine_order() -> None:
    table = {"headers": ["k", "v"], "rows": [["a", "1"], ["b", "2"]]}
    count = [_agg("count_rows", None, "n")]
    cases = [
        ("no_columns", [], count, "needs one or more group columns."),
        ("no_aggregations", ["k"], [], "needs one or more aggregations."),
        ("neither", [], [], "needs one or more group columns."),  # the columns are checked first
    ]
    items = [_group_item(name, keys, aggs) for name, keys, aggs, _text in cases]
    data = _run_items(table, items)
    for name, keys, aggs, text in cases:
        row = _by_id(data, name)
        assert row["status"] == "same", row
        assert text in _engine_error(table, _group_item(name, keys, aggs))
        assert row["refusal"] is not None


def test_malformed_step_shapes_are_refused_with_the_engine_text_and_never_crash_the_tool() -> None:
    table = {"headers": ["k", "v"], "rows": [["a", "1"], ["b", "2"]]}
    items = [
        {"id": "agg_no_column", "step": {"op": "group_by", "columns": ["k"], "aggregations": [{"operation": "sum", "new_name": "s"}]}},
        {"id": "agg_no_name", "step": {"op": "group_by", "columns": ["k"], "aggregations": [{"operation": "count_rows"}]}},
        {"id": "agg_bad_operation", "step": {"op": "group_by", "columns": ["k"], "aggregations": [{"operation": "mode", "new_name": "s"}]}},
        {"id": "group_no_aggregations_key", "step": {"op": "group_by", "columns": ["k"]}},
        {"id": "replace_no_replacement", "step": {"op": "replace_value", "column": "k", "value": "a"}},
        {"id": "replace_no_value", "step": {"op": "replace_value", "column": "k", "replacement": "z"}},
        {"id": "merge_no_separator", "step": {"op": "merge_columns", "columns": ["k", "v"], "new_name": "m"}},
        {"id": "split_no_delimiter", "step": {"op": "split_column", "column": "k"}},
        {"id": "trim_extra_field", "step": {"op": "trim_text", "column": "k", "extra": 1}},
    ]
    data = _run_items(table, items)
    assert {r["id"] for r in data["results"]} == {i["id"] for i in items}
    for item in items:
        row = _by_id(data, item["id"])
        assert row["status"] == "same" and row["refusal"], row
        assert _engine_error(table, item)  # the engine raises, and status "same" means the refusal text matched it
    assert "Aggregation 1 in step 1 has missing or invalid fields." in _engine_error(table, items[0])
    assert "Aggregation 1 in step 1 has missing or invalid fields." in _by_id(data, "agg_no_column")["refusal"]
    assert "Aggregation 1 in step 1 has an unsupported operation." in _by_id(data, "agg_bad_operation")["refusal"]


def test_merge_columns_names_with_edge_spaces_are_stripped_like_the_engine() -> None:
    """The engine strips the step's column names and the CSV import strips the headers ('s ' is 's', ' s' is 's_2')."""
    path = _write_csv({"headers": ["k", "s ", " s", "t"], "rows": [["a", "1", "2", "3"]]})
    assert parse_file(path).headers == ["k", "s", "s_2", "t"]
    table = {"headers": ["k", "s ", " s", "t"], "rows": [["a", "1", "2", "3"], ["b", "", "5", "6"], ["c", "7", "", ""]]}
    items = [
        {"id": "m_trailing", "step": {"op": "merge_columns", "columns": ["k", "s "], "separator": "-", "new_name": "m"}},
        {"id": "m_leading", "step": {"op": "merge_columns", "columns": [" s", "t"], "separator": "+", "new_name": " m "}},
        {"id": "m_new_name_is_selected_column", "step": {"op": "merge_columns", "columns": ["k", "t"], "separator": "|", "new_name": "t "}},
        {"id": "m_clash", "step": {"op": "merge_columns", "columns": ["k", "t"], "separator": "|", "new_name": " s "}},
        {"id": "m_duplicate_after_strip", "step": {"op": "merge_columns", "columns": ["s ", " s"], "separator": "-", "new_name": "m"}},
        {"id": "m_blank_name", "step": {"op": "merge_columns", "columns": ["k", "  "], "separator": "-", "new_name": "m"}},
    ]
    data = _run_items(table, items)
    assert {i["id"]: _by_id(data, i["id"])["status"] for i in items} == {i["id"]: "same" for i in items}
    for good in ("m_trailing", "m_leading", "m_new_name_is_selected_column"):
        assert _by_id(data, good)["refusal"] is None, good
    assert _engine_rows(table, items[0])[0] == ["a-1", "2", "3"]
    for bad in ("m_clash", "m_duplicate_after_strip", "m_blank_name"):
        assert _by_id(data, bad)["refusal"], bad


def test_split_by_each_delimiter_past_the_cell_limit_refuses_with_the_engine_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """rows * (columns - 1 + width) over the cell limit is the engine's error (limit lowered here; 500,000 in the app)."""
    from analytics_studio import transformations

    assert transformations.MAX_CELLS == pq_store_diff.MAX_CELLS == 500_000
    table = {"headers": ["s", "n"], "rows": [["a|b|c", str(i)] for i in range(5)]}  # width 3: 5 rows * 4 columns = 20 cells
    item = {"id": "cells", "step": {"op": "split_column_by_each_delimiter", "column": "s", "delimiter": "|"}}
    monkeypatch.setattr(transformations, "MAX_CELLS", 20)
    monkeypatch.setattr(pq_store_diff, "MAX_CELLS", 20)
    assert _by_id(_run_items(table, [item]), "cells")["refusal"] is None  # exactly at the limit is allowed
    monkeypatch.setattr(transformations, "MAX_CELLS", 19)
    monkeypatch.setattr(pq_store_diff, "MAX_CELLS", 19)
    row = _by_id(_run_items(table, [item]), "cells")
    assert row["status"] == "same" and "Splitting 's' exceeds the 19-cell import limit." in row["refusal"]
    assert "Splitting 's' exceeds the 19-cell import limit." in _engine_error(table, item)
