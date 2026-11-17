# Chapter 1 close report: DAX engine baseline

Closed 2026-11-17 by Team-Planner (Claude Opus 5.5); done list checked by Team-Thinker (Sonnet 5.5). Tag `chapter-1-dax-baseline`.

## Numbers (fresh full gate, `PYTHONPATH=. python tools/parity_check.py --tests`, main `0dd9189`)
- Replayed 540,401 Power BI answers: 537,362 match, 3,039 pending (app refuses), 0 differ, 0 crash. Lock: 537,342 ids (537,341 unique matching ids, because 15 expressions repeat with 21 extra rows, + 1 stale locked id from `dax_battery_allselected_shadow` that is no longer replayed).
- Real app: 575 measures created, 575 equal to Power BI.
- pytest: 5,039 passed, 26 xfailed, 2 order-dependent failures that pass alone.
- PARITY GATE PASSED.

## What was replayed
- DAX batteries: 135 files replayed (136 exist; `dax_battery_xirr_research` is not in the gate list) (Power BI Desktop answers, saved over Iterations ~1-282).
- Table answers: VAT workbook only, 575 answers. `tests/Data/Vat File -Aug 2026.xlsx` (gitignored) SHA-256 `8f7e4656a03b487d4fbe504718aec372c5564d8fc80b5eca38769434ba003965`.
- NOT replayed: DSI workbook (`~/Downloads/DSI.xlsx` missing), 108 saved answers. A fresh clone at this tag also needs the VAT workbook copied in.

## REA evidence
- Target: `bin\msmdsrv.exe` from Power BI Desktop 2.157.879.0 (SHA-256 f71b3817...), Ghidra provider, pilot plan `docs/plans/2026-11-17-rea-msmdsrv-calculate-pilot.md`, findings `docs/rea-msmdsrv-calculate-findings.md`.
- REA found the CALCULATE source-file and operator names, but the DAX core is native code without symbols; it gave no readable rule that the answer check had not already decided. For this chapter the Power BI answer check was the method.

## Known gaps carried forward
- Chapter 1b: the 3,039 pending answers (see `CHAPTERS.md`).
- Two order-dependent pytest failures (xdist pickling of `LineagedRow`; signed int64 range test).
- DSI workbook answers not replayed.
- One stale locked id (`dax_battery_allselected_shadow:CONCATENATEX(SUMMARIZECOLUMNS(...`) is in `baseline.json` but no longer replayed; harmless, left as is (no deletion).
