"""State validation: check atom and adapter states before execution.

Uses the MethodAtom-first split status model:
  - readiness_status: not_configured | configured | needs_attention | ready | blocked
  - execution_status: not_run | queued | running | executed | failed | skipped
  - security_status: trusted | needs_review | quarantined | blocked
"""

from __future__ import annotations

from fnirs_flow.flow.atoms import (
    BoundaryContract,
    ExecutableTrustLevel,
    ExecutionStatus,
    FlowAtom,
    ReadinessStatus,
    SecurityStatus,
)
from fnirs_flow.flow.models import FlowGraph
from fnirs_flow.validation.models import RiskItem

# Valid readiness state transitions for atoms
VALID_READINESS_TRANSITIONS: dict[str, list[str]] = {
    "not_configured": ["configured", "blocked"],
    "configured": ["ready", "needs_attention", "blocked"],
    "needs_attention": ["ready", "configured", "blocked"],
    "blocked": ["configured", "needs_attention"],
    "ready": ["configured", "blocked"],
}

# Valid execution state transitions
VALID_EXECUTION_TRANSITIONS: dict[str, list[str]] = {
    "not_run": ["queued"],
    "queued": ["running", "skipped"],
    "running": ["executed", "failed", "skipped"],
    "executed": ["not_run"],
    "failed": ["not_run", "queued"],
    "skipped": ["not_run", "queued"],
}

# Valid security state transitions
VALID_SECURITY_TRANSITIONS: dict[str, list[str]] = {
    "trusted": ["needs_review"],
    "needs_review": ["trusted", "quarantined", "blocked"],
    "quarantined": ["trusted", "blocked"],
    "blocked": ["needs_review", "quarantined"],
}

# Required states for execution
EXECUTABLE_READINESS_STATES = {"ready", "configured"}

# States that block execution
BLOCKED_READINESS_STATES = {"blocked", "not_configured"}

# Security states that block execution
BLOCKED_SECURITY_STATES = {"quarantined", "blocked"}


def validate_node_states(flow: FlowGraph) -> list[RiskItem]:
    """Validate that all atoms are in valid states for execution.

    Checks readiness and security status transitions only.
    Trust-level, capability manifest, and quarantine checks are in
    security/validation.py (validate_security) to avoid duplication.

    Args:
        flow: FlowGraph to validate

    Returns:
        List of RiskItems for state issues
    """
    risks: list[RiskItem] = []

    for node in flow.nodes:
        readiness_value = (
            node.readiness_status.value
            if isinstance(node.readiness_status, ReadinessStatus)
            else str(node.readiness_status)
        )
        security_value = (
            node.security_status.value
            if isinstance(node.security_status, SecurityStatus)
            else str(node.security_status)
        )

        # Check if atom readiness blocks execution
        if readiness_value in BLOCKED_READINESS_STATES:
            risks.append(
                RiskItem(
                    risk_id=f"state-readiness-blocked-{node.id}",
                    severity="high" if readiness_value == "blocked" else "fatal",
                    domain="security",
                    affected_object=f"atom:{node.id}",
                    message=f"Atom '{node.id}' has readiness '{readiness_value}' and cannot execute",
                    suggested_action="Configure atom before execution",
                )
            )

        # Check if atom security blocks execution
        if security_value in BLOCKED_SECURITY_STATES:
            risks.append(
                RiskItem(
                    risk_id=f"state-security-blocked-{node.id}",
                    severity="high",
                    domain="security",
                    affected_object=f"atom:{node.id}",
                    message=(f"Atom '{node.id}' has security status '{security_value}' and cannot execute"),
                    suggested_action="Review and approve atom before execution",
                )
            )

    return risks


def _to_str(status: ReadinessStatus | ExecutionStatus | SecurityStatus | str) -> str:
    """Extract string value from an enum or pass through string."""
    return status.value if hasattr(status, "value") else str(status)


def _contract_status_values(statuses: list[ReadinessStatus]) -> set[str]:
    return {_to_str(status) for status in statuses}


