import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
import pandas as pd
from collections import namedtuple
from analytics_studio.controller import StudioController

MockCandidate = namedtuple("MockCandidate", ["headers", "rows"])

def test_rls_active_role_filters_rows(tmp_path):
    controller = StudioController()
    
    # Mock data
    df = pd.DataFrame({"Region": ["East", "West", "North"], "Sales": [100, 200, 300]})
    controller._tables = {"Sales": {"data": df}}
    
    # Mock Table Catalog and candidates
    controller._table_catalog = [
        {"id": "Sales", "name": "Sales", "loadEnabled": True, "loaded": True, "sourceId": "s1"}
    ]
    # Rows are typically list of dicts mapped directly from df
    rows = df.to_dict(orient="records")
    controller._loaded_candidates = {
        "s1": MockCandidate(headers=["Region", "Sales"], rows=rows)
    }
    
    # Mock Project with Roles
    controller._project = {
        "model": {
            "roles": {
                "EastRegion": {
                    "tables": {"Sales": "East"} 
                }
            }
        },
        "report": {"pages": [{"visuals": [{"title": "V1", "fields": {"Val": ["Sales", "Sales"]}}]}]}
    }
    
    # Default (No Role)
    controller._source_id = "s1" # Needed for measure context check in some logic
    rows_all, _, _ = controller._report_filter_context("V1")
    assert len(rows_all.get("Sales", [])) == 3
    
    # View as EastRegion
    controller.set_view_as_role("EastRegion")
    rows_east, _, _ = controller._report_filter_context("V1")
    assert len(rows_east.get("Sales", [])) == 1
    
    # Verify exact selected row
    selected_row = rows_east["Sales"][0]
    assert selected_row["Region"] == "East"
