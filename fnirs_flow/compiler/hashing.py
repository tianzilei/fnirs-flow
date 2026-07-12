"""Flow hashing for stable content-addressed identification."""

from __future__ import annotations

import hashlib
import json

# Metadata fields that should be excluded from content hashing
_HASH_EXCLUDE_KEYS = {"metadata", "created_at", "updated_at", "author", "tags", "notes"}


def compute_flow_hash(flow_dict: dict) -> str:
    """Compute SHA256 hash of canonical flow JSON, excluding mutable metadata."""
    filtered = {k: v for k, v in flow_dict.items() if k not in _HASH_EXCLUDE_KEYS}
    canonical = json.dumps(filtered, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
