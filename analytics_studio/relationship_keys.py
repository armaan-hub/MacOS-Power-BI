"""Per-evaluation memo of relationship key work, so one evaluation does not redo it on every context transition.

A measure evaluation calls propagate_relationship_filters once per context transition. Each call rebuilt the key of every
row of every key column it touched, and re-checked that the one-side keys are unique, although the loaded rows do not change
while one evaluation runs. This memo keeps the key of each row (by the identity of the row, holding the row so the identity
cannot be reused), the all-keys set of a column, and the result of a successful uniqueness check, for the life of the memo.

A memo must live no longer than one evaluation: it assumes the row dictionaries and the row lists it has seen are not
changed in place. Errors are never memoised: a bad cell raises again on every read, as it did without the memo."""

from __future__ import annotations

from itertools import chain
from typing import Any, Callable

KeyOf = Callable[[dict[str, Any]], Any]


class RelationshipKeyMemo:
    """Row keys, key sets and uniqueness results of one evaluation, computed with the caller's key function."""

    def __init__(self, key_function: Callable[[Any, str], Any]) -> None:
        self._key_function = key_function
        self._row_keys: dict[tuple[str, str], dict[int, tuple[dict[str, Any], Any]]] = {}
        self._key_sets: dict[tuple[int, int, str, str], tuple[list[dict[str, Any]], set[Any]]] = {}
        self._unique: dict[tuple[int, int, str, str], list[dict[str, Any]]] = {}
        self._positions: dict[tuple[int, int, str, str], tuple[list[dict[str, Any]], dict[Any, list[int]]]] = {}
        self._by_row_id: dict[tuple[int, int, str, str], tuple[list[dict[str, Any]], dict[int, Any] | None]] = {}

    def row_key_reader(self, column: str, column_type: str) -> KeyOf:
        """A function returning the key of a row's value in this column; a row's key is computed once per memo."""
        known = self._row_keys.setdefault((column, column_type), {})
        key_function = self._key_function

        def read(row: dict[str, Any]) -> Any:
            entry = known.get(id(row))
            if entry is not None and entry[0] is row:
                return entry[1]
            key = key_function(row.get(column), column_type)
            known[id(row)] = (row, key)
            return key

        return read

    def key_set(self, rows: list[dict[str, Any]], column: str, column_type: str) -> set[Any]:
        """The set of keys of a column over all of these rows (the set is shared: callers must not change it)."""
        slot = (id(rows), len(rows), column, column_type)
        cached = self._key_sets.get(slot)
        if cached is None:
            read = self.row_key_reader(column, column_type)
            cached = self._key_sets[slot] = (rows, {read(row) for row in rows})  # the list is held so its identity stays unique
        return cached[1]

    def unique_checked(self, rows: list[dict[str, Any]], column: str, column_type: str) -> bool:
        """Has this column of these rows already passed the uniqueness check?"""
        return self._unique.get((id(rows), len(rows), column, column_type)) is rows

    def mark_unique(self, rows: list[dict[str, Any]], column: str, column_type: str) -> None:
        self._unique[(id(rows), len(rows), column, column_type)] = rows

    def key_positions(self, rows: list[dict[str, Any]], column: str, column_type: str) -> dict[Any, list[int]]:
        """For each key of a column over all of these rows, the positions of the rows that have it, in row order (shared: do not change it)."""
        slot = (id(rows), len(rows), column, column_type)
        cached = self._positions.get(slot)
        if cached is None:
            read = self.row_key_reader(column, column_type)
            positions: dict[Any, list[int]] = {}
            for position, row in enumerate(rows):
                positions.setdefault(read(row), []).append(position)
            cached = self._positions[slot] = (rows, positions)
        return cached[1]

    def keys_by_row_id(self, base_rows: list[dict[str, Any]], column: str, column_type: str) -> dict[int, Any] | None:
        """The key of each row of a table by the identity of the row (the memo holds the rows), or None when a cell of the column is a bad key."""
        slot = (id(base_rows), len(base_rows), column, column_type)
        cached = self._by_row_id.get(slot)
        if cached is None:
            read = self.row_key_reader(column, column_type)
            try:
                mapping: dict[int, Any] | None = {id(row): read(row) for row in base_rows}
            except ValueError:
                mapping = None  # only a row-by-row test over the rows in play raises exactly when its own rows are bad
            cached = self._by_row_id[slot] = (base_rows, mapping)
        return cached[1]

    def keys_of_rows(self, current_rows: list[dict[str, Any]], base_rows: list[dict[str, Any]], column: str, column_type: str) -> set[Any]:
        """The set of keys of a column over current_rows, which are rows of base_rows (a row that is not one is read itself)."""
        mapping = self.keys_by_row_id(base_rows, column, column_type)
        if mapping is not None:
            try:
                return set(map(mapping.__getitem__, map(id, current_rows)))
            except KeyError:
                pass
        read = self.row_key_reader(column, column_type)
        return {read(row) for row in current_rows}

    def rows_with_keys(
        self, current_rows: list[dict[str, Any]], base_rows: list[dict[str, Any]], column: str, column_type: str,
        members: set[Any], unless_in: set[Any] | None, whole: bool,
    ) -> list[dict[str, Any]] | None:
        """The rows of current_rows whose key in column is in members, or (when unless_in is given) is not in unless_in, in the order of
        current_rows; None when the rows cannot be picked this way (the caller then tests each row).

        current_rows are rows of base_rows; whole says they are all of them, then the rows are picked by key and the cost follows the rows kept."""
        if whole:
            try:
                by_key = self.key_positions(base_rows, column, column_type)
            except ValueError:
                return None
            wanted = [by_key[key] for key in by_key if key in members or (unless_in is not None and key not in unless_in)]
            if sum(len(positions) for positions in wanted) == len(base_rows):
                return list(base_rows)  # every row passes
            return [base_rows[position] for position in sorted(chain.from_iterable(wanted))]
        mapping = self.keys_by_row_id(base_rows, column, column_type)
        if mapping is None:
            return None
        try:
            if unless_in is None:
                return [row for row in current_rows if mapping[id(row)] in members]
            return [row for row in current_rows if (key := mapping[id(row)]) in members or key not in unless_in]
        except KeyError:
            return None  # a row that is not one of the table's rows: its key must be read
