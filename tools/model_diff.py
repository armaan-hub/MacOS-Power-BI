"""Compare live Power BI Desktop with the local evaluator on the Critic-3 models (ZO, ZB, ZS, ZM) for a list of DAX expressions.

    PYTHONPATH=. python tools/model_diff.py corpus.json report.json [--install ZO ZB ZS ZM]

corpus.json: a list of {"model": "ZO", "expr": "..."} (or plain strings plus --model ZO).
report.json: one record per expression {model, expr, powerbi, ours, status}; the summary counts print at the end.
status: match / gap-reject (we refuse, Power BI answers) / DIFF (both answer, differently) / CRASH.

Models must be installed in the live Power BI model first (tools/pbi_model.py install ...).  Power BI asks are serialised by a file lock
so several agents can share the one Power BI Desktop.  Read-only on the model; never saves the Power BI project.
"""
from __future__ import annotations

import fcntl
import json
import sys
from collections import Counter

from tests.critic3_models import ours_for
from tools import dax_oracle_diff as dax
from tools import pbi_model
from tools.parity_check import status
from tools.pbi_probe import LOCK


def main() -> None:
    args = sys.argv[1:]
    install = []
    if "--install" in args:
        i = args.index("--install")
        install, args = args[i + 1:], args[:i]
    default_model = None
    if "--model" in args:
        i = args.index("--model")
        default_model = args[i + 1]
        del args[i:i + 2]
    corpus_path, report_path = args
    items = [{"model": default_model, "expr": x} if isinstance(x, str) else x for x in json.load(open(corpus_path))]
    LOCK.parent.mkdir(exist_ok=True)
    with open(LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        p = dax.port()
        if install:
            pbi_model.install(p, install)
        answers = dax.power_bi([i["expr"] for i in items], p)
    report = []
    for item, theirs in zip(items, answers):
        ours = ours_for(item["model"], item["expr"])
        report.append({"model": item["model"], "expr": item["expr"], "powerbi": theirs, "ours": ours, "status": status(theirs, ours)})
    json.dump(report, open(report_path, "w"), indent=1)
    by_model = {}
    for r in report:
        by_model.setdefault(r["model"], Counter())[r["status"]] += 1
    for model, counts in by_model.items():
        print(model, dict(counts))
    print("total", dict(Counter(r["status"] for r in report)))


if __name__ == "__main__":
    main()
