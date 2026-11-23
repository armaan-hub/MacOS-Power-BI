"""The memo builds its per-row indexes only for a table column asked for repeatedly in one evaluation (a one-shot evaluation holds none)."""
from __future__ import annotations

from analytics_studio.relationship_keys import LAZY_AFTER, RelationshipKeyMemo
from analytics_studio.relationships import RelationshipError, _relationship_value_key
from analytics_studio.power_query_values import PowerQueryCellError

ROWS = [{"K": f"K{i % 5}"} for i in range(20)]


def _memo():
    return RelationshipKeyMemo(_relationship_value_key)


def test_indexes_start_cold_and_warm_after_repeated_asks():
    memo = _memo()
    for _ in range(LAZY_AFTER):
        assert memo.keys_by_row_id(ROWS, "K", "text") is None
        assert memo.key_positions(ROWS, "K", "text") is None
    mapping = memo.keys_by_row_id(ROWS, "K", "text")
    positions = memo.key_positions(ROWS, "K", "text")
    assert mapping is not None and len(mapping) == 20
    assert positions is not None and positions[("value", "k0")] == [0, 5, 10, 15]
    assert memo.keys_by_row_id(ROWS, "K", "text") is mapping  # built once


def test_cold_answers_equal_warm_answers():
    members = {("value", "k1"), ("value", "k3")}
    current = ROWS[2:15]
    cold, warm = _memo(), _memo()
    for _ in range(LAZY_AFTER + 1):
        warm.keys_by_row_id(ROWS, "K", "text")
        warm.key_positions(ROWS, "K", "text")
    for memo in (cold, warm):
        assert memo.keys_of_rows(current, ROWS, "K", "text") == {_relationship_value_key(row["K"], "text") for row in current}
    assert cold.rows_with_keys(current, ROWS, "K", "text", members, None, False) is None  # cold: the caller tests each row
    expected = [row for row in current if _relationship_value_key(row["K"], "text") in members]
    assert warm.rows_with_keys(current, ROWS, "K", "text", members, None, False) == expected
    assert warm.rows_with_keys(ROWS, ROWS, "K", "text", members, None, True) == [row for row in ROWS if _relationship_value_key(row["K"], "text") in members]


def test_a_bad_key_cell_leaves_the_index_unavailable_and_raises_per_row():
    rows = [{"K": "a"}, {"K": PowerQueryCellError("Expression.Error", "bad")}, {"K": "b"}]
    memo = _memo()
    for _ in range(LAZY_AFTER + 1):
        assert memo.keys_by_row_id(rows, "K", "text") is None
        assert memo.key_positions(rows, "K", "text") is None
    assert memo.keys_of_rows(rows[:1], rows, "K", "text") == {("value", "a")}  # the bad row is not in play: no error
    try:
        memo.keys_of_rows(rows, rows, "K", "text")
    except RelationshipError:
        pass
    else:
        raise AssertionError("a bad key in play must raise")
