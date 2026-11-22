"""Tests for measure dialog and formula bar preview off the window thread with cancellation and busy indicators."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import shiboken6

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


def _pump_until(app: QApplication, predicate, seconds: float = 20.0) -> bool:
    """Process events until predicate() is true or a generous deadline passes."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


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
            self.assertTrue(self.controller._preview_pool.waitForDone(20000))
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

        self.assertTrue(self.controller._preview_pool.waitForDone(20000))
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
        dialog.show()
        dialog.name_edit.setText("Slow")
        dialog.expression_edit.setPlainText(
            "SUMX(BigCancel, CALCULATE(COUNTROWS(BigCancel)))"
        )

        dialog.preview_button.click()
        self.assertFalse(dialog.preview_button.isEnabled())
        self.assertFalse(dialog.preview_cancel_button.isHidden())
        self.assertEqual(dialog.preview_label.text(), "Evaluating…")
        event = self.controller._preview_cancel_event

        dialog.preview_cancel_button.click()
        self.assertTrue(event.is_set(), "cancel flag must be set")
        self.assertEqual(dialog.preview_label.text(), "Cancelled")
        self.assertTrue(self.controller._preview_pool.waitForDone(20000))
        self.app.processEvents()

        # A result finishing after the user pressed Cancel must not overwrite it.
        self.assertEqual(dialog.preview_label.text(), "Cancelled")
        self.assertTrue(dialog.preview_button.isEnabled())
        self.assertTrue(dialog.preview_cancel_button.isHidden())
        dialog.close()

    def test_sync_create_measure_during_preview(self) -> None:
        self.assertTrue(self.controller.create_measure("Base", "SUM(Sales[Amount])"))
        stale = self.controller._preview_measure_expression("Pv", "[Base]")
        self.assertEqual(stale, "2,400")
        results: list[str] = []
        self.controller._preview_measure_expression_async(
            "Pv", "[Base]", results.append
        )
        # The worker finishes, but its result is not yet delivered to the window thread.
        self.assertTrue(self.controller._preview_pool.waitForDone(20000))
        self.assertEqual(results, [])
        # A synchronous engine call changes what the preview means.
        self.assertTrue(
            self.controller.update_measure("Base", "Base", "SUM(Sales[Units])")
        )
        fresh = self.controller._preview_measure_expression("Pv", "[Base]")
        self.assertEqual(fresh, "48")
        self.assertNotEqual(fresh, stale)
        self.assertTrue(_pump_until(self.app, lambda: bool(results)))
        self.controller._preview_pool.waitForDone(20000)
        self.app.processEvents()
        self.assertNotIn(stale, results, "stale result delivered after sync call")
        self.assertEqual(results, [fresh])

    def test_user_cancel_drops_queued_result(self) -> None:
        results: list[str] = []
        self.controller._preview_measure_expression_async(
            "Pv", "SUM(Sales[Amount])", results.append
        )
        self.assertTrue(self.controller._preview_pool.waitForDone(20000))
        self.controller.cancelPreview()
        _pump_until(self.app, lambda: bool(results), seconds=0.3)
        self.assertEqual(results, [])

    def test_report_refresh_interrupts_then_restarts_preview(self) -> None:
        """Preview and report use separate pools, so a report refresh cancels a
        running preview. The preview starts again once the refresh has returned."""
        self.assertIsNot(self.controller._preview_pool, self.controller._report_pool)
        results: list[str] = []
        self.controller._preview_measure_expression_async(
            "Pv", "SUM(Sales[Amount])", results.append
        )
        self.assertTrue(self.controller._preview_pool.waitForDone(20000))
        self.controller._refresh_report()
        self.assertNotIn("Cancelled", results)
        self.assertTrue(_pump_until(self.app, lambda: bool(results)))
        self.assertEqual(results, ["2,400"])

    def test_dialog_closed_during_preview_is_safe(self) -> None:
        slow_csv = Path(self.temp_dir.name) / "BigClose.csv"
        slow_csv.write_text("\n".join(["Val"] + ["1"] * 3000), encoding="utf-8")
        self.controller._commit_import(slow_csv, parse_file(slow_csv))
        for closer in ("accept", "reject", "done"):
            dialog = MeasureDialog(
                ["Val"],
                [],
                preview_async_callback=lambda n, e, cb: (
                    self.controller._preview_measure_expression_async(n, e, cb)
                ),
                cancel_preview_callback=self.controller.cancelPreview,
            )
            dialog.show()
            dialog.name_edit.setText("Slow")
            dialog.expression_edit.setPlainText(
                "SUMX(BigClose, CALCULATE(COUNTROWS(BigClose)))"
            )
            dialog.preview_button.click()
            self.assertFalse(dialog.preview_button.isEnabled())
            event = self.controller._preview_cancel_event
            if closer == "accept":
                dialog.accept()
            elif closer == "reject":
                dialog.reject()
            else:
                dialog.done(0)
            self.assertTrue(event.is_set(), f"{closer} must cancel the preview")
            shiboken6.delete(dialog)
            self.assertTrue(self.controller._preview_pool.waitForDone(20000))
            # Pumping delivers any queued signal; it must not touch the deleted dialog.
            _pump_until(self.app, lambda: False, seconds=0.2)

    def test_qml_facing_slot_shows_formula_without_evaluating(self) -> None:
        bar = self.controller.formulaBar
        self.assertFalse(bar.previewBusy)
        self.assertTrue(self.controller.create_measure("TotalAmount", "SUM(Sales[Amount])"))
        bar_plain = bar.previewMeasure("TotalAmount")
        plain_text = bar.text
        bar.cancel()
        self.assertTrue(bar.previewMeasureInteractive("TotalAmount"))
        self.assertTrue(bar_plain)
        self.assertEqual(bar.text, plain_text)
        self.assertFalse(bar.previewBusy)
        self.assertFalse(self.controller._preview_tasks)

    def test_busy_flag_follows_newest_request(self) -> None:
        slow_csv = Path(self.temp_dir.name) / "BigBusy.csv"
        slow_csv.write_text("\n".join(["Val"] + ["1"] * 3000), encoding="utf-8")
        self.controller._commit_import(slow_csv, parse_file(slow_csv))
        bar = self.controller.formulaBar
        self.assertFalse(bar.previewBusy)
        a: list[str] = []
        b: list[str] = []
        self.controller._preview_measure_expression_async(
            "A", "SUMX(BigBusy, CALCULATE(COUNTROWS(BigBusy)))", a.append
        )
        self.assertTrue(bar.previewBusy)
        self.controller._preview_measure_expression_async(
            "B", "SUM(BigBusy[Val])", b.append
        )
        self.assertTrue(bar.previewBusy)
        self.assertTrue(_pump_until(self.app, lambda: bool(b)))
        self.assertEqual(a, [])
        self.assertEqual(b, ["3,000"])
        self.assertFalse(bar.previewBusy, "busy must clear when the newest request completes")

        # A user cancel clears the flag at once.
        self.controller._preview_measure_expression_async(
            "C", "SUMX(BigBusy, CALCULATE(COUNTROWS(BigBusy)))", a.append
        )
        self.assertTrue(bar.previewBusy)
        self.controller.cancelPreview()
        self.assertFalse(bar.previewBusy)

        # A failed request clears it too.
        failures: list[str] = []
        self.controller._preview_measure_expression_async(
            "D", "SUM(Nope[X])", failures.append
        )
        self.assertTrue(_pump_until(self.app, lambda: bool(failures)))
        self.assertFalse(bar.previewBusy)

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

        self.assertTrue(
            _pump_until(self.app, lambda: done[0]), "preview did not finish before the deadline"
        )

        timer.stop()
        self.assertGreater(ticks, 10, f"Expected > 10 ticks, got {ticks}")
