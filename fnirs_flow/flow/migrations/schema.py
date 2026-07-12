"""Migration schema: version registry and migration entry definitions."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MigrationEntry(BaseModel):
    """A single migration step from one schema version to the next."""

    from_version: str
    to_version: str
    description: str
    rewrites: list[str] = Field(default_factory=list)


# Canonical migration table: ordered list of schema upgrades
MIGRATION_TABLE: list[MigrationEntry] = [
    MigrationEntry(
        from_version="0.1.0",
        to_version="0.2.0",
        description="MethodAtom-first migration: add flow_atoms, atom_type, template_id",
        rewrites=[
            "node_type -> atom_type (dual-write on each atom)",
            "nodes -> flow_atoms (dual-write, keep nodes for compat)",
            "add template_id field to each atom",
        ],
    ),
]


def get_latest_version() -> str:
    """Return the latest schema version."""
    if not MIGRATION_TABLE:
        return "0.1.0"
    return MIGRATION_TABLE[-1].to_version


def get_migrations_from(version: str) -> list[MigrationEntry]:
    """Return all migration entries that apply starting from the given version.

    A migration applies when its from_version >= the current version,
    meaning the flow at that version needs to go through that migration.
    """
    result: list[MigrationEntry] = []
    for entry in MIGRATION_TABLE:
        if _version_gte(entry.from_version, version):
            result.append(entry)
    return result


def needs_migration(version: str) -> bool:
    """Check if a flow at the given version needs migration."""
    return version != get_latest_version()


def _parse_version_part(x: str) -> int:
    """Extract leading numeric part from a semver segment (e.g., '2' from '2-beta')."""
    digits = ""
    for c in x:
        if c.isdigit():
            digits += c
        else:
            break
    return int(digits) if digits else 0


def _version_gte(a: str, b: str) -> bool:
    """Simple semver greater-than-or-equal comparison, tolerating pre-release suffixes."""
    parts_a = [_parse_version_part(x) for x in a.split(".")]
    parts_b = [_parse_version_part(x) for x in b.split(".")]
    return parts_a >= parts_b
