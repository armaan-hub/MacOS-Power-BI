"""Compare the local evaluator with saved probe answers: replay_probe.py battery.json probe_output.txt [statuses]"""
import json, sys
from tools import dax_oracle_diff as dax
from tools.parity_check import status
ex = json.load(open(sys.argv[1]))
lines = open(sys.argv[2]).read().splitlines()
answers = {lines[i]: lines[i + 1][len("    -> "):] for i in range(0, len(lines) - 1, 2) if lines[i + 1].startswith("    -> ")}
counts = {}
for e in ex:
    a = answers[e]
    ours = dax.local(e)
    st = status(a, ours)
    counts[st] = counts.get(st, 0) + 1
    if st != "match" and (len(sys.argv) < 4 or st in sys.argv[3].split(",")):
        print(f"{st:10} {e}\n           PBI={a[:100]}\n           LOC={ours[:100]}")
print(counts)
