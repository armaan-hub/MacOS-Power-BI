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
from analytics_studio.project import new_project, validate_project, _validate_store_source
from analytics_studio.store.base import StoreError
from analytics_studio.store.large_import import (
    LargeImportResult,
    file_fingerprint,
    run_large_import,
)
from analytics_studio.store.session import ProjectStore
from analytics_studio.transformations import SUPPORTED_COLUMN_TYPES, infer_column_types


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

    # Change byte at 750 KiB (within head 1 MiB window, after 512 KiB)
    with open(large_file, "r+b") as f:
        f.seek(750 * 1024)
        f.write(b"Q")

    fp_large3 = file_fingerprint(large_file)
    assert fp_large3["head_tail_sha256"] != fp_large1["head_tail_sha256"]
    assert fp_large3["head_tail_sha256"] != fp_large2["head_tail_sha256"]

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
                source_id="src_csv_diff",
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
                source_id="src_pq_test",
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
                "col_bool": "boolean",
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
                    source_id="src_fail_1",
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
                    source_id="src_fail_2",
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
                    source_id="src_fail_3a",
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
                    source_id="src_fail_3b",
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
                source_id="src_fail_4",
                cancel_event=threading.Event(),
                progress=None,
                max_rows=1_000_000,
            )
            assert res_ok.row_count == 2000
            assert store.has_table(res_ok.table)
    finally:
        ps.close()


def test_parquet_types_validation(tmp_path: Path) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    parquet_file = tmp_path / "all_types.parquet"
    data = {
        "col_bool": pa.array([True, False], type=pa.bool_()),
        "col_int": pa.array([1, 2], type=pa.int64()),
        "col_float": pa.array([1.5, 2.5], type=pa.float64()),
        "col_date32": pa.array([date(2026, 1, 1), date(2026, 1, 2)], type=pa.date32()),
        "col_date64": pa.array([date(2026, 1, 1), date(2026, 1, 2)], type=pa.date64()),
        "col_ts": pa.array([datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 2, 12, 0)], type=pa.timestamp("us")),
        "col_str": pa.array(["a", "b"], type=pa.string()),
    }
    pq.write_table(pa.Table.from_pydict(data), parquet_file)

    ps = ProjectStore.open_unsaved(str(tmp_path / "appdata_types"))
    try:
        with ps.job():
            store = ps.store
            res = run_large_import(
                store,
                parquet_file,
                "parquet",
                {},
                source_id="src_types_1",
            )
            expected = {
                "col_bool": "boolean",
                "col_int": "whole_number",
                "col_float": "decimal_number",
                "col_date32": "date",
                "col_date64": "date",
                "col_ts": "datetime",
                "col_str": "text",
            }
            assert res.model_types == expected
            for col_type in res.model_types.values():
                assert col_type in SUPPORTED_COLUMN_TYPES

            # Build project dict with a store source from the real result and call validate_project
            proj = new_project()
            sid = "src_types_1"
            data_file = Path(ps.path).name
            src = {
                "id": sid,
                "name": "T",
                "kind": "parquet",
                "path": str(parquet_file),
                "options": res.options,
                "store": {
                    "table": res.table,
                    "row_count": res.row_count,
                    "headers": res.headers,
                    "physical_types": res.physical_types,
                    "column_types": res.model_types,
                    "source_id": res.source_id,
                    "generation": 1,
                    "duckdb_version": ProjectStore.duckdb_version(),
                    "data_file": data_file,
                    "fingerprint": res.fingerprint,
                },
            }
            proj["data_sources"].append(src)
            proj["model"]["tables"].append({
                "id": sid,
                "source_id": sid,
                "name": "T",
                "column_types": dict(res.model_types),
            })
            validate_project(proj)
    finally:
        ps.close()


