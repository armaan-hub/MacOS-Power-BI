"""Worker task and thread pool for evaluating report measures and visuals off the window thread."""

from __future__ import annotations

import threading
from typing import Any, Callable
from decimal import Decimal

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from analytics_studio.measures import (
    MeasureError,
    MeasureEvaluationCancelled,
    evaluate_measures,
)


class MeasureTaskSignals(QObject):
    """Signals emitted by MeasureEvaluationTask."""
    completed = Signal(int, object)
    cancelled = Signal(int)
    failed = Signal(int, str)


class MeasureEvaluationTask(QRunnable):
    """QRunnable that evaluates report measures and visual data on a worker thread."""

    def __init__(
        self,
        request_id: int,
        eval_fn: Callable[[Callable[[], bool]], Any],
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.eval_fn = eval_fn
        self.cancel_event = cancel_event
        self.signals = MeasureTaskSignals()

    def run(self) -> None:
        if self.cancel_event.is_set():
            self.signals.cancelled.emit(self.request_id)
            return
        try:
            result = self.eval_fn(self.cancel_event.is_set)
        except MeasureEvaluationCancelled:
            self.signals.cancelled.emit(self.request_id)
        except Exception as exc:
            if self.cancel_event.is_set():
                self.signals.cancelled.emit(self.request_id)
            else:
                self.signals.failed.emit(self.request_id, str(exc))
        else:
            if self.cancel_event.is_set():
                self.signals.cancelled.emit(self.request_id)
            else:
                self.signals.completed.emit(self.request_id, result)


def create_measure_thread_pool() -> QThreadPool:
    """Create a dedicated QThreadPool with max 1 thread for serialized evaluation."""
    pool = QThreadPool()
    pool.setMaxThreadCount(1)
    return pool
