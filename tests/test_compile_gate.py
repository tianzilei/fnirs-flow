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
    def test_rejects_unregistered_operation(self, tmp_path):
        flow = _demo_flow()
        flow["nodes"][0]["config"]["operation"] = "not_registered_anywhere"

        with pytest.raises(ValueError, match="Unknown operation: not_registered_anywhere"):
            compile_flow(flow, tmp_path / "out")

    def test_registered_scientific_operation_has_handler(self, tmp_path):
        flow = _demo_flow()
        flow["nodes"][0]["config"]["operation"] = "mara"
        result = compile_flow(flow, tmp_path / "out")
        assert result.plan is not None

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
        flow = json.loads((Path(__file__).parent.parent / "configs" / "ds007738_covert_glm_flow.json").read_text())
        result = compile_flow(flow, tmp_path / "out")
        assert result.plan is not None
        assert result.execution_dag is not None

    @pytest.mark.parametrize(
        "operation",
        [
            "combat_harmonization",
            "linear_mixed_effects_glm",
            "nuisance_glm",
            "site_covariate_glm",
            "cbsi",
        ],
    )
    def test_scientific_methods_compile_or_enforce_scope(self, tmp_path, operation):
        flow = json.loads((Path(__file__).parent.parent / "configs" / "ds007738_covert_glm_flow.json").read_text())
        node = next(item for item in flow["nodes"] if item["id"] == "filtering")
        node["operation"] = operation
        node["type"] = operation
        node["atom_type"] = operation
        node["backend_binding"]["operation"] = operation
        if operation in {"linear_mixed_effects_glm", "site_covariate_glm"}:
            node["config"]["execution_scope"] = "group"
            result = compile_flow(flow, tmp_path / operation)
            assert result.plan is not None
        else:
            result = compile_flow(flow, tmp_path / operation)
            assert result.plan is not None

    @pytest.mark.parametrize("operation", ["multi_site_harmonization", "mixed_effects_glm"])
    def test_non_methodatom_scenario_aliases_fail_closed(self, tmp_path, operation):
        flow = _demo_flow()
        flow["nodes"][0]["config"]["operation"] = operation
        with pytest.raises(ValueError, match="Unknown operation"):
            compile_flow(flow, tmp_path / operation)


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
