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

# M keywords are lowercase only, so the capitalised spellings are ordinary identifiers.
CAPITALISED_NON_KEYWORDS = ("Type", "Error", "Each", "Otherwise")


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
    def test_every_lowercase_m_keyword_is_rejected(self) -> None:
        for keyword in M_KEYWORDS:
            with self.subTest(keyword=keyword):
                with self.assertRaises(QueryParameterError):
                    normalize_query_parameter(
                        {"name": keyword, "type": "text", "current_value": "x"}
                    )

    def test_capitalised_spellings_are_accepted(self) -> None:
        for name in CAPITALISED_NON_KEYWORDS:
            with self.subTest(name=name):
                self.assertEqual(
                    normalize_query_parameter(
                        {"name": name, "type": "text", "current_value": "x"}
                    )["name"],
                    name,
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

    def test_lowercase_keyword_function_names_are_rejected(self) -> None:
        for keyword in M_KEYWORDS:
            with self.subTest(keyword=keyword):
                with self.assertRaises(QueryFunctionError):
                    validate_query_functions([_function_definition(name=keyword)])

    def test_lowercase_keyword_function_parameters_are_rejected(self) -> None:
        for keyword in M_KEYWORDS:
            with self.subTest(keyword=keyword):
                with self.assertRaises(QueryFunctionError):
                    validate_query_functions(
                        [_function_definition(parameter=keyword)]
                    )

    def test_capitalised_spellings_are_accepted_as_function_names(self) -> None:
        # "Each" and "Otherwise" are only keywords when lowercase.
        for name in ("Each", "Otherwise"):
            with self.subTest(name=name):
                functions = validate_query_functions([_function_definition(name=name)])
                self.assertEqual(functions[0]["name"], name)

    def test_capitalised_non_keywords_are_accepted_as_function_parameters(self) -> None:
        for parameter in ("Each", "Otherwise"):
            with self.subTest(parameter=parameter):
                functions = validate_query_functions(
                    [_function_definition(parameter=parameter)]
                )
                self.assertEqual(functions[0]["parameter"], parameter)

    def test_type_and_error_function_names_hit_the_namespace_rule_not_the_keyword_rule(
        self,
    ) -> None:
        # Pre-existing behaviour outside this task's brief: _M_NAMESPACE_ROOTS is matched
        # case-insensitively (query_functions.py), so a function or function-parameter named
        # "Type"/"Error" is refused as an M library namespace shadow before any keyword test.
        # _M_KEYWORDS therefore only ever sees lowercase "type"/"error" here.
        for name in ("Type", "Error"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(QueryFunctionError, "namespace"):
                    validate_query_functions([_function_definition(name=name)])


if __name__ == "__main__":
    unittest.main()
