"""Deterministic exit-test model generator and verifier for Power BI (guest and local).

Models an enterprise sales dataset with 7 tables, active and inactive relationships,
many-to-many bridge, unknown members, blanks, and budget for TREATAS.
"""
from __future__ import annotations

import base64
import datetime
from decimal import Decimal
import fcntl
import json
import os
import random
import sys
import time
from typing import Any

def _ensure_blocking() -> None:
    for fd in (0, 1, 2):
        try:
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            if fl & os.O_NONBLOCK:
                fcntl.fcntl(fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
        except Exception:
            pass

_ensure_blocking()

from analytics_studio import dax_dates
from analytics_studio.measures import MeasureError, evaluate_measures
from analytics_studio.power_query_values import model_text_normalizer
from tools import dax_oracle_diff as dax

# Seed specified in brief
MODEL_SEED = 20261122

# Schema definitions
TABLE_SPECS: dict[str, list[tuple[str, str]]] = {
    "XT_Date": [
        ("Date", "date"),
        ("Year", "int64"),
        ("MonthNumber", "int64"),
        ("Month", "string"),
        ("Quarter", "string"),
        ("YearMonth", "int64"),
        ("IsWeekend", "boolean"),
    ],
    "XT_Region": [
        ("RegionKey", "int64"),
        ("Region", "string"),
        ("Country", "string"),
    ],
    "XT_Product": [
        ("ProductKey", "int64"),
        ("Product", "string"),
        ("Category", "string"),
        ("Subcategory", "string"),
        ("ListPrice", "decimal"),
        ("Color", "string"),
    ],
    "XT_Customer": [
        ("CustomerKey", "int64"),
        ("Customer", "string"),
        ("Segment", "string"),
        ("FirstOrderDate", "date"),
    ],
    "XT_CustomerRegion": [
        ("CustomerKey", "int64"),
        ("RegionKey", "int64"),
    ],
    "XT_Sales": [
        ("SalesKey", "int64"),
        ("OrderDate", "date"),
        ("ShipDate", "date"),
        ("ProductKey", "int64"),
        ("CustomerKey", "int64"),
        ("RegionKey", "int64"),
        ("Quantity", "int64"),
        ("UnitPrice", "decimal"),
        ("Discount", "double"),
        ("SalesAmount", "decimal"),
        ("Channel", "string"),
    ],
    "XT_Budget": [
        ("YearMonth", "int64"),
        ("Category", "string"),
        ("BudgetAmount", "decimal"),
    ],
}

# Type mappings
# TMSL dataType: int64, string, decimal (fixed decimal currency), double, dateTime, boolean
_TMSL_DATA_TYPES = {
    "int64": "int64",
    "string": "string",
    "decimal": "decimal",
    "double": "double",
    "date": "dateTime",
    "boolean": "boolean",
}

# DAX DATATABLE types: INTEGER, STRING, CURRENCY, DOUBLE, DATETIME, BOOLEAN
_DAX_DATATABLE_TYPES = {
    "int64": "INTEGER",
    "string": "STRING",
    "decimal": "CURRENCY",
    "double": "DOUBLE",
    "date": "DATETIME",
    "boolean": "BOOLEAN",
}

# Local evaluator column_types mapping:
# whole_number, text, currency (fixed decimal), decimal_number (double), date, boolean
_LOCAL_COLUMN_TYPES = {
    "int64": "whole_number",
    "string": "text",
    "decimal": "currency",
    "double": "decimal_number",
    "date": "date",
    "boolean": "boolean",
}

# Relationship specs: (name, from_table, from_col, to_table, to_col, is_active, both_dir, from_card, to_card)
RELATIONSHIP_SPECS = [
    ("rel_sales_date_order", "XT_Sales", "OrderDate", "XT_Date", "Date", True, False, "many", "one"),
    ("rel_sales_date_ship", "XT_Sales", "ShipDate", "XT_Date", "Date", False, False, "many", "one"),
    ("rel_sales_product", "XT_Sales", "ProductKey", "XT_Product", "ProductKey", True, False, "many", "one"),
    ("rel_sales_customer", "XT_Sales", "CustomerKey", "XT_Customer", "CustomerKey", True, False, "many", "one"),
    ("rel_sales_region", "XT_Sales", "RegionKey", "XT_Region", "RegionKey", True, False, "many", "one"),
    ("rel_custreg_customer", "XT_CustomerRegion", "CustomerKey", "XT_Customer", "CustomerKey", True, False, "many", "one"),
    ("rel_custreg_region", "XT_CustomerRegion", "RegionKey", "XT_Region", "RegionKey", True, False, "many", "one"),
]


def generate_data(seed: int = MODEL_SEED) -> dict[str, list[dict[str, Any]]]:
    """Deterministically generate the raw table rows according to spec."""
    rng = random.Random(seed)

    # 1. XT_Date (2023-01-01 .. 2025-12-31)
    start_date = datetime.date(2023, 1, 1)
    end_date = datetime.date(2025, 12, 31)
    cur = start_date
    date_rows = []
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    all_dates = []
    while cur <= end_date:
        all_dates.append(cur)
        quarter = f"Q{(cur.month - 1) // 3 + 1}"
        year_month = cur.year * 100 + cur.month
        is_weekend = cur.weekday() >= 5
        date_rows.append({
            "Date": cur.isoformat(),
            "Year": cur.year,
            "MonthNumber": cur.month,
            "Month": month_names[cur.month - 1],
            "Quarter": quarter,
            "YearMonth": year_month,
            "IsWeekend": is_weekend,
        })
        cur += datetime.timedelta(days=1)

    # 2. XT_Region
    regions = [
        {"RegionKey": 1, "Region": "North", "Country": "USA"},
        {"RegionKey": 2, "Region": "South", "Country": "USA"},
        {"RegionKey": 3, "Region": "East", "Country": "Canada"},
        {"RegionKey": 4, "Region": "West", "Country": "Canada"},
        {"RegionKey": 5, "Region": "Central", "Country": "Mexico"},
    ]

    # 3. XT_Product (ProductKey 1..60)
    categories = [f"Cat_{i}" for i in range(1, 7)]
    subcategories = [f"Subcat_{i}" for i in range(1, 16)]
    colors = ["Red", "Blue", "Black", "Silver", "White", None]
    product_rows = []
    for pk in range(1, 61):
        cat = categories[(pk - 1) % 6]
        subcat = subcategories[(pk - 1) % 15]
        price = round(Decimal(str(rng.uniform(5.0, 500.0))), 2)
        color = rng.choice(colors)
        product_rows.append({
            "ProductKey": pk,
            "Product": f"Product_{pk}",
            "Category": cat,
            "Subcategory": subcat,
            "ListPrice": price,
            "Color": color,
        })

    # 4. XT_Customer (CustomerKey 1..800)
    segments = ["Consumer", "Corporate", "Home Office", "Small Business"]
    customer_rows = []
    for ck in range(1, 801):
        seg = segments[(ck - 1) % 4]
        fod = None if rng.random() < 0.1 else rng.choice(all_dates).isoformat()
        customer_rows.append({
            "CustomerKey": ck,
            "Customer": f"Customer_{ck}",
            "Segment": seg,
            "FirstOrderDate": fod,
        })

    # 5. XT_CustomerRegion bridge (1..3 regions per customer)
    customer_region_rows = []
    for ck in range(1, 801):
        num_regs = rng.randint(1, 3)
        chosen_regs = rng.sample(range(1, 6), num_regs)
        for rk in chosen_regs:
            customer_region_rows.append({
                "CustomerKey": ck,
                "RegionKey": rk,
            })

    # 6. XT_Sales (12,000 rows)
    sales_rows = []
    channels = ["Store", "Online", "Partner"]
    for sk in range(1, 12001):
        order_date = rng.choice(all_dates)
        if rng.random() < 0.05:
            ship_date = None
        else:
            ship_date = (order_date + datetime.timedelta(days=rng.randint(0, 10))).isoformat()

        # ~1% unknown product (key 999)
        prod_key = 999 if rng.random() < 0.01 else rng.randint(1, 60)

        # ~1% blank customer
        cust_key = None if rng.random() < 0.01 else rng.randint(1, 800)

        reg_key = rng.randint(1, 5)
        qty = rng.randint(1, 20)
        unit_price = round(Decimal(str(rng.uniform(5.0, 500.0))), 2)
        disc_float = round(rng.uniform(0.0, 0.3), 2)
        discount = disc_float
        raw_amt = Decimal(qty) * unit_price * (Decimal("1") - Decimal(str(discount)))
        sales_amount = round(raw_amt, 2)
        channel = rng.choice(channels)

        sales_rows.append({
            "SalesKey": sk,
            "OrderDate": order_date.isoformat(),
            "ShipDate": ship_date,
            "ProductKey": prod_key,
            "CustomerKey": cust_key,
            "RegionKey": reg_key,
            "Quantity": qty,
            "UnitPrice": unit_price,
            "Discount": discount,
            "SalesAmount": sales_amount,
            "Channel": channel,
        })

    # 7. XT_Budget (216 rows)
    budget_rows = []
    for y in [2023, 2024, 2025]:
        for m in range(1, 13):
            ym = y * 100 + m
            for cat in categories:
                b_amt = round(Decimal(str(rng.uniform(10000.0, 50000.0))), 2)
                budget_rows.append({
                    "YearMonth": ym,
                    "Category": cat,
                    "BudgetAmount": b_amt,
                })

    return {
        "XT_Date": date_rows,
        "XT_Region": regions,
        "XT_Product": product_rows,
        "XT_Customer": customer_rows,
        "XT_CustomerRegion": customer_region_rows,
        "XT_Sales": sales_rows,
        "XT_Budget": budget_rows,
    }


def _dax_literal(value: Any, col_type: str) -> str:
    """Format a value for a DAX DATATABLE row tuple."""
    if value is None:
        return "BLANK()"
    if col_type == "string":
        escaped = str(value).replace('"', '""')
        return f'"{escaped}"'
    if col_type == "boolean":
        return "TRUE" if value else "FALSE"
    if col_type == "date":
        return f'"{value}"'
    return str(value)


def _build_dax_datatable_chunk(columns: list[tuple[str, str]], rows: list[dict[str, Any]]) -> str:
    """Build a single DATATABLE DAX expression for a slice of rows."""
    col_defs = ", ".join(f'"{name}", {_DAX_DATATABLE_TYPES[kind]}' for name, kind in columns)
    row_literals = []
    for r in rows:
        cells = ", ".join(_dax_literal(r[name], kind) for name, kind in columns)
        row_literals.append(f"{{{cells}}}")
    return f"DATATABLE({col_defs}, {{{', '.join(row_literals)}}})"


def build_partition_expression(table_name: str, rows: list[dict[str, Any]], chunk_size: int = 2000) -> str:
    """Build the calculated table partition expression, chunking into UNION(DATATABLE(...)) if large."""
    columns = TABLE_SPECS[table_name]
    if len(rows) <= chunk_size:
        return _build_dax_datatable_chunk(columns, rows)
    chunks = [rows[i:i + chunk_size] for i in range(0, len(rows), chunk_size)]
    return "UNION(" + ", ".join(_build_dax_datatable_chunk(columns, chunk) for chunk in chunks) + ")"


def tmsl_model_definition(data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Generate the full TMSL model definition including tables and relationships."""
    tables = []
    for name, columns in TABLE_SPECS.items():
        rows = data[name]
        col_objects = []
        for col_name, kind in columns:
            col_def = {
                "name": col_name,
                "dataType": _TMSL_DATA_TYPES[kind],
                "type": "calculatedTableColumn",
                "sourceColumn": f"[{col_name}]",
            }
            if name == "XT_Date" and col_name == "Date":
                col_def["isKey"] = True
            col_objects.append(col_def)

        table_def: dict[str, Any] = {
            "name": name,
            "columns": col_objects,
            "partitions": [{
                "name": "p",
                "source": {
                    "type": "calculated",
                    "expression": build_partition_expression(name, rows),
                },
            }],
        }
        if name == "XT_Date":
            table_def["dataCategory"] = "Time"

        tables.append(table_def)

    rels = []
    for r_name, from_tbl, from_col, to_tbl, to_col, active, both, from_card, to_card in RELATIONSHIP_SPECS:
        rels.append({
            "name": r_name,
            "fromTable": from_tbl,
            "fromColumn": from_col,
            "toTable": to_tbl,
            "toColumn": to_col,
            "isActive": active,
            "fromCardinality": from_card,
            "toCardinality": to_card,
            "crossFilteringBehavior": "bothDirections" if both else "oneDirection",
        })

    return {
        "culture": "en-US",
        "defaultPowerBIDataSourceVersion": "powerBI_V3",
        "tables": tables,
        "relationships": rels,
    }


def compute_expected_aggregates(data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Calculate expected aggregates for all tables in Python."""
    aggregates: dict[str, dict[str, Any]] = {}
    for table_name, columns in TABLE_SPECS.items():
        rows = data[table_name]
        table_aggs: dict[str, Any] = {
            "COUNTROWS": len(rows),
            "COUNTBLANK": {},
            "SUM": {},
        }
        for col_name, kind in columns:
            blanks = sum(1 for r in rows if r[col_name] is None)
            table_aggs["COUNTBLANK"][col_name] = blanks
            if kind in ("int64", "decimal", "double"):
                total = sum((r[col_name] for r in rows if r[col_name] is not None), Decimal("0") if kind == "decimal" else 0.0 if kind == "double" else 0)
                table_aggs["SUM"][col_name] = total
        aggregates[table_name] = table_aggs
    return aggregates


def get_guest_port() -> str:
    """Retrieve the Power BI listening port with retries."""
    for _ in range(5):
        try:
            p = dax.port()
            if p:
                return p
        except Exception:
            time.sleep(0.5)
    return dax.port()


def install_guest_model(port_: str, data: dict[str, list[dict[str, Any]]]) -> None:
    """Deploy the exit model into Power BI via TMSL createOrReplace."""
    model_body = tmsl_model_definition(data)
    cmds = [
        {"createOrReplace": {"object": {"database": "__DB__"}, "database": {"name": "__DB__", "compatibilityLevel": 1700, "model": model_body}}},
        {"refresh": {"type": "calculate", "objects": [{"database": "__DB__"}]}},
    ]
    payload = base64.b64encode(json.dumps(cmds).encode()).decode()
    script = dax.PS_HEAD.replace("__PORT__", port_) + f"""
$cs = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("{payload}")).Replace("__DB__", $c.Database) | ConvertFrom-Json
$bad = $false
foreach($k in $cs){{
    $t = ($k | ConvertTo-Json -Depth 30 -Compress)
    $cmd = $c.CreateCommand()
    $cmd.CommandText = $t
    try {{
        $null = $cmd.ExecuteNonQuery()
    }} catch {{
        $bad = $true
        Write-Output ("TMSL_ERR: " + $_.Exception.ToString())
    }}
}}
if(-not $bad){{ Write-Output "INSTALL_OK" }}
$c.Close()
"""
    for attempt in range(3):
        result = dax.guest(script)
        if "INSTALL_OK" in result:
            return
        time.sleep(1.0)
    raise RuntimeError(f"Could not install exit model in Power BI after 3 tries:\n{result}")


def drop_guest_model(port_: str) -> None:
    """Remove the exit model from Power BI, leaving only a 1-row Empty stand-in."""
    empty_body = {
        "culture": "en-US",
        "defaultPowerBIDataSourceVersion": "powerBI_V3",
        "tables": [
            {
                "name": "Empty",
                "columns": [{"name": "x", "dataType": "int64", "type": "calculatedTableColumn", "sourceColumn": "[x]"}],
                "partitions": [{"name": "p", "source": {"type": "calculated", "expression": 'ROW("x",1)'}}],
            }
        ],
        "relationships": [],
    }
    cmds = [
        {"createOrReplace": {"object": {"database": "__DB__"}, "database": {"name": "__DB__", "compatibilityLevel": 1700, "model": empty_body}}},
        {"refresh": {"type": "calculate", "objects": [{"database": "__DB__"}]}},
    ]
    payload = base64.b64encode(json.dumps(cmds).encode()).decode()
    script = dax.PS_HEAD.replace("__PORT__", port_) + f"""
$cs = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("{payload}")).Replace("__DB__", $c.Database) | ConvertFrom-Json
foreach($k in $cs){{
    $t = ($k | ConvertTo-Json -Depth 30 -Compress)
    $cmd = $c.CreateCommand()
    $cmd.CommandText = $t
    try {{ $null = $cmd.ExecuteNonQuery() }} catch {{}}
}}
$c.Close()
Write-Output "DROPPED"
"""
    dax.guest(script)


def list_guest_model_tables(port_: str) -> list[str]:
    """Query DMV to verify which user tables currently exist in Power BI."""
    script = dax.PS_HEAD.replace("__PORT__", port_) + """
$cmd = $c.CreateCommand()
$cmd.CommandText = "SELECT [Name] FROM `$SYSTEM.TMSCHEMA_TABLES"
$r = $cmd.ExecuteReader()
while($r.Read()){ Write-Output $r["Name"] }
$r.Close()
$c.Close()
"""
    out = dax.guest(script)
    return [line.strip() for line in out.splitlines() if line.strip() and not line.strip().startswith("DateTableTemplate")]


def verify_guest(data: dict[str, list[dict[str, Any]]], port_: str) -> dict[str, Any]:
    """Verify in the guest that every table count, sum, countblank, and sales sumx match Python."""
    exp = compute_expected_aggregates(data)
    queries: list[str] = []
    keys: list[tuple[str, str, str]] = []  # (table, metric, col)

    for tbl_name, spec in TABLE_SPECS.items():
        queries.append(f"COUNTROWS({tbl_name})")
        keys.append((tbl_name, "COUNTROWS", ""))
        for col_name, kind in spec:
            queries.append(f"COUNTBLANK({tbl_name}[{col_name}])")
            keys.append((tbl_name, "COUNTBLANK", col_name))
            if kind in ("int64", "decimal", "double"):
                queries.append(f"SUM({tbl_name}[{col_name}])")
                keys.append((tbl_name, "SUM", col_name))

    # SalesAmount SUMX with ROUND
    queries.append("SUMX(XT_Sales, ROUND(XT_Sales[SalesAmount], 2))")
    keys.append(("XT_Sales", "SUMX_ROUND", "SalesAmount"))

    answers = dax.power_bi(queries, port_, chunk=200)
    results = []
    all_match = True

    for (tbl_name, metric, col), ans in zip(keys, answers):
        if metric == "COUNTROWS":
            expected = str(exp[tbl_name]["COUNTROWS"])
        elif metric == "COUNTBLANK":
            expected = "BLANK" if exp[tbl_name]["COUNTBLANK"][col] == 0 else str(exp[tbl_name]["COUNTBLANK"][col])
        elif metric == "SUM":
            val = exp[tbl_name]["SUM"][col]
            expected = str(val)
        elif metric == "SUMX_ROUND":
            expected = str(exp["XT_Sales"]["SUM"]["SalesAmount"])

        is_same = dax.same(ans, expected)
        if not is_same:
            all_match = False
        results.append({
            "table": tbl_name,
            "metric": metric,
            "column": col,
            "expected": expected,
            "actual": ans,
            "match": is_same,
        })

    return {"results": results, "all_match": all_match}


def local_context(data: dict[str, list[dict[str, Any]]] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build table_context and relationships for analytics_studio.measures.evaluate_measures."""
    if data is None:
        data = generate_data()

    table_contexts = []
    for tbl_name, columns in TABLE_SPECS.items():
        headers = [col for col, _ in columns]
        normalizers = {col: model_text_normalizer() for col, kind in columns if kind == "string"}
        rows = []
        for r in data[tbl_name]:
            cells = {}
            for col, kind in columns:
                val = r[col]
                if val is None:
                    cells[col] = None
                elif kind == "boolean":
                    cells[col] = bool(val)
                else:
                    s_val = str(val)
                    if kind == "string":
                        s_val = normalizers[col](s_val)
                    cells[col] = s_val
            rows.append(cells)

        table_dict: dict[str, Any] = {
            "id": tbl_name.lower(),
            "name": tbl_name,
            "headers": headers,
            "rows": rows,
            "column_types": {col: _LOCAL_COLUMN_TYPES[kind] for col, kind in columns},
        }
        if tbl_name == "XT_Date":
            table_dict["date_column"] = "Date"
        table_contexts.append(table_dict)

    relationships = []
    card_map = {
        ("many", "one"): "many_to_one",
        ("one", "one"): "one_to_one",
        ("many", "many"): "many_to_many",
        ("one", "many"): "one_to_many",
    }
    for r_name, from_tbl, from_col, to_tbl, to_col, active, both, from_card, to_card in RELATIONSHIP_SPECS:
        card = card_map[(from_card, to_card)]
        cross = "both" if both or card == "one_to_one" else "single"
        relationships.append({
            "relationship_version": 1,
            "id": r_name,
            "from": from_col,
            "to": to_col,
            "from_table_id": from_tbl.lower(),
            "from_column": from_col,
            "to_table_id": to_tbl.lower(),
            "to_column": to_col,
            "cardinality": card,
            "is_active": active,
            "cross_filter_direction": cross,
        })

    return table_contexts, relationships


def verify_local(data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Verify local evaluation of aggregate expressions matches Python."""
    tables, rels = local_context(data)
    exp = compute_expected_aggregates(data)
    table_map = {t["id"]: t for t in tables}

    results = []
    all_match = True

    for tbl_name, columns in TABLE_SPECS.items():
        t_id = tbl_name.lower()
        t_obj = table_map[t_id]

        # 1. COUNTROWS
        try:
            val = evaluate_measures(
                [{"name": "m", "expression": f"COUNTROWS({tbl_name})", "home_table_id": t_id}],
                t_obj["rows"], t_obj["headers"], tbl_name, measure_names=["m"],
                table_context=tables, relationships=rels, active_table_id=t_id,
            )["m"]
            ans = "BLANK" if val is None else str(val)
        except Exception as e:
            ans = f"LOCAL-CRASH:{e}"

        expected = str(exp[tbl_name]["COUNTROWS"])
        is_same = dax.same(ans, expected)
        if not is_same:
            all_match = False
        results.append({"table": tbl_name, "metric": "COUNTROWS", "column": "", "expected": expected, "actual": ans, "match": is_same})

        # 2. COUNTBLANK and SUM
        for col, kind in columns:
            try:
                val = evaluate_measures(
                    [{"name": "m", "expression": f"COUNTBLANK({tbl_name}[{col}])", "home_table_id": t_id}],
                    t_obj["rows"], t_obj["headers"], tbl_name, measure_names=["m"],
                    table_context=tables, relationships=rels, active_table_id=t_id,
                )["m"]
                ans = "BLANK" if val is None else str(val)
            except Exception as e:
                ans = f"LOCAL-CRASH:{e}"

            expected = "BLANK" if exp[tbl_name]["COUNTBLANK"][col] == 0 else str(exp[tbl_name]["COUNTBLANK"][col])
            is_same = dax.same(ans, expected)
            if not is_same:
                all_match = False
            results.append({"table": tbl_name, "metric": "COUNTBLANK", "column": col, "expected": expected, "actual": ans, "match": is_same})

            if kind in ("int64", "decimal", "double"):
                try:
                    val = evaluate_measures(
                        [{"name": "m", "expression": f"SUM({tbl_name}[{col}])", "home_table_id": t_id}],
                        t_obj["rows"], t_obj["headers"], tbl_name, measure_names=["m"],
                        table_context=tables, relationships=rels, active_table_id=t_id,
                    )["m"]
                    ans = "BLANK" if val is None else str(val)
                except Exception as e:
                    ans = f"LOCAL-CRASH:{e}"

                expected = str(exp[tbl_name]["SUM"][col])
                is_same = dax.same(ans, expected)
                if not is_same:
                    all_match = False
                results.append({"table": tbl_name, "metric": "SUM", "column": col, "expected": expected, "actual": ans, "match": is_same})

    # SalesAmount SUMX with ROUND
    t_sales = table_map["xt_sales"]
    try:
        val = evaluate_measures(
            [{"name": "m", "expression": "SUMX(XT_Sales, ROUND(XT_Sales[SalesAmount], 2))", "home_table_id": "xt_sales"}],
            t_sales["rows"], t_sales["headers"], "XT_Sales", measure_names=["m"],
            table_context=tables, relationships=rels, active_table_id="xt_sales",
        )["m"]
        ans = "BLANK" if val is None else str(val)
    except Exception as e:
        ans = f"LOCAL-CRASH:{e}"

    expected = str(exp["XT_Sales"]["SUM"]["SalesAmount"])
    is_same = dax.same(ans, expected)
    if not is_same:
        all_match = False
    results.append({"table": "XT_Sales", "metric": "SUMX_ROUND", "column": "SalesAmount", "expected": expected, "actual": ans, "match": is_same})

    return {"results": results, "all_match": all_match}


def print_verification_table(title: str, verification: dict[str, Any]) -> None:
    """Print formatted markdown verification table."""
    _ensure_blocking()
    print(f"\n### {title}")
    print("| Table | Metric | Column | Expected | Actual | Match |")
    print("|---|---|---|---|---|---|")
    for r in verification["results"]:
        col = r["column"] if r["column"] else "-"
        status = "PASS" if r["match"] else "FAIL"
        print(f"| {r['table']} | {r['metric']} | {col} | {r['expected']} | {r['actual']} | {status} |")
    print(f"\nOverall: {'ALL MATCH (PASS)' if verification['all_match'] else 'MISMATCH DETECTED (FAIL)'}\n")


def main() -> None:
    data = generate_data()
    if "--verify-local" in sys.argv:
        print("Running --verify-local...")
        res = verify_local(data)
        print_verification_table("Local Verification Table", res)
        if not res["all_match"]:
            sys.exit(1)

    if "--verify-guest" in sys.argv:
        print("Running --verify-guest...")
        port_ = get_guest_port()
        try:
            install_guest_model(port_, data)
            res = verify_guest(data, port_)
            print_verification_table("Guest Verification Table", res)
            if not res["all_match"]:
                sys.exit(1)
        finally:
            drop_guest_model(port_)
            remaining = [t for t in list_guest_model_tables(port_) if t.startswith("XT_")]
            if remaining:
                print(f"WARNING: Remaining XT_ tables in guest: {remaining}")
            else:
                print("Guest clean: no XT_ tables remaining.")


if __name__ == "__main__":
    main()
