"""Start the Qt Quick shell and expose its Python application controller."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController


def main() -> int:
    # Custom QML backgrounds are supported by the Basic Controls style.
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv)
    app.setApplicationName("Analytics Studio")
    app.setApplicationDisplayName("Analytics Studio")
    available_fonts = {name.casefold(): name for name in QFontDatabase.families()}
    ui_font = next(
        (available_fonts[name.casefold()] for name in ("Segoe UI", "Arial", "Helvetica Neue")
         if name.casefold() in available_fonts),
        "Arial",
    )
    app.setFont(QFont(ui_font))

    controller = StudioController(app)
    engine = QQmlApplicationEngine(app)
    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    component = QQmlComponent(engine)
    component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
    if component.isError():
        for error in component.errors():
            print(error.toString(), file=sys.stderr)
        return 1

    window = component.createWithInitialProperties({"studioController": controller})
    if window is None:
        for error in component.errors():
            print(error.toString(), file=sys.stderr)
        print(f"Could not load the Qt Quick interface: {qml_path}", file=sys.stderr)
        return 1

    if len(sys.argv) > 1:
        project_path = Path(sys.argv[1])
        QTimer.singleShot(0, lambda: controller.open_project_path(project_path))
    else:
        QTimer.singleShot(0, window.requestActivate)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
