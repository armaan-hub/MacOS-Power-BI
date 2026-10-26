# Analytics Studio project rules

## Two-agent workflow (set by the user 2026-10-26)
Antigravity writes the new feature code. Claude plans, tests and fixes errors in Antigravity's code. Claude does NOT write
new feature code until the user explicitly says so (and then only for that task). Full rules: `AGENTS.md`. Message board:
`HANDOFF.md`. Read both before starting, check the "Active agent" line, update status and entries when stopping.

## Parity rule (standing, set by the user 2026-10-21)
Every function or feature we build is compared with Power BI Desktop (Windows VM oracle, `tools/*_oracle_diff.py`, REA)
when it is completed, and from then on it is re-tested on every change so it never has to be worked on again.

- A slice is finished only when: (1) its Power BI answers are saved (`PYTHONPATH=. python tools/parity_check.py --freeze`
  for DAX batteries, `tools/table_oracle_diff.py` for workbooks), (2) the gate passes, (3) it is locked with `--accept`.
- Before and after any code change run `PYTHONPATH=. python tools/parity_check.py --tests`
  (replays every saved Power BI answer, the pytest suite and the real-app run). It must say PARITY GATE PASSED.
- A locked item that stops matching is a regression: fix the code, never edit the saved Power BI answers.
- `PARITY_LEDGER.md` is the status board (locked / pending / differs). Pending items are the work list.
- Test data: `tests/Data/Vat File -Aug 2026.xlsx`, sheet `VAT 5%`, header row 12.
- Use only the iPad (Parallels guest) screen for Power BI; never the main Mac screen; never save the Power BI project.
- After each iteration remind the user to run `/compact`.
