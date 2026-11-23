"""Store protocol and error classes."""

from typing import Any, Iterable, List, Optional, Protocol, Sequence, Tuple

COLUMN_TYPES = ("whole", "decimal", "fixed", "datetime", "text", "boolean")


class StoreError(Exception):
    """Base exception for store errors."""
    pass


class StoreLockedError(StoreError):
    """Raised when a store file is locked by another process or instance."""
    pass


class Store(Protocol):
    """Abstract interface / protocol for table row storage."""

    def create_table(self, name: str, columns: Sequence[Tuple[str, str]]) -> None:
        """Create a table with specified columns and hidden __rn."""
        ...

    def append_rows(self, name: str, rows: Iterable[Sequence[Any]]) -> int:
        """Append rows to a table in batches of 50,000, returning number of rows added."""
        ...

    def row_count(self, name: str) -> int:
        """Return total row count of the table."""
        ...

    def table_names(self) -> List[str]:
        """Return list of user table names."""
        ...

    def columns(self, name: str) -> List[Tuple[str, str]]:
        """Return list of (column_name, type_name) without __rn."""
        ...

    def has_table(self, name: str) -> bool:
        """Return True if table exists, False otherwise."""
        ...

    def drop_table(self, name: str) -> None:
        """Drop a table from the store."""
        ...

    def read_page(
        self,
        name: str,
        offset: int,
        limit: int,
        columns: Optional[Sequence[str]] = None,
    ) -> List[Tuple[Any, ...]]:
        """Read a page of rows ordered by __rn."""
        ...

    def execute(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple[Any, ...]]:
        """Run a single read query (SELECT only) and return list of tuples."""
        ...

    def close(self) -> None:
        """Close store and release locks/resources."""
        ...

    def __enter__(self) -> "Store":
        ...

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        ...
