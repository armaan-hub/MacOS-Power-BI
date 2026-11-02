# Task 20: never-blank-zero-10 (what ISBLANK evaluates, the sign of zero and NaN, the logical BLANK, Currency limits, Double text)

**Branch:** `haiku/never-blank-zero-10`  **Written by:** Claude Opus 5.5, 2026-11-02  **Status:** see `HANDOFF.md`
**Who builds:** Haiku 5.5, one Part at a time, started by Opus 5.5. A Part that fails twice goes to Sonnet 5.5.

Read first: `AGENTS.md` ("Compute, never look up"). Every rule below was measured in Power BI Desktop on 2026-11-02, about 3,900 designed probes on top of the Task 19 review answers.

## Goal
1,669 items in `tools/parity/task20_never_blank_zero_spec.json` (fields `part`, `expr`, `powerbi`, and `app_answer` or `app_refusal`). 1,129 are wrong today, 535 refused, 5 crash. The spec is for reading and for the scoring script; the app must never read it. Clearing a wrong answer matters most. An honest refusal is better than a wrong answer.

## Part A: what ISBLANK evaluates (`_never_blank`, `measures.py` near line 3099, and the ISBLANK branch near line 16352)
Power BI answers False without evaluating when a static analysis says the argument can never be BLANK. Otherwise it evaluates, and an error is an error. The old "ponytail" rule in the ISBLANK branch, which swallows a function's own error (`own_error`, `swallowed`), is a guess at this and must go, with its exception list. `ISBLANK(FACT(-1))` is an error, `ISBLANK(SQRT(-1))` is False, `ISBLANK(IF(TRUE(),SQRT(-1)))` is an error, `ISBLANK(IF(TRUE(),SQRT(-1),2))` is False.

Replace `_NEVER_BLANK_CALLS` with one table:
- **Never blank whatever the arguments:** EXP LN LOG LOG10 NOT AND OR, the type tests ISBOOLEAN ISCURRENCY ISDATETIME ISDECIMAL ISDOUBLE ISERROR ISINT64 ISINTEGER ISLOGICAL ISNONTEXT ISNUMBER ISNUMERIC ISSTRING ISTEXT, PI RAND NOW TODAY UTCNOW UTCTODAY TRUE FALSE USERNAME USERPRINCIPALNAME USERCULTURE, CONTAINSSTRING CONTAINSSTRINGEXACT EXACT FIND SEARCH FORMAT ISAFTER ISONORAFTER PATHCONTAINS RANDBETWEEN, EFFECT NOMINAL COUPDAYBS COUPDAYS COUPDAYSNC COUPNCD COUPNUM COUPPCD PDURATION RRI SLN TBILLEQ TBILLPRICE TBILLYIELD RATE INTRATE PRICEDISC RECEIVED SYD YIELDDISC ACCRINTM DB DDB DISC MDURATION PRICEMAT VDB YIELDMAT CUMIPMT CUMPRINC YIELD AMORDEGRC AMORLINC ODDLPRICE ODDLYIELD ACCRINT DURATION PRICE ODDFPRICE.
- **Never blank when the first argument is:** ABS CURRENCY DATEVALUE DAY FIXED HOUR INT ISO.CEILING LEFT LEN LOWER MINUTE MONTH PATHLENGTH QUARTER RIGHT SECOND SIGN SQRT TIMEVALUE TRIM TRUNC UNICHAR UPPER VALUE WEEKDAY WEEKNUM YEAR CEILING DOLLARDE DOLLARFR EDATE EOMONTH FLOOR MOD MROUND POWER QUOTIENT REPT ROUND ROUNDDOWN ROUNDUP YEARFRAC MID SUBSTITUTE.
- **Never blank when any argument is:** CONCATENATE DATE TIME.
- **Never blank when the third argument is:** PMT PV NPER FV.
- **Never blank when every argument is:** MAX and MIN of two scalars, ISPMT PPMT IPMT REPLACE.
- **IF with three arguments:** both branches; the condition is not looked at. Two arguments: evaluated.
- `x IN {..}` is never blank, like a comparison.
- **Everything else is evaluated**, including SIN COS TAN and the other trigonometry, DEGREES RADIANS, FACT COMBIN COMBINA PERMUT GCD LCM SQRTPI EVEN ODD ISEVEN ISODD UNICODE, the BIT functions, the statistics (NORM.* T.* CHISQ.* BETA.* EXPON.DIST POISSON.DIST CONFIDENCE.*), PATHITEM PATHITEMREVERSE NETWORKDAYS DIVIDE COALESCE IFERROR SWITCH IF.EAGER CALCULATE CONVERT DATEDIFF COMBINEVALUES EVALUATEANDLOG, a VAR block, a measure, and an ERROR call.

