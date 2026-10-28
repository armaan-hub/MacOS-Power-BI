"""DAX LINEST and LINESTX: ordinary least squares as Power BI Desktop returns it.

Power BI solves the regression in binary doubles, so its last digits carry rounding noise from its own routine
(a perfect fit returns 4.44E-16 where the exact slope is 0, and the noise differs from every textbook algorithm).
That noise cannot be reproduced from outside, so this module does the one honest thing: it solves the normal
equations in 60-digit decimal arithmetic on the very same double inputs and rounds once to a double. Agreement with
Power BI is then about 15 significant digits, which is what every comparison of a single value needs.

Everything Power BI answers with rounding noise or with its own convention for degenerate designs is refused
(`LinestRefused`) instead of guessed:
  - a perfect or near-perfect fit (residuals so small next to the data that Power BI's doubles cannot resolve them,
    so every statistic built on the residuals is rounding noise there),
  - a constant response, fewer rows than coefficients + 1, or a rank-deficient design (Power BI zeroes the
    coefficient and counts n - rank degrees of freedom; not modelled),
  - non-finite inputs.
"""

from __future__ import annotations

import math
from decimal import Decimal, localcontext
from typing import Any

_PRECISION = 60
_SINGULAR = Decimal("1e-30")  # a pivot this small next to the largest entry means the design is rank deficient
_NOISE_FLOOR = Decimal("1e-6")  # rms residual below this fraction of the largest |y|: Power BI's residuals are mostly rounding


class LinestRefused(ValueError):
    """The regression is valid DAX but Power BI's answer cannot be reproduced exactly."""


def headers_for(slopes: int, const: bool) -> list[str]:
    """The column names of the one-row result, in Power BI's order."""
    names = [f"Slope{i + 1}" for i in range(slopes)]
    if const:
        names.append("Intercept")
    names += [f"StandardErrorSlope{i + 1}" for i in range(slopes)]
    if const:
        names.append("StandardErrorIntercept")
    return names + [
        "CoefficientOfDetermination", "StandardError", "FStatistic",
        "DegreesOfFreedom", "RegressionSumOfSquares", "ResidualSumOfSquares",
    ]


def _invert(matrix: list[list[Decimal]]) -> list[list[Decimal]]:
    """Gauss-Jordan inverse with partial pivoting; LinestRefused when the matrix is numerically singular."""
    size = len(matrix)
    scale = max(abs(value) for row in matrix for value in row)
    if scale == 0:
        raise LinestRefused("The design matrix is all zeros.")
    work = [row[:] + [Decimal(1) if i == j else Decimal(0) for j in range(size)] for i, row in enumerate(matrix)]
    for column in range(size):
        pivot_row = max(range(column, size), key=lambda r: abs(work[r][column]))
        if abs(work[pivot_row][column]) <= _SINGULAR * scale:
            raise LinestRefused("The regressors are linearly dependent; Power BI's rank-deficient convention is not modelled.")
        work[column], work[pivot_row] = work[pivot_row], work[column]
        pivot = work[column][column]
        work[column] = [value / pivot for value in work[column]]
        for r in range(size):
            if r != column and work[r][column] != 0:
                factor = work[r][column]
                work[r] = [a - factor * b for a, b in zip(work[r], work[column])]
    return [row[size:] for row in work]


def _as_double(value: Decimal) -> Decimal:
    """Round to the nearest double, then back to the shortest Decimal that names it (what a double column holds)."""
    return Decimal(repr(float(value)))


def solve_linest(y_values: list[float], x_columns: list[list[float]], const: bool) -> tuple[list[str], list[dict[str, Any]]]:
    """(headers, rows) of the regression of y on the x columns; no rows at all when there are no data rows."""
    slopes = len(x_columns)
    headers = headers_for(slopes, const)
    rows = len(y_values)
    if rows == 0:
        return headers, []
    if not all(math.isfinite(v) for v in y_values) or not all(math.isfinite(v) for c in x_columns for v in c):
        raise LinestRefused("A value is not a finite number.")
    coefficients = slopes + (1 if const else 0)
    degrees = rows - coefficients
    if degrees <= 0:
        raise LinestRefused("There are not more rows than coefficients; Power BI's answer there is not modelled.")
    with localcontext() as context:
        context.prec = _PRECISION
        y = [Decimal(v) for v in y_values]  # Decimal(float) keeps every bit of the double
        design = [[Decimal(v) for v in column] for column in x_columns]
        if const:
            design.append([Decimal(1)] * rows)
        gram = [[sum((a * b for a, b in zip(design[i], design[j])), Decimal(0)) for j in range(coefficients)] for i in range(coefficients)]
        moment = [sum((a * b for a, b in zip(design[i], y)), Decimal(0)) for i in range(coefficients)]
        inverse = _invert(gram)
        beta = [sum((inverse[i][j] * moment[j] for j in range(coefficients)), Decimal(0)) for i in range(coefficients)]
        residual_ss = Decimal(0)
        for r in range(rows):
            fitted = sum((beta[j] * design[j][r] for j in range(coefficients)), Decimal(0))
            residual_ss += (y[r] - fitted) ** 2
        if const:
            mean = sum(y, Decimal(0)) / rows
            total_ss = sum(((v - mean) ** 2 for v in y), Decimal(0))
        else:
            total_ss = sum((v * v for v in y), Decimal(0))
        if total_ss == 0:
            raise LinestRefused("The response is constant; Power BI's answer there is rounding noise.")
        if residual_ss <= rows * (_NOISE_FLOOR * max(abs(v) for v in y)) ** 2:
            raise LinestRefused("The fit is perfect to within rounding; Power BI's statistics there are rounding noise.")
        regression_ss = total_ss - residual_ss
        mean_square = residual_ss / degrees
        standard_error = mean_square.sqrt()
        std_errors = [(inverse[i][i] * mean_square).sqrt() for i in range(coefficients)]
        row: dict[str, Any] = {}
        for i in range(slopes):
            row[f"Slope{i + 1}"] = _as_double(beta[i])
        if const:
            row["Intercept"] = _as_double(beta[slopes])
        for i in range(slopes):
            row[f"StandardErrorSlope{i + 1}"] = _as_double(std_errors[i])
        if const:
            row["StandardErrorIntercept"] = _as_double(std_errors[slopes])
        row["CoefficientOfDetermination"] = _as_double(regression_ss / total_ss)
        row["StandardError"] = _as_double(standard_error)
        row["FStatistic"] = _as_double((regression_ss / slopes) / mean_square)
        row["DegreesOfFreedom"] = Decimal(degrees)
        row["RegressionSumOfSquares"] = _as_double(regression_ss)
        row["ResidualSumOfSquares"] = _as_double(residual_ss)
    return headers, [row]
