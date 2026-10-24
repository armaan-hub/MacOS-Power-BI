"""Regenerate the function counts and the recognized-names table of DAX_COMPATIBILITY_CONTRACT.md.

    PYTHONPATH=. python tools/sync_dax_contract.py           # rewrite the generated parts
    PYTHONPATH=. python tools/sync_dax_contract.py --check   # exit 1 when the document is stale

The numbers and the table come from the evaluator itself (``analytics_studio.measures``), never
from hand-typed text.  Generated parts are fenced by markers in the document:

* ``<!--gen:functions-->328<!--/gen-->`` - the number of names in ``_FUNCTIONS``
* ``<!--gen:special-->..<!--/gen-->`` - the number of names incl. the parser's special forms
* a ``<!-- BEGIN GENERATED: dax-functions -->`` ... ``<!-- END GENERATED: dax-functions -->`` block
  holding the family table.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analytics_studio import dax_math, dax_time_sets, measures  # noqa: E402

CONTRACT = ROOT / "DAX_COMPATIBILITY_CONTRACT.md"
BEGIN = "<!-- BEGIN GENERATED: dax-functions -->"
END = "<!-- END GENERATED: dax-functions -->"


def families() -> list[tuple[str, list[str]]]:
    """Recognized names grouped by the registry that defines them in the evaluator."""
    everything = set(measures._FUNCTIONS)
    registries: list[tuple[str, set[str]]] = [
        ("Date sets, balances and period functions (`dax_time_sets`)",
         set(dax_time_sets.SET_FUNCTIONS) | set(dax_time_sets.BALANCES)),
        ("Statistics (`dax_math` column, percentile and iterator forms)",
         set(dax_math.STAT_COLUMN_FUNCTIONS) | set(dax_math.STAT_PERCENTILE_COLUMN)
         | set(dax_math.STAT_ITERATORS)),
        ("Text, date/time, information, conversion, math and financial scalars (`_TYPED_ARITY`)",
         set(measures._TYPED_ARITY)),
        ("Lookup, membership, filter-state and table constructors (`_LOOKUP_ARITY`, `SELECTEDVALUE`, `HASONEVALUE`, `CONCATENATEX`)",
         set(measures._LOOKUP_ARITY) | set(measures._COLUMN_SCALAR_ARITY) | {"CONCATENATEX"}),
        ("Table-valued functions and window helpers (`_TABLE_FUNCTION_ARITY`, `IGNORE`, `NONVISUAL`, `CURRENTGROUP`, `ORDERBY`, `PARTITIONBY`, `MATCHBY`, `RELATEDTABLE`)",
         set(measures._TABLE_FUNCTION_ARITY) | {"IGNORE", "NONVISUAL", "CURRENTGROUP", "ORDERBY",
                                                 "PARTITIONBY", "MATCHBY", "RELATEDTABLE"}),
        ("Rank and outer-row functions (`_RANK_ARITY`)", set(measures._RANK_ARITY)),
    ]
    result: list[tuple[str, list[str]]] = []
    taken: set[str] = set()
    for title, names in registries:
        own = sorted((names & everything) - taken)
        taken |= set(own)
        result.append((title, own))
    core = sorted(everything - taken)
    result.insert(0, ("Core: aggregation, iterators, scalar logic, filter context, relationships and the first time-intelligence set", core))
    return [item for item in result if item[1]]


def generated_block() -> str:
    lines = [BEGIN, "", "| Family | Recognized names | Count | Status |", "|---|---|---|---|"]
    for title, names in families():
        lines.append(f"| {title} | " + ", ".join(f"`{name}`" for name in names) + f" | {len(names)} | Partial |")
    special = sorted(set(measures.DAX_FUNCTION_NAMES) - set(measures._FUNCTIONS))
    lines.append(
        "| Parser special forms (not in `_FUNCTIONS`) | "
        + ", ".join(f"`{name}`" for name in special) + f" | {len(special)} | Partial |"
    )
    lines += ["", END]
    return "\n".join(lines)


def render(text: str) -> str:
    total = len(measures._FUNCTIONS)
    with_special = len(measures.DAX_FUNCTION_NAMES)
    text = re.sub(r"<!--gen:functions-->.*?<!--/gen-->", f"<!--gen:functions-->{total}<!--/gen-->", text)
    text = re.sub(r"<!--gen:special-->.*?<!--/gen-->", f"<!--gen:special-->{with_special}<!--/gen-->", text)
    start, finish = text.index(BEGIN), text.index(END) + len(END)
    return text[:start] + generated_block() + text[finish:]


def main(argv: list[str]) -> int:
    current = CONTRACT.read_text(encoding="utf-8")
    updated = render(current)
    if "--check" in argv:
        if updated != current:
            print("DAX_COMPATIBILITY_CONTRACT.md is stale: run PYTHONPATH=. python tools/sync_dax_contract.py")
            return 1
        print("DAX_COMPATIBILITY_CONTRACT.md is up to date")
        return 0
    CONTRACT.write_text(updated, encoding="utf-8")
    print(f"updated: {len(measures._FUNCTIONS)} names in _FUNCTIONS, {len(measures.DAX_FUNCTION_NAMES)} with special forms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
