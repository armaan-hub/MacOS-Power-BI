"""The Power Query ribbon never clips a group label or a button label.

At the widths below every ribbon tab must show each group's full label, every
visible button must have room for its whole text and icon, and groups that do
not fit collapse into a dropdown (like Power BI) instead of being cut off.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QScrollArea, QToolButton, QWidget

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog

WIDTHS = (1000, 1280, 1600)


def _source() -> ImportCandidate:
    return ImportCandidate(
        "inline", ["Region", "Amount"],
        [{"Region": "East", "Amount": "10"}, {"Region": "West", "Amount": "20"}],
        {}, [],
    )


def _flatten(text: str) -> str:
    return " ".join(text.replace("&&", "&").split())


class RibbonLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["ribbon layout tests"])

    def setUp(self) -> None:
        self.dialog = TransformDataDialog(_source(), query_name="Sales")
        self.addCleanup(self.dialog.deleteLater)

    def show_page(self, index: int, width: int) -> QWidget:
        self.dialog.resize(width, 760)
        self.dialog.show()
        self.dialog.ribbon_tabs.setCurrentIndex(index)
        self.app.processEvents()
        self.app.processEvents()
        return self.dialog.ribbon_tabs.widget(index)

    def visible_tabs(self) -> list[int]:
        bar = self.dialog.ribbon_tabs.tabBar()
        return [i for i in range(self.dialog.ribbon_tabs.count()) if bar.isTabVisible(i)]

    def groups(self, page: QWidget) -> list[QWidget]:
        return page.findChildren(QWidget, "powerQueryRibbonGroup")

    def test_every_group_label_fits_inside_its_group_and_inside_the_ribbon(self) -> None:
        for width in WIDTHS:
            for index in self.visible_tabs():
                page = self.show_page(index, width)
                tab = self.dialog.ribbon_tabs.tabText(index)
                scroll = page.findChild(QScrollArea, "powerQueryRibbonScrollArea")
                viewport = scroll.viewport()
                for group in self.groups(page):
                    if not group.isVisible():
                        continue
                    caption = group.findChild(QLabel, "powerQueryRibbonGroupCaption")
                    with self.subTest(width=width, tab=tab, group=caption.text()):
                        hint = caption.sizeHint()
                        self.assertGreaterEqual(caption.width(), hint.width())
                        self.assertGreaterEqual(caption.height(), hint.height())
                        self.assertTrue(
                            QRect(0, 0, group.width(), group.height()).contains(
                                caption.geometry()
                            ),
                            f"{caption.geometry()} not inside {group.rect()}",
                        )
                        # The whole group, caption included, is inside the visible ribbon.
                        bottom_right = group.mapTo(viewport, group.rect().bottomRight())
                        self.assertLessEqual(bottom_right.y(), viewport.height() - 1)
                        self.assertLessEqual(bottom_right.x(), viewport.width() - 1)
                self.assertFalse(
                    scroll.horizontalScrollBar().isVisible(),
                    f"{tab} at {width}px needs a scroll bar instead of collapsing",
                )

    def test_every_visible_button_has_room_for_its_whole_label(self) -> None:
        for width in WIDTHS:
            for index in self.visible_tabs():
                page = self.show_page(index, width)
                tab = self.dialog.ribbon_tabs.tabText(index)
                scroll = page.findChild(QScrollArea, "powerQueryRibbonScrollArea")
                viewport = scroll.viewport()
                for group in self.groups(page):
                    if not group.isVisible():
                        continue
                    for button in group.findChildren(QToolButton):
                        with self.subTest(width=width, tab=tab,
                                          button=_flatten(button.text()) or button.objectName()):
                            hint = button.sizeHint()
                            self.assertGreaterEqual(button.width(), hint.width())
                            self.assertGreaterEqual(button.height(), hint.height())
                            self.assertTrue(button.isVisible())
                            rect = QRect(button.mapTo(viewport, button.rect().topLeft()),
                                         button.size())
                            self.assertTrue(viewport.rect().contains(rect),
                                            f"{rect} outside {viewport.rect()}")

    def test_all_group_labels_are_reachable_either_visible_or_in_a_collapsed_dropdown(self) -> None:
        for width in WIDTHS:
            for index in self.visible_tabs():
                page = self.show_page(index, width)
                tab = self.dialog.ribbon_tabs.tabText(index)
                titles = [g.findChild(QLabel, "powerQueryRibbonGroupCaption").text()
                          for g in self.groups(page)]
                shown: list[str] = []
                for group in self.groups(page):
                    title = group.findChild(QLabel, "powerQueryRibbonGroupCaption").text()
                    if group.isVisible():
                        shown.append(title)
                for button in page.findChildren(QToolButton, "powerQueryRibbonCollapsedGroup"):
                    if button.isVisible():
                        shown.append(_flatten(button.text()))
                with self.subTest(width=width, tab=tab):
                    self.assertEqual(sorted(_flatten(t) for t in titles),
                                     sorted(_flatten(t) for t in shown))

    def test_narrow_window_collapses_groups_into_dropdowns_with_working_commands(self) -> None:
        page = self.show_page(0, 900)
        collapsed = [b for b in page.findChildren(QToolButton, "powerQueryRibbonCollapsedGroup")
                     if b.isVisible()]
        self.assertTrue(collapsed, "Home at 900px should collapse at least one group")
        for button in collapsed:
            hint = button.sizeHint()
            self.assertGreaterEqual(button.width(), hint.width())
            self.assertGreaterEqual(button.height(), hint.height())
            self.assertIsNotNone(button.menu())
        # Menu entries mirror the hidden group's commands and drive the real buttons.
        for button in collapsed:
            if button.property("groupTitle") != "Reduce Rows":
                continue
            button.menu().aboutToShow.emit()
            labels = [a.text() for a in button.menu().actions()]
            self.assertEqual(labels, ["Keep Rows", "Remove Rows"])
            real = self.dialog.ribbon_command_buttons["remove_top_rows"]
            clicked: list[bool] = []
            real.clicked.connect(lambda *_: clicked.append(True))
            next(a for a in button.menu().actions() if a.text() == "Remove Rows").trigger()
            self.assertEqual(clicked, [True])
            break
        else:
            self.skipTest("Reduce Rows was not collapsed at 900px")

    def test_no_sparse_row_buttons_in_the_ribbon(self) -> None:
        # Power BI Desktop has no Sparse Top / Sparse Bottom commands; the ops stay for saved queries.
        for operation in ("remove_sparse_top_rows", "remove_sparse_bottom_rows"):
            self.assertNotIn(operation, self.dialog.ribbon_command_buttons)
        texts = [b.text().strip() for b in self.dialog.findChildren(QToolButton)]
        self.assertFalse([t for t in texts if "Sparse" in t])
        self.assertGreaterEqual(self.dialog.operation_combo.findData("remove_sparse_top_rows"), 0)
        self.assertGreaterEqual(self.dialog.operation_combo.findData("remove_sparse_bottom_rows"), 0)

    def test_widening_the_window_restores_the_full_groups(self) -> None:
        page = self.show_page(0, 900)
        self.assertTrue([b for b in page.findChildren(QToolButton, "powerQueryRibbonCollapsedGroup")
                         if b.isVisible()])
        page = self.show_page(0, 1900)
        self.assertEqual(
            [b for b in page.findChildren(QToolButton, "powerQueryRibbonCollapsedGroup")
             if b.isVisible()], [])

    def test_ribbon_is_tall_enough_for_its_tallest_page(self) -> None:
        for width in WIDTHS:
            page = self.show_page(0, width)
            scroll = page.findChild(QScrollArea, "powerQueryRibbonScrollArea")
            body = scroll.widget()
            self.assertGreaterEqual(scroll.viewport().height(), body.sizeHint().height(),
                                    f"ribbon shorter than its content at {width}px")


if __name__ == "__main__":
    unittest.main()
