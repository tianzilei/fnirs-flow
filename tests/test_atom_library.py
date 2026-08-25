"""Tests for MethodAtomTemplate and MethodAtomLibrary aliases."""

import pytest

from fnirs_flow.flow.atoms import ReadinessStatus
from fnirs_flow.flow.models import NodeCategory, NodeOrigin
from fnirs_flow.registry.atom_templates import (
    ALL_METHOD_ATOM_TEMPLATES,
    HANDWRITTEN_ATOM_TEMPLATES,
    LITERATURE_METHOD_ATOM_TEMPLATES,
    refresh_method_atom_templates,
)
from fnirs_flow.registry.local_atoms import discover_local_method_atom_templates
from fnirs_flow.registry.methodatom_library import (
    load_literature_method_atom_templates,
    method_atom_library_state,
    write_runtime_state,
)
from fnirs_flow.registry.node_library import (
    MethodAtomLibrary,
    MethodAtomTemplate,
    NodeLibrary,
    NodeTemplate,
    create_builtin_library,
)


class TestMethodAtomTemplateAlias:
    """Verify MethodAtomTemplate is an alias for NodeTemplate."""

    def test_alias_identity(self):
        assert MethodAtomTemplate is NodeTemplate

    def test_create_with_new_name(self):
        template = MethodAtomTemplate(
            template_id="test_atom",
            name="Test Atom",
            category=NodeCategory.PREPROCESSING,
            atom_type="optical_density",
        )
        assert template.template_id == "test_atom"
        assert template.category == NodeCategory.PREPROCESSING


class TestMethodAtomLibraryAlias:
    """Verify MethodAtomLibrary is an alias for NodeLibrary."""

    def test_alias_identity(self):
        assert MethodAtomLibrary is NodeLibrary

    def test_create_with_new_name(self):
        library = MethodAtomLibrary()
        assert isinstance(library, NodeLibrary)


class TestCreateAtomMethod:
    """Test that create_atom works as an alias for create_node."""

    def test_create_atom(self):
        library = create_builtin_library()
        atom = library.create_atom("optical_density", atom_id="test-od")
        assert atom is not None
        assert atom.id == "test-od"
        assert atom.type == "optical_density"

    def test_create_atom_returns_none_for_missing(self):
        library = create_builtin_library()
        assert library.create_atom("nonexistent") is None

    def test_create_atom_deterministic(self):
        library = create_builtin_library()
        atom1 = library.create_atom("optical_density", atom_id="same-id")
        library2 = create_builtin_library()
        atom2 = library2.create_atom("optical_density", atom_id="same-id")
        assert atom1.id == atom2.id
        assert atom1.type == atom2.type


