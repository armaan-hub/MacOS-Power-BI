"""Iteration 95 review: LINEST / LINESTX against live Power BI Desktop (2.157.879.0).

Power BI solves the regression in binary doubles; its last digits are rounding noise no outside algorithm reproduces
(the first build "matched" by looking the saved answers up, which is why the solver now has a test of its own).
What is pinned here:
  - three review batteries (2,875 random-data/Facts/context probes, 184 semantics probes and 2,420 larger random tables)
    never differ from Power BI;
  - the solver is real: it agrees with an independent exact-rational least squares on fresh random data;
  - only a literal TRUE()/FALSE() last argument is `const` (1=0, NOT(TRUE()) are regressors; a VAR is not modelled);
  - everything Power BI answers with noise or a convention of its own stays refused.
"""
from __future__ import annotations

import json
import random
import unittest
from fractions import Fraction
from pathlib import Path

from analytics_studio import dax_linest
from analytics_studio.measures import MeasureError, evaluate_measures
from tools import dax_oracle_diff as dax
from tools.dax_oracle_diff import HEADERS, LOCAL_ROWS
from tools.parity_check import status

PARITY = Path(__file__).resolve().parents[1] / "tools" / "parity"

# Valid DAX whose Power BI answer is rounding noise or a rank-deficient convention: the local engine must refuse.
STAYS_REFUSED = [
    'MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{2,4},{3,6},{4,8}}),[y],[x]),[Slope1])',  # perfect fit
    'MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,5},{2,5},{3,5}}),[y],[x]),[Slope1])',  # constant response
    'MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{1,3},{1,5},{1,4}}),[y],[x]),[Slope1])',  # constant regressor
    'MAXX(LINESTX(DATATABLE("x",DOUBLE,"y",DOUBLE,{{1,2},{2,3}}),[y],[x]),[Slope1])',  # as many rows as coefficients
    'MAXX(LINESTX(ROW("a",1,"b",2),[a],[b]),[Slope1])',
    "MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales],1=0),[Slope1])",  # Power BI zeroes the dependent coefficient
    "MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales],1),[Slope1])",
    "MAXX(LINEST(Facts[Quantity],Facts[Sales],Facts[Sales]),[Slope1])",
    "MAXX(LINESTX(Facts,Facts[Quantity],FORMAT(Facts[Quantity],\"0\")),[Slope1])",  # text that looks like a number
    "VAR c=FALSE() RETURN MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales],c),[Slope1])",  # Power BI folds the variable
    "TOCSV(LINEST(Facts[Quantity],Facts[Sales]))",  # the 15 digits include Power BI's rounding noise
    "TOJSON(LINESTX(Facts,Facts[Quantity],Facts[Sales]))",
    "LEN(TOCSV(LINESTX(Facts,Facts[Quantity],Facts[Sales])))",
    "ISDOUBLE(MAXX(LINEST(Facts[Quantity],Facts[Sales]),[Slope1]))",
]


def _replay(name: str) -> tuple[int, list[tuple[str, str, str, str]]]:
    saved = json.loads((PARITY / f"{name}.json").read_text())
    matched, bad = 0, []
    for item in saved["items"]:
        actual = dax.local(item["expr"])
        outcome = status(item["powerbi"], actual)
        if outcome == "match":
            matched += 1
        elif outcome != "gap-reject":
            bad.append((item["expr"], item["powerbi"], actual, outcome))
    return matched, bad


def _exact_ols(y: list[float], columns: list[list[float]], const: bool) -> dict[str, Fraction]:
    """Least squares in exact rational arithmetic, written independently of dax_linest."""
    n, k = len(y), len(columns)
    design = [[Fraction(c[r]) for c in columns] + ([Fraction(1)] if const else []) for r in range(n)]
    p = len(design[0])
    yf = [Fraction(v) for v in y]
    aug = [[sum(design[r][i] * design[r][j] for r in range(n)) for j in range(p)]
           + [sum(design[r][i] * yf[r] for r in range(n))] for i in range(p)]
    for col in range(p):
        pivot = next(r for r in range(col, p) if aug[r][col] != 0)
        aug[col], aug[pivot] = aug[pivot], aug[col]
        aug[col] = [v / aug[col][col] for v in aug[col]]
        for r in range(p):
            if r != col:
                aug[r] = [a - aug[r][col] * b for a, b in zip(aug[r], aug[col])]
    beta = [aug[i][p] for i in range(p)]
    rss = sum((yf[r] - sum(beta[j] * design[r][j] for j in range(p))) ** 2 for r in range(n))
    mean = sum(yf) / n
    sst = sum((v - mean) ** 2 for v in yf) if const else sum(v * v for v in yf)
    return {"beta0": beta[0], "rss": rss, "sst": sst, "df": Fraction(n - p), "r2": 1 - rss / sst}


