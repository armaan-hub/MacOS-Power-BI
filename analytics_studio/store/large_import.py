"""Large-file import job function and helpers (Stage B4b task 11a).

Qt-free, controller-free module for importing large CSV and Parquet files into DuckStore.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import threading
from typing import Any, Callable, Mapping, Optional

from analytics_studio.file_import import (
    FileImportError,
    ImportCancelledError,
    normalize_options,
)
from analytics_studio.store.base import Store, StoreError
from analytics_studio.store.csv_import import import_csv_to_store
from analytics_studio.store.parquet_import import import_parquet_to_store
from analytics_studio.store.session import ProjectStore
from analytics_studio.store.stats import TableStats, compute_table_stats
from analytics_studio.store.table_model import _STORE_TO_APP_TYPE
from analytics_studio.store.type_detect import detect_column_types

_ONE_MIB = 1024 * 1024
_TWO_MIB = 2 * _ONE_MIB


def file_fingerprint(path: str | Path) -> dict[str, Any]:
    """Compute file fingerprint dictionary: size, mtime_ns, head_tail_sha256."""
    p = Path(path)
    try:
        st = os.stat(p)
    except OSError as exc:
        raise FileImportError(f"Could not stat {p.name}: {exc.strerror or exc}.") from exc

    size = st.st_size
    mtime_ns = st.st_mtime_ns

    hasher = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            if size <= _TWO_MIB:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    hasher.update(chunk)
            else:
                # First 1 MiB
                head = f.read(_ONE_MIB)
                hasher.update(head)
                # Last 1 MiB
                f.seek(size - _ONE_MIB)
                tail = f.read(_ONE_MIB)
                hasher.update(tail)
    except OSError as exc:
        raise FileImportError(f"Could not read {p.name}: {exc.strerror or exc}.") from exc

    return {
        "size": size,
        "mtime_ns": mtime_ns,
        "head_tail_sha256": hasher.hexdigest().lower(),
    }


@dataclass
class LargeImportResult:
    kind: str  # "csv" | "parquet"
    table: str
    headers: list[str]
    physical_types: list[str]
    model_types: dict[str, str]  # column name to app type
    row_count: int
    source_id: str
    notices: list[str]
    source_arrow_types: list[str]  # empty for CSV
    fingerprint: dict[str, Any]
    stats: TableStats
    options: dict[str, Any]


def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ImportCancelledError("Import canceled.")


def run_large_import(
    store: Store,
    path: str | Path,
    kind: str,
    options: Mapping[str, Any] | None = None,
    *,
    source_id: str,
    cancel_event: Optional[threading.Event] = None,
    progress: Optional[Callable[[str], None]] = None,
    max_rows: int = 1_000_000,
) -> LargeImportResult:
    """Execute streaming import of a large CSV or Parquet file into the DuckStore."""
    if kind not in {"csv", "parquet"}:
        raise FileImportError(f"Unsupported file kind for large import: {kind}")

    source_path = Path(path)
    opts = normalize_options(kind, dict(options) if options is not None else {})

    # a. Initial fingerprint before importing
    initial_fp = file_fingerprint(source_path)

    _check_cancel(cancel_event)

    # b. Target table name derived from caller-provided source_id
    target_table = ProjectStore.table_name(source_id, 1)
    if store.has_table(target_table):
        raise StoreError(f"The large-data table for this source already exists: {target_table}.")

    existed = False
    try:
        if kind == "csv":
            import_summary = import_csv_to_store(
                store,
                target_table,
                source_path,
                opts,
                cancel_event=cancel_event,
                progress=progress,
                max_rows=max_rows,
            )

            _check_cancel(cancel_event)

            # Detect model types for CSV
            model_types = detect_column_types(
                store,
                target_table,
                cancel_event=cancel_event,
                progress=progress,
            )
            source_arrow_types: list[str] = []

        elif kind == "parquet":
            parquet_summary = import_parquet_to_store(
                store,
                target_table,
                source_path,
                opts,
                cancel_event=cancel_event,
                progress=progress,
                max_rows=max_rows,
            )
            import_summary = parquet_summary

            _check_cancel(cancel_event)

            source_arrow_types = parquet_summary.source_arrow_types
            physical_map = dict(store.columns(target_table))
            model_types = {}
            for header, arrow_type in zip(parquet_summary.headers, source_arrow_types):
                if arrow_type.startswith("date32") or arrow_type.startswith("date64"):
                    model_types[header] = "date"
                else:
                    phys = physical_map.get(header, "text")
                    model_types[header] = _STORE_TO_APP_TYPE.get(phys, "text")

        _check_cancel(cancel_event)

        # a. Re-take fingerprint after import
        post_fp = file_fingerprint(source_path)
        if (
            post_fp["size"] != initial_fp["size"]
            or post_fp["mtime_ns"] != initial_fp["mtime_ns"]
            or post_fp["head_tail_sha256"] != initial_fp["head_tail_sha256"]
        ):
            raise FileImportError("The file changed while it was being imported. Import it again.")

        _check_cancel(cancel_event)

        # e. physical_types
        physical_types = [t for _, t in store.columns(target_table)]

        # f. compute_table_stats
        model_types_in_order = [model_types.get(h, "text") for h in import_summary.headers]
        stats = compute_table_stats(
            store,
            target_table,
            model_types_in_order,
            cancel_event=cancel_event,
            progress=progress,
        )

        _check_cancel(cancel_event)

        # g. return result
        return LargeImportResult(
            kind=kind,
            table=target_table,
            headers=list(import_summary.headers),
            physical_types=physical_types,
            model_types=model_types,
            row_count=import_summary.row_count,
            source_id=source_id,
            notices=list(import_summary.notices),
            source_arrow_types=source_arrow_types,
            fingerprint=post_fp,
            stats=stats,
            options=opts,
        )

    except BaseException as exc:
        if not existed:
            try:
                has_tbl = store.has_table(target_table)
            except Exception as check_exc:
                has_tbl = False
                exc.add_note(f"The partly imported table could not be removed: {check_exc}")
            if has_tbl:
                try:
                    store.drop_table(target_table)
                except Exception as drop_exc:
                    exc.add_note(f"The partly imported table could not be removed: {drop_exc}")
        raise
