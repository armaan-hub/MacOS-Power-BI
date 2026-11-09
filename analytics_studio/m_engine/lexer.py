"""Tokenizer for the Power Query M language.

Token kinds:
  number   numeric literal (value: int or float)
  text     text literal, escapes decoded (value: str)
  ident    identifier, quoted identifier, #intrinsic name (value: str)
  keyword  reserved word such as ``if`` or ``true`` (text is the word)
  field    a bracketed single field selector ``[Name]`` (value: decoded name)
  op       punctuation or operator (text is the operator)
  eof      end of input
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


class MSyntaxError(Exception):
    """A Power Query M syntax error with the character offset and line/column."""

    def __init__(self, message: str, position: Optional[int] = None, source: str = ""):
        self.message = message
        self.position = position
        self.line: Optional[int] = None
        self.column: Optional[int] = None
        if position is not None:
            before = source[:position]
            self.line = before.count("\n") + 1
            self.column = position - (before.rfind("\n") + 1) + 1
            text = f"{message} (line {self.line}, column {self.column})"
        else:
            text = message
        super().__init__(text)


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    position: int
    value: object = None


KEYWORDS = frozenset({
    "and", "as", "each", "else", "error", "false", "if", "in", "is", "let",
    "meta", "not", "null", "or", "optional", "otherwise", "section", "shared",
    "then", "true", "try", "type",
})

_WORD = r"[^\W\d]\w*"
_IDENT_RE = re.compile(rf"{_WORD}(?:\.{_WORD})*")
_HASH_IDENT_RE = re.compile(r"#[^\W\d]\w*(?:\.[^\W\d]\w*)*")
_NUMBER_RE = re.compile(r"0[xX][0-9A-Fa-f]+|(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_FIELD_RE = re.compile(
    r'\[[ \t\r\n]*(#"(?:[^"]|"")*"|[^\W\d][^\[\]"=,{}()\r\n]*?)[ \t\r\n]*\]'
)
_RECORD_NAME_RE = re.compile(
    r'([^\W\d][^\[\]"=,{}()\r\n]*?)[ \t\r\n]*=(?!=)'
)
_OPERATORS = (
    "...", "..", "=>", "<>", "<=", ">=", "(", ")", "[", "]", "{", "}", ",",
    "=", "<", ">", "+", "-", "*", "/", "&", "?", "@",
)
_WHITESPACE = " \t\r\n\f\v﻿"
_HEX_ESCAPE_RE = re.compile(r"[0-9A-Fa-f]{4}|[0-9A-Fa-f]{8}")
_SIMPLE_ESCAPES = {"lf": "\n", "cr": "\r", "tab": "\t"}


def _decode_escape_list(body: str) -> Optional[str]:
    """Decode the inside of ``#(...)``: a comma-separated list of ``cr``, ``lf``, ``tab``, ``#`` (a literal
    ``#``), or a 4 or 8 digit hex code point. Returns None when any item is not one of these."""
    pieces: list[str] = []
    for item in body.split(","):
        if item in _SIMPLE_ESCAPES:
            pieces.append(_SIMPLE_ESCAPES[item])
        elif item == "#":
            pieces.append("#")
        elif _HEX_ESCAPE_RE.fullmatch(item):
            try:
                pieces.append(chr(int(item, 16)))
            except ValueError:
                return None
        else:
            return None
    return "".join(pieces)


def _read_string(source: str, quote: int, terminator_msg: str) -> tuple[str, int]:
    """Decode a ``"..."`` body starting at the opening quote index.

    Handles ``""`` for an embedded quote and ``#(...)`` escape sequences.
    Returns the decoded value and the index just past the closing quote.
    """
    out: list[str] = []
    j = quote + 1
    n = len(source)
    while j < n:
        ch = source[j]
        if ch == '"':
            if j + 1 < n and source[j + 1] == '"':
                out.append('"')
                j += 2
                continue
            return "".join(out), j + 1
        if ch == "#" and j + 1 < n and source[j + 1] == "(":
            close = source.find(")", j + 2)
            if close < 0:
                raise MSyntaxError("Unterminated escape sequence", j, source)
            body = source[j + 2:close]
            decoded = _decode_escape_list(body)
            if decoded is None:
                raise MSyntaxError(f"Invalid escape sequence '#({body})'", j, source)
            out.append(decoded)
            j = close + 1
            continue
        out.append(ch)
        j += 1
    raise MSyntaxError(terminator_msg, quote, source)


def _number_value(text: str) -> object:
    if text[:2] in ("0x", "0X"):
        return int(text[2:], 16)
    if any(c in text for c in ".eE"):
        return float(text)
    return int(text)


def tokenize(source: str) -> list[Token]:
    """Split M source text into tokens; the list always ends with an ``eof`` token."""
    tokens: list[Token] = []
    i = 0
    n = len(source)
    while True:
        while i < n:
            ch = source[i]
            if ch in _WHITESPACE:
                i += 1
            elif source.startswith("//", i):
                nl = source.find("\n", i)
                i = n if nl < 0 else nl + 1
            elif source.startswith("/*", i):
                end = source.find("*/", i + 2)
                if end < 0:
                    raise MSyntaxError("Unterminated comment", i, source)
                i = end + 2
            else:
                break
        if i >= n:
            tokens.append(Token("eof", "", n))
            return tokens

        start = i
        ch = source[i]

        if ch == '"':
            value, i = _read_string(source, i, "Unterminated text literal")
            tokens.append(Token("text", source[start:i], start, value))
            continue

        if source.startswith('#"', i):
            value, i = _read_string(source, i + 1, "Unterminated quoted identifier")
            tokens.append(Token("ident", source[start:i], start, value))
            continue

        if ch == "#":
            m = _HASH_IDENT_RE.match(source, i)
            if not m:
                raise MSyntaxError("Unexpected '#'", i, source)
            tokens.append(Token("ident", m.group(0), start, m.group(0)))
            i = m.end()
            continue

        if ch == "[":
            m = _FIELD_RE.match(source, i)
            if m:
                raw = m.group(1)
                value = _read_string(raw, 1, "Unterminated quoted identifier")[0] if raw.startswith('#"') else raw
                tokens.append(Token("field", source[i:m.end()], start, value))
                i = m.end()
                continue
            tokens.append(Token("op", "[", start))
            i += 1
            continue

        m = _NUMBER_RE.match(source, i)
        if m:
            text = m.group(0)
            tokens.append(Token("number", text, start, _number_value(text)))
            i = m.end()
            continue

        after_separator = bool(tokens) and tokens[-1].kind == "op" and tokens[-1].text in ("[", ",")
        if after_separator:
            # A record field name may contain spaces ("[Column 1 = 1]"); only in record position.
            m = _RECORD_NAME_RE.match(source, i)
            if m and re.search(r"\s", m.group(1)) and m.group(1).split()[0] not in KEYWORDS:
                name = m.group(1)
                tokens.append(Token("ident", name, start, name))
                i = m.end(1)
                continue

        m = _IDENT_RE.match(source, i)
        if m:
            word = m.group(0)
            kind = "keyword" if word in KEYWORDS else "ident"
            tokens.append(Token(kind, word, start, word))
            i = m.end()
            continue

        for op in _OPERATORS:
            if source.startswith(op, i):
                tokens.append(Token("op", op, start))
                i += len(op)
                break
        else:
            raise MSyntaxError(f"Unexpected character {ch!r}", i, source)
