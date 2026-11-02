"""Score a measured Power BI spec file against the current engine.

    PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/score_spec.py tools/parity/task23_big_numbers_spec.json [PART]

Prints match / gap-reject (refused) / DIFF counts per Part and lists the wrong items of the selected Part.
"""
import collections
import json
import sys

from tools import dax_oracle_diff as dax
from tools.parity_check import status


def main() -> None:
    items = json.load(open(sys.argv[1]))["items"]
    part = sys.argv[2] if len(sys.argv) > 2 else None
    counts = collections.Counter()
    wrong = []
    for item in items:
        if part and item["part"] != part:
            continue
        ours = dax.local(item["expr"])
        state = status(item["powerbi"], ours)
        counts[(item["part"], state)] += 1
        if state not in ("match", "gap-reject"):
            wrong.append((item["part"], item["expr"], item["powerbi"][:80], str(ours)[:80]))
    for key in sorted(counts):
        print(key, counts[key])
    for row in wrong[:200]:
        print("WRONG", *row, sep=" | ")
    print(f"{len(wrong)} wrong")


if __name__ == "__main__":
    main()
