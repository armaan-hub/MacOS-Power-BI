"""The per-evaluation key memo gives exactly the rows and the errors that propagation gives without it."""
from __future__ import annotations

import random

import pytest

from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.relationship_keys import RelationshipKeyMemo
from analytics_studio.relationships import RelationshipError, _relationship_value_key, propagate_relationship_filters


def _model(rng: random.Random, fact_count: int, bad_fact_index: int | None = None):
    dims = [{"K": f"K{i}", "G": f"G{i % 3}"} for i in range(8)]
    groups = [{"G": f"G{i}", "N": i} for i in range(3)]
    facts = [{"F": i, "K": rng.choice([f"K{rng.randrange(10)}", None, "K1"]), "V": rng.randrange(5)} for i in range(fact_count)]
    if bad_fact_index is not None:
        facts[bad_fact_index]["K"] = PowerQueryCellError("Expression.Error", "bad")
    tables = [
        {"id": "f", "name": "Fact", "headers": ["F", "K", "V"], "rows": facts, "column_types": {"F": "whole_number", "K": "text", "V": "whole_number"}},
        {"id": "d", "name": "Dim", "headers": ["K", "G"], "rows": dims, "column_types": {"K": "text", "G": "text"}},
        {"id": "g", "name": "Grp", "headers": ["G", "N"], "rows": groups, "column_types": {"G": "text", "N": "whole_number"}},
    ]

    def link(identifier, from_table, from_column, to_table, to_column, direction):
        return {"relationship_version": 1, "id": identifier, "from": from_column, "to": to_column, "from_table_id": from_table,
                "from_column": from_column, "to_table_id": to_table, "to_column": to_column, "cardinality": "many_to_one",
                "is_active": True, "cross_filter_direction": direction}

    return tables, lambda direction: [link("r1", "f", "K", "d", "K", direction), link("r2", "d", "G", "g", "G", direction)]


def _with_filters(tables, rng):
    """Copies of the tables where some are narrowed to a random subset of their own rows (as a filter context leaves them)."""
    narrowed = []
    roots = set()
    for table in tables:
        copy = dict(table)
        if rng.random() < 0.6:
            copy["filter_rows"] = [row for row in table["rows"] if rng.random() < 0.5]
            roots.add(table["id"])
        narrowed.append(copy)
    return narrowed, roots


def _ids(result):
    return {table_id: [id(row) for row in rows] for table_id, rows in result.items()}


@pytest.mark.parametrize("direction", ["single", "both"])
def test_memo_gives_the_same_rows_as_no_memo(direction):
    for seed in range(60):
        rng = random.Random(seed)
        tables, make_links = _model(rng, 40)
        memo = RelationshipKeyMemo(_relationship_value_key)  # one memo across the calls, as one evaluation shares it
        for _ in range(8):
            narrowed, roots = _with_filters(tables, rng)
            if not roots:
                continue
            plain = propagate_relationship_filters(narrowed, make_links(direction), set(roots))
            memoised = propagate_relationship_filters(narrowed, make_links(direction), set(roots), key_memo=memo)
            assert _ids(plain) == _ids(memoised), (seed, direction)


def test_bad_key_cell_in_a_removed_row_raises_or_not_exactly_as_without_the_memo():
    rng = random.Random(7)
    tables, make_links = _model(rng, 30, bad_fact_index=5)
    for keep_bad_row in (True, False):
        narrowed = [dict(table) for table in tables]
        fact = next(table for table in narrowed if table["id"] == "f")
        fact["filter_rows"] = [row for index, row in enumerate(fact["rows"]) if keep_bad_row or index != 5]
        dim = next(table for table in narrowed if table["id"] == "d")
        dim["filter_rows"] = dim["rows"][:3]

        def run(memo):
            try:
                return _ids(propagate_relationship_filters(narrowed, make_links("both"), {"d"}, key_memo=memo))
            except RelationshipError as error:
                return str(error)

        assert run(None) == run(RelationshipKeyMemo(_relationship_value_key)), keep_bad_row