So `ISBLANK(1+FACT(-1))` is False (`+`: either side) and `ISBLANK(ABS(FACT(-1)))` is an error (ABS needs its first argument, FACT is evaluated). `ISBLANK(LEFT(MAX(Facts[Note]),-1))` is an error, because a column aggregate can be BLANK. `ISBLANK(VAR y=1+ERROR("x") RETURN ABS(y))` is an error; `ISBLANK(VAR y=BLANK()+ERROR("x") RETURN 1)` is False, because the unused VAR is not evaluated. The Currency-division check in that branch stays.

## Part C: the logical BLANK (do this after A)
`a&&""`, with a true `a`, and `a||""`, with a false `a`, take the right side. An empty text there gives a BLANK typed True/False. Also `TRIM("")`, `LEFT("a",0)`, `AND(a,"")`, `OR(a,"")`. It is an ordinary BLANK at run time, with two exceptions.
1. **Static type stays:** `ISBLANK` is False, `COALESCE` and `IFERROR` return it (printed BLANK, in text empty), `ISNUMBER(x*2)` is True, `ISLOGICAL` True. `ISBLANK(x*2)` and `ISBLANK(x*"a")` are False because `*` of two never-blank operands is never blank.
2. **It cancels an error** like a BLANK that scans nothing, on both sides of `*` and on the left of `/`: `(1&&"")*ERROR("x")` and `ERROR("x")*(1&&"")` are BLANK, `IFERROR((1&&"")*SQRT(-1),7)` BLANK, `(IFERROR((1&&"")*SQRT(-1),7))+0` is 0, `ISERROR((0||"")*ERROR("x"))` False. Remove the refusal `refuse_logical_blank_beside` where this answers it. `CONVERT(1&&"",DATETIME)+1` is `12/31/1899 00:00:00`.

**A left side that needs a scan gives False instead**, not a BLANK: `SUM(Facts[Sales])&&""` is False, `(SUM(..))&&""&"z"` is `FALSEz`, `AND(SUM(..),"")` False, `OR(SUM(..)<-1000,"")` False, and in a row context `Facts[Sales]&&""` and `Facts[Sales]>1&&""` are False, so `COUNTAX(Facts,Facts[Sales]&&"")` counts every row.
- Needs a scan: a column read in a row context, SUM AVERAGE COUNT COUNTA COUNTBLANK, SUMX, MINX or MAXX of anything but a plain column, COUNTROWS(FILTER(..)) with a predicate reading a column, ISEMPTY, LOOKUPVALUE, FIRSTNONBLANK, CALCULATE with a filter that is not ALL, and anything containing one (`1+SUM(..)`, `ABS(SUM(..))`, `IF(SUM(..)>0,1)`, a VAR of one).
- Needs no scan: constants, MAX and MIN of a column, MAXX of a plain column, DISTINCTCOUNT, COUNTROWS of a table or of ALL or VALUES or `FILTER(t,TRUE())`, HASONEVALUE, ISFILTERED, CALCULATE of those with no filter or an ALL filter.
`(COUNTROWS(FILTER(Facts,FALSE())))||""` is False. A false `a` in `a&&""` is plain False, as today. `"a"` or any non-empty text on the right is the conversion error, as today.

## Part B: the sign of zero and NaN (values are `Decimal`, which keeps both signs)
All of this is IEEE on a Double. An Int64 or Currency zero has no sign, so a result is signed only when its static type is Double (`_static_numeric_type`; `/` is always Double).
- `0*-1`, `-(0)`, `-(1-1)`, `(1-1)*-1`, `-(COUNTROWS(Facts)*0)`: 0. `0.0*-1`, `-(0.0)`, `0*-1.0`, `0/-1`, `(1-1)/-1`, `-(SUM(Facts[Sales])*0)`, `(COUNTROWS(Facts)*0)/-1`: -0.
- `-(0.0)+0` is 0, `-(0.0)-0` and `-(0.0)+-(0.0)` -0, `-(0.0)*-1` 0.
- -0 prints as `0` as a bare result and in `FORMAT(x,"0.0")`, and as `-0` in `&`, `CONCATENATEX`, `CONVERT(x,STRING)` and `FORMAT(x,"General Number")`.
- `1/-(0.0)` is -Infinity, `1/(0*-1)` Infinity, `1/(0/-1)` -Infinity.
- Keep the sign through: VAR, `SQRT(-(0.0))` is -0, `VALUE("-0")` is -0 in text, `SUMX({0.0},-[Value])` -0, `MAX(-(0.0),0)` -0. Dropped by ABS ROUND INT TRUNC CEILING FLOOR MOD POWER `^` CURRENCY `"-0"+0`, `MIN(0,-(0.0))`. `SIGN(-(0.0))` is -1 (measured).
- NaN: `0/0`, `Inf-Inf`, `Inf*0`, `Inf/Inf` make `-nan(ind)`. Unary minus flips it to `nan`, twice back. `*` `+` `-` keep the sign of the first NaN operand: `(-(0/0))+(0/0)` is `nan`, `(0/0)+(-(0/0))` `-nan(ind)`, `(0/0)*-1` `-nan(ind)`. ABS gives `nan`. FORMAT prints the same two spellings, a bare result prints `NaN`.
- Underflow: a Double smaller than about 5E-324 is ±0: `(-1E-200)*1E-200` prints 0, and `-0` in text.
- `MAX(1,0/0)` is 1, `MAX(0/0,1)` NaN: the first argument is kept unless the second is greater.
The 4 expected failures in `tests/test_iteration108_convert_currency_9.py` (`PartGSignOfZeroAndNaNOpenTests`) should now pass: list that in your report, do not edit the test; Opus removes the marker.

