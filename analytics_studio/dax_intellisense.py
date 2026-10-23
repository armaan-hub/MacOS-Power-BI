"""Completion items and parameter hints for the DAX formula bar (pure Python, no Qt).

The editor asks two questions, given the formula text, the caret position and a model snapshot:

* ``complete`` - what can be typed here?  Functions, tables, measures, columns or keywords,
  depending on where the caret is (identifier, after ``Table[``, after a bare ``[``, after a
  quote).  Nothing is offered inside a string literal or a comment.
* ``signature_help`` - which function call is the caret inside, and which parameter is it on?

Functions come from Power BI's full DAX function list.  Only the ones the local evaluator can
run are marked ``supported``; the rest are still listed (greyed in the UI) so the user can see
they exist, but they never insert text, so the editor never completes into a formula that the
engine would then reject.

The model snapshot is a plain dictionary::

    {"home_table": "Sales",
     "tables": [{"name": "Sales", "columns": [{"name": "Qty", "type": "number"}]}],
     "measures": [{"name": "Total", "table": "Sales", "type": "number"}]}
"""

from __future__ import annotations

import re
from typing import Any

from analytics_studio import measures as _measures
from analytics_studio.dax_function_catalog import CATALOG, doc_of, signature_of, split_parameters

KEYWORDS = ("VAR", "RETURN", "IN", "ASC", "DESC")
MAX_ITEMS = 1000
UNSUPPORTED_DETAIL = "Not supported by this app"

SUPPORTED_FUNCTIONS: frozenset[str] = frozenset(_measures.DAX_FUNCTION_NAMES)
FUNCTION_NAMES: tuple[str, ...] = tuple(sorted(set(CATALOG) | SUPPORTED_FUNCTIONS))

_IDENT_CHAR = re.compile(r"[\w.]", re.UNICODE)
_PLAIN_NAME = re.compile(r"^[^\W\d]\w*$", re.UNICODE)
_CALL_NAME = re.compile(r"([^\W\d][\w.]*)\s*$", re.UNICODE)
_QUOTED_BEFORE = re.compile(r"'((?:[^']|'')+)'$")
_BARE_BEFORE = re.compile(r"([^\W\d][\w.]*)$", re.UNICODE)


def split_formula(text: str) -> tuple[str, int] | None:
    """Return ``(name, expression_offset)`` for ``Name = expression`` text, else ``None``."""
    parts = formula_parts(text)
    return None if parts is None else (parts[0], parts[2])


def formula_parts(text: str) -> tuple[str, int, int] | None:
    """Return ``(name, equals_index, expression_offset)`` for ``Name = expression`` text."""
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "'":
            index += 1
            while index < length:
                if text[index] == "'":
                    if index + 1 < length and text[index + 1] == "'":
                        index += 2
                        continue
                    break
                index += 1
        elif char == "=":
            offset = index + 1
            while offset < length and text[offset] in " \t":
                offset += 1
            return text[:index].strip(), index, offset
        elif char in "([\"{,;\n":
            return None
        index += 1
    return None


class _Scan:
    """What the caret sits in, found by reading the text once from the start."""

    __slots__ = ("state", "start", "stack")

    def __init__(self, state: str, start: int, stack: list[dict[str, Any]]) -> None:
        self.state = state  # normal | string | quoted | bracket | comment
        self.start = start  # where the string / quote / bracket / comment began
        self.stack = stack  # open "(" and "{" groups, innermost last


def _scan(text: str, caret: int) -> _Scan:
    caret = max(0, min(caret, len(text)))
    stack: list[dict[str, Any]] = []
    index = 0
    while index < caret:
        char = text[index]
        pair = text[index:index + 2]
        if pair in ("//", "--"):
            end = text.find("\n", index)
            if end < 0 or end >= caret:
                return _Scan("comment", index, stack)
            index = end + 1
            continue
        if pair == "/*":
            end = text.find("*/", index + 2)
            if end < 0 or end + 2 > caret:
                return _Scan("comment", index, stack)
            index = end + 2
            continue
        if char in "\"'[":
            closer = {"\"": '"', "'": "'", "[": "]"}[char]
            state = {"\"": "string", "'": "quoted", "[": "bracket"}[char]
            scan = index + 1
            while True:
                if scan >= caret:
                    return _Scan(state, index, stack)
                if text[scan] == closer:
                    if scan + 1 < len(text) and text[scan + 1] == closer and scan + 1 < caret:
                        scan += 2
                        continue
                    break
                scan += 1
            index = scan + 1
            continue
        if char == "(":
            match = _CALL_NAME.search(text[:index])
            stack.append({"kind": "(", "function": match.group(1) if match else None, "commas": 0})
        elif char == "{":
            stack.append({"kind": "{", "function": None, "commas": 0})
        elif char in ")}":
            if stack:
                stack.pop()
        elif char == "," and stack:
            stack[-1]["commas"] += 1
        index += 1
    return _Scan("normal", caret, stack)


