"""Leave the test process without Qt's interpreter-shutdown teardown.

After a long run, PySide destroys the QApplication while QML items from the UI tests are still alive; one of them
re-lays out its text against an input method that is already gone and the process segfaults at exit, which makes
macOS show a "Python quit unexpectedly" window and turns a green run into a non-zero exit code.  The tests have
already finished and reported by then, so exit directly with pytest's own status.
"""
from __future__ import annotations

import atexit
import os
import sys

from PySide6 import QtCore  # noqa: F401  (imported first so PySide's own exit cleanup is registered before ours and runs after it)

_status: dict[str, int | None] = {"code": None}


def pytest_sessionfinish(session, exitstatus) -> None:
    _status["code"] = int(exitstatus)


def _leave_without_qt_teardown() -> None:
    code = _status["code"]
    if code is None:  # pytest never finished a session (collection error, interrupted import): normal shutdown
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


atexit.register(_leave_without_qt_teardown)
