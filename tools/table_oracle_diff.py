"""Table-level differential check: a real workbook loaded by Power BI Desktop vs the local importer + evaluator.

Run from the repo root:
    PYTHONPATH=. python tools/table_oracle_diff.py /Users/armaan/Downloads/DSI.xlsx --header-row 6 [--name DSI]

Power BI side: the workbook is imported by Power BI's own Power Query engine into a scratch table (TMSL
`createOrReplace` with an M partition on the unsaved model, no UI involved), every cell is dumped through ADOMD
and a measure battery is run. Local side: `file_import.parse_file` + `infer_column_types` + `evaluate_measures`.
The scratch table is dropped afterwards; the workbook and the Power BI project are never modified.
Needs the Parallels VM "Windows 11" with Power BI Desktop open and the Mac home mounted as \\\\Mac\\Home.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

from analytics_studio import dax_dates
from analytics_studio.controller import _model_candidate_with_format_errors_as_blank
from analytics_studio.file_import import parse_file
from analytics_studio.measures import MeasureError, evaluate_measures
from analytics_studio.transformations import infer_column_types
from tools.dax_oracle_diff import PS_HEAD, guest, port, power_bi, same

M_TYPE = {"text": "type text", "date": "type date", "decimal_number": "type number", "whole_number": "Int64.Type"}
TMSL_TYPE = {"text": "string", "date": "dateTime", "decimal_number": "double", "whole_number": "int64"}


def guest_path(path: Path) -> str:
    """Windows path of a Mac file under the home folder, as seen from the guest."""
    return "\\\\Mac\\Home\\" + str(path.resolve().relative_to(Path.home())).replace("/", "\\")


def create_table(port_: str, name: str, path: Path, header_row: int, types: dict[str, str], sheet: str | None = None) -> None:
    cols = ", ".join(f'{{"{h}", {M_TYPE[t]}}}' for h, t in types.items())
    selector = "0" if sheet is None else '[Item="%s",Kind="Sheet"]' % sheet.replace('"', '""')
    m = (
        'let\n Source = Excel.Workbook(File.Contents("%s"), null, false),\n Sheet = Source{%s}[Data],\n'
        ' Skipped = Table.Skip(Sheet, %d),\n Promoted = Table.PromoteHeaders(Skipped, [PromoteAllScalars=true]),\n'
        ' Typed = Table.TransformColumnTypes(Promoted, {%s})\nin\n Typed' % (guest_path(path), selector, header_row - 1, cols)
    )
    tmsl = json.dumps({"createOrReplace": {"object": {"database": "__DB__", "table": name}, "table": {
        "name": name,
        "columns": [{"name": h, "dataType": TMSL_TYPE[t], "sourceColumn": h} for h, t in types.items()],
        "partitions": [{"name": "p", "mode": "import", "source": {"type": "m", "expression": m}}]}}})
    refresh = '{"refresh":{"type":"full","objects":[{"database":"\'+$c.Database+\'","table":"%s"}]}}' % name
    script = PS_HEAD.replace("__PORT__", port_) + "\n$t=@'\n" + tmsl + "\n'@\n$t=$t.Replace('__DB__',$c.Database)\n" \
        "$cmd=$c.CreateCommand(); $cmd.CommandText=$t\n" \
        "try{$null=$cmd.ExecuteNonQuery(); $r=$c.CreateCommand(); $r.CommandText='" + refresh + "'; $null=$r.ExecuteNonQuery(); 'TABLE_OK'}" \
        "catch{'TABLE_ERR '+$_.Exception.Message}\n$c.Close()"
    result = guest(script)
    if "TABLE_OK" not in result:
        raise SystemExit(f"could not load the workbook into Power BI: {result}")


def drop_table(port_: str, name: str) -> None:
    script = PS_HEAD.replace("__PORT__", port_) + (
        "\n$cmd=$c.CreateCommand(); $cmd.CommandText='{\"delete\":{\"object\":{\"database\":\"'+$c.Database+'\",\"table\":\"" + name + "\"}}}'\n"
        "try{$null=$cmd.ExecuteNonQuery(); 'DROPPED'}catch{'DROP_ERR '+$_.Exception.Message}\n$c.Close()")
    if "DROPPED" not in guest(script):
        print(f"WARNING: could not delete scratch table {name} from the Power BI model; remove it manually.")


def dump_table(port_: str, name: str) -> list[dict[str, object]]:
    """Every cell of the Power BI table: doubles as round-trip text, dates as ISO text, blanks as null."""
    out_name = f"dump-{time.time_ns()}.json"
    out = Path.home() / ".rea_scratch" / out_name
    script = PS_HEAD.replace("__PORT__", port_) + f"""
