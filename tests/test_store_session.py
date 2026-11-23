"""Tests for ProjectStore session class (analytics_studio.store.session)."""

import os
import shutil
import threading
import time
import pytest

from analytics_studio.store.base import StoreError, StoreLockedError
from analytics_studio.store.duck_store import DuckStore
from analytics_studio.store.session import ProjectStore
import analytics_studio.store.session as session_module


def test_open_creates_file_and_reopen_and_locked(tmp_path):
    data_path = str(tmp_path / "project.npa.data")
    ps = ProjectStore.open(data_path)
    assert not ps.unsaved
    assert os.path.exists(data_path)
    assert not ps.busy

    # Create a table
    ps.store.create_table("test_table", [("id", "whole"), ("name", "text")])
    ps.store.append_rows("test_table", [(1, "Alice"), (2, "Bob")])
    assert ps.store.row_count("test_table") == 2

    # Second open on the same path raises StoreLockedError
    with pytest.raises(StoreLockedError):
        ProjectStore.open(data_path)

    # After close it opens cleanly and sees existing tables
    ps.close()
    ps2 = ProjectStore.open(data_path)
    try:
        assert ps2.store.has_table("test_table")
        assert ps2.store.row_count("test_table") == 2
    finally:
        ps2.close()


def test_open_readonly_folder(tmp_path):
    ro_dir = tmp_path / "readonly_dir"
    ro_dir.mkdir()
    try:
        ro_dir.chmod(0o555)
    except Exception:
        pytest.skip("chmod not supported or running as root")

    # If running as root, chmod 0555 still allows write, so check write access
    if os.access(str(ro_dir), os.W_OK):
        ro_dir.chmod(0o777)
        pytest.skip("Filesystem ignores chmod 0o555 (e.g. root)")

    data_path = str(ro_dir / "test.npa.data")
    try:
        with pytest.raises(StoreError) as exc_info:
            ProjectStore.open(data_path)
        assert "Cannot create the data file next to the project (folder is read-only). Use Save As in a writable folder." in str(exc_info.value)
    finally:
        ro_dir.chmod(0o777)


def test_open_unsaved_and_reap_stale(tmp_path):
    app_data_dir = str(tmp_path / "app_data")
    os.makedirs(app_data_dir, exist_ok=True)

    ps_unsaved = ProjectStore.open_unsaved(app_data_dir)
    assert ps_unsaved.unsaved
    data_path = ps_unsaved.path
    assert "store-tmp" in data_path
    assert data_path.endswith("unsaved.npa.data")
    assert os.path.exists(data_path)
    assert os.path.exists(data_path + ".lock")

    folder = os.path.dirname(data_path)
    now = time.time()

    # 1. While ps_unsaved is open (lock held), reap_stale with now + 48 hours keeps it
    removed = ProjectStore.reap_stale(app_data_dir, max_age_hours=24.0, now=now + 48 * 3600)
    assert folder not in removed
    assert os.path.exists(folder)

    # Close ps_unsaved so lock is released
    ps_unsaved.close()

    # 2. Young folder is kept
    removed = ProjectStore.reap_stale(app_data_dir, max_age_hours=24.0, now=now + 100)
    assert folder not in removed
    assert os.path.exists(folder)

    # 3. Old folder with an unexpected file is kept
    bad_file = os.path.join(folder, "extra.txt")
    with open(bad_file, "w") as f:
        f.write("hello")
    removed = ProjectStore.reap_stale(app_data_dir, max_age_hours=24.0, now=now + 48 * 3600)
    assert folder not in removed
    assert os.path.exists(folder)
    os.remove(bad_file)

    # 4. Old folder without unexpected files and without lock is removed
    removed = ProjectStore.reap_stale(app_data_dir, max_age_hours=24.0, now=now + 48 * 3600)
    assert folder in removed
    assert not os.path.exists(folder)

    # 5. Path outside store-tmp is never touched
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    ProjectStore.reap_stale(app_data_dir, max_age_hours=0.0)
    assert outside_dir.exists()


