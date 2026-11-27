"""The arithmetic families of the rules tool (tools/store_engine_diff.py, Stage C4b).

The sweep compares every arithmetic row (the plan of dax_sql) with the in-memory engine by EXACT identity: the same
Python class, the same value (tolerance 0), the same sign of a zero and of a NaN, the same report text. These tests
run slices of the families at several seeds, show that the tool itself catches a wrong combiner (mutants through
monkeypatch), and pin the committed baseline. Nothing here asserts on elapsed time.
"""

from __future__ import annotations

import json
import zlib
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from analytics_studio.store import dax_arith
from tools import store_engine_diff as tool
from tools.store_engine_diff import (
    arith_family_counts, build_sweep_catalog, evaluate_sweep_policy, run_sweep, values_identical, with_filter_context,
)

BASELINE = json.loads((Path(tool.__file__).resolve().parent / "store_engine_diff_baseline.json").read_text("utf-8"))
D = Decimal
FAMILIES = (
    "arith_pairs", "arith_literal", "arith_divide", "arith_divide_alt", "arith_unary", "arith_precedence",
    "arith_reference", "arith_context", "arith_group", "arith_group_own_column", "arith_group_context",
    "arith_int_beyond_53", "arith_blank_int", "arith_refused",
)


def arith_only(row: dict[str, Any]) -> bool:
    return row["shape"].startswith("arith_")


def slice_of(index: int, parts: int) -> Any:
    return lambda row: arith_only(row) and zlib.crc32(row["id"].encode("utf-8")) % parts == index


# ---------------------------------------------------------------------------------------------------
# the catalog
# ---------------------------------------------------------------------------------------------------
def test_arithmetic_rows_are_opt_in_and_the_default_catalog_is_unchanged() -> None:
    plain = build_sweep_catalog()
    assert not any(arith_only(r) for r in plain)
    with_arith = build_sweep_catalog(arithmetic=True)
    assert [r["id"] for r in with_arith[: len(plain)]] == [r["id"] for r in plain]
    assert len(with_arith) - len(plain) == sum(arith_family_counts(with_arith).values())


def test_arithmetic_ids_are_unique_stable_and_built_from_the_content() -> None:
    first, second = build_sweep_catalog(arithmetic=True), build_sweep_catalog(arithmetic=True)
    assert [r["id"] for r in first] == [r["id"] for r in second]
    assert len({r["id"] for r in first}) == len(first)
    arith = [r for r in first if arith_only(r)]
    assert all("seed" not in r["id"] and r["id"].startswith(r["shape"] + ": ") for r in arith)
    assert set(arith_family_counts(first)) == set(FAMILIES)


def test_family_counts_are_the_committed_ones() -> None:
    counts = arith_family_counts()
    assert counts == BASELINE["arith_family_counts"]
    assert counts["arith_pairs"] == 12 * 12 * 4
    assert counts["arith_literal"] == 12 * 10 * 4 * 2
    assert counts["arith_divide"] == 12 * 12
    assert sum(counts.values()) >= 3000


def test_a_measure_reference_row_names_its_measures_in_its_id() -> None:
    rows = [r for r in build_sweep_catalog(arithmetic=True) if r["shape"] == "arith_reference"]
    assert rows and all(" | measures " in r["id"] and r["measures"] for r in rows)
    assert len({r["id"] for r in rows}) == len(rows)


def test_the_leaf_pool_has_the_twelve_leaves_of_the_brief() -> None:
    assert len(tool.ARITH_LEAVES) == 12
    for needed in ("SUM(t[sw])", "SUM(t[sd])", "AVERAGE(t[sw])", "AVERAGE(t[sd])", "MIN(t[sw])", "MAX(t[sd])", "COUNTROWS(t)",
                   "COUNT(t[sd])", "COUNTA(t[st])", "DISTINCTCOUNT(t[st])", "CALCULATE(SUM(t[sd]), t[sw] > 5)"):
        assert needed in tool.ARITH_LEAVES
    assert tool.ARITH_BLANK_LEAF in tool.ARITH_LEAVES


# ---------------------------------------------------------------------------------------------------
# the exact comparison
# ---------------------------------------------------------------------------------------------------
def test_values_identical_is_exact_with_signs() -> None:
    assert values_identical(D("1.5"), D("1.5"))
    assert not values_identical(D("1.5"), D("1.5000000000000002"))
    assert not values_identical(D(0), D("-0"))  # a zero of the other sign
    assert values_identical(D("-0"), D("-0"))
    nan, neg_nan = D("NaN"), D("-NaN")
    assert values_identical(nan, D("NaN")) and values_identical(neg_nan, D("-NaN"))
    assert not values_identical(nan, neg_nan)
    assert not values_identical(nan, D(0))
    assert values_identical(D("Infinity"), D("Infinity")) and not values_identical(D("Infinity"), D("-Infinity"))
    assert values_identical(None, None) and not values_identical(None, D(0))
    assert not values_identical(D(1), 1)  # the same value of another class
    assert not values_identical(D("0.1"), D("0.10000000000000000555111512312578270211815834045410156250"))


