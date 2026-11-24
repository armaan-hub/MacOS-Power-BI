"""Tests for ProjectStore session class (analytics_studio.store.session)."""

import contextlib
import errno
import fcntl
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


def test_finding1_copy_to_samefile_and_lock_probe(tmp_path):
    p = str(tmp_path / "live.npa.data")
    ps = ProjectStore.open(p)
    try:
        # Live path
        with pytest.raises(StoreError, match="Cannot copy the data file onto itself"):
            ps.copy_to(p, overwrite=True)
        # Case variation on same path
        p_diff_case = str(tmp_path / "LIVE.NPA.DATA")
        with pytest.raises(StoreError, match="Cannot copy the data file onto itself"):
            ps.copy_to(p_diff_case, overwrite=True)

        # Target lock probe held by another process
        target = str(tmp_path / "target_locked.npa.data")
        target_lock = target + ".lock"
        import fcntl
        fd = os.open(target_lock, os.O_RDWR | os.O_CREAT, 0o666)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(StoreError, match="The data file is in use by another process"):
                ps.copy_to(target)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    finally:
        ps.close()


def test_finding2_discard_copy_samefile_and_case(tmp_path):
    dd = tmp_path / "Dd"
    dd.mkdir()
    p = str(dd / "Live.npa.data")
    ps = ProjectStore.open(p)
    try:
        alias = str(dd / "live.npa.data")
        with pytest.raises(StoreError, match="Cannot discard the current live store data file"):
            ps.discard_copy(alias)

        link = str(dd / "link.npa.data")
        os.symlink(p, link)
        try:
            with pytest.raises(StoreError, match="Cannot discard the current live store data file"):
                ps.discard_copy(link)
        finally:
            if os.path.islink(link):
                os.unlink(link)

        # Nonexistent target with different case of live file
        alias_nonexistent = str(dd / "LIVE.NPA.DATA")
        with pytest.raises(StoreError, match="Cannot discard the current live store data file"):
            ps.discard_copy(alias_nonexistent)
    finally:
        ps.close()


def test_finding3_rebind_preserves_memory_limit_and_threads(tmp_path):
    p = str(tmp_path / "mem.npa.data")
    ps = ProjectStore.open(p, memory_limit="512MB", threads=2)
    try:
        row_before = ps.store.execute("select current_setting('memory_limit'), current_setting('threads')")[0]

        t2 = str(tmp_path / "mem2.npa.data")
        ps.copy_to(t2)
        ps.rebind(t2, delete_old=False)

        row_after = ps.store.execute("select current_setting('memory_limit'), current_setting('threads')")[0]
        assert row_after[0] == row_before[0]
        assert row_after[1] == row_before[1]
        assert int(row_after[1]) == 2
    finally:
        ps.close()


def test_finding4_exclusive_during_operations_and_job_refusal(tmp_path, monkeypatch):
    p = str(tmp_path / "excl.npa.data")
    ps = ProjectStore.open(p)
    try:
        ps.store.create_table("t", [("id", "whole")])
        ps.store.append_rows("t", [(i,) for i in range(100)])

        job_attempts = []
        def on_progress(copied, total):
            try:
                with ps.job():
                    job_attempts.append("job_ran")
            except StoreError as err:
                job_attempts.append("job_refused: " + str(err))

        monkeypatch.setattr(session_module, "_COPY_CHUNK", 128)
        tgt = str(tmp_path / "excl_dst.npa.data")
        ps.copy_to(tgt, progress=on_progress)
        monkeypatch.undo()

        assert len(job_attempts) > 0
        assert all("busy with another operation" in a for a in job_attempts)
    finally:
        ps.close()


def test_finding5_shutdown_shutting_down_flag_and_job_refusal(tmp_path):
    p = str(tmp_path / "shut_flag.npa.data")
    ps = ProjectStore.open(p)
    try:
        ev_entered = threading.Event()
        shutdown_called = threading.Event()

        def slow_cancel():
            ev_entered.set()
            shutdown_called.wait(timeout=2.0)

        ps.request_cancel = slow_cancel

        th = threading.Thread(target=lambda: ps.shutdown(timeout=2.0))
        th.start()
        assert ev_entered.wait(timeout=2.0)

        # While shutting down, job() must refuse to start
        with pytest.raises(StoreError, match="The store is shutting down"):
            with ps.job():
                pass

        shutdown_called.set()
        th.join(timeout=2.0)
    finally:
        ps.close()


def test_finding6_open_readonly_duckstore_cause(tmp_path, monkeypatch):
    ro = tmp_path / "ro_dir"
    ro.mkdir()
    try:
        ro.chmod(0o555)
    except Exception:
        pytest.skip("chmod not supported")

    p = str(ro / "ro.npa.data")
    monkeypatch.setattr(os, "access", lambda *args, **kwargs: True)
    try:
        with pytest.raises(StoreError) as exc_info:
            ProjectStore.open(p)
        assert "Cannot create the data file next to the project (folder is read-only). Use Save As in a writable folder." in str(exc_info.value)
    finally:
        ro.chmod(0o777)


def test_finding7_rebind_same_file_noop_delete_old_ignored(tmp_path):
    p = str(tmp_path / "rebind_same.npa.data")
    ps = ProjectStore.open(p)
    try:
        ps.store.create_table("t", [("a", "whole")])
        ps.store.append_rows("t", [(1,)])

        ps.rebind(p, delete_old=True)
        assert os.path.exists(p)
        assert ps.store.row_count("t") == 1

        p_upper = str(tmp_path / "REBIND_SAME.NPA.DATA")
        ps.rebind(p_upper, delete_old=True)
        assert os.path.exists(p)
        assert ps.store.row_count("t") == 1
    finally:
        ps.close()


def test_finding8_copy_to_removes_target_wal_and_readonly_target(tmp_path):
    p = str(tmp_path / "wal_src.npa.data")
    ps = ProjectStore.open(p)
    try:
        ps.store.create_table("t", [("a", "whole")])
        tgt = str(tmp_path / "wal_dst.npa.data")
        wal = tgt + ".wal"
        with open(wal, "wb") as f:
            f.write(b"PRE_EXISTING_STALE_WAL")

        ps.copy_to(tgt)
        assert not os.path.exists(wal)

        # Read-only target dir
        ro_tgt_dir = tmp_path / "ro_tgt"
        ro_tgt_dir.mkdir()
        try:
            ro_tgt_dir.chmod(0o555)
        except Exception:
            pytest.skip("chmod not supported")

        if not os.access(str(ro_tgt_dir), os.W_OK):
            ro_tgt = str(ro_tgt_dir / "out.npa.data")
            with pytest.raises(StoreError, match="Cannot write the data file: folder is read-only"):
                ps.copy_to(ro_tgt)
        ro_tgt_dir.chmod(0o777)
    finally:
        ps.close()


def test_finding9_close_and_shutdown_spill_dir_cleanup(tmp_path):
    # 1. Spill dir cleaned up even if store.close() raises
    ps = ProjectStore.open(str(tmp_path / "spill_boom.npa.data"))
    spill = ps._spill_dir
    assert spill is not None and os.path.isdir(spill)
    def boom():
        raise RuntimeError("close boom")
    ps.store.close = boom

    with pytest.raises(RuntimeError, match="close boom"):
        ps.close()
    assert not os.path.exists(spill)

    # 2. Caller-supplied spill_dir elsewhere is NEVER removed
    victim = tmp_path / "victim_spill"
    victim.mkdir()
    victim_file = victim / "keep.txt"
    victim_file.write_text("precious")

    st = DuckStore(str(tmp_path / "custom_spill.npa.data"))
    ps_custom = ProjectStore(st, unsaved=False, spill_dir=str(victim))
    ps_custom.close()
    assert victim.exists()
    assert victim_file.exists()


