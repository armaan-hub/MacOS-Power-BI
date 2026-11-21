"""Speed check for the local DAX engine: how long each named formula takes and how much memory it costs.

    PYTHONPATH=. python3 tools/perf_check.py                             # 100,000 and 1,000,000 rows
    PYTHONPATH=. python3 tools/perf_check.py --sizes 100000 --timeout 300
    PYTHONPATH=. python3 tools/perf_check.py --only QUADRATIC --json out.json

A seeded Facts table (seed 1: Sales decimal, Quantity whole number, Region of four text values, Note text with blanks)
is built at each size and every formula runs alone in a spawned child process, so a formula that hangs costs only its
own row: the child is killed after --timeout seconds and the row is reported as "timeout".  "seconds" is the wall time
the evaluation itself took inside the child (building the table is not counted, so the numbers line up with a plain
timing loop); for a timeout it is the wall time the child was given.  "peak MB" is the peak resident set size the operating system reports for the evaluation process
(bytes on macOS, KiB on Linux).
Status is ok, refused (the engine declined the expression), crash (it raised something else), timeout, or
"skipped (over --max-rows)" for a size bigger than the memory budget.  Exit code is always 0: this measures the
engine, it does not judge it.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import random
import resource
import sys
import time
from pathlib import Path

from analytics_studio.measures import MeasureError, evaluate_measures

HEADERS = ["Sales", "Quantity", "Region", "Note"]
TYPES = {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"}
REGIONS = ["East", "West", "North", "South"]
NOTES = ["Paid", "Late", None]

# name -> expression.  The five report-shaped formulas first, then the one whose cost grows with the square of the
# row count, then one each for row aggregation, distinct counting, clearing a filter and ranking.
FORMULAS = {
    "SUM": "SUM(Facts[Sales])",
    "SUMX": "SUMX(Facts, Facts[Sales]*Facts[Quantity])",
    "CALCULATE_FILTER": 'CALCULATE(SUM(Facts[Sales]), Facts[Region]="East")',
    "SUMX_VALUES": "SUMX(VALUES(Facts[Region]), CALCULATE(SUM(Facts[Sales])))",
    "SUMMARIZE": "COUNTROWS(SUMMARIZE(Facts, Facts[Region], Facts[Quantity]))",
    "QUADRATIC": "SUMX(Facts, CALCULATE(SUM(Facts[Sales])))",
    "AVERAGEX": "AVERAGEX(Facts, Facts[Sales])",
    "DISTINCTCOUNT": "DISTINCTCOUNT(Facts[Region])",
    "CALCULATE_ALL": "CALCULATE(SUM(Facts[Sales]), ALL(Facts[Region]))",
    "RANKX": "RANKX(VALUES(Facts[Region]), CALCULATE(SUM(Facts[Sales])))",
}

DEFAULT_SIZES = [100_000, 1_000_000]
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_ROWS = 2_000_000
# Sizes above the default budget are still accepted; they print "skipped (over --max-rows)" unless --max-rows is raised.
BIG_SIZES = [10_000_000, 100_000_000, 1_000_000_000]
# Test hook: a child that sleeps this many seconds before evaluating, so the timeout path can be exercised quickly.
SLEEP_ENV = "PERF_CHECK_SLEEP_SECONDS"
ALLOC_ENV = "PERF_CHECK_ALLOC_MB"

COLUMNS = [("size", "size"), ("name", "name"), ("seconds", "seconds"), ("peak_mb", "peak MB"),
           ("status", "status"), ("value", "value")]
RIGHT_ALIGNED = {"size", "seconds", "peak_mb"}


def build_rows(row_count: int) -> list[dict]:
    """The seeded Facts table: same seed and same generator calls at every size, so sizes stay comparable."""
    rng = random.Random(1)
    return [
        {
            "Sales": round(rng.random() * 100, 2),
            "Quantity": rng.randint(0, 50),
            "Region": rng.choice(REGIONS),
            "Note": rng.choice(NOTES),
        }
        for _ in range(row_count)
    ]


def peak_mb(raw_rss: int | None = None) -> float:
    """Peak resident set size in MB: macOS reports bytes, Linux KiB."""
    raw = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss if raw_rss is None else raw_rss
    return round(raw / 1024 if sys.platform.startswith("linux") else raw / (1024 * 1024), 1)


def _child_run(payload: tuple[int, str, str], reply) -> None:
    """Build the table, evaluate one formula once, and send back the timing and the answer."""
    row_count, _name, expression = payload
    sleep_seconds = float(os.environ.get(SLEEP_ENV, "0") or 0)
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    alloc_mb = float(os.environ.get(ALLOC_ENV, "0") or 0)
    _holder = bytearray(int(alloc_mb * 1024 * 1024)) if alloc_mb > 0 else None
    rows = build_rows(row_count)
    context = [{"id": "facts", "name": "Facts", "headers": HEADERS, "rows": rows, "column_types": TYPES}]
    status, value = "ok", ""
    started = time.perf_counter()
    try:
        answer = evaluate_measures(
            [{"name": "P", "expression": expression}], rows, HEADERS, "Facts",
            measure_names=["P"], table_context=context, active_table_id="facts",
        )["P"]
        value = "" if answer is None else str(answer)
    except MeasureError as error:
        status, value = "refused", str(error)
    except Exception as error:  # a crash is a finding, not a failure of this tool
        status, value = "crash", repr(error)
    seconds = round(time.perf_counter() - started, 3)
    raw_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    reply.send({"seconds": seconds, "status": status, "value": value[:40], "raw_rss": raw_rss})
    reply.close()


def run_one(row_count: int, name: str, expression: str, timeout: float) -> dict:
    """Run one formula in a spawned child process and report its timing, memory and status."""
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_child_run, args=((row_count, name, expression), writer))
    row = {"size": row_count, "name": name, "seconds": "", "peak_mb": "", "status": "ok", "value": ""}
    started = time.perf_counter()
    process.start()
    writer.close()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join(10)
        row["seconds"] = round(time.perf_counter() - started, 3)
        row["status"] = "timeout"
    elif reader.poll(1):
        result = reader.recv()
        peak = peak_mb(result.get("raw_rss")) if result.get("raw_rss") is not None else ""
        row.update(seconds=result["seconds"], status=result["status"], value=result["value"][:40], peak_mb=peak)
    else:
        row["status"] = "crash"
        row["value"] = f"child exited {process.exitcode} without a result"[:40]
    reader.close()
    return row


def _cell(row: dict, key: str) -> str:
    value = row.get(key, "")
    if key == "seconds" and isinstance(value, float):
        return f"{value:.3f}"
    if key == "peak_mb" and isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def render(rows: list[dict]) -> str:
    """The one table: one line per row, numeric columns right-aligned."""
    header = [label for _key, label in COLUMNS]
    cells = [[_cell(row, key) for key, _key in COLUMNS] for row in rows]
    widths = [max([len(label)] + [len(line[i]) for line in cells]) for i, label in enumerate(header)]

    def line(values: list[str]) -> str:
        out = []
        for i, value in enumerate(values):
            out.append(value.rjust(widths[i]) if COLUMNS[i][0] in RIGHT_ALIGNED else value.ljust(widths[i]))
        return "  ".join(out).rstrip()

    return "\n".join([line(header)] + [line(values) for values in cells])


def main(argv: list[str] | None = None) -> list[dict]:
    """Parse the command line, time every requested (size, formula) pair, print the table, return the rows."""
    parser = argparse.ArgumentParser(description="Time the local DAX engine on a seeded Facts table.")
    parser.add_argument("--sizes", default=",".join(str(size) for size in DEFAULT_SIZES),
                        help=f"comma separated row counts (default {DEFAULT_SIZES[0]},{DEFAULT_SIZES[1]}; "
                             f"{','.join(str(size) for size in BIG_SIZES)} are accepted too and are skipped "
                             f"unless --max-rows is raised)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds each child process gets")
    parser.add_argument("--only", default=None, metavar="NAME", help="run just this named formula")
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS,
                        help="sizes above this print skipped (over --max-rows)")
    parser.add_argument("--json", dest="json_out", default=None, metavar="OUT", help="also write the rows as JSON")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return []  # usage and --help print themselves; this tool always exits 0

    try:
        sizes = [int(piece.strip()) for piece in str(args.sizes).split(",") if piece.strip()]
    except ValueError:
        print(f"--sizes must be comma separated whole numbers, got {args.sizes!r}", file=sys.stderr)
        return []
    if any(size <= 0 for size in sizes):
        print(f"--sizes must be positive row counts, got {args.sizes!r}", file=sys.stderr)
        return []
    names = [args.only] if args.only else list(FORMULAS)
    unknown = [name for name in names if name not in FORMULAS]
    if unknown:
        print(f"unknown formula name {unknown[0]!r}; known: {', '.join(FORMULAS)}", file=sys.stderr)
        return []

    rows: list[dict] = []
    for size in sizes:
        if size > args.max_rows:
            rows.append({"size": size, "name": "-", "seconds": "", "peak_mb": "",
                         "status": "skipped (over --max-rows)", "value": ""})
            continue
        for name in names:
            row = run_one(size, name, FORMULAS[name], args.timeout)
            rows.append(row)
            print(f"{size} {name} {row['status']} {row['seconds']}s", file=sys.stderr, flush=True)
    print(render(rows))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return rows


if __name__ == "__main__":
    main(sys.argv[1:])