def test_table_collision_and_naming(tmp_path: Path) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    # Two CSV files with identical headers
    csv_a = tmp_path / "jan.csv"
    csv_b = tmp_path / "feb.csv"
    with open(csv_a, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "val"])
        w.writerow(["1", "x"])
    with open(csv_b, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "val"])
        w.writerow(["2", "y"])

    ps = ProjectStore.open_unsaved(str(tmp_path / "appdata_coll"))
    try:
        with ps.job():
            store = ps.store
            # Two different files with identical headers imported with two different source_ids both succeed
            res_a = run_large_import(store, csv_a, "csv", {}, source_id="src_jan")
            res_b = run_large_import(store, csv_b, "csv", {}, source_id="src_feb")

            assert res_a.table != res_b.table
            assert res_a.table == ProjectStore.table_name("src_jan", 1)
            assert res_b.table == ProjectStore.table_name("src_feb", 1)
            assert res_a.source_id == "src_jan"
            assert res_b.source_id == "src_feb"
            assert store.has_table(res_a.table)
            assert store.has_table(res_b.table)

            # Importing into an existing table name raises StoreError and leaves the old table intact
            row_count_before = store.row_count(res_a.table)
            with pytest.raises(StoreError, match="The large-data table for this source already exists:"):
                run_large_import(store, csv_a, "csv", {}, source_id="src_jan")
            assert store.row_count(res_a.table) == row_count_before

            # Parquet naming check
            pq_file = tmp_path / "data.parquet"
            pq.write_table(pa.Table.from_pydict({"x": [1, 2]}), pq_file)
            res_pq = run_large_import(store, pq_file, "parquet", {}, source_id="src_pq_custom")
            assert res_pq.table == ProjectStore.table_name("src_pq_custom", 1)
            assert res_pq.source_id == "src_pq_custom"
    finally:
        ps.close()


def test_wide_late_csv_import(tmp_path: Path) -> None:
    # 12 MB CSV with 550,000 rows where late row is wider
    wide_csv = tmp_path / "wide_late.csv"
    with open(wide_csv, "w", encoding="utf-8") as f:
        f.write("a,b\n")
        line = "1234567890,abcdefghij\n"
        chunk = line * 10000
        for _ in range(55):  # 550,000 rows * 23 bytes = ~12.6 MB
            f.write(chunk)
        f.write("1,2,3\n")

    ps = ProjectStore.open_unsaved(str(tmp_path / "appdata_wide"))
    try:
        with ps.job():
            store = ps.store
            res = run_large_import(store, wide_csv, "csv", {}, source_id="src_wide", max_rows=1_000_000)
            assert res.table == ProjectStore.table_name(res.source_id, 1)
            assert res.source_id == "src_wide"
            assert res.headers == ["a", "b", "Column 3"]
            assert res.row_count == 550001
            assert store.has_table(res.table)
    finally:
        ps.close()


