"""Tests for measure dialog and formula bar preview off the window thread with cancellation and busy indicators."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.measure_dialog import MeasureDialog


def _ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class TestAsyncPreview(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = _ensure_app()

    def setUp(self) -> None:
        self.controller = StudioController()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.csv_path = Path(self.temp_dir.name) / "Sales.csv"
        # Seed test table with 10 rows for standard calculations
        rows = [
            "Region,Amount,Units",
            "North,100,2",
            "South,200,4",
            "East,300,6",
            "West,400,8",
            "North,150,3",
            "South,250,5",
            "East,350,7",
            "West,450,9",
            "North,50,1",
            "South,150,3",
        ]
        self.csv_path.write_text("\n".join(rows), encoding="utf-8")
        self.controller._commit_import(self.csv_path, parse_file(self.csv_path))

    def tearDown(self) -> None:
        self.controller.cancelPreview()
        self.controller._cancel_and_wait_worker()
        self.temp_dir.cleanup()

    def test_async_preview_text_equals_sync_for_six_formulas(self) -> None:
        formulas = [
            ("M_Sum", "SUM(Sales[Amount])"),
            ("M_Avg", "AVERAGE(Sales[Amount])"),
            ("M_Min", "MIN(Sales[Units])"),
            ("M_Max", "MAX(Sales[Units])"),
            ("M_Count", "COUNTROWS(Sales)"),
            ("M_Divide", "DIVIDE(SUM(Sales[Amount]), SUM(Sales[Units]))"),
        ]
        for name, expr in formulas:
            sync_val = self.controller._preview_measure_expression(name, expr)
            done_holder: list[str] = []

            def on_done(text: str) -> None:
                done_holder.append(text)

            self.controller._preview_measure_expression_async(name, expr, on_done)
            self.controller._preview_pool.waitForDone(5000)
            self.app.processEvents()

            self.assertEqual(len(done_holder), 1, f"Expected 1 callback for {name}")
            self.assertEqual(
                sync_val, done_holder[0], f"Async preview mismatch for formula {expr}"
            )

    def test_newest_only_evaluation(self) -> None:
        # Create a large dataset so the first calculation takes time
        slow_csv = Path(self.temp_dir.name) / "Big.csv"
        lines = ["Val"] + ["1"] * 2500
        slow_csv.write_text("\n".join(lines), encoding="utf-8")
        self.controller._commit_import(slow_csv, parse_file(slow_csv))

        results_a: list[str] = []
        results_b: list[str] = []

        self.controller._preview_measure_expression_async(
            "SlowA",
            "SUMX(Big, CALCULATE(COUNTROWS(Big)))",
            lambda t: results_a.append(t),
        )
        self.controller._preview_measure_expression_async(
            "FastB",
            "SUM(Big[Val])",
            lambda t: results_b.append(t),
        )

        self.controller._preview_pool.waitForDone(5000)
        self.app.processEvents()

        self.assertEqual(results_a, [], "Stale request A should not reach on_done")
        self.assertEqual(results_b, ["2,500"], "Newest request B should reach on_done")

    def test_cancel_slow_preview(self) -> None:
        slow_csv = Path(self.temp_dir.name) / "BigCancel.csv"
        lines = ["Val"] + ["1"] * 3000
        slow_csv.write_text("\n".join(lines), encoding="utf-8")
        self.controller._commit_import(slow_csv, parse_file(slow_csv))

        dialog = MeasureDialog(
            ["Val"],
            [],
            preview_callback=lambda n, e: self.controller._preview_measure_expression(
                n, e
            ),
            preview_async_callback=lambda n, e, cb: (
                self.controller._preview_measure_expression_async(n, e, cb)
            ),
            cancel_preview_callback=self.controller.cancelPreview,
        )
        dialog.name_edit.setText("Slow")
        dialog.expression_edit.setPlainText(
            "SUMX(BigCancel, CALCULATE(COUNTROWS(BigCancel)))"
        )

        dialog.preview_button.click()
        self.assertFalse(dialog.preview_button.isEnabled())
        self.assertFalse(dialog.preview_cancel_button.isHidden())
        self.assertEqual(dialog.preview_label.text(), "Evaluating…")

        time.sleep(0.05)
        # Cancel preview via dialog button
        cancel_start = time.time()
        dialog.preview_cancel_button.click()
        self.controller._preview_pool.waitForDone(2000)
        self.app.processEvents()
        cancel_elapsed = time.time() - cancel_start

        self.assertLess(cancel_elapsed, 2.0, "Cancellation took longer than 2 s")
        self.assertEqual(dialog.preview_label.text(), "Cancelled")
        self.assertTrue(dialog.preview_button.isEnabled())
        self.assertTrue(dialog.preview_cancel_button.isHidden())

    def test_sync_create_measure_during_preview(self) -> None:
        slow_csv = Path(self.temp_dir.name) / "BigSync.csv"
        lines = ["Val"] + ["1"] * 3000
        slow_csv.write_text("\n".join(lines), encoding="utf-8")
        self.controller._commit_import(slow_csv, parse_file(slow_csv))

        preview_results: list[str] = []
        self.controller._preview_measure_expression_async(
            "SlowM",
            "SUMX(BigSync, CALCULATE(COUNTROWS(BigSync)))",
            lambda t: preview_results.append(t),
        )

        time.sleep(0.02)
        # Calling create_measure synchronously cancels and waits the preview worker
        ok = self.controller.create_measure("FastM", "SUM(BigSync[Val])")
        self.assertTrue(ok)

        self.controller._preview_pool.waitForDone(5000)
        self.app.processEvents()

        # Stale preview text must not be shown as a normal value
        for res in preview_results:
            self.assertEqual(res, "Cancelled")

    def test_qml_facing_slot_and_busy_flag(self) -> None:
        bar = self.controller.formulaBar
        self.assertFalse(bar.previewBusy)

        # Calling previewMeasureInteractive returns at once and sets busy flag
        ret = bar.previewMeasureInteractive("Amount")
        # "Amount" is not a measure name in Sales.csv, so it should cleanly return
        self.controller._commit_import(self.csv_path, parse_file(self.csv_path))
        self.assertTrue(self.controller.create_measure("TotalAmount", "SUM(Sales[Amount])"))

        busy_seen: list[bool] = []
        bar.previewBusyChanged.connect(lambda b: busy_seen.append(b))

        start_time = time.time()
        ret = bar.previewMeasureInteractive("TotalAmount")
        elapsed = time.time() - start_time
        self.assertLess(elapsed, 0.5, "previewMeasureInteractive should return at once")
        self.assertTrue(ret)
        self.assertTrue(bar.previewBusy)

        self.controller._preview_pool.waitForDone(5000)
        self.app.processEvents()

        self.assertFalse(bar.previewBusy)
        self.assertIn(True, busy_seen)
        self.assertEqual(busy_seen[-1], False)

    def test_ui_responsiveness_timer(self) -> None:
        slow_csv = Path(self.temp_dir.name) / "BigTimer.csv"
        lines = ["Val"] + ["1"] * 4000
        slow_csv.write_text("\n".join(lines), encoding="utf-8")
        self.controller._commit_import(slow_csv, parse_file(slow_csv))

        ticks = 0

        def on_timeout() -> None:
            nonlocal ticks
            ticks += 1

        timer = QTimer()
        timer.setInterval(20)
        timer.timeout.connect(on_timeout)
        timer.start()

        done = [False]

        def on_done(_val: str) -> None:
            done[0] = True

        self.controller._preview_measure_expression_async(
            "SlowTimer",
            "SUMX(BigTimer, CALCULATE(COUNTROWS(BigTimer)))",
            on_done,
        )

        while not done[0]:
            self.app.processEvents()
            time.sleep(0.005)

        timer.stop()
        self.assertGreater(ticks, 10, f"Expected > 10 ticks, got {ticks}")
