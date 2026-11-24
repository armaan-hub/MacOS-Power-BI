"""Tests for controller profileColumn and export_data_path with store tables."""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate
from analytics_studio.large_table_error import LargeTableError
from analytics_studio.store.base import StoreError
from analytics_studio.store.candidate import StoreCandidate
from analytics_studio.store.session import ProjectStore


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["controller_store_profile_export_test"])
    return app


def test_profile_and_export_differential_2000_rows(qapp: QApplication, tmp_path: Path) -> None:
    """Differential test: profileColumn and export_data_path match ordinary candidate."""
    data_file = tmp_path / "diff.npa.data"
    ps = ProjectStore.open(str(data_file))

    n = 2000
    ints = list(range(n))
    floats = [i * 1.5 for i in range(n)]
    dates = [datetime.date(2020, 1, 1) + datetime.timedelta(days=i) for i in range(n)]
    texts = [None if i % 10 == 0 else ("" if i % 10 == 1 else f"txt_{i}") for i in range(n)]
    dups = [f"dup_{i % 5}" for i in range(n)]

    headers = ["c_int", "c_float", "c_date", "c_text", "c_dup"]
    rows = []
    for i in range(n):
        rows.append({
            "c_int": ints[i],
            "c_float": floats[i],
            "c_date": dates[i].isoformat(),
            "c_text": texts[i],
            "c_dup": dups[i],
        })

    batch = pa.RecordBatch.from_arrays(
        [
            pa.array(ints),
            pa.array(floats),
            pa.array([d.isoformat() for d in dates]),
            pa.array(texts),
            pa.array(dups),
        ],
        names=headers,
    )
    ps.store.create_table_from_arrow(
        "t_2000",
        [("c_int", "whole"), ("c_float", "decimal"), ("c_date", "text"), ("c_text", "text"), ("c_dup", "text")],
        [batch],
    )

    store_cand = StoreCandidate(
        "csv",
        headers,
        {},
        [],
        store_table="t_2000",
        row_count=n,
        physical_types=["whole", "decimal", "text", "text", "text"],
        session=ps,
    )

    ord_cand = ImportCandidate(
        "csv",
        headers,
        rows,
        {},
        [],
    )

    c_store = StudioController()
    c_store._install_source(None, "src_store", store_cand)

    c_ord = StudioController()
    c_ord._install_source(None, "src_ord", ord_cand)

    # 1. profileColumn differential check for all columns
    for col in headers:
        p_store = c_store.profileColumn(col)
        p_ord = c_ord.profileColumn(col)
        assert p_store == p_ord, f"Mismatch in profileColumn('{col}'): {p_store} != {p_ord}"

    # 2. export differential check
    f_store = tmp_path / "export_store.csv"
    f_ord = tmp_path / "export_ord.csv"
    assert c_store.export_data_path(f_store) is True
    assert c_ord.export_data_path(f_ord) is True
    assert f_store.read_bytes() == f_ord.read_bytes(), "Export bytes mismatch between store and ordinary"

    ps.close()


def test_no_candidate_rows_read_during_profile_and_export(qapp: QApplication, tmp_path: Path) -> None:
    ps = ProjectStore.open(str(tmp_path / "norows.npa.data"))
    batch = pa.RecordBatch.from_arrays([pa.array([1, 2, 3])], names=["x"])
    ps.store.create_table_from_arrow("t_norows", [("x", "whole")], [batch])

    store_cand = StoreCandidate(
        "csv",
        ["x"],
        {},
        [],
        store_table="t_norows",
        row_count=3,
        physical_types=["whole"],
        session=ps,
    )

    # Calling .rows directly raises LargeTableError
    with pytest.raises(LargeTableError):
        _ = store_cand.rows

    controller = StudioController()
    controller._install_source(None, "src_norows", store_cand)

    # profileColumn does not raise LargeTableError
    profile = controller.profileColumn("x")
    assert profile["rowCount"] == 3

    # export_data_path does not raise LargeTableError
    exp_file = tmp_path / "out_norows.csv"
    assert controller.export_data_path(exp_file) is True
    assert exp_file.exists()

    ps.close()


