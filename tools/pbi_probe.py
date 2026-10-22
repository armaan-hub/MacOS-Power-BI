"""Ask the live Power BI Desktop what a list of DAX scalar expressions returns (Facts scratch table available).

    PYTHONPATH=. python tools/pbi_probe.py expressions.json              # JSON list of strings; prints expression -> answer
    PYTHONPATH=. python tools/pbi_probe.py expressions.json --no-facts   # pure scalar probe, does not create the scratch table

Runs are serialised with a file lock so several agents can share the one Power BI Desktop instance.
"""
import fcntl
import json
import sys
from pathlib import Path

from tools import dax_oracle_diff as dax

LOCK = Path.home() / ".rea_scratch" / "pbi_probe.lock"


def main() -> None:
    expressions = json.load(open(sys.argv[1]))
    use_facts = "--no-facts" not in sys.argv
    LOCK.parent.mkdir(exist_ok=True)
    with open(LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        p = dax.port()
        if use_facts:
            dax.ensure_facts(p)
        try:
            answers = dax.power_bi(expressions, p)
        finally:
            if use_facts:
                dax.drop_facts(p)
    for e, a in zip(expressions, answers):
        print(f"{e}\n    -> {a}")


if __name__ == "__main__":
    main()
