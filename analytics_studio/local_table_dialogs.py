"""Small native dialogs for entering local table data and previewing transforms."""

from __future__ import annotations

from copy import copy, deepcopy
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QRegularExpression,
    QRect,
    QSignalBlocker,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QIntValidator,
    QIcon,
    QKeySequence,
    QPalette,
    QPainter,
    QPen,
    QRegularExpressionValidator,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QStyle,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from analytics_studio.conditional_column_dialog import ConditionalColumnDialog
from analytics_studio.dialog_theme import apply_light_dialog_theme
from analytics_studio.file_import import MAX_DATA_ROWS, ImportCandidate, lineaged_row
from analytics_studio.import_preview_dialog import ImportPreviewTableModel
from analytics_studio.inline_data import parse_pasted_table, source_from_candidate
from analytics_studio.power_query_step_names import (
    assign_step_names,
    carry_step_metadata,
    is_known_power_bi_step,
)
from analytics_studio.power_query_m import (
    PowerQueryMEditorDialog,
    PowerQueryMScriptError,
    m_compatibility_issues,
    m_script_matches_steps,
    parse_m_script,
    replace_step_expression_in_m,
    rewrite_m_append_source_names,
    step_expression_to_m,
    steps_to_m_script,
)
from analytics_studio.power_query_values import cell_key, cell_to_text, is_cell_error
from analytics_studio.query_dependencies_dialog import QueryDependenciesDialog
from analytics_studio.query_parameters import (
    QUERY_PARAMETER_TYPES,
    QueryParameterError,
    normalize_query_parameter,
    parameter_values,
    validate_query_parameters,
)
from analytics_studio.query_functions import (
    QUERY_FUNCTION_TYPES,
    QueryFunctionError,
    function_references,
    normalize_query_function,
    validate_query_functions,
)
from analytics_studio.measures import (
    MeasureError,
    evaluate_calculated_table,
    normalize_calculated_table_expression,
)
from analytics_studio.query_engine import (
    QueryError,
    append_candidates,
    merge_candidates,
)
from analytics_studio.transformations import (
    FILTER_OPERATORS_WITHOUT_VALUE,
    MAX_CONDITIONAL_CLAUSES,
    MAX_FILTER_CLAUSES,
    MAX_MERGE_SEPARATOR_CHARS,
    TransformationError,
    apply_transformations,
    column_types_after_steps,
    count_conversion_errors,
    infer_column_types,
    validate_applied_step_metadata,
    validate_steps,
)


_CUSTOM_COLUMN_FUNCTIONS: dict[str, tuple[str, str]] = {
    "Text.From": ("Text.From(value)", "Text.From([Column])"),
    "Text.Upper": ("Text.Upper(text)", "Text.Upper([Column])"),
    "Text.Lower": ("Text.Lower(text)", "Text.Lower([Column])"),
    "Text.Trim": ("Text.Trim(text)", "Text.Trim([Column])"),
    "Text.Clean": ("Text.Clean(text)", "Text.Clean([Column])"),
    "Text.Length": ("Text.Length(text)", "Text.Length([Column])"),
    "Text.Contains": (
        "Text.Contains(text, substring)", 'Text.Contains([Column], "value")',
    ),
    "Text.StartsWith": (
        "Text.StartsWith(text, substring)", 'Text.StartsWith([Column], "value")',
    ),
    "Text.EndsWith": (
        "Text.EndsWith(text, substring)", 'Text.EndsWith([Column], "value")',
    ),
    "Text.Replace": (
        "Text.Replace(text, old, new)", 'Text.Replace([Column], "old", "new")',
    ),
    "Number.From": ("Number.From(value)", "Number.From([Column])"),
    "Number.Abs": ("Number.Abs(number)", "Number.Abs([Column])"),
    "Number.Round": ("Number.Round(number, digits)", "Number.Round([Column], 0)"),
    "Date.From": ("Date.From(value)", "Date.From([Column])"),
    "Date.Year": ("Date.Year(date)", "Date.Year([Column])"),
    "Date.Month": ("Date.Month(date)", "Date.Month([Column])"),
    "Date.Day": ("Date.Day(date)", "Date.Day([Column])"),
}



def _m_field_reference(name: str) -> str:
    """Return the safe row-field syntax accepted by the local M subset."""
    if "]" in name:
        return '[#"' + name.replace('"', '""') + '"]'
    return f"[{name}]"


class CustomColumnDialog(QDialog):
    """Formula-first editor for the supported row-scoped Power Query subset."""

    def __init__(
        self,
        columns: list[str],
        *,
        initial_name: str = "",
        initial_expression: str = "",
        functions: list[dict[str, str]] | None = None,
        parameters: list[dict[str, str]] | None = None,
        validate_callback: Callable[[str, str], str | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self.setObjectName("powerQueryCustomColumnDialog")
        self.setWindowTitle("Custom Column")
        self.setMinimumSize(760, 500)
        self.resize(920, 590)
        self._columns = list(columns)
        self._functions = [dict(item) for item in (functions or [])]
        self._parameters = [dict(item) for item in (parameters or [])]
        self._validate_callback = validate_callback
        self._accepted_value: tuple[str, str] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        title = QLabel("Add a custom column")
        title.setObjectName("customColumnDialogTitle")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)
        intro = QLabel(
            "Name the new column and write a formula for each row of this query."
        )
        intro.setStyleSheet("color: #526477;")
        layout.addWidget(intro)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("New column name"))
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("customColumnNameEdit")
        self.name_edit.setMaxLength(120)
        self.name_edit.setPlaceholderText("Column name")
        self.name_edit.setText(initial_name)
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        editor_row = QHBoxLayout()
        editor_row.setSpacing(12)
        formula_panel = QWidget()
        formula_layout = QVBoxLayout(formula_panel)
        formula_layout.setContentsMargins(0, 0, 0, 0)
        formula_layout.setSpacing(5)
        formula_heading = QLabel("Custom column formula")
        formula_heading.setStyleSheet("font-weight: 600; color: #344b5b;")
        formula_layout.addWidget(formula_heading)
        self.expression_edit = QPlainTextEdit()
        self.expression_edit.setObjectName("customColumnFormulaEdit")
        self.expression_edit.setPlaceholderText(
            'if [Quantity] > 0 then Text.Clean([Name]) else "No quantity"'
        )
        self.expression_edit.setPlainText(initial_expression)
        self.expression_edit.setMinimumHeight(150)
        formula_layout.addWidget(self.expression_edit, 1)

        parameter_row = QHBoxLayout()
        self.parameter_combo = QComboBox()
        self.parameter_combo.setObjectName("customColumnDialogParameterCombo")
        self.parameter_combo.addItem("Insert saved parameter…", "")
        for parameter in self._parameters:
            self.parameter_combo.addItem(parameter["name"], parameter["name"])
        self.insert_parameter_button = QPushButton("Insert parameter")
        self.insert_parameter_button.setObjectName(
            "customColumnDialogInsertParameterButton"
        )
        self.insert_parameter_button.setEnabled(bool(self._parameters))
        self.insert_parameter_button.clicked.connect(self._insert_parameter)
        parameter_row.addWidget(self.parameter_combo, 1)
        parameter_row.addWidget(self.insert_parameter_button)
        formula_layout.addLayout(parameter_row)

        self.syntax_help_label = QLabel()
        self.syntax_help_label.setObjectName("customColumnSyntaxHelp")
        self.syntax_help_label.setWordWrap(True)
        self.syntax_help_label.setMinimumHeight(38)
        self.syntax_help_label.setStyleSheet(
            "padding: 7px; background: #f4f7f9; border: 1px solid #dbe3e8; "
            "border-radius: 4px; color: #425768;"
        )
        formula_layout.addWidget(self.syntax_help_label)
        editor_row.addWidget(formula_panel, 1)

        reference_panel = QWidget()
        reference_panel.setObjectName("customColumnReferencePanel")
        reference_panel.setMinimumWidth(235)
        reference_panel.setMaximumWidth(300)
        reference_layout = QVBoxLayout(reference_panel)
        reference_layout.setContentsMargins(0, 0, 0, 0)
        reference_layout.setSpacing(5)
        columns_heading = QLabel("Available columns")
        columns_heading.setStyleSheet("font-weight: 600; color: #344b5b;")
        reference_layout.addWidget(columns_heading)
        self.column_list = QListWidget()
        self.column_list.setObjectName("customColumnAvailableColumns")
        self.column_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for column in self._columns:
            item = QListWidgetItem(column)
            item.setData(Qt.ItemDataRole.UserRole, column)
            item.setToolTip("Double-click to insert this column into the formula.")
            self.column_list.addItem(item)
        self.column_list.itemDoubleClicked.connect(self._insert_selected_column)
        reference_layout.addWidget(self.column_list, 1)
        self.insert_column_button = QPushButton("Insert column")
        self.insert_column_button.setObjectName("customColumnInsertColumnButton")
        self.insert_column_button.clicked.connect(self._insert_selected_column)
        reference_layout.addWidget(self.insert_column_button)

        function_heading = QLabel("Supported functions")
        function_heading.setStyleSheet("font-weight: 600; color: #344b5b;")
        reference_layout.addWidget(function_heading)
        self.function_list = QListWidget()
        self.function_list.setObjectName("customColumnSupportedFunctions")
        self.function_list.setMaximumHeight(132)
        for function, (syntax, insertion) in _CUSTOM_COLUMN_FUNCTIONS.items():
            item = QListWidgetItem(function)
            item.setData(Qt.ItemDataRole.UserRole, (function, syntax, insertion))
            self.function_list.addItem(item)
        for function in self._functions:
            syntax = f"{function['name']}({function['parameter']})"
            insertion = f"{function['name']}([Column])"
            item = QListWidgetItem(function["name"])
            item.setData(
                Qt.ItemDataRole.UserRole,
                (function["name"], syntax, insertion),
            )
            item.setToolTip(
                f"Saved scalar function · {function['parameter_type'].replace('_', ' ')} "
                f"→ {function['return_type'].replace('_', ' ')}"
            )
            self.function_list.addItem(item)
        self.function_list.currentItemChanged.connect(self._show_function_help)
        self.function_list.itemDoubleClicked.connect(self._insert_selected_function)
        reference_layout.addWidget(self.function_list)
        self.function_help_label = QLabel(
            "Choose a function to see its local syntax, then insert it at the caret."
        )
        self.function_help_label.setObjectName("customColumnFunctionHelp")
        self.function_help_label.setWordWrap(True)
        self.function_help_label.setMinimumHeight(42)
        self.function_help_label.setStyleSheet("color: #526477;")
        reference_layout.addWidget(self.function_help_label)
        self.insert_function_button = QPushButton("Insert function")
        self.insert_function_button.setObjectName(
            "customColumnInsertFunctionButton"
        )
        self.insert_function_button.clicked.connect(self._insert_selected_function)
        reference_layout.addWidget(self.insert_function_button)
        editor_row.addWidget(reference_panel)
        layout.addLayout(editor_row, 1)

        self.error_label = QLabel()
        self.error_label.setObjectName("customColumnDialogError")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.save_button.setText("Add column" if not initial_name else "Save column")
        self.buttons.accepted.connect(self._accept_column)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.expression_edit.textChanged.connect(self._update_syntax_help)
        self.name_edit.textChanged.connect(self._refresh_save_state)
        self._update_syntax_help()
        self._refresh_save_state()

    @property
    def column(self) -> tuple[str, str] | None:
        return self._accepted_value

    def _insert_selected_column(self, *_args: object) -> None:
        item = self.column_list.currentItem()
        if item is None:
            return
        self._insert_formula_text(_m_field_reference(str(item.data(Qt.ItemDataRole.UserRole))))

    def _insert_selected_function(self, *_args: object) -> None:
        item = self.function_list.currentItem()
        if item is None:
            return
        _function, _syntax, insertion = item.data(Qt.ItemDataRole.UserRole)
        self._insert_formula_text(str(insertion))

    def _insert_parameter(self) -> None:
        name = str(self.parameter_combo.currentData() or "")
        if name:
            self._insert_formula_text(name)

    def _insert_formula_text(self, text: str) -> None:
        cursor = self.expression_edit.textCursor()
        start = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        cursor.insertText(text)
        open_paren = text.find("(")
        if open_paren >= 0:
            placeholder_start = open_paren + 1
            while placeholder_start < len(text) and text[placeholder_start].isspace():
                placeholder_start += 1
            placeholder_end = placeholder_start
            while placeholder_end < len(text) and text[placeholder_end] not in ",)":
                placeholder_end += 1
            if placeholder_end > placeholder_start:
                cursor.setPosition(start + placeholder_start)
                cursor.setPosition(
                    start + placeholder_end,
                    QTextCursor.MoveMode.KeepAnchor,
                )
        self.expression_edit.setTextCursor(cursor)
        self.expression_edit.setFocus()

    def _show_function_help(self, current: QListWidgetItem | None, *_args: object) -> None:
        if current is None:
            self.function_help_label.setText(
                "Choose a function to see its local syntax, then insert it at the caret."
            )
            return
        function, syntax, _insertion = current.data(Qt.ItemDataRole.UserRole)
        self.function_help_label.setText(
            f"<code>{function}</code> · syntax: <code>{syntax}</code> · "
            "Only the displayed local form is supported."
        )

    def _update_syntax_help(self) -> None:
        formula = self.expression_edit.toPlainText().strip()
        lowered = formula.casefold()
        if lowered.startswith("if") and "then" not in lowered:
            text = (
                "Condition: compare fields, literals, and values with and/or/not. "
                "After the condition, add <code>then</code> and the true result, "
                "then <code>else</code> and the fallback."
            )
        elif lowered.startswith("if") and "else" not in lowered:
            text = (
                "The true-result expression comes after <code>then</code>. "
                "Add <code>else</code> followed by the result for a false condition."
            )
        elif lowered.startswith("if"):
            text = (
                "Conditional form: <code>if condition then value_if_true "
                "else value_if_false</code>. Nest another if/then/else for more branches."
            )
        else:
            text = (
                "Use <code>if condition then value_if_true else value_if_false</code> "
                "for conditional results. This editor supports a safe M subset; "
                "it is not a full M runtime."
            )
        self.syntax_help_label.setText(text)

    def _refresh_save_state(self, *_args: object) -> None:
        self.save_button.setEnabled(
            bool(self.name_edit.text().strip() and self.expression_edit.toPlainText().strip())
        )

    def _accept_column(self) -> None:
        name = self.name_edit.text().strip()
        expression = self.expression_edit.toPlainText().strip()
        if not name or not expression:
            self.error_label.setText("Enter a column name and formula.")
            self.error_label.setVisible(True)
            return
        if self._validate_callback is not None:
            error = self._validate_callback(name, expression)
            if error:
                self.error_label.setText(error)
                self.error_label.setVisible(True)
                return
        self._accepted_value = (name, expression)
        super().accept()


class _RibbonScrollArea(QScrollArea):
    """Ribbon page viewport that re-fits its groups whenever its width changes."""

    def __init__(self, parent: QWidget | None, relayout: Callable[[], None]) -> None:
        super().__init__(parent)
        self._relayout = relayout

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()


class _PowerQueryProfileHeader(QHeaderView):
    """Power Query style column names with quality and distribution summaries."""

    filterRequested = Signal(int)

    _HEADER_ROW_HEIGHT = 27
    _FULL_HEIGHT = 148
    _FILTER_BUTTON_SIZE = QSize(23, 21)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._profiles: list[dict[str, Any]] = []
        self._filter_buttons: list[QToolButton] = []
        self._updating_filter_buttons = False
        self._show_quality = True
        self._show_distribution = True
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Power Query preview column headers")
        self.setAccessibleDescription(
            "Use each column's sort and filter button, or click elsewhere in the "
            "column header, to open its options."
        )
        self.setToolTip(
            "Click a column header for sort and filter options. Filter by values "
            "to keep selected values, or filter by condition."
        )
        self.setMinimumSectionSize(150)
        self.setDefaultSectionSize(220)
        self.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.setFixedHeight(self._FULL_HEIGHT)
        self.sectionResized.connect(self._update_filter_buttons)
        self.sectionMoved.connect(self._update_filter_buttons)
        self.geometriesChanged.connect(self._update_filter_buttons)

    def set_profiles(self, profiles: list[dict[str, Any]]) -> None:
        self._profiles = list(profiles)
        self.viewport().update()
        self._update_filter_buttons()

    def set_quality_visible(self, visible: bool) -> None:
        self._show_quality = bool(visible)
        self._update_header_height()

    def set_distribution_visible(self, visible: bool) -> None:
        self._show_distribution = bool(visible)
        self._update_header_height()

    def _update_header_height(self) -> None:
        if self._show_quality and self._show_distribution:
            height = self._FULL_HEIGHT
        elif self._show_quality:
            height = 78
        elif self._show_distribution:
            height = 106
        else:
            height = self._HEADER_ROW_HEIGHT
        self.setFixedHeight(height)
        self.viewport().update()
        self._update_filter_buttons()

    def _filter_button_rect(self, logical_index: int) -> QRect:
        return QRect(
            self.sectionViewportPosition(logical_index)
            + self.sectionSize(logical_index)
            - self._FILTER_BUTTON_SIZE.width()
            - 6,
            3,
            self._FILTER_BUTTON_SIZE.width(),
            self._FILTER_BUTTON_SIZE.height(),
        )

    def _new_filter_button(self) -> QToolButton:
        button = QToolButton(self.viewport())
        button.setObjectName(
            f"powerQueryHeaderFilterButton{len(self._filter_buttons)}"
        )
        button.setArrowType(Qt.ArrowType.DownArrow)
        button.setAutoRaise(False)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setFixedSize(self._FILTER_BUTTON_SIZE)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setProperty("logicalIndex", -1)
        button.setStyleSheet(
            "QToolButton { padding: 0; margin: 0; border: 1px solid #aebbc4; "
            "background: #ffffff; color: #526575; }"
            "QToolButton[filterActive=\"true\"] { border-color: #77aa9c; "
            "background: #e5f2ef; color: #107c71; }"
            "QToolButton:focus { border: 2px solid #0078d4; }"
        )
        button.installEventFilter(self)
        button.clicked.connect(self._filter_button_clicked)
        self._filter_buttons.append(button)
        return button

    def _profile_name(self, logical_index: int) -> str:
        if 0 <= logical_index < len(self._profiles):
            name = self._profiles[logical_index].get("name")
            if name is not None:
                return str(name)
        if self.model() is not None:
            return str(
                self.model().headerData(
                    logical_index,
                    Qt.Orientation.Horizontal,
                    Qt.ItemDataRole.DisplayRole,
                )
                or f"Column {logical_index + 1}"
            )
        return f"Column {logical_index + 1}"

    def _update_filter_buttons(self, *_args: Any) -> None:
        if self._updating_filter_buttons:
            return
        self._updating_filter_buttons = True
        try:
            viewport_rect = self.viewport().rect()
            visible_sections: list[tuple[int, QRect]] = []
            for logical_index in range(self.count()):
                if self.isSectionHidden(logical_index):
                    continue
                rect = self._filter_button_rect(logical_index)
                if viewport_rect.contains(rect):
                    visible_sections.append((logical_index, rect))

            while len(self._filter_buttons) < len(visible_sections):
                self._new_filter_button()

            for slot, (logical_index, rect) in enumerate(visible_sections):
                button = self._filter_buttons[slot]
                if button.property("logicalIndex") != logical_index:
                    if button.hasFocus():
                        self.setFocus(Qt.FocusReason.OtherFocusReason)
                    button.setProperty("logicalIndex", logical_index)
                column_name = self._profile_name(logical_index)
                accessible_name = f"Sort and filter {column_name}"
                if button.accessibleName() != accessible_name:
                    button.setAccessibleName(accessible_name)
                    button.setAccessibleDescription(
                        "Open sort and filter options for "
                        f"{column_name!r} in the Power Query preview."
                    )
                    button.setToolTip(
                        f"Sort or filter {column_name}. Filter by values or condition."
                    )
                profile = (
                    self._profiles[logical_index]
                    if logical_index < len(self._profiles)
                    else {}
                )
                button.setProperty(
                    "filterActive", bool(profile.get("filter_active", False))
                )
                button.style().unpolish(button)
                button.style().polish(button)
                button.setGeometry(rect)
                button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                button.show()
                button.raise_()

            for button in self._filter_buttons[len(visible_sections):]:
                if button.hasFocus():
                    self.setFocus(Qt.FocusReason.OtherFocusReason)
                button.hide()
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.setProperty("logicalIndex", -1)

            visible_buttons = self._filter_buttons[:len(visible_sections)]
            for left, right in zip(visible_buttons, visible_buttons[1:]):
                QWidget.setTabOrder(left, right)
        finally:
            self._updating_filter_buttons = False

    def _filter_button_clicked(self, *_args: Any) -> None:
        button = self.sender()
        if not isinstance(button, QToolButton):
            return
        logical_index = button.property("logicalIndex")
        if isinstance(logical_index, int) and 0 <= logical_index < self.count():
            self.filterRequested.emit(logical_index)

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802
        if watched in self._filter_buttons and event.type() == QEvent.Type.KeyPress:
            modifiers = event.modifiers()
            supported_modifiers = {
                Qt.KeyboardModifier.NoModifier,
                Qt.KeyboardModifier.ShiftModifier,
            }
            is_plain_tab = (
                event.key() == Qt.Key.Key_Tab
                and modifiers == Qt.KeyboardModifier.NoModifier
            )
            is_shift_tab = (
                event.key() == Qt.Key.Key_Tab
                and modifiers == Qt.KeyboardModifier.ShiftModifier
            )
            is_backtab = (
                event.key() == Qt.Key.Key_Backtab
                and modifiers in supported_modifiers
            )
            if is_plain_tab or is_shift_tab or is_backtab:
                direction = -1 if is_shift_tab or is_backtab else 1
                visible_buttons = [
                    button
                    for button in self._filter_buttons
                    if button.isVisible()
                    and button.focusPolicy() != Qt.FocusPolicy.NoFocus
                ]
                if watched not in visible_buttons:
                    return super().eventFilter(watched, event)
                current_index = visible_buttons.index(watched)
                target_index = current_index + direction
                if 0 <= target_index < len(visible_buttons):
                    visible_buttons[target_index].setFocus(
                        Qt.FocusReason.TabFocusReason
                    )
                    return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_filter_buttons()

    def paintSection(
        self, painter: QPainter, rect: Any, logical_index: int
    ) -> None:  # noqa: N802
        if not rect.isValid():
            return
        painter.save()
        painter.fillRect(rect, QColor("#f3f3f3"))
        painter.setPen(QPen(QColor("#d4d4d4"), 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomRight())

        profile = (
            self._profiles[logical_index]
            if logical_index < len(self._profiles)
            else {}
        )
        header = QRect(
            rect.left() + 6,
            rect.top(),
            max(0, rect.width() - 11),
            self._HEADER_ROW_HEIGHT,
        )
        painter.setPen(QColor("#3d4650"))
        type_name = str(profile.get("type", "any"))
        type_glyph = {
            "text": "ABC",
            "whole_number": "123",
            "decimal_number": "1.2",
            "fixed_decimal": "1.2",
            "decimal": "1.2",
            "currency": "1.2",
            "percentage": "%",
            "date": "CAL",
            "datetime": "CAL",
            "datetime_zone": "CAL",
            "time": "CLK",
            "boolean": "T/F",
        }.get(type_name, "ABC")
        painter.setFont(self.font())
        painter.drawText(
            header.adjusted(0, 1, -25, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            f"{type_glyph}  {str(profile.get('name', ''))}",
        )
        filter_active = bool(profile.get("filter_active", False))
        dropdown = QRect(rect.right() - 28, rect.top() + 3, 23, 21)
        painter.fillRect(
            dropdown,
            QColor("#e5f2ef" if filter_active else "#ffffff"),
        )
        painter.setPen(
            QPen(QColor("#77aa9c" if filter_active else "#aebbc4"), 1)
        )
        painter.drawRect(dropdown)
        painter.setPen(QPen(QColor("#107c71" if filter_active else "#526575"), 1.3))
        cx, cy = dropdown.center().x(), dropdown.center().y()
        painter.drawLine(cx - 5, cy - 5, cx + 5, cy - 5)
        painter.drawLine(cx - 5, cy - 5, cx - 1, cy - 1)
        painter.drawLine(cx + 5, cy - 5, cx + 1, cy - 1)
        painter.drawLine(cx - 1, cy - 1, cx - 1, cy + 3)
        painter.drawLine(cx - 1, cy + 3, cx + 2, cy + 5)
        painter.setPen(QPen(QColor("#d0d0d0"), 1))
        painter.drawLine(
            rect.left(),
            rect.top() + self._HEADER_ROW_HEIGHT,
            rect.right(),
            rect.top() + self._HEADER_ROW_HEIGHT,
        )

        y = rect.top() + self._HEADER_ROW_HEIGHT + 5
        if self._show_quality:
            painter.setFont(self.font())
            painter.setPen(QColor("#4d555c"))
            for label, value, color in (
                ("Valid", profile.get("valid", "0%"), "#00a99d"),
                ("Error", profile.get("error", "0%"), "#e35d5b"),
                ("Empty", profile.get("empty", "0%"), "#858b90"),
            ):
                painter.setPen(QPen(QColor(color), 1))
                painter.setBrush(QColor(color))
                painter.drawEllipse(rect.left() + 9, y + 3, 6, 6)
                painter.setPen(QColor("#4d555c"))
                painter.drawText(
                    rect.left() + 21,
                    y,
                    max(40, rect.width() - 56),
                    13,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    label,
                )
                painter.drawText(
                    rect.right() - 40,
                    y,
                    34,
                    13,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(value),
                )
                y += 13

        if self._show_distribution:
            counts = profile.get("frequencies", [])
            chart_top = rect.top() + (76 if self._show_quality else 39)
            chart_bottom = rect.top() + (126 if self._show_quality else 86)
            chart_left = rect.left() + 7
            chart_right = rect.right() - 7
            painter.fillRect(
                chart_left,
                chart_bottom,
                max(0, chart_right - chart_left),
                1,
                QColor("#c8d1d3"),
            )
            if counts:
                max_count = max(counts) or 1
                visible_counts = counts[: max(1, rect.width() // 4)]
                bar_width = max(2.0, (chart_right - chart_left) / len(visible_counts))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#12b7aa"))
                for index, count in enumerate(visible_counts):
                    bar_height = max(
                        2,
                        int((chart_bottom - chart_top) * count / max_count),
                    )
                    left = chart_left + int(index * bar_width)
                    width = max(1, int(bar_width * 0.62))
                    painter.drawRect(
                        left,
                        chart_bottom - bar_height,
                        width,
                        bar_height,
                    )
            painter.setPen(QColor("#606a70"))
            painter.setFont(self.font())
            painter.drawText(
                QRect(
                    rect.left() + 6,
                    chart_bottom + 3,
                    rect.width() - 12,
                    15,
                ),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                f"{profile.get('distinct', 0)} distinct, {profile.get('unique', 0)} unique",
            )
        painter.restore()


class _PowerQueryValueFilterDialog(QDialog):
    """Select exact preview values for a supported local row-filter step."""

    def __init__(
        self,
        column: str,
        values: list[Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self._values = list(values)
        self.setObjectName("powerQueryValueFilterDialog")
        self.setWindowTitle(f"Filter by values — {column}")
        self.setMinimumSize(340, 390)
        self.resize(420, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        guidance = QLabel(
            f"Choose values to keep in {column!r}. The filter will be added as an "
            "applied step."
        )
        guidance.setWordWrap(True)
        layout.addWidget(guidance)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("powerQueryValueFilterSearch")
        self.search_edit.setPlaceholderText("Search values")
        layout.addWidget(self.search_edit)

        self.select_all_checkbox = QCheckBox("Select all visible values")
        self.select_all_checkbox.setObjectName("powerQueryValueFilterSelectAll")
        self.select_all_checkbox.setTristate(True)
        layout.addWidget(self.select_all_checkbox)

        self.value_list = QListWidget()
        self.value_list.setObjectName("powerQueryValueFilterList")
        self._items: list[QListWidgetItem] = []
        labels = [self._display_value(value) for value in self._values]
        label_counts: dict[str, int] = {}
        for label in labels:
            label_counts[label] = label_counts.get(label, 0) + 1
        for index, (value, label) in enumerate(zip(self._values, labels)):
            if label_counts[label] > 1:
                label = f"{label} [{_profile_cell_type(value)}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if len(self._values) <= MAX_FILTER_CLAUSES
                else Qt.CheckState.Unchecked
            )
            self.value_list.addItem(item)
            self._items.append(item)
        layout.addWidget(self.value_list, 1)

        self.selection_note = QLabel()
        self.selection_note.setObjectName("powerQueryValueFilterSelectionNote")
        layout.addWidget(self.selection_note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply filter")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName(
            "applyPowerQueryValueFilterButton"
        )
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.search_edit.textChanged.connect(self._filter_visible_values)
        self.select_all_checkbox.stateChanged.connect(self._select_visible_values)
        self.value_list.itemChanged.connect(self._refresh_selection_state)
        self._refresh_selection_state()

    @staticmethod
    def _display_value(value: Any) -> str:
        if value is None:
            return "(null)"
        if value == "":
            return "(empty text)"
        return cell_to_text(value)

    def _filter_visible_values(self, text: str) -> None:
        needle = text.strip().casefold()
        for item in self._items:
            item.setHidden(needle not in item.text().casefold())
        self._refresh_selection_state()

    def _select_visible_values(self, state: int) -> None:
        visible_items = [item for item in self._items if not item.isHidden()]
        if state == Qt.CheckState.PartiallyChecked.value:
            selected_state = (
                Qt.CheckState.Unchecked
                if visible_items
                and all(
                    item.checkState() == Qt.CheckState.Checked
                    for item in visible_items
                )
                else Qt.CheckState.Checked
            )
        else:
            selected_state = (
                Qt.CheckState.Checked
                if state == Qt.CheckState.Checked.value
                else Qt.CheckState.Unchecked
            )
        for item in visible_items:
            item.setCheckState(selected_state)
        self._refresh_selection_state()

    def _refresh_selection_state(self, *_args: Any) -> None:
        visible_items = [item for item in self._items if not item.isHidden()]
        visible_checked_count = sum(
            item.checkState() == Qt.CheckState.Checked for item in visible_items
        )
        checked_count = sum(
            item.checkState() == Qt.CheckState.Checked for item in self._items
        )
        self.selection_note.setText(
            f"{checked_count:,} selected from {len(self._values):,} values. "
            f"Choose 1–{MAX_FILTER_CLAUSES} values to apply this local filter."
        )
        self.apply_button.setEnabled(0 < checked_count <= MAX_FILTER_CLAUSES)
        if not visible_items or visible_checked_count == 0:
            state = Qt.CheckState.Unchecked
        elif visible_checked_count == len(visible_items):
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        previous = self.select_all_checkbox.blockSignals(True)
        self.select_all_checkbox.setCheckState(state)
        self.select_all_checkbox.blockSignals(previous)

    def selected_values(self) -> list[Any]:
        return [
            self._values[int(item.data(Qt.ItemDataRole.UserRole))]
            for item in self._items
            if item.checkState() == Qt.CheckState.Checked
        ]


_COLUMN_MENU_VALUE_LIMIT = 1_000
_NOT_SUPPORTED_YET = "Not supported yet"
_NUMBER_COLUMN_TYPES = frozenset({
    "whole_number", "decimal_number", "fixed_decimal", "decimal", "currency",
    "percentage", "number",
})
_DATE_COLUMN_TYPES = frozenset({"date", "datetime", "datetime_zone"})


def _is_blank_value(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value == "")


def _column_value_sort_key(value: Any) -> tuple[Any, ...]:
    """Order a column's distinct values the way Power BI lists them (ascending)."""
    if isinstance(value, bool):
        return (0, int(value), "")
    if isinstance(value, (int, float, Decimal)):
        return (1, float(value), "")
    if isinstance(value, (date, datetime, time)):
        return (2, 0.0, value.isoformat())
    text = cell_to_text(value)
    return (3, 0.0, text.casefold() + "\0" + text)


def _column_distinct_values(
    rows: list[dict[str, Any]], column: str
) -> tuple[list[Any], bool, bool, bool]:
    """Return (values, has_blank, truncated, has_errors) for one column.

    Blank (null or empty text) is reported separately. At most
    ``_COLUMN_MENU_VALUE_LIMIT`` distinct values are kept, in first-seen order.
    """
    values: list[Any] = []
    seen: set[tuple[Any, ...]] = set()
    has_blank = False
    truncated = False
    has_errors = False
    for row in rows:
        value = row.get(column)
        if is_cell_error(value):
            has_errors = True
            continue
        if _is_blank_value(value):
            has_blank = True
            continue
        if truncated:
            continue
        key = cell_key(value)
        if key in seen:
            continue
        if len(values) >= _COLUMN_MENU_VALUE_LIMIT:
            truncated = True
            continue
        seen.add(key)
        values.append(value)
    values.sort(key=_column_value_sort_key)
    return values, has_blank, truncated, has_errors


class _PowerQueryConditionDialog(QDialog):
    """Ask for the one or two values of a "Text/Number/Date Filters" condition."""

    def __init__(
        self,
        column: str,
        title: str,
        input_count: int = 1,
        parent: QWidget | None = None,
        *,
        numeric: bool = False,
        placeholder: str = "",
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self._numeric = numeric
        self.setObjectName("powerQueryConditionDialog")
        self.setWindowTitle(f"Filter Rows — {column}")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel(f"Show rows where {column!r} — {title}"))
        form = QFormLayout()
        self.edits: list[QLineEdit] = []
        captions = ["Value"] if input_count == 1 else ["From", "To"][:input_count]
        for caption in captions:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.setAccessibleName(f"{title} {caption.lower()}")
            edit.textChanged.connect(self._refresh_ok)
            form.addRow(caption, edit)
            self.edits.append(edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setObjectName("applyPowerQueryConditionButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_ok()

    def _valid(self, text: str) -> bool:
        if not text.strip():
            return False
        if not self._numeric:
            return True
        try:
            return Decimal(text.strip()).is_finite()
        except Exception:  # noqa: BLE001 - any parse failure means "not a number"
            return False

    def _refresh_ok(self, *_args: Any) -> None:
        self.ok_button.setEnabled(all(self._valid(edit.text()) for edit in self.edits))

    def values(self) -> list[str]:
        return [edit.text().strip() if self._numeric else edit.text() for edit in self.edits]


class _PowerQueryColumnFilterPanel(QWidget):
    """Search box, value checklist and OK / Cancel shown inside a column dropdown."""

    applied = Signal()
    cancelled = Signal()

    def __init__(
        self,
        column: str,
        values: list[Any],
        has_blank: bool,
        truncated: bool,
        *,
        error_message: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("powerQueryColumnFilterPanel")
        self.setMinimumWidth(270)
        self._values = list(values)
        self._has_blank = has_blank
        self._truncated = truncated
        self._guard = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("powerQueryColumnFilterSearch")
        self.search_edit.setPlaceholderText("Search")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setAccessibleName(f"Search values in {column}")
        layout.addWidget(self.search_edit)

        self.value_list = QListWidget()
        self.value_list.setObjectName("powerQueryColumnFilterList")
        self.value_list.setFixedHeight(168)
        self.value_list.setAccessibleName(f"Values in {column}")
        layout.addWidget(self.value_list)

        self.truncated_note = QLabel("List may be incomplete")
        self.truncated_note.setObjectName("powerQueryColumnFilterTruncatedNote")
        self.truncated_note.setStyleSheet("color: #6b747b; font-size: 11px;")
        self.truncated_note.setVisible(truncated)
        layout.addWidget(self.truncated_note)

        self.error_label = QLabel(error_message)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(bool(error_message))
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.ok_button = QPushButton("OK")
        self.ok_button.setObjectName("applyPowerQueryColumnFilterButton")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("cancelPowerQueryColumnFilterButton")
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        self._select_all = self._new_item("(Select All)", None)
        self._select_all.setFlags(
            self._select_all.flags() | Qt.ItemFlag.ItemIsUserTristate
        )
        self._blank_item: QListWidgetItem | None = None
        if has_blank:
            self._blank_item = self._new_item("(Blank)", None)
        labels = [_PowerQueryValueFilterDialog._display_value(v) for v in self._values]
        counts: dict[str, int] = {}
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
        self._value_items: list[QListWidgetItem] = []
        for index, (value, label) in enumerate(zip(self._values, labels)):
            if counts[label] > 1:
                label = f"{label} [{_profile_cell_type(value)}]"
            self._value_items.append(self._new_item(label, index))
        if error_message:
            self.value_list.setEnabled(False)
            self.search_edit.setEnabled(False)

        self.search_edit.textChanged.connect(self._apply_search)
        self.value_list.itemChanged.connect(self._item_changed)
        self.ok_button.clicked.connect(self.applied)
        self.cancel_button.clicked.connect(self.cancelled)
        self._refresh_state()

    def _new_item(self, label: str, index: int | None) -> QListWidgetItem:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, index)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked)
        self.value_list.addItem(item)
        return item

    def _checkable_items(self) -> list[QListWidgetItem]:
        items = list(self._value_items)
        if self._blank_item is not None:
            items.insert(0, self._blank_item)
        return items

    def _apply_search(self, text: str) -> None:
        needle = text.strip().casefold()
        for item in self._checkable_items():
            item.setHidden(needle not in item.text().casefold())
        self._refresh_state()

    def _item_changed(self, item: QListWidgetItem) -> None:
        if self._guard:
            return
        if item is self._select_all:
            state = item.checkState()
            target = (
                Qt.CheckState.Unchecked
                if state == Qt.CheckState.Unchecked
                else Qt.CheckState.Checked
            )
            self._guard = True
            try:
                for member in self._checkable_items():
                    if not member.isHidden():
                        member.setCheckState(target)
            finally:
                self._guard = False
        self._refresh_state()

    def _refresh_state(self) -> None:
        visible = [item for item in self._checkable_items() if not item.isHidden()]
        checked = sum(item.checkState() == Qt.CheckState.Checked for item in visible)
        if visible and checked == len(visible):
            state = Qt.CheckState.Checked
        elif checked == 0:
            state = Qt.CheckState.Unchecked
        else:
            state = Qt.CheckState.PartiallyChecked
        self._guard = True
        try:
            self._select_all.setCheckState(state)
        finally:
            self._guard = False
        any_checked = any(
            item.checkState() == Qt.CheckState.Checked
            for item in self._checkable_items()
        )
        self.ok_button.setEnabled(any_checked and not self.error_label.isVisible())

    def selection(self) -> dict[str, Any]:
        selected = [
            self._values[int(item.data(Qt.ItemDataRole.UserRole))]
            for item in self._value_items
            if item.checkState() == Qt.CheckState.Checked
        ]
        excluded = [
            self._values[int(item.data(Qt.ItemDataRole.UserRole))]
            for item in self._value_items
            if item.checkState() != Qt.CheckState.Checked
        ]
        blank_selected = (
            self._blank_item is None
            or self._blank_item.checkState() == Qt.CheckState.Checked
        )
        return {
            "selected": selected,
            "excluded": excluded,
            "has_blank": self._has_blank,
            "blank_selected": blank_selected,
            "truncated": self._truncated,
        }


class _PreviewColumnMenu:
    """A built column dropdown: the QMenu, its filter panel and its action handlers."""

    def __init__(self, menu: QMenu, column: str) -> None:
        self.menu = menu
        self.column = column
        self.panel: _PowerQueryColumnFilterPanel | None = None
        self.widget_action: QWidgetAction | None = None
        self.chosen: Callable[[], None] | None = None
        self._actions: dict[str, QAction] = {}
        self._handlers: list[tuple[QAction, Callable[[], None]]] = []

    def register(
        self, path: str, action: QAction, handler: Callable[[], None] | None = None
    ) -> None:
        self._actions[path] = action
        if handler is not None:
            self._handlers.append((action, handler))
            action.triggered.connect(
                lambda _checked=False, target=handler: setattr(self, "chosen", target)
            )

    def action(self, path: str) -> QAction:
        return self._actions[path]

    def handler_for(self, action: QAction | None) -> Callable[[], None] | None:
        if action is not None:
            for candidate, handler in self._handlers:
                if candidate is action:
                    return handler
        return self.chosen

    def trigger(self, path: str) -> None:
        action = self.action(path)
        handler = next(
            (candidate for owner, candidate in self._handlers if owner is action), None
        )
        if handler is None or not action.isEnabled():
            raise AssertionError(f"Menu item {path!r} is not an enabled command.")
        handler()


def _candidate_with_source_id(
    candidate: ImportCandidate, source_id: str
) -> ImportCandidate:
    """Give a query result its saved identity without changing row origins."""
    result = copy(candidate)
    result.source_id = source_id
    return result


def _profile_cell_type(value: Any) -> str:
    if is_cell_error(value):
        return "error"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float, Decimal)):
        return "number"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, time):
        return "time"
    return "text"


class EnterDataDialog(QDialog):
    """Create one table from typed CSV or tab-separated clipboard contents."""

    def __init__(
        self,
        *,
        replacing: bool,
        initial_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self.replacing = replacing
        self._accepted_candidate: ImportCandidate | None = None
        self._preview_candidate: ImportCandidate | None = None
        self.setWindowTitle("Enter data")
        self.setMinimumSize(620, 440)
        self.resize(820, 590)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(9)

        title = QLabel("Create a table from pasted or typed data")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)

        self.replacement_label = QLabel(
            "Creating this table will replace the data source currently loaded in this report."
        )
        self.replacement_label.setWordWrap(True)
        self.replacement_label.setStyleSheet(
            "padding: 7px 9px; color: #6a4d00; background: #fff5d6;"
            "border: 1px solid #e8d391; border-radius: 3px;"
        )
        self.replacement_label.setVisible(replacing)
        layout.addWidget(self.replacement_label)

        name_form = QFormLayout()
        self.name_edit = QLineEdit("Entered data")
        self.name_edit.setMaxLength(120)
        name_form.addRow("Table name", self.name_edit)
        layout.addLayout(name_form)

        help_text = QLabel("Use the first row for column names. Paste cells from Excel or enter comma/tab-separated text.")
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #526477;")
        layout.addWidget(help_text)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Product\tRegion\tRevenue\nCamera\tWest\t240")
        self.text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text_edit.setPlainText(initial_text)
        layout.addWidget(self.text_edit, 1)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.preview = QTableView()
        self.preview.setMinimumHeight(120)
        self.preview.setMaximumHeight(190)
        self.preview.setAlternatingRowColors(True)
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.setModel(ImportPreviewTableModel(self.preview))
        layout.addWidget(self.preview)

        self.count_label = QLabel("Enter data to see a preview.")
        self.count_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.count_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.create_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.create_button.setText("Create table")
        self.create_button.setEnabled(False)
        self.buttons.accepted.connect(self._accept_candidate)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.name_edit.textChanged.connect(self._refresh_preview)
        self.text_edit.textChanged.connect(self._refresh_preview)
        self._refresh_preview()

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    def _refresh_preview(self, *_args: Any) -> None:
        model = self.preview.model()
        assert isinstance(model, ImportPreviewTableModel)
        self._preview_candidate = None
        try:
            candidate = parse_pasted_table(
                self.text_edit.toPlainText(), name=self.name_edit.text().strip()
            )
        except (TypeError, ValueError) as exc:
            model.set_candidate(None)
            self.error_label.setText(str(exc))
            self.error_label.setVisible(bool(self.text_edit.toPlainText().strip()))
            self.count_label.setText("No preview is available until the table is valid.")
            self.create_button.setEnabled(False)
            return

        self._preview_candidate = candidate
        model.set_candidate(candidate)
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.count_label.setText(
            f"{len(candidate.headers):,} columns · {candidate.row_count:,} rows"
        )
        self.create_button.setEnabled(bool(candidate.headers))

    def _accept_candidate(self) -> None:
        if self._preview_candidate is None:
            return
        self._accepted_candidate = self._preview_candidate
        super().accept()

    def reject(self) -> None:
        self._accepted_candidate = None
        super().reject()


class AppendQueriesDialog(QDialog):
    """Choose two loaded tables, validate their schema, and preview an append."""

    def __init__(
        self,
        tables: list[dict[str, str]],
        candidates: dict[str, ImportCandidate],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self._candidates = dict(candidates)
        self._accepted_candidate: ImportCandidate | None = None
        self._accepted_source_ids: list[str] = []
        self.setWindowTitle("Append queries")
        self.setMinimumSize(680, 450)
        self.resize(860, 570)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(9)
        title = QLabel("Append rows from two loaded tables")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)

        form = QFormLayout()
        self.query_name_edit = QLineEdit("Append query")
        self.query_name_edit.setMaxLength(120)
        self.first_combo = QComboBox()
        self.second_combo = QComboBox()
        for table in tables:
            source_id = str(table["sourceId"])
            name = str(table["displayName"])
            self.first_combo.addItem(name, source_id)
            self.second_combo.addItem(name, source_id)
        if self.second_combo.count() > 1:
            self.second_combo.setCurrentIndex(1)
        form.addRow("Query name", self.query_name_edit)
        form.addRow("First table", self.first_combo)
        form.addRow("Second table", self.second_combo)
        layout.addLayout(form)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.preview = QTableView()
        self.preview.setAlternatingRowColors(True)
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.setModel(ImportPreviewTableModel(self.preview))
        layout.addWidget(self.preview, 1)

        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.count_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.create_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.create_button.setText("Create query")
        self.create_button.setEnabled(False)
        self.buttons.accepted.connect(self._accept_query)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.first_combo.currentIndexChanged.connect(self._refresh_preview)
        self.second_combo.currentIndexChanged.connect(self._refresh_preview)
        self.query_name_edit.textChanged.connect(self._refresh_preview)
        self._refresh_preview()

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def source_ids(self) -> list[str]:
        return list(self._accepted_source_ids)

    @property
    def query_name(self) -> str:
        return self.query_name_edit.text().strip()

    def _refresh_preview(self, *_args: Any) -> None:
        first_id = str(self.first_combo.currentData() or "")
        second_id = str(self.second_combo.currentData() or "")
        model = self.preview.model()
        assert isinstance(model, ImportPreviewTableModel)
        self._accepted_candidate = None
        self.create_button.setEnabled(False)
        if not self.query_name:
            model.set_candidate(None)
            self._show_error("Enter a name for the appended query.")
            self.count_label.setText("No append preview is available.")
            return
        if not first_id or not second_id or first_id == second_id:
            model.set_candidate(None)
            self._show_error("Choose two different source tables.")
            self.count_label.setText("No append preview is available.")
            return
        try:
            candidate = append_candidates([
                self._candidates[first_id],
                self._candidates[second_id],
            ])
        except (KeyError, QueryError) as exc:
            model.set_candidate(None)
            self._show_error(str(exc))
            self.count_label.setText("No append preview is available.")
            return
        self._accepted_candidate = candidate
        model.set_candidate(candidate)
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.count_label.setText(
            f"{len(candidate.headers):,} columns · {candidate.row_count:,} rows after append; previewing the first 100 rows"
        )
        self.create_button.setEnabled(True)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _accept_query(self) -> None:
        self._refresh_preview()
        if self._accepted_candidate is None:
            return
        self._accepted_source_ids = [
            str(self.first_combo.currentData()),
            str(self.second_combo.currentData()),
        ]
        super().accept()


class CalculatedTableDialog(QDialog):
    """Create a distinct-value calculated table from one loaded model column."""

    def __init__(
        self,
        tables: list[dict[str, Any]],
        candidates: dict[str, ImportCandidate],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self._tables = [dict(table) for table in tables]
        self._candidates = dict(candidates)
        self._accepted_candidate: ImportCandidate | None = None
        self._accepted_source_id = ""
        self._accepted_definition: dict[str, Any] = {}
        self._accepted_output_types: dict[str, str] = {}
        self.setWindowTitle("New calculated table")
        self.setMinimumSize(680, 470)
        self.resize(820, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(9)
        title = QLabel("Create a calculated table from distinct column values")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)
        help_label = QLabel(
            "This local DAX subset supports DISTINCT('Table'[Column]). "
            "The result keeps one copy of each exact value, including blank, "
            "in the order first seen. It recalculates when its source refreshes."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #526477;")
        layout.addWidget(help_label)

        form = QFormLayout()
        self.table_name_edit = QLineEdit("Distinct values")
        self.table_name_edit.setMaxLength(120)
        self.source_combo = QComboBox()
        self.column_combo = QComboBox()
        for table in self._tables:
            self.source_combo.addItem(
                str(table.get("displayName", table.get("name", "Table"))),
                str(table.get("sourceId", "")),
            )
        self.expression_edit = QLineEdit()
        self.expression_edit.setReadOnly(True)
        self.expression_edit.setAccessibleName("Calculated table DAX expression")
        form.addRow("Table name", self.table_name_edit)
        form.addRow("Source table", self.source_combo)
        form.addRow("Source column", self.column_combo)
        form.addRow("DAX expression", self.expression_edit)
        layout.addLayout(form)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.preview = QTableView()
        self.preview.setAlternatingRowColors(True)
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.setModel(ImportPreviewTableModel(self.preview))
        layout.addWidget(self.preview, 1)

        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.count_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.create_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.create_button.setText("Create table")
        self.create_button.setEnabled(False)
        self.buttons.accepted.connect(self._accept_table)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.source_combo.currentIndexChanged.connect(self._refresh_columns)
        self.column_combo.currentIndexChanged.connect(self._refresh_preview)
        self.table_name_edit.textChanged.connect(self._refresh_preview)
        self._refresh_columns()

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def source_ids(self) -> list[str]:
        return [self._accepted_source_id] if self._accepted_source_id else []

    @property
    def query_definition(self) -> dict[str, Any]:
        return deepcopy(self._accepted_definition)

    @property
    def query_name(self) -> str:
        return self.table_name_edit.text().strip()

    @property
    def output_types(self) -> dict[str, str]:
        return dict(self._accepted_output_types)

    def _selected_table(self) -> dict[str, Any] | None:
        source_id = str(self.source_combo.currentData() or "")
        return next(
            (table for table in self._tables if str(table.get("sourceId", "")) == source_id),
            None,
        )

    def _refresh_columns(self, *_args: Any) -> None:
        table = self._selected_table()
        headers = [str(header) for header in (table or {}).get("headers", [])]
        previous = self.column_combo.currentText()
        self.column_combo.blockSignals(True)
        self.column_combo.clear()
        self.column_combo.addItems(headers)
        if previous in headers:
            self.column_combo.setCurrentText(previous)
        self.column_combo.blockSignals(False)
        self._refresh_preview()

    def _refresh_preview(self, *_args: Any) -> None:
        model = self.preview.model()
        assert isinstance(model, ImportPreviewTableModel)
        model.set_candidate(None)
        self._accepted_candidate = None
        self._accepted_definition = {}
        self._accepted_output_types = {}
        self.create_button.setEnabled(False)
        table = self._selected_table()
        source_id = str(self.source_combo.currentData() or "")
        column = self.column_combo.currentText()
        if not self.query_name or "\x00" in self.query_name:
            self._show_error("Enter a valid name for the calculated table.")
            self.expression_edit.clear()
            self.count_label.setText("No calculated-table preview is available.")
            return
        if table is None or not source_id or not column:
            self._show_error("Choose a loaded source table and column.")
            self.expression_edit.clear()
            self.count_label.setText("No calculated-table preview is available.")
            return
        source_name = str(table.get("name", ""))
        escaped_table = source_name.replace("'", "''")
        expression = f"DISTINCT('{escaped_table}'[{column}])"
        self.expression_edit.setText(expression)
        try:
            definition = normalize_calculated_table_expression(
                expression, source_name, table.get("headers", [])
            )
            source_candidate = self._candidates[source_id]
            headers, rows = evaluate_calculated_table(
                definition["expression"], source_candidate, source_name
            )
            candidate = ImportCandidate(
                kind="query", headers=headers, rows=rows, options={}, notices=[]
            )
        except (KeyError, MeasureError) as exc:
            self._show_error(str(exc))
            self.count_label.setText("No calculated-table preview is available.")
            return
        model.set_candidate(candidate)
        self._accepted_candidate = candidate
        self._accepted_source_id = source_id
        self._accepted_definition = {
            "operation": "calculated_table",
            "source_ids": [source_id],
            "expression": definition["expression"],
            "source_table": source_name,
        }
        source_types = table.get("columnTypes", {})
        self._accepted_output_types = {
            headers[0]: str(source_types.get(headers[0], "text"))
        }
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.count_label.setText(
            f"1 column · {candidate.row_count:,} distinct rows; previewing the first 100 rows"
        )
        self.create_button.setEnabled(True)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _accept_table(self) -> None:
        self._refresh_preview()
        if self._accepted_candidate is None:
            return
        super().accept()


class MergeQueriesDialog(QDialog):
    """Configure, validate, and preview a saved local table merge."""

    _JOIN_OPTIONS = [
        ("Left outer · keep all left rows", "left_outer"),
        ("Right outer · keep all right rows", "right_outer"),
        ("Full outer · keep rows from both", "full_outer"),
        ("Inner · keep matching rows", "inner"),
        ("Left anti · left rows without a match", "left_anti"),
        ("Right anti · right rows without a match", "right_anti"),
    ]

    def __init__(
        self,
        tables: list[dict[str, str]],
        candidates: dict[str, ImportCandidate],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self._tables = [dict(table) for table in tables]
        self._candidates = dict(candidates)
        self._accepted_candidate: ImportCandidate | None = None
        self._accepted_query_definition: dict[str, Any] | None = None
        self._key_pair_rows: list[dict[str, Any]] = []
        self.setWindowTitle("Merge queries")
        self.setMinimumSize(760, 560)
        self.resize(980, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(9)
        title = QLabel("Merge two loaded tables into a saved query")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)

        form = QFormLayout()
        self.query_name_edit = QLineEdit("Merge query")
        self.query_name_edit.setMaxLength(120)
        self.left_combo = QComboBox()
        self.right_combo = QComboBox()
        for table in self._tables:
            source_id = str(table["sourceId"])
            name = str(table["displayName"])
            self.left_combo.addItem(name, source_id)
            self.right_combo.addItem(name, source_id)
        if self.right_combo.count() > 1:
            self.right_combo.setCurrentIndex(1)
        self.join_kind_combo = QComboBox()
        for label, value in self._JOIN_OPTIONS:
            self.join_kind_combo.addItem(label, value)
        form.addRow("Query name", self.query_name_edit)
        form.addRow("Left table", self.left_combo)
        form.addRow("Right table", self.right_combo)
        form.addRow("Join kind", self.join_kind_combo)
        layout.addLayout(form)

        key_title = QLabel("Matching key columns")
        key_title.setStyleSheet("font-weight: 600; color: #273b49;")
        layout.addWidget(key_title)
        key_help = QLabel(
            "Add one or more column pairs. Each left column matches the right column on its row. "
            "Values compare exactly; blank keys do not match."
        )
        key_help.setWordWrap(True)
        key_help.setStyleSheet("color: #526477;")
        layout.addWidget(key_help)
        self.key_pairs_container = QWidget()
        self.key_pairs_layout = QVBoxLayout(self.key_pairs_container)
        self.key_pairs_layout.setContentsMargins(0, 0, 0, 0)
        self.key_pairs_layout.setSpacing(4)
        layout.addWidget(self.key_pairs_container)
        self.add_key_pair_button = QPushButton("Add key pair")
        layout.addWidget(self.add_key_pair_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.preview = QTableView()
        self.preview.setAlternatingRowColors(True)
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.setModel(ImportPreviewTableModel(self.preview))
        layout.addWidget(self.preview, 1)

        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.count_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.create_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.create_button.setText("Create query")
        self.create_button.setEnabled(False)
        self.buttons.accepted.connect(self._accept_query)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.left_combo.currentIndexChanged.connect(self._sources_changed)
        self.right_combo.currentIndexChanged.connect(self._sources_changed)
        self.join_kind_combo.currentIndexChanged.connect(self._refresh_preview)
        self.query_name_edit.textChanged.connect(self._refresh_preview)
        self.add_key_pair_button.clicked.connect(self._add_key_pair)
        self._sources_changed()

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def query_definition(self) -> dict[str, Any]:
        return deepcopy(self._accepted_query_definition or {})

    @property
    def query_name(self) -> str:
        return self.query_name_edit.text().strip()

    def _selected_ids(self) -> tuple[str, str]:
        return (
            str(self.left_combo.currentData() or ""),
            str(self.right_combo.currentData() or ""),
        )

    def _clear_key_pairs(self) -> None:
        while self.key_pairs_layout.count():
            item = self.key_pairs_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._key_pair_rows.clear()

    def _sources_changed(self, *_args: Any) -> None:
        self._clear_key_pairs()
        left_id, right_id = self._selected_ids()
        left = self._candidates.get(left_id)
        right = self._candidates.get(right_id)
        if left is not None and right is not None and left.headers and right.headers:
            common = next((name for name in left.headers if name in right.headers), None)
            self._append_key_pair(left.headers, right.headers, common, common)
        self._refresh_preview()

    def _append_key_pair(
        self,
        left_headers: list[str],
        right_headers: list[str],
        left_value: str | None = None,
        right_value: str | None = None,
    ) -> None:
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        left_combo = QComboBox()
        right_combo = QComboBox()
        left_combo.addItems(left_headers)
        right_combo.addItems(right_headers)
        if left_value is not None:
            left_combo.setCurrentIndex(max(0, left_combo.findText(left_value)))
        if right_value is not None:
            right_combo.setCurrentIndex(max(0, right_combo.findText(right_value)))
        remove_button = QPushButton("Remove")
        row_layout.addWidget(QLabel("Left"))
        row_layout.addWidget(left_combo, 1)
        row_layout.addWidget(QLabel("matches"))
        row_layout.addWidget(QLabel("Right"))
        row_layout.addWidget(right_combo, 1)
        row_layout.addWidget(remove_button)
        self.key_pairs_layout.addWidget(row_widget)
        pair = {
            "widget": row_widget,
            "left": left_combo,
            "right": right_combo,
            "remove": remove_button,
        }
        self._key_pair_rows.append(pair)
        left_combo.currentIndexChanged.connect(self._refresh_preview)
        right_combo.currentIndexChanged.connect(self._refresh_preview)
        remove_button.clicked.connect(
            lambda _checked=False, selected=pair: self._remove_key_pair(selected)
        )
        self._update_key_pair_controls()

    def _add_key_pair(self, *_args: Any) -> None:
        left_id, right_id = self._selected_ids()
        left = self._candidates.get(left_id)
        right = self._candidates.get(right_id)
        if left is None or right is None:
            return
        used_left = {str(pair["left"].currentText()) for pair in self._key_pair_rows}
        used_right = {str(pair["right"].currentText()) for pair in self._key_pair_rows}
        next_left = next((name for name in left.headers if name not in used_left), None)
        next_right = next((name for name in right.headers if name not in used_right), None)
        if next_left is None or next_right is None:
            self._show_error("There are no unused columns available for another key pair.")
            return
        self._append_key_pair(left.headers, right.headers, next_left, next_right)
        self._refresh_preview()

    def _remove_key_pair(self, pair: dict[str, Any]) -> None:
        if len(self._key_pair_rows) <= 1:
            return
        self._key_pair_rows.remove(pair)
        pair["widget"].deleteLater()
        self._update_key_pair_controls()
        self._refresh_preview()

    def _update_key_pair_controls(self) -> None:
        can_remove = len(self._key_pair_rows) > 1
        for pair in self._key_pair_rows:
            pair["remove"].setEnabled(can_remove)
        left_id, right_id = self._selected_ids()
        left = self._candidates.get(left_id)
        right = self._candidates.get(right_id)
        self.add_key_pair_button.setEnabled(
            left is not None and right is not None
            and len(self._key_pair_rows) < min(len(left.headers), len(right.headers))
        )

    def _refresh_preview(self, *_args: Any) -> None:
        model = self.preview.model()
        assert isinstance(model, ImportPreviewTableModel)
        self._accepted_candidate = None
        self._accepted_query_definition = None
        self.create_button.setEnabled(False)
        if not self.query_name:
            model.set_candidate(None)
            self._show_error("Enter a name for the merged query.")
            self.count_label.setText("No merge preview is available.")
            return
        left_id, right_id = self._selected_ids()
        if not left_id or not right_id or left_id == right_id:
            model.set_candidate(None)
            self._show_error("Choose two different source tables.")
            self.count_label.setText("No merge preview is available.")
            return
        if not self._key_pair_rows:
            model.set_candidate(None)
            self._show_error("Add at least one matching key pair.")
            self.count_label.setText("No merge preview is available.")
            return
        left_keys = [str(pair["left"].currentText()) for pair in self._key_pair_rows]
        right_keys = [str(pair["right"].currentText()) for pair in self._key_pair_rows]
        if len(set(left_keys)) != len(left_keys) or len(set(right_keys)) != len(right_keys):
            model.set_candidate(None)
            self._show_error("Each source column can only be used once as a merge key.")
            self.count_label.setText("No merge preview is available.")
            return
        try:
            right_name = str(self.right_combo.currentText())
            candidate = merge_candidates(
                self._candidates[left_id],
                self._candidates[right_id],
                left_keys=left_keys,
                right_keys=right_keys,
                join_kind=str(self.join_kind_combo.currentData()),
                right_name=right_name,
            )
        except (KeyError, QueryError) as exc:
            model.set_candidate(None)
            self._show_error(str(exc))
            self.count_label.setText("No merge preview is available.")
            return
        self._accepted_candidate = candidate
        self._accepted_query_definition = {
            "operation": "merge",
            "source_ids": [left_id, right_id],
            "left_keys": left_keys,
            "right_keys": right_keys,
            "join_kind": str(self.join_kind_combo.currentData()),
            "right_name": right_name,
        }
        model.set_candidate(candidate)
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.count_label.setText(
            f"{len(candidate.headers):,} columns · {candidate.row_count:,} rows after merge; "
            "right-side columns are expanded in the preview (first 100 rows shown)"
        )
        self.create_button.setEnabled(True)

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _accept_query(self) -> None:
        self._refresh_preview()
        if self._accepted_candidate is None:
            return
        super().accept()


class QueryParameterDefinitionDialog(QDialog):
    """Create or edit one validated scalar Power Query parameter."""

    def __init__(
        self, parameter: dict[str, str] | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        parameter = dict(parameter or {})
        self.parameter: dict[str, str] | None = None
        self.setWindowTitle("Power Query Parameter")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        title = QLabel("Parameter properties")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        layout.addWidget(title)
        form = QFormLayout()
        self.name_edit = QLineEdit(parameter.get("name", ""))
        self.name_edit.setObjectName("powerQueryParameterName")
        self.name_edit.setPlaceholderText("e.g. MinimumRevenue")
        form.addRow("Name", self.name_edit)
        self.type_combo = QComboBox()
        self.type_combo.setObjectName("powerQueryParameterType")
        type_labels = {
            "text": "Text", "whole_number": "Whole number",
            "decimal_number": "Decimal number", "boolean": "True/False",
            "date": "Date", "datetime": "DateTime",
        }
        for type_name in QUERY_PARAMETER_TYPES:
            self.type_combo.addItem(type_labels[type_name], type_name)
        current_type = parameter.get("type", "text")
        type_index = self.type_combo.findData(current_type)
        self.type_combo.setCurrentIndex(max(type_index, 0))
        form.addRow("Type", self.type_combo)
        self.value_edit = QLineEdit(parameter.get("current_value", ""))
        self.value_edit.setObjectName("powerQueryParameterValue")
        form.addRow("Current value", self.value_edit)
        self.description_edit = QLineEdit(parameter.get("description", ""))
        self.description_edit.setObjectName("powerQueryParameterDescription")
        form.addRow("Description", self.description_edit)
        layout.addLayout(form)
        self.error_label = QLabel()
        self.error_label.setObjectName("powerQueryParameterError")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save parameter")
        buttons.accepted.connect(self._accept_parameter)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_parameter(self) -> None:
        try:
            self.parameter = normalize_query_parameter({
                "name": self.name_edit.text(),
                "type": str(self.type_combo.currentData()),
                "current_value": self.value_edit.text(),
                "description": self.description_edit.text(),
            })
        except QueryParameterError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            self.parameter = None
            return
        super().accept()


class ManageQueryParametersDialog(QDialog):
    """Stage project parameters and return them only after the user applies."""

    def __init__(
        self, parameters: list[dict[str, str]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self._parameters = validate_query_parameters(deepcopy(parameters))
        self._accepted_parameters: list[dict[str, str]] | None = None
        self.setWindowTitle("Manage Power Query Parameters")
        self.setMinimumSize(620, 420)
        layout = QVBoxLayout(self)
        title = QLabel("Manage Parameters")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)
        note = QLabel(
            "Parameters are saved with the project. In Advanced Editor, reference a parameter by name in a supported row filter."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 4, self)
        self.table.setObjectName("powerQueryParameterTable")
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Current value", "Description"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.new_button = QPushButton("New parameter")
        self.new_button.setObjectName("newPowerQueryParameterButton")
        self.edit_button = QPushButton("Edit")
        self.edit_button.setObjectName("editPowerQueryParameterButton")
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("deletePowerQueryParameterButton")
        actions.addWidget(self.new_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        footer = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply,
            parent=self,
        )
        footer.button(QDialogButtonBox.StandardButton.Apply).setText("Apply parameters")
        footer.accepted.connect(self._accept_parameters)
        footer.rejected.connect(self.reject)
        layout.addWidget(footer)
        self.new_button.clicked.connect(self._new_parameter)
        self.edit_button.clicked.connect(self._edit_parameter)
        self.delete_button.clicked.connect(self._delete_parameter)
        self.table.currentCellChanged.connect(lambda *_args: self._update_actions())
        self._render_parameters()

    @property
    def parameters(self) -> list[dict[str, str]] | None:
        return deepcopy(self._accepted_parameters)

    def _render_parameters(self, selected_name: str = "") -> None:
        self.table.setRowCount(len(self._parameters))
        labels = {
            "text": "Text", "whole_number": "Whole number",
            "decimal_number": "Decimal number", "boolean": "True/False",
            "date": "Date", "datetime": "DateTime",
        }
        for row, parameter in enumerate(self._parameters):
            for column, value in enumerate((
                parameter["name"], labels[parameter["type"]],
                parameter["current_value"], parameter.get("description", ""),
            )):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, parameter["name"])
                self.table.setItem(row, column, item)
            if parameter["name"] == selected_name:
                self.table.selectRow(row)
        if self._parameters and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self._update_actions()

    def _selected_index(self) -> int:
        return self.table.currentRow()

    def _update_actions(self) -> None:
        selected = 0 <= self._selected_index() < len(self._parameters)
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

    def _new_parameter(self) -> None:
        dialog = QueryParameterDefinitionDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.parameter is None:
            return
        try:
            candidate = validate_query_parameters([*self._parameters, dialog.parameter])
        except QueryParameterError as exc:
            QMessageBox.warning(self, "Duplicate parameter", str(exc))
            return
        self._parameters = candidate
        self._render_parameters(dialog.parameter["name"])

    def _edit_parameter(self) -> None:
        index = self._selected_index()
        if not 0 <= index < len(self._parameters):
            return
        original = self._parameters[index]
        dialog = QueryParameterDefinitionDialog(original, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.parameter is None:
            return
        candidate = list(self._parameters)
        candidate[index] = dialog.parameter
        try:
            self._parameters = validate_query_parameters(candidate)
        except QueryParameterError as exc:
            QMessageBox.warning(self, "Duplicate parameter", str(exc))
            return
        self._render_parameters(dialog.parameter["name"])

    def _delete_parameter(self) -> None:
        index = self._selected_index()
        if 0 <= index < len(self._parameters):
            removed = self._parameters.pop(index)
            self._render_parameters()
            self.setWindowTitle(f"Manage Power Query Parameters · removed {removed['name']}")

    def _accept_parameters(self) -> None:
        try:
            self._accepted_parameters = validate_query_parameters(self._parameters)
        except QueryParameterError as exc:
            QMessageBox.warning(self, "Invalid parameters", str(exc))
            return
        super().accept()


class QueryFunctionDefinitionDialog(QDialog):
    """Create or edit one safe, reusable scalar Power Query function."""

    def __init__(
        self,
        function: dict[str, str] | None = None,
        parent: QWidget | None = None,
        *,
        name_locked: bool = False,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        function = dict(function or {})
        self.function: dict[str, str] | None = None
        self.setWindowTitle("Power Query Function")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        title = QLabel("Function properties")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        layout.addWidget(title)
        form = QFormLayout()
        self.name_edit = QLineEdit(function.get("name", ""))
        self.name_edit.setObjectName("powerQueryFunctionName")
        self.name_edit.setEnabled(not name_locked)
        self.name_edit.setPlaceholderText("e.g. NormalizeName")
        form.addRow("Function name", self.name_edit)
        self.parameter_edit = QLineEdit(function.get("parameter", "Value"))
        self.parameter_edit.setObjectName("powerQueryFunctionParameter")
        form.addRow("Parameter", self.parameter_edit)
        type_labels = {
            "text": "Text", "whole_number": "Whole number",
            "decimal_number": "Decimal number", "boolean": "True/False",
            "date": "Date", "datetime": "DateTime",
        }
        self.parameter_type_combo = QComboBox()
        self.parameter_type_combo.setObjectName("powerQueryFunctionParameterType")
        self.return_type_combo = QComboBox()
        self.return_type_combo.setObjectName("powerQueryFunctionReturnType")
        for type_name in QUERY_FUNCTION_TYPES:
            self.parameter_type_combo.addItem(type_labels[type_name], type_name)
            self.return_type_combo.addItem(type_labels[type_name], type_name)
        for combo, key in (
            (self.parameter_type_combo, "parameter_type"),
            (self.return_type_combo, "return_type"),
        ):
            index = combo.findData(function.get(key, "text"))
            combo.setCurrentIndex(max(index, 0))
        form.addRow("Parameter type", self.parameter_type_combo)
        form.addRow("Result type", self.return_type_combo)
        self.expression_edit = QPlainTextEdit(function.get("expression", ""))
        self.expression_edit.setObjectName("powerQueryFunctionExpression")
        self.expression_edit.setPlaceholderText('Text.Upper(Text.Trim(Value))')
        self.expression_edit.setMaximumHeight(110)
        form.addRow("M expression", self.expression_edit)
        self.description_edit = QLineEdit(function.get("description", ""))
        self.description_edit.setObjectName("powerQueryFunctionDescription")
        form.addRow("Description", self.description_edit)
        layout.addLayout(form)
        preview_row = QHBoxLayout()
        self.preview_button = QPushButton("Validate and preview")
        self.preview_button.setObjectName("previewPowerQueryFunctionButton")
        self.preview_result = QLabel("Enter an expression to preview it with a sample value.")
        self.preview_result.setObjectName("powerQueryFunctionPreview")
        self.preview_result.setWordWrap(True)
        preview_row.addWidget(self.preview_button)
        preview_row.addWidget(self.preview_result, 1)
        layout.addLayout(preview_row)
        self.error_label = QLabel()
        self.error_label.setObjectName("powerQueryFunctionError")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save function")
        buttons.accepted.connect(self._accept_function)
        buttons.rejected.connect(self.reject)
        self.preview_button.clicked.connect(self._preview_function)
        layout.addWidget(buttons)

    def _definition(self) -> dict[str, str]:
        return normalize_query_function({
            "name": self.name_edit.text(),
            "parameter": self.parameter_edit.text(),
            "parameter_type": str(self.parameter_type_combo.currentData()),
            "return_type": str(self.return_type_combo.currentData()),
            "expression": self.expression_edit.toPlainText(),
            "description": self.description_edit.text(),
        })

    def _preview_function(self) -> None:
        try:
            from analytics_studio.power_query_expression import (
                compile_expression,
                evaluate_expression,
                expression_value_to_text,
            )
            from analytics_studio.query_functions import (
                coerce_function_argument,
                validate_function_result,
            )

            definition = self._definition()
            sample_text = {
                "text": "Sample",
                "whole_number": "7",
                "decimal_number": "7.5",
                "boolean": "true",
                "date": "2026-01-15",
                "datetime": "2026-01-15T12:30:00",
            }[definition["parameter_type"]]
            sample = coerce_function_argument(
                definition["parameter_type"], sample_text
            )
            body = compile_expression(
                definition["expression"],
                allowed_symbols={definition["parameter"]},
            )
            result = evaluate_expression(
                body, {}, {definition["parameter"]: sample}
            )
            result = validate_function_result(definition["return_type"], result)
            self.preview_result.setText(
                f"Sample result: {expression_value_to_text(result)}"
            )
            self.error_label.clear()
            self.error_label.setVisible(False)
        except (QueryFunctionError, ValueError) as exc:
            self.preview_result.setText("Preview is unavailable.")
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)

    def _accept_function(self) -> None:
        try:
            self.function = self._definition()
            from analytics_studio.power_query_expression import (
                compile_expression,
                evaluate_expression,
            )
            from analytics_studio.query_functions import (
                coerce_function_argument,
                validate_function_result,
            )
            sample_text = {
                "text": "Sample",
                "whole_number": "7",
                "decimal_number": "7.5",
                "boolean": "true",
                "date": "2026-01-15",
                "datetime": "2026-01-15T12:30:00",
            }[self.function["parameter_type"]]
            sample = coerce_function_argument(
                self.function["parameter_type"], sample_text
            )
            body = compile_expression(
                self.function["expression"],
                allowed_symbols={self.function["parameter"]},
            )
            result = evaluate_expression(
                body, {}, {self.function["parameter"]: sample}
            )
            validate_function_result(self.function["return_type"], result)
        except (QueryFunctionError, ValueError) as exc:
            self.function = None
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            return
        super().accept()


class ManageQueryFunctionsDialog(QDialog):
    """Stage reusable project functions and protect referenced names."""

    def __init__(
        self,
        functions: list[dict[str, str]],
        referenced_names: set[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self._functions = validate_query_functions(deepcopy(functions))
        self._referenced_names = set(referenced_names)
        self._accepted_functions: list[dict[str, str]] | None = None
        self.setWindowTitle("Manage Power Query Functions")
        self.setMinimumSize(680, 420)
        layout = QVBoxLayout(self)
        title = QLabel("Manage Functions")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)
        note = QLabel(
            "Functions are saved with the project and can be reused in custom-column formulas. "
            "The local M editor supports one typed parameter and the safe expression subset."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 4, self)
        self.table.setObjectName("powerQueryFunctionTable")
        self.table.setHorizontalHeaderLabels(["Name", "Signature", "Result", "Description"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.new_button = QPushButton("New function")
        self.new_button.setObjectName("newPowerQueryFunctionButton")
        self.edit_button = QPushButton("Edit")
        self.edit_button.setObjectName("editPowerQueryFunctionButton")
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("deletePowerQueryFunctionButton")
        actions.addWidget(self.new_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        footer = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply,
            parent=self,
        )
        footer.button(QDialogButtonBox.StandardButton.Apply).setText("Apply functions")
        footer.accepted.connect(self._accept_functions)
        footer.rejected.connect(self.reject)
        layout.addWidget(footer)
        self.new_button.clicked.connect(self._new_function)
        self.edit_button.clicked.connect(self._edit_function)
        self.delete_button.clicked.connect(self._delete_function)
        self.table.currentCellChanged.connect(lambda *_args: self._update_actions())
        self._render_functions()

    @property
    def functions(self) -> list[dict[str, str]] | None:
        return deepcopy(self._accepted_functions)

    def _selected_index(self) -> int:
        return self.table.currentRow()

    def _render_functions(self, selected_name: str = "") -> None:
        labels = {
            "text": "Text", "whole_number": "Whole number",
            "decimal_number": "Decimal number", "boolean": "True/False",
            "date": "Date", "datetime": "DateTime",
        }
        self.table.setRowCount(len(self._functions))
        for row, function in enumerate(self._functions):
            values = (
                function["name"],
                f"({function['parameter']} as {labels[function['parameter_type']]})",
                labels[function["return_type"]],
                function.get("description", ""),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
            if function["name"] == selected_name:
                self.table.selectRow(row)
        if self._functions and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self._update_actions()

    def _update_actions(self) -> None:
        selected = 0 <= self._selected_index() < len(self._functions)
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

    def _new_function(self) -> None:
        dialog = QueryFunctionDefinitionDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.function is None:
            return
        try:
            self._functions = validate_query_functions(
                [*self._functions, dialog.function]
            )
        except QueryFunctionError as exc:
            QMessageBox.warning(self, "Duplicate function", str(exc))
            return
        self._render_functions(dialog.function["name"])

    def _edit_function(self) -> None:
        index = self._selected_index()
        if not 0 <= index < len(self._functions):
            return
        original = self._functions[index]
        dialog = QueryFunctionDefinitionDialog(
            original, self, name_locked=True
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.function is None:
            return
        candidate = list(self._functions)
        candidate[index] = dialog.function
        try:
            self._functions = validate_query_functions(candidate)
        except QueryFunctionError as exc:
            QMessageBox.warning(self, "Invalid function", str(exc))
            return
        self._render_functions(dialog.function["name"])

    def _delete_function(self) -> None:
        index = self._selected_index()
        if not 0 <= index < len(self._functions):
            return
        function = self._functions[index]
        if function["name"] in self._referenced_names:
            QMessageBox.warning(
                self,
                "Function is in use",
                f"Update every query that calls {function['name']!r} before deleting it.",
            )
            return
        self._functions.pop(index)
        self._render_functions()

    def _accept_functions(self) -> None:
        try:
            self._accepted_functions = validate_query_functions(self._functions)
        except QueryFunctionError as exc:
            QMessageBox.warning(self, "Invalid functions", str(exc))
            return
        super().accept()


class TransformDataDialog(QDialog):
    """Build and preview an ordered, replayable local transformation sequence."""

    _STEP_OPERATIONS_WITHOUT_SETTINGS = frozenset({
        "promote_headers", "demote_headers", "transpose_table", "remove_blank_rows",
        "remove_rows_with_errors", "remove_sparse_top_rows",
        "remove_sparse_bottom_rows", "m_sparse_boundary_helper", "count_rows",
    })

    def __init__(
        self,
        source_candidate: ImportCandidate,
        steps: list[dict[str, Any]] | None = None,
        parent: QWidget | None = None,
        query_name: str = "Current Query",
        queries: list[dict[str, Any]] | None = None,
        active_query_id: str = "",
        reserved_query_names: set[str] | None = None,
        query_dependents: dict[str, list[str]] | None = None,
        query_parameters: list[dict[str, str]] | None = None,
        query_functions: list[dict[str, str]] | None = None,
        new_source_candidate: Callable[
            [], tuple[ImportCandidate, dict[str, Any]] | None
        ] | None = None,
        new_folder_source_candidate: Callable[
            [], tuple[ImportCandidate, dict[str, Any]] | None
        ] | None = None,
        new_sql_server_source_candidate: Callable[
            [], tuple[ImportCandidate, dict[str, Any]] | None
        ] | None = None,
        new_odata_source_candidate: Callable[
            [], tuple[ImportCandidate, dict[str, Any]] | None
        ] | None = None,
        new_web_source_candidate: Callable[
            [], tuple[ImportCandidate, dict[str, Any]] | None
        ] | None = None,
        edit_source_candidate: Callable[
            [dict[str, Any]], tuple[ImportCandidate, dict[str, Any]] | None
        ] | None = None,
        refresh_candidate: Callable[
            [
                str,
                dict[str, dict[str, Any]],
                dict[str, Any],
            ],
            tuple[
                ImportCandidate,
                dict[str, str],
                dict[str, tuple[
                    ImportCandidate,
                    ImportCandidate,
                    dict[str, str],
                    dict[str, str],
                ]],
            ],
        ] | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        editor_palette = QPalette(self.palette())
        editor_palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
        editor_palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        editor_palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
        self.setPalette(editor_palette)
        self.setStyleSheet(self.styleSheet() + """
            QDialog#powerQueryEditorDialog { background: #ffffff; }
            QWidget#powerQueryQueriesPane, QWidget#powerQuerySettingsStepsPane {
                background: #ffffff;
            }
            QTabWidget#powerQueryRibbonTabs::pane {
                border: 0;
                border-bottom: 1px solid #d6d6d6;
                background: #ffffff;
            }
            QTabWidget#powerQueryRibbonTabs,
            QTabWidget#powerQueryRibbonTabs QTabBar {
                background: #ffffff;
            }
            QTabWidget#powerQueryRibbonTabs QTabBar::base,
            QTabWidget#powerQueryRibbonTabs::tab-bar {
                background: #ffffff;
                border: 0;
            }
            QTabWidget#powerQueryRibbonTabs QWidget#powerQueryRibbonPage,
            QTabWidget#powerQueryRibbonTabs QWidget#powerQueryRibbonBody,
            QTabWidget#powerQueryRibbonTabs QWidget#powerQueryRibbonGroup {
                background-color: #f7f5f5;
                color: #333333;
            }
            QWidget#powerQueryRibbonPage,
            QWidget#powerQueryRibbonBody,
            QWidget#powerQueryRibbonGroup {
                background-color: #f7f5f5;
            }
            QTabWidget#powerQueryRibbonTabs QTabBar::tab {
                background: transparent;
                border: 0;
                min-width: 52px;
                padding: 4px 11px 5px 11px;
                color: #444c53;
                font-size: 12px;
            }
            QTabWidget#powerQueryRibbonTabs QTabBar::tab:selected {
                background: #ffffff;
                color: #252525;
                border-bottom: 0;
                font-weight: 600;
            }
            QTabWidget#powerQueryRibbonTabs QToolButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 2px;
                padding: 1px 3px;
                color: #30363b;
                font-size: 10px;
                text-align: center;
            }
            QTabWidget#powerQueryRibbonTabs QToolButton[powerQueryRibbonSize="small"] {
                font-size: 9px;
                text-align: left;
                padding-left: 2px;
            }
            QTabWidget#powerQueryRibbonTabs QToolButton[powerQueryRibbonSize="large"] {
                font-size: 10px;
            }
            QTabWidget#powerQueryRibbonTabs QToolButton[powerQueryRibbonSize="medium"] {
                font-size: 9px;
            }
            QTabWidget#powerQueryRibbonTabs QToolButton#openPowerQueryMEditorHomeButton {
                font-size: 9px;
                padding: 0;
                border: 0;
            }
            QTabWidget#powerQueryRibbonTabs QToolButton:hover {
                background: #e4edf7;
                border-color: #a8bfd7;
            }
            QTabWidget#powerQueryRibbonTabs QToolButton:focus {
                background: #e4edf7;
                border: 1px solid #7da5c9;
                padding: 2px 4px;
            }
            QTabWidget#powerQueryRibbonTabs QToolButton:pressed,
            QTabWidget#powerQueryRibbonTabs QToolButton:checked {
                background: #dce9f5;
                border-color: #9fb8d1;
                color: #293943;
            }
            QTabWidget#powerQueryRibbonTabs QToolButton:disabled {
                background: transparent;
                border-color: transparent;
                color: #929a9f;
            }
            QLabel#powerQueryRibbonGroupCaption {
                color: #555b60;
                font-size: 10px;
                padding-top: 2px;
            }
            QTabWidget#powerQueryRibbonTabs QToolButton#powerQueryFileButton {
                background: #c03223;
                border: 0;
                border-radius: 0;
                color: #ffffff;
                font-size: 11px;
                font-weight: 600;
                padding: 4px 12px;
                text-align: center;
            }
            QTabWidget#powerQueryRibbonTabs QToolButton#powerQueryFileButton:hover {
                background: #a9271c;
            }
            QToolButton#powerQueryFileButton::menu-indicator {
                image: none;
                width: 0;
            }
            QTabWidget#powerQueryRibbonTabs QToolButton::menu-indicator {
                width: 8px;
                height: 8px;
            }
            QToolButton#powerQuerySettingsCloseButton {
                background: transparent;
                border: 0;
                color: #66727a;
                font-size: 15px;
                padding: 0;
            }
            QToolButton#powerQuerySettingsCloseButton:hover {
                background: #f0f2f3;
                color: #26343c;
            }
            QLabel#powerQuerySettingsTitle {
                color: #30383d;
                font-size: 12px;
                font-weight: 500;
            }
            QLabel#powerQueryStepsEmptyState {
                color: #7b858c;
                font-size: 11px;
                padding: 8px;
            }
            QSplitter#powerQueryWorkspaceSplitter::handle:horizontal {
                background: #d8d8d8;
                width: 1px;
            }
            QSplitter#powerQuerySettingsStepsSplitter::handle:vertical {
                background: #e2e2e2;
                height: 1px;
            }
            QLabel#powerQueryQueriesHeading,
            QLabel#powerQueryPropertiesHeading,
            QLabel#powerQueryAppliedStepsHeading {
                color: #347552;
                font-size: 10px;
                font-weight: 600;
            }
            QListWidget#powerQueryQueriesList,
            QListWidget#powerQueryAppliedStepsList {
                background: #ffffff;
                border: 0;
                selection-background-color: #d8f1e3;
                selection-color: #264f38;
            }
            QListWidget#powerQueryQueriesList::item,
            QListWidget#powerQueryAppliedStepsList::item {
                padding: 4px 5px;
            }
            QListWidget#powerQueryQueriesList::item:selected,
            QListWidget#powerQueryAppliedStepsList::item:selected {
                background: #d8f1e3;
                color: #264f38;
            }
            QGroupBox#powerQuerySettingsPanel {
                background-color: #ffffff;
                border: 0;
                border-left: 1px solid #dddddd;
                border-radius: 0;
                margin-top: 0;
                padding-top: 1px;
            }
            QGroupBox#powerQuerySettingsPanel::title {
                left: 7px;
                padding: 0 3px;
                color: #30383d;
                font-weight: 500;
            }
            QToolButton#powerQueryAllPropertiesButton {
                color: #3675a7;
                text-align: left;
                padding: 0;
            }
            QTableView#powerQueryDataPreview {
                background: #ffffff;
                alternate-background-color: #ffffff;
                gridline-color: #d5d5d5;
                border: 0;
                font-size: 11px;
            }
            QTableView#powerQueryDataPreview QHeaderView {
                background-color: #edf2f5;
                color: #30485b;
            }
            QTableView#powerQueryDataPreview QHeaderView::section,
            QTableView#powerQueryDataPreview QTableCornerButton::section {
                background-color: #edf2f5;
                color: #30485b;
                border: 0;
                border-right: 1px solid #d6dee5;
                border-bottom: 1px solid #d6dee5;
                padding: 5px 7px;
            }
            QWidget#powerQueryPreviewPane,
            QWidget#powerQueryAppliedStepsPane {
                background-color: #ffffff;
                color: #243746;
            }
            QWidget#powerQueryFormulaBarRow {
                background: #ffffff;
                border-top: 1px solid #e2e2e2;
                border-bottom: 1px solid #d4d4d4;
                min-height: 34px;
            }
            QLabel#powerQueryFormulaGlyph {
                color: #47525a;
                font-weight: 600;
                font-style: italic;
                padding: 0 5px;
            }
            QLabel#powerQueryCountLabel {
                background: #f4f4f4;
                color: #606a70;
                font-size: 10px;
                border-top: 1px solid #d6d6d6;
                padding: 4px 8px;
            }
            QPushButton#cancelPowerQueryFormulaEditButton,
            QPushButton#applyPowerQueryFormulaButton {
                min-height: 24px;
                max-height: 24px;
                padding: 0;
                border-radius: 2px;
            }
            QLabel#powerQueryFormulaEquals {
                color: #58636a;
                padding: 0 1px;
            }
            QDialogButtonBox QPushButton {
                min-height: 26px;
                padding: 2px 12px;
            }
        """)
        fallback_name = query_name.strip() or "Current Query"
        self._reserved_query_names = {
            str(name).strip().casefold()
            for name in (reserved_query_names or set())
            if str(name).strip()
        }
        self._query_dependents = {
            str(query_id): [str(dependent_id) for dependent_id in dependent_ids]
            for query_id, dependent_ids in (query_dependents or {}).items()
        }
        self._deleted_query_ids: set[str] = set()
        self._operation_dialog: QDialog | None = None
        # Index at which the in-flight ribbon command inserts its step (None = append at the end).
        self._insert_at: int | None = None
        self._conditional_dialog: QDialog | None = None
        self._query_parameters = validate_query_parameters(
            deepcopy(query_parameters or [])
        )
        self._query_functions = validate_query_functions(
            deepcopy(query_functions or [])
        )
        self._refresh_candidate_callback = refresh_candidate
        self._new_source_candidate_callback = new_source_candidate
        self._new_folder_source_candidate_callback = new_folder_source_candidate
        self._new_sql_server_source_candidate_callback = new_sql_server_source_candidate
        self._new_odata_source_candidate_callback = new_odata_source_candidate
        self._new_web_source_candidate_callback = new_web_source_candidate
        self._edit_source_candidate_callback = edit_source_candidate
        self._accepted_parameters: list[dict[str, str]] | None = None
        self._accepted_functions: list[dict[str, str]] | None = None
        self._query_states: dict[str, dict[str, Any]] = {}
        self._query_order: list[str] = []
        if queries:
            for query in queries:
                query_id = str(query.get("id", "")).strip()
                candidate = query.get("candidate")
                unavailable = query.get("is_unavailable") is True
                if not query_id or (
                    not isinstance(candidate, ImportCandidate) and not unavailable
                ):
                    continue
                source_candidate = query.get("source_candidate")
                if not isinstance(source_candidate, ImportCandidate):
                    source_candidate = candidate
                if unavailable:
                    candidate = ImportCandidate("query", [], [], {}, [])
                    # Keep the saved definition visible to dependency checks
                    # even when its source could not be loaded for this session.
                    query_steps = validate_steps(query.get("steps", []))
                    preview_candidate = candidate
                    step_metadata: list[dict[str, Any]] = []
                else:
                    query_steps = validate_steps(query.get("steps", []))
                    preview_candidate = apply_transformations(
                        candidate, query_steps,
                        parameters=parameter_values(
                            self._query_parameters, self._query_functions
                        ),
                    )
                    step_metadata = validate_applied_step_metadata(
                        query.get("step_metadata", []), len(query_steps)
                    )
                query_name_value = str(query.get("name", fallback_name)).strip() or fallback_name
                self._query_states[query_id] = {
                    "id": query_id,
                    "name": query_name_value,
                    "display_name": str(query.get("display_name", query_name_value)),
                    "description": str(query.get("description", "")),
                    "query_group": str(query.get("query_group", "")),
                    "is_saved_query": bool(query.get("is_saved_query", False)),
                    "load_enabled": query.get("load_enabled", True),
                    "include_in_report_refresh": query.get(
                        "include_in_report_refresh", True
                    ),
                    "query_definition": deepcopy(query.get("query_definition", {})),
                    "is_new_query": bool(query.get("is_new_query", False)),
                    "is_new_source": bool(query.get("is_new_source", False)),
                    "is_source_settings_changed": bool(
                        query.get("is_source_settings_changed", False)
                    ),
                    "source_record": deepcopy(query.get("source_record")),
                    "preview_refreshed": False,
                    "is_unavailable": unavailable,
                    "preview_error": str(query.get("preview_error", "")),
                    "source_candidate": source_candidate,
                    "source_column_types": dict(query.get("source_column_types", {})),
                    "column_types": dict(query.get("column_types", {})),
                    "original_steps": deepcopy(query_steps),
                    "steps": deepcopy(query_steps),
                    "step_metadata": step_metadata,
                    "m_script": query.get("m_script"),
                    "preview_candidate": preview_candidate,
                }
                self._query_order.append(query_id)
            for query in self._query_states.values():
                if isinstance(query.get("m_script"), str):
                    query["m_script_source_names"] = self._query_source_names(query)
        if not self._query_states:
            query_id = "__active__"
            initial_steps = validate_steps(steps or [])
            self._query_states[query_id] = {
                "id": query_id,
                "name": fallback_name,
                "display_name": fallback_name,
                "description": "",
                "query_group": "",
                "is_saved_query": False,
                "load_enabled": True,
                "include_in_report_refresh": True,
                "query_definition": {},
                "is_new_query": False,
                "is_new_source": False,
                "source_record": None,
                "preview_refreshed": False,
                "source_candidate": source_candidate,
                "source_column_types": {},
                "column_types": {},
                "original_steps": deepcopy(initial_steps),
                "steps": deepcopy(initial_steps),
                "step_metadata": validate_applied_step_metadata([], len(initial_steps)),
                "m_script": None,
                "preview_candidate": apply_transformations(
                    source_candidate, initial_steps,
                    parameters=parameter_values(
                        self._query_parameters, self._query_functions
                    ),
                ),
            }
            self._query_order.append(query_id)
        self._active_query_id = (
            active_query_id if active_query_id in self._query_states
            else self._query_order[0]
        )
        active_query = self._query_states[self._active_query_id]
        self._source_candidate = active_query["source_candidate"]
        self._query_name = active_query["name"]
        self._steps = deepcopy(active_query["steps"])
        self._step_metadata = deepcopy(active_query["step_metadata"])
        self._accepted_candidate: ImportCandidate | None = None
        self._accepted_steps: list[dict[str, Any]] | None = None
        self._accepted_queries: dict[str, dict[str, Any]] | None = None
        self._preview_candidate = active_query["preview_candidate"]
        self.setObjectName("powerQueryEditorDialog")
        self.setWindowTitle(f"{fallback_name} - Power Query Editor")
        screen = self.screen() or QApplication.primaryScreen()
        workspace_scale = 1.0
        if screen is not None:
            available = screen.availableGeometry()
            workspace_scale = min(1.0, max(0.45, available.width() / 732))
            minimum_width = min(900, available.width())
            minimum_height = min(650, available.height())
            self.setMinimumSize(minimum_width, minimum_height)
            self.resize(
                min(available.width(), max(minimum_width, int(available.width() * 0.96))),
                min(available.height(), max(minimum_height, int(available.height() * 0.93))),
            )
        else:
            self.setMinimumSize(900, 650)
            self.resize(1240, 820)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.ribbon_tabs = QTabWidget()
        self.ribbon_tabs.setObjectName("powerQueryRibbonTabs")
        self.ribbon_tabs.setDocumentMode(True)
        # The ribbon height is computed from the tallest page once every page
        # exists (see _populate_ribbon), so no group label can be clipped.
        layout.addWidget(self.ribbon_tabs)
        self.file_button = QToolButton(self.ribbon_tabs)
        self.file_button.setObjectName("powerQueryFileButton")
        self.file_button.setText("File")
        self.file_button.setFixedSize(56, 29)
        self.file_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.file_menu = QMenu(self.file_button)
        self.file_button.setMenu(self.file_menu)
        self.ribbon_tabs.setCornerWidget(
            self.file_button, Qt.Corner.TopLeftCorner
        )

        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.workspace_splitter.setObjectName("powerQueryWorkspaceSplitter")
        self.workspace_splitter.setChildrenCollapsible(False)
        layout.addWidget(self.workspace_splitter, 1)

        self.query_panel = QWidget()
        self.query_panel.setObjectName("powerQueryQueriesPane")
        self.query_panel.setMinimumWidth(max(100, round(150 * workspace_scale)))
        query_column = QVBoxLayout(self.query_panel)
        query_column.setContentsMargins(8, 8, 4, 0)
        query_column.setSpacing(3)
        self.queries_heading = QLabel("Queries [0]")
        self.queries_heading.setObjectName("powerQueryQueriesHeading")
        query_column.addWidget(self.queries_heading)
        self.query_list = QListWidget()
        self.query_list.setObjectName("powerQueryQueriesList")
        self.query_list.setMinimumWidth(max(90, round(140 * workspace_scale)))
        self.query_list.setMaximumWidth(260)
        self.query_list.setIconSize(QSize(16, 16))
        self.query_list.setSpacing(2)
        self.query_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.query_list.customContextMenuRequested.connect(self._show_query_context_menu)
        query_column.addWidget(self.query_list, 1)
        self.query_settings_panel = QGroupBox("Query Settings")
        self.query_settings_panel.setObjectName("powerQuerySettingsPanel")
        self.query_settings_panel.setTitle("")
        query_settings_layout = QVBoxLayout(self.query_settings_panel)
        query_settings_layout.setContentsMargins(7, 6, 7, 5)
        query_settings_layout.setSpacing(4)
        settings_heading_row = QHBoxLayout()
        settings_heading_row.setContentsMargins(0, 0, 0, 2)
        settings_title = QLabel("Query Settings")
        settings_title.setObjectName("powerQuerySettingsTitle")
        settings_heading_row.addWidget(settings_title, 1)
        self.settings_close_button = QToolButton(self.query_settings_panel)
        self.settings_close_button.setObjectName("powerQuerySettingsCloseButton")
        self.settings_close_button.setText("×")
        self.settings_close_button.setFixedSize(22, 22)
        self.settings_close_button.setToolTip("Hide Query Settings")
        settings_heading_row.addWidget(self.settings_close_button)
        query_settings_layout.addLayout(settings_heading_row)
        properties_heading = QLabel("▾  PROPERTIES")
        properties_heading.setObjectName("powerQueryPropertiesHeading")
        query_settings_layout.addWidget(properties_heading)
        query_settings_layout.addWidget(QLabel("Name"))
        self.query_name_edit = QLineEdit()
        self.query_name_edit.setObjectName("powerQueryNameEdit")
        self.query_name_edit.setMaxLength(120)
        self.query_name_edit.setPlaceholderText("Query name")
        query_settings_layout.addWidget(self.query_name_edit)
        self.all_properties_button = QToolButton(self.query_settings_panel)
        self.all_properties_button.setObjectName("powerQueryAllPropertiesButton")
        self.all_properties_button.setText("All Properties")
        self.all_properties_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.all_properties_button.setAutoRaise(True)
        query_settings_layout.addWidget(
            self.all_properties_button, 0, Qt.AlignmentFlag.AlignLeft
        )
        self.optional_properties_panel = QWidget(self.query_settings_panel)
        optional_properties_layout = QFormLayout(self.optional_properties_panel)
        optional_properties_layout.setContentsMargins(0, 0, 0, 0)
        optional_properties_layout.setSpacing(4)
        self.query_description_edit = QPlainTextEdit()
        self.query_description_edit.setObjectName("powerQueryDescriptionEdit")
        self.query_description_edit.setPlaceholderText("Optional description")
        self.query_description_edit.setMaximumHeight(64)
        optional_properties_layout.addRow("Description", self.query_description_edit)
        self.query_group_edit = QLineEdit()
        self.query_group_edit.setObjectName("powerQueryGroupEdit")
        self.query_group_edit.setPlaceholderText("Optional group")
        self.query_group_edit.setToolTip(
            "Assign this source or query to a project query group. Leave empty to remove the group."
        )
        optional_properties_layout.addRow("Group", self.query_group_edit)
        self.query_load_enabled_checkbox = QCheckBox("Enable load")
        self.query_load_enabled_checkbox.setObjectName("powerQueryEnableLoadCheckBox")
        self.query_load_enabled_checkbox.setToolTip(
            "Include this saved query as a table in the semantic model."
        )
        optional_properties_layout.addRow("Model", self.query_load_enabled_checkbox)
        self.query_refresh_included_checkbox = QCheckBox("Include in report refresh")
        self.query_refresh_included_checkbox.setObjectName(
            "powerQueryRefreshIncludedCheckBox"
        )
        self.query_refresh_included_checkbox.setToolTip(
            "Re-evaluate this saved query when report data is refreshed."
        )
        optional_properties_layout.addRow("Refresh", self.query_refresh_included_checkbox)
        query_settings_layout.addWidget(self.optional_properties_panel)
        self.optional_properties_panel.setVisible(False)
        self.all_properties_button.clicked.connect(
            lambda: self.optional_properties_panel.setVisible(
                not self.optional_properties_panel.isVisible()
            )
        )
        self.query_name_edit.setText(active_query.get("name", ""))
        self.query_description_edit.setPlainText(active_query.get("description", ""))
        self.query_group_edit.setText(active_query.get("query_group", ""))
        self.query_load_enabled_checkbox.setChecked(active_query.get("load_enabled", True))
        self.query_refresh_included_checkbox.setChecked(
            active_query.get("include_in_report_refresh", True)
        )
        self._set_query_lifecycle_controls(bool(active_query.get("is_saved_query")))
        self.query_name_edit.textChanged.connect(
            lambda _text: self._save_active_query_state()
        )
        self.query_description_edit.textChanged.connect(self._save_active_query_state)
        self.query_group_edit.textChanged.connect(
            lambda _text: self._save_active_query_state()
        )
        self.query_load_enabled_checkbox.toggled.connect(
            lambda _checked: self._save_active_query_state()
        )
        self.query_refresh_included_checkbox.toggled.connect(
            self._refresh_inclusion_changed
        )
        self.query_panel.setVisible(True)

        self.steps_panel = QWidget()
        self.steps_panel.setObjectName("powerQueryAppliedStepsPane")
        self.steps_panel.setPalette(editor_palette)
        step_column = QVBoxLayout(self.steps_panel)
        step_column.setContentsMargins(0, 0, 0, 0)
        self.applied_steps_heading = QLabel("▾  APPLIED STEPS")
        self.applied_steps_heading.setObjectName("powerQueryAppliedStepsHeading")
        step_column.addWidget(self.applied_steps_heading)
        self.step_list = QListWidget()
        self.step_list.setObjectName("powerQueryAppliedStepsList")
        self.step_list.setMinimumWidth(max(100, round(180 * workspace_scale)))
        self.step_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.step_list.customContextMenuRequested.connect(self._show_step_context_menu)
        self.step_list.itemDoubleClicked.connect(
            lambda _item: self._edit_selected_step_settings()
        )
        step_column.addWidget(self.step_list, 1)
        self.steps_empty_label = QLabel("No transformation steps yet")
        self.steps_empty_label.setObjectName("powerQueryStepsEmptyState")
        self.steps_empty_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        step_column.addWidget(self.steps_empty_label, 1)
        step_buttons = QHBoxLayout()
        self.step_settings_button = QToolButton()
        self.step_settings_button.setObjectName("editAppliedStepSettingsButton")
        self.step_settings_button.setText("⚙")
        self.step_settings_button.setAccessibleName("Edit step settings")
        self.step_settings_button.setToolTip(
            "Edit settings for the selected applied step"
        )
        self.step_settings_button.setFixedSize(30, 28)
        self.step_settings_button.clicked.connect(
            self._edit_selected_step_settings
        )
        step_buttons.addWidget(self.step_settings_button)
        self.remove_button = QPushButton("Remove")
        self.up_button = QPushButton("Up")
        self.down_button = QPushButton("Down")
        step_buttons.addWidget(self.remove_button)
        step_buttons.addWidget(self.up_button)
        step_buttons.addWidget(self.down_button)
        step_column.addLayout(step_buttons)
        for button in (
            self.step_settings_button,
            self.remove_button,
            self.up_button,
            self.down_button,
        ):
            button.setVisible(False)

        self.editor_panel = QWidget()
        self.editor_panel.setObjectName("powerQueryPreviewPane")
        self.editor_panel.setPalette(editor_palette)
        self.editor_panel.setMinimumWidth(max(160, round(360 * workspace_scale)))
        editor = QVBoxLayout(self.editor_panel)
        self.operation_settings_panel = QWidget()
        self.operation_settings_panel.setObjectName("powerQueryStepSettingsPanel")
        form = QFormLayout(self.operation_settings_panel)
        self.operation_combo = QComboBox()
        for label, value in (
            ("Rename column", "rename_column"),
            ("Remove column", "remove_column"),
            ("Filter rows", "filter_rows"),
            ("Filter rows (advanced)", "filter_rows_advanced"),
            ("Sort rows", "sort_rows"),
            ("Sort rows by multiple columns", "sort_rows_by_columns"),
            ("Convert type", "convert_type"),
            ("Change type using locale", "convert_type_using_locale"),
            ("Replace values", "replace_value"),
            ("Extract text before/after delimiter", "extract_text_by_delimiter"),
            ("Extract text between delimiters", "extract_text_between_delimiters"),
            ("Split column by delimiter", "split_column"),
            ("Split column at every delimiter into columns", "split_column_by_each_delimiter"),
            ("Split column into rows", "split_column_to_rows"),
            ("Split column by positions", "split_column_by_positions"),
            ("Merge columns", "merge_columns"),
            ("Fill down", "fill_down"),
            ("Fill up", "fill_up"),
            ("Duplicate column", "duplicate_column"),
            ("Add index column", "add_index_column"),
            ("Group by and aggregate rows", "group_by"),
            ("Unpivot selected columns", "unpivot_columns"),
            ("Unpivot other columns", "unpivot_other_columns"),
            ("Pivot column", "pivot_column"),
            ("Add custom column", "add_custom_column"),
            ("Add conditional column", "conditional_column"),
            ("Trim text", "trim_text"),
            ("Clean text", "clean_text"),
            ("Lowercase text", "lowercase_text"),
            ("Uppercase text", "uppercase_text"),
            ("Capitalize each word", "proper_case_text"),
            ("Reverse text", "reverse_text"),
            ("Remove duplicates", "remove_duplicates"),
            ("Keep duplicates", "keep_duplicates"),
            ("Remove blank rows", "remove_blank_rows"),
            ("Remove rows with errors", "remove_rows_with_errors"),
            ("Count rows", "count_rows"),
            ("Remove top rows", "remove_top_rows"),
            ("Remove bottom rows", "remove_bottom_rows"),
            ("Remove sparse top rows", "remove_sparse_top_rows"),
            ("Remove sparse bottom rows", "remove_sparse_bottom_rows"),
            ("Keep top rows", "keep_top_rows"),
            ("Keep bottom rows", "keep_bottom_rows"),
            ("Keep range of rows", "keep_range_rows"),
            ("Remove alternate rows", "remove_alternate_rows"),
            ("Keep columns", "keep_columns"),
            ("Reorder columns", "reorder_columns"),
            ("Use first row as headers", "promote_headers"),
            ("Use headers as first row", "demote_headers"),
            ("Transpose table", "transpose_table"),
        ):
            self.operation_combo.addItem(label, value)
            if value in {"remove_sparse_top_rows", "remove_sparse_bottom_rows"}:
                edge = "top" if value == "remove_sparse_top_rows" else "bottom"
                self.operation_combo.setItemData(
                    self.operation_combo.count() - 1,
                    f"Remove consecutive {edge} rows with at most one nonblank cell; "
                    "stop at the first row with two or more nonblank cells or a cell error.",
                    Qt.ItemDataRole.ToolTipRole,
                )
        self.column_combo = QComboBox()
        self.sort_criteria_widget = QWidget()
        sort_criteria_layout = QVBoxLayout(self.sort_criteria_widget)
        sort_criteria_layout.setContentsMargins(0, 0, 0, 0)
        sort_criteria_layout.setSpacing(4)
        self.sort_criteria_table = QTableWidget(0, 2)
        self.sort_criteria_table.setObjectName("sortCriteriaTable")
        self.sort_criteria_table.setHorizontalHeaderLabels(("Column", "Order"))
        self.sort_criteria_table.verticalHeader().setVisible(False)
        self.sort_criteria_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.sort_criteria_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.sort_criteria_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.sort_criteria_table.setMaximumHeight(142)
        sort_criteria_layout.addWidget(self.sort_criteria_table)
        sort_criteria_buttons = QHBoxLayout()
        self.sort_add_button = QPushButton("Add level")
        self.sort_add_button.setObjectName("addSortLevelButton")
        self.sort_remove_button = QPushButton("Remove")
        self.sort_remove_button.setObjectName("removeSortLevelButton")
        self.sort_up_button = QPushButton("Up")
        self.sort_down_button = QPushButton("Down")
        sort_criteria_buttons.addWidget(self.sort_add_button)
        sort_criteria_buttons.addWidget(self.sort_remove_button)
        sort_criteria_buttons.addWidget(self.sort_up_button)
        sort_criteria_buttons.addWidget(self.sort_down_button)
        sort_criteria_layout.addLayout(sort_criteria_buttons)
        self.sort_criteria_widget.setToolTip(
            "Top rows have higher priority. Each key can sort ascending or descending."
        )
        self.sort_priority_label = QLabel("Sort priority")
        self.value_edit = QLineEdit()
        self.filter_parameter_label = QLabel("Use parameter")
        self.filter_parameter_combo = QComboBox()
        self.filter_parameter_combo.setObjectName("filterParameterCombo")
        self.filter_parameter_combo.setToolTip(
            "Use a saved Power Query parameter instead of a fixed filter value."
        )
        self.culture_edit = QLineEdit("en-US")
        self.culture_edit.setObjectName("transformCultureEdit")
        self.culture_edit.setPlaceholderText("en-US")
        self.culture_edit.setToolTip(
            "Culture is saved with this step and used again when the source refreshes. "
            "Examples: en-US, en-GB, de-DE, fr-FR."
        )
        self.range_first_row_edit = QLineEdit()
        self.range_first_row_edit.setObjectName("keepRangeFirstRowEdit")
        self.alternate_first_row_edit = QLineEdit()
        self.alternate_first_row_edit.setObjectName("removeAlternateFirstRowEdit")
        self.alternate_remove_count_edit = QLineEdit()
        self.alternate_remove_count_edit.setObjectName("removeAlternateCountEdit")
        self.alternate_keep_count_edit = QLineEdit()
        self.alternate_keep_count_edit.setObjectName("keepAlternateCountEdit")
        self.index_start_edit = QLineEdit()
        self.index_start_edit.setObjectName("indexColumnStartEdit")
        self.index_increment_edit = QLineEdit()
        self.index_increment_edit.setObjectName("indexColumnIncrementEdit")
        self._row_count_validator = QIntValidator(0, MAX_DATA_ROWS, self)
        self._first_row_validator = QIntValidator(1, MAX_DATA_ROWS, self)
        self._index_value_validator = QRegularExpressionValidator(
            QRegularExpression(r"-?[0-9]{1,19}"), self
        )
        self.index_start_edit.setMaxLength(20)
        self.index_increment_edit.setMaxLength(20)
        self.custom_expression_edit = QPlainTextEdit()
        self.custom_expression_edit.setObjectName("customColumnExpressionEdit")
        self.custom_expression_edit.setPlaceholderText('Text.Clean([Name])')
        self.custom_expression_edit.setMaximumHeight(76)
        self.custom_expression_label = QLabel("Custom column formula (M subset)")
        self.custom_expression_edit.setToolTip(
            "Supports field references, literals, arithmetic, comparisons, if/then/else, "
            "typed Power Query parameters, saved scalar functions, and selected Text, Number, and Date functions. "
            "This is not full M."
        )
        self.custom_output_type_combo = QComboBox()
        self.custom_output_type_combo.setObjectName("customColumnOutputTypeCombo")
        for label, type_name in (
            ("Text", "text"), ("Whole number", "whole_number"),
            ("Decimal number", "decimal_number"), ("True/False", "boolean"),
            ("Date", "date"), ("DateTime", "datetime"),
        ):
            self.custom_output_type_combo.addItem(label, type_name)
        self.custom_output_type_label = QLabel("Output type")
        self.custom_parameter_combo = QComboBox()
        self.custom_parameter_combo.setObjectName("customColumnParameterCombo")
        self.custom_parameter_combo.setToolTip(
            "Select a saved typed parameter to insert its name into the formula."
        )
        self.insert_custom_parameter_button = QPushButton("Insert parameter")
        self.insert_custom_parameter_button.setObjectName(
            "insertCustomColumnParameterButton"
        )
        self.insert_custom_parameter_button.clicked.connect(
            self._insert_custom_parameter
        )
        custom_parameter_row = QWidget()
        custom_parameter_layout = QHBoxLayout(custom_parameter_row)
        custom_parameter_layout.setContentsMargins(0, 0, 0, 0)
        custom_parameter_layout.addWidget(self.custom_parameter_combo, 1)
        custom_parameter_layout.addWidget(self.insert_custom_parameter_button)
        self.custom_parameter_widget = custom_parameter_row
        self.custom_parameter_label = QLabel("Parameter")
        self.custom_function_combo = QComboBox()
        self.custom_function_combo.setObjectName("customColumnFunctionCombo")
        self.custom_function_combo.setToolTip(
            "Select a saved function to insert a call into this formula."
        )
        self.insert_custom_function_button = QPushButton("Insert function")
        self.insert_custom_function_button.setObjectName(
            "insertCustomColumnFunctionButton"
        )
        self.insert_custom_function_button.clicked.connect(
            self._insert_custom_function
        )
        custom_function_row = QWidget()
        custom_function_layout = QHBoxLayout(custom_function_row)
        custom_function_layout.setContentsMargins(0, 0, 0, 0)
        custom_function_layout.addWidget(self.custom_function_combo, 1)
        custom_function_layout.addWidget(self.insert_custom_function_button)
        self.custom_function_widget = custom_function_row
        self.custom_function_label = QLabel("Function")
        self._conditional_clauses: list[dict[str, str]] = []
        self._filter_clauses: list[dict[str, str]] = []
        self.conditional_column_label = QLabel("Conditional rules")
        self.advanced_filter_widget = QWidget()
        self.advanced_filter_label = QLabel("Filter conditions")
        advanced_filter_layout = QVBoxLayout(self.advanced_filter_widget)
        advanced_filter_layout.setContentsMargins(0, 0, 0, 0)
        advanced_filter_layout.setSpacing(4)
        advanced_filter_join_row = QHBoxLayout()
        advanced_filter_join_row.addWidget(QLabel("Clause connector"))
        self.advanced_filter_join_combo = QComboBox()
        self.advanced_filter_join_combo.setObjectName("advancedFilterJoinCombo")
        self.advanced_filter_join_combo.addItem("AND", "and")
        self.advanced_filter_join_combo.addItem("OR", "or")
        self.advanced_filter_join_combo.setToolTip(
            "This connector joins the selected clause to the clause before it. "
            "AND is evaluated before OR. The first clause has no connector."
        )
        advanced_filter_join_row.addWidget(self.advanced_filter_join_combo)
        advanced_filter_join_row.addStretch(1)
        advanced_filter_layout.addLayout(advanced_filter_join_row)
        self.advanced_filter_clause_list = QListWidget()
        self.advanced_filter_clause_list.setObjectName("advancedFilterClausesList")
        self.advanced_filter_clause_list.setMaximumHeight(96)
        self.advanced_filter_clause_list.setToolTip(
            "Clauses form one flat expression; AND binds more tightly than OR. "
            "Use separate filter steps for nested logic."
        )
        advanced_filter_layout.addWidget(self.advanced_filter_clause_list)
        advanced_filter_buttons = QHBoxLayout()
        self.add_advanced_filter_clause_button = QPushButton("Add clause")
        self.add_advanced_filter_clause_button.setObjectName("addAdvancedFilterClauseButton")
        self.update_advanced_filter_clause_button = QPushButton("Update clause")
        self.update_advanced_filter_clause_button.setObjectName("updateAdvancedFilterClauseButton")
        self.remove_advanced_filter_clause_button = QPushButton("Remove clause")
        self.remove_advanced_filter_clause_button.setObjectName("removeAdvancedFilterClauseButton")
        advanced_filter_buttons.addWidget(self.add_advanced_filter_clause_button)
        advanced_filter_buttons.addWidget(self.update_advanced_filter_clause_button)
        advanced_filter_buttons.addWidget(self.remove_advanced_filter_clause_button)
        advanced_filter_layout.addLayout(advanced_filter_buttons)
        self.conditional_column_widget = QWidget()
        conditional_layout = QVBoxLayout(self.conditional_column_widget)
        conditional_layout.setContentsMargins(0, 0, 0, 0)
        conditional_layout.setSpacing(4)

        condition_row = QHBoxLayout()
        self.conditional_test_column_combo = QComboBox()
        self.conditional_test_column_combo.setObjectName("conditionalTestColumnCombo")
        self.conditional_operator_combo = QComboBox()
        self.conditional_operator_combo.setObjectName("conditionalOperatorCombo")
        for label, value in (
            ("Equals", "equals"),
            ("Does not equal", "not_equals"),
            ("Greater than", "greater_than"),
            ("Greater than or equal", "greater_than_or_equal"),
            ("Less than", "less_than"),
            ("Less than or equal", "less_than_or_equal"),
            ("Begins with", "begins_with"),
            ("Does not begin with", "does_not_begin_with"),
            ("Ends with", "ends_with"),
            ("Does not end with", "does_not_end_with"),
            ("Contains", "contains"),
            ("Does not contain", "does_not_contain"),
        ):
            self.conditional_operator_combo.addItem(label, value)
        condition_row.addWidget(QLabel("If"))
        condition_row.addWidget(self.conditional_test_column_combo, 2)
        condition_row.addWidget(self.conditional_operator_combo, 3)
        conditional_layout.addLayout(condition_row)

        compare_row = QHBoxLayout()
        self.conditional_test_value_kind_combo = QComboBox()
        self.conditional_test_value_kind_combo.setObjectName("conditionalTestValueKindCombo")
        self.conditional_test_value_kind_combo.addItem("Value", "value")
        self.conditional_test_value_kind_combo.addItem("Column", "column")
        self.conditional_test_value_edit = QLineEdit()
        self.conditional_test_value_edit.setObjectName("conditionalTestValueEdit")
        self.conditional_test_value_edit.setPlaceholderText("Compare value")
        self.conditional_test_value_column_combo = QComboBox()
        self.conditional_test_value_column_combo.setObjectName("conditionalTestValueColumnCombo")
        compare_row.addWidget(QLabel("Against"))
        compare_row.addWidget(self.conditional_test_value_kind_combo)
        compare_row.addWidget(self.conditional_test_value_edit, 2)
        compare_row.addWidget(self.conditional_test_value_column_combo, 2)
        conditional_layout.addLayout(compare_row)

        output_row = QHBoxLayout()
        self.conditional_output_kind_combo = QComboBox()
        self.conditional_output_kind_combo.setObjectName("conditionalOutputKindCombo")
        self.conditional_output_kind_combo.addItem("Value", "value")
        self.conditional_output_kind_combo.addItem("Column", "column")
        self.conditional_output_edit = QLineEdit()
        self.conditional_output_edit.setObjectName("conditionalOutputValueEdit")
        self.conditional_output_edit.setPlaceholderText("Return value")
        self.conditional_output_column_combo = QComboBox()
        self.conditional_output_column_combo.setObjectName("conditionalOutputColumnCombo")
        output_row.addWidget(QLabel("Return"))
        output_row.addWidget(self.conditional_output_kind_combo)
        output_row.addWidget(self.conditional_output_edit, 2)
        output_row.addWidget(self.conditional_output_column_combo, 2)
        conditional_layout.addLayout(output_row)

        self.conditional_clause_list = QListWidget()
        self.conditional_clause_list.setObjectName("conditionalClausesList")
        self.conditional_clause_list.setMaximumHeight(76)
        self.conditional_clause_list.setToolTip(
            "Rules run from top to bottom. The first matching rule supplies the output."
        )
        conditional_layout.addWidget(self.conditional_clause_list)
        clause_buttons = QHBoxLayout()
        self.add_conditional_clause_button = QPushButton("Add clause")
        self.add_conditional_clause_button.setObjectName("addConditionalClauseButton")
        self.update_conditional_clause_button = QPushButton("Update clause")
        self.update_conditional_clause_button.setObjectName("updateConditionalClauseButton")
        self.remove_conditional_clause_button = QPushButton("Remove clause")
        self.remove_conditional_clause_button.setObjectName("removeConditionalClauseButton")
        self.up_conditional_clause_button = QPushButton("Up")
        self.down_conditional_clause_button = QPushButton("Down")
        clause_buttons.addWidget(self.add_conditional_clause_button)
        clause_buttons.addWidget(self.update_conditional_clause_button)
        clause_buttons.addWidget(self.remove_conditional_clause_button)
        clause_buttons.addWidget(self.up_conditional_clause_button)
        clause_buttons.addWidget(self.down_conditional_clause_button)
        conditional_layout.addLayout(clause_buttons)

        else_row = QHBoxLayout()
        self.conditional_else_kind_combo = QComboBox()
        self.conditional_else_kind_combo.setObjectName("conditionalElseKindCombo")
        self.conditional_else_kind_combo.addItem("Value", "value")
        self.conditional_else_kind_combo.addItem("Column", "column")
        self.conditional_else_edit = QLineEdit()
        self.conditional_else_edit.setObjectName("conditionalElseValueEdit")
        self.conditional_else_edit.setPlaceholderText("Else value")
        self.conditional_else_column_combo = QComboBox()
        self.conditional_else_column_combo.setObjectName("conditionalElseColumnCombo")
        else_row.addWidget(QLabel("Else"))
        else_row.addWidget(self.conditional_else_kind_combo)
        else_row.addWidget(self.conditional_else_edit, 2)
        else_row.addWidget(self.conditional_else_column_combo, 2)
        conditional_layout.addLayout(else_row)

        self.replacement_edit = QLineEdit()
        self.replacement_edit.setObjectName("replacementValueEdit")
        self.delimiter_edit = QLineEdit()
        self.delimiter_edit.setObjectName("splitColumnDelimiterEdit")
        self.delimiter_edit.setMaxLength(MAX_MERGE_SEPARATOR_CHARS)
        self.end_delimiter_edit = QLineEdit()
        self.end_delimiter_edit.setObjectName("extractBetweenEndDelimiterEdit")
        self.end_delimiter_edit.setMaxLength(MAX_MERGE_SEPARATOR_CHARS)
        self.end_occurrence_edit = QLineEdit()
        self.end_occurrence_edit.setObjectName("extractBetweenEndOccurrenceEdit")
        self.end_occurrence_edit.setMaxLength(6)
        self.end_occurrence_edit.setValidator(self._row_count_validator)
        self.delimiter_label = QLabel("Delimiter (first match)")
        self.end_delimiter_label = QLabel("End delimiter")
        self.end_occurrence_label = QLabel("End occurrence (zero-based)")
        self.option_combo = QComboBox()
        self.value_label = QLabel("Value")
        self.range_first_row_label = QLabel("First row")
        self.alternate_first_row_label = QLabel("First row to remove")
        self.alternate_remove_count_label = QLabel("Number of rows to remove")
        self.alternate_keep_count_label = QLabel("Number of rows to keep")
        self.index_start_label = QLabel("Starting index")
        self.index_increment_label = QLabel("Increment")
        self.replacement_label = QLabel("Replace with")
        self.option_label = QLabel("Option")
        self.culture_label = QLabel("Culture")
        self.column_label = QLabel("Column")
        self.pivot_value_column_combo = QComboBox()
        self.pivot_value_column_combo.setObjectName("pivotValueColumnCombo")
        self.pivot_value_column_label = QLabel("Value column")
        self.keep_columns_list = QListWidget()
        self.keep_columns_list.setObjectName("keepTransformColumnsList")
        self.keep_columns_list.setMaximumHeight(90)
        self.keep_columns_label = QLabel("Columns to keep")
        self.attribute_name_edit = QLineEdit("Attribute")
        self.attribute_name_edit.setObjectName("unpivotAttributeNameEdit")
        self.attribute_name_label = QLabel("Attribute column")
        self.value_column_name_edit = QLineEdit("Value")
        self.value_column_name_edit.setObjectName("unpivotValueNameEdit")
        self.value_column_name_label = QLabel("Value column")
        self._group_aggregations: list[dict[str, str]] = []
        self.group_aggregation_label = QLabel("Aggregations")
        self.group_aggregation_widget = QWidget()
        group_aggregation_layout = QVBoxLayout(self.group_aggregation_widget)
        group_aggregation_layout.setContentsMargins(0, 0, 0, 0)
        group_aggregation_layout.setSpacing(4)
        group_aggregation_fields = QHBoxLayout()
        group_aggregation_fields.setSpacing(4)
        group_aggregation_fields.addWidget(QLabel("Operation"))
        self.group_aggregate_operation_combo = QComboBox()
        self.group_aggregate_operation_combo.setObjectName("groupAggregateOperationCombo")
        self.group_aggregate_operation_combo.setToolTip("Choose the aggregation to calculate per group.")
        for label, value in (
            ("Sum", "sum"),
            ("Average", "average"),
            ("Median", "median"),
            ("Minimum", "min"),
            ("Maximum", "max"),
            ("Count distinct values", "count_distinct_values"),
            ("Count rows", "count_rows"),
            ("Count distinct rows", "count_distinct_rows"),
        ):
            self.group_aggregate_operation_combo.addItem(label, value)
        self.group_aggregate_column_combo = QComboBox()
        self.group_aggregate_column_combo.setObjectName("groupAggregateColumnCombo")
        self.group_aggregate_column_combo.setToolTip(
            "Source column for column-based aggregations."
        )
        self.group_aggregate_name_edit = QLineEdit()
        self.group_aggregate_name_edit.setObjectName("groupAggregateNameEdit")
        self.group_aggregate_name_edit.setPlaceholderText("Output column (optional)")
        group_aggregation_fields.addWidget(self.group_aggregate_operation_combo, 2)
        group_aggregation_fields.addWidget(self.group_aggregate_column_combo, 2)
        group_aggregation_fields.addWidget(self.group_aggregate_name_edit, 2)
        group_aggregation_layout.addLayout(group_aggregation_fields)
        group_aggregation_buttons = QHBoxLayout()
        self.add_group_aggregation_button = QPushButton("Add aggregation")
        self.add_group_aggregation_button.setObjectName("addGroupAggregationButton")
        self.remove_group_aggregation_button = QPushButton("Remove aggregation")
        self.remove_group_aggregation_button.setObjectName("removeGroupAggregationButton")
        group_aggregation_buttons.addWidget(self.add_group_aggregation_button)
        group_aggregation_buttons.addWidget(self.remove_group_aggregation_button)
        group_aggregation_layout.addLayout(group_aggregation_buttons)
        self.group_aggregations_list = QListWidget()
        self.group_aggregations_list.setObjectName("groupAggregationsList")
        self.group_aggregations_list.setMaximumHeight(72)
        self.group_aggregations_list.setToolTip(
            "Numeric and min/max aggregates ignore empty cells. Numeric aggregates report "
            "invalid non-empty numbers. "
            "Distinct-value counts include blank cells."
        )
        group_aggregation_layout.addWidget(self.group_aggregations_list)
        self.operation_label = QLabel("Operation")
        form.addRow(self.operation_label, self.operation_combo)
        form.addRow(self.column_label, self.column_combo)
        form.addRow(self.sort_priority_label, self.sort_criteria_widget)
        form.addRow(self.pivot_value_column_label, self.pivot_value_column_combo)
        form.addRow(self.range_first_row_label, self.range_first_row_edit)
        form.addRow(self.alternate_first_row_label, self.alternate_first_row_edit)
        form.addRow(self.alternate_remove_count_label, self.alternate_remove_count_edit)
        form.addRow(self.alternate_keep_count_label, self.alternate_keep_count_edit)
        form.addRow(self.value_label, self.value_edit)
        form.addRow(self.filter_parameter_label, self.filter_parameter_combo)
        form.addRow(self.index_start_label, self.index_start_edit)
        form.addRow(self.index_increment_label, self.index_increment_edit)
        form.addRow(self.custom_parameter_label, self.custom_parameter_widget)
        form.addRow(self.custom_function_label, self.custom_function_widget)
        form.addRow(self.custom_output_type_label, self.custom_output_type_combo)
        form.addRow(self.custom_expression_label, self.custom_expression_edit)
        form.addRow(self.conditional_column_label, self.conditional_column_widget)
        form.addRow(self.advanced_filter_label, self.advanced_filter_widget)
        form.addRow(self.replacement_label, self.replacement_edit)
        form.addRow(self.delimiter_label, self.delimiter_edit)
        form.addRow(self.end_occurrence_label, self.end_occurrence_edit)
        form.addRow(self.end_delimiter_label, self.end_delimiter_edit)
        form.addRow(self.option_label, self.option_combo)
        form.addRow(self.culture_label, self.culture_edit)
        form.addRow(self.keep_columns_label, self.keep_columns_list)
        form.addRow(self.attribute_name_label, self.attribute_name_edit)
        form.addRow(self.value_column_name_label, self.value_column_name_edit)
        form.addRow(self.group_aggregation_label, self.group_aggregation_widget)

        self.add_button = QPushButton("Add step")
        self.add_button.setObjectName("addTransformStepButton")
        self.update_button = QPushButton("Update selected")
        self.update_button.setObjectName("updateTransformStepButton")
        action_row = QHBoxLayout()
        self.step_settings_toggle = QToolButton(self.editor_panel)
        self.step_settings_toggle.setObjectName("powerQueryStepSettingsToggle")
        self.step_settings_toggle.setText("Step settings")
        self.step_settings_toggle.setToolTip(
            "Show or hide the selected transformation's settings. Ribbon commands open this pane when needed."
        )
        self.step_settings_toggle.setCheckable(True)
        self.step_settings_toggle.setChecked(False)
        self.step_settings_toggle.toggled.connect(
            self.operation_settings_panel.setVisible
        )
        action_row.addWidget(self.step_settings_toggle)
        action_row.addWidget(self.add_button)
        action_row.addWidget(self.update_button)
        action_row.addStretch(1)
        form.addRow(action_row)
        editor.addWidget(self.operation_settings_panel)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        editor.addWidget(self.error_label)
        self.operation_settings_panel.setVisible(False)
        self.formula_bar_row = QWidget(self.editor_panel)
        self.formula_bar_row.setObjectName("powerQueryFormulaBarRow")
        formula_row = QHBoxLayout(self.formula_bar_row)
        formula_row.setContentsMargins(5, 3, 5, 3)
        formula_row.setSpacing(5)
        self.cancel_formula_button = QPushButton("×")
        self.cancel_formula_button.setObjectName(
            "cancelPowerQueryFormulaEditButton"
        )
        self.cancel_formula_button.setFixedWidth(27)
        self.cancel_formula_button.setToolTip("Cancel formula edit")
        self.cancel_formula_button.clicked.connect(self._refresh_formula_bar)
        formula_row.addWidget(self.cancel_formula_button)
        self.apply_formula_button = QPushButton("✓")
        self.apply_formula_button.setObjectName("applyPowerQueryFormulaButton")
        self.apply_formula_button.setFixedWidth(27)
        self.apply_formula_button.setToolTip(
            "Parse and preview this supported M expression as the selected applied step."
        )
        self.apply_formula_button.clicked.connect(self._apply_formula_bar)
        formula_row.addWidget(self.apply_formula_button)
        formula_label = QLabel("fx")
        formula_label.setObjectName("powerQueryFormulaGlyph")
        formula_row.addWidget(formula_label)
        formula_equals = QLabel("=")
        formula_equals.setObjectName("powerQueryFormulaEquals")
        formula_row.addWidget(formula_equals)
        self.formula_bar = QLineEdit()
        self.formula_bar.setObjectName("powerQueryFormulaBar")
        self.formula_bar.setMaxLength(32_000)
        self.formula_bar.setPlaceholderText("Select an applied step to inspect its M expression")
        formula_row.addWidget(self.formula_bar, 1)
        self.formula_edit_button = QPushButton("Edit M…")
        self.formula_edit_button.setObjectName("editPowerQueryFormulaButton")
        self.formula_edit_button.setToolTip(
            "Open the separate Advanced Editor to edit the complete supported M query."
        )
        self.formula_edit_button.clicked.connect(self._open_advanced_editor)
        self.formula_edit_button.setVisible(False)
        self.formula_bar.returnPressed.connect(self._apply_formula_bar)
        editor.addWidget(self.formula_bar_row)

        self.preview_tabs = QTabWidget()
        self.preview_tabs.setObjectName("powerQueryPreviewTabs")
        self.preview_tabs.tabBar().hide()
        self.preview = QTableView()
        self.preview.setObjectName("powerQueryDataPreview")
        self.preview.setAlternatingRowColors(False)
        self.preview_header = _PowerQueryProfileHeader(self.preview)
        header_palette = QPalette(editor_palette)
        header_palette.setColor(QPalette.ColorRole.Window, QColor("#edf2f5"))
        header_palette.setColor(QPalette.ColorRole.Base, QColor("#edf2f5"))
        self.preview_header.setPalette(header_palette)
        self.preview.verticalHeader().setPalette(header_palette)
        self.preview_header.sectionClicked.connect(
            self._show_preview_column_menu
        )
        self.preview_header.filterRequested.connect(
            self._show_preview_column_menu
        )
        self.preview.setHorizontalHeader(self.preview_header)
        self.preview.horizontalHeader().setStretchLastSection(False)
        self.preview.horizontalHeader().setDefaultSectionSize(198)
        self.preview.horizontalHeader().setMinimumSectionSize(105)
        self.preview.verticalHeader().setDefaultSectionSize(26)
        self.preview.setModel(ImportPreviewTableModel(self.preview))
        self.preview.horizontalScrollBar().valueChanged.connect(
            self.preview_header._update_filter_buttons
        )
        self.preview_tabs.addTab(self.preview, "Data preview")

        self.quality_table = QTableWidget(0, 5)
        self.quality_table.setObjectName("powerQueryColumnQualityTable")
        self.quality_table.setHorizontalHeaderLabels(
            ("Column", "Valid", "Empty text", "Errors", "Null")
        )
        self.quality_table.verticalHeader().setVisible(False)
        self.quality_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.quality_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.quality_table.horizontalHeader().setStretchLastSection(True)
        self.preview_tabs.addTab(self.quality_table, "Column quality")

        profile_page = QWidget(self.preview_tabs)
        profile_layout = QVBoxLayout(profile_page)
        profile_layout.setContentsMargins(6, 6, 6, 6)
        profile_scope_row = QHBoxLayout()
        profile_scope_row.addWidget(QLabel("Profile based on"))
        self.profile_scope_combo = QComboBox()
        self.profile_scope_combo.setObjectName("powerQueryProfileScope")
        self.profile_scope_combo.addItem("Entire table", "all")
        self.profile_scope_combo.addItem("First 100 preview rows", "preview")
        profile_scope_row.addWidget(self.profile_scope_combo)
        profile_scope_row.addStretch(1)
        profile_layout.addLayout(profile_scope_row)
        self.profile_table = QTableWidget(0, 5)
        self.profile_table.setObjectName("powerQueryColumnProfileTable")
        self.profile_table.setHorizontalHeaderLabels(
            ("Column", "Type", "Distinct", "Unique", "Top values")
        )
        self.profile_table.verticalHeader().setVisible(False)
        self.profile_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.profile_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.profile_table.horizontalHeader().setStretchLastSection(True)
        profile_layout.addWidget(self.profile_table, 1)
        self.profile_scope_note = QLabel()
        self.profile_scope_note.setWordWrap(True)
        self.profile_scope_note.setStyleSheet("color: #526477;")
        profile_layout.addWidget(self.profile_scope_note)
        self.preview_tabs.addTab(profile_page, "Column profile")
        self.schema_table = QTableWidget(0, 4)
        self.schema_table.setObjectName("powerQuerySchemaTable")
        self.schema_table.setHorizontalHeaderLabels(
            ("Position", "Column", "Data type", "Sample values")
        )
        self.schema_table.verticalHeader().setVisible(False)
        self.schema_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.schema_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.schema_table.horizontalHeader().setStretchLastSection(True)
        self.preview_tabs.addTab(self.schema_table, "Schema")
        self.profile_scope_combo.currentIndexChanged.connect(self._refresh_column_profiles)
        editor.addWidget(self.preview_tabs, 1)

        self.settings_steps_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.settings_steps_splitter.setObjectName("powerQuerySettingsStepsSplitter")
        self.settings_steps_splitter.setChildrenCollapsible(False)
        self.settings_steps_splitter.addWidget(self.query_settings_panel)
        self.settings_steps_splitter.addWidget(self.steps_panel)
        self.settings_steps_splitter.setStretchFactor(0, 0)
        self.settings_steps_splitter.setStretchFactor(1, 1)
        self.settings_steps_splitter.setHandleWidth(1)
        self.settings_steps_pane = QWidget()
        self.settings_steps_pane.setObjectName("powerQuerySettingsStepsPane")
        self.settings_steps_pane.setMinimumWidth(max(110, round(220 * workspace_scale)))
        settings_steps_layout = QVBoxLayout(self.settings_steps_pane)
        settings_steps_layout.setContentsMargins(0, 0, 0, 0)
        settings_steps_layout.addWidget(self.settings_steps_splitter)

        self.workspace_splitter.addWidget(self.query_panel)
        self.workspace_splitter.addWidget(self.editor_panel)
        self.workspace_splitter.addWidget(self.settings_steps_pane)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setStretchFactor(2, 0)
        settings_width = max(
            round(220 * workspace_scale), round(self.width() * 0.13)
        )
        queries_width = max(
            round(150 * workspace_scale), round(self.width() * 0.09)
        )
        self.workspace_splitter.setSizes([
            queries_width,
            max(1, self.width() - queries_width - settings_width),
            settings_width,
        ])
        self.workspace_splitter.setCollapsible(0, False)
        self.workspace_splitter.setCollapsible(1, False)
        self.workspace_splitter.setCollapsible(2, False)
        self.settings_steps_splitter.setSizes([
            max(140, round(self.height() * 0.15)),
            max(1, self.height() - 320),
        ])

        self.count_label = QLabel()
        self.count_label.setObjectName("powerQueryCountLabel")
        self.count_label.setStyleSheet("color: #526477;")
        layout.addWidget(self.count_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText("Close & Apply")
        self.buttons.accepted.connect(self._accept_candidate)
        self.buttons.rejected.connect(self.reject)
        self.buttons.setVisible(False)
        layout.addWidget(self.buttons)

        self._last_non_custom_operation = self.operation_combo.currentData()
        self.operation_combo.currentIndexChanged.connect(
            self._on_operation_combo_changed
        )
        self.operation_combo.activated.connect(self._on_operation_combo_activated)
        self.option_combo.currentIndexChanged.connect(
            self._update_filter_value_visibility
        )
        self.filter_parameter_combo.currentIndexChanged.connect(
            self._update_filter_value_visibility
        )
        self.sort_add_button.clicked.connect(self._add_sort_level)
        self.sort_remove_button.clicked.connect(self._remove_sort_level)
        self.sort_up_button.clicked.connect(lambda: self._move_sort_level(-1))
        self.sort_down_button.clicked.connect(lambda: self._move_sort_level(1))
        self.sort_criteria_table.currentCellChanged.connect(
            lambda *_args: self._update_sort_level_controls()
        )
        self.column_combo.currentIndexChanged.connect(self._update_pivot_value_choices)
        self.group_aggregate_operation_combo.currentIndexChanged.connect(
            self._configure_group_aggregate_fields
        )
        self.add_group_aggregation_button.clicked.connect(self._add_group_aggregation)
        self.remove_group_aggregation_button.clicked.connect(self._remove_group_aggregation)
        self.group_aggregations_list.currentRowChanged.connect(
            lambda _row: self._update_group_aggregation_controls()
        )
        self.add_button.clicked.connect(self._add_or_start_new_step)
        self.update_button.clicked.connect(self._update_selected_step)
        self.remove_button.clicked.connect(self._remove_step)
        self.up_button.clicked.connect(lambda: self._move_step(-1))
        self.down_button.clicked.connect(lambda: self._move_step(1))
        self.step_list.currentRowChanged.connect(self._select_step)
        self.query_list.currentRowChanged.connect(self._switch_query)
        self.conditional_test_value_kind_combo.currentIndexChanged.connect(
            self._configure_conditional_fields
        )
        self.conditional_output_kind_combo.currentIndexChanged.connect(
            self._configure_conditional_fields
        )
        self.conditional_else_kind_combo.currentIndexChanged.connect(
            self._configure_conditional_fields
        )
        self.conditional_clause_list.currentRowChanged.connect(
            self._select_conditional_clause
        )
        self.advanced_filter_clause_list.currentRowChanged.connect(
            self._select_advanced_filter_clause
        )
        self.add_advanced_filter_clause_button.clicked.connect(
            self._add_advanced_filter_clause
        )
        self.update_advanced_filter_clause_button.clicked.connect(
            self._update_advanced_filter_clause
        )
        self.remove_advanced_filter_clause_button.clicked.connect(
            self._remove_advanced_filter_clause
        )
        self.add_conditional_clause_button.clicked.connect(self._add_conditional_clause)
        self.update_conditional_clause_button.clicked.connect(self._update_conditional_clause)
        self.remove_conditional_clause_button.clicked.connect(self._remove_conditional_clause)
        self.up_conditional_clause_button.clicked.connect(
            lambda: self._move_conditional_clause(-1)
        )
        self.down_conditional_clause_button.clicked.connect(
            lambda: self._move_conditional_clause(1)
        )
        self._render_steps()
        self._refresh_preview()
        self._configure_editor()
        self._configure_group_aggregate_fields()
        self._update_step_controls()
        self._populate_ribbon()
        self.file_menu.addAction(
            "Close & Apply", lambda: self.apply_button.click()
        )
        self.file_menu.addSeparator()
        self.file_menu.addAction("Close", self.request_close)
        self.settings_close_button.clicked.connect(
            lambda: self._set_settings_steps_pane_visible(False)
        )
        self._populate_queries()
        self._set_query_editing_enabled(
            not bool(active_query.get("is_unavailable"))
        )
        QShortcut(
            QKeySequence(QKeySequence.StandardKey.Close), self, self.request_close
        )
        self._initial_pending_state = self._pending_state()

    def _populate_ribbon(self) -> None:
        """Expose every supported local transform through task-oriented ribbon tabs."""
        self.ribbon_command_buttons: dict[str, QToolButton] = {}
        self._ribbon_icon_cache: dict[str, QIcon] = {}
        self._ribbon_pages: list[dict[str, Any]] = []

        def command(
            label: str,
            operation: str,
            tooltip: str,
            *,
            size: str = "small",
            slot: tuple[int, int, int, int] | None = None,
            width: int | None = None,
        ) -> dict[str, Any]:
            entry = {
                "label": label,
                "operation": operation,
                "tooltip": tooltip,
                "size": size,
            }
            if slot is not None:
                entry["slot"] = slot
            if width is not None:
                entry["width"] = width
            return entry

        def action(
            label: str,
            tooltip: str,
            callback: Any,
            *,
            checkable: bool = False,
            checked: bool = False,
            object_name: str = "powerQueryRibbonAction",
            size: str = "small",
            slot: tuple[int, int, int, int] | None = None,
            width: int | None = None,
            menu_items: list[tuple[str, Any, bool]] | None = None,
            menu_button_popup: bool = False,
            enabled: bool = True,
            menu_label: str | None = None,
        ) -> dict[str, Any]:
            entry = {
                "label": label,
                "tooltip": tooltip,
                "callback": callback,
                "checkable": checkable,
                "checked": checked,
                "object_name": object_name,
                "size": size,
                "enabled": enabled,
            }
            if slot is not None:
                entry["slot"] = slot
            if width is not None:
                entry["width"] = width
            if menu_items is not None:
                entry["menu_items"] = menu_items
            if menu_button_popup:
                entry["menu_button_popup"] = True
            if menu_label is not None:
                entry["menu_label"] = menu_label
            return entry

        self.home_advanced_editor_button = QToolButton(self)
        self.home_advanced_editor_button.setObjectName(
            "openPowerQueryMEditorHomeButton"
        )
        self.home_advanced_editor_button.setText("Advanced Editor")
        self.home_advanced_editor_button.setToolTip(
            "Edit and preview this query in the separate Advanced Editor for the supported local M subset."
        )
        self.home_advanced_editor_button.clicked.connect(self._open_advanced_editor)

        source_menu_items = [
            ("From File…", self._add_new_source, self._new_source_candidate_callback is not None),
            ("From Folder…", self._add_folder_source, self._new_folder_source_candidate_callback is not None),
            ("SQL Server…", self._add_sql_server_source, self._new_sql_server_source_candidate_callback is not None),
            ("OData Feed…", self._add_odata_source, self._new_odata_source_candidate_callback is not None),
            ("Web…", self._add_web_source, self._new_web_source_candidate_callback is not None),
        ]
        recent_source_menu_items = [
            (
                str(query.get("display_name") or query.get("name") or "Query"),
                lambda query_id=str(query_id): self._switch_query(
                    self._query_order.index(query_id)
                ) if query_id in self._query_order else None,
                True,
            )
            for query_id, query in self._query_states.items()
        ]
        manage_query_menu_items = [
            ("Duplicate Query", self._duplicate_selected_query, True),
            ("Reference Query", self._create_reference_query, True),
            ("Edit Source Settings", self._edit_source_settings, True),
            ("Delete Query", self._delete_selected_query, True),
        ]
        data_type_menu_items = [
            ("Text", lambda: self._select_ribbon_data_type("text"), True),
            ("Whole Number", lambda: self._select_ribbon_data_type("whole_number"), True),
            ("Decimal Number", lambda: self._select_ribbon_data_type("decimal_number"), True),
            ("Boolean", lambda: self._select_ribbon_data_type("boolean"), True),
            ("Date", lambda: self._select_ribbon_data_type("date"), True),
            ("Date/Time", lambda: self._select_ribbon_data_type("datetime"), True),
            ("Time", lambda: self._select_ribbon_data_type("time"), True),
        ]
        home_groups = [
            ("Close", [action(
                "Close &\nLoad",
                "Apply the staged query changes and return to the report.",
                self.apply_button.click,
                object_name="powerQueryCloseApplyButton",
                size="large",
                slot=(0, 0, 3, 1),
                width=48,
                menu_items=[
                    ("Close & Load", self.apply_button.click, True),
                    ("Close", self.request_close, True),
                ],
                menu_button_popup=True,
            )], "office"),
            ("Query", [
                action(
                    "Refresh\nPreview",
                    "Refresh included sources and dependencies, replay current steps, and use cached sources for excluded queries.",
                    self._refresh_source_preview,
                    object_name="powerQueryRefreshPreviewButton",
                    size="large",
                    slot=(0, 0, 3, 1),
                    width=50,
                ),
                action(
                    "Properties",
                    "Expand query properties in the Query Settings pane.",
                    self.all_properties_button.click,
                    object_name="powerQueryPropertiesButton",
                    size="small",
                    slot=(0, 1, 1, 1),
                    width=100,
                ),
                {
                    "label": "Advanced Editor",
                    "tooltip": self.home_advanced_editor_button.toolTip(),
                    "widget": self.home_advanced_editor_button,
                    "size": "small",
                    "slot": (1, 1, 1, 1),
                    "width": 104,
                },
                action(
                    "Manage",
                    "Duplicate, reference, edit, or delete the current query.",
                    lambda: None,
                    object_name="powerQueryManageQueriesButton",
                    size="small",
                    slot=(2, 1, 1, 1),
                    width=100,
                    menu_items=manage_query_menu_items,
                ),
            ], "office"),
            ("Manage Columns", [
                command("Choose Columns", "keep_columns", "Choose the columns that remain in the query.", size="medium", slot=(0, 0, 3, 1), width=52),
                command("Remove Columns", "remove_column", "Remove the selected column.", size="medium", slot=(0, 1, 3, 1), width=52),
            ], "office"),
            ("Reduce Rows", [
                command("Keep Rows", "keep_top_rows", "Keep the first N rows.", size="medium", slot=(0, 0, 3, 1), width=47),
                command("Remove Rows", "remove_top_rows", "Remove the first N rows.", size="medium", slot=(0, 1, 3, 1), width=47),
            ], "office"),
            ("Sort", [
                action(
                    "", "Sort rows in ascending order.",
                    lambda: self._select_ribbon_sort("asc"),
                    object_name="powerQuerySortAscendingButton",
                    size="small", slot=(0, 0, 1, 1), width=25,
                    menu_label="Sort Ascending",
                ),
                action(
                    "", "Sort rows in descending order.",
                    lambda: self._select_ribbon_sort("desc"),
                    object_name="powerQuerySortDescendingButton",
                    size="small", slot=(1, 0, 1, 1), width=25,
                    menu_label="Sort Descending",
                ),
            ], "office"),
            ("Transform", [
                command("Split Column", "split_column", "Split a column at its first delimiter.", size="medium", slot=(0, 0, 3, 1), width=50),
                command("Group By", "group_by", "Group rows and add supported aggregations.", size="medium", slot=(0, 1, 3, 1), width=50),
                action(
                    "Data Type: Any",
                    "Choose a target data type. The selection configures the Convert Type step.",
                    lambda: self._select_ribbon_operation("convert_type"),
                    object_name="powerQueryDataTypeButton",
                    size="small",
                    slot=(0, 2, 1, 1),
                    width=145,
                    menu_items=data_type_menu_items,
                ),
                command("Use First Row as Headers", "promote_headers", "Use the first row as column names.", size="small", slot=(1, 2, 1, 1), width=150),
                command("Replace Values", "replace_value", "Replace matching values in a column.", size="small", slot=(2, 2, 1, 1), width=145),
                action(
                    "Detect Data Types",
                    "Infer safe types for columns and add explicit conversion steps.",
                    self._detect_data_types,
                    object_name="powerQueryDetectDataTypesButton",
                    size="small",
                    slot=(3, 2, 1, 1),
                    width=145,
                ),
            ], "office"),
            ("Combine", [
                action(
                    "Merge Queries",
                    "Join the current staged results of two queries into a new query.",
                    self._merge_queries,
                    object_name="powerQueryMergeQueriesButton",
                    size="small",
                    slot=(0, 0, 1, 1),
                    width=112,
                ),
                action(
                    "Append Queries",
                    "Append the current staged results of two queries into a new query.",
                    self._append_queries,
                    object_name="powerQueryAppendQueriesButton",
                    size="small",
                    slot=(1, 0, 1, 1),
                    width=112,
                ),
                action(
                    "Combine Files",
                    "Combine Files is unavailable for this source type.",
                    lambda: None,
                    object_name="powerQueryCombineFilesButton",
                    size="small",
                    slot=(2, 0, 1, 1),
                    width=112,
                    enabled=False,
                ),
            ], "office"),
            ("Parameters", [action(
                "Manage\nParameters",
                "Create, edit, and remove project parameters used by supported Power Query M row filters.",
                self._manage_query_parameters,
                object_name="managePowerQueryParametersButton",
                size="large",
                slot=(0, 0, 3, 1),
                width=68,
            )], "office"),
            ("Data Sources", [action(
                "Data Source\nSettings",
                "Change the path or parser options for a supported file-backed query.",
                self._edit_source_settings,
                object_name="powerQueryEditSourceSettingsButton",
                size="large",
                slot=(0, 0, 3, 1),
                width=72,
            )], "office"),
            ("New Query", [action(
                "New Source",
                "Add a supported file, folder, SQL Server, OData, or web source.",
                lambda: None,
                object_name="powerQueryNewSourceButton",
                size="small",
                slot=(0, 0, 1, 1),
                width=102,
                menu_items=source_menu_items,
            ), action(
                "Recent Sources",
                "Switch to a source query already open in this editor.",
                lambda: None,
                object_name="powerQueryRecentSourcesButton",
                size="small",
                slot=(1, 0, 1, 1),
                width=102,
                menu_items=recent_source_menu_items,
            ), action(
                "Enter Data",
                "Create a query from values you type or paste.",
                self._add_entered_data_source,
                object_name="powerQueryEnterDataButton",
                size="small",
                slot=(2, 0, 1, 1),
                width=102,
            )], "office"),
        ]
        transform_groups = [
            ("Table", [
                command("Transpose", "transpose_table", "Swap table rows and columns.", size="medium", slot=(0, 0, 3, 1)),
                command("Demote Headers", "demote_headers", "Use column names as the first data row.", size="medium", slot=(0, 1, 3, 1)),
                command("Count Rows", "count_rows", "Add a query step that returns the row count.", slot=(0, 2, 1, 1)),
            ], "office"),
            ("Any Column", [
                command("Change Type", "convert_type", "Convert values to a supported data type.", slot=(0, 0, 1, 1)),
                command("Type w/ Locale", "convert_type_using_locale", "Convert values using an explicit culture.", slot=(1, 0, 1, 1)),
                command("Rename", "rename_column", "Rename the selected column.", slot=(2, 0, 1, 1)),
                command("Reorder", "reorder_columns", "Drag columns into the required order.", slot=(3, 0, 1, 1)),
                command("Fill Down", "fill_down", "Fill blank cells with the preceding value.", slot=(0, 1, 1, 1)),
                command("Fill Up", "fill_up", "Fill blank cells with the following value.", slot=(1, 1, 1, 1)),
                command("Pivot", "pivot_column", "Pivot distinct values into columns.", slot=(2, 1, 1, 1)),
                command("Unpivot Cols", "unpivot_columns", "Turn selected columns into attribute/value rows.", slot=(3, 1, 1, 1)),
                command("Unpivot Other", "unpivot_other_columns", "Keep selected columns and unpivot the rest.", slot=(0, 2, 1, 1)),
                command("Remove Duplicates", "remove_duplicates", "Keep the first row for each duplicate key.", slot=(1, 2, 1, 1)),
                command("Keep Duplicates", "keep_duplicates", "Keep rows whose selected key occurs more than once.", slot=(2, 2, 1, 1)),
            ], "office"),
            ("Text Column", [
                command("Trim", "trim_text", "Remove leading and trailing whitespace.", slot=(0, 0, 1, 1)),
                command("Clean", "clean_text", "Remove control characters.", slot=(1, 0, 1, 1)),
                command("Lowercase", "lowercase_text", "Convert text to lowercase.", slot=(2, 0, 1, 1)),
                command("Uppercase", "uppercase_text", "Convert text to uppercase.", slot=(3, 0, 1, 1)),
                command("Capitalize", "proper_case_text", "Capitalize each word.", slot=(0, 1, 1, 1)),
                command("Reverse", "reverse_text", "Reverse text in the selected column.", slot=(1, 1, 1, 1)),
                command("Split Each Delim.", "split_column_by_each_delimiter", "Split at every delimiter into columns.", slot=(2, 1, 1, 1)),
                command("Split to Rows", "split_column_to_rows", "Create a row for each delimited value.", slot=(3, 1, 1, 1)),
                command("Split at Positions", "split_column_by_positions", "Split text at character positions.", slot=(0, 2, 1, 1)),
                command("Extract Delim.", "extract_text_by_delimiter", "Extract text around a selected delimiter occurrence.", slot=(1, 2, 1, 1)),
                command("Between Delims", "extract_text_between_delimiters", "Extract text between matching delimiters.", slot=(2, 2, 1, 1)),
            ], "office"),
            ("Rows", [
                command("Filter Rows", "filter_rows", "Filter one column with a supported comparison.", slot=(0, 0, 1, 1)),
                command("Advanced Filter", "filter_rows_advanced", "Build an AND/OR filter across columns.", slot=(1, 0, 1, 1)),
                command("Keep Bottom", "keep_bottom_rows", "Keep the last N rows.", slot=(2, 0, 1, 1)),
                command("Keep Range", "keep_range_rows", "Keep a range beginning at a one-based row number.", slot=(3, 0, 1, 1)),
                command("Remove Bottom", "remove_bottom_rows", "Remove the last N rows.", slot=(0, 1, 1, 1)),
                command("Remove Alternate", "remove_alternate_rows", "Remove repeating groups of rows.", slot=(1, 1, 1, 1)),
                command("Remove Blank Rows", "remove_blank_rows", "Remove rows where every field is blank.", slot=(2, 1, 1, 1)),
                command("Remove Error Rows", "remove_rows_with_errors", "Remove rows with an error in any column.", slot=(3, 1, 1, 1)),
                command("Sort Rows", "sort_rows", "Sort the selected column ascending or descending.", slot=(0, 2, 1, 1)),
                command("Sort by Columns", "sort_rows_by_columns", "Set multiple column sort priorities.", slot=(1, 2, 1, 1)),
            ], "office"),
        ]
        add_column_groups = [
            ("General", [
                command("Custom Column", "add_custom_column", "Create a column with a supported M-subset expression.", size="medium", slot=(0, 0, 3, 1)),
                command("Conditional Column", "conditional_column", "Create a column from ordered conditional rules.", size="medium", slot=(0, 1, 3, 1), width=74),
                command("Index Column", "add_index_column", "Add an index with a chosen start and increment.", size="medium", slot=(0, 2, 3, 1)),
                command("Duplicate Column", "duplicate_column", "Copy a column under a new name.", size="medium", slot=(0, 3, 3, 1)),
                action("Manage Functions", "Create and reuse safe typed scalar M functions in custom-column formulas.", self._manage_query_functions, object_name="managePowerQueryFunctionsButton", size="medium", slot=(0, 4, 3, 1)),
            ], "office"),
            ("From Text", [
                command("Merge Columns", "merge_columns", "Combine selected columns in their displayed order.", size="medium", slot=(0, 0, 3, 1)),
                command("Extract Delim.", "extract_text_by_delimiter", "Extract text around a selected delimiter occurrence.", slot=(0, 1, 1, 1)),
                command("Between Delims", "extract_text_between_delimiters", "Extract text between matching delimiters.", slot=(1, 1, 1, 1)),
            ], "office"),
        ]

        self.advanced_editor_button = QToolButton(self)
        self.advanced_editor_button.setObjectName("openPowerQueryMEditorButton")
        self.advanced_editor_button.setText("Advanced\nEditor (M)")
        self.advanced_editor_button.setToolTip(
            "Edit and preview the supported Power Query M subset for this query."
        )
        self.advanced_editor_button.clicked.connect(self._open_advanced_editor)

        view_groups = [
            ("Layout", [
                action(
                    "Query Settings",
                    "Show or hide Query Settings and Applied Steps.",
                    self._set_settings_steps_pane_visible,
                    checkable=True,
                    checked=True,
                    object_name="powerQueryQuerySettingsToggleButton",
                    size="medium",
                    slot=(0, 0, 3, 1),
                ),
                action(
                    "Formula Bar",
                    "Show or hide the formula bar for the selected query step.",
                    self._set_formula_bar_visible,
                    checkable=True,
                    checked=True,
                    object_name="powerQueryFormulaBarToggleButton",
                    slot=(0, 1, 1, 1),
                ),
            ], "office"),
            ("Data Preview", [
                action(
                    "Data Preview",
                    "Show or hide the data preview and profiling pane.",
                    self._set_preview_visible,
                    checkable=True,
                    checked=True,
                    slot=(0, 0, 1, 1),
                ),
                action(
                    "Column Quality",
                    "Show valid and empty value counts by column.",
                    self._show_quality_view,
                    checkable=True,
                    checked=True,
                    slot=(1, 0, 1, 1),
                ),
                action(
                    "Column Profile",
                    "Profile distinct, unique, and frequent values by column.",
                    self._show_profile_view,
                    checkable=True,
                    checked=True,
                    slot=(2, 0, 1, 1),
                ),
            ], "office"),
            ("Columns", [
                action(
                    "Schema View",
                    "Show the selected step's column names, types, and sample values.",
                    self._show_schema_view,
                    size="medium",
                    slot=(0, 0, 3, 1),
                ),
            ], "office"),
            ("Parameters", [action(
                "Manage\nParameters",
                "Create, edit, and remove project parameters used by supported Power Query M row filters.",
                self._manage_query_parameters,
                object_name="powerQueryManageParametersViewButton",
                size="medium",
                slot=(0, 0, 3, 1),
            )], "office"),
            ("Advanced", [
                {
                    "label": "Advanced Editor",
                    "tooltip": self.advanced_editor_button.toolTip(),
                    "widget": self.advanced_editor_button,
                    "size": "medium",
                    "slot": (0, 0, 3, 1),
                },
            ], "office"),
            ("Dependencies", [
                action(
                    "Diagram View",
                    "View source-to-query dependencies for the current editor session.",
                    self._show_query_dependencies,
                    object_name="powerQueryDiagramViewButton",
                    size="medium",
                    slot=(0, 0, 3, 1),
                ),
            ], "office"),
        ]
        tools_groups = [
            ("Applied step actions", [
                action("Add Step", "Add a transformation step.", lambda: self.add_button.click(), slot=(0, 0, 1, 1)),
                action("Update Step", "Update the selected step from the editor controls.", lambda: self.update_button.click(), slot=(1, 0, 1, 1)),
                action("Remove Step", "Remove the selected applied step.", lambda: self.remove_button.click(), slot=(2, 0, 1, 1)),
                action("Move Step Up", "Move the selected step earlier in the query.", lambda: self.up_button.click(), slot=(0, 1, 1, 1)),
                action("Move Step Down", "Move the selected step later in the query.", lambda: self.down_button.click(), slot=(1, 1, 1, 1)),
            ], "office"),
        ]
        help_groups = [
            ("Power Query", [
                action(
                    "Feature Guide",
                    "See the available ribbon commands and the supported M subset.",
                    self._show_feature_guide,
                    size="medium",
                    slot=(0, 0, 3, 1),
                ),
            ], "office"),
        ]
        view_groups.extend(tools_groups)
        view_groups.extend(help_groups)

        for tab_name, groups in (
            ("Home", home_groups),
            ("Transform", transform_groups),
            ("Add Column", add_column_groups),
            ("View", view_groups),
            ("Tools", tools_groups),
            ("Help", help_groups),
        ):
            self.ribbon_tabs.addTab(self._make_ribbon_page(groups), tab_name)
        tab_bar = self.ribbon_tabs.tabBar()
        tab_bar.setElideMode(Qt.TextElideMode.ElideNone)
        tab_bar.setUsesScrollButtons(False)
        tab_bar.setDrawBase(False)
        tab_bar.setFixedHeight(28)
        tab_bar.setStyleSheet("""
            QTabBar { background: #ffffff; }
            QTabBar::base { background: #ffffff; border: 0; }
            QTabBar::tab-bar { background: #ffffff; }
            QTabBar::tab {
                background: #ffffff;
                border: 0;
                min-width: 52px;
                padding: 4px 11px 5px 11px;
                color: #444c53;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #252525;
                border-bottom: 0;
                font-weight: 600;
            }
        """)
        tab_bar.setTabVisible(4, False)
        tab_bar.setTabVisible(5, False)
        self.ribbon_tabs.setCurrentIndex(0)
        self._fit_ribbon_height()
        self.query_settings_toggle_button = self.findChild(
            QToolButton, "powerQueryQuerySettingsToggleButton"
        )

    def _make_ribbon_page(
        self,
        groups: list[tuple[Any, ...]],
    ) -> QWidget:
        page = QWidget(self.ribbon_tabs)
        page.setObjectName("powerQueryRibbonPage")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_state: dict[str, Any] = {"items": [], "row": None, "scroll": None}
        scroll = _RibbonScrollArea(
            page, lambda state=page_state: self._relayout_ribbon_page(state)
        )
        scroll.setObjectName("powerQueryRibbonScrollArea")
        scroll.setPalette(self.palette())
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        # Groups that do not fit collapse into dropdowns; the scroll bar is only
        # a last resort for windows narrower than every collapsed group.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(scroll)
        body.setObjectName("powerQueryRibbonBody")
        row = QHBoxLayout(body)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(0)
        for group_index, group_spec in enumerate(groups):
            title, entries = group_spec[:2]
            presentation = group_spec[2] if len(group_spec) > 2 else "office"
            group = QWidget(page)
            group.setObjectName("powerQueryRibbonGroup")
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(2, 1, 2, 1)
            group_layout.setSpacing(0)
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(1)
            grid.setVerticalSpacing(1)
            default_size = {
                "large": "large",
                "tiles": "medium",
                "stack": "small",
                "grid": "small",
                "office": "small",
            }.get(presentation, "small")
            fallback_row = 0
            group_buttons: list[tuple[QToolButton, dict[str, Any]]] = []
            for index, entry in enumerate(entries):
                size = str(entry.get("size", default_size))
                label = str(entry.get("label", "")).strip()
                text = label if size != "small" else " ".join(label.split())
                button = entry.get("widget")
                if button is None:
                    button = QToolButton(group)
                    button.setText(text)
                    button.setObjectName(
                        f"powerQueryCommand_{entry['operation']}"
                        if "operation" in entry
                        else entry.get("object_name", "powerQueryRibbonAction")
                    )
                    button.setToolTip(entry["tooltip"])
                    if "operation" in entry:
                        operation = entry["operation"]
                        self.ribbon_command_buttons[operation] = button
                        button.clicked.connect(
                            lambda _checked=False, op=operation: self._select_ribbon_operation(op)
                        )
                    else:
                        button.setCheckable(bool(entry.get("checkable")))
                        button.setChecked(bool(entry.get("checked")))
                        callback = entry["callback"]
                        button.clicked.connect(
                            lambda checked=False, fn=callback, checkable=entry.get("checkable", False):
                                fn(checked) if checkable else fn()
                        )
                    menu_items = entry.get("menu_items")
                    if menu_items:
                        menu = QMenu(button)
                        for menu_label, menu_callback, enabled in menu_items:
                            menu_action = menu.addAction(menu_label)
                            menu_action.setEnabled(bool(enabled))
                            if enabled:
                                menu_action.triggered.connect(
                                    lambda _checked=False, fn=menu_callback: fn()
                                )
                        button.setMenu(menu)
                        button.setPopupMode(
                            QToolButton.ToolButtonPopupMode.MenuButtonPopup
                            if entry.get("menu_button_popup")
                            else QToolButton.ToolButtonPopupMode.InstantPopup
                        )
                if "widget" in entry:
                    button.setText(text)
                icon = self._ribbon_icon(entry)
                button.setIcon(icon)
                if icon.isNull():
                    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                elif size == "small":
                    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
                else:
                    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                if size != "small":
                    text = self._wrap_ribbon_text(text)
                    button.setText(text)
                if size == "large":
                    button_size = QSize(int(entry.get("width", 58)), 72)
                    icon_size = QSize(34, 34)
                elif size == "medium":
                    button_size = QSize(int(entry.get("width", 62)), 72)
                    icon_size = QSize(32, 32)
                else:
                    requested_width = int(entry.get("width", 0))
                    small_width = requested_width or min(180, max(108, int(len(text) * 6 + 34)))
                    button_size = QSize(small_width, 23)
                    icon_size = QSize(18, 18)
                    if button.objectName() == "openPowerQueryMEditorHomeButton":
                        icon_size = QSize(16, 16)
                button.setIconSize(icon_size)
                button.setProperty("powerQueryRibbonSize", size)
                # Never smaller than the text, icon and menu arrow need.
                button.setFixedSize(self._fit_ribbon_button_size(button, button_size))
                button.setEnabled(bool(entry.get("enabled", True)))
                button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                button.setAutoRaise(True)
                slot = entry.get("slot")
                if slot is None:
                    if presentation == "tiles":
                        slot = (0, index, 1, 1)
                    else:
                        slot = (fallback_row, 0, 1, 1)
                        fallback_row += 1
                grid.addWidget(button, *slot)
                group_buttons.append((button, entry))
            group_layout.addLayout(grid)
            group_layout.addStretch(1)
            caption = QLabel(title, group)
            caption.setObjectName("powerQueryRibbonGroupCaption")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setFixedHeight(19)
            group_layout.addWidget(caption)
            # Groups fill the ribbon height so every label sits on the same baseline.
            row.addWidget(group, 0)
            collapsed_button = self._make_collapsed_group_button(
                title, group_buttons, body
            )
            collapsed_button.hide()
            row.addWidget(collapsed_button, 0, Qt.AlignmentFlag.AlignTop)
            separator: QFrame | None = None
            if group_index < len(groups) - 1:
                separator = QFrame(body)
                separator.setFrameShape(QFrame.Shape.VLine)
                separator.setFrameShadow(QFrame.Shadow.Plain)
                separator.setStyleSheet("color: #d0d0d0;")
                row.addWidget(separator, 0)
            page_state["items"].append(
                {"group": group, "collapsed": collapsed_button, "separator": separator}
            )
        row.addStretch(1)
        row.activate()
        page_state["row"] = row
        page_state["scroll"] = scroll
        scroll.setWidget(body)
        page_layout.addWidget(scroll)
        self._ribbon_pages.append(page_state)
        self._relayout_ribbon_page(page_state)
        self._update_refresh_preview_button()
        new_source_button = self.findChild(QToolButton, "powerQueryNewSourceButton")
        if new_source_button is not None:
            new_source_button.setEnabled(
                self._new_source_candidate_callback is not None
            )
        self._update_edit_source_settings_button()
        if new_source_button is not None:
            new_source_button.setEnabled(any(
                callback is not None
                for callback in (
                    self._new_source_candidate_callback,
                    self._new_folder_source_candidate_callback,
                    self._new_sql_server_source_candidate_callback,
                    self._new_odata_source_candidate_callback,
                    self._new_web_source_candidate_callback,
                )
            ))
        return page

    def _tallest_ribbon_group(self) -> int:
        return max(
            (
                item["group"].sizeHint().height()
                for state in self._ribbon_pages
                for item in state["items"]
            ),
            default=0,
        )

    def _fit_ribbon_height(self) -> None:
        """Make the ribbon exactly tall enough for its tallest group, label included.

        The pane's chrome (tab bar, border) depends on the platform style, so once
        the dialog is laid out the real overhead is measured instead of guessed.
        """
        page = self.ribbon_tabs.currentWidget()
        overhead = self.ribbon_tabs.tabBar().height() + 4
        if page is not None and page.isVisible() and page.height() > 0:
            overhead = self.ribbon_tabs.height() - page.height()
        target = self._tallest_ribbon_group() + overhead
        if target != self.ribbon_tabs.height():
            self.ribbon_tabs.setFixedHeight(target)

    def showEvent(self, event: Any) -> None:  # noqa: N802
        super().showEvent(event)
        self._fit_ribbon_height()

    @staticmethod
    def _fit_ribbon_button_size(button: QToolButton, requested: QSize) -> QSize:
        """Return the requested size, grown when the button's own content needs more."""
        button.ensurePolished()
        hint = button.sizeHint()
        return QSize(
            max(requested.width(), hint.width()),
            max(requested.height(), hint.height()),
        )

    def _make_collapsed_group_button(
        self,
        title: str,
        group_buttons: list[tuple[QToolButton, dict[str, Any]]],
        parent: QWidget,
    ) -> QToolButton:
        """Build the dropdown that stands in for a group that does not fit."""
        button = QToolButton(parent)
        button.setObjectName("powerQueryRibbonCollapsedGroup")
        button.setProperty("groupTitle", title)
        button.setProperty("powerQueryRibbonSize", "large")
        button.setToolTip(f"{title}: show the commands in this group.")
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        icon = next(
            (member.icon() for member, _entry in group_buttons if not member.icon().isNull()),
            QIcon(),
        )
        button.setIcon(icon)
        button.setIconSize(QSize(32, 32))
        button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
            if icon.isNull()
            else Qt.ToolButtonStyle.ToolButtonTextUnderIcon
        )
        button.setText(self._wrap_ribbon_text(title))
        button.setFixedSize(
            self._fit_ribbon_button_size(button, QSize(62, 72))
        )

        menu = QMenu(button)
        mirrors: list[tuple[QAction, QToolButton, bool]] = []
        for member, entry in group_buttons:
            label = str(
                entry.get("menu_label")
                or " ".join(member.text().replace("&&", "&").split())
                or entry.get("tooltip", "")
            )
            shown = label.replace("&", "&&")
            member_menu = member.menu()
            if member_menu is not None:
                submenu = menu.addMenu(shown)
                if (
                    member.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup
                    and label not in [a.text().replace("&&", "&") for a in member_menu.actions()]
                ):
                    submenu.addAction(shown).triggered.connect(
                        lambda _checked=False, target=member: target.click()
                    )
                for member_action in member_menu.actions():
                    submenu.addAction(member_action)
                mirrors.append((submenu.menuAction(), member, False))
                continue
            action = menu.addAction(shown)
            action.setToolTip(str(entry.get("tooltip", "")))
            action.setCheckable(member.isCheckable())
            action.triggered.connect(
                lambda _checked=False, target=member: target.click()
            )
            mirrors.append((action, member, member.isCheckable()))

        def sync_states() -> None:
            for action, member, checkable in mirrors:
                action.setEnabled(member.isEnabled())
                if checkable:
                    action.setChecked(member.isChecked())

        menu.aboutToShow.connect(sync_states)
        sync_states()
        menu.setToolTipsVisible(True)
        button.setMenu(menu)
        return button

    @staticmethod
    def _wrap_ribbon_text(text: str) -> str:
        """Wrap a ribbon label onto short lines like Power BI's stacked captions."""
        wrapped: list[str] = []
        line = ""
        for word in text.split():
            candidate = f"{line} {word}".strip()
            if line and len(candidate) > 7:
                wrapped.append(line)
                line = word
            else:
                line = candidate
        if line:
            wrapped.append(line)
        return "\n".join(wrapped)

    def _relayout_ribbon_page(self, page_state: dict[str, Any]) -> None:
        """Collapse the rightmost groups that do not fit, restoring them when room returns."""
        scroll = page_state.get("scroll")
        row = page_state.get("row")
        items = page_state["items"]
        if scroll is None or row is None or not items:
            return
        available = scroll.maximumViewportSize().width()
        if available <= 0:
            return
        margins = row.contentsMargins()
        fixed = margins.left() + margins.right() + 2
        full_widths: list[int] = []
        collapsed_widths: list[int] = []
        for item in items:
            separator = item["separator"]
            separator_width = separator.sizeHint().width() if separator is not None else 0
            full_widths.append(item["group"].sizeHint().width() + separator_width)
            collapsed_widths.append(item["collapsed"].width() + separator_width)
        total = fixed + sum(full_widths)
        collapsed_indexes: set[int] = set()
        for index in range(len(items) - 1, -1, -1):
            if total <= available:
                break
            saving = full_widths[index] - collapsed_widths[index]
            if saving <= 0:
                continue
            collapsed_indexes.add(index)
            total -= saving
        for index, item in enumerate(items):
            collapsed = index in collapsed_indexes
            item["group"].setVisible(not collapsed)
            item["collapsed"].setVisible(collapsed)
        row.activate()

    def _ribbon_icon(self, entry: dict[str, Any]):
        operation_icons = {
            "keep_columns": "table",
            "remove_column": "table_edit_c65911",
            "rename_column": "table_edit",
            "reorder_columns": "data_bar_horizontal",
            "filter_rows": "filter",
            "filter_rows_advanced": "filter",
            "remove_blank_rows": "dismiss_c65911",
            "remove_rows_with_errors": "dismiss_c65911",
            "keep_top_rows": "data_bar_vertical_ascending",
            "keep_bottom_rows": "data_bar_vertical",
            "keep_range_rows": "table",
            "remove_top_rows": "table_edit_c65911",
            "remove_bottom_rows": "table_edit_c65911",
            "remove_sparse_top_rows": "table_edit_c65911",
            "remove_sparse_bottom_rows": "table_edit_c65911",
            "remove_alternate_rows": "table_edit_c65911",
            "sort_rows": "data_bar_vertical_ascending",
            "sort_rows_by_columns": "data_bar_vertical_ascending",
            "group_by": "table_multiple_107c71",
            "remove_duplicates": "dismiss_c65911",
            "keep_duplicates": "table_multiple_107c71",
            "count_rows": "data_bar_vertical",
            "convert_type": "table_edit",
            "convert_type_using_locale": "document",
            "trim_text": "text_align_left",
            "clean_text": "text_align_left",
            "lowercase_text": "text_align_left",
            "uppercase_text": "text_align_left",
            "proper_case_text": "text_align_left",
            "reverse_text": "text_align_left",
            "replace_value": "text_align_left",
            "split_column": "text_add",
            "split_column_by_each_delimiter": "text_add",
            "split_column_to_rows": "text_add",
            "split_column_by_positions": "text_add",
            "extract_text_by_delimiter": "text_add",
            "extract_text_between_delimiters": "text_add",
            "merge_columns": "table_multiple_107c71",
            "fill_down": "data_bar_vertical",
            "fill_up": "data_bar_vertical_ascending",
            "pivot_column": "table_multiple_107c71",
            "unpivot_columns": "table_multiple_107c71",
            "unpivot_other_columns": "table_multiple_107c71",
            "promote_headers": "table_edit",
            "demote_headers": "table_edit",
            "transpose_table": "table_multiple_107c71",
            "add_custom_column": "text_add",
            "conditional_column": "filter",
            "add_index_column": "data_bar_vertical_add",
            "duplicate_column": "table_multiple_107c71",
        }
        object_icons = {
            "powerQueryCloseApplyButton": "save_107c71",
            "powerQueryNewSourceButton": "folder_open_8a6d1d",
            "powerQueryRecentSourcesButton": "history_0078d4",
            "powerQueryEnterDataButton": "table_add_107c71",
            "powerQueryPropertiesButton": "settings_647382",
            "powerQueryManageQueriesButton": "table_edit_0078d4",
            "powerQuerySortAscendingButton": "data_bar_vertical_ascending",
            "powerQuerySortDescendingButton": "data_bar_vertical",
            "powerQueryDataTypeButton": "table_edit_107c71",
            "powerQueryCombineFilesButton": "folder_open_647382",
            "powerQueryEditSourceSettingsButton": "settings_c65911",
            "powerQueryFolderSourceButton": "folder_open_8a6d1d",
            "powerQuerySqlServerSourceButton": "database",
            "powerQueryODataSourceButton": "database",
            "powerQueryWebSourceButton": "document_arrow_right",
            "powerQueryRefreshPreviewButton": "arrow_sync",
            "managePowerQueryParametersButton": "math_symbols_107c71",
            "powerQueryManageParametersViewButton": "math_symbols_107c71",
            "managePowerQueryFunctionsButton": "code",
            "powerQueryAppendQueriesButton": "table_multiple",
            "powerQueryMergeQueriesButton": "table_multiple",
            "powerQueryDetectDataTypesButton": "data_histogram_107c71",
            "powerQueryDiagramViewButton": "flowchart",
        }
        label_icons = {
            "advanced editor": "code",
            "advanced ed.": "code",
            "advanced editor (m)": "code",
            "reference": "branch",
            "reference query": "branch",
            "properties": "settings",
            "manage": "table_edit",
            "data type: any": "table_edit",
            "use first row as headers": "table_edit",
            "recent sources": "history",
            "enter data": "table_add",
            "duplicate": "table_multiple",
            "duplicate query": "table_multiple",
            "delete": "dismiss",
            "delete query": "dismiss",
            "applied steps": "checkmark",
            "data preview": "table",
            "column quality": "data_bar_vertical",
            "column profile": "data_histogram",
            "schema view": "table_edit",
            "query settings": "settings",
            "formula bar": "code",
            "manage parameters": "math_symbols",
            "query dependencies": "flowchart",
            "diagram view": "flowchart",
            "count rows": "data_bar_vertical",
            "add step": "add",
            "update step": "checkmark",
            "remove step": "dismiss",
            "move step up": "data_bar_vertical_ascending",
            "move step down": "data_bar_vertical",
            "feature guide": "question",
        }
        operation = str(entry.get("operation", "")).casefold()
        widget = entry.get("widget")
        object_name = str(
            entry.get("object_name")
            or (widget.objectName() if widget is not None else "")
        )
        label = " ".join(str(entry.get("label", "")).split()).casefold()
        reference_icons = {
            "close_load": "close_load",
            "powerQueryRefreshPreviewButton": "refresh_preview",
            "powerQueryPropertiesButton": "properties",
            "openPowerQueryMEditorHomeButton": "advanced_editor",
            "powerQueryManageQueriesButton": "manage_query",
            "powerQuerySortAscendingButton": "sort_ascending",
            "powerQuerySortDescendingButton": "sort_descending",
            "powerQueryMergeQueriesButton": "merge_queries",
            "powerQueryAppendQueriesButton": "append_queries",
            "powerQueryCombineFilesButton": "combine_files",
            "managePowerQueryParametersButton": "manage_parameters",
            "powerQueryEditSourceSettingsButton": "data_source_settings",
            "powerQueryNewSourceButton": "new_source",
            "powerQueryRecentSourcesButton": "recent_sources",
            "powerQueryEnterDataButton": "enter_data",
        }
        operation_reference_icons = {
            "keep_columns": "choose_columns",
            "remove_column": "remove_columns",
            "keep_top_rows": "keep_rows",
            "remove_top_rows": "remove_rows",
            "promote_headers": "use_first_row_headers",
            "replace_value": "replace_values",
            "split_column": "split_column",
            "group_by": "group_by",
        }
        reference_icon_name = (
            reference_icons.get(object_name)
            or operation_reference_icons.get(operation)
        )
        if object_name == "powerQueryCloseApplyButton":
            reference_icon_name = "close_load"
        if reference_icon_name is not None:
            cache_key = f"reference:{reference_icon_name}"
            cached = self._ribbon_icon_cache.get(cache_key)
            if cached is not None:
                return cached
            icon_path = (
                Path(__file__).resolve().parent
                / "qml"
                / "icons"
                / "power_query_ribbon"
                / f"{reference_icon_name}.png"
            )
            icon = QIcon(str(icon_path)) if icon_path.is_file() else QIcon()
            self._ribbon_icon_cache[cache_key] = icon
            return icon
        if object_name == "powerQueryDataTypeButton":
            return QIcon()
        icon_name = (
            operation_icons.get(operation)
            or object_icons.get(object_name)
            or label_icons.get(label)
        )
        if icon_name is None:
            return QIcon()

        cached = self._ribbon_icon_cache.get(icon_name)
        if cached is not None:
            return cached

        icon_directory = Path(__file__).resolve().parent / "qml" / "icons" / "fluent"
        candidates = [
            icon_directory / f"{icon_name}_0078d4_20_regular.svg",
            icon_directory / f"{icon_name}_107c71_20_regular.svg",
            icon_directory / f"{icon_name}_c65911_20_regular.svg",
            icon_directory / f"{icon_name}_8a6d1d_20_regular.svg",
            icon_directory / f"{icon_name}_647382_20_regular.svg",
            icon_directory / f"{icon_name}_20_regular.svg",
        ]
        icon_path = next((candidate for candidate in candidates if candidate.is_file()), None)
        icon = QIcon(str(icon_path)) if icon_path is not None else QIcon()
        self._ribbon_icon_cache[icon_name] = icon
        return icon

    def _update_refresh_preview_button(self) -> None:
        button = self.findChild(QToolButton, "powerQueryRefreshPreviewButton")
        if button is None:
            return
        query = self._query_states.get(self._active_query_id, {})
        unavailable = bool(query.get("is_unavailable"))
        excluded = (
            bool(query.get("is_saved_query"))
            and not bool(query.get("include_in_report_refresh", True))
        )
        button.setEnabled(
            self._refresh_candidate_callback is not None
            and not unavailable
            and not excluded
        )
        if excluded:
            button.setToolTip(
                "This query is excluded from report refresh and uses its cached preview. "
                "Enable 'Include in report refresh' in Query Settings to refresh its sources."
            )
        else:
            button.setToolTip(
                "Refresh included sources and dependencies, replay current steps, "
                "and use cached sources for excluded queries."
            )

    def _update_edit_source_settings_button(self) -> None:
        button = self.findChild(
            QToolButton, "powerQueryEditSourceSettingsButton"
        )
        if button is None:
            return
        query = self._query_states.get(self._active_query_id, {})
        source = query.get("source_record")
        supported = isinstance(source, dict) and source.get("kind") in {
            "csv", "excel", "json", "xml", "parquet", "sqlite", "folder",
            "sql_server", "odata", "web",
        }
        enabled = (
            self._edit_source_candidate_callback is not None
            and supported
            and not query.get("is_unavailable")
            and not query.get("is_duplicate")
        )
        button.setEnabled(bool(enabled))
        kind = str(source.get("kind", "")) if isinstance(source, dict) else ""
        descriptions = {
            "folder": "Change this folder path or combine recipe.",
            "sql_server": "Change the SQL Server connection or selected table/view.",
            "odata": "Change the OData service root or selected entity set.",
            "web": "Change the Web URL or selected data object.",
        }
        description = descriptions.get(kind, "Change this file path or parser options.")
        button.setToolTip(
            f"{description} Existing column names and data types must stay the same."
            if enabled else
            "Edit source settings is available for supported local and remote root queries."
        )

    def _edit_source_settings(self) -> None:
        """Stage source path/parser options while preserving query/model identity."""
        self._save_active_query_state()
        query = self._query_states.get(self._active_query_id)
        callback = self._edit_source_candidate_callback
        original_record = query.get("source_record") if query else None
        if (
            query is None
            or query.get("is_unavailable")
            or query.get("is_duplicate")
            or not isinstance(original_record, dict)
            or original_record.get("kind") not in {
                "csv", "excel", "json", "xml", "parquet", "sqlite", "folder",
                "sql_server", "odata", "web",
            }
        ):
            self._show_error("Select a supported root query to edit its source settings.")
            return
        if callback is None:
            self._show_error("Source settings are unavailable in this editor session.")
            return
        try:
            staged = callback(deepcopy(original_record))
            if staged is None:
                return
            candidate, supplied_record = staged
            if not isinstance(candidate, ImportCandidate) or not isinstance(supplied_record, dict):
                raise ValueError("The source settings preview is incomplete.")
            candidate = deepcopy(candidate)
            source_record = deepcopy(supplied_record)
            source_id = str(query.get("id", ""))
            source_kind = str(original_record.get("kind", ""))
            local_kinds = {
                "csv", "excel", "json", "xml", "parquet", "sqlite", "folder",
            }
            remote_connection_keys = {
                "sql_server": "credential_ref",
                "odata": "service_root",
                "web": "url",
            }
            connection = source_record.get("connection")
            if (
                source_record.get("id") != source_id
                or source_record.get("kind") != source_kind
                or candidate.kind != source_kind
                or not isinstance(source_record.get("parser_options"), dict)
                or (
                    source_kind in local_kinds
                    and not str(source_record.get("path", "")).strip()
                )
                or (
                    source_kind in remote_connection_keys
                    and (
                        not isinstance(connection, dict)
                        or not str(
                            connection.get(remote_connection_keys[source_kind], "")
                        ).strip()
                    )
                )
            ):
                raise ValueError("The edited source settings must keep the same source ID and type.")
            candidate.set_source_identity(
                source_id,
                preserve_origins=source_kind == "folder",
            )
            stable_keys = (set(original_record) | set(source_record)) - {
                "path", "parser_options", "connection", "_staged_password",
            }
            if any(original_record.get(key) != source_record.get(key) for key in stable_keys):
                raise ValueError("Source settings cannot rename or replace the existing query definition.")
            old_source_candidate = query.get("source_candidate")
            if not isinstance(old_source_candidate, ImportCandidate):
                raise ValueError("The current source preview is unavailable.")
            source_types = infer_column_types(candidate.headers, candidate.rows)
            if (
                candidate.headers != old_source_candidate.headers
                or source_types != dict(query.get("source_column_types", {}))
            ):
                raise ValueError(
                    "Source settings must preserve existing column names or data types so model and report references remain valid."
                )
            steps = validate_steps(query.get("steps", []))
            preview = apply_transformations(
                candidate, steps, parameters=self._parameter_values()
            )
            result_types = column_types_after_steps(
                candidate.headers,
                steps,
                output_headers=preview.headers,
                initial_types=source_types,
            )
            old_preview = query.get("preview_candidate")
            if (
                not isinstance(old_preview, ImportCandidate)
                or preview.headers != old_preview.headers
                or result_types != dict(query.get("column_types", {}))
            ):
                raise ValueError(
                    "Source settings must preserve existing column names or data types so model and report references remain valid."
                )

            previous_states = deepcopy(self._query_states)
            expected_schemas = {
                query_id: self._query_schema_signature(state)
                for query_id, state in self._query_states.items()
            }
            query["source_record"] = source_record
            query["source_candidate"] = candidate
            query["source_column_types"] = source_types
            query["preview_candidate"] = preview
            query["column_types"] = result_types
            query["preview_refreshed"] = True
            query["is_source_settings_changed"] = not query.get("is_new_source")
            self._source_candidate = candidate
            self._preview_candidate = preview
            self._steps = steps
            if not self._refresh_source_preview(
                expected_schemas=(
                    expected_schemas if not query.get("is_new_source") else None
                )
            ):
                error = self.error_label.text()
                self._query_states = previous_states
                self._switch_query(self._query_order.index(self._active_query_id), force_reload=True)
                self._show_error(error)
                return
            self._update_edit_source_settings_button()
        except (OSError, QueryError, TransformationError, TypeError, ValueError) as exc:
            self._show_error(f"Could not edit source settings: {exc}")

    @staticmethod
    def _query_schema_signature(query: dict[str, Any]) -> tuple[Any, ...]:
        source = query.get("source_candidate")
        output = query.get("preview_candidate")
        return (
            tuple(source.headers) if isinstance(source, ImportCandidate) else (),
            tuple(output.headers) if isinstance(output, ImportCandidate) else (),
            tuple(sorted(dict(query.get("source_column_types", {})).items())),
            tuple(sorted(dict(query.get("column_types", {})).items())),
        )

    def _refresh_inclusion_changed(self, _checked: bool) -> None:
        self._save_active_query_state()
        self._update_refresh_preview_button()

    # Power BI applies parameterless commands immediately and opens a dialog with
    # OK / Cancel for commands that need input. These sets drive that split.
    _OPERATION_DIALOG_TITLES: dict[str, str] = {
        "rename_column": "Rename Column",
        "keep_columns": "Choose Columns",
        "reorder_columns": "Reorder Columns",
        "filter_rows": "Filter Rows",
        "filter_rows_advanced": "Filter Rows",
        "sort_rows": "Sort Rows",
        "sort_rows_by_columns": "Sort Rows",
        "convert_type": "Change Type",
        "convert_type_using_locale": "Change Type with Locale",
        "replace_value": "Replace Values",
        "extract_text_by_delimiter": "Extract Text Before or After Delimiter",
        "extract_text_between_delimiters": "Extract Text Between Delimiters",
        "split_column": "Split Column by Delimiter",
        "split_column_by_each_delimiter": "Split Column by Delimiter",
        "split_column_to_rows": "Split Column by Delimiter",
        "split_column_by_positions": "Split Column by Positions",
        "merge_columns": "Merge Columns",
        "add_index_column": "Add Index Column",
        "group_by": "Group By",
        "pivot_column": "Pivot Column",
        "keep_top_rows": "Keep Top Rows",
        "keep_bottom_rows": "Keep Bottom Rows",
        "keep_range_rows": "Keep Range of Rows",
        "remove_top_rows": "Remove Top Rows",
        "remove_bottom_rows": "Remove Bottom Rows",
        "remove_alternate_rows": "Remove Alternate Rows",
    }
    # Operations that need no input beyond the current column selection.
    _SELECTION_OPERATIONS_PER_COLUMN = frozenset({
        "remove_column", "duplicate_column", "trim_text", "clean_text",
        "lowercase_text", "uppercase_text", "proper_case_text", "reverse_text",
    })
    _SELECTION_OPERATIONS_COLUMN_LIST = frozenset({
        "fill_down", "fill_up", "keep_duplicates", "unpivot_columns",
        "unpivot_other_columns",
    })
    _PARAMETERLESS_OPERATIONS = frozenset({
        "remove_blank_rows", "remove_rows_with_errors",
    })

    def _selected_preview_columns(self) -> list[str]:
        """Column names selected in the preview grid, left to right (current cell if none)."""
        headers = self._selected_preview_candidate().headers
        model = self.preview.selectionModel()
        indexes = list(model.selectedIndexes()) if model is not None else []
        current = self.preview.currentIndex()
        if not indexes and current.isValid():
            indexes = [current]
        columns = sorted({index.column() for index in indexes if index.isValid()})
        return [headers[column] for column in columns if 0 <= column < len(headers)]

    def _confirm_insert_step(self) -> bool:
        """Start a ribbon command: with a middle applied step selected, ask "Insert step".

        Like Power BI, Insert places the new step directly after the selected step (the grid shows
        that step's output, so the column the user picked exists there) and Cancel changes nothing.
        The position is held in ``_insert_at`` until the command finishes (``_finish_insert``).
        """
        self._insert_at = None
        row = self.step_list.currentRow()
        later = len(self._steps) - 1 - row
        if row < 0 or later <= 0:
            return True
        box = QDialog(self)
        box.setObjectName("powerQueryInsertStepPrompt")
        box.setWindowTitle("Insert step")
        box.setModal(True)
        box.setMinimumWidth(420)
        layout = QVBoxLayout(box)
        message = QLabel(
            f"Insert step: the selected step is followed by {later} more "
            f"step{'s' if later != 1 else ''}; inserting here may affect "
            f"{'them' if later != 1 else 'it'}."
        )
        message.setObjectName("powerQueryInsertStepMessage")
        message.setWordWrap(True)
        layout.addWidget(message)
        buttons = QDialogButtonBox(box)
        insert_button = buttons.addButton("Insert", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        insert_button.setAutoDefault(False)
        cancel_button.setAutoDefault(True)
        cancel_button.setDefault(True)
        buttons.accepted.connect(box.accept)
        buttons.rejected.connect(box.reject)
        layout.addWidget(buttons)
        cancel_button.setFocus()
        if box.exec() != QDialog.DialogCode.Accepted:
            return False
        self._insert_at = row + 1
        return True

    def _insert_position(self) -> int:
        """Where the next added step goes: the pending insert point, else the end."""
        at = self._insert_at
        if at is not None and 0 <= at <= len(self._steps):
            return at
        return len(self._steps)

    def _editor_base_candidate(self) -> ImportCandidate:
        """The table the step form works on: the selected step's input, else the insert point's."""
        row = self.step_list.currentRow()
        if 0 <= row < len(self._steps):
            upto = row
        else:
            upto = self._insert_position()
        if upto < len(self._steps):
            return apply_transformations(
                self._source_candidate, self._steps[:upto],
                parameters=self._parameter_values(),
            )
        return self._preview_candidate

    def _finish_insert(self, added: bool, prior_row: int) -> None:
        """End of a synchronous ribbon command: drop the insert point, restore a rejected insert."""
        inserting = self._insert_at is not None
        self._insert_at = None
        if added or not inserting:
            return
        message = self.error_label.text() if self.error_label.isVisible() else ""
        self._reselect_step(prior_row)
        if message:
            self._show_error(message)

    def _select_ribbon_sort(self, direction: str) -> None:
        if not self._confirm_insert_step():
            return
        selected = self._selected_preview_columns()
        prior_row = self.step_list.currentRow()
        if prior_row >= 0:
            self.step_list.setCurrentRow(-1)
        if selected:
            added = self._add_step(
                {"op": "sort_rows", "column": selected[0], "direction": direction},
                power_bi_name=True,
            )
            self._finish_insert(added, prior_row)
            if added:
                self.step_settings_toggle.setChecked(False)
            return
        self._open_operation_dialog(
            "sort_rows", selected, option_value=direction, prior_row=prior_row
        )

    def _select_ribbon_data_type(self, data_type: str) -> None:
        if not self._confirm_insert_step():
            return
        selected = self._selected_preview_columns()
        prior_row = self.step_list.currentRow()
        if prior_row >= 0:
            self.step_list.setCurrentRow(-1)
        if not selected:
            self._open_operation_dialog(
                "convert_type", selected, option_value=data_type, prior_row=prior_row
            )
            return
        added = False
        for column in selected:
            added = self._add_step(
                {"op": "convert_type", "column": column, "type": data_type},
                power_bi_name=True,
            )
            if not added:
                break
        self._finish_insert(added, prior_row)
        if added:
            self.step_settings_toggle.setChecked(False)

    def _select_ribbon_operation(self, operation: str) -> None:
        if not self._confirm_insert_step():
            return
        operation_index = self.operation_combo.findData(operation)
        if operation_index < 0:
            self._insert_at = None
            self._show_error(
                f"The {operation.replace('_', ' ').title()} command is not available in this editor."
            )
            return
        prior_row = self.step_list.currentRow()
        if operation == "conditional_column":
            self._open_conditional_dialog(prior_row=prior_row)
            return
        if operation == "add_custom_column":
            if prior_row >= 0:
                self.step_list.setCurrentRow(-1)
            self.operation_combo.setCurrentIndex(operation_index)
            self._configure_editor()
            before = len(self._steps)
            if not self._launch_custom_column_dialog():
                self._restore_non_custom_operation()
            self._finish_insert(len(self._steps) > before, prior_row)
            return
        selected = self._selected_preview_columns()
        if prior_row >= 0:
            self.step_list.setCurrentRow(-1)
        before = len(self._steps)
        if self._apply_direct_operation(operation, selected):
            self._finish_insert(len(self._steps) > before, prior_row)
            return
        self._open_operation_dialog(operation, selected, prior_row=prior_row)

    def _apply_direct_operation(self, operation: str, selected: list[str]) -> bool:
        """Apply a command that needs no further input. False means it needs a dialog."""
        if operation in self._STEP_OPERATIONS_WITHOUT_SETTINGS | self._PARAMETERLESS_OPERATIONS:
            steps: list[dict[str, Any]] = [{"op": operation}]
        elif operation in self._SELECTION_OPERATIONS_PER_COLUMN:
            if not selected:
                self._show_error("Select a column in the preview first.")
                return True
            taken = set(self._editor_base_candidate().headers)
            steps = []
            for column in selected:
                step: dict[str, Any] = {"op": operation, "column": column}
                if operation == "duplicate_column":
                    new_name, suffix = f"{column} - Copy", 0
                    while new_name in taken:
                        suffix += 1
                        new_name = f"{column} - Copy{suffix}"
                    taken.add(new_name)
                    step["new_name"] = new_name
                steps.append(step)
        elif operation in self._SELECTION_OPERATIONS_COLUMN_LIST:
            if not selected:
                self._show_error("Select one or more columns in the preview first.")
                return True
            step = {"op": operation, "columns": list(selected)}
            if operation in {"unpivot_columns", "unpivot_other_columns"}:
                step["attribute_name"] = "Attribute"
                step["value_name"] = "Value"
            steps = [step]
        elif operation == "remove_duplicates":
            steps = (
                [{"op": operation, "columns": list(selected)}]
                if selected else [{"op": operation}]
            )
        else:
            return False
        for step in steps:
            if not self._add_step(step, power_bi_name=True):
                break
        self.step_settings_toggle.setChecked(False)
        return True

    def _close_operation_dialog(self) -> None:
        for name in ("_operation_dialog", "_conditional_dialog"):
            dialog = getattr(self, name, None)
            if dialog is not None:
                dialog.reject()

    def _open_operation_dialog(
        self,
        operation: str,
        selected: list[str],
        *,
        option_value: str | None = None,
        prior_row: int = -1,
    ) -> None:
        """Show the command's settings in a modal OK / Cancel dialog (nothing applies until OK)."""
        insert_at = self._insert_at
        self._close_operation_dialog()
        self._insert_at = insert_at
        operation_index = self.operation_combo.findData(operation)
        self.operation_combo.setCurrentIndex(operation_index)
        self._configure_editor()
        if option_value is not None:
            index = self.option_combo.findData(option_value)
            if index >= 0:
                self.option_combo.setCurrentIndex(index)
        if selected and not self.column_combo.isHidden():
            self.column_combo.setCurrentText(selected[0])
        self._clear_error()
        title = self._OPERATION_DIALOG_TITLES.get(
            operation, self.operation_combo.currentText()
        )
        sub = QDialog(self)
        sub.setObjectName("powerQueryOperationDialog")
        sub.setWindowTitle(title)
        sub.setWindowModality(Qt.WindowModality.ApplicationModal)
        sub.setMinimumWidth(480)
        form_hint = self.operation_settings_panel.sizeHint()
        sub.resize(
            max(540, min(900, form_hint.width() + 48)),
            max(170, min(640, form_hint.height() + 110)),
        )
        layout = QVBoxLayout(sub)
        layout.setContentsMargins(16, 14, 16, 12)
        scroll = QScrollArea(sub)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        editor_layout = self.editor_panel.layout()
        panel_index = editor_layout.indexOf(self.operation_settings_panel)
        error_index = editor_layout.indexOf(self.error_label)
        editor_layout.removeWidget(self.operation_settings_panel)
        scroll.setWidget(self.operation_settings_panel)
        self.operation_settings_panel.setVisible(True)
        layout.addWidget(scroll, 1)
        editor_layout.removeWidget(self.error_label)
        self.error_label.setParent(sub)
        layout.addWidget(self.error_label)
        chrome = (
            self.operation_combo, self.operation_label, self.add_button,
            self.update_button, self.step_settings_toggle,
        )
        for widget in chrome:
            widget.setVisible(False)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=sub,
        )
        buttons.setObjectName("powerQueryOperationDialogButtons")
        sub.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        sub.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        sub.ok_button.clicked.connect(
            lambda: sub.accept() if self._add_step(power_bi_name=True) else None
        )
        buttons.rejected.connect(sub.reject)
        layout.addWidget(buttons)

        def restore(_result: int = 0) -> None:
            # Release the panel from the scroll area first so its resize events no
            # longer reach a scroll area that is about to be deleted.
            scroll.takeWidget()
            self.operation_settings_panel.setParent(self.editor_panel)
            editor_layout.insertWidget(max(panel_index, 0), self.operation_settings_panel)
            self.error_label.setParent(self.editor_panel)
            editor_layout.insertWidget(max(error_index, 1), self.error_label)
            for widget in chrome:
                widget.setVisible(True)
            self.step_settings_toggle.setChecked(False)
            self.operation_settings_panel.setVisible(False)
            if self._operation_dialog is sub:
                self._operation_dialog = None
            self._insert_at = None
            if _result != QDialog.DialogCode.Accepted.value:
                self._reselect_step(prior_row)
            sub.deleteLater()

        sub.finished.connect(restore)
        self._operation_dialog = sub
        sub.show()

    def _conditional_dialog_validator(
        self, editing_index: int | None
    ) -> Callable[[dict[str, Any]], str | None]:
        def validate(step: dict[str, Any]) -> str | None:
            next_steps = deepcopy(self._steps)
            if editing_index is None:
                next_steps.insert(self._insert_position(), step)
            else:
                if not 0 <= editing_index < len(next_steps):
                    return "The selected conditional-column step is no longer available."
                next_steps[editing_index] = step
            try:
                validated = validate_steps(next_steps)
                apply_transformations(
                    self._source_candidate, validated,
                    parameters=self._parameter_values(),
                )
            except (TransformationError, ValueError) as exc:
                return str(exc)
            return None
        return validate

    def _reselect_step(self, row: int) -> None:
        """After a cancelled dialog, put the applied-step selection back where it was."""
        if 0 <= row < len(self._steps) and self.step_list.currentRow() < 0:
            self.step_list.setCurrentRow(row)
            self.step_settings_toggle.setChecked(False)

    def _open_conditional_dialog(
        self, editing_index: int | None = None, *, prior_row: int = -1
    ) -> None:
        """Power BI's Add Conditional Column dialog; OK inserts (or updates) the step."""
        insert_at = self._insert_at
        self._close_operation_dialog()
        self._insert_at = insert_at
        selected = self._selected_preview_columns()
        if editing_index is None and self.step_list.currentRow() >= 0:
            self.step_list.setCurrentRow(-1)
        try:
            base = self._custom_column_base(editing_index)
        except TransformationError as exc:
            self._insert_at = None
            self._show_error(str(exc))
            return
        existing = (
            self._steps[editing_index]
            if editing_index is not None and 0 <= editing_index < len(self._steps)
            else None
        )
        sub = ConditionalColumnDialog(
            base.headers,
            initial_step=existing,
            default_column=selected[0] if selected else None,
            validate_callback=self._conditional_dialog_validator(editing_index),
            parent=self,
        )
        sub.setWindowModality(Qt.WindowModality.ApplicationModal)

        def accepted() -> None:
            step = sub.step()
            if editing_index is None:
                self._add_step(step, power_bi_name=True)
            else:
                self.step_list.setCurrentRow(editing_index)
                self._replace_selected_step(step)
            self.step_settings_toggle.setChecked(False)

        def finished(_result: int = 0) -> None:
            if self._conditional_dialog is sub:
                self._conditional_dialog = None
            self._insert_at = None
            if _result != QDialog.DialogCode.Accepted.value:
                self._reselect_step(prior_row)
            sub.deleteLater()

        sub.accepted.connect(accepted)
        sub.finished.connect(finished)
        self._conditional_dialog = sub
        sub.show()

    def _replace_selected_step(self, step: dict[str, Any]) -> bool:
        """Replace the selected applied step with an explicit step (used by dialogs)."""
        index = self.step_list.currentRow()
        if not 0 <= index < len(self._steps):
            return False
        next_steps = deepcopy(self._steps)
        try:
            next_steps[index] = step
            next_steps = validate_steps(next_steps)
            transformed = apply_transformations(
                self._source_candidate, next_steps,
                parameters=self._parameter_values(),
            )
        except TransformationError as exc:
            self._show_error(str(exc))
            return False
        if self._steps[index].get("op") != next_steps[index].get("op"):
            self._step_metadata[index] = {}
        self._steps = next_steps
        self._preview_candidate = transformed
        self._render_steps()
        self._refresh_preview()
        self.step_list.setCurrentRow(index)
        self._clear_error()
        return True

    def _custom_column_base(self, editing_index: int | None) -> ImportCandidate:
        steps = (
            self._steps[:editing_index] if editing_index is not None
            else self._steps[:self._insert_position()]
        )
        return apply_transformations(
            self._source_candidate, steps, parameters=self._parameter_values()
        )

    def _validate_custom_column_draft(
        self,
        name: str,
        expression: str,
        editing_index: int | None,
    ) -> str | None:
        step: dict[str, Any] = {
            "op": "add_custom_column", "name": name, "expression": expression,
        }
        next_steps = deepcopy(self._steps)
        if editing_index is None:
            next_steps.insert(self._insert_position(), step)
        else:
            if not 0 <= editing_index < len(next_steps):
                return "The selected custom-column step is no longer available."
            old_step = next_steps[editing_index]
            if "output_type" in old_step:
                step["output_type"] = old_step["output_type"]
            next_steps[editing_index] = step
        try:
            validated = validate_steps(next_steps)
            apply_transformations(
                self._source_candidate,
                validated,
                parameters=self._parameter_values(),
            )
        except (TransformationError, ValueError) as exc:
            return str(exc)
        return None

    def _launch_custom_column_dialog(
        self,
        editing_index: int | None = None,
        *,
        initial_name: str = "",
        initial_expression: str = "",
    ) -> bool:
        existing = (
            self._steps[editing_index]
            if editing_index is not None and 0 <= editing_index < len(self._steps)
            else {}
        )
        try:
            base = self._custom_column_base(editing_index)
        except TransformationError as exc:
            self._show_error(str(exc))
            return False
        dialog = CustomColumnDialog(
            base.headers,
            initial_name=str(existing.get("name", initial_name)),
            initial_expression=str(existing.get("expression", initial_expression)),
            functions=self._query_functions,
            parameters=self._query_parameters,
            validate_callback=lambda name, expression: self._validate_custom_column_draft(
                name, expression, editing_index
            ),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.column is None:
            return False
        name, expression = dialog.column
        self.operation_combo.setCurrentIndex(
            self.operation_combo.findData("add_custom_column")
        )
        self.value_edit.setText(name)
        self.custom_expression_edit.setPlainText(expression)
        if editing_index is None:
            self._add_step(power_bi_name=True)
        else:
            self._set_combo_data(
                self.custom_output_type_combo,
                existing.get("output_type", "text"),
            )
            self.step_list.setCurrentRow(editing_index)
            self._update_selected_step()
        return True

    def _on_operation_combo_changed(self, *_args: Any) -> None:
        operation = self.operation_combo.currentData()
        if operation != "add_custom_column":
            self._last_non_custom_operation = operation
        self._configure_editor(*_args)

    def _restore_non_custom_operation(self) -> None:
        operation_index = self.operation_combo.findData(
            self._last_non_custom_operation
        )
        if operation_index >= 0:
            self.operation_combo.setCurrentIndex(operation_index)
        self._configure_editor()

    def _on_operation_combo_activated(self, index: int) -> None:
        if self.operation_combo.itemData(index) != "add_custom_column":
            return
        if self.step_list.currentRow() >= 0:
            self.step_list.setCurrentRow(-1)
        self.step_settings_toggle.setChecked(True)
        self._configure_editor()
        if not self._launch_custom_column_dialog():
            self._restore_non_custom_operation()

    def _set_steps_panel_visible(self, visible: bool) -> None:
        self.steps_panel.setVisible(visible)

    def _set_formula_bar_visible(self, visible: bool) -> None:
        self.formula_bar_row.setVisible(bool(visible))

    def _set_settings_steps_pane_visible(self, visible: bool) -> None:
        self.settings_steps_pane.setVisible(bool(visible))
        toggle = getattr(self, "query_settings_toggle_button", None)
        if toggle is not None and toggle.isChecked() != bool(visible):
            toggle.setChecked(bool(visible))

    def _populate_queries(self) -> None:
        blocker = QSignalBlocker(self.query_list)
        self.query_list.clear()
        self.queries_heading.setText(f"Queries [{len(self._query_order)}]")
        query_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        for query_id in self._query_order:
            query = self._query_states[query_id]
            item = QListWidgetItem(query_icon, query["display_name"])
            item.setData(Qt.ItemDataRole.UserRole, query_id)
            item.setToolTip(
                query.get("preview_error") or query.get("description") or query["name"]
            )
            self.query_list.addItem(item)
        if self._active_query_id in self._query_order:
            self.query_list.setCurrentRow(self._query_order.index(self._active_query_id))
        del blocker
        self._update_edit_source_settings_button()
        self._update_combine_button_states()

    def _update_combine_button_states(self) -> None:
        _, candidates = self._session_combine_sources()
        enabled = len(candidates) >= 2
        for object_name in (
            "powerQueryAppendQueriesButton",
            "powerQueryMergeQueriesButton",
        ):
            button = self.findChild(QToolButton, object_name)
            if button is not None:
                button.setEnabled(enabled)

    def _show_query_context_menu(self, position: Any) -> None:
        item = self.query_list.itemAt(position)
        if item is None:
            return
        self.query_list.setCurrentItem(item)
        menu = QMenu(self.query_list)
        duplicate_action = menu.addAction("Duplicate Query")
        edit_source_action = menu.addAction("Edit Source Settings")
        delete_action = menu.addAction("Delete Query")
        state = self._query_states.get(self._active_query_id, {})
        source = state.get("source_record")
        edit_source_action.setEnabled(
            self._edit_source_candidate_callback is not None
            and isinstance(source, dict)
            and source.get("kind") in {
                "csv", "excel", "json", "xml", "parquet", "sqlite", "folder",
            }
            and not state.get("is_unavailable")
            and not state.get("is_duplicate")
        )
        selected = menu.exec(self.query_list.mapToGlobal(position))
        if selected is duplicate_action:
            self._duplicate_selected_query()
        elif selected is edit_source_action:
            self._edit_source_settings()
        elif selected is delete_action:
            self._delete_selected_query()

    def _add_new_source(self) -> None:
        """Stage a file-backed root query without mutating project state."""
        self._stage_new_source(self._new_source_candidate_callback)

    def _add_entered_data_source(self) -> None:
        """Stage a typed or pasted inline table as a new Power Query source."""
        dialog = EnterDataDialog(replacing=False, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return
        candidate = deepcopy(dialog.candidate)
        source_id = str(uuid4())
        query_name = str(candidate.options.get("name", "Entered data")).strip() or "Entered data"
        candidate.set_source_identity(source_id)
        source_record = source_from_candidate(candidate, source_id, query_name)
        source_record["query_name"] = query_name
        source_record["transform_steps"] = []
        self._stage_new_source(lambda: (candidate, source_record))

    def _add_folder_source(self) -> None:
        """Stage a combined folder source without mutating project state."""
        self._stage_new_source(self._new_folder_source_candidate_callback)

    def _add_sql_server_source(self) -> None:
        """Stage a SQL Server source without storing credentials before Apply."""
        self._stage_new_source(self._new_sql_server_source_candidate_callback)

    def _add_odata_source(self) -> None:
        """Stage an anonymous OData source in the current session."""
        self._stage_new_source(self._new_odata_source_candidate_callback)

    def _add_web_source(self) -> None:
        """Stage an anonymous Web source in the current session."""
        self._stage_new_source(self._new_web_source_candidate_callback)

    def _stage_new_source(
        self,
        callback: Callable[
            [], tuple[ImportCandidate, dict[str, Any]] | None
        ] | None,
    ) -> None:
        if callback is None:
            self._show_error("This source connector is unavailable in this editor session.")
            return
        self._save_active_query_state()
        try:
            staged = callback()
            if staged is None:
                return
            candidate, supplied_record = staged
            if not isinstance(candidate, ImportCandidate):
                raise ValueError("The source preview did not contain a table.")
            supported_kinds = {
                "csv", "excel", "json", "xml", "parquet", "sqlite", "folder",
                "sql_server", "odata", "web", "inline",
            }
            if candidate.kind not in supported_kinds:
                raise ValueError("Choose a supported local or remote table source.")
            if not isinstance(supplied_record, dict):
                raise ValueError("The source details are invalid.")
            source_record = deepcopy(supplied_record)
            source_id = str(source_record.get("id", "")).strip()
            source_path = str(source_record.get("path", "")).strip()
            source_kind = str(source_record.get("kind", ""))
            if not source_id or source_id in self._query_states:
                raise ValueError("The source needs a new unique ID.")
            if str(source_record.get("kind", "")) != candidate.kind:
                raise ValueError("The selected source type does not match its preview.")
            if source_kind in {"csv", "excel", "json", "xml", "parquet", "sqlite", "folder"}:
                if not source_path:
                    raise ValueError("The selected local source needs a valid path.")
            elif source_kind in {"sql_server", "odata", "web"}:
                connection = source_record.get("connection")
                if not isinstance(connection, dict) or not isinstance(
                    source_record.get("parser_options", {}), dict
                ):
                    raise ValueError("The connector details are invalid.")
                required_connection_key = {
                    "sql_server": "credential_ref",
                    "odata": "service_root",
                    "web": "url",
                }[source_kind]
                if not str(connection.get(required_connection_key, "")).strip():
                    raise ValueError("The connector connection details are incomplete.")
                if source_kind == "sql_server" and not str(
                    source_record.get("_staged_password", "")
                ):
                    raise ValueError("Enter a SQL Server password before adding this source.")
            elif source_kind != "inline":
                raise ValueError("Choose a supported local, remote, or entered-data source.")

            used_names = set(self._reserved_query_names)
            used_names.update(
                str(query.get("name", "")).strip().casefold()
                for query in self._query_states.values()
            )
            base_name = str(
                source_record.get("query_name")
                or source_record.get("name")
                or "New Source"
            ).strip() or "New Source"
            base_name = base_name[:120].rstrip() or "New Source"
            query_name = base_name
            suffix = 2
            while query_name.casefold() in used_names:
                suffix_text = f" ({suffix})"
                query_name = f"{base_name[:120 - len(suffix_text)].rstrip()}{suffix_text}"
                suffix += 1

            source_record.update({
                "id": source_id,
                "name": str(
                    source_record.get("name")
                    or source_path.rsplit("/", 1)[-1]
                    or source_record.get("query_name")
                    or source_kind
                ),
                "query_name": query_name,
                "kind": candidate.kind,
                "transform_steps": [],
            })
            if source_kind == "inline":
                source_record.pop("parser_options", None)
            else:
                source_record["parser_options"] = deepcopy(candidate.options)
            if source_path:
                source_record["path"] = source_path
            else:
                source_record.pop("path", None)
            candidate = deepcopy(candidate)
            candidate.set_source_identity(
                source_id,
                preserve_origins=source_kind == "folder",
            )
            source_types = infer_column_types(candidate.headers, candidate.rows)
            query_id = source_id
            self._query_states[query_id] = {
                "id": query_id,
                "name": query_name,
                "display_name": query_name,
                "description": "",
                "query_group": "",
                "is_saved_query": False,
                "load_enabled": True,
                "include_in_report_refresh": True,
                "query_definition": {},
                "is_new_query": True,
                "is_new_source": True,
                "source_record": source_record,
                "is_duplicate": False,
                "is_unavailable": False,
                "preview_refreshed": False,
                "source_candidate": candidate,
                "source_column_types": source_types,
                "column_types": dict(source_types),
                "original_steps": [],
                "steps": [],
                "step_metadata": [],
                "m_script": None,
                "preview_candidate": candidate,
            }
            self._query_order.append(query_id)
            self._populate_queries()
            self.query_list.setCurrentRow(self._query_order.index(query_id))
            self._clear_error()
        except (OSError, TypeError, ValueError, TransformationError) as exc:
            self._show_error(f"Could not stage the new source: {exc}")

    def _unique_copy_name(self, name: str) -> str:
        used_names = set(self._reserved_query_names)
        used_names.update(
            str(query.get("name", "")).strip().casefold()
            for query in self._query_states.values()
        )
        suffix_number = 1
        while True:
            suffix = " (Copy)" if suffix_number == 1 else f" (Copy {suffix_number})"
            base = (name.strip() or "Query")[: max(1, 120 - len(suffix))].rstrip()
            candidate = f"{base}{suffix}"
            if candidate.casefold() not in used_names:
                return candidate
            suffix_number += 1

    def _duplicate_selected_query(self) -> None:
        self._save_active_query_state()
        original = self._query_states.get(self._active_query_id)
        if original is None:
            self._show_error("Choose a query before duplicating it.")
            return
        if original.get("is_unavailable"):
            self._show_error(
                "This query cannot be duplicated until its source preview is available."
            )
            return
        query_id = str(uuid4())
        query_name = self._unique_copy_name(str(original.get("name", "Query")))
        duplicate = deepcopy(original)
        duplicate.update({
            "id": query_id,
            "name": query_name,
            "display_name": (
                f"{original['query_group']} / {query_name}"
                if original.get("query_group") else query_name
            ),
            "is_new_query": True,
            "is_duplicate": True,
            "duplicate_of_id": self._active_query_id,
            "original_steps": deepcopy(original["steps"]),
            "steps": deepcopy(original["steps"]),
            "step_metadata": deepcopy(original.get("step_metadata", [])),
        })
        if duplicate.get("is_new_source") and isinstance(
            duplicate.get("source_record"), dict
        ):
            duplicate["source_record"]["id"] = query_id
            duplicate["source_record"]["query_name"] = query_name
        # A duplicated query has a different root binding in its M `Source`
        # expression. Regenerate its script from the copied local steps.
        duplicate.pop("m_script", None)
        duplicate["preview_candidate"] = apply_transformations(
            duplicate["source_candidate"], duplicate["steps"],
            parameters=self._parameter_values(),
        )
        duplicate["column_types"] = column_types_after_steps(
            duplicate["source_candidate"].headers,
            duplicate["steps"],
            output_headers=duplicate["preview_candidate"].headers,
            initial_types=duplicate.get("source_column_types", {}),
        )
        self._query_states[query_id] = duplicate
        self._query_order.append(query_id)
        self._populate_queries()
        row = self._query_order.index(query_id)
        blocker = QSignalBlocker(self.query_list)
        self.query_list.setCurrentRow(row)
        del blocker
        self._switch_query(row)
        self._clear_error()

    def _delete_selected_query(self) -> None:
        self._save_active_query_state()
        query_id = self._active_query_id
        query = self._query_states.get(query_id)
        if query is None:
            self._show_error("Choose a query before deleting it.")
            return
        if len(self._query_order) <= 1:
            self._show_error("At least one query must remain open in the editor.")
            return
        dependent_ids = set(self._query_dependents.get(query_id, []))
        dependent_ids.update(
            other_id
            for other_id, other in self._query_states.items()
            if other_id != query_id
            and query_id in other.get("query_definition", {}).get("source_ids", [])
        )
        blocking_dependents = sorted(
            dependent_id for dependent_id in dependent_ids
            if dependent_id not in self._deleted_query_ids
        )
        if blocking_dependents:
            names = [
                str(self._query_states.get(item, {}).get("name", item))
                for item in blocking_dependents
            ]
            self._show_error(
                "Delete dependent queries first: " + ", ".join(names)
            )
            return
        answer = QMessageBox.question(
            self,
            "Delete Query",
            f"Delete {query['name']} from this project? The linked source file will not be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        removed_active = query_id == self._active_query_id
        if not query.get("is_new_query"):
            self._deleted_query_ids.add(query_id)
        self._query_order.remove(query_id)
        self._query_states.pop(query_id, None)
        if removed_active:
            self._active_query_id = ""
        self._populate_queries()
        if removed_active:
            self._switch_query(0)
            blocker = QSignalBlocker(self.query_list)
            self.query_list.setCurrentRow(0)
            del blocker
        self._refresh_preview()
        self._refresh_column_profiles()
        self._clear_error()

    def _query_source_names(
        self, state: dict[str, Any] | None
    ) -> list[str] | None:
        definition = (state or {}).get("query_definition", {})
        if definition.get("operation") != "append":
            return None
        source_ids = definition.get("source_ids", [])
        if not isinstance(source_ids, list) or len(source_ids) != 2:
            return []
        names: list[str] = []
        for source_id in source_ids:
            parent = self._query_states.get(str(source_id))
            if parent is None or parent.get("is_unavailable"):
                return []
            names.append(str(parent.get("name", "")).strip())
        return names

    def _query_sources_for_names(
        self, names: list[str] | None, state: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        if names is None:
            return []
        definition = (state or {}).get("query_definition", {})
        source_ids = definition.get("source_ids", [])
        if (
            definition.get("operation") != "append"
            or not isinstance(source_ids, list)
            or len(source_ids) != len(names)
        ):
            return []
        sources: list[dict[str, Any]] = []
        for source_id, name in zip(source_ids, names):
            parent = self._query_states.get(str(source_id))
            candidate = (parent or {}).get("preview_candidate")
            if (
                parent is None
                or parent.get("is_unavailable")
                or str(parent.get("name", "")).casefold() != name.casefold()
                or not isinstance(candidate, ImportCandidate)
            ):
                return []
            sources.append({
                "id": str(parent.get("id", "")),
                "name": str(parent.get("name", "")),
                "candidate": candidate,
            })
        return sources

    def _save_active_query_state(self) -> None:
        state = self._query_states.get(self._active_query_id)
        if state is None or state.get("is_unavailable"):
            return
        state["name"] = self.query_name_edit.text()
        state["description"] = self.query_description_edit.toPlainText()
        state["steps"] = deepcopy(self._steps)
        state["step_metadata"] = deepcopy(self._step_metadata)
        state["preview_candidate"] = self._preview_candidate
        self._rebind_m_script_source_names(state)
        state["query_group"] = self.query_group_edit.text()
        state["load_enabled"] = self.query_load_enabled_checkbox.isChecked()
        state["include_in_report_refresh"] = (
            self.query_refresh_included_checkbox.isChecked()
        )
        try:
            state["column_types"] = column_types_after_steps(
                self._source_candidate.headers,
                self._steps,
                output_headers=self._preview_candidate.headers,
                initial_types=state.get("source_column_types", {}),
            )
        except TransformationError:
            pass
        group_name = state["query_group"].strip()
        display_name = state["name"].strip() or "Query name required"
        state["display_name"] = (
            f"{group_name} / {display_name}" if group_name else display_name
        )
        for row, query_id in enumerate(self._query_order):
            if query_id == self._active_query_id:
                self.query_list.item(row).setText(state["display_name"])
                self.query_list.item(row).setToolTip(
                    state.get("description") or display_name
                )
                break
        self._query_name = state["name"].strip() or self._query_name
        self._update_refresh_preview_button()
        self._refresh_staged_query_dependencies()

    def _rebind_m_script_source_names(self, query: dict[str, Any]) -> None:
        saved_m_script = query.get("m_script")
        if not isinstance(saved_m_script, str):
            return
        source_names = self._query_source_names(query)
        steps = query.get("steps", [])
        query_name = str(query.get("name", ""))
        parameters = set(self._parameter_values())
        initial_types = query.get("source_column_types", {})
        is_current = m_script_matches_steps(
            saved_m_script,
            query_name,
            steps,
            parameter_names=parameters,
            query_functions=self._query_functions,
            source_query_names=source_names,
            initial_column_types=initial_types,
        )
        if is_current:
            if source_names is not None:
                query["m_script_source_names"] = list(source_names)
            return

        if isinstance(source_names, list) and len(source_names) == 2:
            rewritten = rewrite_m_append_source_names(
                saved_m_script,
                query_name,
                steps,
                query.get("m_script_source_names", []),
                source_names,
                parameter_names=parameters,
                query_functions=self._query_functions,
                initial_column_types=initial_types,
            )
            if rewritten is not None and m_script_matches_steps(
                rewritten,
                query_name,
                steps,
                parameter_names=parameters,
                query_functions=self._query_functions,
                source_query_names=source_names,
                initial_column_types=initial_types,
            ):
                query["m_script"] = rewritten
                query["m_script_source_names"] = list(source_names)
                return

        query.pop("m_script", None)
        query.pop("m_script_source_names", None)

    def _refresh_staged_query_dependencies(self) -> None:
        """Keep dependent M sources and newly staged previews aligned with edits."""
        for query_id in self._query_order:
            query = self._query_states.get(query_id, {})
            if not query.get("is_unavailable"):
                self._rebind_m_script_source_names(query)
            definition = query.get("query_definition", {})
            source_ids = definition.get("source_ids", [])
            operation = definition.get("operation")
            if not query.get("is_new_query") or query.get("is_unavailable") or operation not in {
                "reference", "append", "merge"
            }:
                continue
            expected_inputs = 1 if operation == "reference" else 2
            if len(source_ids) != expected_inputs:
                continue
            parents = [self._query_states.get(str(source_id)) for source_id in source_ids]
            if any(parent is None or parent.get("is_unavailable") for parent in parents):
                continue
            try:
                parent_candidates = [
                    parent.get("preview_candidate") for parent in parents
                ]
                if any(
                    not isinstance(candidate, ImportCandidate)
                    for candidate in parent_candidates
                ):
                    continue
                if operation == "reference":
                    raw_candidate = parent_candidates[0]
                    source_types = dict(parents[0].get("column_types", {}))
                elif operation == "append":
                    raw_candidate = append_candidates(parent_candidates)
                    source_types = self._combined_source_types(
                        operation, source_ids, raw_candidate
                    )
                else:
                    raw_candidate = merge_candidates(
                        parent_candidates[0],
                        parent_candidates[1],
                        left_keys=definition.get("left_keys", []),
                        right_keys=definition.get("right_keys", []),
                        join_kind=str(definition.get("join_kind", "")),
                        right_name=str(definition.get("right_name", "Right")),
                    )
                    source_types = self._combined_source_types(
                        operation, source_ids, raw_candidate
                    )
                raw_candidate = _candidate_with_source_id(raw_candidate, query_id)
                query["source_candidate"] = raw_candidate
                query["source_column_types"] = source_types
                preview = apply_transformations(
                    raw_candidate, query.get("steps", []),
                    parameters=self._parameter_values(),
                )
                query["preview_candidate"] = preview
                query["column_types"] = column_types_after_steps(
                    raw_candidate.headers,
                    query.get("steps", []),
                    output_headers=preview.headers,
                    initial_types=source_types,
                )
                query.pop("preview_error", None)
            except (QueryError, TransformationError, TypeError, ValueError) as exc:
                query["preview_error"] = str(exc)
                query["source_candidate"] = ImportCandidate(
                    kind="query", headers=[], rows=[], options={}, notices=[]
                )
                query["preview_candidate"] = ImportCandidate(
                    kind="query", headers=[], rows=[], options={}, notices=[]
                )
                query["column_types"] = {}

    def _session_combine_sources(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, ImportCandidate]]:
        tables: list[dict[str, Any]] = []
        candidates: dict[str, ImportCandidate] = {}
        for query_id in self._query_order:
            query = self._query_states.get(query_id, {})
            candidate = query.get("preview_candidate")
            if query.get("is_unavailable") or not isinstance(candidate, ImportCandidate):
                continue
            candidates[query_id] = candidate
            tables.append({
                "sourceId": query_id,
                "name": str(query.get("name", "")),
                "displayName": str(query.get("display_name", query.get("name", ""))),
                "headers": list(candidate.headers),
                "columnTypes": dict(query.get("column_types", {})),
            })
        return tables, candidates

    def _append_queries(self) -> None:
        self._save_active_query_state()
        tables, candidates = self._session_combine_sources()
        if len(tables) < 2:
            self._show_error("Load at least two available queries before appending.")
            return
        dialog = AppendQueriesDialog(tables, candidates, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return
        source_ids = dialog.source_ids
        self._stage_combined_query(
            dialog.query_name,
            {"operation": "append", "source_ids": source_ids},
            dialog.candidate,
            self._append_output_types(source_ids, dialog.candidate.headers),
        )

    def _merge_queries(self) -> None:
        self._save_active_query_state()
        tables, candidates = self._session_combine_sources()
        if len(tables) < 2:
            self._show_error("Load at least two available queries before merging.")
            return
        dialog = MergeQueriesDialog(tables, candidates, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return
        definition = dialog.query_definition
        source_ids = [str(item) for item in definition.get("source_ids", [])]
        output_types = self._combined_source_types(
            "merge", source_ids, dialog.candidate
        )
        self._stage_combined_query(
            dialog.query_name,
            definition,
            dialog.candidate,
            output_types,
        )

    def _append_output_types(
        self, source_ids: list[str], headers: list[str]
    ) -> dict[str, str]:
        parents = [self._query_states.get(source_id, {}) for source_id in source_ids]
        if len(parents) != 2:
            return {header: "text" for header in headers}
        first_types = dict(parents[0].get("column_types", {}))
        second_types = dict(parents[1].get("column_types", {}))
        return {
            header: first_types.get(header, "text")
            if first_types.get(header, "text") == second_types.get(header, "text")
            else "text"
            for header in headers
        }

    def _combined_source_types(
        self,
        operation: str,
        source_ids: list[str],
        candidate: ImportCandidate,
    ) -> dict[str, str]:
        if operation == "append":
            return self._append_output_types(source_ids, candidate.headers)
        if operation != "merge":
            return {}
        column_sources = candidate.options.get("column_sources", {})
        if not isinstance(column_sources, dict):
            return {}
        result: dict[str, str] = {}
        for output_column, origin in column_sources.items():
            if not isinstance(origin, dict):
                continue
            parent_index = 0 if origin.get("side") == "left" else 1
            if parent_index >= len(source_ids):
                continue
            parent = self._query_states.get(str(source_ids[parent_index]), {})
            parent_types = parent.get("column_types", {})
            result[str(output_column)] = str(
                parent_types.get(str(origin.get("column", "")), "text")
            )
        return result

    def _stage_combined_query(
        self,
        query_name: str,
        definition: dict[str, Any],
        candidate: ImportCandidate,
        output_types: dict[str, str],
    ) -> None:
        query_name = query_name.strip()
        used_names = {
            str(query.get("name", "")).strip().casefold()
            for query in self._query_states.values()
        }
        used_names.update(self._reserved_query_names)
        if (
            not query_name
            or len(query_name) > 120
            or any(ord(char) < 32 for char in query_name)
            or "\x00" in query_name
        ):
            self._show_error("Query names must be 1–120 characters and contain no control characters.")
            return
        if query_name.casefold() in used_names:
            self._show_error(f"A query or model table named {query_name!r} already exists.")
            return
        source_ids = [str(item) for item in definition.get("source_ids", [])]
        if (
            definition.get("operation") not in {"append", "merge"}
            or len(source_ids) != 2
            or source_ids[0] == source_ids[1]
            or any(source_id not in self._query_states for source_id in source_ids)
        ):
            self._show_error("Choose two distinct, available queries to combine.")
            return
        query_id = str(uuid4())
        candidate = _candidate_with_source_id(candidate, query_id)
        try:
            steps = validate_steps([
                {"op": "convert_type", "column": header, "type": output_types.get(header, "text")}
                for header in candidate.headers
                if output_types.get(header, "text") != "text"
            ])
            preview = apply_transformations(
                candidate, steps, parameters=self._parameter_values()
            )
            column_types = column_types_after_steps(
                candidate.headers,
                steps,
                output_headers=preview.headers,
                initial_types=output_types,
            )
        except (TransformationError, TypeError, ValueError) as exc:
            self._show_error(f"Could not stage the combined query: {exc}")
            return
        self._query_states[query_id] = {
            "id": query_id,
            "name": query_name,
            "display_name": query_name,
            "description": "",
            "query_group": "",
            "is_saved_query": True,
            "load_enabled": True,
            "include_in_report_refresh": True,
            "query_definition": deepcopy(definition),
            "is_new_query": True,
            "is_duplicate": False,
            "is_unavailable": False,
            "source_candidate": candidate,
            "source_column_types": dict(output_types),
            "column_types": column_types,
            "original_steps": [],
            "steps": steps,
            "step_metadata": [{} for _ in steps],
            "preview_candidate": preview,
        }
        self._query_order.append(query_id)
        self._refresh_staged_query_dependencies()
        self._populate_queries()
        self.query_list.setCurrentRow(self._query_order.index(query_id))
        self._clear_error()

    def _switch_query(self, row: int, force_reload: bool = False) -> None:
        if not 0 <= row < self.query_list.count():
            return
        item = self.query_list.item(row)
        query_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not query_id or (query_id == self._active_query_id and not force_reload):
            return
        if not force_reload:
            self._save_active_query_state()
        self._active_query_id = query_id
        query = self._query_states[query_id]
        self._source_candidate = query["source_candidate"]
        self._query_name = query["name"]
        self._steps = deepcopy(query["steps"])
        self._step_metadata = deepcopy(query["step_metadata"])
        self._preview_candidate = query["preview_candidate"]
        blockers = [
            QSignalBlocker(widget)
            for widget in (
                self.query_name_edit,
                self.query_description_edit,
                self.query_group_edit,
                self.query_load_enabled_checkbox,
                self.query_refresh_included_checkbox,
            )
        ]
        self.query_name_edit.setText(query["name"])
        self.query_description_edit.setPlainText(query.get("description", ""))
        self.query_group_edit.setText(query.get("query_group", ""))
        self.query_load_enabled_checkbox.setChecked(query.get("load_enabled", True))
        self.query_refresh_included_checkbox.setChecked(
            query.get("include_in_report_refresh", True)
        )
        del blockers
        self._set_query_lifecycle_controls(bool(query.get("is_saved_query")))
        self._set_query_editing_enabled(not bool(query.get("is_unavailable")))
        self._update_refresh_preview_button()
        self._update_edit_source_settings_button()
        self._accepted_candidate = None
        self._accepted_steps = None
        self._accepted_queries = None
        self._render_steps()
        self._refresh_preview()
        self._configure_editor()
        self._update_step_controls()
        self._clear_error()
        if query.get("preview_error"):
            self._show_error(query["preview_error"])

    def _create_reference_query(self) -> None:
        """Stage a query that follows the selected query's current result."""
        self._save_active_query_state()
        parent = self._query_states.get(self._active_query_id)
        if parent is None:
            self._show_error("Choose a query before creating a reference.")
            return
        if parent.get("is_unavailable"):
            self._show_error(
                "This query cannot be referenced until its source preview is available."
            )
            return
        try:
            parent_types = column_types_after_steps(
                self._source_candidate.headers,
                self._steps,
                output_headers=self._preview_candidate.headers,
                initial_types=parent.get("source_column_types", {}),
            )
        except TransformationError as exc:
            self._show_error(f"Cannot reference this preview until its types are valid: {exc}")
            return

        base_name = (str(parent.get("name", "Query")).strip() or "Query")[:96]
        desired_name = f"{base_name} (Reference)"
        used_names = {
            str(query.get("name", "")).strip().casefold()
            for query in self._query_states.values()
        }
        used_names.update(self._reserved_query_names)
        query_name = desired_name
        suffix = 2
        while query_name.casefold() in used_names:
            query_name = f"{base_name} (Reference {suffix})"
            suffix += 1

        query_id = str(uuid4())
        query_candidate = ImportCandidate(
            kind="query",
            headers=list(self._preview_candidate.headers),
            rows=[lineaged_row(row, row) for row in self._preview_candidate.rows],
            options={},
            notices=[],
            source_id=query_id,
        )
        self._query_states[query_id] = {
            "id": query_id,
            "name": query_name,
            "display_name": query_name,
            "description": "",
            "query_group": str(parent.get("query_group", "")),
            "is_saved_query": True,
            "is_new_query": True,
            "load_enabled": True,
            "include_in_report_refresh": True,
            "query_definition": {
                "operation": "reference",
                "source_ids": [self._active_query_id],
            },
            "source_candidate": query_candidate,
            "source_column_types": parent_types,
            "column_types": dict(parent_types),
            "original_steps": [],
            "steps": [],
            "step_metadata": [],
            "preview_candidate": query_candidate,
        }
        self._query_order.append(query_id)
        self._populate_queries()
        self.query_list.setCurrentRow(self._query_order.index(query_id))
        self._clear_error()

    def _set_query_lifecycle_controls(self, is_saved_query: bool) -> None:
        self.query_load_enabled_checkbox.setVisible(is_saved_query)
        self.query_load_enabled_checkbox.setEnabled(is_saved_query)
        self.query_refresh_included_checkbox.setVisible(is_saved_query)
        self.query_refresh_included_checkbox.setEnabled(is_saved_query)

    def _set_query_editing_enabled(self, enabled: bool) -> None:
        """Keep unavailable query records visible for removal without editing them."""
        self.query_settings_panel.setEnabled(enabled)
        self.ribbon_tabs.setEnabled(enabled)
        self.steps_panel.setEnabled(enabled)
        self.editor_panel.setEnabled(enabled)

    def _parameter_values(self) -> dict[str, Any]:
        return parameter_values(self._query_parameters, self._query_functions)

    def _insert_custom_parameter(self) -> None:
        name = str(self.custom_parameter_combo.currentData() or "")
        if not name:
            return
        cursor = self.custom_expression_edit.textCursor()
        cursor.insertText(name)
        self.custom_expression_edit.setTextCursor(cursor)
        self.custom_expression_edit.setFocus()

    def _insert_custom_function(self) -> None:
        name = str(self.custom_function_combo.currentData() or "")
        if not name:
            return
        cursor = self.custom_expression_edit.textCursor()
        cursor.insertText(f"{name}([Column])")
        self.custom_expression_edit.setTextCursor(cursor)
        self.custom_expression_edit.setFocus()

    def _manage_query_parameters(self) -> None:
        self._save_active_query_state()
        dialog = ManageQueryParametersDialog(self._query_parameters, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.parameters is None:
            return
        self._query_parameters = dialog.parameters
        values = self._parameter_values()
        for query_id in self._query_order:
            query = self._query_states.get(query_id)
            if query is None or query.get("is_unavailable"):
                continue
            definition = query.get("query_definition", {})
            operation = definition.get("operation")
            source_ids = [str(item) for item in definition.get("source_ids", [])]
            try:
                if operation in {"reference", "append", "merge"}:
                    expected = 1 if operation == "reference" else 2
                    parents = [self._query_states.get(item) for item in source_ids]
                    if len(parents) == expected and all(
                        parent is not None
                        and not parent.get("is_unavailable")
                        and isinstance(parent.get("preview_candidate"), ImportCandidate)
                        for parent in parents
                    ):
                        parent_candidates = [parent["preview_candidate"] for parent in parents]
                        if operation == "reference":
                            raw_candidate = parent_candidates[0]
                            source_types = dict(parents[0].get("column_types", {}))
                        elif operation == "append":
                            raw_candidate = append_candidates(parent_candidates)
                            source_types = self._combined_source_types(
                                operation, source_ids, raw_candidate
                            )
                        else:
                            raw_candidate = merge_candidates(
                                parent_candidates[0], parent_candidates[1],
                                left_keys=definition.get("left_keys", []),
                                right_keys=definition.get("right_keys", []),
                                join_kind=str(definition.get("join_kind", "")),
                                right_name=str(definition.get("right_name", "Right")),
                            )
                            source_types = self._combined_source_types(
                                operation, source_ids, raw_candidate
                            )
                        raw_candidate = _candidate_with_source_id(
                            raw_candidate, query_id
                        )
                        query["source_candidate"] = raw_candidate
                        query["source_column_types"] = source_types
                preview = apply_transformations(
                    query["source_candidate"], query["steps"], parameters=values
                )
                query["preview_candidate"] = preview
                query["column_types"] = column_types_after_steps(
                    query["source_candidate"].headers,
                    query["steps"],
                    output_headers=preview.headers,
                    initial_types=query.get("source_column_types", {}),
                )
                query.pop("preview_error", None)
            except (QueryError, TransformationError, TypeError, ValueError) as exc:
                query["preview_error"] = str(exc)
        self._refresh_staged_query_dependencies()
        self._switch_query(
            self._query_order.index(self._active_query_id), force_reload=True
        )
        if self._query_states.get(self._active_query_id, {}).get("preview_error"):
            self._show_error(
                self._query_states[self._active_query_id]["preview_error"]
            )
        else:
            self._clear_error()

    def _manage_query_functions(self) -> None:
        self._save_active_query_state()
        referenced_names: set[str] = set()
        for query in self._query_states.values():
            referenced_names.update(
                function_references(query.get("steps", []), self._query_functions)
            )
        dialog = ManageQueryFunctionsDialog(
            self._query_functions, referenced_names, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.functions is None:
            return
        next_functions = dialog.functions
        parameter_names = {item["name"].casefold() for item in self._query_parameters}
        if parameter_names & {item["name"].casefold() for item in next_functions}:
            self._show_error("Power Query parameter and function names must be unique.")
            return
        old_by_name = {item["name"]: item for item in self._query_functions}
        new_by_name = {item["name"]: item for item in next_functions}
        changed_names = {
            name for name in old_by_name.keys() | new_by_name.keys()
            if old_by_name.get(name) != new_by_name.get(name)
        }
        unavailable_dependents = [
            str(query.get("name", query_id))
            for query_id, query in self._query_states.items()
            if query.get("is_unavailable")
            and function_references(query.get("steps", []), self._query_functions)
            & changed_names
        ]
        if unavailable_dependents:
            self._show_error(
                "Cannot change a function used by an unavailable query: "
                + ", ".join(unavailable_dependents)
                + ". Reconnect or refresh that query, then retry the function change."
            )
            return
        self._query_functions = next_functions
        values = self._parameter_values()
        for query_id in self._query_order:
            query = self._query_states.get(query_id)
            if query is None or query.get("is_unavailable"):
                continue
            definition = query.get("query_definition", {})
            operation = definition.get("operation")
            source_ids = [str(item) for item in definition.get("source_ids", [])]
            try:
                if operation in {"reference", "append", "merge"}:
                    expected = 1 if operation == "reference" else 2
                    parents = [self._query_states.get(item) for item in source_ids]
                    if len(parents) == expected and all(
                        parent is not None
                        and not parent.get("is_unavailable")
                        and isinstance(parent.get("preview_candidate"), ImportCandidate)
                        for parent in parents
                    ):
                        parent_candidates = [parent["preview_candidate"] for parent in parents]
                        if operation == "reference":
                            query["source_candidate"] = parent_candidates[0]
                            query["source_column_types"] = dict(
                                parents[0].get("column_types", {})
                            )
                        elif operation == "append":
                            query["source_candidate"] = append_candidates(parent_candidates)
                            query["source_column_types"] = self._combined_source_types(
                                operation, source_ids, query["source_candidate"]
                            )
                        else:
                            query["source_candidate"] = merge_candidates(
                                parent_candidates[0], parent_candidates[1],
                                left_keys=definition.get("left_keys", []),
                                right_keys=definition.get("right_keys", []),
                                join_kind=str(definition.get("join_kind", "")),
                                right_name=str(definition.get("right_name", "Right")),
                            )
                            query["source_column_types"] = self._combined_source_types(
                                operation, source_ids, query["source_candidate"]
                            )
                if isinstance(query.get("source_candidate"), ImportCandidate):
                    query["source_candidate"] = _candidate_with_source_id(
                        query["source_candidate"], query_id
                    )
                preview = apply_transformations(
                    query["source_candidate"], query["steps"], parameters=values
                )
                query["preview_candidate"] = preview
                query["column_types"] = column_types_after_steps(
                    query["source_candidate"].headers,
                    query["steps"],
                    output_headers=preview.headers,
                    initial_types=query.get("source_column_types", {}),
                )
                query.pop("preview_error", None)
            except (QueryError, TransformationError, TypeError, ValueError) as exc:
                query["preview_error"] = str(exc)
        self._refresh_staged_query_dependencies()
        self._switch_query(
            self._query_order.index(self._active_query_id), force_reload=True
        )
        active_error = self._query_states.get(self._active_query_id, {}).get("preview_error")
        if active_error:
            self._show_error(active_error)
        else:
            self._clear_error()

    def _set_preview_visible(self, visible: bool) -> None:
        if visible:
            self.preview_tabs.setCurrentWidget(self.preview)
            self.preview.setVisible(True)
        self.preview.setVisible(visible)
        self.preview_tabs.setVisible(visible)

    def _show_quality_view(self, visible: bool = True) -> None:
        self.preview_header.set_quality_visible(visible)

    def _show_profile_view(self, visible: bool = True) -> None:
        self.preview_header.set_distribution_visible(visible)

    def _show_preview_column_menu(self, logical_index: int) -> None:
        headers = self._selected_preview_candidate().headers
        if logical_index < 0 or logical_index >= len(headers):
            return
        info = self._build_preview_column_menu(logical_index)
        self._column_menu_info = info
        chosen = info.menu.exec(self._preview_column_menu_position(logical_index))
        handler = info.handler_for(chosen)
        if handler is not None:
            handler()

    def _preview_column_scope(self) -> range:
        selected = self.step_list.currentRow()
        if 0 <= selected < len(self._steps):
            return range(selected + 1)
        return range(len(self._steps))

    def _column_sort_step_indexes(self, column: str) -> list[int]:
        indexes: list[int] = []
        for index in self._preview_column_scope():
            step = self._steps[index]
            if step["op"] == "sort_rows" and step["column"] == column:
                indexes.append(index)
            elif step["op"] == "sort_rows_by_columns" and any(
                sort["column"] == column for sort in step["sorts"]
            ):
                indexes.append(index)
        return indexes

    def _column_filter_step_indexes(self, column: str) -> list[int]:
        indexes: list[int] = []
        for index in self._preview_column_scope():
            step = self._steps[index]
            if step["op"] == "filter_rows" and step["column"] == column:
                indexes.append(index)
            elif step["op"] == "filter_rows_advanced" and all(
                clause["column"] == column for clause in step["clauses"]
            ):
                indexes.append(index)
        return indexes

    def _build_preview_column_menu(self, logical_index: int) -> _PreviewColumnMenu:
        """Build the Power BI style dropdown for one preview column."""
        candidate = self._selected_preview_candidate()
        column = candidate.headers[logical_index]
        profiles = self.preview_header._profiles
        type_name = (
            str(profiles[logical_index].get("type", "text"))
            if logical_index < len(profiles)
            else "text"
        )
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        menu.setObjectName("powerQueryColumnMenu")
        info = _PreviewColumnMenu(menu, column)

        def add(
            path: str,
            handler: Callable[[], None] | None,
            *,
            enabled: bool = True,
            tooltip: str = "",
            target: QMenu = menu,
        ) -> QAction:
            action = target.addAction(path.rsplit("/", 1)[-1])
            action.setEnabled(enabled)
            if tooltip:
                action.setToolTip(tooltip)
            info.register(path, action, handler if enabled else None)
            return action

        add("Sort Ascending", lambda: self._sort_preview_column(column, "asc"))
        add("Sort Descending", lambda: self._sort_preview_column(column, "desc"))
        add(
            "Clear Sort",
            lambda: self._clear_column_steps(column, self._column_sort_step_indexes(column)),
            enabled=bool(self._column_sort_step_indexes(column)),
            tooltip="" if self._column_sort_step_indexes(column) else "No sort on this column.",
        )
        add(
            "Clear Filter",
            lambda: self._clear_column_steps(column, self._column_filter_step_indexes(column)),
            enabled=bool(self._column_filter_step_indexes(column)),
            tooltip="" if self._column_filter_step_indexes(column) else "No filter on this column.",
        )
        add("Remove Empty", lambda: self._remove_empty_column_values(column))

        if type_name in _NUMBER_COLUMN_TYPES:
            self._add_number_filter_menu(info, add, column)
        elif type_name in _DATE_COLUMN_TYPES:
            self._add_date_filter_menu(info, add, column)
        elif type_name not in {"boolean", "time"}:
            self._add_text_filter_menu(info, add, column)

        menu.addSeparator()
        values, has_blank, truncated, has_errors = _column_distinct_values(
            candidate.rows, column
        )
        error = (
            f"Column {column!r} contains errors. Remove or replace those errors "
            "before filtering by values."
            if has_errors
            else ""
        )
        panel = _PowerQueryColumnFilterPanel(
            column, values, has_blank, truncated, error_message=error
        )
        info.panel = panel
        widget_action = QWidgetAction(menu)
        widget_action.setDefaultWidget(panel)
        menu.addAction(widget_action)
        info.widget_action = widget_action
        panel.applied.connect(
            lambda: (menu.close(), self._apply_column_value_selection(column, panel))
        )
        panel.cancelled.connect(menu.close)
        return info

    def _add_submenu(self, info: _PreviewColumnMenu, title: str) -> QMenu:
        submenu = info.menu.addMenu(title)
        submenu.setToolTipsVisible(True)
        info.register(title, submenu.menuAction())
        return submenu

    def _add_text_filter_menu(self, info: _PreviewColumnMenu, add: Any, column: str) -> None:
        submenu = self._add_submenu(info, "Text Filters")
        for label, operator in (
            ("Equals", "equals"),
            ("Does Not Equal", "not_equals"),
            ("Begins With", "begins_with"),
            ("Does Not Begin With", "does_not_begin_with"),
            ("Ends With", "ends_with"),
            ("Does Not End With", "does_not_end_with"),
            ("Contains", "contains"),
            ("Does Not Contain", "does_not_contain"),
        ):
            add(
                f"Text Filters/{label}…",
                lambda label=label, operator=operator: self._open_column_condition(
                    column, label, operator
                ),
                target=submenu,
            )

    def _add_number_filter_menu(self, info: _PreviewColumnMenu, add: Any, column: str) -> None:
        submenu = self._add_submenu(info, "Number Filters")
        for label, operator in (
            ("Equals", "equals"),
            ("Does Not Equal", "not_equals"),
            ("Greater Than", "greater_than"),
            ("Greater Than Or Equal To", "greater_than_or_equal"),
            ("Less Than", "less_than"),
            ("Less Than Or Equal To", "less_than_or_equal"),
            ("Between", "between"),
        ):
            add(
                f"Number Filters/{label}…",
                lambda label=label, operator=operator: self._open_column_condition(
                    column, label, operator, numeric=True
                ),
                target=submenu,
            )

    def _add_date_filter_menu(self, info: _PreviewColumnMenu, add: Any, column: str) -> None:
        submenu = self._add_submenu(info, "Date Filters")
        add(
            "Date Filters/Equals…",
            lambda: self._open_column_condition(
                column, "Equals", "equals", placeholder="yyyy-mm-dd"
            ),
            target=submenu,
        )
        # The local filter engine compares dates only by equality, so every other
        # date condition is shown disabled instead of pretending to work.
        for label in (
            "Before…", "After…", "Between…", "In the Next…", "In the Previous…",
            "Is Earliest", "Is Latest", "Year", "Quarter", "Month", "Week", "Day",
        ):
            add(
                f"Date Filters/{label}",
                None,
                enabled=False,
                tooltip=_NOT_SUPPORTED_YET,
                target=submenu,
            )

    def _preview_column_menu_position(self, logical_index: int) -> QPoint:
        header = self.preview_header
        for button in header._filter_buttons:
            if (
                button.property("logicalIndex") == logical_index
                and button.isVisible()
            ):
                return button.mapToGlobal(QPoint(0, button.height()))

        # A partly clipped section may not have a visible filter button. Keep
        # header clicks usable by anchoring at the nearest visible viewport edge.
        viewport = header.viewport()
        anchor_rect = header._filter_button_rect(logical_index)
        viewport_rect = viewport.rect()
        x = min(max(anchor_rect.left(), viewport_rect.left()), viewport_rect.right())
        y = min(
            max(anchor_rect.bottom() + 1, viewport_rect.top()),
            viewport_rect.bottom(),
        )
        return viewport.mapToGlobal(QPoint(x, y))

    def _sort_preview_column(self, column: str, direction: str) -> None:
        if not self._confirm_insert_step():
            return
        prior_row = self.step_list.currentRow()
        self.step_list.setCurrentRow(-1)
        operation_index = self.operation_combo.findData("sort_rows")
        if operation_index < 0:
            self._insert_at = None
            return
        self.operation_combo.setCurrentIndex(operation_index)
        self.column_combo.setCurrentIndex(self.column_combo.findText(column))
        self.step_settings_toggle.setChecked(True)
        self._set_combo_data(self.option_combo, direction)
        self._finish_insert(self._add_step(), prior_row)

    def _remove_empty_column_values(self, column: str) -> None:
        self._insert_step_after_selection({
            "op": "filter_rows", "column": column,
            "operator": "is_not_blank", "value": "",
        })

    def _open_column_condition(
        self,
        column: str,
        label: str,
        operator: str,
        *,
        numeric: bool = False,
        placeholder: str = "",
    ) -> None:
        dialog = _PowerQueryConditionDialog(
            column,
            label,
            2 if operator == "between" else 1,
            self,
            numeric=numeric,
            placeholder=placeholder,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if operator == "between":
            step: dict[str, Any] = {
                "op": "filter_rows_advanced",
                "clauses": [
                    {"column": column, "operator": "greater_than_or_equal",
                     "value": values[0], "join": "and"},
                    {"column": column, "operator": "less_than_or_equal",
                     "value": values[1], "join": "and"},
                ],
            }
        else:
            step = {
                "op": "filter_rows", "column": column,
                "operator": operator, "value": values[0],
            }
        self._insert_step_after_selection(step)

    def _clear_column_steps(self, column: str, indexes: list[int]) -> None:
        """Remove the given steps (or this column's level of a multi-column sort)."""
        if not indexes:
            return
        original_steps = deepcopy(self._steps)
        original_metadata = deepcopy(self._step_metadata)
        next_steps: list[dict[str, Any]] = []
        next_metadata: list[dict[str, Any]] = []
        for index, (step, metadata) in enumerate(
            zip(self._steps, self._step_metadata)
        ):
            if index in indexes:
                if step["op"] == "sort_rows_by_columns":
                    sorts = [s for s in step["sorts"] if s["column"] != column]
                    if sorts:
                        next_steps.append({**step, "sorts": sorts})
                        next_metadata.append(metadata)
                continue
            next_steps.append(step)
            next_metadata.append(metadata)
        try:
            next_steps = validate_steps(next_steps)
            next_metadata = validate_applied_step_metadata(
                next_metadata, len(next_steps)
            )
            transformed = apply_transformations(
                self._source_candidate,
                next_steps,
                parameters=self._parameter_values(),
            )
        except TransformationError as exc:
            self._steps = original_steps
            self._step_metadata = original_metadata
            self._show_error(str(exc))
            return
        self._steps = next_steps
        self._step_metadata = next_metadata
        self._preview_candidate = transformed
        self._render_steps()
        self._refresh_preview()
        self._configure_editor()
        self.step_list.setCurrentRow(min(indexes[0], self.step_list.count() - 1))
        self._clear_error()

    def _apply_column_value_selection(
        self, column: str, panel: _PowerQueryColumnFilterPanel
    ) -> None:
        selection = panel.selection()
        selected: list[Any] = selection["selected"]
        excluded: list[Any] = selection["excluded"]
        has_blank: bool = selection["has_blank"]
        blank_selected: bool = selection["blank_selected"]
        truncated: bool = selection["truncated"]
        blank_excluded = has_blank and not blank_selected
        if not excluded and not blank_excluded:
            return  # Everything listed is still selected: nothing to filter.

        exclude_count = len(excluded) + (1 if blank_excluded else 0)
        include_count = len(selected) + (1 if has_blank and blank_selected else 0)
        use_exclusion = (
            truncated
            or exclude_count <= include_count
            or include_count > MAX_FILTER_CLAUSES
        )
        clauses: list[dict[str, str]] = []
        if use_exclusion:
            for value in excluded:
                clauses.append({
                    "column": column, "operator": "not_equals",
                    "value": cell_to_text(value), "join": "and",
                })
            if blank_excluded:
                clauses.append({
                    "column": column, "operator": "is_not_blank",
                    "value": "", "join": "and",
                })
        else:
            for value in selected:
                clauses.append({
                    "column": column, "operator": "equals",
                    "value": cell_to_text(value),
                    "join": "and" if not clauses else "or",
                })
            if has_blank and blank_selected:
                clauses.append({
                    "column": column, "operator": "is_blank", "value": "",
                    "join": "and" if not clauses else "or",
                })
        if len(clauses) > MAX_FILTER_CLAUSES:
            self._show_error(
                f"This local value filter supports at most {MAX_FILTER_CLAUSES} "
                "changed values. Search the list or use Advanced Filter."
            )
            return
        if len(clauses) == 1:
            # The canonical single-condition step, so the M round trip is exact.
            only = clauses[0]
            step: dict[str, Any] = {
                "op": "filter_rows", "column": only["column"],
                "operator": only["operator"], "value": only["value"],
            }
        else:
            step = {"op": "filter_rows_advanced", "clauses": clauses}
        self._insert_step_after_selection(step)

    def _add_filter_by_selected_values(
        self, column: str, selected_values: list[Any]
    ) -> bool:
        if not selected_values:
            self._show_error("Select at least one value to add a filter step.")
            return False
        if len(selected_values) > MAX_FILTER_CLAUSES:
            self._show_error(
                f"This local value filter supports at most {MAX_FILTER_CLAUSES} "
                "selected values. Search the list or use Advanced Filter."
            )
            return False

        clauses: list[dict[str, str]] = []
        for index, value in enumerate(selected_values):
            if is_cell_error(value):
                self._show_error(
                    "Error values cannot be included in a value filter. "
                    "Remove or replace errors first."
                )
                return False
            if value is None:
                operator = "is_null"
                comparison = ""
            else:
                operator = "equals"
                comparison = cell_to_text(value)
            clauses.append({
                "column": column,
                "operator": operator,
                "value": comparison,
                "join": "and" if index == 0 else "or",
            })
        return self._insert_step_after_selection(
            {"op": "filter_rows_advanced", "clauses": clauses}
        )

    def _insert_step_after_selection(self, step: dict[str, Any]) -> bool:
        """Validate, apply and insert one step after the selected applied step."""
        selected_index = self.step_list.currentRow()
        insert_at = (
            selected_index + 1
            if 0 <= selected_index < len(self._steps)
            else len(self._steps)
        )
        try:
            next_steps = deepcopy(self._steps)
            next_steps.insert(insert_at, step)
            next_steps = validate_steps(next_steps)
            next_metadata = validate_applied_step_metadata(
                deepcopy(self._step_metadata), len(self._steps)
            )
            next_metadata.insert(insert_at, {})
            next_metadata = validate_applied_step_metadata(
                next_metadata, len(next_steps)
            )
            transformed = apply_transformations(
                self._source_candidate,
                next_steps,
                parameters=self._parameter_values(),
            )
        except TransformationError as exc:
            self._show_error(str(exc))
            return False
        self._steps = next_steps
        self._step_metadata = next_metadata
        self._preview_candidate = transformed
        self._render_steps()
        self._refresh_preview()
        self._configure_editor()
        self.step_list.setCurrentRow(insert_at)
        self._clear_error()
        return True

    def _show_schema_view(self) -> None:
        self.preview_tabs.setCurrentWidget(self.schema_table)

    def _show_data_preview(self) -> None:
        self.preview_tabs.setCurrentWidget(self.preview)
        self.preview.setVisible(True)
        self.preview_tabs.setVisible(True)

    def _show_query_dependencies(self) -> None:
        self._save_active_query_state()
        dialog = QueryDependenciesDialog(
            [self._query_states[query_id] for query_id in self._query_order],
            self,
        )
        dialog.exec()

    def _show_feature_guide(self) -> None:
        QMessageBox.information(
            self,
            "Power Query feature guide",
            "Home includes staged New Source for local files and folders plus Reference, Duplicate, Delete, Append, and Merge Query workflows. "
            "Append combines two queries with the same ordered columns; Merge supports the listed exact-match join kinds and key pairs. "
            "Home, Transform, and Add Column expose the local shaping operations supported by this editor. "
            "View includes the table preview, column quality, column profile, and the selected step's schema; the formula bar shows the selected step. "
            "Tools manages step order and edits.\n\n"
            "Advanced Editor reads and writes a bounded subset of Power Query M, including Group, Pivot, Unpivot, "
            "and the Table.Range, Table.RemoveLastN, and Table.AlternateRows row-window functions. It is not a full M runtime; "
            "unsupported expressions are rejected. These steps replay when the source refreshes.",
        )

    @property
    def candidate(self) -> ImportCandidate | None:
        return self._accepted_candidate if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def steps(self) -> list[dict[str, Any]] | None:
        return deepcopy(self._accepted_steps) if self.result() == QDialog.DialogCode.Accepted else None

    @property
    def accepted_queries(self) -> dict[str, dict[str, Any]] | None:
        if self.result() != QDialog.DialogCode.Accepted or self._accepted_queries is None:
            return None
        return deepcopy(self._accepted_queries)

    @property
    def accepted_parameters(self) -> list[dict[str, str]] | None:
        if self.result() != QDialog.DialogCode.Accepted or self._accepted_parameters is None:
            return None
        return deepcopy(self._accepted_parameters)

    @property
    def accepted_functions(self) -> list[dict[str, str]] | None:
        if self.result() != QDialog.DialogCode.Accepted or self._accepted_functions is None:
            return None
        return deepcopy(self._accepted_functions)

    @property
    def deleted_query_ids(self) -> set[str]:
        if self.result() != QDialog.DialogCode.Accepted:
            return set()
        return set(self._deleted_query_ids)

    def _configure_editor(self, *_args: Any) -> None:
        if _args:
            self.step_settings_toggle.setChecked(True)
        op = str(self.operation_combo.currentData())
        selected_index = self.step_list.currentRow()
        base_candidate = self._editor_base_candidate()
        self.column_combo.clear()
        self.column_combo.addItems(base_candidate.headers)
        self.pivot_value_column_combo.clear()
        self.conditional_test_column_combo.clear()
        self.conditional_test_column_combo.addItems(base_candidate.headers)
        self.conditional_test_value_column_combo.clear()
        self.conditional_test_value_column_combo.addItems(base_candidate.headers)
        self.conditional_output_column_combo.clear()
        self.conditional_output_column_combo.addItems(base_candidate.headers)
        self.conditional_else_column_combo.clear()
        self.conditional_else_column_combo.addItems(base_candidate.headers)
        self.value_edit.clear()
        self.filter_parameter_combo.clear()
        self.filter_parameter_combo.addItem("Use typed value", "")
        for parameter in self._query_parameters:
            self.filter_parameter_combo.addItem(
                parameter["name"], parameter["name"]
            )
        self.custom_parameter_combo.clear()
        self.custom_parameter_combo.addItem("Select parameter", "")
        for parameter in self._query_parameters:
            self.custom_parameter_combo.addItem(
                f"{parameter['name']} · {parameter['type'].replace('_', ' ')}",
                parameter["name"],
            )
        self.custom_function_combo.clear()
        self.custom_function_combo.addItem("Select function", "")
        for function in self._query_functions:
            self.custom_function_combo.addItem(
                f"{function['name']} · {function['return_type'].replace('_', ' ')}",
                function["name"],
            )
        self._set_combo_data(self.custom_output_type_combo, "text")
        self.culture_edit.setText("en-US")
        self.value_edit.setValidator(None)
        self.range_first_row_edit.clear()
        self.range_first_row_edit.setValidator(None)
        self.alternate_first_row_edit.clear()
        self.alternate_first_row_edit.setValidator(None)
        self.alternate_remove_count_edit.clear()
        self.alternate_remove_count_edit.setValidator(None)
        self.alternate_keep_count_edit.clear()
        self.alternate_keep_count_edit.setValidator(None)
        self.index_start_edit.clear()
        self.index_start_edit.setValidator(None)
        self.index_increment_edit.clear()
        self.index_increment_edit.setValidator(None)
        self.custom_expression_edit.clear()
        self.conditional_test_value_edit.clear()
        self.conditional_output_edit.clear()
        self.conditional_else_edit.clear()
        self._conditional_clauses = []
        self.conditional_clause_list.clear()
        self._filter_clauses = []
        self.advanced_filter_clause_list.clear()
        self._set_combo_data(self.advanced_filter_join_combo, "and")
        self.delimiter_edit.setPlaceholderText("Delimiter")
        self.conditional_test_value_kind_combo.setCurrentIndex(0)
        self.conditional_output_kind_combo.setCurrentIndex(0)
        self.conditional_else_kind_combo.setCurrentIndex(0)
        self.replacement_edit.clear()
        self.delimiter_edit.clear()
        self.end_delimiter_edit.clear()
        self.end_occurrence_edit.clear()
        self.attribute_name_edit.clear()
        self.value_column_name_edit.clear()
        self.option_combo.clear()
        self.option_combo.setToolTip("")
        pivot_visible = op == "pivot_column"
        self.pivot_value_column_label.setVisible(pivot_visible)
        self.pivot_value_column_combo.setVisible(pivot_visible)
        option_visible = op in {
            "filter_rows", "filter_rows_advanced", "sort_rows", "convert_type", "convert_type_using_locale",
            "pivot_column", "extract_text_by_delimiter",
        }
        self.option_combo.setVisible(option_visible)
        self.option_label.setVisible(option_visible)
        self.option_label.setText(
            "Aggregate values"
            if pivot_visible
            else "Extract"
            if op == "extract_text_by_delimiter"
            else "Target type"
            if op in {"convert_type", "convert_type_using_locale"}
            else "Filter operator"
            if op in {"filter_rows", "filter_rows_advanced"}
            else "Option"
        )
        culture_visible = op == "convert_type_using_locale"
        self.culture_edit.setVisible(culture_visible)
        self.culture_label.setVisible(culture_visible)
        custom_visible = op == "add_custom_column"
        self.custom_expression_label.setVisible(custom_visible)
        self.custom_expression_edit.setVisible(custom_visible)
        self.custom_parameter_widget.setVisible(
            custom_visible and self.custom_parameter_combo.count() > 1
        )
        self.custom_parameter_label.setVisible(
            custom_visible and self.custom_parameter_combo.count() > 1
        )
        self.custom_function_widget.setVisible(
            custom_visible and self.custom_function_combo.count() > 1
        )
        self.custom_function_label.setVisible(
            custom_visible and self.custom_function_combo.count() > 1
        )
        self.custom_output_type_label.setVisible(custom_visible)
        self.custom_output_type_combo.setVisible(custom_visible)
        conditional_visible = op == "conditional_column"
        self.conditional_column_label.setVisible(conditional_visible)
        self.conditional_column_widget.setVisible(conditional_visible)
        advanced_filter_visible = op == "filter_rows_advanced"
        self.advanced_filter_label.setVisible(advanced_filter_visible)
        self.advanced_filter_widget.setVisible(advanced_filter_visible)
        range_rows_visible = op == "keep_range_rows"
        self.range_first_row_label.setVisible(range_rows_visible)
        self.range_first_row_edit.setVisible(range_rows_visible)
        alternate_rows_visible = op == "remove_alternate_rows"
        for widget in (
            self.alternate_first_row_label,
            self.alternate_first_row_edit,
            self.alternate_remove_count_label,
            self.alternate_remove_count_edit,
            self.alternate_keep_count_label,
            self.alternate_keep_count_edit,
        ):
            widget.setVisible(alternate_rows_visible)
        index_column_visible = op == "add_index_column"
        self.index_start_label.setVisible(index_column_visible)
        self.index_start_edit.setVisible(index_column_visible)
        self.index_increment_label.setVisible(index_column_visible)
        self.index_increment_edit.setVisible(index_column_visible)
        value_visible = op in {
            "rename_column", "filter_rows", "filter_rows_advanced", "replace_value", "add_custom_column", "add_index_column",
            "conditional_column", "merge_columns", "duplicate_column",
            "remove_top_rows", "remove_bottom_rows", "keep_top_rows", "keep_bottom_rows",
            "keep_range_rows", "extract_text_by_delimiter", "extract_text_between_delimiters",
        }
        self.value_edit.setVisible(value_visible)
        self.value_label.setVisible(value_visible)
        name_entry = op in {
            "rename_column", "add_custom_column", "add_index_column", "conditional_column", "merge_columns",
            "duplicate_column",
        }
        self.value_label.setText("New column name" if name_entry else "Value to match")
        self.value_edit.setPlaceholderText("New column name" if name_entry else "Value to match")
        if op == "filter_rows_advanced":
            self.value_label.setText("Clause value")
            self.value_edit.setPlaceholderText("Value to match")
        if op in {"extract_text_by_delimiter", "extract_text_between_delimiters"}:
            self.value_label.setText(
                "Start occurrence (zero-based)"
                if op == "extract_text_between_delimiters"
                else "Occurrence (zero-based)"
            )
            self.value_edit.setPlaceholderText("0")
            self.value_edit.setValidator(self._row_count_validator)
            self.value_edit.setText("0")
        elif op == "keep_range_rows":
            self.value_label.setText("Number of rows")
            self.value_edit.setPlaceholderText("1")
            self.value_edit.setValidator(self._row_count_validator)
            self.value_edit.setText("1")
            self.range_first_row_edit.setValidator(self._first_row_validator)
            self.range_first_row_edit.setPlaceholderText("1")
            self.range_first_row_edit.setText("1")
        elif op == "remove_alternate_rows":
            self.value_edit.setVisible(False)
            self.value_label.setVisible(False)
            self.alternate_first_row_edit.setValidator(self._first_row_validator)
            self.alternate_first_row_edit.setPlaceholderText("2")
            self.alternate_first_row_edit.setText("2")
            self.alternate_remove_count_edit.setValidator(self._row_count_validator)
            self.alternate_remove_count_edit.setPlaceholderText("1")
            self.alternate_remove_count_edit.setText("1")
            self.alternate_keep_count_edit.setValidator(self._row_count_validator)
            self.alternate_keep_count_edit.setPlaceholderText("1")
            self.alternate_keep_count_edit.setText("1")
        elif op == "add_index_column":
            self.value_label.setText("New column name")
            self.value_edit.setPlaceholderText("Index")
            self.value_edit.setText("Index")
            self.index_start_edit.setValidator(self._index_value_validator)
            self.index_start_edit.setPlaceholderText("0")
            self.index_start_edit.setText("0")
            self.index_increment_edit.setValidator(self._index_value_validator)
            self.index_increment_edit.setPlaceholderText("1")
            self.index_increment_edit.setText("1")
        elif op in {"remove_top_rows", "remove_bottom_rows", "keep_top_rows", "keep_bottom_rows"}:
            self.value_label.setText("Number of rows")
            self.value_edit.setPlaceholderText("0")
            self.value_edit.setValidator(self._row_count_validator)
            self.value_edit.setText("1")
        else:
            self.value_edit.setValidator(None)
            self.range_first_row_edit.setValidator(None)
            self.alternate_first_row_edit.setValidator(None)
            self.alternate_remove_count_edit.setValidator(None)
            self.alternate_keep_count_edit.setValidator(None)
            self.index_start_edit.setValidator(None)
            self.index_increment_edit.setValidator(None)
        replacement_visible = op == "replace_value"
        self.replacement_edit.setVisible(replacement_visible)
        self.replacement_label.setVisible(replacement_visible)
        delimiter_visible = op in {
            "extract_text_by_delimiter", "extract_text_between_delimiters", "split_column", "split_column_by_each_delimiter", "split_column_to_rows",
            "split_column_by_positions", "merge_columns"
        }
        self.delimiter_edit.setVisible(delimiter_visible)
        self.delimiter_label.setVisible(delimiter_visible)
        between_delimiters = op == "extract_text_between_delimiters"
        self.end_delimiter_edit.setVisible(between_delimiters)
        self.end_delimiter_label.setVisible(between_delimiters)
        self.end_occurrence_edit.setVisible(between_delimiters)
        self.end_occurrence_label.setVisible(between_delimiters)
        if between_delimiters:
            self.delimiter_label.setText("Start delimiter")
            self.delimiter_edit.setPlaceholderText("Start delimiter")
            self.end_delimiter_label.setText("End delimiter")
            self.end_delimiter_edit.setPlaceholderText("End delimiter")
            self.end_occurrence_label.setText("End occurrence (zero-based)")
            self.end_occurrence_edit.setPlaceholderText("0")
            self.end_occurrence_edit.setText("0")
            self.end_occurrence_edit.setValidator(self._row_count_validator)
        if op == "extract_text_between_delimiters":
            self.delimiter_edit.setToolTip("The opening delimiter to search for.")
            self.end_delimiter_edit.setToolTip(
                "The closing delimiter to find after the selected opening delimiter."
            )
        elif op == "extract_text_by_delimiter":
            self.delimiter_label.setText("Delimiter")
            self.delimiter_edit.setPlaceholderText("Delimiter text")
            self.delimiter_edit.setToolTip(
                "Extracts text before or after the selected zero-based delimiter occurrence. "
                "A missing occurrence reports the row and column."
            )
        elif op == "split_column":
            self.delimiter_label.setText("Delimiter (first match)")
            self.delimiter_edit.setToolTip(
                "Text after the first match stays in the second output; missing matches leave it blank."
            )
        elif op == "split_column_by_each_delimiter":
            self.delimiter_label.setText("Delimiter (each match, columns)")
            self.delimiter_edit.setPlaceholderText("Delimiter text")
            self.delimiter_edit.setText("")
            self.delimiter_edit.setToolTip(
                "Each match starts another output column. Rows with fewer parts receive blank values."
            )
        elif op == "split_column_to_rows":
            self.delimiter_label.setText("Delimiter (each match)")
            self.delimiter_edit.setToolTip(
                "Each delimited item becomes a row; the other column values repeat."
            )
        elif op == "split_column_by_positions":
            self.delimiter_label.setText("Split starts (zero-based positions)")
            self.delimiter_edit.setPlaceholderText("0, 6, 14")
            self.delimiter_edit.setText("0, 6")
            self.delimiter_edit.setToolTip(
                "Enter increasing character positions starting with 0. Each position starts an output segment."
            )
        elif op == "merge_columns":
            self.delimiter_label.setText("Separator")
            self.delimiter_edit.setPlaceholderText("Space, comma, or custom text")
            self.delimiter_edit.setText(" ")
            self.delimiter_edit.setToolTip(
                "The separator is inserted between selected values. Blank values remain in their positions."
            )
        reorder_columns = op == "reorder_columns"
        self.keep_columns_list.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
            if reorder_columns
            else QAbstractItemView.DragDropMode.NoDragDrop
        )
        self.keep_columns_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.keep_columns_list.setMaximumHeight(220 if reorder_columns else 90)
        self.keep_columns_list.clear()
        for header in base_candidate.headers:
            item = QListWidgetItem(header)
            if reorder_columns:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if op in {"remove_duplicates", "keep_duplicates"}
                    else Qt.CheckState.Unchecked
                )
            self.keep_columns_list.addItem(item)
        unpivot_visible = op in {"unpivot_columns", "unpivot_other_columns"}
        self.attribute_name_label.setVisible(unpivot_visible)
        self.attribute_name_edit.setVisible(unpivot_visible)
        self.value_column_name_label.setVisible(unpivot_visible)
        self.value_column_name_edit.setVisible(unpivot_visible)
        if unpivot_visible:
            self.attribute_name_edit.setText("Attribute")
            self.value_column_name_edit.setText("Value")
        keep_columns_visible = op in {
            "keep_columns",
            "remove_duplicates",
            "keep_duplicates",
            "merge_columns",
            "fill_down",
            "fill_up",
            "group_by",
            "unpivot_columns",
            "unpivot_other_columns",
            "reorder_columns",
        }
        self.keep_columns_list.setVisible(keep_columns_visible)
        self.keep_columns_label.setVisible(keep_columns_visible)
        selection_labels = {
            "remove_duplicates": "Columns that define duplicates",
            "keep_duplicates": "Columns to check for duplicates",
            "merge_columns": "Columns to merge",
            "fill_down": "Columns to fill down",
            "fill_up": "Columns to fill up",
            "group_by": "Columns to group by",
            "unpivot_columns": "Columns to unpivot",
            "unpivot_other_columns": "Columns to keep",
            "keep_columns": "Columns to keep",
            "reorder_columns": "Column order",
        }
        self.keep_columns_label.setText(selection_labels.get(op, "Columns to keep"))
        selection_tooltips = {
            "remove_duplicates": (
                "Rows with identical exact, case-sensitive values in the selected columns are reduced to one; "
                "the first row is retained. All columns are selected by default."
            ),
            "keep_duplicates": (
                "Keeps every row when its exact, case-sensitive selected key values occur more than once. "
                "All columns are selected by default; output row order is preserved."
            ),
            "merge_columns": (
                "Selected columns are combined in displayed order, then replaced by the new text column."
            ),
            "fill_down": "Blank cells receive the preceding non-empty value; leading blanks remain blank.",
            "fill_up": "Blank cells receive the following non-empty value; trailing blanks remain blank.",
            "group_by": "Rows are grouped by the exact values in the selected columns.",
            "unpivot_columns": (
                "Each non-empty selected cell becomes an attribute/value row; other columns stay fixed."
            ),
            "unpivot_other_columns": (
                "Selected columns stay fixed; each non-empty cell in every other column is unpivoted."
            ),
            "keep_columns": "Selected columns remain in their current source order.",
            "reorder_columns": (
                "Drag columns to set their order. Unspecified columns keep their positions."
            ),
        }
        self.keep_columns_list.setToolTip(selection_tooltips.get(op, ""))
        self.group_aggregation_label.setVisible(op == "group_by")
        self.group_aggregation_widget.setVisible(op == "group_by")
        if op == "group_by":
            selected_is_group_step = (
                0 <= selected_index < len(self._steps)
                and self._steps[selected_index]["op"] == "group_by"
            )
            self._group_aggregations = (
                deepcopy(self._steps[selected_index]["aggregations"])
                if selected_is_group_step
                else []
            )
            self.group_aggregate_column_combo.clear()
            self.group_aggregate_column_combo.addItems(base_candidate.headers)
            self._render_group_aggregations()
        column_visible = op not in {
            "count_rows",
            "remove_duplicates",
            "keep_duplicates",
            "remove_blank_rows",
            "remove_rows_with_errors",
            "remove_sparse_top_rows",
            "remove_sparse_bottom_rows",
            "remove_top_rows",
            "remove_bottom_rows",
            "keep_top_rows",
            "keep_bottom_rows",
            "keep_range_rows",
            "remove_alternate_rows",
            "add_index_column",
            "keep_columns",
            "reorder_columns",
            "promote_headers",
            "demote_headers",
            "transpose_table",
            "merge_columns",
            "fill_down",
            "fill_up",
            "group_by",
            "unpivot_columns",
            "unpivot_other_columns",
            "add_custom_column",
            "conditional_column",
            "sort_rows_by_columns",
        }
        self.column_combo.setVisible(column_visible)
        self.column_label.setVisible(column_visible)
        self.column_label.setText(
            "Column to pivot"
            if pivot_visible
            else "Filter column"
            if op == "filter_rows_advanced"
            else "Column"
        )
        if op in {"filter_rows", "filter_rows_advanced"}:
            self.option_combo.addItem("Equals", "equals")
            self.option_combo.addItem("Does not equal", "not_equals")
            self.option_combo.addItem("Is null", "is_null")
            self.option_combo.addItem("Is not null", "is_not_null")
            self.option_combo.addItem("Is blank", "is_blank")
            self.option_combo.addItem("Is not blank", "is_not_blank")
            self.option_combo.addItem("Contains", "contains")
            self.option_combo.addItem("Does not contain", "does_not_contain")
            self.option_combo.addItem("Begins with", "begins_with")
            self.option_combo.addItem("Does not begin with", "does_not_begin_with")
            self.option_combo.addItem("Ends with", "ends_with")
            self.option_combo.addItem("Does not end with", "does_not_end_with")
            self.option_combo.addItem("Greater than", "greater_than")
            self.option_combo.addItem("Greater than or equal", "greater_than_or_equal")
            self.option_combo.addItem("Less than", "less_than")
            self.option_combo.addItem("Less than or equal", "less_than_or_equal")
            self.option_combo.setToolTip(
                "Text filters compare exact, case-sensitive values. Empty text criteria follow normal substring, prefix, or suffix matching. "
                "Numeric greater/less-than filters use finite invariant numbers and exclude blank cells. "
                "Null checks match only null; blank checks match null or empty text. Whitespace-only values are not blank."
            )
        elif op == "sort_rows":
            self.option_combo.addItem("Ascending", "asc")
            self.option_combo.addItem("Descending", "desc")
        elif op == "extract_text_by_delimiter":
            self.option_combo.addItem("Before delimiter", "before")
            self.option_combo.addItem("After delimiter", "after")
        elif op == "convert_type":
            self.option_combo.addItem("Text", "text")
            self.option_combo.addItem("Whole number", "whole_number")
            self.option_combo.addItem("Decimal number", "decimal_number")
            self.option_combo.addItem("Boolean", "boolean")
            self.option_combo.addItem("Date (YYYY-MM-DD)", "date")
            self.option_combo.addItem("Date/time (ISO 8601)", "datetime")
            self.option_combo.addItem("Time (ISO 8601)", "time")
        elif op == "convert_type_using_locale":
            self.option_combo.addItem("Whole number", "whole_number")
            self.option_combo.addItem("Decimal number", "decimal_number")
            self.option_combo.addItem("Date", "date")
            self.option_combo.addItem("Date/time", "datetime")
            self.option_combo.addItem("Time", "time")
            self.option_combo.setToolTip(
                "Parses numbers and dates with a Babel/CLDR culture. Date parsing uses "
                "the Gregorian calendar; localized dates use numeric Babel/CLDR patterns; localized date-times require a date followed by a colon-form clock time; CLDR AM/PM markers are accepted."
            )
        elif op == "pivot_column":
            self.option_combo.addItem("Don't aggregate", "none")
            self.option_combo.addItem("Count (all)", "count_all")
            self.option_combo.addItem("Count (not blank)", "count_non_blank")
            self.option_combo.addItem("Minimum", "min")
            self.option_combo.addItem("Maximum", "max")
            self.option_combo.addItem("Median", "median")
            self.option_combo.addItem("Sum", "sum")
            self.option_combo.addItem("Average", "average")
            self.option_combo.setToolTip(
                "Default is Don't aggregate. Repeated row-key and pivot-value pairs then show an error; choose an aggregation to combine them."
            )
            self._update_pivot_value_choices()
        self.column_combo.setEnabled(self.column_combo.count() > 0)
        if op == "extract_text_between_delimiters":
            column_tooltip = (
                "Extracts text between two exact delimiters from a Text-typed column."
            )
        elif op == "extract_text_by_delimiter":
            column_tooltip = (
                "Extracts before or after a selected delimiter occurrence from a Text-typed column."
            )
        elif op == "split_column":
            column_tooltip = (
                "Replaces the selected column with <column>.1 and <column>.2."
            )
        elif op == "split_column_by_each_delimiter":
            column_tooltip = (
                "Replaces the selected column with numbered text columns, one per delimited part."
            )
        elif op == "split_column_to_rows":
            column_tooltip = (
                "Creates one row for each delimited item and repeats the other column values."
            )
        elif op == "pivot_column":
            column_tooltip = "Distinct values in this column become output column names."
        elif op == "clean_text":
            column_tooltip = (
                "Removes control characters throughout the value. The current column type must be Text."
            )
        elif op == "lowercase_text":
            column_tooltip = (
                "Converts values with locale-neutral Unicode lowercase rules. The current column type must be Text."
            )
        elif op == "uppercase_text":
            column_tooltip = (
                "Converts values with locale-neutral Unicode uppercase rules. The current column type must be Text."
            )
        elif op == "proper_case_text":
            column_tooltip = (
                "Capitalizes each word with locale-neutral Unicode title casing. The current column type must be Text."
            )
        elif op == "reverse_text":
            column_tooltip = (
                "Reverses the Unicode code points in each value. The current column type must be Text."
            )
        elif op == "duplicate_column":
            column_tooltip = "Appends a copy of this column, including its saved type."
        else:
            column_tooltip = ""
        self.column_combo.setToolTip(column_tooltip)
        self._configure_conditional_fields()
        self._configure_group_aggregate_fields()
        multi_sort_visible = op == "sort_rows_by_columns"
        self.sort_priority_label.setVisible(multi_sort_visible)
        self.sort_criteria_widget.setVisible(multi_sort_visible)
        if multi_sort_visible:
            selected_sort_step = (
                self._steps[selected_index]
                if 0 <= selected_index < len(self._steps)
                and self._steps[selected_index]["op"] == "sort_rows_by_columns"
                else None
            )
            sort_levels = (
                deepcopy(selected_sort_step["sorts"])
                if selected_sort_step is not None
                else ([{"column": base_candidate.headers[0], "direction": "asc"}]
                      if base_candidate.headers else [])
            )
            self._set_sort_levels(base_candidate.headers, sort_levels)
        else:
            self._set_sort_levels(base_candidate.headers, [])
        self._update_filter_value_visibility()
        self._update_advanced_filter_clause_controls()

    def _set_sort_levels(
        self,
        headers: list[str],
        sorts: list[dict[str, str]],
    ) -> None:
        table = self.sort_criteria_table
        table.setRowCount(0)
        for sort in sorts:
            row = table.rowCount()
            table.insertRow(row)
            column_combo = QComboBox(table)
            column_combo.addItems(headers)
            if sort["column"] not in headers:
                column_combo.addItem(sort["column"])
            column_combo.setCurrentText(sort["column"])
            column_combo.setObjectName(f"sortColumnCombo{row}")
            direction_combo = QComboBox(table)
            direction_combo.addItem("Ascending", "asc")
            direction_combo.addItem("Descending", "desc")
            direction_combo.setCurrentIndex(
                max(0, direction_combo.findData(sort["direction"]))
            )
            direction_combo.setObjectName(f"sortDirectionCombo{row}")
            table.setCellWidget(row, 0, column_combo)
            table.setCellWidget(row, 1, direction_combo)
            table.setRowHeight(row, 30)
        table.setColumnWidth(0, 180)
        if table.rowCount():
            table.setCurrentCell(0, 0)
        self._update_sort_level_controls()

    def _read_sort_levels(self) -> list[dict[str, str]]:
        sorts = []
        for row in range(self.sort_criteria_table.rowCount()):
            column_combo = self.sort_criteria_table.cellWidget(row, 0)
            direction_combo = self.sort_criteria_table.cellWidget(row, 1)
            if not isinstance(column_combo, QComboBox) or not isinstance(
                direction_combo, QComboBox
            ):
                continue
            sorts.append({
                "column": column_combo.currentText(),
                "direction": str(direction_combo.currentData()),
            })
        return sorts

    def _add_sort_level(self) -> None:
        sorts = self._read_sort_levels()
        headers = [
            self.column_combo.itemText(index)
            for index in range(self.column_combo.count())
        ]
        used = {sort["column"] for sort in sorts}
        next_column = next((header for header in headers if header not in used), None)
        if next_column is None:
            self._show_error("Each column can appear only once in the sort priority list.")
            return
        sorts.append({"column": next_column, "direction": "asc"})
        self._set_sort_levels(headers, sorts)
        self.sort_criteria_table.setCurrentCell(len(sorts) - 1, 0)
        self._clear_error()

    def _remove_sort_level(self) -> None:
        sorts = self._read_sort_levels()
        row = self.sort_criteria_table.currentRow()
        if len(sorts) <= 1 or row < 0:
            return
        sorts.pop(row)
        headers = [
            self.column_combo.itemText(index)
            for index in range(self.column_combo.count())
        ]
        self._set_sort_levels(headers, sorts)
        self.sort_criteria_table.setCurrentCell(min(row, len(sorts) - 1), 0)

    def _move_sort_level(self, offset: int) -> None:
        sorts = self._read_sort_levels()
        row = self.sort_criteria_table.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < len(sorts):
            return
        sorts[row], sorts[target] = sorts[target], sorts[row]
        headers = [
            self.column_combo.itemText(index)
            for index in range(self.column_combo.count())
        ]
        self._set_sort_levels(headers, sorts)
        self.sort_criteria_table.setCurrentCell(target, 0)

    def _update_sort_level_controls(self) -> None:
        row = self.sort_criteria_table.currentRow()
        count = self.sort_criteria_table.rowCount()
        self.sort_add_button.setEnabled(count < self.column_combo.count())
        self.sort_remove_button.setEnabled(count > 1 and row >= 0)
        self.sort_up_button.setEnabled(row > 0)
        self.sort_down_button.setEnabled(0 <= row < count - 1)

    def _update_pivot_value_choices(self, *_args: Any) -> None:
        if str(self.operation_combo.currentData()) != "pivot_column":
            return
        attribute_column = self.column_combo.currentText()
        selected_value = self.pivot_value_column_combo.currentText()
        headers = [
            self.column_combo.itemText(index)
            for index in range(self.column_combo.count())
            if self.column_combo.itemText(index) != attribute_column
        ]
        self.pivot_value_column_combo.clear()
        self.pivot_value_column_combo.addItems(headers)
        selected_index = self.pivot_value_column_combo.findText(selected_value)
        if selected_index < 0 and headers:
            selected_index = 0
        if selected_index >= 0:
            self.pivot_value_column_combo.setCurrentIndex(selected_index)
        self.pivot_value_column_combo.setEnabled(bool(headers))

    def _update_filter_value_visibility(self, *_args: Any) -> None:
        is_filter = str(self.operation_combo.currentData()) in {
            "filter_rows", "filter_rows_advanced"
        }
        needs_value = (
            is_filter
            and self.option_combo.currentData() not in FILTER_OPERATORS_WITHOUT_VALUE
        )
        has_parameters = self.filter_parameter_combo.count() > 1
        using_parameter = bool(self.filter_parameter_combo.currentData())
        show_parameter = needs_value and has_parameters
        show_literal = needs_value and not (show_parameter and using_parameter)
        self.filter_parameter_label.setVisible(show_parameter)
        self.filter_parameter_combo.setVisible(show_parameter)
        if not is_filter:
            # _configure_editor already decided whether this command shows a value
            # field (Replace Values, Keep Top Rows, names...); do not hide it again.
            return
        self.value_edit.setVisible(show_literal)
        self.value_label.setVisible(show_literal)

    def _select_step(self, index: int) -> None:
        if index < 0 or index >= len(self._steps):
            self._configure_editor()
            self._update_step_controls()
            self._refresh_formula_bar()
            self._refresh_preview()
            return
        step = self._steps[index]
        operation_index = self.operation_combo.findData(step["op"])
        previous_block_state = self.operation_combo.blockSignals(True)
        self.operation_combo.setCurrentIndex(operation_index)
        self.operation_combo.blockSignals(previous_block_state)
        self._group_aggregations = (
            deepcopy(step["aggregations"]) if step["op"] == "group_by" else []
        )
        self._configure_editor()
        if "column" in step:
            column_index = self.column_combo.findText(step["column"])
            if column_index >= 0:
                self.column_combo.setCurrentIndex(column_index)
        if "operator" in step:
            option_index = self.option_combo.findData(step["operator"])
            if option_index >= 0:
                self.option_combo.setCurrentIndex(option_index)
            self._set_combo_data(
                self.filter_parameter_combo, step.get("parameter", "")
            )
            self.value_edit.setText(step.get("value", ""))
        elif "side" in step:
            option_index = self.option_combo.findData(step["side"])
            if option_index >= 0:
                self.option_combo.setCurrentIndex(option_index)
        elif "direction" in step:
            option_index = self.option_combo.findData(step["direction"])
            if option_index >= 0:
                self.option_combo.setCurrentIndex(option_index)
        elif "type" in step:
            type_name = "decimal_number" if step["type"] == "number" else step["type"]
            option_index = self.option_combo.findData(type_name)
            if option_index >= 0:
                self.option_combo.setCurrentIndex(option_index)
        if "culture" in step:
            self.culture_edit.setText(step["culture"])
        elif "aggregation" in step:
            option_index = self.option_combo.findData(step["aggregation"])
            if option_index >= 0:
                self.option_combo.setCurrentIndex(option_index)
        if "count" in step:
            self.value_edit.setText(str(step["count"]))
        if "occurrence" in step:
            self.value_edit.setText(str(step["occurrence"]))
        if "start_occurrence" in step:
            self.value_edit.setText(str(step["start_occurrence"]))
        if "end_occurrence" in step:
            self.end_occurrence_edit.setText(str(step["end_occurrence"]))
        if "first_row" in step:
            self.range_first_row_edit.setText(str(step["first_row"]))
        if step["op"] == "remove_alternate_rows":
            self.alternate_first_row_edit.setText(str(step["first_row_to_remove"]))
            self.alternate_remove_count_edit.setText(str(step["remove_count"]))
            self.alternate_keep_count_edit.setText(str(step["keep_count"]))
        if step["op"] == "add_index_column":
            self.index_start_edit.setText(str(step["start"]))
            self.index_increment_edit.setText(str(step["increment"]))
        if "attribute_column" in step:
            attribute_index = self.column_combo.findText(step["attribute_column"])
            if attribute_index >= 0:
                self.column_combo.setCurrentIndex(attribute_index)
        if "value_column" in step:
            value_index = self.pivot_value_column_combo.findText(step["value_column"])
            if value_index >= 0:
                self.pivot_value_column_combo.setCurrentIndex(value_index)
        if "new_name" in step:
            self.value_edit.setText(step["new_name"])
        if "name" in step:
            self.value_edit.setText(step["name"])
        if "expression" in step:
            self.custom_expression_edit.setPlainText(step["expression"])
        if step["op"] == "add_custom_column":
            self._set_combo_data(
                self.custom_output_type_combo,
                step.get("output_type", "text"),
            )
        if step["op"] == "conditional_column":
            self._conditional_clauses = deepcopy(step["clauses"])
            self._set_combo_data(self.conditional_else_kind_combo, step["else_kind"])
            if step["else_kind"] == "column":
                self._set_combo_text(self.conditional_else_column_combo, step["else_value"])
            else:
                self.conditional_else_edit.setText(step["else_value"])
            self._render_conditional_clauses()
        elif step["op"] == "filter_rows_advanced":
            self._filter_clauses = deepcopy(step["clauses"])
            self._render_advanced_filter_clauses(select_row=0)
        if "replacement" in step:
            self.value_edit.setText(step["value"])
            self.replacement_edit.setText(step["replacement"])
        if "delimiter" in step:
            self.delimiter_edit.setText(step["delimiter"])
        if "start_delimiter" in step:
            self.delimiter_edit.setText(step["start_delimiter"])
        if "end_delimiter" in step:
            self.end_delimiter_edit.setText(step["end_delimiter"])
        if "positions" in step:
            self.delimiter_edit.setText(", ".join(str(position) for position in step["positions"]))
        if "separator" in step:
            self.delimiter_edit.setText(step["separator"])
        if "attribute_name" in step:
            self.attribute_name_edit.setText(step["attribute_name"])
        if "value_name" in step:
            self.value_column_name_edit.setText(step["value_name"])
        if step["op"] == "reorder_columns":
            items_by_name = {}
            while self.keep_columns_list.count():
                item = self.keep_columns_list.takeItem(0)
                items_by_name[item.text()] = item
            current_order = list(items_by_name)
            requested = [
                column for column in step["columns"] if column in items_by_name
            ]
            selected = set(requested)
            slots = [
                item_index for item_index, name in enumerate(current_order)
                if name in selected
            ]
            for item_index, column_name in zip(slots, requested):
                current_order[item_index] = column_name
            self.keep_columns_list.clear()
            for column_name in current_order:
                item = items_by_name.get(column_name)
                if item is not None:
                    self.keep_columns_list.addItem(item)
        elif "columns" in step:
            selected_columns = set(step["columns"])
            for item_index in range(self.keep_columns_list.count()):
                item = self.keep_columns_list.item(item_index)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if item.text() in selected_columns
                    else Qt.CheckState.Unchecked
                )
        self._render_group_aggregations()
        self._clear_error()
        self._update_step_controls()
        self._refresh_formula_bar()
        self._refresh_preview()

    def _add_or_start_new_step(self) -> None:
        if self.step_list.currentRow() >= 0:
            self.step_list.setCurrentRow(-1)
            self.operation_combo.setCurrentIndex(0)
            self._configure_editor()
            self._clear_error()
            return
        if self.operation_combo.currentData() == "add_custom_column":
            accepted = self._launch_custom_column_dialog(
                initial_name=self.value_edit.text(),
                initial_expression=self.custom_expression_edit.toPlainText(),
            )
            if not accepted:
                self._restore_non_custom_operation()
            return
        self._add_step()

    def _create_step(self) -> dict[str, Any]:
        op = str(self.operation_combo.currentData())
        column = self.column_combo.currentText()
        if op in {
            "count_rows", "promote_headers", "demote_headers", "transpose_table",
            "remove_sparse_top_rows", "remove_sparse_bottom_rows",
        }:
            return {"op": op}
        if op == "rename_column":
            return {"op": op, "column": column, "new_name": self.value_edit.text().strip()}
        if op == "remove_column":
            return {"op": op, "column": column}
        if op == "filter_rows":
            operator = str(self.option_combo.currentData())
            step = {"op": op, "column": column, "operator": operator}
            if operator not in FILTER_OPERATORS_WITHOUT_VALUE:
                parameter = str(self.filter_parameter_combo.currentData() or "")
                if parameter:
                    step["parameter"] = parameter
                else:
                    step["value"] = self.value_edit.text()
            else:
                step["value"] = ""
            return step
        if op == "filter_rows_advanced":
            return {"op": op, "clauses": deepcopy(self._filter_clauses)}
        if op == "sort_rows":
            return {"op": op, "column": column, "direction": str(self.option_combo.currentData())}
        if op == "sort_rows_by_columns":
            return {"op": op, "sorts": self._read_sort_levels()}
        if op == "replace_value":
            return {
                "op": op,
                "column": column,
                "value": self.value_edit.text(),
                "replacement": self.replacement_edit.text(),
            }
        if op == "extract_text_by_delimiter":
            try:
                occurrence = int(self.value_edit.text().strip())
            except ValueError as exc:
                raise TransformationError(
                    "Enter a zero-based delimiter occurrence from 0 to 100,000."
                ) from exc
            return {
                "op": op,
                "column": column,
                "side": str(self.option_combo.currentData()),
                "delimiter": self.delimiter_edit.text(),
                "occurrence": occurrence,
            }
        if op == "extract_text_between_delimiters":
            try:
                start_occurrence = int(self.value_edit.text().strip())
                end_occurrence = int(self.end_occurrence_edit.text().strip())
            except ValueError as exc:
                raise TransformationError(
                    "Enter zero-based start and end occurrences from 0 to 100,000."
                ) from exc
            return {
                "op": op,
                "column": column,
                "start_delimiter": self.delimiter_edit.text(),
                "end_delimiter": self.end_delimiter_edit.text(),
                "start_occurrence": start_occurrence,
                "end_occurrence": end_occurrence,
            }
        if op in {"split_column", "split_column_by_each_delimiter", "split_column_to_rows"}:
            return {
                "op": op,
                "column": column,
                "delimiter": self.delimiter_edit.text(),
            }
        if op == "split_column_by_positions":
            raw_positions = [part.strip() for part in self.delimiter_edit.text().split(",")]
            if any(not part or not part.isascii() or not part.isdecimal() for part in raw_positions):
                raise TransformationError(
                    "Enter comma-separated zero-based positions starting with 0, such as 0, 6, 14."
                )
            try:
                positions = [int(part) for part in raw_positions]
            except ValueError as exc:
                raise TransformationError(
                    "Enter comma-separated whole-number split positions."
                ) from exc
            return {"op": op, "column": column, "positions": positions}
        if op == "merge_columns":
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
                if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
            ]
            return {
                "op": op,
                "columns": columns,
                "separator": self.delimiter_edit.text(),
                "new_name": self.value_edit.text().strip(),
            }
        if op == "duplicate_column":
            return {
                "op": op,
                "column": column,
                "new_name": self.value_edit.text().strip(),
            }
        if op == "add_index_column":
            try:
                start = int(self.index_start_edit.text().strip())
                increment = int(self.index_increment_edit.text().strip())
            except ValueError as exc:
                raise TransformationError(
                    "Enter whole numbers for the starting index and increment."
                ) from exc
            return {
                "op": op,
                "new_name": self.value_edit.text().strip(),
                "start": start,
                "increment": increment,
            }
        if op in {"fill_down", "fill_up"}:
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
                if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
            ]
            return {"op": op, "columns": columns}
        if op in {"trim_text", "clean_text", "lowercase_text", "uppercase_text", "proper_case_text", "reverse_text"}:
            return {"op": op, "column": column}
        if op in {"remove_duplicates", "keep_duplicates"}:
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
                if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
            ]
            return {"op": op, "columns": columns}
        if op in {"remove_blank_rows", "remove_rows_with_errors"}:
            return {"op": op}
        if op == "keep_range_rows":
            try:
                first_row = int(self.range_first_row_edit.text().strip())
                count = int(self.value_edit.text().strip())
            except ValueError as exc:
                raise TransformationError(
                    f"Enter a first row from 1 to {MAX_DATA_ROWS:,} and a row count from 0 to {MAX_DATA_ROWS:,}."
                ) from exc
            return {"op": op, "first_row": first_row, "count": count}
        if op == "remove_alternate_rows":
            try:
                first_row_to_remove = int(self.alternate_first_row_edit.text().strip())
                remove_count = int(self.alternate_remove_count_edit.text().strip())
                keep_count = int(self.alternate_keep_count_edit.text().strip())
            except ValueError as exc:
                raise TransformationError(
                    "Enter a first row to remove and whole-number remove/keep counts."
                ) from exc
            return {
                "op": op,
                "first_row_to_remove": first_row_to_remove,
                "remove_count": remove_count,
                "keep_count": keep_count,
            }
        if op in {"remove_top_rows", "remove_bottom_rows", "keep_top_rows", "keep_bottom_rows"}:
            raw_count = self.value_edit.text().strip()
            try:
                count = int(raw_count)
            except ValueError as exc:
                raise TransformationError(
                    f"Enter a whole number from 0 to {MAX_DATA_ROWS:,}."
                ) from exc
            return {"op": op, "count": count}
        if op == "keep_columns":
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
                if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
            ]
            return {"op": op, "columns": columns}
        if op == "reorder_columns":
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
            ]
            return {"op": op, "columns": columns}
        if op == "group_by":
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
                if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
            ]
            return {
                "op": op,
                "columns": columns,
                "aggregations": deepcopy(self._group_aggregations),
            }
        if op in {"unpivot_columns", "unpivot_other_columns"}:
            columns = [
                self.keep_columns_list.item(index).text()
                for index in range(self.keep_columns_list.count())
                if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
            ]
            return {
                "op": op,
                "columns": columns,
                "attribute_name": self.attribute_name_edit.text().strip(),
                "value_name": self.value_column_name_edit.text().strip(),
            }
        if op == "pivot_column":
            return {
                "op": op,
                "attribute_column": self.column_combo.currentText(),
                "value_column": self.pivot_value_column_combo.currentText(),
                "aggregation": str(self.option_combo.currentData()),
            }
        if op == "add_custom_column":
            step = {
                "op": op,
                "name": self.value_edit.text().strip(),
                "expression": self.custom_expression_edit.toPlainText().strip(),
            }
            output_type = str(self.custom_output_type_combo.currentData() or "text")
            if output_type != "text":
                step["output_type"] = output_type
            return step
        if op == "conditional_column":
            return {
                "op": op,
                "name": self.value_edit.text().strip(),
                "clauses": deepcopy(self._conditional_clauses),
                "else_value": (
                    self.conditional_else_column_combo.currentText()
                    if self.conditional_else_kind_combo.currentData() == "column"
                    else self.conditional_else_edit.text()
                ),
                "else_kind": str(self.conditional_else_kind_combo.currentData()),
            }
        if op == "convert_type_using_locale":
            return {
                "op": op,
                "column": column,
                "type": str(self.option_combo.currentData()),
                "culture": self.culture_edit.text(),
            }
        return {"op": op, "column": column, "type": str(self.option_combo.currentData())}

    def _configure_conditional_fields(self, *_args: Any) -> None:
        test_uses_column = self.conditional_test_value_kind_combo.currentData() == "column"
        output_uses_column = self.conditional_output_kind_combo.currentData() == "column"
        else_uses_column = self.conditional_else_kind_combo.currentData() == "column"
        self.conditional_test_value_edit.setVisible(not test_uses_column)
        self.conditional_test_value_column_combo.setVisible(test_uses_column)
        self.conditional_output_edit.setVisible(not output_uses_column)
        self.conditional_output_column_combo.setVisible(output_uses_column)
        self.conditional_else_edit.setVisible(not else_uses_column)
        self.conditional_else_column_combo.setVisible(else_uses_column)
        self._update_conditional_clause_controls()

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _set_combo_text(combo: QComboBox, value: str) -> None:
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _current_conditional_clause(self) -> dict[str, str]:
        test_value_kind = str(self.conditional_test_value_kind_combo.currentData())
        output_kind = str(self.conditional_output_kind_combo.currentData())
        return {
            "column": self.conditional_test_column_combo.currentText(),
            "operator": str(self.conditional_operator_combo.currentData()),
            "test_value": (
                self.conditional_test_value_column_combo.currentText()
                if test_value_kind == "column"
                else self.conditional_test_value_edit.text()
            ),
            "test_value_kind": test_value_kind,
            "output": (
                self.conditional_output_column_combo.currentText()
                if output_kind == "column"
                else self.conditional_output_edit.text()
            ),
            "output_kind": output_kind,
        }

    def _add_conditional_clause(self) -> None:
        if len(self._conditional_clauses) >= MAX_CONDITIONAL_CLAUSES:
            self._show_error(
                f"A conditional column may contain at most {MAX_CONDITIONAL_CLAUSES} clauses."
            )
            return
        clause = self._current_conditional_clause()
        if not clause["column"]:
            self._show_error("Choose a column for the conditional test.")
            return
        if clause["test_value_kind"] == "column" and not clause["test_value"]:
            self._show_error("Choose a comparison column.")
            return
        if clause["output_kind"] == "column" and not clause["output"]:
            self._show_error("Choose an output column.")
            return
        self._conditional_clauses.append(clause)
        self._render_conditional_clauses(select_row=len(self._conditional_clauses) - 1)
        self._clear_error()

    def _update_conditional_clause(self) -> None:
        index = self.conditional_clause_list.currentRow()
        if not 0 <= index < len(self._conditional_clauses):
            return
        clause = self._current_conditional_clause()
        if not clause["column"]:
            self._show_error("Choose a column for the conditional test.")
            return
        if clause["test_value_kind"] == "column" and not clause["test_value"]:
            self._show_error("Choose a comparison column.")
            return
        if clause["output_kind"] == "column" and not clause["output"]:
            self._show_error("Choose an output column.")
            return
        self._conditional_clauses[index] = clause
        self._render_conditional_clauses(select_row=index)
        self._clear_error()

    def _remove_conditional_clause(self) -> None:
        index = self.conditional_clause_list.currentRow()
        if not 0 <= index < len(self._conditional_clauses):
            return
        self._conditional_clauses.pop(index)
        next_index = min(index, len(self._conditional_clauses) - 1)
        self._render_conditional_clauses(select_row=next_index)
        self._clear_error()

    def _move_conditional_clause(self, direction: int) -> None:
        index = self.conditional_clause_list.currentRow()
        target = index + direction
        if not 0 <= index < len(self._conditional_clauses):
            return
        if not 0 <= target < len(self._conditional_clauses):
            return
        self._conditional_clauses[index], self._conditional_clauses[target] = (
            self._conditional_clauses[target],
            self._conditional_clauses[index],
        )
        self._render_conditional_clauses(select_row=target)
        self._clear_error()

    def _render_conditional_clauses(self, *, select_row: int = -1) -> None:
        previous_block_state = self.conditional_clause_list.blockSignals(True)
        self.conditional_clause_list.clear()
        for clause in self._conditional_clauses:
            operator_index = self.conditional_operator_combo.findData(clause["operator"])
            operator_label = (
                self.conditional_operator_combo.itemText(operator_index)
                if operator_index >= 0
                else clause["operator"].replace("_", " ")
            )
            test_value = (
                f"column {clause['test_value']}"
                if clause["test_value_kind"] == "column"
                else repr(clause["test_value"])
            )
            output = (
                f"column {clause['output']}"
                if clause["output_kind"] == "column"
                else repr(clause["output"])
            )
            self.conditional_clause_list.addItem(
                f"If {clause['column']} {operator_label} {test_value} → {output}"
            )
        if 0 <= select_row < self.conditional_clause_list.count():
            self.conditional_clause_list.setCurrentRow(select_row)
        else:
            self.conditional_clause_list.setCurrentRow(-1)
        self.conditional_clause_list.blockSignals(previous_block_state)
        if 0 <= select_row < len(self._conditional_clauses):
            self._load_conditional_clause(select_row)
        self._update_conditional_clause_controls()

    def _select_conditional_clause(self, index: int) -> None:
        if 0 <= index < len(self._conditional_clauses):
            self._load_conditional_clause(index)
        self._update_conditional_clause_controls()

    def _load_conditional_clause(self, index: int) -> None:
        clause = self._conditional_clauses[index]
        self._set_combo_text(self.conditional_test_column_combo, clause["column"])
        self._set_combo_data(self.conditional_operator_combo, clause["operator"])
        self._set_combo_data(self.conditional_test_value_kind_combo, clause["test_value_kind"])
        if clause["test_value_kind"] == "column":
            self._set_combo_text(self.conditional_test_value_column_combo, clause["test_value"])
            self.conditional_test_value_edit.clear()
        else:
            self.conditional_test_value_edit.setText(clause["test_value"])
        self._set_combo_data(self.conditional_output_kind_combo, clause["output_kind"])
        if clause["output_kind"] == "column":
            self._set_combo_text(self.conditional_output_column_combo, clause["output"])
            self.conditional_output_edit.clear()
        else:
            self.conditional_output_edit.setText(clause["output"])
        self._configure_conditional_fields()

    def _update_conditional_clause_controls(self) -> None:
        index = self.conditional_clause_list.currentRow()
        selected = 0 <= index < len(self._conditional_clauses)
        self.update_conditional_clause_button.setEnabled(selected)
        self.remove_conditional_clause_button.setEnabled(selected)
        self.up_conditional_clause_button.setEnabled(selected and index > 0)
        self.down_conditional_clause_button.setEnabled(
            selected and index < len(self._conditional_clauses) - 1
        )

    def _current_advanced_filter_clause(self, *, index: int | None = None) -> dict[str, str]:
        operator = str(self.option_combo.currentData())
        join = "and" if index == 0 or not self._filter_clauses else str(
            self.advanced_filter_join_combo.currentData()
        )
        clause = {
            "column": self.column_combo.currentText(),
            "operator": operator,
            "join": join,
        }
        if operator in FILTER_OPERATORS_WITHOUT_VALUE:
            clause["value"] = ""
        else:
            parameter = str(self.filter_parameter_combo.currentData() or "")
            if parameter:
                clause["parameter"] = parameter
            else:
                clause["value"] = self.value_edit.text()
        return clause

    def _add_advanced_filter_clause(self) -> None:
        if len(self._filter_clauses) >= MAX_FILTER_CLAUSES:
            self._show_error(
                f"An advanced filter may contain at most {MAX_FILTER_CLAUSES} clauses."
            )
            return
        clause = self._current_advanced_filter_clause()
        if not clause["column"]:
            self._show_error("Choose a column for this filter clause.")
            return
        if not clause["operator"]:
            self._show_error("Choose an operator for this filter clause.")
            return
        if not self._filter_clauses:
            clause["join"] = "and"
        self._filter_clauses.append(clause)
        self._render_advanced_filter_clauses(select_row=len(self._filter_clauses) - 1)
        self._clear_error()

    def _update_advanced_filter_clause(self) -> None:
        index = self.advanced_filter_clause_list.currentRow()
        if not 0 <= index < len(self._filter_clauses):
            return
        clause = self._current_advanced_filter_clause(index=index)
        if not clause["column"]:
            self._show_error("Choose a column for this filter clause.")
            return
        if not clause["operator"]:
            self._show_error("Choose an operator for this filter clause.")
            return
        self._filter_clauses[index] = clause
        self._render_advanced_filter_clauses(select_row=index)
        self._clear_error()

    def _remove_advanced_filter_clause(self) -> None:
        index = self.advanced_filter_clause_list.currentRow()
        if not 0 <= index < len(self._filter_clauses):
            return
        self._filter_clauses.pop(index)
        if self._filter_clauses:
            self._filter_clauses[0]["join"] = "and"
        self._render_advanced_filter_clauses(
            select_row=min(index, len(self._filter_clauses) - 1)
        )
        self._clear_error()

    def _render_advanced_filter_clauses(self, *, select_row: int = -1) -> None:
        previous_block_state = self.advanced_filter_clause_list.blockSignals(True)
        self.advanced_filter_clause_list.clear()
        for index, clause in enumerate(self._filter_clauses):
            operator_index = self.option_combo.findData(clause["operator"])
            operator_label = (
                self.option_combo.itemText(operator_index)
                if operator_index >= 0
                else clause["operator"].replace("_", " ")
            )
            connector = "FIRST" if index == 0 else clause["join"].upper()
            value_text = (
                ""
                if clause["operator"] in FILTER_OPERATORS_WITHOUT_VALUE
                else f" parameter {clause['parameter']}"
                if "parameter" in clause
                else f" {clause['value']!r}"
            )
            self.advanced_filter_clause_list.addItem(
                f"{connector}: {clause['column']} {operator_label}{value_text}"
            )
        if 0 <= select_row < self.advanced_filter_clause_list.count():
            self.advanced_filter_clause_list.setCurrentRow(select_row)
        else:
            self.advanced_filter_clause_list.setCurrentRow(-1)
        self.advanced_filter_clause_list.blockSignals(previous_block_state)
        if 0 <= select_row < len(self._filter_clauses):
            self._load_advanced_filter_clause(select_row)
        self._update_advanced_filter_clause_controls()

    def _select_advanced_filter_clause(self, index: int) -> None:
        if 0 <= index < len(self._filter_clauses):
            self._load_advanced_filter_clause(index)
        self._update_advanced_filter_clause_controls()

    def _load_advanced_filter_clause(self, index: int) -> None:
        clause = self._filter_clauses[index]
        self._set_combo_text(self.column_combo, clause["column"])
        self._set_combo_data(self.option_combo, clause["operator"])
        self._set_combo_data(
            self.filter_parameter_combo, clause.get("parameter", "")
        )
        self.value_edit.setText(clause.get("value", ""))
        self._set_combo_data(
            self.advanced_filter_join_combo,
            "and" if index == 0 else clause["join"],
        )

    def _update_advanced_filter_clause_controls(self) -> None:
        selected = 0 <= self.advanced_filter_clause_list.currentRow() < len(
            self._filter_clauses
        )
        self.add_advanced_filter_clause_button.setEnabled(
            len(self._filter_clauses) < MAX_FILTER_CLAUSES
        )
        self.update_advanced_filter_clause_button.setEnabled(selected)
        self.remove_advanced_filter_clause_button.setEnabled(selected)

    def _configure_group_aggregate_fields(self, *_args: Any) -> None:
        operation = str(self.group_aggregate_operation_combo.currentData())
        needs_column = operation not in {"count_rows", "count_distinct_rows"}
        self.group_aggregate_column_combo.setVisible(needs_column)
        self._update_group_aggregation_controls()

    def _update_group_aggregation_controls(self) -> None:
        self.remove_group_aggregation_button.setEnabled(
            self.group_aggregations_list.currentRow() >= 0
        )

    def _render_group_aggregations(self) -> None:
        self.group_aggregations_list.clear()
        for aggregate in self._group_aggregations:
            operation = self.group_aggregate_operation_combo.findData(
                aggregate["operation"]
            )
            label = (
                self.group_aggregate_operation_combo.itemText(operation)
                if operation >= 0
                else aggregate["operation"].replace("_", " ").title()
            )
            detail = label
            if "column" in aggregate:
                detail += f" of {aggregate['column']}"
            detail += f" → {aggregate['new_name']}"
            self.group_aggregations_list.addItem(QListWidgetItem(detail))
        self._update_group_aggregation_controls()

    def _add_group_aggregation(self) -> None:
        group_columns = [
            self.keep_columns_list.item(index).text()
            for index in range(self.keep_columns_list.count())
            if self.keep_columns_list.item(index).checkState() == Qt.CheckState.Checked
        ]
        if not group_columns:
            self._show_error("Select one or more columns to group by first.")
            return
        operation = str(self.group_aggregate_operation_combo.currentData())
        aggregate: dict[str, str] = {"operation": operation}
        if operation not in {"count_rows", "count_distinct_rows"}:
            column = self.group_aggregate_column_combo.currentText()
            if not column:
                self._show_error("Select a source column for this aggregation.")
                return
            aggregate["column"] = column
        name = self.group_aggregate_name_edit.text().strip()
        if not name:
            label = self.group_aggregate_operation_combo.currentText()
            name = label if "column" not in aggregate else f"{label} of {aggregate['column']}"
        aggregate["new_name"] = name
        next_aggregations = [*self._group_aggregations, aggregate]
        draft_step = {
            "op": "group_by",
            "columns": group_columns,
            "aggregations": next_aggregations,
        }
        selected_index = self.step_list.currentRow()
        next_steps = deepcopy(self._steps)
        try:
            if 0 <= selected_index < len(next_steps):
                next_steps[selected_index] = draft_step
            else:
                next_steps.append(draft_step)
            next_steps = validate_steps(next_steps)
            transformed = apply_transformations(
                self._source_candidate, next_steps,
                parameters=self._parameter_values(),
            )
        except TransformationError as exc:
            self._show_error(str(exc))
            return
        self._group_aggregations = next_aggregations
        if 0 <= selected_index < len(self._steps):
            self._steps = next_steps
            self._preview_candidate = transformed
            self._render_steps()
            self._refresh_preview()
            self.step_list.setCurrentRow(selected_index)
        else:
            self._render_group_aggregations()
        self.group_aggregate_name_edit.clear()
        self._clear_error()

    def _remove_group_aggregation(self) -> None:
        selected_aggregate = self.group_aggregations_list.currentRow()
        if selected_aggregate < 0:
            return
        next_aggregations = deepcopy(self._group_aggregations)
        next_aggregations.pop(selected_aggregate)
        selected_step = self.step_list.currentRow()
        if 0 <= selected_step < len(self._steps):
            next_steps = deepcopy(self._steps)
            next_steps[selected_step]["aggregations"] = next_aggregations
            try:
                transformed = apply_transformations(
                    self._source_candidate, next_steps,
                    parameters=self._parameter_values(),
                )
            except TransformationError as exc:
                self._show_error(str(exc))
                return
            self._steps = next_steps
            self._preview_candidate = transformed
            self._render_steps()
            self._refresh_preview()
            self.step_list.setCurrentRow(selected_step)
        else:
            self._group_aggregations = next_aggregations
            self._render_group_aggregations()
        self._clear_error()

    def _add_step(
        self,
        step: dict[str, Any] | None = None,
        *,
        power_bi_name: bool = False,
    ) -> bool:
        """Add a step built from the form (or the explicit ``step``); True on success.

        It goes at the end, or at the pending insert point of a ribbon command run with a middle
        step selected (the whole new list is validated and replayed; a failure changes nothing).
        """
        at = self._insert_position()
        try:
            new_step = step if step is not None else self._create_step()
            next_steps = validate_steps(
                [*self._steps[:at], new_step, *self._steps[at:]]
            )
            transformed = apply_transformations(
                self._source_candidate, next_steps,
                parameters=self._parameter_values(),
            )
            next_metadata = validate_applied_step_metadata(
                deepcopy(self._step_metadata), len(self._steps)
            ) if at < len(self._steps) else list(self._step_metadata)
        except TransformationError as exc:
            self._show_error(str(exc))
            return False
        next_metadata.insert(at, {})
        self._steps, self._step_metadata = next_steps, next_metadata
        step_name = (
            self._applied_step_names().get(at, "")
            if power_bi_name and is_known_power_bi_step(next_steps[at]) else ""
        )
        if step_name:
            self._step_metadata[at] = {"name": step_name}
        self._preview_candidate = transformed
        if self._insert_at is not None:
            self._insert_at = at + 1
        self._render_steps()
        self._refresh_preview()
        self._configure_editor()
        self.step_list.setCurrentRow(at)
        self._clear_error()
        return True

    def _detect_data_types(self) -> None:
        """Add explicit conversion steps for columns with safe inferred types."""
        if not self._confirm_insert_step():
            return
        try:
            self._detect_data_types_at(self._insert_position())
        finally:
            self._insert_at = None

    def _detect_data_types_at(self, at: int) -> None:
        """Detect on the table as it is before step ``at`` and insert the conversions there."""
        state = self._query_states.get(self._active_query_id, {})
        inserting = at < len(self._steps)
        try:
            base = (
                apply_transformations(
                    self._source_candidate, self._steps[:at],
                    parameters=self._parameter_values(),
                )
                if inserting else self._preview_candidate
            )
            current_types = column_types_after_steps(
                self._source_candidate.headers,
                self._steps[:at],
                output_headers=base.headers,
                initial_types=state.get("source_column_types", {}),
            )
            detected_types = infer_column_types(base.headers, base.rows)
            detected_steps = [
                {"op": "convert_type", "column": column, "type": type_name}
                for column, type_name in detected_types.items()
                if type_name != "text" and current_types.get(column, "text") != type_name
            ]
            if not detected_steps:
                self._clear_error()
                self.error_label.setStyleSheet("color: #526477;")
                self.error_label.setText("No additional columns have a safe supported type to apply.")
                self.error_label.setVisible(True)
                return
            next_steps = validate_steps(
                [*self._steps[:at], *detected_steps, *self._steps[at:]]
            )
            transformed = apply_transformations(
                self._source_candidate, next_steps,
                parameters=self._parameter_values(),
            )
            next_metadata = (
                validate_applied_step_metadata(
                    deepcopy(self._step_metadata), len(self._steps)
                )
                if inserting else list(self._step_metadata)
            )
        except (TransformationError, ValueError) as exc:
            self._show_error(str(exc))
            return

        next_metadata[at:at] = [{} for _ in detected_steps]
        self._steps = next_steps
        self._step_metadata = next_metadata
        self._preview_candidate = transformed
        self._render_steps()
        self._refresh_preview()
        self._configure_editor()
        if inserting:
            self.step_list.setCurrentRow(at + len(detected_steps) - 1)
        self._save_active_query_state()
        self._clear_error()

    def _remove_step(self) -> None:
        index = self.step_list.currentRow()
        if index < 0:
            return
        original_steps = deepcopy(self._steps)
        original_metadata = deepcopy(self._step_metadata)
        removed_step = self._steps.pop(index)
        self._step_metadata.pop(index)
        if removed_step["op"] in {
            "remove_sparse_top_rows", "remove_sparse_bottom_rows",
        } and not any(
            step["op"] in {"remove_sparse_top_rows", "remove_sparse_bottom_rows"}
            for step in self._steps
        ):
            helper_index = next(
                (
                    helper_index
                    for helper_index, step in enumerate(self._steps)
                    if step["op"] == "m_sparse_boundary_helper"
                ),
                None,
            )
            if helper_index is not None:
                self._steps.pop(helper_index)
                self._step_metadata.pop(helper_index)
        try:
            transformed = apply_transformations(
                self._source_candidate, self._steps,
                parameters=self._parameter_values(),
            )
        except TransformationError as exc:
            self._steps = original_steps
            self._step_metadata = original_metadata
            self._show_error(str(exc))
            return
        self._preview_candidate = transformed
        self._render_steps()
        self._refresh_preview()
        self._configure_editor()
        self.step_list.setCurrentRow(min(index, self.step_list.count() - 1))

    def _move_step(self, offset: int) -> None:
        index = self.step_list.currentRow()
        target = index + offset
        if index < 0 or target < 0 or target >= len(self._steps):
            return
        self._steps[index], self._steps[target] = self._steps[target], self._steps[index]
        self._step_metadata[index], self._step_metadata[target] = (
            self._step_metadata[target], self._step_metadata[index]
        )
        try:
            self._preview_candidate = apply_transformations(
                self._source_candidate, self._steps,
                parameters=self._parameter_values(),
            )
        except TransformationError as exc:
            self._steps[index], self._steps[target] = self._steps[target], self._steps[index]
            self._step_metadata[index], self._step_metadata[target] = (
                self._step_metadata[target], self._step_metadata[index]
            )
            self._show_error(str(exc))
            return
        self._render_steps()
        self._refresh_preview()
        self.step_list.setCurrentRow(target)

    def _update_selected_step(self) -> bool:
        index = self.step_list.currentRow()
        if index < 0 or index >= len(self._steps):
            return False
        next_steps = deepcopy(self._steps)
        try:
            next_steps[index] = self._create_step()
            next_steps = validate_steps(next_steps)
            transformed = apply_transformations(
                self._source_candidate, next_steps,
                parameters=self._parameter_values(),
            )
        except TransformationError as exc:
            self._show_error(str(exc))
            return False
        if self._steps[index].get("op") != next_steps[index].get("op"):
            self._step_metadata[index] = {}
        self._steps = next_steps
        self._preview_candidate = transformed
        self._render_steps()
        self._refresh_preview()
        self.step_list.setCurrentRow(index)
        self._clear_error()
        return True

    def _show_step_context_menu(self, position: Any) -> None:
        item = self.step_list.itemAt(position)
        if item is None:
            return
        self.step_list.setCurrentItem(item)
        index = self.step_list.currentRow()
        menu = QMenu(self.step_list)
        step = self._steps[index]
        edit_settings_action = menu.addAction("Edit Settings…")
        edit_settings_action.setObjectName("editAppliedStepSettingsAction")
        edit_settings_action.setEnabled(
            step["op"] not in self._STEP_OPERATIONS_WITHOUT_SETTINGS
        )
        rename_action = menu.addAction("Rename Step…")
        description_action = menu.addAction("Edit Description…")
        selected = menu.exec(self.step_list.mapToGlobal(position))
        if edit_settings_action is not None and selected is edit_settings_action:
            self._edit_selected_step_settings()
        elif selected is rename_action:
            self._rename_selected_step()
        elif selected is description_action:
            self._describe_selected_step()

    def _edit_selected_step_settings(self) -> None:
        """Open the selected step's initialized settings in a modal page."""
        index = self.step_list.currentRow()
        if not 0 <= index < len(self._steps):
            return
        step = self._steps[index]
        if step["op"] in self._STEP_OPERATIONS_WITHOUT_SETTINGS:
            return
        self._select_step(index)
        self.step_list.scrollToItem(self.step_list.item(index))
        if step["op"] == "add_custom_column":
            self._launch_custom_column_dialog(index)
            return
        if step["op"] == "conditional_column":
            self._open_conditional_dialog(index)
            return
        operation_name = self.operation_combo.currentText()
        settings_dialog = QDialog(self)
        settings_dialog.setObjectName("powerQueryStepSettingsDialog")
        settings_dialog.setWindowTitle(f"{operation_name} Settings")
        settings_dialog.setMinimumWidth(480)
        settings_dialog.resize(540, 460)
        dialog_layout = QVBoxLayout(settings_dialog)
        dialog_layout.setContentsMargins(16, 14, 16, 12)
        dialog_layout.addWidget(QLabel(f"Edit settings for {operation_name.lower()}"))
        settings_was_visible = not self.operation_settings_panel.isHidden()
        scroll = QScrollArea(settings_dialog)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        editor_layout = self.editor_panel.layout()
        editor_layout.removeWidget(self.operation_settings_panel)
        scroll.setWidget(self.operation_settings_panel)
        self.operation_settings_panel.setVisible(True)
        dialog_layout.addWidget(scroll, 1)
        editor_layout.removeWidget(self.error_label)
        self.error_label.setParent(settings_dialog)
        dialog_layout.addWidget(self.error_label)
        self.operation_combo.setVisible(False)
        self.operation_label.setVisible(False)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            parent=settings_dialog,
        )
        buttons.setObjectName("powerQueryStepSettingsButtons")
        buttons.button(QDialogButtonBox.StandardButton.Save).clicked.connect(
            lambda: settings_dialog.accept()
            if self._update_selected_step()
            else None
        )
        buttons.rejected.connect(settings_dialog.reject)
        dialog_layout.addWidget(buttons)
        try:
            result = settings_dialog.exec()
        finally:
            self.operation_settings_panel.setParent(self.editor_panel)
            editor_layout.insertWidget(0, self.operation_settings_panel)
            self.operation_settings_panel.setVisible(settings_was_visible)
            self.error_label.setParent(self.editor_panel)
            editor_layout.insertWidget(2, self.error_label)
            self.operation_combo.setVisible(True)
            self.operation_label.setVisible(True)
            self._select_step(index)
        if result != QDialog.DialogCode.Accepted:
            self._clear_error()

    def _edit_selected_step_metadata(
        self, index: int, *, name: str | None = None, description: str | None = None
    ) -> None:
        if not 0 <= index < len(self._steps):
            return
        metadata = deepcopy(self._step_metadata)
        while len(metadata) < len(self._steps):
            metadata.append({})
        if name is not None:
            if name.strip():
                metadata[index]["name"] = name.strip()
            else:
                metadata[index].pop("name", None)
        if description is not None:
            if description.strip():
                metadata[index]["description"] = description.strip()
            else:
                metadata[index].pop("description", None)
        try:
            self._step_metadata = validate_applied_step_metadata(metadata, len(self._steps))
        except TransformationError as exc:
            self._show_error(str(exc))
            return
        self._save_active_query_state()
        self._render_steps()
        self.step_list.setCurrentRow(index)
        self._clear_error()

    def _rename_selected_step(self) -> None:
        index = self.step_list.currentRow()
        if not 0 <= index < len(self._steps):
            return
        current = self._step_metadata[index].get("name", self.step_list.item(index).text())
        name, accepted = QInputDialog.getText(
            self, "Rename Applied Step", "Step name:", QLineEdit.EchoMode.Normal, current
        )
        if accepted:
            self._edit_selected_step_metadata(index, name=name)

    def _describe_selected_step(self) -> None:
        index = self.step_list.currentRow()
        if not 0 <= index < len(self._steps):
            return
        current = self._step_metadata[index].get("description", "")
        description, accepted = QInputDialog.getMultiLineText(
            self, "Applied Step Description", "Description:", current
        )
        if accepted:
            self._edit_selected_step_metadata(index, description=description)

    def _applied_step_names(self) -> dict[int, str]:
        """Power BI style names for the applied steps, keyed by step index."""
        table_indexes = [
            index for index, step in enumerate(self._steps)
            if step["op"] != "m_sparse_boundary_helper"
        ]
        names = assign_step_names(
            [self._steps[index] for index in table_indexes],
            custom_names=[
                str(self._step_metadata[index].get("name", "")).strip()
                if index < len(self._step_metadata) else ""
                for index in table_indexes
            ],
            reserved=["Source"],
        )
        return dict(zip(table_indexes, names))

    def _step_names_for(self, steps: list[dict[str, Any]]) -> list[str | None]:
        """Applied-step names for ``steps`` (a slice of ``self._steps``), by identity."""
        by_identity = {
            id(step): name
            for step, name in (
                (self._steps[index], name)
                for index, name in self._applied_step_names().items()
            )
        }
        return [by_identity.get(id(step)) for step in steps]

    def _render_steps(self) -> None:
        self.step_list.clear()
        applied_names = self._applied_step_names()
        for index, step in enumerate(self._steps):
            op = (
                "Count Rows"
                if step["op"] == "count_rows"
                else "Keep Range of Rows"
                if step["op"] == "keep_range_rows"
                else "Remove Alternate Rows"
                if step["op"] == "remove_alternate_rows"
                else f"Extract Text {step['side'].title()} Delimiter"
                if step["op"] == "extract_text_by_delimiter"
                else "Extract Text Between Delimiters"
                if step["op"] == "extract_text_between_delimiters"
                else "Capitalize Each Word"
                if step["op"] == "proper_case_text"
                else "Reverse Text"
                if step["op"] == "reverse_text"
                else "Sort Rows by Multiple Columns"
                if step["op"] == "sort_rows_by_columns"
                else "Advanced Filter Rows"
                if step["op"] == "filter_rows_advanced"
                else "Use First Row as Headers"
                if step["op"] == "promote_headers"
                else "Use Headers as First Row"
                if step["op"] == "demote_headers"
                else "Remove Sparse Top Rows"
                if step["op"] == "remove_sparse_top_rows"
                else "Remove Sparse Bottom Rows"
                if step["op"] == "remove_sparse_bottom_rows"
                else "Filter Null And Whitespace"
                if step["op"] == "m_sparse_boundary_helper"
                else step["op"].replace("_", " ").title()
            )
            detail = step.get("column", "")
            if "culture" in step:
                op = "Change Type Using Locale"
            if step["op"] == "promote_headers":
                detail = "first data row becomes column names"
            elif step["op"] == "count_rows":
                detail = "row count → Count"
            elif step["op"] == "demote_headers":
                detail = "column names become the first data row"
            elif step["op"] == "transpose_table":
                detail = "rows ↔ columns; original column names are dropped"
            elif step["op"] in {"remove_sparse_top_rows", "remove_sparse_bottom_rows"}:
                detail = (
                    "consecutive boundary rows with at most one nonblank field; "
                    "stop at the first row with two or more nonblank fields or a cell error"
                )
            elif step["op"] == "m_sparse_boundary_helper":
                detail = "function definition; does not change table rows"
            elif step["op"] == "sort_rows_by_columns":
                detail = ", ".join(
                    f"{sort['column']} {sort['direction']}" for sort in step["sorts"]
                )
            elif step["op"] == "split_column_by_positions":
                detail = (
                    f"{step['column']} at {', '.join(map(str, step['positions']))} (zero-based)"
                )
            elif step["op"] == "add_index_column":
                detail = (
                    f"start {step['start']}, increment {step['increment']} "
                    f"→ {step['new_name']}"
                )
            elif step["op"] == "merge_columns":
                detail = (
                    f"{', '.join(step['columns'])} {step['separator']!r} "
                    f"→ {step['new_name']}"
                )
            elif step["op"] == "extract_text_by_delimiter":
                detail = (
                    f"{step['column']} occurrence {step['occurrence']} "
                    f"{step['delimiter']!r}"
                )
            elif step["op"] == "extract_text_between_delimiters":
                detail = (
                    f"{step['column']} {step['start_delimiter']!r} "
                    f"({step['start_occurrence']}) … {step['end_delimiter']!r} "
                    f"({step['end_occurrence']})"
                )
            elif step["op"] == "reorder_columns":
                detail = " → ".join(step["columns"])
                if len(detail) > 80:
                    detail = detail[:77] + "…"
            elif "new_name" in step:
                detail += f" → {step['new_name']}"
            elif "replacement" in step:
                detail += f" {step['value']!r} → {step['replacement']!r}"
            elif "delimiter" in step:
                split_mode = {
                    "split_column": "first",
                    "split_column_by_each_delimiter": "each into columns",
                    "split_column_to_rows": "each into rows",
                }.get(step["op"], "")
                detail += f" at {split_mode} {step['delimiter']!r}"
            elif (
                step["op"] == "filter_rows"
                and step["operator"] in FILTER_OPERATORS_WITHOUT_VALUE
            ):
                detail += (
                    " is blank"
                    if step["operator"] == "is_blank"
                    else " is not blank"
                )
            elif "parameter" in step:
                detail += f" {step['operator']} parameter {step['parameter']}"
            elif "value" in step:
                detail += f" {step['operator']} {step['value']}"
            elif "direction" in step:
                detail += f" {step['direction']}"
            elif "type" in step:
                detail += f" → {step['type']}"
                if "culture" in step:
                    detail += f" ({step['culture']})"
            elif step["op"] == "add_custom_column":
                expression = step["expression"].replace("\n", " ").strip()
                if len(expression) > 52:
                    expression = expression[:49] + "…"
                detail = f"{expression} → {step['name']}"
            elif step["op"] == "conditional_column":
                detail = f"{len(step['clauses'])} clauses → {step['name']}"
            elif step["op"] == "filter_rows_advanced":
                detail = f"{len(step['clauses'])} clauses; AND before OR"
            elif step["op"] in {"fill_down", "fill_up"}:
                detail = ", ".join(step["columns"])
            elif step["op"] == "pivot_column":
                detail = (
                    f"{step['attribute_column']} → {step['value_column']}; "
                    f"{step['aggregation'].replace('_', ' ')}"
                )
            elif "columns" in step:
                if step["op"] == "group_by":
                    keys = ", ".join(step["columns"])
                    aggregates = "; ".join(
                        f"{aggregate['operation'].replace('_', ' ')}"
                        + (f"({aggregate['column']})" if "column" in aggregate else "")
                        + f" → {aggregate['new_name']}"
                        for aggregate in step["aggregations"]
                    )
                    detail = f"{keys}; {aggregates}"
                elif step["op"] in {"unpivot_columns", "unpivot_other_columns"}:
                    mode = (
                        "unpivot"
                        if step["op"] == "unpivot_columns"
                        else "keep; unpivot other"
                    )
                    detail = (
                        f"{mode} {', '.join(step['columns'])}; "
                        f"{step['attribute_name']} / {step['value_name']}"
                    )
                elif step["op"] in {"remove_duplicates", "keep_duplicates"}:
                    detail = f"keys: {', '.join(step['columns'])}"
                else:
                    detail = ", ".join(step["columns"])
            elif step["op"] == "remove_duplicates":
                detail = "entire rows"
            elif step["op"] == "remove_blank_rows":
                detail = "all fields empty"
            elif step["op"] == "remove_rows_with_errors":
                detail = (
                    "all fields"
                    if "columns" not in step
                    else f"columns: {', '.join(step['columns'])}"
                )
            elif step["op"] == "keep_range_rows":
                detail = f"from row {step['first_row']}, {step['count']} rows"
            elif step["op"] == "remove_alternate_rows":
                detail = (
                    f"from row {step['first_row_to_remove']}; remove "
                    f"{step['remove_count']}, keep {step['keep_count']}"
                )
            elif step["op"] in {"remove_top_rows", "remove_bottom_rows", "keep_top_rows", "keep_bottom_rows"}:
                detail = str(step["count"])
            default_label = f"{op}: {detail}" if detail else op
            metadata = self._step_metadata[index] if index < len(self._step_metadata) else {}
            custom_name = str(metadata.get("name", "")).strip()
            description = str(metadata.get("description", "")).strip()
            item = QListWidgetItem(
                applied_names.get(index) or custom_name or default_label
            )
            item.setToolTip(
                f"{description}\n\n{default_label}" if description else default_label
            )
            self.step_list.addItem(item)
        has_steps = bool(self._steps)
        self.step_list.setVisible(has_steps)
        self.steps_empty_label.setVisible(not has_steps)
        self._update_step_controls()
        self._refresh_formula_bar()

    def _refresh_preview(self) -> None:
        model = self.preview.model()
        assert isinstance(model, ImportPreviewTableModel)
        candidate = self._selected_preview_candidate()
        model.set_candidate(candidate)
        selected_step = self.step_list.currentRow()
        stage = (
            f"after step {selected_step + 1}"
            if 0 <= selected_step < len(self._steps)
            else "after all steps"
        )
        self.count_label.setText(
            f"{len(candidate.headers):,} columns · "
            f"{candidate.row_count:,} rows {stage}"
        )
        self._refresh_column_profiles()

    def _refresh_source_preview(
        self,
        *,
        expected_schemas: dict[str, tuple[Any, ...]] | None = None,
    ) -> bool:
        """Reread this query's source inputs and replay its current steps."""
        callback = self._refresh_candidate_callback
        if callback is None:
            return False
        query = self._query_states.get(self._active_query_id)
        if query is None or query.get("is_unavailable"):
            return False
        if (
            query.get("is_saved_query")
            and not query.get("include_in_report_refresh", True)
        ):
            self._show_error(
                "This query is excluded from report refresh and uses its cached preview. "
                "Enable 'Include in report refresh' in Query Settings to refresh its sources."
            )
            return False
        try:
            source_candidate, source_types, refreshed_queries = callback(
                self._active_query_id,
                self._query_states,
                self._parameter_values(),
            )
            if not isinstance(source_candidate, ImportCandidate):
                raise QueryError("The source refresh returned no table preview.")
            source_types = dict(source_types)
            steps = validate_steps(self._steps)
            preview_candidate = apply_transformations(
                source_candidate,
                steps,
                parameters=self._parameter_values(),
            )
            result_types = column_types_after_steps(
                source_candidate.headers,
                steps,
                output_headers=preview_candidate.headers,
                initial_types=source_types,
            )
            if expected_schemas is not None:
                source_signature = (
                    tuple(source_candidate.headers),
                    tuple(preview_candidate.headers),
                    tuple(sorted(source_types.items())),
                    tuple(sorted(result_types.items())),
                )
                if expected_schemas.get(self._active_query_id) != source_signature:
                    raise TransformationError(
                        "Source settings must preserve existing column names or data types so model and report references remain valid."
                    )
                for query_id, refreshed in refreshed_queries.items():
                    raw_candidate, transformed, initial_types, type_map = refreshed
                    dependent_signature = (
                        tuple(raw_candidate.headers),
                        tuple(transformed.headers),
                        tuple(sorted(initial_types.items())),
                        tuple(sorted(type_map.items())),
                    )
                    if expected_schemas.get(query_id) != dependent_signature:
                        raise TransformationError(
                            "Source settings must preserve existing column names or data types so model and report references remain valid."
                        )
        except (OSError, QueryError, TransformationError, TypeError, ValueError) as exc:
            self._show_error(f"Could not refresh preview: {exc}")
            return False

        selected_step = self.step_list.currentRow()
        for query_id, refreshed in refreshed_queries.items():
            state = self._query_states.get(query_id)
            if state is None:
                continue
            raw_candidate, preview, initial_types, result_types = refreshed
            state["source_candidate"] = raw_candidate
            state["source_column_types"] = dict(initial_types)
            state["preview_candidate"] = preview
            state["column_types"] = dict(result_types)
            state["preview_refreshed"] = True
        self._source_candidate = source_candidate
        self._preview_candidate = preview_candidate
        query["source_candidate"] = source_candidate
        query["source_column_types"] = source_types
        query["steps"] = deepcopy(steps)
        query["preview_candidate"] = preview_candidate
        query["column_types"] = result_types
        query["preview_refreshed"] = True
        self._render_steps()
        if 0 <= selected_step < self.step_list.count():
            self.step_list.setCurrentRow(selected_step)
        else:
            self._refresh_preview()
        self._save_active_query_state()
        self._clear_error()
        self.count_label.setToolTip("Preview refreshed from the current source data.")
        return True

    def _selected_preview_candidate(self) -> ImportCandidate:
        selected_step = self.step_list.currentRow()
        if 0 <= selected_step < len(self._steps):
            return apply_transformations(
                self._source_candidate, self._steps[: selected_step + 1],
                parameters=self._parameter_values(),
            )
        return self._preview_candidate

    def _refresh_formula_bar(self) -> None:
        index = self.step_list.currentRow()
        self.formula_bar.setReadOnly(False)
        self.formula_edit_button.setEnabled(True)
        self.cancel_formula_button.setEnabled(False)
        if index < 0:
            state = self._query_states.get(self._active_query_id, {})
            try:
                source_line = steps_to_m_script(
                    [], self._query_name,
                    source_query_names=self._query_source_names(state),
                    initial_column_types=state.get("source_column_types", {}),
                ).splitlines()[1].strip()
            except PowerQueryMScriptError:
                self.formula_bar.clear()
                self.formula_bar.setPlaceholderText(
                    "Append source is unavailable until both parent queries load"
                )
                self.formula_bar.setToolTip(
                    "The saved Append dependencies could not be resolved in this session."
                )
                self.formula_bar.setEnabled(False)
                self.apply_formula_button.setEnabled(False)
                return
            self.formula_bar.setText(source_line.split(" = ", 1)[1])
            self.formula_bar.setToolTip("The source reference for this query.")
            self.formula_bar.setEnabled(False)
            self.apply_formula_button.setEnabled(False)
            return
        if index >= len(self._steps):
            self.formula_bar.clear()
            self.formula_bar.setPlaceholderText(
                "Select an applied step to inspect its M expression"
            )
            self.formula_bar.setEnabled(False)
            self.apply_formula_button.setEnabled(False)
            return
        selected_helper = self._steps[index]["op"] == "m_sparse_boundary_helper"
        current_steps = (
            self._steps if selected_helper else self._steps[: index + 1]
        )
        expression_index = index
        if (
            not selected_helper
            and any(step["op"] == "m_sparse_boundary_helper" for step in current_steps)
            and not any(
                step["op"] in {"remove_sparse_top_rows", "remove_sparse_bottom_rows"}
                for step in current_steps
            )
        ):
            current_steps = [
                step for step in current_steps
                if step["op"] != "m_sparse_boundary_helper"
            ]
            expression_index -= 1
        issues = m_compatibility_issues(
            current_steps,
            parameter_names=set(self._parameter_values()),
            query_functions=self._query_functions,
            initial_column_types=self._query_states.get(
                self._active_query_id, {}
            ).get("source_column_types", {}),
        )
        if issues:
            issue = issues[0]
            self.formula_bar.clear()
            self.formula_bar.setPlaceholderText(
                f"M formula unavailable for step {issue['step']}: {issue['message']}"
            )
            self.formula_bar.setToolTip(
                "This local transformation has no faithful expression in the supported M subset."
            )
            self.formula_bar.setEnabled(False)
            self.apply_formula_button.setEnabled(False)
            return
        try:
            expression = step_expression_to_m(
                current_steps,
                self._query_name,
                expression_index,
                parameter_names=set(self._parameter_values()),
                query_functions=self._query_functions,
                initial_column_types=self._query_states.get(
                    self._active_query_id, {}
                ).get("source_column_types", {}),
                step_names=self._step_names_for(current_steps),
            )
        except (IndexError, ValueError, PowerQueryMScriptError, TransformationError) as exc:
            self.formula_bar.clear()
            self.formula_bar.setPlaceholderText(f"Could not display this M expression: {exc}")
            return
        if "\n" in expression or "\r" in expression:
            self.formula_bar.clear()
            self.formula_bar.setPlaceholderText(
                "This M expression spans multiple lines; edit it in Advanced Editor"
            )
            self.formula_bar.setToolTip(
                "The formula bar is single-line. Advanced Editor preserves the complete multiline expression."
            )
            self.formula_bar.setEnabled(False)
            self.apply_formula_button.setEnabled(False)
            return
        self.formula_bar.setPlaceholderText("Select an applied step to inspect its M expression")
        self.formula_bar.setText(expression)
        self.formula_bar.setEnabled(True)
        self.formula_bar.setReadOnly(selected_helper)
        self.apply_formula_button.setEnabled(not selected_helper)
        self.cancel_formula_button.setEnabled(not selected_helper)
        self.formula_bar.setToolTip(
            "This captured function definition is read-only in the local subset."
            if selected_helper
            else "Edit this supported step expression and press Return or Apply formula. Edit the complete query in Advanced Editor."
        )

    def _apply_formula_bar(self) -> None:
        index = self.step_list.currentRow()
        expression = self.formula_bar.text().strip()
        if not 0 <= index < len(self._steps):
            self._show_error("Select an applied step before editing its formula.")
            return
        if self._steps[index]["op"] == "m_sparse_boundary_helper":
            self._show_error(
                "This captured sparse-boundary helper definition is fixed in the local M subset."
            )
            return
        if not expression:
            self._show_error("Enter a Power Query M table expression.")
            return
        try:
            edited_script = replace_step_expression_in_m(
                self._steps,
                self._query_name,
                index,
                expression,
                parameter_names=set(self._parameter_values()),
                query_functions=self._query_functions,
                initial_column_types=self._query_states.get(
                    self._active_query_id, {}
                ).get("source_column_types", {}),
                step_names=self._step_names_for(self._steps),
            )
            parsed_prefix = parse_m_script(
                edited_script, self._query_name,
                parameter_names=set(self._parameter_values()),
                query_functions=self._query_functions,
                initial_column_types=self._query_states.get(
                    self._active_query_id, {}
                ).get("source_column_types", {}),
            )
            selected_table_index = sum(
                step["op"] != "m_sparse_boundary_helper"
                for step in self._steps[:index]
            )
            parsed_table_positions = [
                parsed_index
                for parsed_index, parsed_step in enumerate(parsed_prefix)
                if parsed_step["op"] != "m_sparse_boundary_helper"
            ]
            if selected_table_index >= len(parsed_table_positions):
                raise PowerQueryMScriptError(
                    "The edited M expression did not produce a local table step."
                )
            edited_steps = parsed_prefix[
                parsed_table_positions[selected_table_index]:
            ]
            next_steps = [
                *self._steps[:index], *edited_steps, *self._steps[index + 1:]
            ]
            next_metadata = [
                *deepcopy(self._step_metadata[:index]),
                *(
                    [deepcopy(self._step_metadata[index])]
                    if edited_steps[0]["op"] == self._steps[index]["op"]
                    else [{}]
                ),
                *({} for _ in edited_steps[1:]),
                *deepcopy(self._step_metadata[index + 1:]),
            ]
            if not any(
                step["op"] in {"remove_sparse_top_rows", "remove_sparse_bottom_rows"}
                for step in next_steps
            ):
                retained = [
                    (step, metadata)
                    for step, metadata in zip(next_steps, next_metadata)
                    if step["op"] != "m_sparse_boundary_helper"
                ]
                next_steps = [step for step, _metadata in retained]
                next_metadata = [metadata for _step, metadata in retained]
            next_steps = validate_steps(next_steps)
            next_metadata = validate_applied_step_metadata(
                next_metadata, len(next_steps)
            )
            transformed = apply_transformations(
                self._source_candidate, next_steps,
                parameters=self._parameter_values(),
            )
        except (PowerQueryMScriptError, TransformationError, ValueError) as exc:
            self._show_error(str(exc))
            return
        self._steps = next_steps
        self._step_metadata = next_metadata
        self._preview_candidate = transformed
        self._render_steps()
        self._refresh_preview()
        self._configure_editor()
        self.step_list.setCurrentRow(min(index, self.step_list.count() - 1))
        self._clear_error()

    def _refresh_column_profiles(self, *_args: Any) -> None:
        candidate = self._selected_preview_candidate()
        rows = candidate.rows
        if self.profile_scope_combo.currentData() == "preview":
            rows = rows[:100]
        row_count = len(rows)
        selected_step = self.step_list.currentRow()
        profile_steps = (
            self._steps[: selected_step + 1]
            if 0 <= selected_step < len(self._steps)
            else self._steps
        )
        active_filter_columns: set[str] = set()
        for step in profile_steps:
            if step["op"] == "filter_rows":
                active_filter_columns.add(step["column"])
            elif step["op"] == "filter_rows_advanced":
                active_filter_columns.update(
                    clause["column"] for clause in step["clauses"]
                )
        try:
            type_map = column_types_after_steps(
                self._source_candidate.headers,
                profile_steps,
                output_headers=candidate.headers,
                initial_types=self._query_states.get(
                    self._active_query_id, {}
                ).get("source_column_types", {}),
            )
        except TransformationError:
            type_map = {}

        self.quality_table.setRowCount(len(candidate.headers))
        self.profile_table.setRowCount(len(candidate.headers))
        self.schema_table.setRowCount(len(candidate.headers))
        inline_profiles: list[dict[str, Any]] = []
        for index, column in enumerate(candidate.headers):
            values = [row.get(column, "") for row in rows]
            null_count = sum(value is None for value in values)
            empty_count = sum(
                value == "" for value in values if not is_cell_error(value)
            )
            type_name = type_map.get(column, "text")
            error_count = (
                count_conversion_errors(values, type_name)
                if type_name != "text"
                else sum(is_cell_error(value) for value in values)
            )
            valid_values = [
                value for value in values
                if value is not None and value != "" and not is_cell_error(value)
            ]
            valid_count = row_count - null_count - empty_count - error_count
            valid_percent = (100.0 * valid_count / row_count) if row_count else 0.0
            empty_percent = (100.0 * empty_count / row_count) if row_count else 0.0
            error_percent = (100.0 * error_count / row_count) if row_count else 0.0
            null_percent = (100.0 * null_count / row_count) if row_count else 0.0
            quality_values = (
                column,
                f"{valid_percent:.1f}% ({valid_count:,})",
                f"{empty_percent:.1f}% ({empty_count:,})",
                f"{error_percent:.1f}% ({error_count:,})",
                f"{null_percent:.1f}% ({null_count:,})",
            )
            for column_index, value in enumerate(quality_values):
                self.quality_table.setItem(index, column_index, QTableWidgetItem(value))

            # Null, empty text, and errors remain separate from valid value frequencies.
            non_empty_counts: dict[tuple[Any, ...], dict[str, Any]] = {}
            for value in valid_values:
                key = cell_key(value)
                entry = non_empty_counts.setdefault(key, {
                    "value": cell_to_text(value),
                    "type": _profile_cell_type(value),
                    "count": 0,
                })
                entry["count"] += 1
            top_values = sorted(
                non_empty_counts.values(),
                key=lambda item: (
                    -item["count"], item["value"].casefold(),
                    item["value"], item["type"],
                ),
            )[:3]
            top_text = ", ".join(
                f"{item['value']}"
                + (f" [{item['type']}]" if item["type"] != "text" else "")
                + f" ({item['count']:,})"
                for item in top_values
            )
            frequencies = [
                int(item["count"])
                for item in sorted(
                    non_empty_counts.values(),
                    key=lambda item: (
                        -item["count"], item["value"].casefold(),
                        item["value"], item["type"],
                    ),
                )
            ]
            unique_count = sum(
                1 for item in non_empty_counts.values() if item["count"] == 1
            )
            inline_profiles.append({
                "name": column,
                "type": type_name,
                "valid": f"{valid_percent:.0f}%",
                "error": f"{error_percent:.0f}%",
                "empty": f"{(empty_percent + null_percent):.0f}%",
                "distinct": len(non_empty_counts),
                "unique": unique_count,
                "frequencies": frequencies,
                "filter_active": column in active_filter_columns,
            })
            profile_values = (
                column,
                type_name,
                f"{len(non_empty_counts):,}",
                f"{unique_count:,}",
                top_text or "—",
            )
            for column_index, value in enumerate(profile_values):
                self.profile_table.setItem(index, column_index, QTableWidgetItem(value))

            sample_values: list[str] = []
            sample_keys: set[tuple[Any, ...]] = set()
            for row in candidate.rows[:100]:
                raw_value = row.get(column, "")
                if raw_value is None or raw_value == "" or is_cell_error(raw_value):
                    continue
                value = cell_to_text(raw_value)
                key = cell_key(raw_value)
                if key not in sample_keys:
                    sample_keys.add(key)
                    sample_values.append(value)
                    if len(sample_values) == 3:
                        break
            schema_values = (
                str(index + 1),
                column,
                type_map.get(column, "text").replace("_", " "),
                ", ".join(sample_values) or "—",
            )
            for column_index, value in enumerate(schema_values):
                item = QTableWidgetItem(value)
                if column_index == 4 and sample_values:
                    item.setToolTip("\n".join(sample_values))
                self.schema_table.setItem(index, column_index, item)
        self.preview_header.set_profiles(inline_profiles)
        self.profile_scope_note.setText(
            f"Profile covers all {row_count:,} rows in the selected scope. "
            "Null, empty text, and conversion errors are counted separately."
        )

    def _update_step_controls(self) -> None:
        index = self.step_list.currentRow()
        valid = 0 <= index < len(self._steps)
        is_sparse_helper = (
            valid and self._steps[index]["op"] == "m_sparse_boundary_helper"
        )
        helper_precedes_step = (
            valid and index == 1
            and self._steps[0]["op"] == "m_sparse_boundary_helper"
        )
        self.remove_button.setEnabled(valid and not is_sparse_helper)
        self.up_button.setEnabled(valid and index > 0 and not helper_precedes_step)
        self.down_button.setEnabled(
            valid and index < len(self._steps) - 1 and not is_sparse_helper
        )
        self.step_settings_button.setEnabled(
            valid
            and self._steps[index]["op"] not in self._STEP_OPERATIONS_WITHOUT_SETTINGS
        )
        self.add_button.setText("New step" if valid else "Add step")
        self.update_button.setEnabled(
            valid
            and self._steps[index]["op"] not in self._STEP_OPERATIONS_WITHOUT_SETTINGS
            and self.operation_combo.findData(self._steps[index]["op"]) >= 0
        )

    def _show_error(self, message: str) -> None:
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.setVisible(False)

    def _accept_candidate(self) -> None:
        try:
            self._save_active_query_state()
            if self._query_states.get(self._active_query_id, {}).get("is_unavailable"):
                self._show_error(
                    "Select an available query before applying Power Query changes."
                )
                return
            accepted_queries: dict[str, dict[str, Any]] = {}
            normalized_names: set[str] = set()
            for query_id in self._query_order:
                query = self._query_states[query_id]
                if query.get("is_unavailable"):
                    continue
                if query.get("preview_error"):
                    raise TransformationError(
                        f"Cannot apply {query.get('name', 'query')!r}: "
                        f"{query['preview_error']}"
                    )
                query_name = str(query.get("name", "")).strip()
                description = str(query.get("description", ""))
                if (
                    not query_name
                    or len(query_name) > 120
                    or any(ord(char) < 32 for char in query_name)
                ):
                    raise TransformationError(
                        "Query names must be 1–120 characters and contain no control characters."
                    )
                if len(description) > 4000 or "\x00" in description:
                    raise TransformationError(
                        f"The description for {query_name!r} must be at most 4,000 characters and contain no null characters."
                    )
                normalized_name = query_name.casefold()
                if normalized_name in normalized_names:
                    raise TransformationError(
                        f"The query name {query_name!r} is already used by another query."
                    )
                normalized_names.add(normalized_name)
                query_group = str(query.get("query_group", "")).strip()
                if (
                    len(query_group) > 80
                    or "\x00" in query_group
                    or any(ord(char) < 32 for char in query_group)
                ):
                    raise TransformationError(
                        f"The query group for {query['name']!r} must be at most 80 characters and contain no control characters."
                    )
                query_steps = validate_steps(query["steps"])
                step_metadata = validate_applied_step_metadata(
                    query.get("step_metadata", []), len(query_steps)
                )
                candidate = apply_transformations(
                    query["source_candidate"], query_steps,
                    parameters=self._parameter_values(),
                )
                if candidate != query["preview_candidate"]:
                    raise TransformationError(
                        f"The preview for {query['name']!r} is out of date. Reopen the query and try again."
                    )
                accepted_queries[query_id] = {
                    "id": query_id,
                    "name": query_name,
                    "description": description.strip(),
                    "source_candidate": query["source_candidate"],
                    "source_column_types": dict(
                        query.get("source_column_types", {})
                    ),
                    "steps": query_steps,
                    "step_metadata": step_metadata,
                    "m_script": (
                        query.get("m_script")
                        if isinstance(query.get("m_script"), str)
                        and m_script_matches_steps(
                            query["m_script"], query_name, query_steps,
                            parameter_names=set(self._parameter_values()),
                            query_functions=self._query_functions,
                            source_query_names=self._query_source_names(query),
                            initial_column_types=query.get(
                                "source_column_types", {}
                            ),
                        )
                        else None
                    ),
                    "candidate": candidate,
                    "query_group": query_group,
                    "load_enabled": bool(query.get("load_enabled", True)),
                    "include_in_report_refresh": bool(
                        query.get("include_in_report_refresh", True)
                    ),
                    "query_definition": deepcopy(query.get("query_definition", {})),
                    "is_new_query": bool(query.get("is_new_query", False)),
                    "is_new_source": bool(query.get("is_new_source", False)),
                    "is_source_settings_changed": bool(
                        query.get("is_source_settings_changed", False)
                    ),
                    "source_record": deepcopy(query.get("source_record")),
                    "is_duplicate": bool(query.get("is_duplicate", False)),
                    "preview_refreshed": bool(query.get("preview_refreshed", False)),
                    "duplicate_of_id": str(query.get("duplicate_of_id", "")),
                    "is_active": query_id == self._active_query_id,
                    "column_types": column_types_after_steps(
                        query["source_candidate"].headers,
                        query_steps,
                        output_headers=candidate.headers,
                        initial_types=query.get("source_column_types", {}),
                    ),
                }
        except TransformationError as exc:
            QMessageBox.warning(self, "Could not apply transformations", str(exc))
            return
        active_result = accepted_queries[self._active_query_id]
        self._accepted_queries = accepted_queries
        self._accepted_candidate = active_result["candidate"]
        self._accepted_steps = active_result["steps"]
        self._accepted_parameters = deepcopy(self._query_parameters)
        self._accepted_functions = deepcopy(self._query_functions)
        super().accept()

    def _open_advanced_editor(self) -> None:
        self._save_active_query_state()
        active_state = self._query_states.get(self._active_query_id)
        if active_state is None or active_state.get("is_unavailable"):
            return
        self._query_name = str(active_state.get("name", self._query_name)).strip()
        source_query_names = self._query_source_names(active_state)
        query_sources = self._query_sources_for_names(
            source_query_names, active_state
        )
        if source_query_names is not None and (
            len(source_query_names) != 2 or len(query_sources) != 2
        ):
            self._show_error(
                "This Append query needs two available source queries before Advanced Editor can open."
            )
            return
        issues = m_compatibility_issues(
            self._steps,
            parameter_names=set(self._parameter_values()),
            query_functions=self._query_functions,
            initial_column_types=active_state.get("source_column_types", {}),
        )
        if issues:
            details = "\n".join(
                f"Step {issue['step']} ({issue['operation']}): {issue['message']}"
                for issue in issues
            )
            self._show_error(
                "Advanced Editor cannot represent every current step in its local M subset. "
                "Remove or replace these steps in Transform Data, then retry:\n" + details
            )
            return
        try:
            dialog = PowerQueryMEditorDialog(
                self._source_candidate,
                self._steps,
                self._query_name,
                self,
                initial_script=self._query_states.get(
                    self._active_query_id, {}
                ).get("m_script"),
                parameters=self._parameter_values(),
                query_functions=self._query_functions,
                source_query_names=source_query_names,
                query_sources=query_sources,
                source_column_types=active_state.get("source_column_types", {}),
                step_names=self._step_names_for(self._steps),
            )
        except (PowerQueryMScriptError, TransformationError) as exc:
            self._show_error(str(exc))
            return
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.candidate is None or dialog.steps is None:
            return
        if source_query_names is not None:
            source_candidate = dialog.source_candidate
            if source_candidate is None:
                return
            active_state["source_candidate"] = source_candidate
            self._source_candidate = source_candidate
        previous_steps = self._steps
        previous_metadata = self._step_metadata
        self._steps = dialog.steps
        state = self._query_states.get(self._active_query_id)
        if state is not None:
            if dialog.script is None:
                state.pop("m_script", None)
                state.pop("m_script_source_names", None)
            else:
                state["m_script"] = dialog.script
                if source_query_names is not None:
                    state["m_script_source_names"] = list(source_query_names)
            state["preview_candidate"] = dialog.candidate
        self._step_metadata = validate_applied_step_metadata(
            carry_step_metadata(
                dialog.initial_step_bindings,
                [str(step.get("op")) for step in previous_steps],
                previous_metadata,
                dialog.step_bindings or [],
                [str(step.get("op")) for step in self._steps],
            ),
            len(self._steps),
        )
        self._preview_candidate = dialog.candidate
        self._render_steps()
        self._refresh_preview()
        self._configure_editor()
        self._clear_error()

    def reject(self) -> None:
        self._accepted_candidate = None
        self._accepted_steps = None
        self._accepted_queries = None
        super().reject()

    # ---- closing the editor like Power BI -------------------------------

    def _pending_state(self) -> dict[str, Any]:
        """Everything the user can change in this session that Close & Apply would commit."""
        self._save_active_query_state()
        return {
            "order": list(self._query_order),
            "deleted": sorted(self._deleted_query_ids),
            "parameters": deepcopy(self._query_parameters),
            "functions": deepcopy(self._query_functions),
            "queries": {
                query_id: {
                    key: deepcopy(query.get(key))
                    for key in (
                        "name", "description", "steps", "step_metadata", "m_script",
                        "query_group", "load_enabled", "include_in_report_refresh",
                    )
                }
                for query_id, query in self._query_states.items()
            },
        }

    def has_pending_changes(self) -> bool:
        """True when the session holds edits or newly staged queries not yet applied."""
        if any(
            query.get("is_new_query") or query.get("is_new_source")
            or query.get("is_duplicate") or query.get("is_source_settings_changed")
            for query in self._query_states.values()
        ):
            return True
        return self._pending_state() != self._initial_pending_state

    def _ask_pending_changes(self) -> str:
        """Ask what to do with unapplied changes: ``apply``, ``discard`` or ``cancel``."""
        box = QMessageBox(self)
        box.setObjectName("powerQueryPendingChangesBox")
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Power Query Editor")
        box.setText(
            "You have pending changes in the Power Query Editor that have not been applied."
        )
        box.setInformativeText("Do you want to apply your changes before closing?")
        apply_button = box.addButton("Apply changes", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton(
            "Discard changes", QMessageBox.ButtonRole.DestructiveRole
        )
        cancel_button = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(apply_button)
        box.setEscapeButton(cancel_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is apply_button:
            return "apply"
        if clicked is discard_button:
            return "discard"
        return "cancel"

    def request_close(self) -> bool:
        """User-facing close (window button, Cmd+W, Esc, File > Close): ask when changes are pending."""
        self._close_operation_dialog()
        if not self.has_pending_changes():
            self.reject()
            return True
        choice = self._ask_pending_changes()
        if choice == "discard":
            self.reject()
            return True
        if choice == "apply":
            self._accept_candidate()
            return self.result() == QDialog.DialogCode.Accepted
        return False

    def done(self, result: int) -> None:
        # A parameter dialog borrows the settings panel; give it back before closing.
        self._close_operation_dialog()
        super().done(result)

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        event.ignore()
        self.request_close()

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and not event.modifiers():
            event.accept()
            self.request_close()
            return
        super().keyPressEvent(event)
