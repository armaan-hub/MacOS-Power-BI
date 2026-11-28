"""Slow items moved out of test_pq_store_diff_tool.py (the nine-mutant exit-code test, 18 cases) so each file runs in under 25 s.

Same test, same parametrize cases, same helpers (`_baseline` is copied unchanged). Independent of order and worker:
the cache only holds one shared engine pass per (rows, seed) inside one process.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import pq_store_diff
from tools.pq_store_diff import evaluate_exit_policy

BASELINE_FILE = Path(pq_store_diff.__file__).parent / "pq_store_diff_baseline.json"


def _baseline() -> dict[str, Any]:
    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


NINE_MUTANTS = [
    "mutant_sort_ignore_non_ascii", "mutant_sort_numeric_as_text", "mutant_sort_nulls_first",
    "mutant_sort_no_rn_tiebreak", "mutant_sort_reverse_ties", "mutant_filter_op_off_by_one",
    "mutant_filter_trim_trailing_spaces", "mutant_duplicate_casefold", "mutant_fill_across_whitespace",
]


_NINE_CACHE: dict[tuple[int, int], list[dict[str, Any]]] = {}


def _nine_runs(rows: int, seed: int) -> list[dict[str, Any]]:
    """One shared engine pass per (rows, seed); only the SQL side runs once per mutant."""
    if (rows, seed) not in _NINE_CACHE:
        _NINE_CACHE[(rows, seed)] = pq_store_diff.run_pq_step_diff_many(
            rows, seed, [{m: True} for m in NINE_MUTANTS]
        )
    return _NINE_CACHE[(rows, seed)]


@pytest.mark.parametrize("mutant", NINE_MUTANTS)
@pytest.mark.parametrize("rows,seed", [(50, 42), (400, 1)])
def test_nine_mutants_exit_1_on_generated_data(mutant: str, rows: int, seed: int) -> None:
    """Each mutant makes the whole tool differ and exit 1 on generated data (clean run exits 0)."""
    data = _nine_runs(rows, seed)[NINE_MUTANTS.index(mutant)]
    code, msgs = evaluate_exit_policy(data, _baseline())
    assert code == 1, (mutant, rows, seed)
    assert any("unclassified differences" in m for m in msgs)
