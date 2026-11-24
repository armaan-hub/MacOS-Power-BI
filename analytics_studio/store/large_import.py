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
    ImportCandidate,
    normalize_options,
)
from analytics_studio.store.base import Store
from analytics_studio.store.csv_import import import_csv_to_store
from analytics_studio.store.parquet_import import import_parquet_to_store
from analytics_studio.store.parquet_source import plan_parquet
from analytics_studio.store.session import ProjectStore
from analytics_studio.store.stats import TableStats, compute_table_stats
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


def _map_parquet_arrow_type_to_model_type(arrow_type_str: str) -> str:
    """Map Parquet Arrow type string to application model type name."""
    s = arrow_type_str.lower()
    if s.startswith("date32") or s.startswith("date64"):
        return "date"
    if s.startswith("timestamp"):
        return "datetime"
    if (
        s.startswith("int8")
        or s.startswith("int16")
        or s.startswith("int32")
        or s.startswith("int64")
        or s.startswith("uint8")
        or s.startswith("uint16")
        or s.startswith("uint32")
        or s.startswith("uint64")
    ):
        return "whole_number"
    if (
        s.startswith("float")
        or s.startswith("double")
        or s.startswith("halffloat")
        or s.startswith("decimal128")
        or s.startswith("decimal256")
    ):
        return "decimal_number"
    if s == "bool" or s == "boolean":
        return "true_false"
    return "text"


def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ImportCancelledError("Import canceled.")


def _derive_candidate_source_id(kind: str, path: Path, options: dict[str, Any]) -> str:
    """Derive candidate source_id before table creation without reading all rows."""
    if kind == "parquet":
        plan = plan_parquet(path, options)
        candidate = ImportCandidate("parquet", plan.headers, [], options, plan.notices)
        return candidate.source_id or ""
    elif kind == "csv":
        from analytics_studio.file_import import _parse_csv_head
        cand_head = _parse_csv_head(path, options, 1)
        candidate = ImportCandidate("csv", cand_head.headers, [], options, [])
        return candidate.source_id or ""
    else:
        raise FileImportError(f"Unsupported large import kind: {kind}")


def run_large_import(
    store: Store,
    path: str | Path,
    kind: str,
    options: Mapping[str, Any] | None = None,
    *,
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

    # b. Choose table name directly via candidate_source_id
    candidate_source_id = _derive_candidate_source_id(kind, source_path, opts)
    target_table = ProjectStore.table_name(candidate_source_id, 1)

    table_created = False
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
            table_created = True

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
            table_created = True
            import_summary = parquet_summary

            _check_cancel(cancel_event)

            source_arrow_types = parquet_summary.source_arrow_types
            model_types = {
                header: _map_parquet_arrow_type_to_model_type(arrow_type)
                for header, arrow_type in zip(parquet_summary.headers, source_arrow_types)
            }

        _check_cancel(cancel_event)

        # a. Re-take fingerprint after import
        post_fp = file_fingerprint(source_path)
        if post_fp["size"] != initial_fp["size"] or post_fp["mtime_ns"] != initial_fp["mtime_ns"]:
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
            source_id=import_summary.source_id,
            notices=list(import_summary.notices),
            source_arrow_types=source_arrow_types,
            fingerprint=post_fp,
            stats=stats,
            options=opts,
        )

    except Exception:
        if table_created:
            try:
                store.drop_table(target_table)
            except Exception:
                pass
        raise
