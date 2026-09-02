"""Machine-verifiable appraisal facts without subjective aggregate scoring."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class AppraisalFactValue(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"
    NOT_MACHINE_VERIFIABLE = "not_machine_verifiable"


MACHINE_APPRAISAL_DIMENSIONS = (
    # A7 normative fact dimensions.  Values are tri-state and never mapped
    # directly to a numeric score.
    "full_text_available",
    "study_design_explicit",
    "sample_size_explicit",
    "comparison_explicit",
    "uncertainty_reported",
    "method_parameters_reported",
    "population_context_explicit",
    "outcome_definition_explicit",
    "limitations_reported",
    "independence_resolved",
    # Legacy dimensions retained for backward-compatible profile replay.
    "source_completeness",
    "sample_traceability",
    "acquisition_parameters_complete",
    "preprocessing_complete",
    "qc_reported",
    "statistical_or_ml_leakage_addressed",
    "open_materials",
    "reproducibility_information",
)


class MachineAppraisalFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dimension: str
    value: AppraisalFactValue
    input_claim_ids: tuple[str, ...] = ()
    locator_ids: tuple[str, ...] = ()
    rule_id: str
    reason_code: str


class MachineAppraisal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    appraisal_id: str
    object_id: str
    profile_version: str
    facts: tuple[MachineAppraisalFact, ...]
    score: None = None


def appraise_facts(
    *,
    appraisal_id: str,
    object_id: str,
    profile_version: str,
    observed: dict[str, tuple[AppraisalFactValue, tuple[str, ...], tuple[str, ...], str]],
) -> MachineAppraisal:
    facts = []
    for dimension in MACHINE_APPRAISAL_DIMENSIONS:
        value, claims, locators, reason = observed.get(
            dimension, (AppraisalFactValue.UNKNOWN, (), (), "missing_machine_verifiable_evidence")
        )
        # A positive/negative machine fact must be traceable to both an input
        # claim and a locator.  Otherwise preserve uncertainty explicitly.
        if value not in {AppraisalFactValue.UNKNOWN, AppraisalFactValue.NOT_APPLICABLE} and (
            not claims or not locators
        ):
            value = AppraisalFactValue.UNKNOWN
            reason = "missing_fact_provenance"
            claims = ()
            locators = ()
        facts.append(
            MachineAppraisalFact(
                dimension=dimension,
                value=value,
                input_claim_ids=claims,
                locator_ids=locators,
                rule_id=f"{profile_version}:{dimension}",
                reason_code=reason,
            )
        )
    return MachineAppraisal(
        appraisal_id=appraisal_id,
        object_id=object_id,
        profile_version=profile_version,
        facts=tuple(facts),
    )
