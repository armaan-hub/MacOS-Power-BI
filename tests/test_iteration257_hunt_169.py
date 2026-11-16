"""Iteration 257: Task 169 (dax-hunt-169), a bare column as a table argument of SUBSTITUTEWITHINDEX is refused before evaluation.

Power BI validates the whole query before it runs it, so a bare column in a table position (argument 1 <table> and argument 3
<indexColumnTable>) with no row context is a query error that IFERROR / ISERROR cannot catch. The static check that refuses bare
columns outside a row context now follows SUBSTITUTEWITHINDEX's two table arguments.

Values are the Power BI answers measured for the hunt rows. Refusals are checked by the LOCAL-REJECT prefix of dax.local.
"""

import unittest
from tools import dax_oracle_diff as dax


class TestIteration257Hunt169(unittest.TestCase):
    def test_rept_error_then_bare_column_in_swi_table_is_refused(self) -> None:
        # measured: IFERROR(REPT("x",-3)&SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1),"E") is a query error in Power BI
        self.assertTrue(dax.local('IFERROR(REPT("x",-3)&SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1),"E")').startswith("LOCAL-REJECT"))

    def test_sqrt_error_then_bare_column_in_swi_table_is_refused(self) -> None:
        # measured: IFERROR(SQRT(-1)+SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1),"E") is a query error in Power BI
        self.assertTrue(dax.local('IFERROR(SQRT(-1)+SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1),"E")').startswith("LOCAL-REJECT"))

    def test_error_call_then_bare_column_in_swi_table_is_refused(self) -> None:
        # measured: IFERROR(ERROR("boom")&SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1),"E") is a query error in Power BI
        self.assertTrue(dax.local('IFERROR(ERROR("boom")&SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1),"E")').startswith("LOCAL-REJECT"))

    def test_log_error_then_bare_column_in_swi_table_is_refused(self) -> None:
        # measured: IFERROR(LOG(-1)+SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1),"E") is a query error in Power BI
        self.assertTrue(dax.local('IFERROR(LOG(-1)+SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1),"E")').startswith("LOCAL-REJECT"))

    def test_iserror_rept_then_bare_column_in_swi_table_is_refused(self) -> None:
        # measured: ISERROR(REPT("x",-3)&SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1)) is a query error in Power BI
        self.assertTrue(dax.local('ISERROR(REPT("x",-3)&SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1))').startswith("LOCAL-REJECT"))

    def test_valid_swi_with_index_column_name_still_answers(self) -> None:
        # measured: MAXX(SUBSTITUTEWITHINDEX(VALUES(Facts[Quantity]),"i",Facts,IF(Facts[Region]="East",1,2),ASC),[i]) is 5
        self.assertEqual(dax.local('MAXX(SUBSTITUTEWITHINDEX(VALUES(Facts[Quantity]),"i",Facts,IF(Facts[Region]="East",1,2),ASC),[i])'), "5")

    def test_valid_swi_over_facts_still_answers(self) -> None:
        # measured: CONCATENATEX(SUBSTITUTEWITHINDEX(Facts,"i",Facts,Facts[Region],ASC),[i],"|",[i]) is 0|1|2|3|4|5
        self.assertEqual(dax.local('CONCATENATEX(SUBSTITUTEWITHINDEX(Facts,"i",Facts,Facts[Region],ASC),[i],"|",[i])'), "0|1|2|3|4|5")

    def test_sqrt_error_then_countrows_of_swi_bare_table_is_refused(self) -> None:
        # measured (t212): IFERROR(SQRT(-1)+COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1)),"E") is a query error
        self.assertTrue(dax.local('IFERROR(SQRT(-1)+COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1)),"E")').startswith("LOCAL-REJECT"))

    def test_untaken_if_branch_with_bare_swi_table_is_refused(self) -> None:
        # measured (t212): IF(FALSE(),COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1)),1) is a query error
        self.assertTrue(dax.local('IF(FALSE(),COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1)),1)').startswith("LOCAL-REJECT"))

    def test_sqrt_error_then_sumx_of_swi_bare_table_is_refused(self) -> None:
        # measured (t212): IFERROR(SQRT(-1)+SUMX(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1),[a]),"E") is a query error
        self.assertTrue(dax.local('IFERROR(SQRT(-1)+SUMX(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"a",Facts[Region],1),[a]),"E")').startswith("LOCAL-REJECT"))

    def test_bare_column_in_swi_index_table_argument_is_refused(self) -> None:
        # measured (t212): IFERROR(SQRT(-1)+COUNTROWS(SUBSTITUTEWITHINDEX(Facts[Region],"a",VALUES(Facts[Region]),1)),"E") is a query error
        self.assertTrue(dax.local('IFERROR(SQRT(-1)+COUNTROWS(SUBSTITUTEWITHINDEX(Facts[Region],"a",VALUES(Facts[Region]),1)),"E")').startswith("LOCAL-REJECT"))

    def test_valid_swi_over_summarize_still_answers(self) -> None:
        # measured (t212): COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region]),"a",VALUES(Facts[Region]),1)) is 3
        self.assertEqual(dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region]),"a",VALUES(Facts[Region]),1))'), "3")

    def test_valid_swi_over_filter_still_answers_and_guarded_error_stays_e(self) -> None:
        # measured (t212): COUNTROWS(SUBSTITUTEWITHINDEX(FILTER(VALUES(Facts[Region]),Facts[Region]="East"),"a",VALUES(Facts[Region]),1)) is 1
        self.assertEqual(dax.local('COUNTROWS(SUBSTITUTEWITHINDEX(FILTER(VALUES(Facts[Region]),Facts[Region]="East"),"a",VALUES(Facts[Region]),1))'), "1")
        # measured (t212): IFERROR(REPT("x",-3)&COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region]),"a",VALUES(Facts[Region]),1)),"E") is E
        self.assertEqual(dax.local('IFERROR(REPT("x",-3)&COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region]),"a",VALUES(Facts[Region]),1)),"E")'), "E")


if __name__ == "__main__":
    unittest.main()
