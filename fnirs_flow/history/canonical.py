"""Canonical JSON serialization and content-addressed hashing for FlowVCS."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Produce deterministic JSON bytes for hashing.

    Rules:
    - sort_keys for deterministic key order
    - no whitespace separators
    - allow_nan=False to reject NaN/Infinity
    - UTF-8 encoding
    """
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def compute_object_id(design_object: dict[str, Any]) -> str:
    """Compute the content-addressed ID for a DesignObject.

    This hashes the entire stored history object.
    """
    return hashlib.sha256(canonical_json_bytes(design_object)).hexdigest()


def compute_semantic_flow_id(flow: dict[str, Any]) -> str:
    """Compute the History-only stable identifier for a Flow revision."""
    filtered = {
        key: value
        for key, value in flow.items()
        if key not in {"metadata", "created_at", "updated_at", "author", "tags", "notes"}
    }
    return hashlib.sha256(canonical_json_bytes(filtered)).hexdigest()


def compute_commit_id(commit_payload: dict[str, Any]) -> str:
    """Compute the content-addressed ID for a DesignCommit.

    The commit_id field itself must NOT be present in the payload.
    """
    return hashlib.sha256(canonical_json_bytes(commit_payload)).hexdigest()
