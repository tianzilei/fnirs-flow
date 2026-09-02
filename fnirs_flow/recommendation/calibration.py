"""Release-gate evaluation for calibrated recommendation rollouts."""

from __future__ import annotations

from dataclasses import dataclass

SCENARIOS = (
    "task_glm",
    "short_channel",
    "motion_correction",
    "resting_state",
    "mobile",
    "group_analysis",
    "leakage_safe_ml",
)


@dataclass(frozen=True)
class CalibrationMetrics:
    """Metrics supplied by an independently annotated calibration/holdout run."""

    hard_exclusion_errors_calibration: int
    hard_exclusion_errors_holdout: int
    unsafe_best_errors_calibration: int
    unsafe_best_errors_holdout: int
    accepted_top3_fraction: float
    explanation_completeness: float
    deterministic: bool
    scenarios: tuple[str, ...] = SCENARIOS


@dataclass(frozen=True)
class ReleaseGateResult:
    passed: bool
    failures: tuple[str, ...]


def evaluate_release_gates(metrics: CalibrationMetrics | None) -> ReleaseGateResult:
    """Evaluate the v1.3.0 publication gates without deriving a gold standard."""
    if metrics is None:
        return ReleaseGateResult(False, ("calibration/holdout metrics not supplied",))
    failures: list[str] = []
    if set(metrics.scenarios) != set(SCENARIOS):
        failures.append("all seven required scenarios are not covered")
    if metrics.hard_exclusion_errors_calibration or metrics.hard_exclusion_errors_holdout:
        failures.append("hard exclusion entered an eligible set")
    if metrics.unsafe_best_errors_calibration or metrics.unsafe_best_errors_holdout:
        failures.append("unsafe best recommendation was produced")
    if metrics.accepted_top3_fraction < 0.90:
        failures.append("accepted top-3 fraction is below 0.90")
    if metrics.explanation_completeness < 1.0:
        failures.append("candidate explanation completeness is below 1.0")
    if not metrics.deterministic:
        failures.append("repeat/shuffled-input determinism gate failed")
    return ReleaseGateResult(not failures, tuple(failures))
