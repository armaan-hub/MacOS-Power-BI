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
_NEW, _QUEUED, _RUNNING, _FINISHED = "new", "queued", "running", "finished"
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
        self._cm: Optional[Any] = None
        self._cancel_event: Optional[threading.Event] = None
        self._lock = threading.Lock()
        self._state = _NEW

    def start(self, pool: QThreadPool) -> None:
        """UI thread entry point. Marks store busy BEFORE submitting to the thread pool.

        A job object is single-use. No state changes until the store context was entered;
        any failure leaves the job exactly as it was before the call.
        """
        with self._lock:
            if self._state != _NEW:
                raise StoreError("This job was already started.")
        cm = self.project_store.job()
        cancel_evt = cm.__enter__()
        with self._lock:
            if self._state != _NEW:
                late = True
            else:
                late = False
                self._cm = cm
                self._cancel_event = cancel_evt
                self._state = _QUEUED
        if late:
            cm.__exit__(None, None, None)
            raise StoreError("This job was already started.")
        try:
            pool.start(self)
        except Exception:
            with self._lock:
                if self._state == _QUEUED and self._cm is cm:
                    self._cm = None
                    self._cancel_event = None
                    self._state = _NEW
            cm.__exit__(None, None, None)
            raise

    def cancel(self) -> None:
        """Signal cancellation to the project store, only while this job is queued or running."""
        with self._lock:
            if self._state not in (_QUEUED, _RUNNING):
                return
        self.project_store.request_cancel()

    def release_if_not_started(self) -> None:
        """Release a queued job whose run() never began. Idempotent and thread-safe.

        Emits canceled then done from the calling thread. A later run() returns at once.
        """
        with self._lock:
            if self._state != _QUEUED:
                return
            cm_to_exit = self._cm
            self._cm = None
            self._cancel_event = None
            self._state = _FINISHED
        self._finish(cm_to_exit, lambda: self.signals.canceled.emit())

    def _finish(self, cm: Optional[Any], outcome_signal: Optional[Callable[[], None]]) -> None:
        """Release the store context, emit the outcome, then emit done. Every step is guarded."""
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

    def run(self) -> None:
        """Worker thread entry point."""
        with self._lock:
            if self._state != _QUEUED:
                # Never started, already released, or already finished.
                return
            self._state = _RUNNING
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
        except BaseException as exc:  # GeneratorExit and other BaseException subclasses
            exc_type = type(exc).__name__
            msg = f"Unexpected error: {exc_type}: {exc}"
            logger.error("Unexpected BaseException in StoreJob %r: %s", self.title, msg)
            outcome_signal = lambda: self.signals.failed.emit(msg)
        finally:
            with self._lock:
                self._state = _FINISHED
                cm = self._cm
                self._cm = None
                self._cancel_event = None
            self._finish(cm, outcome_signal)


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
