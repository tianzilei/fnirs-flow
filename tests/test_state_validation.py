"""Tests for state validation mechanism."""

from __future__ import annotations

from fnirs_flow.flow.atoms import (
    AdapterStateContract,
    BoundaryContract,
    CapabilityManifest,
    ExecutableTrustLevel,
    ReadinessStatus,
    SecurityStatus,
)
from fnirs_flow.flow.models import (
    AdapterDefinition,
    FlowEdge,
    FlowGraph,
    FlowNode,
    NodeCategory,
    NodePort,
    NodeStateContract,
)
from fnirs_flow.validation.state import (
    approve_atom_readiness,
    approve_atom_security,
    quarantine_atom,
    validate_adapter_tags,
    validate_custom_node_safety,
    validate_node_states,
    validate_readiness_transition,
    validate_state_contracts,
)


class TestNodeStateValidation:
    def test_ready_node_passes(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="n1",
                    type="test",
                    category=NodeCategory.DATA,
                    readiness_status=ReadinessStatus.READY,
                ),
            ]
        )
        risks = validate_node_states(flow)
        assert len(risks) == 0

    def test_blocked_node_fails(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="n1",
                    type="test",
                    category=NodeCategory.DATA,
                    readiness_status=ReadinessStatus.BLOCKED,
                ),
            ]
        )
        risks = validate_node_states(flow)
        assert any("blocked" in r.message for r in risks)

    def test_quarantined_node_fails(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="n1",
                    type="test",
                    category=NodeCategory.DATA,
                    security_status=SecurityStatus.QUARANTINED,
                ),
            ]
        )
        risks = validate_node_states(flow)
        assert any("quarantined" in r.message for r in risks)

    def test_not_configured_node_fails(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="n1",
                    type="test",
                    category=NodeCategory.DATA,
                    readiness_status=ReadinessStatus.NOT_CONFIGURED,
                ),
            ]
        )
        risks = validate_node_states(flow)
        assert any("not_configured" in r.message for r in risks)

    def test_imported_custom_not_quarantined(self):
        """Quarantine check is in validate_security, not validate_node_states."""
        from fnirs_flow.security.validation import validate_security

        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="n1",
                    type="test",
                    category=NodeCategory.DATA,
                    readiness_status=ReadinessStatus.READY,
                    security_status=SecurityStatus.TRUSTED,
                    execution_trust_level=ExecutableTrustLevel.IMPORTED_CUSTOM,
                    capability_manifest=CapabilityManifest(),
                ),
            ]
        )
        risks = validate_security(flow)
        assert any("quarantined" in r.message for r in risks)

    def test_imported_custom_quarantined_ok(self):
        """Quarantine check is in validate_security, not validate_node_states."""
        from fnirs_flow.security.validation import validate_security

        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="n1",
                    type="test",
                    category=NodeCategory.DATA,
                    security_status=SecurityStatus.QUARANTINED,
                    execution_trust_level=ExecutableTrustLevel.IMPORTED_CUSTOM,
                    capability_manifest=CapabilityManifest(),
                ),
            ]
        )
        risks = validate_security(flow)
        # Should not have the "not quarantined" risk
        assert not any("should be quarantined" in r.message for r in risks)


class TestAdapterTagValidation:
    def test_valid_category_transition(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="src",
                    type="data",
                    category=NodeCategory.DATA,
                    ports=[NodePort(name="out", direction="out", schema="X")],
                ),
                FlowNode(
                    id="tgt",
                    type="prep",
                    category=NodeCategory.PREPROCESSING,
                    ports=[NodePort(name="in", direction="in", schema="X")],
                ),
            ],
            edges=[
                FlowEdge(id="e1", source="src", target="tgt", source_handle="out", target_handle="in"),
            ],
        )
        risks = validate_adapter_tags(flow)
        category_risks = [r for r in risks if "category" in r.message.lower()]
        assert len(category_risks) == 0

    def test_compiled_task_glm_category_transitions_are_valid(self):
        cases = [
            (NodeCategory.DATA, NodeCategory.DATA),
            (NodeCategory.DATA, NodeCategory.ANALYSIS),
            (NodeCategory.ANALYSIS, NodeCategory.ANALYSIS),
            (NodeCategory.OUTPUT, NodeCategory.OUTPUT),
        ]

        for source_category, target_category in cases:
            flow = FlowGraph(
                nodes=[
                    FlowNode(
                        id="src",
                        type="src",
                        category=source_category,
                        ports=[NodePort(name="out", direction="out", schema="X")],
                    ),
                    FlowNode(
                        id="tgt",
                        type="tgt",
                        category=target_category,
                        ports=[NodePort(name="in", direction="in", schema="X")],
                    ),
                ],
                edges=[
                    FlowEdge(id="e1", source="src", target="tgt", source_handle="out", target_handle="in"),
                ],
            )
            risks = validate_adapter_tags(flow)
            category_risks = [r for r in risks if "category" in r.message.lower()]
            assert len(category_risks) == 0

    def test_invalid_category_transition(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="src",
                    type="export",
                    category=NodeCategory.EXPORT,
                    ports=[NodePort(name="out", direction="out", schema="X")],
                ),
                FlowNode(
                    id="tgt",
                    type="data",
                    category=NodeCategory.DATA,
                    ports=[NodePort(name="in", direction="in", schema="X")],
                ),
            ],
            edges=[
                FlowEdge(id="e1", source="src", target="tgt", source_handle="out", target_handle="in"),
            ],
        )
        risks = validate_adapter_tags(flow)
        assert any("category" in r.message.lower() for r in risks)

    def test_scenario_tag_mismatch(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="src",
                    type="a",
                    category=NodeCategory.DATA,
                    ports=[NodePort(name="out", direction="out", schema="X")],
                    metadata={"tags": ["task"]},
                ),
                FlowNode(
                    id="tgt",
                    type="b",
                    category=NodeCategory.PREPROCESSING,
                    ports=[NodePort(name="in", direction="in", schema="X")],
                    metadata={"tags": ["resting_state"]},
                ),
            ],
            edges=[
                FlowEdge(id="e1", source="src", target="tgt", source_handle="out", target_handle="in"),
            ],
        )
        risks = validate_adapter_tags(flow)
        assert any("scenario" in r.message.lower() for r in risks)


