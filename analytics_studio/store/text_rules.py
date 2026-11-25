"""Model-load rule for text, shared by Stage C SQL and tools/store_engine_diff.py.

The DAX engine (VertiPaq rule, see model_text_normalizer in power_query_values.py) loads text this way:
drop trailing characters U+0000 to U+0020, fold case for ASCII letters only (A-Z to a-z), and keep the
first-seen spelling of each folded value. The store holds cells as read, so SQL applies the same rule.
A NULL cell and the empty string are the same blank value (COALESCE to '').
"""

from __future__ import annotations

import string
from typing import Any

# SQL text for the 33 characters U+0000..U+0020 (used as the character set of rtrim)
TRIM_CHARS_SQL = " || ".join(f"chr({i})" for i in range(33))

_TRIM_CHARS = "".join(chr(code) for code in range(33))
_UPPER = string.ascii_uppercase
_LOWER = string.ascii_lowercase
_ASCII_FOLD = str.maketrans(_UPPER, _LOWER)


def trim_sql(expr: str) -> str:
    """SQL text of the value with trailing U+0000..U+0020 dropped (NULL read as blank)."""
    return f"rtrim(COALESCE({expr}, ''), {TRIM_CHARS_SQL})"


def fold_sql(expr: str) -> str:
    """SQL text of the folded value: trailing U+0000..U+0020 dropped, then ASCII-only lowercase."""
    return f"translate({trim_sql(expr)}, '{_UPPER}', '{_LOWER}')"


def first_spelling_expr_sql(expr: str, rowid: str = "rowid") -> str:
    """SQL aggregate for the first-seen trimmed spelling inside a GROUP BY fold_sql(expr) query."""
    return f"arg_min({trim_sql(expr)}, {rowid})"


def first_spelling_sql(table: str, column: str, rowid: str = "rowid") -> str:
    """SQL returning (folded, spelling) per folded value, ordered by first appearance.

    `table` and `column` are inserted as written, so the caller quotes them if needed.

    `rowid` is the physical DuckDB rowid by default. That is the load order only for a table that was
    loaded in order and not re-sorted. On a derived or re-ordered table, pass the column that holds the
    load order (the store's "__rn") or "first-seen" will follow the physical order instead.
    """
    return (
        f"SELECT {fold_sql(column)} AS folded, {first_spelling_expr_sql(column, rowid)} AS spelling "
        f"FROM {table} GROUP BY {fold_sql(column)} ORDER BY MIN({rowid})"
    )


def trim_text(value: Any) -> str:
    """Python reference of trim_sql: None reads as blank, trailing U+0000..U+0020 dropped."""
    return ("" if value is None else str(value)).rstrip(_TRIM_CHARS)


def fold_text(value: Any) -> str:
    """Python reference of fold_sql: trim_text, then lowercase A-Z only (non-ASCII untouched)."""
    return trim_text(value).translate(_ASCII_FOLD)
