# Phase 9: Security (Row-Level Security) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Row-Level Security (RLS) rules and "View As Role" simulation within the native analytics engine.

**Architecture:** We will extend the `Controller` to track an `active_role` and store `roles` in the semantic project schema. We will alter the base DAX/Pandas query path (`_report_filter_context` / data extraction) to intersect the RLS DAX filters before applying visual filters.

**Tech Stack:** Python, PySide6, QML, pytest.

**Spec:** Phase 9 of POWER_BI_FUNCTIONALITY_ROADMAP.md.

## Global Constraints
- Do not introduce massive external parser libraries just for RLS. Pre-evaluate DAX mappings using existing tools.
- Strict Ponytail rule: Keep the implementation bare-metal local (no cloud dependencies for Phase 9).

## Review Focus
- Bypassing RLS: Cross-filtering from another table should not expose hidden rows.
- Invalid syntax: Bad DAX in a role should error softly in Manage Roles without crashing the app.

---

### Task 1: Engine Support for Active Roles

**Files:**
- Modify: `analytics_studio/controller.py`
- Test: `tests/test_rls_security.py` (Create)

- [ ] **Step 1: Write the failing test**

```python
import pytest
import pandas as pd
from analytics_studio.controller import StudioController

def test_rls_active_role_filters_rows(tmp_path):
    controller = StudioController()
    
    # Mock data
    df = pd.DataFrame({"Region": ["East", "West", "North"], "Sales": [100, 200, 300]})
    controller._tables = {"Sales": {"data": df}}
    controller._rows = list(range(len(df)))
    
    # Mock Project with Roles
    controller._project = {
        "model": {
            "roles": {
                "EastRegion": {
                    "tables": {"Sales": "Region = 'East'"}
                }
            }
        },
        "report": {"pages": [{"visuals": [{"title": "V1", "fields": {"Val": ["Sales", "Sales"]}}]}]}
    }
    
    # Default (No Role)
    rows_all, _, _ = controller._report_filter_context("V1")
    assert len(rows_all.get("Sales", [])) == 3
    
    # View as EastRegion
    controller.set_view_as_role("EastRegion")
    rows_east, _, _ = controller._report_filter_context("V1")
    assert len(rows_east.get("Sales", [])) == 1
    
    selected_idx = rows_east["Sales"][0]
    assert df.iloc[selected_idx]["Region"] == "East"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_rls_security.py -v`
Expected: FAIL, missing `set_view_as_role` and output len 3 != 1.

- [ ] **Step 3: Write minimal implementation**
In `analytics_studio/controller.py`, add:
```python
def set_view_as_role(self, role_name: str):
    self._active_role = role_name
    self.refresh_all_visuals() # or equivalent
```
Modify `_report_filter_context` to read `self._project.get("model", {}).get("roles", {})`. If `_active_role` is set, parse the expression (e.g., simplistic string exact match or passing to DAX pandas parser) and intersect bounding `_rows`.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_rls_security.py -v`

- [ ] **Step 5: Commit**
```bash
git add tests/test_rls_security.py analytics_studio/controller.py
git commit -m "feat: core RLS data masking driven by active role context"
```