def _quote_if_needed(name: str, *, force: bool = False) -> str:
    if not force and _PLAIN_NAME.match(name):
        return name
    return "'" + name.replace("'", "''") + "'"


def _table_by_name(model: dict[str, Any], name: str) -> dict[str, Any] | None:
    wanted = name.casefold()
    for table in model.get("tables", []):
        if str(table.get("name", "")).casefold() == wanted:
            return table
    return None


def _rank(prefix: str, label: str) -> int | None:
    """0 for a prefix match, 1 for a contains match, ``None`` for no match."""
    if not prefix:
        return 0
    folded = label.casefold()
    wanted = prefix.casefold()
    if folded.startswith(wanted):
        return 0
    if wanted in folded:
        return 1
    return None


def _ordered(entries: list[tuple[int, str, dict[str, Any]]]) -> list[dict[str, Any]]:
    entries.sort(key=lambda entry: (entry[0], entry[1].casefold(), entry[1]))
    return [item for _rank_value, _label, item in entries][:MAX_ITEMS]


def _function_item(name: str, start: int, end: int) -> dict[str, Any]:
    supported = name in SUPPORTED_FUNCTIONS
    return {
        "label": name,
        "kind": "function",
        "detail": "Function" if supported else UNSUPPORTED_DETAIL,
        "insertText": f"{name}(" if supported else "",
        "signature": signature_of(name),
        "doc": doc_of(name),
        "supported": supported,
        "replaceStart": start,
        "replaceEnd": end,
    }


def _column_item(column: dict[str, Any], table_name: str, insert: str, start: int, end: int) -> dict[str, Any]:
    kind = str(column.get("type") or "text").replace("_", " ")
    return {
        "label": str(column["name"]),
        "kind": "column",
        "detail": f"Column · {kind} · {table_name}",
        "insertText": insert,
        "signature": f"{table_name}[{column['name']}]",
        "doc": "",
        "supported": True,
        "replaceStart": start,
        "replaceEnd": end,
    }


def _measure_item(measure: dict[str, Any], insert: str, start: int, end: int) -> dict[str, Any]:
    kind = str(measure.get("type") or "")
    table = str(measure.get("table") or "")
    detail = "Measure" + (f" · {kind}" if kind else "") + (f" · {table}" if table else "")
    return {
        "label": str(measure["name"]),
        "kind": "measure",
        "detail": detail,
        "insertText": insert,
        "signature": f"[{measure['name']}]",
        "doc": "",
        "supported": True,
        "replaceStart": start,
        "replaceEnd": end,
    }


def complete(
    expression: str, caret: int, model: dict[str, Any] | None = None, *, invoked: bool = False
) -> list[dict[str, Any]]:
    """Completion items for ``expression`` with the caret at ``caret``.

    ``invoked`` is true when the user asked for the list (Ctrl+Space); otherwise an empty
    identifier prefix offers nothing, so the popup only appears while typing a name.
    """
    model = model or {}
    caret = max(0, min(caret, len(expression)))
    scan = _scan(expression, caret)
    if scan.state in {"string", "comment"}:
        return []
    if scan.state == "quoted":
        partial = expression[scan.start + 1:caret].replace("''", "'")
        entries = []
        for table in model.get("tables", []):
            name = str(table["name"])
            rank = _rank(partial, name)
            if rank is None:
                continue
            entries.append((rank, name, {
                "label": name, "kind": "table", "detail": "Table",
                "insertText": _quote_if_needed(name, force=True), "signature": name, "doc": "",
                "supported": True, "replaceStart": scan.start, "replaceEnd": caret,
            }))
        return _ordered(entries)
    if scan.state == "bracket":
        return _complete_bracket(expression, caret, scan.start, model)
    return _complete_identifier(expression, caret, model, invoked)