def _validate_boundary_contract(
    *,
    contract: BoundaryContract,
    node: FlowAtom,
    edge_id: str,
    role: str,
    owner: str,
) -> list[RiskItem]:
    """Validate one ingress/egress boundary against an atom."""
    risks: list[RiskItem] = []
    readiness_value = _to_str(node.readiness_status)
    allowed_statuses = _contract_status_values(contract.allowed_statuses)
    blocked_statuses = _contract_status_values(contract.blocked_statuses)

    if allowed_statuses and readiness_value not in allowed_statuses:
        risks.append(
            RiskItem(
                risk_id=f"state-contract-status-{owner}-{edge_id}-{role}-{node.id}",
                severity="fatal",
                domain="adapter",
                affected_object=f"edge:{edge_id}",
                message=(
                    f"{owner} {role} contract rejects atom '{node.id}' "
                    f"in '{readiness_value}' readiness "
                    f"(allowed: {sorted(allowed_statuses)})"
                ),
                suggested_action=(
                    "Move the atom to an allowed readiness state before connecting or executing this edge"
                ),
            )
        )

    if blocked_statuses and readiness_value in blocked_statuses:
        risks.append(
            RiskItem(
                risk_id=f"state-contract-blocked-{owner}-{edge_id}-{role}-{node.id}",
                severity="fatal",
                domain="adapter",
                affected_object=f"edge:{edge_id}",
                message=(f"{owner} {role} contract blocks atom '{node.id}' in '{readiness_value}' readiness"),
                suggested_action="Resolve the blocked readiness state or change the boundary contract",
            )
        )

    missing_config = [key for key in contract.required_config_keys if key not in node.config]
    if missing_config:
        risks.append(
            RiskItem(
                risk_id=f"state-contract-config-{owner}-{edge_id}-{role}-{node.id}",
                severity="fatal",
                domain="adapter",
                affected_object=f"atom:{node.id}",
                message=(f"{owner} {role} contract requires config keys on atom '{node.id}': {missing_config}"),
                suggested_action="Add the missing atom config keys before validation or execution",
            )
        )

    missing_metadata = [key for key in contract.required_metadata_keys if key not in node.metadata]
    if missing_metadata:
        risks.append(
            RiskItem(
                risk_id=f"state-contract-metadata-{owner}-{edge_id}-{role}-{node.id}",
                severity="fatal",
                domain="adapter",
                affected_object=f"atom:{node.id}",
                message=(f"{owner} {role} contract requires metadata keys on atom '{node.id}': {missing_metadata}"),
                suggested_action="Add the missing atom metadata keys before validation or execution",
            )
        )

    return risks


def _validate_post_readiness_transition(
    *,
    current_status: ReadinessStatus,
    target_status: ReadinessStatus | None,
    owner: str,
    affected_object: str,
    risk_id: str,
) -> list[RiskItem]:
    if target_status is None:
        return []
    if validate_readiness_transition(current_status, target_status):
        return []
    return [
        RiskItem(
            risk_id=risk_id,
            severity="fatal",
            domain="adapter",
            affected_object=affected_object,
            message=(
                f"{owner} declares invalid post-readiness transition {current_status.value} -> {target_status.value}"
            ),
            suggested_action=("Update the post-readiness contract or move the atom through a valid transition"),
        )
    ]


