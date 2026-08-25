"""Versioned Flow payload conversion at the persistence boundary.

The domain model is canonical ``flow_atoms``/``atom_type``. Legacy ``nodes``
and ``type`` fields are accepted only when crossing this module.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from fnirs_flow.flow.models import FlowGraph

CURRENT_SCHEMA_VERSION = "0.4.0"
LEGACY_FIELD_REMOVAL_VERSION = "1.3.0"
logger = logging.getLogger(__name__)


def normalize_flow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize historical Flow JSON into one canonical in-memory shape."""
    result = deepcopy(payload)
    if "flow_atoms" not in result and "nodes" in result:
        if not isinstance(result["nodes"], list):
            raise ValueError("Legacy Flow field 'nodes' must be a list")
        logger.debug(
            "Normalizing deprecated Flow field 'nodes'; support is scheduled for removal in %s",
            LEGACY_FIELD_REMOVAL_VERSION,
        )
        result["flow_atoms"] = result["nodes"]
    result.pop("nodes", None)
    atoms = result.get("flow_atoms")
    if isinstance(atoms, list):
        normalized: list[Any] = []
        for atom in atoms:
            if not isinstance(atom, dict):
                normalized.append(atom)
                continue
            item = dict(atom)
            if "atom_type" not in item and item.get("type"):
                logger.debug(
                    "Normalizing deprecated Flow atom field 'type'; support is scheduled for removal in %s",
                    LEGACY_FIELD_REMOVAL_VERSION,
                )
                item["atom_type"] = item["type"]
            item.pop("type", None)
            if "status" in item and "readiness_status" not in item:
                logger.debug(
                    "Normalizing deprecated Flow atom field 'status'; support is scheduled for removal in %s",
                    LEGACY_FIELD_REMOVAL_VERSION,
                )
                item["readiness_status"] = item["status"]
            item.pop("status", None)
            normalized.append(item)
        result["flow_atoms"] = normalized
    result.setdefault("schema_version", CURRENT_SCHEMA_VERSION)
    return result


def serialize_flow_payload(flow: FlowGraph, *, schema_version: str | None = None) -> dict[str, Any]:
    """Serialize a canonical Flow to the requested persistence schema."""
    version = schema_version or flow.schema_version or CURRENT_SCHEMA_VERSION
    data = flow.model_dump(exclude_none=True)
    atoms = data.pop("flow_atoms", [])
    if version in {"0.1.0"}:
        data["nodes"] = [
            {**{key: value for key, value in atom.items() if key != "atom_type"}, "type": atom.get("atom_type", "")}
            for atom in atoms
        ]
    else:
        data["flow_atoms"] = atoms
    data["schema_version"] = version
    return data


def load_canonical_flow(payload: dict[str, Any]) -> FlowGraph:
    """Deserialize a historical or current payload into the canonical model."""
    normalized = normalize_flow_payload(payload)
    return FlowGraph.model_validate(normalized)