def test_the_old_tolerance_is_not_used_by_the_identity() -> None:
    a = D("1.000000000000001")
    assert tool.exact_values_agree(1.0, a)  # the old catalog tolerance (float engine value) still accepts it
    assert not values_identical(D(1), a)


@pytest.mark.parametrize("text,wrapped", [
    ("CALCULATE(SUM(t[a]), t[b] = 1)", True),
    ("CALCULATE(SUM(t[a]), t[b] = \")\")", True),
    ("CALCULATE(SUM(t[a]), t[b] = 1) / CALCULATE(SUM(t[a]), t[c] = 2)", False),
    ("CALCULATE(SUM(t[a]), t[b] = 1) + 1", False),
    ("CALCULATE(SUM(t[a]), t[b] = 1) * (2)", False),
    ("CALCULATE(SUM(t[a]), t[b] = \"(\") / SUM(t[a])", False),
    ("CALCULATE(SUM(t[a]), t[b)] = 1)", True),
    ("SUM(t[a])", False),
])
def test_with_filter_context_adds_the_filter_to_a_single_calculate_only(text: str, wrapped: bool) -> None:
    out = with_filter_context(text, ("t[k] = 5",))
    if wrapped:
        assert out == text[:-1] + ", t[k] = 5)"
    else:
        assert out == f"CALCULATE({text}, t[k] = 5)"


# ---------------------------------------------------------------------------------------------------
# the sweep itself: every arithmetic row, in slices (any order, any worker)
# ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("seed", [1, 7, 42])
def test_every_arithmetic_row_is_same_or_a_baselined_refusal(seed: int) -> None:
    parts = 12
    index = (seed * 5) % parts
    data = run_sweep(rows=300, seed=seed, arithmetic=True, row_filter=slice_of(index, parts))
    results = data["sweep_results"]
    assert len(results) >= 200, len(results)
    failures = [(r["id"], r["status"], r["error"]) for r in results if r["status"] in tool.SWEEP_FAILURE_STATUSES]
    assert not failures, failures
    refused = {r["id"] for r in results if r["status"].startswith("refused")}
    assert refused <= set(BASELINE["sweep_refused"]), sorted(refused - set(BASELINE["sweep_refused"]))
    assert sum(1 for r in results if r["status"] == "same") >= 100


@pytest.mark.parametrize("family", FAMILIES)
def test_each_family_has_no_difference_at_seed_one(family: str) -> None:
    data = run_sweep(rows=300, seed=1, arithmetic=True, row_filter=lambda r: r["shape"] == family)
    results = data["sweep_results"]
    assert len(results) == BASELINE["arith_family_counts"][family]
    failures = [(r["id"], r["status"], r["error"]) for r in results if r["status"] in tool.SWEEP_FAILURE_STATUSES]
    assert not failures, failures
    assert data["arith_families"][family]["differs"] == 0
    refused = {r["id"] for r in results if r["status"].startswith("refused")}
    assert refused <= set(BASELINE["sweep_refused"])
    if family in ("arith_pairs", "arith_literal", "arith_divide", "arith_unary", "arith_precedence", "arith_blank_int",
                  "arith_int_beyond_53"):
        assert all(r["status"] == "same" for r in results), [(r["id"], r["status"]) for r in results if r["status"] != "same"][:3]
    if family == "arith_refused":
        assert all(r["status"] == "refused-whitelist" and r["reason"] for r in results)


def test_the_refused_set_is_the_same_at_other_sizes_and_seeds() -> None:
    wanted = lambda r: r["shape"] in ("arith_refused", "arith_group_own_column", "arith_group_context", "arith_reference")  # noqa: E731
    one = run_sweep(rows=300, seed=1, arithmetic=True, row_filter=wanted)["sweep_results"]
    other = run_sweep(rows=700, seed=19, arithmetic=True, row_filter=wanted)["sweep_results"]
    refused = lambda rows: {r["id"] for r in rows if r["status"].startswith("refused")}  # noqa: E731
    assert refused(one) == refused(other) and refused(one)


# ---------------------------------------------------------------------------------------------------
# the tool catches a wrong combiner (mutants through monkeypatch)
# ---------------------------------------------------------------------------------------------------
def count_differs(rows_filter: Any, seed: int = 1) -> int:
    data = run_sweep(rows=300, seed=seed, arithmetic=True, row_filter=rows_filter)
    assert data["sweep_results"]
    return sum(1 for r in data["sweep_results"] if r["status"] == "differs")


