"""Tests for security validation."""

from __future__ import annotations

from fnirs_flow.flow.atoms import (
    CapabilityManifest,
    ExecutableTrustLevel,
)
from fnirs_flow.flow.models import (
    FlowGraph,
    FlowNode,
    NodeCategory,
    NodeStatus,
)
from fnirs_flow.security.validation import validate_security


class TestSecurityValidation:
    def _node(self, trust_level, cap_manifest=None, status=NodeStatus.CONFIGURED):
        return FlowNode(
            id="n1",
            atom_type="custom",
            category=NodeCategory.DATA,
            execution_trust_level=trust_level,
            capability_manifest=cap_manifest,
            readiness_status=status,
        )

    def test_builtin_no_risk(self):
        risks = validate_security(
            FlowGraph(
                flow_atoms=[
                    FlowNode(
                        id="n1",
                        atom_type="x",
                        category=NodeCategory.DATA,
                        execution_trust_level=ExecutableTrustLevel.BUILTIN_MANAGED,
                    )
                ]
            )
        )
        assert len(risks) == 0

    def test_imported_custom_no_manifest_fatal(self):
        risks = validate_security(
            FlowGraph(
                flow_atoms=[
                    FlowNode(
                        id="n1",
                        atom_type="x",
                        category=NodeCategory.DATA,
                        execution_trust_level=ExecutableTrustLevel.IMPORTED_CUSTOM,
                        capability_manifest=None,
                    )
                ]
            )
        )
        assert any("no capability_manifest" in r.message for r in risks)
        assert any(r.severity == "fatal" for r in risks)

    def test_imported_custom_with_manifest_no_network(self):
        risks = validate_security(
            FlowGraph(
                flow_atoms=[
                    FlowNode(
                        id="n1",
                        atom_type="x",
                        category=NodeCategory.DATA,
                        execution_trust_level=ExecutableTrustLevel.IMPORTED_CUSTOM,
                        capability_manifest=CapabilityManifest(network=False),
                    )
                ]
            )
        )
        fatal = [r for r in risks if r.severity == "fatal"]
        assert not any("network" in r.message for r in fatal)

    def test_custom_operation_must_be_declared_in_manifest(self):
        risks = validate_security(
            FlowGraph(
                flow_atoms=[
                    FlowNode(
                        id="n1",
                        atom_type="x",
                        operation="custom_execute",
                        category=NodeCategory.DATA,
                        execution_trust_level=ExecutableTrustLevel.PROJECT_CUSTOM,
                        capability_manifest=CapabilityManifest(allowed_operations=["different_operation"]),
                    )
                ]
            )
        )
        assert any(r.risk_id == "safety-operation-n1" and r.severity == "fatal" for r in risks)

    def test_imported_custom_network_fatal(self):
        risks = validate_security(
            FlowGraph(
                flow_atoms=[
                    FlowNode(
                        id="n1",
                        atom_type="x",
                        category=NodeCategory.DATA,
                        execution_trust_level=ExecutableTrustLevel.IMPORTED_CUSTOM,
                        capability_manifest=CapabilityManifest(network=True),
                    )
                ]
            )
        )
        assert any("network" in r.message for r in risks)
        assert any(r.severity == "fatal" for r in risks)

    def test_imported_custom_shell_fatal(self):
        risks = validate_security(
            FlowGraph(
                flow_atoms=[
                    FlowNode(
                        id="n1",
                        atom_type="x",
                        category=NodeCategory.DATA,
                        execution_trust_level=ExecutableTrustLevel.IMPORTED_CUSTOM,
                        capability_manifest=CapabilityManifest(shell=True),
                    )
                ]
            )
        )
        assert any("shell" in r.message for r in risks)

    def test_imported_custom_external_path_fatal(self):
        risks = validate_security(
            FlowGraph(
                flow_atoms=[
                    FlowNode(
                        id="n1",
                        atom_type="x",
                        category=NodeCategory.DATA,
                        execution_trust_level=ExecutableTrustLevel.IMPORTED_CUSTOM,
                        capability_manifest=CapabilityManifest(file_access=["/etc/passwd"]),
                    )
                ]
            )
        )
        assert any("project-external path" in r.message for r in risks)

    def test_imported_custom_not_quarantined_warns(self):
        risks = validate_security(
            FlowGraph(
                flow_atoms=[
                    FlowNode(
                        id="n1",
                        atom_type="x",
                        category=NodeCategory.DATA,
                        execution_trust_level=ExecutableTrustLevel.IMPORTED_CUSTOM,
                        capability_manifest=CapabilityManifest(),
                        readiness_status=NodeStatus.CONFIGURED,
                    )
                ]
            )
        )
        assert any("not quarantined" in r.message for r in risks)

    def test_project_custom_no_manifest_fatal(self):
        risks = validate_security(
            FlowGraph(
                flow_atoms=[
                    FlowNode(
                        id="n1",
                        atom_type="x",
                        category=NodeCategory.DATA,
                        execution_trust_level=ExecutableTrustLevel.PROJECT_CUSTOM,
                        capability_manifest=None,
                    )
                ]
            )
        )
        assert any("no capability_manifest" in r.message for r in risks)
