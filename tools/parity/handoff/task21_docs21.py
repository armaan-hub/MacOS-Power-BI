import re,sys
LOCK,MATCH,REF,TOT,PYT=sys.argv[1:6]
status = (f"**Latest status (2026-11-02, after Iteration 110 / Task 21 currency-double-11, Currency with Doubles computed in doubles, static types beside text numbers, CURRENCY of text and non-finite values, dates beside Infinity or NaN, the logical BLANK beside an error, "
 f"coded by Haiku 5.5, fixed by Sonnet 5.5, planned, reviewed and shipped by Claude Opus 5.5 under the user's delegated approval):** pytest {PYT} passed and 1 expected failure, real app 575/575 and 6,000 fresh probes with 0 wrong, "
 f"replay {TOT} answers with {MATCH} match, {REF} refused, 0 DIFF, 0 CRASH, locked {LOCK}. Open: refusals listed in `HANDOFF.md`. Next: Task 22 from those open items.")
for f in ["PROJECT_PROGRESS_SUMMARY.md","POWER_BI_FUNCTIONALITY_PROGRESS.md","POWER_BI_FUNCTIONALITY_ROADMAP.md"]:
    s=open(f,encoding="utf-8").read()
    s,n=re.subn(r"^\*\*Latest status \(2026-11-02, after Iteration 109.*$", lambda m: status, s, count=1, flags=re.M)
    assert n==1,f
    open(f,"w",encoding="utf-8").write(s)
