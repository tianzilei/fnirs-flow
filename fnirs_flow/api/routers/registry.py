"""Registry-driven palette and guided checklist endpoints."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, HTTPException

from fnirs_flow.api.models import AtomTemplate, EmptyMarkerSpec, FlowChecklist, FlowChecklistSummary

router = APIRouter()


def _is_parameter_option_value(value: Any) -> bool:
    return isinstance(value, str | int | float) and not isinstance(value, bool)


def _unique_parameter_options(values: list[Any]) -> list[Any]:
    seen: set[tuple[str, str]] = set()
    options: list[Any] = []
    for value in values:
        if not _is_parameter_option_value(value):
            continue
        key = (type(value).__name__, str(value))
        if key in seen:
            continue
        seen.add(key)
        options.append(value)
    return options


def _template_parameter_options(template: Any, templates: list[Any]) -> dict[str, list[Any]]:
    default_config = dict(getattr(template, "default_config", {}) or {})
    explicit = dict(getattr(template, "parameter_options", {}) or {})
    atom_type = getattr(template, "atom_type", "")
    peers = [item for item in templates if getattr(item, "atom_type", "") == atom_type]
    options: dict[str, list[Any]] = {}
    for name, value in default_config.items():
        values = list(explicit.get(name, []))
        values.extend(dict(getattr(peer, "default_config", {}) or {}).get(name) for peer in peers)
        merged = _unique_parameter_options(values)
        if len(merged) > 1 or explicit.get(name):
            current_included = any(str(item) == str(value) for item in merged)
            options[name] = merged if current_included or not _is_parameter_option_value(value) else [value, *merged]
    return options


@router.get("/api/atom-templates", response_model=list[AtomTemplate])
async def list_atom_templates() -> list[dict[str, Any]]:
    """List all available MethodAtom templates from the backend registry."""
    from fnirs_flow.execution.operations import create_default_registry
    from fnirs_flow.registry.atom_templates import ALL_ATOM_TEMPLATES
    from fnirs_flow.registry.node_templates import attach_common_parameter_options

    attach_common_parameter_options(ALL_ATOM_TEMPLATES)
    operation_registry = create_default_registry()
    templates: list[dict[str, Any]] = []
    for template in ALL_ATOM_TEMPLATES:
        readiness_status = getattr(template, "default_readiness_status", None)
        operation = template.operation or template.atom_type
        operation_spec = operation_registry.get(operation)
        templates.append(
            {
                "id": template.node_id,
                "atom_type": template.atom_type,
                "display_name": template.display_name,
                "category": template.category.value if hasattr(template.category, "value") else str(template.category),
                "operation": operation,
                "description": getattr(template, "description", ""),
                "default_config": dict(getattr(template, "default_config", {}) or {}),
                "parameter_options": _template_parameter_options(template, ALL_ATOM_TEMPLATES),
                "parameter_specs": dict(getattr(template, "parameter_specs", {}) or {}),
                "default_readiness_status": (
                    readiness_status.value if readiness_status is not None else "not_configured"
                ),
                "default_execution_scope": getattr(template, "default_execution_scope", None) or "run",
                "input_ports": [
                    {"name": port.name, "schema": port.port_schema, "required": port.required}
                    for port in getattr(template, "input_ports", [])
                ],
                "output_ports": [
                    {"name": port.name, "schema": port.port_schema, "required": port.required}
                    for port in getattr(template, "output_ports", [])
                ],
                "evidence_refs": list(getattr(template, "evidence_refs", [])),
                "operation_contract": (
                    {
                        "canonical_operation": operation_spec.operation_id,
                        "execution_scope": operation_spec.execution_scope,
                        "capabilities": operation_spec.capabilities,
                        "supported_backends": operation_spec.supported_backends,
                        "handler_backends": sorted(operation_spec.backend_handler_factories),
                        "artifact_contract": operation_spec.artifact_contract,
                        "allow_reviewed_noop": operation_spec.allow_reviewed_noop,
                    }
                    if operation_spec is not None
                    else None
                ),
            }
        )
    return templates


@router.get("/api/empty-marker-specs", response_model=list[EmptyMarkerSpec])
async def list_empty_marker_specs() -> list[dict[str, Any]]:
    from fnirs_flow.flow.empty_markers import empty_marker_specs_json

    return cast(list[dict[str, Any]], empty_marker_specs_json())


@router.get("/api/flow-checklists", response_model=list[FlowChecklistSummary])
async def list_checklists() -> list[dict[str, Any]]:
    from fnirs_flow.flow.checklists import list_flow_checklists

    return cast(list[dict[str, Any]], list_flow_checklists())


@router.get("/api/flow-checklists/{scenario_id}", response_model=FlowChecklist)
async def get_checklist(scenario_id: str) -> dict[str, Any]:
    from fnirs_flow.flow.checklists import checklist_to_dict, get_flow_checklist

    checklist = get_flow_checklist(scenario_id)
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")
    return cast(dict[str, Any], checklist_to_dict(checklist))