def test_data_file_for_and_resolve_data_file(tmp_path):
    proj_path = str(tmp_path / "my_project.npa")
    assert ProjectStore.data_file_for(proj_path) == str(tmp_path / "my_project.npa.data")

    # 1. Missing data file returns None
    assert ProjectStore.resolve_data_file(proj_path, None) is None

    # 2. data_file_for exists
    expected_data = tmp_path / "my_project.npa.data"
    expected_data.write_text("data")
    assert ProjectStore.resolve_data_file(proj_path, None) == str(expected_data)
    expected_data.unlink()

    # 3. saved_name fallback exists
    saved_file = tmp_path / "saved_custom.data"
    saved_file.write_text("custom")
    assert ProjectStore.resolve_data_file(proj_path, "saved_custom.data") == str(saved_file)

    # 4. Refuse malicious or relative saved_name
    assert ProjectStore.resolve_data_file(proj_path, "../outside.data") is None
    assert ProjectStore.resolve_data_file(proj_path, "sub/dir.data") is None
    assert ProjectStore.resolve_data_file(proj_path, "..") is None


def test_table_name_and_duckdb_acceptance(tmp_path):
    assert ProjectStore.table_name("Sales Data", 1) == "src_sales_data_g1"
    assert ProjectStore.table_name("src-2024!_#$", 0) == "src_src_2024_____g0"

    with pytest.raises(StoreError):
        ProjectStore.table_name("", 0)
    with pytest.raises(StoreError):
        ProjectStore.table_name("valid", -1)

    # Test that DuckStore accepts generated table name
    t_name = ProjectStore.table_name("My Table #1", 3)
    ps = ProjectStore.open(str(tmp_path / "tbl_test.npa.data"))
    try:
        ps.store.create_table(t_name, [("c1", "whole")])
        assert ps.store.has_table(t_name)
    finally:
        ps.close()

    assert isinstance(ProjectStore.duckdb_version(), str)
    assert len(ProjectStore.duckdb_version()) > 0


def test_job_and_busy_behavior(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "job_test.npa.data"))
    try:
        assert not ps.busy

        job_entered = threading.Event()
        release_job = threading.Event()

        def worker():
            with ps.job() as cancel_ev:
                assert not cancel_ev.is_set()
                job_entered.set()
                release_job.wait()

        th = threading.Thread(target=worker)
        th.start()
        job_entered.wait()

        assert ps.busy

        # Second job raises busy StoreError
        with pytest.raises(StoreError, match="busy with another operation"):
            with ps.job():
                pass

        # call and checkpoint raise busy StoreError
        with pytest.raises(StoreError, match="busy with another operation"):
            ps.call(lambda store: store.table_names())

        with pytest.raises(StoreError, match="busy with another operation"):
            ps.checkpoint()

        # The DuckStore itself is NOT locked by job()
        # Direct call on ps.store works if invoked directly
        assert ps.store.table_names() == []

        release_job.set()
        th.join()

        assert not ps.busy

        # After exception in job(), busy flag is cleared
        with pytest.raises(RuntimeError):
            with ps.job():
                assert ps.busy
                raise RuntimeError("failure")
        assert not ps.busy
    finally:
        ps.close()


def test_validate_table(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "val_test.npa.data"))
    try:
        ps.store.create_table("t1", [("a", "whole"), ("b", "text")])
        ps.store.append_rows("t1", [(1, "x"), (2, "y")])

        # OK
        ps.validate_table("t1", ["a", "b"], ["whole", "text"], 2)

        # Missing table
        with pytest.raises(StoreError, match="missing from the store"):
            ps.validate_table("missing_tbl", ["a"], ["whole"], 0)

        # Column name mismatch
        with pytest.raises(StoreError, match="Columns differ for table 't1' at position 0"):
            ps.validate_table("t1", ["diff_name", "b"], ["whole", "text"], 2)

        # Type mismatch
        with pytest.raises(StoreError, match="Columns differ for table 't1' at position 1"):
            ps.validate_table("t1", ["a", "b"], ["whole", "whole"], 2)

        # Row count mismatch
        with pytest.raises(StoreError, match="Row count differs for table 't1': expected 5, found 2"):
            ps.validate_table("t1", ["a", "b"], ["whole", "text"], 5)
    finally:
        ps.close()


