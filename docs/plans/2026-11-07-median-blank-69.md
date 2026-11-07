# Task 79: MEDIAN / PERCENTILE returning BLANK (median-blank-69)

Grid `SP/t79e` holds 196 MEDIANX, PERCENTILEX.INC/EXC, MEDIAN and PERCENTILE expressions over Facts, ALL, ALLSELECTED and FILTER, unfiltered and under filters. It was run on 35 alternate row sets (ds.py d2–d36). There are 120 wrong answers on main, all with the same symptom: **Power BI returns BLANK where we return 0.** The standard Facts table never shows it.

The set of rows the expression sees evidently produces BLANK in Power BI, while we produce 0. For each wrong row:
- Work out the values that row set gives, with BLANKs included.
- Find the rule. Candidates: the median lands on a BLANK; BLANKs are counted in n but sorted first; the result is the 0 that BLANK becomes, which Power BI then returns as BLANK.
- Check the rule against every matching row too.

Paths:
- SP=/private/tmp/claude-501/-Users-armaan-Power-BI-tool/67587267-1afe-455e-9564-38768bd7190f/scratchpad
- Dataset rows: SP/t67d/ds.py.
- Rebuild, run from the worktree: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen /usr/local/bin/python3 SP/t67d/ds.py local N SP/t79e/in.json SP/t79e/dN/build.json`
- Score: `PYTHONPATH=. python3 SP/cmp.py SP/t79e/dN`

Fit on d2–d24. d25–d36 are held out for Opus.

Rules:
- Compute the answer; never key on expressions or datasets.
- Locked batteries must stay green.
- The standard grid t72a (statistics, 1,500 rows) must not regress. Rebuild it with SP/t38f/local.py, then run cmp.py.
- New test file: tests/test_iteration168_median_blank_69.py.
