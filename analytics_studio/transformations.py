"""Replayable, local transformations for bounded imported tables.

Each step is a JSON-safe object with an ``op`` discriminator. Steps are applied
in list order to a copy of an :class:`ImportCandidate`; source files and the
supplied candidate are never changed.

Supported shapes::

    {"op": "rename_column", "column": "Old", "new_name": "New"}
    {"op": "remove_column", "column": "Old"}
    {"op": "filter_rows", "column": "Amount", "operator": "greater_than", "value": "10"}
    {"op": "filter_rows_advanced", "clauses": [
        {"column": "Region", "operator": "equals", "value": "West", "join": "and"},
        {"column": "Year", "operator": "greater_than_or_equal", "value": "2024", "join": "or"}
    ]}
    {"op": "sort_rows", "column": "Amount", "direction": "asc"}
    {"op": "sort_rows_by_columns", "sorts": [
        {"column": "Region", "direction": "asc"},
        {"column": "Revenue", "direction": "desc"}
    ]}
    {"op": "convert_type", "column": "Amount", "type": "number"}
    {"op": "convert_type_using_locale", "column": "Amount",
        "type": "decimal_number", "culture": "de-DE"}
    {"op": "replace_value", "column": "Status", "value": "Open", "replacement": "Closed"}
    {"op": "extract_text_by_delimiter", "column": "Email", "side": "before",
        "delimiter": "@", "occurrence": 0}
    {"op": "extract_text_between_delimiters", "column": "Code",
        "start_delimiter": "[", "end_delimiter": "]",
        "start_occurrence": 0, "end_occurrence": 0}
    {"op": "split_column", "column": "Account", "delimiter": " "}
    {"op": "split_column_by_each_delimiter", "column": "Tags", "delimiter": ","}
    {"op": "split_column_to_rows", "column": "Accounts", "delimiter": ";"}
    {"op": "split_column_by_positions", "column": "Code", "positions": [0, 4, 9]}
    {"op": "merge_columns", "columns": ["First", "Last"],
        "separator": " ", "new_name": "Full name"}
    {"op": "fill_down", "columns": ["Region", "Category"]}
    {"op": "fill_up", "columns": ["Region", "Category"]}
    {"op": "duplicate_column", "column": "Revenue", "new_name": "Revenue copy"}
    {"op": "group_by", "columns": ["Region"], "aggregations": [
        {"operation": "sum", "column": "Revenue", "new_name": "Total revenue"}
    ]}
    {"op": "unpivot_columns", "columns": ["2024", "2025"],
        "attribute_name": "Attribute", "value_name": "Value"}
    {"op": "unpivot_other_columns", "columns": ["Region"],
        "attribute_name": "Attribute", "value_name": "Value"}
    {"op": "pivot_column", "attribute_column": "Attribute",
        "value_column": "Value", "aggregation": "none"}
    {"op": "add_custom_column", "name": "Net sales",
        "expression": "[Units] * [#\"Unit Price\"]"}
    {"op": "conditional_column", "name": "Price tier",
        "clauses": [{"column": "Tier", "operator": "equals",
            "test_value": "1", "test_value_kind": "value",
            "output": "Tier 1 Price", "output_kind": "column"}],
        "else_value": "Tier 3 Price", "else_kind": "column"}
    {"op": "trim_text", "column": "Name"}
    {"op": "clean_text", "column": "Name"}
    {"op": "lowercase_text", "column": "Name"}
    {"op": "uppercase_text", "column": "Name"}
    {"op": "proper_case_text", "column": "Name"}
    {"op": "reverse_text", "column": "Name"}
    {"op": "remove_duplicates"}
    {"op": "remove_duplicates", "columns": ["Customer ID"]}
    {"op": "keep_duplicates", "columns": ["Customer ID"]}
    {"op": "remove_blank_rows"}
    {"op": "remove_top_rows", "count": 4}
    {"op": "remove_bottom_rows", "count": 4}
    {"op": "keep_top_rows", "count": 4}
    {"op": "keep_bottom_rows", "count": 4}
    {"op": "keep_range_rows", "first_row": 6, "count": 8}
    {"op": "remove_alternate_rows", "first_row_to_remove": 2,
        "remove_count": 1, "keep_count": 1}
    {"op": "add_index_column", "new_name": "Index", "start": 0,
        "increment": 1}
    {"op": "keep_columns", "columns": ["Name", "Amount"]}
    {"op": "promote_headers"}
    {"op": "demote_headers"}
    {"op": "transpose_table"}

Filter operators include exact, text, numeric, and blank-state comparisons.
Numeric comparisons parse values as finite decimals. Null and empty text do not
match numeric comparisons. Blank-state operators match null or empty text and
do not take a comparison value. Advanced filters support up to 64 clauses
across columns; AND binds tighter than OR. Sorts are stable,
case-insensitive for text, numeric when every non-empty value is numeric, and
keep null and empty text at the end in either direction. Grouping uses typed
cell values and preserves the first-seen group order. Numeric aggregates ignore
null and empty values; cell errors propagate to aggregate cells. Min/max compare numeric
values when possible and otherwise compare case-insensitive text. Replace
values matches whole cell text. Merge columns combines at least two selected
fields in saved order, inserts the configured separator between every value,
replaces the selected fields at their first table position, and emits text.
Its combined output is capped at 80 MiB UTF-8. Remove duplicates keeps the first
row for each exact value tuple in its selected key columns; legacy steps without
keys compare the complete row. Keep duplicates retains every row whose exact
selected key tuple occurs more than once, preserving the current row order. Keep
columns retains the selected columns in their current source order. Unpivot retains other columns and emits one row
per selected non-null cell; unpivot-other keeps the selected columns fixed and
un-pivots the rest. Attribute values are the original column names. Both
generated columns have text type; null cells are omitted and empty-text cells
are retained.
Pivot turns distinct values from one attribute column into new columns, using
all remaining columns as row keys. It can keep a single value per key/category
or aggregate duplicates. Generated pivot columns default to text in the model.
Custom columns use a bounded, safe M-style expression subset over native scalar,
null, empty-text, and error values; they do not run arbitrary Python or implement
the full Power Query M language.
Conditional columns test ordered clauses against one row and return the first
matching literal or source-column value, followed by a literal or column value
for the final else branch. Equality and text operators compare exact strings;
ordered comparisons use finite decimal values when both sides parse as numbers
and otherwise use ordinal string ordering. Empty cells are normalized to blank
strings before a conditional step runs. Fill Down copies the preceding
non-null value into null cells; Fill Up copies the following non-null value
into null cells. Empty text is not filled. Leading or trailing nulls remain
null when no source value exists in that direction.
Duplicate Column appends an exact copy of the selected field's values, and the
model metadata keeps the source column's type for the copy.
Remove blank rows drops only rows where every cell is null or empty text;
whitespace-only text is retained.
Remove top rows removes the requested number of rows from the start of the
current row order and leaves the remaining order unchanged.
Remove bottom rows removes the requested number from the end of the current
row order and leaves the preceding rows unchanged.
Keep top rows retains the requested number of rows from the start of the
current row order; counts larger than the row count retain all rows.
Keep bottom rows retains the requested number of rows from the end of the
current row order while preserving their original order; a zero count keeps
no rows and counts larger than the row count keep all rows.
Keep range rows uses a one-based first-row position and a row count, then
retains that contiguous slice in its original order. A range beyond the end
returns only the rows still available, or no rows when it starts past the end.
Remove alternate rows keeps all rows before a one-based first-row position,
then repeatedly removes ``remove_count`` rows and keeps ``keep_count`` rows.
At least one of those counts must be positive so the pattern advances. A zero
remove count keeps all rows after the starting position; a zero keep count
removes all rows from that position onward.
Add Index Column appends signed 64-bit whole-number values, beginning at the
configured start and increasing by the configured increment for each row.
Lowercase Text applies Python's locale-neutral Unicode lowercase mapping to
each value in a text-typed column; no culture selector is available.
Uppercase Text applies Python's locale-neutral Unicode uppercase mapping to
each value in a text-typed column; no culture selector is available.
Transpose Table rotates the current data cells, drops the source column
names, and assigns sequential ``Column1``-style output names. Generated
columns default to text. A table with no data rows cannot be transposed because
the result would contain zero columns.
Split Column by Positions requires two or more strictly increasing
zero-based Unicode-code-point positions starting at 0. Each position starts
one output segment; the final segment includes the remaining suffix. It
replaces the source field with numbered text columns and checks output column
and cell limits before allocating the result.
Change Type Using Locale parses whole/decimal numbers and date/time values
with an explicit Babel/CLDR culture saved in the step. Numbers are normalized
to invariant decimal strings, and dates and times to ISO strings. Date parsing
uses the Gregorian calendar and Babel's locale-aware numeric date patterns;
localized date-times accept a date followed by a clock time, while ISO
timestamps keep their timezone offsets. This bounded local parser does not
implement every Power Query calendar or format rule.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, time
from decimal import (
    MAX_EMAX, MIN_EMIN, Decimal, DecimalException, ROUND_HALF_EVEN, localcontext,
)
from typing import Any

from babel import Locale
from babel.core import UnknownLocaleError
from babel.dates import parse_date, parse_time
from babel.numbers import parse_decimal

from analytics_studio.file_import import (
    MAX_CELLS,
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    ImportCandidate,
    normalize_promoted_headers,
)
from analytics_studio.power_query_expression import (
    ExpressionError as PowerQueryExpressionError,
    MAX_EXPRESSION_OUTPUT_BYTES,
    compile_expression,
    evaluate_expression,
    expression_value_to_text,
    referenced_columns,
)
from analytics_studio.power_query_values import (
    PowerQueryCellError,
    cell_key,
    cell_to_text,
    is_cell_error,
    is_supported_cell_value,
)


MAX_TRANSFORMATION_STEPS = 256
MIN_INDEX_VALUE = -(2**63)
MAX_INDEX_VALUE = 2**63 - 1
MAX_GROUP_DECIMAL_PRECISION = 4096
MAX_SPLIT_POSITION = MAX_EXPRESSION_OUTPUT_BYTES
MAX_DELIMITER_OCCURRENCE = MAX_DATA_ROWS
MAX_CONVERSION_DIAGNOSTICS = 20
MAX_CONVERSION_DIAGNOSTIC_VALUE_CHARS = 120


class TransformationError(ValueError):
    """A malformed transformation or a step that cannot be replayed."""

    def __init__(
        self,
        message: str,
        *,
        row_diagnostics: list[dict[str, Any]] | None = None,
        error_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.row_diagnostics = deepcopy(row_diagnostics or [])
        self.error_count = error_count


_FILTER_OPERATORS = {
    "equals",
    "not_equals",
    "is_null",
    "is_not_null",
    "is_blank",
    "is_not_blank",
    "contains",
    "does_not_contain",
    "begins_with",
    "does_not_begin_with",
    "ends_with",
    "does_not_end_with",
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "less_than_or_equal",
}
FILTER_OPERATORS_WITHOUT_VALUE = frozenset({
    "is_null", "is_not_null", "is_blank", "is_not_blank",
})
_NUMERIC_FILTER_OPERATORS = {
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "less_than_or_equal",
}
_GROUP_ROW_OPERATIONS = {"count_rows", "count_distinct_rows"}
_GROUP_COLUMN_OPERATIONS = {
    "sum",
    "average",
    "median",
    "min",
    "max",
    "count_distinct_values",
}
_PIVOT_AGGREGATIONS = {
    "none",
    "count_all",
    "count_non_blank",
    "min",
    "max",
    "median",
    "sum",
    "average",
}
_CONDITIONAL_OPERATORS = {
    "equals",
    "not_equals",
    "greater_than",
    "greater_than_or_equal",
    "less_than",
    "less_than_or_equal",
    "begins_with",
    "does_not_begin_with",
    "ends_with",
    "does_not_end_with",
    "contains",
    "does_not_contain",
}
_CONDITIONAL_VALUE_KINDS = {"value", "column", "null"}
MAX_CONDITIONAL_CLAUSES = 64
MAX_FILTER_CLAUSES = 64
MAX_MERGE_SEPARATOR_CHARS = 32_767
SUPPORTED_COLUMN_TYPES = {
    "text",
    "whole_number",
    "decimal_number",
    "boolean",
    "date",
    "datetime",
    "time",
}
_CONVERT_TYPES = SUPPORTED_COLUMN_TYPES | {"number"}  # Keep v4/v5 project steps readable.
_LOCALE_CONVERT_TYPES = {"whole_number", "decimal_number", "date", "datetime", "time"}
_LOCALE_CLOCK_PATTERN = r"(?<!\S)\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d{1,6})?)?"
_STEP_FIELDS: dict[str, set[str]] = {
    "rename_column": {"op", "column", "new_name"},
    "remove_column": {"op", "column"},
    "filter_rows": {"op", "column", "operator", "value"},
    "filter_rows_advanced": {"op", "clauses"},
    "sort_rows": {"op", "column", "direction"},
    "sort_rows_by_columns": {"op", "sorts"},
    "convert_type": {"op", "column", "type"},
    "convert_type_using_locale": {"op", "column", "type", "culture"},
    "replace_value": {"op", "column", "value", "replacement"},
    "extract_text_by_delimiter": {"op", "column", "side", "delimiter", "occurrence"},
    "extract_text_between_delimiters": {
        "op", "column", "start_delimiter", "end_delimiter",
        "start_occurrence", "end_occurrence",
    },
    "split_column": {"op", "column", "delimiter"},
    "split_column_by_each_delimiter": {"op", "column", "delimiter"},
    "split_column_to_rows": {"op", "column", "delimiter"},
    "split_column_by_positions": {"op", "column", "positions"},
    "merge_columns": {"op", "columns", "separator", "new_name"},
    "fill_down": {"op", "columns"},
    "fill_up": {"op", "columns"},
    "duplicate_column": {"op", "column", "new_name"},
    "group_by": {"op", "columns", "aggregations"},
    "unpivot_columns": {"op", "columns", "attribute_name", "value_name"},
    "unpivot_other_columns": {"op", "columns", "attribute_name", "value_name"},
    "pivot_column": {"op", "attribute_column", "value_column", "aggregation"},
    "add_custom_column": {"op", "name", "expression"},
    "conditional_column": {"op", "name", "clauses", "else_value", "else_kind"},
    "trim_text": {"op", "column"},
    "clean_text": {"op", "column"},
    "lowercase_text": {"op", "column"},
    "uppercase_text": {"op", "column"},
    "proper_case_text": {"op", "column"},
    "reverse_text": {"op", "column"},
    "remove_duplicates": {"op"},
    "keep_duplicates": {"op", "columns"},
    "remove_blank_rows": {"op"},
    "remove_rows_with_errors": {"op"},
    "remove_top_rows": {"op", "count"},
    "remove_bottom_rows": {"op", "count"},
    "keep_top_rows": {"op", "count"},
    "keep_bottom_rows": {"op", "count"},
    "keep_range_rows": {"op", "first_row", "count"},
    "remove_alternate_rows": {
        "op", "first_row_to_remove", "remove_count", "keep_count"
    },
    "add_index_column": {"op", "new_name", "start", "increment"},
    "keep_columns": {"op", "columns"},
    "reorder_columns": {"op", "columns"},
    "promote_headers": {"op"},
    "demote_headers": {"op"},
    "transpose_table": {"op"},
}


def validate_steps(steps: Any) -> list[dict[str, Any]]:
    """Validate and copy an ordered JSON-serializable step list."""
    if not isinstance(steps, list):
        raise TransformationError("Transformation steps must be a list.")
    if len(steps) > MAX_TRANSFORMATION_STEPS:
        raise TransformationError(
            f"A transformation sequence may contain at most {MAX_TRANSFORMATION_STEPS} steps."
        )

    validated: list[dict[str, Any]] = []
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict) or any(not isinstance(key, str) for key in step):
            raise TransformationError(f"Transformation step {index} must be an object with string keys.")
        op = step.get("op")
        if not isinstance(op, str) or op not in _STEP_FIELDS:
            raise TransformationError(f"Transformation step {index} has an unsupported operation.")
        if op == "remove_duplicates":
            allowed_shapes = (_STEP_FIELDS[op], _STEP_FIELDS[op] | {"columns"})
            if set(step) not in allowed_shapes:
                raise TransformationError(
                    f"Transformation step {index} has missing or unsupported fields."
                )
        elif op == "remove_rows_with_errors":
            allowed_shapes = (_STEP_FIELDS[op], _STEP_FIELDS[op] | {"columns"})
            if set(step) not in allowed_shapes:
                raise TransformationError(
                    f"Transformation step {index} has missing or unsupported fields."
                )
        elif op == "filter_rows":
            allowed_shapes = (
                _STEP_FIELDS[op],
                (_STEP_FIELDS[op] - {"value"}) | {"parameter"},
            )
            if set(step) not in allowed_shapes:
                raise TransformationError(
                    f"Transformation step {index} has missing or unsupported fields."
                )
        elif op == "add_custom_column":
            if set(step) not in (
                _STEP_FIELDS[op], _STEP_FIELDS[op] | {"output_type"}
            ):
                raise TransformationError(f"Transformation step {index} has missing or unsupported fields.")
        elif set(step) != _STEP_FIELDS[op]:
            raise TransformationError(f"Transformation step {index} has missing or unsupported fields.")
        if op == "add_custom_column" and "output_type" in step:
            if not isinstance(step["output_type"], str) or step["output_type"] not in {
                "text", "whole_number", "decimal_number", "boolean", "date", "datetime"
            }:
                raise TransformationError(
                    f"Transformation step {index} has an unsupported custom-column output type."
                )
            if step["output_type"] == "text":
                step = dict(step)
                step.pop("output_type")
        if op in {"remove_duplicates", "keep_duplicates"} and "columns" in step:
            columns = step["columns"]
            if not isinstance(columns, list) or not columns or any(
                not isinstance(column, str) or not column.strip() for column in columns
            ):
                raise TransformationError(
                    f"Transformation step {index} needs one or more duplicate-key columns."
                )
            columns = [column.strip() for column in columns]
            if len(set(columns)) != len(columns):
                raise TransformationError(
                    f"Transformation step {index} selects a duplicate key column more than once."
                )
            step = {**step, "columns": columns}
        elif op == "remove_rows_with_errors" and "columns" in step:
            columns = step["columns"]
            if not isinstance(columns, list) or not columns or any(
                not isinstance(column, str) or not column.strip() for column in columns
            ):
                raise TransformationError(
                    f"Transformation step {index} needs one or more error-check columns."
                )
            columns = [column.strip() for column in columns]
            if len(set(columns)) != len(columns):
                raise TransformationError(
                    f"Transformation step {index} selects an error-check column more than once."
                )
            step = {**step, "columns": columns}
        elif op in {
            "remove_top_rows", "remove_bottom_rows", "keep_top_rows",
            "keep_bottom_rows", "keep_range_rows",
        }:
            count = step["count"]
            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or count < 0
                or count > MAX_DATA_ROWS
            ):
                raise TransformationError(
                    f"Transformation step {index} needs a whole number from 0 to {MAX_DATA_ROWS:,}."
                )
            if op == "keep_range_rows":
                first_row = step["first_row"]
                if (
                    not isinstance(first_row, int)
                    or isinstance(first_row, bool)
                    or first_row < 1
                    or first_row > MAX_DATA_ROWS
                ):
                    raise TransformationError(
                        f"Transformation step {index} needs a first row from 1 to {MAX_DATA_ROWS:,}."
                    )
        elif op == "remove_alternate_rows":
            first_row = step["first_row_to_remove"]
            remove_count = step["remove_count"]
            keep_count = step["keep_count"]
            if (
                not isinstance(first_row, int)
                or isinstance(first_row, bool)
                or first_row < 1
                or first_row > MAX_DATA_ROWS
            ):
                raise TransformationError(
                    f"Transformation step {index} needs a first row to remove from 1 to {MAX_DATA_ROWS:,}."
                )
            for field_name, field_value in (
                ("remove count", remove_count), ("keep count", keep_count)
            ):
                if (
                    not isinstance(field_value, int)
                    or isinstance(field_value, bool)
                    or field_value < 0
                    or field_value > MAX_DATA_ROWS
                ):
                    raise TransformationError(
                        f"Transformation step {index} needs a {field_name} from 0 to {MAX_DATA_ROWS:,}."
                    )
            if remove_count == 0 and keep_count == 0:
                raise TransformationError(
                    f"Transformation step {index} must remove or keep at least one row per cycle."
                )
        elif op == "keep_columns":
            columns = step["columns"]
            if not isinstance(columns, list) or not columns or any(
                not isinstance(column, str) or not column.strip() for column in columns
            ):
                raise TransformationError(f"Transformation step {index} needs one or more column names.")
            if len(set(columns)) != len(columns):
                raise TransformationError(f"Transformation step {index} contains a duplicate column name.")
        elif op == "reorder_columns":
            columns = step["columns"]
            if not isinstance(columns, list) or not columns or any(
                not isinstance(column, str) or not column.strip() for column in columns
            ):
                raise TransformationError(f"Transformation step {index} needs one or more column names.")
            columns = [column.strip() for column in columns]
            if len(set(columns)) != len(columns):
                raise TransformationError(f"Transformation step {index} contains a duplicate column name.")
            step = {**step, "columns": columns}
        elif op in {"fill_down", "fill_up"}:
            columns = step["columns"]
            if not isinstance(columns, list) or not columns or any(
                not isinstance(column, str) or not column.strip() for column in columns
            ):
                raise TransformationError(f"Transformation step {index} needs one or more column names.")
            columns = [column.strip() for column in columns]
            if len(set(columns)) != len(columns):
                raise TransformationError(f"Transformation step {index} contains a duplicate column name.")
            step = {**step, "columns": columns}
        elif op == "duplicate_column":
            column = step["column"]
            new_name = step["new_name"]
            if not isinstance(column, str) or not column.strip():
                raise TransformationError(f"Transformation step {index} needs a column name.")
            if not isinstance(new_name, str) or not new_name.strip():
                raise TransformationError(f"Transformation step {index} needs a new column name.")
            step = {**step, "column": column.strip(), "new_name": new_name.strip()}
        elif op == "split_column_by_positions":
            column = step["column"]
            positions = step["positions"]
            if not isinstance(column, str) or not column.strip():
                raise TransformationError(f"Transformation step {index} needs a column name.")
            if not isinstance(positions, list) or not 2 <= len(positions) <= MAX_COLUMNS:
                raise TransformationError(
                    f"Transformation step {index} needs 2 to {MAX_COLUMNS} split positions."
                )
            if any(
                not isinstance(position, int)
                or isinstance(position, bool)
                or position < 0
                or position > MAX_SPLIT_POSITION
                for position in positions
            ):
                raise TransformationError(
                    f"Transformation step {index} positions must be whole numbers from 0 to {MAX_SPLIT_POSITION:,}."
                )
            if positions[0] != 0:
                raise TransformationError(
                    f"Transformation step {index} positions must start at 0."
                )
            if any(left >= right for left, right in zip(positions, positions[1:])):
                raise TransformationError(
                    f"Transformation step {index} positions must be in strictly increasing order."
                )
            step = {
                **step,
                "column": column.strip(),
                "positions": list(positions),
            }
        elif op == "extract_text_by_delimiter":
            column = step["column"]
            side = step["side"]
            occurrence = step["occurrence"]
            if not isinstance(column, str) or not column.strip():
                raise TransformationError(f"Transformation step {index} needs a column name.")
            if not isinstance(side, str) or side not in {"before", "after"}:
                raise TransformationError(
                    f"Transformation step {index} must extract text before or after the delimiter."
                )
            if not isinstance(step["delimiter"], str) or not step["delimiter"]:
                raise TransformationError(f"Transformation step {index} needs a non-empty delimiter.")
            if (
                not isinstance(occurrence, int)
                or isinstance(occurrence, bool)
                or occurrence < 0
                or occurrence > MAX_DELIMITER_OCCURRENCE
            ):
                raise TransformationError(
                    f"Transformation step {index} needs a zero-based delimiter occurrence "
                    f"from 0 to {MAX_DELIMITER_OCCURRENCE:,}."
                )
            step = {**step, "column": column.strip()}
        elif op == "extract_text_between_delimiters":
            column = step["column"]
            if not isinstance(column, str) or not column.strip():
                raise TransformationError(f"Transformation step {index} needs a column name.")
            for field_name in ("start_delimiter", "end_delimiter"):
                delimiter = step[field_name]
                if not isinstance(delimiter, str) or not delimiter:
                    raise TransformationError(
                        f"Transformation step {index} needs a non-empty {field_name.replace('_', ' ')}."
                    )
            for field_name in ("start_occurrence", "end_occurrence"):
                occurrence = step[field_name]
                if (
                    not isinstance(occurrence, int)
                    or isinstance(occurrence, bool)
                    or occurrence < 0
                    or occurrence > MAX_DELIMITER_OCCURRENCE
                ):
                    raise TransformationError(
                        f"Transformation step {index} needs {field_name.replace('_', ' ')} "
                        f"from 0 to {MAX_DELIMITER_OCCURRENCE:,}."
                    )
            step = {**step, "column": column.strip()}
        elif op == "add_index_column":
            new_name = step["new_name"]
            if not isinstance(new_name, str) or not new_name.strip():
                raise TransformationError(f"Transformation step {index} needs a new column name.")
            for field_name in ("start", "increment"):
                field_value = step[field_name]
                if (
                    not isinstance(field_value, int)
                    or isinstance(field_value, bool)
                    or field_value < MIN_INDEX_VALUE
                    or field_value > MAX_INDEX_VALUE
                ):
                    raise TransformationError(
                        f"Transformation step {index} needs {field_name} to be a signed 64-bit whole number."
                    )
            step = {**step, "new_name": new_name.strip()}
        elif op == "merge_columns":
            columns = step["columns"]
            separator = step["separator"]
            new_name = step["new_name"]
            if not isinstance(columns, list) or len(columns) < 2 or any(
                not isinstance(column, str) or not column.strip() for column in columns
            ):
                raise TransformationError(
                    f"Transformation step {index} needs at least two columns to merge."
                )
            columns = [column.strip() for column in columns]
            if len(set(columns)) != len(columns):
                raise TransformationError(
                    f"Transformation step {index} contains a duplicate merge column."
                )
            if not isinstance(separator, str):
                raise TransformationError(
                    f"Transformation step {index} needs a text separator."
                )
            if len(separator) > MAX_MERGE_SEPARATOR_CHARS:
                raise TransformationError(
                    f"The merge separator may contain at most {MAX_MERGE_SEPARATOR_CHARS:,} characters."
                )
            if not isinstance(new_name, str) or not new_name.strip():
                raise TransformationError(
                    f"Transformation step {index} needs a new column name."
                )
            step = {
                **step,
                "columns": columns,
                "separator": separator,
                "new_name": new_name.strip(),
            }
        elif op == "group_by":
            columns = step["columns"]
            aggregations = step["aggregations"]
            if not isinstance(columns, list) or not columns or any(
                not isinstance(column, str) or not column.strip() for column in columns
            ):
                raise TransformationError(f"Transformation step {index} needs one or more group columns.")
            if len(set(columns)) != len(columns):
                raise TransformationError(f"Transformation step {index} contains a duplicate group column.")
            if not isinstance(aggregations, list) or not aggregations:
                raise TransformationError(f"Transformation step {index} needs one or more aggregations.")
            if len(columns) + len(aggregations) > MAX_COLUMNS:
                raise TransformationError(
                    f"A grouped result cannot exceed the {MAX_COLUMNS}-column import limit."
                )
            validated_aggregations: list[dict[str, str]] = []
            output_names: set[str] = set(columns)
            for aggregate_index, aggregate in enumerate(aggregations, 1):
                if not isinstance(aggregate, dict) or any(
                    not isinstance(key, str) for key in aggregate
                ):
                    raise TransformationError(
                        f"Aggregation {aggregate_index} in step {index} must be an object."
                    )
                operation = aggregate.get("operation")
                if not isinstance(operation, str) or operation not in (
                    _GROUP_ROW_OPERATIONS | _GROUP_COLUMN_OPERATIONS
                ):
                    raise TransformationError(
                        f"Aggregation {aggregate_index} in step {index} has an unsupported operation."
                    )
                if operation in _GROUP_ROW_OPERATIONS:
                    expected_fields = {"operation", "new_name"}
                elif operation in _GROUP_COLUMN_OPERATIONS:
                    expected_fields = {"operation", "column", "new_name"}
                else:
                    raise TransformationError(
                        f"Aggregation {aggregate_index} in step {index} has an unsupported operation."
                    )
                if set(aggregate) != expected_fields or any(
                    not isinstance(value, str) for value in aggregate.values()
                ):
                    raise TransformationError(
                        f"Aggregation {aggregate_index} in step {index} has missing or invalid fields."
                    )
                new_name = aggregate["new_name"].strip()
                if not new_name:
                    raise TransformationError(
                        f"Aggregation {aggregate_index} in step {index} needs an output column name."
                    )
                if new_name in output_names:
                    raise TransformationError(
                        f"Group output column {new_name!r} conflicts with another output column."
                    )
                if "column" in expected_fields and not aggregate["column"].strip():
                    raise TransformationError(
                        f"Aggregation {aggregate_index} in step {index} needs a source column."
                    )
                output_names.add(new_name)
                validated_aggregations.append({
                    key: (new_name if key == "new_name" else value)
                    for key, value in aggregate.items()
                })
            step = {
                **step,
                "columns": list(columns),
                "aggregations": validated_aggregations,
            }
        elif op in {"unpivot_columns", "unpivot_other_columns"}:
            columns = step["columns"]
            if not isinstance(columns, list) or not columns or any(
                not isinstance(column, str) or not column.strip() for column in columns
            ):
                raise TransformationError(
                    f"Transformation step {index} needs one or more columns."
                )
            if len(set(columns)) != len(columns):
                raise TransformationError(
                    f"Transformation step {index} contains a duplicate column name."
                )
            if any(
                not isinstance(step[name], str) or not step[name].strip()
                for name in ("attribute_name", "value_name")
            ):
                raise TransformationError(
                    f"Transformation step {index} needs both output column names."
                )
            attribute_name = step["attribute_name"].strip()
            value_name = step["value_name"].strip()
            if attribute_name == value_name:
                raise TransformationError(
                    f"Transformation step {index} output column names must be different."
                )
            step = {
                **step,
                "columns": list(columns),
                "attribute_name": attribute_name,
                "value_name": value_name,
            }
        elif op == "pivot_column":
            if any(
                not isinstance(step[name], str) or not step[name].strip()
                for name in ("attribute_column", "value_column", "aggregation")
            ):
                raise TransformationError(
                    f"Transformation step {index} needs an attribute, value, and aggregation choice."
                )
            if step["attribute_column"].strip() == step["value_column"].strip():
                raise TransformationError(
                    f"Transformation step {index} must use different attribute and value columns."
                )
            aggregation = step["aggregation"].strip()
            if aggregation not in _PIVOT_AGGREGATIONS:
                raise TransformationError(
                    f"Transformation step {index} has an unsupported pivot aggregation."
                )
            step = {
                **step,
                "attribute_column": step["attribute_column"].strip(),
                "value_column": step["value_column"].strip(),
                "aggregation": aggregation,
            }
        elif op == "add_custom_column":
            name = step["name"]
            expression = step["expression"]
            if not isinstance(name, str) or not name.strip():
                raise TransformationError(
                    f"Transformation step {index} needs a new column name."
                )
            if not isinstance(expression, str) or not expression.strip():
                raise TransformationError(
                    f"Transformation step {index} needs a formula."
                )
            try:
                compile_expression(
                    expression,
                    allow_unknown_symbols=True,
                    allow_unknown_functions=True,
                )
            except PowerQueryExpressionError as exc:
                raise TransformationError(
                    f"Custom column formula in step {index}: {exc}"
                ) from exc
            step = {**step, "name": name.strip(), "expression": expression.strip()}
        elif op == "conditional_column":
            name = step["name"]
            clauses = step["clauses"]
            else_value = step["else_value"]
            else_kind = step["else_kind"]
            if not isinstance(name, str) or not name.strip():
                raise TransformationError(
                    f"Transformation step {index} needs a new column name."
                )
            if not isinstance(clauses, list) or not clauses:
                raise TransformationError(
                    f"Transformation step {index} needs one or more conditional clauses."
                )
            if len(clauses) > MAX_CONDITIONAL_CLAUSES:
                raise TransformationError(
                    f"A conditional column may contain at most {MAX_CONDITIONAL_CLAUSES} clauses."
                )
            validated_clauses: list[dict[str, str]] = []
            clause_fields = {
                "column", "operator", "test_value", "test_value_kind", "output", "output_kind"
            }
            for clause_index, clause in enumerate(clauses, 1):
                if (
                    not isinstance(clause, dict)
                    or set(clause) != clause_fields
                    or any(not isinstance(value, str) for value in clause.values())
                ):
                    raise TransformationError(
                        f"Clause {clause_index} in step {index} has missing or invalid fields."
                    )
                column = clause["column"].strip()
                operator = clause["operator"].strip()
                test_value = clause["test_value"]
                test_value_kind = clause["test_value_kind"].strip()
                output = clause["output"]
                output_kind = clause["output_kind"].strip()
                if not column:
                    raise TransformationError(
                        f"Clause {clause_index} in step {index} needs a test column."
                    )
                if operator not in _CONDITIONAL_OPERATORS:
                    raise TransformationError(
                        f"Clause {clause_index} in step {index} has an unsupported operator."
                    )
                if test_value_kind not in _CONDITIONAL_VALUE_KINDS:
                    raise TransformationError(
                        f"Clause {clause_index} in step {index} has an invalid comparison-value type."
                    )
                if test_value_kind == "column" and not test_value.strip():
                    raise TransformationError(
                        f"Clause {clause_index} in step {index} needs a comparison column."
                    )
                if test_value_kind == "null" and test_value:
                    raise TransformationError(
                        f"Clause {clause_index} in step {index} must use an empty placeholder for a null comparison."
                    )
                if output_kind not in {"value", "column"}:
                    raise TransformationError(
                        f"Clause {clause_index} in step {index} has an invalid output type."
                    )
                if output_kind == "column" and not output.strip():
                    raise TransformationError(
                        f"Clause {clause_index} in step {index} needs an output column."
                    )
                validated_clauses.append({
                    "column": column,
                    "operator": operator,
                    "test_value": test_value.strip() if test_value_kind == "column" else test_value,
                    "test_value_kind": test_value_kind,
                    "output": output.strip() if output_kind == "column" else output,
                    "output_kind": output_kind,
                })
            if not isinstance(else_value, str) or not isinstance(else_kind, str):
                raise TransformationError(
                    f"Transformation step {index} needs a valid final else value."
                )
            else_kind = else_kind.strip()
            if else_kind not in {"value", "column"}:
                raise TransformationError(
                    f"Transformation step {index} has an invalid final else type."
                )
            if else_kind == "column" and not else_value.strip():
                raise TransformationError(
                    f"Transformation step {index} needs a final else column."
                )
            step = {
                **step,
                "name": name.strip(),
                "clauses": validated_clauses,
                "else_value": else_value.strip() if else_kind == "column" else else_value,
                "else_kind": else_kind,
            }
        elif op == "filter_rows_advanced":
            clauses = step["clauses"]
            if not isinstance(clauses, list) or not clauses:
                raise TransformationError(
                    f"Transformation step {index} needs at least one filter clause."
                )
            if len(clauses) > MAX_FILTER_CLAUSES:
                raise TransformationError(
                    f"An advanced filter may contain at most {MAX_FILTER_CLAUSES} clauses."
                )
            clause_fields = {"column", "operator", "value", "join"}
            parameter_clause_fields = {"column", "operator", "parameter", "join"}
            validated_clauses: list[dict[str, str]] = []
            for clause_index, clause in enumerate(clauses, 1):
                if (
                    not isinstance(clause, dict)
                    or frozenset(clause) not in {
                        frozenset(clause_fields), frozenset(parameter_clause_fields),
                    }
                    or any(not isinstance(value, str) for value in clause.values())
                ):
                    raise TransformationError(
                        f"Filter clause {clause_index} in step {index} has missing or invalid fields."
                    )
                column = clause["column"]
                operator = clause["operator"].strip()
                join = clause["join"].strip()
                parameter_name = clause.get("parameter")
                if not column.strip():
                    raise TransformationError(
                        f"Filter clause {clause_index} in step {index} needs a column."
                    )
                if operator not in _FILTER_OPERATORS:
                    raise TransformationError(
                        f"Filter clause {clause_index} in step {index} has an unsupported operator."
                    )
                if (
                    operator in FILTER_OPERATORS_WITHOUT_VALUE
                    and ("parameter" in clause or clause["value"])
                ):
                    raise TransformationError(
                        f"Filter clause {clause_index} in step {index} does not use a comparison value."
                    )
                if join not in {"and", "or"}:
                    raise TransformationError(
                        f"Filter clause {clause_index} in step {index} must join with 'and' or 'or'."
                    )
                if clause_index == 1 and join != "and":
                    raise TransformationError(
                        f"The first filter clause in step {index} cannot have a join operator."
                    )
                if parameter_name is not None and not parameter_name.strip():
                    raise TransformationError(
                        f"Filter clause {clause_index} in step {index} needs a parameter name."
                    )
                validated_clause = {
                    "column": column,
                    "operator": operator,
                    "join": join,
                }
                if parameter_name is None:
                    validated_clause["value"] = clause["value"]
                else:
                    validated_clause["parameter"] = parameter_name.strip()
                validated_clauses.append(validated_clause)
            step = {**step, "clauses": validated_clauses}
        elif op == "sort_rows_by_columns":
            sorts = step["sorts"]
            if not isinstance(sorts, list) or not sorts or len(sorts) > MAX_COLUMNS:
                raise TransformationError(
                    f"Transformation step {index} needs 1 to {MAX_COLUMNS} sort columns."
                )
            validated_sorts: list[dict[str, str]] = []
            selected_columns: set[str] = set()
            for sort_index, sort in enumerate(sorts, 1):
                if (
                    not isinstance(sort, dict)
                    or set(sort) != {"column", "direction"}
                    or any(not isinstance(value, str) for value in sort.values())
                ):
                    raise TransformationError(
                        f"Sort level {sort_index} in step {index} has missing or invalid fields."
                    )
                column = sort["column"].strip()
                direction = sort["direction"].strip()
                if not column:
                    raise TransformationError(
                        f"Sort level {sort_index} in step {index} needs a column."
                    )
                if direction not in {"asc", "desc"}:
                    raise TransformationError(
                        f"Sort level {sort_index} in step {index} direction must be 'asc' or 'desc'."
                    )
                if column in selected_columns:
                    raise TransformationError(
                        f"Sort column {column!r} appears more than once in step {index}."
                    )
                selected_columns.add(column)
                validated_sorts.append({"column": column, "direction": direction})
            step = {**step, "sorts": validated_sorts}
        elif any(not isinstance(value, str) for value in step.values()):
            raise TransformationError(f"Transformation step {index} values must be strings.")

        column = step.get("column")
        if column is not None and not column.strip():
            raise TransformationError(f"Transformation step {index} needs a column name.")
        if op in {
            "extract_text_by_delimiter", "split_column",
            "split_column_by_each_delimiter", "split_column_to_rows",
        }:
            if not step["delimiter"]:
                raise TransformationError(f"Transformation step {index} needs a non-empty delimiter.")
        elif op == "extract_text_between_delimiters":
            if not step["start_delimiter"] or not step["end_delimiter"]:
                raise TransformationError(
                    f"Transformation step {index} needs non-empty start and end delimiters."
                )
        elif op == "rename_column":
            if not step["new_name"].strip():
                raise TransformationError(f"Transformation step {index} needs a new column name.")
        elif op == "filter_rows":
            if step["operator"] not in _FILTER_OPERATORS:
                raise TransformationError(f"Transformation step {index} has an unsupported filter operator.")
            if "parameter" in step:
                if (
                    not isinstance(step["parameter"], str)
                    or not step["parameter"].strip()
                    or step["operator"] in FILTER_OPERATORS_WITHOUT_VALUE
                ):
                    raise TransformationError(
                        f"Transformation step {index} needs a comparison parameter for this filter."
                    )
                step = {**step, "parameter": step["parameter"].strip()}
            if (
                step["operator"] in FILTER_OPERATORS_WITHOUT_VALUE
                and step.get("value")
            ):
                raise TransformationError(
                    f"Transformation step {index} does not use a comparison value for this filter."
                )
        elif op == "sort_rows":
            if step["direction"] not in {"asc", "desc"}:
                raise TransformationError(f"Transformation step {index} direction must be 'asc' or 'desc'.")
        elif op == "convert_type":
            if step["type"] not in _CONVERT_TYPES:
                raise TransformationError(f"Transformation step {index} has an unsupported column type.")
        elif op == "convert_type_using_locale":
            if step["type"] not in _LOCALE_CONVERT_TYPES:
                raise TransformationError(
                    f"Transformation step {index} has an unsupported locale-aware column type."
                )
            try:
                culture = _canonical_culture(step["culture"])
            except TransformationError as exc:
                raise TransformationError(f"Transformation step {index}: {exc}") from exc
            step = {**step, "column": step["column"].strip(), "culture": culture}
        validated.append(deepcopy(step))
    return validated


def validate_applied_step_metadata(value: Any, step_count: int) -> list[dict[str, str]]:
    """Normalize display names/descriptions stored beside an applied-step list."""
    if not isinstance(value, list):
        raise TransformationError("Applied-step metadata must be a list.")
    if (
        not isinstance(step_count, int)
        or isinstance(step_count, bool)
        or step_count < 0
        or step_count > MAX_TRANSFORMATION_STEPS
    ):
        raise TransformationError("Applied-step metadata has an invalid step count.")
    if len(value) > MAX_TRANSFORMATION_STEPS:
        raise TransformationError(
            f"Applied-step metadata may contain at most {MAX_TRANSFORMATION_STEPS} items."
        )

    normalized: list[dict[str, str]] = []
    for index in range(step_count):
        item = value[index] if index < len(value) else {}
        if not isinstance(item, dict) or set(item) - {"name", "description"}:
            raise TransformationError(
                f"Applied-step metadata {index + 1} must contain only name and description."
            )
        name = item.get("name", "")
        description = item.get("description", "")
        if (
            not isinstance(name, str)
            or len(name) > 120
            or any(ord(char) < 32 for char in name)
        ):
            raise TransformationError(
                f"The name for applied step {index + 1} must be at most 120 characters and contain no control characters."
            )
        if (
            not isinstance(description, str)
            or len(description) > 4000
            or "\x00" in description
        ):
            raise TransformationError(
                f"The description for applied step {index + 1} must be at most 4,000 characters and contain no null characters."
            )
        clean: dict[str, str] = {}
        if name.strip():
            clean["name"] = name.strip()
        if description.strip():
            clean["description"] = description.strip()
        normalized.append(clean)
    return normalized


def apply_transformations(
    candidate: ImportCandidate,
    steps: Any,
    *,
    parameters: dict[str, Any] | None = None,
) -> ImportCandidate:
    """Return a transformed copy of ``candidate`` after replaying ``steps``."""
    validated_steps = validate_steps(steps)
    parameter_values = parameters if parameters is not None else {}
    from analytics_studio.query_functions import (
        QueryFunctionError,
        compile_query_functions,
    )
    try:
        compiled_query_functions = compile_query_functions(
            getattr(parameter_values, "query_functions", [])
        )
    except QueryFunctionError as exc:
        raise TransformationError(f"Power Query functions: {exc}") from exc
    resolved_steps: list[dict[str, Any]] = []
    for step in validated_steps:
        resolved = dict(step)
        if step["op"] == "filter_rows" and "parameter" in step:
            name = step["parameter"]
            if name not in parameter_values:
                raise TransformationError(
                    f"Power Query parameter {name!r} has no current value."
                )
            resolved.pop("parameter")
            resolved["value"] = _parameter_filter_text(parameter_values[name])
        elif step["op"] == "filter_rows_advanced":
            clauses = []
            for clause in step["clauses"]:
                resolved_clause = dict(clause)
                if "parameter" in clause:
                    name = clause["parameter"]
                    if name not in parameter_values:
                        raise TransformationError(
                            f"Power Query parameter {name!r} has no current value."
                        )
                    resolved_clause.pop("parameter")
                    resolved_clause["value"] = _parameter_filter_text(parameter_values[name])
                clauses.append(resolved_clause)
            resolved["clauses"] = clauses
        resolved_steps.append(resolved)
    validated_steps = validate_steps(resolved_steps)
    _validate_candidate(candidate)

    result = ImportCandidate(
        kind=candidate.kind,
        headers=list(candidate.headers),
        rows=deepcopy(candidate.rows),
        options=deepcopy(candidate.options),
        notices=deepcopy(candidate.notices),
    )
    for step in validated_steps:
        op = step["op"]
        if op in {"remove_duplicates", "keep_duplicates"}:
            if op == "remove_duplicates":
                result.rows = _remove_duplicates(
                    result.headers,
                    result.rows,
                    step.get("columns"),
                )
            else:
                result.rows = _keep_duplicates(
                    result.headers, result.rows, step["columns"]
                )
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op in {"promote_headers", "demote_headers", "transpose_table"}:
            if op == "promote_headers":
                result = _promote_headers(result)
            elif op == "demote_headers":
                result = _demote_headers(result)
            else:
                result = _transpose_table(result)
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "remove_blank_rows":
            # Keep whitespace-only text because Power Query's blank-row operation
            # removes null and empty-text cells without trimming text.
            result.rows = [
                row for row in result.rows
                if any(row[header] is not None and row[header] != "" for header in result.headers)
            ]
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "remove_rows_with_errors":
            columns = step.get("columns", result.headers)
            missing = next((column for column in columns if column not in result.headers), None)
            if missing is not None:
                raise TransformationError(
                    f"Error-check column {missing!r} does not exist."
                )
            result.rows = [
                row for row in result.rows
                if not any(is_cell_error(row[column]) for column in columns)
            ]
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "remove_top_rows":
            result.rows = result.rows[step["count"]:]
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "remove_bottom_rows":
            keep_count = max(0, len(result.rows) - step["count"])
            result.rows = result.rows[:keep_count]
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "keep_top_rows":
            result.rows = result.rows[:step["count"]]
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "keep_bottom_rows":
            count = step["count"]
            result.rows = result.rows[-count:] if count else []
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "keep_range_rows":
            start = step["first_row"] - 1
            result.rows = result.rows[start:start + step["count"]]
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "remove_alternate_rows":
            source_rows = result.rows
            position = step["first_row_to_remove"] - 1
            remove_count = step["remove_count"]
            keep_count = step["keep_count"]
            retained_rows = source_rows[:position]
            while position < len(source_rows):
                position += remove_count
                if position >= len(source_rows):
                    break
                retained_rows.extend(source_rows[position:position + keep_count])
                position += keep_count
            result.rows = retained_rows
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "add_index_column":
            result = _add_index_column(
                result, step["new_name"], step["start"], step["increment"]
            )
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "keep_columns":
            result = _keep_columns(result, step["columns"])
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "reorder_columns":
            result = _reorder_columns(result, step["columns"])
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op in {"fill_down", "fill_up"}:
            result = _fill_values(result, step["columns"], fill_down=op == "fill_down")
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "duplicate_column":
            result = _duplicate_column(result, step["column"], step["new_name"])
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "merge_columns":
            result = _merge_columns(
                result,
                step["columns"],
                step["separator"],
                step["new_name"],
            )
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "group_by":
            result = _group_by(result, step["columns"], step["aggregations"])
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op in {"unpivot_columns", "unpivot_other_columns"}:
            result = _unpivot_columns(
                result,
                step["columns"],
                step["attribute_name"],
                step["value_name"],
                unpivot_other=op == "unpivot_other_columns",
            )
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "pivot_column":
            result = _pivot_column(
                result,
                step["attribute_column"],
                step["value_column"],
                step["aggregation"],
            )
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "add_custom_column":
            result = _add_custom_column(
                result,
                step["name"],
                step["expression"],
                parameter_values,
                output_type=step.get("output_type", "text"),
                query_functions=compiled_query_functions,
            )
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "conditional_column":
            result = _add_conditional_column(
                result,
                step["name"],
                step["clauses"],
                step["else_value"],
                step["else_kind"],
            )
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "sort_rows_by_columns":
            result.rows = _sort_rows_by_columns(
                result.rows, result.headers, step["sorts"]
            )
            _check_candidate_limits(result.headers, result.rows)
            continue
        if op == "filter_rows_advanced":
            result.rows = _filter_rows_advanced(
                result.rows, result.headers, step["clauses"]
            )
            _check_candidate_limits(result.headers, result.rows)
            continue

        column = step["column"]
        column_index = _column_index(result.headers, column)

        if op == "rename_column":
            new_name = step["new_name"].strip()
            if new_name in result.headers and new_name != column:
                raise TransformationError(f"Column {new_name!r} already exists.")
            result.headers[column_index] = new_name
            for row in result.rows:
                rebuilt = {}
                for header in result.headers:
                    key = column if header == new_name and header != column else header
                    if key not in row:
                        key = column if header == new_name else header
                    rebuilt[header] = row[key]
                row.clear()
                row.update(rebuilt)
        elif op == "remove_column":
            if len(result.headers) == 1:
                raise TransformationError("Cannot remove the last column from a table.")
            result.headers.pop(column_index)
            for row in result.rows:
                del row[column]
        elif op == "filter_rows":
            result.rows = _filter_rows(result.rows, column, step["operator"], step["value"])
        elif op == "sort_rows":
            result.rows = _sort_rows(result.rows, column, step["direction"])
        elif op == "convert_type":
            _convert_column(result.rows, column, step["type"])
        elif op == "convert_type_using_locale":
            _convert_column_using_locale(
                result.rows, column, step["type"], step["culture"]
            )
        elif op == "replace_value":
            old_value = step["value"]
            replacement = step["replacement"]
            for row in result.rows:
                if not is_cell_error(row[column]) and _filter_values_equal(
                    row[column], old_value
                ):
                    row[column] = replacement
        elif op == "extract_text_by_delimiter":
            _extract_text_by_delimiter(
                result,
                column,
                step["side"],
                step["delimiter"],
                step["occurrence"],
            )
        elif op == "extract_text_between_delimiters":
            _extract_text_between_delimiters(
                result,
                column,
                step["start_delimiter"],
                step["end_delimiter"],
                step["start_occurrence"],
                step["end_occurrence"],
            )
        elif op == "split_column":
            _split_column(result, column, step["delimiter"])
        elif op == "split_column_by_each_delimiter":
            _split_column_by_each_delimiter(result, column, step["delimiter"])
        elif op == "split_column_by_positions":
            _split_column_by_positions(result, column, step["positions"])
        elif op == "split_column_to_rows":
            _split_column_to_rows(result, column, step["delimiter"])
        elif op == "trim_text":
            for row in result.rows:
                value = row[column]
                if value is not None and not is_cell_error(value):
                    row[column] = cell_to_text(value).strip()
        elif op == "clean_text":
            for row in result.rows:
                value = row[column]
                if value is not None and not is_cell_error(value):
                    row[column] = "".join(
                        character for character in cell_to_text(value)
                        if unicodedata.category(character) != "Cc"
                    )
        elif op in {"lowercase_text", "uppercase_text", "proper_case_text", "reverse_text"}:
            operation = {
                "lowercase_text": "Lowercase Text",
                "uppercase_text": "Uppercase Text",
                "proper_case_text": "Capitalize Each Word",
                "reverse_text": "Reverse Text",
            }[op]
            transform_text = {
                "lowercase_text": str.lower,
                "uppercase_text": str.upper,
                "proper_case_text": str.title,
                "reverse_text": lambda value: value[::-1],
            }[op]
            total_output_bytes = 0
            for row in result.rows:
                value = row[column]
                if value is None or is_cell_error(value):
                    continue
                converted = transform_text(cell_to_text(value))
                try:
                    total_output_bytes += len(converted.encode("utf-8"))
                except UnicodeEncodeError as exc:
                    raise TransformationError(
                        f"{operation} found a value that cannot be encoded as UTF-8; replace the invalid value first."
                    ) from exc
                if total_output_bytes > MAX_EXPRESSION_OUTPUT_BYTES:
                    raise TransformationError(
                        f"{operation} exceeds the 80 MiB output-column limit."
                    )
                row[column] = converted

        _check_candidate_limits(result.headers, result.rows)
    # Later value transforms can invalidate an earlier conversion. Check the
    # final values too so the persisted model type always describes its cells.
    for column, target_type in column_types_after_steps(
        candidate.headers, validated_steps, output_headers=result.headers
    ).items():
        if target_type != "text":
            _convert_column(result.rows, column, target_type)
    return result


def canonical_column_type(type_name: str) -> str:
    """Return the current model type name for a supported conversion type."""
    return "decimal_number" if type_name == "number" else type_name


_IDENTIFIER_HEADER_WORDS = {
    "account", "code", "customer", "id", "key", "mobile", "no", "phone",
    "postal", "ref", "reference", "serial", "trn", "voucher", "zip",
}
_IDENTIFIER_HEADER_SUFFIXES = ("id", "key", "code", "ref", "reference", "number")
_LONG_INTEGER_TEXT = re.compile(r"^[+-]?\d{16,}$")
_LEADING_ZERO_INTEGER = re.compile(r"^[+-]?0\d+$")
_WHOLE_NUMBER_TEXT = re.compile(r"^[+-]?\d+$")


def infer_column_types(
    headers: list[str],
    rows: list[dict[str, Any]],
    *,
    sample_size: int = 200,
) -> dict[str, str]:
    """Infer conservative model types from a bounded sample of imported text.

    The first ``sample_size`` rows choose a candidate type. The complete column
    must also convert cleanly before the type is applied, and identifier-like
    fields stay text to preserve leading zeroes and large numeric keys.
    """
    if not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size < 1:
        raise ValueError("A type-detection sample must contain at least one row.")
    inferred = {header: "text" for header in headers}
    sample = rows[:sample_size]
    for header in headers:
        sample_cells = [
            row.get(header, "") for row in sample
            if row.get(header, "") not in (None, "")
            and not is_cell_error(row.get(header, ""))
        ]
        all_cells = [
            row.get(header, "") for row in rows
            if row.get(header, "") not in (None, "")
            and not is_cell_error(row.get(header, ""))
        ]
        sample_values = [
            cell_to_text(row.get(header, "")).strip()
            for row in sample
            if row.get(header, "") not in (None, "")
            and not is_cell_error(row.get(header, ""))
        ]
        all_values = [
            cell_to_text(row.get(header, "")).strip()
            for row in rows
            if row.get(header, "") not in (None, "")
            and not is_cell_error(row.get(header, ""))
        ]
        if not sample_values:
            continue

        native_type = _infer_native_type(sample_cells)
        if native_type is not None and _infer_native_type(all_cells) == native_type:
            # Preserve explicitly typed source columns, including numeric IDs.
            # Text identifiers still use the conservative header/leading-zero
            # checks below because their original type carries no type signal.
            inferred[header] = native_type
            continue
        if _is_identifier_column(header, all_values):
            continue

        lowered = {value.casefold() for value in sample_values}
        if lowered <= {"true", "false"}:
            candidate_type = "boolean"
        else:
            candidate_type = _infer_iso_temporal_type(sample_values)
            if candidate_type == "date" and _infer_iso_temporal_type(all_values) == "datetime":
                candidate_type = "datetime"
            if candidate_type is None:
                numeric_values = [_parse_number_for_inference(value) for value in sample_values]
                if all(value is not None for value in numeric_values):
                    whole_numbers = all(
                        value == value.to_integral_value()
                        and _WHOLE_NUMBER_TEXT.fullmatch(source) is not None
                        for value, source in zip(numeric_values, sample_values)
                    )
                    all_numeric_values = [_parse_number_for_inference(value) for value in all_values]
                    if not all(value is not None for value in all_numeric_values):
                        candidate_type = None
                    elif whole_numbers and all(
                        value == value.to_integral_value()
                        and _WHOLE_NUMBER_TEXT.fullmatch(source) is not None
                        for value, source in zip(all_numeric_values, all_values)
                    ):
                        candidate_type = "whole_number"
                    else:
                        candidate_type = "decimal_number"
        if (
            candidate_type is not None
            and count_conversion_errors(all_cells, candidate_type) == 0
        ):
            inferred[header] = candidate_type
    return inferred


def _infer_native_type(values: list[Any]) -> str | None:
    if not values:
        return None
    if all(isinstance(value, bool) for value in values):
        return "boolean"
    if all(isinstance(value, datetime) for value in values):
        return "datetime"
    if all(isinstance(value, date) and not isinstance(value, datetime) for value in values):
        return "date"
    if all(isinstance(value, time) for value in values):
        return "time"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "whole_number"
    if all(
        isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
        for value in values
    ):
        return "decimal_number"
    return None


def _is_identifier_column(header: str, values: list[str]) -> bool:
    words = re.findall(r"[a-z0-9]+", header.casefold())
    if _IDENTIFIER_HEADER_WORDS.intersection(words):
        return True
    compact = "".join(words)
    if compact.endswith(_IDENTIFIER_HEADER_SUFFIXES):
        return True
    return any(
        _LONG_INTEGER_TEXT.fullmatch(value) or _LEADING_ZERO_INTEGER.fullmatch(value)
        for value in values
    )


def _infer_iso_temporal_type(values: list[str]) -> str | None:
    try:
        for value in values:
            date.fromisoformat(value)
        return "date"
    except ValueError:
        pass
    try:
        parsed = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in values]
        if any("T" in value or " " in value for value in values):
            return "datetime"
        # Keep a consistently date-only ISO column as a date rather than
        # inferring midnight datetimes from Python's permissive parser.
        return "date" if all(value.date().isoformat() == source for value, source in zip(parsed, values)) else "datetime"
    except ValueError:
        pass
    # ``time.fromisoformat`` accepts compact strings such as ``"10"`` as
    # 10:00. Plain digit-only business values are much more often counts or
    # amounts, so require the hour/minute separator before considering a time.
    if any(":" not in value for value in values):
        return None
    try:
        for value in values:
            time.fromisoformat(value)
        return "time"
    except ValueError:
        return None


def _parse_number_for_inference(value: str) -> Decimal | None:
    try:
        number = Decimal(value)
    except (DecimalException, ValueError):
        return None
    return number if number.is_finite() else None


def column_types_after_steps(
    headers: list[str],
    steps: Any,
    *,
    output_headers: list[str] | None = None,
    initial_types: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return the column types produced by a validated transformation sequence."""
    supplied_types = initial_types or {}
    types = {
        header: canonical_column_type(supplied_types.get(header, "text"))
        for header in headers
    }
    validated_steps = validate_steps(steps)
    header_count: int | None = len(headers)
    header_names_known = True
    for step_index, step in enumerate(validated_steps):
        op = step["op"]
        if op in {"promote_headers", "demote_headers", "transpose_table"}:
            # Schema reshaping changes the fields; rebuilt columns default to text.
            types = {}
            header_names_known = False
            if op == "transpose_table":
                header_count = None
        elif op == "rename_column":
            column_type = types.pop(step["column"], "text")
            types[step["new_name"].strip()] = column_type
        elif op == "remove_column":
            types.pop(step["column"], None)
        elif op == "keep_columns":
            selected = set(step["columns"])
            types = {header: value for header, value in types.items() if header in selected}
        elif op == "reorder_columns":
            known_order = [column for column in step["columns"] if column in types]
            reordered_headers = _reordered_headers(list(types), known_order)
            types = {header: types[header] for header in reordered_headers}
        elif op == "duplicate_column":
            types[step["new_name"]] = types.get(step["column"], "text")
        elif op == "add_index_column":
            types[step["new_name"]] = "whole_number"
        elif op == "merge_columns":
            selected = set(step["columns"]) & set(types)
            new_types: dict[str, str] = {}
            first_index = (
                min(list(types).index(column) for column in selected)
                if selected else len(types)
            )
            for index, (header, column_type) in enumerate(types.items()):
                if index == first_index:
                    new_types[step["new_name"]] = "text"
                if header not in selected:
                    new_types[header] = column_type
            if not selected:
                new_types[step["new_name"]] = "text"
            types = new_types
        elif op in {"convert_type", "convert_type_using_locale"}:
            types[step["column"]] = canonical_column_type(step["type"])
        elif op in {"clean_text", "lowercase_text", "uppercase_text", "proper_case_text", "reverse_text"} and types.get(step["column"], "text") != "text":
            operation = {
                "clean_text": "Clean Text",
                "lowercase_text": "Lowercase Text",
                "uppercase_text": "Uppercase Text",
                "proper_case_text": "Capitalize Each Word",
                "reverse_text": "Reverse Text",
            }[op]
            raise TransformationError(
                f"{operation} requires a text-typed column. Place it before a type conversion."
            )
        elif op == "extract_text_by_delimiter" and types.get(step["column"], "text") != "text":
            raise TransformationError(
                "Extract Text Before/After Delimiter requires a text-typed column. "
                "Place it before a type conversion."
            )
        elif op == "extract_text_between_delimiters" and types.get(step["column"], "text") != "text":
            raise TransformationError(
                "Extract Text Between Delimiters requires a text-typed column. "
                "Place it before a type conversion."
            )
        elif op == "split_column":
            types.pop(step["column"], None)
            types[f"{step['column']}.1"] = "text"
            types[f"{step['column']}.2"] = "text"
        elif op == "split_column_by_each_delimiter":
            types.pop(step["column"], None)
            types[f"{step['column']}.1"] = "text"
            types[f"{step['column']}.2"] = "text"
        elif op == "split_column_by_positions":
            source_column = step["column"]
            split_types: dict[str, str] = {}
            for header, column_type in types.items():
                if header == source_column:
                    split_types.update({
                        f"{source_column}.{index}": "text"
                        for index in range(1, len(step["positions"]) + 1)
                    })
                else:
                    split_types[header] = column_type
            types = split_types
        elif op == "split_column_to_rows":
            types[step["column"]] = "text"
        elif op == "group_by":
            previous_types = types
            types = {column: previous_types.get(column, "text") for column in step["columns"]}
            for aggregate in step["aggregations"]:
                operation = aggregate["operation"]
                if operation in _GROUP_ROW_OPERATIONS or operation == "count_distinct_values":
                    aggregate_type = "whole_number"
                elif operation in {"average", "median"}:
                    aggregate_type = "decimal_number"
                elif operation == "sum":
                    source_type = previous_types.get(aggregate["column"], "text")
                    aggregate_type = (
                        "whole_number" if source_type == "whole_number" else "decimal_number"
                    )
                else:
                    aggregate_type = previous_types.get(aggregate["column"], "text")
                types[aggregate["new_name"]] = aggregate_type
        elif op in {"unpivot_columns", "unpivot_other_columns"}:
            selected = set(step["columns"])
            if op == "unpivot_columns":
                retained = [header for header in types if header not in selected]
                unpivoted = [header for header in types if header in selected]
            else:
                retained = [header for header in types if header in selected]
                unpivoted = [header for header in types if header not in selected]
            unpivoted_types = {types[header] for header in unpivoted}
            types = {header: types[header] for header in retained}
            types[step["attribute_name"]] = "text"
            types[step["value_name"]] = (
                next(iter(unpivoted_types))
                if len(unpivoted_types) == 1 else "text"
            )
        elif op == "pivot_column":
            attribute_column = step["attribute_column"]
            value_column = step["value_column"]
            types = {
                header: column_type
                for header, column_type in types.items()
                if header not in {attribute_column, value_column}
            }
            if (
                output_headers is not None
                and step["aggregation"] in {"count_all", "count_non_blank"}
            ):
                if header_names_known:
                    # Data-derived category fields are the new names absent
                    # from the retained key-column type map.
                    for header in output_headers:
                        if header not in types:
                            types[header] = "whole_number"
                elif (
                    header_count is not None
                    and all(
                        following["op"] in {
                            "filter_rows", "filter_rows_advanced", "remove_blank_rows",
                            "sort_rows", "sort_rows_by_columns", "keep_top_rows",
                            "keep_bottom_rows", "keep_range_rows", "remove_top_rows",
                            "remove_bottom_rows", "remove_alternate_rows", "convert_type",
                            "convert_type_using_locale", "fill_down", "fill_up",
                            "trim_text", "clean_text", "lowercase_text", "uppercase_text",
                            "proper_case_text", "reverse_text", "replace_value",
                            "extract_text_by_delimiter", "extract_text_between_delimiters",
                            "split_column_to_rows",
                        }
                        for following in validated_steps[step_index + 1:]
                    )
                ):
                    # After header promotion the key names are not known here.
                    # Pivot always appends its data-derived categories after
                    # its retained key columns, so only that output suffix is
                    # safe to type.
                    key_count = max(0, header_count - 2)
                    for header in output_headers[key_count:]:
                        types[header] = "whole_number"
        elif op == "add_custom_column":
            types[step["name"]] = step.get("output_type", "text")
        elif op == "conditional_column":
            types[step["name"]] = "text"

        # Keep a conservative schema width so a Pivot after Promote Headers can
        # distinguish retained keys from appended data-derived categories.
        if op == "keep_columns":
            header_count = len(step["columns"])
        elif op == "remove_column" and header_count is not None:
            header_count = max(0, header_count - 1)
        elif op in {"duplicate_column", "add_index_column", "add_custom_column", "conditional_column"}:
            if header_count is not None:
                header_count += 1
        elif op == "merge_columns" and header_count is not None:
            header_count += 1 - len(step["columns"])
        elif op == "split_column" and header_count is not None:
            header_count += 1
        elif op == "split_column_by_positions" and header_count is not None:
            header_count += len(step["positions"]) - 1
        elif op == "split_column_by_each_delimiter":
            header_count = None
        elif op == "group_by":
            header_count = len(step["columns"]) + len(step["aggregations"])
        elif op == "unpivot_columns" and header_count is not None:
            header_count += 2 - len(step["columns"])
        elif op == "unpivot_other_columns":
            header_count = len(step["columns"]) + 2
        elif op == "pivot_column":
            header_count = None
    if output_headers is not None:
        return {header: types.get(header, "text") for header in output_headers}
    return types


