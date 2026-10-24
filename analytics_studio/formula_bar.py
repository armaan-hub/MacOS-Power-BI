"""The Power BI style formula bar: one draft measure or calculated column at a time.

``New measure`` and ``New column`` open a draft named ``Measure = `` / ``Column = ``.  The draft
only reaches the model on commit (Enter or the check mark) and every commit goes through the
same engine paths the old dialogs used (``create_measure`` / ``update_measure`` and the
calculated-column planner), so a formula the engine rejects is never accepted: the engine's own
error text goes into ``error`` and the bar stays open.  ``validate`` performs the same dry run
without touching the model, which the QML editor calls (debounced) while the user types.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from analytics_studio import dax_intellisense
from analytics_studio.measures import MeasureError

if TYPE_CHECKING:  # pragma: no cover
    from analytics_studio.controller import StudioController

FORMULA_HELP = (
    "Write the formula as Name = expression, for example Measure = SUM(Table[Column])."
)


class FormulaBarController(QObject):
    changed = Signal()
    revisionChanged = Signal()  # the text was replaced from Python: the editor must reload it
    committed = Signal(str, str)  # kind ("measure" | "column"), name

    def __init__(self, studio: "StudioController") -> None:
        super().__init__(studio)
        self._studio = studio
        self._active = False
        self._mode = ""
        self._is_new = True
        self._text = ""
        self._initial_text = ""
        self._original_name = ""
        self._error = ""
        self._selection = (0, 0)
        self._revision = 0
        self._home_table_id = ""
        self._last_binding = ""
        self._focus_requested = True
        studio.stateChanged.connect(self.changed)

    # ------------------------------------------------------------------ properties

    @Property(bool, notify=changed)
    def active(self) -> bool:
        return self._active

    @Property(str, notify=changed)
    def mode(self) -> str:
        return self._mode

    @Property(bool, notify=changed)
    def isNew(self) -> bool:  # noqa: N802
        return self._is_new

    @Property(str, notify=changed)
    def text(self) -> str:
        return self._text

    @Property(bool, notify=changed)
    def dirty(self) -> bool:
        return self._active and self._text != self._initial_text

    @Property(str, notify=changed)
    def error(self) -> str:
        return self._error

    @Property(str, notify=changed)
    def name(self) -> str:
        parts = dax_intellisense.split_formula(self._text)
        return parts[0] if parts else ""

    @Property(str, notify=changed)
    def originalName(self) -> str:  # noqa: N802
        return self._original_name

    @Property(int, notify=changed)
    def selectionStart(self) -> int:  # noqa: N802
        return self._selection[0]

    @Property(int, notify=changed)
    def selectionEnd(self) -> int:  # noqa: N802
        return self._selection[1]

    @Property(int, notify=revisionChanged)
    def textRevision(self) -> int:  # noqa: N802
        """Bumped whenever the text was replaced from Python so the editor reloads it."""
        return self._revision

    @Property(bool, notify=changed)
    def focusRequested(self) -> bool:  # noqa: N802
        """False when the formula was only shown for the selected field (the editor keeps no focus)."""
        return self._focus_requested

    @Property(str, notify=changed)
    def activeTableName(self) -> str:  # noqa: N802
        return self._studio._active_model_table_name() if self._studio.sourceLoaded else ""

    @Property(str, notify=changed)
    def lastBinding(self) -> str:  # noqa: N802
        return self._last_binding

    @Property(str, notify=changed)
    def homeTableId(self) -> str:  # noqa: N802
        return self._home_table_id

    @Property(str, notify=changed)
    def tableName(self) -> str:  # noqa: N802
        table = self._table_for_id(self._home_table_id)
        if table is not None:
            return str(table.get("name", ""))
        return self._studio._active_model_table_name() if self._active else ""

    # ------------------------------------------------------------------ helpers

    def _table_for_id(self, table_id: str) -> dict[str, Any] | None:
        return next((
            table for table in self._studio._table_catalog
            if str(table.get("id", "")) == str(table_id or "")
        ), None)

    def _open(self, mode: str, text: str, *, is_new: bool, original: str,
              selection: tuple[int, int], home_table_id: str, focus: bool = True) -> None:
        self._focus_requested = focus
        self._active = True
        self._mode = mode
        self._is_new = is_new
        self._text = text
        self._initial_text = text
        self._original_name = original
        self._error = ""
        self._selection = selection
        self._home_table_id = home_table_id
        self._revision += 1
        self.revisionChanged.emit()
        self.changed.emit()

    @Slot(result=bool)
    def confirmDiscardDraft(self) -> bool:  # noqa: N802
        """True when it is safe to replace the bar: it is clean, or the user saved / discarded it.

        A dirty draft is never dropped silently (Power BI asks too): Save commits it (a draft the
        engine rejects stays open with its error), Discard drops it, Cancel keeps it.
        """
        if not self.dirty:
            return True
        what = "column" if self._mode == "column" else "measure"
        answer = QMessageBox.question(
            None,
            "Unsaved formula",
            f"The {what} formula in the formula bar has not been saved. Save it before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.commit()
        if answer == QMessageBox.StandardButton.Discard:
            self._close()
            return True
        self._studio._set_status("Finish or discard the formula in the formula bar first.")
        return False

    def reset(self) -> None:
        """Drop the draft without asking (the project it belonged to is gone)."""
        if self._active or self._text:
            self._close()

    def _close(self) -> None:
        self._active = False
        self._mode = ""
        self._text = ""
        self._initial_text = ""
        self._original_name = ""
        self._error = ""
        self._selection = (0, 0)
        self._revision += 1
        self.revisionChanged.emit()
        self.changed.emit()

    def _unique_name(self, base: str, taken: list[str]) -> str:
        used = {item.casefold() for item in taken}
        if base.casefold() not in used:
            return base
        number = 2
        while f"{base} {number}".casefold() in used:
            number += 1
        return f"{base} {number}"

    def _measure_names(self) -> list[str]:
        return [str(item["name"]) for item in self._studio._project.get("model", {}).get("measures", [])]

    def _column_names(self) -> list[str]:
        return [str(item) for item in self._studio._headers]

    def _split(self) -> tuple[str, str] | None:
        parts = dax_intellisense.split_formula(self._text)
        if parts is None:
            return None
        return parts[0], self._text[parts[1]:]

    def _may_replace(self, focus: bool) -> bool:
        """A preview (shown for the selected field) never touches a dirty draft; a real edit asks."""
        if not focus:
            return not self.dirty
        return self.confirmDiscardDraft()

    # ------------------------------------------------------------------ opening

    @Slot(result=bool)
    def beginNewMeasure(self) -> bool:  # noqa: N802
        studio = self._studio
        if not studio.sourceLoaded:
            studio._set_status("Import a table before creating a measure.")
            return False
        if not self.confirmDiscardDraft():
            return False
        name = self._unique_name("Measure", self._measure_names())
        self._open("measure", f"{name} = ", is_new=True, original="",
                   selection=(0, len(name)), home_table_id=studio._active_model_table_id())
        return True

    @Slot(result=bool)
    def beginNewColumn(self) -> bool:  # noqa: N802
        studio = self._studio
        if not studio.sourceLoaded:
            studio._set_status("Load a table before creating a calculated column.")
            return False
        if not self.confirmDiscardDraft():
            return False
        name = self._unique_name("Column", self._column_names())
        self._open("column", f"{name} = ", is_new=True, original="",
                   selection=(0, len(name)), home_table_id=studio._active_model_table_id())
        return True

    @Slot(str, result=bool)
    def previewMeasure(self, measure_name: str) -> bool:  # noqa: N802
        """Show a selected measure's formula without taking keyboard focus."""
        return self.beginEditMeasure(measure_name, focus=False)

    @Slot(str, result=bool)
    def previewColumn(self, column_name: str) -> bool:  # noqa: N802
        return self.beginEditColumn(column_name, focus=False)

    @Slot(str, result=bool)
    def isCalculatedColumn(self, column_name: str) -> bool:  # noqa: N802
        studio = self._studio
        table = studio._model_table_for_source(studio._project, studio._active_source_id or "")
        return any(
            str(item.get("name", "")).casefold() == str(column_name).casefold()
            for item in (table or {}).get("calculated_columns", [])
        )

    @Slot(str, result=bool)
    def beginEditMeasure(self, measure_name: str, focus: bool = True) -> bool:  # noqa: N802
        studio = self._studio
        measure = next((
            item for item in studio._project.get("model", {}).get("measures", [])
            if str(item.get("name", "")).casefold() == str(measure_name).casefold()
        ), None)
        if measure is None:
            studio._set_status(f"Measure {measure_name!r} no longer exists.")
            return False
        if not self._may_replace(focus):
            return False
        name = str(measure["name"])
        text = f"{name} = {measure['expression']}"
        self._open("measure", text, is_new=False, original=name,
                   selection=(len(text), len(text)), focus=focus,
                   home_table_id=str(measure.get("home_table_id") or studio._active_model_table_id()))
        return True

    @Slot(str, result=bool)
    def beginEditColumn(self, column_name: str, focus: bool = True) -> bool:  # noqa: N802
        studio = self._studio
        table = studio._model_table_for_source(studio._project, studio._active_source_id or "")
        column = next((
            item for item in (table or {}).get("calculated_columns", [])
            if str(item.get("name", "")).casefold() == str(column_name).casefold()
        ), None)
        if column is None:
            return False
        if not self._may_replace(focus):
            return False
        text = f"{column['name']} = {column['expression']}"
        self._open("column", text, is_new=False, original=str(column["name"]),
                   selection=(len(text), len(text)), home_table_id=studio._active_model_table_id(),
                   focus=focus)
        return True

    # ------------------------------------------------------------------ editing

    @Slot(str)
    def setText(self, text: str) -> None:  # noqa: N802
        """The editor reports what the user typed (does not reload the editor)."""
        if text == self._text:
            return
        self._text = text
        if self._error:
            self._error = ""
        self.changed.emit()

    @Slot(str)
    def setName(self, name: str) -> None:  # noqa: N802
        """Rewrite only the name part of the formula (the ribbon's Name box)."""
        if not self._active:
            return
        parts = dax_intellisense.formula_parts(self._text)
        new_name = str(name).strip() or (parts[0] if parts else "")
        if "=" in new_name:
            self._error = "A name cannot contain an equals sign."
            self.changed.emit()
            return
        self._text = (
            f"{new_name} {self._text[parts[1]:]}" if parts else f"{new_name} = "
        )
        self._error = ""
        self._revision += 1
        self.revisionChanged.emit()
        self.changed.emit()

    @Slot(str)
    def setHomeTable(self, table_id: str) -> None:  # noqa: N802
        """Move the measure to another table; a saved, unedited measure moves immediately."""
        if not self._active or self._mode != "measure" or self._table_for_id(table_id) is None:
            return
        if not self._is_new and not self.dirty and self._original_name:
            studio = self._studio
            current = next((
                item for item in studio._project.get("model", {}).get("measures", [])
                if str(item.get("name", "")) == self._original_name
            ), None)
            if current is not None and studio.update_measure(
                self._original_name, self._original_name, str(current["expression"]),
                home_table_id=table_id,
            ):
                self._home_table_id = str(table_id)
                self.changed.emit()
            return
        self._home_table_id = str(table_id)
        self.changed.emit()

    @Slot()
    def cancel(self) -> None:
        """Escape and the X button: a clean bar closes, a dirty draft asks Save / Discard / Cancel first (never dropped silently)."""
        if not self._active:
            return
        if self.dirty:
            self.confirmDiscardDraft()
            return
        self._close()

    # ------------------------------------------------------------------ validation / commit

    def _check(self, *, strict: bool) -> tuple[str, str, str]:
        """Return ``(name, expression, error)``; the model is never changed."""
        parts = self._split()
        if parts is None:
            return "", "", FORMULA_HELP
        name, expression = parts
        if not expression.strip():
            return name, expression, (
                "Enter a DAX expression after the equals sign." if strict else ""
            )
        if self._mode == "column":
            error = self._studio.validate_calculated_column(
                name, expression.strip(), self._original_name)
            return name, expression, error
        try:
            self._studio._preview_measure_expression(
                name, expression.strip(),
                editing_name=self._original_name or None,
                home_table_id=self._home_table_id or None,
            )
        except (MeasureError, ValueError, TypeError, KeyError) as exc:
            return name, expression, str(exc)
        return name, expression, ""

    @Slot(result=str)
    def validate(self) -> str:
        """Dry-run the current text (live validation); sets and returns the error text."""
        if not self._active:
            return ""
        _name, _expression, error = self._check(strict=False)
        if error != self._error:
            self._error = error
            self.changed.emit()
        return error

    @Slot(result=bool)
    def commit(self) -> bool:
        if not self._active:
            return False
        name, expression, error = self._check(strict=True)
        if not error:
            error = self._save(name, expression.strip())
        if error:
            self._error = error
            self.changed.emit()
            return False
        kind = self._mode
        self._last_binding = self._binding_for(kind, name)
        self._close()
        self.committed.emit(kind, name)
        return True

    def _save(self, name: str, expression: str) -> str:
        studio = self._studio
        if self._mode == "column":
            return studio.save_calculated_column(name, expression, self._original_name)
        home = self._home_table_id or None
        if self._is_new:
            ok = studio.create_measure(name, expression, home_table_id=home)
        else:
            ok = studio.update_measure(
                self._original_name, name, expression, home_table_id=home)
        return "" if ok else (studio.statusMessage or "The measure could not be saved.")

    @staticmethod
    def _binding_for(kind: str, name: str) -> str:
        if kind == "measure":
            from analytics_studio.controller import _visual_measure_binding
            return _visual_measure_binding(name)
        return name

    # ------------------------------------------------------------------ IntelliSense

    def intellisense_model(self) -> dict[str, Any]:
        studio = self._studio
        tables = []
        names_by_id: dict[str, str] = {}
        for table in studio._table_catalog:
            if not (table.get("loaded") and table.get("loadEnabled")):
                continue
            name = str(table.get("name", ""))
            if not name:
                continue
            names_by_id[str(table.get("id", ""))] = name
            types = table.get("columnTypes", {}) or {}
            tables.append({
                "name": name,
                "columns": [
                    {"name": str(column), "type": str(types.get(column, "text"))}
                    for column in table.get("headers", [])
                ],
            })
        measures = [
            {"name": str(item["name"]), "type": "",
             "table": names_by_id.get(str(item.get("home_table_id") or ""), "")}
            for item in studio._project.get("model", {}).get("measures", [])
        ]
        home = names_by_id.get(self._home_table_id) or studio._active_model_table_name()
        return {"home_table": home, "tables": tables, "measures": measures}

    @Slot(str, int, bool, result="QVariantList")
    def completions(self, text: str, caret: int, invoked: bool) -> list[dict[str, Any]]:
        return dax_intellisense.complete_formula(
            text, caret, self.intellisense_model(), invoked=bool(invoked))

    @Slot(str, int, result="QVariantMap")
    def signature(self, text: str, caret: int) -> dict[str, Any]:
        hint = dax_intellisense.signature_help_formula(text, caret, None)
        return hint or {}

    @Slot(str, "QVariantMap", result="QVariantMap")
    def applyCompletion(self, text: str, item: dict[str, Any]) -> dict[str, Any]:  # noqa: N802
        """Insert an accepted completion; unsupported functions are refused with a message."""
        result = dax_intellisense.apply_completion(text, dict(item))
        if result is None:
            label = str(item.get("label", "This function"))
            return {
                "text": text,
                "caret": int(item.get("replaceEnd", len(text))),
                "message": f"{label} is not supported by this app yet.",
            }
        return {"text": result[0], "caret": result[1], "message": ""}
