"""Install / drop the Critic-3 test models (ZO, ZB, ZS, ZM) in the live, unsaved Power BI Desktop model.

    PYTHONPATH=. python tools/pbi_model.py install ZO ZB     # replaces the live model with these models' tables, relationships, measures
    PYTHONPATH=. python tools/pbi_model.py drop              # back to an empty stand-in model
    PYTHONPATH=. python tools/pbi_model.py probe ZO ZB expressions.json   # install, add Facts, answer every expression, leave installed

Uses TMSL through ADOMD only (no UI); never saves the Power BI project.  Runs share the guest lock of tools/dax_oracle_diff.
"""
from __future__ import annotations

import base64
import json
import sys

from tests import critic3_models as m
from tools import dax_oracle_diff as dax

_TMSL_TYPE = {"string": "string", "int64": "int64", "double": "double", "dateTime": "dateTime"}
_PLACEHOLDER = {"string": '"x"', "int64": "0", "double": "0.0", "dateTime": "DATE(2000,1,1)"}


def _literal(value, kind: str) -> str:
    if value is None:
        return f"IF(TRUE(),BLANK(),{_PLACEHOLDER[kind]})"
    if kind == "dateTime":
        return "DATE(%d,%d,%d)" % value
    if kind == "string":
        return '"%s"' % str(value).replace('"', '""')
    return repr(value) if kind == "double" else str(value)


def _table_expression(columns, rows) -> str:
    if rows is None:
        return m.CAL_EXPR
    parts = []
    for row in rows:
        cells = ",".join('"%s",%s' % (name, _literal(v, kind)) for (name, kind), v in zip(columns, row))
        parts.append(f"ROW({cells})")
    return parts[0] if len(parts) == 1 else "UNION(" + ",".join(parts) + ")"


def _model_parts(model: str, with_measures: bool) -> tuple[list[dict], list[dict]]:
    spec = m.SPEC[model]
    roles = m._ROLES.get(model)
    tables = []
    for name, (columns, rows) in spec["tables"].items():
        table = {"name": name,
                 "columns": [{"name": c, "dataType": _TMSL_TYPE[k], "type": "calculatedTableColumn", "sourceColumn": f"[{c}]"} for c, k in columns],
                 "partitions": [{"name": "p", "source": {"type": "calculated", "expression": _table_expression(columns, rows)}}]}
        if with_measures and roles and name == roles[0]:
            table["measures"] = [{"name": k, "expression": t.format(F=roles[0], D=roles[1], C=roles[2])} for k, t in m._MEASURES.items()]
        tables.append(table)
    rels = []
    for n, ft, fc, tt, tc, active, both, fcard, tcard in spec["rels"]:
        rels.append({"name": n, "fromTable": ft, "fromColumn": fc, "toTable": tt, "toColumn": tc, "isActive": active,
                     "fromCardinality": fcard, "toCardinality": tcard,
                     "crossFilteringBehavior": "bothDirections" if both else "oneDirection"})
    return tables, rels


def _commands(models: list[str]) -> list[dict]:
    """Power BI Desktop only accepts relationships inside a whole-model replace, so the installed set is replaced as one."""
    tables: list[dict] = []
    rels: list[dict] = []
    for index, model in enumerate(models):
        t, r = _model_parts(model, with_measures=index == 0)  # measure names are global: only the first model gets mSum, mCnt, ...
        tables += t
        rels += r
    if not tables:  # a model needs a table; keep a one-row stand-in
        tables = [{"name": "Empty", "columns": [{"name": "x", "dataType": "int64", "type": "calculatedTableColumn", "sourceColumn": "[x]"}],
                   "partitions": [{"name": "p", "source": {"type": "calculated", "expression": 'ROW("x",1)'}}]}]
    model_body = {"culture": "en-US", "defaultPowerBIDataSourceVersion": "powerBI_V3", "tables": tables, "relationships": rels}
    return [{"createOrReplace": {"object": {"database": "__DB__"},
                                 "database": {"name": "__DB__", "compatibilityLevel": 1700, "model": model_body}}},
            {"refresh": {"type": "calculate", "objects": [{"database": "__DB__"}]}}]


def _run(port_: str, commands: list[dict], ok: str) -> str:
    payload = base64.b64encode(json.dumps(commands).encode()).decode()
    script = dax.PS_HEAD.replace("__PORT__", port_) + (
        f"\n$cs=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json\n"
        "$bad=$false\n"
        "foreach($k in $cs){ $t=($k | ConvertTo-Json -Depth 30 -Compress).Replace('__DB__',$c.Database)\n"
        " try{ $cmd=$c.CreateCommand(); $cmd.CommandText=$t; $null=$cmd.ExecuteNonQuery() }catch{ $bad=$true; 'ERR '+$t.Substring(0,[Math]::Min(120,$t.Length))+' :: '+($_.Exception.Message -replace '\\s+',' ') } }\n"
        f"if(-not $bad){{ '{ok}' }}\n$c.Close()")
    return dax.guest(script)


def install(port_: str, models: list[str]) -> None:
    """Replace the live model with exactly these models (and nothing else, so re-add Facts afterwards if needed)."""
    result = _run(port_, _commands(models), "MODEL_OK")
    if "MODEL_OK" not in result:
        raise SystemExit(f"could not install {models} in Power BI:\n{result}")


def drop(port_: str) -> None:
    install(port_, [])


def main() -> None:
    action, *rest = sys.argv[1:]
    p = dax.port()
    if action == "probe":
        models, path = rest[:-1], rest[-1]
        install(p, models)
        dax.ensure_facts(p)
        exprs = json.load(open(path))
        for e, a in zip(exprs, dax.power_bi(exprs, p)):
            print(f"{e}\n    -> {a}")
        return
    if action == "install":
        install(p, rest)
    else:
        drop(p)
    print(action, rest, "ok")


if __name__ == "__main__":
    main()
