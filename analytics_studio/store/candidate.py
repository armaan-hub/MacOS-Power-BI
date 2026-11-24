"""StoreCandidate: an import candidate whose rows live in the large-data store.

A StoreCandidate is a subclass of ImportCandidate so that the ~30 existing
isinstance checks keep working. It holds no rows. Any code that reads
``rows`` gets a LargeTableError (a ValueError), so older handlers that catch
ValueError still see a clear message instead of an empty table.

Dataclass helpers: ``dataclasses.asdict`` and ``dataclasses.replace`` read
every parent field, including ``rows``, so both raise LargeTableError. No
call sites exist in the app. ``repr``, ``==``, ``hash``, ``copy.copy`` and
``copy.deepcopy`` do not read rows.
"""

from __future__ import annotations

import contextvars
import copy as _copy
from contextlib import contextmanager
from typing import Any, Iterator

from analytics_studio.file_import import ImportCandidate
from analytics_studio.large_table_error import LargeTableError

_DEFAULT_WHAT = "This feature"

_WHAT: contextvars.ContextVar[str] = contextvars.ContextVar(
    "large_table_what", default=_DEFAULT_WHAT
)

LARGE_TABLE_REFUSAL_TEXT = (
    "{what} is not available for large-data tables yet. Tables up to 100,000 rows "
    "work everywhere; large tables support the data grid, sort, filter, column "
    "statistics and export. Other features arrive in a later release."
)


def large_table_message(what: str) -> str:
    """Return the user-facing refusal text for the named feature."""
    return LARGE_TABLE_REFUSAL_TEXT.format(what=what)


@contextmanager
def large_table_context(what: str) -> Iterator[None]:
    """Name the feature for any LargeTableError raised inside the block."""
    token = _WHAT.set(what)
    try:
        yield
    finally:
        _WHAT.reset(token)


def _large_table_error() -> LargeTableError:
    what = _WHAT.get()
    return LargeTableError(
        f"{what}: this table is stored in the large-data store; "
        "this feature is not available for it yet"
    )


class StoreCandidate(ImportCandidate):
    """An import candidate whose rows are stored in the DuckDB store.

    Plain class on purpose: it does not call ImportCandidate.__init__ and is
    not a dataclass, so the parent's generated __repr__, __eq__ and
    __post_init__ never touch ``rows``.
    """

    is_store_backed = True

    def __init__(
        self,
        kind: str,
        headers: list[str],
        options: dict[str, Any],
        notices: list[str],
        *,
        store_table: str,
        row_count: int,
        physical_types: list[str] | None = None,
        model_types: dict[str, str] | None = None,
        source_id: str | None = None,
        header_row_used: int | None = None,
        session: Any = None,
    ) -> None:
        self.kind = kind
        self.headers = headers
        self.options = options
        self.notices = notices
        self.header_row_used = header_row_used
        self.store_table = store_table
        self._row_count = int(row_count)
        self.physical_types = list(physical_types) if physical_types is not None else []
        self.model_types = dict(model_types) if model_types is not None else {}
        self.session = session
        if source_id:
            self.source_id = source_id
        else:
            # Same hash as ImportCandidate.__post_init__: build a parent with no rows.
            self.source_id = ImportCandidate(
                kind, headers, [], options, notices
            ).source_id

    @property
    def rows(self) -> list[dict[str, Any]]:  # type: ignore[override]
        raise _large_table_error()

    @property
    def row_count(self) -> int:  # type: ignore[override]
        return self._row_count

    def set_source_identity(
        self,
        source_id: str,
        *,
        preserve_origins: bool = False,
    ) -> None:
        """Set only the source id. Row lineage lives in the store, so nothing else changes."""
        self.source_id = source_id

    def __repr__(self) -> str:
        return (
            f"StoreCandidate(kind={self.kind!r}, store_table={self.store_table!r}, "
            f"row_count={self._row_count!r}, headers={len(self.headers)})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StoreCandidate):
            return NotImplemented
        return (
            type(self) is type(other)
            and self.kind == other.kind
            and self.store_table == other.store_table
            and self.source_id == other.source_id
            and self._row_count == other._row_count
            and self.headers == other.headers
        )

    def __hash__(self) -> int:
        return hash((self.kind, self.store_table, self.source_id, self._row_count))

    def __copy__(self) -> StoreCandidate:
        clone = type(self).__new__(type(self))
        for key, value in self.__dict__.items():
            if key == "session":
                clone.session = value  # shared by reference
            elif isinstance(value, (list, dict)):
                clone.__dict__[key] = value.copy()
            else:
                clone.__dict__[key] = value
        return clone

    def __deepcopy__(self, memo: dict[int, Any]) -> StoreCandidate:
        # The session holds a thread lock, so it must be shared, never copied.
        if self.session is not None:
            memo[id(self.session)] = self.session
        clone = type(self).__new__(type(self))
        memo[id(self)] = clone
        for key, value in self.__dict__.items():
            clone.__dict__[key] = _copy.deepcopy(value, memo)
        return clone
