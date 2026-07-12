"""Golden output regression tests for demo flow compilation."""

from __future__ import annotations

import json
from pathlib import Path

from fnirs_flow.compiler.compiler import compile_flow


def _compile_demo(tmp_path) -> Path:
    demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
    flow_dict = json.loads(demo_path.read_text())
    outdir = tmp_path / "golden"
    result = compile_flow(flow_dict, outdir)
    # result.outdir points to the compiled/ subdirectory
    return result.outdir


class TestGoldenPlan:
    def test_plan_schema_version(self, tmp_path):
        outdir = _compile_demo(tmp_path)
        plan = json.loads((outdir / "plan.json").read_text())
        assert plan["schema_version"] == "0.2.0"

    def test_plan_flow_id(self, tmp_path):
        outdir = _compile_demo(tmp_path)
        plan = json.loads((outdir / "plan.json").read_text())
        assert plan["flow_id"] == "demo-task-001"

    def test_plan_has_dual_write_chains(self, tmp_path):
        outdir = _compile_demo(tmp_path)
        plan = json.loads((outdir / "plan.json").read_text())
        # Legacy chains
        assert "preprocessing_chain" in plan
        assert "analysis_chain" in plan
        # MethodAtom-first chains
        assert "preprocessing_atoms" in plan
        assert "analysis_atoms" in plan
        assert len(plan["preprocessing_atoms"]) > 0
        assert len(plan["analysis_atoms"]) > 0

    def test_plan_atom_fields(self, tmp_path):
        outdir = _compile_demo(tmp_path)
        plan = json.loads((outdir / "plan.json").read_text())
        for atom in plan["preprocessing_atoms"] + plan["analysis_atoms"]:
            assert "atom_id" in atom
            assert "atom_type" in atom
            assert "operation" in atom

    def test_plan_execution_steps(self, tmp_path):
        outdir = _compile_demo(tmp_path)
        plan = json.loads((outdir / "plan.json").read_text())
        assert plan["execution"]["total_steps"] > 0
        assert len(plan["execution"]["execution_layers"]) > 0


class TestGoldenDag:
    def test_dag_has_nodes(self, tmp_path):
        outdir = _compile_demo(tmp_path)
        dag = json.loads((outdir / "execution_dag.json").read_text())
        assert len(dag["nodes"]) > 0

    def test_dag_has_layers(self, tmp_path):
        outdir = _compile_demo(tmp_path)
        dag = json.loads((outdir / "execution_dag.json").read_text())
        assert len(dag["execution_layers"]) > 0

    def test_dag_node_has_atom_fields(self, tmp_path):
        outdir = _compile_demo(tmp_path)
        dag = json.loads((outdir / "execution_dag.json").read_text())
        for node in dag["nodes"]:
            assert "atom_id" in node
            assert "atom_type" in node
            assert "step_id" in node

    def test_dag_dual_write(self, tmp_path):
        outdir = _compile_demo(tmp_path)
        dag = json.loads((outdir / "execution_dag.json").read_text())
        # nodes and atoms should have same length
        assert len(dag["nodes"]) == len(dag.get("atoms", dag["nodes"]))


class TestGoldenHash:
    def test_hash_stability_100x(self, tmp_path):
        demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
        flow_dict = json.loads(demo_path.read_text())
        from fnirs_flow.compiler.hashing import compute_flow_hash

        hashes = [compute_flow_hash(flow_dict) for _ in range(100)]
        assert len(set(hashes)) == 1

    def test_hash_sensitivity(self, tmp_path):
        from fnirs_flow.compiler.hashing import compute_flow_hash

        flow = {"flow_id": "test", "nodes": [{"id": "n1", "type": "a"}], "edges": []}
        h1 = compute_flow_hash(flow)
        flow["nodes"][0]["type"] = "b"
        h2 = compute_flow_hash(flow)
        assert h1 != h2

    def test_two_compilations_same_hash(self, tmp_path):
        outdir1 = _compile_demo(tmp_path / "c1")
        outdir2 = _compile_demo(tmp_path / "c2")
        plan1 = json.loads((outdir1 / "plan.json").read_text())
        plan2 = json.loads((outdir2 / "plan.json").read_text())
        assert plan1["flow_hash"] == plan2["flow_hash"]


class TestGoldenManifests:
    def test_all_manifests_present(self, tmp_path):
        outdir = _compile_demo(tmp_path)
        expected = [
            "adapter_manifest.json",
            "risk_register.json",
            "reporting_checklist.json",
            "artifact_manifest.json",
            "reproducibility_manifest.json",
        ]
        for name in expected:
            assert (outdir / name).exists(), f"Missing manifest: {name}"

    def test_risk_register_has_risks(self, tmp_path):
        outdir = _compile_demo(tmp_path)
        data = json.loads((outdir / "risk_register.json").read_text())
        assert isinstance(data, dict)
        assert "risks" in data
        assert isinstance(data["risks"], list)
