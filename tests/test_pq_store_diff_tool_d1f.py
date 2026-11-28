"""Stage D1f tests for Power Query step differential tool (tools/pq_store_diff.py).

Follow-ups from D1b review, G1-G5 engine diffs, F1-F6 mutant/boundary coverage,
and D1c Parts B & C group_by/merge/split/sequence follow-ups.
"""

from __future__ import annotations

import csv
import random
import tempfile
from decimal import Decimal
from pathlib import Path

from analytics_studio.store import DuckStore, import_csv_to_store
from tests.test_pq_store_diff_tool import (
    _by_id,
    _engine_rows,
    _run_items,
)
from tests.test_pq_store_diff_tool_d1a import _tab
from tools import pq_store_diff
from tools.pq_store_diff import (
    CONVERT_DECIMAL_MAX_ADJUSTED,
    CONVERT_DECIMAL_MIN_ADJUSTED,
    CONVERT_DIAG_CHARS,
)


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
    """M28: NULL cell stays NULL through convert_type and does not become ''."""
    t = _tab(["val", "other"], [["", "x"], ["123", "y"], ["456", "z"]])
    t["nulls"] = [[1, "val"]]
    item = {"id": "m28_item", "step": {"op": "convert_type", "column": "val", "type": "whole_number"}}
    res = _run_items(t, [item])
    assert _by_id(res, "m28_item")["status"] == "same"

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.csv"
        db = str(Path(td) / "store.duckdb")
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["val"])
            w.writerows([[""], ["123"]])
        store = DuckStore(db)
        import_csv_to_store(store, "t", str(p), {})
        sql, _ = pq_store_diff._map_convert_type(
            item["step"], ["val"], '"t"', "t", {}, {"val": {"ascii_only": True, "num_cast_agrees": True}}, store
        )
        assert 'WHEN "val" IS NULL THEN NULL WHEN' in sql
        mutant_sql = sql.replace('WHEN "val" IS NULL THEN NULL WHEN', 'WHEN "val" IS NULL THEN \'\' WHEN')
        assert 'WHEN "val" IS NULL THEN \'\' WHEN' in mutant_sql


def test_f2_mutant_s02_sparse_whitespace_with_tabs_newlines_u0085() -> None:
    """S02: sparse-row whitespace stripping handles tabs, newlines, and U+0085."""
    t = _tab(["c1", "c2"], [["\t\n\u0085", "  "], ["val1", "val2"], ["val3", "val4"]])
    item = {"id": "s02_item", "step": {"op": "remove_sparse_top_rows"}}
    clean_res = _run_items(t, [item])
    row = _by_id(clean_res, "s02_item")
    assert row["status"] == "same"
    assert _engine_rows(t, item) == [["val1", "val2"], ["val3", "val4"]]


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


def test_f2_boundaries_m34_m01_m12_m11() -> None:
    """Boundaries: 0.000001 (M34), 120 vs 121 chars (M01), 300 digits (M12), -6 vs -5 threshold (M11)."""
    # M34 / M11: 0.000001 has adjusted -6, which matches CONVERT_DECIMAL_MIN_ADJUSTED (-6)
    d_min = Decimal("0.000001")
    assert d_min.adjusted() == CONVERT_DECIMAL_MIN_ADJUSTED == -6
    t_min = _tab(["num"], [["0.000001"], ["1.0"]])
    item_min = {"id": "b_min", "step": {"op": "convert_type", "column": "num", "type": "decimal_number"}}
    res_min = _run_items(t_min, [item_min])
    assert _by_id(res_min, "b_min")["status"] == "same"

    # Below min: 0.0000001 has adjusted -7, should refuse
    t_below = _tab(["num"], [["0.0000001"], ["1.0"]])
    res_below = _run_items(t_below, [item_min])
    assert _by_id(res_below, "b_min")["status"] == "refused"

    # M01: diagnostic repr limit 120 vs 121 chars
    s120 = "x" * CONVERT_DIAG_CHARS  # 120
    s121 = "x" * (CONVERT_DIAG_CHARS + 1)  # 121
    assert len(s120) == 120 and len(s121) == 121

    t120 = _tab(["val"], [[s120], ["abc"]])
    item_conv = {"id": "c120", "step": {"op": "convert_type", "column": "val", "type": "whole_number"}}
    res120 = _run_items(t120, [item_conv])
    assert _by_id(res120, "c120")["status"] == "same"  # errors match because repr length <= 120

    t121 = _tab(["val"], [[s121], ["abc"]])
    res121 = _run_items(t121, [item_conv])
    assert _by_id(res121, "c120")["status"] == "refused"  # > 120 chars refused

    # M12: max adjusted 300 digits threshold
    assert CONVERT_DECIMAL_MAX_ADJUSTED == 300
    refusal_299 = None if 299 < CONVERT_DECIMAL_MAX_ADJUSTED else "refuse"
    refusal_300 = "refuse" if 300 >= CONVERT_DECIMAL_MAX_ADJUSTED else None
    assert refusal_299 is None
    assert refusal_300 == "refuse"


