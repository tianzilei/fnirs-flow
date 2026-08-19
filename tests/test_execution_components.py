import pytest

from fnirs_flow.compiler.execution_dag import ExecutionDag
from fnirs_flow.execution.dag_payload import normalize_execution_dag_payload
from fnirs_flow.execution.dag_scheduler import DAGScheduler, resolve_edge_dependency
from fnirs_flow.execution.engine import RunContext
from fnirs_flow.execution.group_executor import GroupExecutor
from fnirs_flow.execution.operation_dispatcher import OperationDispatcher
from fnirs_flow.execution.operations import (
    CallableOperationHandler,
    OperationContext,
    OperationRegistry,
    OperationSpec,
    create_default_registry,
)
from fnirs_flow.execution.run_executor import RunExecutor


def test_dag_scheduler_splits_intra_layer_dependencies():
    layers = DAGScheduler.normalize_layers([["b", "a"]], [{"source": "a", "target": "b"}])
    assert layers == [["a"], ["b"]]


def test_dag_scheduler_rejects_cycle():
    with pytest.raises(ValueError, match="Cycle"):
        DAGScheduler.normalize_layers(
            [["a", "b"]],
            [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
        )


def test_edge_dependency_resolver_uses_actual_predecessor_and_rejects_ambiguity():
    atom = {"operation": "first_level_glm"}
    params = {}
    atom_map = {
        "design": {"operation": "build_design_matrix"},
        "unrelated": {"operation": "compute_qc"},
    }
    resolve_edge_dependency("glm", atom, params, {"design": "matrix"}, {"design", "unrelated"}, atom_map)
    assert params["design_matrix"] == "matrix"

    with pytest.raises(ValueError, match="ambiguous"):
        resolve_edge_dependency(
            "glm",
            atom,
            {},
            {"a": 1, "b": 2},
            {"a", "b"},
            {"a": {"operation": "build_design_matrix"}, "b": {"operation": "build_design_matrix"}},
        )


def test_execution_dag_accepts_legacy_nodes_but_serializes_atoms_only():
    dag = ExecutionDag.model_validate(normalize_execution_dag_payload(
        {
            "flow_id": "legacy",
            "nodes": [{"step_id": "a", "node_type": "read_run"}],
        }
    ))
    dumped = dag.model_dump()
    assert [atom.atom_id for atom in dag.atoms] == ["a"]
    assert "nodes" not in dumped


def test_operation_aliases_are_registry_metadata():
    registry = OperationRegistry()
    registry.register(OperationSpec(operation_id="canonical", aliases=["alias"]))
    dispatcher = OperationDispatcher(registry)
    assert dispatcher.require_registered("alias") == "canonical"


def test_unregistered_operation_fails_before_dispatch():
    with pytest.raises(ValueError, match="Unknown operation"):
        OperationDispatcher(OperationRegistry()).require_registered("missing")


def test_new_operation_executes_without_dispatcher_change():
    registry = OperationRegistry()
    spec = OperationSpec(
        operation_id="custom",
        handler_factory=lambda registered: CallableOperationHandler(
            registered,
            lambda context: context.parameters["value"] * 2,
        ),
    )
    registry.register(spec)
    assert registry.execute("custom", OperationContext(None, None, {"value": 3})) == 6


def test_operation_contract_requires_declared_capabilities_and_handler():
    registry = OperationRegistry()
    registry.register(OperationSpec(operation_id="needs-cap", capabilities=["cap-a"]))
    errors = registry.validate_execution(
        "needs-cap",
        required_capabilities=set(),
        require_handler=True,
    )
    assert errors == [
        "Operation needs-cap is missing required capability declarations: cap-a",
        "Operation needs-cap has no registered handler",
    ]


def test_scientific_and_core_handlers_are_explicitly_registered():
    registry = create_default_registry()
    optical_density = registry.get("optical_density")
    group_design = registry.get("group_design_matrix")
    assert optical_density is not None
    assert set(optical_density.backend_handler_factories) == {"mne_nirs", "cedalion"}
    assert group_design is not None
    assert set(group_design.backend_handler_factories) == {"core"}


def test_run_and_group_executors_are_independent_boundaries(tmp_path):
    class FakeService:
        def _check_cancelled(self):
            return None

        def _execute_dag(self, _run_ctx, _dag, _outdir, result, continue_on_failure=True):
            assert continue_on_failure
            result.status = "completed"

        def _write_run_outputs(self, result, outdir):
            (outdir / f"{result.run_id}.txt").write_text("done", encoding="utf-8")

        def _execute_group_scope_atoms(self, dag, outdir):
            return [(dag["id"], outdir.name)]

        def _generate_group_summary(self, runs, outdir, *, group_config=None):
            return outdir / str((group_config or {}).get("name", "summary"))

    service = FakeService()
    data_path = tmp_path / "run.snirf"
    data_path.write_bytes(b"fixture")
    context = RunContext(run_id="sub-01", data_path=str(data_path))
    run_result = RunExecutor(service).execute(context, {}, {}, tmp_path)
    assert run_result.status == "completed"
    assert (tmp_path / "sub-01.txt").read_text(encoding="utf-8") == "done"
    group = GroupExecutor(service)
    assert group.execute_atoms({"id": "g"}, tmp_path) == [("g", tmp_path.name)]
    assert group.generate_summary([], tmp_path, group_config={"name": "result"}) == tmp_path / "result"
