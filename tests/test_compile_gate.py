"""Tests for stricter compile gate: schema/graph errors and fatal risks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fnirs_flow.compiler.compiler import compile_flow


def _demo_flow() -> dict:
    demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
    return json.loads(demo_path.read_text())


class TestCompileGateErrors:
    def test_rejects_missing_flow_id(self, tmp_path):
        flow = _demo_flow()
        del flow["flow_id"]
        with pytest.raises(ValueError, match="validation errors"):
            compile_flow(flow, tmp_path / "out")

    def test_rejects_missing_nodes(self, tmp_path):
        flow = _demo_flow()
        del flow["nodes"]
        with pytest.raises(ValueError, match="validation errors"):
            compile_flow(flow, tmp_path / "out")

    def test_rejects_invalid_schema(self, tmp_path):
        flow = {"nodes": "not-a-list", "edges": []}
        # Pydantic raises ValidationError for truly malformed input
        with pytest.raises(Exception):
            compile_flow(flow, tmp_path / "out")

    def test_error_message_includes_details(self, tmp_path):
        flow = _demo_flow()
        del flow["flow_id"]
        with pytest.raises(ValueError, match="validation errors") as exc_info:
            compile_flow(flow, tmp_path / "out")
        msg = str(exc_info.value)
        assert "flow_id" in msg or "Flow" in msg

    def test_allows_low_risk_flows(self, tmp_path):
        flow = _demo_flow()
        result = compile_flow(flow, tmp_path / "out")
        assert result.plan is not None
        assert result.execution_dag is not None


class TestCompileGateFatalRisks:
    def test_rejects_not_configured_node(self, tmp_path):
        flow = _demo_flow()
        # Add a node with status "not_configured" which triggers a fatal risk
        flow["nodes"].append(
            {
                "id": "unconfigured_node",
                "type": "optical_density",
                "category": "preprocessing",
                "origin": "builtin",
                "position": {"x": 0, "y": 0},
                "config": {},
                "ports": [
                    {"name": "raw_data", "direction": "in", "schema": "RawData", "required": True},
                    {
                        "name": "od_data",
                        "direction": "out",
                        "schema": "OpticalDensityData",
                        "required": True,
                    },
                ],
                "status": "not_configured",
                "execution_trust_level": "builtin_managed",
            }
        )
        with pytest.raises(ValueError, match="fatal risks|validation errors"):
            compile_flow(flow, tmp_path / "out")
