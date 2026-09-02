"""Route admitted claims to typed candidates while prohibiting default promotion."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .extraction_proposals import ExtractionProposal, TargetType


class RoutedObjectType(str, Enum):
    METHOD_ATOM = "MethodAtom"
    PARAMETER_CANDIDATE = "ParameterCandidate"
    RISK_RULE_CANDIDATE = "RiskRuleCandidate"
    REPORTING_REQUIREMENT = "ReportingRequirement"
    FLOW_SLOT_CONTRACT = "FlowSlotContract"
    FLOW_TEMPLATE = "FlowTemplate"
    ADAPTER_DEFINITION = "AdapterDefinition"


class RoutedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_id: str
    object_type: RoutedObjectType
    target_id: str
    claim_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "candidate"
    verification_required: bool = False
    promoted_to_runtime_default: bool = False


def route_proposal(
    proposal: ExtractionProposal, *, claim_id: str, candidate_id: str,
    synthesis_support: str = "insufficient", execution: str = "unavailable",
) -> RoutedCandidate:
    routes = {
        TargetType.METHOD_ATOM: RoutedObjectType.METHOD_ATOM,
        TargetType.PARAMETER_CANDIDATE: RoutedObjectType.PARAMETER_CANDIDATE,
        TargetType.FLOW_SLOT: RoutedObjectType.FLOW_SLOT_CONTRACT,
        TargetType.RISK_RULE: RoutedObjectType.RISK_RULE_CANDIDATE,
        TargetType.REPORTING_REQUIREMENT: RoutedObjectType.REPORTING_REQUIREMENT,
    }
    if proposal.target_type is TargetType.REPRODUCIBILITY_ARTIFACT:
        if proposal.claim_type == "adapter_definition":
            route = RoutedObjectType.ADAPTER_DEFINITION
        elif proposal.claim_type == "flow_template":
            route = RoutedObjectType.FLOW_TEMPLATE
        else:
            raise ValueError("reproducibility_artifact_requires_explicit_route")
    else:
        route = routes[proposal.target_type]
    payload: dict[str, Any] = {
        "source_version_id": proposal.source_version_id, "segment_id": proposal.segment_id,
        "locator": proposal.locator.model_dump(mode="json"), "direction": proposal.direction.value,
        "synthesis_support": synthesis_support,
    }
    if route is RoutedObjectType.PARAMETER_CANDIDATE:
        if proposal.numeric is None:
            raise ValueError("parameter_candidate_requires_numeric_value")
        payload.update({
            "value": proposal.numeric.value, "raw_value": proposal.numeric.raw,
            "unit": proposal.numeric.unit, "applicable_stage": proposal.qualifiers.get("stage", "unknown"),
            "context_conditions": proposal.numeric.context, "verification_run": proposal.extractor_run_id,
        })
    if route is RoutedObjectType.METHOD_ATOM:
        payload["execution"] = execution
    high_risk = route in {RoutedObjectType.PARAMETER_CANDIDATE, RoutedObjectType.RISK_RULE_CANDIDATE}
    high_risk = high_risk or "short_channel" in proposal.target_id or "machine_learning" in proposal.target_id
    return RoutedCandidate(
        candidate_id=candidate_id, object_type=route, target_id=proposal.target_id,
        claim_id=claim_id, payload=payload, verification_required=high_risk,
        promoted_to_runtime_default=False,
    )
