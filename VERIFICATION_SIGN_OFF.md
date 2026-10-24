# Iteration 84 verification sign-off (Testing Agent, main b856211)

Verdict: **NOT VERIFIED** (the gate and suites are green, but 70 fresh live probes disagree with Power BI Desktop).

## Fresh live probes (tests/fixtures_testing84.json)
- 12,534 new expressions in no existing fixture or battery (0 overlap, 0 duplicates per model), seeds ZO 8411/8421, ZB 8412/8422, ZS 8413/8423, ZM 8414/8424, run one model per run with `tools/model_diff.py`.
- match 11,149, gap-reject 1,315, DIFF 70, CRASH 0.
- ZO 2755/388/13, ZB 2760/381/16, ZS 2792/341/11, ZM 2842/205/30 (match/gap-reject/DIFF).

## DIFF classes (all in the fixture file, with reduced reproducers under "reproducers")
| class | n | minimal reproducer | Power BI | ours |
|---|---|---|---|---|
| ZM one-to-one orphan member (W row with no U partner counts the orphan fact rows) | 29 | `SUMX(ZM_W,CALCULATE(COUNTROWS(ZM_F)))` | 4 | 5 |
| same class, filter on the many side | | `CALCULATE(COUNTROWS(ZM_W),FILTER(ZM_F,1=1))` | 3 | 4 |
| same class | | `CONCATENATEX(ZM_W,ZM_W[K]&":"&CALCULATE(SUM(ZM_F[Amt])),"\|",ZM_W[K],ASC)` | k5: (blank) | k5:32 |
| same class | | `CALCULATE(SUMX(ZM_W,CALCULATE(COUNTROWS(ZM_F))),ZM_F[K]="k9")` | BLANK | 1 |
| OPENINGBALANCE* over a fact date column / set | 3 | `OPENINGBALANCEMONTH(COUNTROWS(ZO_Fact),DATESYTD(ZO_Fact[Dt]))` | 1 | BLANK |
| | | `OPENINGBALANCEQUARTER(MAX(ZB_Fact[Amt]),ENDOFQUARTER(ZB_Fact[Ship]))` | 60 | BLANK |
| | | `OPENINGBALANCEMONTH(SUMX(ZB_Fact,ZB_Fact[Amt]*ZB_Fact[Qty]),LASTDATE(DISTINCT(ZB_Fact[Dt])))` (ALL(ZB_Cal[Date]), Year=2023) | 440 | BLANK |
| ALLSELECTED shadow inside CALCULATE with FILTER(ALL(cal)) | 1 | `COUNTROWS(CALCULATETABLE(NEXTMONTH(FIRSTDATE(ALLSELECTED(ZS_Cal[Date]))),ZS_Cal[MonthNo]=10,FILTER(ALL(ZS_Cal),ZS_Cal[Year]=2024)))` (MAXX gives 02/29/2024 in Power BI, 11/30/2024 ours) | 29 | 30 |
| Power BI refuses ("A single value for column ... cannot be determined"), ours answers BLANK (empty/one-row iteration) | 34 | `SUMX(FILTER(ZO_Cal,FALSE()),ZO_Fact[Amt])` | ERR | BLANK |
| Power BI validates every branch (KEEPFILTERS used outside CALCULATE), ours is lazy | 2 | `IF(TRUE(),1,CALCULATE(MAX(ZS_Cal[Date]),PREVIOUSQUARTER(KEEPFILTERS(ZS_Cal[Date]))))` | ERR | 1 |
| Power BI validates a text column in TOTALYTD in an untaken branch | 1 | `IF(COUNTROWS(VALUES(ZM_F2[K]))>3,TOTALYTD(SUM(ZM_F[Amt]),ZM_U[K]),"n")` | ERR | n |

gap-reject clusters (we refuse, Power BI answers): SAMEPERIODLASTYEAR/DATEADD/PARALLELPERIOD over a set or fact date column (about 325), TOTAL*TD with a table-expression date argument (134), CALENDAR start>end (23), CROSSJOIN same-name columns (23), one-to-one both-table filters (16), others.

## Gate and suites
- `parity_check.py --tests`: PARITY GATE PASSED. pytest 1822 passed, 6262 subtests; real app 575/575 equal Power BI; replay 45,516 saved answers: match 44,345, gap-reject 1,171, DIFF 0, CRASH 0, locked 44,300. Gap: /Users/armaan/Downloads/DSI.xlsx missing, its answers were not replayed.
- `pytest tests/test_formula_bar_draft_guard.py tests/test_advanced_editor.py`: 34 passed, exit 0.
- macOS crash reports `Python-*.ips`: 23 before, 23 after every run (0 new).

## UI smoke (offscreen, real app object)
All 8 items exercised (header menu, ribbon labels and direct apply, Advanced Editor, Conditional Column, formula bar draft guard / IntelliSense / Table and Measure tools / error banner): 56+13 checks pass; the only failures were test-script mistakes. Open observations: Home ribbon "Reduce Rows" shows non-Power-BI "Sparse Top / Sparse Bottom" buttons; Escape in the formula bar discards a dirty draft without asking.
