"""Tests for adapter compatibility validation."""

from __future__ import annotations

from fnirs_flow.flow.models import (
    AdapterDefinition,
    FlowEdge,
    FlowGraph,
    FlowNode,
    NodeCategory,
    NodePort,
)
from fnirs_flow.validation.adapters import validate_adapters


class TestAdapterValidation:
    def _make_flow(self, source_schema, target_schema, adapter_id=None, registry=None):
        return FlowGraph(
            nodes=[
                FlowNode(
                    id="src",
                    type="a",
                    category=NodeCategory.DATA,
                    ports=[NodePort(name="out", direction="out", schema=source_schema)],
                ),
                FlowNode(
                    id="tgt",
                    type="b",
                    category=NodeCategory.DATA,
                    ports=[NodePort(name="in", direction="in", schema=target_schema)],
                ),
            ],
            edges=[
                FlowEdge(
                    id="e1",
                    source="src",
                    target="tgt",
                    source_handle="out",
                    target_handle="in",
                    adapter_id=adapter_id,
                ),
            ],
            adapter_registry=registry or [],
        )

    def test_matching_schemas_no_risk(self):
        flow = self._make_flow("X", "X")
        risks = validate_adapters(flow)
        assert len(risks) == 0

    def test_missing_adapter_fatal(self):
        flow = self._make_flow("A", "B", adapter_id="missing-adapter")
        risks = validate_adapters(flow)
        assert any("not found" in r.message for r in risks)
        assert any(r.severity == "fatal" for r in risks)

    def test_adapter_type_mismatch(self):
        registry = [AdapterDefinition(adapter_id="ad1", name="AD1", source_type="A", target_type="C")]
        flow = self._make_flow("A", "B", adapter_id="ad1", registry=registry)
        risks = validate_adapters(flow)
        assert any("type mismatch" in r.message for r in risks)

    def test_auto_resolve_single_adapter(self):
        registry = [AdapterDefinition(adapter_id="ad1", name="AD1", source_type="A", target_type="B")]
        flow = self._make_flow("A", "B", registry=registry)
        risks = validate_adapters(flow)
        assert any("Auto-resolved" in r.message for r in risks)

    def test_ambiguous_adapters(self):
        registry = [
            AdapterDefinition(adapter_id="ad1", name="AD1", source_type="A", target_type="B"),
            AdapterDefinition(adapter_id="ad2", name="AD2", source_type="A", target_type="B"),
        ]
        flow = self._make_flow("A", "B", registry=registry)
        risks = validate_adapters(flow)
        assert any("Multiple adapter" in r.message for r in risks)

    def test_no_adapter_no_match_fatal(self):
        flow = self._make_flow("A", "B")
        risks = validate_adapters(flow)
        assert any("No adapter found" in r.message for r in risks)
        assert any(r.severity == "fatal" for r in risks)
