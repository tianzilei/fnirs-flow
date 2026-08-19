"""Structural matching helpers for Flow compilation state."""

from __future__ import annotations

from typing import Any

from fnirs_flow.flow.empty_markers import normalize_empty_markers
from fnirs_flow.flow.serialization import load_canonical_flow


def canonical_flow_snapshot(flow_dict: dict[str, Any]) -> dict[str, Any]:
    """Return the schema-normalized Flow representation used for plain matching."""
    normalized = normalize_empty_markers(flow_dict)
    flow = load_canonical_flow(normalized)
    return flow.model_dump(mode="json", exclude_none=True)


def flows_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare two Flow payloads structurally, without a content digest."""
    return canonical_flow_snapshot(left) == canonical_flow_snapshot(right)