def _merge_columns(
    candidate: ImportCandidate,
    columns: list[str],
    separator: str,
    new_name: str,
) -> ImportCandidate:
    """Combine selected text columns, preserving their displayed order."""
    positions = [_column_index(candidate.headers, column) for column in columns]
    selected = set(columns)
    first_position = min(positions)
    collision = next(
        (header for header in candidate.headers if header == new_name and header not in selected),
        None,
    )
    if collision is not None:
        raise TransformationError(
            f"Cannot merge columns: output column {new_name!r} already exists."
        )

    try:
        separator_bytes = len(separator.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise TransformationError("The merge separator must be valid UTF-8 text.") from exc
    headers: list[str] = []
    for index, header in enumerate(candidate.headers):
        if index == first_position:
            headers.append(new_name)
        if header not in selected:
            headers.append(header)

    rows: list[dict[str, Any]] = []
    total_output_bytes = 0
    for row in candidate.rows:
        values = [row[column] for column in columns]
        existing_error = next((value for value in values if is_cell_error(value)), None)
        text_values = [
            "" if value is None or value == "" else cell_to_text(value)
            for value in values
            if not is_cell_error(value)
        ]
        merged_value: Any = existing_error if existing_error is not None else separator.join(text_values)
        try:
            merged_bytes = len(cell_to_text(merged_value).encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise TransformationError(
                f"A value in the merged columns cannot be encoded as UTF-8 in row {len(rows) + 1}."
            ) from exc
        if existing_error is None:
            merged_bytes = sum(len(value.encode("utf-8")) for value in text_values)
            merged_bytes += separator_bytes * (len(values) - 1)
        total_output_bytes += merged_bytes
        if total_output_bytes > MAX_EXPRESSION_OUTPUT_BYTES:
            raise TransformationError("The merged column exceeds the 80 MiB output limit.")
        rebuilt: dict[str, Any] = {}
        for index, header in enumerate(candidate.headers):
            if index == first_position:
                rebuilt[new_name] = merged_value
            if header not in selected:
                rebuilt[header] = row[header]
        rows.append(rebuilt)

    return ImportCandidate(
        kind=candidate.kind,
        headers=headers,
        rows=rows,
        options=candidate.options,
        notices=candidate.notices,
    )


def _split_column(candidate: ImportCandidate, column: str, delimiter: str) -> None:
    """Split at the leftmost delimiter, replacing the source with two text columns."""
    column_index = _column_index(candidate.headers, column)
    first_name = f"{column}.1"
    second_name = f"{column}.2"
    remaining_headers = [header for header in candidate.headers if header != column]
    collision = next(
        (name for name in (first_name, second_name) if name in remaining_headers),
        None,
    )
    if collision is not None:
        raise TransformationError(
            f"Cannot split {column!r}: output column {collision!r} already exists."
        )

    headers = list(candidate.headers)
    headers[column_index:column_index + 1] = [first_name, second_name]
    rows: list[dict[str, Any]] = []
    for row in candidate.rows:
        value = row[column]
        if value is None or is_cell_error(value):
            first, second = value, value
        else:
            first, found, remainder = cell_to_text(value).partition(delimiter)
            second = remainder if found else ""
        rebuilt: dict[str, Any] = {}
        for header in candidate.headers:
            if header == column:
                rebuilt[first_name] = first
                rebuilt[second_name] = second
            else:
                rebuilt[header] = row[header]
        rows.append(rebuilt)
    candidate.headers = headers
    candidate.rows = rows


def _find_delimiter_occurrence(
    value: str, delimiter: str, occurrence: int, start_from: int = 0
) -> int:
    """Return the requested non-overlapping delimiter position, or -1."""
    delimiter_index = -1
    search_from = start_from
    for _ in range(occurrence + 1):
        delimiter_index = value.find(delimiter, search_from)
        if delimiter_index < 0:
            return -1
        search_from = delimiter_index + len(delimiter)
    return delimiter_index


def _extract_text_by_delimiter(
    candidate: ImportCandidate,
    column: str,
    side: str,
    delimiter: str,
    occurrence: int,
) -> None:
    """Keep text before or after one zero-based delimiter occurrence."""
    _column_index(candidate.headers, column)
    for row_index, row in enumerate(candidate.rows, 1):
        value = row[column]
        if value is None or value == "" or is_cell_error(value):
            continue
        value = cell_to_text(value)

        delimiter_index = _find_delimiter_occurrence(value, delimiter, occurrence)
        if delimiter_index < 0:
            raise TransformationError(
                f"Could not find zero-based delimiter occurrence {occurrence} "
                f"in row {row_index} of column {column!r}."
            )

        if side == "before":
            row[column] = value[:delimiter_index]
        else:
            row[column] = value[delimiter_index + len(delimiter):]


def _extract_text_between_delimiters(
    candidate: ImportCandidate,
    column: str,
    start_delimiter: str,
    end_delimiter: str,
    start_occurrence: int,
    end_occurrence: int,
) -> None:
    """Keep text between selected start and following end delimiter occurrences."""
    _column_index(candidate.headers, column)
    for row_index, row in enumerate(candidate.rows, 1):
        value = row[column]
        if value is None or value == "" or is_cell_error(value):
            continue
        value = cell_to_text(value)

        start_index = _find_delimiter_occurrence(
            value, start_delimiter, start_occurrence
        )
        if start_index < 0:
            raise TransformationError(
                f"Could not find start delimiter occurrence {start_occurrence} "
                f"in row {row_index} of column {column!r}."
            )
        content_start = start_index + len(start_delimiter)
        end_index = _find_delimiter_occurrence(
            value, end_delimiter, end_occurrence, content_start
        )
        if end_index < 0:
            raise TransformationError(
                f"Could not find end delimiter occurrence {end_occurrence} after "
                f"start delimiter occurrence {start_occurrence} in row {row_index} "
                f"of column {column!r}."
            )
        row[column] = value[content_start:end_index]


def _split_column_by_each_delimiter(
    candidate: ImportCandidate, column: str, delimiter: str
) -> None:
    """Split at every delimiter into numbered text columns, replacing the source."""
    column_index = _column_index(candidate.headers, column)
    # Keep at least two outputs, matching the standard split-column operation;
    # rows with fewer segments receive blank values in the remaining columns.
    output_count = max(
        2,
        max((
            cell_to_text(row[column]).count(delimiter) + 1
            for row in candidate.rows
            if row[column] is not None and not is_cell_error(row[column])
        ), default=1),
    )
    if output_count > MAX_COLUMNS - len(candidate.headers) + 1:
        raise TransformationError(
            f"Splitting {column!r} exceeds the {MAX_COLUMNS}-column import limit."
        )
    final_column_count = len(candidate.headers) - 1 + output_count
    if len(candidate.rows) * final_column_count > MAX_CELLS:
        raise TransformationError(
            f"Splitting {column!r} exceeds the {MAX_CELLS:,}-cell import limit."
        )

    output_names = [f"{column}.{index}" for index in range(1, output_count + 1)]
    remaining_headers = [header for header in candidate.headers if header != column]
    collision = next((name for name in output_names if name in remaining_headers), None)
    if collision is not None:
        raise TransformationError(
            f"Cannot split {column!r}: output column {collision!r} already exists."
        )

    headers = list(candidate.headers)
    headers[column_index:column_index + 1] = output_names
    rows: list[dict[str, Any]] = []
    for row in candidate.rows:
        value = row[column]
        if value is None or is_cell_error(value):
            parts = [value] * output_count
        else:
            parts = cell_to_text(value).split(delimiter)
            parts.extend([""] * (output_count - len(parts)))
        rebuilt: dict[str, Any] = {}
        for header in candidate.headers:
            if header == column:
                rebuilt.update(zip(output_names, parts))
            else:
                rebuilt[header] = row[header]
        rows.append(rebuilt)

    candidate.headers = headers
    candidate.rows = rows


def _split_column_by_positions(
    candidate: ImportCandidate, column: str, positions: list[int]
) -> None:
    """Split a text column into fixed-start text segments, replacing its field."""
    column_index = _column_index(candidate.headers, column)
    output_names = [f"{column}.{index}" for index in range(1, len(positions) + 1)]
    remaining_headers = [header for header in candidate.headers if header != column]
    collision = next((name for name in output_names if name in remaining_headers), None)
    if collision is not None:
        raise TransformationError(
            f"Cannot split {column!r}: output column {collision!r} already exists."
        )

    headers = list(candidate.headers)
    headers[column_index:column_index + 1] = output_names
    if len(headers) > MAX_COLUMNS:
        raise TransformationError(
            f"Splitting {column!r} exceeds the {MAX_COLUMNS}-column import limit."
        )
    if len(candidate.rows) * len(headers) > MAX_CELLS:
        raise TransformationError(
            f"Splitting {column!r} exceeds the {MAX_CELLS:,}-cell import limit."
        )

    rows: list[dict[str, Any]] = []
    for row in candidate.rows:
        value = row[column]
        if value is None or is_cell_error(value):
            parts = [value] * (len(positions) + 1)
            rebuilt: dict[str, Any] = {}
            for header in candidate.headers:
                if header == column:
                    rebuilt.update(zip(output_names, parts))
                else:
                    rebuilt[header] = row[header]
            rows.append(rebuilt)
            continue
        value = cell_to_text(value)
        parts = [
            value[start:end]
            for start, end in zip(positions, positions[1:])
        ]
        parts.append(value[positions[-1]:])
        rebuilt: dict[str, Any] = {}
        for header in candidate.headers:
            if header == column:
                rebuilt.update(zip(output_names, parts))
            else:
                rebuilt[header] = row[header]
        rows.append(rebuilt)

    candidate.headers = headers
    candidate.rows = rows


def _split_column_to_rows(
    candidate: ImportCandidate, column: str, delimiter: str
) -> None:
    """Split at every delimiter, repeating the other cell values on each row."""
    _column_index(candidate.headers, column)
    rows: list[dict[str, Any]] = []
    for row in candidate.rows:
        value = row[column]
        if value is None or is_cell_error(value):
            parts = [value]
        else:
            parts = cell_to_text(value).split(delimiter)
        part_count = len(parts)
        expanded_count = len(rows) + part_count
        if expanded_count > MAX_DATA_ROWS:
            raise TransformationError(
                f"Splitting into rows exceeds the {MAX_DATA_ROWS:,}-row limit."
            )
        if expanded_count * len(candidate.headers) > MAX_CELLS:
            raise TransformationError(
                f"Splitting into rows exceeds the {MAX_CELLS:,}-cell limit."
            )
        for part in parts:
            expanded = dict(row)
            expanded[column] = part
            rows.append(expanded)
    candidate.rows = rows


def _group_by(
    candidate: ImportCandidate,
    columns: list[str],
    aggregations: list[dict[str, str]],
) -> ImportCandidate:
    """Group rows by exact keys and calculate flat scalar aggregate columns."""
    for column in columns:
        _column_index(candidate.headers, column)
    result_headers = [*columns, *(aggregate["new_name"] for aggregate in aggregations)]
    if len(result_headers) > MAX_COLUMNS:
        raise TransformationError(f"Grouping exceeds the {MAX_COLUMNS}-column import limit.")
    for aggregate in aggregations:
        if "column" in aggregate:
            _column_index(candidate.headers, aggregate["column"])

    grouped: dict[
        tuple[tuple[Any, ...], ...], list[tuple[int, dict[str, Any]]]
    ] = {}
    key_values_by_key: dict[tuple[tuple[Any, ...], ...], tuple[Any, ...]] = {}
    for row_index, row in enumerate(candidate.rows, 1):
        key_values = tuple(row[column] for column in columns)
        error_column = next(
            (column for column, value in zip(columns, key_values) if is_cell_error(value)),
            None,
        )
        if error_column is not None:
            raise TransformationError(
                f"Cannot group: row {row_index} of group key column {error_column!r} contains an error."
            )
        key = tuple(cell_key(value) for value in key_values)
        key_values_by_key.setdefault(key, key_values)
        grouped.setdefault(key, []).append((row_index, row))
    if len(grouped) * len(result_headers) > MAX_CELLS:
        raise TransformationError(f"Grouping exceeds the {MAX_CELLS:,}-cell import limit.")

    result_rows: list[dict[str, Any]] = []
    for key, members in grouped.items():
        result = {
            column: value
            for column, value in zip(columns, key_values_by_key[key])
        }
        for aggregate in aggregations:
            result[aggregate["new_name"]] = _aggregate_group(
                aggregate, members, candidate.headers
            )
        result_rows.append(result)

    return ImportCandidate(
        kind=candidate.kind,
        headers=result_headers,
        rows=result_rows,
        options=candidate.options,
        notices=candidate.notices,
    )


def _unpivot_columns(
    candidate: ImportCandidate,
    columns: list[str],
    attribute_name: str,
    value_name: str,
    *,
    unpivot_other: bool,
) -> ImportCandidate:
    """Convert selected columns (or all but selected columns) into attribute/value rows."""
    selected = set(columns)
    for column in columns:
        _column_index(candidate.headers, column)
    if unpivot_other:
        retained_headers = [header for header in candidate.headers if header in selected]
        pivot_headers = [header for header in candidate.headers if header not in selected]
    else:
        pivot_headers = [header for header in candidate.headers if header in selected]
        retained_headers = [header for header in candidate.headers if header not in selected]
    if not pivot_headers:
        raise TransformationError("Select at least one column to unpivot.")
    collisions = [
        name for name in (attribute_name, value_name) if name in retained_headers
    ]
    if collisions:
        raise TransformationError(
            f"Cannot unpivot: output column {collisions[0]!r} already exists."
        )
    result_headers = [*retained_headers, attribute_name, value_name]
    if len(result_headers) > MAX_COLUMNS:
        raise TransformationError(f"Unpivoting exceeds the {MAX_COLUMNS}-column import limit.")
    result_row_count = sum(
        1
        for row in candidate.rows
        for column in pivot_headers
        if row[column] is not None
    )
    if result_row_count > MAX_DATA_ROWS:
        raise TransformationError(
            f"Unpivoting exceeds the {MAX_DATA_ROWS:,}-row import limit."
        )
    if result_row_count * len(result_headers) > MAX_CELLS:
        raise TransformationError(
            f"Unpivoting exceeds the {MAX_CELLS:,}-cell import limit."
        )

    result_rows: list[dict[str, Any]] = []
    for row in candidate.rows:
        for column in pivot_headers:
            value = row[column]
            if value is None:
                continue
            unpivoted = {header: row[header] for header in retained_headers}
            unpivoted[attribute_name] = column
            unpivoted[value_name] = value
            result_rows.append(unpivoted)
    return ImportCandidate(
        kind=candidate.kind,
        headers=result_headers,
        rows=result_rows,
        options=candidate.options,
        notices=candidate.notices,
    )


def _pivot_column(
    candidate: ImportCandidate,
    attribute_column: str,
    value_column: str,
    aggregation: str,
) -> ImportCandidate:
    """Pivot an attribute column into first-seen scalar columns."""
    _column_index(candidate.headers, attribute_column)
    _column_index(candidate.headers, value_column)
    key_headers = [
        header for header in candidate.headers
        if header not in {attribute_column, value_column}
    ]

    pivot_values: list[str] = []
    seen_values: dict[str, tuple[Any, ...]] = {}
    for row_index, row in enumerate(candidate.rows, 1):
        value = row[attribute_column]
        if is_cell_error(value):
            raise TransformationError(
                f"Cannot pivot: row {row_index} of {attribute_column!r} contains an error."
            )
        value_text = cell_to_text(value)
        if not value_text.strip():
            raise TransformationError(
                f"Cannot pivot: row {row_index} has a blank value in {attribute_column!r}."
            )
        value_key = cell_key(value)
        previous_key = seen_values.get(value_text)
        if previous_key is not None and previous_key != value_key:
            raise TransformationError(
                f"Cannot pivot: distinct typed categories in {attribute_column!r} "
                f"produce the same output column {value_text!r}; convert the column to text first."
            )
        if previous_key is None:
            seen_values[value_text] = value_key
            pivot_values.append(value_text)
    if not pivot_values and not key_headers:
        raise TransformationError("Cannot pivot an empty table without remaining key columns.")

    collisions = [value for value in pivot_values if value in key_headers]
    if collisions:
        raise TransformationError(
            f"Cannot pivot: output column {collisions[0]!r} conflicts with an existing key column."
        )
    result_headers = [*key_headers, *pivot_values]
    if len(result_headers) > MAX_COLUMNS:
        raise TransformationError(f"Pivoting exceeds the {MAX_COLUMNS}-column import limit.")

    grouped: dict[
        tuple[tuple[Any, ...], ...],
        dict[str, list[tuple[int, dict[str, Any]]]],
    ] = {}
    key_values_by_key: dict[tuple[tuple[Any, ...], ...], tuple[Any, ...]] = {}
    for row_index, row in enumerate(candidate.rows, 1):
        key_values = tuple(row[header] for header in key_headers)
        error_column = next(
            (header for header, value in zip(key_headers, key_values) if is_cell_error(value)),
            None,
        )
        if error_column is not None:
            raise TransformationError(
                f"Cannot pivot: row {row_index} of key column {error_column!r} contains an error."
            )
        key = tuple(cell_key(value) for value in key_values)
        key_values_by_key.setdefault(key, key_values)
        group = grouped.setdefault(key, {})
        group.setdefault(cell_to_text(row[attribute_column]), []).append((row_index, row))
    if len(grouped) > MAX_DATA_ROWS:
        raise TransformationError(f"Pivoting exceeds the {MAX_DATA_ROWS:,}-row import limit.")
    if len(grouped) * len(result_headers) > MAX_CELLS:
        raise TransformationError(f"Pivoting exceeds the {MAX_CELLS:,}-cell import limit.")

    result_rows: list[dict[str, Any]] = []
    for key, cells in grouped.items():
        result = {
            header: value
            for header, value in zip(key_headers, key_values_by_key[key])
        }
        for pivot_value in pivot_values:
            members = cells.get(pivot_value, [])
            if not members:
                result[pivot_value] = None
            elif aggregation == "none":
                if len(members) != 1:
                    raise TransformationError(
                        "Cannot pivot without aggregation: multiple values exist for "
                        f"a row-key/category pair ({pivot_value!r})."
                    )
                result[pivot_value] = members[0][1][value_column]
            elif aggregation == "count_all":
                result[pivot_value] = len(members)
            elif aggregation == "count_non_blank":
                result[pivot_value] = sum(
                    row[value_column] is not None and row[value_column] != ""
                    for _, row in members
                )
            else:
                result[pivot_value] = _aggregate_group(
                    {"operation": aggregation, "column": value_column},
                    members,
                    candidate.headers,
                )
        result_rows.append(result)

    if key_headers:
        result_rows = _sort_rows(result_rows, key_headers[0], "asc")
    return ImportCandidate(
        kind=candidate.kind,
        headers=result_headers,
        rows=result_rows,
        options=candidate.options,
        notices=candidate.notices,
    )


def _add_conditional_column(
    candidate: ImportCandidate,
    name: str,
    clauses: list[dict[str, str]],
    else_value: str,
    else_kind: str,
) -> ImportCandidate:
    """Append the first matching literal or source-column value for every row."""
    if name in candidate.headers:
        raise TransformationError(f"Column {name!r} already exists.")
    if len(candidate.headers) >= MAX_COLUMNS:
        raise TransformationError(
            f"Adding a conditional column exceeds the {MAX_COLUMNS}-column limit."
        )
    if len(candidate.rows) * (len(candidate.headers) + 1) > MAX_CELLS:
        raise TransformationError(
            f"Adding a conditional column exceeds the {MAX_CELLS:,}-cell limit."
        )

    required_columns: set[str] = set()
    for clause in clauses:
        required_columns.add(clause["column"])
        if clause["test_value_kind"] == "column":
            required_columns.add(clause["test_value"])
        if clause["output_kind"] == "column":
            required_columns.add(clause["output"])
    if else_kind == "column":
        required_columns.add(else_value)
    missing = sorted(required_columns - set(candidate.headers))
    if missing:
        raise TransformationError(
            f"Conditional column refers to missing column {missing[0]!r}."
        )

    for row in candidate.rows:
        result = (
            else_value
            if else_kind == "value"
            else _conditional_output_text(row[else_value])
        )
        for clause in clauses:
            left = row[clause["column"]]
            right = (
                row[clause["test_value"]]
                if clause["test_value_kind"] == "column"
                else None
                if clause["test_value_kind"] == "null"
                else clause["test_value"]
            )
            if is_cell_error(left) or is_cell_error(right):
                result = left if is_cell_error(left) else right
                break
            if _conditional_clause_matches(left, right, clause["operator"]):
                result = (
                    _conditional_output_text(row[clause["output"]])
                    if clause["output_kind"] == "column"
                    else clause["output"]
                )
                break
        if is_cell_error(result):
            row[name] = result
            continue
        row[name] = result
    return ImportCandidate(
        kind=candidate.kind,
        headers=[*candidate.headers, name],
        rows=candidate.rows,
        options=candidate.options,
        notices=candidate.notices,
    )


def _conditional_output_text(value: Any) -> Any:
    """Return text at the conditional-column boundary without flattening Null or Error."""
    if value is None or is_cell_error(value):
        return value
    try:
        return cell_to_text(value)
    except TypeError as exc:
        raise TransformationError(str(exc)) from exc


def _conditional_clause_matches(left: Any, right: Any, operator: str) -> bool:
    if is_cell_error(left) or is_cell_error(right):
        error = left if is_cell_error(left) else right
        raise TransformationError(f"Conditional Column encountered a cell error: {error.message}")
    if isinstance(left, bool) and isinstance(right, str):
        boolean_literal = right.casefold()
        if boolean_literal in {"true", "false"}:
            right = boolean_literal == "true"
    if operator in {"equals", "not_equals"}:
        if left is None or right is None:
            matched = left is None and right is None
        elif isinstance(left, (int, float, Decimal)) and not isinstance(left, bool):
            try:
                matched = _parse_number(left) == _parse_number(right)
            except TransformationError:
                matched = left == right
        else:
            matched = left == right
        return matched if operator == "equals" else not matched
    if left is None or right is None:
        return operator in {"does_not_contain", "does_not_begin_with", "does_not_end_with"}
    if operator == "equals":
        return left == right
    if operator == "not_equals":
        return left != right
    if operator in {"contains", "does_not_contain"}:
        matched = cell_to_text(right) in cell_to_text(left)
        return matched if operator == "contains" else not matched
    if operator in {"begins_with", "does_not_begin_with"}:
        matched = cell_to_text(left).startswith(cell_to_text(right))
        return matched if operator == "begins_with" else not matched
    if operator in {"ends_with", "does_not_end_with"}:
        matched = cell_to_text(left).endswith(cell_to_text(right))
        return matched if operator == "ends_with" else not matched

    try:
        left_number, right_number = _parse_number(left), _parse_number(right)
    except TransformationError:
        left_value, right_value = cell_to_text(left), cell_to_text(right)
    else:
        left_value, right_value = left_number, right_number
    if operator == "greater_than":
        return left_value > right_value
    if operator == "greater_than_or_equal":
        return left_value >= right_value
    if operator == "less_than":
        return left_value < right_value
    if operator == "less_than_or_equal":
        return left_value <= right_value
    raise TransformationError(f"Unsupported conditional operator {operator!r}.")


def _add_custom_column(
    candidate: ImportCandidate,
    name: str,
    expression: str,
    parameters: dict[str, Any] | None = None,
    *,
    output_type: str = "text",
    query_functions: dict[str, tuple[dict[str, str], tuple[Any, ...]]] | None = None,
) -> ImportCandidate:
    """Evaluate one bounded M-style formula against each row and append its result."""
    if name in candidate.headers:
        raise TransformationError(f"Column {name!r} already exists.")
    if len(candidate.headers) >= MAX_COLUMNS:
        raise TransformationError(f"Adding a custom column exceeds the {MAX_COLUMNS}-column limit.")
    if len(candidate.rows) * (len(candidate.headers) + 1) > MAX_CELLS:
        raise TransformationError(f"Adding a custom column exceeds the {MAX_CELLS:,}-cell limit.")
    parameter_values = parameters if parameters is not None else {}
    try:
        function_map = query_functions or {}
        formula = compile_expression(
            expression,
            allowed_symbols=set(parameter_values),
            function_names=set(function_map),
        )
    except PowerQueryExpressionError as exc:
        raise TransformationError(f"Custom column formula: {exc}") from exc
    missing = sorted(referenced_columns(formula) - set(candidate.headers))
    if missing:
        raise TransformationError(
            f"Custom column formula refers to missing column {missing[0]!r}."
        )

    total_output_bytes = 0
    referenced = referenced_columns(formula)
    for row_index, row in enumerate(candidate.rows, 1):
        propagated_error = next(
            (row[column] for column in referenced if is_cell_error(row[column])),
            None,
        )
        if propagated_error is not None:
            row[name] = propagated_error
            continue
        try:
            value = evaluate_expression(
                formula, row, parameter_values, function_map
            )
            if output_type != "text":
                from analytics_studio.query_functions import (
                    QueryFunctionError,
                    validate_typed_scalar,
                )
                try:
                    value = validate_typed_scalar(output_type, value)
                except QueryFunctionError as exc:
                    raise PowerQueryExpressionError(str(exc)) from exc
            result_text = expression_value_to_text(value)
            total_output_bytes += len(result_text.encode("utf-8"))
            if total_output_bytes > MAX_EXPRESSION_OUTPUT_BYTES:
                raise PowerQueryExpressionError(
                    "The custom-column output exceeds the 80 MiB total limit."
                )
            row[name] = (
                None if value is None else result_text
            ) if output_type == "text" else value
        except PowerQueryExpressionError as exc:
            raise TransformationError(
                f"Custom column {name!r}, row {row_index}: {exc}"
            ) from exc
    return ImportCandidate(
        kind=candidate.kind,
        headers=[*candidate.headers, name],
        rows=candidate.rows,
        options=candidate.options,
        notices=candidate.notices,
    )


def _parameter_filter_text(value: Any) -> str:
    """Normalize a typed parameter to the table model's comparison text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _aggregate_group(
    aggregate: dict[str, str],
    members: list[tuple[int, dict[str, Any]]],
    headers: list[str],
) -> Any:
    operation = aggregate["operation"]
    if operation == "count_rows":
        return len(members)
    if operation in {
        "count_distinct_rows", "count_distinct_values", "sum", "average",
        "median", "min", "max",
    }:
        checked_columns = headers if operation == "count_distinct_rows" else [aggregate["column"]]
        first_error = next(
            (
                row[column]
                for _, row in members
                for column in checked_columns
                if is_cell_error(row[column])
            ),
            None,
        )
        if first_error is not None:
            return first_error
    if operation == "count_distinct_rows":
        return len({
            tuple(cell_key(row[header]) for header in headers)
            for _, row in members
        })
    column = aggregate["column"]
    if operation == "count_distinct_values":
        return len({cell_key(row[column]) for _, row in members})
    if operation in {"sum", "average", "median"}:
        values = [
            _parse_row_number(row[column], row_index, column)
            for row_index, row in members
            if row[column] is not None and row[column] != ""
        ]
        if not values:
            return None
        with localcontext() as context:
            context.prec = _aggregate_precision(values)
            context.Emax = MAX_EMAX
            context.Emin = MIN_EMIN
            try:
                if operation == "sum":
                    result = sum(values, Decimal(0))
                elif operation == "average":
                    result = sum(values, Decimal(0)) / Decimal(len(values))
                else:
                    ordered = sorted(values)
                    middle = len(ordered) // 2
                    if len(ordered) % 2:
                        result = ordered[middle]
                    else:
                        result = (ordered[middle - 1] + ordered[middle]) / Decimal(2)
            except DecimalException as exc:
                raise TransformationError(
                    "The numeric aggregation result exceeds the supported range."
                ) from exc
        return result

    non_empty = [
        row[column] for _, row in members
        if row[column] is not None and row[column] != ""
    ]
    if not non_empty:
        return None
    numeric_values: list[tuple[Any, Decimal]] = []
    for value in non_empty:
        try:
            numeric_values.append((value, _parse_number(value)))
        except TransformationError:
            numeric_values = []
            break
    if numeric_values:
        selected = min(numeric_values, key=lambda item: item[1]) if operation == "min" else max(
            numeric_values, key=lambda item: item[1]
        )
        return selected[0]
    return min(non_empty, key=lambda value: cell_to_text(value).casefold()) if operation == "min" else max(
        non_empty, key=lambda value: cell_to_text(value).casefold()
    )


def _aggregate_precision(values: list[Decimal]) -> int:
    non_zero = [value for value in values if value]
    if not non_zero:
        return 28
    required = max(value.adjusted() for value in non_zero) - min(
        value.as_tuple().exponent for value in non_zero
    ) + len(str(len(values))) + 2
    if required > MAX_GROUP_DECIMAL_PRECISION:
        raise TransformationError(
            "The numeric range is too large to aggregate safely at the supported precision."
        )
    return max(28, required)


def _remove_duplicates(
    headers: list[str],
    rows: list[dict[str, Any]],
    columns: list[str] | None = None,
) -> list[dict[str, Any]]:
    key_columns = _duplicate_key_columns(headers, columns)
    seen: set[tuple[tuple[Any, ...], ...]] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = tuple(cell_key(row[header]) for header in key_columns)
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


def _keep_duplicates(
    headers: list[str],
    rows: list[dict[str, Any]],
    columns: list[str],
) -> list[dict[str, Any]]:
    key_columns = _duplicate_key_columns(headers, columns)
    key_for_row = lambda row: tuple(cell_key(row[column]) for column in key_columns)
    counts = Counter(key_for_row(row) for row in rows)
    return [
        row for row in rows
        if counts[key_for_row(row)] > 1
    ]


def _duplicate_key_columns(
    headers: list[str],
    columns: list[str] | None,
) -> list[str]:
    key_columns = columns if columns is not None else headers
    missing = next((column for column in key_columns if column not in headers), None)
    if missing is not None:
        raise TransformationError(f"Column {missing!r} does not exist.")
    return key_columns


def _keep_columns(candidate: ImportCandidate, columns: list[str]) -> ImportCandidate:
    selected = set(columns)
    missing = next((column for column in columns if column not in candidate.headers), None)
    if missing is not None:
        raise TransformationError(f"Column {missing!r} does not exist.")
    headers = [header for header in candidate.headers if header in selected]
    return ImportCandidate(
        kind=candidate.kind,
        headers=headers,
        rows=[{header: row[header] for header in headers} for row in candidate.rows],
        options=candidate.options,
        notices=candidate.notices,
    )


def _promote_headers(candidate: ImportCandidate) -> ImportCandidate:
    """Use the first data row's values as unique column names."""
    if not candidate.rows:
        raise TransformationError(
            "Cannot use the first row as headers because the table has no data rows."
        )
    first_row_values = [candidate.rows[0][header] for header in candidate.headers]
    header_error = next((value for value in first_row_values if is_cell_error(value)), None)
    if header_error is not None:
        raise TransformationError(
            f"Cannot promote headers because the first row contains an error: {header_error.message}"
        )
    promoted = normalize_promoted_headers(
        [cell_to_text(value) for value in first_row_values],
        len(candidate.headers),
    )
    rows = [
        {
            new_header: row[old_header]
            for old_header, new_header in zip(candidate.headers, promoted)
        }
        for row in candidate.rows[1:]
    ]
    return ImportCandidate(
        kind=candidate.kind,
        headers=promoted,
        rows=rows,
        options=candidate.options,
        notices=candidate.notices,
    )


def _demote_headers(candidate: ImportCandidate) -> ImportCandidate:
    """Move column names into a new first row and assign default names."""
    headers = [f"Column{index}" for index in range(1, len(candidate.headers) + 1)]
    rows = [
        {
            header: old_header
            for header, old_header in zip(headers, candidate.headers)
        },
        *(
            {
                new_header: row[old_header]
                for old_header, new_header in zip(candidate.headers, headers)
            }
            for row in candidate.rows
        ),
    ]
    return ImportCandidate(
        kind=candidate.kind,
        headers=headers,
        rows=rows,
        options=candidate.options,
        notices=candidate.notices,
    )


def _transpose_table(candidate: ImportCandidate) -> ImportCandidate:
    """Transpose table cells, dropping the original headers like Table.Transpose."""
    if not candidate.rows:
        raise TransformationError("Cannot transpose a table with no data rows.")
    output_column_count = len(candidate.rows)
    if output_column_count > MAX_COLUMNS:
        raise TransformationError(
            f"Transposing exceeds the {MAX_COLUMNS}-column import limit."
        )
    if len(candidate.headers) * output_column_count > MAX_CELLS:
        raise TransformationError(
            f"Transposing exceeds the {MAX_CELLS:,}-cell import limit."
        )

    headers = [f"Column{index}" for index in range(1, output_column_count + 1)]
    rows = []
    for old_header in candidate.headers:
        values = [row[old_header] for row in candidate.rows]
        rows.append(dict(zip(headers, values)))
    return ImportCandidate(
        kind=candidate.kind,
        headers=headers,
        rows=rows,
        options=candidate.options,
        notices=candidate.notices,
    )


def _reorder_columns(candidate: ImportCandidate, columns: list[str]) -> ImportCandidate:
    """Reorder named columns within their existing header positions."""
    headers = _reordered_headers(candidate.headers, columns)
    return ImportCandidate(
        kind=candidate.kind,
        headers=headers,
        rows=[{header: row[header] for header in headers} for row in candidate.rows],
        options=candidate.options,
        notices=candidate.notices,
    )


def _reordered_headers(headers: list[str], columns: list[str]) -> list[str]:
    """Apply Power Query's partial column-order semantics to a header list."""
    for column in columns:
        _column_index(headers, column)
    selected = set(columns)
    slots = [index for index, header in enumerate(headers) if header in selected]
    reordered = list(headers)
    for index, column in zip(slots, columns):
        reordered[index] = column
    return reordered


def _fill_values(
    candidate: ImportCandidate, columns: list[str], *, fill_down: bool
) -> ImportCandidate:
    """Propagate adjacent non-empty values through selected columns."""
    for column in columns:
        _column_index(candidate.headers, column)
        source_value = None
        has_source_value = False
        rows = candidate.rows if fill_down else reversed(candidate.rows)
        for row in rows:
            value = row[column]
            if value is not None:
                source_value = value
                has_source_value = True
            elif has_source_value:
                row[column] = source_value
    return candidate


def _duplicate_column(
    candidate: ImportCandidate, column: str, new_name: str
) -> ImportCandidate:
    """Append a copy of a column, retaining its values in row order."""
    _column_index(candidate.headers, column)
    if new_name in candidate.headers:
        raise TransformationError(
            f"Cannot duplicate {column!r}: output column {new_name!r} already exists."
        )
    headers = [*candidate.headers, new_name]
    rows = [
        {**row, new_name: row[column]}
        for row in candidate.rows
    ]
    return ImportCandidate(
        kind=candidate.kind,
        headers=headers,
        rows=rows,
        options=candidate.options,
        notices=candidate.notices,
    )


def _add_index_column(
    candidate: ImportCandidate,
    new_name: str,
    start: int,
    increment: int,
) -> ImportCandidate:
    """Append a replayable whole-number index to the current row order."""
    if new_name in candidate.headers:
        raise TransformationError(
            f"Cannot add index column: output column {new_name!r} already exists."
        )
    if len(candidate.headers) >= MAX_COLUMNS:
        raise TransformationError(
            f"Adding an index column exceeds the {MAX_COLUMNS}-column limit."
        )
    if len(candidate.rows) * (len(candidate.headers) + 1) > MAX_CELLS:
        raise TransformationError(
            f"Adding an index column exceeds the {MAX_CELLS:,}-cell limit."
        )
    if candidate.rows:
        last_value = start + (len(candidate.rows) - 1) * increment
        if not MIN_INDEX_VALUE <= last_value <= MAX_INDEX_VALUE:
            raise TransformationError(
                "Index column values must stay within the signed 64-bit whole-number range."
            )

    rows = [
        {**row, new_name: start + row_index * increment}
        for row_index, row in enumerate(candidate.rows)
    ]
    return ImportCandidate(
        kind=candidate.kind,
        headers=[*candidate.headers, new_name],
        rows=rows,
        options=candidate.options,
        notices=candidate.notices,
    )


def _validate_candidate(candidate: ImportCandidate) -> None:
    if not isinstance(candidate, ImportCandidate):
        raise TransformationError("A parsed import candidate is required.")
    if not isinstance(candidate.kind, str) or not candidate.kind:
        raise TransformationError("The import candidate has an invalid source kind.")
    if not isinstance(candidate.options, dict) or not isinstance(candidate.notices, list):
        raise TransformationError("The import candidate metadata is invalid.")
    if any(not isinstance(notice, str) for notice in candidate.notices):
        raise TransformationError("The import candidate notices must be text.")
    _check_candidate_limits(candidate.headers, candidate.rows)


def _check_candidate_limits(headers: Any, rows: Any) -> None:
    if not isinstance(headers, list) or not headers or any(
        not isinstance(header, str) or not header.strip() for header in headers
    ):
        raise TransformationError("The import candidate must have non-empty column names.")
    if len(headers) > MAX_COLUMNS:
        raise TransformationError(f"The table exceeds the {MAX_COLUMNS}-column import limit.")
    if len(set(headers)) != len(headers):
        raise TransformationError("The import candidate has duplicate column names.")
    if not isinstance(rows, list):
        raise TransformationError("The import candidate rows must be a list.")
    if len(rows) > MAX_DATA_ROWS:
        raise TransformationError(f"The table exceeds the {MAX_DATA_ROWS:,}-row import limit.")
    if len(rows) * len(headers) > MAX_CELLS:
        raise TransformationError(f"The table exceeds the {MAX_CELLS:,}-cell import limit.")
    expected = set(headers)
    for row_index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or set(row) != expected:
            raise TransformationError(f"Import candidate row {row_index} does not match its columns.")
        invalid_value = next(
            (value for value in row.values() if not is_supported_cell_value(value)),
            None,
        )
        if any(not is_supported_cell_value(value) for value in row.values()):
            raise TransformationError(
                f"Import candidate row {row_index} contains an unsupported cell value "
                f"of type {type(invalid_value).__name__}."
            )


def _column_index(headers: list[str], column: str) -> int:
    try:
        return headers.index(column)
    except ValueError as exc:
        raise TransformationError(f"Column {column!r} does not exist.") from exc


def _filter_rows(rows: list[dict[str, str]], column: str, operator: str, expected: str) -> list[dict[str, str]]:
    prepared_expected = (
        _parse_number(expected)
        if operator in _NUMERIC_FILTER_OPERATORS
        else expected
    )
    return [
        row
        for row_index, row in enumerate(rows, 1)
        if _filter_value_matches(
            row[column], column, operator, prepared_expected, row_index
        )
    ]


def _filter_rows_advanced(
    rows: list[dict[str, str]],
    headers: list[str],
    clauses: list[dict[str, str]],
) -> list[dict[str, str]]:
    prepared_clauses: list[tuple[str, str, str | Decimal, str]] = []
    for clause in clauses:
        column = clause["column"]
        _column_index(headers, column)
        operator = clause["operator"]
        value = clause["value"]
        expected: str | Decimal = (
            _parse_number(value)
            if operator in _NUMERIC_FILTER_OPERATORS
            else value
        )
        prepared_clauses.append((column, operator, expected, clause["join"]))

    filtered: list[dict[str, str]] = []
    for row_index, row in enumerate(rows, 1):
        completed_or_groups: list[bool] = []
        current_and_group: list[bool] = []
        for clause_index, (column, operator, expected, join) in enumerate(prepared_clauses):
            matched = _filter_value_matches(
                row[column], column, operator, expected, row_index
            )
            if clause_index == 0 or join == "and":
                current_and_group.append(matched)
            else:
                completed_or_groups.append(all(current_and_group))
                current_and_group = [matched]
        completed_or_groups.append(all(current_and_group))
        if any(completed_or_groups):
            filtered.append(row)
    return filtered


def _filter_value_matches(
    value: Any,
    column: str,
    operator: str,
    expected: str | Decimal,
    row_index: int,
) -> bool:
    if is_cell_error(value):
        raise TransformationError(
            f"Cannot evaluate row {row_index} of column {column!r}: {value.message}"
        )
    if operator in _NUMERIC_FILTER_OPERATORS:
        if value is None or value == "":
            return False
        number = _parse_row_number(value, row_index, column)
        if not isinstance(expected, Decimal):
            raise TransformationError(f"Unsupported filter operator {operator!r}.")
        if operator == "greater_than":
            return number > expected
        if operator == "greater_than_or_equal":
            return number >= expected
        if operator == "less_than":
            return number < expected
        if operator == "less_than_or_equal":
            return number <= expected
    elif operator == "equals":
        return _filter_values_equal(value, expected)
    elif operator == "not_equals":
        return not _filter_values_equal(value, expected)
    elif operator == "is_null":
        return value is None
    elif operator == "is_not_null":
        return value is not None
    elif operator == "is_blank":
        return value is None or value == ""
    elif operator == "is_not_blank":
        return value is not None and value != ""
    elif operator == "contains":
        return str(expected) in cell_to_text(value)
    elif operator == "does_not_contain":
        return str(expected) not in cell_to_text(value)
    elif operator == "begins_with":
        return cell_to_text(value).startswith(str(expected))
    elif operator == "does_not_begin_with":
        return not cell_to_text(value).startswith(str(expected))
    elif operator == "ends_with":
        return cell_to_text(value).endswith(str(expected))
    elif operator == "does_not_end_with":
        return not cell_to_text(value).endswith(str(expected))
    raise TransformationError(f"Unsupported filter operator {operator!r}.")


def _filter_values_equal(value: Any, expected: str | Decimal) -> bool:
    if value is None:
        return False
    if is_cell_error(value):
        return False
    if isinstance(value, bool):
        if not isinstance(expected, str) or expected.strip().casefold() not in {"true", "false"}:
            return False
        return value == (expected.strip().casefold() == "true")
    if isinstance(value, (int, float, Decimal)):
        try:
            return _parse_number(value) == _parse_number(expected)
        except TransformationError:
            return False
    if isinstance(value, (date, datetime, time)):
        return cell_to_text(value) == expected
    return value == expected


def _sort_rows(
    rows: list[dict[str, Any]],
    column: str,
    direction: str,
    *,
    case_sensitive: bool = False,
) -> list[dict[str, Any]]:
    non_empty = [
        row for row in rows
        if row[column] is not None and row[column] != "" and not is_cell_error(row[column])
    ]
    empty = [row for row in rows if row[column] is None or row[column] == ""]
    errors = [row for row in rows if is_cell_error(row[column])]
    values = [row[column] for row in non_empty]
    numeric = True
    for value in values:
        try:
            _parse_number(value)
        except TransformationError:
            numeric = False
            break
    if numeric:
        ordered = sorted(non_empty, key=lambda row: _parse_number(row[column]), reverse=direction == "desc")
    else:
        key = (
            (lambda row: cell_to_text(row[column]))
            if case_sensitive
            else (lambda row: cell_to_text(row[column]).casefold())
        )
        try:
            ordered = sorted(non_empty, key=key, reverse=direction == "desc")
        except TypeError:
            ordered = sorted(
                non_empty,
                key=lambda row: cell_to_text(row[column]).casefold(),
                reverse=direction == "desc",
            )
    return ordered + empty + errors


def _sort_rows_by_columns(
    rows: list[dict[str, str]],
    headers: list[str],
    sorts: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Apply stable sorts from the lowest-priority key up to the primary key."""
    ordered = rows
    for sort in reversed(sorts):
        column = sort["column"]
        _column_index(headers, column)
        ordered = _sort_rows(
            ordered, column, sort["direction"], case_sensitive=True
        )
    return ordered


def _convert_column(rows: list[dict[str, Any]], column: str, target_type: str) -> None:
    target_type = canonical_column_type(target_type)
    converted_values: list[Any] = []
    for row_index, row in enumerate(rows, 1):
        value = row[column]
        try:
            converted_values.append(
                _convert_value(value, target_type, row_index, column)
            )
        except TransformationError as exc:
            converted_values.append(PowerQueryCellError(
                reason="DataFormat.Error",
                message=str(exc),
                value=value,
                target_type=target_type,
                row=row_index,
            ))
    for row, value in zip(rows, converted_values):
        row[column] = value


def _conversion_diagnostics_error(
    column: str,
    target_type: str,
    diagnostics: list[dict[str, Any]],
    error_count: int,
    culture: str | None = None,
) -> TransformationError:
    first = diagnostics[0]
    culture_text = f" using culture {culture}" if culture else ""
    message = (
        f"Cannot convert value {_conversion_diagnostic_value(first['value'])} "
        f"in row {first['row']} "
        f"of column {_conversion_diagnostic_value(column)} "
        f"to {target_type}{culture_text}."
    )
    if error_count > 1:
        other_errors = diagnostics[1:]
        message += f" {error_count} conversion errors total."
        if other_errors:
            examples = "; ".join(
                f"row {item['row']} value {_conversion_diagnostic_value(item['value'])}"
                for item in other_errors
            )
            message += f" Other failing rows: {examples}."
        if error_count > len(diagnostics):
            message += (
                f" Showing the first {len(diagnostics)} of {error_count} errors."
            )
    message += " Row numbers are 1-based in the input to this step."
    return TransformationError(
        message,
        row_diagnostics=diagnostics,
        error_count=error_count,
    )


def _conversion_diagnostic_value(value: str) -> str:
    if len(value) <= MAX_CONVERSION_DIAGNOSTIC_VALUE_CHARS:
        return repr(value)
    prefix = value[:MAX_CONVERSION_DIAGNOSTIC_VALUE_CHARS - 1]
    return f"{prefix!r}…"


def _canonical_culture(culture: str) -> str:
    """Validate and store a Babel/CLDR locale as a stable BCP-47-like ID."""
    normalized = culture.strip().replace("_", "-")
    try:
        locale = Locale.parse(normalized, sep="-")
    except (UnknownLocaleError, ValueError) as exc:
        raise TransformationError(
            f"Culture {culture!r} is not recognized. Use a locale ID such as en-US, en-GB, or de-DE."
        ) from exc
    return str(locale).replace("_", "-")


def _locale_period_tokens(locale: Locale) -> list[tuple[str, str]]:
    tokens = {"am": "am", "pm": "pm"}
    for period in ("am", "pm"):
        label = locale.periods.get(period)
        if label:
            tokens[" ".join(label.split()).casefold()] = period
    return sorted(tokens.items(), key=lambda item: len(item[0]), reverse=True)


def _locale_datetime_time_match(value: str, locale: Locale) -> re.Match[str] | None:
    marker_patterns = [
        r"\s*".join(re.escape(part) for part in token.split())
        for token, _period in _locale_period_tokens(locale)
    ]
    marker_suffix = rf"(?:\s*(?:{'|'.join(marker_patterns)}))?"
    return re.search(
        rf"{_LOCALE_CLOCK_PATTERN}{marker_suffix}\s*$",
        value,
        flags=re.IGNORECASE,
    )


def _parse_locale_time(value: str, locale: Locale) -> time:
    normalized = " ".join(value.strip().split())
    period = None
    folded = normalized.casefold()
    for token, period_kind in _locale_period_tokens(locale):
        if not folded.endswith(token):
            continue
        prefix = normalized[:-len(token)].rstrip()
        if prefix and not prefix[-1].isalpha():
            normalized, period = prefix, period_kind
            break

    microsecond = 0
    fraction = re.search(r"(?<=\d)[.,](\d+)$", normalized)
    if fraction is not None:
        digits = fraction.group(1)
        if len(digits) > 6:
            raise ValueError
        microsecond = int((digits + "000000")[:6])
        normalized = normalized[:fraction.start()]

    parsed = parse_time(normalized, locale=locale)
    if period is not None:
        if not 1 <= parsed.hour <= 12:
            raise ValueError
        hour = parsed.hour % 12 + (12 if period == "pm" else 0)
        parsed = parsed.replace(hour=hour)
    if fraction is not None:
        parsed = parsed.replace(microsecond=microsecond)
    return parsed


def _convert_column_using_locale(
    rows: list[dict[str, Any]], column: str, target_type: str, culture: str
) -> None:
    target_type = canonical_column_type(target_type)
    locale = Locale.parse(culture.replace("-", "_"))
    converted_values: list[Any] = []
    for row_index, row in enumerate(rows, 1):
        value = row[column]
        try:
            converted_values.append(
                _convert_value_using_locale(value, target_type, locale)
            )
        except (DecimalException, IndexError, OverflowError, ValueError):
            converted_values.append(PowerQueryCellError(
                reason="DataFormat.Error",
                message=(
                    f"Cannot convert value {_conversion_diagnostic_value(cell_to_text(value))} "
                    f"in row {row_index} of column "
                    f"{_conversion_diagnostic_value(column)} to {target_type} "
                    f"using culture {culture}."
                ),
                value=value,
                target_type=target_type,
                culture=culture,
                row=row_index,
            ))
    for row, value in zip(rows, converted_values):
        row[column] = value


def _decimal_number_text(number: Decimal) -> str:
    double_value = float(number)
    if not math.isfinite(double_value):
        raise ValueError
    if double_value == 0.0:
        return "-0" if number.is_signed() else "0"
    return str(number)


def _int64_number_text(number: Decimal) -> str:
    rounded = number.to_integral_value(rounding=ROUND_HALF_EVEN)
    if rounded < -(1 << 63) or rounded > (1 << 63) - 1:
        raise ValueError
    return str(int(rounded))


def _convert_value_using_locale(value: Any, target_type: str, locale: Locale) -> Any:
    if is_cell_error(value) or value is None:
        return value
    source = cell_to_text(value)
    if source == "":
        raise ValueError
    if target_type in {"whole_number", "decimal_number"}:
        number = parse_decimal(
            source.strip(), locale=locale, strict=True, numbering_system="default"
        )
        if not number.is_finite():
            raise ValueError
        if target_type == "whole_number":
            return int(_int64_number_text(number))
        return Decimal(_decimal_number_text(number))
    if target_type == "date":
        stripped = source.strip()
        try:
            return date.fromisoformat(stripped)
        except ValueError:
            try:
                return datetime.fromisoformat(
                    stripped.replace("Z", "+00:00")
                ).date()
            except ValueError:
                parsed = parse_date(stripped, locale=locale)
                return date(parsed.year, parsed.month, parsed.day)
    if target_type == "time":
        try:
            return time.fromisoformat(source.strip())
        except ValueError:
            return _parse_locale_time(source, locale)
    if target_type == "datetime":
        stripped = source.strip()
        try:
            return datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except ValueError:
            pass
        match = _locale_datetime_time_match(stripped, locale)
        if match is not None:
            date_text = stripped[:match.start()].strip()
            if not date_text:
                raise ValueError
            parsed_date = parse_date(date_text, locale=locale)
            parsed_time = _parse_locale_time(match.group(0).strip(), locale)
            return datetime.combine(parsed_date, parsed_time)
        parsed_date = parse_date(stripped, locale=locale)
        return datetime.combine(parsed_date, time.min)
    raise ValueError


def count_conversion_errors(values: list[Any], target_type: str) -> int:
    """Count values that fail a model type without changing the supplied values."""
    target_type = canonical_column_type(target_type)
    errors = 0
    for row_index, value in enumerate(values, 1):
        if is_cell_error(value):
            errors += 1
            continue
        if value is None or value == "":
            continue
        try:
            _convert_value(value, target_type, row_index, "column")
        except TransformationError:
            errors += 1
    return errors


def _convert_value(value: Any, target_type: str, row_index: int, column: str) -> Any:
    if is_cell_error(value) or value is None:
        return value
    if target_type == "text":
        return cell_to_text(value)
    source = cell_to_text(value)
    try:
        if target_type == "decimal_number":
            return Decimal(_decimal_number_text(_parse_number(source)))
        if target_type == "whole_number":
            return int(_int64_number_text(_parse_number(source)))
        if target_type == "boolean":
            lowered = source.strip().casefold()
            if lowered not in {"true", "false"}:
                raise ValueError
            return lowered == "true"
        if target_type == "date":
            stripped = source.strip()
            try:
                return date.fromisoformat(stripped)
            except ValueError:
                pass
            try:
                return datetime.fromisoformat(
                    stripped.replace("Z", "+00:00")
                ).date()
            except ValueError:
                raise ValueError
        if target_type == "datetime":
            return datetime.fromisoformat(source.strip().replace("Z", "+00:00"))
        if target_type == "time":
            return time.fromisoformat(source.strip())
        raise ValueError
    except (TransformationError, ValueError, OverflowError) as exc:
        raise TransformationError(
            f"Cannot convert value {_conversion_diagnostic_value(source)} in row {row_index} "
            f"of column {_conversion_diagnostic_value(column)} to {target_type}."
        ) from exc


def _parse_row_number(value: Any, row_index: int, column: str) -> Decimal:
    try:
        return _parse_number(value)
    except TransformationError as exc:
        raise TransformationError(
            f"Value {value!r} in row {row_index} of column {column!r} is not a valid number."
        ) from exc


def _parse_number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise TransformationError("A boolean value is not a numeric cell.")
    try:
        if isinstance(value, Decimal):
            number = value
        elif isinstance(value, int):
            number = Decimal(value)
        elif isinstance(value, float):
            number = Decimal(str(value))
        elif isinstance(value, str):
            number = Decimal(value.strip())
        else:
            raise ValueError
    except (DecimalException, ValueError):
        raise TransformationError("Expected a finite number.") from None
    if not number.is_finite():
        raise TransformationError("Expected a finite number.")
    return number
