# Task 131 (Iteration 220): DAX refusal backlog, part 19 — float noise of PRODUCTX over Currency and STDEVX/VARX over a repeated date (dax-floatnoise-121)

Coder: Antigravity, worktree `/Users/armaan/Power BI tool-task131`, branch `antigravity/dax-floatnoise-121`
(branched from main 9abe139; Task 130 is still on its own branch, do not touch its date code).

237 saved Power BI answers are refused today, in two families. Both look like EXACT, reproducible floating-point
arithmetic, not randomness, so they can be modelled if the exact operation order is found.

**Part A: PRODUCTX over a Currency inside IF / IF.EAGER / IFERROR / VAR (61 refused).**
Refused with "PRODUCTX over a Currency in a conditional is not modelled". Examples:
- `PRODUCTX(Facts,IF(1,CURRENCY(-2)))` → 63.9999999999994 (not 64)
- `PRODUCTX(Facts,IF(1=1,CURRENCY(3),Facts[Region]))` → 728.999999999995 (not 729)
- `PRODUCTX(ADDCOLUMNS(Facts,"z",1),IF(TRUE(),CURRENCY(2.75),1))` → 432.510009765625
- `PRODUCTX(Facts,VAR x=CURRENCY(3) RETURN IF(Facts[Quantity],x,Facts[Quantity]>2)) ` → 243
Hypothesis: when the iterated value is a Variant holding a Currency, Power BI multiplies through
`exp(sum(ln|x|))` in double with a separate sign (and BLANK / zero handling), while a plain typed path multiplies
directly. Find which shapes take which path and the exact formula (summation order, sign, zero, BLANK rows);
reproduce Power BI's printed digits exactly (15 significant digits).

**Part B: STDEVX / VARX (.S and .P) over one repeated inexact date or time value (176 refused).**
Refused with "... over one repeated inexact date value has a float-noise spread". Examples:
- `STDEVX.S(FILTER(Facts,Facts[Sales]>0),DATE(1900,3,1)+1/2.5)` → 9.5367431640625E-07 (= 2^-20)
- `STDEVX.P({3,9,10},DATE(1900,3,1)+1/2.5)+1` → 1.00000067434958
- `CALCULATE(VARX.P({4,5,2},DATE(1899,12,31)+1/5),Facts[Region]<>"West")` → 2.22044604925031E-16
- `STDEVX.S({2,1,12,2},DATE(1900,3,1)+1/6)` → 0
Hypothesis: the same value repeated n times gives a non-zero spread because of how the engine accumulates
(e.g. sum of x and sum of x² in double, then n*Σx² − (Σx)², or a datetime stored at reduced precision). Find the
exact accumulation that gives Power BI's digits on EVERY spec item, including the zeros.

**Add-on (old wrong answer on main, found by a fresh probe):** `VARX.P(ADDCOLUMNS(Facts,"z",1),DATE(1999,12,31)+0.3)+1`:
Power BI 1.00000047683716, we answer 1. Fix it with the Part B rule, or refuse it. More old wrong answers of the same shape (STDEVX/VARX over
`ADDCOLUMNS(Facts,...)`) are in `docs/plans/2026-11-11-dax-floatnoise-121-addon.json`; all must end right or refused.

**Spec:** `docs/plans/2026-11-11-dax-floatnoise-121-spec.json` (177 items). Today: 0 exact, 177 refused. Opus holds out 60
more and will check ~1,000 fresh Power BI probes you have not seen (other values, row counts, tables).

LESSON FROM TASKS 119-130: first versions fitted the spec 100% but got fresh probes wrong. Answer only where the rule
holds on every spec item; refuse neighbouring shapes. Prefer refusing. Never change an answer that is not in these
two families (PRODUCTX over plain numbers, STDEVX over distinct values must stay exactly as they are).

## Rules (binding, see AGENTS.md)
- Compute, never look up: app code must never read `tools/parity/*.json`, the spec, plans, tests or scratch files;
  no tables keyed by expression text.
- An answer you cannot derive exactly stays refused. A locked answer must never change.
- Do not run Power BI or any Power BI tool (pbi_probe, pbi_freeze, pbi_model, dax_oracle_diff main, --freeze / --accept);
  no merge or push. If you need a Power BI answer, write the expression in HANDOFF and Opus will probe it.
- Check with `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/parity_check.py` (DIFF 0, CRASH 0), then
  `git checkout -- PARITY_LEDGER.md`; run the relevant pytest files with `-p no:cacheprovider` (never `-n`).
  Score the spec with `tools/dax_oracle_diff.local`.
- Commit on the branch. Report at the end of `HANDOFF.md` under "Antigravity (Task 131) ready for review": exact /
  refused / wrong on the spec (wrong must be 0), the rules, files changed. Then stop.

## Review outcome (2026-11-11)
Shipped as Iteration 220. Locked 536645.
