"""Native editors for local DAX measures and common quick aggregations."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from analytics_studio.measures import MeasureError, normalize_measure


class MeasureDialog(QDialog):
    """Collect one measure definition; computation is performed by the controller."""

    def __init__(
        self,
        headers: list[str],
        existing_names: list[str],
        *,
        quick: bool = False,
        default_column: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.quick = quick
        self._existing_names = {name.casefold() for name in existing_names}
        self._accepted_measure: dict[str, str] | None = None
        self.setWindowTitle("Quick measure" if quick else "New measure")
        self.setMinimumWidth(520)
        self.resize(600, 380 if quick else 430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        title = QLabel("Create a local DAX measure")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #273b49;")
        layout.addWidget(title)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(120)
        form.addRow("Measure name", self.name_edit)
        self.expression_edit = QPlainTextEdit()
        self.expression_edit.setPlaceholderText("SUM([Sales]) / COUNTROWS()")
        self.expression_edit.setMaximumHeight(110)
        self.expression_edit.setVisible(not quick)
        if quick:
            self.function_combo = QComboBox()
            for label, function in (
                ("Sum", "SUM"), ("Average", "AVERAGE"), ("Minimum", "MIN"),
                ("Maximum", "MAX"), ("Count numbers", "COUNT"),
                ("Count non-empty", "COUNTA"), ("Distinct count", "DISTINCTCOUNT"),
            ):
                self.function_combo.addItem(label, function)
            self.column_combo = QComboBox()
            self.column_combo.addItems(headers)
            if default_column in headers:
                self.column_combo.setCurrentText(default_column)
            form.addRow("Calculation", self.function_combo)
            form.addRow("Column", self.column_combo)
            self.function_combo.currentIndexChanged.connect(self._refresh_error)
            self.column_combo.currentIndexChanged.connect(self._refresh_error)
            if headers:
                self.name_edit.setText(f"Sum of {self.column_combo.currentText()}")
            self.column_combo.currentTextChanged.connect(self._update_quick_name)
        else:
            form.addRow("DAX expression", self.expression_edit)
        layout.addLayout(form)

        help_label = QLabel(
            "Supported functions: SUM, AVERAGE, MIN, MAX, COUNT, COUNTA, DISTINCTCOUNT, "
            "COUNTROWS, DIVIDE, ABS, ROUND, IF, AND, OR, NOT, SUMX, AVERAGEX, TOTALYTD, "
            "TOTALQTD, TOTALMTD, DATEADD, SAMEPERIODLASTYEAR, DATESYTD, DATESQTD, "
            "DATESMTD, DATESBETWEEN, DATESINPERIOD, PREVIOUSYEAR, PREVIOUSQUARTER, PREVIOUSMONTH, "
            "and the filter modifiers REMOVEFILTERS, ALL, ALLNOBLANKROW, ALLEXCEPT, "
            "ALLSELECTED, USERELATIONSHIP, and CROSSFILTER. "
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
        layout.addWidget(help_label)

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
        self.save_button.setText("Create measure")
        self.buttons.accepted.connect(self._accept_measure)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.name_edit.textChanged.connect(self._refresh_error)
        self.expression_edit.textChanged.connect(self._refresh_error)
        self._refresh_error()

    def _update_quick_name(self, column: str) -> None:
        if self.quick and self.name_edit.text().startswith("Sum of "):
            self.name_edit.setText(f"Sum of {column}")

    @property
    def measure(self) -> dict[str, str] | None:
        return dict(self._accepted_measure) if self.result() == QDialog.DialogCode.Accepted and self._accepted_measure else None

    def _current_measure(self) -> dict[str, str]:
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
        measure = normalize_measure(name, expression)
        if measure["name"].casefold() in self._existing_names:
            raise MeasureError(f"A measure named {measure['name']!r} already exists.")
        return measure

    def _refresh_error(self, *_args: object) -> None:
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