def test_drop_unreferenced(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "drop_test.npa.data"))
    try:
        ps.store.create_table("src_keep_g1", [("a", "whole")])
        ps.store.create_table("src_drop_g1", [("a", "whole")])
        ps.store.create_table("other_table", [("a", "whole")])

        dropped = ps.drop_unreferenced(keep=["SRC_KEEP_g1"])
        assert "src_drop_g1" in dropped
        assert "other_table" not in dropped
        assert ps.store.has_table("src_keep_g1")
        assert not ps.store.has_table("src_drop_g1")
        assert ps.store.has_table("other_table")

        # Refuses while busy
        with ps.job():
            with pytest.raises(StoreError, match="busy with another operation"):
                ps.drop_unreferenced([])
    finally:
        ps.close()


def test_copy_to_wal_and_features(tmp_path, monkeypatch):
    ps = ProjectStore.open(str(tmp_path / "copy_src.npa.data"))
    try:
        # Create 20,000-row table
        ps.store.create_table("t_large", [("num", "whole"), ("txt", "text")])
        rows = [(i, f"val_{i}") for i in range(20000)]
        ps.store.append_rows("t_large", rows)
        # Note: we do NOT call ps.checkpoint() manually; copy_to must checkpoint.

        progress_calls = []
        def on_progress(copied, total):
            progress_calls.append((copied, total))

        target_path = str(tmp_path / "copy_dst.npa.data")
        ret_path = ps.copy_to(target_path, progress=on_progress)
        assert os.path.realpath(ret_path) == os.path.realpath(target_path)
        assert os.path.exists(target_path)

        # Verify progress calls monotone and ends at total
        assert len(progress_calls) > 0
        last_copied = 0
        for c, tot in progress_calls:
            assert c >= last_copied
            assert tot == progress_calls[0][1]
            last_copied = c
        assert progress_calls[-1][0] == progress_calls[-1][1]

        # Verify rows in copied store
        with DuckStore(target_path) as dst_store:
            assert dst_store.row_count("t_large") == 20000
            first_row = dst_store.read_page("t_large", offset=0, limit=1)
            assert first_row[0] == (0, "val_0")

        # Overwrite refusal and overwrite=True
        with pytest.raises(StoreError, match="already exists"):
            ps.copy_to(target_path, overwrite=False)

        # Overwrite=True succeeds
        ps.copy_to(target_path, overwrite=True)

        # Free space check failure leaves no temp files
        import collections
        DiskUsage = collections.namedtuple("usage", ["total", "used", "free"])
        monkeypatch.setattr(shutil, "disk_usage", lambda path: DiskUsage(1000, 1000, 0))
        target_fail = str(tmp_path / "fail_space.npa.data")
        with pytest.raises(StoreError, match="Not enough free disk space"):
            ps.copy_to(target_fail)
        monkeypatch.undo()

        # No temp files left
        tmp_files = [f for f in os.listdir(tmp_path) if ".tmp-" in f]
        assert tmp_files == []

        # Cancel mid-copy leaves no temp file and target untouched
        cancel_target = str(tmp_path / "cancel_target.npa.data")
        monkeypatch.setattr(session_module, "_COPY_CHUNK", 1024)
        c_ev = threading.Event()
        c_ev.set()  # Cancelled before first chunk or immediately
        with pytest.raises(Exception) as exc_info:
            ps.copy_to(cancel_target, cancel_event=c_ev)
        assert "Copy canceled" in str(exc_info.value)
        assert not os.path.exists(cancel_target)
        tmp_files = [f for f in os.listdir(tmp_path) if ".tmp-" in f]
        assert tmp_files == []
        monkeypatch.undo()

        # Verification failure removes temp file
        monkeypatch.setattr(ps.store, "row_count", lambda tbl: 999999)
        verif_target = str(tmp_path / "verif_target.npa.data")
        with pytest.raises(StoreError, match="Verification failed"):
            ps.copy_to(verif_target)
        monkeypatch.undo()
        assert not os.path.exists(verif_target)
        tmp_files = [f for f in os.listdir(tmp_path) if ".tmp-" in f]
        assert tmp_files == []

        # Source store still usable
        assert ps.store.row_count("t_large") == 20000
    finally:
        ps.close()


