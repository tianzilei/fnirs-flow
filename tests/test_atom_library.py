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
