from __future__ import annotations

import numpy as np
import pytest
import statsmodels.api as sm

from fnirs_flow.analysis.contrasts import estimate_contrast
from fnirs_flow.analysis.first_level_solvers import (
    SolverConfig,
    _check_covariance,
    _huber_weights,
    _prais_winsten,
    _weighted_fit,
    fit_first_level,
)


def test_ols_beta_covariance_and_contrast_are_reconstructable():
    x = np.c_[np.ones(50), np.linspace(-1, 1, 50)]
    y = x @ np.array([2.0, 3.0]) + np.sin(np.arange(50)) * 0.01
    fit = fit_first_level(y, x, solver_requested="ols")
    assert fit["solver_effective"] == "ols"
    assert np.allclose(fit["beta"], [2, 3], atol=0.01)
    result = estimate_contrast(fit, np.array([0.0, 1.0]))
    assert np.isclose(result["estimate"], fit["beta"][1])
    assert result["covariance"] >= 0


def test_ar1_is_effective_prewhitening_not_ols_label():
    rng = np.random.default_rng(7)
    x = np.c_[np.ones(100), np.linspace(-1, 1, 100)]
    noise = np.zeros(100)
    for i in range(1, 100):
        noise[i] = 0.7 * noise[i - 1] + rng.normal(scale=0.1)
    fit = fit_first_level(x @ np.array([1.0, 2.0]) + noise, x, solver_requested="ar1")
    assert fit["solver_effective"] == "ar1"
    assert abs(fit["ar1_rho"]) > 0.1
    assert np.asarray(fit["covariance"]).shape == (2, 2)


def test_rank_deficient_design_fails_closed():
    x = np.c_[np.ones(20), np.ones(20)]
    with __import__("pytest").raises(ValueError, match="rank deficient"):
        fit_first_level(np.arange(20.0), x, solver_requested="ols")


def test_ols_matches_statsmodels_reference():
    rng = np.random.default_rng(41)
    x = np.c_[np.ones(120), np.linspace(-1, 1, 120), np.sin(np.linspace(0, 4, 120))]
    y = x @ np.array([0.5, -1.2, 0.7]) + rng.normal(scale=0.2, size=120)
    fit = fit_first_level(y, x, solver_requested="ols")
    reference = sm.OLS(y, x).fit()
    assert np.allclose(fit["beta"], reference.params, rtol=1e-12, atol=1e-12)
    assert np.allclose(fit["covariance"], reference.cov_params(), rtol=1e-10, atol=1e-12)
    assert fit["df"] == reference.df_resid


def test_multidimensional_contrast_uses_wald_f():
    x = np.c_[np.ones(80), np.linspace(-1, 1, 80), np.sin(np.linspace(0, 6, 80))]
    y = x @ np.array([1.0, 0.5, -0.25]) + np.cos(np.arange(80)) * 0.02
    fit = fit_first_level(y, x, solver_requested="ols")
    result = estimate_contrast(fit, np.array([[0, 1, 0], [0, 0, 1]]))
    assert result["statistic_type"] == "F"
    assert result["contrast_dimension"] == 2
    assert np.asarray(result["covariance_matrix"]).shape == (2, 2)


def test_ar1_matches_explicit_final_prais_winsten_fit():
    rng = np.random.default_rng(17)
    x = np.c_[np.ones(160), np.linspace(-1, 1, 160), np.sin(np.linspace(0, 5, 160))]
    noise = np.zeros(160)
    for index in range(1, len(noise)):
        noise[index] = 0.55 * noise[index - 1] + rng.normal(scale=0.15)
    y = x @ np.array([0.2, 1.1, -0.4]) + noise
    fit = fit_first_level(y, x, solver_requested="ar1")
    whitened_x, whitened_y = _prais_winsten(x, y, float(fit["ar1_rho"]), True)
    reference_beta = np.linalg.lstsq(whitened_x, whitened_y, rcond=None)[0]
    reference = sm.OLS(whitened_y, whitened_x).fit()
    assert np.allclose(fit["beta"], reference_beta, rtol=1e-10, atol=1e-12)
    assert np.allclose(fit["covariance"], reference.cov_params(), rtol=1e-9, atol=1e-12)


def test_ar1_irls_matches_explicit_staged_reference():
    rng = np.random.default_rng(23)
    x = np.c_[np.ones(140), np.linspace(-1, 1, 140)]
    y = x @ np.array([1.0, -0.8]) + rng.normal(scale=0.1, size=140)
    y[[20, 70, 120]] += [2.0, -2.5, 1.8]
    config = SolverConfig()
    fit = fit_first_level(y, x, solver_requested="ar1_irls", solver_config=config)
    whitened_x, whitened_y = _prais_winsten(x, y, float(fit["ar1_rho"]), True)
    beta = np.linalg.lstsq(whitened_x, whitened_y, rcond=None)[0]
    weights = np.ones(len(whitened_y))
    for _ in range(config.irls_max_iterations):
        next_weights, _ = _huber_weights(whitened_y - whitened_x @ beta, config.huber_c)
        next_beta, _ = _weighted_fit(whitened_y, whitened_x, next_weights, config.rank_rcond)
        if (
            np.max(np.abs(next_beta - beta)) <= config.irls_beta_tolerance
            and np.max(np.abs(next_weights - weights)) <= config.irls_weight_tolerance
        ):
            beta, weights = next_beta, next_weights
            break
        beta, weights = next_beta, next_weights
    assert np.allclose(fit["beta"], beta, rtol=1e-11, atol=1e-12)
    assert np.allclose(fit["weights"], weights, rtol=1e-11, atol=1e-12)


def test_ar_and_irls_nonconvergence_fail_closed():
    x = np.c_[np.ones(60), np.linspace(-1, 1, 60)]
    y = x @ np.array([1.0, 2.0]) + np.sin(np.arange(60))
    with pytest.raises(ValueError, match="AR_NOT_CONVERGED"):
        fit_first_level(
            y,
            x,
            solver_requested="ar1",
            solver_config=SolverConfig(ar_max_iterations=1, ar_tolerance=0.0),
        )
    with pytest.raises(ValueError, match="IRLS_NOT_CONVERGED"):
        fit_first_level(
            y + (np.arange(60) == 15) * 20,
            x,
            solver_requested="ar1_irls",
            solver_config=SolverConfig(irls_max_iterations=1),
        )


def test_covariance_numeric_gates_honor_tolerances():
    config = SolverConfig(covariance_symmetry_atol=1e-6, covariance_psd_tolerance=1e-6)
    _check_covariance(np.array([[1.0, 1e-8], [0.0, 1.0]]), config)
    _check_covariance(np.array([[1.0, 0.0], [0.0, -5e-7]]), config)
    with pytest.raises(ValueError, match="COVARIANCE_ASYMMETRIC"):
        _check_covariance(np.array([[1.0, 1e-3], [0.0, 1.0]]), config)
    with pytest.raises(ValueError, match="COVARIANCE_NOT_PSD"):
        _check_covariance(np.array([[1.0, 0.0], [0.0, -1e-3]]), config)