def test_a_combiner_that_does_not_wrap_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    assert count_differs(lambda r: r["shape"] == "arith_int_beyond_53") == 0
    monkeypatch.setattr(dax_arith, "_int64_wrap", lambda op, left, right: dax_arith._binary_value(op, left, right))
    assert count_differs(lambda r: r["shape"] == "arith_int_beyond_53") > 0


def test_a_combiner_that_never_converts_to_double_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dax_arith, "_double_operation", lambda op, left, right: None)
    assert count_differs(lambda r: r["shape"] == "arith_pairs" and " / " in r["id"]) > 0


def test_a_combiner_that_keeps_the_sign_of_a_zero_in_the_result_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dax_arith, "bare_result", lambda value: value)
    assert count_differs(lambda r: r["shape"] == "arith_unary" or r["shape"] == "arith_precedence") > 0


def test_a_reference_typed_as_a_known_number_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    real = dax_arith.evaluate

    def typed(tree: Any, values: Any) -> Any:
        if tree[0] == "ref":
            inner = real(tree[1], values)
            return dax_arith.Num("double", inner.value)
        return real(tree, values)

    monkeypatch.setattr(dax_arith, "evaluate", typed)
    assert count_differs(lambda r: r["shape"] == "arith_reference") > 0


def test_a_wrong_blank_rule_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    real = dax_arith.combine

    def blank_plus_is_zero_plus(op: str, left: Any, right: Any) -> Any:
        if op == "+" and left.value is None and right.value is not None:
            return real(op, dax_arith.Num(left.kind, D(0)), right)  # 0 + x as a double loses the exact digits
        return real(op, left, right)

    monkeypatch.setattr(dax_arith, "combine", blank_plus_is_zero_plus)
    assert count_differs(lambda r: r["shape"] == "arith_pairs" and r["id"].startswith("arith_pairs: CALCULATE(SUM(t[sd]), t[scat]")) > 0


# ---------------------------------------------------------------------------------------------------
# the exit policy: row counts and refused ids of the arithmetic families are pinned
# ---------------------------------------------------------------------------------------------------
def test_policy_fails_when_an_arithmetic_family_loses_a_row() -> None:
    results = [{"id": f"arith_pairs: {n}", "shape": "arith_pairs", "status": "same"} for n in range(3)]
    ok = evaluate_sweep_policy(results, {"sweep_refused": [], "arith_family_counts": {"arith_pairs": 3}})
    assert ok == (0, [])
    code, messages = evaluate_sweep_policy(results[:2], {"sweep_refused": [], "arith_family_counts": {"arith_pairs": 3}})
    assert code == 1 and "family row counts" in messages[0]
    code, _ = evaluate_sweep_policy(results, {"sweep_refused": [], "arith_family_counts": {"arith_pairs": 3, "arith_x": 1}})
    assert code == 1


def test_policy_fails_on_a_new_arithmetic_refusal_and_on_a_difference() -> None:
    base = {"sweep_refused": ["arith_refused: a"], "arith_family_counts": {"arith_refused": 2}}
    good = [
        {"id": "arith_refused: a", "shape": "arith_refused", "status": "refused-whitelist"},
        {"id": "arith_refused: b", "shape": "arith_refused", "status": "same"},
    ]
    assert evaluate_sweep_policy(good, base) == (0, [])
    new_refusal = [good[0], {**good[1], "status": "refused-planner"}]
    assert evaluate_sweep_policy(new_refusal, base)[0] == 1
    differs = [good[0], {**good[1], "status": "differs", "error": "engine 1 vs plan 2"}]
    code, messages = evaluate_sweep_policy(differs, base)
    assert code == 1 and "sweep failures" in messages[0]


def test_forced_wrong_arithmetic_row_exits_1() -> None:
    row_id = "arith_pairs: SUM(t[sw]) + COUNTROWS(t)"
    clean = run_sweep(rows=300, seed=1, arithmetic=True, row_filter=lambda r: r["id"] == row_id)
    assert [r["status"] for r in clean["sweep_results"]] == ["same"]
    wrong = run_sweep(
        rows=300, seed=1, arithmetic=True, overrides={"forced_wrong_sweep_row": row_id},
        row_filter=lambda r: r["id"] == row_id,
    )
    assert [r["status"] for r in wrong["sweep_results"]] == ["differs"]
    assert evaluate_sweep_policy(wrong["sweep_results"], {"sweep_refused": []})[0] == 1


def test_the_baseline_lists_every_arithmetic_refusal_of_the_catalog_rules() -> None:
    refused = set(BASELINE["sweep_refused"])
    names = [i for i in refused if i.startswith("arith_refused: ")]
    assert len(names) == len(tool.ARITH_REFUSED_SHAPES)  # one id per shape that must stay refused
    assert any(i.startswith("arith_group_own_column: ") for i in refused)
