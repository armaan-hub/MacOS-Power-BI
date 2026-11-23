"""Per-evaluation memo of relationship key work, so one evaluation does not redo it on every context transition.

A measure evaluation calls propagate_relationship_filters once per context transition. Each call rebuilt the key of every
row of every key column it touched, and re-checked that the one-side keys are unique, although the loaded rows do not change
while one evaluation runs. This memo keeps, for the life of the memo, the all-keys set of a column, the key of each row (by the identity of the row, holding the
rows so the identity cannot be reused), the rows holding each key, and the result of a successful uniqueness check.

The heavy indexes (a key for every row of a table) are built lazily: a table column is indexed only when the same kind of index is
asked for again in the same evaluation (after LAZY_AFTER earlier asks). A one-shot evaluation, with one context transition, takes the
direct path and holds no index, so it costs what it cost without the memo.

A memo must live no longer than one evaluation: it assumes the row dictionaries and the row lists it has seen are not
changed in place. Errors are never memoised: a bad cell raises again on every read, as it did without the memo."""

from __future__ import annotations

from itertools import chain
from typing import Any, Callable

KeyOf = Callable[[dict[str, Any]], Any]
MAX_INDEXED_ROWS = 300_000  # a table with more rows is never indexed per row: the index would cost more memory than the table's own rows
LAZY_AFTER = 2  # an index is built on the ask after this many earlier asks of the same kind for the same table column


class RelationshipKeyMemo:
    """Key sets, row-to-key indexes and uniqueness results of one evaluation, computed with the caller's key function."""

    def __init__(self, key_function: Callable[[Any, str], Any]) -> None:
        self._key_function = key_function
        self._key_sets: dict[tuple[int, int, str, str], tuple[list[dict[str, Any]], set[Any]]] = {}
        self._unique: dict[tuple[int, int, str, str], list[dict[str, Any]]] = {}
        self._positions: dict[tuple[int, int, str, str], tuple[list[dict[str, Any]], dict[Any, list[int]]]] = {}
        self._by_row_id: dict[tuple[int, int, str, str], tuple[list[dict[str, Any]], dict[int, Any] | None]] = {}
        self._asks: dict[tuple[Any, ...], int] = {}

    def _warm(self, kind: str, *slot: Any) -> bool:
        """Count one ask of this kind for this slot; True once it has been asked more than LAZY_AFTER times (then build the index)."""
        ask = (kind, *slot)
        count = self._asks.get(ask, 0) + 1
        self._asks[ask] = count
        return count > LAZY_AFTER

    def row_key_reader(self, column: str, column_type: str) -> KeyOf:
        """A function returning the key of a row's value in this column (computed directly: the indexes below hold the keys worth keeping)."""
        key_function = self._key_function
        return lambda row: key_function(row.get(column), column_type)

    def key_set(self, rows: list[dict[str, Any]], column: str, column_type: str) -> set[Any]:
        """The set of keys of a column over all of these rows (the set may be shared: callers must not change it)."""
        slot = (id(rows), len(rows), column, column_type)
        cached = self._key_sets.get(slot)
        if cached is None:
            key_function = self._key_function
            keys = {key_function(row.get(column), column_type) for row in rows}
            if not self._warm("key_set", *slot):
                return keys
            cached = self._key_sets[slot] = (rows, keys)  # the list is held so its identity stays unique
        return cached[1]

    def unique_checked(self, rows: list[dict[str, Any]], column: str, column_type: str) -> bool:
        """Has this column of these rows already passed the uniqueness check?"""
        return self._unique.get((id(rows), len(rows), column, column_type)) is rows

    def mark_unique(self, rows: list[dict[str, Any]], column: str, column_type: str) -> None:
        self._unique[(id(rows), len(rows), column, column_type)] = rows

    def key_positions(self, rows: list[dict[str, Any]], column: str, column_type: str) -> dict[Any, list[int]] | None:
        """For each key of a column over all of these rows, the positions of the rows that have it, in row order (shared: do not change it).

        None while the column is not asked for often enough to be worth indexing, or when a cell of it is a bad key."""
        slot = (id(rows), len(rows), column, column_type)
        cached = self._positions.get(slot)
        if cached is None:
            if len(rows) > MAX_INDEXED_ROWS or not self._warm("positions", *slot):
                return None
            key_function = self._key_function
            positions: dict[Any, list[int]] | None = {}
            try:
                for position, row in enumerate(rows):
                    positions.setdefault(key_function(row.get(column), column_type), []).append(position)
            except ValueError:
                positions = None  # only a row-by-row test over the rows in play raises exactly when its own rows are bad
            cached = self._positions[slot] = (rows, positions)
        return cached[1]

    def keys_by_row_id(self, base_rows: list[dict[str, Any]], column: str, column_type: str) -> dict[int, Any] | None:
        """The key of each row of a table by the identity of the row (the memo holds the rows).

        None while the column is not asked for often enough to be worth indexing, or when a cell of it is a bad key."""
        slot = (id(base_rows), len(base_rows), column, column_type)
        cached = self._by_row_id.get(slot)
        if cached is None:
            if len(base_rows) > MAX_INDEXED_ROWS or not self._warm("by_row_id", *slot):
                return None
            key_function = self._key_function
            try:
                mapping: dict[int, Any] | None = {id(row): key_function(row.get(column), column_type) for row in base_rows}
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
            by_key = self.key_positions(base_rows, column, column_type)
            if by_key is None:
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