def validate_state_contracts(flow: FlowGraph) -> list[RiskItem]:
    """Validate atom, adapter, and port ingress/egress state contracts."""
    risks: list[RiskItem] = []
    node_map = {n.id: n for n in flow.nodes}
    adapter_map = {a.adapter_id: a for a in flow.adapter_registry}

    for node in flow.nodes:
        risks.extend(
            _validate_post_readiness_transition(
                current_status=node.readiness_status,
                target_status=node.state_contract.post_readiness_status,
                owner=f"Atom '{node.id}'",
                affected_object=f"atom:{node.id}",
                risk_id=f"state-contract-post-node-{node.id}",
            )
        )

    for edge in flow.edges:
        source_node = node_map.get(edge.source)
        target_node = node_map.get(edge.target)
        if not source_node or not target_node:
            continue

        source_port = next(
            (p for p in source_node.ports if p.name == edge.source_handle and p.direction == "out"),
            None,
        )
        target_port = next(
            (p for p in target_node.ports if p.name == edge.target_handle and p.direction == "in"),
            None,
        )

        risks.extend(
            _validate_boundary_contract(
                contract=source_node.state_contract.egress,
                node=source_node,
                edge_id=edge.id,
                role="egress",
                owner=f"Atom '{source_node.id}'",
            )
        )
        risks.extend(
            _validate_boundary_contract(
                contract=target_node.state_contract.ingress,
                node=target_node,
                edge_id=edge.id,
                role="ingress",
                owner=f"Atom '{target_node.id}'",
            )
        )

        if source_port:
            risks.extend(
                _validate_boundary_contract(
                    contract=source_port.contract,
                    node=source_node,
                    edge_id=edge.id,
                    role=f"port:{source_port.name}:egress",
                    owner=f"Port '{source_port.name}'",
                )
            )
        if target_port:
            risks.extend(
                _validate_boundary_contract(
                    contract=target_port.contract,
                    node=target_node,
                    edge_id=edge.id,
                    role=f"port:{target_port.name}:ingress",
                    owner=f"Port '{target_port.name}'",
                )
            )

        if edge.adapter_id:
            adapter = adapter_map.get(edge.adapter_id)
            if not adapter:
                continue
            contract = adapter.state_contract
            risks.extend(
                _validate_boundary_contract(
                    contract=contract.ingress,
                    node=source_node,
                    edge_id=edge.id,
                    role="ingress",
                    owner=f"Adapter '{adapter.adapter_id}'",
                )
            )
            risks.extend(
                _validate_boundary_contract(
                    contract=contract.egress,
                    node=target_node,
                    edge_id=edge.id,
                    role="egress",
                    owner=f"Adapter '{adapter.adapter_id}'",
                )
            )
            risks.extend(
                _validate_post_readiness_transition(
                    current_status=source_node.readiness_status,
                    target_status=contract.post_source_readiness,
                    owner=f"Adapter '{adapter.adapter_id}' source side",
                    affected_object=f"edge:{edge.id}",
                    risk_id=f"state-contract-post-adapter-source-{edge.id}-{adapter.adapter_id}",
                )
            )
            risks.extend(
                _validate_post_readiness_transition(
                    current_status=target_node.readiness_status,
                    target_status=contract.post_target_readiness,
                    owner=f"Adapter '{adapter.adapter_id}' target side",
                    affected_object=f"edge:{edge.id}",
                    risk_id=f"state-contract-post-adapter-target-{edge.id}-{adapter.adapter_id}",
                )
            )

    return risks


