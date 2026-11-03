"""Iteration 121: linest-edge-21 (LINEST and LINESTX rank-deficient regressors and near-perfect fits).

Plan: docs/plans/2026-11-03-linest-edge-21.md
Spec: tools/parity/task31_linest_edge_spec.json
"""
from __future__ import annotations

import unittest
from tools import dax_oracle_diff as dax
from tools.parity_check import status


class LinestEdge21PartATest(unittest.TestCase):
    def test_large_offset_fits(self) -> None:
        """Near-perfect fits with large offsets are evaluated accurately without premature refusal."""
        expr_slope = 'MAXX(LINESTX(DATATABLE("y",DOUBLE,"a",DOUBLE,{{1460005.231,1000000.4},{1460004.387,1000001.47},{1460006.856,1000002.19},{1460007.534,1000003.48},{1460009.052,1000004.34},{1460012.851,1000005.23},{1460013.613,1000006.38},{1460012.105,1000007.1}}),[y],[a]),[Slope1])'
        self.assertEqual("match", status("1.39467184717032", dax.local(expr_slope)))

        expr_intercept = 'MAXX(LINESTX(DATATABLE("y",DOUBLE,"a",DOUBLE,{{1460005.231,1000000.4},{1460004.387,1000001.47},{1460006.856,1000002.19},{1460007.534,1000003.48},{1460009.052,1000004.34},{1460012.851,1000005.23},{1460013.613,1000006.38},{1460012.105,1000007.1}}),[y],[a]),[Intercept])'
        self.assertEqual("match", status("65331.7735782033", dax.local(expr_intercept)))

        expr_r2 = 'MAXX(LINESTX(DATATABLE("y",DOUBLE,"a",DOUBLE,{{1460005.231,1000000.4},{1460004.387,1000001.47},{1460006.856,1000002.19},{1460007.534,1000003.48},{1460009.052,1000004.34},{1460012.851,1000005.23},{1460013.613,1000006.38},{1460012.105,1000007.1}}),[y],[a]),[CoefficientOfDetermination])'
        self.assertEqual("match", status("0.874777585374994", dax.local(expr_r2)))

    def test_exact_fit_remains_refused(self) -> None:
        """Exact fits where statistics are floating-point rounding noise remain refused."""
        expr_f = 'MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales]+1,Facts[Quantity]*0.5+Facts[Sales]),[FStatistic])'
        res = dax.local(expr_f)
        self.assertTrue(res.startswith("LOCAL-REJECT:The fit is perfect to within rounding"))


class LinestEdge21PartBTest(unittest.TestCase):
    def test_constant_regressor_absorbed_by_intercept(self) -> None:
        """Constant regressor with const=True has slope 0 and is absorbed by the intercept."""
        expr_slope = 'MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{1,3},{1,5},{1,4}}),[y],[x]),[Slope1])'
        self.assertEqual("0", dax.local(expr_slope))

        expr_intercept = 'MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{1,3},{1,5},{1,4}}),[y],[x]),[Intercept])'
        self.assertEqual("3.5", dax.local(expr_intercept))

        expr_df = 'MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{1,3},{1,5},{1,4}}),[y],[x]),[DegreesOfFreedom])'
        self.assertEqual("3", dax.local(expr_df))

    def test_duplicate_collinear_regressors(self) -> None:
        """Duplicate regressor columns get slope 0 and standard error 0."""
        expr_s1 = 'MAXX(LINEST(Facts[Quantity],Facts[Sales],Facts[Sales]),[Slope1])'
        self.assertEqual("match", status("0.0374955783516095", dax.local(expr_s1)))

        expr_s2 = 'MAXX(LINEST(Facts[Quantity],Facts[Sales],Facts[Sales]),[Slope2])'
        self.assertEqual("0", dax.local(expr_s2))

        expr_df = 'MAXX(LINEST(Facts[Quantity],Facts[Sales],Facts[Sales]),[DegreesOfFreedom])'
        self.assertEqual("4", dax.local(expr_df))

    def test_blank_and_constant_scalar_regressors(self) -> None:
        """BLANK() or constant expressions in regressors are dropped cleanly."""
        expr = 'MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales],BLANK()),[Slope2])'
        self.assertEqual("0", dax.local(expr))

        expr_df = 'MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales],BLANK()),[DegreesOfFreedom])'
        self.assertEqual("4", dax.local(expr_df))


if __name__ == "__main__":
    unittest.main()
