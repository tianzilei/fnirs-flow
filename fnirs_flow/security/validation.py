"""Security validation for executable atoms."""

from __future__ import annotations

from fnirs_flow.flow.models import FlowGraph
from fnirs_flow.validation.models import RiskItem
from fnirs_flow.validation.state import validate_custom_node_safety


def validate_security(flow: FlowGraph) -> list[RiskItem]:
    """Check security constraints on executable atoms.

    Delegates per-atom checks to validate_custom_node_safety.
    Returns list of RiskItems.
    """
    risks: list[RiskItem] = []
    for node in flow.nodes:
        risks.extend(validate_custom_node_safety(node))
    return risks