def test_finding10_resolve_data_file_dots_and_dirs(tmp_path):
    proj = str(tmp_path / "proj.npa")
    assert ProjectStore.resolve_data_file(proj, ".") is None
    assert ProjectStore.resolve_data_file(proj, "..") is None

    # Directory named like data file is not a data file
    d = tmp_path / "proj.npa.data"
    d.mkdir()
    assert ProjectStore.resolve_data_file(proj, None) is None
    d.rmdir()


def test_finding11_open_unsaved_failure_cleans_tmp_dir_and_rebind_cleans_empty(tmp_path, monkeypatch):
    app = str(tmp_path / "app11")
    def boom_store(*args, **kwargs):
        raise RuntimeError("duckstore failure")
    monkeypatch.setattr("analytics_studio.store.session.DuckStore", boom_store)

    with pytest.raises(RuntimeError, match="duckstore failure"):
        ProjectStore.open_unsaved(app)
    monkeypatch.undo()

    st_tmp = os.path.join(app, "store-tmp")
    if os.path.exists(st_tmp):
        assert os.listdir(st_tmp) == []

    # Rebind delete_old=True cleans empty store-tmp/<uuid>
    ps_unsaved = ProjectStore.open_unsaved(app)
    raw_folder = os.path.dirname(ps_unsaved.path)
    target = str(tmp_path / "saved_final.npa.data")
    ps_unsaved.copy_to(target)
    ps_unsaved.rebind(target, delete_old=True)
    assert not os.path.exists(raw_folder)
    ps_unsaved.close()


def test_finding12_reap_stale_symlinks(tmp_path):
    app = str(tmp_path / "app12")
    st = tmp_path / "app12" / "store-tmp"
    st.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside_stale"
    outside.mkdir()
    old_file = outside / "unsaved.npa.data"
    old_file.write_text("x")
    old_time = time.time() - 100 * 3600
    os.utime(str(old_file), (old_time, old_time))
    os.utime(str(outside), (old_time, old_time))

    os.symlink(str(outside), str(st))
    assert ProjectStore.reap_stale(app, now=time.time()) == []
    assert outside.exists()
    assert old_file.exists()


def test_finding13_table_name_sanitization_rules():
    with pytest.raises(StoreError, match="generation must be a non-negative integer"):
        ProjectStore.table_name("x", True)
    with pytest.raises(StoreError, match="must contain at least one letter or digit"):
        ProjectStore.table_name("___", 0)
    with pytest.raises(StoreError, match="must contain at least one letter or digit"):
        ProjectStore.table_name("!@#$", 0)
    assert ProjectStore.table_name("table1", 0) == "src_table1_g0"


def test_cancel_mid_stream_chunk_mutation(tmp_path, monkeypatch):
    ps = ProjectStore.open(str(tmp_path / "cancel_stream_src.npa.data"))
    try:
        ps.store.create_table("t", [("x", "text")])
        ps.store.append_rows("t", [("x" * 200,) for _ in range(2000)])
        monkeypatch.setattr(session_module, "_COPY_CHUNK", 128)

        cancel_ev = threading.Event()
        chunk_count = [0]
        def on_prog(copied, total):
            chunk_count[0] += 1
            if chunk_count[0] == 2:
                cancel_ev.set()

        tgt = str(tmp_path / "cancel_stream_dst.npa.data")
        with pytest.raises(Exception, match="Copy canceled"):
            ps.copy_to(tgt, progress=on_prog, cancel_event=cancel_ev)

        assert not os.path.exists(tgt)
        assert not os.path.exists(tgt + ".wal")
        assert not os.path.exists(tgt + ".lock")
        tmp_files = [f for f in os.listdir(tmp_path) if ".tmp-" in f]
        assert tmp_files == []
    finally:
        ps.close()


def test_copy_to_race_already_exists_final_recheck(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "race_src.npa.data"))
    try:
        tgt = str(tmp_path / "race_dst.npa.data")
        def create_target_during_copy(copied, total):
            if not os.path.exists(tgt):
                with open(tgt, "wb") as f:
                    f.write(b"interfering file")

        with pytest.raises(StoreError, match="already exists"):
            ps.copy_to(tgt, overwrite=False, progress=create_target_during_copy)
    finally:
        ps.close()


def test_copy_to_verification_table_names_mismatch(tmp_path, monkeypatch):
    ps = ProjectStore.open(str(tmp_path / "verif_tbl_src.npa.data"))
    try:
        ps.store.create_table("t1", [("a", "whole")])
        tgt = str(tmp_path / "verif_tbl_dst.npa.data")

        orig_duckstore = DuckStore
        def mock_duckstore(path, *args, **kwargs):
            st = orig_duckstore(path, *args, **kwargs)
            if ".tmp-" in path:
                monkeypatch.setattr(st, "table_names", lambda: [])
            return st

        monkeypatch.setattr("analytics_studio.store.session.DuckStore", mock_duckstore)
        with pytest.raises(StoreError, match="Verification failed: tables do not match"):
            ps.copy_to(tgt)

        assert not os.path.exists(tgt)
        tmp_files = [f for f in os.listdir(tmp_path) if ".tmp-" in f]
        assert tmp_files == []
    finally:
        ps.close()


def test_rebind_delete_old_ignored_when_not_unsaved(tmp_path):
    p = str(tmp_path / "saved_src.npa.data")
    ps = ProjectStore.open(p)
    try:
        assert not ps.unsaved
        tgt = str(tmp_path / "saved_dst.npa.data")
        ps.copy_to(tgt)
        ps.rebind(tgt, delete_old=True)
        assert os.path.exists(p)  # Must NOT be deleted because it wasn't unsaved
    finally:
        ps.close()


def test_discard_copy_removes_wal_and_lock(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "discard_wal_src.npa.data"))
    try:
        tgt = str(tmp_path / "discard_target.npa.data")
        with open(tgt, "wb") as f:
            f.write(b"data")
        with open(tgt + ".wal", "wb") as f:
            f.write(b"wal")
        with open(tgt + ".lock", "wb") as f:
            f.write(b"lock")

        ps.discard_copy(tgt)
        assert not os.path.exists(tgt)
        assert not os.path.exists(tgt + ".wal")
        assert not os.path.exists(tgt + ".lock")
    finally:
        ps.close()


def test_job_clears_cancel_at_start_and_shutdown_speed(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "job_cancel_clear.npa.data"))
    try:
        ps.request_cancel()
        assert ps.cancel_event.is_set()

        with ps.job() as cancel_ev:
            assert not cancel_ev.is_set()
            assert not ps.cancel_event.is_set()

        # shutdown speed with short-lived job
        job_done = threading.Event()
        def quick_job():
            with ps.job() as ev:
                ev.wait(timeout=0.05)
            job_done.set()

        th = threading.Thread(target=quick_job)
        th.start()
        time.sleep(0.01)

        t0 = time.time()
        assert ps.shutdown(timeout=5.0) is True
        elapsed = time.time() - t0
        assert elapsed < 1.0
        assert job_done.wait(timeout=1.0)
        th.join()
    finally:
        ps.close()


