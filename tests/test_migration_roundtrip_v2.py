"""Migration roundtrip tests for flow_atoms + nodes dual-write.

These tests verify that:
1. v0.1 flows can be migrated to v0.2
2. v0.2 flows roundtrip through dump/load correctly
3. Migration table tracks all schema changes
4. Typed error codes are consistent
"""

from __future__ import annotations

import json

from fnirs_flow.flow.migration import (
    ensure_atom_fields,
    migrate_flow_schema_v0_1_to_v0_2,
)
from fnirs_flow.flow.migrations.rewrite import migrate_flow
from fnirs_flow.flow.migrations.schema import (
    MIGRATION_TABLE,
    get_latest_version,
    needs_migration,
)
from fnirs_flow.flow.models import FlowGraph
from fnirs_flow.flow.serialization import load_canonical_flow
from fnirs_flow.validation.error_codes import (
    ERROR_CODE_MAP,
    ErrorCode,
    all_error_codes,
    get_error_domain,
    get_error_severity,
)

# ============================================================================
# Fixtures
# ============================================================================


def _v0_1_flow_dict() -> dict:
    """A minimal v0.1 flow dict with legacy naming."""
    return {
        "schema_version": "0.1.0",
        "flow_id": "test-flow-001",
        "name": "Test Flow",
        "nodes": [
            {
                "id": "node-1",
                "type": "optical_density",
                "category": "preprocessing",
                "config": {"operation": "optical_density"},
            },
            {
                "id": "node-2",
                "type": "beer_lambert_law",
                "category": "preprocessing",
                "config": {"operation": "beer_lambert_law"},
            },
        ],
        "edges": [
            {
                "id": "edge-1",
                "source": "node-1",
                "target": "node-2",
                "source_handle": "out",
                "target_handle": "in",
            }
        ],
    }


def _v0_2_flow_dict() -> dict:
    """A minimal v0.2 flow dict with MethodAtom-first naming."""
    return {
        "schema_version": "0.2.0",
        "flow_id": "test-flow-002",
        "name": "Test Flow v2",
        "nodes": [
            {
                "id": "atom-1",
                "type": "optical_density",
                "atom_type": "optical_density",
                "category": "preprocessing",
                "config": {"operation": "optical_density"},
            },
            {
                "id": "atom-2",
                "type": "beer_lambert_law",
                "atom_type": "beer_lambert_law",
                "category": "preprocessing",
                "config": {"operation": "beer_lambert_law"},
            },
        ],
        "flow_atoms": [
            {
                "id": "atom-1",
                "type": "optical_density",
                "atom_type": "optical_density",
                "category": "preprocessing",
                "config": {"operation": "optical_density"},
            },
            {
                "id": "atom-2",
                "type": "beer_lambert_law",
                "atom_type": "beer_lambert_law",
                "category": "preprocessing",
                "config": {"operation": "beer_lambert_law"},
            },
        ],
        "edges": [
            {
                "id": "edge-1",
                "source": "atom-1",
                "target": "atom-2",
                "source_handle": "out",
                "target_handle": "in",
            }
        ],
    }


# ============================================================================
# Migration v0.1 -> v0.2
# ============================================================================


class TestV01ToV02Migration:
    def test_adds_flow_atoms(self):
        v01 = _v0_1_flow_dict()
        v02 = migrate_flow_schema_v0_1_to_v0_2(v01)
        assert "flow_atoms" in v02
        assert "nodes" not in v02
        assert len(v02["flow_atoms"]) == len(v01["nodes"])

    def test_adds_atom_type(self):
        v01 = _v0_1_flow_dict()
        v02 = migrate_flow_schema_v0_1_to_v0_2(v01)
        for atom in v02["flow_atoms"]:
            assert "atom_type" in atom
            assert "type" not in atom

    def test_removes_legacy_nodes(self):
        v01 = _v0_1_flow_dict()
        v02 = migrate_flow_schema_v0_1_to_v0_2(v01)
        assert "nodes" not in v02

    def test_does_not_mutate_original(self):
        v01 = _v0_1_flow_dict()
        original_nodes = json.loads(json.dumps(v01["nodes"]))
        migrate_flow_schema_v0_1_to_v0_2(v01)
        assert v01["nodes"] == original_nodes

    def test_schema_version_bumps(self):
        v01 = _v0_1_flow_dict()
        v02 = migrate_flow_schema_v0_1_to_v0_2(v01)
        assert v02["schema_version"] == "0.2.0"


