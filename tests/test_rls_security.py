from __future__ import annotations

from types import SimpleNamespace

from analytics_studio.controller import StudioController


def test_role_preview_is_reported_unavailable_and_does_not_fake_rls() -> None:
    controller = StudioController()
    rows = [
        {"Region": "East", "Sales": "100"},
        {"Region": "West", "Sales": "200"},
    ]
    controller._source_id = "source-sales"
    controller._active_source_id = "source-sales"
    controller._headers = ["Region", "Sales"]
    controller._rows = rows
    controller._table_catalog = [{
        "id": "Sales",
        "sourceId": "source-sales",
        "loaded": True,
        "loadEnabled": True,
        "columnTypes": {},
    }]
    controller._loaded_candidates = {
        "source-sales": SimpleNamespace(headers=controller._headers, rows=rows)
    }
    controller._project["model"]["roles"] = {
        "EastRegion": {"tables": {"Sales": "East"}}
    }

    before, _, _ = controller._report_filter_context()
    controller.set_view_as_role("EastRegion")
    after, _, _ = controller._report_filter_context()

    assert before["Sales"] == rows
    assert after["Sales"] == rows
    assert "unavailable" in controller._status_message.lower()
    assert not hasattr(controller, "_tables")
