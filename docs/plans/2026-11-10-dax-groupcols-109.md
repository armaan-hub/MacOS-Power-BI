# Task 119 (Iteration 208): DAX refusal backlog, part 7 — row order of SUMMARIZECOLUMNS and GROUPBY results (dax-groupcols-109)

Coder: Antigravity, worktree `/Users/armaan/Power BI tool-task119`, branch `antigravity/dax-groupcols-109`
(branched from Task 118's commit, which is in the gate now; do not touch the UNION code from Task 118).

The group `dax_battery_orderaudit57_extra` holds 270 saved Power BI answers the app refuses today with
"The row order of this table expression is not modelled in the local engine, so TOCSV / TOJSON refuse it." for
`TOCSV` / `TOJSON` of `SUMMARIZECOLUMNS(...)` and `GROUPBY(...)` (one or several group columns, with or without
extension columns such as `"s", SUM(...)` or `"m", MAXX(CURRENTGROUP(), ...)`, over `Facts` or `FILTER(Facts, ...)`),
mostly under an outer `CALCULATE` filter.

Examples (expressions from the spec; read their saved Power BI answers there):
- `TOCSV(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity]),100)`
- `CALCULATE(TOCSV(SUMMARIZECOLUMNS(Facts[Note],Facts[Region],"s",SUM(Facts[Quantity])),100),Facts[Quantity]>1,Facts[Note]<>"Late")`
- `CALCULATE(TOCSV(GROUPBY(Facts,Facts[Note],Facts[Sales]),100),Facts[Note]="Paid")`
- `TOJSON(GROUPBY(FILTER(Facts,Facts[Quantity]>1),Facts[Region],"c",COUNTX(CURRENTGROUP(),1)))`

**Spec:** `docs/plans/2026-11-10-dax-groupcols-109-spec.json` (216 items: `expr`, `powerbi`, `group`). Today: 0 exact,
216 refused. Opus holds out 54 more and will probe fresh shapes on Power BI.
Read the existing SUMMARIZECOLUMNS / GROUPBY code, the TOCSV / TOJSON row-order code (`_tocsv_row_order` in
`measures.py`, including the existing "grouped" and "dictionary" order classes) and `dax_iteration_order.py` first.
Single-column group order may already be modelled for SUMMARIZE / VALUES; check how several group columns, extension
columns, BLANK groups and outer filters change the order.

Your job: find the rule Power BI uses for the row order of SUMMARIZECOLUMNS and GROUPBY results, and answer those
exactly. Where a shape is not certain (for example several group columns whose combined order you cannot derive),
keep refusing. Write the rule per family (answered / refused) in your report.

## Rules (binding, see AGENTS.md)
- Compute, never look up: app code must never read `tools/parity/*.json`, the spec, plans, tests or scratch files;
  no tables keyed by expression text.
- An answer you cannot derive exactly stays refused. A locked answer must never change.
- Do not run Power BI; no `--freeze` / `--accept`; no commit, merge or push.
- Check with `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/parity_check.py` (DIFF 0, CRASH 0), then
  `git checkout -- PARITY_LEDGER.md`; run the relevant pytest files with `-p no:cacheprovider` (never `-n`).
  Score the spec with `tools/dax_oracle_diff.local`.
- Report at the end of `HANDOFF.md` under "Antigravity (Task 119) ready for review": exact / refused / wrong on the
  spec (wrong must be 0), the rules, files changed. Then stop.
