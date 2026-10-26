# Task 2: var-scoping-1 (nested VAR blocks, table VAR, VAR in a CALCULATE filter, bare CR ends a line comment)

**Branch:** `antigravity/var-scoping-1`  **Written by:** Claude, 2026-10-26  **Status:** see `HANDOFF.md`
**Start condition:** Task 1 (`scalar-gaps-1`) must be merged to `main` and committed first. Branch from that `main`. Do not start before `HANDOFF.md` says Active agent: Antigravity.

## Goal
Make the local DAX engine answer 7 pending ledger entries (6 distinct expressions' worth of behaviour) that Power BI already answers and the app still refuses.
No Power BI VM is needed: every answer is already saved in `tools/parity/*.json`. Do not read the VM, do not run `--freeze`.

## The 7 ledger entries (expression => Power BI answer)
Read the exact strings from the JSON files (`tools/parity/dax_battery_round2.json`, `tools/parity/dax_battery_round3.json`, key `items`, fields `expr` and `powerbi`). Do not retype them. Line breaks and carriage returns inside the expressions matter.

| # | Expression (shown with escapes) | Power BI | Battery |
|---|---|---|---|
| 1 | `VAR x=1 RETURN VAR x=2 RETURN x` | `2` | round2 |
| 2 | `VAR x=1 RETURN x+VAR y=2 RETURN y` | `3` | round2 |
| 3 | `VAR t=Facts RETURN COUNTROWS(t)` | `6` | round2 |
| 4 | `VAR a = 1 // x\rRETURN a` (a bare carriage return, no line feed, after the comment) | `1` | round3 |
| 5 | `VAR a = 1 -- x\rRETURN a` (same, with `--`) | `1` | round3 |
| 6 | `CALCULATE(COUNTROWS(Facts),VAR t = Facts[Quantity] RETURN t>2)` | `3` | round3 |
| 7 | `CALCULATE(COUNTROWS(Facts),VAR t = 2 RETURN Facts[Quantity]>t)` | `3` | round3 |

Today the app says: #1 "Variable 'x' cannot be created because a variable with the same name already exists."; #2 "Function VAR is not supported"; #3 "Function FACTS is not supported"; #4 and #5 "A VAR block needs a RETURN expression."; #6 and #7 "CALCULATE filters must be column comparisons joined with AND, OR, or NOT." (search `analytics_studio/measures.py` for those message texts; do not trust line numbers).

## Rules (what Power BI does, from the saved answers)
1. **Nested VAR shadows.** A `VAR` block that starts after a `RETURN` may reuse an outer variable name (`VAR x=1 RETURN VAR x=2 RETURN x` is `2`). The inner `x` is visible only in that inner block. **But two VARs with the same name in the SAME block stay an error** (`VAR x=1 VAR x=2 RETURN x`: Power BI errors, the app must keep refusing; this is already locked).
2. **A VAR block is an expression.** After an operator it can be the right operand: `x+VAR y=2 RETURN y` is `3`. Treat it like a parenthesised `(VAR ... RETURN ...)`, which the app already supports (`VAR x=1 RETURN (VAR y=x+1 RETURN y*2)` is `4`).
3. **Table VAR from a bare table name.** `VAR t=Facts RETURN COUNTROWS(t)` is `6`. Power BI accepts a variable holding a model table when a table function consumes it. Power BI REFUSES these (saved errors, already locked, must stay refused): `VAR t=Facts RETURN t`, `VAR t=Facts RETURN IF(FALSE(),t,1)`, `VAR t=Facts RETURN IF(FALSE(),t+1,1)`. So accept it ONLY where `t` is the argument of `COUNTROWS`. Any other use of such a variable stays refused (no Power BI answer is saved: `SUMX(t,...)`, `FILTER(t,...)`, `VALUES(t)`, `t` in a comparison and so on).
4. **VAR inside a CALCULATE True/False filter.** The variable may hold a plain column reference (`Facts[Quantity]`) or a constant (`2`); the RETURN is then the row-by-row condition (#6, #7). Power BI REFUSES a filter whose VAR holds an aggregate or CALCULATE (`SUM(...)`, `Facts[Quantity]+SUM(...)`, `CALCULATE(...)`: 4 saved errors, already locked). Those must stay refused. A VAR defined as anything other than a bare column reference or a numeric constant stays refused (no answer saved: do not guess).
5. **Line comments end at CR, LF or CRLF.** `// x\rRETURN a` and `-- x\rRETURN a` are `1`. `\n` and `\r\n` already work. Find the comment tokenizer (search `startswith(("//", "--")`) and end the comment at a bare `\r` as well. The same must hold for every place comments are skipped.

## Must NOT change (do not guess, refuse instead)
- Everything refused today that is not in the table above stays refused. In particular the Power BI errors listed in rules 1, 3 and 4, and every shape for which no answer is saved.
- A comment that is not closed by CR or LF (end of text) keeps the behaviour it has today.
- The 14 "Known deviations" in `PARITY_LEDGER.md`, saved Power BI answers, `PARITY_LEDGER.md`, `tools/parity_check.py`, existing tests: untouched (see `AGENTS.md`).
- Do not touch `TOCSV`/`TOJSON` (waiting for a Power BI re-ask).
- If you need a shape that is not in the table, write it under "Open questions" in `HANDOFF.md` and refuse it.

## Acceptance checks
1. New test file `tests/test_iteration90_var_scoping_1.py` (new file, allowed). Write the failing test first, see it fail, then fix.
   - The 7 expressions with their Power BI answers, each asserting `status(power_bi, dax.local(expr)) == "match"` (copy the style of `tests/test_iteration89_scalar_gaps_1.py`; it exists on `main` once Task 1 is merged).
   - A "stays refused" test (`dax.local(expr)` starts with `LOCAL-REJECT`) for at least: `VAR x=1 VAR x=2 RETURN x`; `VAR t=Facts RETURN t`; `VAR t=Facts RETURN IF(FALSE(),t,1)`; `VAR t=Facts RETURN SUMX(t,1)`; `VAR t=Facts RETURN COUNTROWS(FILTER(t,TRUE()))`; `CALCULATE(COUNTROWS(Facts),VAR t = SUM(Facts[Quantity]) RETURN Facts[Quantity]+t>16)`; `CALCULATE(COUNTROWS(Facts),VAR t = CALCULATE(SUM(Facts[Quantity])) RETURN Facts[Quantity]+t>16)`; `CALCULATE(COUNTROWS(Facts),VAR t = Facts[Quantity]+1 RETURN t>2)`. First check each is refused today before relying on it; if one is not, say so in `HANDOFF.md`.
2. `PYTHONPATH=. python tools/parity_check.py` (offline replay): "Pending work" drops by 7 (from 61 to 54 once Task 1 is locked); DIFF 0; CRASH 0; every previously locked item still matches (the locked count from the `main` ledger).
3. `PYTHONPATH=. caffeinate -i python tools/parity_check.py --tests` ends with PARITY GATE PASSED and 0 pytest failures. Run it under `caffeinate -i`, check it finished with `pgrep` before you quote it, and paste the real summary lines (pytest, real app, replay) into your `HANDOFF.md` entry.
4. Do not run `--freeze` or `--accept`. The 7 items will show "match (not yet locked)"; Claude locks them after review.
5. Expected new probe results to put in your entry: the table of the 7 expressions with the app's answer.

## Hand-over
Set the task status `READY FOR REVIEW`, add an entry to `HANDOFF.md` (template inside), list every file changed, and say whether anything was not done.
