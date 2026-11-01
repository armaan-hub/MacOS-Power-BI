"""Iteration 106: small-gaps-7 (Task 17).

Plan: docs/plans/2026-11-01-small-gaps-7.md
Parts:
  - Part A: A VAR holding a True/False expression or a TREATAS table as a CALCULATE filter
  - Part B: EVALUATEANDLOG around a filter modifier
  - Part C: Types of date arithmetic in a table constructor
  - Part D: Table constructors as an iterator body
  - Part E: A table on a row
  - Part F: A typed BLANK beside a second branch
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_MISC3_PATH = ROOT / "tests" / "fixtures_misc3_alt.json"
FIXTURES_TYPED3_PATH = ROOT / "tests" / "fixtures_typed3_review_alt.json"
FIXTURES_TYPED5_PATH = ROOT / "tests" / "fixtures_typed5_review_alt.json"
FIXTURES_STRICT6_PATH = ROOT / "tests" / "fixtures_strict6_review_alt.json"


def _local_on(rows: list[tuple[str, ...] | list[str]], expression: str) -> str:
    saved = (dax.ROWS, dax.LOCAL_ROWS)
    dax.ROWS = [tuple(r) for r in rows]
    dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in rows]
    try:
        return dax.local(expression)
    finally:
        dax.ROWS, dax.LOCAL_ROWS = saved


def _rows_from(path: Path, table: str) -> list[list[str]]:
    return json.loads(path.read_text())["datasets"][table]["rows"]


PART_A_EXPRESSIONS: list[tuple[str, str]] = [
    ('CALCULATE(COUNTROWS(Facts),VAR t=TREATAS({"West"},Facts[Region]) RETURN t)', "2"),
    ('CALCULATE(COUNTROWS(Facts),VAR b=Facts[Quantity]>2 RETURN b)', "3"),
    ('CALCULATE(COUNTROWS(Facts),VAR b=Facts[Region]="West" RETURN b)', "2"),
    ('CALCULATE(COUNTROWS(Facts),VAR b=ISBLANK(Facts[Note]) RETURN b)', "2"),
    ('CALCULATE(SUM(Facts[Quantity]),VAR t=TREATAS({"West"},Facts[Region]) RETURN t)', "3"),
    ('CALCULATE(SUM(Facts[Quantity]),VAR b=Facts[Quantity]>2 RETURN b)', "12"),
    ('CALCULATE(SUM(Facts[Quantity]),VAR b=Facts[Region]="West" RETURN b)', "3"),
    ('CALCULATE(SUM(Facts[Quantity]),VAR b=ISBLANK(Facts[Note]) RETURN b)', "8"),
    ('CALCULATE(COUNTROWS(Facts),VAR t=TREATAS({"West"},Facts[Region]) RETURN t,Facts[Region]="West")', "2"),
    ('CALCULATE(COUNTROWS(Facts),VAR b=Facts[Quantity]>2 RETURN b,Facts[Region]="West")', "1"),
    ('CALCULATE(COUNTROWS(Facts),VAR b=Facts[Region]="West" RETURN b,Facts[Region]="West")', "2"),
    ('CALCULATE(COUNTROWS(Facts),VAR b=ISBLANK(Facts[Note]) RETURN b,Facts[Region]="West")', "1"),
    ('CALCULATE(COUNTROWS(Facts),Facts[Quantity]>1,VAR t=TREATAS({"West"},Facts[Region]) RETURN t)', "1"),
    ('CALCULATE(COUNTROWS(Facts),Facts[Quantity]>1,VAR b=Facts[Quantity]>2 RETURN b)', "3"),
    ('CALCULATE(COUNTROWS(Facts),Facts[Quantity]>1,VAR b=Facts[Region]="West" RETURN b)', "1"),
    ('CALCULATE(COUNTROWS(Facts),Facts[Quantity]>1,VAR b=ISBLANK(Facts[Note]) RETURN b)', "2"),
    ('CALCULATETABLE(ROW("n",COUNTROWS(Facts)),VAR t=TREATAS({"West"},Facts[Region]) RETURN t)', "2"),
    ('CALCULATETABLE(ROW("n",COUNTROWS(Facts)),VAR b=Facts[Quantity]>2 RETURN b)', "3"),
    ('CALCULATETABLE(ROW("n",COUNTROWS(Facts)),VAR b=Facts[Region]="West" RETURN b)', "2"),
    ('CALCULATETABLE(ROW("n",COUNTROWS(Facts)),VAR b=ISBLANK(Facts[Note]) RETURN b)', "2"),
    ('COUNTROWS(CALCULATETABLE(Facts,VAR t=TREATAS({"West"},Facts[Region]) RETURN t))', "2"),
    ('COUNTROWS(CALCULATETABLE(Facts,VAR b=Facts[Quantity]>2 RETURN b))', "3"),
    ('COUNTROWS(CALCULATETABLE(Facts,VAR b=Facts[Region]="West" RETURN b))', "2"),
    ('COUNTROWS(CALCULATETABLE(Facts,VAR b=ISBLANK(Facts[Note]) RETURN b))', "2"),
    ('CALCULATE(COUNTROWS(Facts),KEEPFILTERS(VAR t=TREATAS({"West"},Facts[Region]) RETURN t))', "2"),
    ('CALCULATE(COUNTROWS(Facts),KEEPFILTERS(VAR b=Facts[Quantity]>2 RETURN b))', "3"),
    ('CALCULATE(COUNTROWS(Facts),KEEPFILTERS(VAR b=Facts[Region]="West" RETURN b))', "2"),
    ('CALCULATE(COUNTROWS(Facts),KEEPFILTERS(VAR b=ISBLANK(Facts[Note]) RETURN b))', "2"),
    ('CALCULATE(CALCULATE(COUNTROWS(Facts),VAR t=TREATAS({"West"},Facts[Region]) RETURN t),Facts[Region]="East")', "2"),
    ('CALCULATE(CALCULATE(COUNTROWS(Facts),VAR b=Facts[Quantity]>2 RETURN b),Facts[Region]="East")', "1"),
    ('CALCULATE(CALCULATE(COUNTROWS(Facts),VAR b=Facts[Region]="West" RETURN b),Facts[Region]="East")', "2"),
    ('CALCULATE(CALCULATE(COUNTROWS(Facts),VAR b=ISBLANK(Facts[Note]) RETURN b),Facts[Region]="East")', "1"),
    ('SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),VAR t=TREATAS({"West"},Facts[Region]) RETURN t))', "6"),
    ('SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),VAR b=Facts[Quantity]>2 RETURN b))', "3"),
    ('SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),VAR b=Facts[Region]="West" RETURN b))', "6"),
    ('SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),VAR b=ISBLANK(Facts[Note]) RETURN b))', "2"),
    ('SUMX(Facts,CALCULATE(COUNTROWS(Facts),VAR t=TREATAS({"West"},Facts[Region]) RETURN t))', "2"),
    ('SUMX(Facts,CALCULATE(COUNTROWS(Facts),VAR b=Facts[Quantity]>2 RETURN b))', "3"),
    ('SUMX(Facts,CALCULATE(COUNTROWS(Facts),VAR b=Facts[Region]="West" RETURN b))', "2"),
    ('SUMX(Facts,CALCULATE(COUNTROWS(Facts),VAR b=ISBLANK(Facts[Note]) RETURN b))', "2"),
]


class PartAVarCalculateFilterTest(unittest.TestCase):
    """Part A: a VAR holding a True/False expression or a TREATAS table is a CALCULATE filter."""

    def test_standard_facts_table(self) -> None:
        for expression, expected in PART_A_EXPRESSIONS:
            self.assertEqual(expected, dax.local(expression), expression)

    def test_alternate_tables_follow_the_same_rule(self) -> None:
        tables = [
            ("misc3/A", _rows_from(FIXTURES_MISC3_PATH, "A")),
            ("misc3/B", _rows_from(FIXTURES_MISC3_PATH, "B")),
            ("typed3/N", _rows_from(FIXTURES_TYPED3_PATH, "N")),
            ("typed3/A", _rows_from(FIXTURES_TYPED3_PATH, "A")),
            ("typed3/B", _rows_from(FIXTURES_TYPED3_PATH, "B")),
            ("typed5/B", _rows_from(FIXTURES_TYPED5_PATH, "B")),
            ("strict6/B", _rows_from(FIXTURES_STRICT6_PATH, "B")),
        ]
        pairs = [
            (
                'CALCULATE(COUNTROWS(Facts),VAR t=TREATAS({"West"},Facts[Region]) RETURN t)',
                'CALCULATE(COUNTROWS(Facts),TREATAS({"West"},Facts[Region]))',
            ),
            (
                'CALCULATE(COUNTROWS(Facts),VAR b=Facts[Quantity]>2 RETURN b)',
                'CALCULATE(COUNTROWS(Facts),Facts[Quantity]>2)',
            ),
            (
                'CALCULATE(COUNTROWS(Facts),VAR b=Facts[Region]="West" RETURN b)',
                'CALCULATE(COUNTROWS(Facts),Facts[Region]="West")',
            ),
            (
                'CALCULATE(COUNTROWS(Facts),VAR b=ISBLANK(Facts[Note]) RETURN b)',
                'CALCULATE(COUNTROWS(Facts),ISBLANK(Facts[Note]))',
            ),
            (
                'CALCULATE(SUM(Facts[Quantity]),VAR b=Facts[Quantity]>2 RETURN b)',
                'CALCULATE(SUM(Facts[Quantity]),Facts[Quantity]>2)',
            ),
            (
                'CALCULATE(SUM(Facts[Quantity]),VAR b=ISBLANK(Facts[Note]) RETURN b)',
                'CALCULATE(SUM(Facts[Quantity]),ISBLANK(Facts[Note]))',
            ),
            (
                'SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),VAR b=Facts[Region]="West" RETURN b))',
                'SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),Facts[Region]="West"))',
            ),
            (
                'SUMX(Facts,CALCULATE(COUNTROWS(Facts),VAR b=ISBLANK(Facts[Note]) RETURN b))',
                'SUMX(Facts,CALCULATE(COUNTROWS(Facts),ISBLANK(Facts[Note])))',
            ),
        ]
        for name, rows in tables:
            for with_var, inline in pairs:
                self.assertEqual(_local_on(rows, inline), _local_on(rows, with_var), f"{name}: {with_var}")

    def test_aggregate_inside_a_var_filter_stays_refused(self) -> None:
        for expression in (
            "CALCULATE(COUNTROWS(Facts),VAR b=MAX(Facts[Quantity])>2 RETURN b)",
            "CALCULATE(COUNTROWS(Facts),VAR b=SUM(Facts[Quantity])>2 RETURN b)",
        ):
            result = dax.local(expression)
            self.assertTrue(result.startswith("LOCAL-REJECT"), expression)
            self.assertIn("has been used in a True/False expression that contains a variable definition", result, expression)


PART_C_CONSTRUCTOR_BODIES = [
    "1-DATE(2020,1,1)",
    "CURRENCY(1)+DATE(2020,1,1)",
    "DATE(2020,1,1)+CURRENCY(1)",
]
PART_C_CONSTRUCTOR_VARIANTS = [
    ("{body}", True),
    ("{body},1", True),
    ("{body},1.5", True),
    ("{body},CURRENCY(2)", True),
]
PART_C_COALESCE = [
    ('COALESCE(AVERAGEX(Facts,DATE(2020,1,1)+Facts[Quantity]),"a")', True),
    ('COALESCE(AVERAGEX(Facts,DATE(2020,1,1)),"a")', True),
    ('COALESCE(AVERAGEX(Facts,MAX(Facts[Quantity])),"a")', True),
    ('COALESCE(AVERAGEX(Facts,CURRENCY(1)),"a")', False),
    ('COALESCE(AVERAGEX(Facts,BLANK()),"a")', False),
    ('COALESCE(AVERAGEX(Facts,Facts[Quantity]),"a")', True),
    ('COALESCE(AVERAGEX(Facts,IF(Facts[Quantity]>1,DATE(2020,1,1))),"a")', True),
]


class PartCDateArithmeticTypesTest(unittest.TestCase):
    """Part C: a number minus a DATE is a Double; CURRENCY plus DATE is a datetime; a number beside a datetime is a Double."""

    def test_constructor_items(self) -> None:
        for body in PART_C_CONSTRUCTOR_BODIES:
            for template, _ in PART_C_CONSTRUCTOR_VARIANTS:
                table = "{" + template.format(body=body) + "}"
                expression = f"MAXX({table},[Value])"
                expected_double = not (body.startswith("CURRENCY") or body.startswith("DATE")) or "," in template
                self.assertEqual(str(expected_double), dax.local(f"ISDOUBLE({expression})"), expression)
                self.assertEqual("False", dax.local(f"ISINT64({expression})"), expression)
                self.assertEqual("False", dax.local(f"ISCURRENCY({expression})"), expression)
                self.assertEqual("False", dax.local(f"ISDECIMAL({expression})"), expression)

    def test_coalesce_beside_a_text_stays_refused(self) -> None:
        """Its type is the runtime value's, and an average over no rows would be the text: no rule on types alone."""
        for body, _expected_double in PART_C_COALESCE:
            self.assertIn("Cannot determine static type", dax.local(f"ISDOUBLE(MAXX(Facts,{body}))"), body)

    def test_a_true_false_beside_a_date_is_not_a_number(self) -> None:
        self.assertEqual("False", dax.local("ISDOUBLE(MAXX({CURRENCY(1)+DATE(2020,1,1),TRUE()},[Value]))"))
        self.assertEqual("False", dax.local("ISINT64(MAXX({DATE(2020,1,1)-1,TRUE()},[Value]))"))


