"""Stage D1d: the D1a "d1a" table follows `--rows` (Part D, item 4).

- `generate_d1a_csv` row counts: fixed up to 41 data rows, `scale_rows` rows above, never more than D1A_SCALE_MAX_ROWS,
  the first 41 rows the same as the fixed table, other shapes and "d1a_small" never scaled.
- The catalog puts the steps that transpose on the fixed "d1a_small" table (a table of more than 512 rows cannot be
  transposed within the 512-column limit).
- End-to-end runs of the tool on scaled tables: the engine file is parsed with the raised limits, and the step results
  equal the engine's.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from tools import pq_store_diff
from tools.pq_store_diff import D1A_ROWS, D1A_SCALE_MAX_ROWS, _d1a_catalog, generate_d1a_csv, run_pq_step_diff


def _read(path: Path) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def test_generate_d1a_csv_row_counts_and_stable_first_rows(tmp_path: Path) -> None:
    fixed_path = tmp_path / "fixed.csv"
    generate_d1a_csv(fixed_path, 1, "d1a")
    fixed = _read(fixed_path)
    assert len(fixed) - 1 == D1A_ROWS + 1 == 41  # the header-like row plus 40 drawn rows
    counts = {}
    for scale_rows in (None, 1, 40, 41, 42, 400, 2000):
        path = tmp_path / f"s{scale_rows}.csv"
        generate_d1a_csv(path, 1, "d1a", scale_rows=scale_rows)
        table = _read(path)
        counts[scale_rows] = len(table) - 1
        assert table[: len(fixed)] == fixed, scale_rows  # a larger table only appends fresh draws
    assert counts == {None: 41, 1: 41, 40: 41, 41: 41, 42: 42, 400: 400, 2000: 2000}
    # fresh draws, not a tiled copy: the 41 appended-after rows are not the first 41 again, and keys stay unique
    big = _read(tmp_path / "s400.csv")
    keys = [row[0] for row in big[2:]]
    assert len(set(keys)) == len(keys) == 399
    assert big[42:82] != big[2:42]


def test_generate_d1a_csv_cap_and_unscaled_shapes(tmp_path: Path) -> None:
    capped = tmp_path / "capped.csv"
    generate_d1a_csv(capped, 1, "d1a", scale_rows=D1A_SCALE_MAX_ROWS + 5_000)
    assert len(_read(capped)) - 1 == D1A_SCALE_MAX_ROWS == 90_000
    expected = {"d1a_small": 41, "d1a_empty": 0, "d1a_one_row": 1, "d1a_one_col": 5, "d1a_blank": 3}
    for shape, want in expected.items():
        path = tmp_path / f"{shape}.csv"
        generate_d1a_csv(path, 1, shape, scale_rows=2000)
        assert len(_read(path)) - 1 == want, shape
    small = tmp_path / "small.csv"
    fixed = tmp_path / "fixed.csv"
    generate_d1a_csv(small, 1, "d1a_small", scale_rows=2000)
    generate_d1a_csv(fixed, 1, "d1a")
    assert _read(small) == _read(fixed)


def test_transposing_steps_use_the_fixed_table_and_the_rest_the_scaled_one() -> None:
    from tools.pq_store_diff import _store_table_name

    catalog = _d1a_catalog()
    assert Counter(item["table"] for item in catalog) == {"d1a": 109, "d1a_empty": 4, "d1a_one_row": 4, "d1a_one_col": 2}
    used = Counter(_store_table_name(item) for item in catalog)
    assert used == {"d1a": 107, "d1a_small": 2, "d1a_empty": 4, "d1a_one_row": 4, "d1a_one_col": 2}
    small = sorted(item["id"] for item in catalog if _store_table_name(item) == "d1a_small")
    assert small == ["d1a_seq_transpose_then_promote", "d1a_transpose_table"]
    # an item written by hand with table "d1a" is mapped the same way, a transpose on another table is not
    assert _store_table_name({"id": "x", "step": {"op": "transpose_table"}, "table": "d1a"}) == "d1a_small"
    assert _store_table_name({"id": "x", "step": {"op": "sequence"}, "sequence": [{"op": "promote_headers"}, {"op": "transpose_table"}], "table": "d1a"}) == "d1a_small"
    assert _store_table_name({"id": "x", "step": {"op": "transpose_table"}, "table": "d1a_one_row"}) == "d1a_one_row"
    assert _store_table_name({"id": "x", "step": {"op": "promote_headers"}, "table": "d1a"}) == "d1a"
    assert _store_table_name({"id": "x", "step": {"op": "transpose_table"}}) == "main"


def test_transposing_steps_at_600_rows_are_not_refused_for_the_512_column_limit() -> None:
    """At 600 rows a transpose of the scaled table would exceed 512 columns: the fixed table keeps it a real transpose."""
    ids = ["d1a_transpose_table", "d1a_seq_transpose_then_promote", "d1a_promote_headers", "d1a_demote_headers"]
    data = run_pq_step_diff(rows=600, seed=1, item_filter=ids)
    by_id = {r["id"]: r for r in data["results"]}
    assert sorted(by_id) == sorted(ids)
    for item_id, res in by_id.items():
        assert res["status"] == "same", (item_id, res)
        assert res.get("refusal") in (None, "None"), (item_id, res.get("refusal"))


def test_scaled_d1a_table_above_the_engine_cell_limit_runs_with_raised_limits() -> None:
    """50,000 rows x 11 columns is 550,000 cells (over the 500,000-cell engine import limit): the engine parse is raised too."""
    ids = ["d1a_promote_headers", "d1a_split_column_to_rows", "d1a_cond_equals_value"]
    assert 50_000 * len(pq_store_diff.D1A_HEADERS) > 500_000
    try:
        data = run_pq_step_diff(rows=50_000, seed=1, item_filter=ids)
    except Exception as exc:  # an import limit not raised makes the tool itself crash
        raise AssertionError(f"the tool crashed on a 50,000-row D1a table: {exc!r}") from exc
    by_id = {r["id"]: r for r in data["results"]}
    assert sorted(by_id) == sorted(ids), sorted(by_id)
    for item_id, res in by_id.items():
        assert res["status"] == "same", (item_id, res)
        assert res.get("refusal") in (None, "None"), (item_id, res.get("refusal"))
