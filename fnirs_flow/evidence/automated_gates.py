"""Versioned release gates for automated evidence snapshots and slot activation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

PRIORITY_SLOTS = frozenset({
    "motion_correction_slot", "filtering_slot", "short_channel_regression_slot",
    "task_glm_slot", "resting_connectivity_slot",
})


class ReleaseMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    locator_exact_match_rate: float = Field(ge=0, le=1)
    schema_and_reference_integrity: float = Field(ge=0, le=1)
    numeric_round_trip_accuracy: float = Field(ge=0, le=1)
    unit_dimension_accuracy: float = Field(ge=0, le=1)
    hard_exclusion_false_accepts: int = Field(ge=0)
    adversarial_false_best: int = Field(ge=0)
    unsupported_claim_admission_rate: float = Field(ge=0, le=1)
    critical_field_cross_model_agreement: float = Field(ge=0, le=1)
    explanation_and_lineage_completeness: float = Field(ge=0, le=1)
    repeatability_failures: int = Field(ge=0)
    corpus_processed_coverage: float = Field(ge=0, le=1)
    claim_extraction_coverage: float = Field(ge=0, le=1)
    admission_coverage: float = Field(ge=0, le=1)


class AutomatedGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    passed: bool
    source_mode: str
    reason_codes: tuple[str, ...]
    failed_metrics: tuple[str, ...] = ()


def evaluate_automated_gates(
    metrics: ReleaseMetrics, *, slot_id: str, independent_fnirs_benchmark: bool,
    distribution_drift: bool = False,
) -> AutomatedGateResult:
    thresholds = {
        "locator_exact_match_rate": metrics.locator_exact_match_rate == 1,
        "schema_and_reference_integrity": metrics.schema_and_reference_integrity == 1,
        "numeric_round_trip_accuracy": metrics.numeric_round_trip_accuracy >= 0.999,
        "unit_dimension_accuracy": metrics.unit_dimension_accuracy == 1,
        "hard_exclusion_false_accepts": metrics.hard_exclusion_false_accepts == 0,
        "adversarial_false_best": metrics.adversarial_false_best == 0,
        "unsupported_claim_admission_rate": metrics.unsupported_claim_admission_rate <= 0.001,
        "critical_field_cross_model_agreement": metrics.critical_field_cross_model_agreement >= 0.99,
        "explanation_and_lineage_completeness": metrics.explanation_and_lineage_completeness == 1,
        "repeatability_failures": metrics.repeatability_failures == 0,
    }
    failed = tuple(sorted(key for key, passed in thresholds.items() if not passed))
    reasons = list(f"release_metric_failed:{item}" for item in failed)
    if slot_id not in PRIORITY_SLOTS:
        reasons.append("slot_outside_v2_release_scope")
    if not independent_fnirs_benchmark:
        reasons.append("independent_fnirs_benchmark_missing")
    if distribution_drift:
        reasons.append("distribution_drift_detected")
    passed = not reasons
    return AutomatedGateResult(
        passed=passed, source_mode="automated_evidence" if passed else "shadow",
        reason_codes=tuple(sorted(reasons)) or ("all_release_gates_passed",), failed_metrics=failed,
    )
