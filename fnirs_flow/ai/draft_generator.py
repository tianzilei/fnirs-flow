"""AI draft flow generator: template-based flow creation with AI metadata."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fnirs_flow.flow.atoms import Position
from fnirs_flow.registry.node_library import create_builtin_library
from fnirs_flow.registry.presets import create_builtin_preset_library
from fnirs_flow.registry.scenarios import ScenarioRegistry


def generate_draft_flow(
    scenario_id: str,
    *,
    study_name: str = "",
    data_format: str = "snirf",
    conditions: list[str] | None = None,
    model_name: str = "template_based",
    assumptions: list[str] | None = None,
    user_confirmations: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a candidate flow JSON from a scenario template.

    This is a template-based draft generator (not LLM-powered).
    It uses scenario definitions and preset libraries to create
    a valid starting flow that requires user review.

    Args:
        scenario_id: One of: task, resting_state, machine_learning, etc.
        study_name: Human-readable study name.
        data_format: Data format (snirf, nirx, hitachi, etc.)
        conditions: Experimental conditions (for task-based designs).
        model_name: Identifier for the generation model.
        assumptions: List of assumptions made during generation.
        user_confirmations: Items requiring user confirmation.

    Returns:
        A flow dict with AI generation metadata.
    """
    registry = ScenarioRegistry()
    scenario = registry.get(scenario_id)
    if scenario is None:
        raise ValueError(f"Unknown scenario: {scenario_id}. Available: {list(registry._scenarios.keys())}")

    node_lib = create_builtin_library()
    preset_lib = create_builtin_preset_library()

    # Build nodes from scenario's required + optional atom types
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    all_atom_types = list(scenario.required_atom_types)
    for opt in scenario.optional_atom_types:
        if opt not in all_atom_types:
            all_atom_types.append(opt)

    for atom_type in all_atom_types:
        template = node_lib.get(atom_type)
        if template is None:
            continue

        node_id = f"n_{atom_type}"

        # Apply default presets
        params: dict[str, Any] = {}
        for preset_role, preset_id in scenario.default_presets.items():
            preset = preset_lib.get(preset_id)
            if preset and atom_type in preset.applicable_atom_types:
                params.update(preset.parameters)

        atom = node_lib.create_atom(
            atom_type,
            atom_id=node_id,
            position=Position(x=100 + len(nodes) * 200, y=200),
            config_override=params,
        )
        if atom is None:
            continue
        node = atom.model_dump(mode="json", by_alias=True, exclude_none=True)
        node["label"] = template.name
        node["readiness_status"] = (
            "needs_attention" if atom_type in scenario.required_atom_types else "not_configured"
        )

        # Mark high-impact atoms
        high_impact_types = {"motion_correction", "filtering", "design_matrix", "first_level_glm", "contrast"}
        if atom_type in high_impact_types or node.get("type") in high_impact_types:
            node["readiness_status"] = "needs_attention"
            node["requires_review"] = True

        nodes.append(node)

    # Connect compatible required ports. A scenario's conceptual order is not
    # necessarily a linear data pipeline, so only create schema-matched edges.
    required_nodes: list[dict[str, Any]] = []
    for atom_type in scenario.required_atom_types:
        nid = f"n_{atom_type}"
        required_node: dict[str, Any] | None = next(
            (candidate for candidate in nodes if candidate["id"] == nid),
            None,
        )
        if required_node is not None:
            required_nodes.append(required_node)

    for target_index, target in enumerate(required_nodes):
        target_ports = [
            port for port in target.get("ports", [])
            if port.get("direction") == "in" and port.get("required", True)
        ]
        for target_port in target_ports:
            target_schema = target_port.get("schema")
            source_match: tuple[dict[str, Any], dict[str, Any]] | None = None
            for source in reversed(required_nodes[:target_index]):
                source_port = next(
                    (
                        port for port in source.get("ports", [])
                        if port.get("direction") == "out" and port.get("schema") == target_schema
                    ),
                    None,
                )
                if source_port is not None:
                    source_match = (source, source_port)
                    break
            if source_match is None:
                continue
            source, source_port = source_match
            edges.append(
                {
                    "id": (
                        f"e_{source['id']}_{source_port['name']}"
                        f"_{target['id']}_{target_port['name']}"
                    ),
                    "source": source["id"],
                    "target": target["id"],
                    "source_handle": source_port["name"],
                    "target_handle": target_port["name"],
                }
            )

    # Build assumptions
    default_assumptions = [
        f"Data format: {data_format}",
        f"Scenario: {scenario.name}",
    ]
    if conditions:
        default_assumptions.append(f"Conditions: {', '.join(conditions)}")
    all_assumptions = default_assumptions + (assumptions or [])

    # Build confirmations
    default_confirmations = []
    for atom_type in scenario.required_atom_types:
        if atom_type in ("motion_correction", "filtering", "design_matrix"):
            default_confirmations.append(f"{atom_type}: confirm parameters match study design")
    all_confirmations = default_confirmations + (user_confirmations or [])

    # Build flow
    now = datetime.now(timezone.utc).isoformat()
    flow: dict[str, Any] = {
        "schema_version": "0.2.0",
        "flow_id": f"draft-{scenario_id}-{uuid.uuid4().hex[:8]}",
        "name": study_name or f"AI Draft: {scenario.name}",
        "description": (
            f"AI-generated candidate flow for {scenario.description}. "
            "Requires user review before execution."
        ),
        "metadata": {
            "author": "ai-draft",
            "tags": [scenario_id, "ai-generated"],
            "ai_generation": {
                "generated_by": "generative_ai",
                "model": model_name,
                "created_at": now,
                "input_summary": f"Scenario: {scenario_id}, format: {data_format}",
                "assumptions": all_assumptions,
                "requires_user_confirmation": all_confirmations,
                "confirmed_parameters": [],
                "not_used_for_execution": True,
            },
        },
        "nodes": nodes,
        "edges": edges,
    }

    return flow