PART_D_EMPTY_BODIES = ('{"a","b"}', '{"a"&"b","c"&"d"}', '{1,2}', '{1,"a"}', '{"a",1}', '{BLANK(),"a"}', '{UPPER("a"),UPPER("b")}')


class PartDTableConstructorBodyTest(unittest.TestCase):
    """Part D: a one-row constructor on a table with rows is its value; an iterator over an empty table does not check its body."""

    def test_one_row_constructor_on_a_table_with_rows(self) -> None:
        self.assertEqual("1", dax.local('MAXX(Facts,EVALUATEANDLOG({1},"a"))'))

    def test_empty_table_does_not_check_the_body(self) -> None:
        for body in PART_D_EMPTY_BODIES:
            for function in ("MAXX", "COUNTX"):
                expression = f"{function}(FILTER(Facts,FALSE()),{body})"
                self.assertEqual("BLANK", dax.local(expression), expression)

    def test_many_row_constructor_on_a_table_with_rows_stays_refused(self) -> None:
        for expression in (
            'MAXX(Facts,{UPPER("a"),UPPER("b")})',
            "MAXX(Facts,{1,2})",
            'COUNTX(Facts,{"a","b"})',
        ):
            result = dax.local(expression)
            self.assertTrue(result.startswith("LOCAL-REJECT"), expression)

    def test_one_row_constructor_on_alternate_tables(self) -> None:
        tables = [
            ("misc3/A", _rows_from(FIXTURES_MISC3_PATH, "A")),
            ("misc3/B", _rows_from(FIXTURES_MISC3_PATH, "B")),
            ("typed3/N", _rows_from(FIXTURES_TYPED3_PATH, "N")),
            ("typed3/A", _rows_from(FIXTURES_TYPED3_PATH, "A")),
            ("typed3/B", _rows_from(FIXTURES_TYPED3_PATH, "B")),
            ("typed5/B", _rows_from(FIXTURES_TYPED5_PATH, "B")),
            ("strict6/B", _rows_from(FIXTURES_STRICT6_PATH, "B")),
        ]
        for name, rows in tables:
            self.assertEqual("1", _local_on(rows, "MAXX(Facts,{1})"), name)
            self.assertEqual("BLANK", _local_on(rows, "MAXX(FILTER(Facts,FALSE()),{1,2})"), name)


