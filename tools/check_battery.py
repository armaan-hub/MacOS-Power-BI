"""Replay one saved Power BI battery against the app: PYTHONPATH=. python tools/check_battery.py dax_battery_stats [all]

Prints every item that is not a match (or every item with ``all``) and the totals.  Status meaning: match, gap-reject
(Power BI answers, the app refuses), DIFF (different answer), CRASH (the evaluator raised an unexpected exception).
"""
import json
import sys
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    items = json.loads((ROOT / "tools" / "parity" / f"{sys.argv[1]}.json").read_text())["items"]
    counts: dict[str, int] = {}
    for item in items:
        ours = dax.local(item["expr"])
        state = status(item["powerbi"], ours)
        counts[state] = counts.get(state, 0) + 1
        if state != "match" or "all" in sys.argv[2:]:
            print(f"{state:10} {item['expr']}\n           PBI={item['powerbi'][:110]}\n           APP={ours[:110]}")
    print(counts)
    return 1 if counts.get("DIFF") or counts.get("CRASH") or counts.get("gap-reject") else 0


if __name__ == "__main__":
    sys.exit(main())
