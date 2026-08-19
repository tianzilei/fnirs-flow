"""AI-assisted draft Flow endpoints."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException

from fnirs_flow.api.error_responses import api_error
from fnirs_flow.api.models import AIDraftEnvelope, AIDraftFlow, AIDraftValidation, GenerateAIDraftRequest
from fnirs_flow.api.router_dependencies import bind_router_context, current_store

router = APIRouter(dependencies=[Depends(bind_router_context)])


def _store() -> Any:
    return current_store()


def _sanitize_ai_settings(body: dict[str, Any]) -> dict[str, Any]:
    settings = body.get("ai_settings")
    if not isinstance(settings, dict):
        return {}
    sanitized: dict[str, Any] = {}
    for key in ("provider", "base_url", "model", "organization", "project"):
        value = str(settings.get(key, "")).strip()
        if value:
            sanitized[key] = value
    for key in ("temperature", "max_tokens", "timeout_seconds"):
        numeric_value = settings.get(key)
        if isinstance(numeric_value, int | float):
            sanitized[key] = numeric_value
    sanitized["api_key_present"] = bool(settings.get("api_key_present")) or bool(
        str(settings.get("api_key", "")).strip()
    )
    sanitized["mode"] = str(settings.get("mode", "template")).strip() or "template"
    return sanitized


def _draft_generation_inputs(body: dict[str, Any], ai_settings: dict[str, Any]) -> dict[str, Any]:
    assumptions = list(body.get("assumptions") or [])
    user_confirmations = list(body.get("user_confirmations") or [])
    model_name = str(ai_settings.get("model") or body.get("model", "api_template"))
    external_flow: dict[str, Any] | None = None
    if ai_settings.get("mode") == "openai-compatible":
        if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("FNIRS_FLOW_ALLOW_EXTERNAL_AI_IN_TESTS"):
            ai_settings["provider_status"] = "disabled_in_tests"
            return {"assumptions": assumptions, "user_confirmations": user_confirmations,
                    "model_name": model_name, "ai_settings": ai_settings, "external_flow": external_flow}
        from fnirs_flow.ai.openai_compatible import (
            AIProviderError,
            AIProviderNotConfigured,
            generate_openai_compatible_flow,
        )
        try:
            generated = generate_openai_compatible_flow(
                scenario=str(body.get("scenario", "task")), study_name=str(body.get("study_name", "")),
                data_format=str(body.get("data_format", "snirf")),
                conditions=[str(item) for item in body.get("conditions") or []], settings=ai_settings,
            )
        except AIProviderNotConfigured:
            ai_settings["provider_status"] = "not_configured"
        except AIProviderError as exc:
            raise api_error(502, "AI_PROVIDER_REQUEST_FAILED", str(exc), "ai_draft", recoverable=True,
                            suggested_action=("Check OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_API_KEY, "
                                              "and provider chat/completions support.")) from exc
        else:
            external_flow = generated.get("flow") if isinstance(generated.get("flow"), dict) else None
            ai_settings.update(generated.get("settings") or {})
            if generated.get("usage"):
                ai_settings["usage"] = generated["usage"]
            model_name = str(ai_settings.get("model") or model_name)
    return {"assumptions": assumptions, "user_confirmations": user_confirmations, "model_name": model_name,
            "ai_settings": ai_settings, "external_flow": external_flow}


def _generate_template_flow(body: dict[str, Any], draft_inputs: dict[str, Any]) -> dict[str, Any]:
    from fnirs_flow.ai.draft_generator import generate_draft_flow
    try:
        flow = generate_draft_flow(
            body.get("scenario", "task"), study_name=body.get("study_name", ""),
            data_format=body.get("data_format", "snirf"), conditions=body.get("conditions"),
            model_name=draft_inputs["model_name"], assumptions=draft_inputs["assumptions"],
            user_confirmations=draft_inputs["user_confirmations"],
        )
    except ValueError as exc:
        raise api_error(422, "INVALID_SCENARIO", str(exc), "ai_draft", recoverable=True,
                        suggested_action=("Use task or resting_state, or add the missing MethodAtom templates "
                                          "and input bindings.")) from exc
    if draft_inputs["ai_settings"]:
        flow.setdefault("metadata", {}).setdefault("ai_generation", {})["settings"] = draft_inputs["ai_settings"]
    return cast(dict[str, Any], flow)


@router.post("/api/ai/draft-flow", response_model=AIDraftFlow)
async def generate_ai_draft_endpoint(body: GenerateAIDraftRequest) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    ai_settings = _sanitize_ai_settings(payload)
    draft_inputs = _draft_generation_inputs(payload, ai_settings)
    return draft_inputs["external_flow"] or _generate_template_flow(payload, draft_inputs)


@router.post("/api/projects/{project_id}/ai/draft-flow")
async def generate_ai_draft_for_project_endpoint(project_id: str, body: GenerateAIDraftRequest) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    ai_settings = _sanitize_ai_settings(payload)
    draft_inputs = _draft_generation_inputs(payload, ai_settings)
    external = draft_inputs["external_flow"] is not None
    flow = draft_inputs["external_flow"] or _generate_template_flow(payload, draft_inputs)
    if external:
        flow.setdefault("metadata", {}).setdefault("ai_generation", {})["settings"] = draft_inputs["ai_settings"]
    store = _store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    store.save_draft(project_id, flow)
    if external:
        store.update_flow(project_id, flow)
    return {"status": "draft_pending", "flow_id": flow.get("flow_id"),
            "ai_generation": flow.get("metadata", {}).get("ai_generation"), "imported_to_flow": external,
            "message": ("Draft saved. Confirm with POST /api/projects/{id}/ai/confirm-draft"
                        " or discard with DELETE /api/projects/{id}/ai/draft")}


@router.get("/api/projects/{project_id}/ai/draft", response_model=AIDraftEnvelope)
async def get_ai_draft_endpoint(project_id: str) -> dict[str, Any]:
    store = _store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    draft = store.get_draft(project_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No pending draft")
    return {"status": "draft_exists", "draft": draft}


@router.post("/api/projects/{project_id}/ai/validate-draft", response_model=AIDraftValidation)
async def validate_ai_draft_endpoint(project_id: str) -> dict[str, Any]:
    from fnirs_flow.validation.api import validate_flow
    store = _store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    draft = store.get_draft(project_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No pending draft to validate")
    report = validate_flow(draft)
    return {"status": "draft_validated", "flow_id": draft.get("flow_id"), "valid": len(report.errors) == 0,
            "errors": report.errors, "warnings": report.warnings,
            "risks": [{"risk_id": r.risk_id, "code": r.code, "severity": r.severity, "domain": r.domain,
                       "message": r.message, "suggested_action": r.suggested_action} for r in report.risks],
            "readiness": report.readiness}


@router.post("/api/projects/{project_id}/ai/confirm-draft")
async def confirm_ai_draft_endpoint(project_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    store = _store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    draft = store.get_draft(project_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No pending draft to confirm")
    if body:
        ai_generation = draft.get("metadata", {}).get("ai_generation", {})
        required = [str(item) for item in ai_generation.get("requires_user_confirmation", [])]
        reviewed = list(dict.fromkeys(str(item) for item in body.get("confirmed_parameters", [])))
        confirmed_by = str(body.get("confirmed_by", "")).strip()
        missing = [item for item in required if item not in set(reviewed)]
        if missing or (required and not confirmed_by):
            detail = "All AI confirmation items and a human reviewer are required"
            if missing:
                detail += f"; missing: {'; '.join(missing)}"
            raise api_error(422, "AI_CONFIRMATIONS_INCOMPLETE", detail, "ai_draft_review", recoverable=True,
                            suggested_action="Review every listed item and identify the human reviewer")
        ai_generation.update({"confirmed_parameters": reviewed, "confirmed_by": confirmed_by,
                              "confirmed_at": datetime.now(timezone.utc).isoformat(), "not_used_for_execution": False})
    confirmed = store.confirm_draft(project_id)
    if confirmed is None:
        raise HTTPException(status_code=404, detail="No pending draft to confirm")
    ai_generation = confirmed.get("metadata", {}).get("ai_generation", {})
    return {"status": "draft_confirmed", "flow_id": confirmed.get("flow_id"),
            "confirmed_by": ai_generation.get("confirmed_by", ""),
            "confirmed_count": len(ai_generation.get("confirmed_parameters", []))}


@router.delete("/api/projects/{project_id}/ai/draft")
async def discard_ai_draft_endpoint(project_id: str) -> dict[str, str]:
    store = _store()
    if store.get(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not store.discard_draft(project_id):
        raise HTTPException(status_code=404, detail="No pending draft to discard")
    return {"status": "draft_discarded"}