open("POWER_BI_FUNCTIONALITY_WORK_LOG.md","a",encoding="utf-8").write(f"""
## 2026-11-02 — Iteration 110 (Task 21 currency-double-11: Currency with Doubles, types beside text numbers, CURRENCY of text, dates beside Infinity or NaN, logical BLANK beside an error)

**Who did what:** Haiku 5.5 coded the six Parts as one subagent. Sonnet 5.5 fixed the review findings in two rounds. Claude Opus 5.5 planned, measured the rules in Power BI on the iPad guest, reviewed and shipped under the delegated approval.

**Rules measured in Power BI and now in the engine:**
- A Currency times or over a Double: the Currency's count of ten-thousandths is taken as a double, multiplied or divided in doubles and rounded half away from zero (136 of 136 rows). A Double over a Currency is a plain Double, held at 15 significant digits.
- Static types beside text numbers: text + or - Currency is a Double, text times Currency is a Currency, Currency over text or a date is a Currency, text or a date over Currency is a Double, text or a logical + a date is a date.
- CURRENCY and CONVERT of a text read its exact digits, rounded half to even; beyond the Currency range, or Infinity or NaN, is the error.
- A text number beyond the Double range (`"1E400"`) in + - * / is the conversion error; IFERROR catches it, and for `/` it shows through type tests.
- A date beside Infinity or NaN keeps that value: NaN prints as day zero, Infinity as the ends of the range; FORMAT "yyyy" of NaN is 1899 and of Infinity the error.
- MINX or MAXX over a stored table whose body is NaN on every row is BLANK, but NaN when evaluated inside IFERROR's first argument (14 probes); a VAR bound outside keeps BLANK.
- AVERAGEX of a Currency body is a Currency, rounded to ten-thousandths.
- The logical BLANK `(x&&"")` or `(x||"")` cancels an error in `*` and on the left of `/`, also one level deeper in a chain.
- UNICHAR(BLANK()) is BLANK; DIVIDE with a scanned BLANK numerator converts a text divisor.
- Type tests of a row-reading Currency product beyond range: ISCURRENCY and ISNUMBER show the error, ISDOUBLE and ISINT64 answer by type (saved answers).

**Review:** a fresh batch of 5,914 new shapes on 3 tables (17,742 Power BI answers), scored on `main` and the build: first round 10 new wrong answers (Double over Currency kept the full binary expansion; `"1E400"` under ISCURRENCY), fixed. Final: 560 wrong to right, 1,036 refused to match, 15,304 stay matching, 824 stay refused, 18 wrong to refused, 0 new wrong, 0 wrong on both. Spec score: 2,508 match, 29 refused, 0 wrong of 2,537. Code read for lookups: none.

**Tested in the real app and against Power BI on the iPad guest:** the real app through the measure path, offscreen: 575/575 equal, and 6,000 fresh probes, 5,181 created, 819 refused (603 Power BI errors, 216 safe gaps), 0 wrong. New answers came from Power BI Desktop on the iPad guest, headless; the project was not saved.

**Saved:** `tools/parity/dax_battery_currency11_extra.json` (8,168 answers on the standard table: the fresh probes, the Task 21 spec answers and the MINX probes), `tests/fixtures_currency11_review_alt.json` (5,789 each on tables A and B). No saved Power BI answer was edited. Two stale test expectations changed, each now asserting Power BI's saved answer: `tests/test_iteration108_convert_currency_9.py` (CONVERT(1/0,DATETIME) is 12/31/9999 23:59:59) and `tests/test_iteration100_variant_iterators_2_review.py` (an AVERAGEX of a Currency SWITCH is 5.1667).

**Gate:** PARITY GATE PASSED. pytest {PYT} passed, 1 expected failure; replay {TOT}: {MATCH} match, {REF} refused, 0 DIFF, 0 CRASH; locked 422,299 to {LOCK}. The DSI workbook is still missing on this Mac, so its answers were not replayed.

**Open (refused, not wrong):** ISINT64 and ISCURRENCY of `"1E400"` minus a date; IFERROR around MINX or MAXX of NaN beside other functions; `(1&&"")*"a"*1` and `"a"*(1&&"")` with constant x; 5 Part D items (TODAY()*0 and a NaN date product); 24 Part E items (text beside the logical BLANK, constant x).
""")
s=open("HANDOFF.md",encoding="utf-8").read()
lines=s.split("\n")
for i,l in enumerate(lines):
    if l.startswith("| 21 | currency-double-11"):
        c=l.split(" | ")
        c[3]=f"DONE (coded by Haiku 5.5, fixed by Sonnet 5.5, reviewed, locked {LOCK}, merged 2026-11-02)"
        c[4]="Claude |"
        lines[i]=" | ".join(c[:5])
    if l.startswith("Task 21 currency-double-11, on branch"):
        lines[i]="None. Task 22 is to be planned from the Task 21 open items below."
    if l.startswith("## Open questions"):
        lines.insert(i+1,"- Claude (open, Task 21, refused rather than wrong): ISINT64/ISCURRENCY of `\"1E400\"-DATE(...)` (Power BI False); IFERROR around MINX/MAXX of NaN inside COALESCE or IF; `(1&&\"\")*\"a\"*1` (Power BI BLANK) and `\"a\"*(1&&\"\")`; TODAY()*0 and NaN date products (Part D); text beside the logical BLANK and constant x (Part E, 24); the Task 20 refusals (ATAN/CEILING of non-finite in ISBLANK, type tests around a failing power).")
        break
open("HANDOFF.md","w",encoding="utf-8").write("\n".join(lines))
p="docs/plans/2026-11-02-currency-double-11.md"
s=open(p,encoding="utf-8").read().rstrip("\n")+f"""

## Review outcome (2026-11-02)
Shipped as Iteration 110. Haiku's six Parts scored 2,508 match, 29 refused, 0 wrong on the spec. A fresh batch of 5,914 shapes on 3 tables found 10 new wrong answers and 256 wrong on both; Sonnet fixed them in two rounds (Double over Currency at 15 digits, text beyond the Double range, FORMAT of a non-finite date, MINX/MAXX of NaN inside IFERROR, AVERAGEX of Currency, the logical BLANK in chains, type tests of a Currency product beyond range). Final: 0 wrong, 560 wrong to right, 1,036 refused to match. Locked {LOCK}.
"""
open(p,"w",encoding="utf-8").write(s)