def validate_adapter_tags(flow: FlowGraph) -> list[RiskItem]:
    """Validate adapter compatibility based on tags and categories.

    Args:
        flow: FlowGraph to validate

    Returns:
        List of RiskItems for tag/category mismatches
    """
    risks: list[RiskItem] = []
    node_map = {n.id: n for n in flow.nodes}
    adapter_map = {a.adapter_id: a for a in flow.adapter_registry}

    for edge in flow.edges:
        source_node = node_map.get(edge.source)
        target_node = node_map.get(edge.target)

        if not source_node or not target_node:
            continue

        # Get adapter for this edge
        adapter = None
        if edge.adapter_id:
            adapter = adapter_map.get(edge.adapter_id)

        # Check category compatibility
        source_category = source_node.category
        target_category = target_node.category

        # Category transitions describe workflow phases, not strict type
        # conversions. Same-phase links and direct data-to-analysis links are
        # valid in compiled DAGs where upstream data artifacts feed model
        # construction or reporting branches.
        valid_transitions = {
            "data": {"data", "preprocessing", "design", "analysis", "validation", "output", "export"},
            "design": {"design", "preprocessing", "analysis", "validation", "output", "export"},
            "preprocessing": {"preprocessing", "analysis", "validation", "output", "export"},
            "analysis": {"analysis", "output", "validation", "export"},
            "validation": {"output", "export"},
            "output": {"output", "export"},
            "export": set(),
        }

        if target_category.value not in valid_transitions.get(source_category.value, set()):
            risks.append(
                RiskItem(
                    risk_id=f"tag-category-mismatch-{edge.id}",
                    severity="medium",
                    domain="adapter",
                    affected_object=f"edge:{edge.id}",
                    message=(
                        f"Category transition {source_category.value} -> {target_category.value} "
                        f"may be invalid for edge '{edge.id}'"
                    ),
                    suggested_action="Verify the atom order is correct",
                )
            )

        # Check atom metadata tags if present
        source_tags = set(source_node.metadata.get("tags", []))
        target_tags = set(target_node.metadata.get("tags", []))

        # Warn if tags indicate incompatible scenarios
        scenario_tags = ("task", "resting_state", "real_world", "hyperscanning", "machine_learning")
        source_scenarios = {t for t in source_tags if t in scenario_tags}
        target_scenarios = {t for t in target_tags if t in scenario_tags}

        if source_scenarios and target_scenarios and not source_scenarios & target_scenarios:
            risks.append(
                RiskItem(
                    risk_id=f"tag-scenario-mismatch-{edge.id}",
                    severity="low",
                    domain="adapter",
                    affected_object=f"edge:{edge.id}",
                    message=(f"Scenario tag mismatch: source has {source_scenarios}, target has {target_scenarios}"),
                    suggested_action="Verify atoms are compatible for the intended scenario",
                )
            )

        # Check adapter tags if present
        if adapter and hasattr(adapter, "tags"):
            adapter_tags = set(getattr(adapter, "tags", []))
            if adapter_tags and not adapter_tags & (source_tags | target_tags):
                risks.append(
                    RiskItem(
                        risk_id=f"tag-adapter-mismatch-{edge.id}",
                        severity="low",
                        domain="adapter",
                        affected_object=f"edge:{edge.id}",
                        message=f"Adapter '{edge.adapter_id}' tags don't match connected atoms",
                        suggested_action="Verify adapter is appropriate for these atom types",
                    )
                )

    return risks


def validate_custom_node_safety(node: FlowAtom) -> list[RiskItem]:
    """Validate safety of a custom atom before execution.

    Checks capability manifests, dangerous capabilities (network/shell),
    file access paths, quarantine status, and checksum integrity.

    Args:
        node: FlowAtom to validate

    Returns:
        List of RiskItems for safety issues
    """
    risks: list[RiskItem] = []

    # Only check custom atoms
    if node.execution_trust_level == ExecutableTrustLevel.BUILTIN_MANAGED:
        return risks

    # Check capability manifest
    if node.capability_manifest is None:
        risks.append(
            RiskItem(
                risk_id=f"safety-no-manifest-{node.id}",
                severity="fatal",
                domain="security",
                affected_object=f"atom:{node.id}",
                message=f"Custom atom '{node.id}' has no capability_manifest",
                suggested_action="Add capability_manifest with allowed operations",
            )
        )
        return risks

    manifest = node.capability_manifest

    # Check for dangerous capabilities
    if manifest.network:
        risks.append(
            RiskItem(
                risk_id=f"safety-network-{node.id}",
                severity="fatal",
                domain="security",
                affected_object=f"atom:{node.id}",
                message=f"Atom '{node.id}' requests network access",
                suggested_action="Remove network capability from manifest",
            )
        )

    if manifest.shell:
        risks.append(
            RiskItem(
                risk_id=f"safety-shell-{node.id}",
                severity="fatal",
                domain="security",
                affected_object=f"atom:{node.id}",
                message=f"Atom '{node.id}' requests shell access",
                suggested_action="Remove shell capability from manifest",
            )
        )

    # Check file access paths
    for path in manifest.file_access:
        if path.startswith("/") or ".." in path:
            risks.append(
                RiskItem(
                    risk_id=f"safety-path-{node.id}",
                    severity="fatal",
                    domain="security",
                    affected_object=f"atom:{node.id}",
                    message=f"Atom '{node.id}' requests project-external path: {path}",
                    suggested_action="Restrict file access to project-relative paths",
                )
            )

    # Imported custom atoms must be quarantined
    if node.execution_trust_level == ExecutableTrustLevel.IMPORTED_CUSTOM:
        security_value = (
            node.security_status.value if hasattr(node.security_status, "value") else str(node.security_status)
        )
        if security_value != "quarantined":
            risks.append(
                RiskItem(
                    risk_id=f"safety-quarantine-{node.id}",
                    severity="high",
                    domain="security",
                    affected_object=f"atom:{node.id}",
                    message=(
                        f"Imported custom atom '{node.id}' is not quarantined (security_status: {security_value})"
                    ),
                    suggested_action=("Set security_status to 'quarantined' until trust is confirmed"),
                )
            )

        # Check for missing checksum on imported atoms
        if not manifest.checksum:
            risks.append(
                RiskItem(
                    risk_id=f"safety-no-checksum-{node.id}",
                    severity="medium",
                    domain="security",
                    affected_object=f"atom:{node.id}",
                    message=f"Imported atom '{node.id}' has no checksum for integrity verification",
                    suggested_action="Add SHA256 checksum to capability_manifest",
                )
            )

    return risks