def test_spill_dir_removed_when_open_fails(tmp_path, monkeypatch):
    p = str(tmp_path / "open_fail.npa.data")
    def fail_duckstore(*args, **kwargs):
        raise RuntimeError("open failed")
    monkeypatch.setattr("analytics_studio.store.session.DuckStore", fail_duckstore)

    spill_base = os.path.join(session_module.tempfile.gettempdir(), "analytics-studio-spill")
    before_dirs = set(os.listdir(spill_base)) if os.path.exists(spill_base) else set()

    with pytest.raises(RuntimeError, match="open failed"):
        ProjectStore.open(p)

    after_dirs = set(os.listdir(spill_base)) if os.path.exists(spill_base) else set()
    assert after_dirs == before_dirs


def test_two_project_stores_have_different_spill_dirs(tmp_path):
    p1 = str(tmp_path / "p1.npa.data")
    p2 = str(tmp_path / "p2.npa.data")
    ps1 = ProjectStore.open(p1)
    ps2 = ProjectStore.open(p2)
    try:
        assert ps1._spill_dir != ps2._spill_dir
    finally:
        ps1.close()
        ps2.close()


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
    assert job_started.wait(timeout=5.0)

    assert ps2.shutdown(timeout=5.0) is True
    assert job_ended.wait(timeout=5.0)
    th.join(timeout=5.0)

    # Shutdown with a job that never ends and timeout expires -> returns False
    ps3 = ProjectStore.open(str(tmp_path / "shutdown_hang.npa.data"))
    hang_started = threading.Event()
    stop_hang = threading.Event()

    def hang_runner():
        with ps3.job():
            hang_started.set()
            assert stop_hang.wait(timeout=5.0)

    th_hang = threading.Thread(target=hang_runner)
    th_hang.start()
    assert hang_started.wait(timeout=5.0)

    try:
        assert ps3.shutdown(timeout=0.2) is False
        assert ps3._store is not None  # Store still open
        # close() during job raises busy
        with pytest.raises(StoreError, match="busy with another operation"):
            ps3.close()
    finally:
        stop_hang.set()
        th_hang.join(timeout=5.0)
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


# ---------------------------------------------------------------------------
# Second fix pass (Stage B4b task 2): re-review items N1-N7 and mutation survivors
# ---------------------------------------------------------------------------

RO_FOLDER_MSG = (
    "Cannot create the data file next to the project (folder is read-only). "
    "Use Save As in a writable folder."
)


