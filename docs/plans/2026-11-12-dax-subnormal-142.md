# Task 142 — dax-subnormal-142: subnormal doubles (0 < |x| < 2.2250738585072014E-308)

Goal: answer DAX math, rounding, conversion and power calls whose argument is a subnormal double, which the engine
refused or (in 3 saved cases) answered wrongly.

Spec: the measured Power BI table in `analytics_studio/dax_subnormal.py` (built from probe grids on Power BI Desktop in
the guest). Power BI's behaviour on a subnormal depends only on its sign: SIGN gives 0 for a positive one and -1 for a
negative one, DIVIDE by one gives BLANK, INT gives 0, MOD/POWER(x,0) give the wrong-data-type error, ROUND keeps the
value, FIXED gives "0", CURRENCY gives 0, CONVERT(x,BOOLEAN) gives True.

Rules (Haiku 5.5 coded the table and hooks, Sonnet 5.5 reviewed and fixed):
- Hooks in `measures.py`: call dispatch (literal and evaluated arguments), the scalar values block, `^`, binary `/`,
  unary minus and the scalar-math branch (so computed subnormals such as `1E-160*1E-155` reach the table).
- SIGN/INT/ROUND use the sign-only rule up to 5.1E-310 and ordinary-number answers from 4.9E-309; the gap between is
  refused. POWER and `^` switch at 5.9E-309.
- DEGREES/RADIANS computed in double; GCD, QUOTIENT/MOD by 0, LOG with a base <= 0, POWER(b,x) and subnormal bases with
  negative exponents follow the measured grid; QUOTIENT never returns a negative zero.
- Combinations outside the table keep the existing path (answer or refusal); unlisted POWER/`^` combinations refuse.

## Results
spec 256 -> 590 exact (93 refused), holdout 577/580, hidden1-3 540/540 each; fresh 250-expression Power BI probe
250/250 (strict: 244 exact, 6 within Power BI's own one-step subnormal print rounding); wrong 0 everywhere.
`tests/test_iteration164_convert_audit_64.py` now asserts Power BI's probe-verified answers for the 11 rows it used to
expect refusals for.

## Review outcome (2026-11-12)
Shipped as Iteration 231. Locked 537342.
