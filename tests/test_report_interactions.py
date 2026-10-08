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
    assert len(rows_before.get("T1", controller._rows)) == 4
    
    # Toggle cross filter on Vis1 to 'A'
    controller._cross_filters = {"Vis1": ["A"]}
    
    # Peer Vis2 should now only see rows where Category == 'A'
    rows_after, _, _ = controller._report_filter_context("Vis2")
    assert len(rows_after.get("T1", controller._rows)) == 2

def test_cross_filter_persists_in_ui_model(tmp_path):
    controller = StudioController()
    controller.toggle_cross_filter("Vis1", "A")
    val = controller.selectedCrossFiltersForVisual("Vis1")
    assert val == ["A"]
    controller.toggle_cross_filter("Vis1", "A") 
    assert controller.selectedCrossFiltersForVisual("Vis1") == []
