# Task 95 (Iteration 184): ORDER arguments of CONCATENATEX, RANKX and ORDERBY (order-argument-85)

DAX close-out finding (2026-11-08): the app accepts ORDER values Power BI rejects, so it answers where Power BI errors
(28 wrong answers in the probe battery). TOPN, TOPNSKIP and SAMPLE already validate; CONCATENATEX, RANKX and ORDERBY do not.

**Spec:** `docs/plans/2026-11-08-order-argument-85-spec.json` (144 live Power BI cases on Facts). Main: 115 match,
28 wrong, 1 refused. Target: 0 wrong (an `ERR:` answer is matched by any `LOCAL-REJECT`).

## Measured behaviour
- An ORDER argument (CONCATENATEX positions 5, 7, 9 … after each orderBy expression; RANKX argument 4; ORDERBY's
  argument after each expression) accepts exactly: `0`, `1`, `TRUE()`, `FALSE()` (also the bare `TRUE`/`FALSE`
  constants), `ASC`, `DESC`. `1`/`TRUE`/`ASC` ascending, `0`/`FALSE`/`DESC` descending.
- Anything else is Power BI's error `Unexpected value for ORDER argument in <FUNCTION> function. Use 0/FALSE/DESC for
  descending order or 1/TRUE/ASC for ascending order.` — columns, other numbers (`2`, `-1`, `1.5`), text `"ASC"`, `BLANK()`,
  comparisons, `SKIP`, `DENSE`. In CONCATENATEX, an expression in an ORDER position is this error, NOT a second
  orderBy expression (e.g. `CONCATENATEX(Facts,…,",",Facts[Sales],Facts[Quantity])` is an error).
- A non-literal ORDER (variable, measure, calculated expression that happens to be 0/1) is not measured: refuse.
- Reuse the existing helper style (`analytics_studio/dax_order.py` `_ascending` and the TOPN check near
  `measures.py` "Unexpected value for the ORDER argument in the TOPN function"); keep TOPN / TOPNSKIP / SAMPLE / ISAFTER /
  ISONORAFTER behaviour unchanged.

## Part 1 (Haiku)
- [ ] Step 1: test `tests/test_iteration184_order_argument_85.py`: every spec case (spec read in the test only): `ERR:` → local
  starts with `LOCAL-REJECT`; else `tools.dax_oracle_diff.same(power_bi, local)` or a LOCAL-REJECT (refusal allowed only for the
  case already refused on main).
- [ ] Step 2: run it (28 failures on main).
- [ ] Step 3: implement the checks in CONCATENATEX, RANKX and ORDERBY.
- [ ] Step 4: run the new test plus every test file mentioning CONCATENATEX, RANKX, ORDERBY, WINDOW, OFFSET, INDEX, TOPN
  (`grep -l` in tests/), all pass.
- [ ] Step 5: leave uncommitted and report (Opus commits).
