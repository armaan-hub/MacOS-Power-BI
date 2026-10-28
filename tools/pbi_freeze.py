"""Save Power BI Desktop's answers for one battery so the parity gate can replay them offline.

    PYTHONPATH=. python tools/pbi_freeze.py dax_battery_stats [--no-facts]

Reads tools/<name>.json (a JSON list of DAX scalar expressions), asks the live Power BI Desktop (serialised with the same
lock as tools/pbi_probe.py) and writes tools/parity/<name>.json.  Register the name in DAX_BATTERIES of
tools/parity_check.py (the lead does this) and lock it with ``tools/parity_check.py --accept``.
"""
import fcntl
import json
import sys
from datetime import date
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.pbi_probe import LOCK

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    name = sys.argv[1]
    use_facts = "--no-facts" not in sys.argv
    expressions = json.loads((ROOT / "tools" / f"{name}.json").read_text())
    LOCK.parent.mkdir(exist_ok=True)
    with open(LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        p = dax.port()
        version = dax.guest("(Get-Item (Get-Process PBIDesktop | Select-Object -First 1).Path).VersionInfo.ProductVersion").strip().splitlines()[-1]
        if use_facts:
            dax.ensure_facts(p)
        try:
            answers = dax.power_bi(expressions, p)
        finally:
            if use_facts:
                dax.drop_facts(p)
    assert len(answers) == len(expressions), (len(answers), len(expressions))
    (ROOT / "tools" / "parity").mkdir(exist_ok=True)
    (ROOT / "tools" / "parity" / f"{name}.json").write_text(json.dumps({
        "powerbi_version": version, "frozen": date.today().isoformat(),
        "items": [{"expr": e, "powerbi": a} for e, a in zip(expressions, answers)]}, indent=1))
    print(f"froze {name}: {len(answers)} answers from Power BI {version}")


if __name__ == "__main__":
    main()
