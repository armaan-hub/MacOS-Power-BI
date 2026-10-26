# Experiment Log

*Objective: Audit Power Query Editor and semantic-model/DAX capabilities against official Power BI Desktop workflows, create a prioritized acceptance roadmap, and implement the highest-priority complete end-to-end increment while preserving existing workspace changes.*
*Metric:  (lower is better)*

## Experiments

| # | Iteration | Action | Metric | Changes | Learnings |
|---|---|---|---|---|---|
| 1 | 8 | KEEP | full suite: 601 passed, 433 subtests; focused Power Query 153/194 and DAX 37/20 | POWER_BI_FUNCTIONALITY_PROGRESS.md           |   48 +-
 POWER_BI_FUNCTIONALITY_ROADMAP.md            | - |

---

**Legend:**
- ✅ KEEP = Metric improved or acceptable. Changes retained.
- ⏪ DISCARD = Metric regressed or unacceptable. Changes rolled back.
| 2 | 84 | KEEP | gate: pytest 1,827 passed (6,262 subtests), real app 575/575, replay 44,345 match / 0 DIFF / 0 CRASH, locked 44,325 | date/time-intelligence engine (TOTAL*TD, DATEADD, PARALLELPERIOD, DATESINPERIOD/BETWEEN, FIRST/LASTDATE, STARTOF*/ENDOF*, NEXT*/PREVIOUS*, OPENING/CLOSINGBALANCE*, FIRST/LASTNONBLANK), one-to-one blank members, 8 UI fixes (PQ column menu, ribbon, direct apply, Advanced Editor, Conditional Column, DAX formula bar/IntelliSense/Table+Measure tools), Critic and Testing fixes | Critic: 36,288 fresh live probes found 1,187 wrong answers, all now match (1,137) or refuse (50). Testing: 12,534 fresh probes found 70, all now match (27) or refuse (43). A guard that refuses is safer than a wrong answer; every fix that was too broad was caught by locked tests (131 answers once). Wall-clock times in the agent sandbox were inflated by Mac sleep (use CPU time); a modal prompt inside a locked test hangs pytest (cancel() must stay a plain discard). |
| 3 | 85 | KEEP | gate: pytest 1,871 passed (6,283 subtests), real app 575/575, replay 44,962 match / 554 refused / 0 DIFF / 0 CRASH, locked 44,942 | ribbon insert-after-selected step, `]]` DAX names, SWITCH over text in iterators (617 more answers), Sparse buttons removed | Wrong answers hide in mixed-type iterator columns; refuse them per row, not per expression |
| 3 | 86 | KEEP | gate: pytest 1,882 passed (6,283 subtests), real app 575/575, replay 45,158 match / 358 refused / 0 DIFF / 0 CRASH, locked 45,138 | CALCULATETABLE in True/False filter (hoist vs transition), Booleans in COUNTX/MAXX arithmetic, NaN in COUNTX | Hoist-vs-transition rule found from saved answers then 12,500 fresh probes; a first rule had 14 wrong answers that probes caught |
| 3 | 87 | KEEP | gate: pytest 1,897 passed (6,281 subtests), real app 575/575, replay 45,322 match / 194 refused / 0 DIFF / 0 CRASH, locked 45,302 | mixed-type (Variant) IF/SWITCH/IFERROR/COALESCE iterator bodies, types of IN/information functions/statistics/numeric conditions; 164 refusals answered |
| 3 | 88 | KEEP | gate: pytest 1,917 passed, real app 575/575, replay 45,446 match / 70 refused / 0 DIFF / 0 CRASH, locked 45,426 | nested row contexts (EARLIER/EARLIEST), CALCULATETABLE in True/False filters under any context, strict ==, text as True/False, small functions | refusals 194 -> 70; 46,891 fresh live probes, 0 wrong |
