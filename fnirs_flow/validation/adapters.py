"""Adapter compatibility validation: checks atom port schema matching."""

from __future__ import annotations

from fnirs_flow.flow.models import FlowGraph
from fnirs_flow.validation.models import RiskItem


def validate_adapters(flow: FlowGraph) -> list[RiskItem]:
    """Check adapter compatibility across edges. Returns list of RiskItems."""
    risks: list[RiskItem] = []
    node_map = {n.id: n for n in flow.nodes}
    adapter_map = {a.adapter_id: a for a in flow.adapter_registry}

    # Check for mixed backend usage without bridge
    backend_atoms = {}
    for node in flow.nodes:
        if node.backend_binding:
            backend_atoms[node.id] = node.backend_binding.backend_id

    # Check edges for mixed backend connections
    for edge in flow.edges:
        source_backend = backend_atoms.get(edge.source)
        target_backend = backend_atoms.get(edge.target)

        # If both have backends and they're different, check for bridge
        if source_backend and target_backend and source_backend != target_backend:
            # Check if there's an adapter that can bridge them
            has_bridge = False
            if edge.adapter_id:
                adapter = adapter_map.get(edge.adapter_id)
                if adapter and hasattr(adapter, 'bridge_backends'):
                    has_bridge = True

            if not has_bridge:
                risks.append(
                    RiskItem(
                        risk_id=f"backend-bridge-required-{edge.id}",
                        code="BACKEND_BRIDGE_REQUIRED",
                        severity="fatal",
                        domain="adapter",
                        affected_object=f"edge:{edge.id}",
                        message=(
                            f"Mixed backend connection without bridge: "
                            f"{source_backend} -> {target_backend}"
                        ),
                        suggested_action="Add an adapter that bridges these backends or use the same backend",
                    )
                )

    for edge in flow.edges:
        source_atom = node_map.get(edge.source)
        target_atom = node_map.get(edge.target)
        if not source_atom or not target_atom:
            continue

        # Find output port schema
        source_port = None
        for p in source_atom.ports:
            if p.name == edge.source_handle and p.direction == "out":
                source_port = p
                break

        # Find input port schema
        target_port = None
        for p in target_atom.ports:
            if p.name == edge.target_handle and p.direction == "in":
                target_port = p
                break

        if not source_port or not target_port:
            risks.append(
                RiskItem(
                    risk_id=f"adapter-missing-port-{edge.id}",
                    code="ADAPTER_MISSING_PORT",
                    severity="high",
                    domain="adapter",
                    affected_object=f"edge:{edge.id}",
                    message=f"Edge '{edge.id}' references non-existent port on atom",
                    suggested_action="Check port names on source/target atoms",
                )
            )
            continue

        # Check if schemas match directly
        if source_port.port_schema == target_port.port_schema:
            continue

        # Check if an adapter is specified or can resolve
        if edge.adapter_id:
            adapter = adapter_map.get(edge.adapter_id)
            if adapter:
                # Verify adapter matches the types
                if adapter.source_type != source_port.port_schema or adapter.target_type != target_port.port_schema:
                    risks.append(
                        RiskItem(
                            risk_id=f"adapter-type-mismatch-{edge.id}",
                            code="ADAPTER_TYPE_MISMATCH",
                            severity="medium",
                            domain="adapter",
                            affected_object=f"edge:{edge.id}",
                            message=(
                                f"Adapter '{edge.adapter_id}' type mismatch: "
                                f"expected {source_port.port_schema}->{target_port.port_schema}, "
                                f"got {adapter.source_type}->{adapter.target_type}"
                            ),
                            suggested_action="Update adapter or edge configuration",
                        )
                    )
            else:
                risks.append(
                    RiskItem(
                        risk_id=f"adapter-not-found-{edge.id}",
                        code="ADAPTER_NOT_FOUND",
                        severity="fatal",
                        domain="adapter",
                        affected_object=f"edge:{edge.id}",
                        message=f"Adapter '{edge.adapter_id}' not found in registry",
                        suggested_action="Add adapter definition to adapter_registry",
                    )
                )
        else:
            # No adapter specified and types don't match directly
            # Try to find a compatible adapter
            candidates = [
                a
                for a in flow.adapter_registry
                if (a.source_type == source_port.port_schema and a.target_type == target_port.port_schema)
            ]
            if len(candidates) == 1:
                # Auto-resolve
                risks.append(
                    RiskItem(
                        risk_id=f"adapter-auto-resolve-{edge.id}",
                        code="ADAPTER_AUTO_RESOLVED",
                        severity="low",
                        domain="adapter",
                        affected_object=f"edge:{edge.id}",
                        message=(f"Auto-resolved adapter '{candidates[0].adapter_id}' for edge '{edge.id}'"),
                        rationale=(f"Schema mismatch: {source_port.port_schema} -> {target_port.port_schema}"),
                        suggested_action="Consider explicitly binding adapter for clarity",
                        status="acknowledged",
                    )
                )
            elif len(candidates) > 1:
                risks.append(
                    RiskItem(
                        risk_id=f"adapter-ambiguous-{edge.id}",
                        code="ADAPTER_AMBIGUOUS",
                        severity="medium",
                        domain="adapter",
                        affected_object=f"edge:{edge.id}",
                        message=(
                            f"Multiple adapter candidates for edge '{edge.id}': {[c.adapter_id for c in candidates]}"
                        ),
                        suggested_action="Explicitly bind an adapter to this edge",
                    )
                )
            else:
                risks.append(
                    RiskItem(
                        risk_id=f"adapter-no-match-{edge.id}",
                        code="ADAPTER_NO_MATCH",
                        severity="fatal",
                        domain="adapter",
                        affected_object=f"edge:{edge.id}",
                        message=(f"No adapter found to convert {source_port.port_schema} -> {target_port.port_schema}"),
                        suggested_action="Add an adapter definition or change port schemas",
                    )
                )

    return risks
