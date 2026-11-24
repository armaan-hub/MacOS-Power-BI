"""LargeTableError lives here so importing it does not load the store stack.

``analytics_studio.store`` pulls in duckdb and pyarrow. The controller only needs
the exception class to catch it, so the class sits in this small module and
``analytics_studio.store.candidate`` re-exports it.
"""

from __future__ import annotations


class LargeTableError(ValueError):
    """Raised when code tries to read the rows of a store-backed table."""
