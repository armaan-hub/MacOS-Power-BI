# Task 33 xirr-oddfyield-23: new DAX functions XIRR and ODDFYIELD, PATHITEM with a type argument

**Coder:** Antigravity. **Work folder:** git worktree `/Users/armaan/Power BI tool-task33` (branch `antigravity/xirr-oddfyield-23`). Work ONLY there.
**Spec:** `tools/parity/task33_xirr_oddfyield_spec.json`: 392 answers measured live in Power BI Desktop on 2026-11-03.
- Part A (187): **XIRR(table, values, dates[, guess[, alternate]])** on 70 random cash-flow tables (2-8 rows, some with unsorted dates, no sign change, or a duplicate date), plus guesses, the alternate result, an empty table, a BLANK value, times of day, a zero flow. Today "Function XIRR is not supported". Power BI: `XIRR(DATATABLE("v",DOUBLE,"d",DATETIME,{{-1000,"2020-01-01"},{300,"2020-06-01"},{400,"2021-01-01"},{500,"2021-06-01"}}),[v],[d])` = 0.196920434385538; no sign change is the error "The XIRR function couldn't find a solution."
- Part B (45): **ODDFYIELD(settlement, maturity, issue, first_coupon, rate, pr, redemption, frequency[, basis])** on 40 random bonds plus error cases (frequency 3, negative rate, basis 5, settlement after first coupon, 8 arguments). Power BI: `ODDFYIELD(DATE(2008,11,11),DATE(2021,3,1),DATE(2008,10,15),DATE(2009,3,1),0.0575,84.5,100,2,0)` = 0.0772455415972989. (Many error rows already match.)
- Part C (160): **PATHITEM / PATHITEMREVERSE with the type argument** (INTEGER, TEXT, 1, 0) on several paths and positions. Today the type argument refuses.

## Background
XNPV (Task 3) and the other financial functions live in the engine (search XNPV, ODDFPRICE in `analytics_studio`); add XIRR beside XNPV (Excel-compatible: Newton iteration on XNPV with dates relative to the first row's date / the minimum date, 365-day year; check Power BI's convergence tolerance and iteration limit against the rows, and what "alternate" returns). ODDFYIELD is the Excel odd-first-period yield (solve ODDFPRICE for the yield). Register new names in `_FUNCTIONS`, the function catalog and the insert list; Claude re-syncs DAX_COMPATIBILITY_CONTRACT.md.

## Rules
Compute, never look up. Never edit saved Power BI answers or existing tests. No --freeze/--accept/commit/merge/push/full pytest. 0 wrong is mandatory; refuse what the rows do not settle. Replay: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen caffeinate -i python3 tools/parity_check.py` (0 DIFF, 0 CRASH, PARITY GATE PASSED; then `git checkout PARITY_LEDGER.md`). Expect `tests/test_dax_contract_sync.py` to fail because the function count changes: leave it, Claude syncs the contract.

## Commands (in the worktree)
Scorer: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/score_spec.py tools/parity/task33_xirr_oddfyield_spec.json [A|B|C]`. Tests: `tests/test_iteration123_xirr_oddfyield_23.py`. When done, leave changes uncommitted and write a ready-for-review entry in this worktree's `HANDOFF.md`. Do not write session logs outside this worktree.
