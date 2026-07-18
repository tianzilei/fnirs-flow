"""Server-side OpenAI-compatible client for AI draft guidance."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fnirs_flow.ai.draft_generator import generate_draft_flow
from fnirs_flow.validation.api import validate_flow


class AIProviderError(RuntimeError):
    """Base error for OpenAI-compatible provider calls."""


class AIProviderNotConfigured(AIProviderError):
    """Raised when the server has no provider API key configured."""


def _read_env_file() -> dict[str, str]:
    path = Path.home() / ".config" / "fnirs-flow" / "openai.env"
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env_value(name: str, env_file: dict[str, str]) -> str:
    return os.environ.get(name, "").strip() or env_file.get(name, "").strip()


def _json_from_text(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def _string_list(value: Any, *, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text[:500])
        if len(result) >= limit:
            break
    return result


def _extract_chat_content(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    if isinstance(first.get("text"), str):
        return first["text"]
    return ""


def _extract_responses_content(body: dict[str, Any]) -> str:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    output = body.get("output")
    if not isinstance(output, list):
        return ""
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    return "\n".join(chunks)


def _setting_number(settings: dict[str, Any], key: str, default: float) -> float:
    value = settings.get(key)
    return float(value) if isinstance(value, int | float) else default


def _provider_config(settings: dict[str, Any]) -> tuple[str, str, str, float, int, int, str]:
    env_file = _read_env_file()
    api_key = _env_value("OPENAI_API_KEY", env_file)
    if not api_key:
        raise AIProviderNotConfigured("OPENAI_API_KEY is not configured on the server")

    base_url = _env_value("OPENAI_BASE_URL", env_file) or "https://api.openai.com/v1"
    model = _env_value("OPENAI_MODEL", env_file) or str(settings.get("model", "")).strip()
    if not model:
        raise AIProviderNotConfigured("OPENAI_MODEL is not configured on the server")

    temperature = _setting_number(settings, "temperature", 0.2)
    max_tokens = max(int(_setting_number(settings, "max_tokens", 4096)), 1024)
    timeout = max(int(_setting_number(settings, "timeout_seconds", 60)), 1)
    provider = str(settings.get("provider", "OpenAI compatible")).strip() or "OpenAI compatible"
    return api_key, base_url, model, temperature, max_tokens, timeout, provider


def _request_provider_json(
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: int,
) -> tuple[dict[str, Any], str]:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise AIProviderError(f"Provider returned HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise AIProviderError(f"Provider request failed: {type(exc).__name__}: {exc}") from exc

    content = _extract_chat_content(body)
    parsed = _json_from_text(content)
    if not parsed:
        raise AIProviderError("Provider response did not contain a JSON object")
    return body, content


def _flow_prompt(
    *,
    scenario: str,
    study_name: str,
    data_format: str,
    conditions: list[str],
    model: str,
) -> str:
    example = generate_draft_flow(
        scenario if scenario in {"task", "resting_state"} else "task",
        study_name=study_name or "AI Draft Example",
        data_format=data_format,
        conditions=conditions,
        model_name=model,
    )
    example["flow_id"] = "replace-with-new-flow-id"
    example["name"] = study_name or "AI Generated Flow"
    ai_generation = example.setdefault("metadata", {}).setdefault("ai_generation", {})
    ai_generation["model"] = model
    ai_generation["not_used_for_execution"] = True
    ai_generation["confirmed_parameters"] = []
    ai_generation["requires_user_confirmation"] = [
        "motion_correction: confirm method and parameters match study design",
        "filtering: confirm frequency cutoffs preserve task response",
        "design_matrix: confirm conditions, HRF model, and nuisance regressors",
        "first_level_glm: confirm GLM configuration and contrast definitions",
        "contrast: confirm all contrasts match the scientific hypothesis",
    ]
    return json.dumps(
        {
            "instruction": "Generate one complete fnirs-flow FlowGraph JSON object for immediate import.",
            "study": {
                "scenario": scenario,
                "study_name": study_name,
                "data_format": data_format,
                "conditions": conditions,
            },
            "generation_strategy": [
                "Use reference_shape as the validated structural base.",
                "Preserve compatible node order, port schemas, handles, categories, and builtin template IDs.",
                "Adapt only flow_id, name, description, study conditions, contrasts, and parameter values.",
                "Do not invent node types, port schemas, handles, or edge fields not present in reference_shape.",
                "Do not return explanations, markdown, comments, or wrapper objects.",
            ],
            "hard_requirements": [
                "The root object itself must be the FlowGraph.",
                "Include schema_version, flow_id, name, description, metadata, nodes, and edges.",
                "Use a stable non-placeholder flow_id derived from the study name.",
                "Do not leave empty strings, TODO, unknown, TBD, null, or placeholder values in required fields.",
                (
                    "Every node must include id, type, atom_type, template_id, operation, category, origin, "
                    "position, config, ports, readiness_status, execution_status, security_status, "
                    "and execution_trust_level."
                ),
                "Every node readiness_status must be configured or needs_attention, not not_configured.",
                "Every node execution_status must be not_run.",
                "Every node security_status must be trusted.",
                "Every edge must reference existing node ids and valid source_handle/target_handle names.",
                "Every required input port must have one incoming edge from a matching output schema.",
                "Use only builtin-managed nodes and no executable code.",
                "Set dataset_discovery.config.source_kind from the requested data_format.",
                "Set study_design.config.conditions exactly from requested conditions.",
                "Set study_design.config.contrasts and contrast.config.contrasts with concrete names.",
                "Set filtering, motion_correction, design_matrix, first_level_glm, and contrast configs explicitly.",
                "metadata.ai_generation.generated_by must be generative_ai.",
                "metadata.ai_generation.model must match the requested model.",
                "metadata.ai_generation.requires_user_confirmation must include all high-impact choices.",
                "metadata.ai_generation.confirmed_parameters must be empty.",
                "metadata.ai_generation.not_used_for_execution must be true.",
                "The generated FlowGraph should pass fnirs-flow schema and graph validation.",
            ],
            "reference_shape": example,
        },
        ensure_ascii=False,
    )


def _repair_flow_prompt(*, invalid_flow: dict[str, Any], errors: list[str], original_prompt: str) -> str:
    return json.dumps(
        {
            "instruction": (
                "Repair the FlowGraph JSON so it passes validation. Return the corrected FlowGraph JSON only."
            ),
            "validation_errors": errors[:12],
            "original_generation_prompt": json.loads(original_prompt),
            "invalid_flow": invalid_flow,
            "repair_rules": [
                "Do not return markdown or explanations.",
                "Preserve the requested study intent.",
                "Fix only the JSON structure, missing required fields, bad ports, bad edges, and invalid values.",
                "Keep metadata.ai_generation.requires_user_confirmation non-empty.",
                "Keep metadata.ai_generation.not_used_for_execution true.",
            ],
        },
        ensure_ascii=False,
    )


def generate_openai_compatible_flow(
    *,
    scenario: str,
    study_name: str,
    data_format: str,
    conditions: list[str],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Ask the external provider to produce a complete FlowGraph JSON object."""
    api_key, base_url, model, temperature, max_tokens, timeout, provider = _provider_config(settings)
    original_prompt = _flow_prompt(
        scenario=scenario,
        study_name=study_name,
        data_format=data_format,
        conditions=conditions,
        model=model,
    )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You generate strict, validation-ready fnirs-flow FlowGraph JSON. "
                    "Return only one JSON object. Never return markdown, prose, or wrappers."
                ),
            },
            {"role": "user", "content": original_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    body, content = _request_provider_json(
        base_url=base_url,
        api_key=api_key,
        payload=payload,
        timeout=timeout,
    )
    flow = _json_from_text(content)
    report = validate_flow(flow)
    if report.errors:
        repair_payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You repair fnirs-flow FlowGraph JSON. Return only the corrected JSON object."
                    ),
                },
                {
                    "role": "user",
                    "content": _repair_flow_prompt(
                        invalid_flow=flow,
                        errors=report.errors,
                        original_prompt=original_prompt,
                    ),
                },
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        body, content = _request_provider_json(
            base_url=base_url,
            api_key=api_key,
            payload=repair_payload,
            timeout=timeout,
        )
        flow = _json_from_text(content)
        report = validate_flow(flow)
        if report.errors:
            raise AIProviderError("Provider generated invalid FlowGraph: " + "; ".join(report.errors[:8]))
    ai_generation = flow.get("metadata", {}).get("ai_generation", {})
    if not isinstance(ai_generation, dict):
        raise AIProviderError("Provider generated FlowGraph without metadata.ai_generation")
    confirmations = ai_generation.get("requires_user_confirmation")
    if not isinstance(confirmations, list) or not confirmations:
        raise AIProviderError("Provider generated FlowGraph without AI confirmation items")
    if ai_generation.get("not_used_for_execution") is not True:
        raise AIProviderError("Provider generated FlowGraph must set not_used_for_execution=true")

    return {
        "flow": flow,
        "settings": {
            "mode": "openai-compatible",
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout_seconds": timeout,
            "api_key_present": True,
            "endpoint": "chat/completions",
            "direct_import": True,
            "provider_status": "connected",
            "generation_source": "external_api_flow_json",
        },
        "usage": body.get("usage") if isinstance(body.get("usage"), dict) else {},
    }


