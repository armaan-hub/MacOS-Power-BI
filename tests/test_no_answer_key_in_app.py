"""The app must compute its answers. No code in analytics_studio may read the saved Power BI answers.

Why this test exists: the first build of LINEST/LINESTX (iteration 95) "matched" all 219 saved Power BI answers by loading
tools/parity/dax_battery_linest.json at run time and returning the stored text. It passed the gate and was wrong for
every input outside the file. Docstrings may still name the batteries they were compared with; code may not touch them.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "analytics_studio"
FORBIDDEN_SUBSTRINGS = ("tools/parity", "tools\\parity", "dax_battery", "parity_check", "PARITY_LEDGER", "oracle_diff", "table_oracle")
FORBIDDEN_EXACT = {"tools", "parity"}  # os.path.join(root, "tools", "parity", ...)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                nodes.add(id(body[0].value))
    return nodes


class NoAnswerKeyInAppTest(unittest.TestCase):
    def test_app_code_never_reads_saved_power_bi_answers(self) -> None:
        offences = []
        for path in sorted(APP.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            docstrings = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "tools" for alias in node.names):
                    offences.append(f"{path.name}:{node.lineno} imports tools")
                elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "tools":
                    offences.append(f"{path.name}:{node.lineno} imports from tools")
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                    text = node.value
                    if text in FORBIDDEN_EXACT or any(part in text for part in FORBIDDEN_SUBSTRINGS):
                        offences.append(f"{path.name}:{node.lineno} string {text[:60]!r}")
        self.assertEqual([], offences)


if __name__ == "__main__":
    unittest.main()
