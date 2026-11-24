"""StoreJob: QRunnable background worker for long-running ProjectStore operations.

Runs jobs on a QThreadPool while keeping ProjectStore's busy state and cancel_event
synchronized. Emits Qt signals for progress, result, failure, and completion.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Generic, Optional, TypeVar

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .base import StoreError
from .duck_store import DuckStore
from .session import ProjectStore

try:
    from .csv_import import FileImportError, ImportCancelledError
except ImportError:
    class FileImportError(ValueError):  # type: ignore[no-redef]
        """Fallback file import error."""
        pass

    class ImportCancelledError(StoreError):  # type: ignore[no-redef]
        """Fallback cancellation error."""
        pass

T = TypeVar("T")
logger = logging.getLogger(__name__)


class StoreJobSignals(QObject):
    """Signals emitted by StoreJob during its lifecycle."""

    progress = Signal(str, int, int)  # message, done, total (total 0 = unknown)
    finished = Signal(object)  # result of fn
    failed = Signal(str)  # user-readable message
    canceled = Signal()
    done = Signal()  # always emitted last, exactly once


class StoreJob(QRunnable, Generic[T]):
    """Background QRunnable task bound to a ProjectStore session."""

    def __init__(
        self,
        project_store: ProjectStore,
        fn: Callable[[DuckStore, threading.Event, Callable[[str, int, int], None]], T],
        *,
        title: str = "",
    ) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.project_store = project_store
        self.fn = fn
        self.title = title
        self.signals = StoreJobSignals()
        self._cm: Optional[object] = None
        self._cancel_event: Optional[threading.Event] = None
        self._lock = threading.Lock()
        self._running = False
        self._started = False

    def start(self, pool: QThreadPool) -> None:
        """UI thread entry point. Marks store busy BEFORE submitting to the thread pool."""
        with self._lock:
            self._running = True
            self._started = False
        cm = self.project_store.job()
        cancel_evt = cm.__enter__()
        self._cm = cm
        self._cancel_event = cancel_evt
        try:
            pool.start(self)
        except Exception:
            self._cm = None
            self._cancel_event = None
            with self._lock:
                self._running = False
            cm.__exit__(None, None, None)
            raise

    def cancel(self) -> None:
        """Signal cancellation to the project store if this job is currently running."""
        with self._lock:
            if not self._running:
                return
        self.project_store.request_cancel()

    def release_if_not_started(self) -> None:
        """Release the store's busy context if run() has not yet begun. Idempotent and thread-safe."""
        cm_to_exit = None
        with self._lock:
            if not self._started and self._cm is not None:
                cm_to_exit = self._cm
                self._cm = None
                self._cancel_event = None
                self._running = False
        if cm_to_exit is not None:
            try:
                cm_to_exit.__exit__(None, None, None)
            except Exception:
                logger.exception("Error exiting ProjectStore.job context in release_if_not_started")

    def run(self) -> None:
        """Worker thread entry point."""
        with self._lock:
            if self._cm is None:
                # Already released before start (e.g. via release_if_not_started)
                return
            self._started = True

        cancel_evt = self._cancel_event
        if cancel_evt is None:
            cancel_evt = self.project_store.cancel_event

        def progress_callback(message: str, done: int, total: int) -> None:
            self.signals.progress.emit(message, done, total)

        outcome_signal: Optional[Callable[[], None]] = None

        try:
            store = self.project_store.store
            result = self.fn(store, cancel_evt, progress_callback)
            outcome_signal = lambda: self.signals.finished.emit(result)
        except ImportCancelledError:
            outcome_signal = lambda: self.signals.canceled.emit()
        except (KeyboardInterrupt, SystemExit):
            outcome_signal = lambda: self.signals.failed.emit("The job was interrupted.")
        except Exception as exc:
            if cancel_evt.is_set():
                outcome_signal = lambda: self.signals.canceled.emit()
            elif isinstance(exc, (StoreError, FileImportError, ValueError)):
                msg = str(exc)
                outcome_signal = lambda: self.signals.failed.emit(msg)
            else:
                exc_type = type(exc).__name__
                msg = f"Unexpected error: {exc_type}: {exc}"
                logger.exception("Unexpected error in StoreJob %r", self.title)
                outcome_signal = lambda: self.signals.failed.emit(msg)
        finally:
            with self._lock:
                self._running = False

            cm = self._cm
            self._cm = None
            self._cancel_event = None
            if cm is not None:
                try:
                    cm.__exit__(None, None, None)
                except Exception:
                    logger.exception("Error exiting ProjectStore.job context")

            if outcome_signal is not None:
                try:
                    outcome_signal()
                except Exception:
                    logger.exception("Error emitting StoreJob outcome signal")

            try:
                self.signals.done.emit()
            except Exception:
                logger.exception("Error emitting StoreJob done signal")


class ProgressDialogBinder(QObject):
    """Binds a modal QProgressDialog to a StoreJob lifecycle."""

    def __init__(self, job: StoreJob, dialog: Any, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.job = job
        self.dialog = dialog
        if job.title:
            dialog.setWindowTitle(job.title)
        dialog.canceled.connect(job.cancel)
        job.signals.progress.connect(self._on_progress)
        job.signals.done.connect(self._on_done)

    def _on_done(self) -> None:
        try:
            self.dialog.canceled.disconnect(self.job.cancel)
        except Exception:
            pass
        self.dialog.close()

    def _on_progress(self, message: str, done: int, total: int) -> None:
        if message:
            self.dialog.setLabelText(message)
        if total > 0:
            self.dialog.setMaximum(total)
            self.dialog.setValue(done)
        else:
            self.dialog.setMaximum(0)
            self.dialog.setValue(0)