def test_failure_cleanup_and_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_file = tmp_path / "data.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["a", "b"])
        w.writerow(["1", "2"])

    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    pq_file = tmp_path / "data.parquet"
    pq.write_table(pa.Table.from_pydict({"a": [1, 2]}), pq_file)

    ps = ProjectStore.open_unsaved(str(tmp_path / "appdata_clean"))
    try:
        with ps.job():
            store = ps.store

            # (a) monkeypatch import_csv_to_store and import_parquet_to_store with a fake that creates the table and raises StoreError
            import analytics_studio.store.large_import as li_mod

            def fake_csv_import(s, tbl, *args, **kwargs):
                batch = pa.RecordBatch.from_arrays([pa.array(["1"]), pa.array(["2"])], names=["a", "b"])
                s.create_table_from_arrow(tbl, [("a", "text"), ("b", "text")], [batch])
                raise StoreError("fake csv import fail")

            def fake_pq_import(s, tbl, *args, **kwargs):
                batch = pa.RecordBatch.from_arrays([pa.array([1])], names=["a"])
                s.create_table_from_arrow(tbl, [("a", "whole")], [batch])
                raise StoreError("fake pq import fail")

            monkeypatch.setattr(li_mod, "import_csv_to_store", fake_csv_import)
            with pytest.raises(StoreError, match="fake csv import fail"):
                run_large_import(store, csv_file, "csv", {}, source_id="src_fake_csv")
            assert store.table_names() == []
            monkeypatch.undo()

            monkeypatch.setattr(li_mod, "import_parquet_to_store", fake_pq_import)
            with pytest.raises(StoreError, match="fake pq import fail"):
                run_large_import(store, pq_file, "parquet", {}, source_id="src_fake_pq")
            assert store.table_names() == []
            monkeypatch.undo()

            # (b) KeyboardInterrupt raised from detect_column_types, compute_table_stats, post-import fingerprint, progress callback
            def raise_ki(*args, **kwargs):
                raise KeyboardInterrupt()

            monkeypatch.setattr(li_mod, "detect_column_types", raise_ki)
            with pytest.raises(KeyboardInterrupt):
                run_large_import(store, csv_file, "csv", {}, source_id="src_ki_detect")
            assert store.table_names() == []
            monkeypatch.undo()

            monkeypatch.setattr(li_mod, "compute_table_stats", raise_ki)
            with pytest.raises(KeyboardInterrupt):
                run_large_import(store, csv_file, "csv", {}, source_id="src_ki_stats")
            assert store.table_names() == []
            monkeypatch.undo()

            orig_fp = li_mod.file_fingerprint
            fp_calls = 0

            def fp_ki(p):
                nonlocal fp_calls
                fp_calls += 1
                if fp_calls >= 2:
                    raise KeyboardInterrupt()
                return orig_fp(p)

            monkeypatch.setattr(li_mod, "file_fingerprint", fp_ki)
            with pytest.raises(KeyboardInterrupt):
                run_large_import(store, csv_file, "csv", {}, source_id="src_ki_fp")
            assert store.table_names() == []
            monkeypatch.undo()

            def progress_ki(msg: str) -> None:
                raise KeyboardInterrupt()

            with pytest.raises(KeyboardInterrupt):
                run_large_import(store, csv_file, "csv", {}, source_id="src_ki_prog", progress=progress_ki)
            assert store.table_names() == []

            # (c) drop_table raising: original exception arrives with note attached and is the type raised
            orig_drop = store.drop_table

            def failing_drop(t):
                raise RuntimeError("disk error during drop")

            monkeypatch.setattr(store, "drop_table", failing_drop)
            monkeypatch.setattr(li_mod, "compute_table_stats", raise_ki)
            with pytest.raises(KeyboardInterrupt) as exc_info:
                run_large_import(store, csv_file, "csv", {}, source_id="src_note_test")
            exc = exc_info.value
            assert hasattr(exc, "__notes__") and len(exc.__notes__) > 0
            assert "The partly imported table could not be removed: disk error during drop" in exc.__notes__[0]
            monkeypatch.undo()
            # Clean up the table manually using orig_drop
            orig_drop(ProjectStore.table_name("src_note_test", 1))
            assert store.table_names() == []

            # (d) cancel at every _check_cancel: no table left
            orig_cc = li_mod._check_cancel
            for k in range(1, 6):
                check_count = 0
                cancel_event = threading.Event()

                def counting_check_cancel(ev, k_target=k):
                    nonlocal check_count
                    check_count += 1
                    if check_count == k_target:
                        cancel_event.set()
                    orig_cc(ev)

                monkeypatch.setattr(li_mod, "_check_cancel", counting_check_cancel)
                with pytest.raises(ImportCancelledError):
                    run_large_import(store, csv_file, "csv", {}, source_id=f"src_cancel_{k}", cancel_event=cancel_event)
                assert store.table_names() == []
                monkeypatch.undo()
    finally:
        ps.close()