def test_export_calls_fsync(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that export_data_path calls os.fsync before closing the temp file."""
    ps = ProjectStore.open(str(tmp_path / "fsync.npa.data"))
    batch = pa.RecordBatch.from_arrays([pa.array([1, 2])], names=["val"])
    ps.store.create_table_from_arrow("t_fsync", [("val", "whole")], [batch])

    store_cand = StoreCandidate(
        "csv",
        ["val"],
        {},
        [],
        store_table="t_fsync",
        row_count=2,
        physical_types=["whole"],
        session=ps,
    )

    controller = StudioController()
    controller._install_source(None, "src_fsync", store_cand)

    fsync_called = []
    real_fsync = os.fsync

    def tracking_fsync(fd: int) -> None:
        fsync_called.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", tracking_fsync)

    out_file = tmp_path / "fsync_out.csv"
    assert controller.export_data_path(out_file) is True
    assert len(fsync_called) == 1, "Expected os.fsync to be called once during export"

    ps.close()



def test_busy_store_refusal(qapp: QApplication, tmp_path: Path) -> None:
    """Verify that when store is busy, profileColumn and export_data_path refuse with busy status."""
    ps = ProjectStore.open(str(tmp_path / "busy.npa.data"))
    batch = pa.RecordBatch.from_arrays([pa.array([10, 20])], names=["val"])
    ps.store.create_table_from_arrow("t_busy", [("val", "whole")], [batch])

    store_cand = StoreCandidate(
        "csv",
        ["val"],
        {},
        [],
        store_table="t_busy",
        row_count=2,
        physical_types=["whole"],
        session=ps,
    )

    controller = StudioController()
    controller._install_source(None, "src_busy", store_cand)

    # Mark store busy via job() context
    with ps.job():
        assert ps.busy is True
        # profileColumn returns {} and sets busy status
        profile = controller.profileColumn("val")
        assert profile == {}
        assert controller.statusMessage == "The large-data store is busy. Try again in a moment."

        # export_data_path returns False, creates no file, and sets busy status
        exp_path = tmp_path / "should_not_exist.csv"
        assert controller.export_data_path(exp_path) is False
        assert not exp_path.exists()
        assert controller.statusMessage == "The large-data store is busy. Try again in a moment."

    ps.close()


def test_export_failure_cleanup(qapp: QApplication, tmp_path: Path) -> None:
    """Verify that failure mid-stream leaves no temp file and leaves existing target untouched."""
    ps = ProjectStore.open(str(tmp_path / "fail.npa.data"))
    batch = pa.RecordBatch.from_arrays([pa.array([1, 2, 3])], names=["val"])
    ps.store.create_table_from_arrow("t_fail", [("val", "whole")], [batch])

    store_cand = StoreCandidate(
        "csv",
        ["val"],
        {},
        [],
        store_table="t_fail",
        row_count=3,
        physical_types=["whole"],
        session=ps,
    )

    controller = StudioController()
    controller._install_source(None, "src_fail", store_cand)

    target_file = tmp_path / "target.csv"
    target_file.write_text("existing content", encoding="utf-8")

    # Monkeypatch session.call to simulate error mid-stream
    real_call = ps.call

    def failing_call(fn: Any) -> Any:
        def wrapped_fn(store: Any) -> Any:
            # Let it start then raise StoreError
            raise StoreError("Disk write failed simulated")
        return real_call(wrapped_fn)

    ps.call = failing_call  # type: ignore[assignment]

    assert controller.export_data_path(target_file) is False
    assert "Could not export data: Disk write failed simulated" in controller.statusMessage
    # Target file still exists with original content
    assert target_file.read_text(encoding="utf-8") == "existing content"

    # Verify no temp files left behind in target directory
    temp_files = list(tmp_path.glob(".target.csv.*.tmp"))
    assert len(temp_files) == 0

    ps.call = real_call  # type: ignore[assignment]
    ps.close()


def test_export_atomic_overwrite_and_empty_table(qapp: QApplication, tmp_path: Path) -> None:
    """Verify atomic overwrite of target and export of empty table (0 rows)."""
    ps = ProjectStore.open(str(tmp_path / "empty_overwrite.npa.data"))
    batch_0 = pa.RecordBatch.from_arrays([pa.array([], type=pa.int64())], names=["col"])
    ps.store.create_table_from_arrow("t_empty", [("col", "whole")], [batch_0])

    store_cand_empty = StoreCandidate(
        "csv",
        ["col"],
        {},
        [],
        store_table="t_empty",
        row_count=0,
        physical_types=["whole"],
        session=ps,
    )

    controller = StudioController()
    controller._install_source(None, "src_empty", store_cand_empty)

    exp_file = tmp_path / "empty_out.csv"
    # Pre-write some file to test atomic overwrite
    exp_file.write_text("old junk", encoding="utf-8")

    assert controller.export_data_path(exp_file) is True
    assert controller.statusMessage == f"Exported 0 rows to {exp_file.name}"
    lines = exp_file.read_text(encoding="utf-8-sig").splitlines()
    assert lines == ["col"]

    # Re-export with data to test atomic overwrite again
    batch_2 = pa.RecordBatch.from_arrays([pa.array([100, 200])], names=["col"])
    ps.store.create_table_from_arrow("t_two", [("col", "whole")], [batch_2])
    store_cand_two = StoreCandidate(
        "csv",
        ["col"],
        {},
        [],
        store_table="t_two",
        row_count=2,
        physical_types=["whole"],
        session=ps,
    )
    controller._install_source(None, "src_two", store_cand_two)

    assert controller.export_data_path(exp_file) is True
    assert controller.statusMessage == f"Exported 2 rows to {exp_file.name}"
    lines2 = exp_file.read_text(encoding="utf-8-sig").splitlines()
    assert lines2 == ["col", "100", "200"]

    ps.close()


def test_column_name_collision_resilience(qapp: QApplication, tmp_path: Path) -> None:
    """H1: Column names 'val', 'cnt', and literal '__pv_val' do not collide with SQL aliases."""
    import csv as py_csv
    from analytics_studio.store.large_import import run_large_import

    for names in (["id", "val"], ["id", "cnt"], ["val", "cnt"]):
        p = tmp_path / f"n_{'_'.join(names)}.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = py_csv.writer(f)
            w.writerow(names)
            for i in range(300):
                w.writerow([i % 7, i % 3])

        sid = "sid_" + "_".join(names)
        ps = ProjectStore.open(str(tmp_path / f"{sid}.data"))
        with ps.job():
            res = run_large_import(ps.store, p, "csv", {}, source_id=sid, max_rows=1000)

        c_store = StudioController()
        c_store._effective_app_data_dir = lambda s=sid: str(tmp_path / f"app_{s}")
        assert c_store._commit_store_import(p, res, ps)

        c_ord = StudioController()
        c_ord._effective_app_data_dir = lambda s=sid: str(tmp_path / f"app_ord_{s}")
        from analytics_studio.file_import import parse_file
        cand_ord = parse_file(p)
        assert c_ord._commit_import(p, cand_ord)

        for h in names:
            prof_store = c_store.profileColumn(h)
            prof_ord = c_ord.profileColumn(h)
            assert prof_store == prof_ord, f"Mismatch on column {h} for table {names}: {prof_store} != {prof_ord}"

        ps.close()

    # Also test a table with column literally named '__pv_val' created directly via Arrow
    ps_arrow = ProjectStore.open(str(tmp_path / "pv_col.data"))
    names_arrow = ["id", "__pv_val"]
    rows_arrow = [{"id": i % 7, "__pv_val": i % 3} for i in range(300)]
    batch_pv = pa.RecordBatch.from_arrays(
        [pa.array([r["id"] for r in rows_arrow]), pa.array([r["__pv_val"] for r in rows_arrow])],
        names=names_arrow,
    )
    ps_arrow.store.create_table_from_arrow("t_pv", [("id", "whole"), ("__pv_val", "whole")], [batch_pv])
    cand_pv_store = StoreCandidate("csv", names_arrow, {}, [], store_table="t_pv", row_count=300, physical_types=["whole", "whole"], session=ps_arrow)
    cand_pv_ord = ImportCandidate("csv", names_arrow, rows_arrow, {}, [])

    c_s = StudioController()
    c_s._install_source(None, "src_pv_s", cand_pv_store)
    c_o = StudioController()
    c_o._install_source(None, "src_pv_o", cand_pv_ord)

    for h in names_arrow:
        assert c_s.profileColumn(h) == c_o.profileColumn(h)
    ps_arrow.close()


def test_typed_column_differential_parquet(qapp: QApplication, tmp_path: Path) -> None:
    """H2 & M1: Differential test on Parquet typed columns: date, datetime, decimal, bool, text, int."""
    import decimal as D
    import pyarrow.parquet as pq
    from analytics_studio.store.large_import import run_large_import
    from analytics_studio.file_import import parse_file

    N = 600
    t = pa.table({
        "i64": pa.array([None if i % 11 == 0 else i % 40 for i in range(N)], pa.int64()),
        "f64": pa.array([None if i % 13 == 0 else [0.1 + 0.2, 1.5, -0.0, 2.0][i % 4] for i in range(N)], pa.float64()),
        "d32": pa.array([None if i % 17 == 0 else datetime.date(2026, 1, 1) + datetime.timedelta(days=i % 30) for i in range(N)], pa.date32()),
        "ts": pa.array([None if i % 19 == 0 else datetime.datetime(2026, 3, 1, 10, 0, 0) + datetime.timedelta(seconds=(i % 20) * 3661) for i in range(N)], pa.timestamp("us")),
        "ts_frac": pa.array([None if i % 23 == 0 else datetime.datetime(2026, 3, 1, 10, 0, 0, 123456) + datetime.timedelta(seconds=i % 5) for i in range(N)], pa.timestamp("us")),
        "dec": pa.array([None if i % 29 == 0 else D.Decimal(i % 9) / D.Decimal(4) for i in range(N)], pa.decimal128(12, 3)),
        "bool": pa.array([None if i % 7 == 0 else bool(i % 3) for i in range(N)], pa.bool_()),
        "txtblank": pa.array(["" if i % 4 == 0 else (None if i % 4 == 1 else f"x{i % 3}") for i in range(N)], pa.string()),
    })
    p = tmp_path / "all_types.parquet"
    pq.write_table(t, p)

    sid = "pq_diff"
    ps = ProjectStore.open(str(tmp_path / f"{sid}.data"))
    with ps.job():
        res = run_large_import(ps.store, p, "parquet", {}, source_id=sid, max_rows=10000)

    cs = StudioController()
    cs._effective_app_data_dir = lambda: str(tmp_path / "app_pq_s")
    assert cs._commit_store_import(p, res, ps)

    co = StudioController()
    co._effective_app_data_dir = lambda: str(tmp_path / "app_pq_o")
    cand_ord = parse_file(p)
    assert co._commit_import(p, cand_ord)

    # 1. Profile differential on every typed column
    for h in t.column_names:
        prof_s = cs.profileColumn(h)
        prof_o = co.profileColumn(h)
        assert prof_s == prof_o, f"Profile mismatch on {h}: {prof_s} != {prof_o}"

    # 2. Export bytes differential
    out_s = tmp_path / "exp_s.csv"
    out_o = tmp_path / "exp_o.csv"
    assert cs.export_data_path(out_s) is True
    assert co.export_data_path(out_o) is True
    assert out_s.read_bytes() == out_o.read_bytes(), "Export bytes mismatch on typed parquet"

    ps.close()


def test_text_case_space_divergence_documented(qapp: QApplication, tmp_path: Path) -> None:
    """M2: Intended Stage B divergence: VertiPaq ordinary folds text case/space, store preserves exact text."""
    import pyarrow.parquet as pq
    from analytics_studio.store.large_import import run_large_import
    from analytics_studio.file_import import parse_file

    # "Alpha" vs "alpha", and "  sp " vs "  sp"
    words = ["Alpha", "alpha", "  sp ", "  sp"]
    t = pa.table({"txt": pa.array(words * 20, pa.string())})
    p = tmp_path / "divergence.parquet"
    pq.write_table(t, p)

    sid = "div_sid"
    ps = ProjectStore.open(str(tmp_path / f"{sid}.data"))
    with ps.job():
        res = run_large_import(ps.store, p, "parquet", {}, source_id=sid, max_rows=1000)

    cs = StudioController()
    cs._effective_app_data_dir = lambda: str(tmp_path / "app_div_s")
    assert cs._commit_store_import(p, res, ps)

    co = StudioController()
    co._effective_app_data_dir = lambda: str(tmp_path / "app_div_o")
    cand_ord = parse_file(p)
    assert co._commit_import(p, cand_ord)

    prof_s = cs.profileColumn("txt")
    prof_o = co.profileColumn("txt")

    # Documented intended divergence: store has 4 distinct groups ("Alpha", "alpha", "  sp ", "  sp"),
    # while ordinary importer folds case and strips trailing whitespace (2 distinct groups).
    assert prof_s["distinctCount"] == 4
    assert prof_o["distinctCount"] == 2

    ps.close()


def test_busy_folder_name_not_misclassified(qapp: QApplication, tmp_path: Path) -> None:
    """M3: Exporting to a path whose folder contains 'busy' but fails with a non-busy error must NOT say busy."""
    ps = ProjectStore.open(str(tmp_path / "busy_name.data"))
    batch = pa.RecordBatch.from_arrays([pa.array([1, 2])], names=["x"])
    ps.store.create_table_from_arrow("t_x", [("x", "whole")], [batch])
    cand = StoreCandidate("csv", ["x"], {}, [], store_table="t_x", row_count=2, physical_types=["whole"], session=ps)
    c = StudioController()
    c._install_source(None, "src_x", cand)

    # Create a file named 'busybox' so that attempting to create a directory under it fails with NotADirectory or FileExists
    busybox_file = tmp_path / "busybox"
    busybox_file.write_text("not a directory", encoding="utf-8")
    target = busybox_file / "out.csv"

    assert c.export_data_path(target) is False
    assert "The large-data store is busy" not in c.statusMessage
    assert "Could not export data:" in c.statusMessage

    ps.close()


def test_top_values_tiebreak_and_c5_cut(qapp: QApplication, tmp_path: Path) -> None:
    """M1 & M7: Top-by-count order with unequal counts and exact tiebreak rule."""
    ps = ProjectStore.open(str(tmp_path / "tiebreak.data"))
    # Groups:
    # 'a': 100
    # 'b': 80
    # 'c': 60
    # 'd': 40
    # 'beta': 20
    # 'Zeta': 20  (tie on count 20 at 5th rank: 'beta'.casefold() < 'Zeta'.casefold(), whereas 'Zeta' < 'beta' in raw ASCII)
    # 'f': 10
    vals = ["a"] * 100 + ["b"] * 80 + ["c"] * 60 + ["d"] * 40 + ["beta"] * 20 + ["Zeta"] * 20 + ["f"] * 10
    batch = pa.RecordBatch.from_arrays([pa.array(vals)], names=["v"])
    ps.store.create_table_from_arrow("t_tb", [("v", "text")], [batch])
    cand = StoreCandidate("csv", ["v"], {}, [], store_table="t_tb", row_count=len(vals), physical_types=["text"], session=ps)
    c = StudioController()
    c._install_source(None, "src_tb", cand)

    prof = c.profileColumn("v")
    top = prof["topValues"]
    assert len(top) == 5
    assert [x["value"] for x in top[:4]] == ["a", "b", "c", "d"]
    # With casefold() tier: 'beta' wins over 'Zeta' because 'beta' < 'zeta'.
    # Without casefold() tier: 'Zeta' would win because 'Z' < 'b'.
    assert top[4]["value"] == "beta"
    assert top[4]["count"] == 20

    ps.close()


def test_valid_percent_rounding(qapp: QApplication, tmp_path: Path) -> None:
    """M7: validPercent uses round() not floor //."""
    ps = ProjectStore.open(str(tmp_path / "round.data"))
    # 200 rows total: 101 valid, 99 null.
    # 101 / 200 = 50.5% -> round() gives 50, but floor // gives 50.
    # Let's use 300 rows total: 199 valid, 101 null.
    # 199 * 100 / 300 = 66.333% -> round is 66, floor is 66.
    # 201 valid out of 300: 201 * 100 / 300 = 67.0%.
    # 1000 rows: 505 valid, 495 null -> 50.5% -> round is 50 or 51?
    # In Python, round(50.5) is 50 (round-half-to-even), round(51.5) is 52.
    # Let's use 100 rows: 67 valid, 33 null -> 67% (same).
    # 3 rows: 2 valid, 1 null -> 2 * 100 / 3 = 66.6666...% -> round is 67, floor is 66!
    vals = ["x", "y", None]
    batch = pa.RecordBatch.from_arrays([pa.array(vals, type=pa.string())], names=["r"])
    ps.store.create_table_from_arrow("t_rnd", [("r", "text")], [batch])
    cand = StoreCandidate("csv", ["r"], {}, [], store_table="t_rnd", row_count=3, physical_types=["text"], session=ps)
    c = StudioController()
    c._install_source(None, "src_rnd", cand)

    prof = c.profileColumn("r")
    assert prof["validPercent"] == 67
    assert prof["nullPercent"] == 33

    ps.close()


def test_profile_and_export_error_policy_logging_and_return(qapp: QApplication, tmp_path: Path) -> None:
    """M6: Errors caught, logged with logger.exception, status set, return {} / False, no crash."""
    from unittest.mock import patch

    ps = ProjectStore.open(str(tmp_path / "err_pol.data"))
    batch = pa.RecordBatch.from_arrays([pa.array([1, 2])], names=["col"])
    ps.store.create_table_from_arrow("t_ep", [("col", "whole")], [batch])
    cand = StoreCandidate("csv", ["col"], {}, [], store_table="t_ep", row_count=2, physical_types=["whole"], session=ps)
    c = StudioController()
    c._install_source(None, "src_ep", cand)

    # 1. StoreError("The store is closed.")
    with patch.object(type(ps), "call", side_effect=StoreError("The store is closed.")):
        res_prof = c.profileColumn("col")
        assert res_prof == {}
        assert c.statusMessage == "Could not profile column: The store is closed."

        res_exp = c.export_data_path(tmp_path / "ep1.csv")
        assert res_exp is False
        assert c.statusMessage == "Could not export data: The store is closed."

    # 2. RuntimeError("arbitrary bug")
    with patch.object(type(ps), "call", side_effect=RuntimeError("disk controller melted")):
        res_prof2 = c.profileColumn("col")
        assert res_prof2 == {}
        assert c.statusMessage == "Could not profile column: disk controller melted"

        res_exp2 = c.export_data_path(tmp_path / "ep2.csv")
        assert res_exp2 is False
        assert c.statusMessage == "Could not export data: disk controller melted"

    ps.close()


def test_export_true_midstream_failure_and_os_replace_failure(qapp: QApplication, tmp_path: Path) -> None:
    """M7: cursor.fetchmany / iter_rows failure leaves old target untouched and no .tmp files."""
    import csv as py_csv
    from unittest.mock import patch

    ps = ProjectStore.open(str(tmp_path / "midfail.data"))
    N = 2500
    batch = pa.RecordBatch.from_arrays([pa.array(list(range(N)))], names=["num"])
    ps.store.create_table_from_arrow("t_mf", [("num", "whole")], [batch])
    cand = StoreCandidate("csv", ["num"], {}, [], store_table="t_mf", row_count=N, physical_types=["whole"], session=ps)
    c = StudioController()
    c._install_source(None, "src_mf", cand)

    target = tmp_path / "mf_target.csv"
    target.write_bytes(b"OLD_INTACT_CONTENT")

    # 1. Simulate midstream failure during writer.writerow
    orig_writer = py_csv.writer
    class FailingWriter:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._w = orig_writer(*args, **kwargs)
            self._count = 0

        def writerow(self, row: Any) -> Any:
            self._count += 1
            if self._count == 100:
                raise OSError("Midstream disk write error")
            return self._w.writerow(row)

    with patch("csv.writer", FailingWriter):
        assert c.export_data_path(target) is False
        assert target.read_bytes() == b"OLD_INTACT_CONTENT"
        assert list(tmp_path.glob(".mf_target.csv.*.tmp")) == []

    # 2. Simulate os.replace failure
    with patch("os.replace", side_effect=OSError("Atomic rename boom")):
        assert c.export_data_path(target) is False
        assert target.read_bytes() == b"OLD_INTACT_CONTENT"
        assert list(tmp_path.glob(".mf_target.csv.*.tmp")) == []

    ps.close()


def test_export_multi_chunk_120001_rows(qapp: QApplication, tmp_path: Path) -> None:
    """M7: Multi-chunk export of 120,001 rows matching expected bytes and row order."""
    ps = ProjectStore.open(str(tmp_path / "big_export.data"))
    N = 120_001
    batch = pa.RecordBatch.from_arrays([pa.array(list(range(N)))], names=["id"])
    ps.store.create_table_from_arrow("t_120k", [("id", "whole")], [batch])
    cand = StoreCandidate("csv", ["id"], {}, [], store_table="t_120k", row_count=N, physical_types=["whole"], session=ps)
    c = StudioController()
    c._install_source(None, "src_120k", cand)

    out = tmp_path / "out_120k.csv"
    assert c.export_data_path(out) is True
    assert c.statusMessage == f"Exported {N:,} rows to {out.name}"

    lines = out.read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) == N + 1
    assert lines[0] == "id"
    assert lines[1] == "0"
    assert lines[-1] == str(N - 1)

    ps.close()


