"""Pure M IntelliSense and completion provider.

No Qt dependencies.
"""

from __future__ import annotations

from typing import Any

from .m_engine.stdlib import GLOBALS
from .m_engine.pbi_library_names import PBI_LIBRARY_NAMES

M_KEYWORDS: tuple[str, ...] = (
    "if",
    "then",
    "else",
    "each",
    "let",
    "in",
    "and",
    "or",
    "not",
    "true",
    "false",
    "null",
)

_IDENTIFIER_CHARS: frozenset[str] = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_."
)


def _scan_strings_and_comments(text: str, caret: int) -> tuple[bool, list[int]]:
    """Scan `text` up to `caret`.

    Returns ``(inside, code_positions)`` where ``inside`` is True when the caret
    sits inside a string literal ("...") or a //... or /*...*/ comment, and
    ``code_positions`` lists the indices of characters that were seen outside
    strings and comments.
    """
    in_string = False
    in_line_comment = False
    in_block_comment = False
    code_positions: list[int] = []
    i = 0
    n = min(caret, len(text))
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            if ch == '"':
                if nxt == '"':
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        code_positions.append(i)
        i += 1

    return in_string or in_line_comment or in_block_comment, code_positions


def _is_inside_string_or_comment(text: str, caret: int) -> bool:
    """Check if the caret is inside an M string literal ("...") or line comment (//...)."""
    inside, _code_positions = _scan_strings_and_comments(text, caret)
    return inside


def _last_open_bracket(text: str, caret: int) -> int:
    """Return the index of the last '[' outside strings/comments that is still open.

    A ']' outside strings/comments closes the bracket; -1 means there is none.
    """
    _inside, code_positions = _scan_strings_and_comments(text, caret)
    bracket_pos = -1
    for index in code_positions:
        ch = text[index]
        if ch == "[":
            bracket_pos = index
        elif ch == "]":
            bracket_pos = -1
    return bracket_pos


def complete_m(text: str, caret: int, columns: list[str]) -> list[dict[str, Any]]:
    """Return completion proposals at `caret` in M expression `text`.

    Each item has:
      label: str
      kind: "function" | "keyword" | "column"
      insertText: str
      replaceStart: int
      replaceEnd: int
      supported: bool (optional for keywords/columns, present for functions)
    """
    if caret < 0 or caret > len(text):
        return []

    if _is_inside_string_or_comment(text, caret):
        return []

    # 1. Column completion after '['
    bracket_pos = _last_open_bracket(text, caret)
    if bracket_pos != -1:
        segment = text[bracket_pos + 1 : caret]
        if "]" not in segment and "\n" not in segment:
            col_prefix = segment.casefold()
            has_closing_bracket = (caret < len(text) and text[caret] == "]")
            matches = []
            for col in columns:
                cf = col.casefold()
                if not col_prefix or cf.startswith(col_prefix) or col_prefix in cf:
                    is_prefix = cf.startswith(col_prefix) if col_prefix else True
                    insert_text = col if has_closing_bracket else col + "]"
                    matches.append(
                        (
                            0 if is_prefix else 1,
                            col,
                            {
                                "label": col,
                                "kind": "column",
                                "insertText": insert_text,
                                "replaceStart": bracket_pos + 1,
                                "replaceEnd": caret,
                            },
                        )
                    )
            matches.sort(key=lambda item: (item[0], item[1]))
            return [item[2] for item in matches[:200]]

    # 2. Identifier completion (keywords & functions)
    start = caret
    while start > 0 and text[start - 1] in _IDENTIFIER_CHARS:
        start -= 1
    prefix = text[start:caret]
    if not prefix:
        return []

    p_fold = prefix.casefold()
    results: list[dict[str, Any]] = []

    # Keywords
    kw_matches: list[tuple[int, str, dict[str, Any]]] = []
    for kw in M_KEYWORDS:
        kf = kw.casefold()
        if kf.startswith(p_fold):
            kw_matches.append(
                (
                    0,
                    kw,
                    {
                        "label": kw,
                        "kind": "keyword",
                        "insertText": kw,
                        "replaceStart": start,
                        "replaceEnd": caret,
                    },
                )
            )
        elif p_fold in kf:
            kw_matches.append(
                (
                    1,
                    kw,
                    {
                        "label": kw,
                        "kind": "keyword",
                        "insertText": kw,
                        "replaceStart": start,
                        "replaceEnd": caret,
                    },
                )
            )
    kw_matches.sort(key=lambda item: (item[0], item[1]))
    results.extend(item[2] for item in kw_matches)

    # Functions: supported (in GLOBALS)
    fn_supported: list[tuple[int, str, dict[str, Any]]] = []
    for fn in GLOBALS.keys():
        ff = fn.casefold()
        if ff.startswith(p_fold):
            fn_supported.append(
                (
                    0,
                    fn,
                    {
                        "label": fn,
                        "kind": "function",
                        "insertText": fn + "(",
                        "replaceStart": start,
                        "replaceEnd": caret,
                        "supported": True,
                    },
                )
            )
        elif p_fold in ff:
            fn_supported.append(
                (
                    1,
                    fn,
                    {
                        "label": fn,
                        "kind": "function",
                        "insertText": fn + "(",
                        "replaceStart": start,
                        "replaceEnd": caret,
                        "supported": True,
                    },
                )
            )
    fn_supported.sort(key=lambda item: (item[0], item[1]))
    results.extend(item[2] for item in fn_supported)

    # Functions: unsupported (in PBI_LIBRARY_NAMES and not in GLOBALS)
    fn_unsupported: list[tuple[int, str, dict[str, Any]]] = []
    for fn in PBI_LIBRARY_NAMES:
        if fn in GLOBALS:
            continue
        ff = fn.casefold()
        if ff.startswith(p_fold):
            fn_unsupported.append(
                (
                    0,
                    fn,
                    {
                        "label": fn,
                        "kind": "function",
                        "insertText": fn + "(",
                        "replaceStart": start,
                        "replaceEnd": caret,
                        "supported": False,
                    },
                )
            )
        elif p_fold in ff:
            fn_unsupported.append(
                (
                    1,
                    fn,
                    {
                        "label": fn,
                        "kind": "function",
                        "insertText": fn + "(",
                        "replaceStart": start,
                        "replaceEnd": caret,
                        "supported": False,
                    },
                )
            )
    fn_unsupported.sort(key=lambda item: (item[0], item[1]))
    results.extend(item[2] for item in fn_unsupported)

    return results[:200]
