# Task 74: conversion audit (convert-audit-64)

A broad grid of 1,500 information, conversion, math and logical expressions was probed on Power BI (scratchpad t74a). Main got 51 of them wrong. They are recorded in the spec `tools/parity/task74_convert_audit_spec.json` in three parts.

- **A: the text "1e400" (30 rows).** In Power BI, text that converts to a number outside the double range raises an error. We currently return huge Decimal values instead.
  - In a numeric context (VALUE, ABS, ROUND, SQRT, LN, SIGN, POWER, DIVIDE, CONVERT to DOUBLE, FIXED), the error is "Cannot convert value '1e400' of type Text to type Number."
  - In a logical context (AND, OR, NOT, CONVERT to BOOLEAN), the error is "The following system error occurred: Out of present range."
  - Fix the shared text-to-number conversion: parse as a double, and treat an overflow to ±inf as that error.
- **B: int64 extremes 9223372036854775807 and -9223372036854775808 (14 rows).**
  - INT, TRUNC and ROUND of the max value raise "The result of a conversion or arithmetic operation is either too large or too small." ISEVEN and ISODD of the min value raise the same error.
  - ISEVEN and ISODD of the max value go through a double (9.223372036854776E18, which is even), so ISEVEN gives True.
  - FIXED rounds to 15 significant digits through a double: 9,223,372,036,854,780,000.
  - FORMAT "Standard" of the max value is exact: 9,223,372,036,854,775,807.00.
  - Find the general rules (which functions go through a double, and which raise on an int64 overflow) and check them against the evidence.
- **C: other (7 rows).**
  - TRUNC(-1/0) gives NaN.
  - FIXED(0/0,…) raises an error.
  - FORMAT(DATE,"@") gives the date text 1/1/2024.

Rules:
- Compute the answer. Never key on literal text.
- No row that matches on main may change.
- The new tests go in `tests/test_iteration164_convert_audit_64.py`.
