"""Differential DAX check: Power BI Desktop (Parallels guest, ADOMD) vs the local evaluator.

Run from the repo root:  PYTHONPATH=. python tools/dax_oracle_diff.py [battery.json]
Needs the Parallels VM "Windows 11" with Power BI Desktop open (any project; the script
creates a scratch calculated table `Facts` in the *unsaved* in-memory model only).
Read-only otherwise; never saves the Power BI project.
"""
from __future__ import annotations

import base64
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time
from decimal import Decimal, InvalidOperation

from analytics_studio import dax_dates
from analytics_studio.measures import MeasureError, evaluate_measures

VM = "Windows 11"
HEADERS = ["Sales", "Quantity", "Region", "Note"]
ROWS = [
    ("10.5", "2", "East", "Paid"),
    ("20", "3", "West", ""),
    ("-1.5", "1", "East", "Paid"),
    ("", "4", "North", "Late"),
    ("0", "0", "West", "Paid"),
    ("2.5", "5", "East", ""),
]
# The loaded model stores a blank cell as None; "" would be a distinct empty-text value.
LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(HEADERS, row)} for row in ROWS]


def _dax_row(row: tuple[str, ...]) -> str:
    sales = "IF(TRUE(),BLANK(),0.0)" if row[0] == "" else row[0]
    note = 'IF(TRUE(),BLANK(),"x")' if row[3] == "" else f'"{row[3]}"'
    return f'ROW("Sales",{sales},"Quantity",{row[1]},"Region","{row[2]}","Note",{note})'


FACTS_DAX = "UNION(" + ",".join(_dax_row(r) for r in ROWS) + ")"

PS_HEAD = r"""
$ProgressPreference='SilentlyContinue'
$p=Split-Path (Get-Process PBIDesktop).Path
Add-Type -Path "$p\Microsoft.PowerBI.AdomdClient.dll"
$c=New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:__PORT__")
$c.Open()
function Run($q){ try{ $cmd=$c.CreateCommand(); $cmd.CommandText=$q; $r=$cmd.ExecuteReader(); $v=$null; while($r.Read()){ $v=$r.GetValue(0) }; $r.Close(); if($v -eq $null -or $v -is [DBNull]){'BLANK'}else{ [string]$v } }catch{ 'ERR:'+($_.Exception.Message -replace '\s+',' ') } }
"""