class PartFTypedBlankBesideSecondBranchTest(unittest.TestCase):
    """Part F: a logical operator's BLANK beside a Boolean branch stays BLANK in an added column."""

    def test_added_column(self) -> None:
        self.assertEqual("BLANK", dax.local('COUNTAX(ADDCOLUMNS(Facts,"q",IF(TRUE(),2.5&&"",FALSE())),[q])'))
        self.assertEqual("6", dax.local('SUMX(ADDCOLUMNS(Facts,"q",IF(TRUE(),2.5&&"",FALSE())),IF(ISBLANK([q]),1,2))'))
        self.assertEqual("BLANK", dax.local('IF(TRUE(),2.5&&"")'))
        self.assertEqual("BLANK", dax.local('CALCULATE(IF(TRUE(),2.5&&"",FALSE()))'))

    def test_a_reader_of_its_type_sees_false(self) -> None:
        self.assertEqual("False", dax.local('ISBLANK(IF(TRUE(),2.5&&"",FALSE()))'))
        self.assertEqual("True", dax.local('ISLOGICAL(IF(TRUE(),2.5&&"",1>2))'))
        self.assertEqual("1", dax.local('COUNTAX({IF(TRUE(),2.5&&"",FALSE())},[Value])'))
        self.assertEqual("z", dax.local('(IF(TRUE(),2.5&&"",1>2))&"z"'))
        self.assertEqual("False", dax.local('VAR v=IF(TRUE(),2.5&&"",FALSE()) RETURN ISBLANK(v)'))

    def test_alternate_tables(self) -> None:
        tables = [
            ("misc3/A", _rows_from(FIXTURES_MISC3_PATH, "A")),
            ("misc3/B", _rows_from(FIXTURES_MISC3_PATH, "B")),
            ("typed3/N", _rows_from(FIXTURES_TYPED3_PATH, "N")),
            ("typed3/A", _rows_from(FIXTURES_TYPED3_PATH, "A")),
            ("typed3/B", _rows_from(FIXTURES_TYPED3_PATH, "B")),
            ("typed5/B", _rows_from(FIXTURES_TYPED5_PATH, "B")),
            ("strict6/B", _rows_from(FIXTURES_STRICT6_PATH, "B")),
        ]
        for name, rows in tables:
            self.assertEqual("BLANK", _local_on(rows, 'COUNTAX(ADDCOLUMNS(Facts,"q",IF(TRUE(),2.5&&"",FALSE())),[q])'), name)
            self.assertEqual(str(len(rows)), _local_on(rows, 'SUMX(ADDCOLUMNS(Facts,"q",IF(TRUE(),2.5&&"",FALSE())),IF(ISBLANK([q]),1,2))'), name)