class LinestReviewTest(unittest.TestCase):
    def test_review_batteries_never_differ_from_power_bi(self) -> None:
        matched, bad = _replay("dax_battery_linest_extra")
        self.assertEqual([], bad)
        self.assertGreaterEqual(matched, 2600)
        matched2, bad2 = _replay("dax_battery_linest_extra2")
        self.assertEqual([], bad2)
        self.assertGreaterEqual(matched2, 90)
        matched3, bad3 = _replay("dax_battery_linest_extra3")
        self.assertEqual([], bad3)
        self.assertGreaterEqual(matched3, 1990)

    def test_solver_is_not_a_lookup_of_saved_answers(self) -> None:
        source = Path(dax_linest.__file__).read_text()
        for forbidden in ("parity", ".json", "open(", "battery", "powerbi"):
            self.assertNotIn(forbidden, source)

    def test_solver_agrees_with_exact_rational_least_squares(self) -> None:
        rng = random.Random(95)
        for trial in range(40):
            n, k = rng.randint(6, 14), rng.choice([1, 2, 3])
            const = trial % 3 != 0
            columns = [[round(rng.uniform(-5, 10), 2) for _ in range(n)] for _ in range(k)]
            y = [round(sum((j + 1) * columns[j][r] for j in range(k)) + rng.gauss(0, 2), 3) for r in range(n)]
            headers, rows = dax_linest.solve_linest(y, columns, const)
            exact = _exact_ols(y, columns, const)
            row = rows[0]
            self.assertEqual(headers, list(row))
            for key, want in (("Slope1", exact["beta0"]), ("ResidualSumOfSquares", exact["rss"]),
                              ("CoefficientOfDetermination", exact["r2"]), ("DegreesOfFreedom", exact["df"])):
                self.assertAlmostEqual(float(row[key]) / float(want), 1.0, places=13, msg=f"{key} trial {trial}")

    def test_known_power_bi_values(self) -> None:
        """x = 1..5, y = 2, 4.1, 5.9, 8.2, 9.8: every column as Power BI printed it (15 digits)."""
        _, rows = dax_linest.solve_linest([2.0, 4.1, 5.9, 8.2, 9.8], [[1.0, 2.0, 3.0, 4.0, 5.0]], True)
        want = {"Slope1": "1.97", "Intercept": "0.09", "StandardErrorSlope1": "0.0550757054728609",
                "StandardErrorIntercept": "0.182665450117603", "CoefficientOfDetermination": "0.997660668380463",
                "StandardError": "0.174164673034841", "FStatistic": "1279.41758241759", "DegreesOfFreedom": "3",
                "RegressionSumOfSquares": "38.809", "ResidualSumOfSquares": "0.091"}
        for key, text in want.items():
            self.assertAlmostEqual(float(rows[0][key]) / float(text), 1.0, places=12, msg=key)

    def test_const_is_only_a_literal_true_or_false(self) -> None:
        self.assertFalse(dax.local("MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales],FALSE()),[Slope1])").startswith("LOCAL"))
        self.assertTrue(dax.local("MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales],FALSE()),[Intercept])").startswith("LOCAL-REJECT"))
        self.assertFalse(dax.local("MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales],TRUE()),[Intercept])").startswith("LOCAL"))
        # 1=0 is a regressor column: Power BI has a Slope2 and an Intercept there; the local engine refuses the design
        self.assertTrue(dax.local("MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales],1=0),[Intercept])").startswith("LOCAL-REJECT"))

    def test_blank_is_zero_and_booleans_are_numbers(self) -> None:
        self.assertEqual("4", dax.local("MAXX(LINESTX(Facts,Facts[Sales],Facts[Quantity]),[DegreesOfFreedom])"))
        self.assertEqual("4", dax.local("MAXX(LINESTX(Facts,Facts[Quantity],Facts[Quantity]>2),[DegreesOfFreedom])"))

    def test_empty_input_gives_no_rows(self) -> None:
        self.assertEqual("BLANK", dax.local("COUNTROWS(LINESTX(FILTER(Facts,Facts[Quantity]>9),Facts[Quantity],Facts[Sales]))"))

    def test_stays_refused(self) -> None:
        for expression in STAYS_REFUSED:
            outcome = dax.local(expression)
            self.assertTrue(outcome.startswith("LOCAL-REJECT"), f"{expression} -> {outcome}")

    def test_columns_of_two_tables_are_refused(self) -> None:
        tables = [
            {"id": "facts", "name": "Facts", "headers": HEADERS, "rows": LOCAL_ROWS,
             "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"}},
            {"id": "other", "name": "Other", "headers": ["A"], "rows": [{"A": str(v)} for v in (3, 1, 4, 1, 5, 9)],
             "column_types": {"A": "whole_number"}},
        ]
        with self.assertRaises(MeasureError):
            evaluate_measures(
                [{"name": "P__", "expression": "MAXX(LINEST(Facts[Quantity],Other[A]),[Slope1])"}],
                LOCAL_ROWS, HEADERS, "Facts", measure_names=["P__"], table_context=tables, active_table_id="facts",
            )


if __name__ == "__main__":
    unittest.main()
