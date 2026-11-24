"""Start the Qt Quick shell and expose its Python application controller."""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController

logger = logging.getLogger(__name__)


def install_excepthook() -> None:
    """Install a sys.excepthook wrapper that logs tracebacks before chaining."""
    if getattr(sys.excepthook, "_analytics_studio_installed", False):
        return

    previous_hook = sys.excepthook

    def _logging_excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        logger.error(
            "Uncaught exception: %s",
            exc_value,
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        if previous_hook is not None:
            previous_hook(exc_type, exc_value, exc_traceback)

    _logging_excepthook._analytics_studio_installed = True
    sys.excepthook = _logging_excepthook

    if hasattr(threading, "excepthook"):
        if not getattr(threading.excepthook, "_analytics_studio_installed", False):
            previous_thread_hook = threading.excepthook

            def _logging_thread_excepthook(args: Any) -> None:
                logger.error(
                    "Uncaught exception in thread %s: %s",
                    args.thread.name if args.thread else "unknown",
                    args.exc_value,
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                )
                if previous_thread_hook is not None:
                    previous_thread_hook(args)

            _logging_thread_excepthook._analytics_studio_installed = True
            threading.excepthook = _logging_thread_excepthook


def _on_about_to_quit(controller: StudioController) -> None:
    """Cleanly shut down background store jobs and the open project store on quit.

    Total blocking time:
    - Global QThreadPool waitForDone up to 15 s (UI / background Qt worker pool).
    - StoreJob runs on its own background thread pool, cancelled immediately by request_cancel().
    - ProjectStore.shutdown(timeout=15.0) waits up to 15 s for active DuckStore operations to complete.
    - If first shutdown attempt fails, retry once after a 2.0 s event processing loop with timeout=5.0 s.
    Maximum theoretical blocking delay on quit is ~37 s if jobs fail to cancel.
    """
    if controller._project_store is not None:
        controller._project_store.request_cancel()
    global_pool = QThreadPool.globalInstance()
    if global_pool is not None:
        global_pool.waitForDone(15000)

    success = controller.shutdown_store(timeout=15.0)
    if not success:
        # Retry once after 2 s with a processEvents loop
        app = QCoreApplication.instance()
        end_time = time.time() + 2.0
        while time.time() < end_time:
            if app is not None:
                app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
            time.sleep(0.01)
        success = controller.shutdown_store(timeout=5.0)
        if not success:
            logger.error("Failed to shutdown ProjectStore on aboutToQuit after retry.")


def main() -> int:
    install_excepthook()
    # Custom QML backgrounds are supported by the Basic Controls style.
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv)
    app.setApplicationName("Analytics Studio")
    app.setApplicationDisplayName("Analytics Studio")
    available_fonts = {name.casefold(): name for name in QFontDatabase.families()}
    ui_font = next(
        (available_fonts[name.casefold()] for name in ("Segoe UI", "Arial", "Helvetica Neue")
         if name.casefold() in available_fonts),
        "Arial",
    )
    app.setFont(QFont(ui_font))

    controller = StudioController(app)
    app.aboutToQuit.connect(lambda: _on_about_to_quit(controller))
    engine = QQmlApplicationEngine(app)
    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    component = QQmlComponent(engine)
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    if component.isError():
        for error in component.errors():
            print(error.toString(), file=sys.stderr)
        return 1

    window = component.createWithInitialProperties({"studioController": controller})
    if window is None:
        for error in component.errors():
            print(error.toString(), file=sys.stderr)
        print(f"Could not load the Qt Quick interface: {qml_path}", file=sys.stderr)
        return 1

    if len(sys.argv) > 1:
        project_path = Path(sys.argv[1])
        QTimer.singleShot(0, lambda: controller.open_project_path(project_path))
    else:
        QTimer.singleShot(0, window.requestActivate)

    exit_code = app.exec()
    # Remove the window while the application still exists.  Left to Python's shutdown, QApplication deletes the controller
    # first, the window's bindings then update text with no application behind them, and the process ends with a segmentation fault.
    window.deleteLater()
    QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
