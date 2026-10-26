# Task 1: scalar-gaps-1 (single-cell tables as scalars, DIVIDE text/Boolean alternate, LN(BLANK()), comment inside BLANK( ))

**Branch:** `antigravity/scalar-gaps-1`  **Written by:** Claude, 2026-10-26  **Status:** see `HANDOFF.md`

## Goal
Make the local DAX engine answer 8 distinct expressions (9 ledger entries) that Power BI already answers and the app still refuses ("Pending work" in `PARITY_LEDGER.md`).
No Power BI VM is needed: the Power BI answers are already saved in `tools/parity/*.json`.

## The 9 ledger entries (expression => Power BI answer, exact text the app must return)

| # | Expression | Power BI | Battery file |
|---|---|---|---|
| 1 | `{{1}}` | `1` | `dax_battery_round2_scope` |
| 2 | `ROW("a",1)` | `1` | `dax_battery_round2` |
| 3 | `DATATABLE("a",INTEGER,{{1}})` | `1` | `dax_battery_round2` |
| 4 | `COUNTROWS({{1,2},{3,4}})` | `2` | `dax_battery_round2_scope` and `dax_battery_round2` (same expression, two entries) |
| 5 | `DIVIDE(1,0,"x")` | `x` | `dax_battery_round2` |
| 6 | `DIVIDE(1,0,TRUE())` | `True` | `dax_battery_round2` |
| 7 | `LN(BLANK())` | `-Infinity` | `dax_battery_round2` |
| 8 | `BLANK( //c` newline `)` (BLANK, a line comment, newline, then `)`) | `BLANK` | `dax_battery_round2` |

(Item 4 is in two batteries, hence 9 entries.) Read the exact strings from the JSON files, do not retype them.

## Rules (what Power BI does)
- A table with exactly one row and one column used where a single value is expected is that value: `ROW("a",1)`, a one-cell `DATATABLE`, and `{{1}}` are `1`. Today `{1}` already works (`measures.py` around line 11780); `{{1}}` and the other two do not.
- `{{1,2},{3,4}}` is a 2-row, 2-column table, so `COUNTROWS` of it is `2`. It is still NOT a scalar (keep refusing it where a single value is needed).
- `DIVIDE(a, b, alt)` returns `alt` when `b` is 0 or BLANK. A text or Boolean `alt` makes the result text or Boolean (`x`, `True`). Today only a numeric constant or BLANK() is accepted (`measures.py` around line 2283).
- `LN(BLANK())` is `-Infinity` (an error value in the app: see the existing `error.infinity` handling near `measures.py` line 1900). Make the top-level result text `-Infinity`, the way other Infinity results are already reported by `dax_oracle_diff.local`.
- A `//` or `--` comment between `BLANK(` and `)` does not change the meaning of `BLANK()`.

## Where to look (do not trust line numbers, search for the message text)
- `analytics_studio/measures.py`: messages "A table constructor with more than one value...", "...returns a table; use it inside COUNTROWS...", "DIVIDE alternate result must be a constant...", "LN needs a number greater than zero.", "BLANK() is supported only in explicitly allowed argument positions."
- `tools/dax_oracle_diff.py` function `local()` shows how a value becomes the text the gate compares.
- Existing tests to imitate (read, do not edit): `tests/test_iteration88_text_and_comments.py` (list of `(expression, Power BI answer)` pairs checked with `tools.parity_check.status`).

## Must NOT change
- Anything else that is refused today must stay refused unless this table says otherwise. Examples that must remain refused: `DIVIDE(1,0,"x")` is allowed, but do not guess other shapes (`DIVIDE(1,1,"x")`, a text alternate with a non-zero denominator, a column as alternate). Power BI answers for those are not saved. If you need one, write it under "Open questions" in `HANDOFF.md` and refuse it.
- `ROW`/`DATATABLE` with more than one cell, used as a single value, must stay refused.
- The 14 "Known deviations" in `PARITY_LEDGER.md`, the saved Power BI answers, `PARITY_LEDGER.md`, `tools/parity_check.py`, existing tests: untouched (see `AGENTS.md`).
- Excluded on purpose: `TOCSV` and `TOJSON` items. The saved answers only kept their first output line; Claude will re-ask Power BI first (needs the VM). Do not implement them in this task.

## Acceptance checks
1. New test file `tests/test_iteration89_scalar_gaps_1.py` (new file, allowed): the 8 expressions with their Power BI answers, each asserting `status(power_bi, dax.local(expr)) == "match"`, plus negative tests that these stay refused: `ROW("a",1,"b",2)` and `{{1,2},{3,4}}+1` used as single values (check they are refused today before relying on them; if one is not, tell me in `HANDOFF.md`). `DIVIDE(1,1,"x")` is undecided: do not add a test for it, just do not widen beyond the table. Write the failing test first, see it fail, then fix.
2. `PYTHONPATH=. python tools/parity_check.py` (offline replay): "Pending work" drops from 70 to 61; DIFF 0; CRASH 0; every previously locked item still matches (45,426).
3. `PYTHONPATH=. python tools/parity_check.py --tests` ends with PARITY GATE PASSED (previous: pytest 1,917 passed, real app 575/575). Paste the real summary lines in your `HANDOFF.md` entry. Run it under `caffeinate -i`.
4. Do not run `--freeze` or `--accept`. The 9 items will show "match (not yet locked)"; Claude locks them after review.

## Hand-over
Set the task status `READY FOR REVIEW`, add an entry to `HANDOFF.md` (template inside), list every file changed. Claude then reviews, runs the gate, and asks the user before locking.
