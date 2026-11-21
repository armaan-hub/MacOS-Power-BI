"""Write tools/parity/known_diffs.json: every row of the hunt batteries on which the app answers differently from Power BI.

    PYTHONPATH=. python tools/make_known_diffs.py

The list is made by replaying the hunt batteries, never typed by hand: each entry holds the lock id, Power BI's saved answer and the
app's current wrong answer.  The gate counts a listed row as known-diff while the app still gives that answer; see tools/parity_check.py.
A crash is a bug and is never listed.  Run it again only to record a change on purpose (a row fixed is removed by running it again).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import parity_check as pc  # noqa: E402


def cause_group(expr: str) -> str:
    """The shape the row belongs to, read from its text (a label for the ledger, not a rule the engine uses)."""
    if "ALLSELECTED(" in expr:
        return "ALLSELECTED inside the added column of SUMMARIZE (outer filters and the group column)"
    if "ALL(Facts[" in expr:
        return "ALL of a column inside the added column of SUMMARIZE"
    if expr.startswith("CONCATENATEX") or "CONCATENATEX(" in expr:
        return "CONCATENATEX over an inner table: row order or value"
    return "other nested table builder"


def main() -> int:
    entries = []
    for name in pc.HUNT_BATTERIES:
        battery = json.loads((pc.PARITY / f"{name}.json").read_text())
        tables = battery.get("facts_tables", {})
        for item in battery["items"]:
            table = item.get("facts")
            ours = pc.dax.local(item["expr"], tables[table] if table is not None else None)
            if pc.status(item["powerbi"], ours) != "DIFF":
                continue
            row_id = f"{name}:{table}|{item['expr']}" if table is not None else f"{name}:{item['expr']}"
            entries.append({"id": row_id, "powerbi": item["powerbi"], "app": ours, "cause_group": cause_group(item["expr"])})
    entries.sort(key=lambda entry: entry["id"])
    (pc.PARITY / "known_diffs.json").write_text(json.dumps(entries, indent=1))
    groups: dict[str, int] = {}
    for entry in entries:
        groups[entry["cause_group"]] = groups.get(entry["cause_group"], 0) + 1
    print(f"wrote {len(entries)} known diffs", groups)
    return 0


if __name__ == "__main__":
    sys.exit(main())
