from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
from scipy import stats

from fnirs_flow.analysis.numerics import finite_pinv


def _matrix_vector(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    """Multiply finite operands without unsupported-BLAS warning noise.

    NumPy 1.26 on Python 3.13 can emit spurious ``matmul`` floating-point
    warnings for finite operands. ``einsum`` performs the same contraction
    while explicit finite checks preserve fail-closed numerical behavior.
    """
    if not np.isfinite(matrix).all() or not np.isfinite(vector).all():
        raise ValueError("matrix-vector operands must be finite")
    result = np.einsum("ij,j->i", matrix, vector, optimize=True)
    if not np.isfinite(result).all():
        raise ValueError("matrix-vector result must be finite")
    return cast(np.ndarray, result)


@dataclass(frozen=True)
class SolverConfig:
    rank_rcond: float | None = None
    rho_bound: float = 0.99
    ar_max_iterations: int = 50
    ar_tolerance: float = 1e-8
    prais_winsten_first_row: bool = True
    huber_c: float = 1.345
    irls_max_iterations: int = 50
    irls_beta_tolerance: float = 1e-10
    irls_weight_tolerance: float = 1e-8
    minimum_effective_weight: float = 1e-8
    robust_covariance: str = "HC0_sandwich"
    covariance_symmetry_atol: float = 1e-12
    covariance_symmetry_rtol: float = 1e-8
    covariance_psd_tolerance: float = 1e-10


def _weighted_fit(y: np.ndarray, x: np.ndarray, weights: np.ndarray, rcond: float | None):
    sw = np.sqrt(weights)
    xw, yw = x * sw[:, None], y * sw
    beta = np.linalg.lstsq(xw, yw, rcond=rcond)[0]
    return beta, y - _matrix_vector(x, beta)


def _prais_winsten(x: np.ndarray, y: np.ndarray, rho: float, keep_first: bool):
    xt, yt = x[1:] - rho * x[:-1], y[1:] - rho * y[:-1]
    if keep_first:
        scale = np.sqrt(max(1.0 - rho * rho, 0.0))
        xt, yt = np.vstack((scale * x[0], xt)), np.concatenate(([scale * y[0]], yt))
    return xt, yt


def _estimate_rho(residuals: np.ndarray, bound: float) -> float:
    denominator = float(np.einsum("i,i->", residuals[:-1], residuals[:-1], optimize=True))
    if denominator <= 0 or not np.isfinite(denominator):
        return 0.0
    numerator = float(np.einsum("i,i->", residuals[1:], residuals[:-1], optimize=True))
    rho = numerator / denominator
    if not np.isfinite(rho):
        raise ValueError("AR_RHO_NONFINITE")
    return float(np.clip(rho, -bound, bound))


def _huber_weights(residuals: np.ndarray, c: float) -> tuple[np.ndarray, float]:
    scale = float(1.4826 * np.median(np.abs(residuals - np.median(residuals))))
    if not np.isfinite(scale) or scale <= np.finfo(float).eps:
        scale = float(np.sqrt(np.mean(residuals**2)))
    if not np.isfinite(scale) or scale <= np.finfo(float).eps:
        return np.ones(len(residuals)), max(scale, float(np.finfo(float).eps))
    standardized = np.abs(residuals) / scale
    weights = np.ones(len(residuals))
    mask = standardized > c
    weights[mask] = c / standardized[mask]
    return weights, scale


def _covariance(x, residuals, weights, df, method, rcond):
    sw = np.sqrt(weights)
    xw, ew = x * sw[:, None], residuals * sw
    gram = np.einsum("ni,nj->ij", xw, xw, optimize=True)
    bread = finite_pinv(gram, rcond=rcond or 1e-15)
    if method.casefold() in {"hc0_sandwich", "sandwich_hc0"}:
        score = xw * ew[:, None]
        score_gram = np.einsum("ni,nj->ij", score, score, optimize=True)
        return np.einsum("ij,jk,kl->il", bread, score_gram, bread, optimize=True)
    residual_sum_squares = float(np.einsum("i,i->", ew, ew, optimize=True))
    return residual_sum_squares / df * bread


def _check_covariance(covariance: np.ndarray, config: SolverConfig) -> None:
    if not np.isfinite(covariance).all():
        raise ValueError("COVARIANCE_NONFINITE")
    if not np.allclose(
        covariance, covariance.T, atol=config.covariance_symmetry_atol, rtol=config.covariance_symmetry_rtol
    ):
        raise ValueError("COVARIANCE_ASYMMETRIC")
    minimum = float(np.min(np.linalg.eigvalsh((covariance + covariance.T) / 2)))
    scale = max(float(np.max(np.abs(np.diag(covariance)))), 1.0)
    if minimum < -config.covariance_psd_tolerance * scale:
        raise ValueError("COVARIANCE_NOT_PSD")


def fit_first_level(
    y: np.ndarray,
    x: np.ndarray,
    *,
    solver_requested: str = "ols",
    robust: bool = False,
    max_iter: int | None = None,
    huber_c: float | None = None,
    fallback_policy: str = "forbid",
    solver_config: SolverConfig | None = None,
) -> dict[str, object]:
    y, x = np.asarray(y, float), np.asarray(x, float)
    config = solver_config or SolverConfig()
    overrides: dict[str, int | float] = {}
    if max_iter is not None:
        overrides["irls_max_iterations"] = max_iter
    if huber_c is not None:
        overrides["huber_c"] = huber_c
    if overrides:
        config = SolverConfig(**{**config.__dict__, **overrides})
    requested = solver_requested.casefold()
    if robust and requested == "ar1":
        requested = "ar1_irls"
    if requested not in {"ols", "ar1", "ar1_irls"}:
        raise ValueError(f"unsupported solver: {solver_requested}")
    if fallback_policy not in {"forbid", "allow_explicit"}:
        raise ValueError("fallback_policy must be 'forbid' or 'allow_explicit'")
    if y.ndim != 1 or x.ndim != 2 or len(y) != x.shape[0]:
        raise ValueError("y and x dimensions do not match")
    if not np.isfinite(y).all() or not np.isfinite(x).all():
        raise ValueError("NONFINITE_SOLVER_INPUT")
    rank = int(np.linalg.matrix_rank(x, tol=config.rank_rcond))
    if rank < x.shape[1]:
        raise ValueError("design matrix is rank deficient")

    beta, _ = _weighted_fit(y, x, np.ones(len(y)), config.rank_rcond)
    rho, ar_iterations, ar_converged, fit_x, fit_y = 0.0, 0, True, x, y
    if requested.startswith("ar1"):
        ar_converged, previous_beta = False, beta
        for ar_iterations in range(1, config.ar_max_iterations + 1):
            new_rho = _estimate_rho(y - _matrix_vector(x, previous_beta), config.rho_bound)
            fit_x, fit_y = _prais_winsten(x, y, new_rho, config.prais_winsten_first_row)
            beta, _ = _weighted_fit(fit_y, fit_x, np.ones(len(fit_y)), config.rank_rcond)
            if (
                abs(new_rho - rho) <= config.ar_tolerance
                and np.max(np.abs(beta - previous_beta)) <= config.ar_tolerance
            ):
                rho, ar_converged = new_rho, True
                break
            rho, previous_beta = new_rho, beta
        if not ar_converged:
            raise ValueError("AR_NOT_CONVERGED")

    weights = np.ones(len(fit_y))
    irls_iterations, irls_converged, robust_scale = 0, requested != "ar1_irls", None
    if requested == "ar1_irls":
        irls_converged = False
        for irls_iterations in range(1, config.irls_max_iterations + 1):
            new_weights, robust_scale = _huber_weights(
                fit_y - _matrix_vector(fit_x, beta), config.huber_c
            )
            if float(np.sum(new_weights >= config.minimum_effective_weight)) <= rank:
                raise ValueError("INSUFFICIENT_EFFECTIVE_WEIGHT")
            beta_new, _ = _weighted_fit(fit_y, fit_x, new_weights, config.rank_rcond)
            beta_delta = float(np.max(np.abs(beta_new - beta)))
            weight_delta = float(np.max(np.abs(new_weights - weights)))
            beta, weights = beta_new, new_weights
            if beta_delta <= config.irls_beta_tolerance and weight_delta <= config.irls_weight_tolerance:
                irls_converged = True
                break
        if not irls_converged:
            raise ValueError("IRLS_NOT_CONVERGED")

    residuals = y - _matrix_vector(x, beta)
    fit_residuals = fit_y - _matrix_vector(fit_x, beta)
    fit_rank = int(np.linalg.matrix_rank(fit_x * np.sqrt(weights)[:, None], tol=config.rank_rcond))
    df = int(np.sum(weights >= config.minimum_effective_weight)) - fit_rank
    if df <= 0:
        raise ValueError("INSUFFICIENT_RESIDUAL_DF")
    robust_method = config.robust_covariance if requested == "ar1_irls" else "model_based"
    covariance = _covariance(fit_x, fit_residuals, weights, df, robust_method, config.rank_rcond)
    _check_covariance(covariance, config)
    covariance_method = (
        "HC0_sandwich_whitened"
        if requested == "ar1_irls"
        else ("model_based_prais_winsten" if requested == "ar1" else "model_based_ols")
    )
    se = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    statistic = np.divide(beta, se, out=np.full_like(beta, np.nan), where=se > 0)
    return {
        "beta": beta,
        "covariance": covariance,
        "standard_error": se,
        "statistic": statistic,
        "p_value": 2 * stats.t.sf(np.abs(statistic), df),
        "df": df,
        "solver_requested": requested,
        "solver_effective": requested,
        "solver_version": "processed_hb_solver_v2",
        "ar1_rho": rho,
        "ar_iterations": ar_iterations,
        "ar_converged": ar_converged,
        "irls_iterations": irls_iterations,
        "irls_converged": irls_converged,
        "robust_scale": robust_scale,
        "weights": weights,
        "residuals": residuals,
        "whitened_residuals": fit_residuals,
        "covariance_method": covariance_method,
        "calculation_status": "success",
        "reason_code": "",
    }