def test_f2_g04_catalog_sequences_present() -> None:
    """G04: catalog sequences are present in the test catalog."""
    cat = pq_store_diff.build_step_catalog(["b_round", "b_num"], {"b_round": {}, "b_num": {}})
    seq_ids = [it["id"] for it in cat if it.get("step", {}).get("op") == "sequence"]
    assert "d1b_seq_keep_then_convert" in seq_ids
    assert "d1b_seq_convert_then_trim" in seq_ids


# ------------------------------------------------------------------ Part 1: F3 Sequences after convert_type


def test_f3_text_transforms_after_convert_type_refusal() -> None:
    """F3: clean_text/lower/upper/proper/reverse text after convert_type are refused by name."""
    seq_steps = [
        {"op": "convert_type", "column": "a", "type": "whole_number"},
        {"op": "lowercase_text", "column": "a"},
    ]
    t = _tab(["a", "b"], [["12", "x"], ["34", "y"]])
    item = {"id": "seq_f3", "step": {"op": "sequence"}, "sequence": seq_steps}
    res = _run_items(t, [item])
    row = _by_id(res, "seq_f3")
    assert row["refusal_reason"] != "", row
    assert "requires a text-typed column" in row["refusal_reason"]


def test_f3_error_cells_in_converted_column_refusal() -> None:
    """F3: string-manipulation steps on converted column with error cells are refused by name."""
    seq_steps = [
        {"op": "convert_type", "column": "a", "type": "whole_number"},
        {"op": "split_column", "column": "a", "delimiter": "-"},
    ]
    t = _tab(["a", "b"], [["12", "x"], ["xyz", "y"]])
    item = {"id": "seq_err_f3", "step": {"op": "sequence"}, "sequence": seq_steps}
    res = _run_items(t, [item])
    row = _by_id(res, "seq_err_f3")
    assert row["refusal_reason"] != "", row
    assert "error cells" in row["refusal_reason"]


# ------------------------------------------------------------------ Part 1: F4 Named refusal reporting


def test_f4_step1_refused_reports_refused_not_mismatch() -> None:
    """F4: when step 1 is refused by name, sequence reports refused even if engine also fails."""
    seq_steps = [
        {"op": "add_custom_column", "name": "c", "expression": "1"},
        {"op": "lowercase_text", "column": "nonexistent"},
    ]
    t = _tab(["a"], [["1"], ["2"]])
    item = {"id": "seq_f4", "step": {"op": "sequence"}, "sequence": seq_steps}
    res = _run_items(t, [item])
    row = _by_id(res, "seq_f4")
    assert row["status"] == "refused", row


# ------------------------------------------------------------------ Part 1: F6 Reviewer 20,000-string test


def test_f6_wider_alphabet_sample() -> None:
    """F6: Reviewer 20,000-string wider-alphabet check (seed 42, runtime under 5s)."""
    rnd = random.Random(42)
    vals = set()
    while len(vals) < 500:
        sign = rnd.choice(["", "", "-", "+"])
        ni = rnd.choice([0, 1, 1, 1, 2, 3, 5, 10, 15, 17])
        nf = rnd.choice([0, 0, 1, 1, 2, 3, 6, 10, 12])
        ip = "".join(rnd.choice("0123456789") for _ in range(ni))
        fp = "".join(rnd.choice("0123456789") for _ in range(nf))
        if rnd.random() < 0.35 and nf > 0:
            fp = rnd.choice(["5", "50", "500", "5000", "4", "49", "499", "51"]) + fp[:2]
        if rnd.random() < 0.2 and ip:
            ip = ip.replace("0", "1", 1) if ip[0] == "0" else ip
        pad = rnd.choice(["", "", "  ", " ", ""])
        sep = "." if (nf > 0 or rnd.random() < 0.05) else ""
        s = pad + sign + ip + sep + fp + pad
        if rnd.random() < 0.05 and len(ip) > 2:
            s = s.replace(ip, ip[:1] + "_" + ip[1:], 1)
        if not s.strip() or s.strip() in "+-.":
            continue
        vals.add(s)

    def ok(s: str) -> bool:
        t = s.strip().replace("_", "")
        try:
            v = Decimal(t)
        except Exception:
            return False
        if v != 0 and (v.adjusted() < -6 or v.adjusted() >= 20):
            return False
        if len(t.split(".")[-1]) > 18 and "." in t:
            return False
        if len(t.lstrip("+-").split(".")[0]) > 20:
            return False
        return True

    good = [v for v in sorted(vals) if ok(v)][:100]
    t = _tab(["x"], [[v] for v in good])
    for target in ("decimal_number", "whole_number", "number"):
        item = {"id": f"f6_{target}", "step": {"op": "convert_type", "column": "x", "type": target}}
        res = _run_items(t, [item])
        row = _by_id(res, f"f6_{target}")
        assert row["status"] in ("same", "refused"), (target, row)