def test_surviving_mutants_and_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_file = tmp_path / "survivor.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["col_a", "col_b"])
        w.writerow(["1", "2"])

    ps = ProjectStore.open_unsaved(str(tmp_path / "appdata_mut"))
    try:
        with ps.job():
            store = ps.store

            # 1. Unsupported kind guard raises FileImportError
            with pytest.raises(FileImportError, match="Unsupported file kind for large import: xlsx"):
                run_large_import(store, csv_file, "xlsx", {}, source_id="src_xlsx")

            # 2. Options returned in result equal normalized options
            raw_options = {"delimiter": ",", "encoding": "utf-8"}
            res = run_large_import(store, csv_file, "csv", raw_options, source_id="src_opts")
            assert res.options == normalize_options("csv", raw_options)
            assert res.notices == []
            # Notices returned for Parquet
            pq = pytest.importorskip("pyarrow.parquet")
            pa = pytest.importorskip("pyarrow")
            pq_file = tmp_path / "notice.parquet"
            pq.write_table(pa.Table.from_pydict({"num": [1], "name": ["text_val"]}), pq_file)
            res_pq = run_large_import(store, pq_file, "parquet", {}, source_id="src_notice_pq")
            assert len(res_pq.notices) > 0
            assert "nested, binary, time-zone" in res_pq.notices[0]
            # Stats header order equals headers order and labels match model types
            stats_headers = [c.name for c in res_pq.stats.columns]
            assert stats_headers == res_pq.headers
            stats_labels = [c.label for c in res_pq.stats.columns]
            expected_labels = [res_pq.model_types[h] for h in res_pq.headers]
            assert stats_labels == expected_labels
            assert stats_labels == ["whole_number", "text"]

            # 3. Whole fingerprint dict comparison (hash changed only -> FileImportError)
            orig_fp = file_fingerprint
            call_count = 0

            def patched_fp_hash(p: str | Path) -> dict[str, object]:
                nonlocal call_count
                call_count += 1
                fp = orig_fp(p)
                if call_count >= 2:
                    fp = dict(fp)
                    fp["head_tail_sha256"] = "0" * 64
                return fp

            import analytics_studio.store.large_import as li_mod
            monkeypatch.setattr(li_mod, "file_fingerprint", patched_fp_hash)
            with pytest.raises(FileImportError, match="The file changed while it was being imported. Import it again."):
                run_large_import(store, csv_file, "csv", {}, source_id="src_fp_hash")
            assert set(store.table_names()) == {res.table, res_pq.table}
            monkeypatch.undo()

            # 3b. Whole fingerprint dict comparison (mtime changed only -> FileImportError)
            call_count_mtime = 0

            def patched_fp_mtime(p: str | Path) -> dict[str, object]:
                nonlocal call_count_mtime
                call_count_mtime += 1
                fp = orig_fp(p)
                if call_count_mtime >= 2:
                    fp = dict(fp)
                    fp["mtime_ns"] = int(fp["mtime_ns"]) + 5000
                return fp

            monkeypatch.setattr(li_mod, "file_fingerprint", patched_fp_mtime)
            with pytest.raises(FileImportError, match="The file changed while it was being imported. Import it again."):
                run_large_import(store, csv_file, "csv", {}, source_id="src_fp_mtime")
            monkeypatch.undo()

            # 4. Fingerprint returned is the post-import one (has 3 keys and matches file_fingerprint(path))
            cur_fp = file_fingerprint(csv_file)
            assert set(res.fingerprint.keys()) == {"size", "mtime_ns", "head_tail_sha256"}
            assert res.fingerprint == cur_fp

            # 5. Early cancel check before fingerprint
            early_cancel = threading.Event()
            early_cancel.set()
            with pytest.raises(ImportCancelledError):
                run_large_import(store, csv_file, "csv", {}, source_id="src_early_cancel", cancel_event=early_cancel)
    finally:
        ps.close()
