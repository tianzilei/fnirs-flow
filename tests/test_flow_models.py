"""Tests for flow models: FlowGraph, FlowNode, FlowEdge serialization."""

from __future__ import annotations

import copy

import pytest

from fnirs_flow.flow.atoms import (
    CapabilityManifest,
    Position,
    ReadinessStatus,
)
from fnirs_flow.flow.models import (
    AdapterDefinition,
    FlowEdge,
    FlowGraph,
    FlowNode,
    NodeCategory,
    NodePort,
    NodeReference,
)
from fnirs_flow.flow.schemas import flow_to_dict, load_flow_from_dict, validate_flow_dict

pytestmark = pytest.mark.core


def test_minimal_flow_factory_returns_isolated_nested_data(minimal_flow_factory):
    first = minimal_flow_factory()
    second = minimal_flow_factory()

    first["nodes"][0]["config"]["dataset_id"] = "mutated"

    assert second["nodes"][0]["config"]["dataset_id"] == "test-dataset"


class TestFlowNode:
    def test_create_node(self):
        node = FlowNode(
            id="n1",
            atom_type="optical_density",
            category=NodeCategory.PREPROCESSING,
            position=Position(x=100, y=200),
        )
        assert node.id == "n1"
        assert node.category == NodeCategory.PREPROCESSING
        assert node.readiness_status == ReadinessStatus.NOT_CONFIGURED

    def test_node_serialization(self):
        node = FlowNode(
            id="n1",
            atom_type="test",
            category=NodeCategory.DATA,
            ports=[NodePort(name="out", direction="out", schema="TestData")],
        )
        d = node.model_dump()
        assert d["id"] == "n1"
        assert len(d["ports"]) == 1
        restored = FlowNode.model_validate(d)
        assert restored.id == node.id


class TestFlowEdge:
    def test_create_edge(self):
        edge = FlowEdge(
            id="e1",
            source="n1",
            target="n2",
            source_handle="output",
            target_handle="input",
        )
        assert edge.source == "n1"
        assert edge.target == "n2"

    def test_edge_with_adapter(self):
        edge = FlowEdge(
            id="e1",
            source="n1",
            target="n2",
            source_handle="out",
            target_handle="in",
            adapter_id="adapter-1",
        )
        d = edge.model_dump()
        assert d["adapter_id"] == "adapter-1"


class TestFlowGraph:
    def test_create_graph(self):
        graph = FlowGraph(
            flow_id="test-001",
            name="Test Flow",
            flow_atoms=[
                FlowNode(id="n1", atom_type="a", category=NodeCategory.DATA),
                FlowNode(id="n2", atom_type="b", category=NodeCategory.ANALYSIS),
            ],
            edges=[
                FlowEdge(id="e1", source="n1", target="n2", source_handle="out", target_handle="in"),
            ],
        )
        assert len(graph.flow_atoms) == 2
        assert len(graph.edges) == 1

    def test_node_map(self):
        graph = FlowGraph(
            flow_atoms=[FlowNode(id="a", atom_type="x", category=NodeCategory.DATA)],
        )
        nm = graph.node_map()
        assert "a" in nm
        assert nm["a"].atom_type == "x"

    def test_get_node(self):
        graph = FlowGraph(
            flow_atoms=[FlowNode(id="a", atom_type="x", category=NodeCategory.DATA)],
        )
        assert graph.get_node("a") is not None
        assert graph.get_node("missing") is None

    def test_serialization_roundtrip(self):
        graph = FlowGraph(
            flow_id="rt-001",
            flow_atoms=[FlowNode(id="n1", atom_type="test", category=NodeCategory.DATA)],
        )
        d = flow_to_dict(graph)
        restored = load_flow_from_dict(d)
        assert restored.flow_id == "rt-001"
        assert len(restored.flow_atoms) == 1


class TestSchemaValidation:
    def test_valid_flow_passes(self, minimal_flow_dict):
        errors = validate_flow_dict(minimal_flow_dict)
        assert errors == [], f"Validation errors: {errors}"

    def test_missing_required_field_fails(self):
        invalid = {"schema_version": "0.1.0"}  # missing flow_id, nodes, edges
        errors = validate_flow_dict(invalid)
        assert len(errors) > 0

    def test_invalid_node_category_fails(self, minimal_flow_dict):
        bad = copy.deepcopy(minimal_flow_dict)
        bad["nodes"] = [{"id": "x", "type": "y", "category": "invalid_cat", "position": {"x": 0, "y": 0}}]
        errors = validate_flow_dict(bad)
        assert len(errors) > 0


class TestReferences:
    def test_node_reference(self):
        ref = NodeReference(
            source_project="mne-python",
            source_file="mne/preprocessing/nirs",
            reuse_mode="wrap",
            divergence_reason="fnirs-flow wraps MNE preprocessing",
        )
        d = ref.model_dump()
        assert d["reuse_mode"] == "wrap"


class TestAdapterModels:
    def test_adapter_definition(self):
        ad = AdapterDefinition(
            adapter_id="mne-od",
            name="MNE Optical Density",
            source_type="RawData",
            target_type="OpticalDensityData",
        )
        assert ad.source_type == "RawData"

    def test_capability_manifest(self):
        cap = CapabilityManifest(
            allowed_operations=["read", "preprocess"],
            network=False,
            checksum="abc123",
        )
        assert not cap.network
        assert not cap.shell  # default