def _typed_csv_controllers(tmp_path: Path, name: str, cols: dict[str, list[str]]):
    """Import one CSV through the large-file path and the ordinary path."""
    import csv as py_csv
    from analytics_studio.store.large_import import run_large_import
    from analytics_studio.file_import import parse_file

    n = len(next(iter(cols.values())))
    path = tmp_path / f"{name}.csv"
    with open(path, "w", newline="") as handle:
        writer = py_csv.writer(handle)
        writer.writerow(list(cols))
        for i in range(n):
            writer.writerow([cols[c][i] for c in cols])
    ps = ProjectStore.open(str(tmp_path / f"{name}.data"))
    with ps.job():
        res = run_large_import(ps.store, path, "csv", {}, source_id=name, max_rows=100_000)
    cs = StudioController()
    cs._effective_app_data_dir = lambda: str(tmp_path / f"app_{name}_s")
    assert cs._commit_store_import(path, res, ps)
    co = StudioController()
    co._effective_app_data_dir = lambda: str(tmp_path / f"app_{name}_o")
    assert co._commit_import(path, parse_file(path))
    return cs, co, ps


def test_store_profile_error_count_always_zero_typed_csv(qapp: QApplication, tmp_path: Path) -> None:
    """M5: a stored column has no conversion errors; a YYYYMMDD date column is 100% valid."""
    n = 60
    cols = {
        "d_iso": [f"2026-01-{(i % 28) + 1:02d}" for i in range(n)],
        "d_ymd": [f"2026{(i % 12) + 1:02d}{(i % 28) + 1:02d}" for i in range(n)],
        "dt": [f"2026-01-05 10:{i % 60:02d}:00" for i in range(n)],
        "tm": [f"10:{i % 60:02d}:00" for i in range(n)],
        "bl": [["true", "false"][i % 2] for i in range(n)],
        "whole": [str(i) for i in range(n)],
        "dec": [f"{i}.25" for i in range(n)],
        "whole_blank": ["" if i % 5 == 0 else str(i) for i in range(n)],
        "dec_bad": ["x" if i == 3 else f"{i}.5" for i in range(n)],
    }
    cs, co, ps = _typed_csv_controllers(tmp_path, "m5", cols)
    types = cs._active_column_type_map()
    assert types == co._active_column_type_map()
    assert [types[h] for h in ("d_iso", "d_ymd", "dt", "tm", "bl", "whole", "dec")] == [
        "date", "date", "datetime", "time", "boolean", "whole_number", "decimal_number",
    ]
    for h in cols:
        a = cs.profileColumn(h)
        assert a["errorCount"] == 0, h
        assert a["errorPercent"] == 0, h
        assert a["validCount"] == a["rowCount"] - a["emptyCount"] - a["nullCount"], h
        b = co.profileColumn(h)
        # Both paths agree on counts whenever the ordinary path finds no errors either.
        if b["errorCount"] == 0:
            assert a == b, f"{h}: {a} != {b}"
    ymd = cs.profileColumn("d_ymd")
    assert ymd["validPercent"] == 100
    assert ymd["validCount"] == n
    ps.close()