class PartECalculateTableOnRowTest(unittest.TestCase):
    """Part E: a table from CALCULATE(DISTINCT/VALUES(...)) on a row."""

    def test_standard_facts_table(self) -> None:
        cases = [
            ('MAXX(ADDCOLUMNS(Facts,"q",CALCULATE(DISTINCT(Facts[Region]),Facts[Region]="East")),[q])', "East"),
            ('COUNTROWS(FILTER(Facts,CALCULATE(DISTINCT(Facts[Sales]),Facts[Region]="East")))', "3"),
            ('SUMX(Facts,IF(CALCULATE(VALUES(Facts[Region]),Facts[Region]="East")="East",1,0))', "3"),
            ('COUNTROWS(FILTER(ADDCOLUMNS(Facts,"z",1),CALCULATE(DISTINCT(Facts[Sales]),Facts[Region]="East")))', "3"),
            ('CONCATENATEX(ALL(Facts),1,"|",CALCULATE(VALUES(Facts[Note]),Facts[Region]="East"))', "1|1|1|1|1|1"),
            ('SUMX(ADDCOLUMNS(FILTER(Facts,Facts[Quantity]>2),"q",CALCULATE(VALUES(Facts[Quantity]),Facts[Region]="East")),1)', "3"),
            ('COUNTROWS(TOPN(1,FILTER(Facts,Facts[Quantity]>2),CALCULATE(DISTINCT(Facts[Sales]),Facts[Region]="East")))', "1"),
            ('SUMX(ADDCOLUMNS(Facts,"q",CALCULATE(VALUES(Facts[Note]),Facts[Region]="East")),1)', "6"),
            ('COUNTROWS(FILTER(FILTER(Facts,Facts[Region]="East"),CALCULATE(DISTINCT(Facts[Region]),Facts[Region]="East")="East"))', "3"),
            ('SUMX(ADDCOLUMNS(ADDCOLUMNS(Facts,"z",1),"q",CALCULATE(DISTINCT(Facts[Sales]),Facts[Region]="East")),1)', "6"),
            ('SUMX(ADDCOLUMNS(FILTER(Facts,Facts[Quantity]>2),"q",CALCULATE(VALUES(Facts[Region]),Facts[Region]="East")),1)', "3"),
            ('MAXX(ADDCOLUMNS(Facts,"q",CALCULATE(VALUES(Facts[Region]),Facts[Region]="East")),[q])', "East"),
            ('MAXX(ADDCOLUMNS(CALCULATETABLE(Facts,Facts[Region]="East"),"q",CALCULATE(VALUES(Facts[Quantity]),Facts[Region]="East")),[q])', "5"),
            ('CONCATENATEX(SELECTCOLUMNS(Facts,"z",Facts[Quantity]),1,"|",CALCULATE(DISTINCT(Facts[Sales]),Facts[Region]="East"))', "1|1|1|1|1|1"),
            ('COUNTROWS(ADDCOLUMNS(FILTER(Facts,Facts[Region]="East"),"q",CALCULATE(VALUES(Facts[Region]),Facts[Region]="East")))', "3"),
            ('SUMX(ALL(Facts),IF(CALCULATE(DISTINCT(Facts[Region]),Facts[Region]="East")="East",1,0))', "3"),
            ('COUNTROWS(FILTER(Facts,CALCULATE(DISTINCT(Facts[Region]),Facts[Region]="East")="East"))', "3"),
            ('SUMX(ADDCOLUMNS(FILTER(Facts,Facts[Quantity]>2),"q",CALCULATE(DISTINCT(Facts[Region]),Facts[Region]="East")),1)', "3"),
            ('SUMX(ADDCOLUMNS(TOPN(2,Facts,Facts[Quantity]),"q",CALCULATE(VALUES(Facts[Quantity]),Facts[Region]="East")),1)', "2"),
            ('COUNTROWS(TOPN(1,Facts,CALCULATE(VALUES(Facts[Region]),Facts[Region]="East")))', "3"),
            ('CONCATENATEX(FILTER(Facts,Facts[Region]="East"),1,"|",CALCULATE(VALUES(Facts[Quantity]),Facts[Region]="East"))', "1|1|1"),
        ]
        for expression, expected in cases:
            self.assertEqual(expected, dax.local(expression), expression)

    def test_medianx_over_several_rows_stays_refused(self) -> None:
        answer = dax.local('MEDIANX(ADDCOLUMNS(Facts,"z",1),CALCULATE(DISTINCT(Facts[Sales]),Facts[Region]="East"))')
        self.assertIn("CALCULATE of a table on a row", answer)

    def test_alternate_tables_follow_the_same_rule(self) -> None:
        tables = [
            ("misc3/A", _rows_from(FIXTURES_MISC3_PATH, "A")),
            ("misc3/B", _rows_from(FIXTURES_MISC3_PATH, "B")),
            ("typed3/N", _rows_from(FIXTURES_TYPED3_PATH, "N")),
            ("typed3/A", _rows_from(FIXTURES_TYPED3_PATH, "A")),
            ("typed3/B", _rows_from(FIXTURES_TYPED3_PATH, "B")),
            ("typed5/B", _rows_from(FIXTURES_TYPED5_PATH, "B")),
            ("strict6/B", _rows_from(FIXTURES_STRICT6_PATH, "B")),
        ]
        pairs = [
            ('MAXX(ADDCOLUMNS(Facts,"q",CALCULATE(VALUES(Facts[Region]),Facts[Region]="East")),[q])', 'MAXX(FILTER(Facts,Facts[Region]="East"),Facts[Region])'),
            ('COUNTROWS(FILTER(Facts,CALCULATE(DISTINCT(Facts[Sales]),Facts[Region]="East")))', 'COUNTROWS(FILTER(Facts,Facts[Region]="East"))'),
            ('SUMX(Facts,IF(CALCULATE(VALUES(Facts[Region]),Facts[Region]="East")="East",1,0))', 'SUMX(Facts,IF(Facts[Region]="East",1,0))'),
            ('SUMX(ADDCOLUMNS(Facts,"q",CALCULATE(VALUES(Facts[Note]),Facts[Region]="East")),1)', 'COUNTROWS(Facts)'),
            ('CONCATENATEX(ALL(Facts),1,"|",CALCULATE(VALUES(Facts[Note]),Facts[Region]="East"))', 'CONCATENATEX(ALL(Facts),1,"|")'),
        ]
        for name, rows in tables:
            for expression, oracle in pairs:
                self.assertEqual(_local_on(rows, oracle), _local_on(rows, expression), f"{name}: {expression}")
            east = sum(1 for row in rows if row[2] == "East")
            expected = str(east if east else len(rows))
            self.assertEqual(
                expected,
                _local_on(rows, 'COUNTROWS(TOPN(1,Facts,CALCULATE(VALUES(Facts[Region]),Facts[Region]="East")))'),
                f"{name}: TOPN ties",
            )


