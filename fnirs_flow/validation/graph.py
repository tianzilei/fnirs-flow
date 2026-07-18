"""Graph validation: atom/edge uniqueness, connectivity, cycle detection, slot contracts."""

from __future__ import annotations

from fnirs_flow.flow.models import FlowGraph
from fnirs_flow.validation.models import RiskItem
from fnirs_flow.validation.order import validate_order_and_empty_policy


def validate_atom_slot_contracts(flow: FlowGraph) -> list[RiskItem]:
    """Validate that connected atoms have compatible port schemas.

    For each edge, checks that the source output port's schema matches
    the target input port's schema.
    """
    risks: list[RiskItem] = []
    node_map = {n.id: n for n in flow.nodes}

    for edge in flow.edges:
        source_node = node_map.get(edge.source)
        target_node = node_map.get(edge.target)
        if not source_node or not target_node:
            continue

        # Find the source output port
        source_port = next(
            (p for p in source_node.ports if p.name == edge.source_handle and p.direction == "out"),
            None,
        )
        # Find the target input port
        target_port = next(
            (p for p in target_node.ports if p.name == edge.target_handle and p.direction == "in"),
            None,
        )

        if source_port and target_port:
            source_schema = source_port.port_schema
            target_schema = target_port.port_schema
            if source_schema != target_schema:
                risks.append(
                    RiskItem(
                        risk_id=f"slot-schema-mismatch-{edge.id}",
                        code="ADAPTER_SCHEMA_MISMATCH",
                        severity="high",
                        domain="adapter",
                        affected_object=f"edge:{edge.id}",
                        message=(
                            f"Schema mismatch on edge '{edge.id}': "
                            f"source atom '{edge.source}' port "
                            f"'{edge.source_handle}' produces '{source_schema}', "
                            f"but target atom '{edge.target}' port "
                            f"'{edge.target_handle}' expects '{target_schema}'"
                        ),
                        suggested_action=(
                            f"Add an adapter to convert '{source_schema}' to '{target_schema}', "
                            f"or change the port schemas to match"
                        ),
                    )
                )

    return risks


def validate_graph(flow: FlowGraph) -> tuple[list[str], list[str], list[RiskItem]]:
    """Validate flow graph structure. Returns (errors, warnings, risks)."""
    errors: list[str] = []
    warnings: list[str] = []
    risks: list[RiskItem] = []

    # Check atom IDs unique
    node_ids = [n.id for n in flow.nodes]
    seen_ids: set[str] = set()
    for nid in node_ids:
        if nid in seen_ids:
            errors.append(f"Duplicate atom ID: {nid}")
        seen_ids.add(nid)

    # Check edge IDs unique
    edge_ids = [e.id for e in flow.edges]
    seen_edge_ids: set[str] = set()
    for eid in edge_ids:
        if eid in seen_edge_ids:
            errors.append(f"Duplicate edge ID: {eid}")
        seen_edge_ids.add(eid)

    # Check source/target atoms exist
    node_set = set(node_ids)
    for edge in flow.edges:
        if edge.source not in node_set:
            errors.append(f"Edge '{edge.id}' references non-existent source atom '{edge.source}'")
        if edge.target not in node_set:
            errors.append(f"Edge '{edge.id}' references non-existent target atom '{edge.target}'")

    # Check source/target ports exist
    node_map = {n.id: n for n in flow.nodes}
    for edge in flow.edges:
        source_node = node_map.get(edge.source)
        target_node = node_map.get(edge.target)
        if source_node:
            out_ports = [p.name for p in source_node.ports if p.direction == "out"]
            if edge.source_handle not in out_ports:
                errors.append(
                    f"Edge '{edge.id}' source_handle '{edge.source_handle}' not found "
                    f"on atom '{edge.source}' (available: {out_ports})"
                )
        if target_node:
            in_ports = [p.name for p in target_node.ports if p.direction == "in"]
            if edge.target_handle not in in_ports:
                errors.append(
                    f"Edge '{edge.id}' target_handle '{edge.target_handle}' not found "
                    f"on atom '{edge.target}' (available: {in_ports})"
                )

    # Check required inputs are connected
    for node in flow.nodes:
        required_in = [p for p in node.ports if p.direction == "in" and p.required]
        connected_targets = {e.target_handle for e in flow.edges if e.target == node.id}
        for port in required_in:
            if port.name not in connected_targets:
                warnings.append(f"Atom '{node.id}' required input port '{port.name}' is not connected")

    # Check atom slot contracts (schema compatibility)
    risks.extend(validate_atom_slot_contracts(flow))
    risks.extend(validate_order_and_empty_policy(flow))

    # Cycle detection via DFS
    adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for edge in flow.edges:
        if edge.source in adjacency:
            adjacency[edge.source].append(edge.target)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {nid: WHITE for nid in node_ids}
    parent: dict[str, str | None] = {nid: None for nid in node_ids}
    cycle_end: str | None = None

    def dfs(node_id: str) -> bool:
        nonlocal cycle_end
        color[node_id] = GRAY
        for neighbor in adjacency.get(node_id, []):
            if color.get(neighbor) == GRAY:
                parent[neighbor] = node_id
                cycle_end = neighbor
                return True
            if color.get(neighbor) == WHITE:
                parent[neighbor] = node_id
                if dfs(neighbor):
                    return True
        color[node_id] = BLACK
        return False

    for nid in node_ids:
        if color[nid] == WHITE:
            if dfs(nid):
                # Reconstruct cycle path
                if cycle_end is None:
                    continue
                path: list[str] = [cycle_end]
                current_node: str | None = parent[cycle_end]
                while current_node is not None and current_node != cycle_end:
                    path.append(current_node)
                    current_node = parent[current_node]
                path.reverse()
                errors.append(f"Cycle detected: {' -> '.join(path)} -> {cycle_end}")
                break

    return errors, warnings, risks