def _make_store_controller(tmp_path: Path, name: str, values: list[Any], arrow_type: Any, phys: str):
    """One-column store table 'col' with the given values, installed in a controller."""
    ps = ProjectStore.open(str(tmp_path / f"{name}.data"))
    batch = pa.RecordBatch.from_arrays([pa.array(values, type=arrow_type)], names=["col"])
    ps.store.create_table_from_arrow(f"t_{name}", [("col", phys)], [batch])
    cand = StoreCandidate(
        "csv", ["col"], {}, [], store_table=f"t_{name}", row_count=len(values),
        physical_types=[phys], session=ps,
    )
    c = StudioController()
    c._install_source(None, f"src_{name}", cand)
    return c, ps


def test_top_values_type_tiebreak_after_text_tiebreak(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q2b: equal count and equal text order by profile type (injected: real data cannot reach it).

    One stored column has one DuckDB type, and the formatter gives one profile type per
    Python type, so two groups with the same text and different types cannot come from a
    real import (checked: int/float/Decimal -> number, bool -> boolean, date/datetime -> date or
    datetime with different text, str -> text). The formatter is replaced to pin the sort key
    against the ordinary branch, which sorts on (count, casefold, text, type).
    """
    import analytics_studio.controller as ctl

    c, ps = _make_store_controller(tmp_path, "q2b", [1, 1, 2, 2], pa.int64(), "whole")
    for first_type, second_type in (("number", "boolean"), ("boolean", "number")):
        def fake(val: Any, app_type: Any, target: str, source_arrow_type: Any = None) -> Any:
            return "same", (first_type if val == 1 else second_type)

        monkeypatch.setattr(ctl, "_format_store_cell", fake)
        top = c.profileColumn("col")["topValues"]
        assert [t["type"] for t in top] == ["boolean", "number"], (first_type, second_type)
        assert [t["value"] for t in top] == ["same", "same"]
    ps.close()


def test_export_follows_rn_order_not_physical_order(qapp: QApplication, tmp_path: Path) -> None:
    """X2: the CSV follows __rn even when rows are stored in another physical order."""
    ps = ProjectStore.open(str(tmp_path / "rn_order.data"))
    ps.store.create_table("t_rn", [("v", "text")])
    ps.store._conn.execute("INSERT INTO \"t_rn\" VALUES ('third', 2), ('first', 0), ('second', 1)")
    assert [r[0] for r in ps.store._conn.execute('SELECT "v" FROM "t_rn"').fetchall()] == ["third", "first", "second"]
    cand = StoreCandidate("csv", ["v"], {}, [], store_table="t_rn", row_count=3, physical_types=["text"], session=ps)
    c = StudioController()
    c._install_source(None, "src_rn", cand)
    out = tmp_path / "rn_out.csv"
    assert c.export_data_path(out) is True
    assert out.read_text(encoding="utf-8-sig").splitlines() == ["v", "first", "second", "third"]
    ps.close()


def test_export_creates_missing_parent_folders(qapp: QApplication, tmp_path: Path) -> None:
    """X14: export to <tmp>/new/sub/out.csv creates the folders."""
    c, ps = _make_store_controller(tmp_path, "mkdir", [1, 2], pa.int64(), "whole")
    out = tmp_path / "new" / "sub" / "out.csv"
    assert not out.parent.exists()
    assert c.export_data_path(out) is True
    assert out.read_text(encoding="utf-8-sig").splitlines() == ["col", "1", "2"]
    assert [p.name for p in out.parent.iterdir()] == ["out.csv"]
    ps.close()


BUSY_TEXT = "The large-data store is busy. Try again in a moment."


def test_busy_race_session_call_raises_store_busy(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """X12/Q18: session.call itself raises StoreBusyError (race after the busy check)."""
    from analytics_studio.store.base import StoreBusyError

    c, ps = _make_store_controller(tmp_path, "race", [1, 2], pa.int64(), "whole")
    target = tmp_path / "race_target.csv"
    target.write_bytes(b"OLD_INTACT_CONTENT")

    def boom(self: Any, fn: Any) -> Any:
        raise StoreBusyError("The store is busy with another operation.")

    monkeypatch.setattr(type(ps), "call", boom)
    c._set_status("")
    assert c.profileColumn("col") == {}
    assert c.statusMessage == BUSY_TEXT
    c._set_status("")
    assert c.export_data_path(target) is False
    assert c.statusMessage == BUSY_TEXT
    assert target.read_bytes() == b"OLD_INTACT_CONTENT"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
    ps.close()


def test_store_own_lock_busy_shows_friendly_status(qapp: QApplication, tmp_path: Path) -> None:
    """Low: the DuckStore thread guard (another thread inside the store) shows the busy text too."""
    import threading

    c, ps = _make_store_controller(tmp_path, "ownlock", [1, 2], pa.int64(), "whole")
    target = tmp_path / "ownlock_target.csv"
    target.write_bytes(b"OLD_INTACT_CONTENT")
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with ps.store._lock:
            held.set()
            release.wait(timeout=5.0)

    th = threading.Thread(target=hold)
    th.start()
    assert held.wait(timeout=5.0)
    try:
        assert c.profileColumn("col") == {}
        assert c.statusMessage == BUSY_TEXT
        c._set_status("")
        assert c.export_data_path(target) is False
        assert c.statusMessage == BUSY_TEXT
        assert target.read_bytes() == b"OLD_INTACT_CONTENT"
    finally:
        release.set()
        th.join()
    assert c.profileColumn("col")["rowCount"] == 2
    ps.close()


def test_runtime_error_is_logged_with_traceback(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Q17/X17: an unexpected error in profile and export goes through logger.exception."""
    import logging

    c, ps = _make_store_controller(tmp_path, "logexc", [1, 2], pa.int64(), "whole")

    def boom(self: Any, fn: Any) -> Any:
        raise RuntimeError("disk controller melted")

    monkeypatch.setattr(type(ps), "call", boom)
    with caplog.at_level(logging.ERROR, logger="analytics_studio.controller"):
        assert c.profileColumn("col") == {}
        profile_records = [r for r in caplog.records if "Could not profile column" in r.getMessage()]
        assert len(profile_records) == 1
        assert profile_records[0].exc_info is not None
        assert profile_records[0].exc_info[0] is RuntimeError

        assert c.export_data_path(tmp_path / "logexc.csv") is False
        export_records = [r for r in caplog.records if "Could not export data to" in r.getMessage()]
        assert len(export_records) == 1
        assert export_records[0].exc_info is not None
        assert export_records[0].exc_info[0] is RuntimeError
    ps.close()


def test_parquet_date32_profile_type_and_value_text(qapp: QApplication, tmp_path: Path) -> None:
    """F11: Parquet date32 is stored in a datetime column; it profiles as a date, like the ordinary path."""
    import pyarrow.parquet as pq
    from analytics_studio.file_import import parse_file
    from analytics_studio.store.large_import import run_large_import

    dates = [datetime.date(2026, 1, 5)] * 3 + [datetime.date(2026, 1, 6)] * 2 + [None]
    path = tmp_path / "f11.parquet"
    pq.write_table(pa.table({"d32": pa.array(dates, pa.date32())}), path)
    ps = ProjectStore.open(str(tmp_path / "f11.data"))
    with ps.job():
        res = run_large_import(ps.store, path, "parquet", {}, source_id="f11", max_rows=1000)
    cs = StudioController()
    cs._effective_app_data_dir = lambda: str(tmp_path / "app_f11_s")
    assert cs._commit_store_import(path, res, ps)
    co = StudioController()
    co._effective_app_data_dir = lambda: str(tmp_path / "app_f11_o")
    assert co._commit_import(path, parse_file(path))

    assert cs._active_store_candidate.physical_types == ["datetime"]
    prof = cs.profileColumn("d32")
    assert prof["type"] == "date"
    assert [dict(t) for t in prof["topValues"]] == [
        {"value": "2026-01-05", "count": 3, "type": "date"},
        {"value": "2026-01-06", "count": 2, "type": "date"},
    ]
    assert prof == co.profileColumn("d32")
    out = tmp_path / "f11.csv"
    assert cs.export_data_path(out) is True
    assert out.read_text(encoding="utf-8-sig").splitlines()[1:3] == ["2026-01-05", "2026-01-05"]
    ps.close()


def test_format_store_cell_date_value_under_datetime_type() -> None:
    """F11: a plain date under a datetime column type keeps profile type 'date' (export gets midnight)."""
    import analytics_studio.controller as ctl

    value = datetime.date(2026, 1, 5)
    assert ctl._format_store_cell(value, "datetime", "profile") == ("2026-01-05", "date")
    assert ctl._format_store_cell(value, "datetime", "export") == "2026-01-05 00:00:00"
    stamp = datetime.datetime(2026, 1, 5, 0, 0)
    assert ctl._format_store_cell(stamp, "datetime", "profile") == ("2026-01-05T00:00:00", "datetime")
