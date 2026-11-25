"""Tests for Stage C0e store_engine_diff tool.

Every rule of the tool is killed by behaviour: a mutant (an override that breaks one rule, or a forced wrong value)
must change a status, a value or the exit policy code. No test asserts on the text of generated SQL.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from analytics_studio.store import DuckStore, import_csv_to_store
from tools import store_engine_diff
from tools.store_engine_diff import (
    StoreResultLayer,
    Refusal,
    classify_parquet_diff,
    eval_distinct_numeric_predicate,
    evaluate_exit_policy,
    generate_markdown_report,
    generate_sql,
    refusal_matches_engine_error,
    run_comparison,
)

CLASSES = ["distinct_numeric_text_variants", "parquet_source_precision", "parquet_counta_refusal"]
BASELINE_FILE = Path(store_engine_diff.__file__).parent / "store_engine_diff_baseline.json"


@pytest.fixture(scope="module")
def run50() -> dict[str, Any]:
    return run_comparison(rows=50, seed=42)


@pytest.fixture(scope="module")
def run100() -> dict[str, Any]:
    return run_comparison(rows=100, seed=7)


def _run(
    overrides: dict[str, Any] | None,
    ids: list[str],
    *,
    rows: int = 100,
    seed: int = 42,
    parquet: bool = False,
    group_by: bool = False,
) -> dict[str, Any]:
    """Targeted run: only the named formulas, only the paths under test."""
    return run_comparison(
        rows=rows,
        seed=seed,
        overrides=overrides,
        formula_filter=ids,
        skip_naive=True,
        skip_parquet=not parquet,
        skip_group_by=not group_by,
    )


def _policy(data: dict[str, Any], classes: list[str] | None = None) -> tuple[int, list[str]]:
    """Exit policy with a baseline that lists classes only (the refused set is not checked on subset runs)."""
    return evaluate_exit_policy(data, {"classes": CLASSES if classes is None else classes})


def _status(data: dict[str, Any], f_id: str) -> str:
    return next(r["mapped_status"] for r in data["results"] if r["id"] == f_id)


# ------------------------------------------------------------------ end to end


def test_tool_runs_end_to_end_and_has_unique_ids(run100: dict[str, Any]) -> None:
    """Tool runs end-to-end offscreen, formula list >= 200 with unique ids."""
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"

    results = run100["results"]
    assert len(results) >= 200

    ids = [r["id"] for r in results]
    assert len(ids) == len(set(ids)), "All formula IDs must be unique"

    md = generate_markdown_report(run100)
    assert "# Engine versus DuckStore Rules Table Report" in md
    assert "## Headline Summary" in md
    assert "## Rules Table Grouped by Shape" in md
    assert "## VM Check List" in md
    assert "## Parquet Path Comparison" in md


def test_known_differences_naive_differs_mapped_same(run100: dict[str, Any]) -> None:
    """Check at least 8 known differences from the attack are differs in naive and same in mapped."""
    by_id = {r["id"]: r for r in run100["results"]}

    check_ids = [
        "DISTINCTCOUNT_t",
        "COUNTROWS_t_text_eq_lower",
        "COUNTROWS_t_w_zero",
        "COUNTROWS_t_w_lt",
        "COUNT_w",
        "COUNTROWS_t_empty_set",
        "MIN_dt",
        "arith_sum_d_div_count",
    ]

    for c_id in check_ids:
        assert c_id in by_id, f"Formula {c_id} missing from results"
        r = by_id[c_id]
        assert r["naive_status"] == "differs", f"{c_id} naive status should be differs, got {r['naive_status']}"
        assert r["mapped_status"] == "same", f"{c_id} mapped status should be same, got {r['mapped_status']}"


def test_known_engine_errors_flagged(run100: dict[str, Any]) -> None:
    """Engine errors on invalid types (SUM of text, bool, date) are recorded as engine-error in naive."""
    by_id = {r["id"]: r for r in run100["results"]}

    for agg_id in ["SUM_t", "SUM_flag", "SUM_dt"]:
        r = by_id[agg_id]
        assert r["engine_err"] is not None
        assert r["naive_status"] == "engine-error"
        assert r["mapped_status"] == "same"  # refused like engine in mapped SQL


def test_tool_deterministic(run50: dict[str, Any]) -> None:
    """Same seed produces identical JSON outputs."""
    res1 = copy.deepcopy(run50)
    res2 = run_comparison(rows=50, seed=42)

    # Exclude wall_sec since execution time varies slightly
    res1.pop("wall_sec")
    res2.pop("wall_sec")

    assert json.dumps(res1, sort_keys=True, default=str) == json.dumps(res2, sort_keys=True, default=str)


# ------------------------------------------------------------------ mapped rules: mutants change results


def test_mutants_fail_when_mapped_rule_broken(run50: dict[str, Any]) -> None:
    """Break mapped rules via overrides and verify the mapped status changes (kills mutants M1-M15)."""
    mutants = [
        ("M1 drop DISTINCTCOUNT fold", {"drop_distinct_fold": True}, "DISTINCTCOUNT_t"),
        ("M2 drop COALESCE in w=0", {"drop_w_zero_coalesce": True}, "COUNTROWS_t_w_zero"),
        ("M3 drop rtrim in fold", {"drop_rtrim": True}, "COUNTROWS_t_text_eq_space"),
        ("M4 SUM whole HUGEINT->DOUBLE", {"m4_whole_double": True}, "SUM_w"),
        ("M5 COUNTA counts non-blank only", {"m5_counta_nonblank": True}, "COUNTA_w"),
        ("M5 prime COUNTA nonblank CSV", {"m5_prime_counta_nonblank": True}, "COUNTA_w"),
        ("M6 date serial epoch off by one", {"m6_date_epoch_off": True}, "MIN_dt"),
        ("M8 SUM decimal DECIMAL->DOUBLE", {"m8_decimal_double": True}, "SUM_d"),
        ("M8 prime SUM decimal CSV", {"m8_prime_decimal_double": True}, "SUM_d"),
        ("M9 broken SQL where engine errors", {"broken_sql_m9": True}, "SUM_t"),
        ("M10 filter w<100 drop COALESCE", {"drop_w_lt_coalesce": True}, "COUNTROWS_t_w_lt"),
        ("M11 empty-set guard removed", {"drop_empty_guard": True}, "COUNTROWS_t_empty_set"),
        ("M12 trim set space only", {"trim_set_space_only": True}, "COUNTROWS_t_text_eq_untrimmed"),
        ("M13 scale hardcoded 4", {"hardcode_scale_4": True}, "SUM_w_d_neq"),
        ("M14 DISTINCTCOUNT numeric without +1", {"m14_distinct_no_blank_add": True}, "DISTINCTCOUNT_w"),
        ("M15 num gte to gt", {"m15_num_gte_to_gt": True}, "COUNTROWS_t_w_gte"),
        ("M15 date gte to gt", {"m15_date_gte_to_gt": True}, "COUNTROWS_t_dt_range"),
    ]

    for name, overrides, f_id in mutants:
        assert _status(run50, f_id) == "same", f"Clean run must match the engine on {f_id}"
        mutated = _run(overrides, [f_id], rows=50)
        assert _status(mutated, f_id) in ("differs", "sql-error"), f"Mutant '{name}' failed to kill {f_id}"


def test_null_comparison_mutants_change_results() -> None:
    """Blank numbers compare as 0: dropping COALESCE in <=, <>, NOT(=) and d >= 0 changes the mapped counts."""
    cases = [
        ("drop_w_lte_coalesce", "COUNTROWS_t_w_lte"),
        ("drop_w_neq_coalesce", "COUNTROWS_t_w_neq"),
        ("drop_w_neq_coalesce", "COUNTROWS_t_w_not"),
        ("drop_d_gte_coalesce", "COUNTROWS_t_d_gte"),
    ]
    for override, f_id in cases:
        assert _status(_run({}, [f_id]), f_id) == "same", f"Clean run must match the engine on {f_id}"
        assert _status(_run({override: True}, [f_id]), f_id) == "differs", f"{override} must change {f_id}"


def _small_store(tmp_path: Path, csv_text: str) -> DuckStore:
    csv_path = tmp_path / "small.csv"
    csv_path.write_text(csv_text, encoding="utf-8")
    store = DuckStore(str(tmp_path / "small.db"))
    import_csv_to_store(store, "t_csv", csv_path, {})
    return store


SMALL_TYPES = {"id": "text", "w": "whole_number", "d": "decimal_number", "t": "text", "dt": "date", "cat": "text"}
SMALL_META = {"decimal_scales": {"d": 4, "w": 4, "big": 4, "num_dups": 4}, "max_digits": {}}
SMALL_CSV = (
    "id,w,d,t,dt,cat\n"
    "1,100,1.5,East,2026-06-01,A\n"
    "2,,,east,,A\n"
    "3,200,-1,EAST ,2026-07-01,B\n"
    "4,50,0,SS,2026-05-01,B\n"
    "5,,2,ss,,A\n"
    "6,7,,,2026-06-02,B\n"
)


def _mapped_value(store: DuckStore, agg: str, col: str | None, filter_type: str | None) -> Any:
    formula = {"id": "x", "agg": agg, "col": col, "filter_type": filter_type, "shape": "x"}
    sql = generate_sql(formula, "t_csv", SMALL_TYPES, mode="mapped", store_meta=SMALL_META)
    assert isinstance(sql, str)
    return store.execute(sql)[0][0]


def test_mapped_rules_on_small_data(tmp_path: Path) -> None:
    """Six hand-checked rows: each rule gives the DAX answer, and each broken variant would give another number."""
    store = _small_store(tmp_path, SMALL_CSV)
    try:
        # blank w counts as 0: w <> 100 keeps rows 2..6, w <= 100 keeps rows 1,2,4,5,6, NOT(w = 100) keeps rows 2..6
        assert _mapped_value(store, "COUNTROWS", None, "w_neq") == 5
        assert _mapped_value(store, "COUNTROWS", None, "w_not") == 5
        assert _mapped_value(store, "COUNTROWS", None, "w_lte") == 5
        # blank d counts as 0: d >= 0 keeps rows 1,2,4,5,6
        assert _mapped_value(store, "COUNTROWS", None, "d_gte") == 5
        # text fold: trailing space dropped, ASCII lowercase: East, east and "EAST " all equal "EAST"
        assert _mapped_value(store, "COUNTROWS", None, "text_eq_upper") == 3
        # text_ss: "SS" and "ss" fold to the same text
        assert _mapped_value(store, "COUNTROWS", None, "text_ss") == 2
        # COUNTBLANK of text counts the empty string (row 6)
        assert _mapped_value(store, "COUNTBLANK", "t", None) == 1
    finally:
        store.close()


def test_divide_is_exact_decimal() -> None:
    """AVERAGE divides in Decimal: 10 / 3 carries Decimal digits, not float digits."""
    assert StoreResultLayer.divide("10", "3") == Decimal(10) / Decimal(3)
    assert StoreResultLayer.divide(Decimal("123456789012345.6789"), 7) == Decimal("123456789012345.6789") / Decimal(7)
    assert StoreResultLayer.divide("10", 0) is None
    assert StoreResultLayer.divide(None, 3) is None


def test_scale_keyed_by_filtered_column(run50: dict[str, Any]) -> None:
    """A filter on d uses the scale of d, not the scale of the aggregated column w (M13 hard-coded 4 is killed)."""
    assert run50["decimal_scales"]["d"] > run50["decimal_scales"]["w"], "data must make the two scales differ"
    res = _run({}, ["SUM_w_d_neq", "COUNTROWS_t_d_neq", "SUM_d_d_neq"], rows=50)
    for r in res["results"]:
        assert r["mapped_status"] == "same", f"{r['id']} failed: {r}"
    hard = _run({"hardcode_scale_4": True}, ["SUM_w_d_neq"], rows=50)
    assert _status(hard, "SUM_w_d_neq") == "differs"


def test_blank_date_rules_per_operator() -> None:
    """Blank dates: dt <= D and dt <> D include blanks; dt >= D and dt > D do not."""
    res = _run(
        {},
        ["COUNTROWS_t_dt_lte", "COUNTROWS_t_dt_lt", "COUNTROWS_t_dt_neq", "COUNTROWS_t_dt_gt", "COUNTROWS_t_dt_range"],
        rows=50,
    )
    assert len(res["results"]) == 5
    for r in res["results"]:
        assert r["mapped_status"] == "same", f"Date rule mismatch on {r['id']}"


def test_exact_average_at_high_magnitude() -> None:
    """AVERAGE computes sum/count in Python Decimal result layer without double precision loss."""
    res = _run({}, ["AVERAGE_d"], rows=50)
    r = res["results"][0]
    assert r["mapped_status"] == "same", f"AVERAGE_d precision loss: {r}"
    assert Decimal(str(r["mapped_val"])) > 10000000000000, "Must be at 1e13-1e14 magnitude"


# ------------------------------------------------------------------ group-by


def test_group_by_mutants_and_harness() -> None:
    """Group-by harness kills SUM DOUBLE, AVERAGE float, DISTINCTCOUNT without +1, extra/missing/order mutants."""
    cases = [
        # (override, formula, rows): the clean run must be same, the mutant must change the answer
        ("gb_sum_double", "group_by_cat_SUM_w", 1000),  # w sums above 2^53 lose digits in DOUBLE
        ("gb_sum_double", "group_by_cat_SUM_d", 50),
        ("gb_avg_float", "group_by_cat_AVERAGE_d", 50),
        # flag has blank cells in every group; the engine counts blank as a value, so +1 is needed
        ("gb_distinct_no_blank_add", "group_by_cat_DISTINCTCOUNT_flag", 50),
    ]
    for override, f_id, rows in cases:
        clean = _run({}, [f_id], rows=rows, group_by=True)
        assert _status(clean, f_id) == "same", f"Clean run must match the engine on {f_id}"
        mutated = _run({override: True}, [f_id], rows=rows, group_by=True)
        assert _status(mutated, f_id) == "differs", f"{override} must change {f_id}"

    # Key set and key order mutants are sql-errors
    for override in ("gb_missing_key", "gb_extra_key", "gb_reverse_order"):
        res = _run({override: True}, ["group_by_cat_SUM_w"], rows=50, group_by=True)
        assert _status(res, "group_by_cat_SUM_w") == "sql-error", override


def test_group_by_distinct_column_has_blanks() -> None:
    """The group-by DISTINCTCOUNT target flag has blank cells, so the blank +1 rule is exercised."""
    res = _run({}, ["group_by_cat_DISTINCTCOUNT_flag"], rows=50, group_by=True)
    r = res["results"][0]
    assert r["mapped_status"] == "same"
    # a group of 3 values (TRUE, FALSE, blank) is only possible with the +1 for the blank cells
    values = {kv[1] for kv in r["mapped_kv"]}
    assert "3" in values and values <= {"1", "2", "3"}, r["mapped_val"]


def test_group_by_harness_blank_key_and_order() -> None:
    """Group-by harness preserves blank key, matches engine VertiPaq order, and formats values."""
    res_gb = _run({}, ["group_by_cat_SUM_w", "group_by_dt_MIN_dt"], rows=50, group_by=True)
    assert len(res_gb["results"]) == 2
    for r in res_gb["results"]:
        assert r["mapped_status"] == "same", f"Group-by mismatch on {r['id']}"
        assert ":" in r["mapped_val"], "Group-by must format key-value pairs separated by :"
        if r["id"] == "group_by_dt_MIN_dt":
            assert r["mapped_val"].startswith('"":'), "Blank key group must be preserved and present"


# ------------------------------------------------------------------ refusals


def test_refusals_have_reasons() -> None:
    """Store refusals (DISTINCTCOUNTNOBLANK, COUNT of text) must carry explicit reason string."""
    res = _run({}, ["DISTINCTCOUNTNOBLANK_w", "COUNT_t"], rows=50)
    assert len(res["results"]) == 2
    for r in res["results"]:
        assert r["mapped_status"] == "refused"
        ref_text = r.get("mapped_refusal")
        assert ref_text and ref_text.startswith("REFUSED:"), f"Missing refusal string: {r}"


def test_every_refusal_with_engine_error_names_that_error(run100: dict[str, Any]) -> None:
    """A refusal that stands for an engine error carries expected text, and the engine error contains it."""
    with_engine_error = [r for r in run100["results"] if r["mapped_refusal_obj"] is not None and r["engine_err"]]
    assert len(with_engine_error) >= 60
    for r in with_engine_error:
        expected = r["mapped_refusal_obj"].expected_error
        assert expected, f"{r['id']}: refusal for an engine error has no expected text"
        assert expected in r["engine_err"], f"{r['id']}: '{expected}' not in '{r['engine_err']}'"
        assert r["mapped_status"] == "same"

    by_id = {r["id"]: r for r in run100["results"]}
    # numeric IN and && refusals compare the engine text, date IN too
    for f_id, text in [
        ("COUNTROWS_t_w_in", "Cannot convert value '' of type Text to type Number."),
        ("COUNTROWS_t_filter_two_cols", "Cannot convert value '' of type Text to type Number."),
        ("COUNTROWS_t_dt_in", "Cannot convert value '46174' of type Text to type Date."),
    ]:
        assert by_id[f_id]["mapped_refusal_obj"].expected_error == text


def test_refusal_text_has_no_data_dependent_row_number(run100: dict[str, Any]) -> None:
    """The engine names the first offending row; expected text must not, or the tool breaks on other seeds."""
    for r in run100["results"]:
        obj = r["mapped_refusal_obj"]
        if obj is not None and obj.expected_error:
            assert " at row " not in obj.expected_error, r["id"]


def test_refusal_text_matches_engine_when_first_row_is_blank() -> None:
    """Seed 15 names row 2 for COUNT(flag) (row 1 flag is blank): the refusal must still match."""
    res = _run({}, ["COUNT_flag"], rows=2000, seed=15)
    r = res["results"][0]
    assert "at row 2" in r["engine_err"]
    assert r["mapped_status"] == "same"


# ------------------------------------------------------------------ class predicate DISTINCTCOUNT numeric


PRED_CSV = (
    "id,w,num_dups,d,t,dt,cat\n"
    "1,1,5,0.000000001,a,2026-06-01,A\n"
    "2,1.0,5,0.000000001,a,2026-06-01,A\n"
    "3,+1,5.0,,a,2026-06-01,A\n"
    "4,2,6,0.000000001,a,2026-06-01,A\n"
    "5,,6,0.5,a,2026-06-01,A\n"
)


def test_distinct_predicate_class_membership(tmp_path: Path) -> None:
    """The class holds only for engine minus mapped == surplus textual forms; any other value is not a member."""
    store = _small_store(tmp_path, PRED_CSV)
    meta_9 = {"decimal_scales": {"d": 9, "w": 4, "num_dups": 4}, "max_digits": {}}
    meta_4 = {"decimal_scales": {"d": 4, "w": 4, "num_dups": 4}, "max_digits": {}}
    try:
        w_all = {"agg": "DISTINCTCOUNT", "col": "w", "filter_type": None}
        # w: forms 1, 1.0, +1, 2 and a blank = 5 textual values; numbers 1, 2 and the blank = 3 -> surplus 2
        assert eval_distinct_numeric_predicate({"engine_val": "5", "mapped_val": "3"}, w_all, store, meta_9)
        # forced wrong values: engine - mapped is not the surplus (killers for >= 0 and always-True predicates)
        assert not eval_distinct_numeric_predicate({"engine_val": "5", "mapped_val": "2"}, w_all, store, meta_9)
        assert not eval_distinct_numeric_predicate({"engine_val": "4", "mapped_val": "3"}, w_all, store, meta_9)
        assert not eval_distinct_numeric_predicate({"engine_val": "3", "mapped_val": "3"}, w_all, store, meta_9)
        assert not eval_distinct_numeric_predicate({"engine_val": "BLANK", "mapped_val": "3"}, w_all, store, meta_9)

        nd_all = {"agg": "DISTINCTCOUNT", "col": "num_dups", "filter_type": None}
        assert eval_distinct_numeric_predicate({"engine_val": "3", "mapped_val": "2"}, nd_all, store, meta_9)

        # filter on d: the rows kept depend on the scale of d (9 here), taken from the real mapped WHERE clause
        w_d_neq = {"agg": "DISTINCTCOUNT", "col": "w", "filter_type": "d_neq"}
        assert eval_distinct_numeric_predicate({"engine_val": "4", "mapped_val": "3"}, w_d_neq, store, meta_9)
        # at scale 4 the 1e-9 cells round to 0 and the filter keeps another set of rows: no surplus form remains
        assert not eval_distinct_numeric_predicate({"engine_val": "4", "mapped_val": "3"}, w_d_neq, store, meta_4)

        # not a DISTINCTCOUNT of w or num_dups: never a member, whatever the numbers are
        for item in (
            {"agg": "DISTINCTCOUNT", "col": "w_blank", "filter_type": None},
            {"agg": "DISTINCTCOUNT", "col": "d", "filter_type": None},
            {"agg": "COUNTROWS", "col": None, "filter_type": "w_zero"},
            {"agg": "SUM", "col": "w", "filter_type": None},
        ):
            assert not eval_distinct_numeric_predicate({"engine_val": "5", "mapped_val": "3"}, item, store, meta_9)
    finally:
        store.close()


def test_class_member_and_non_member_exit_codes() -> None:
    """A real class member exits 0; the same formula with a wrong mapped value and a non-member difference exit 1."""
    member = _run({}, ["DISTINCTCOUNT_w", "DISTINCTCOUNT_num_dups"], rows=800)
    for r in member["results"]:
        assert r["mapped_status"] == "differs"
        assert r["mapped_diff_class"] == "distinct_numeric_text_variants"
    assert _policy(member)[0] == 0

    # wrong value: M14 (no +1 for blanks) makes engine - mapped = surplus + 1, so the class does not hold
    wrong = _run({"m14_distinct_no_blank_add": True}, ["DISTINCTCOUNT_w"], rows=800)
    assert wrong["results"][0]["mapped_status"] == "differs"
    assert wrong["results"][0]["mapped_diff_class"] is None
    code, messages = _policy(wrong)
    assert code == 1 and "un-baselined" in messages[0]

    # non-member: a difference on a formula that is not a numeric DISTINCTCOUNT
    other = _run({"drop_w_zero_coalesce": True}, ["COUNTROWS_t_w_zero"], rows=100)
    assert other["results"][0]["mapped_status"] == "differs"
    assert other["results"][0]["mapped_diff_class"] is None
    code, messages = _policy(other)
    assert code == 1 and "un-baselined" in messages[0]


def test_filtered_distinct_class_uses_real_filter_scale() -> None:
    """Seed 11 at 2000 rows: DISTINCTCOUNT_w_d_neq (d has scale 9) is a class member (rows kept use the real filter)."""
    res = _run({}, ["DISTINCTCOUNT_w_d_neq", "DISTINCTCOUNT_w_blank"], rows=2000, seed=11)
    by_id = {r["id"]: r for r in res["results"]}
    assert res["decimal_scales"]["d"] == 9
    assert by_id["DISTINCTCOUNT_w_d_neq"]["mapped_status"] == "differs"
    assert by_id["DISTINCTCOUNT_w_d_neq"]["mapped_diff_class"] == "distinct_numeric_text_variants"
    # the all-blank column w_blank is not column w
    assert by_id["DISTINCTCOUNT_w_blank"]["mapped_diff_class"] is None
    assert _policy(res)[0] == 0


# ------------------------------------------------------------------ Parquet path: mutants change the exit code


PARQUET_IDS = ["SUM_d", "AVERAGE_d", "COUNTA_d", "COUNTA_w", "SUM_w", "DISTINCTCOUNT_d", "MAX_d", "MIN_d"]


def test_parquet_clean_run_classes_are_by_data() -> None:
    """Clean run: the known Parquet differences are classified by data and the policy passes."""
    data = _run({}, PARQUET_IDS, parquet=True)
    by_id = {r["id"]: r for r in data["results"]}
    assert by_id["SUM_d"]["pq_vs_csv_diff"] and by_id["SUM_d"]["pq_diff_class"] == "parquet_source_precision"
    assert by_id["COUNTA_d"]["pq_vs_csv_diff"] and by_id["COUNTA_d"]["pq_diff_class"] == "parquet_counta_refusal"
    assert by_id["COUNTA_w"]["pq_diff_class"] == "parquet_counta_refusal"
    assert not by_id["SUM_w"]["pq_vs_csv_diff"]
    assert _policy(data) == (0, [])


@pytest.mark.parametrize(
    "name, override, f_ids",
    [
        ("N04 Parquet whole SUM(col+1)", "pq_sum_plus_one", ["SUM_w"]),
        ("N07 Parquet AVERAGE cast at scale 0", "pq_avg_scale0", ["AVERAGE_d"]),
        ("S09 Parquet DECIMAL by direct CAST", "pq_decimal_direct_cast", ["SUM_d"]),
        ("S10 Parquet COUNTA refusal removed", "pq_counta_no_refusal", ["COUNTA_d", "COUNTA_w"]),
        ("S08 Parquet DISTINCTCOUNT without +1", "pq_distinct_no_blank_add", ["DISTINCTCOUNT_d"]),
    ],
)
def test_parquet_mutants_exit_one(name: str, override: str, f_ids: list[str]) -> None:
    """Each broken Parquet rule produces an unclassified Parquet difference and the tool exits 1."""
    data = _run({override: True}, f_ids, parquet=True)
    flagged = [r for r in data["results"] if r["pq_vs_csv_diff"]]
    assert flagged, f"{name}: no Parquet difference was produced"
    assert all(r["pq_diff_class"] is None for r in flagged), name
    code, messages = _policy(data)
    assert code == 1, name
    assert "Parquet" in messages[0], name


def test_parquet_group_by_precision_classified_by_data() -> None:
    """Group-by SUM and AVERAGE of d differ on Parquet and match the DOUBLE-rounded cells group by group."""
    data = _run({}, ["group_by_cat_SUM_d", "group_by_flag_AVERAGE_d"], rows=2000, parquet=True, group_by=True)
    by_id = {r["id"]: r for r in data["results"]}
    assert by_id["group_by_cat_SUM_d"]["pq_vs_csv_diff"]
    assert by_id["group_by_cat_SUM_d"]["pq_diff_class"] == "parquet_source_precision"
    assert _policy(data)[0] == 0


def _pq_result(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "pq_refusal": None,
        "mapped_refusal": None,
        "pq_err": None,
        "mapped_err": None,
        "mapped_val": "None",
        "pq_val": "None",
        "pq_text": "",
        "mapped_kv": None,
        "pq_kv": None,
    }
    base.update(fields)
    return base


def test_parquet_classes_need_their_data(tmp_path: Path) -> None:
    """Class rules on crafted results: each condition of a Parquet class must hold, or the difference is unclassified."""
    store = _small_store(tmp_path, "id,d\n1,123456789012345.6789\n2,0.1\n")
    meta = {"decimal_scales": {"d": 4}, "max_digits": {}}
    cells = [123456789012345.6789, 0.1]
    ctx = {"store": store, "store_meta": meta, "overrides": {}, "group_keys": {"cat": ["A", "B"]}, "cols": {"d": cells, "w": [1, 2], "cat": ["A", "A"]}}
    sum_d = {"agg": "SUM", "col": "d", "filter_type": None}
    try:
        # exact CSV sum 123456789012345.7789 (19 digits); Parquet holds the DOUBLE-rounded cells: ...345.67 + 0.1
        good = _pq_result(mapped_val="123456789012345.7789", pq_val="123456789012345.7700", pq_text="x")
        assert classify_parquet_diff(good, sum_d, ctx) == "parquet_source_precision"
        # Parquet value is not the sum of the DOUBLE-rounded cells
        off = _pq_result(mapped_val="123456789012345.7789", pq_val="123456789012345.7701", pq_text="x")
        assert classify_parquet_diff(off, sum_d, ctx) is None
        # CSV exact value has 15 or fewer significant digits: precision loss cannot explain a difference
        short = _pq_result(mapped_val="123456789012345", pq_val="123456789012345.7700", pq_text="x")
        assert classify_parquet_diff(short, sum_d, ctx) is None
        # a Parquet error or refusal is never a precision difference
        assert classify_parquet_diff(dict(good, pq_err="boom"), sum_d, ctx) is None
        # only the decimal column d is covered
        sum_w = {"agg": "SUM", "col": "w", "filter_type": None}
        assert classify_parquet_diff(good, sum_w, ctx) is None

        # COUNTA: only the exact refusal, and only where the CSV store answered with a value
        counta = {"agg": "COUNTA", "col": "d", "filter_type": None}
        exact = _pq_result(pq_refusal="REFUSED: COUNTA on Parquet typed columns differs from CSV store", pq_text="REFUSED")
        assert classify_parquet_diff(exact, counta, ctx) == "parquet_counta_refusal"
        other = _pq_result(pq_refusal="REFUSED: COUNT not supported on text column", pq_text="REFUSED")
        assert classify_parquet_diff(other, counta, ctx) is None
        assert classify_parquet_diff(_pq_result(pq_val="2"), counta, ctx) is None
        assert classify_parquet_diff(dict(exact, mapped_refusal="REFUSED: x"), counta, ctx) is None

        # group-by SUM of d: the Parquet text must equal the per-group sums of the DOUBLE-rounded cells
        gb = {"agg": "SUM", "col": "d", "group_col": "cat", "filter_type": "group_by"}
        csv_kv = [["A", "123456789012345.7789"], ["B", "BLANK"]]
        good_gb = _pq_result(mapped_kv=csv_kv, pq_kv=[["A", "123,456,789,012,345.77"], ["B", "BLANK"]], pq_text="A:123,456,789,012,345.77;B:BLANK")
        assert classify_parquet_diff(good_gb, gb, ctx) == "parquet_source_precision"
        bad_gb = dict(good_gb, pq_text="A:123,456,789,012,345.78;B:BLANK")
        assert classify_parquet_diff(bad_gb, gb, ctx) is None
    finally:
        store.close()


def test_refusal_must_name_the_engine_error() -> None:
    """A refusal for an engine error needs expected text that the engine error contains."""
    engine_err = "Cannot convert value '' of type Text to type Number."
    assert refusal_matches_engine_error(Refusal("r", expected_error="Cannot convert value ''"), engine_err)
    assert not refusal_matches_engine_error(Refusal("r", expected_error=None), engine_err)
    assert not refusal_matches_engine_error(Refusal("r", expected_error=""), engine_err)
    assert not refusal_matches_engine_error(Refusal("r", expected_error="Cannot convert value 'zzz'"), engine_err)


# ------------------------------------------------------------------ SQL error exit


def test_sql_error_exits_one() -> None:
    """A mapped SQL error where the engine also errs is an sql-error and the policy exits 1."""
    data = _run({"broken_sql_m9": True}, ["SUM_t"])
    assert data["results"][0]["mapped_status"] == "sql-error"
    code, messages = _policy(data)
    assert code == 1 and "SQL errors" in messages[0]


# ------------------------------------------------------------------ exit policy on baseline


def test_policy_refused_set_checked_even_when_empty(run50: dict[str, Any]) -> None:
    """An empty refused list means no refusals expected: any refusal exits 1; a missing list is not checked."""
    assert any(r.get("mapped_refusal") for r in run50["results"])
    code, messages = evaluate_exit_policy(run50, {"classes": CLASSES, "refused": []})
    assert code == 1 and "Refused formula set changed" in messages[0]
    exact = sorted(r["id"] for r in run50["results"] if r.get("mapped_refusal"))
    assert evaluate_exit_policy(run50, {"classes": CLASSES, "refused": exact}) == (0, [])
    code, _ = evaluate_exit_policy(run50, {"classes": CLASSES, "refused": exact[:-1]})
    assert code == 1
    code, _ = evaluate_exit_policy(run50, {"classes": CLASSES, "refused": exact + ["NOT_A_FORMULA"]})
    assert code == 1


def test_policy_unknown_class_exits_one(run50: dict[str, Any]) -> None:
    """With no classes in the baseline, a classified difference is still not allowed."""
    assert any(r["mapped_status"] == "differs" for r in run50["results"])
    code, messages = evaluate_exit_policy(run50, {"classes": []})
    assert code == 1 and "un-baselined" in messages[0]
    code, messages = evaluate_exit_policy(run50, {})
    assert code == 1
    code, messages = evaluate_exit_policy(run50, {"classes": ["distinct_numeric_text_variants"]})
    assert code == 1 and "Parquet" in messages[0]


def test_committed_baseline_matches_run(run50: dict[str, Any]) -> None:
    """The committed baseline lists the classes and the refused set of the tool at the standard size."""
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    assert baseline["classes"] == CLASSES
    exact = sorted(r["id"] for r in run50["results"] if r.get("mapped_refusal"))
    assert sorted(baseline["refused"]) == exact


# ------------------------------------------------------------------ report


def test_report_refused_counts_and_texts(run100: dict[str, Any]) -> None:
    """Headline refused count equals the refusals listed; per-reason counts sum to it; DISTINCTCOUNT states the rule."""
    md = generate_markdown_report(run100)
    refusals = [r for r in run100["results"] if r.get("mapped_refusal")]
    assert f"- **Refused:** {len(refusals)} (" in md

    reason_lines = md.split("  - Refused by reason:\n", 1)[1].split("- **SQL Errors")[0].strip().split("\n")
    counts = {line.strip()[2:].rsplit(": ", 1)[0]: int(line.rsplit(": ", 1)[1]) for line in reason_lines}
    assert sum(counts.values()) == len(refusals)
    assert any("numeric IN or && filter" in reason for reason in counts)
    assert any("date IN filter" in reason for reason in counts)

    shape_line = next(line for line in md.split("\n") if "Refused shapes breakdown" in line)
    shape_counts = ast.literal_eval(shape_line.split("breakdown: ", 1)[1])
    assert sum(shape_counts.values()) == len(refusals)

    assert "distinct textual forms" in md
    assert "DISTINCTCOUNT of 1, 1.0, +1, -0 and 0 in a numeric column: one value or several?" in md


# ------------------------------------------------------------------ command line exit codes


def _cli(baseline: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(baseline, f)
        path = f.name
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["QT_QPA_PLATFORM"] = "offscreen"
    try:
        return subprocess.run(
            [sys.executable, "tools/store_engine_diff.py", "--rows", "50", "--seed", "42", "--baseline", path],
            capture_output=True,
            text=True,
            env=env,
        )
    finally:
        os.unlink(path)


def test_exit_policy_subprocess(run50: dict[str, Any]) -> None:
    """Command line: exit 0 on matching baseline, exit 1 on a baseline without the classes, exit 1 on refusal change."""
    refs_50 = sorted(r["id"] for r in run50["results"] if r.get("mapped_refusal"))

    p1 = _cli({"classes": CLASSES, "refused": refs_50})
    assert p1.returncode == 0, f"Expected exit 0, got {p1.returncode}: {p1.stderr}"

    p2 = _cli({"classes": [], "refused": refs_50})
    assert p2.returncode == 1, f"Expected exit 1, got {p2.returncode}: {p2.stderr}"
    assert "un-baselined" in p2.stderr

    p3 = _cli({"classes": CLASSES, "refused": refs_50[:-1]})
    assert p3.returncode == 1, f"Expected exit 1 on refusal change, got {p3.returncode}"
    assert "Refused formula set changed" in p3.stderr

    p4 = _cli({"classes": CLASSES, "refused": []})
    assert p4.returncode == 1, f"Expected exit 1 on empty refused list, got {p4.returncode}"
