"""Critic (minor): names containing ']' are offered, escaped as ']]' like DAX."""

from __future__ import annotations

import unittest

from analytics_studio.dax_intellisense import apply_completion, complete, complete_formula

MODEL = {
    "home_table": "Sales",
    "tables": [
        {"name": "Sales", "columns": [
            {"name": "Net [USD]", "type": "number"},
            {"name": "Qty]", "type": "number"},
            {"name": "Region", "type": "text"},
        ]},
    ],
    "measures": [{"name": "Margin]", "table": "Sales", "type": "number"}],
}


def item_for(items: list[dict], label: str) -> dict:
    return next(item for item in items if item["label"] == label)


class BracketNameTests(unittest.TestCase):
    def test_table_qualified_column_with_a_bracket_is_offered_and_escaped(self) -> None:
        text = "Sales[Net"
        items = complete(text, len(text), MODEL)
        item = item_for(items, "Net [USD]")
        self.assertEqual(item["insertText"], "Net [USD]]]")  # name 'Net [USD]' + closing bracket
        new_text, caret = apply_completion(text, item)
        self.assertEqual(new_text, "Sales[Net [USD]]]")
        self.assertEqual(caret, len(new_text))

    def test_column_whose_name_ends_with_a_bracket(self) -> None:
        text = "SUM(Sales[Q)"
        items = complete(text, len("SUM(Sales[Q"), MODEL)
        item = item_for(items, "Qty]")
        new_text, _caret = apply_completion(text, item)
        self.assertEqual(new_text, "SUM(Sales[Qty]]])")  # name 'Qty]' escaped, then the closer

    def test_an_existing_closing_bracket_is_stepped_over(self) -> None:
        text = "Sales[Q]"  # caret before the closer that is already there
        items = complete(text, len("Sales[Q"), MODEL)
        new_text, caret = apply_completion(text, item_for(items, "Qty]"))
        self.assertEqual(new_text, "Sales[Qty]]]")  # name 'Qty]' escaped + the existing closer
        self.assertEqual(caret, len(new_text))

    def test_typing_the_escaped_form_filters_to_the_same_name(self) -> None:
        text = "Sales[Net [USD]]"
        items = complete(text, len(text), MODEL)
        self.assertIn("Net [USD]", [item["label"] for item in items])

    def test_bare_bracket_offers_home_columns_and_measures_with_brackets(self) -> None:
        items = complete("[", 1, MODEL)
        labels = [item["label"] for item in items]
        self.assertIn("Net [USD]", labels)
        self.assertIn("Margin]", labels)
        self.assertEqual(item_for(items, "Margin]")["insertText"], "Margin]]]")

    def test_measure_in_identifier_position_is_offered_escaped(self) -> None:
        items = complete("Mar", 3, MODEL)
        self.assertEqual(item_for(items, "Margin]")["insertText"], "[Margin]]]")

    def test_formula_text_round_trip(self) -> None:
        text = "Total = SUM(Sales[Net"
        items = complete_formula(text, len(text), MODEL)
        self.assertIn("Net [USD]", [item["label"] for item in items])

    def test_plain_names_are_unchanged(self) -> None:
        text = "Sales[Reg"
        item = item_for(complete(text, len(text), MODEL), "Region")
        self.assertEqual(item["insertText"], "Region]")
        self.assertEqual(apply_completion(text, item)[0], "Sales[Region]")


if __name__ == "__main__":
    unittest.main()