class TestStateContracts:
    def test_node_egress_rejects_disallowed_source_state(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="src",
                    type="a",
                    category=NodeCategory.DATA,
                    readiness_status=ReadinessStatus.CONFIGURED,
                    ports=[NodePort(name="out", direction="out", schema="X")],
                    state_contract=NodeStateContract(egress=BoundaryContract(allowed_statuses=[ReadinessStatus.READY])),
                ),
                FlowNode(
                    id="tgt",
                    type="b",
                    category=NodeCategory.PREPROCESSING,
                    readiness_status=ReadinessStatus.READY,
                    ports=[NodePort(name="in", direction="in", schema="X")],
                ),
            ],
            edges=[
                FlowEdge(id="e1", source="src", target="tgt", source_handle="out", target_handle="in"),
            ],
        )
        risks = validate_state_contracts(flow)
        assert any("egress contract rejects" in r.message for r in risks)
        assert any(r.severity == "fatal" for r in risks)

    def test_adapter_ingress_rejects_disallowed_source_state(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="src",
                    type="a",
                    category=NodeCategory.DATA,
                    readiness_status=ReadinessStatus.CONFIGURED,
                    ports=[NodePort(name="out", direction="out", schema="A")],
                ),
                FlowNode(
                    id="tgt",
                    type="b",
                    category=NodeCategory.PREPROCESSING,
                    readiness_status=ReadinessStatus.READY,
                    ports=[NodePort(name="in", direction="in", schema="B")],
                ),
            ],
            edges=[
                FlowEdge(
                    id="e1",
                    source="src",
                    target="tgt",
                    source_handle="out",
                    target_handle="in",
                    adapter_id="ad1",
                ),
            ],
            adapter_registry=[
                AdapterDefinition(
                    adapter_id="ad1",
                    name="A to B",
                    source_type="A",
                    target_type="B",
                    state_contract=AdapterStateContract(
                        ingress=BoundaryContract(allowed_statuses=[ReadinessStatus.READY])
                    ),
                )
            ],
        )
        risks = validate_state_contracts(flow)
        assert any("Adapter 'ad1' ingress contract rejects" in r.message for r in risks)

    def test_port_contract_requires_target_metadata(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="src",
                    type="a",
                    category=NodeCategory.DATA,
                    readiness_status=ReadinessStatus.READY,
                    ports=[NodePort(name="out", direction="out", schema="X")],
                ),
                FlowNode(
                    id="tgt",
                    type="b",
                    category=NodeCategory.PREPROCESSING,
                    readiness_status=ReadinessStatus.READY,
                    ports=[
                        NodePort(
                            name="in",
                            direction="in",
                            schema="X",
                            contract=BoundaryContract(required_metadata_keys=["validated_ingress"]),
                        )
                    ],
                ),
            ],
            edges=[
                FlowEdge(id="e1", source="src", target="tgt", source_handle="out", target_handle="in"),
            ],
        )
        risks = validate_state_contracts(flow)
        assert any("requires metadata keys" in r.message for r in risks)

    def test_invalid_node_post_state_transition_fails(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="n1",
                    type="a",
                    category=NodeCategory.DATA,
                    readiness_status=ReadinessStatus.READY,
                    state_contract=NodeStateContract(post_readiness_status=ReadinessStatus.NOT_CONFIGURED),
                )
            ]
        )
        risks = validate_state_contracts(flow)
        assert any("invalid post-readiness transition" in r.message for r in risks)

    def test_valid_contracts_pass(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="src",
                    type="a",
                    category=NodeCategory.DATA,
                    readiness_status=ReadinessStatus.READY,
                    config={"dataset_id": "demo"},
                    ports=[
                        NodePort(
                            name="out",
                            direction="out",
                            schema="X",
                            contract=BoundaryContract(required_config_keys=["dataset_id"]),
                        )
                    ],
                    state_contract=NodeStateContract(egress=BoundaryContract(allowed_statuses=[ReadinessStatus.READY])),
                ),
                FlowNode(
                    id="tgt",
                    type="b",
                    category=NodeCategory.PREPROCESSING,
                    readiness_status=ReadinessStatus.READY,
                    metadata={"validated_ingress": True},
                    ports=[
                        NodePort(
                            name="in",
                            direction="in",
                            schema="X",
                            contract=BoundaryContract(required_metadata_keys=["validated_ingress"]),
                        )
                    ],
                    state_contract=NodeStateContract(
                        ingress=BoundaryContract(allowed_statuses=[ReadinessStatus.READY])
                    ),
                ),
            ],
            edges=[
                FlowEdge(id="e1", source="src", target="tgt", source_handle="out", target_handle="in"),
            ],
        )
        risks = validate_state_contracts(flow)
        assert risks == []


