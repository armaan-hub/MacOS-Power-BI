"""Streaming Parquet importer into DuckStore.

This module streams Parquet batches directly into DuckStore in one transaction.
Python performs no per-cell work on the data rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any, Callable, Mapping, Optional

import pyarrow.parquet as pq

from analytics_studio.file_import import (
    FileImportError,
    ImportCancelledError,
    ImportCandidate,
    MAX_CELLS,
    MAX_SOURCE_BYTES,
)
from analytics_studio.store.base import Store, StoreError
from analytics_studio.store.csv_import import _validate_headers_for_store
from analytics_studio.store.parquet_source import (
    iter_parquet_batches,
    plan_parquet,
)


@dataclass
class ParquetImportSummary:
    headers: list[str]
    column_types: list[str]
    source_arrow_types: list[str]
    row_count: int
    source_id: str
    notices: list[str]


def _read_source_arrow_types(path: Path) -> list[str]:
    parquet_file = None
    try:
        parquet_file = pq.ParquetFile(
            path,
            thrift_string_size_limit=MAX_SOURCE_BYTES,
            thrift_container_size_limit=MAX_CELLS,
        )
        return [str(field.type) for field in parquet_file.schema_arrow]
    except FileImportError:
        raise
    except Exception as exc:
        raise FileImportError(
            f"Could not read {path.name} as Parquet: {exc}"
        ) from exc
    finally:
        if parquet_file is not None:
            parquet_file.close()


def import_parquet_to_store(
    store: Store,
    table: str,
    path: str | Path,
    options: Mapping[str, Any] | None = None,
    *,
    cancel_event: Optional[threading.Event] = None,
    progress: Optional[Callable[[str], None]] = None,
    max_rows: int = 1_000_000,
    batch_size: int = 50_000,
) -> ParquetImportSummary:
    """Import a Parquet file into the store, streaming rows in Arrow batches.

    Parameters
    ----------
    store:
        DuckStore instance.
    table:
        Target table name.
    path:
        Source Parquet file path.
    options:
        Optional mapping of import options.
    cancel_event:
        Optional threading.Event to signal cooperative cancellation.
    progress:
        Optional callback reporting progress messages.
    max_rows:
        Maximum allowed data rows (default 1,000,000).
    """
    if path is None or isinstance(path, bool) or not isinstance(path, (str, Path)):
        raise FileImportError("Path must be a string or Path object.")
    if max_rows is None or isinstance(max_rows, bool) or not isinstance(max_rows, int):
        raise FileImportError("max_rows must be an integer.")
    if max_rows < 1:
        raise FileImportError("max_rows must be at least 1.")

    source_path = Path(path)
    plan = plan_parquet(
        source_path,
        options,
        cancel_event=cancel_event,
    )

    if plan.row_count > max_rows:
        raise FileImportError(f"The file exceeds the {max_rows:,}-row import limit.")

    _validate_headers_for_store(plan.headers)

    source_arrow_types = _read_source_arrow_types(source_path)

    columns = list(zip(plan.headers, plan.column_types))
    batches = iter_parquet_batches(
        source_path,
        plan,
        cancel_event=cancel_event,
        progress=progress,
        batch_size=batch_size,
    )

    try:
        row_count = store.create_table_from_arrow(
            table,
            columns,
            batches,
            cancel_event=cancel_event,
            progress=None,
            max_rows=max_rows,
        )
    except (FileImportError, ImportCancelledError, StoreError):
        raise
    except Exception as exc:
        raise FileImportError(
            f"Could not read {source_path.name} as Parquet: {exc}"
        ) from exc

    opts = dict(options) if options is not None else {}
    candidate = ImportCandidate("parquet", plan.headers, [], opts, plan.notices)
    source_id = candidate.source_id or ""

    return ParquetImportSummary(
        headers=plan.headers,
        column_types=plan.column_types,
        source_arrow_types=source_arrow_types,
        row_count=row_count,
        source_id=source_id,
        notices=plan.notices,
    )
