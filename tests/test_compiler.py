"""Tests for flow compiler."""

from __future__ import annotations

import json
from pathlib import Path

from fnirs_flow.compiler.compiler import compile_flow
from fnirs_flow.compiler.hashing import compute_flow_hash


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
