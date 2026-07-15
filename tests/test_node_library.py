"""Tests for enhanced node library with extensibility."""

from __future__ import annotations

from fnirs_flow.flow.models import NodeCategory
from fnirs_flow.registry.node_library import NodeLibrary, NodeTemplate, create_builtin_library
from fnirs_flow.registry.node_templates import ALL_NODE_TEMPLATES


class TestNodeTemplate:
    def test_create_template(self):
        template = NodeTemplate(
            template_id="test",
            name="Test Node",
            category=NodeCategory.DATA,
            atom_type="test_type",
        )
        assert template.template_id == "test"
        assert template.category == NodeCategory.DATA

    def test_matches_tags(self):
        template = NodeTemplate(
            template_id="test",
            name="Test",
            category=NodeCategory.DATA,
            atom_type="test",
            tags=["data", "input"],
        )
        assert template.matches_tags(["data"])
        assert not template.matches_tags(["output"])
        assert template.matches_tags(["data", "output"])


class TestNodeLibrary:
    def test_register_template(self):
        lib = NodeLibrary()
        template = NodeTemplate(
            template_id="test",
            name="Test",
            category=NodeCategory.DATA,
            atom_type="test",
        )
        lib.register(template)
        assert lib.get("test") is not None

    def test_register_many(self):
        lib = NodeLibrary()
        templates = [
            NodeTemplate(template_id=f"t{i}", name=f"T{i}", category=NodeCategory.DATA, atom_type=f"type{i}")
            for i in range(5)
        ]
        count = lib.register_many(templates)
        assert count == 5
        assert len(lib.all_ids()) == 5

    def test_by_category(self):
        lib = NodeLibrary()
        lib.register(NodeTemplate(template_id="d1", name="D1", category=NodeCategory.DATA, atom_type="d"))
        lib.register(NodeTemplate(template_id="p1", name="P1", category=NodeCategory.PREPROCESSING, atom_type="p"))
        assert len(lib.by_category(NodeCategory.DATA)) == 1
        assert len(lib.by_category(NodeCategory.PREPROCESSING)) == 1

    def test_by_tags(self):
        lib = NodeLibrary()
        lib.register(
            NodeTemplate(
                template_id="t1",
                name="T1",
                category=NodeCategory.DATA,
                atom_type="t",
                tags=["data", "input"],
            )
        )
        lib.register(
            NodeTemplate(
                template_id="t2",
                name="T2",
                category=NodeCategory.DATA,
                atom_type="t",
                tags=["output"],
            )
        )
        assert len(lib.by_tags(["data"])) == 1
        assert len(lib.by_tags(["output"])) == 1

    def test_create_atom(self):
        lib = NodeLibrary()
        lib.register(
            NodeTemplate(
                template_id="test",
                name="Test",
                category=NodeCategory.DATA,
                atom_type="test_type",
                default_config={"param": "value"},
            )
        )
        atom = lib.create_atom("test")
        assert atom is not None
        assert atom.type == "test_type"
        assert atom.config["param"] == "value"

    def test_create_atom_with_override(self):
        lib = NodeLibrary()
        lib.register(
            NodeTemplate(
                template_id="test",
                name="Test",
                category=NodeCategory.DATA,
                atom_type="test_type",
                default_config={"param": "default"},
            )
        )
        atom = lib.create_atom("test", config_override={"param": "override"})
        assert atom.config["param"] == "override"

    def test_create_atom_unknown(self):
        lib = NodeLibrary()
        assert lib.create_atom("nonexistent") is None

    def test_export_import(self, tmp_path):
        lib = NodeLibrary()
        lib.register(
            NodeTemplate(
                template_id="test",
                name="Test",
                category=NodeCategory.DATA,
                atom_type="test",
            )
        )

        # Export
        path = tmp_path / "templates.json"
        count = lib.export_to_file(path)
        assert count == 1

        # Import
        lib2 = NodeLibrary()
        count = lib2.load_from_file(path)
        assert count == 1
        assert lib2.get("test") is not None


class TestBuiltinLibrary:
    def test_create_builtin_library(self):
        lib = create_builtin_library()
        assert len(lib.all_ids()) > 0

    def test_builtin_templates_count(self):
        assert len(ALL_NODE_TEMPLATES) >= 25

    def test_all_categories_covered(self):
        lib = create_builtin_library()
        categories = {t.category for t in lib.all()}
        assert NodeCategory.DATA in categories
        assert NodeCategory.DESIGN in categories
        assert NodeCategory.PREPROCESSING in categories
        assert NodeCategory.ANALYSIS in categories
        assert NodeCategory.OUTPUT in categories
        assert NodeCategory.VALIDATION in categories
        assert NodeCategory.EXPORT in categories

    def test_data_nodes(self):
        lib = create_builtin_library()
        data_nodes = lib.by_category(NodeCategory.DATA)
        assert len(data_nodes) >= 3
        assert any(t.template_id == "dataset_discovery" for t in data_nodes)

    def test_preprocessing_nodes(self):
        lib = create_builtin_library()
        prep_nodes = lib.by_category(NodeCategory.PREPROCESSING)
        assert len(prep_nodes) >= 5
        assert any(t.template_id == "optical_density" for t in prep_nodes)
        assert any(t.template_id == "beer_lambert_law" for t in prep_nodes)

    def test_analysis_nodes(self):
        lib = create_builtin_library()
        analysis_nodes = lib.by_category(NodeCategory.ANALYSIS)
        assert len(analysis_nodes) >= 4
        assert any(t.template_id == "first_level_glm" for t in analysis_nodes)

    def test_ml_nodes(self):
        lib = create_builtin_library()
        ml_nodes = lib.by_tags(["ml"])
        assert len(ml_nodes) >= 2
        assert any(t.template_id == "feature_extraction" for t in ml_nodes)
        assert any(t.template_id == "ml_model" for t in ml_nodes)

    def test_connectivity_nodes(self):
        lib = create_builtin_library()
        conn_nodes = lib.by_tags(["connectivity"])
        assert len(conn_nodes) >= 2

    def test_hyperscanning_nodes(self):
        lib = create_builtin_library()
        hyper_nodes = lib.by_tags(["hyperscanning"])
        assert len(hyper_nodes) >= 1

    def test_multi_site_nodes(self):
        lib = create_builtin_library()
        multi_site_nodes = lib.by_tags(["multi_site"])
        assert len(multi_site_nodes) >= 6
        assert any(t.template_id == "site_metadata_extraction" for t in multi_site_nodes)
        assert any(t.template_id == "site_level_qc" for t in multi_site_nodes)
        assert any(t.template_id == "combat_harmonization" for t in multi_site_nodes)
        assert any(t.template_id == "linear_mixed_effects_glm" for t in multi_site_nodes)
        assert any(t.template_id == "site_covariate_glm" for t in multi_site_nodes)
        assert any(t.template_id == "batch_effect_diagnostics" for t in multi_site_nodes)
