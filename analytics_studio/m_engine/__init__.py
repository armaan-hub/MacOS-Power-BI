"""Power Query M language engine (Part A: lexer and parser).

Exports ``parse`` (source text to AST) and ``MSyntaxError``.
"""

from __future__ import annotations

from .lexer import MSyntaxError
from .parser import parse

__all__ = ["parse", "MSyntaxError"]
