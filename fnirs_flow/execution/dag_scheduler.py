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
        normalized = [[str(item) for item in layer] for layer in layers]
        positions: dict[str, tuple[int, int]] = {}
        for layer_index, layer in enumerate(normalized):
            for item_index, item in enumerate(layer):
                if item in positions:
                    raise ValueError(f"Duplicate atom '{item}' in execution DAG layers")
                positions[item] = (layer_index, item_index)

        dependencies: dict[str, set[str]] = {item: set() for item in positions}
        for edge in edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source in positions and target in positions:
                dependencies[target].add(source)

        result: list[list[str]] = []
        remaining = set(positions)
        while remaining:
            ready = [item for item in remaining if not (dependencies[item] & remaining)]
            if not ready:
                raise ValueError("Cycle detected in execution DAG")

            # Preserve compiler layer boundaries for independent atoms while
            # repairing dependencies that cross malformed or legacy layers.
            next_layer = min(positions[item][0] for item in ready)
            batch = sorted(
                (item for item in ready if positions[item][0] == next_layer),
                key=lambda item: positions[item][1],
            )
            result.append(batch)
            remaining.difference_update(batch)
        return result