@contextlib.contextmanager
def _readonly_dir(path):
    """Yield a 0o555 folder; skip when the filesystem or user ignores chmod."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o555)
    except Exception:
        pytest.skip("chmod not supported")
    if os.access(str(path), os.W_OK):
        path.chmod(0o777)
        pytest.skip("Filesystem ignores chmod 0o555 (e.g. root)")
    try:
        yield path
    finally:
        path.chmod(0o777)


def _store_with_rows(tmp_path, name, rows=2000):
    ps = ProjectStore.open(str(tmp_path / name))
    ps.store.create_table("t", [("x", "text")])
    ps.store.append_rows("t", [("x" * 200,) for _ in range(rows)])
    return ps


def _tmp_leftovers(folder):
    return [f for f in os.listdir(str(folder)) if ".tmp-" in f]


# ---- N1: StoreLockedError is never turned into the read-only message -------


@pytest.mark.parametrize("folder", ["read-only", "Errno 13 backup", "Permission denied stuff"])
def test_n1_locked_error_not_masked_by_words_in_path(tmp_path, folder):
    d = tmp_path / folder
    d.mkdir()
    p = str(d / "x.npa.data")
    first = ProjectStore.open(p)
    try:
        with pytest.raises(StoreLockedError):
            ProjectStore.open(p)
    finally:
        first.close()


def test_n1_locked_error_with_permission_cause_is_not_masked(tmp_path, monkeypatch):
    """A lock conflict stays a lock conflict even if its cause looks like a permission error."""
    err = _with_cause(StoreLockedError("locked"), PermissionError(errno.EACCES, "Permission denied"))

    def failing(*args, **kwargs):
        raise err

    monkeypatch.setattr(session_module, "DuckStore", failing)
    with pytest.raises(StoreLockedError) as exc_info:
        ProjectStore.open(str(tmp_path / "locked_perm.npa.data"))
    assert exc_info.value is err


def test_n1_detector_access_precheck_only(tmp_path, monkeypatch):
    """Read-only folder is found by the os.access pre-check alone (DuckStore never called)."""
    def must_not_run(*args, **kwargs):
        raise AssertionError("DuckStore must not be reached")

    monkeypatch.setattr(session_module, "DuckStore", must_not_run)
    with _readonly_dir(tmp_path / "ro1") as ro:
        with pytest.raises(StoreError) as exc_info:
            ProjectStore.open(str(ro / "a.npa.data"))
    assert str(exc_info.value) == RO_FOLDER_MSG


def test_n1_detector_access_precheck_missing_subfolder(tmp_path, monkeypatch):
    """Not-yet-existing subfolder of a read-only folder: pre-check on the nearest existing parent."""
    def must_not_run(*args, **kwargs):
        raise AssertionError("DuckStore must not be reached")

    monkeypatch.setattr(session_module, "DuckStore", must_not_run)
    with _readonly_dir(tmp_path / "ro1b") as ro:
        with pytest.raises(StoreError) as exc_info:
            ProjectStore.open(str(ro / "sub" / "deeper" / "a.npa.data"))
        assert not (ro / "sub").exists()
    assert str(exc_info.value) == RO_FOLDER_MSG


@pytest.mark.parametrize(
    "cause",
    [
        PermissionError(errno.EACCES, "Permission denied"),
        PermissionError("PermissionError without an errno"),
        OSError(errno.EROFS, "Read-only file system"),
        OSError(errno.EACCES, "plain OSError with EACCES"),
    ],
)
def test_n1_detector_cause_only(tmp_path, monkeypatch, cause):
    """Writable folder, pre-check passes; the DuckStore error carries a permission __cause__."""
    def failing(*args, **kwargs):
        raise StoreError("Failed to acquire lock file") from cause

    monkeypatch.setattr(session_module, "DuckStore", failing)
    with pytest.raises(StoreError) as exc_info:
        ProjectStore.open(str(tmp_path / "w" / "a.npa.data"))
    assert str(exc_info.value) == RO_FOLDER_MSG
    assert exc_info.value.__cause__ is not None


def test_n1_detector_end_to_end_real_readonly_folder_without_precheck(tmp_path, monkeypatch):
    """Real DuckStore on a real read-only folder with the os.access pre-check disabled."""
    with _readonly_dir(tmp_path / "ro1c") as ro:
        monkeypatch.setattr(os, "access", lambda *args, **kwargs: True)
        with pytest.raises(StoreError) as exc_info:
            ProjectStore.open(str(ro / "a.npa.data"))
    assert str(exc_info.value) == RO_FOLDER_MSG


@pytest.mark.parametrize(
    "build",
    [
        lambda: StoreError("Permission denied: Errno 13: read-only file system"),
        lambda: _with_cause(StoreError("Failed to open"), OSError(errno.ENOENT, "No such file")),
        lambda: _with_cause(StoreError("Permission denied"), ValueError("not an OS error")),
    ],
)
def test_n1_message_text_alone_is_not_read_only(tmp_path, monkeypatch, build):
    err = build()

    def failing(*args, **kwargs):
        raise err

    monkeypatch.setattr(session_module, "DuckStore", failing)
    with pytest.raises(StoreError) as exc_info:
        ProjectStore.open(str(tmp_path / "plain.npa.data"))
    assert exc_info.value is err
    assert str(exc_info.value) != RO_FOLDER_MSG


def _with_cause(exc, cause):
    exc.__cause__ = cause
    return exc


# ---- N6: read-only data file in a writable folder --------------------------


def test_n6_readonly_data_file_in_writable_folder(tmp_path):
    p = str(tmp_path / "f.npa.data")
    ProjectStore.open(p).close()
    os.chmod(p, 0o444)
    try:
        if os.access(p, os.W_OK):
            pytest.skip("Filesystem ignores chmod 0o444 (e.g. root)")
        with pytest.raises(StoreError) as exc_info:
            ProjectStore.open(p)
        assert str(exc_info.value) == "The data file is read-only: f.npa.data."
        assert "folder" not in str(exc_info.value)
    finally:
        os.chmod(p, 0o644)


# ---- N2: copy_to stops on the store's own cancel event ---------------------


def test_n2_request_cancel_stops_copy_and_shutdown_is_quick(tmp_path, monkeypatch):
    ps = _store_with_rows(tmp_path, "n2_src.npa.data")
    try:
        monkeypatch.setattr(session_module, "_COPY_CHUNK", 4096)
        calls = [0]

        def on_progress(copied, total):
            calls[0] += 1
            if calls[0] == 2:
                ps.request_cancel()

        tgt = str(tmp_path / "n2_dst.npa.data")
        with pytest.raises(session_module.ImportCancelledError, match="Copy canceled"):
            ps.copy_to(tgt, progress=on_progress)
        assert calls[0] == 2  # stopped within one chunk of the cancel
        assert not os.path.exists(tgt)
        assert not os.path.exists(tgt + ".wal")
        assert not os.path.exists(tgt + ".lock")
        assert _tmp_leftovers(tmp_path) == []

        t0 = time.time()
        assert ps.shutdown(timeout=5.0) is True
        assert time.time() - t0 < 1.0
    finally:
        ps.close()


def test_n2_shutdown_from_another_thread_stops_copy(tmp_path, monkeypatch):
    ps = _store_with_rows(tmp_path, "n2b_src.npa.data")
    try:
        monkeypatch.setattr(session_module, "_COPY_CHUNK", 4096)
        result = []
        sd_thread = threading.Thread(target=lambda: result.append(ps.shutdown(timeout=5.0)))
        calls = [0]

        def on_progress(copied, total):
            calls[0] += 1
            if calls[0] == 2:
                sd_thread.start()
                deadline = time.time() + 5.0
                while not ps.cancel_event.is_set() and time.time() < deadline:
                    time.sleep(0.005)

        tgt = str(tmp_path / "n2b_dst.npa.data")
        with pytest.raises(session_module.ImportCancelledError, match="Copy canceled"):
            ps.copy_to(tgt, progress=on_progress)
        assert calls[0] == 2
        t0 = time.time()
        sd_thread.join(timeout=5.0)
        assert not sd_thread.is_alive()
        assert result == [True]
        assert time.time() - t0 < 1.0
        assert not os.path.exists(tgt)
        assert _tmp_leftovers(tmp_path) == []
    finally:
        ps.close()


def test_n2_stale_cancel_from_earlier_does_not_cancel_a_new_copy(tmp_path):
    ps = _store_with_rows(tmp_path, "n2c_src.npa.data", rows=50)
    try:
        ps.request_cancel()  # left over from an earlier canceled job
        tgt = str(tmp_path / "n2c_dst.npa.data")
        ps.copy_to(tgt)
        assert os.path.exists(tgt)
    finally:
        ps.close()


class _EofSignal:
    """Wraps the source file; sets an event when read() returns b'' (end of file)."""

    def __init__(self, fobj, on_eof):
        self._f = fobj
        self._on_eof = on_eof

    def read(self, n=-1):
        data = self._f.read(n)
        if not data:
            self._on_eof()
        return data

    def __enter__(self):
        self._f.__enter__()
        return self

    def __exit__(self, *exc):
        return self._f.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._f, name)


@pytest.mark.parametrize("which", ["caller", "store"])
def test_copy_to_cancel_after_last_chunk_is_honored(tmp_path, monkeypatch, which):
    """Cancel arrives after the last chunk was read (at end of file): the copy must not finish."""
    ps = _store_with_rows(tmp_path, "eof_src.npa.data", rows=50)
    try:
        caller_ev = threading.Event()
        real_open = open
        source = ps.path

        def fake_open(path, mode="r", *args, **kwargs):
            f = real_open(path, mode, *args, **kwargs)
            if path == source and mode == "rb":
                return _EofSignal(f, caller_ev.set if which == "caller" else ps.request_cancel)
            return f

        monkeypatch.setattr(session_module, "open", fake_open, raising=False)
        tgt = str(tmp_path / "eof_dst.npa.data")
        with pytest.raises(session_module.ImportCancelledError, match="Copy canceled"):
            ps.copy_to(tgt, cancel_event=caller_ev if which == "caller" else None)
        assert not os.path.exists(tgt)
        assert _tmp_leftovers(tmp_path) == []
    finally:
        ps.close()


def test_copy_to_progress_not_called_again_after_caller_cancel(tmp_path, monkeypatch):
    ps = _store_with_rows(tmp_path, "pc_src.npa.data")
    try:
        monkeypatch.setattr(session_module, "_COPY_CHUNK", 4096)
        ev = threading.Event()
        calls = [0]

        def on_progress(copied, total):
            calls[0] += 1
            if calls[0] == 3:
                ev.set()

        with pytest.raises(session_module.ImportCancelledError):
            ps.copy_to(str(tmp_path / "pc_dst.npa.data"), progress=on_progress, cancel_event=ev)
        assert calls[0] == 3
    finally:
        ps.close()


# ---- N3: shutdown() that returns False lets the caller keep working --------


def test_n3_failed_shutdown_resets_shutting_down_flag(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "n3.npa.data"))
    started = threading.Event()
    release = threading.Event()
    waited = []

    def worker():
        with ps.job():
            started.set()
            waited.append(release.wait(timeout=10.0))

    th = threading.Thread(target=worker)
    th.start()
    try:
        assert started.wait(timeout=5.0)
        assert ps.shutdown(timeout=0.2) is False
        # Not "shutting down" any more: the ordinary busy message applies.
        with pytest.raises(StoreError, match="busy with another operation"):
            ps.call(lambda store: store.table_names())
        with pytest.raises(StoreError, match="busy with another operation"):
            ps.checkpoint()
    finally:
        release.set()
        th.join(timeout=5.0)
    assert not th.is_alive()
    assert waited == [True]
    assert ps.call(lambda store: store.table_names()) == []
    with ps.job() as ev:
        assert not ev.is_set()
    assert ps.shutdown(timeout=5.0) is True


# ---- N4: a failed replace leaves the old target and its WAL alone ----------


def test_n4_replace_failure_keeps_old_target_and_wal(tmp_path, monkeypatch):
    ps = _store_with_rows(tmp_path, "n4_src.npa.data", rows=50)
    try:
        tgt = str(tmp_path / "n4_dst.npa.data")
        ps.copy_to(tgt)
        with open(tgt, "rb") as f:
            old_bytes = f.read()
        with open(tgt + ".wal", "wb") as f:
            f.write(b"PRECIOUS-WAL")

        def bad_replace(src, dst):
            raise OSError("replace failed")

        monkeypatch.setattr(os, "replace", bad_replace)
        with pytest.raises(OSError, match="replace failed"):
            ps.copy_to(tgt, overwrite=True)
        monkeypatch.undo()

        with open(tgt, "rb") as f:
            assert f.read() == old_bytes
        with open(tgt + ".wal", "rb") as f:
            assert f.read() == b"PRECIOUS-WAL"
        assert _tmp_leftovers(tmp_path) == []
    finally:
        ps.close()


def test_n4_stale_wal_removed_after_successful_replace(tmp_path, monkeypatch):
    ps = _store_with_rows(tmp_path, "n4b_src.npa.data", rows=50)
    try:
        tgt = str(tmp_path / "n4b_dst.npa.data")
        ps.copy_to(tgt)
        wal = tgt + ".wal"
        with open(wal, "wb") as f:
            f.write(b"STALE")
        seen = []
        real_replace = os.replace

        def spy_replace(src, dst):
            seen.append(os.path.exists(wal))  # WAL must still be there at replace time
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", spy_replace)
        ps.copy_to(tgt, overwrite=True)
        assert seen == [True]
        assert not os.path.exists(wal)
    finally:
        ps.close()


# ---- N5: target lock probe runs before the copy; probe errors are reported -


def test_n5_lock_probe_runs_before_copy(tmp_path):
    ps = _store_with_rows(tmp_path, "n5_src.npa.data", rows=50)
    other = ProjectStore.open(str(tmp_path / "n5_other.npa.data"))
    try:
        calls = []
        with pytest.raises(StoreError, match=r"The data file is in use by another process: n5_other\.npa\.data\."):
            ps.copy_to(other.path, overwrite=True, progress=lambda c, t: calls.append(c))
        assert calls == []
        assert _tmp_leftovers(tmp_path) == []
        assert os.path.exists(other.path)
    finally:
        other.close()
        ps.close()


def test_n5_stale_unlocked_lock_file_does_not_block_copy(tmp_path):
    ps = _store_with_rows(tmp_path, "n5s_src.npa.data", rows=50)
    try:
        tgt = str(tmp_path / "n5s_dst.npa.data")
        with open(tgt + ".lock", "wb") as f:
            f.write(b"")
        ps.copy_to(tgt)
        assert os.path.exists(tgt)
    finally:
        ps.close()


def test_n5_probe_open_error_is_not_reported_as_in_use(tmp_path, monkeypatch):
    ps = _store_with_rows(tmp_path, "n5o_src.npa.data", rows=50)
    try:
        tgt = str(tmp_path / "n5o_dst.npa.data")
        with open(tgt + ".lock", "wb") as f:
            f.write(b"")
        real_open = os.open

        def fake_open(path, *args, **kwargs):
            if str(path) == tgt + ".lock":
                raise PermissionError(errno.EACCES, "Permission denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(os, "open", fake_open)
        calls = []
        with pytest.raises(StoreError) as exc_info:
            ps.copy_to(tgt, progress=lambda c, t: calls.append(c))
        monkeypatch.undo()
        msg = str(exc_info.value)
        assert msg.startswith("Cannot check whether the data file is in use: ")
        assert "Permission denied" in msg
        assert "in use by another process" not in msg
        assert calls == []
        assert not os.path.exists(tgt)
    finally:
        ps.close()


def test_n5_probe_flock_error_is_not_reported_as_in_use(tmp_path, monkeypatch):
    ps = _store_with_rows(tmp_path, "n5f_src.npa.data", rows=50)
    try:
        tgt = str(tmp_path / "n5f_dst.npa.data")
        with open(tgt + ".lock", "wb") as f:
            f.write(b"")

        def bad_flock(fd, op):
            raise OSError(errno.EBADF, "Bad file descriptor")

        monkeypatch.setattr(session_module.fcntl, "flock", bad_flock)
        with pytest.raises(StoreError) as exc_info:
            ps.copy_to(tgt)
        monkeypatch.undo()
        assert str(exc_info.value).startswith("Cannot check whether the data file is in use: ")
        assert "in use by another process" not in str(exc_info.value)
    finally:
        ps.close()


def test_n5_discard_copy_refuses_file_locked_by_another_store(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "n5d_src.npa.data"))
    other = ProjectStore.open(str(tmp_path / "n5d_other.npa.data"))
    try:
        with pytest.raises(StoreError, match=r"The data file is in use: n5d_other\.npa\.data\."):
            ps.discard_copy(other.path)
        assert os.path.exists(other.path)
        assert os.path.exists(other.path + ".lock")
        assert other.store.table_names() == []
    finally:
        other.close()
        ps.close()


def test_n5_discard_copy_refuses_file_with_raw_flock_held(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "n5r_src.npa.data"))
    target = str(tmp_path / "n5r_target.npa.data")
    with open(target, "wb") as f:
        f.write(b"data")
    fd = os.open(target + ".lock", os.O_RDWR | os.O_CREAT, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(StoreError, match="The data file is in use: n5r_target.npa.data."):
            ps.discard_copy(target)
        assert os.path.exists(target)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    ps.discard_copy(target)  # lock released: now it is removed
    assert not os.path.exists(target)
    ps.close()


def test_n5_discard_copy_probe_error_is_reported(tmp_path, monkeypatch):
    ps = ProjectStore.open(str(tmp_path / "n5e_src.npa.data"))
    try:
        target = str(tmp_path / "n5e_target.npa.data")
        with open(target, "wb") as f:
            f.write(b"data")
        with open(target + ".lock", "wb") as f:
            f.write(b"")
        real_open = os.open

        def fake_open(path, *args, **kwargs):
            if str(path) == target + ".lock":
                raise PermissionError(errno.EACCES, "Permission denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(os, "open", fake_open)
        with pytest.raises(StoreError, match="Cannot check whether the data file is in use"):
            ps.discard_copy(target)
        monkeypatch.undo()
        assert os.path.exists(target)
    finally:
        ps.close()


# ---- N7: rebind to a file that does not exist ------------------------------


def test_n7_rebind_to_missing_file_is_refused(tmp_path):
    ps = _store_with_rows(tmp_path, "n7_src.npa.data", rows=10)
    try:
        missing = str(tmp_path / "n7_missing.npa.data")
        with pytest.raises(StoreError) as exc_info:
            ps.rebind(missing, delete_old=False)
        assert str(exc_info.value) == "The data file does not exist: n7_missing.npa.data. Save a copy first."
        assert not os.path.exists(missing)
        assert not os.path.exists(missing + ".lock")
        assert ps.store.row_count("t") == 10
        assert ps.path == os.path.realpath(str(tmp_path / "n7_src.npa.data"))

        # A folder is not a data file either.
        folder = tmp_path / "n7_folder"
        folder.mkdir()
        with pytest.raises(StoreError, match="The data file does not exist: n7_folder"):
            ps.rebind(str(folder), delete_old=False)
        assert ps.store.row_count("t") == 10
    finally:
        ps.close()


def test_n7_unsaved_store_missing_target_keeps_files(tmp_path):
    ps = ProjectStore.open_unsaved(str(tmp_path / "n7_app"))
    try:
        old = ps.path
        with pytest.raises(StoreError, match="Save a copy first"):
            ps.rebind(str(tmp_path / "nothing.npa.data"), delete_old=True)
        assert ps.unsaved
        assert os.path.exists(old)
    finally:
        ps.close()


# ---- Mutation survivors ----------------------------------------------------


def test_rebind_same_path_unsaved_with_delete_old_keeps_file(tmp_path):
    ps = ProjectStore.open_unsaved(str(tmp_path / "same_app"))
    try:
        ps.store.create_table("t", [("a", "whole")])
        ps.store.append_rows("t", [(1,), (2,)])
        p = ps.path
        ps.rebind(p, delete_old=True)
        assert os.path.exists(p)
        assert ps.unsaved
        assert ps.store.row_count("t") == 2
        ps.store.append_rows("t", [(3,)])
        assert ps.store.row_count("t") == 3
    finally:
        ps.close()


def test_reap_stale_does_not_follow_symlinked_store_tmp_with_real_stale_child(tmp_path):
    app = tmp_path / "app_sym_a"
    app.mkdir()
    outside = tmp_path / "outside_a"
    child = outside / "u1"
    child.mkdir(parents=True)
    data = child / "unsaved.npa.data"
    data.write_text("x")
    old = time.time() - 100 * 3600
    os.utime(str(data), (old, old))
    os.utime(str(child), (old, old))
    os.symlink(str(outside), str(app / "store-tmp"))
    assert ProjectStore.reap_stale(str(app), now=time.time()) == []
    assert child.is_dir()
    assert data.exists()


def test_reap_stale_skips_symlinked_child_folder(tmp_path):
    app = tmp_path / "app_sym_b"
    st = app / "store-tmp"
    st.mkdir(parents=True)
    outside = tmp_path / "outside_b"
    outside.mkdir()
    data = outside / "unsaved.npa.data"
    data.write_text("x")
    old = time.time() - 100 * 3600
    os.utime(str(data), (old, old))
    os.utime(str(outside), (old, old))
    os.symlink(str(outside), str(st / "linked"))
    assert ProjectStore.reap_stale(str(app), now=time.time()) == []
    assert data.exists()
    assert os.path.islink(str(st / "linked"))


def test_resolve_data_file_rejects_paths_dots_and_directories(tmp_path):
    # saved_name with a separator pointing at an existing file in a subfolder
    proj = str(tmp_path / "proj_a.npa")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.npa.data").write_bytes(b"x")
    assert ProjectStore.resolve_data_file(proj, "sub/x.npa.data") is None

    # saved_name with a backslash for a file that exists with that literal name
    (tmp_path / "a\\b.npa.data").write_bytes(b"x")
    assert ProjectStore.resolve_data_file(proj, "a\\b.npa.data") is None

    # dot names
    assert ProjectStore.resolve_data_file(proj, ".") is None
    assert ProjectStore.resolve_data_file(proj, "..") is None

    # an existing DIRECTORY named like the saved name is not a data file
    (tmp_path / "other.npa.data").mkdir()
    assert ProjectStore.resolve_data_file(proj, "other.npa.data") is None

    # an existing DIRECTORY named like the beside-project data file is not one either
    proj_b = str(tmp_path / "proj_b.npa")
    (tmp_path / "proj_b.npa.data").mkdir()
    assert ProjectStore.resolve_data_file(proj_b, None) is None
    assert ProjectStore.resolve_data_file(proj_b, "") is None

    # a name starting with ".." is not a bare file name, even when the file exists
    (tmp_path / "..odd.npa.data").write_bytes(b"x")
    assert ProjectStore.resolve_data_file(proj, "..odd.npa.data") is None

    # sanity: a plain bare file name resolves
    real = tmp_path / "real.npa.data"
    real.write_bytes(b"x")
    assert ProjectStore.resolve_data_file(proj, "real.npa.data") == str(real)


def test_copy_to_fsyncs_temp_file_before_replace(tmp_path, monkeypatch):
    ps = _store_with_rows(tmp_path, "fs_src.npa.data", rows=50)
    try:
        events = []
        inodes = []
        real_fsync = os.fsync
        real_replace = os.replace

        def spy_fsync(fd):
            inodes.append(os.fstat(fd).st_ino)
            events.append("fsync")
            return real_fsync(fd)

        def spy_replace(src, dst):
            events.append("replace")
            return real_replace(src, dst)

        monkeypatch.setattr(os, "fsync", spy_fsync)
        monkeypatch.setattr(os, "replace", spy_replace)
        tgt = str(tmp_path / "fs_dst.npa.data")
        ps.copy_to(tgt)
        monkeypatch.undo()
        assert "fsync" in events and "replace" in events
        assert events.index("fsync") < events.index("replace")
        assert os.stat(tgt).st_ino in inodes  # the fsynced file is the one that became the target
    finally:
        ps.close()


def test_copy_to_readonly_parent_folder_checked_before_makedirs(tmp_path, monkeypatch):
    ps = _store_with_rows(tmp_path, "rop_src.npa.data", rows=50)
    try:
        with _readonly_dir(tmp_path / "rop") as ro:
            made = []
            real_makedirs = os.makedirs

            def spy_makedirs(path, *args, **kwargs):
                made.append(str(path))
                return real_makedirs(path, *args, **kwargs)

            monkeypatch.setattr(os, "makedirs", spy_makedirs)
            tgt = str(ro / "newsub" / "deeper" / "x.npa.data")
            with pytest.raises(StoreError) as exc_info:
                ps.copy_to(tgt)
            monkeypatch.undo()
            assert str(exc_info.value) == "Cannot write the data file: folder is read-only."
            assert not (ro / "newsub").exists()
            assert [m for m in made if str(ro) in m] == []
    finally:
        ps.close()


def test_copy_to_makedirs_error_is_mapped(tmp_path, monkeypatch):
    ps = _store_with_rows(tmp_path, "mk_src.npa.data", rows=50)
    try:
        target_dir = str(tmp_path / "mk_new")
        real_makedirs = os.makedirs

        def bad_makedirs(path, *args, **kwargs):
            if os.path.abspath(str(path)) == target_dir:
                raise PermissionError(errno.EACCES, "Permission denied")
            return real_makedirs(path, *args, **kwargs)

        monkeypatch.setattr(os, "makedirs", bad_makedirs)
        with pytest.raises(StoreError) as exc_info:
            ps.copy_to(os.path.join(target_dir, "x.npa.data"))
        monkeypatch.undo()
        assert str(exc_info.value) == "Cannot write the data file: folder is read-only."
        assert isinstance(exc_info.value.__cause__, PermissionError)
        assert not os.path.exists(target_dir)
    finally:
        ps.close()


def test_open_unsaved_failure_after_folder_created_removes_folder_and_spill(tmp_path, monkeypatch):
    app = str(tmp_path / "app_late_fail")
    seen = {}

    def late_failure(path, *args, **kwargs):
        os.makedirs(os.path.dirname(path), exist_ok=True)  # DuckStore creates the folder first
        seen["folder"] = os.path.dirname(path)
        seen["spill"] = kwargs["temp_directory"]
        seen["spill_existed"] = os.path.isdir(kwargs["temp_directory"])
        raise RuntimeError("late failure")

    monkeypatch.setattr(session_module, "DuckStore", late_failure)
    with pytest.raises(RuntimeError, match="late failure"):
        ProjectStore.open_unsaved(app)
    assert seen["spill_existed"]
    assert not os.path.exists(seen["folder"])
    assert not os.path.exists(seen["spill"])
    assert os.listdir(os.path.join(app, "store-tmp")) == []


def test_shutdown_removes_spill_dir_when_store_close_raises(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "sd_boom.npa.data"))
    spill = ps._spill_dir
    assert spill is not None and os.path.isdir(spill)
    real_close = ps.store.close

    def boom():
        raise RuntimeError("close boom")

    ps.store.close = boom
    try:
        with pytest.raises(RuntimeError, match="close boom"):
            ps.shutdown(timeout=1.0)
        assert not os.path.exists(spill)
    finally:
        real_close()


def test_rebind_restore_after_failed_open_uses_same_settings(tmp_path, monkeypatch):
    p = str(tmp_path / "rs_src.npa.data")
    ps = ProjectStore.open(p, memory_limit="512MB", threads=2)
    try:
        ps.store.create_table("t", [("a", "whole")])
        ps.store.append_rows("t", [(1,), (2,), (3,)])
        before = ps.store.execute("select current_setting('memory_limit'), current_setting('threads')")[0]
        tgt = str(tmp_path / "rs_dst.npa.data")
        ps.copy_to(tgt)

        real_duckstore = session_module.DuckStore
        calls = []

        def flaky(path, *args, **kwargs):
            calls.append((path, dict(kwargs)))
            if len(calls) == 1:
                raise StoreError("simulated open failure")
            return real_duckstore(path, *args, **kwargs)

        monkeypatch.setattr(session_module, "DuckStore", flaky)
        with pytest.raises(StoreError, match="simulated open failure"):
            ps.rebind(tgt, delete_old=False)
        monkeypatch.undo()

        assert len(calls) == 2
        assert calls[0][0] == tgt or os.path.realpath(calls[0][0]) == os.path.realpath(tgt)
        assert calls[1][0] == os.path.realpath(p)
        assert calls[1][1]["memory_limit"] == "512MB"
        assert calls[1][1]["threads"] == 2
        assert calls[1][1]["temp_directory"] == ps._spill_dir
        assert ps.path == os.path.realpath(p)
        assert ps.store.row_count("t") == 3
        after = ps.store.execute("select current_setting('memory_limit'), current_setting('threads')")[0]
        assert tuple(after) == tuple(before)
    finally:
        ps.close()


def test_exclusive_operations_refused_while_shutting_down(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "ex_shut.npa.data"))
    entered = threading.Event()
    go = threading.Event()

    def slow_cancel():
        entered.set()
        go.wait(timeout=5.0)

    ps.request_cancel = slow_cancel
    th = threading.Thread(target=lambda: ps.shutdown(timeout=5.0))
    th.start()
    try:
        assert entered.wait(timeout=5.0)
        with pytest.raises(StoreError, match="The store is shutting down"):
            ps.validate_table("t", ["a"], ["whole"], 0)
        with pytest.raises(StoreError, match="The store is shutting down"):
            ps.drop_unreferenced([])
        with pytest.raises(StoreError, match="The store is shutting down"):
            ps.copy_to(str(tmp_path / "ex_shut_dst.npa.data"))
        with pytest.raises(StoreError, match="The store is shutting down"):
            ps.rebind(str(tmp_path / "ex_shut_dst.npa.data"), delete_old=False)
        with pytest.raises(StoreError, match="The store is shutting down"):
            ps.call(lambda store: 1)
        with pytest.raises(StoreError, match="The store is shutting down"):
            ps.checkpoint()
    finally:
        go.set()
        th.join(timeout=5.0)
    assert not th.is_alive()
    ps.close()


def test_exclusive_exit_wakes_shutdown_waiter(tmp_path, monkeypatch):
    ps = ProjectStore.open(str(tmp_path / "ex_wake.npa.data"))
    ps.store.create_table("t", [("a", "whole")])
    ps.store.append_rows("t", [(1,)])
    started = threading.Event()
    release = threading.Event()
    real_row_count = ps.store.row_count

    def slow_row_count(table):
        started.set()
        release.wait(timeout=10.0)
        return real_row_count(table)

    monkeypatch.setattr(ps.store, "row_count", slow_row_count)
    errors = []

    def validate():
        try:
            ps.validate_table("t", ["a"], ["whole"], 1)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    result = []
    op_thread = threading.Thread(target=validate)
    sd_thread = threading.Thread(target=lambda: result.append(ps.shutdown(timeout=5.0)))
    op_thread.start()
    try:
        assert started.wait(timeout=5.0)
        sd_thread.start()
        deadline = time.time() + 5.0
        while not ps._shutting_down and time.time() < deadline:
            time.sleep(0.005)
        assert ps._shutting_down
        t0 = time.time()
        release.set()
        op_thread.join(timeout=5.0)
        sd_thread.join(timeout=5.0)
        elapsed = time.time() - t0
    finally:
        release.set()
    assert errors == []
    assert result == [True]
    assert elapsed < 1.0


def test_discard_copy_refuses_case_alias_when_live_file_is_gone(tmp_path):
    d = tmp_path / "Dd2"
    d.mkdir()
    ps = ProjectStore.open(str(d / "Live.npa.data"))
    try:
        os.remove(ps.path)  # live file no longer exists, so only the name comparison can refuse
        alias = str(d / "LIVE.NPA.DATA")
        with pytest.raises(StoreError, match="Cannot discard the current live store data file"):
            ps.discard_copy(alias)
    finally:
        ps.close()


def test_drop_unreferenced_keep_is_case_insensitive_for_uppercase_tables(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "drop_case.npa.data"))
    try:
        ps.store.create_table("SRC_X_G0", [("a", "whole")])
        ps.store.create_table("src_y_g0", [("a", "whole")])
        # upper-case table kept by a lower-case keep entry; lower-case table kept by an upper-case one
        assert ps.drop_unreferenced(keep=["src_x_g0", "SRC_Y_G0"]) == []
        assert len(ps.store.table_names()) == 2
        assert ps.drop_unreferenced(keep=["SRC_X_G0"]) == ["src_y_g0"]
        assert len(ps.store.table_names()) == 1
        dropped = ps.drop_unreferenced(keep=[])
        assert [d.lower() for d in dropped] == ["src_x_g0"]
        assert ps.store.table_names() == []
    finally:
        ps.close()


def test_validate_table_column_count_differences_name_first_difference(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "val_count.npa.data"))
    try:
        ps.store.create_table("t1", [("a", "whole"), ("b", "text")])
        ps.store.append_rows("t1", [(1, "x")])
        # expected has an EXTRA column the store does not have
        with pytest.raises(StoreError) as extra:
            ps.validate_table("t1", ["a", "b", "c"], ["whole", "text", "whole"], 1)
        assert "Columns differ for table 't1'" in str(extra.value)
        assert "expected 3 columns, found 2 columns" in str(extra.value)
        assert "position 2" in str(extra.value)
        assert "'c'" in str(extra.value)
        # expected is MISSING a column the store has
        with pytest.raises(StoreError) as missing:
            ps.validate_table("t1", ["a"], ["whole"], 1)
        assert "Columns differ for table 't1'" in str(missing.value)
        assert "expected 1 columns, found 2 columns" in str(missing.value)
        assert "position 1" in str(missing.value)
        assert "'b'" in str(missing.value)
        # a name difference before the count difference is the first difference
        with pytest.raises(StoreError) as first:
            ps.validate_table("t1", ["z"], ["whole"], 1)
        assert "position 0" in str(first.value)
        assert "'z'" in str(first.value) and "'a'" in str(first.value)
    finally:
        ps.close()


def test_job_and_busy_behavior_bounded_waits(tmp_path):
    """Same checks as test_job_and_busy_behavior, but no wait or join can hang the suite."""
    ps = ProjectStore.open(str(tmp_path / "job_bounded.npa.data"))
    job_entered = threading.Event()
    release_job = threading.Event()
    outcome = {}

    def worker():
        with ps.job() as cancel_ev:
            outcome["cancel_clear"] = not cancel_ev.is_set()
            job_entered.set()
            outcome["release_in_time"] = release_job.wait(timeout=10.0)

    th = threading.Thread(target=worker)
    th.start()
    try:
        assert job_entered.wait(timeout=5.0), "job did not start in time"
        assert ps.busy
        with pytest.raises(StoreError, match="busy with another operation"):
            with ps.job():
                pass
        with pytest.raises(StoreError, match="busy with another operation"):
            ps.call(lambda store: store.table_names())
        with pytest.raises(StoreError, match="busy with another operation"):
            ps.checkpoint()
        assert ps.store.table_names() == []
    finally:
        release_job.set()
        th.join(timeout=5.0)
    assert not th.is_alive(), "worker thread did not finish in time"
    assert outcome == {"cancel_clear": True, "release_in_time": True}
    assert not ps.busy
    with pytest.raises(RuntimeError):
        with ps.job():
            assert ps.busy
            raise RuntimeError("failure")
    assert not ps.busy
    ps.close()


# ---- Re-review 4: lock probe before replace, refused copy, case alias, shutdown overlap ----


def test_copy_to_refuses_target_opened_by_another_store_during_the_copy(tmp_path, monkeypatch):
    ps = _store_with_rows(tmp_path, "f1_src.npa.data")
    tgt = str(tmp_path / "f1_dst.npa.data")
    old = ProjectStore.open(tgt)
    old.store.create_table("keep", [("a", "whole")])
    old.store.append_rows("keep", [(1,), (2,), (3,)])
    old.close()
    old_size = os.path.getsize(tgt)
    monkeypatch.setattr(session_module, "_COPY_CHUNK", 4096)
    holder = {}
    calls = [0]

    def on_progress(copied, total):
        calls[0] += 1
        if calls[0] == 2:
            holder["other"] = ProjectStore.open(tgt)

    try:
        with pytest.raises(StoreError, match=r"in use.*f1_dst\.npa\.data"):
            ps.copy_to(tgt, overwrite=True, progress=on_progress)
        other = holder["other"]
        assert calls[0] > 2  # the copy ran on after the other store opened the target
        assert _tmp_leftovers(tmp_path) == []
        assert os.path.getsize(tgt) == old_size
        assert other.store.row_count("keep") == 3
        other.store.append_rows("keep", [(4,)])
        assert other.store.row_count("keep") == 4
        other.close()
    finally:
        if "other" in holder:
            holder["other"].close()
        ps.close()


def test_copy_to_refused_by_existing_target_never_copies(tmp_path):
    ps = _store_with_rows(tmp_path, "f2_src.npa.data", rows=50)
    tgt = tmp_path / "f2_dst.npa.data"
    tgt.write_bytes(b"existing target")
    calls = []
    try:
        with pytest.raises(StoreError, match=r"already exists: f2_dst\.npa\.data"):
            ps.copy_to(str(tgt), overwrite=False, progress=lambda c, t: calls.append(c))
        assert calls == []
        assert tgt.read_bytes() == b"existing target"
        assert _tmp_leftovers(tmp_path) == []
    finally:
        ps.close()


def test_copy_to_refuses_case_alias_of_a_live_file_that_no_longer_exists(tmp_path):
    d = tmp_path / "F3"
    d.mkdir()
    ps = ProjectStore.open(str(d / "Live.npa.data"))
    try:
        os.remove(ps.path)  # target spelling cannot exist either, so only the name comparison can refuse
        alias = str(d / "LIVE.NPA.DATA")
        calls = []
        with pytest.raises(StoreError, match="Cannot copy the data file onto itself"):
            ps.copy_to(alias, overwrite=True, progress=lambda c, t: calls.append(c))
        assert calls == []
        assert _tmp_leftovers(d) == []
    finally:
        ps.close()


def test_overlapping_shutdowns_do_not_reopen_the_store_while_one_still_waits(tmp_path):
    ps = ProjectStore.open(str(tmp_path / "f4.npa.data"))
    started = threading.Event()
    release = threading.Event()
    results = {}

    def worker():
        with ps.job():
            started.set()
            release.wait(timeout=10.0)

    def slow_shutdown():
        results["slow"] = ps.shutdown(timeout=8.0)

    th = threading.Thread(target=worker)
    slow = threading.Thread(target=slow_shutdown)
    th.start()
    try:
        assert started.wait(timeout=5.0)
        slow.start()
        deadline = time.time() + 5.0
        while time.time() < deadline and not ps._shutting_down:
            time.sleep(0.01)
        assert ps._shutting_down
        time.sleep(0.1)  # let the slow shutdown reach its wait
        assert ps.shutdown(timeout=0.2) is False
        # The slow shutdown is still waiting: the store must still refuse new work as "shutting down".
        with pytest.raises(StoreError, match="shutting down"):
            ps.call(lambda store: store.table_names())
        with pytest.raises(StoreError, match="shutting down"):
            ps.checkpoint()
    finally:
        release.set()
        th.join(timeout=5.0)
        slow.join(timeout=10.0)
    assert not th.is_alive() and not slow.is_alive()
    assert results == {"slow": True}


def test_store_busy_error_subclass_raised_and_caught(tmp_path):
    """Verify that StoreBusyError is raised at all busy sites and caught by except StoreError."""
    from analytics_studio.store.base import StoreBusyError, StoreError
    assert issubclass(StoreBusyError, StoreError)

    data_file = str(tmp_path / "busy_test.npa.data")
    ps = ProjectStore.open(data_file)
    with ps.job():
        # 1. second job() raises StoreBusyError
        with pytest.raises(StoreBusyError, match="busy with another operation"):
            with ps.job():
                pass

        # 2. call() raises StoreBusyError
        with pytest.raises(StoreBusyError, match="busy with another operation"):
            ps.call(lambda store: store.table_names())

        # 3. checkpoint() raises StoreBusyError
        with pytest.raises(StoreBusyError, match="busy with another operation"):
            ps.checkpoint()

        # 4. close() raises StoreBusyError
        with pytest.raises(StoreBusyError, match="busy with another operation"):
            ps.close()

        # 5. verify except StoreError also catches it
        caught = False
        try:
            ps.checkpoint()
        except StoreError as e:
            caught = True
            assert isinstance(e, StoreBusyError)
        assert caught is True

    # 5th site: _exclusive internal context manager
    with ps.job():
        with pytest.raises(StoreBusyError, match="busy with another operation"):
            with ps._exclusive():
                pass

    ps.close()
