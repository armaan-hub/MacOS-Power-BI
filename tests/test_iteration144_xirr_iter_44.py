"""Iteration 144: tests for Task 54 xirr-iter-44 (XIRR's iterative answers, Part A).

The bracket search of the Task 33 root finder answers several brackets above the guess when no bracket lies below it
(Power BI took the lowest of them).  Cases with several brackets on both sides, or with no bracket found, stay refused.
"""

import unittest
from tools import dax_oracle_diff as dax
from tools.dax_oracle_diff import same


ROWS_4 = '{{-7115.09,"2018-07-25"},{4526.59,"2018-11-28"},{2476.41,"2020-10-30"},{3469.45,"2020-03-01"},{3819.24,"2018-06-21"},{-1135.95,"2023-11-24"},{-2447.35,"2019-12-01"},{3109.63,"2024-07-06"}}'
ROWS_33 = '{{3682.28,"2021-10-09"},{1909.99,"2024-09-25"},{-516.28,"2019-10-31"},{660.82,"2018-12-24"},{-4304.07,"2020-11-24"}}'
ROWS_1 = '{{-6900.64,"2021-03-04"},{3236.06,"2023-06-15"},{1864.79,"2020-10-18"}}'
ROWS_47 = '{{-1801.98,"2021-10-21"},{1169.95,"2023-08-23"},{-4011.96,"2023-07-09"}}'
ROWS_5 = '{{-5455.84,"2020-07-11"},{-4615.36,"2021-02-10"},{2869.8,"2020-01-24"},{4691.53,"2024-08-23"},{374.18,"2022-11-11"},{57.74,"2023-12-13"},{4113.19,"2022-09-01"},{1384.98,"2018-11-25"}}'
ROWS_23 = '{{-7460.3,"2021-01-30"},{2638.28,"2020-01-25"},{-3318.55,"2020-10-21"},{4134.2,"2022-04-20"},{1178.31,"2022-08-15"},{4807.3,"2021-08-24"},{-736.0,"2023-04-22"}}'


def table(rows: str) -> str:
    return f'DATATABLE("v",DOUBLE,"d",DATETIME,{rows})'


class TestIteration144XirrIter44(unittest.TestCase):
    def test_lowest_of_several_upper_brackets_is_answered(self) -> None:
        # Power BI: 3.78280493915081 (guess 0.1, alternate -1); the bracket above the guess is taken
        res = dax.local(f"XIRR({table(ROWS_4)},[v],[d],0.1,-1)")
        self.assertTrue(same("3.78280493915081", res), res)

    def test_guess_with_five_rows(self) -> None:
        # Power BI: 0.222669897880405 (guess 0.05)
        res = dax.local(f"XIRR({table(ROWS_33)},[v],[d],0.05)")
        self.assertTrue(same("0.222669897880405", res), res)

    def test_single_upper_bracket_with_alternate(self) -> None:
        # Power BI: 31.6426521062851 (guess 0.3, alternate 0)
        res = dax.local(f"XIRR({table(ROWS_1)},[v],[d],0.3,0)")
        self.assertTrue(same("31.6426521062851", res), res)

    def test_refusals_kept(self) -> None:
        # several brackets on both sides, no bracket found, and a root near -1 stay refused (not answered wrongly)
        self.assertTrue(dax.local(f"XIRR({table(ROWS_5)},[v],[d],-0.5)").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local(f"XIRR({table(ROWS_23)},[v],[d])").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local(f"XIRR({table(ROWS_47)},[v],[d])").startswith("LOCAL-REJECT:"))


if __name__ == "__main__":
    unittest.main()
