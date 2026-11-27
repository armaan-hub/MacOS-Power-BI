"""Stage D1c: named refusals for the three steps the store does not run (Part A item 3).

Each refusal is a plain sentence that names the step. The engine accepts these well-formed steps, so the tool
must refuse them by name (status "refused"), never skip them.
"""

from __future__ import annotations

import pytest

from tests.test_pq_store_diff_tool import _by_id, _run_items
from tests.test_pq_store_diff_tool_d1a import _tab
from tools.pq_store_diff import NAMED_UNSUPPORTED_REASONS, evaluate_exit_policy

NAMED_STEPS = [
    ("add_custom_column", {"op": "add_custom_column", "name": "c", "expression": "1"}),
    ("m_script", {"op": "m_script", "script": "let x = 1 in x", "source_binding": "x"}),
    ("m_sparse_boundary_helper", {"op": "m_sparse_boundary_helper", "name": "helper"}),
]
TABLE = _tab(["n", "k"], [["1", "r1"], ["", "r2"]])


@pytest.mark.parametrize("op,step", NAMED_STEPS, ids=[op for op, _ in NAMED_STEPS])
def test_well_formed_step_is_a_named_refusal(op: str, step: dict) -> None:
    data = _run_items(TABLE, [{"id": op, "step": step}])
    row = _by_id(data, op)
    assert row["status"] == "refused", row
    assert row["refusal_reason"] == NAMED_UNSUPPORTED_REASONS[op], row
    code, _ = evaluate_exit_policy(data, {"classes": [], "refused": [op]})
    assert code == 0


def test_reasons_are_plain_sentences_that_name_their_step() -> None:
    for op, reason in NAMED_UNSUPPORTED_REASONS.items():
        assert reason.startswith(op + ":") and reason.endswith("not mirrored."), reason


def test_add_custom_column_with_output_type_is_still_a_named_refusal() -> None:
    step = {"op": "add_custom_column", "name": "c", "expression": "1", "output_type": "text"}
    row = _by_id(_run_items(TABLE, [{"id": "ac_ot", "step": step}]), "ac_ot")
    assert row["status"] == "refused" and row["refusal_reason"] == NAMED_UNSUPPORTED_REASONS["add_custom_column"], row
