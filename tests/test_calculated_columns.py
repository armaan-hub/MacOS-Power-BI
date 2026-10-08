"""Checks for the supported row-scoped calculated-column DAX subset."""

from __future__ import annotations

from analytics_studio.measures import (
    MeasureError,
    evaluate_calculated_columns,
    validate_calculated_columns,
)


def test_calculated_columns_evaluate_numeric_boolean_and_prior_column_references() -> None:
    headers, rows, types = evaluate_calculated_columns(
        [
            {"name": "Line total", "expression": "[Quantity] * [Unit price]"},
            {
                "name": "Large order",
                "expression": "IF([Line total] >= 20, TRUE(), FALSE())",
            },
            {"name": "Rounded", "expression": "ROUND([Line total], 1)"},
        ],
        [
            {"Quantity": "2", "Unit price": "12.25"},
            {"Quantity": "3", "Unit price": "8"},
            {"Quantity": "", "Unit price": "9"},
        ],
        ["Quantity", "Unit price"],
        "Orders",
    )

    assert headers == ["Quantity", "Unit price", "Line total", "Large order", "Rounded"]
    assert rows == [
        {
            "Quantity": "2", "Unit price": "12.25", "Line total": "24.50",
            "Large order": "True", "Rounded": "24.5",
        },
        {
            "Quantity": "3", "Unit price": "8", "Line total": "24",
            "Large order": "True", "Rounded": "24.0",
        },
        {
            "Quantity": "", "Unit price": "9", "Line total": "0",
            "Large order": "False", "Rounded": "0.0",
        },
    ]
    assert types == {
        "Line total": "decimal_number",
        "Large order": "boolean",
        "Rounded": "decimal_number",
    }


def test_calculated_columns_preserve_blank_direct_values_and_allow_same_table_qualification() -> None:
    headers, rows, types = evaluate_calculated_columns(
        [{"name": "Copy amount", "expression": "'Orders'[Amount]"}],
        [{"Amount": "5"}, {"Amount": ""}],
        ["Amount"],
        "Orders",
    )

    assert headers == ["Amount", "Copy amount"]
    assert [row["Copy amount"] for row in rows] == ["5", ""]
    assert types == {"Copy amount": "decimal_number"}


def test_calculated_columns_reject_unsupported_context_types_and_bad_shapes() -> None:
    for expression, rows, headers in (
        ("SUM([Amount])", [{"Amount": "2"}], ["Amount"]),
        ("'Other'[Amount]", [{"Amount": "2"}], ["Amount"]),
        ("[Label] + 1", [{"Label": "north"}], ["Label"]),
        ("1 / [Divisor]", [{"Divisor": "0"}], ["Divisor"]),
        (
            "IF([Amount] > 0, TRUE, 1)",
            [{"Amount": "2"}, {"Amount": "-1"}],
            ["Amount"],
        ),
    ):
        try:
            evaluate_calculated_columns(
                [{"name": "Invalid", "expression": expression}],
                rows,
                headers,
                "Orders",
            )
        except MeasureError:
            continue
        raise AssertionError(f"Expected calculated-column validation to reject {expression!r}")

    for definitions in (
        [{"name": "A", "expression": "1"}, {"name": "a", "expression": "2"}],
        [{"name": "A", "expression": "1", "type": "decimal_number"}],
    ):
        try:
            validate_calculated_columns(definitions)
        except MeasureError:
            continue
        raise AssertionError(f"Expected calculated-column definitions to reject {definitions!r}")
