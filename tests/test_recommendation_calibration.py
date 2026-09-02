from fnirs_flow.recommendation import CalibrationMetrics, evaluate_release_gates


def test_release_gates_fail_closed_without_metrics() -> None:
    result = evaluate_release_gates(None)
    assert not result.passed


def test_release_gates_require_all_scenarios_and_thresholds() -> None:
    result = evaluate_release_gates(
        CalibrationMetrics(
            hard_exclusion_errors_calibration=0,
            hard_exclusion_errors_holdout=0,
            unsafe_best_errors_calibration=0,
            unsafe_best_errors_holdout=0,
            accepted_top3_fraction=0.95,
            explanation_completeness=1.0,
            deterministic=True,
        )
    )
    assert result.passed