class TestLiteratureDerivedMethodAtoms:
    """Verify synthesized MethodAtom records are bundled as built-in templates."""

    def test_literature_templates_are_loaded(self):
        state = method_atom_library_state()
        assert len(LITERATURE_METHOD_ATOM_TEMPLATES) == state["method_atoms_rows"]
        assert len(ALL_METHOD_ATOM_TEMPLATES) == len(HANDWRITTEN_ATOM_TEMPLATES) + state["method_atoms_rows"]

    def test_literature_template_is_in_builtin_library(self):
        library = create_builtin_library()
        template = library.get("atom_descriptive_statistics")
        assert template is not None
        assert template.origin == NodeOrigin.EVIDENCE_DERIVED
        assert "literature_derived" in template.tags
        assert len(template.evidence_refs) > 0

    def test_create_literature_derived_atom(self):
        library = create_builtin_library()
        atom = library.create_atom("atom_descriptive_statistics", atom_id="desc")
        assert atom is not None
        assert atom.origin == NodeOrigin.EVIDENCE_DERIVED
        assert "source_atom_id" not in atom.config
        assert atom.metadata["source_atom_id"] == "ATOM_descriptive_statistics"

    def test_literature_candidates_are_not_executable_defaults(self):
        template = next(
            item for item in LITERATURE_METHOD_ATOM_TEMPLATES if item.template_id == "atom_motion_correction"
        )
        assert "method" not in template.default_config
        assert "method" in template.metadata["parameter_candidates"]
        assert template.default_readiness_status.value == "needs_attention"

    def test_nirs_spm_spatial_registration_projection_atom(self):
        library = create_builtin_library()
        template = library.get("atom_nirs_spm_spatial_registration_projection")
        assert template is not None
        assert template.operation == "nirs_spm_spatial_registration_projection"
        assert "NIRS_SPM_UsersGuide_v4_spatial_registration" in template.evidence_refs
        assert template.metadata["parameter_candidates"]["software"] == "NIRS-SPM v4 r1"
        assert "software" not in template.default_config
        assert template.metadata["parameter_candidates"]["mri_registration_algorithm"] == "Horn absolute orientation"
        assert template.metadata["parameter_candidates"]["template_registration_algorithm"] == "NFRI MNI estimation"
        assert template.metadata["parameter_candidates"]["projection_sequence"] == [
            "rendered_brain",
            "hypothetical_head_surface",
            "cortical_surface",
        ]
        assert template.metadata["execution_readiness"] == "needs_attention"

    def test_localization_projection_import_atom_is_executable(self):
        library = create_builtin_library()
        template = library.get("localization_projection_import")
        assert template is not None
        assert template.operation == "localization_projection_import"
        assert template.default_execution_scope == "group"
        assert template.default_readiness_status == ReadinessStatus.READY
        assert template.output_ports[0].port_schema == "ProjectedMNIChannels"
        atom = library.create_atom("localization_projection_import", atom_id="loc")
        assert atom is not None
        assert atom.execution_scope == "group"
        assert atom.readiness_status == ReadinessStatus.READY

    def test_nirs_spm_surface_projection_atom_is_executable(self):
        library = create_builtin_library()
        template = library.get("nirs_spm_surface_projection")
        assert template is not None
        assert template.operation == "nirs_spm_surface_projection"
        assert template.default_execution_scope == "group"
        assert template.default_readiness_status == ReadinessStatus.NEEDS_ATTENTION
        assert template.output_ports[0].port_schema == "ProjectedMNIChannels"
        atom = library.create_atom("nirs_spm_surface_projection", atom_id="nirsspm-projection")
        assert atom is not None
        assert atom.execution_scope == "group"
        assert atom.readiness_status == ReadinessStatus.NEEDS_ATTENTION

    def test_runtime_state_reports_library_inputs(self):
        state = method_atom_library_state()
        assert state["method_atoms_rows"] > 0
        assert state["atom_evidence_links_rows"] >= 0
        assert state["method_atoms_size"] > 0

    def test_refresh_keeps_literature_templates_current(self):
        library_state = method_atom_library_state()
        state = refresh_method_atom_templates(force=True, write_state=False)
        assert state["loaded_templates"] == library_state["method_atoms_rows"]
        assert state["total_templates"] == len(HANDWRITTEN_ATOM_TEMPLATES) + library_state["method_atoms_rows"]

    def test_runtime_state_is_written_to_external_cache(self, tmp_path):
        state = refresh_method_atom_templates(force=True, write_state=False)
        path = write_runtime_state(state, tmp_path / "registry-cache")
        assert path.parent == tmp_path / "registry-cache"
        assert path.is_file()
        assert str(state["method_atoms_rows"]) in path.read_text(encoding="utf-8")

    def test_duplicate_resource_ids_are_rejected(self, tmp_path):
        atoms = tmp_path / "atoms.csv"
        atoms.write_text(
            "atom_id,operation,domain\natom_x,one,analysis\natom_x,two,analysis\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Duplicate MethodAtom template id"):
            load_literature_method_atom_templates(atoms, tmp_path / "missing-links.csv")

    def test_missing_resource_ids_are_rejected(self, tmp_path):
        atoms = tmp_path / "atoms.csv"
        atoms.write_text("atom_id,operation,domain\n,one,analysis\n", encoding="utf-8")
        with pytest.raises(ValueError, match="atom_id is required"):
            load_literature_method_atom_templates(atoms, tmp_path / "missing-links.csv")

    def test_cedalion_method_atoms_have_explicit_backend_bindings(self):
        library = create_builtin_library()
        template = library.get("atom_dot_image_recon")
        assert template is not None
        assert template.backend_binding is not None
        assert template.backend_binding.backend_id == "cedalion"
        assert template.backend_binding.operation == "reconstruct_image"
        assert "experimental" in template.tags
        assert template.metadata["verification_status"] == "contract_test_required"

    def test_cedalion_binding_is_preserved_when_atom_is_created(self):
        library = create_builtin_library()
        atom = library.create_atom("atom_dot_image_recon", atom_id="dot-recon")
        assert atom is not None
        assert atom.backend_binding is not None
        assert atom.backend_binding.backend_id == "cedalion"
        assert atom.backend_binding.operation == "reconstruct_image"
        assert atom.readiness_status == ReadinessStatus.NEEDS_ATTENTION

    def test_verified_cedalion_atom_is_ready(self):
        library = create_builtin_library()
        template = library.get("atom_extinction_coefficients")
        assert template is not None
        assert "experimental" not in template.tags
        atom = library.create_atom("atom_extinction_coefficients", atom_id="extinction")
        assert atom is not None
        assert atom.backend_binding is not None
        assert atom.backend_binding.operation == "get_extinction_coefficients"
        assert atom.readiness_status == ReadinessStatus.READY

    def test_bundled_method_atoms_have_complete_parameter_status_and_stable_ports(self):
        import csv
        import json

        from fnirs_flow.registry.methodatom_library import METHOD_ATOMS_CSV

        allowed_domains = {
            "data_import",
            "metadata",
            "acquisition",
            "qc",
            "preprocessing",
            "analysis",
            "machine_learning",
            "reporting",
            "export",
            "security",
        }
        with METHOD_ATOMS_CSV.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert rows
        for row in rows:
            parameters = json.loads(row["parameters"])
            statuses = json.loads(row["parameter_status"])
            assert set(parameters) == set(statuses), row["atom_id"]
            assert row["domain"] in allowed_domains, row["atom_id"]
            assert row["input_port"] == "input_data", row["atom_id"]
            assert row["output_port"] == "output_data", row["atom_id"]
            if any(value in {"inferred", "missing"} for value in statuses.values()):
                assert row["readiness_status"] == "needs_attention", row["atom_id"]

    def test_bundled_templates_have_resolvable_nonempty_sequences(self):
        import csv
        import json

        from fnirs_flow.registry.methodatom_library import PACKAGE_LIBRARY_DIR

        def rows(name: str):
            with (PACKAGE_LIBRARY_DIR / name).open(encoding="utf-8", newline="") as stream:
                return list(csv.DictReader(stream))

        atom_ids = {row["atom_id"] for row in rows("method_atoms.csv")}
        slot_ids = {row["slot_id"] for row in rows("flow_slot_contracts.csv")}
        rule_ids = {row["rule_id"] for row in rows("risk_rule_candidates.csv")}
        requirement_ids = {row["requirement_id"] for row in rows("reporting_requirements.csv")}
        for template in rows("templates.csv"):
            atoms = json.loads(template["atom_sequence"])
            slots = json.loads(template["slot_sequence"])
            risks = json.loads(template["required_risk_rules"])
            requirements = json.loads(template["required_reporting_requirements"])
            assert atoms and set(atoms) <= atom_ids, template["template_id"]
            assert slots and set(slots) <= slot_ids, template["template_id"]
            assert len(atoms) == len(slots), template["template_id"]
            assert risks and set(risks) <= rule_ids, template["template_id"]
            assert requirements and set(requirements) <= requirement_ids, template["template_id"]

    def test_bundled_sources_have_local_bibliographic_titles(self):
        import csv

        from fnirs_flow.registry.methodatom_library import PACKAGE_LIBRARY_DIR

        with (PACKAGE_LIBRARY_DIR / "sources.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert rows
        assert all(row["title"] and row["title"] != "Bundled extracted evidence source" for row in rows)

    def test_local_python_declaration_is_static_and_quarantined(self, tmp_path):
        path = tmp_path / "workshop_atom.py"
        path.write_text(
            "METHOD_ATOM = "
            "{'template_id': 'workshop_local', 'name': 'Workshop local', "
            "'category': 'analysis', 'atom_type': 'workshop_local', "
            "'operation': 'workshop_local', 'ports': ["
            "{'name': 'input', 'direction': 'in', 'schema': 'Input'}, "
            "{'name': 'output', 'direction': 'out', 'schema': 'Output'}], "
            "'implementation': 'workshop_impl:execute'}\n",
            encoding="utf-8",
        )
        discovered = discover_local_method_atom_templates(tmp_path)
        assert discovered.errors == []
        assert len(discovered.templates) == 1
        template = discovered.templates[0]
        assert template.origin == NodeOrigin.IMPORTED
        assert template.metadata["local_atom_file"] == str(path)
        assert template.implementation_module == "workshop_impl"
        assert template.implementation_callable == "execute"

        library = MethodAtomLibrary()
        library.register(template)
        atom = library.create_atom("workshop_local", atom_id="local-1")
        assert atom is not None
        assert atom.metadata["local_atom_file"] == "workshop_atom.py"
        assert atom.template_snapshot["metadata"]["local_atom_file"] == "workshop_atom.py"

    def test_local_python_code_is_not_executed(self, tmp_path):
        path = tmp_path / "unsafe_atom.py"
        path.write_text(
            "open('should-not-exist.txt', 'w').write('bad')\n"
            "METHOD_ATOM = {'template_id': 'unsafe', 'name': 'Unsafe', "
            "'category': 'analysis', 'atom_type': 'unsafe'}\n",
            encoding="utf-8",
        )
        discovered = discover_local_method_atom_templates(tmp_path)
        assert discovered.errors == []
        assert not (tmp_path / "should-not-exist.txt").exists()

    def test_local_duplicate_is_reported_by_registry(self, tmp_path):
        (tmp_path / "one.json").write_text(
            '{"template_id":"local_duplicate","name":"One","category":"analysis","atom_type":"one"}',
            encoding="utf-8",
        )
        (tmp_path / "two.json").write_text(
            '{"template_id":"local_duplicate","name":"Two","category":"analysis","atom_type":"two"}',
            encoding="utf-8",
        )
        discovered = discover_local_method_atom_templates(tmp_path)
        library = MethodAtomLibrary()
        with pytest.raises(ValueError, match="Duplicate MethodAtom template id"):
            library.register_many(discovered.templates)

    def test_local_templates_are_composed_by_refresh(self, tmp_path):
        path = tmp_path / "local.json"
        path.write_text(
            '{"template_id":"workshop_refresh","name":"Workshop refresh",'
            '"category":"analysis","atom_type":"workshop_refresh",'
            '"ports":[{"name":"in","direction":"in","schema":"Input"},'
            '{"name":"out","direction":"out","schema":"Output"}]}',
            encoding="utf-8",
        )
        state = refresh_method_atom_templates(force=True, write_state=False, local_atom_dir=str(tmp_path))
        assert state["local_templates"] == 1
        from fnirs_flow.registry.atom_templates import ALL_METHOD_ATOM_TEMPLATES

        template = next(item for item in ALL_METHOD_ATOM_TEMPLATES if item.template_id == "workshop_refresh")
        assert template is not None
        assert template.origin == NodeOrigin.IMPORTED
        # Restore the default discovery state for subsequent tests.
        refresh_method_atom_templates(force=True, write_state=False)
