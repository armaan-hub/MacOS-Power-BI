# Error report for Antigravity: Task 1 `scalar-gaps-1` sent back

Written by Claude, 2026-10-26. Branch: `antigravity/scalar-gaps-1`. Plan: `docs/plans/2026-10-26-scalar-gaps-1.md`.
Read `GEMINI.md`, `AGENTS.md`, `HANDOFF.md` and the plan first. Before you start, set **Active agent: Antigravity** in `HANDOFF.md`.

## Verdict
The 8 planned expressions work. Your 2 new tests pass. Your replay result is right (pending 70 -> 61, 0 DIFF, 0 CRASH).
**The task is not accepted yet.** Your change also makes about 10 other expressions answer that must stay refused, and one existing test fails because of it.

## What went wrong
The plan said (section "Must NOT change"): everything else that is refused today stays refused, and do not guess. Power BI has no saved answer for the expressions below, so we do not know what Power BI returns. An app that answers differently from Power BI is worse than an app that refuses.

I ran each expression on a clean copy of `HEAD` and on your branch with `dax.local(expr)`:

| Expression | `HEAD` | Your branch | Required |
|---|---|---|---|
| `BLANK()` (plain, top level) | refused | `BLANK` | refused |
| `ROW("a",1)+1` | refused | `2` | refused |
| `ROW("a","x")` | refused | `x` | refused |
| `ROW("a",TRUE())` | refused | `True` | refused |
| `ROW("a",BLANK())` | refused | `BLANK` | refused |
| `ROW("a",1)*ROW("b",3)` | refused | `3` | refused |
| `ROW("a",1)=1` | refused | `True` | refused |
| `ROW("a",1)=ROW("b",1)` | refused | `True` | refused |
| `DIVIDE(1,0,FALSE())` | refused | `False` | refused |
| `DIVIDE(1,0,"")` | refused | empty answer | refused |

Still correct, do not change: `DIVIDE(1,2,"x")` refused, `DIVIDE(1,0,DATE(2020,1,1))` refused, `ROW("a",1,"b",2)` refused, `{{1,2},{3,4}}+1` refused, `{}` refused, `LOG10(BLANK())`, `LOG(BLANK())`, `LOG(BLANK(),10)` refused.

## Failing test (real output)
```
FAILED tests/test_iteration88_text_and_comments.py::TextAndComments::test_unmodelled_stays_refused
AssertionError: False is not true : ROW("a",1)+1
```
`STAYS_REFUSED` in that file is the list of expressions that must be refused. I (Claude) already removed the 5 entries that Power BI has confirmed (`ROW("a",1)`, `{{1}}`, `DIVIDE(1,0,"x")`, `DIVIDE(1,0,TRUE())`, `LN(BLANK())`). Every expression left in that list must be refused. **Do not edit that test.** Fix the code.

## What to fix (in `analytics_studio/measures.py` only)
Make the single-cell-table-as-value rule and the DIVIDE rule as narrow as the verified answers:

1. **Single-cell tables.** `ROW("a",1)`, `{{1}}` and `DATATABLE("a",INTEGER,{{1}})` return `1` only when the table is the **whole expression** and the one cell is a **number**. Inside any other expression (`+1`, `*`, `=`, as an IF argument, and so on) and for a text, Boolean or BLANK cell, they stay refused. `COUNTROWS({{1,2},{3,4}})` stays working.
2. **DIVIDE alternate.** Only a string literal other than `""` and the Boolean `TRUE()` are accepted as the third argument when the denominator is 0 (the two verified cases `"x"` and `TRUE()`). `FALSE()` and `""` stay refused. This looks arbitrary on purpose: we only have Power BI answers for those two.
3. **Plain `BLANK()`.** `BLANK( //c` + newline + `)` must still return `BLANK`. Plain `BLANK()` at the top level must stay refused as it was. Your `allow_blank=True` change at the end of `_Parser.parse` (around line 2466) lets plain `BLANK()` through. Find a narrow way to keep only the comment case. If you cannot do that without a hack, do not guess: write the question under "Open questions" in `HANDOFF.md` and stop.
4. Keep everything else you built that is not in the table above.

## Do not
- Do not edit any existing test, saved Power BI answers, `PARITY_LEDGER.md`, or `tools/parity_check.py`.
- Do not run `--freeze` or `--accept`. Do not commit or merge.
- Do not add new behaviour beyond the plan.

## How to prove it is fixed
1. Run the table above through `dax.local(expr)`. Every row marked "refused" must start with `LOCAL-REJECT`.
2. `PYTHONPATH=. python3 -m pytest tests/test_iteration88_text_and_comments.py tests/test_iteration89_scalar_gaps_1.py -q` must pass.
3. If you want extra safety, add the 10 expressions above as "stays refused" cases in your **own new** file `tests/test_iteration89_scalar_gaps_1.py` (not in iteration 88).
4. `PYTHONPATH=. caffeinate -i python3 tools/parity_check.py --tests` must end with PARITY GATE PASSED and 0 failed. Paste the real summary lines into your HANDOFF entry (pytest line, real-app line, replay line).
5. Set status `READY FOR REVIEW` and add a HANDOFF entry using the template. Say if anything was not done.
