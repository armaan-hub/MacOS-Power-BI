import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import pandas as pd
from analytics_studio.controller import StudioController

def test_rls_active_role_filters_rows(tmp_path):
    controller = StudioController()
    
    # Mock data
    df = pd.DataFrame({"Region": ["East", "West", "North"], "Sales": [100, 200, 300]})
    controller._tables = {"Sales": {"data": df}}
    
    # Generate initial rows list equivalent
    controller._rows = {"Sales": list(range(len(df)))} # Keep consistent with dict structure
    
    # Mock Project with Roles
    controller._project = {
        "model": {
            "roles": {
                "EastRegion": {
                    "tables": {"Sales": "East"} # Simple substring/equality for mock DAX evaluator currently
                }
            }
        },
        "report": {"pages": [{"visuals": [{"title": "V1", "fields": {"Val": ["Sales", "Sales"]}}]}]}
    }
    
    # Default (No Role)
    rows_all, _, _ = controller._report_filter_context("V1")
    # if it's missing, defaults to full length
    assert len(rows_all.get("Sales", list(range(len(df))))) == 3
    
    # View as EastRegion
    controller.set_view_as_role("EastRegion")
    rows_east, _, _ = controller._report_filter_context("V1")
    assert len(rows_east.get("Sales", [])) == 1
    
    selected_idx = rows_east["Sales"][0]
    assert df.iloc[selected_idx]["Region"] == "East"
