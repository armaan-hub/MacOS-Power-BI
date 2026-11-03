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
_SINGULAR = Decimal("1e-12")  # relative squared norm below this: regressor is linearly dependent / redundant
_TIE = Decimal("1e-9")  # relative closeness at which two pivot candidates count as tied
_RELATIVE_FLOOR = Decimal("1e-7")  # rms residual below this fraction of the spread of y: FStatistic divides by residuals that carry rounding noise (measured 1e-9 to 1e-8 off at 1e-8)
_NOISE_FLOOR = Decimal("1e-8")  # rms residual below this fraction of largest |y|: Power BI's residuals are mostly rounding


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
        if abs(work[pivot_row][column]) <= Decimal("1e-30") * scale:
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

    with localcontext() as context:
        context.prec = _PRECISION
        y = [Decimal(v) for v in y_values]  # Decimal(float) keeps every bit of the double

        cols: list[tuple[str, list[Decimal]]] = []
        if const:
            cols.append(("const", [Decimal(1)] * rows))
        for i, c in enumerate(x_columns):
            cols.append((f"slope_{i}", [Decimal(v) for v in c]))

        # Power BI picks the regressors by QR with column pivoting: the intercept first (when there is one), then
        # repeatedly the column with the largest remainder after the chosen ones are projected out, swapped into
        # the next position (so with two identical columns the one that ends up later in the swapped order is the
        # one dropped, and its slope is reported as 0). Measured on 440 fresh Power BI answers. When two different
        # columns tie for the pivot the winner is decided by rounding noise inside Power BI, so that is refused.
        Q: list[list[Decimal]] = []
        kept_indices: list[int] = []
        start = 0
        if const:
            Q.append([Decimal(1) / Decimal(rows).sqrt()] * rows)
            kept_indices.append(0)
            start = 1
        remainders: dict[int, list[Decimal]] = {}
        reference: dict[int, Decimal] = {}
        for idx in range(start, len(cols)):
            col = cols[idx][1]
            v = col[:]
            for q in Q:
                dot = sum((a * b for a, b in zip(v, q)), Decimal(0))
                v = [a - dot * b for a, b in zip(v, q)]
            if const:
                mean = sum(col, Decimal(0)) / rows
                ref_norm_sq = sum(((c - mean) ** 2 for c in col), Decimal(0))
            else:
                ref_norm_sq = sum((c * c for c in col), Decimal(0))
            if ref_norm_sq == 0:
                continue  # an all-constant regressor is absorbed by the intercept (or is zero): never a pivot
            remainders[idx] = v
            reference[idx] = ref_norm_sq
        order = list(remainders)  # candidate positions, swapped like LAPACK's pivot vector
        tied = False
        while order:
            norms = {i: sum((a * a for a in remainders[i]), Decimal(0)) for i in order}
            best = max(norms.values())
            if best <= _SINGULAR * max(reference[i] for i in order if norms[i] == best):
                break
            near = [i for i in order if norms[i] >= best * (1 - _TIE)]
            winner = near[0]
            for other in near[1:]:
                gap = sum(((a - b) ** 2 for a, b in zip(remainders[winner], remainders[other])), Decimal(0))
                if gap > _TIE * best:
                    tied = True
            position = order.index(winner)
            order[0], order[position] = order[position], order[0]
            order.pop(0)
            norm = norms[winner].sqrt()
            q = [a / norm for a in remainders[winner]]
            Q.append(q)
            kept_indices.append(winner)
            for i in order:
                dot = sum((a * b for a, b in zip(remainders[i], q)), Decimal(0))
                remainders[i] = [a - dot * b for a, b in zip(remainders[i], q)]
        if tied and len(kept_indices) - start < len(remainders):
            raise LinestRefused("Two different regressors tie for the pivot of a rank-deficient design; Power BI's choice there is rounding noise.")

        rank = len(kept_indices)
        degrees = rows - rank
        if degrees <= 0:
            raise LinestRefused("There are not more rows than independent coefficients; Power BI's answer there is not modelled.")

        if rank == 0:
            raise LinestRefused("The design matrix is all zeros.")

        kept_cols = [cols[i][1] for i in kept_indices]
        p = len(kept_cols)
        gram = [[sum(a * b for a, b in zip(kept_cols[i], kept_cols[j])) for j in range(p)] for i in range(p)]
        moment = [sum(a * b for a, b in zip(kept_cols[i], y)) for i in range(p)]
        inv = _invert(gram)
        beta_kept = [sum(inv[i][j] * moment[j] for j in range(p)) for i in range(p)]

        beta = [Decimal(0)] * slopes
        intercept = Decimal(0)
        std_errors = [Decimal(0)] * slopes
        std_error_intercept = Decimal(0)

        fitted = [Decimal(0)] * rows
        for k_idx, orig_idx in enumerate(kept_indices):
            b = beta_kept[k_idx]
            col_name = cols[orig_idx][0]
            if col_name == "const":
                intercept = b
            else:
                s_i = int(col_name.split("_")[1])
                beta[s_i] = b
            for r in range(rows):
                fitted[r] += b * cols[orig_idx][1][r]

        residual_ss = sum((y[r] - fitted[r]) ** 2 for r in range(rows))

        if const:
            mean = sum(y, Decimal(0)) / rows
            total_ss = sum(((v - mean) ** 2 for v in y), Decimal(0))
        else:
            total_ss = sum((v * v for v in y), Decimal(0))

        if total_ss == 0:
            mean = sum(y, Decimal(0)) / rows
            row: dict[str, Any] = {}
            for i in range(slopes):
                row[f"Slope{i + 1}"] = Decimal(0)
            if const:
                row["Intercept"] = _as_double(mean)
            for i in range(slopes):
                row[f"StandardErrorSlope{i + 1}"] = Decimal(0)
            if const:
                row["StandardErrorIntercept"] = Decimal(0)
            row["CoefficientOfDetermination"] = Decimal(1)
            row["StandardError"] = Decimal(0)
            row["FStatistic"] = Decimal(0)
            row["DegreesOfFreedom"] = Decimal(degrees)
            row["RegressionSumOfSquares"] = Decimal(0)
            row["ResidualSumOfSquares"] = Decimal(0)
            return headers, [row]

        if residual_ss <= rows * (_NOISE_FLOOR * max(abs(v) for v in y)) ** 2 or residual_ss <= _RELATIVE_FLOOR**2 * total_ss:
            raise LinestRefused("The fit is perfect to within rounding; Power BI's statistics there are rounding noise.")

        regression_ss = total_ss - residual_ss
        mean_square = residual_ss / degrees
        standard_error = mean_square.sqrt()

        for k_idx, orig_idx in enumerate(kept_indices):
            se = (inv[k_idx][k_idx] * mean_square).sqrt()
            col_name = cols[orig_idx][0]
            if col_name == "const":
                std_error_intercept = se
            else:
                s_i = int(col_name.split("_")[1])
                std_errors[s_i] = se

        df_reg = rank - (1 if const and 0 in kept_indices else 0)
        if df_reg > 0 and mean_square > 0:
            f_stat = (regression_ss / df_reg) / mean_square
        else:
            f_stat = Decimal(0)

        r_squared = regression_ss / total_ss if total_ss > 0 else Decimal(0)

        row = {}
        for i in range(slopes):
            row[f"Slope{i + 1}"] = _as_double(beta[i])
        if const:
            row["Intercept"] = _as_double(intercept)
        for i in range(slopes):
            row[f"StandardErrorSlope{i + 1}"] = _as_double(std_errors[i])
        if const:
            row["StandardErrorIntercept"] = _as_double(std_error_intercept)
        row["CoefficientOfDetermination"] = _as_double(r_squared)
        row["StandardError"] = _as_double(standard_error)
        row["FStatistic"] = _as_double(f_stat)
        row["DegreesOfFreedom"] = Decimal(degrees)
        row["RegressionSumOfSquares"] = _as_double(regression_ss)
        row["ResidualSumOfSquares"] = _as_double(residual_ss)
    return headers, [row]