def validate_readiness_transition(
    current_status: ReadinessStatus | str,
    target_status: ReadinessStatus | str,
) -> bool:
    """Check if a readiness state transition is valid.

    Args:
        current_status: Current atom readiness status
        target_status: Desired target readiness status

    Returns:
        True if transition is valid
    """
    current_value = _to_str(current_status)
    target_value = _to_str(target_status)
    valid_targets = VALID_READINESS_TRANSITIONS.get(current_value, [])
    return target_value in valid_targets


def validate_execution_transition(
    current_status: ExecutionStatus | str,
    target_status: ExecutionStatus | str,
) -> bool:
    """Check if an execution state transition is valid."""
    current_value = _to_str(current_status)
    target_value = _to_str(target_status)
    valid_targets = VALID_EXECUTION_TRANSITIONS.get(current_value, [])
    return target_value in valid_targets


def validate_security_transition(
    current_status: SecurityStatus | str,
    target_status: SecurityStatus | str,
) -> bool:
    """Check if a security state transition is valid."""
    current_value = _to_str(current_status)
    target_value = _to_str(target_status)
    valid_targets = VALID_SECURITY_TRANSITIONS.get(current_value, [])
    return target_value in valid_targets


def approve_atom_readiness(node: FlowAtom) -> FlowAtom:
    """Approve an atom for execution by updating readiness_status.

    Args:
        node: Atom to approve

    Returns:
        Updated atom with 'ready' readiness_status
    """
    if node.readiness_status == ReadinessStatus.NEEDS_ATTENTION:
        node.readiness_status = ReadinessStatus.READY
    elif node.readiness_status == ReadinessStatus.BLOCKED:
        node.readiness_status = ReadinessStatus.CONFIGURED
    return node


def approve_atom_security(node: FlowAtom) -> FlowAtom:
    """Approve a quarantined atom by updating security_status.

    Args:
        node: Atom to approve

    Returns:
        Updated atom with 'trusted' security_status
    """
    if node.security_status == SecurityStatus.QUARANTINED:
        node.security_status = SecurityStatus.TRUSTED
    elif node.security_status == SecurityStatus.BLOCKED:
        node.security_status = SecurityStatus.NEEDS_REVIEW
    return node


def quarantine_atom(node: FlowAtom) -> FlowAtom:
    """Quarantine an atom by updating security_status.

    Args:
        node: Atom to quarantine

    Returns:
        Updated atom with 'quarantined' security_status
    """
    node.security_status = SecurityStatus.QUARANTINED
    return node


# Legacy function names for backward compatibility
approve_node = approve_atom_readiness
quarantine_node = quarantine_atom
validate_state_transition = validate_readiness_transition
