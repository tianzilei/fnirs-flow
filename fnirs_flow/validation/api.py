"""Top-level validation API combining schema, graph, adapter, security, and state checks."""

from __future__ import annotations

from fnirs_flow.flow.models import FlowGraph
from fnirs_flow.flow.schemas import validate_flow_dict
from fnirs_flow.registry.validators import validate_scenario_constraints
from fnirs_flow.security.validation import validate_security
from fnirs_flow.validation.adapters import validate_adapters
from fnirs_flow.validation.graph import validate_graph
from fnirs_flow.validation.models import ValidationReport
from fnirs_flow.validation.state import (
    validate_adapter_tags,
    validate_node_states,
    validate_state_contracts,
)


def validate_flow(flow_dict: dict, scenario_id: str | None = None) -> ValidationReport:
    """Run all validation checks on a flow dict. Returns ValidationReport.

    Validation order:
    1. Schema validation (JSON Schema)
    2. Graph validation (structure, connectivity, cycles)
    3. Adapter validation (type compatibility)
    4. Security validation (capability manifests, trust levels)
    5. State validation (node states)
    6. Ingress/egress state-contract validation
    7. Adapter tag validation
    8. Custom node safety (for project_custom/imported_custom nodes)
    9. Scenario-specific validation (if scenario_id provided)
    """
    report = ValidationReport()

    # 1. Schema validation
    schema_errors = validate_flow_dict(flow_dict)
    report.errors.extend(schema_errors)

    if schema_errors:
        # If schema is invalid, we can't trust the model parsing
        report.readiness = report.derive_readiness()
        return report

    # 2. Parse to model
    try:
        flow = FlowGraph.model_validate(flow_dict)
    except Exception as e:
        report.errors.append(f"Flow model parsing failed: {e}")
        report.readiness = report.derive_readiness()
        return report

    # 3. Graph validation
    graph_errors, graph_warnings, graph_risks = validate_graph(flow)
    report.errors.extend(graph_errors)
    report.warnings.extend(graph_warnings)
    report.risks.extend(graph_risks)

    # 4. Adapter validation
    adapter_risks = validate_adapters(flow)
    report.risks.extend(adapter_risks)

    # 5. Security validation
    security_risks = validate_security(flow)
    report.risks.extend(security_risks)

    # 6. State validation
    state_risks = validate_node_states(flow)
    report.risks.extend(state_risks)

    # 7. Ingress/egress state-contract validation
    contract_risks = validate_state_contracts(flow)
    report.risks.extend(contract_risks)

    # 8. Adapter tag validation
    tag_risks = validate_adapter_tags(flow)
    report.risks.extend(tag_risks)

    # 9. Scenario-specific validation
    if scenario_id:
        scenario_risks = validate_scenario_constraints(flow, scenario_id)
        report.risks.extend(scenario_risks)

    report.readiness = report.derive_readiness()
    return report
