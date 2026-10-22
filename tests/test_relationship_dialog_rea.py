"""UI workflow checks for the REA-guided relationship dialog changes."""

from __future__ import annotations

import os
import unittest
from copy import deepcopy
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QMessageBox

from analytics_studio.relationship_dialog import RelationshipDialog


def make_relationship(
    index: int,
    *,
    from_column: str,
    cardinality: str = "many_to_one",
    direction: str = "single",
    active: bool = True,
) -> dict:
    return {
        "relationship_version": 1,
        "id": f"relationship-{index}",
        "from": f"A[{from_column}]",
        "to": f"B[Key{index}]",
        "from_table_id": "a",
        "from_column": from_column,
        "to_table_id": "b",
        "to_column": f"Key{index}",
        "cardinality": cardinality,
        "cross_filter_direction": direction,
        "is_active": active,
    }


class RelationshipDialogReaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Relationship dialog tests"])

    def setUp(self) -> None:
        self.tables = [
            {
                "id": table_id,
                "name": name,
                "displayName": name,
                "headers": ["Key", "Other"],
                "loaded": True,
                "loadEnabled": True,
            }
            for table_id, name in (("a", "Alpha"), ("b", "Beta"), ("c", "Gamma"))
        ]

    def make_dialog(self, relationships=None, detect_candidates=None):
        return RelationshipDialog(
            self.tables,
            relationships or [],
            lambda candidate: candidate,
            detect_candidates=detect_candidates,
        )

    def visible_indexes(self, dialog: RelationshipDialog) -> list[int]:
        return [
            int(dialog.relationship_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(dialog.relationship_list.count())
            if not dialog.relationship_list.item(row).isHidden()
        ]

    def test_global_autodetect_is_reviewable_and_stays_staged_until_save(self) -> None:
        original = [make_relationship(0, from_column="Existing")]
        suggestion = make_relationship(1, from_column="Suggested")
        calls: list[tuple] = []

        def detect(current, target_tables=None):
            calls.append((current, target_tables))
            return [suggestion]

        dialog = self.make_dialog(original, detect)
        with patch("analytics_studio.relationship_dialog.QMessageBox.information") as message:
            dialog._autodetect_relationships()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], original)
        self.assertIsNone(calls[0][1])
        self.assertEqual(len(message.call_args.args), 3)
        self.assertIn("1 proposed relationship", message.call_args.args[2])
        self.assertEqual(len(dialog._relationships), 2)
        self.assertEqual(dialog.relationships, [])
        self.assertIn("select Save", dialog.status_label.text())

        dialog.accept()
        self.assertEqual(dialog.relationships, [*original, suggestion])
        dialog.deleteLater()

    def test_scope_picker_requires_two_tables_and_passes_selected_table_ids(self) -> None:
        seen: list[set[str] | None] = []
        dialog = self.make_dialog(
            detect_candidates=lambda _current, target_tables=None: (
                seen.append(target_tables) or []
            )
        )

        def choose_two_tables(scope_dialog: QDialog) -> QDialog.DialogCode:
            table_list = scope_dialog.findChild(QListWidget)
            self.assertIsNotNone(table_list)
            self.assertEqual(table_list.count(), 3)
            table_list.item(0).setCheckState(Qt.CheckState.Checked)
            table_list.item(2).setCheckState(Qt.CheckState.Checked)
            return QDialog.DialogCode.Accepted

        with (
            patch.object(QDialog, "exec", new=lambda scope_dialog: choose_two_tables(scope_dialog)),
            patch("analytics_studio.relationship_dialog.QMessageBox.information"),
        ):
            dialog._choose_autodetect_scope()

        self.assertEqual(seen, [{"a", "c"}])
        self.assertIn("selected tables", dialog.status_label.text())
        dialog.deleteLater()

    def test_list_sorting_and_filters_match_rea_without_reordering_saved_items(self) -> None:
        relationships = [
            make_relationship(0, from_column="Zulu", cardinality="many_to_one", direction="single", active=True),
            make_relationship(1, from_column="alpha", cardinality="one_to_one", direction="both", active=False),
            make_relationship(2, from_column="Bravo", cardinality="many_to_one", direction="both", active=False),
            make_relationship(3, from_column="Charlie", cardinality="one_to_many", direction="single", active=True),
        ]
        original = deepcopy(relationships)
        dialog = self.make_dialog(relationships)

        self.assertEqual(self.visible_indexes(dialog), [1, 2, 3, 0])
        dialog._sort_field_actions["active"].trigger()
        self.assertEqual(self.visible_indexes(dialog), [1, 2, 0, 3])

        dialog._cardinality_filter_actions["many_to_one"].setChecked(True)
        dialog._cardinality_filter_actions["one_to_one"].setChecked(True)
        dialog._direction_filter_actions["single"].setChecked(True)
        self.assertEqual(self.visible_indexes(dialog), [0])
        self.assertEqual(dialog.filter_button.text(), "Filter (2)")

        dialog._clear_relationship_filters()
        self.assertEqual(len(self.visible_indexes(dialog)), 4)
        self.assertEqual(relationships, original)
        self.assertEqual(dialog._relationships, original)
        dialog.deleteLater()

    def test_batch_delete_confirms_once_and_remains_staged_until_save(self) -> None:
        relationships = [
            make_relationship(index, from_column=f"Column{index}")
            for index in range(3)
        ]
        dialog = self.make_dialog(relationships)
        dialog.relationship_list.item(0).setSelected(True)
        dialog.relationship_list.item(1).setSelected(True)

        with patch(
            "analytics_studio.relationship_dialog.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ) as confirmation:
            dialog._confirm_delete_selected()

        self.assertEqual(len(confirmation.call_args.args), 5)
        self.assertEqual(confirmation.call_args.args[1], "Delete relationships")
        self.assertIn("2 selected relationships", confirmation.call_args.args[2])
        self.assertIn("select Save", confirmation.call_args.args[2])
        self.assertEqual(len(dialog._relationships), 1)
        self.assertEqual(relationships, [make_relationship(i, from_column=f"Column{i}") for i in range(3)])
        self.assertEqual(dialog.relationships, [])
        dialog.accept()
        self.assertEqual(dialog.relationships, [relationships[2]])
        dialog.deleteLater()

    def test_no_suggestions_shows_feedback_without_modifying_dialog_state(self) -> None:
        relationships = [make_relationship(0, from_column="Existing")]
        dialog = self.make_dialog(relationships, detect_candidates=lambda *_args: [])

        with patch("analytics_studio.relationship_dialog.QMessageBox.information") as message:
            dialog._autodetect_relationships()

        self.assertEqual(len(dialog._relationships), 1)
        self.assertIn("No additional relationships", message.call_args.args[2])
        self.assertIn("No additional relationships", dialog.status_label.text())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
