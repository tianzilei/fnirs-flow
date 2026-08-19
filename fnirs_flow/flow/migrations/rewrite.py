"""Migration rewriters: transform flow dicts between schema versions."""

from __future__ import annotations

from typing import Any

from fnirs_flow.flow.migrations.schema import get_migrations_from


def migrate_flow(flow_dict: dict[str, Any]) -> dict[str, Any]:
    """Migrate a flow dict from its current version to the latest.

    Applies all necessary migrations in order. Returns a new dict
    (the original is not mutated).
    """
    current_version = flow_dict.get("schema_version", "0.1.0")
    migrations = get_migrations_from(current_version)

    if not migrations:
        return dict(flow_dict)

    result = dict(flow_dict)
    for migration in migrations:
        result = _apply_migration(result, migration.from_version, migration.to_version)

    return result


def _apply_migration(
    flow_dict: dict[str, Any],
    from_version: str,
    to_version: str,
) -> dict[str, Any]:
    """Apply a specific migration step."""
    result = dict(flow_dict)

    if from_version == "0.1.0" and to_version == "0.2.0":
        result = _migrate_v0_1_to_v0_2(result)

    result["schema_version"] = to_version
    return result


def _migrate_v0_1_to_v0_2(flow_dict: dict[str, Any]) -> dict[str, Any]:
    """v0.1 -> v0.2: MethodAtom-first migration.

    Changes:
      - nodes -> flow_atoms
      - type -> atom_type
      - Add template_id field to each atom
    """
    from fnirs_flow.flow.serialization import normalize_flow_payload

    result = normalize_flow_payload(flow_dict)
    flow_atoms = []
    for item in result.get("flow_atoms", []):
        atom = dict(item)
        # Ensure template_id field exists
        if "template_id" not in atom:
            atom["template_id"] = atom.get("metadata", {}).get("template_id")
        flow_atoms.append(atom)

    result["flow_atoms"] = flow_atoms

    # Migrate evidence links if present
    if "evidence_links" in result:
        new_links = []
        for link in result["evidence_links"]:
            new_link = dict(link)
            if "target_atom_type" not in new_link and "target_node_type" in new_link:
                new_link["target_atom_type"] = new_link["target_node_type"]
            if new_link.get("type") == "NodeEvidenceLink":
                new_link["type"] = "AtomEvidenceLink"
            new_links.append(new_link)
        result["evidence_links"] = new_links

    return result
