"""Pure DAG scheduling helpers independent of scientific backends."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def resolve_edge_dependency(
    atom_id: str,
    atom: dict[str, Any],
    params: dict[str, Any],
    state: dict[str, Any],
    predecessors: set[str],
    atom_map: dict[str, dict[str, Any]],
) -> None:
    """Inject a typed input from the target's actual DAG predecessors.

    Ambiguous fan-in fails closed. This resolver is independent from the
    execution host and can be unit-tested without a backend.
    """
    from fnirs_flow.execution.operations import canonical_operation

    operation = canonical_operation(str(atom.get("operation") or atom.get("atom_type") or ""))
    requirements: dict[str, tuple[str, str]] = {
        "first_level_glm": ("design_matrix", "build_design_matrix"),
        "estimate_contrast": ("glm_result", "first_level_glm"),
        "channel_output": ("contrast_result", "estimate_contrast"),
        "roi_output": ("channel_results", "channel_output"),
    }
    requirement = requirements.get(operation)
    if requirement is None:
        return
    param_key, source_operation = requirement
    if param_key in params:
        return

    exact_candidates: list[str] = []
    alias_candidates: list[str] = []
    for predecessor in sorted(predecessors):
        source = atom_map.get(predecessor, {})
        declared = str(source.get("operation") or source.get("atom_type") or "")
        if canonical_operation(declared) == source_operation and predecessor in state:
            (exact_candidates if declared == source_operation else alias_candidates).append(predecessor)
    candidates = exact_candidates or alias_candidates
    if len(candidates) > 1:
        raise ValueError(f"Atom '{atom_id}' has ambiguous '{param_key}' inputs from: {candidates}")
    if candidates:
        params[param_key] = state[candidates[0]]


class DAGScheduler:
    """Validate and normalize execution layers from the compiled DAG artifact."""

    @staticmethod
    def normalize_layers(layers: Iterable[Iterable[str]], edges: Iterable[dict[str, str]]) -> list[list[str]]:
        normalized = [list(layer) for layer in layers]
        dependencies: dict[str, set[str]] = {}
        for edge in edges:
            dependencies.setdefault(str(edge.get("target", "")), set()).add(str(edge.get("source", "")))
        result: list[list[str]] = []
        for layer in normalized:
            remaining = set(layer)
            while remaining:
                ready = sorted(item for item in remaining if not (dependencies.get(item, set()) & remaining))
                if not ready:
                    raise ValueError("Cycle detected in execution DAG layer")
                result.append(ready)
                remaining.difference_update(ready)
        return result
