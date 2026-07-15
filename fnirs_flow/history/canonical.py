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

    This hashes the *entire* object (including flow and semantic_flow_hash),
    unlike compute_flow_hash which excludes mutable metadata.
    """
    return hashlib.sha256(canonical_json_bytes(design_object)).hexdigest()


def compute_commit_id(commit_payload: dict[str, Any]) -> str:
    """Compute the content-addressed ID for a DesignCommit.

    The commit_id field itself must NOT be present in the payload.
    """
    return hashlib.sha256(canonical_json_bytes(commit_payload)).hexdigest()
