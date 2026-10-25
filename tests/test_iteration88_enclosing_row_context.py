"""Iteration 88: nested iterators read columns from the enclosing row contexts, EARLIER / EARLIEST are positional, renamed SELECTCOLUMNS columns are
not table columns, TOPN breaks ties like Power BI (compared with Power BI Desktop 2.157.879.0; about 9,000 + 3,000 fresh probes, 0 differences).

Rule:
* A column the innermost row context does not hold is read from the nearest enclosing row context that does (SUMX(Facts, SUMX(ROW("a",1), Facts[Quantity]))
  is the sum of Quantity per outer row, 15); a table column is not found among the renamed columns of SELECTCOLUMNS (an error).
* EARLIER(col, n) drops the n innermost row contexts and reads the nearest of the others that holds the column; EARLIEST reads the outermost one;
  too few row contexts, or none that holds the column, is an error, also in an iteration that has no rows.
* The body of an iteration without rows is still validated: a column of a table that no nested iteration and no enclosing row context holds is an error.
* The walk order of CONCATENATEX / TOPN ties over expressions that depend on an enclosing row context is not modelled: refused unless the ORDER BY is total.
The expected values are live Power BI answers ("ERR" = Power BI raised an error; the local engine must refuse or raise)."""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status


POWER_BI = [
    ('SUMX(Facts,SUMX(ROW("a",1),Facts[Quantity]))', '15'),
    ('SUMX(Facts,SUMX(VALUES(Facts[Region]),Facts[Quantity]))', '45'),
    ('SUMX(Facts,SUMX(GENERATESERIES(1,2),Facts[Quantity]))', '30'),
    ('SUMX(Facts,SUMX(SELECTCOLUMNS(Facts,"x",Facts[Region]),Facts[Quantity]))', '90'),
    ('SUMX(Facts,SUMX(DISTINCT(Facts[Region]),Facts[Quantity]))', '45'),
    ('SUMX(Facts,SUMX(SUMMARIZE(Facts,Facts[Region]),Facts[Quantity]))', '45'),
    ('SUMX(Facts,SUMX(ADDCOLUMNS(VALUES(Facts[Region]),"k",1),Facts[Quantity]))', '45'),
    ('SUMX(Facts,SUMX(VALUES(Facts[Region]),IF(Facts[Quantity]>2,1,0)))', '9'),
    ('SUMX(VALUES(Facts[Region]),SUMX(ROW("a",1),Facts[Quantity]))', 'ERR'),
    ('SUMX(VALUES(Facts[Region]),SUMX(VALUES(Facts[Note]),Facts[Quantity]))', 'ERR'),
    ('SUMX(VALUES(Facts[Region]),SUMX(VALUES(Facts[Note]),Facts[Region]="East"))', 'ERR'),
    ('SUMX(VALUES(Facts[Region]),SUMX(ROW("a",1),IF(Facts[Region]="East",1,0)))', '1'),
    ('SUMX(ADDCOLUMNS(Facts,"q",Facts[Quantity]),SUMX(ROW("a",1),Facts[Quantity]))', '15'),
    ('SUMX(ADDCOLUMNS(Facts,"q",Facts[Quantity]),SUMX(ROW("a",1),[q]))', '15'),
    ('SUMX(SELECTCOLUMNS(Facts,"q",Facts[Quantity]),SUMX(ROW("a",1),[q]))', '15'),
    ('SUMX(SELECTCOLUMNS(Facts,"q",Facts[Quantity]),SUMX(ROW("a",1),Facts[Quantity]))', 'ERR'),
    ('SUMX(FILTER(Facts,Facts[Quantity]>1),SUMX(ROW("a",1),Facts[Quantity]))', '14'),
    ('SUMX(Facts,SUMX(ROW("a",Facts[Quantity]),[a]))', '15'),
    ('SUMX(Facts,SUMX(ROW("a",1),CALCULATE(COUNTROWS(Facts))))', '6'),
    ('SUMX(Facts,SUMX(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity]))', '12'),
    ('SUMX(Facts,SUMX(INDEX(2,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity]))', '15'),
    ('COUNTROWS(FILTER(ALL(Facts),Facts[Quantity]>SUMX(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity])))', '1'),
    ('SUMX(Facts,SUMX(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity]*2))', '24'),
    ('SUMX(Facts,SUMX(OFFSET(-1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),Facts[Quantity]))', '7'),
    ('SUMX(Facts,SUMX(ROW("a",1),COUNTROWS(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])))))', '4'),
    ('SUMX(Facts,SUMX(GENERATESERIES(1,2),COUNTROWS(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])))))', '8'),
    ('SUMX(TOPN(2,Facts,Facts[Sales],ASC,Facts[Quantity],ASC),Facts[Quantity])', '5'),
    ('SUMX(TOPN(1,Facts,Facts[Sales],ASC,Facts[Quantity],ASC),Facts[Quantity])', '1'),
    ('SUMX(TOPN(2,Facts,Facts[Sales],DESC,Facts[Quantity],ASC),Facts[Quantity])', '5'),
    ('SUMX(TOPN(6,Facts,Facts[Sales],ASC,Facts[Quantity],ASC),Facts[Quantity])', '15'),
    ('CONCATENATEX(TOPN(3,Facts,Facts[Sales],ASC,Facts[Quantity],ASC),Facts[Quantity],"|")', '0|4|1'),
    ('SUMX(TOPN(2,Facts,Facts[Sales],ASC),Facts[Quantity])', '5'),
    ('SUMX(TOPN(1,Facts,Facts[Sales],ASC),Facts[Quantity])', '1'),
    ('CONCATENATEX(TOPN(4,Facts,Facts[Sales],DESC,Facts[Quantity],ASC),Facts[Quantity],"|")', '0|5|2|3'),
    ('CONCATENATEX(TOPN(4,Facts,Facts[Sales],DESC,Facts[Quantity],DESC),Facts[Quantity],"|")', '0|5|2|3'),
    ('CONCATENATEX(TOPN(3,Facts,Facts[Sales],ASC,Facts[Quantity],DESC),Facts[Quantity],"|")', '0|4|1'),
    ('CONCATENATEX(TOPN(2,Facts,Facts[Sales],ASC,Facts[Quantity],ASC),Facts[Quantity],"|")', '4|1'),
    ('CONCATENATEX(TOPN(2,Facts,Facts[Sales],ASC,Facts[Quantity],DESC),Facts[Quantity],"|")', '4|1'),
    ('CONCATENATEX(TOPN(5,Facts,Facts[Sales],DESC,Facts[Quantity],ASC),Facts[Quantity],"|")', '4|0|2|3|5'),
    ('CONCATENATEX(TOPN(5,Facts,Facts[Sales],DESC,Facts[Quantity],DESC),Facts[Quantity],"|")', '4|0|2|3|5'),
    ('CONCATENATEX(TOPN(4,Facts,Facts[Sales],ASC,Facts[Quantity],ASC),Facts[Quantity],"|")', '5|0|1|4'),
    ('CONCATENATEX(TOPN(2,Facts,Facts[Sales],ASC),Facts[Quantity],"|")', '4|1'),
    ('CONCATENATEX(TOPN(4,Facts,Facts[Sales],DESC),Facts[Quantity],"|")', '0|5|2|3'),
    ('CONCATENATEX(TOPN(5,Facts,Facts[Sales],DESC),Facts[Quantity],"|")', '4|0|2|3|5'),
    ('CONCATENATEX(TOPN(2,Facts,Facts[Note],ASC,Facts[Quantity],ASC),Facts[Quantity],"|")', '5|3'),
    ('CONCATENATEX(TOPN(3,Facts,Facts[Note],ASC,Facts[Quantity],ASC),Facts[Quantity],"|")', '4|3|5'),
    ('CONCATENATEX(TOPN(3,Facts,Facts[Note],DESC,Facts[Quantity],ASC),Facts[Quantity],"|")', '2|1|0'),
    ('SUMX(Facts,SUMX(VALUES(Facts[Region]),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER(Facts[Quantity])))))', '45'),
    ('SUMX(Facts,SUMX(VALUES(Facts[Region]),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER(Facts[Quantity],2)))))', '45'),
    ('SUMX(Facts,SUMX(ROW("a",1),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER(Facts[Quantity])))))', '15'),
    ('SUMX(Facts,SUMX(VALUES(Facts[Region]),EARLIER(Facts[Quantity])))', '45'),
    ('SUMX(ADDCOLUMNS(Facts,"q2",Facts[Quantity]*2),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER([q2]))))', '9'),
    ('SUMX(ADDCOLUMNS(Facts,"q2",Facts[Quantity]*2),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER(Facts[Quantity]))))', '15'),
    ('SUMX(ADDCOLUMNS(Facts,"q2",Facts[Quantity]*2),EARLIER([q2]))', 'ERR'),
    ('SUMX(ADDCOLUMNS(Facts,"q2",Facts[Quantity]*2),COUNTROWS(FILTER(VALUES(Facts[Region]),EARLIER([q2])>2)))', '12'),
    ('SUMX(Facts,COUNTROWS(FILTER(VALUES(Facts[Region]),EARLIER(Facts[Quantity],2)>2)))', 'ERR'),
    ('SUMX(ADDCOLUMNS(Facts,"q2",Facts[Quantity]*2),COUNTROWS(FILTER(Facts,EARLIER([q2])>2)))', '24'),
    ('SUMX(ADDCOLUMNS(Facts,"q2",Facts[Quantity]*2),COUNTROWS(FILTER(Facts,EARLIER([q2],2)>2)))', 'ERR'),
    ('SUMX(ADDCOLUMNS(Facts,"q2",Facts[Quantity]*2),COUNTROWS(FILTER(Facts,EARLIEST([q2])>2)))', '24'),
    ('SUMX(SELECTCOLUMNS(Facts,"q",Facts[Quantity]),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER([q])*2)))', '9'),
    ('SUMX(SELECTCOLUMNS(Facts,"q",Facts[Quantity],"r",Facts[Region]),COUNTROWS(FILTER(Facts,Facts[Region]=EARLIER([r]))))', '14'),
    ('SUMX(Facts,SUMX(SELECTCOLUMNS(Facts,"q",Facts[Quantity]),EARLIER(Facts[Quantity])))', '90'),
    ('SUMX(Facts,SUMX(FILTER(Facts,Facts[Quantity]>1),EARLIER(Facts[Quantity])))', '60'),
    ('SUMX(Facts,SUMX(FILTER(Facts,Facts[Quantity]>1),EARLIER(Facts[Quantity],2)))', 'ERR'),
    ('SUMX(VALUES(Facts[Region]),SUMX(Facts,COUNTROWS(FILTER(Facts,EARLIEST(Facts[Quantity])>2))))', 'ERR'),
    ('SUMX(VALUES(Facts[Region]),SUMX(Facts,COUNTROWS(FILTER(Facts,EARLIER(Facts[Quantity])>2))))', '54'),
    ('SUMX(Facts,SUMX(FILTER(Facts,Facts[Quantity]>3),SUMX(VALUES(Facts[Region]),EARLIER(Facts[Quantity]))))', '162'),
    ('SUMX(Facts,SUMX(FILTER(Facts,Facts[Quantity]>3),EARLIER(Facts[Quantity])))', '30'),
    ('SUMX(Facts,SUMX(FILTER(Facts,Facts[Quantity]>3),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER(Facts[Quantity])))))', '6'),
    ('SUMX(Facts,SUMX(FILTER(Facts,Facts[Quantity]>3),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIEST(Facts[Quantity])))))', '30'),
    ('SUMX(ADDCOLUMNS(Facts,"q2",Facts[Quantity]*2),SUMX(FILTER(Facts,Facts[Quantity]>3),SUMX(VALUES(Facts[Region]),EARLIER([q2]))))', '180'),
    ('SUMX(Facts,SUMX(VALUES(Facts[Region]),SUMX(VALUES(Facts[Note]),EARLIER(Facts[Quantity],2))))', '135'),
    ('SUMX(Facts,SUMX(FILTER(Facts,Facts[Quantity]>3),SUMX(VALUES(Facts[Region]),EARLIER(Facts[Quantity],2))))', '90'),
    ('SUMX(Facts,SUMX(FILTER(Facts,Facts[Quantity]>3),SUMX(VALUES(Facts[Region]),EARLIEST(Facts[Quantity]))))', '90'),
    ('SUMX(VALUES(Facts[Region]),SUMX(Facts,SUMX(VALUES(Facts[Note]),EARLIER(Facts[Quantity]))))', '135'),
    ('SUMX(VALUES(Facts[Region]),SUMX(Facts,SUMX(VALUES(Facts[Note]),EARLIER(Facts[Quantity],2))))', 'ERR'),
    ('SUMX(VALUES(Facts[Region]),SUMX(Facts,SUMX(VALUES(Facts[Note]),EARLIEST(Facts[Quantity]))))', 'ERR'),
    ('SUMX(VALUES(Facts[Region]),SUMX(Facts,EARLIER(Facts[Quantity])))', 'ERR'),
    ('SUMX(VALUES(Facts[Region]),SUMX(Facts,EARLIEST(Facts[Quantity])))', 'ERR'),
    ('SUMX(VALUES(Facts[Region]),SUMX(Facts,EARLIER(Facts[Region])))', 'ERR'),
    ('SUMX(Facts,SUMX(FILTER(Facts,Facts[Quantity]>3),SUMX(VALUES(Facts[Region]),EARLIER(Facts[Region]))))', 'ERR'),
    ('OFFSET(1,ALL(Facts[Quantity]),ORDERBY(Facts[Quantity]))', 'ERR'),
    ('SUMX(Facts,COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER(Facts[Quantity]))))', '15'),
    ('SUMX(Facts,SUMX(VALUES(Facts[Region]),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER(Facts[Quantity],1)))))', '45'),
    ('SUMX(Facts,SUMX(VALUES(Facts[Region]),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIEST(Facts[Quantity])))))', '45'),
    ('SUMX(Facts,COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER(Facts[Quantity],2))))', 'ERR'),
    ('COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER(Facts[Quantity])))', 'ERR'),
    ('SUMX(Facts,TOPN(1,Facts,Facts[Sales],ASC,Facts[Quantity],ASC)[Quantity])', 'ERR'),
    ('SUMX(VALUES(Facts[Region]),PERCENTILEX.INC(FILTER(Facts,Facts[Region]=EARLIER(Facts[Region])),Facts[Quantity],BLANK()))', '5'),
]

