"""Flow compiler: compiles flow.json into plan.json, execution_dag.json, and manifests.

MethodAtom-first: compilation populates atom_id, atom_type, template_id, and operation
on each DagNode for full traceability.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from fnirs_flow.compiler.execution_dag import DagNode, ExecutionDag
from fnirs_flow.compiler.hashing import compute_flow_hash
from fnirs_flow.compiler.manifests import (
    write_adapter_manifest,
    write_artifact_manifest,
    write_reporting_checklist,
    write_reproducibility_manifest,
    write_risk_register,
)
from fnirs_flow.dependencies.resolver import resolve_dependencies
from fnirs_flow.filesystem import remove_macos_metadata_paths
from fnirs_flow.flow.empty_markers import normalize_empty_markers
from fnirs_flow.flow.models import FlowGraph
from fnirs_flow.validation.api import validate_flow

GROUP_SCOPE_OPERATIONS = {
    "participant_table_input",
    "participant_metadata_validate",
    "participant_metadata_join",
    "group_design_matrix",
    "group_level_glm",
    "group_glm_nirs_spm",
    "group_contrast",
    "group_summary",
    "combat_harmonization",
    "site_covariate_glm",
    "linear_mixed_effects_glm",
}

PROJECT_SCOPE_OPERATIONS = {"project_report", "package_export"}


class CompileResult:
    def __init__(
        self,
        flow_graph: FlowGraph,
        plan: dict[str, Any],
        execution_dag: ExecutionDag,
        flow_hash: str,
        outdir: Path,
    ):
        self.flow_graph = flow_graph
        self.plan = plan
        self.execution_dag = execution_dag
        self.flow_hash = flow_hash
        self.outdir = outdir


def _topological_layers(flow: FlowGraph) -> list[list[str]]:
    """Compute topological execution layers. Raises ValueError if cycle detected."""
    adjacency: dict[str, list[str]] = defaultdict(list)
    node_ids = {n.id for n in flow.nodes}
    in_degree: dict[str, int] = {n.id: 0 for n in flow.nodes}

    for edge in flow.edges:
        # Skip edges referencing non-existent nodes (ghost edges)
        if edge.source not in node_ids or edge.target not in node_ids:
            continue
        adjacency[edge.source].append(edge.target)
        in_degree[edge.target] += 1

    layers: list[list[str]] = []
    queue = [nid for nid, deg in in_degree.items() if deg == 0]

    while queue:
        layers.append(sorted(queue))
        next_queue: list[str] = []
        for node_id in queue:
            for neighbor in adjacency.get(node_id, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    next_queue.append(neighbor)
        queue = next_queue

    # Check for cycles (nodes not in any layer)
    nodes_in_layers = {nid for layer in layers for nid in layer}
    all_nodes = set(in_degree.keys())
    cycle_nodes = all_nodes - nodes_in_layers
    if cycle_nodes:
        raise ValueError(f"Cycle detected in flow graph. Nodes involved: {cycle_nodes}")

    return layers


def _validate_cross_backend_edges(
    dag_nodes: list[DagNode],
    edges: list[Any],
) -> None:
    """Validate cross-backend adapter edges.

    §7.2: Cross-backend edges must pass through an explicit AdapterDefinition
    or a persisted data boundary. Passing MNE objects directly into Cedalion
    MethodAtoms is forbidden. If no validated bridge adapter exists, compilation
    must stop.

    Raises ValueError if cross-backend edge found without explicit adapter.
    """
    # Build node_id -> backend_id map
    node_backend: dict[str, str | None] = {}
    node_adapter: dict[str, str | None] = {}
    for node in dag_nodes:
        node_backend[node.step_id] = node.backend_id
        node_adapter[node.step_id] = node.adapter_id

    # Check each edge
    cross_backend_edges: list[dict[str, Any]] = []
    for edge in edges:
        source = edge.source if hasattr(edge, "source") else edge.get("source", "")
        target = edge.target if hasattr(edge, "target") else edge.get("target", "")

        source_backend = node_backend.get(source)
        target_backend = node_backend.get(target)

        # Skip if either node has no backend
        if source_backend is None or target_backend is None:
            continue

        # Skip if same backend
        if source_backend == target_backend:
            continue

        # Cross-backend edge detected
        # Check if target node has an explicit adapter binding
        target_adapter = node_adapter.get(target)
        if target_adapter is None:
            cross_backend_edges.append(
                {
                    "source": source,
                    "target": target,
                    "source_backend": source_backend,
                    "target_backend": target_backend,
                }
            )

    # Block if cross-backend edges without adapters found
    if cross_backend_edges:
        error_lines = ["Cross-backend edges detected without explicit adapter bindings:"]
        for edge in cross_backend_edges:
            error_lines.append(
                f"  {edge['source']} ({edge['source_backend']}) -> {edge['target']} ({edge['target_backend']})"
            )
        error_lines.append("")
        error_lines.append(
            "Cross-backend data flow requires an explicit AdapterDefinition or "
            "data serialization boundary. Add an adapter binding to the target node."
        )
        raise ValueError("\n".join(error_lines))


def compile_flow(flow_dict: dict[str, Any], outdir: str | Path) -> CompileResult:
    """Compile a flow dict into plan.json, execution_dag.json, and manifest files.

    Outputs are written to ``outdir/compiled/`` following the derivatives-style
    layout convention.
    """
    outdir = Path(outdir)
    compiled_dir = outdir / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)

    flow_dict = normalize_empty_markers(flow_dict)

    # Parse flow
    flow = FlowGraph.model_validate(flow_dict)
    flow_hash = compute_flow_hash(flow_dict)

    # Validate: errors (schema/graph) = hard fail, fatal risks = hard fail
    report = validate_flow(flow_dict)
    if not report.is_valid:
        raise ValueError(f"Flow has validation errors: {report.errors}")
    if report.has_fatal_risks:
        raise ValueError(f"Flow has fatal risks: {[r.message for r in report.risks if r.severity == 'fatal']}")

    # Build execution DAG (will raise ValueError if cycles exist)
    layers = _topological_layers(flow)
    node_map = {n.id: n for n in flow.nodes}

    dag_nodes: list[DagNode] = []
    for layer in layers:
        for nid in layer:
            node = node_map[nid]
            # Find dependencies from edges
            deps = [e.source for e in flow.edges if e.target == nid]
            # Find adapter for this node
            adapter_id = None
            if node.adapter_bindings:
                adapter_id = node.adapter_bindings[0].definition_id

            # Find backend binding
            backend_id = None
            backend_operation = None
            backend_version_spec = None
            dependency_profile_id = None
            required_capabilities: list[str] = []
            dependency_optional = False
            if node.backend_binding:
                backend_id = node.backend_binding.backend_id
                backend_operation = node.backend_binding.operation
                backend_version_spec = node.backend_binding.version_spec
                dependency_profile_id = node.backend_binding.dependency_profile_id
                required_capabilities = list(node.backend_binding.required_capabilities)

            # MethodAtom-level dependency declarations
            if node.dependency_profile_id:
                dependency_profile_id = node.dependency_profile_id
            if node.required_capabilities:
                required_capabilities = list(node.required_capabilities)
            dependency_optional = node.dependency_optional

            # MethodAtom-first: populate atom fields
            atom_type = node.atom_type or node.type
            operation = node.operation or node.config.get("operation", atom_type)
            execution_scope = node.execution_scope
            if "execution_scope" in node.config:
                execution_scope = str(node.config["execution_scope"])
            elif operation in GROUP_SCOPE_OPERATIONS or atom_type in GROUP_SCOPE_OPERATIONS:
                execution_scope = "group"
            elif operation in PROJECT_SCOPE_OPERATIONS or atom_type in PROJECT_SCOPE_OPERATIONS:
                execution_scope = "project"

            dag_nodes.append(
                DagNode(
                    step_id=nid,
                    node_type=node.type,
                    atom_id=nid,
                    atom_type=atom_type,
                    template_id=node.template_id,
                    operation=operation,
                    category=(node.category.value if hasattr(node.category, "value") else str(node.category)),
                    execution_scope=execution_scope,
                    adapter_id=adapter_id,
                    backend_id=backend_id,
                    backend_operation=backend_operation,
                    backend_version_spec=backend_version_spec,
                    dependency_profile_id=dependency_profile_id,
                    required_capabilities=required_capabilities,
                    dependency_optional=dependency_optional,
                    parameters=node.config,
                    evidence_refs=list(node.evidence_refs),
                    dependencies=deps,
                )
            )

    execution_dag = ExecutionDag(
        flow_id=flow.flow_id,
        flow_hash=flow_hash,
        nodes=dag_nodes,
        atoms=dag_nodes,  # MethodAtom-first dual-write
        edges=[{"source": e.source, "target": e.target} for e in flow.edges],
        execution_layers=layers,
    )

    # §7.2: Validate cross-backend adapter edges
    _validate_cross_backend_edges(dag_nodes, flow.edges)

    # Build plan.json
    # Extract study_design from original flow dict (not parsed model)
    study_design = flow_dict.get("study_design", {})
    conditions = study_design.get("conditions", [])
    contrasts = study_design.get("contrasts", [])

    plan = {
        "schema_version": "0.2.0",
        "flow_id": flow.flow_id,
        "flow_hash": flow_hash,
        "name": flow.name,
        "description": flow.description,
        "metadata": flow.metadata.model_dump(exclude_none=True),
        "project": {},
        "dataset": {},
        "study_design": study_design,
        "acquisition": {},
        "conditions": conditions,
        "contrasts": contrasts,
        "preprocessing_chain": [
            {"step_id": n.step_id, "type": n.node_type, "parameters": n.parameters}
            for n in dag_nodes
            if n.category == "preprocessing"
        ],
        "analysis_chain": [
            {"step_id": n.step_id, "type": n.node_type, "parameters": n.parameters}
            for n in dag_nodes
            if n.category == "analysis"
        ],
        # MethodAtom-first dual-write chains
        "preprocessing_atoms": [
            {
                "atom_id": n.atom_id,
                "atom_type": n.atom_type,
                "operation": n.operation,
                "template_id": n.template_id,
                "parameters": n.parameters,
                "evidence_refs": n.evidence_refs,
            }
            for n in dag_nodes
            if n.category == "preprocessing"
        ],
        "analysis_atoms": [
            {
                "atom_id": n.atom_id,
                "atom_type": n.atom_type,
                "operation": n.operation,
                "template_id": n.template_id,
                "parameters": n.parameters,
                "evidence_refs": n.evidence_refs,
            }
            for n in dag_nodes
            if n.category == "analysis"
        ],
        "output_chain": [
            {"step_id": n.step_id, "type": n.node_type, "parameters": n.parameters}
            for n in dag_nodes
            if n.category == "output"
        ],
        "output_atoms": [
            {
                "atom_id": n.atom_id,
                "atom_type": n.atom_type,
                "operation": n.operation,
                "template_id": n.template_id,
                "parameters": n.parameters,
                "evidence_refs": n.evidence_refs,
            }
            for n in dag_nodes
            if n.category == "output"
        ],
        "roi_definitions": [],
        "validation": {},
        "execution": {
            "total_steps": len(dag_nodes),
            "execution_layers": layers,
            "scopes": {
                "run": [n.atom_id for n in dag_nodes if n.execution_scope == "run"],
                "subject": [n.atom_id for n in dag_nodes if n.execution_scope == "subject"],
                "group": [n.atom_id for n in dag_nodes if n.execution_scope == "group"],
                "project": [n.atom_id for n in dag_nodes if n.execution_scope == "project"],
            },
        },
        "exports": {},
    }

    # Write outputs to compiled/ subdirectory
    (compiled_dir / "flow.json").write_text(
        json.dumps(flow.model_dump(mode="json", exclude_none=True), indent=2),
        encoding="utf-8",
    )
    (compiled_dir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (compiled_dir / "execution_dag.json").write_text(json.dumps(execution_dag.model_dump(), indent=2), encoding="utf-8")

    if flow.metadata.ai_generation is not None:
        ai_generation = flow.metadata.ai_generation
        confirmation_record = {
            "flow_id": flow.flow_id,
            "flow_hash": flow_hash,
            "required": ai_generation.requires_user_confirmation,
            "confirmed": ai_generation.confirmed_parameters,
            "pending": ai_generation.pending_confirmations,
            "confirmed_by": ai_generation.confirmed_by,
            "confirmed_at": ai_generation.confirmed_at,
        }
        (compiled_dir / "parameter_confirmation_record.json").write_text(
            json.dumps(confirmation_record, indent=2),
            encoding="utf-8",
        )

    # Resolve dependencies (read-only, no imports, no network)
    dag_dict = execution_dag.model_dump()
    dep_plan = resolve_dependencies(dag_dict, flow_id=flow.flow_id)
    (compiled_dir / "dependency_plan.json").write_text(
        json.dumps(dep_plan.model_dump(), indent=2, default=str),
        encoding="utf-8",
    )

    # Write manifests (reuse report from validation above)
    write_adapter_manifest(flow, compiled_dir)
    write_risk_register(report.risks, compiled_dir)
    write_reporting_checklist(compiled_dir)
    write_artifact_manifest([], compiled_dir)
    write_reproducibility_manifest(flow_hash, compiled_dir)
    remove_macos_metadata_paths(compiled_dir)

    return CompileResult(
        flow_graph=flow,
        plan=plan,
        execution_dag=execution_dag,
        flow_hash=flow_hash,
        outdir=compiled_dir,
    )