# ============================================================================
# Migration table
# ============================================================================


class TestMigrationTable:
    def test_table_has_entries(self):
        assert len(MIGRATION_TABLE) > 0

    def test_latest_version(self):
        assert get_latest_version() == "0.4.0"

    def test_needs_migration_for_v01(self):
        assert needs_migration("0.1.0")

    def test_no_migration_for_latest(self):
        assert not needs_migration("0.4.0")

    def test_migration_chain_versions(self):
        for entry in MIGRATION_TABLE:
            assert entry.from_version != entry.to_version


# ============================================================================
# Full migrate_flow via rewrite module
# ============================================================================


class TestMigrateFlowRewrite:
    def test_v01_to_latest(self):
        v01 = _v0_1_flow_dict()
        result = migrate_flow(v01)
        assert result["schema_version"] == get_latest_version()
        assert "flow_atoms" in result
        assert len(result["flow_atoms"]) == 2

    def test_v02_unchanged(self):
        v02 = _v0_2_flow_dict()
        result = migrate_flow(v02)
        assert result["schema_version"] == "0.4.0"
        assert len(result["flow_atoms"]) == 2

    def test_roundtrip_through_model(self):
        v02 = _v0_2_flow_dict()
        migrated = migrate_flow(v02)
        flow = FlowGraph.model_validate(migrated)
        dumped = flow.model_dump(exclude_none=True)
        assert dumped["schema_version"] == "0.4.0"
        assert len(dumped.get("flow_atoms", [])) == 2
        assert "nodes" not in dumped


# ============================================================================
# Model-level dual-write
# ============================================================================


class TestFlowGraphCanonicalModel:
    def test_model_dump_uses_flow_atoms_only(self):
        v02 = _v0_2_flow_dict()
        # Remove flow_atoms to test auto-population
        v02.pop("flow_atoms", None)
        flow = load_canonical_flow(v02)
        dumped = flow.model_dump(exclude_none=True)
        assert "flow_atoms" in dumped
        assert "nodes" not in dumped
        assert len(dumped["flow_atoms"]) == 2

    def test_atom_map_uses_flow_atoms(self):
        v02 = _v0_2_flow_dict()
        flow = FlowGraph.model_validate(v02)
        atom_map = flow.atom_map()
        assert "atom-1" in atom_map
        assert "atom-2" in atom_map


# ============================================================================
# ensure_atom_fields helper
# ============================================================================


class TestEnsureAtomFields:
    def test_adds_atom_type(self):
        node = {"id": "n1", "type": "optical_density", "category": "preprocessing"}
        result = ensure_atom_fields(node)
        assert result["atom_type"] == "optical_density"
        assert result["atom_id"] == "n1"

    def test_preserves_existing(self):
        node = {
            "id": "n1",
            "type": "optical_density",
            "atom_type": "custom_od",
            "category": "preprocessing",
        }
        result = ensure_atom_fields(node)
        assert result["atom_type"] == "custom_od"


# ============================================================================
# Typed error codes
# ============================================================================


class TestTypedErrorCodes:
    def test_all_codes_present(self):
        codes = all_error_codes()
        assert len(codes) >= 17
        assert "atom-compat-version-unsatisfied" in codes
        assert "flow-cycle-detected" in codes
        assert "harmonization-site-missing" in codes

    def test_error_code_map_consistent(self):
        for code in ErrorCode:
            severity, domain = ERROR_CODE_MAP[code]
            assert severity.value in ("fatal", "high", "medium", "low")
            assert isinstance(domain, str)

    def test_severity_helpers(self):
        assert get_error_severity(ErrorCode.ATOM_MANIFEST_MISSING).value == "fatal"
        assert get_error_domain(ErrorCode.ADAPTER_SCHEMA_MISMATCH) == "adapter"
        assert get_error_severity(ErrorCode.REPRODUCIBILITY_NO_SEED).value == "low"
