# Task 60: type tests over failing arithmetic with column reads (type-tests-columns-50)

**Goal:** answer more of the 474 pending rows in tools/parity/task60_type_tests_columns_spec.json (Part A ISLOGICAL/
ISBOOLEAN 107, Part B number/date tests 216, Part C ISTEXT/ISNONTEXT/ISSTRING 95, Part D no type test 56; 24 match now)
with 0 wrong. These are what Task 57 left: a type test (or VAR/SUMX wrapper) around +, -, *, /, &, &&, || where an
operand reads a column (MAX(Facts[Note]), SUM(Facts[Sales]) ...) or is a VAR, and the conversion fails.

**Why refused now:** analytics_studio/measures.py hidden_failure_verdict / static_type_answer / _structural_type_answer
(~line 4400-4700) refuse column-read arithmetic because 26 saved Power BI rows of that kind RAISE instead of answering.

**Method (data first, then code):**
1. Write an analysis script in the scratchpad (NOT in the app) that loads every tools/parity/dax_battery_*.json row whose
   expression is a type test or one of the Part D shapes over such an operator, and classifies each row by a small
   feature tuple: (type test name, operator, left operand kind, right operand kind, wrapper), where operand kind is one of
   literal-number, literal-text, BLANK, TRUE/FALSE, column-aggregate-number (SUM/MAX of Quantity/Sales), column-aggregate-text
   (MAX/MIN of Note/Region), VAR, failing-call (VALUE("x"), "a"*2, INT("a")), empty-iteration (SUMX(FILTER(Facts,FALSE()),1)).
   For each tuple record the outcomes: Power BI answer value or ERR.
2. A rule may be implemented only for a tuple class where every saved row agrees (no ERR beside an answer, no two
   different answers) AND there are at least 5 rows. Answers come from the static result type of the operator
   (+ - * / -> Double, & -> Text, && || -> Boolean), never from a lookup.
3. Implement those rules in the existing functions; everything else keeps refusing.

**Done when:** spec 0 wrong (report per part), full pytest, replay DIFF 0 CRASH 0, tests in
tests/test_iteration150_type_tests_columns_50.py (answered rows plus one raising row that stays refused).
