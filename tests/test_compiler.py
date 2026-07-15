"""Tests for flow compiler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fnirs_flow.compiler.compiler import compile_flow
from fnirs_flow.compiler.hashing import compute_flow_hash

pytestmark = pytest.mark.core


class TestFlowHash:
    def test_same_input_same_hash(self):
        d = {"a": 1, "b": 2}
        h1 = compute_flow_hash(d)
        h2 = compute_flow_hash(d)
        assert h1 == h2

    def test_different_input_different_hash(self):
        h1 = compute_flow_hash({"a": 1})
        h2 = compute_flow_hash({"a": 2})
        assert h1 != h2

    def test_deterministic(self):
        d = {"nodes": [{"id": "n1"}], "edges": []}
        hashes = [compute_flow_hash(d) for _ in range(10)]
        assert len(set(hashes)) == 1


class TestCompiler:
    def test_compile_demo_flow(self, tmp_path):
        demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
        flow_dict = json.loads(demo_path.read_text())
        result = compile_flow(flow_dict, tmp_path / "output")

        assert result.plan is not None
        assert result.execution_dag is not None
        assert result.flow_hash

    def test_compile_flow_atoms_only_input(self, tmp_path):
        flow_dict = {
            "schema_version": "0.2.0",
            "flow_id": "atoms-only",
            "flow_atoms": [
                {
                    "id": "a1",
                    "atom_type": "optical_density",
                    "template_id": "optical_density",
                    "operation": "optical_density",
                    "category": "preprocessing",
                    "position": {"x": 0, "y": 0},
                    "config": {"operation": "optical_density"},
                    "ports": [
                        {
                            "name": "od_data",
                            "direction": "out",
                            "schema": "OpticalDensityData",
                            "required": True,
                        },
                    ],
                    "evidence_refs": ["ev-1"],
                    "status": "configured",
                    "execution_trust_level": "builtin_managed",
                },
            ],
            "edges": [],
        }

        result = compile_flow(flow_dict, tmp_path / "output")

        assert len(result.flow_graph.nodes) == 1
        dag_node = result.execution_dag.nodes[0]
        assert dag_node.atom_id == "a1"
        assert dag_node.atom_type == "optical_density"
        assert dag_node.template_id == "optical_density"
        assert dag_node.evidence_refs == ["ev-1"]

    def test_generates_plan_json(self, tmp_path):
        demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
        flow_dict = json.loads(demo_path.read_text())
        result = compile_flow(flow_dict, tmp_path / "output")

        # result.outdir points to compiled/ subdirectory
        plan_path = result.outdir / "plan.json"
        assert plan_path.exists()
        plan = json.loads(plan_path.read_text())
        assert plan["schema_version"] == "0.2.0"
        assert plan["flow_id"] == "demo-task-001"
        assert "preprocessing_chain" in plan
        assert "analysis_chain" in plan
        # MethodAtom-first: dual-write chains
        assert "preprocessing_atoms" in plan
        assert "analysis_atoms" in plan
        assert len(plan["preprocessing_atoms"]) > 0
        first_atom = plan["preprocessing_atoms"][0]
        assert "atom_id" in first_atom
        assert "atom_type" in first_atom

    def test_generates_execution_dag(self, tmp_path):
        demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
        flow_dict = json.loads(demo_path.read_text())
        result = compile_flow(flow_dict, tmp_path / "output")

        dag_path = result.outdir / "execution_dag.json"
        assert dag_path.exists()
        dag = json.loads(dag_path.read_text())
        assert len(dag["nodes"]) > 0
        assert len(dag["execution_layers"]) > 0

    def test_generates_manifests(self, tmp_path):
        demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
        flow_dict = json.loads(demo_path.read_text())
        result = compile_flow(flow_dict, tmp_path / "output")

        # result.outdir points to compiled/ subdirectory
        assert (result.outdir / "adapter_manifest.json").exists()
        assert (result.outdir / "risk_register.json").exists()
        assert (result.outdir / "reporting_checklist.json").exists()
        assert (result.outdir / "artifact_manifest.json").exists()
        assert (result.outdir / "reproducibility_manifest.json").exists()

    def test_deterministic_output(self, tmp_path):
        demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
        flow_dict = json.loads(demo_path.read_text())

        r1 = compile_flow(flow_dict, tmp_path / "out1")
        r2 = compile_flow(flow_dict, tmp_path / "out2")

        assert r1.flow_hash == r2.flow_hash
        plan1 = json.loads((r1.outdir / "plan.json").read_text())
        plan2 = json.loads((r2.outdir / "plan.json").read_text())
        assert plan1 == plan2

    def test_topological_ordering(self, tmp_path):
        demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
        flow_dict = json.loads(demo_path.read_text())
        result = compile_flow(flow_dict, tmp_path / "output")

        dag = result.execution_dag
        # Verify that for each node, all dependencies appear in earlier layers
        node_layer_map: dict[str, int] = {}
        for i, layer in enumerate(dag.execution_layers):
            for nid in layer:
                node_layer_map[nid] = i

        for dag_node in dag.nodes:
            node_layer = node_layer_map.get(dag_node.step_id, -1)
            for dep in dag_node.dependencies:
                dep_layer = node_layer_map.get(dep, -1)
                assert dep_layer < node_layer, (
                    f"Node {dag_node.step_id} (layer {node_layer}) depends on {dep} (layer {dep_layer})"
                )

    def test_ai_draft_pending_confirmation_blocks_compile(self, tmp_path, minimal_flow_dict):
        flow = dict(minimal_flow_dict)
        flow["metadata"] = {
            "ai_generation": {
                "requires_user_confirmation": ["contrast"],
                "confirmed_parameters": [],
                "not_used_for_execution": True,
            }
        }

        with pytest.raises(ValueError, match="fatal risks"):
            compile_flow(flow, tmp_path / "blocked")

    def test_ai_confirmation_and_metadata_are_preserved(self, tmp_path, minimal_flow_dict):
        flow = dict(minimal_flow_dict)
        flow["metadata"] = {
            "ai_generation": {
                "model": "test-model",
                "requires_user_confirmation": ["contrast"],
                "confirmed_parameters": ["contrast"],
                "confirmed_by": "human-reviewer",
                "confirmed_at": "2026-07-13T12:00:00+08:00",
                "not_used_for_execution": True,
            }
        }

        result = compile_flow(flow, tmp_path / "confirmed")
        plan = json.loads((result.outdir / "plan.json").read_text())
        record = json.loads((result.outdir / "parameter_confirmation_record.json").read_text())

        assert plan["metadata"]["ai_generation"]["model"] == "test-model"
        assert record["pending"] == []
        assert record["confirmed_by"] == "human-reviewer"

    def test_group_scope_is_compiled_for_participant_metadata_atoms(self, tmp_path):
        flow = {
            "schema_version": "0.3.0",
            "flow_id": "group-scope",
            "nodes": [
                {
                    "id": "participants",
                    "type": "participant_table_input",
                    "atom_type": "participant_table_input",
                    "operation": "participant_table_input",
                    "category": "data",
                    "config": {},
                    "position": {"x": 0, "y": 0},
                    "readiness_status": "ready",
                    "ports": [
                        {"name": "participant_table", "direction": "out", "schema": "ParticipantTable"},
                    ],
                },
                {
                    "id": "design",
                    "type": "group_design_matrix",
                    "atom_type": "group_design_matrix",
                    "operation": "group_design_matrix",
                    "category": "design",
                    "config": {},
                    "position": {"x": 100, "y": 0},
                    "readiness_status": "ready",
                    "ports": [
                        {"name": "participant_table", "direction": "in", "schema": "ParticipantTable"},
                        {"name": "group_design_matrix", "direction": "out", "schema": "GroupDesignMatrix"},
                    ],
                },
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "participants",
                    "target": "design",
                    "source_handle": "participant_table",
                    "target_handle": "participant_table",
                }
            ],
        }

        result = compile_flow(flow, tmp_path / "output")

        dag = {node.atom_id: node for node in result.execution_dag.nodes}
        assert dag["participants"].execution_scope == "group"
        assert dag["design"].execution_scope == "group"
        assert result.plan["execution"]["scopes"]["group"] == ["participants", "design"]
