"""Start the real Analytics Studio shell (same setup as main.py, hidden offscreen window), load the standing test
workbook tests/Data/Vat File -Aug 2026.xlsx (sheet 'VAT 5%', header row 12), create the Power BI-verified measure
battery through the app, build visuals, save and reopen.  Screenshots and results go to the folder given as argv[1].

    QT_QPA_PLATFORM=offscreen PYTHONPATH=. python tools/app_smoke.py /tmp/app_smoke_out

Needs tools/table_oracle_report_VAT.json, written by:
    PYTHONPATH=. python tools/table_oracle_diff.py "tests/Data/Vat File -Aug 2026.xlsx" --header-row 12 --sheet "VAT 5%" --name VAT
"""
import json, os, sys, tempfile
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication
from analytics_studio.controller import StudioController, _visual_measure_binding
from analytics_studio.file_import import parse_file

OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
QQuickStyle.setStyle("Basic")
app = QApplication(["Analytics Studio"])
settings = QSettings(str(OUT / "settings.ini"), QSettings.Format.IniFormat)
controller = StudioController(app, settings)
engine = QQmlApplicationEngine(app)
comp = QQmlComponent(engine)
comp.loadUrl(QUrl.fromLocalFile(str(ROOT / "analytics_studio/qml/Main.qml")))
assert not comp.isError(), [e.toString() for e in comp.errors()]
window = comp.createWithInitialProperties({"studioController": controller})
assert window is not None
window.resize(1600, 900); window.show(); app.processEvents()
def shot(name):
    app.processEvents(); app.processEvents()
    img = window.grabWindow(); img.save(str(OUT / f"{name}.png")); print("screenshot", name, img.width(), img.height())

shot("01_start")
dsi = ROOT / "tests/Data/Vat File -Aug 2026.xlsx"
cand = parse_file(dsi, {"header_row": 12, "sheet_name": "VAT 5%"})
print("parsed:", len(cand.rows), "rows;", cand.headers)
ok = controller._commit_import(dsi, cand)
print("commit_import:", ok, "| status:", controller.statusMessage if hasattr(controller,'statusMessage') else '')
print("source:", controller.sourceName, "rows:", controller.rowCount if hasattr(controller,'rowCount') else '?', "headers:", controller.headers)
controller.setCurrentView("Data"); shot("02_data_view")
controller.setCurrentView("Model"); shot("03_model_view")
controller.setCurrentView("Report"); shot("04_report_view")

print("modelTables:", controller.modelTables)
table = controller.modelTables[0]
print("table name in model:", table)
import re
from decimal import Decimal, InvalidOperation
report = json.load(open(str(ROOT / "tools/table_oracle_report_VAT.json")))["measures"]
def prep(expr): return re.sub(r"\bVAT(?=[\[,)])", "VAT" if table == "VAT" else f"'{table}'", expr)
def equal(pbi, shown):
    if pbi == shown: return True
    if pbi == "BLANK" and shown == "\u2014": return True      # the app shows a blank measure as an em dash
    if re.fullmatch(r"\d\d/\d\d/\d{4} \d\d:\d\d:\d\d", pbi):    # a DateTime result: compare as the app's date text
        from datetime import datetime as _dt
        from analytics_studio import dax_dates
        return shown == dax_dates.date_text(dax_dates.from_datetime(_dt.strptime(pbi, "%m/%d/%Y %H:%M:%S")))
    try: a = Decimal(pbi); b = Decimal(shown.replace(",", ""))
    except InvalidOperation: return pbi.lower() == shown.lower()
    return abs(a - b) <= Decimal("0.0051")   # the app displays at most 2 decimals
created = refused = 0; mism = []; refusals = []
BATCH = 90
for start in range(0, len(report), BATCH):
    batch = report[start:start + BATCH]; names = []
    for i, e in enumerate(batch):
        name = f"M{start+i:03d}"
        if controller.create_measure(name, prep(e["expr"])): created += 1; names.append((name, e))
        else: refused += 1; refusals.append(e["expr"])
    shown = {m["name"]: m for m in controller.modelMeasures}
    for name, e in names:
        m = shown[name]; val = ("ERR:" + str(m["error"])) if m.get("error") else ("BLANK" if m.get("value") is None else str(m["value"]))
        if not equal(e["powerbi"], val): mism.append((e["expr"], e["powerbi"], val))
    if start == 0: shot("05_model_with_90_measures")
    for name, _ in names: controller.remove_measure(name)
print(f"MEASURES THROUGH THE APP: {created} created, {refused} refused by the app; {created-len(mism)} equal to Power BI, {len(mism)} different")
for r in refusals[:5]: print("  refused:", r)
for m in mism[:12]: print("  DIFF", m)

# visuals on the real data
for name, expr in (("Total Value", "SUM(VAT[Value])"), ("VAT Total", "SUM(VAT[VAT-5%])"), ("Rows", "COUNTROWS(VAT)")):
    print("create", name, controller.create_measure(name, prep(expr)))
controller.setCurrentView("Report"); app.processEvents()
print("card:", controller.add_visual("card", "Total value", 14, 14, 220, 110))
controller.add_field_to_well("Fields", _visual_measure_binding("Total Value"))
print("card data:", controller.visualCardData("Total value"))
print("bar:", controller.add_visual("column", "Value by emirate", 14, 140, 520, 300))
for w, f in (("X-axis", "Emirates"), ("Y-axis", "Value")): controller.add_field_to_well(w, f)
print("bar series:", controller.visualSeries("Value by emirate")[:5])
print("table:", controller.add_visual("table", "Details", 550, 140, 520, 300))
for f in ("Date", "Particulars", "Value", "Gross Total"): controller.add_field_to_well("Fields", f)
td = controller.visualTableData("Details"); print("table cols/rows:", td["columns"], td["total_rows"])
shot("06_report_with_visuals")

# save, reopen
proj = OUT / "vat_test.npa"
print("saved:", controller._save_to(proj))
reopened = StudioController(app, QSettings(str(OUT / "settings2.ini"), QSettings.Format.IniFormat))
print("reopen:", reopened.open_project_path(proj), "| rows:", reopened.rowCount, "| tables:", reopened.modelTables,
      "| measures:", [m["name"] for m in reopened.modelMeasures], "| visuals:", [v["title"] for v in reopened.activeVisualObjects])
print("card after reopen:", reopened.visualCardData("Total value")["value"])

# Everything is printed; skip Qt's interpreter-shutdown teardown, which can segfault on the live QML items and pop up a macOS crash window.
sys.stdout.flush(); sys.stderr.flush()
os._exit(0)
