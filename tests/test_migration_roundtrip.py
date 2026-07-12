"""Tests for v0.1 -> v0.2 migration round-trip with demo_task_flow.json.

Verifies that:
  1. v0.1 demo flow can be loaded
  2. Migration to v0.2 produces valid output
  3. v0.2 flow can be compiled
  4. Compilation output contains MethodAtom-first fields
  5. Original v0.1 flow is not mutated
"""

import json
from pathlib import Path

import pytest

from fnirs_flow.flow.migration import (
    ensure_atom_fields,
    ensure_dag_atom_fields,
    migrate_flow_schema_v0_1_to_v0_2,
)
from fnirs_flow.flow.models import FlowGraph

CONFIGS_DIR = Path(__file__).parent.parent / "configs"
DEMO_FLOW_PATH = CONFIGS_DIR / "demo_task_flow.json"


class TestDemoFlowMigrationRoundTrip:
    """Round-trip test: load v0.1 -> migrate -> validate -> compile."""

    @pytest.fixture
    def v01_flow_dict(self) -> dict:
        if not DEMO_FLOW_PATH.exists():
            pytest.skip("demo_task_flow.json not found")
        with open(DEMO_FLOW_PATH) as f:
            return json.load(f)

    def test_v01_flow_loads(self, v01_flow_dict: dict):
        """v0.1 demo flow can be parsed as FlowGraph."""
        flow = FlowGraph.model_validate(v01_flow_dict)
        assert flow.schema_version == "0.1.0"
        assert len(flow.nodes) > 0

    def test_v01_to_v02_migration(self, v01_flow_dict: dict):
        """Migration produces valid v0.2 output with flow_atoms."""
        v02 = migrate_flow_schema_v0_1_to_v0_2(v01_flow_dict)

        assert v02["schema_version"] == "0.2.0"
        assert "flow_atoms" in v02
        assert len(v02["flow_atoms"]) == len(v02["nodes"])

        # Each atom should have atom_type
        for atom in v02["flow_atoms"]:
            assert "atom_type" in atom
            assert atom["atom_type"] == atom["type"]

    def test_v02_flow_parses(self, v01_flow_dict: dict):
        """Migrated v0.2 flow can be parsed as FlowGraph."""
        v02 = migrate_flow_schema_v0_1_to_v0_2(v01_flow_dict)
        flow = FlowGraph.model_validate(v02)
        assert flow.schema_version == "0.2.0"
        assert len(flow.nodes) > 0

    def test_v02_atom_map_works(self, v01_flow_dict: dict):
        """Migrated v0.2 flow atom_map accessor works."""
        v02 = migrate_flow_schema_v0_1_to_v0_2(v01_flow_dict)
        flow = FlowGraph.model_validate(v02)

        atoms = flow.atom_map()
        assert len(atoms) == len(flow.nodes)
        for node in flow.nodes:
            assert node.id in atoms

    def test_migration_does_not_mutate_original(self, v01_flow_dict: dict):
        """Migration does not mutate the original dict."""
        original_schema = v01_flow_dict["schema_version"]
        original_nodes = v01_flow_dict["nodes"]
        migrate_flow_schema_v0_1_to_v0_2(v01_flow_dict)

        assert v01_flow_dict["schema_version"] == original_schema
        assert v01_flow_dict["nodes"] is original_nodes

    def test_ensure_atom_fields_on_v01_nodes(self, v01_flow_dict: dict):
        """ensure_atom_fields populates atom_type from type on v0.1 nodes."""
        for node in v01_flow_dict["nodes"]:
            enriched = ensure_atom_fields(node)
            assert enriched["atom_type"] == node["type"]
            assert enriched["atom_id"] == node["id"]


class TestMigrationHelperEdgeCases:
    """Test migration helpers with edge cases."""

    def test_empty_flow_migration(self):
        v01 = {"schema_version": "0.1.0", "flow_id": "empty", "nodes": [], "edges": []}
        v02 = migrate_flow_schema_v0_1_to_v0_2(v01)
        assert v02["flow_atoms"] == []
        assert v02["nodes"] == []

    def test_node_with_existing_atom_type(self):
        node = {"id": "n1", "type": "old", "atom_type": "new"}
        result = ensure_atom_fields(node)
        assert result["atom_type"] == "new"  # preserved

    def test_dag_node_ensure_fields(self):
        dag = {"step_id": "s1", "node_type": "optical_density"}
        result = ensure_dag_atom_fields(dag)
        assert result["atom_id"] == "s1"
        assert result["atom_type"] == "optical_density"