class PartBEvaluateAndLogModifierTest(unittest.TestCase):
    """Part B: EVALUATEANDLOG returns its argument, so a wrapped filter modifier acts exactly as the bare one."""

    def test_standard_facts_table(self) -> None:
        pairs = [
            ("CALCULATE(COUNTROWS(Facts),ALLEXCEPT(Facts,Facts[Region]))", 'CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(ALLEXCEPT(Facts,Facts[Region]),"log"))', "6"),
            ("CALCULATE(SUM(Facts[Quantity]),ALLEXCEPT(Facts,Facts[Region]))", 'CALCULATE(SUM(Facts[Quantity]),EVALUATEANDLOG(ALLEXCEPT(Facts,Facts[Region]),"log"))', "15"),
            ('CALCULATE(COUNTROWS(Facts),Facts[Region]="East",ALLEXCEPT(Facts,Facts[Region]))', 'CALCULATE(COUNTROWS(Facts),Facts[Region]="East",EVALUATEANDLOG(ALLEXCEPT(Facts,Facts[Region]),"log"))', "3"),
            ('CALCULATE(SUM(Facts[Quantity]),Facts[Region]="East",ALLEXCEPT(Facts,Facts[Region]))', 'CALCULATE(SUM(Facts[Quantity]),Facts[Region]="East",EVALUATEANDLOG(ALLEXCEPT(Facts,Facts[Region]),"log"))', "8"),
            ("CALCULATE(COUNTROWS(Facts),Facts[Quantity]>2,ALLEXCEPT(Facts,Facts[Region]))", 'CALCULATE(COUNTROWS(Facts),Facts[Quantity]>2,EVALUATEANDLOG(ALLEXCEPT(Facts,Facts[Region]),"log"))', "3"),
            ("CALCULATE(SUM(Facts[Quantity]),Facts[Quantity]>2,ALLEXCEPT(Facts,Facts[Region]))", 'CALCULATE(SUM(Facts[Quantity]),Facts[Quantity]>2,EVALUATEANDLOG(ALLEXCEPT(Facts,Facts[Region]),"log"))', "12"),
            ("COUNTROWS(CALCULATETABLE(Facts,ALLEXCEPT(Facts,Facts[Region])))", 'COUNTROWS(CALCULATETABLE(Facts,EVALUATEANDLOG(ALLEXCEPT(Facts,Facts[Region]),"log")))', "6"),
            ("CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts))", 'CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(ALLSELECTED(Facts),"log"))', "6"),
            ("CALCULATE(SUM(Facts[Quantity]),ALLSELECTED(Facts))", 'CALCULATE(SUM(Facts[Quantity]),EVALUATEANDLOG(ALLSELECTED(Facts),"log"))', "15"),
            ('CALCULATE(COUNTROWS(Facts),Facts[Region]="East",ALLSELECTED(Facts))', 'CALCULATE(COUNTROWS(Facts),Facts[Region]="East",EVALUATEANDLOG(ALLSELECTED(Facts),"log"))', "3"),
            ('CALCULATE(SUM(Facts[Quantity]),Facts[Region]="East",ALLSELECTED(Facts))', 'CALCULATE(SUM(Facts[Quantity]),Facts[Region]="East",EVALUATEANDLOG(ALLSELECTED(Facts),"log"))', "8"),
            ("CALCULATE(COUNTROWS(Facts),Facts[Quantity]>2,ALLSELECTED(Facts))", 'CALCULATE(COUNTROWS(Facts),Facts[Quantity]>2,EVALUATEANDLOG(ALLSELECTED(Facts),"log"))', "3"),
            ("CALCULATE(SUM(Facts[Quantity]),Facts[Quantity]>2,ALLSELECTED(Facts))", 'CALCULATE(SUM(Facts[Quantity]),Facts[Quantity]>2,EVALUATEANDLOG(ALLSELECTED(Facts),"log"))', "12"),
            ("COUNTROWS(CALCULATETABLE(Facts,ALLSELECTED(Facts)))", 'COUNTROWS(CALCULATETABLE(Facts,EVALUATEANDLOG(ALLSELECTED(Facts),"log")))', "6"),
            ("CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Region]))", 'CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(ALLSELECTED(Facts[Region]),"log"))', "6"),
            ("CALCULATE(SUM(Facts[Quantity]),ALLSELECTED(Facts[Region]))", 'CALCULATE(SUM(Facts[Quantity]),EVALUATEANDLOG(ALLSELECTED(Facts[Region]),"log"))', "15"),
            ('CALCULATE(COUNTROWS(Facts),Facts[Region]="East",ALLSELECTED(Facts[Region]))', 'CALCULATE(COUNTROWS(Facts),Facts[Region]="East",EVALUATEANDLOG(ALLSELECTED(Facts[Region]),"log"))', "3"),
            ('CALCULATE(SUM(Facts[Quantity]),Facts[Region]="East",ALLSELECTED(Facts[Region]))', 'CALCULATE(SUM(Facts[Quantity]),Facts[Region]="East",EVALUATEANDLOG(ALLSELECTED(Facts[Region]),"log"))', "8"),
            ("CALCULATE(COUNTROWS(Facts),Facts[Quantity]>2,ALLSELECTED(Facts[Region]))", 'CALCULATE(COUNTROWS(Facts),Facts[Quantity]>2,EVALUATEANDLOG(ALLSELECTED(Facts[Region]),"log"))', "3"),
            ("CALCULATE(SUM(Facts[Quantity]),Facts[Quantity]>2,ALLSELECTED(Facts[Region]))", 'CALCULATE(SUM(Facts[Quantity]),Facts[Quantity]>2,EVALUATEANDLOG(ALLSELECTED(Facts[Region]),"log"))', "12"),
            ("COUNTROWS(CALCULATETABLE(Facts,ALLSELECTED(Facts[Region])))", 'COUNTROWS(CALCULATETABLE(Facts,EVALUATEANDLOG(ALLSELECTED(Facts[Region]),"log")))', "6"),
        ]
        for bare, wrapped, expected in pairs:
            self.assertEqual(expected, dax.local(bare), bare)
            self.assertEqual(dax.local(bare), dax.local(wrapped), wrapped)

    def test_alternate_tables_follow_the_same_rule(self) -> None:
        tables = [
            ("misc3/A", _rows_from(FIXTURES_MISC3_PATH, "A")),
            ("misc3/B", _rows_from(FIXTURES_MISC3_PATH, "B")),
            ("typed3/N", _rows_from(FIXTURES_TYPED3_PATH, "N")),
            ("typed3/A", _rows_from(FIXTURES_TYPED3_PATH, "A")),
            ("typed3/B", _rows_from(FIXTURES_TYPED3_PATH, "B")),
            ("typed5/B", _rows_from(FIXTURES_TYPED5_PATH, "B")),
            ("strict6/B", _rows_from(FIXTURES_STRICT6_PATH, "B")),
        ]
        pairs = [
            ("CALCULATE(COUNTROWS(Facts),ALLEXCEPT(Facts,Facts[Region]))", 'CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(ALLEXCEPT(Facts,Facts[Region]),"log"))'),
            ("CALCULATE(SUM(Facts[Quantity]),ALLEXCEPT(Facts,Facts[Region]))", 'CALCULATE(SUM(Facts[Quantity]),EVALUATEANDLOG(ALLEXCEPT(Facts,Facts[Region]),"log"))'),
            ('CALCULATE(COUNTROWS(Facts),Facts[Region]="East",ALLEXCEPT(Facts,Facts[Region]))', 'CALCULATE(COUNTROWS(Facts),Facts[Region]="East",EVALUATEANDLOG(ALLEXCEPT(Facts,Facts[Region]),"log"))'),
            ("CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts))", 'CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(ALLSELECTED(Facts),"log"))'),
            ("CALCULATE(COUNTROWS(Facts),ALLSELECTED(Facts[Region]))", 'CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(ALLSELECTED(Facts[Region]),"log"))'),
            ("COUNTROWS(CALCULATETABLE(Facts,ALLSELECTED(Facts)))", 'COUNTROWS(CALCULATETABLE(Facts,EVALUATEANDLOG(ALLSELECTED(Facts),"log")))'),
        ]
        for name, rows in tables:
            for bare, wrapped in pairs:
                self.assertEqual(_local_on(rows, bare), _local_on(rows, wrapped), f"{name}: {wrapped}")

    def test_other_modifiers_stay_refused(self) -> None:
        for expression in (
            "CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(REMOVEFILTERS(Facts[Region]),\"log\"))",
            "CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(ALLCROSSFILTERED(Facts),\"log\"))",
            "CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(Facts[Region] IN {\"East\"},\"log\"))",
        ):
            result = dax.local(expression)
            self.assertTrue(result.startswith("LOCAL-REJECT"), expression)


