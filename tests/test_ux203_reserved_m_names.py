"""Every M keyword is reserved in query parameter, function and function-parameter names."""

from __future__ import annotations

import unittest

from analytics_studio.query_functions import (
    QueryFunctionError,
    validate_query_functions,
)
from analytics_studio.query_parameters import (
    QueryParameterError,
    normalize_query_parameter,
)

M_KEYWORDS = (
    "and", "as", "each", "else", "error", "false", "if", "in", "is", "let",
    "meta", "not", "null", "or", "otherwise", "section", "shared", "then",
    "true", "try", "type",
)


def _function_definition(**changes: str) -> dict[str, str]:
    definition = {
        "name": "NormalizeName",
        "parameter": "Value",
        "parameter_type": "text",
        "return_type": "text",
        "expression": "Text.Upper(Text.Trim(Value))",
    }
    definition.update(changes)
    if changes.get("parameter"):
        definition["expression"] = f"Text.Upper({definition['parameter']})"
    return definition


class ReservedParameterNameTests(unittest.TestCase):
    def test_every_m_keyword_is_rejected(self) -> None:
        for keyword in M_KEYWORDS:
            with self.subTest(keyword=keyword):
                with self.assertRaises(QueryParameterError):
                    normalize_query_parameter(
                        {"name": keyword, "type": "text", "current_value": "x"}
                    )

    def test_non_keyword_names_are_accepted(self) -> None:
        for name in ("Region", "eachValue"):
            with self.subTest(name=name):
                self.assertEqual(
                    normalize_query_parameter(
                        {"name": name, "type": "text", "current_value": "x"}
                    )["name"],
                    name,
                )


class ReservedFunctionNameTests(unittest.TestCase):
    def test_valid_function_still_passes(self) -> None:
        functions = validate_query_functions([_function_definition()])
        self.assertEqual(functions[0]["name"], "NormalizeName")

    def test_function_name_each_is_rejected(self) -> None:
        with self.assertRaises(QueryFunctionError):
            validate_query_functions([_function_definition(name="each")])

    def test_parameter_name_otherwise_is_rejected(self) -> None:
        with self.assertRaises(QueryFunctionError):
            validate_query_functions([_function_definition(parameter="otherwise")])


if __name__ == "__main__":
    unittest.main()