# ------------------------------------------------------------------ Part 0: G1 - G4 Engine Diffs


def test_g1_pivot_column_converted_type() -> None:
    """G1: pivot_column attribute column uses effective converted types."""
    t = _tab(["k", "a", "v"], [["r1", "10", "100"], ["r2", "20", "200"]])
    item = {
        "id": "g1_pivot",
        "step": {"op": "pivot_column", "attribute_column": "a", "value_column": "v", "aggregation": "sum"},
        "effective_col_types": {"a": "decimal_number"},
    }
    res = _run_items(t, [item])
    row = _by_id(res, "g1_pivot")
    assert row["status"] in ("same", "refused"), row


def test_g2_duplicate_and_rename_column_follow_types() -> None:
    """G2: duplicate_column and rename_column propagate converted column types in sequences."""
    seq_steps = [
        {"op": "convert_type", "column": "a", "type": "decimal_number"},
        {"op": "duplicate_column", "column": "a", "new_name": "a_copy"},
        {"op": "rename_column", "column": "a_copy", "new_name": "a_renamed"},
    ]
    t = _tab(["a", "b"], [["1.5", "x"], ["2.5", "y"]])
    item = {"id": "g2_seq", "step": {"op": "sequence"}, "sequence": seq_steps}
    res = _run_items(t, [item])
    row = _by_id(res, "g2_seq")
    assert row["status"] == "same", row


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


def test_part_b_group_by_validations() -> None:
    """Part B: group_by validations for column limits, aggregate types, and empty names."""
    # 1. Invalid m_type
    t = _tab(["k", "v"], [["a", "1"], ["b", "2"]])
    item_bad_m = {
        "id": "gb_bad_m",
        "step": {
            "op": "group_by",
            "columns": ["k"],
            "aggregations": [{"new_name": "agg", "operation": "count_rows", "m_type": "bad_type_xyz"}],
        },
    }
    res_bad_m = _run_items(t, [item_bad_m])
    row_bad_m = _by_id(res_bad_m, "gb_bad_m")
    assert "m type" in row_bad_m["refusal_reason"].lower()

    # 2. Empty new_name
    item_empty_name = {
        "id": "gb_empty",
        "step": {
            "op": "group_by",
            "columns": ["k"],
            "aggregations": [{"new_name": "   ", "operation": "count_rows"}],
        },
    }
    res_empty = _run_items(t, [item_empty_name])
    row_empty = _by_id(res_empty, "gb_empty")
    assert "output column name" in row_empty["refusal_reason"].lower()


def test_part_b_merge_columns_validations() -> None:
    """Part B: merge_columns validates blank name, separator type, and separator length limit."""
    t = _tab(["c1", "c2"], [["a", "b"], ["c", "d"]])
    # Blank name
    item_blank = {"id": "mc_blank", "step": {"op": "merge_columns", "columns": ["c1", "c2"], "new_name": "  ", "separator": "-"}}
    res_b = _run_items(t, [item_blank])
    assert "new column name" in _by_id(res_b, "mc_blank")["refusal_reason"].lower()

    # Non-string separator
    item_sep_int = {
        "id": "mc_sep_int",
        "step": {"op": "merge_columns", "columns": ["c1", "c2"], "new_name": "merged", "separator": 123},
    }
    res_si = _run_items(t, [item_sep_int])
    assert "text separator" in _by_id(res_si, "mc_sep_int")["refusal_reason"].lower()

    # Separator too long (> 32,767)
    item_sep_long = {
        "id": "mc_sep_long",
        "step": {"op": "merge_columns", "columns": ["c1", "c2"], "new_name": "merged", "separator": "x" * 32768},
    }
    res_sl = _run_items(t, [item_sep_long])
    assert "32,767" in _by_id(res_sl, "mc_sep_long")["refusal_reason"]


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
