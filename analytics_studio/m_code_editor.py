"""A small code editor for Power Query M: monospace, line numbers, Tab indentation."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QKeyEvent, QPainter, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget

INDENT = "    "


class _LineNumberArea(QWidget):
    def __init__(self, editor: "MCodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._editor.paint_line_numbers(event)


class MCodeEditor(QPlainTextEdit):
    """Plain-text editor with Power BI Advanced Editor behaviour."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(12)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * len(INDENT))
        self.setUndoRedoEnabled(True)
        self.line_number_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._scroll_line_numbers)
        self._update_margin()

    # ---- line numbers -------------------------------------------------
    def line_number_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margin(self, *_args) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)
        self._place_line_numbers()

    def _place_line_numbers(self) -> None:
        rect = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(rect.left(), rect.top(), self.line_number_width(), rect.height())
        )

    def _scroll_line_numbers(self, rect: QRect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margin()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._place_line_numbers()

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#eef1f4"))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        painter.setPen(QColor("#7a8794"))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(
                    0, top, self.line_number_area.width() - 6, self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, str(number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    # ---- keyboard -----------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        key = event.key()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Backtab or (key == Qt.Key.Key_Tab and shift):
            self._unindent()
            return
        if key == Qt.Key.Key_Tab and not (
            event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        ):
            self._indent()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not self.isReadOnly():
            cursor = self.textCursor()
            line = cursor.block().text()
            leading = line[: len(line) - len(line.lstrip(" \t"))]
            cursor.insertText("\n" + leading)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
            return
        super().keyPressEvent(event)

    def _selected_blocks(self) -> tuple[int, int]:
        cursor = self.textCursor()
        document = self.document()
        first = document.findBlock(cursor.selectionStart()).blockNumber()
        end = cursor.selectionEnd()
        last_block = document.findBlock(end)
        last = last_block.blockNumber()
        if cursor.hasSelection() and last > first and end == last_block.position():
            last -= 1
        return first, last

    def _indent(self) -> None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            column = cursor.positionInBlock()
            cursor.insertText(" " * (len(INDENT) - column % len(INDENT)))
            self.setTextCursor(cursor)
            return
        first, last = self._selected_blocks()
        cursor.beginEditBlock()
        for number in range(first, last + 1):
            block = self.document().findBlockByNumber(number)
            edit = QTextCursor(block)
            edit.insertText(INDENT)
        cursor.endEditBlock()

    def _unindent(self) -> None:
        first, last = self._selected_blocks()
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for number in range(first, last + 1):
            block = self.document().findBlockByNumber(number)
            text = block.text()
            if text.startswith("\t"):
                remove = 1
            else:
                remove = min(len(INDENT), len(text) - len(text.lstrip(" ")))
            if remove:
                edit = QTextCursor(block)
                edit.movePosition(
                    QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, remove
                )
                edit.removeSelectedText()
        cursor.endEditBlock()

    def focusNextPrevChild(self, next_child: bool) -> bool:  # noqa: N802 - Qt override
        return False  # Tab belongs to the code, not to focus navigation
