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
    from fnirs_flow.registry.atom_templates import create_method_atom_library
    from fnirs_flow.registry.node_templates import attach_common_parameter_options

    library = create_method_atom_library()
    all_templates = library.all()
    attach_common_parameter_options(all_templates)
    operation_registry = create_default_registry()
    templates: list[dict[str, Any]] = []
    for template in all_templates:
        readiness_status = getattr(template, "default_readiness_status", None)
        operation = template.operation or template.atom_type
        operation_spec = operation_registry.get(operation)
        blueprint = library.create_atom(template.template_id, atom_id="__METHOD_ATOM_INSTANCE_ID__")
        if blueprint is None:  # pragma: no cover - guarded by iteration over this library
            continue
        blueprint_data = blueprint.model_dump(mode="json", by_alias=True, exclude_none=True)
        blueprint_data.pop("id", None)
        blueprint_data.pop("position", None)
        blueprint_metadata = dict(blueprint_data.get("metadata") or {})
        blueprint_metadata.update(
            {
                "template_reference": template.reference,
                "template_tags": list(template.tags),
                "implementation_status": template.implementation_status,
            }
        )
        blueprint_data["metadata"] = blueprint_metadata
        templates.append(
            {
                "id": template.node_id,
                "atom_type": template.atom_type,
                "display_name": template.display_name,
                "category": template.category.value if hasattr(template.category, "value") else str(template.category),
                "operation": operation,
                "description": getattr(template, "description", ""),
                "default_config": dict(getattr(template, "default_config", {}) or {}),
                "parameter_options": _template_parameter_options(template, all_templates),
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
                "origin": template.origin.value,
                "reference": template.reference,
                "tags": list(template.tags),
                "flow_atom_blueprint": blueprint_data,
                "implementation_module": template.implementation_module,
                "implementation_callable": template.implementation_callable,
                "implementation_status": template.implementation_status,
                "capability_manifest": (
                    template.capability_manifest.model_dump(mode="json")
                    if template.capability_manifest
                    else None
                ),
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


@router.get("/api/atom-registry-status")
async def atom_registry_status() -> dict[str, Any]:
    """Return the current built-in, literature, and local Atom composition state."""
    from fnirs_flow.registry.atom_templates import refresh_method_atom_templates

    return refresh_method_atom_templates()


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