STAYS_REFUSED = ['AVERAGEX(ADDCOLUMNS(Facts,"k",Facts[Sales]*2),COUNTX(VALUES(Facts[Note]),AVERAGEX(OFFSET(-1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])),1)))',
 'SUMX(Facts,COUNTX(VALUES(Facts[Note]),COUNTROWS(OFFSET(-1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])))))',
 'SUMX(VALUES(Facts[Note]),SUMX(Facts,COUNTROWS(OFFSET(-1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])))))',
 'SUMX(Facts,SUMX(VALUES(Facts[Region]),COUNTROWS(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])))))',
 'SUMX(Facts,SUMX(VALUES(Facts[Note]),COUNTROWS(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])))))',
 'SUMX(VALUES(Facts[Note]),SUMX(VALUES(Facts[Region]),COUNTROWS(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])))))',
 'SUMX(VALUES(Facts[Region]),SUMX(VALUES(Facts[Note]),COUNTROWS(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])))))',
 'SUMX(FILTER(Facts,Facts[Quantity]>1),SUMX(VALUES(Facts[Note]),COUNTROWS(OFFSET(1,SUMMARIZE(Facts,Facts[Region]),ORDERBY(Facts[Region])))))',
 'SUMX(Facts,COUNTROWS(FILTER(VALUES(Facts[Region]),EARLIER(Facts[Quantity])>2)))',
 'SUMX(Facts,COUNTROWS(FILTER(VALUES(Facts[Region]),EARLIEST(Facts[Quantity])>2)))']


