from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file

QQuickStyle.setStyle("Basic")


def _controller(tmp_path: Path) -> tuple[StudioController, Path]:
    app = QApplication.instance() or QApplication(["visual interaction tests"])
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        "Category,Amount\nA,10\nA,20\nB,50\n",
        encoding="utf-8",
    )
    controller = StudioController(
        app,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    assert controller._commit_import(csv_path, parse_file(csv_path))
    controller._active_page()["visuals"] = []
    controller.add_visual("bar", "Source", 40, 40, 360, 240)
    controller.add_field_to_well("X-axis", "Category")
    controller.add_visual("column", "Target", 420, 40, 360, 240)
    controller.add_field_to_well("X-axis", "Category")
    controller.add_field_to_well("Y-axis", "Amount")
    controller.selectVisual("Source")
    return controller, csv_path


def test_filter_highlight_and_none_modes_apply_to_visual_pair(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)
    page = controller._active_page()
    source = next(item for item in page["visuals"] if item["title"] == "Source")
    target = next(item for item in page["visuals"] if item["title"] == "Target")

    assert controller.activeVisualInteractions == [
        {"title": "Target", "mode": "filter", "mode_index": 0}
    ]
    controller.set_visual_interaction("Source", "Target", "Highlight")
    assert page["visual_interactions"] == [{
        "source_visual_id": source["id"],
        "target_visual_id": target["id"],
        "mode": "highlight",
    }]
    controller.toggle_cross_filter("Source", "A")
    assert controller.visualSeries("Target") == [
        {"label": "A", "value": 30.0},
        {"label": "B", "value": 50.0},
    ]
    assert controller.visualHighlightSeries("Target") == [
        {"label": "A", "value": 30.0},
    ]

    controller.set_visual_interaction("Source", "Target", "None")
    assert controller.visualSeries("Target") == [
        {"label": "A", "value": 30.0},
        {"label": "B", "value": 50.0},
    ]
    assert controller.visualHighlightSeries("Target") == []

    controller.set_visual_interaction("Source", "Target", "Filter")
    assert page["visual_interactions"] == []
    assert controller.visualSeries("Target") == [{"label": "A", "value": 30.0}]


def test_interaction_mode_persists_and_replays_after_reopen(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)
    controller.set_visual_interaction("Source", "Target", "Highlight")
    project_path = tmp_path / "visual-interactions.npa"
    assert controller._save_to(project_path)

    reopened = StudioController(
        QApplication.instance(),
        QSettings(str(tmp_path / "reopened-settings.ini"), QSettings.Format.IniFormat),
    )
    assert reopened.open_project_path(project_path)
    reopened.selectVisual("Source")
    assert reopened.activeVisualInteractions == [
        {"title": "Target", "mode": "highlight", "mode_index": 1}
    ]
    reopened.toggle_cross_filter("Source", "A")
    assert reopened.visualSeries("Target") == [
        {"label": "A", "value": 30.0},
        {"label": "B", "value": 50.0},
    ]
    assert reopened.visualHighlightSeries("Target") == [
        {"label": "A", "value": 30.0},
    ]


def test_removing_either_visual_clears_saved_pair_settings(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)
    page = controller._active_page()
    source = next(item for item in page["visuals"] if item["title"] == "Source")
    target = next(item for item in page["visuals"] if item["title"] == "Target")
    controller.set_visual_interaction("Source", "Target", "Highlight")

    controller.remove_visual(target["id"])

    assert page["visual_interactions"] == []
    assert controller.visualHighlightSeries("Target") == []
    controller.add_visual("column", "Target", 420, 40, 360, 240)
    controller.selectVisual("Source")
    assert controller.activeVisualInteractions == [
        {"title": "Target", "mode": "filter", "mode_index": 0}
    ]
    assert source in page["visuals"]
    from analytics_studio.project import validate_project

    validate_project(controller._project)


def test_build_pane_exposes_filter_highlight_and_none_modes(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["visual interaction QML tests"])
    controller, _ = _controller(tmp_path)
    controller._dirty = False
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    qml_path = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(error.toString() for error in component.errors())

    def items(item: QQuickItem):
        yield item
        for child in item.childItems():
            yield from items(child)

    try:
        window.show()
        controller.setCurrentView("Report")
        controller.selectVisual("Source")
        app.processEvents()
        combo = next(
            item for item in items(window.contentItem())
            if item.objectName() == "visualInteractionMode" and item.isVisible()
        )
        assert list(combo.property("model")) == ["Filter", "Highlight", "None"]
        combo.chooseInteraction(1)
        app.processEvents()
        assert controller.activeVisualInteractions[0]["mode"] == "highlight"
        assert combo.property("currentIndex") == 1
    finally:
        controller._dirty = False
        window.close()
        window.deleteLater()
        engine.deleteLater()
        app.processEvents()
