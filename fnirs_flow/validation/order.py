"""Atom ordering and empty-link risk validation."""

from __future__ import annotations

from typing import Any

from fnirs_flow.flow.models import FlowAtom, FlowGraph
from fnirs_flow.validation.models import RiskItem

CATEGORY_ORDER: dict[str, int] = {
    "data": 0,
    "design": 1,
    "preprocessing": 2,
    "analysis": 3,
    "output": 4,
    "validation": 5,
    "export": 6,
}


def _category_value(atom: FlowAtom) -> str:
    return atom.category.value if hasattr(atom.category, "value") else str(atom.category)


def _metadata_contract(atom: FlowAtom) -> dict[str, Any]:
    contract = atom.metadata.get("order_contract", {})
    return contract if isinstance(contract, dict) else {}


def _allowed_categories(contract: dict[str, Any], key: str) -> set[str]:
    value = contract.get(key, [])
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value}


def _risk_severity(allowed: bool, strict: str = "fatal") -> str:
    return "high" if allowed and strict == "fatal" else ("medium" if allowed else strict)


def _is_empty_marker(atom: FlowAtom) -> bool:
    return (
        atom.operation == "empty_marker" or atom.atom_type == "empty_marker" or atom.metadata.get("empty_atom") is True
    )


def validate_empty_link_policy(flow: FlowGraph) -> list[RiskItem]:
    """Flag flows that are structurally empty or leave required inputs floating."""
    risks: list[RiskItem] = []
    allow_empty_edges = flow.metadata.order_policy.allow_empty_edges
    empty_markers = [atom for atom in flow.flow_atoms if _is_empty_marker(atom)]

    if len(flow.flow_atoms) > 1 and not flow.edges:
        if allow_empty_edges and empty_markers:
            risks.append(
                RiskItem(
                    risk_id="atom-empty-markers-active",
                    code="ATOM_EMPTY_MARKERS_ACTIVE",
                    severity="medium",
                    domain="graph",
                    affected_object=f"flow:{flow.flow_id}",
                    message=(
                        f"Flow has {len(empty_markers)} explicit empty marker atom(s); these stages "
                        "will update state metadata without running processing"
                    ),
                    suggested_action=(
                        "Connect real processing atoms when available, or keep the empty markers "
                        "as documented no-op decisions"
                    ),
                )
            )
            return risks
        risks.append(
            RiskItem(
                risk_id="atom-empty-flow-no-edges",
                code="ATOM_EMPTY_FLOW",
                severity=_risk_severity(allow_empty_edges),
                domain="graph",
                affected_object=f"flow:{flow.flow_id}",
                message="Flow has multiple atoms but no edges, so execution order and data flow are undefined",
                suggested_action=(
                    "Connect compatible atom ports, or enable metadata.order_policy.allow_empty_edges "
                    "to accept this as a reviewed risk"
                ),
            )
        )

    connected_inputs = {(edge.target, edge.target_handle) for edge in flow.edges}
    for atom in flow.flow_atoms:
        for port in atom.ports:
            if port.direction != "in" or not port.required:
                continue
            if (atom.id, port.name) in connected_inputs:
                continue
            risks.append(
                RiskItem(
                    risk_id=f"atom-required-input-unconnected-{atom.id}-{port.name}",
                    code="ATOM_REQUIRED_INPUT_UNCONNECTED",
                    severity="low" if allow_empty_edges else "high",
                    domain="graph",
                    affected_object=f"atom:{atom.id}",
                    message=f"Atom '{atom.id}' required input port '{port.name}' is not connected",
                    suggested_action=(
                        "Connect this input, provide an explicit source/configured no-op, or enable "
                        "metadata.order_policy.allow_empty_edges to accept empty handling as a risk"
                    ),
                )
            )

    return risks


def validate_atom_order_contracts(flow: FlowGraph) -> list[RiskItem]:
    """Validate that edges move forward through MethodAtom stages."""
    risks: list[RiskItem] = []
    allow_order_violations = flow.metadata.order_policy.allow_order_violations
    node_map = {node.id: node for node in flow.flow_atoms}

    for edge in flow.edges:
        source = node_map.get(edge.source)
        target = node_map.get(edge.target)
        if source is None or target is None:
            continue

        source_category = _category_value(source)
        target_category = _category_value(target)
        source_rank = CATEGORY_ORDER.get(source_category)
        target_rank = CATEGORY_ORDER.get(target_category)
        if source_rank is None or target_rank is None:
            continue

        source_contract = _metadata_contract(source)
        target_contract = _metadata_contract(target)
        source_downstream = _allowed_categories(source_contract, "allowed_downstream_categories")
        target_upstream = _allowed_categories(target_contract, "allowed_upstream_categories")
        explicit_exception = (source_downstream and target_category in source_downstream) or (
            target_upstream and source_category in target_upstream
        )

        contract_violation = False
        if source_downstream and target_category not in source_downstream:
            contract_violation = True
        if target_upstream and source_category not in target_upstream:
            contract_violation = True

        rank_violation = source_rank > target_rank and not explicit_exception
        if not rank_violation and not contract_violation:
            continue

        risks.append(
            RiskItem(
                risk_id=f"atom-order-violation-{edge.id}",
                code="ATOM_ORDER_VIOLATION",
                severity=_risk_severity(allow_order_violations),
                domain="graph",
                affected_object=f"edge:{edge.id}",
                message=(
                    f"Edge '{edge.id}' connects {source_category} atom '{source.id}' "
                    f"to earlier-stage {target_category} atom '{target.id}'"
                ),
                rationale="Atom execution order is derived from edges, not canvas y-position.",
                suggested_action=(
                    "Reverse or remove the edge, add an explicit adapter/design exception, or enable "
                    "metadata.order_policy.allow_order_violations to accept this as a reviewed risk"
                ),
            )
        )

    return risks


def validate_order_and_empty_policy(flow: FlowGraph) -> list[RiskItem]:
    """Run all order and empty-link policy checks."""
    return [*validate_empty_link_policy(flow), *validate_atom_order_contracts(flow)]
