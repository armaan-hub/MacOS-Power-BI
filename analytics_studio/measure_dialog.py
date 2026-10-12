"""Native editors for local DAX measures and common quick aggregations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.measures import (
    DAX_FUNCTION_NAMES,
    MeasureError,
    normalize_measure,
)
from analytics_studio.dialog_theme import apply_light_dialog_theme


DAX_FUNCTION_TEMPLATES: dict[str, tuple[str, str | None]] = {
    "ABS": ("ABS(number)", "number"),
    "ALL": ("ALL('Table')", "'Table'"),
    "ALLEXCEPT": ("ALLEXCEPT('Table', 'Table'[Column])", "'Table'"),
    "ALLNOBLANKROW": ("ALLNOBLANKROW('Table')", "'Table'"),
    "ALLSELECTED": ("ALLSELECTED('Table')", "'Table'"),
    "AND": ("AND(condition1, condition2)", "condition1"),
    "AVERAGE": ("AVERAGE([Column])", "[Column]"),
    "AVERAGEX": ("AVERAGEX('Table', row_expression)", "'Table'"),
    "BLANK": ("BLANK()", None),
    "CALCULATE": ("CALCULATE(expression, filter)", "expression"),
    "CROSSFILTER": (
        "CROSSFILTER('Table'[Column], 'Table'[Column], BOTH)", "'Table'[Column]"
    ),
    "COUNT": ("COUNT([Column])", "[Column]"),
    "COUNTAX": ("COUNTAX('Table', row_expression)", "'Table'"),
    "COUNTA": ("COUNTA([Column])", "[Column]"),
    "COUNTROWS": ("COUNTROWS('Table')", "'Table'"),
    "COUNTX": ("COUNTX('Table', row_expression)", "'Table'"),
    "DATEADD": ("DATEADD('Calendar'[Date], intervals, MONTH)", "'Calendar'[Date]"),
    "DATESBETWEEN": (
        "DATESBETWEEN('Calendar'[Date], start_date, end_date)", "'Calendar'[Date]"
    ),
    "DATESINPERIOD": (
        "DATESINPERIOD('Calendar'[Date], end_date, intervals, MONTH)", "'Calendar'[Date]"
    ),
    "DATESMTD": ("DATESMTD('Calendar'[Date])", "'Calendar'[Date]"),
    "DATESQTD": ("DATESQTD('Calendar'[Date])", "'Calendar'[Date]"),
    "DATESYTD": ("DATESYTD('Calendar'[Date])", "'Calendar'[Date]"),
    "DISTINCT": ("DISTINCT('Table'[Column])", "'Table'[Column]"),
    "DISTINCTCOUNT": ("DISTINCTCOUNT([Column])", "[Column]"),
    "DISTINCTCOUNTNOBLANK": ("DISTINCTCOUNTNOBLANK([Column])", "[Column]"),
    "DIVIDE": ("DIVIDE(numerator, denominator)", "numerator"),
    "FALSE": ("FALSE()", None),
    "FILTER": ("FILTER('Table', condition)", "'Table'"),
    "IF": ("IF(condition, value_if_true, value_if_false)", "condition"),
    "KEEPFILTERS": ("KEEPFILTERS(filter)", "filter"),
    "MAX": ("MAX([Column])", "[Column]"),
    "MIN": ("MIN([Column])", "[Column]"),
    "NEXTDAY": ("NEXTDAY('Calendar'[Date])", "'Calendar'[Date]"),
    "NEXTMONTH": ("NEXTMONTH('Calendar'[Date])", "'Calendar'[Date]"),
    "NEXTQUARTER": ("NEXTQUARTER('Calendar'[Date])", "'Calendar'[Date]"),
    "NEXTYEAR": ("NEXTYEAR('Calendar'[Date])", "'Calendar'[Date]"),
    "NOT": ("NOT(condition)", "condition"),
    "OR": ("OR(condition1, condition2)", "condition1"),
    "PARALLELPERIOD": (
        "PARALLELPERIOD('Calendar'[Date], intervals, MONTH)", "'Calendar'[Date]"
    ),
    "PREVIOUSDAY": ("PREVIOUSDAY('Calendar'[Date])", "'Calendar'[Date]"),
    "PREVIOUSMONTH": ("PREVIOUSMONTH('Calendar'[Date])", "'Calendar'[Date]"),
    "PREVIOUSQUARTER": ("PREVIOUSQUARTER('Calendar'[Date])", "'Calendar'[Date]"),
    "PREVIOUSYEAR": ("PREVIOUSYEAR('Calendar'[Date])", "'Calendar'[Date]"),
    "REMOVEFILTERS": ("REMOVEFILTERS()", None),
    "RELATED": ("RELATED('Related table'[Column])", "'Related table'[Column]"),
    "ROUND": ("ROUND(number, digits)", "number"),
    "SAMEPERIODLASTYEAR": ("SAMEPERIODLASTYEAR('Calendar'[Date])", "'Calendar'[Date]"),
    "SUM": ("SUM([Column])", "[Column]"),
    "SUMX": ("SUMX('Table', row_expression)", "'Table'"),
    "TRUE": ("TRUE()", None),
    "TOTALMTD": ("TOTALMTD(expression, 'Calendar'[Date])", "expression"),
    "TOTALQTD": ("TOTALQTD(expression, 'Calendar'[Date])", "expression"),
    "TOTALYTD": ("TOTALYTD(expression, 'Calendar'[Date])", "expression"),
    "USERELATIONSHIP": (
        "USERELATIONSHIP('Table'[Column], 'Table'[Column])", "'Table'[Column]"
    ),
}


class MeasureDialog(QDialog):
    """Collect one measure definition; computation is performed by the controller."""

    def __init__(
        self,
        headers: list[str],
        existing_names: list[str],
        *,
        quick: bool = False,
        default_column: str | None = None,
        initial_measure: dict[str, Any] | None = None,
        field_references: list[tuple[str, str]] | None = None,
        measure_references: list[str] | None = None,
        preview_callback: Callable[[str, str], str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_light_dialog_theme(self)
        self.quick = quick
        self._editing_name = (
            str(initial_measure.get("name", "")) if initial_measure else ""
        )
        self._existing_names = {
            name.casefold() for name in existing_names
            if name.casefold() != self._editing_name.casefold()
        }
        self._accepted_measure: dict[str, Any] | None = None
        self._preview_callback = preview_callback
        editing = initial_measure is not None
        self.setWindowTitle(
            "Quick measure" if quick else "Edit measure" if editing else "New measure"
        )
        self.setMinimumWidth(560)
        self.resize(640, 470 if quick else 590)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        title = QLabel(
            "Edit a local DAX measure" if editing else "Create a local DAX measure"
        )
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(120)
        if initial_measure:
            self.name_edit.setText(str(initial_measure.get("name", "")))
        form.addRow("Measure name", self.name_edit)
        self.expression_edit = QPlainTextEdit()
        self.expression_edit.setPlaceholderText("SUM([Sales]) / COUNTROWS()")
        self.expression_edit.setMaximumHeight(110)
        self.expression_edit.setObjectName("daxMeasureExpression")
        if initial_measure:
            self.expression_edit.setPlainText(str(initial_measure.get("expression", "")))
        self.expression_edit.setVisible(not quick)
        if quick:
            self.function_combo = QComboBox()
            for label, function in (
                ("Sum", "SUM"), ("Average", "AVERAGE"), ("Minimum", "MIN"),
                ("Maximum", "MAX"), ("Count numbers", "COUNT"),
                ("Count non-empty", "COUNTA"), ("Distinct count", "DISTINCTCOUNT"),
                ("Distinct count without blank", "DISTINCTCOUNTNOBLANK"),
            ):
                self.function_combo.addItem(label, function)
            self.column_combo = QComboBox()
            self.column_combo.addItems(headers)
            if default_column in headers:
                self.column_combo.setCurrentText(default_column)
            form.addRow("Calculation", self.function_combo)
            form.addRow("Column", self.column_combo)
            self.function_combo.currentIndexChanged.connect(self._refresh_error)
            self.function_combo.currentIndexChanged.connect(
                lambda _index: self._update_quick_name(self.column_combo.currentText())
            )
            self.column_combo.currentIndexChanged.connect(self._refresh_error)
            if headers:
                self.name_edit.setText(f"Sum of {self.column_combo.currentText()}")
            self.column_combo.currentTextChanged.connect(self._update_quick_name)
        else:
            form.addRow("DAX expression", self.expression_edit)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setObjectName("daxMeasureDescription")
        self.description_edit.setPlaceholderText("Describe what this measure represents")
        self.description_edit.setMaximumHeight(62)
        if initial_measure:
            self.description_edit.setPlainText(str(initial_measure.get("description", "")))
        form.addRow("Description", self.description_edit)
        self.display_folder_edit = QLineEdit()
        self.display_folder_edit.setObjectName("daxMeasureDisplayFolder")
        self.display_folder_edit.setMaxLength(400)
        self.display_folder_edit.setPlaceholderText("Optional model display folder")
        if initial_measure:
            self.display_folder_edit.setText(str(initial_measure.get("display_folder", "")))
        form.addRow("Display folder", self.display_folder_edit)
        self.hidden_checkbox = QCheckBox("Hide from report field lists")
        self.hidden_checkbox.setObjectName("daxMeasureHidden")
        self.hidden_checkbox.setChecked(bool(initial_measure and initial_measure.get("is_hidden", False)))
        form.addRow("Visibility", self.hidden_checkbox)
        layout.addLayout(form)

        if not quick:
            self.function_combo = self._search_combo("Search supported function names")
            self.function_combo.setObjectName("daxFunctionPicker")
            self.function_combo.addItems(DAX_FUNCTION_NAMES)
            self.function_combo.setCurrentIndex(-1)
            self.function_signature_label = QLabel(
                "Choose a recognized function to see its local syntax template."
            )
            self.function_signature_label.setObjectName("daxFunctionSignatureHint")
            self.function_signature_label.setWordWrap(True)
            self.function_signature_label.setStyleSheet("color: #526477;")
            self.function_combo.currentTextChanged.connect(
                self._update_function_signature
            )
            self.insert_function_button = QPushButton("Insert function")
            self.insert_function_button.setObjectName("insertDaxFunctionButton")
            self.insert_function_button.clicked.connect(self._insert_function)
            function_row = QHBoxLayout()
            function_row.addWidget(self.function_combo, 1)
            function_row.addWidget(self.insert_function_button)
            form.addRow("Function", function_row)
            form.addRow("Syntax", self.function_signature_label)

            self.field_combo = self._search_combo("Search loaded table fields")
            self.field_combo.setObjectName("daxFieldPicker")
            for label, reference in field_references or []:
                self.field_combo.addItem(label, reference)
            self.field_combo.setCurrentIndex(-1)
            self.insert_field_button = QPushButton("Insert field")
            self.insert_field_button.setObjectName("insertDaxFieldButton")
            self.insert_field_button.clicked.connect(self._insert_field_reference)
            field_row = QHBoxLayout()
            field_row.addWidget(self.field_combo, 1)
            field_row.addWidget(self.insert_field_button)
            form.addRow("Model field", field_row)

            self.measure_combo = self._search_combo("Search saved measures")
            self.measure_combo.setObjectName("daxMeasurePicker")
            for measure_name in measure_references or []:
                self.measure_combo.addItem(measure_name, f"[{measure_name}]")
            self.measure_combo.setCurrentIndex(-1)
            self.insert_measure_button = QPushButton("Insert measure")
            self.insert_measure_button.setObjectName("insertDaxMeasureButton")
            self.insert_measure_button.clicked.connect(self._insert_measure_reference)
            measure_row = QHBoxLayout()
            measure_row.addWidget(self.measure_combo, 1)
            measure_row.addWidget(self.insert_measure_button)
            form.addRow("Measure", measure_row)

        preview_row = QHBoxLayout()
        self.preview_button = QPushButton("Validate / preview")
        self.preview_button.setObjectName("previewDaxMeasureButton")
        self.preview_button.setVisible(preview_callback is not None)
        self.preview_button.setEnabled(preview_callback is not None)
        self.preview_button.clicked.connect(self._preview_measure)
        self.preview_label = QLabel()
        self.preview_label.setObjectName("daxMeasurePreview")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("color: #526477;")
        preview_row.addWidget(self.preview_button)
        preview_row.addWidget(self.preview_label, 1)
        layout.addLayout(preview_row)

        help_label = QLabel(
            "Recognized local function names (partial support): "
            + ", ".join(DAX_FUNCTION_NAMES)
            + ". Not every Microsoft signature or behavior is implemented. Validate / preview "
            "checks the current expression against this model and report context. "
            "Time-intelligence functions use their supported "
            "CALCULATE date-filter forms. "
            "TOTALYTD(expression, 'Calendar'[Date]), "
            "TOTALQTD(expression, 'Calendar'[Date]), and "
            "TOTALMTD(expression, 'Calendar'[Date]) require a marked date-table column. "
            "TOTALYTD, TOTALQTD, and TOTALMTD do not accept extra filter arguments. "
            "Use CALCULATE(SUM([Amount]), DATEADD('Calendar'[Date], -1, MONTH)) for a shifted measure. "
            "Use CALCULATE(SUM([Amount]), SAMEPERIODLASTYEAR('Calendar'[Date])) for prior-year dates. "
            "Use CALCULATE(SUM([Amount]), PREVIOUSYEAR('Calendar'[Date])) for the full prior year; "
            'PREVIOUSYEAR also accepts an M/D year-end, such as "6/30". '
            "Use CALCULATE(SUM([Amount]), PREVIOUSQUARTER('Calendar'[Date])) for the full previous calendar quarter. "
            "Use CALCULATE(SUM([Amount]), PREVIOUSMONTH('Calendar'[Date])) for the full previous calendar month. "
            "Use CALCULATE(SUM([Amount]), DATESYTD('Calendar'[Date])) for year-to-date dates; "
            'DATESYTD also accepts an M/D year-end, such as "6/30". '
            "Use CALCULATE(SUM([Amount]), DATESQTD('Calendar'[Date])) for quarter-to-date dates. "
            "Use CALCULATE(SUM([Amount]), DATESMTD('Calendar'[Date])) for month-to-date dates. "
            'Use CALCULATE(SUM([Amount]), DATESBETWEEN(\'Calendar\'[Date], '
            '"2024-01-01", "2024-01-31")); bounds can use BLANK(). '
            'Use CALCULATE(SUM([Amount]), DATESINPERIOD(\'Calendar\'[Date], '
            '"2024-06-30", -1, MONTH)) for a rolling period. '
            "Boolean CALCULATE filters support typed single-column comparisons, such as "
            'CALCULATE(SUM([Amount]), \'Sales\'[Color] = "Blue"). '
            "Multiple filter arguments combine with AND; they replace saved filters "
            "on the same columns and retain other filters. Wrap a predicate in "
            "KEEPFILTERS(...) to intersect it with the existing filter. Boolean "
            "comparisons coerce BLANK() to zero, FALSE(), empty text, or 1899-12-30 "
            "by the target column type. A nested Boolean filter preserves an outer "
            "time-intelligence date set when per-column filter provenance is available. "
            "Boolean and time-intelligence filters cannot yet appear together as arguments "
            "to one CALCULATE call; do not mix wrapped and unwrapped filters on the same column. "
            "REMOVEFILTERS accepts no arguments, one loaded table, or qualified columns from "
            "one table, for example CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Color])). "
            "ALL supports the same filter-modifier forms, for example "
            "CALCULATE(SUM([Amount]), ALL('Sales'[Color])). Both functions must be the "
            "only CALCULATE filter argument in this local subset. ALL table-returning "
            "forms work in COUNTROWS, SUMX, and AVERAGEX; table rows keep duplicates, "
            "while column lists return distinct values/tuples and preserve other filters. "
            "ALL includes a virtual blank relationship member when loaded regular "
            "relationship keys do not match; one-to-one mismatches can affect either "
            "side, and inactive relationships can also produce blank groupings. "
            "Residual filters on other columns can exclude that member. "
            "ALLNOBLANKROW accepts a table or same-table columns in this local subset; "
            "it excludes the virtual relationship-generated blank row and keeps physical "
            "blank rows/values. Its table results also work in COUNTROWS, SUMX, and AVERAGEX. "
            "As a CALCULATE modifier it must be the only filter argument; a nested ALL table "
            "expression or matching inner ALL modifier clears its exclusion context. "
            "ALLEXCEPT accepts one base table and one or more qualified columns from that "
            "table, for example ALLEXCEPT('Sales', 'Sales'[Region]); it keeps filters on "
            "those columns and clears the other direct filters on the table. It must also "
            "be the only CALCULATE filter argument and needs complete per-column filter context. "
            "ALLSELECTED accepts no arguments, one loaded table, or qualified columns from "
            "one table as the only CALCULATE filter argument. It also returns the currently "
            "visible rows or distinct selected column tuples in COUNTROWS, SUMX, and AVERAGEX. "
            "This report evaluator has no visual row/column query context, so its modifier "
            "preserves current report/page/visual selections; full visual totals are not modeled. "
            "USERELATIONSHIP takes two qualified columns from an existing saved relationship, "
            "for example CALCULATE(SUM([Amount]), USERELATIONSHIP('Sales'[ShipDate], 'Calendar'[Date])). "
            "It temporarily selects that link and overrides a competing active link between "
            "the same tables. Multiple selected links must connect different table pairs in "
            "one call; nested calculations restore their outer relationship context. "
            "This local subset does not combine USERELATIONSHIP with other filter argument types. "
            "CROSSFILTER takes two existing relationship columns and a bare direction token: "
            "None, Both, OneWay, OneWay_LeftFiltersRight, or OneWay_RightFiltersLeft. For example, "
            "CALCULATE(COUNTROWS('Category'), CROSSFILTER('Sales'[CategoryKey], 'Category'[Key], Both)) "
            "temporarily lets a Sales filter flow back to Category. It supports active links only "
            "and must be the only kind of filter argument in that CALCULATE. DAX restricts OneWay "
            "directions by relationship cardinality; this evaluator checks those restrictions. "
            "Clearing a column requires saved per-column filter provenance; table and global "
            "removal also clear opaque table-filter rowsets. "
            "DATEADD date-column selections must be contiguous and support YEAR, QUARTER, MONTH, "
            "or DAY. "
            "Arithmetic, parentheses, and "
            "references to other measures also work. Use [Column] for the active table or "
            "'Table Name'[Column] for a loaded table. "
            "The active Region filter follows active model relationships; COUNTROWS() counts "
            "the active table."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #526477;")
        self.help_scroll_area = QScrollArea()
        self.help_scroll_area.setObjectName("daxFunctionHelpScrollArea")
        self.help_scroll_area.setWidgetResizable(True)
        self.help_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.help_scroll_area.setMinimumHeight(76)
        self.help_scroll_area.setMaximumHeight(132)
        self.help_scroll_area.setWidget(help_label)
        layout.addWidget(self.help_scroll_area)
        catalog_label = QLabel(
            'This editor evaluates a partial local DAX subset. Microsoft documents '
            '<a href="https://learn.microsoft.com/en-us/dax/dax-function-reference">'
            '250+ DAX functions</a>; functions outside this picker are not evaluated here.'
        )
        catalog_label.setObjectName("daxFunctionCatalogBoundary")
        catalog_label.setWordWrap(True)
        catalog_label.setOpenExternalLinks(True)
        catalog_label.setStyleSheet("color: #526477;")
        layout.addWidget(catalog_label)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a4262c;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.save_button.setText("Save measure" if editing else "Create measure")
        self.buttons.accepted.connect(self._accept_measure)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.name_edit.textChanged.connect(self._refresh_error)
        self.expression_edit.textChanged.connect(self._refresh_error)
        self.description_edit.textChanged.connect(self._refresh_error)
        self.display_folder_edit.textChanged.connect(self._refresh_error)
        self._refresh_error()

    def _update_quick_name(self, column: str) -> None:
        if not self.quick:
            return
        prefixes = {
            "SUM": "Sum of",
            "AVERAGE": "Average of",
            "MIN": "Minimum of",
            "MAX": "Maximum of",
            "COUNT": "Count of",
            "COUNTA": "Count non-empty of",
            "DISTINCTCOUNT": "Distinct count of",
            "DISTINCTCOUNTNOBLANK": "Distinct count without blank of",
        }
        old_prefixes = tuple(prefix + " " for prefix in prefixes.values())
        current_name = self.name_edit.text()
        if any(current_name.startswith(prefix) for prefix in old_prefixes):
            function = str(self.function_combo.currentData())
            self.name_edit.setText(f"{prefixes.get(function, 'Measure of')} {column}")

    @staticmethod
    def _search_combo(placeholder: str) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setMaxVisibleItems(16)
        combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        combo.lineEdit().setPlaceholderText(placeholder)
        return combo

    def _insert_text(
        self,
        text: str,
        *,
        cursor_offset: int | None = None,
        selection: tuple[int, int] | None = None,
    ) -> None:
        cursor = self.expression_edit.textCursor()
        start = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        cursor.insertText(text)
        if selection is not None:
            cursor.setPosition(start + selection[0])
            cursor.setPosition(
                start + selection[0] + selection[1],
                QTextCursor.MoveMode.KeepAnchor,
            )
        elif cursor_offset is not None:
            cursor.setPosition(start + cursor_offset)
        self.expression_edit.setTextCursor(cursor)
        self.expression_edit.setFocus()

    def _insert_function(self) -> None:
        function = self.function_combo.currentText().strip().upper()
        if function not in DAX_FUNCTION_NAMES:
            self.preview_label.setText("Choose a function from the supported local list.")
            return
        insertion, selection_text = DAX_FUNCTION_TEMPLATES[function]
        if selection_text is not None:
            self._insert_text(
                insertion,
                selection=(insertion.index(selection_text), len(selection_text)),
            )
        else:
            self._insert_text(insertion, cursor_offset=insertion.index("(") + 1)

    def _update_function_signature(self, function: str) -> None:
        function = function.strip().upper()
        if function not in DAX_FUNCTION_TEMPLATES:
            self.function_signature_label.setText(
                "Choose a function from the recognized local list."
            )
            return
        template, _selection = DAX_FUNCTION_TEMPLATES[function]
        self.function_signature_label.setText(
            f"Local template: <code>{template}</code> · support is limited to the forms documented in this editor."
        )

    def _insert_reference(self, combo: QComboBox) -> None:
        reference = combo.currentData()
        if not isinstance(reference, str) or not reference:
            self.preview_label.setText("Choose a loaded field or saved measure first.")
            return
        self._insert_text(reference)

    def _insert_field_reference(self) -> None:
        self._insert_reference(self.field_combo)

    def _insert_measure_reference(self) -> None:
        self._insert_reference(self.measure_combo)

    def _preview_measure(self) -> None:
        if self._preview_callback is None:
            return
        try:
            measure = self._current_measure()
            value = self._preview_callback(measure["name"], measure["expression"])
        except (MeasureError, TypeError, ValueError) as exc:
            self.preview_label.setStyleSheet("color: #a4262c;")
            self.preview_label.setText(str(exc))
            return
        self.preview_label.setStyleSheet("color: #107c10;")
        self.preview_label.setText(f"Current report-context result: {value}")

    @property
    def measure(self) -> dict[str, Any] | None:
        return dict(self._accepted_measure) if self.result() == QDialog.DialogCode.Accepted and self._accepted_measure else None

    def _current_measure(self) -> dict[str, Any]:
        name = self.name_edit.text().strip()
        if self.quick:
            column = self.column_combo.currentText()
            if not column:
                raise MeasureError("Choose a column for the quick measure.")
            if "]" in column:
                raise MeasureError("Column names containing ']' are not supported in this DAX subset.")
            function = str(self.function_combo.currentData())
            expression = f"{function}([{column}])"
        else:
            expression = self.expression_edit.toPlainText()
        measure = normalize_measure(
            name,
            expression,
            description=self.description_edit.toPlainText(),
            display_folder=self.display_folder_edit.text(),
            is_hidden=self.hidden_checkbox.isChecked(),
        )
        if measure["name"].casefold() in self._existing_names:
            raise MeasureError(f"A measure named {measure['name']!r} already exists.")
        return measure

    def _refresh_error(self, *_args: object) -> None:
        if hasattr(self, "preview_label"):
            self.preview_label.clear()
            self.preview_label.setStyleSheet("color: #526477;")
        try:
            self._current_measure()
        except MeasureError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            self.save_button.setEnabled(False)
            return
        self.error_label.clear()
        self.error_label.setVisible(False)
        self.save_button.setEnabled(True)

    def _accept_measure(self) -> None:
        try:
            measure = self._current_measure()
        except MeasureError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            return
        self._accepted_measure = measure
        super().accept()

    def reject(self) -> None:
        self._accepted_measure = None
        super().reject()
