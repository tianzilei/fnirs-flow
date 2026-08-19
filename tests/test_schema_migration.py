"""Tests for schema migration helpers: v0.1 -> v0.2 MethodAtom-first migration."""

from fnirs_flow.flow.migration import (
    ensure_atom_fields,
    ensure_dag_atom_fields,
    migrate_flow_schema_v0_1_to_v0_2,
    migrate_literature_evidence_v0_1_to_v0_2,
)


class TestFlowSchemaMigration:
    """Test flow.json v0.1 -> v0.2 migration."""

    def test_basic_migration(self):
        v01 = {
            "schema_version": "0.1.0",
            "flow_id": "test-flow",
            "nodes": [
                {
                    "id": "n1",
                    "type": "optical_density",
                    "category": "preprocessing",
                    "position": {"x": 0, "y": 0},
                },
            ],
            "edges": [],
        }
        v02 = migrate_flow_schema_v0_1_to_v0_2(v01)

        assert v02["schema_version"] == "0.2.0"
        assert v02["flow_id"] == "test-flow"
        # Legacy nodes are consumed at the migration boundary.
        assert "nodes" not in v02
        assert len(v02["flow_atoms"]) == 1
        assert v02["flow_atoms"][0]["atom_type"] == "optical_density"

    def test_preserves_existing_atom_type(self):
        v01 = {
            "schema_version": "0.1.0",
            "flow_id": "test-flow",
            "nodes": [
                {
                    "id": "n1",
                    "type": "optical_density",
                    "atom_type": "custom_atom",
                    "category": "preprocessing",
                    "position": {"x": 0, "y": 0},
                },
            ],
            "edges": [],
        }
        v02 = migrate_flow_schema_v0_1_to_v0_2(v01)
        # existing atom_type preserved
        assert v02["flow_atoms"][0]["atom_type"] == "custom_atom"

    def test_does_not_mutate_original(self):
        v01 = {
            "schema_version": "0.1.0",
            "flow_id": "test-flow",
            "nodes": [
                {
                    "id": "n1",
                    "type": "optical_density",
                    "category": "preprocessing",
                    "position": {"x": 0, "y": 0},
                },
            ],
            "edges": [],
        }
        original_nodes = v01["nodes"]
        migrate_flow_schema_v0_1_to_v0_2(v01)
        assert v01["nodes"] is original_nodes

    def test_empty_flow(self):
        v01 = {"schema_version": "0.1.0", "flow_id": "test", "nodes": [], "edges": []}
        v02 = migrate_flow_schema_v0_1_to_v0_2(v01)
        assert v02["flow_atoms"] == []


class TestLiteratureEvidenceMigration:
    """Test literature evidence v0.1 -> v0.2 migration."""

    def test_migrates_target_node_type(self):
        v01 = {
            "evidence_links": [
                {"target_node_type": "optical_density", "type": "NodeEvidenceLink"},
            ]
        }
        v02 = migrate_literature_evidence_v0_1_to_v0_2(v01)
        link = v02["evidence_links"][0]
        assert link["target_atom_type"] == "optical_density"
        assert link["target_node_type"] == "optical_density"  # original preserved
        assert link["type"] == "AtomEvidenceLink"

    def test_preserves_existing_target_atom_type(self):
        v01 = {
            "evidence_links": [
                {"target_node_type": "old", "target_atom_type": "new", "type": "AtomEvidenceLink"},
            ]
        }
        v02 = migrate_literature_evidence_v0_1_to_v0_2(v01)
        assert v02["evidence_links"][0]["target_atom_type"] == "new"

    def test_migrates_method_atom_node_type(self):
        v01 = {
            "method_atoms": [
                {"node_type": "optical_density"},
            ]
        }
        v02 = migrate_literature_evidence_v0_1_to_v0_2(v01)
        assert v02["method_atoms"][0]["atom_type"] == "optical_density"


class TestEnsureAtomFields:
    """Test ensure_atom_fields helper."""

    def test_adds_atom_type_from_type(self):
        node = {"id": "n1", "type": "optical_density"}
        result = ensure_atom_fields(node)
        assert result["atom_type"] == "optical_density"
        assert result["atom_id"] == "n1"

    def test_preserves_existing_atom_type(self):
        node = {"id": "n1", "type": "optical_density", "atom_type": "custom"}
        result = ensure_atom_fields(node)
        assert result["atom_type"] == "custom"

    def test_does_not_mutate_original(self):
        node = {"id": "n1", "type": "optical_density"}
        ensure_atom_fields(node)
        assert "atom_type" not in node


class TestEnsureDagAtomFields:
    """Test ensure_dag_atom_fields helper."""

    def test_adds_atom_fields(self):
        dag_node = {"step_id": "s1", "node_type": "optical_density"}
        result = ensure_dag_atom_fields(dag_node)
        assert result["atom_id"] == "s1"
        assert result["atom_type"] == "optical_density"

    def test_preserves_existing(self):
        dag_node = {"step_id": "s1", "node_type": "old", "atom_id": "a1", "atom_type": "new"}
        result = ensure_dag_atom_fields(dag_node)
        assert result["atom_id"] == "a1"
        assert result["atom_type"] == "new"
