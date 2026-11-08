"""Power Query (M) language engine.

Part A (Iteration 188): ``parse`` (source text to AST) and ``MSyntaxError``.
Part B (Task 100): ``evaluate_to_text`` (source text to Power BI's answer text).
"""

from __future__ import annotations

from .evaluator import evaluate_to_text
from .lexer import MSyntaxError
from .parser import parse

__all__ = ["parse", "MSyntaxError", "evaluate_to_text"]
