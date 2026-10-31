"""Closing the app with data loaded must end cleanly: QApplication used to delete the controller while the window's bindings still read it,
and the process ended with a segmentation fault (found when the user closed the app, 2026-10-31)."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = """
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import analytics_studio.main as m
from analytics_studio.file_import import parse_file
made = []
class Controller(m.StudioController):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        made.append(self)
m.StudioController = Controller
real_exec = QApplication.exec
def load():
    path = Path("tests/Data/Vat File -Aug 2026.xlsx")
    assert made[0]._commit_import(path, parse_file(path, {}))
    assert made[0].create_measure("M1", "1+1")
def run(*_):
    QTimer.singleShot(100, load)
    QTimer.singleShot(2000, QApplication.quit)
    return real_exec()
QApplication.exec = run
raise SystemExit(m.main())
"""


class AppCloseTest(unittest.TestCase):
    def test_closing_with_data_loaded_ends_cleanly(self) -> None:
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(ROOT)}
        finished = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(0, finished.returncode, finished.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
