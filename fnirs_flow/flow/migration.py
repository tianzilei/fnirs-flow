"""Schema migration helpers: v0.1 -> v0.2 MethodAtom-first migration.

These helpers convert legacy flow.json and literature evidence files
from v0.1 (node-centric) to v0.2 (MethodAtom-first) format while
preserving backward compatibility.
"""

from __future__ import annotations

import copy
from typing import Any


def migrate_flow_schema_v0_1_to_v0_2(flow_dict: dict[str, Any]) -> dict[str, Any]:
    """Migrate a v0.1 flow dict to v0.2 MethodAtom-first format.

    Changes:
      - schema_version: "0.1.0" -> "0.2.0"
      - nodes -> flow_atoms (dual-write, keep nodes for compat)
      - node_type -> atom_type (dual-write on each atom)
      - Each atom gets a template_id field

    Args:
        flow_dict: v0.1 flow dictionary

    Returns:
        Migrated v0.2 flow dictionary (original is not mutated)
    """
    result = copy.deepcopy(flow_dict)
    result["schema_version"] = "0.2.0"

    # Dual-write: keep nodes, add flow_atoms
    nodes = result.get("nodes", [])
    flow_atoms = []
    for node in nodes:
        atom = dict(node)
        # Add atom_type = node_type
        if "atom_type" not in atom and "type" in atom:
            atom["atom_type"] = atom["type"]
        flow_atoms.append(atom)

    result["flow_atoms"] = flow_atoms

    return result


def migrate_literature_evidence_v0_1_to_v0_2(
    evidence_dict: dict[str, Any],
) -> dict[str, Any]:
    """Migrate a v0.1 literature evidence dict to v0.2 MethodAtom-first format.

    Changes:
      - target_node_type -> target_atom_type (dual-write)
      - NodeEvidenceLink -> AtomEvidenceLink (type field)

    Args:
        evidence_dict: v0.1 literature evidence dictionary

    Returns:
        Migrated v0.2 evidence dictionary (original is not mutated)
    """
    result = dict(evidence_dict)

    # Migrate evidence links
    if "evidence_links" in result:
        new_links = []
        for link in result["evidence_links"]:
            new_link = dict(link)
            # Dual-write target_atom_type
            if "target_atom_type" not in new_link and "target_node_type" in new_link:
                new_link["target_atom_type"] = new_link["target_node_type"]
            # Update type field
            if new_link.get("type") == "NodeEvidenceLink":
                new_link["type"] = "AtomEvidenceLink"
            new_links.append(new_link)
        result["evidence_links"] = new_links

    # Migrate method_atoms if present
    if "method_atoms" in result:
        for atom in result["method_atoms"]:
            if "atom_type" not in atom and "node_type" in atom:
                atom["atom_type"] = atom["node_type"]

    return result


def ensure_atom_fields(node_dict: dict[str, Any]) -> dict[str, Any]:
    """Ensure a node dict has MethodAtom-first fields populated.

    Useful when reading v0.1 data that hasn't been migrated yet.
    """
    result = dict(node_dict)
    if "atom_type" not in result and "type" in result:
        result["atom_type"] = result["type"]
    if "atom_id" not in result and "id" in result:
        result["atom_id"] = result["id"]
    return result


def ensure_dag_atom_fields(dag_node_dict: dict[str, Any]) -> dict[str, Any]:
    """Ensure a DAG node dict has MethodAtom-first fields populated."""
    result = dict(dag_node_dict)
    if "atom_id" not in result and "step_id" in result:
        result["atom_id"] = result["step_id"]
    if "atom_type" not in result and "node_type" in result:
        result["atom_type"] = result["node_type"]
    return result
