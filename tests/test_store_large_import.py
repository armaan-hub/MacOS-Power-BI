"""Tests for large file import job function (analytics_studio.store.large_import)."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
import threading
import pytest

from analytics_studio.file_import import (
    FileImportError,
    ImportCancelledError,
    normalize_options,
)
from analytics_studio.project import _validate_store_source
from analytics_studio.store.large_import import (
    LargeImportResult,
    file_fingerprint,
    run_large_import,
)
from analytics_studio.store.session import ProjectStore
from analytics_studio.transformations import infer_column_types


def test_fingerprint(tmp_path: Path) -> None:
    # 1. 10 KiB file (<= 2 MiB)
    small_file = tmp_path / "small.dat"
    small_bytes = b"abcdef123456" * 850  # ~10.2 KiB
    small_file.write_bytes(small_bytes)

    fp_small = file_fingerprint(small_file)
    assert set(fp_small.keys()) == {"size", "mtime_ns", "head_tail_sha256"}
    assert fp_small["size"] == len(small_bytes)
    assert isinstance(fp_small["mtime_ns"], int)
    assert len(fp_small["head_tail_sha256"]) == 64
    assert fp_small["head_tail_sha256"] == fp_small["head_tail_sha256"].lower()
    int(fp_small["head_tail_sha256"], 16)  # hex check

    # same file produces same fingerprint
    fp_small_2 = file_fingerprint(small_file)
    assert fp_small == fp_small_2

    # 2. File > 3 MiB so head and tail differ
    large_file = tmp_path / "large.dat"
    size = 3 * 1024 * 1024 + 100
    chunk = b"X" * (1024 * 1024)
    with open(large_file, "wb") as f:
        f.write(chunk)
        f.write(chunk)
        f.write(chunk)
        f.write(b"Z" * 100)

    fp_large1 = file_fingerprint(large_file)
    assert fp_large1["size"] == size
    assert len(fp_large1["head_tail_sha256"]) == 64

    # Change the file's last byte
    with open(large_file, "r+b") as f:
        f.seek(size - 1)
        f.write(b"Y")

    fp_large2 = file_fingerprint(large_file)
    assert fp_large2["head_tail_sha256"] != fp_large1["head_tail_sha256"]

    # Passes project.py validator
    source_dict = {
        "id": "src_test_1",
        "kind": "csv",
        "path": str(small_file),
        "store": {
            "table": "src_test_1_g1",
            "row_count": 10,
            "headers": ["col1"],
            "physical_types": ["text"],
            "source_id": "src_test_1",
            "data_file": "appdata.npa.data",
            "fingerprint": fp_small,
            "generation": 1,
            "duckdb_version": "1.0.0",
        },
    }
    _validate_store_source(source_dict)


def test_csv_import_differential(tmp_path: Path) -> None:
    csv_file = tmp_path / "test_2000.csv"
    headers = ["id", "val_float", "event_date", "description", "blank_col"]

    rows_data: list[list[str]] = []
    for i in range(1, 2001):
        if i % 10 == 0:
            rows_data.append([str(i), "", "", "", ""])
        else:
            rows_data.append([
                str(i),
                f"{i * 1.25:.2f}",
                f"2026-08-{((i % 28) + 1):02d}",
                f"Description for item {i}",
                "",
            ])

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows_data)

    options = normalize_options("csv", {})

    # Old parser parse for differential check
    from analytics_studio.file_import import _parse_csv
    cand_old = _parse_csv(csv_file, options)
    old_types = infer_column_types(cand_old.headers, cand_old.rows)

    ps = ProjectStore.open_unsaved(str(tmp_path / "appdata"))
    try:
        with ps.job():
            store = ps.store
            cancel_ev = threading.Event()
            progress_calls: list[str] = []

            result = run_large_import(
                store,
                csv_file,
                "csv",
                options,
                cancel_event=cancel_ev,
                progress=progress_calls.append,
                max_rows=1_000_000,
            )

            assert isinstance(result, LargeImportResult)
            assert result.kind == "csv"
            assert result.row_count == 2000
            assert result.headers == headers
            assert result.model_types == old_types
            assert result.physical_types == ["text"] * len(headers)
            assert result.source_arrow_types == []
            assert result.fingerprint == file_fingerprint(csv_file)
            assert len(result.stats.columns) == len(headers)
            assert store.has_table(result.table)
    finally:
        ps.close()


def test_parquet_import(tmp_path: Path) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    parquet_file = tmp_path / "test.parquet"
    data = {
        "col_int": pa.array([1, 2, 3], type=pa.int64()),
        "col_float": pa.array([1.5, 2.5, 3.5], type=pa.float64()),
        "col_bool": pa.array([True, False, True], type=pa.bool_()),
        "col_date": pa.array([date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)], type=pa.date32()),
        "col_ts": pa.array([datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 2, 12, 0), datetime(2026, 1, 3, 12, 0)], type=pa.timestamp("us")),
        "col_str": pa.array(["a", "b", "c"], type=pa.string()),
    }
    table = pa.Table.from_pydict(data)
    pq.write_table(table, parquet_file)

    options: dict[str, str] = {}
    ps = ProjectStore.open_unsaved(str(tmp_path / "appdata_pq"))
    try:
        with ps.job():
            store = ps.store
            cancel_ev = threading.Event()
            result = run_large_import(
                store,
                parquet_file,
                "parquet",
                options,
                cancel_event=cancel_ev,
                progress=None,
                max_rows=1_000_000,
            )

            assert isinstance(result, LargeImportResult)
            assert result.kind == "parquet"
            assert result.row_count == 3
            assert result.headers == list(data.keys())
            expected_model_types = {
                "col_int": "whole_number",
                "col_float": "decimal_number",
                "col_bool": "true_false",
                "col_date": "date",
                "col_ts": "datetime",
                "col_str": "text",
            }
            assert result.model_types == expected_model_types
            assert store.has_table(result.table)
    finally:
        ps.close()


def test_failure_leaves_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_file = tmp_path / "test_2000_fail.csv"
    headers = ["a", "b"]
    rows = [[str(i), str(i * 2)] for i in range(2000)]
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    options = normalize_options("csv", {})
    ps = ProjectStore.open_unsaved(str(tmp_path / "appdata_fail"))
    try:
        with ps.job():
            store = ps.store

            # 1. max_rows=10 on 2000 rows raises error and leaves no tables
            with pytest.raises(FileImportError):
                run_large_import(
                    store,
                    csv_file,
                    "csv",
                    options,
                    cancel_event=threading.Event(),
                    progress=None,
                    max_rows=10,
                )
            assert store.table_names() == []

            # 2. File changed during import (monkeypatch file_fingerprint on 2nd call)
            original_fp = file_fingerprint
            call_count = 0

            def patched_fp(path: str | Path) -> dict[str, object]:
                nonlocal call_count
                call_count += 1
                res = original_fp(path)
                if call_count >= 2:
                    res = dict(res)
                    res["size"] = int(res["size"]) + 100
                return res

            monkeypatch.setattr(
                "analytics_studio.store.large_import.file_fingerprint",
                patched_fp,
            )

            with pytest.raises(FileImportError, match="The file changed while it was being imported. Import it again."):
                run_large_import(
                    store,
                    csv_file,
                    "csv",
                    options,
                    cancel_event=threading.Event(),
                    progress=None,
                    max_rows=1_000_000,
                )
            assert store.table_names() == []

            monkeypatch.undo()

            # 3. Cancel during import raises ImportCancelledError and leaves no tables
            # 3a. Cancel checked between steps (specifically after compute_table_stats before returning)
            cancel_between = threading.Event()
            import analytics_studio.store.large_import as li_mod

            def fake_stats(s, t, ct, **kw):
                cancel_between.set()
                from analytics_studio.store.stats import TableStats
                return TableStats(table=t, rows=1, columns=(), approx_bytes=0, warnings=())

            monkeypatch.setattr(li_mod, "compute_table_stats", fake_stats)

            with pytest.raises(ImportCancelledError, match="Import canceled."):
                run_large_import(
                    store,
                    csv_file,
                    "csv",
                    options,
                    cancel_event=cancel_between,
                    progress=None,
                    max_rows=1_000_000,
                )
            assert store.table_names() == []
            monkeypatch.undo()

            # 3b. Cancel triggered during progress
            cancel_ev = threading.Event()

            def cancelling_progress(msg: str) -> None:
                cancel_ev.set()

            with pytest.raises(ImportCancelledError):
                run_large_import(
                    store,
                    csv_file,
                    "csv",
                    options,
                    cancel_event=cancel_ev,
                    progress=cancelling_progress,
                    max_rows=1_000_000,
                )
            assert store.table_names() == []

            # 4. Store stays usable (a second import of the same file then succeeds)
            res_ok = run_large_import(
                store,
                csv_file,
                "csv",
                options,
                cancel_event=threading.Event(),
                progress=None,
                max_rows=1_000_000,
            )
            assert res_ok.row_count == 2000
            assert store.has_table(res_ok.table)
    finally:
        ps.close()
