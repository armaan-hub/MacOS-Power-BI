from __future__ import annotations

from pathlib import Path
import pytest
from PySide6.QtCore import QMetaObject, QUrl, Qt, Q_ARG, Q_RETURN_ARG
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine


@pytest.fixture(scope="module")
def qapp():
    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication([])
    return app


@pytest.fixture
def chart_fixture(qapp):
    engine = QQmlEngine()
    qml_file = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "ChartCard.qml"
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_file)))
    assert component.status() == QQmlComponent.Status.Ready, component.errorString()
    item = component.create()
    assert item is not None
    yield {"engine": engine, "component": component, "chart": item}


def _invoke(item, method: str, *args):
    qargs = [Q_ARG("QVariant", a) for a in args]
    res = QMetaObject.invokeMethod(
        item,
        method,
        Qt.ConnectionType.DirectConnection,
        Q_RETURN_ARG("QVariant"),
        *qargs,
    )
    if hasattr(res, "toVariant"):
        return res.toVariant()
    return res


def test_nice_ticks_algorithms(chart_fixture):
    chart = chart_fixture["chart"]

    # niceTicks(0, 37) -> [0, 10, 20, 30, 40]
    ticks37 = [int(x) if x == int(x) else x for x in _invoke(chart, "niceTicks", 0, 37, 5)]
    assert ticks37 == [0, 10, 20, 30, 40]

    # niceTicks(0, 1234) -> [0, 250, 500, 750, 1000, 1250]
    ticks1234 = [int(x) if x == int(x) else x for x in _invoke(chart, "niceTicks", 0, 1234, 5)]
    assert ticks1234 == [0, 250, 500, 750, 1000, 1250]


def test_axis_value_labels(chart_fixture):
    chart = chart_fixture["chart"]

    assert _invoke(chart, "axisValueLabel", 2500, "K", 2500) == "2.5K"
    assert _invoke(chart, "axisValueLabel", 10000, "K", 10000) == "10K"
    assert _invoke(chart, "axisValueLabel", 3000000, "M", 3000000) == "3M"
    assert _invoke(chart, "axisValueLabel", 950, "", 950) == "950"
    assert _invoke(chart, "axisValueLabel", 4.2e9, "bn", 4.2e9) == "4.2bn"


def test_column_chart_value_axis_labels_toggle(chart_fixture):
    chart = chart_fixture["chart"]

    chart.setProperty("chartType", "column")
    chart.setProperty(
        "series",
        [
            {"label": "A", "value": 10},
            {"label": "B", "value": 37},
        ],
    )
    chart.setProperty("showYAxis", True)

    raw_labels = chart.property("valueAxisLabels")
    labels = raw_labels.toVariant() if hasattr(raw_labels, "toVariant") else raw_labels
    assert labels == ["0", "10", "20", "30", "40"]

    # When showYAxis is false, labels disappear
    chart.setProperty("showYAxis", False)
    raw_hidden = chart.property("valueAxisLabels")
    labels_hidden = raw_hidden.toVariant() if hasattr(raw_hidden, "toVariant") else raw_hidden
    assert labels_hidden == []


def test_bar_chart_value_axis_labels_toggle(chart_fixture):
    chart = chart_fixture["chart"]

    chart.setProperty("chartType", "bar")
    chart.setProperty(
        "series",
        [
            {"label": "Cat1", "value": 15},
            {"label": "Cat2", "value": 37},
        ],
    )
    chart.setProperty("showXAxis", True)

    raw_labels = chart.property("valueAxisLabels")
    labels = raw_labels.toVariant() if hasattr(raw_labels, "toVariant") else raw_labels
    assert labels == ["0", "10", "20", "30", "40"]

    # When showXAxis is false, labels disappear
    chart.setProperty("showXAxis", False)
    raw_hidden = chart.property("valueAxisLabels")
    labels_hidden = raw_hidden.toVariant() if hasattr(raw_hidden, "toVariant") else raw_hidden
    assert labels_hidden == []


def test_negative_values_axis(chart_fixture):
    chart = chart_fixture["chart"]

    chart.setProperty("chartType", "column")
    chart.setProperty(
        "series",
        [
            {"label": "A", "value": -35},
            {"label": "B", "value": 15},
        ],
    )
    chart.setProperty("showYAxis", True)

    ticks = _invoke(chart, "computeValueTicks", "column", chart.property("series"), [])
    assert ticks[0] <= -35
    assert ticks[-1] >= 15
    assert 0 in ticks

    raw_labels = chart.property("valueAxisLabels")
    labels = raw_labels.toVariant() if hasattr(raw_labels, "toVariant") else raw_labels
    assert len(labels) > 0
    assert any("-" in lbl for lbl in labels)