def _complete_bracket(expression: str, caret: int, open_at: int, model: dict[str, Any]) -> list[dict[str, Any]]:
    partial = expression[open_at + 1:caret]
    before = expression[:open_at]
    closed = expression[caret:caret + 1] == "]"
    suffix = "" if closed else "]"
    quoted = _QUOTED_BEFORE.search(before)
    bare = _BARE_BEFORE.search(before)
    entries: list[tuple[int, str, dict[str, Any]]] = []
    if quoted or bare:
        table_name = quoted.group(1).replace("''", "'") if quoted else bare.group(1)  # type: ignore[union-attr]
        table = _table_by_name(model, table_name)
        if table is None:
            return []
        for column in table.get("columns", []):
            name = str(column["name"])
            rank = _rank(partial, name)
            if rank is None or "]" in name:
                continue
            entries.append((rank, name, _column_item(
                column, str(table["name"]), name + suffix, open_at + 1, caret)))
        return _ordered(entries)
    for measure in model.get("measures", []):
        name = str(measure["name"])
        rank = _rank(partial, name)
        if rank is not None and "]" not in name:
            entries.append((rank, name, _measure_item(measure, name + suffix, open_at + 1, caret)))
    home = _table_by_name(model, str(model.get("home_table") or ""))
    if home is not None:
        for column in home.get("columns", []):
            name = str(column["name"])
            rank = _rank(partial, name)
            if rank is not None and "]" not in name:
                entries.append((rank, name, _column_item(
                    column, str(home["name"]), name + suffix, open_at + 1, caret)))
    return _ordered(entries)


def _complete_identifier(
    expression: str, caret: int, model: dict[str, Any], invoked: bool
) -> list[dict[str, Any]]:
    start = caret
    while start > 0 and _IDENT_CHAR.match(expression[start - 1]):
        start -= 1
    prefix = expression[start:caret]
    if prefix and not (prefix[0].isalpha() or prefix[0] == "_"):
        return []
    if not prefix and not invoked:
        return []
    entries: list[tuple[int, str, dict[str, Any]]] = []
    for name in FUNCTION_NAMES:
        rank = _rank(prefix, name)
        if rank is not None:
            entries.append((rank, name, _function_item(name, start, caret)))
    for name in KEYWORDS:
        rank = _rank(prefix, name)
        if rank is not None:
            entries.append((rank, name, {
                "label": name, "kind": "keyword", "detail": "Keyword", "insertText": name + " ",
                "signature": name, "doc": "", "supported": True,
                "replaceStart": start, "replaceEnd": caret,
            }))
    for table in model.get("tables", []):
        name = str(table["name"])
        rank = _rank(prefix, name)
        if rank is not None:
            entries.append((rank, name, {
                "label": name, "kind": "table", "detail": "Table",
                "insertText": _quote_if_needed(name), "signature": name, "doc": "",
                "supported": True, "replaceStart": start, "replaceEnd": caret,
            }))
    for measure in model.get("measures", []):
        name = str(measure["name"])
        rank = _rank(prefix, name)
        if rank is not None and "]" not in name:
            entries.append((rank, name, _measure_item(measure, f"[{name}]", start, caret)))
    return _ordered(entries)


def signature_help(expression: str, caret: int, model: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The innermost known function call around the caret, with the active parameter."""
    scan = _scan(expression, max(0, min(caret, len(expression))))
    if scan.state != "normal":
        return None
    for group in reversed(scan.stack):
        name = group["function"] if group["kind"] == "(" else None
        if not name or name.upper() not in CATALOG and name.upper() not in SUPPORTED_FUNCTIONS:
            continue
        function = name.upper()
        signature = signature_of(function)
        parameters = split_parameters(signature)
        active = int(group["commas"])
        if parameters:
            active = min(active, len(parameters) - 1)
        return {
            "function": function,
            "signature": signature,
            "parameters": parameters,
            "activeParameter": active,
            "doc": doc_of(function),
            "supported": function in SUPPORTED_FUNCTIONS,
        }
    return None


def complete_formula(
    text: str, caret: int, model: dict[str, Any] | None = None, *, invoked: bool = False
) -> list[dict[str, Any]]:
    """``complete`` for ``Name = expression`` text; nothing is offered inside the name."""
    parts = split_formula(text)
    if parts is None or caret < parts[1]:
        return []
    offset = parts[1]
    items = complete(text[offset:], caret - offset, model, invoked=invoked)
    for item in items:
        item["replaceStart"] += offset
        item["replaceEnd"] += offset
    return items


def signature_help_formula(text: str, caret: int, model: dict[str, Any] | None = None) -> dict[str, Any] | None:
    parts = split_formula(text)
    if parts is None or caret < parts[1]:
        return None
    return signature_help(text[parts[1]:], caret - parts[1], model)


def apply_completion(text: str, item: dict[str, Any]) -> tuple[str, int] | None:
    """Text and caret after accepting ``item``; ``None`` when the item must not be inserted."""
    insert = str(item.get("insertText") or "")
    if not item.get("supported", True) or not insert:
        return None
    start, end = int(item["replaceStart"]), int(item["replaceEnd"])
    caret = start + len(insert)
    if (
        item.get("kind") in {"column", "measure"}
        and not insert.endswith("]")
        and text[end:end + 1] == "]"
    ):
        caret += 1  # step over the closing bracket that is already there
    return text[:start] + insert + text[end:], caret
