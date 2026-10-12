"""Light, high-contrast styling for native authoring dialogs."""

LIGHT_DIALOG_STYLESHEET = """
QDialog {
    background-color: #f4f6f8;
    color: #243746;
}
QLabel, QCheckBox, QRadioButton, QGroupBox {
    color: #243746;
}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QListWidget,
QTableView, QTableWidget, QTreeView {
    background-color: #ffffff;
    color: #243746;
    border: 1px solid #c9d2da;
    selection-background-color: #d9edf9;
    selection-color: #17324d;
}
QComboBox::drop-down {
    border-left: 1px solid #c9d2da;
    width: 22px;
}
QHeaderView::section {
    background-color: #edf2f5;
    color: #30485b;
    border: 0;
    border-right: 1px solid #d6dee5;
    border-bottom: 1px solid #d6dee5;
    padding: 5px 7px;
}
QTabWidget::pane {
    background-color: #ffffff;
    border: 1px solid #c9d2da;
}
QTabBar::tab {
    background-color: #e8edf1;
    color: #30485b;
    border: 1px solid #c9d2da;
    padding: 6px 10px;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    color: #17324d;
}
QPushButton, QToolButton {
    background-color: #ffffff;
    color: #243746;
    border: 1px solid #bdc9d2;
    border-radius: 4px;
    padding: 5px 8px;
}
QPushButton:hover, QToolButton:hover {
    background-color: #edf6fb;
    border-color: #1683c4;
}
QPushButton:disabled, QToolButton:disabled {
    background-color: #edf0f2;
    color: #7c8993;
    border-color: #d6dde2;
}
QGroupBox {
    border: 1px solid #d1d9df;
    border-radius: 5px;
    margin-top: 8px;
    padding-top: 5px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 3px;
}
"""


def apply_light_dialog_theme(dialog: object) -> None:
    """Keep authoring controls readable when macOS itself is in dark mode."""
    set_style_sheet = getattr(dialog, "setStyleSheet", None)
    if callable(set_style_sheet):
        set_style_sheet(LIGHT_DIALOG_STYLESHEET)
