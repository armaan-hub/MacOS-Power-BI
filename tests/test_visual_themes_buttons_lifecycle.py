from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.project import REPORT_THEMES


def _controller(tmp_path: Path) -> StudioController:
    app = QApplication.instance() or QApplication(["visual theme and button tests"])
    return StudioController(
        app,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )


def test_report_theme_survives_refresh_save_and_reopen(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.add_visual("bar", "First chart", 10, 10, 220, 150)
    controller.add_visual("column", "Second chart", 240, 10, 220, 150)

    controller.set_report_theme("Sunset")

    assert controller.reportTheme == "Sunset"
    assert controller._project["report"]["theme"] == "Sunset"
    assert all(
        visual["color"] == REPORT_THEMES["Sunset"]["primary"]
        for visual in controller.activeVisualObjects
    )
    controller.selectVisual("First chart")
    controller.set_visual_property("title", "Updated chart")
    assert controller.reportTheme == "Sunset"

    project_path = tmp_path / "themed.npa"
    assert controller._save_to(project_path)
    reopened = _controller(tmp_path)
    assert reopened.open_project_path(project_path)

    assert reopened.reportTheme == "Sunset"
    assert reopened._project["report"]["theme"] == "Sunset"
    assert all(
        visual["color"] == REPORT_THEMES["Sunset"]["primary"]
        for visual in reopened.activeVisualObjects
    )


def test_button_url_action_is_editable_persisted_and_uses_desktop_handler(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)
    controller.add_visual("button", "Open site", 10, 10, 130, 36)
    controller.set_visual_property("text", "Visit dashboard")
    controller.set_visual_property("actionUrl", "https://example.com/report")

    action_group = next(
        group for group in controller.activeVisualPropertyGroups
        if group["name"] == "Action"
    )
    action_properties = {item["key"]: item["value"] for item in action_group["properties"]}
    assert action_properties == {
        "actionUrl": "https://example.com/report",
        "text": "Visit dashboard",
    }

    project_path = tmp_path / "button-action.npa"
    assert controller._save_to(project_path)
    reopened = _controller(tmp_path)
    assert reopened.open_project_path(project_path)
    reopened.selectVisual("Open site")
    visual = next(item for item in reopened.activeVisualObjects if item["title"] == "Open site")
    assert visual["text"] == "Visit dashboard"
    assert visual["actionUrl"] == "https://example.com/report"

    with patch("analytics_studio.controller._open_external_url", return_value=True) as open_url:
        assert reopened.open_button_action(visual["actionUrl"])
        open_url.assert_called_once()
        assert open_url.call_args.args[0].toString() == "https://example.com/report"

    with patch("analytics_studio.controller._open_external_url") as open_url:
        assert not reopened.open_button_action("file:///tmp/private.txt")
        open_url.assert_not_called()