class TestCustomNodeSafety:
    def test_builtin_no_risks(self):
        node = FlowNode(
            id="n1",
            type="test",
            category=NodeCategory.DATA,
            execution_trust_level=ExecutableTrustLevel.BUILTIN_MANAGED,
        )
        risks = validate_custom_node_safety(node)
        assert len(risks) == 0

    def test_custom_no_manifest_fails(self):
        node = FlowNode(
            id="n1",
            type="test",
            category=NodeCategory.DATA,
            execution_trust_level=ExecutableTrustLevel.PROJECT_CUSTOM,
            capability_manifest=None,
        )
        risks = validate_custom_node_safety(node)
        assert any("no capability_manifest" in r.message for r in risks)

    def test_custom_network_fails(self):
        node = FlowNode(
            id="n1",
            type="test",
            category=NodeCategory.DATA,
            execution_trust_level=ExecutableTrustLevel.PROJECT_CUSTOM,
            capability_manifest=CapabilityManifest(network=True),
        )
        risks = validate_custom_node_safety(node)
        assert any("network" in r.message for r in risks)

    def test_custom_shell_fails(self):
        node = FlowNode(
            id="n1",
            type="test",
            category=NodeCategory.DATA,
            execution_trust_level=ExecutableTrustLevel.PROJECT_CUSTOM,
            capability_manifest=CapabilityManifest(shell=True),
        )
        risks = validate_custom_node_safety(node)
        assert any("shell" in r.message for r in risks)

    def test_custom_external_path_fails(self):
        node = FlowNode(
            id="n1",
            type="test",
            category=NodeCategory.DATA,
            execution_trust_level=ExecutableTrustLevel.PROJECT_CUSTOM,
            capability_manifest=CapabilityManifest(file_access=["/etc/passwd"]),
        )
        risks = validate_custom_node_safety(node)
        assert any("project-external" in r.message for r in risks)

    def test_imported_no_checksum_warns(self):
        node = FlowNode(
            id="n1",
            type="test",
            category=NodeCategory.DATA,
            execution_trust_level=ExecutableTrustLevel.IMPORTED_CUSTOM,
            capability_manifest=CapabilityManifest(checksum=""),
        )
        risks = validate_custom_node_safety(node)
        assert any("checksum" in r.message for r in risks)


class TestStateTransition:
    def test_valid_readiness_transition(self):
        assert validate_readiness_transition(ReadinessStatus.NOT_CONFIGURED, ReadinessStatus.CONFIGURED) is True

    def test_invalid_readiness_transition(self):
        assert validate_readiness_transition(ReadinessStatus.READY, ReadinessStatus.NOT_CONFIGURED) is False

    def test_blocked_to_configured(self):
        assert validate_readiness_transition(ReadinessStatus.BLOCKED, ReadinessStatus.CONFIGURED) is True


class TestNodeApproval:
    def test_approve_quarantined(self):
        node = FlowNode(
            id="n1",
            type="test",
            category=NodeCategory.DATA,
            security_status=SecurityStatus.QUARANTINED,
        )
        approved = approve_atom_security(node)
        assert approved.security_status == SecurityStatus.TRUSTED

    def test_approve_blocked(self):
        node = FlowNode(
            id="n1",
            type="test",
            category=NodeCategory.DATA,
            readiness_status=ReadinessStatus.BLOCKED,
        )
        approved = approve_atom_readiness(node)
        assert approved.readiness_status == ReadinessStatus.CONFIGURED

    def test_quarantine_node(self):
        node = FlowNode(
            id="n1",
            type="test",
            category=NodeCategory.DATA,
            readiness_status=ReadinessStatus.READY,
        )
        quarantined = quarantine_atom(node)
        assert quarantined.security_status == SecurityStatus.QUARANTINED
