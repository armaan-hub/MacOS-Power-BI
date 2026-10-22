# Bidirectional Cross-Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement visual bidirectional cross-filtering mechanics inside the analytics studio, such that selecting a category in one visual curtails the row-context evaluation for all other visuals on the canvas.

**Architecture:** Connect the existing `self._cross_filters` dictionary in `StudioController` to the semantic evaluation path. When computing the dataset for visual B, we must compute the intersection of cross-filters propagated from visual A.
1. Extend `self._report_filter_context(visual_name)` in `StudioController` to intercept the local `_cross_filters` state and return the reduced row-indices dynamically evaluated against the semantic dimensions selected.
2. Ensure filtering is additive across multiple visuals. 
3. Create testing frameworks explicitly testing cross-filtering behavior inside `tests/test_interactions.py` or equivalent report tester.

**Tech Stack:** Python, PySide6, Qt Quick / QML (if adjustments needed), pytest.

**Spec:** `POWER_BI_DESKTOP_PARITY_BRAIN.md` and `POWER_BI_FUNCTIONALITY_ROADMAP.md` (Phase 8.1 Highlight and Cross-Filtering).

## Global Constraints

- No structural GUI dependencies to be placed inside the core data logic layers.
- Limit external UI libraries outside of PySide6/QML for UI state. 
- Must ensure cross-filter logic reacts dynamically (does not permanently mutate `_rows`), returning dynamic row subsets similar to DAX measure filters.

## Review Focus

- Selecting a dimension in Visual A filters rows correctly in Visual B.
- Selecting a dimension in Visual A does *not* recursively self-filter Visual A in un-expected ways (a cross-filter should self-highlight, usually not eliminate siblings).
- Desurfacing an element properly restores global state visually.
- Multi-dimensional selection (Option/Ctrl clicking equivalent) correctly performs OR limits within a visual, AND bounding across visual boundaries.

---

### Task 1: Extend `_report_filter_context` to handle active cross-filters

**Files:**
- Modify: `analytics_studio/controller.py`
- Test: `tests/test_report_interactions.py`

**Interfaces:**
- Consumes: `_cross_filters` (Dict[str, List[str]]) existing in controller.
- Produces: Correct subset of rows during QML data bindings. 

- [ ] **Step 1: Write the failing test for cross filtering interaction**

```python
import pytest
from analytics_studio.controller import StudioController
import pandas as pd

def test_cross_filtering_updates_peer_visual_rows(tmp_path):
    controller = StudioController()
    df = pd.DataFrame({
        "Category": ["A", "A", "B", "B"],
        "Value": [10, 20, 30, 40]
    })
    
    # Pre-setup mock project with 2 visuals
    controller._tables = {"T1": {"data": df}}
    controller._rows = list(range(len(df)))
    
    page = {
        "visuals": [
            {"title": "Vis1", "type": "bar", "fields": {"Category": ["T1", "Category"]}},
            {"title": "Vis2", "type": "bar", "fields": {"Category": ["T1", "Category"], "Y": ["T1", "Value"]}}
        ]
    }
    controller._project = {"report": {"pages": [page]}}
    
    # Initially Vis2 sees all 4 rows
    rows_before, _, _ = controller._report_filter_context("Vis2")
    assert len(rows_before.get("T1", [])) == 4
    
    # Toggle cross filter on Vis1 to 'A'
    controller._cross_filters = {"Vis1": ["A"]}
    
    # Peer Vis2 should now only see rows where Category == 'A'
    rows_after, _, _ = controller._report_filter_context("Vis2")
    assert len(rows_after.get("T1", [])) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report_interactions.py -v`
Expected: FAIL due to assertions, length being 4 instead of 2.

- [ ] **Step 3: Write minimal implementation in `analytics_studio/controller.py`**

Modify `_report_filter_context(self, visual_name: str)` logic so that after grabbing page-level/report-level filters, it iterates over `self._cross_filters`. If `cv_name != visual_name`, dynamically slice row inclusions by evaluating the selected category field vs. the filter's listed subset. 

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report_interactions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_report_interactions.py analytics_studio/controller.py
git commit -m "feat: apply cross filter selections onto report filter evaluation context"
```

### Task 2: Fix QML Slicer/Chart interaction bugs

**Files:**
- Modify: `analytics_studio/qml/Main.qml`
- Test: Playwright UI visual checks (or manual/test stub via qt testing if setup). For now, integration via `test_report_interactions.py` QML loading.

**Interfaces:**
- Consumes: The `toggle_cross_filter` slot.
- Produces: Correct visual highlight feedback on selected charts.

- [ ] **Step 1: Write a UI integration check**

```python
def test_cross_filter_persists_in_ui_model(tmp_path):
    controller = StudioController()
    controller.toggle_cross_filter("Vis1", "A")
    val = controller.selectedCrossFiltersForVisual("Vis1")
    assert val == ["A"]
    controller.toggle_cross_filter("Vis1", "A") 
    assert controller.selectedCrossFiltersForVisual("Vis1") == []
```

- [ ] **Step 2: Run test to verify it fails/passes** (It should pass due to previous commits but acts as regression).

Run: `pytest tests/test_report_interactions.py -v`

- [ ] **Step 3: Update `analytics_studio/qml/Main.qml` cross-filter toggling bounds (if required)**

Check that the existing cross-filter patch ensures clicks on Pie/Bar components properly inject `label` strings instead of arbitrary integers into `toggle_cross_filter`. (Patch it if missing inside the QML series onClicked signal).

- [ ] **Step 4: Test implementation**
Run: `pytest tests/test_report_interactions.py -v`

- [ ] **Step 5: Commit**

```bash
git add tests/test_report_interactions.py analytics_studio/qml/Main.qml
git commit -m "fix: enforce stable integration for cross filter slice toggling"
```
