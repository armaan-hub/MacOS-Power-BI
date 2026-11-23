"""ProjectStore: per-project session object for large-data DuckDB store.

One object per project. It owns one DuckStore, a busy flag, and a cancel event.
Qt-free: contains no PySide imports.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager
from typing import (
    Callable,
    Collection,
    Iterator,
    Optional,
    Sequence,
    TypeVar,
)

import duckdb

from .base import StoreError
from .duck_store import DuckStore

try:
    from .csv_import import ImportCancelledError
except ImportError:
    class ImportCancelledError(StoreError):  # type: ignore[no-redef]
        """Fallback cancellation error if csv_import cannot be imported."""
        pass

T = TypeVar("T")

_COPY_CHUNK = 8 * 1024 * 1024  # 8 MiB chunks for copy_to


class ProjectStore:
    """Manages the DuckStore lifecycle and operations for a single project."""

    DATA_SUFFIX = ".npa.data"

    def __init__(
        self,
        store: DuckStore,
        *,
        unsaved: bool,
        spill_dir: Optional[str] = None,
    ) -> None:
        self._store: Optional[DuckStore] = store
        self._unsaved = bool(unsaved)
        self._spill_dir = spill_dir
        self._cancel_event = threading.Event()
        self._busy = False
        self._lock = threading.Condition(threading.Lock())
        self._closed = False

    @property
    def store(self) -> DuckStore:
        if self._store is None:
            raise StoreError("The store is closed.")
        return self._store

    @property
    def path(self) -> str:
        if self._store is None:
            raise StoreError("The store is closed.")
        return self._store.path

    @property
    def unsaved(self) -> bool:
        return self._unsaved

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel_event

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    @classmethod
    def open(
        cls,
        data_path: str,
        *,
        memory_limit: str = "2GB",
        threads: Optional[int] = None,
    ) -> "ProjectStore":
        """Open an existing or new data file next to a saved project."""
        folder = os.path.dirname(os.path.abspath(data_path))
        if os.path.exists(folder):
            if not os.access(folder, os.W_OK):
                raise StoreError(
                    "Cannot create the data file next to the project (folder is read-only). "
                    "Use Save As in a writable folder."
                )
        else:
            parent = os.path.dirname(folder)
            if os.path.exists(parent) and not os.access(parent, os.W_OK):
                raise StoreError(
                    "Cannot create the data file next to the project (folder is read-only). "
                    "Use Save As in a writable folder."
                )

        spill_id = uuid.uuid4().hex
        spill_dir = os.path.join(tempfile.gettempdir(), "analytics-studio-spill", spill_id)
        try:
            os.makedirs(spill_dir, exist_ok=True)
        except (OSError, PermissionError) as exc:
            raise StoreError(
                "Cannot create the data file next to the project (folder is read-only). "
                "Use Save As in a writable folder."
            ) from exc

        try:
            store = DuckStore(
                data_path,
                memory_limit=memory_limit,
                threads=threads,
                temp_directory=spill_dir,
            )
        except (PermissionError, OSError) as exc:
            if isinstance(exc, PermissionError) or exc.errno in (13, 30):  # EACCES, EROFS
                try:
                    shutil.rmtree(spill_dir, ignore_errors=True)
                except Exception:
                    pass
                raise StoreError(
                    "Cannot create the data file next to the project (folder is read-only). "
                    "Use Save As in a writable folder."
                ) from exc
            try:
                shutil.rmtree(spill_dir, ignore_errors=True)
            except Exception:
                pass
            raise
        except Exception:
            try:
                shutil.rmtree(spill_dir, ignore_errors=True)
            except Exception:
                pass
            raise

        return cls(store, unsaved=False, spill_dir=spill_dir)

    @classmethod
    def open_unsaved(
        cls,
        app_data_dir: str,
        *,
        memory_limit: str = "2GB",
        threads: Optional[int] = None,
    ) -> "ProjectStore":
        """Open a new data file for an unsaved project under <app_data_dir>/store-tmp/<uuid>/unsaved.npa.data."""
        run_id = uuid.uuid4().hex
        data_path = os.path.join(app_data_dir, "store-tmp", run_id, "unsaved.npa.data")
        spill_id = uuid.uuid4().hex
        spill_dir = os.path.join(tempfile.gettempdir(), "analytics-studio-spill", spill_id)
        os.makedirs(spill_dir, exist_ok=True)
        try:
            store = DuckStore(
                data_path,
                memory_limit=memory_limit,
                threads=threads,
                temp_directory=spill_dir,
            )
        except Exception:
            try:
                shutil.rmtree(spill_dir, ignore_errors=True)
            except Exception:
                pass
            raise
        return cls(store, unsaved=True, spill_dir=spill_dir)

    @staticmethod
    def reap_stale(
        app_data_dir: str,
        max_age_hours: float = 24.0,
        now: Optional[float] = None,
    ) -> list[str]:
        """Remove store-tmp/<uuid> folders older than max_age_hours whose lock is not held."""
        store_tmp_dir = os.path.join(app_data_dir, "store-tmp")
        if not os.path.isdir(store_tmp_dir):
            return []

        import time
        current_time = now if now is not None else time.time()
        max_age_seconds = max_age_hours * 3600.0

        allowed_files = {"unsaved.npa.data", "unsaved.npa.data.lock", "unsaved.npa.data.wal"}
        removed_folders: list[str] = []

        try:
            entries = os.listdir(store_tmp_dir)
        except OSError:
            return []

        for entry in entries:
            folder_path = os.path.join(store_tmp_dir, entry)
            # Only direct child directories of store-tmp
            if not os.path.isdir(folder_path):
                continue

            try:
                files = os.listdir(folder_path)
            except OSError:
                continue

            if not files:
                # Empty directory? Check folder mtime
                try:
                    mtime = os.path.getmtime(folder_path)
                    if (current_time - mtime) >= max_age_seconds:
                        os.rmdir(folder_path)
                        removed_folders.append(folder_path)
                except OSError:
                    pass
                continue

            # Must contain ONLY allowed files
            unexpected = False
            newest_mtime = 0.0
            for f in files:
                if f not in allowed_files:
                    unexpected = True
                    break
                fpath = os.path.join(folder_path, f)
                try:
                    f_mtime = os.path.getmtime(fpath)
                    if f_mtime > newest_mtime:
                        newest_mtime = f_mtime
                except OSError:
                    pass

            if unexpected:
                continue

            if (current_time - newest_mtime) < max_age_seconds:
                continue

            # Check if .lock file is held
            lock_file = os.path.join(folder_path, "unsaved.npa.data.lock")
            lock_held = False
            if os.path.exists(lock_file):
                fd = None
                try:
                    fd = os.open(lock_file, os.O_RDWR)
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except (BlockingIOError, OSError):
                    lock_held = True
                finally:
                    if fd is not None:
                        try:
                            os.close(fd)
                        except OSError:
                            pass

            if lock_held:
                continue

            # Safe to remove
            try:
                shutil.rmtree(folder_path)
                removed_folders.append(folder_path)
            except OSError:
                pass

        return removed_folders

    @staticmethod
    def data_file_for(project_path: str) -> str:
        """Return '<dir>/<stem>.npa.data' for '<dir>/<stem>.npa'."""
        d = os.path.dirname(project_path)
        base = os.path.basename(project_path)
        if base.endswith(".npa"):
            stem = base[:-4]
        else:
            stem, _ = os.path.splitext(base)
        return os.path.join(d, stem + ProjectStore.DATA_SUFFIX)

    @staticmethod
    def resolve_data_file(project_path: str, saved_name: Optional[str]) -> Optional[str]:
        """Resolve the data file path for a project.

        1) data_file_for(project_path) if it exists;
        2) join(dirname(project_path), saved_name) if saved_name is a BARE filename (no path separator, no ..) and exists;
        else None.
        """
        candidate1 = ProjectStore.data_file_for(project_path)
        if os.path.exists(candidate1):
            return candidate1

        if saved_name:
            if "/" not in saved_name and "\\" not in saved_name and saved_name != ".." and not saved_name.startswith(".."):
                candidate2 = os.path.join(os.path.dirname(project_path), saved_name)
                if os.path.exists(candidate2):
                    return candidate2

        return None

    @staticmethod
    def table_name(source_id: str, generation: int) -> str:
        """Return 'src_<id>_g<n>' where id is lower-cased ASCII with [^a-z0-9_] replaced by '_'."""
        if not isinstance(source_id, str) or not source_id:
            raise StoreError("source_id must be a non-empty string.")
        if not isinstance(generation, int) or generation < 0:
            raise StoreError("generation must be a non-negative integer.")

        sanitized_id = "".join(
            c if ("a" <= c <= "z" or "0" <= c <= "9" or c == "_") else "_"
            for c in source_id.lower()
        )
        if not sanitized_id:
            raise StoreError("source_id cannot be empty.")

        t_name = f"src_{sanitized_id}_g{generation}"
        return t_name

    @staticmethod
    def duckdb_version() -> str:
        return str(duckdb.__version__)

    @contextmanager
    def job(self) -> Iterator[threading.Event]:
        """Marks busy, clears cancel_event, yields cancel_event; unmarks in finally.

        A second job() while busy raises StoreError("The store is busy with another operation.").
        """
        with self._lock:
            if self._closed:
                raise StoreError("The store is closed.")
            if self._busy:
                raise StoreError("The store is busy with another operation.")
            self._busy = True
            self._cancel_event.clear()

        try:
            yield self._cancel_event
        finally:
            with self._lock:
                self._busy = False
                self._lock.notify_all()

    def call(self, fn: Callable[[DuckStore], T]) -> T:
        """Call fn(self.store) on UI thread; raises busy StoreError if busy."""
        with self._lock:
            if self._closed or self._store is None:
                raise StoreError("The store is closed.")
            if self._busy:
                raise StoreError("The store is busy with another operation.")
        return fn(self._store)

    def checkpoint(self) -> None:
        """Checkpoint store; raises busy StoreError if busy."""
        with self._lock:
            if self._closed or self._store is None:
                raise StoreError("The store is closed.")
            if self._busy:
                raise StoreError("The store is busy with another operation.")
        self._store.checkpoint()

    def validate_table(
        self,
        table: str,
        headers: Sequence[str],
        physical_types: Sequence[str],
        row_count: int,
    ) -> None:
        """Validates that table exists, columns match, and row count matches."""
        with self._lock:
            if self._closed or self._store is None:
                raise StoreError("The store is closed.")
            if self._busy:
                raise StoreError("The store is busy with another operation.")
            store = self._store

        if not store.has_table(table):
            raise StoreError(f"Table '{table}' is missing from the store.")

        actual_cols = store.columns(table)  # list of (name, type) without __rn
        expected_cols = list(zip(headers, physical_types))

        if len(actual_cols) != len(expected_cols):
            raise StoreError(
                f"Columns differ for table '{table}': expected {len(expected_cols)} columns, "
                f"found {len(actual_cols)} columns."
            )

        for i, (act, exp) in enumerate(zip(actual_cols, expected_cols)):
            if act[0] != exp[0] or act[1] != exp[1]:
                raise StoreError(
                    f"Columns differ for table '{table}' at position {i}: "
                    f"expected ('{exp[0]}', '{exp[1]}'), found ('{act[0]}', '{act[1]}')."
                )

        actual_row_count = store.row_count(table)
        if actual_row_count != row_count:
            raise StoreError(
                f"Row count differs for table '{table}': expected {row_count}, found {actual_row_count}."
            )

    def drop_unreferenced(self, keep: Collection[str]) -> list[str]:
        """Drop tables whose name starts with 'src_' and not in keep (ASCII case-insensitive)."""
        with self._lock:
            if self._closed or self._store is None:
                raise StoreError("The store is closed.")
            if self._busy:
                raise StoreError("The store is busy with another operation.")
            store = self._store

        keep_lower = {k.lower() for k in keep}
        all_tables = store.table_names()
        dropped: list[str] = []

        for tbl in all_tables:
            if tbl.lower().startswith("src_") and tbl.lower() not in keep_lower:
                store.drop_table(tbl)
                dropped.append(tbl)

        return dropped

    def copy_to(
        self,
        target_data_path: str,
        *,
        overwrite: bool = False,
        progress: Optional[Callable[[int, int], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> str:
        """Atomically copy the store data file to target_data_path."""
        with self._lock:
            if self._closed or self._store is None:
                raise StoreError("The store is closed.")
            if self._busy:
                raise StoreError("The store is busy with another operation.")

        source_path = self.path
        if not overwrite and os.path.exists(target_data_path):
            raise StoreError(f"The data file already exists: {os.path.basename(target_data_path)}.")

        # 1. Checkpoint
        self.checkpoint()

        # 2. Free space check
        source_size = os.path.getsize(source_path)
        required_space = int(source_size * 1.1) + 64 * 1024 * 1024
        target_dir = os.path.dirname(os.path.abspath(target_data_path))
        os.makedirs(target_dir, exist_ok=True)
        usage = shutil.disk_usage(target_dir)
        if usage.free < required_space:
            raise StoreError(
                f"Not enough free disk space for the data file: need {required_space}, have {usage.free}."
            )

        # 3. Copy in chunks to tmp file
        tmp_id = uuid.uuid4().hex
        tmp_path = f"{target_data_path}.tmp-{tmp_id}"

        def _cleanup_tmp() -> None:
            for p in [tmp_path, tmp_path + ".lock", tmp_path + ".wal"]:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass

        try:
            copied = 0
            with open(source_path, "rb") as fsrc, open(tmp_path, "wb") as fdst:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise ImportCancelledError("Copy canceled.")
                    chunk = fsrc.read(_COPY_CHUNK)
                    if not chunk:
                        break
                    fdst.write(chunk)
                    copied += len(chunk)
                    if progress is not None:
                        progress(copied, source_size)

            if cancel_event is not None and cancel_event.is_set():
                raise ImportCancelledError("Copy canceled.")

            # 4. Verify: open temp copy with DuckStore, compare tables and row counts
            temp_store: Optional[DuckStore] = None
            try:
                temp_store = DuckStore(tmp_path)
                src_tables = sorted(self._store.table_names())
                dst_tables = sorted(temp_store.table_names())
                if src_tables != dst_tables:
                    raise StoreError("Verification failed: tables do not match.")
                for tbl in src_tables:
                    if self._store.row_count(tbl) != temp_store.row_count(tbl):
                        raise StoreError(f"Verification failed: row count mismatch for table '{tbl}'.")
            finally:
                if temp_store is not None:
                    try:
                        temp_store.close()
                    except Exception:
                        pass
                for p in [tmp_path + ".lock", tmp_path + ".wal"]:
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except OSError:
                        pass

            # Final check before replace
            if not overwrite and os.path.exists(target_data_path):
                raise StoreError(f"The data file already exists: {os.path.basename(target_data_path)}.")

            os.replace(tmp_path, target_data_path)
            return os.path.realpath(target_data_path)
        except Exception:
            _cleanup_tmp()
            raise

    def rebind(self, target_data_path: str, *, delete_old: bool) -> None:
        """Switch the session to target_data_path; removes old files if delete_old and unsaved."""
        with self._lock:
            if self._closed or self._store is None:
                raise StoreError("The store is closed.")
            if self._busy:
                raise StoreError("The store is busy with another operation.")

        old_store = self._store
        old_path = old_store.path
        was_unsaved = self._unsaved
        old_spill_dir = self._spill_dir

        old_store.close()

        new_store: Optional[DuckStore] = None
        try:
            new_store = DuckStore(target_data_path, temp_directory=old_spill_dir)
        except Exception:
            # Reopen old path and restore
            try:
                self._store = DuckStore(old_path, temp_directory=old_spill_dir)
            except Exception:
                pass
            raise

        self._store = new_store
        self._unsaved = False

        if delete_old and was_unsaved:
            for p in [old_path, old_path + ".wal", old_path + ".lock"]:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass

    def discard_copy(self, target_data_path: str) -> None:
        """Remove a copy made by copy_to when the JSON write failed."""
        real_target = os.path.realpath(target_data_path)
        if self._store is not None and real_target == self.path:
            raise StoreError("Cannot discard the current live store data file.")

        for p in [target_data_path, target_data_path + ".wal", target_data_path + ".lock"]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

    def request_cancel(self) -> None:
        """Signal cancel event."""
        self._cancel_event.set()

    def shutdown(self, timeout: float = 15.0) -> bool:
        """App quit: request cancel, wait up to timeout for job to end, close and remove spill dir."""
        self.request_cancel()
        with self._lock:
            if self._closed:
                return True
            if self._busy:
                ended = self._lock.wait_for(lambda: not self._busy, timeout=timeout)
                if not ended or self._busy:
                    return False

            self._closed = True
            store = self._store
            self._store = None
            spill_dir = self._spill_dir
            self._spill_dir = None

        if store is not None:
            try:
                store.close()
            except Exception:
                pass

        if spill_dir is not None:
            try:
                shutil.rmtree(spill_dir, ignore_errors=True)
            except Exception:
                pass

        return True

    def close(self) -> None:
        """Close store and remove spill directory; raises busy StoreError if busy."""
        with self._lock:
            if self._closed:
                return
            if self._busy:
                raise StoreError("The store is busy with another operation.")
            self._closed = True
            store = self._store
            self._store = None
            spill_dir = self._spill_dir
            self._spill_dir = None

        if store is not None:
            store.close()

        if spill_dir is not None:
            try:
                shutil.rmtree(spill_dir, ignore_errors=True)
            except Exception:
                pass
