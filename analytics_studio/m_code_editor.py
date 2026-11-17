"""A small code editor for Power Query M: monospace, line numbers, Tab indentation."""

from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QKeyEvent,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import QPlainTextEdit, QWidget

INDENT = "    "


class MSyntaxHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for Power Query M code matching Power BI Advanced Editor."""

    STATE_NORMAL = 0
    STATE_BLOCK_COMMENT = 1
    STATE_STRING = 2

    COLOR_KEYWORD = QColor("#0000FF")
    COLOR_STRING = QColor("#A31515")
    COLOR_COMMENT = QColor("#008000")
    COLOR_NUMBER = QColor("#098658")
    COLOR_INTRINSIC = QColor("#001080")

    KEYWORDS = {
        "let", "in", "each", "if", "then", "else", "try", "otherwise",
        "and", "or", "not", "as", "is", "meta", "type", "error",
        "section", "shared", "true", "false", "null",
    }

    _NUMBER_RE = re.compile(
        r"^(?:0[xX][0-9a-fA-F]+|(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
    )

    def __init__(self, parent: QTextDocument | None = None) -> None:
        super().__init__(parent)
        self._fmt_keyword = QTextCharFormat()
        self._fmt_keyword.setForeground(self.COLOR_KEYWORD)

        self._fmt_string = QTextCharFormat()
        self._fmt_string.setForeground(self.COLOR_STRING)

        self._fmt_comment = QTextCharFormat()
        self._fmt_comment.setForeground(self.COLOR_COMMENT)

        self._fmt_number = QTextCharFormat()
        self._fmt_number.setForeground(self.COLOR_NUMBER)

        self._fmt_intrinsic = QTextCharFormat()
        self._fmt_intrinsic.setForeground(self.COLOR_INTRINSIC)

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt override
        i = 0
        n = len(text)
        state = self.previousBlockState()
        if state == -1:
            state = self.STATE_NORMAL

        while i < n:
            if state == self.STATE_BLOCK_COMMENT:
                end = text.find("*/", i)
                if end != -1:
                    self.setFormat(i, end + 2 - i, self._fmt_comment)
                    i = end + 2
                    state = self.STATE_NORMAL
                else:
                    self.setFormat(i, n - i, self._fmt_comment)
                    i = n
                continue

            if state == self.STATE_STRING:
                start = i
                closed = False
                while i < n:
                    if text[i] == '"':
                        if i + 1 < n and text[i + 1] == '"':
                            i += 2
                        else:
                            i += 1
                            closed = True
                            break
                    else:
                        i += 1
                self.setFormat(start, i - start, self._fmt_string)
                if closed:
                    state = self.STATE_NORMAL
                continue

            # In STATE_NORMAL
            # Line comment
            if text.startswith("//", i):
                self.setFormat(i, n - i, self._fmt_comment)
                i = n
                continue

            # Block comment
            if text.startswith("/*", i):
                end = text.find("*/", i + 2)
                if end != -1:
                    self.setFormat(i, end + 2 - i, self._fmt_comment)
                    i = end + 2
                else:
                    self.setFormat(i, n - i, self._fmt_comment)
                    i = n
                    state = self.STATE_BLOCK_COMMENT
                continue

            # Quoted identifier #"..."
            if text.startswith('#"', i):
                start = i
                i += 2
                closed = False
                while i < n:
                    if text[i] == '"':
                        if i + 1 < n and text[i + 1] == '"':
                            i += 2
                        else:
                            i += 1
                            closed = True
                            break
                    else:
                        i += 1
                self.setFormat(start, i - start, self._fmt_string)
                if not closed:
                    state = self.STATE_STRING
                continue

            # String literal "..."
            if text[i] == '"':
                start = i
                i += 1
                closed = False
                while i < n:
                    if text[i] == '"':
                        if i + 1 < n and text[i + 1] == '"':
                            i += 2
                        else:
                            i += 1
                            closed = True
                            break
                    else:
                        i += 1
                self.setFormat(start, i - start, self._fmt_string)
                if not closed:
                    state = self.STATE_STRING
                continue

            # #identifier intrinsics: #date, #datetime, #table, #duration, etc.
            if text[i] == "#" and i + 1 < n and (text[i + 1].isalpha() or text[i + 1] == "_"):
                start = i
                i += 1
                while i < n and (text[i].isalnum() or text[i] == "_"):
                    i += 1
                self.setFormat(start, i - start, self._fmt_intrinsic)
                continue

            # Numbers
            if (
                text[i].isdigit() or (text[i] == "." and i + 1 < n and text[i + 1].isdigit())
            ) and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
                match = self._NUMBER_RE.match(text[i:])
                if match:
                    length = len(match.group(0))
                    if i + length >= n or not (text[i + length].isalpha() or text[i + length] == "_"):
                        self.setFormat(i, length, self._fmt_number)
                        i += length
                        continue

            # Identifiers / Keywords
            if text[i].isalpha() or text[i] == "_":
                start = i
                while i < n and (text[i].isalnum() or text[i] == "_"):
                    i += 1
                word = text[start:i]
                preceded_by_dot = (start > 0 and text[start - 1] == ".")
                followed_by_dot = (i < n and text[i] == ".")
                if not preceded_by_dot and not followed_by_dot and word in self.KEYWORDS:
                    self.setFormat(start, i - start, self._fmt_keyword)
                continue

            i += 1

        self.setCurrentBlockState(state)


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
        self.highlighter = MSyntaxHighlighter(self.document())
        self.line_number_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._scroll_line_numbers)
        self._update_margin()

    def format_at(self, block_number: int, column: int) -> QTextCharFormat | None:
        """Expose text char format at a given block number and column for tests."""
        block = self.document().findBlockByNumber(block_number)
        if not block.isValid():
            return None
        formats = block.layout().formats()
        for f in formats:
            if f.start <= column < f.start + f.length:
                return QTextCharFormat(f.format)
        return None

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