$ci=[Globalization.CultureInfo]::InvariantCulture
$cmd=$c.CreateCommand(); $cmd.CommandText='EVALUATE {name}'; $r=$cmd.ExecuteReader(); $rows=New-Object System.Collections.ArrayList
while($r.Read()){{ $o=[ordered]@{{}}; for($i=0;$i -lt $r.FieldCount;$i++){{ $n=$r.GetName($i) -replace '^.*\\[|\\]$',''; $v=$r.GetValue($i)
  if($v -is [DBNull] -or $v -eq $null){{$o[$n]=$null}} elseif($v -is [double]){{$o[$n]='D:'+$v.ToString('R',$ci)}} elseif($v -is [datetime]){{$o[$n]='T:'+$v.ToString('s',$ci)}} else {{$o[$n]='S:'+[string]$v}} }}
  [void]$rows.Add($o) }}
$r.Close(); $c.Close()
ConvertTo-Json -InputObject @($rows) -Depth 4 -Compress | Out-File -Encoding utf8 '\\\\Mac\\Home\\.rea_scratch\\{out_name}'
'DUMPED'"""
    if "DUMPED" not in guest(script):
        raise SystemExit("could not dump the Power BI table")
    data = json.loads(out.read_text(encoding="utf-8-sig"))
    out.unlink(missing_ok=True)
    return data


def _local_cell(value: object, kind: str) -> object:
    if value is None or value == "":
        return None
    if kind == "decimal_number":
        return repr(float(value))
    if kind == "date":
        return value.isoformat() if isinstance(value, date) else f"?{value!r}"
    return str(value)


def _pbi_cell(value: object, kind: str) -> object:
    if value is None or value == "S:":
        return None
    if kind == "decimal_number":
        return repr(float(value[2:]))
    if kind == "date":
        return value[2:12] if value.endswith("T00:00:00") else f"?{value}"
    return value[2:]


def compare_cells(headers: list[str], types: dict[str, str], rows: list[dict], theirs: list[dict]) -> list[str]:
    """Row order and column order out of `EVALUATE` are not guaranteed, so compare the two tables as multisets of rows."""
    findings: list[str] = []
    if len(rows) != len(theirs):
        findings.append(f"row count: local {len(rows)} vs Power BI {len(theirs)}")
    if sorted(theirs[0].keys()) != sorted(headers):
        findings.append(f"column names: local {headers} vs Power BI {list(theirs[0].keys())}")
    mine = Counter(tuple(_local_cell(r[h], types[h]) for h in headers) for r in rows)
    pbi = Counter(tuple(_pbi_cell(r.get(h), types[h]) for h in headers) for r in theirs)
    for row, count in (mine - pbi).items():
        findings.append(f"only local x{count}: {row}")
    for row, count in (pbi - mine).items():
        findings.append(f"only Power BI x{count}: {row}")
    text_diffs = sum(
        1 for r in rows for h in headers
        if types[h] == "decimal_number" and r[h] is not None and str(r[h]) != repr(float(r[h])).removesuffix(".0")
    )
    if text_diffs:
        findings.append(
            f"info: {text_diffs} decimal cells are the same double as Power BI's but the local Decimal keeps the workbook's "
            "17-digit text (for example 66.150000000000006) where Power BI shows the shortest double (66.15)")
    return findings


def battery(name: str, headers: list[str], types: dict[str, str], rows: list[dict]) -> list[str]:
    numeric = [h for h, t in types.items() if t == "decimal_number"]
    texts = [h for h, t in types.items() if t == "text"]
    expressions: list[str] = [f"COUNTROWS({name})"]
    for h in numeric:
        col = f"{name}[{h}]"
        expressions += [f"SUM({col})", f"AVERAGE({col})", f"MIN({col})", f"MAX({col})", f"COUNT({col})",
                        f"COUNTBLANK({col})", f"MEDIAN({col})", f"DISTINCTCOUNT({col})", f"SUMX({name},{col}*2)"]
    for h in texts:
        expressions += [f"DISTINCTCOUNT({name}[{h}])", f"COUNTA({name}[{h}])", f"COUNTBLANK({name}[{h}])"]
    roles = [("Gross Amt", "Gross Total"), ("Disc Amt", "Discount"), ("VAT Amt", "Input Vat"), ("Net Amount", "Value")]
    picked = [next((x for x in role if x in numeric), None) for role in roles]
    spare = [h for h in numeric if h not in picked]
    g, d, v, n = (f"{name}[{x or spare.pop(0)}]" for x in picked)
    expressions += [
        f"SUMX({name},{g}-{d}+{v})", f"SUM({n})-SUM({g})-SUM({v})+SUM({d})", f"DIVIDE(SUM({v}),SUM({g}))",
        f"SUM({v})/SUM({g})", f"CALCULATE(SUM({n}),{g}>10000)", f"COUNTROWS(FILTER({name},{n}>10000))",
        f"SUMX(FILTER({name},{v}>0),{v})", f"IF(ISBLANK(SUM({n})),0,SUM({n}))", f"ROUND(SUM({v})/SUM({g}),4)",
        f"CALCULATE(COUNTROWS({name}),{d}>0)", f"MAXX({name},{n})", f"MINX({name},{n})",
        f"AVERAGEX({name},{v}/{g})", f"COUNTX({name},{v})",
    ]
    for h in (h for h, t in types.items() if t == "date"):
        col = f"{name}[{h}]"
        seen = sorted({r[h] for r in rows if r[h] is not None})
        if not seen:
            continue
        mid = seen[len(seen) // 2]
        pivot = f"DATE({mid.year},{mid.month},{mid.day})"
        expressions += [
            f"MIN({col})", f"MAX({col})", f"COUNT({col})", f"COUNTBLANK({col})", f"DISTINCTCOUNT({col})",
            f"YEAR(MAX({col}))", f"MONTH(MIN({col}))", f"DATEDIFF(MIN({col}),MAX({col}),DAY)",
            f'FORMAT(MAX({col}),"dd-MMM-yyyy")', f"EOMONTH(MAX({col}),0)", f"CALCULATE(SUM({n}),{col}>={pivot})",
            f"CALCULATE(COUNTROWS({name}),{col}=MIN({col}))", f"SUMX({name},IF({col}>{pivot},1,0))",
            f"COUNTX({name},YEAR({col}))", f"MAXX({name},{col})", f"MINX({name},DAY({col}))", f"SELECTEDVALUE({col})",
            f"SUMX({name},WEEKDAY({col}))", f"CALCULATE(SUM({n}),{col}<{pivot})", f"MAX({col})-MIN({col})",
            f"MAX({col})&\"\"", f'FORMAT(MIN({col}),"dddd, d MMMM yyyy")', f"WEEKNUM(MAX({col}))",
            f"CALCULATE(COUNTROWS({name}),{col}>=EDATE({pivot},-1))",
        ]
    small = [h for h in texts if len({r[h] for r in rows if r[h] is not None}) <= 25 and not any(
        ord(ch) < 32 for r in rows if r[h] for ch in r[h])]
    for h in small[:2]:
        col = f"{name}[{h}]"
        expressions += [
            f"COUNTROWS(VALUES({col}))", f"COUNTROWS(DISTINCT({col}))", f"MAX({col})", f"MIN({col})", f'SELECTEDVALUE({col},"many")',
            f"HASONEVALUE({col})", f"SUMX(VALUES({col}),CALCULATE(SUM({n})))", f"MAXX(VALUES({col}),CALCULATE(SUM({n})))",
            f"SUMX({name},LEN({col}))", f'COUNTX({name},IF(LEFT({col},1)="A",1,BLANK()))', f"UPPER(MAX({col}))", f"LEN(MIN({col}))",
            f'CONCATENATEX(VALUES({col}),{col},", ",{col},ASC)', f'CONCATENATEX(VALUES({col}),{col}&"="&FORMAT(CALCULATE(SUM({n})),"#,0.00"),"; ",{col},DESC)',
            f'AVERAGEX(VALUES({col}),CALCULATE(SUM({n})))', f'COUNTROWS(FILTER({name},{col}<>MAX({col})))',
        ]
    expressions += [
        f'IF(SUM({n})>0,"pos","neg")', f'FORMAT(SUM({n}),"#,0.00")', f'"Total: "&FORMAT(SUM({n}),"#,0")', f"SUM({n})&\"\"",
        f'FORMAT(SUM({v})/SUM({g}),"0.00%")', f'VAR t=SUM({n}) VAR s=SUM({g}) RETURN IF(s=0,BLANK(),t/s)',
        f"SUM({n})^2", f"CONVERT(SUM({n}),INTEGER)", f"ROUND(SUM({n}),1)&\"\"", f"SUM({g})>SUM({n})", f"AND(SUM({n})>0,SUM({g})>0)",
    ]
    party = "Party Name" if "Party Name" in headers else ("Particulars" if "Particulars" in headers else texts[0])
    # a literal holding CR/LF cannot travel through the guest script intact (checked live: UNICHAR(13)&UNICHAR(10) matches)
    for value in sorted({r[party] for r in rows if r[party] and not any(ord(ch) < 32 for ch in r[party])}):
        escaped = value.replace('"', '""')
        expressions += [f'CALCULATE(SUM({n}),{name}[{party}]="{escaped}")', f'CALCULATE(COUNTROWS({name}),{name}[{party}]="{escaped}")']
    return expressions


def local_value(expression: str, name: str, headers: list[str], types: dict[str, str], rows: list[dict]) -> str:
    try:
        value = evaluate_measures(
            [{"name": "M", "expression": expression}], rows, headers, name, measure_names=["M"],
            table_context=[{"id": name.lower(), "name": name, "headers": headers, "rows": rows, "column_types": types}],
            active_table_id=name.lower())["M"]
    except MeasureError as error:
        return f"LOCAL-REJECT:{error}"
    except Exception as error:  # evaluator crashes are findings, never hidden
        return f"LOCAL-CRASH:{type(error).__name__}:{error}"
    if isinstance(value, dax_dates.DaxDateTime):
        return dax_dates.oracle_text(value)
    return "BLANK" if value is None else str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook")
    parser.add_argument("--header-row", type=int, default=1)
    parser.add_argument("--name", default="DSI")
    parser.add_argument("--sheet", default=None, help="worksheet name; default is the first sheet in Power BI and the importer's own choice locally")
    parser.add_argument("--keep", action="store_true", help="leave the scratch table in the model for ad-hoc queries")
    args = parser.parse_args()
    path = Path(args.workbook).expanduser()
    candidate = parse_file(path, {"header_row": args.header_row, **({"sheet_name": args.sheet} if args.sheet else {})})
    headers = candidate.headers
    types = infer_column_types(headers, candidate.rows)
    # what the app's model holds after the load step (trailing spaces trimmed, ASCII-case variants merged)
    rows = [dict(r) for r in _model_candidate_with_format_errors_as_blank(candidate).rows]
    print(f"local import: {len(rows)} rows, types {types}")

    p = port()
    create_table(p, args.name, path, args.header_row, types, args.sheet)
    try:
        theirs = dump_table(p, args.name)
        expressions = battery(args.name, headers, types, rows)
        pbi = power_bi(expressions, p)
    finally:
        if not args.keep:
            drop_table(p, args.name)

    print("\n== cell-by-cell import comparison ==")
    cell_findings = compare_cells(headers, types, rows, theirs)
    print("\n".join(cell_findings[:40]) or "all cells identical")

    print("\n== measure battery ==")
    report = []
    for expression, answer in zip(expressions, pbi):
        ours = local_value(expression, args.name, headers, types, rows)
        both_reject = answer.startswith("ERR") and ours.startswith("LOCAL-REJECT")
        status = "match" if same(answer, ours) or both_reject else (
            "gap-reject" if ours.startswith("LOCAL-REJECT") and not answer.startswith("ERR") else "DIFF")
        report.append({"expr": expression, "powerbi": answer, "local": ours, "status": status})
    for item in report:
        if item["status"] != "match":
            print(f"{item['status']:10} {item['expr']}\n           PBI={item['powerbi'][:100]}\n           LOC={item['local'][:100]}")
    counts = {s: sum(1 for i in report if i["status"] == s) for s in ("match", "gap-reject", "DIFF")}
    print(counts, f"of {len(report)} expressions; cell findings: {len([f for f in cell_findings if not f.startswith('info')])}")
    json.dump({"cells": cell_findings, "measures": report}, open("tools/table_oracle_report.json" if args.name == "DSI" else f"tools/table_oracle_report_{args.name}.json", "w"), indent=1)


if __name__ == "__main__":
    sys.exit(main())