def guest(script: str) -> str:
    """Run a PowerShell script in the guest via the shared Mac home folder (no argv length limit)."""
    folder = Path.home() / ".rea_scratch"
    folder.mkdir(exist_ok=True)
    name = f"run-{time.time_ns()}.ps1"  # fresh name each call: the guest's share view caches by path
    (folder / name).write_text("\ufeff" + script, encoding="utf-8")
    # one guest call at a time across every process (the guest is slow when queries overlap)
    with open(folder / "guest.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        out = subprocess.run(
            # no --current-user: the script then runs as SYSTEM in session 0, which has no desktop, so no window can open
            # (it still reaches the shared folder and Power BI's local port)
            ["prlctl", "exec", VM, "powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", rf"\\Mac\Home\.rea_scratch\{name}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        ).stdout
    (folder / name).unlink(missing_ok=True)
    return "\n".join(line for line in out.splitlines() if not line.startswith(("#< CLIXML", "<Objs")))


def port() -> str:
    out = guest("(Get-NetTCPConnection -State Listen -OwningProcess (Get-Process msmdsrv).Id | Select -First 1).LocalPort")
    return out.strip().splitlines()[-1].strip()


def ensure_facts(port_: str) -> None:
    tmsl = json.dumps({"createOrReplace": {"object": {"database": "__DB__", "table": "Facts"}, "table": {
        "name": "Facts", "columns": [
            {"name": "Sales", "dataType": "double", "type": "calculatedTableColumn", "sourceColumn": "[Sales]"},
            {"name": "Quantity", "dataType": "int64", "type": "calculatedTableColumn", "sourceColumn": "[Quantity]"},
            {"name": "Region", "dataType": "string", "type": "calculatedTableColumn", "sourceColumn": "[Region]"},
            {"name": "Note", "dataType": "string", "type": "calculatedTableColumn", "sourceColumn": "[Note]"}],
        "partitions": [{"name": "p", "source": {"type": "calculated", "expression": FACTS_DAX}}]}}})
    script = PS_HEAD.replace("__PORT__", port_) + "\n$t=@'\n" + tmsl + "\n'@\n$t=$t.Replace('__DB__',$c.Database)\n" \
        "$cmd=$c.CreateCommand(); $cmd.CommandText=$t; try{$null=$cmd.ExecuteNonQuery(); $cmd2=$c.CreateCommand(); $cmd2.CommandText='{\"refresh\":{\"type\":\"calculate\",\"objects\":[{\"database\":\"'+$c.Database+'\",\"table\":\"Facts\"}]}}'; $null=$cmd2.ExecuteNonQuery(); 'FACTS_OK'}catch{'FACTS_ERR '+$_.Exception.Message}\n$c.Close()"
    result = guest(script)
    if "FACTS_OK" not in result:
        raise SystemExit(f"could not create Facts in Power BI: {result}")


def drop_facts(port_: str) -> None:
    script = PS_HEAD.replace("__PORT__", port_) + (
        "\n$cmd=$c.CreateCommand(); $cmd.CommandText='{\"delete\":{\"object\":{\"database\":\"'+$c.Database+'\",\"table\":\"Facts\"}}}'\n"
        "try{$null=$cmd.ExecuteNonQuery(); 'DROPPED'}catch{'DROP_ERR '+$_.Exception.Message}\n$c.Close()"
    )
    if "DROPPED" not in guest(script):
        print("WARNING: could not delete scratch table Facts from the Power BI model; remove it manually.")


def power_bi(expressions: list[str], port_: str, chunk: int = 250) -> list[str]:
    """Power BI's answer for every expression, asked in chunks so a large battery never outruns the guest call timeout."""
    if len(expressions) > chunk:
        answers: list[str] = []
        for start in range(0, len(expressions), chunk):
            answers += power_bi(expressions[start:start + chunk], port_, chunk)
        return answers
    payload = base64.b64encode(json.dumps(expressions).encode()).decode()
    script = PS_HEAD.replace("__PORT__", port_) + (
        f"\n$ex=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json\n"
        "foreach($e in $ex){ 'R|' + (Run ('EVALUATE ROW(\"v\", ' + $e + ')')) }\n$c.Close()"
    )
    for _attempt in range(3):  # the guest sometimes returns nothing for a chunk; never let that shift the answers
        answers = [line[2:] for line in guest(script).splitlines() if line.startswith("R|")]
        if len(answers) == len(expressions):
            return answers
    raise RuntimeError(f"Power BI returned {len(answers)} answers for {len(expressions)} expressions after 3 tries")


def local(expression: str) -> str:
    try:
        value = evaluate_measures(
            [{"name": "Probe__", "expression": expression}], LOCAL_ROWS, HEADERS, "Facts", measure_names=["Probe__"],
            table_context=[{
                "id": "facts", "name": "Facts", "headers": HEADERS, "rows": LOCAL_ROWS,
                "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"},
            }],
            active_table_id="facts",
        )["Probe__"]
    except MeasureError as error:
        return f"LOCAL-REJECT:{error}"
    except Exception as error:  # surface evaluator crashes as findings, never hide them
        return f"LOCAL-CRASH:{type(error).__name__}:{error}"
    if isinstance(value, dax_dates.DaxDateTime):
        return dax_dates.oracle_text(value)
    return "BLANK" if value is None else str(value)


def same(pbi: str, loc: str) -> bool:
    if pbi == loc:
        return True
    try:
        a, b = Decimal(pbi), Decimal(loc)
    except InvalidOperation:
        return pbi.lower() == loc.lower() and pbi in ("True", "False")
    if not a.is_finite() or not b.is_finite():
        return False  # NaN / Infinity are equal only as the same text (checked above); subtracting them raises or hides a sign difference
    return abs(a - b) <= Decimal("1e-9") * max(Decimal(1), abs(a))


def main() -> None:
    battery = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else json.load(open("tools/dax_battery.json"))
    p = port()
    ensure_facts(p)
    try:
        pbi = power_bi(battery, p)
    finally:
        drop_facts(p)
    assert len(pbi) == len(battery), (len(pbi), len(battery))
    report = []
    for expr, theirs in zip(battery, pbi):
        ours = local(expr)
        both_reject = theirs.startswith("ERR") and ours.startswith("LOCAL-REJECT")
        status = "match" if same(theirs, ours) or both_reject else ("gap-reject" if ours.startswith("LOCAL-REJECT") and not theirs.startswith("ERR") else "DIFF")
        report.append({"expr": expr, "powerbi": theirs, "local": ours, "status": status})
    for item in report:
        print(f"{item['status']:10} {item['expr']}\n           PBI={item['powerbi'][:110]}\n           LOC={item['local'][:110]}")
    counts = {s: sum(1 for i in report if i["status"] == s) for s in ("match", "gap-reject", "DIFF")}
    print(counts)
    json.dump(report, open("tools/dax_oracle_report.json", "w"), indent=1)


if __name__ == "__main__":
    main()