def test_rebind(tmp_path):
    app_data = str(tmp_path / "app_data")
    ps = ProjectStore.open_unsaved(app_data)
    old_path = ps.path
    ps.store.create_table("t1", [("x", "whole")])
    ps.store.append_rows("t1", [(10,)])

    target_data = str(tmp_path / "saved.npa.data")
    ps.copy_to(target_data)

    # 1. Unsaved move with delete_old=True
    ps.rebind(target_data, delete_old=True)
    assert not ps.unsaved
    assert ps.path == os.path.realpath(target_data)
    assert ps.store.row_count("t1") == 1
    assert not os.path.exists(old_path)
    assert not os.path.exists(old_path + ".lock")

    # 2. Save As with delete_old=False
    save_as_target = str(tmp_path / "saved_as.npa.data")
    ps.copy_to(save_as_target)
    live_path_before = ps.path
    ps.rebind(save_as_target, delete_old=False)
    assert os.path.exists(live_path_before)  # Old file stayed
    assert ps.path == os.path.realpath(save_as_target)

    # 3. Failed open of target restores the old store
    bad_target = str(tmp_path / "is_a_directory")
    os.makedirs(bad_target, exist_ok=True)
    with pytest.raises(StoreError):
        ps.rebind(bad_target, delete_old=False)
    assert ps.path == os.path.realpath(save_as_target)
    assert ps.store.row_count("t1") == 1

    # 4. Refuse while busy
    with ps.job():
        with pytest.raises(StoreError, match="busy with another operation"):
            ps.rebind(save_as_target, delete_old=False)
    ps.close()


def test_discard_copy(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "discard_src.npa.data"))
    try:
        copy_path = str(tmp_path / "discard_copy.npa.data")
        ps.copy_to(copy_path)
        assert os.path.exists(copy_path)

        # Refuses live path
        with pytest.raises(StoreError, match="Cannot discard the current live store"):
            ps.discard_copy(ps.path)

        # Discards copy
        ps.discard_copy(copy_path)
        assert not os.path.exists(copy_path)
        assert not os.path.exists(copy_path + ".lock")
    finally:
        ps.close()


def test_shutdown_and_close(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "shutdown_test.npa.data"))
    spill = ps._spill_dir
    assert spill is not None and os.path.isdir(spill)

    # Idle shutdown closes store and removes spill
    assert ps.shutdown() is True
    assert not os.path.exists(spill)
    # Safe to call twice
    assert ps.shutdown() is True

    # Shutdown with a running job that ends after cancel
    ps2 = ProjectStore.open(str(tmp_path / "shutdown_job.npa.data"))
    job_started = threading.Event()
    job_ended = threading.Event()

    def job_runner():
        with ps2.job() as cancel_ev:
            job_started.set()
            while not cancel_ev.is_set():
                time.sleep(0.01)
        job_ended.set()

    th = threading.Thread(target=job_runner)
    th.start()
    job_started.wait()

    assert ps2.shutdown(timeout=5.0) is True
    job_ended.wait()
    th.join()

    # Shutdown with a job that never ends and timeout expires -> returns False
    ps3 = ProjectStore.open(str(tmp_path / "shutdown_hang.npa.data"))
    hang_started = threading.Event()
    stop_hang = threading.Event()

    def hang_runner():
        with ps3.job():
            hang_started.set()
            stop_hang.wait()

    th_hang = threading.Thread(target=hang_runner)
    th_hang.start()
    hang_started.wait()

    try:
        assert ps3.shutdown(timeout=0.2) is False
        assert ps3._store is not None  # Store still open
        # close() during job raises busy
        with pytest.raises(StoreError, match="busy with another operation"):
            ps3.close()
    finally:
        stop_hang.set()
        th_hang.join()
        ps3.close()


def test_spill_dir_config(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "spill_test.npa.data"))
    try:
        spill_dir = ps._spill_dir
        assert spill_dir is not None
        assert "analytics-studio-spill" in spill_dir
        res = ps.store.execute("SELECT current_setting('temp_directory')")
        setting_val = res[0][0]
        assert os.path.realpath(setting_val) == os.path.realpath(spill_dir)
    finally:
        ps.close()
