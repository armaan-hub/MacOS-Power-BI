# Task 125 (Iteration 214): DAX refusal backlog, part 13 — row order of UNION results with a TOPN(n>1) arm (dax-uniontopn-115)

Coder: Antigravity, worktree `/Users/armaan/Power BI tool-task125`, branch `antigravity/dax-uniontopn-115`
(branched from Task 124's merge commit 86b0384, which is in the gate now; do not touch the order code of other tasks).

157 saved Power BI answers are refused today for `TOCSV` / `TOJSON` of `UNION(...)` where one arm is `TOPN(n, ALL(Facts),
<col> [, ASC|DESC])` with n > 1 (other arms: `ALL(Facts)`, `Facts`, `FILTER(...)`, `CALCULATETABLE(...)`), mostly under an
outer `CALCULATE` filter. Task 118 (Iteration 207) answered UNION when every arm's order is modelled and a TOPN arm has
n = 1, and refused TOPN arms with n > 1 because Power BI lists their rows in an order that is neither storage nor ranked
(e.g. `TOPN(4, Sales ASC)` gave 2.5, 0, -1.5, blank).

Example (spec): `CALCULATE(TOCSV(UNION(FILTER(Facts,Facts[Sales]>100),TOPN(2,ALL(Facts),Facts[Sales]),CALCULATETABLE(ALL(Facts),Facts[Region]="West"))),Facts[Quantity]<>3)`
Power BI: the TOPN arm rows come out as 10.5,2,East,Paid / 20,3,West,  (20 is the top Sales value, yet it comes second).

**Spec:** `docs/plans/2026-11-10-dax-uniontopn-115-spec.json` (118 items). Today: 0 exact, 118 refused. Opus holds out 39
more and will check ~500 fresh Power BI probes you have not seen.

Your job: find the rule for the row order inside a TOPN(n>1) arm (it may be the storage order of the selected rows,
i.e. the TOPN picks the top n rows but lists them in table order; check ties, ASC / DESC, blank values, n larger than
the row count, and the ORDER BY column). Answer only where the rule holds on every spec item; refuse the rest.

LESSON FROM TASKS 119-124: first versions fitted the spec 100% but got fresh probes wrong. Prefer refusing.

## Rules (binding, see AGENTS.md)
- Compute, never look up: app code must never read `tools/parity/*.json`, the spec, plans, tests or scratch files;
  no tables keyed by expression text.
- An answer you cannot derive exactly stays refused. A locked answer must never change.
- Do not run Power BI; no `--freeze` / `--accept`; no merge or push.
- Check with `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python3 tools/parity_check.py` (DIFF 0, CRASH 0), then
  `git checkout -- PARITY_LEDGER.md`; run the relevant pytest files with `-p no:cacheprovider` (never `-n`).
  Score the spec with `tools/dax_oracle_diff.local`.
- Commit on the branch. Report at the end of `HANDOFF.md` under "Antigravity (Task 125) ready for review": exact /
  refused / wrong on the spec (wrong must be 0), the rules, files changed. Then stop.
