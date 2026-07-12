"""Tests for graph validation."""

from __future__ import annotations

import json
from pathlib import Path

from fnirs_flow.flow.models import FlowEdge, FlowGraph, FlowNode, NodeCategory, NodePort
from fnirs_flow.validation.graph import validate_graph


class TestGraphValidation:
    def test_valid_graph(self, minimal_flow_dict):
        flow = FlowGraph.model_validate(minimal_flow_dict)
        errors, warnings, risks = validate_graph(flow)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_duplicate_node_id(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(id="n1", type="a", category=NodeCategory.DATA),
                FlowNode(id="n1", type="b", category=NodeCategory.DATA),
            ],
        )
        errors, _, _ = validate_graph(flow)
        assert any("Duplicate atom ID" in e for e in errors)

    def test_duplicate_edge_id(self):
        flow = FlowGraph(
            nodes=[FlowNode(id="n1", type="a", category=NodeCategory.DATA)],
            edges=[
                FlowEdge(id="e1", source="n1", target="n1", source_handle="out", target_handle="in"),
                FlowEdge(id="e1", source="n1", target="n1", source_handle="out", target_handle="in"),
            ],
        )
        errors, _, _ = validate_graph(flow)
        assert any("Duplicate edge ID" in e for e in errors)

    def test_nonexistent_source_node(self):
        flow = FlowGraph(
            nodes=[FlowNode(id="n1", type="a", category=NodeCategory.DATA)],
            edges=[
                FlowEdge(id="e1", source="missing", target="n1", source_handle="out", target_handle="in"),
            ],
        )
        errors, _, _ = validate_graph(flow)
        assert any("non-existent source" in e for e in errors)

    def test_nonexistent_target_node(self):
        flow = FlowGraph(
            nodes=[FlowNode(id="n1", type="a", category=NodeCategory.DATA)],
            edges=[
                FlowEdge(id="e1", source="n1", target="missing", source_handle="out", target_handle="in"),
            ],
        )
        errors, _, _ = validate_graph(flow)
        assert any("non-existent target" in e for e in errors)

    def test_invalid_source_port(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="n1",
                    type="a",
                    category=NodeCategory.DATA,
                    ports=[NodePort(name="out", direction="out", schema="X")],
                ),
                FlowNode(id="n2", type="b", category=NodeCategory.DATA),
            ],
            edges=[
                FlowEdge(id="e1", source="n1", target="n2", source_handle="wrong", target_handle="in"),
            ],
        )
        errors, _, _ = validate_graph(flow)
        assert any("source_handle" in e for e in errors)

    def test_unconnected_required_input_warns(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="n1",
                    type="a",
                    category=NodeCategory.DATA,
                    ports=[NodePort(name="out", direction="out", schema="X")],
                ),
                FlowNode(
                    id="n2",
                    type="b",
                    category=NodeCategory.DATA,
                    ports=[NodePort(name="in", direction="in", schema="X", required=True)],
                ),
            ],
            edges=[],
        )
        _, warnings, _ = validate_graph(flow)
        assert any("not connected" in w for w in warnings)

    def test_cycle_detection(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(id="a", type="x", category=NodeCategory.DATA),
                FlowNode(id="b", type="y", category=NodeCategory.DATA),
                FlowNode(id="c", type="z", category=NodeCategory.DATA),
            ],
            edges=[
                FlowEdge(id="e1", source="a", target="b", source_handle="out", target_handle="in"),
                FlowEdge(id="e2", source="b", target="c", source_handle="out", target_handle="in"),
                FlowEdge(id="e3", source="c", target="a", source_handle="out", target_handle="in"),
            ],
        )
        errors, _, _ = validate_graph(flow)
        assert any("Cycle" in e for e in errors)

    def test_demo_flow_valid(self):
        demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
        if demo_path.exists():
            flow_dict = json.loads(demo_path.read_text())
            flow = FlowGraph.model_validate(flow_dict)
            errors, warnings, risks = validate_graph(flow)
            assert errors == [], f"Demo flow graph errors: {errors}"


class TestAtomSlotContracts:
    """Test atom slot contract validation (schema compatibility)."""

    def test_matching_schemas_pass(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="src",
                    type="a",
                    category=NodeCategory.DATA,
                    ports=[NodePort(name="out", direction="out", schema="RawData")],
                ),
                FlowNode(
                    id="tgt",
                    type="b",
                    category=NodeCategory.PREPROCESSING,
                    ports=[NodePort(name="in", direction="in", schema="RawData")],
                ),
            ],
            edges=[
                FlowEdge(id="e1", source="src", target="tgt", source_handle="out", target_handle="in"),
            ],
        )
        _, _, risks = validate_graph(flow)
        schema_risks = [r for r in risks if "slot-schema-mismatch" in r.risk_id]
        assert len(schema_risks) == 0

    def test_mismatched_schemas_warn(self):
        flow = FlowGraph(
            nodes=[
                FlowNode(
                    id="src",
                    type="a",
                    category=NodeCategory.DATA,
                    ports=[NodePort(name="out", direction="out", schema="RawData")],
                ),
                FlowNode(
                    id="tgt",
                    type="b",
                    category=NodeCategory.PREPROCESSING,
                    ports=[NodePort(name="in", direction="in", schema="OpticalDensityData")],
                ),
            ],
            edges=[
                FlowEdge(id="e1", source="src", target="tgt", source_handle="out", target_handle="in"),
            ],
        )
        _, _, risks = validate_graph(flow)
        schema_risks = [r for r in risks if "slot-schema-mismatch" in r.risk_id]
        assert len(schema_risks) == 1
        assert "RawData" in schema_risks[0].message
        assert "OpticalDensityData" in schema_risks[0].message
