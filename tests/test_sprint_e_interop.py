"""Sprint E tests: Homer3 export adapter and ComBat diagnostics atom."""

from __future__ import annotations

import json

from fnirs_flow.adapters.homer3_export import (
    ATOM_TO_HOMER3,
    Homer3ProcessConfig,
    convert_flow_to_homer3,
    write_homer3_config,
    write_homer3_mapping_report,
)
from fnirs_flow.registry.combat_diagnostics import (
    ComBatPreflightResult,
    generate_combat_output_manifest,
    validate_combat_preflight,
)

# ============================================================================
# Homer3 export adapter tests
# ============================================================================


class TestHomer3Export:
    def test_atom_to_homer3_mapping_has_common_atoms(self):
        assert "optical_density" in ATOM_TO_HOMER3
        assert "beer_lambert_law" in ATOM_TO_HOMER3
        assert "bandpass_filter" in ATOM_TO_HOMER3
        assert "scalp_coupling_index" in ATOM_TO_HOMER3

    def test_convert_mapped_atoms(self):
        atoms = [
            {"atom_type": "optical_density", "config": {}},
            {"atom_type": "bandpass_filter", "config": {"parameters": {"lpf": 0.5}}},
            {"atom_type": "beer_lambert_law", "config": {}},
        ]
        config = convert_flow_to_homer3(atoms)
        assert len(config.steps) == 3
        assert config.steps[0].func == "hmrR_Intensity2OD"
        assert len(config.unmapped_atoms) == 0

    def test_convert_unmapped_atoms(self):
        atoms = [
            {"atom_type": "ica_motion_correction", "config": {}},
            {"atom_type": "custom_atom", "config": {}},
        ]
        config = convert_flow_to_homer3(atoms)
        assert len(config.steps) == 0
        assert len(config.unmapped_atoms) == 2
        assert "ica_motion_correction" in config.unmapped_atoms

    def test_convert_mixed_atoms(self):
        atoms = [
            {"atom_type": "optical_density", "config": {}},
            {"atom_type": "ica_motion_correction", "config": {}},
            {"atom_type": "beer_lambert_law", "config": {}},
        ]
        config = convert_flow_to_homer3(atoms)
        assert len(config.steps) == 2
        assert len(config.unmapped_atoms) == 1

    def test_convert_legacy_type_field(self):
        atoms = [
            {"type": "optical_density", "config": {}},
        ]
        config = convert_flow_to_homer3(atoms)
        assert len(config.steps) == 1

    def test_write_homer3_config(self, tmp_path):
        atoms = [
            {"atom_type": "optical_density", "config": {}},
            {"atom_type": "beer_lambert_law", "config": {}},
        ]
        config = convert_flow_to_homer3(atoms)
        path = write_homer3_config(config, tmp_path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data["steps"]) == 2

    def test_write_mapping_report(self, tmp_path):
        atoms = [
            {"atom_type": "optical_density", "config": {}},
            {"atom_type": "ica_motion_correction", "config": {}},
        ]
        config = convert_flow_to_homer3(atoms)
        path = write_homer3_mapping_report(config, tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "Mapped Steps" in content
        assert "Unmapped Atoms" in content
        assert "ica_motion_correction" in content

    def test_homer3_process_config_model(self):
        config = Homer3ProcessConfig()
        assert config.process_type == "preprocessing"
        assert len(config.steps) == 0


# ============================================================================
# ComBat diagnostics tests
# ============================================================================


class TestComBatDiagnostics:
    def _make_manifest(self, runs):
        return {"subject_session_runs": runs}

    def test_preflight_passes_with_valid_data(self):
        runs = [{"subject": f"sub-{i:02d}", "site": "site_A", "group": "control"} for i in range(10)] + [
            {"subject": f"sub-{i + 10:02d}", "site": "site_B", "group": "patient"} for i in range(10)
        ]
        manifest = self._make_manifest(runs)
        result = validate_combat_preflight(
            manifest,
            biological_covariates=["age", "sex"],
        )
        assert result.ready
        assert result.site_summary["n_sites"] == 2

    def test_preflight_fatal_when_no_site(self):
        runs = [
            {"subject": "sub-01", "group": "control"},
            {"subject": "sub-02", "group": "patient"},
        ]
        manifest = self._make_manifest(runs)
        result = validate_combat_preflight(manifest)
        assert not result.ready
        assert any(r.severity == "fatal" for r in result.risks)

    def test_preflight_warns_few_samples(self):
        runs = [
            {"subject": "sub-01", "site": "site_A", "group": "control"},
            {"subject": "sub-02", "site": "site_B", "group": "patient"},
            {"subject": "sub-03", "site": "site_B", "group": "patient"},
        ]
        manifest = self._make_manifest(runs)
        result = validate_combat_preflight(manifest, min_samples_per_site=5)
        assert result.ready
        assert any("site_B" in r.message for r in result.risks)

    def test_preflight_warns_no_covariates(self):
        runs = [{"subject": f"sub-{i:02d}", "site": "site_A"} for i in range(10)]
        manifest = self._make_manifest(runs)
        result = validate_combat_preflight(manifest, biological_covariates=[])
        assert result.ready
        assert any(r.risk_id == "combat-no-covariates" for r in result.risks)

    def test_preflight_detects_confounding(self):
        runs = [
            {"subject": "sub-01", "site": "site_A", "group": "control"},
            {"subject": "sub-02", "site": "site_A", "group": "control"},
            {"subject": "sub-03", "site": "site_B", "group": "patient"},
            {"subject": "sub-04", "site": "site_B", "group": "patient"},
        ]
        manifest = self._make_manifest(runs)
        result = validate_combat_preflight(
            manifest,
            biological_covariates=["age"],
            min_samples_per_site=2,
        )
        assert any(r.risk_id == "combat-site-confounded" for r in result.risks)

    def test_output_manifest(self):
        preflight = ComBatPreflightResult(
            site_summary={"n_sites": 2, "total_runs": 20},
            covariate_summary={"declared_covariates": ["age", "sex"]},
        )
        manifest = generate_combat_output_manifest(
            preflight,
            harmonization_params={"method": "neuroCombat"},
        )
        assert manifest.input_site_count == 2
        assert manifest.input_subject_count == 20
        assert "age" in manifest.covariates_preserved
