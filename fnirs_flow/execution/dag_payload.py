"""Canonical execution-DAG payload conversion at the runtime boundary."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

logger = logging.getLogger(__name__)
LEGACY_DAG_FIELD_REMOVAL_VERSION = "1.3.0"


def normalize_execution_dag_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy DAG JSON into the canonical atoms shape."""
    result = deepcopy(payload)
    if "atoms" not in result and isinstance(result.get("nodes"), list):
        logger.debug(
            "Normalizing deprecated DAG field 'nodes'; support is scheduled for removal in %s",
            LEGACY_DAG_FIELD_REMOVAL_VERSION,
        )
        result["atoms"] = result["nodes"]
    result.pop("nodes", None)
    atoms = result.get("atoms")
    if isinstance(atoms, list):
        normalized: list[Any] = []
        for atom in atoms:
            if not isinstance(atom, dict):
                normalized.append(atom)
                continue
            item = dict(atom)
            if "atom_id" not in item and item.get("step_id"):
                item["atom_id"] = item.pop("step_id")
            else:
                item.pop("step_id", None)
            if "atom_type" not in item and item.get("node_type"):
                item["atom_type"] = item.pop("node_type")
            else:
                item.pop("node_type", None)
            normalized.append(item)
        result["atoms"] = normalized
    return result


def execution_atoms(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return canonical atoms from current or legacy DAG JSON."""
    atoms = normalize_execution_dag_payload(payload).get("atoms", [])
    return [atom for atom in atoms if isinstance(atom, dict)] if isinstance(atoms, list) else []


def assert_atom_security(payload: dict[str, Any]) -> None:
    """Fail closed before executing a DAG containing blocked Atom states."""
    blocked = [
        str(atom.get("atom_id") or atom.get("atom_type") or "<unknown>")
        for atom in execution_atoms(payload)
        if str(atom.get("security_status", "trusted")) in {"quarantined", "blocked"}
    ]
    if blocked:
        raise ValueError(
            "QUARANTINED_ATOMS: explicitly review and trust these atoms before execution: "
            + ", ".join(blocked)
        )
