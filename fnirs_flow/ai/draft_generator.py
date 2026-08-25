"""AI draft flow generator: template-based flow creation with AI metadata."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fnirs_flow.flow.atoms import Position
from fnirs_flow.registry.node_library import create_builtin_library
from fnirs_flow.registry.presets import create_builtin_preset_library
from fnirs_flow.registry.scenarios import ScenarioRegistry

TEMPLATE_ALIASES = {
    "filtering": "bandpass_filter",
    "motion_correction": "tddr_motion_correction",
}

TASK_GLM_TEMPLATE_ORDER = [
    ("dataset_discovery", "dataset_discovery"),
    ("read_run", "read_run"),
    ("study_design", "study_design"),
    ("event_extraction", "event_extraction"),
    ("optical_density", "optical_density"),
    ("bad_channel_detection", "bad_channel_detection"),
    ("motion_correction", "tddr_motion_correction"),
    ("filtering", "bandpass_filter"),
    ("beer_lambert_law", "beer_lambert_law"),
    ("short_channel_regression", "short_channel_regression"),
    ("design_matrix", "design_matrix"),
    ("first_level_glm", "first_level_glm"),
    ("contrast", "contrast"),
    ("multiple_comparison_correction", "multiple_comparison_correction"),
    ("channel_output", "channel_output"),
    ("roi_output", "roi_output"),
]

HIGH_IMPACT_TYPES = {"motion_correction", "filtering", "design_matrix", "first_level_glm", "contrast"}


def _scenario_template_plan(scenario_id: str, required_atom_types: list[str]) -> list[tuple[str, str]]:
    if scenario_id == "task":
        return TASK_GLM_TEMPLATE_ORDER

    plan = [(atom_type, TEMPLATE_ALIASES.get(atom_type, atom_type)) for atom_type in required_atom_types]
    atom_types = [atom_type for atom_type, _ in plan]
    if "dataset_discovery" in atom_types and "optical_density" in atom_types and "read_run" not in atom_types:
        insert_at = atom_types.index("dataset_discovery") + 1
        plan.insert(insert_at, ("read_run", "read_run"))
    return plan


def _default_task_contrasts(conditions: list[str]) -> list[dict[str, Any]]:
    if len(conditions) < 2:
        return []
    control = next((condition for condition in conditions if condition.lower() == "control"), conditions[-1])
    return [
        {"name": f"{condition}_vs_{control}", "condition": condition, "baseline": control}
        for condition in conditions
        if condition != control
    ]


def _connect_schema_matched_ports(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for target_index, target in enumerate(nodes):
        target_ports = [
            port for port in target.get("ports", []) if port.get("direction") == "in" and port.get("required", True)
        ]
        for target_port in target_ports:
            target_schema = target_port.get("schema")
            source_match: tuple[dict[str, Any], dict[str, Any]] | None = None
            for source in reversed(nodes[:target_index]):
                source_port = next(
                    (
                        port
                        for port in source.get("ports", [])
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
                    "id": (f"e_{source['id']}_{source_port['name']}_{target['id']}_{target_port['name']}"),
                    "source": source["id"],
                    "target": target["id"],
                    "source_handle": source_port["name"],
                    "target_handle": target_port["name"],
                }
            )
    return edges


def _unconnected_required_inputs(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[str]:
    connected_targets = {(edge["target"], edge.get("target_handle")) for edge in edges}
    missing: list[str] = []
    for node in nodes:
        for port in node.get("ports", []):
            if port.get("direction") != "in" or not port.get("required", True):
                continue
            target = (node["id"], port.get("name"))
            if target not in connected_targets:
                missing.append(f"{node['id']}.{port.get('name')}")
    return missing


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

    confirmed_conditions = conditions or []
    contrasts = _default_task_contrasts(confirmed_conditions)

    # Build nodes from the scenario. The task template is an executable
    # default path; broad optional branches that need unavailable external
    # inputs (physiology/confounds/etc.) stay in the library for manual use.
    nodes: list[dict[str, Any]] = []
    template_plan = _scenario_template_plan(scenario_id, scenario.required_atom_types)
    missing_templates = [
        f"{atom_type} ({template_id})" for atom_type, template_id in template_plan if node_lib.get(template_id) is None
    ]
    if missing_templates:
        raise ValueError(
            f"Scenario '{scenario_id}' references unavailable required MethodAtom templates: "
            + ", ".join(missing_templates)
        )

    for index, (atom_type, template_id) in enumerate(template_plan):
        template = node_lib.get(template_id)
        if template is None:
            raise ValueError(f"Unavailable required MethodAtom template: {template_id}")

        node_id = f"n_{atom_type}"

        # Apply default presets
        params: dict[str, Any] = {}
        for preset_role, preset_id in scenario.default_presets.items():
            preset = preset_lib.get(preset_id)
            if preset and atom_type in preset.applicable_atom_types:
                params.update(preset.parameters)
        if atom_type == "study_design" and confirmed_conditions:
            params["conditions"] = confirmed_conditions
            params["contrasts"] = contrasts
        if atom_type == "contrast" and contrasts:
            params["contrasts"] = contrasts

        atom = node_lib.create_atom(
            template_id,
            atom_id=node_id,
            position=Position(x=100 + (index % 6) * 220, y=120 + (index // 6) * 170),
            config_override=params,
        )
        if atom is None:
            continue
        node = atom.model_dump(mode="json", by_alias=True, exclude_none=True)
        node["label"] = template.name
        node["readiness_status"] = "configured"

        # Mark high-impact atoms
        if atom_type in HIGH_IMPACT_TYPES or node.get("atom_type") in HIGH_IMPACT_TYPES:
            node["readiness_status"] = "needs_attention"
            node["requires_review"] = True
        if atom_type == "design_matrix":
            metadata = node.setdefault("metadata", {})
            metadata["order_contract"] = {
                "allowed_upstream_categories": ["design", "preprocessing"],
            }

        nodes.append(node)

    edges = _connect_schema_matched_ports(nodes)
    unconnected_inputs = _unconnected_required_inputs(nodes, edges)
    if unconnected_inputs:
        raise ValueError(
            f"Scenario '{scenario_id}' requires inputs not available in the built-in draft path: "
            + ", ".join(unconnected_inputs)
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
        if atom_type in ("motion_correction", "filtering", "design_matrix", "first_level_glm", "contrast"):
            default_confirmations.append(f"{atom_type}: confirm parameters match study design")
    all_confirmations = default_confirmations + (user_confirmations or [])

    # Build flow
    now = datetime.now(timezone.utc).isoformat()
    flow: dict[str, Any] = {
        "schema_version": "0.4.0",
        "flow_id": f"draft-{scenario_id}-{uuid.uuid4().hex[:8]}",
        "name": study_name or f"AI Draft: {scenario.name}",
        "description": (
            f"AI-generated candidate flow for {scenario.description}. Requires user review before execution."
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
        "flow_atoms": nodes,
        "edges": edges,
    }

    return flow
