"""Scenario-specific validation rules.

MethodAtom-first: uses atom_type for scenario validation, with
fallback to legacy node type for backward compatibility.
"""

from __future__ import annotations

from fnirs_flow.flow.models import FlowGraph
from fnirs_flow.registry.scenarios import ScenarioDefinition, ScenarioRegistry
from fnirs_flow.validation.models import RiskItem


def validate_scenario_constraints(
    flow: FlowGraph,
    scenario_id: str,
    config: dict[str, str | bool | int | float | list[str]] | None = None,
) -> list[RiskItem]:
    """Validate scenario-specific constraints."""
    risks: list[RiskItem] = []
    registry = ScenarioRegistry()
    scenario = registry.get(scenario_id)

    if scenario is None:
        risks.append(
            RiskItem(
                risk_id=f"scenario-unknown-{scenario_id}",
                severity="fatal",
                domain="design",
                message=f"Unknown scenario: {scenario_id}",
                suggested_action="Choose a valid scenario type",
            )
        )
        return risks

    # Check required atom types (MethodAtom-first)
    atom_types = {n.type for n in flow.nodes}
    required_types = scenario.required_atom_types or scenario.required_node_types
    for required_type in required_types:
        if required_type not in atom_types:
            risks.append(
                RiskItem(
                    risk_id=f"scenario-missing-atom-{scenario_id}-{required_type}",
                    severity="high",
                    domain="design",
                    affected_object=f"atom_type:{required_type}",
                    message=f"Scenario '{scenario_id}' requires atom type '{required_type}'",
                    suggested_action=f"Add a '{required_type}' atom to the flow",
                )
            )

    # Scenario-specific validation
    if scenario_id == "task":
        risks.extend(_validate_task_scenario(flow, scenario, config))
    elif scenario_id == "resting_state":
        risks.extend(_validate_resting_state_scenario(flow, scenario, config))
    elif scenario_id == "real_world":
        risks.extend(_validate_real_world_scenario(flow, scenario, config))
    elif scenario_id == "hyperscanning":
        risks.extend(_validate_hyperscanning_scenario(flow, scenario, config))
    elif scenario_id == "machine_learning":
        risks.extend(_validate_ml_scenario(flow, scenario, config))

    return risks


def _validate_task_scenario(
    flow: FlowGraph,
    scenario: ScenarioDefinition,
    config: dict[str, str | bool | int | float | list[str]] | None,
) -> list[RiskItem]:
    """Validate task-specific constraints."""
    risks: list[RiskItem] = []

    # Contrast atom is already checked via required_atom_types in main loop
    # Additional task-specific checks can be added here

    return risks


def _validate_resting_state_scenario(
    flow: FlowGraph,
    scenario: ScenarioDefinition,
    config: dict[str, str | bool | int | float | list[str]] | None,
) -> list[RiskItem]:
    """Validate resting-state specific constraints."""
    risks: list[RiskItem] = []

    # Connectivity atom is already checked via required_atom_types in main loop
    # Additional resting-state specific checks can be added here

    return risks


def _validate_real_world_scenario(
    flow: FlowGraph,
    scenario: ScenarioDefinition,
    config: dict[str, str | bool | int | float | list[str]] | None,
) -> list[RiskItem]:
    """Validate real-world specific constraints."""
    risks: list[RiskItem] = []

    # Event reconstruction atom is already checked via required_atom_types in main loop
    # Additional real-world specific checks can be added here

    return risks


def _validate_hyperscanning_scenario(
    flow: FlowGraph,
    scenario: ScenarioDefinition,
    config: dict[str, str | bool | int | float | list[str]] | None,
) -> list[RiskItem]:
    """Validate hyperscanning specific constraints."""
    risks: list[RiskItem] = []

    # Inter-brain connectivity atom is already checked via required_atom_types in main loop
    # Additional hyperscanning specific checks can be added here

    return risks


def _validate_ml_scenario(
    flow: FlowGraph,
    scenario: ScenarioDefinition,
    config: dict[str, str | bool | int | float | list[str]] | None,
) -> list[RiskItem]:
    """Validate ML-specific constraints."""
    risks: list[RiskItem] = []

    # Check for feature extraction and ML model
    has_features = any(n.type == "feature_extraction" for n in flow.nodes)
    has_model = any(n.type == "ml_model" for n in flow.nodes)

    if not has_features:
        risks.append(
            RiskItem(
                risk_id="ml-no-features",
                severity="high",
                domain="analysis",
                message="ML scenario requires feature extraction",
                suggested_action="Add a feature_extraction atom",
            )
        )

    if not has_model:
        risks.append(
            RiskItem(
                risk_id="ml-no-model",
                severity="high",
                domain="analysis",
                message="ML scenario requires ML model atom",
                suggested_action="Add an ml_model atom",
            )
        )

    # Check for prohibited split strategies
    for node in flow.nodes:
        if node.type == "ml_model":
            split = node.config.get("split_strategy", "")
            # Check against scenario's prohibited list (supports both forms)
            prohibited = scenario.constraints.get("prohibited", [])
            prohibited_expanded = set(prohibited)
            # Also add short forms if long forms are in prohibited
            for p in prohibited:
                if p.endswith("_split"):
                    prohibited_expanded.add(p[:-6])  # random_trial_split -> random_trial
            if split in prohibited_expanded:
                risks.append(
                    RiskItem(
                        risk_id="ml-leakage-risk",
                        severity="fatal",
                        domain="analysis",
                        message=f"Prohibited split strategy: {split}. Use subject_wise or group_wise.",
                        suggested_action="Change split_strategy to subject_wise or group_wise",
                    )
                )

    return risks