if __name__ == "__main__":
    unittest.main()


class ReviewFindingsTest(unittest.TestCase):
    """Task 17 review, answers from live Power BI."""

    def test_allselected_without_arguments_is_not_a_table(self) -> None:
        self.assertTrue(dax.local("CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(ALLSELECTED()))").startswith("LOCAL-REJECT"))

    def test_keepfilters_around_a_logged_modifier_is_refused(self) -> None:
        self.assertTrue(dax.local("SUMX(Facts,CALCULATE(COUNTROWS(Facts),KEEPFILTERS(EVALUATEANDLOG(ALLSELECTED(Facts)))))").startswith("LOCAL-REJECT"))

    def test_a_date_constructor_over_no_rows_keeps_its_type(self) -> None:
        self.assertTrue(dax.local("MAXX(FILTER(Facts,FALSE()),{DATE(2020,1,1)})+1").startswith("LOCAL-REJECT"))

    def test_a_table_on_a_row_stays_refused_where_order_or_several_values_decide(self) -> None:
        self.assertTrue(dax.local('MEDIANX(ADDCOLUMNS(Facts,"q",CALCULATE(VALUES(Facts[Quantity]),Facts[Quantity]=3)),[q])').startswith("LOCAL-REJECT"))
        self.assertTrue(dax.local('CONCATENATEX(Facts,CALCULATE(VALUES(Facts[Region])),"|")').startswith("LOCAL-REJECT"))

    def test_switch_and_iferror_give_a_plain_blank(self) -> None:
        self.assertEqual("True", dax.local('ISBLANK(SWITCH(TRUE(),TRUE(),2.5&&"",FALSE()))'))
        self.assertEqual("False", dax.local('ISLOGICAL(IFERROR(2.5&&"",FALSE()))'))
        self.assertEqual("BLANK", dax.local('COUNTAX({SWITCH(1,2,FALSE(),2.5&&"")},[Value])'))
        self.assertEqual("z", dax.local('(IF(TRUE(),IF(TRUE(),2.5&&"",FALSE()),FALSE()))&"z"'))

    def test_a_date_beside_a_number_is_a_number(self) -> None:
        self.assertEqual("43831", dax.local("MAXX({DATE(2020,1,1),1.5},[Value])"))
        self.assertEqual("43831", dax.local("MAXX({TRUE(),DATE(2020,1,1),1.5},[Value])"))
        self.assertEqual("True", dax.local("ISDOUBLE(MAXX({TRUE(),DATE(2020,1,1),1},[Value]))"))

    def test_a_constructor_over_no_rows_keeps_its_type(self) -> None:
        self.assertIn("Boolean", dax.local("COUNTX(FILTER(Facts,FALSE()),{TRUE(),FALSE()})"))
        self.assertTrue(dax.local("MAXX(FILTER(Facts,FALSE()),{DATE(2020,1,1),DATE(2021,1,1)})+1").startswith("LOCAL-REJECT"))

    def test_a_variable_reading_a_column_beside_a_table_filter(self) -> None:
        self.assertIn("single value", dax.local('CALCULATE(COUNTROWS(Facts),VAR b=Facts[Quantity]>2 RETURN TREATAS({"West"},Facts[Region]))'))

    def test_switch_and_iferror_columns_are_true_false(self) -> None:
        self.assertIn("Boolean", dax.local('COUNTX(ADDCOLUMNS(Facts,"q",SWITCH(TRUE(),FALSE(),FALSE(),2.5&&"")),[q])'))
        self.assertTrue(dax.local('COUNTAX({SWITCH(TRUE(),TRUE(),2.5&&"",Facts[Quantity]>2)},[Value])').startswith("LOCAL-REJECT"))

    def test_only_a_plain_if_beside_a_direct_true_false_reads_false(self) -> None:
        self.assertEqual("True", dax.local('ISBLANK(IF.EAGER(TRUE(),2.5&&"",1>2))'))
        self.assertEqual("BLANK", dax.local('COUNTAX({IF.EAGER(TRUE(),2.5&&"",FALSE())},[Value])'))
        self.assertEqual("True", dax.local('ISBLANK(IF(TRUE(),2.5&&"",VAR z=FALSE() RETURN z))'))
        self.assertEqual("False", dax.local('ISLOGICAL(IF(1=1,2.5&&"",IF(FALSE(),TRUE())))'))
        self.assertEqual("False", dax.local('ISBLANK(IF(1=1,2.5&&"",1>2))'))