class EnclosingRowContext(unittest.TestCase):
    def test_power_bi_answers(self) -> None:
        wrong = [(expr, answer, dax.local(expr)) for expr, answer in POWER_BI if status(answer, dax.local(expr)) != "match"]
        self.assertEqual([], wrong)

    def test_outer_column_is_read_from_the_enclosing_row(self) -> None:
        self.assertEqual("15", dax.local('SUMX(Facts,SUMX(ROW("a",1),Facts[Quantity]))'))
        self.assertEqual("45", dax.local("SUMX(Facts,SUMX(VALUES(Facts[Region]),Facts[Quantity]))"))

    def test_earlier_is_positional(self) -> None:
        self.assertEqual("45", dax.local("SUMX(Facts,SUMX(VALUES(Facts[Region]),COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER(Facts[Quantity],2)))))"))
        self.assertTrue(dax.local("SUMX(Facts,COUNTROWS(FILTER(Facts,Facts[Quantity]>EARLIER(Facts[Quantity],2))))").startswith("LOCAL-REJECT"))

    def test_empty_iteration_body_is_validated(self) -> None:
        """Power BI raises an error for these although the filtered iteration has no rows; the local engine used to answer BLANK."""
        for expr in (
            'COUNTX(FILTER(VALUES(Facts[Note]),Facts[Note]="West"),MINX(DISTINCT(Facts[Note]),Facts[Quantity]+1))',
            'SUMX(FILTER(VALUES(Facts[Note]),Facts[Note]="West"),SUMX(VALUES(Facts[Sales]),Facts[Quantity]))',
            'SUMX(SELECTCOLUMNS(Facts,"s",Facts[Region]),SUMX(ADDCOLUMNS(VALUES(Facts[Note]),"j",2),SUMX(FILTER(VALUES(Facts[Region]),Facts[Region]="P1"),[s])))',
        ):
            self.assertTrue(dax.local(expr).startswith("LOCAL-REJECT"), expr)

    def test_unmodelled_walk_order_stays_refused(self) -> None:
        for expr in STAYS_REFUSED:
            self.assertTrue(dax.local(expr).startswith("LOCAL-REJECT"), expr)


if __name__ == "__main__":
    unittest.main()