def generate_openai_compatible_draft_guidance(
    *,
    scenario: str,
    study_name: str,
    data_format: str,
    conditions: list[str],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Call a server-configured OpenAI-compatible chat completions endpoint.

    The model only provides review guidance and metadata. The executable
    FlowGraph continues to be built from vetted local templates.
    """
    api_key, base_url, model, temperature, max_tokens, timeout, provider = _provider_config(settings)

    prompt = {
        "task": "Generate cautious fNIRS analysis draft guidance.",
        "scenario": scenario,
        "study_name": study_name,
        "data_format": data_format,
        "conditions": conditions,
        "requirements": [
            "Return JSON only.",
            "Do not create executable code.",
            "Focus on assumptions and human confirmation items for a FlowGraph draft.",
            "Keep confirmations specific to high-impact fNIRS analysis choices.",
        ],
        "schema": {
            "assumptions": ["short assumption string"],
            "user_confirmations": ["specific human review item"],
            "draft_note": "one short sentence",
        },
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are assisting with reproducible fNIRS workflow drafting. "
                    "Return compact JSON only and do not include secrets."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    body, _ = _request_provider_json(base_url=base_url, api_key=api_key, payload=payload, timeout=timeout)
    content = _extract_chat_content(body)
    parsed = _json_from_text(content)
    assumptions = _string_list(parsed.get("assumptions"))
    confirmations = _string_list(parsed.get("user_confirmations"))
    draft_note = str(parsed.get("draft_note", "")).strip()[:500]
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}

    return {
        "assumptions": assumptions,
        "user_confirmations": confirmations,
        "draft_note": draft_note,
        "settings": {
            "mode": "openai-compatible",
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout_seconds": timeout,
            "api_key_present": True,
            "endpoint": "chat/completions",
        },
        "usage": usage,
    }