## Part D: Currency limits
- Currency holds value×10000 in a signed 64-bit integer. `+`, `-`, and `*` by a non-Currency, wrap at 64 bits with no error: `CURRENCY(1E14)*10` is -844674407370955.1616, `CURRENCY(922337203685477)+1` is -922337203685477.1616, `CURRENCY(922337203685477)*2` -1.1616, `CURRENCY(1E14)*100` 776627963145224.192. The wrapped value carries on in later arithmetic and text.
- `CURRENCY(x)` of a value outside ±922337203685477.5807 is the overflow error, as is `CURRENCY(1E14)/0.01`. `CURRENCY*CURRENCY` is a Double, no wrap: `CURRENCY(9E14)*CURRENCY(100)` is 9E+16.
- `x^y` with a Currency on one side and an infinite or NaN on the other: exponent Infinity is an error. Exponent -Infinity or NaN: base ≥ 0 gives 0, base < 0 an error. Base Infinity, -Infinity or NaN with a Currency exponent: exponent > 0 error, 0 gives 1, < 0 gives 0. A BLANK base stays BLANK: `(BLANK()*CURRENCY(1))^(1/0)` is BLANK.

## Part E: small rules
1. `IF(ISFILTERED(col),1)`, `IF(ISINSCOPE(col),1)`: a BLANK that reads only the filter context cancels an error also under CALCULATE or CALCULATETABLE with a column filter: `CALCULATE(ISERROR((IF(ISFILTERED(Facts[Region]),1))/(ERROR("x"))),Facts[Quantity]=2)` is False.
2. Arithmetic on text is Double, also for text conversion: `("1E15"+0)&"z"` is `1E+15z`, `LEN("1E15"+0)` 5, `("1000000000000000"+0)&"z"` `1E+15z`.
3. Double to text: take the shortest round-trip digits of the Double, then round to 15 significant half up. `(2/41)&"z"` is `4.87804878048781E-02z`. If this breaks locked items, drop it and report.
4. `FORMAT(1E300,"0")` and `"#,0"` and `"0.00"`: the 15 significant digits then zeros, no `NaN`.
5. `CONVERT(BLANK(),DATETIME)+1` is `12/31/1899 00:00:00`. `SUMX` over a CONVERT to DATETIME of a non-finite value prints `12/30/1899 00:00:00`, `12/31/9999 23:59:59`, `01/01/0100 00:00:00` as a bare result (a date type through SUMX, with VAR and IF).

## Not in Task 20
COUNTAX of NaN through IFERROR, conversion errors of constants in empty iterators through COALESCE, `DATEVALUE` of numeric text, `TIME` through FORMAT and DATEVALUE. They stay open.

## Rules
1. One Part at a time, in the order A, C, B, D, E, then stop and report. Do not start the next Part.
2. Tests first, in `tests/test_iteration109_never_blank_zero_10.py`. Compute expected answers from the rule above.
3. Change the fewest lines you can, and reuse what exists.
4. No rule keyed to how an expression looks. No literal text from the spec in the code. No new kind of value. A result that depends on row order stays refused.
5. A refusal raises `MeasureError` (`dax_typed.refusal`), never `MeasureRuntimeError`.
6. After each Part run the scoring script for that Part (`PYTHONPATH=. QT_QPA_PLATFORM=offscreen python <scratchpad>/t20/score.py A`) and the replay (about 2 minutes): `PYTHONPATH=. QT_QPA_PLATFORM=offscreen python tools/parity_check.py`. It must show 0 DIFF, 0 CRASH. `git checkout PARITY_LEDGER.md` after a replay.
7. Never run `--freeze`, `--accept`, commit, merge, push or Power BI. No global replace on `measures.py`. No edits to existing tests or saved answers: list those in your report. Scratch files go in the scratchpad.
