from __future__ import annotations

from typing import cast

import numpy as np
from scipy import stats

from fnirs_flow.analysis.numerics import finite_pinv


def estimate_contrast(
    fit: dict[str, object], weights: np.ndarray, *, contrast_id: str = "contrast"
) -> dict[str, object]:
    c = np.asarray(weights, float)
    beta, cov = np.asarray(fit["beta"], float), np.asarray(fit["covariance"], float)
    if c.ndim == 1:
        c = c[None, :]
    if c.ndim != 2 or c.shape[1] != len(beta) or c.shape[0] < 1:
        raise ValueError("contrast weights do not match design")
    if not np.isfinite(c).all() or np.allclose(c, 0):
        raise ValueError("contrast is non-finite or all zero")
    estimate = np.einsum("ij,j->i", c, beta, optimize=True)
    contrast_covariance = np.einsum("ij,jk,lk->il", c, cov, c, optimize=True)
    contrast_covariance = (contrast_covariance + contrast_covariance.T) / 2
    if not np.isfinite(contrast_covariance).all():
        raise ValueError("CONTRAST_COVARIANCE_NONFINITE")
    df = int(cast(int | float | str, fit["df"]))
    if c.shape[0] == 1:
        variance = float(contrast_covariance[0, 0])
        if variance < 0:
            raise ValueError("CONTRAST_COVARIANCE_NOT_PSD")
        se = float(np.sqrt(variance))
        statistic = float(estimate[0] / se) if se > 0 else float("nan")
        p_value = float(2 * stats.t.sf(abs(statistic), df)) if np.isfinite(statistic) else float("nan")
        return {
            "contrast_id": contrast_id,
            "contrast_dimension": 1,
            "estimate": float(estimate[0]),
            "standard_error": se,
            "statistic": statistic,
            "statistic_type": "t",
            "df": df,
            "df_numerator": 1,
            "df_denominator": df,
            "p_value": p_value,
            "covariance": variance,
            "covariance_matrix": contrast_covariance.tolist(),
            "weights": c[0].tolist(),
        }
    dimension = c.shape[0]
    if np.linalg.matrix_rank(contrast_covariance) != dimension:
        raise ValueError("CONTRAST_COVARIANCE_SINGULAR")
    inverse_estimate = np.einsum(
        "ij,j->i", finite_pinv(contrast_covariance), estimate, optimize=True
    )
    statistic = float(np.einsum("i,i->", estimate, inverse_estimate, optimize=True) / dimension)
    return {
        "contrast_id": contrast_id,
        "contrast_dimension": dimension,
        "estimate": None,
        "estimate_vector": estimate.tolist(),
        "standard_error": None,
        "statistic": statistic,
        "statistic_type": "F",
        "df": df,
        "df_numerator": dimension,
        "df_denominator": df,
        "p_value": float(stats.f.sf(statistic, dimension, df)),
        "covariance": None,
        "covariance_matrix": contrast_covariance.tolist(),
        "weights": c.tolist(),
    }
