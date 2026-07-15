"""Integration tests for cross-backend adapter chain: Homer3 → fnirs-flow → AnalyzIR.

Validates the full pipeline:
  Homer3 .cfg/.json  →  import  →  fnirs-flow atoms  →  export  →  AnalyzIR R script
  AnalyzIR .R/.json  →  import  →  fnirs-flow atoms  →  export  →  Homer3 config
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fnirs_flow.adapters.analyzir_export import (
    convert_flow_to_analyzir,
    generate_r_script,
    write_analyzir_script,
)
from fnirs_flow.adapters.analyzir_import import (
    parse_analyzir_json,
    parse_analyzir_r_script,
)
from fnirs_flow.adapters.homer3_export import (
    convert_flow_to_homer3,
    write_homer3_config,
)
from fnirs_flow.adapters.homer3_import import (
    import_homer3,
    parse_homer3_cfg,
    parse_homer3_json,
    parse_homer3_process_func,
)

# ============================================================================
# Shared test pipelines
# ============================================================================

# A complete task-GLM preprocessing + analysis pipeline
FULL_PIPELINE_ATOMS = [
    {"atom_type": "optical_density", "config": {"parameters": {}}},
    {"atom_type": "scalp_coupling_index", "config": {"parameters": {"sci_threshold": 0.8}}},
    {"atom_type": "tddr_motion", "config": {"parameters": {}}},
    {"atom_type": "bandpass_filter", "config": {"parameters": {"l_freq": 0.01, "h_freq": 0.2}}},
    {"atom_type": "beer_lambert_law", "config": {"parameters": {"ppf": 6.0}}},
    {
        "atom_type": "block_averaging",
        "config": {"parameters": {"baseline_window": [-5, 0], "response_window": [0, 20]}},
    },
]

# Pipeline with all supported motion correction methods
MOTION_VARIANTS_ATOMS = [
    {"atom_type": "optical_density", "config": {"parameters": {}}},
    {"atom_type": "wavelet_motion_correction", "config": {"parameters": {"method": "wavelet", "threshold": 1.5}}},
    {"atom_type": "bandpass_filter", "config": {"parameters": {"l_freq": 0.01, "h_freq": 0.5}}},
    {"atom_type": "beer_lambert_law", "config": {"parameters": {"ppf": 6.0}}},
]

# Minimal pipeline (fewest steps)
MINIMAL_ATOMS = [
    {"atom_type": "optical_density", "config": {"parameters": {}}},
    {"atom_type": "beer_lambert_law", "config": {"parameters": {"ppf": 6.0}}},
]


# ============================================================================
# Homer3 → fnirs-flow → AnalyzIR
# ============================================================================


class TestHomer3ToAnalyzIR:
    """Test: Homer3 config → import → fnirs-flow atoms → export → AnalyzIR R script."""

    def test_homer3_json_to_analyzir_r_full_pipeline(self):
        """Full pipeline: Homer3 JSON → fnirs-flow atoms → AnalyzIR R script."""
        homer3_config = {
            "process_type": "preprocessing",
            "steps": [
                {"name": "od", "func": "hmrR_Intensity2OD", "params": {}},
                {"name": "td", "func": "hmrR_MotionCorrectTD", "params": {}},
                {"name": "filt", "func": "hmrR_BandpassFilt", "params": {"lpf": 0.2, "hpf": 0.01}},
                {"name": "bll", "func": "hmrR_OD2Conc", "params": {"DPF": [6, 6]}},
                {"name": "sci", "func": "hmrR_Sci", "params": {"sciThresh": 0.8}},
                {"name": "block", "func": "hmrR_BlockAvg", "params": {"tRange": [-5, 20]}},
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Step 1: Write Homer3 config
            homer3_path = tmpdir / "homer3_config.json"
            homer3_path.write_text(json.dumps(homer3_config), encoding="utf-8")

            # Step 2: Import Homer3 → fnirs-flow atoms
            import_result = parse_homer3_json(homer3_path)
            assert len(import_result.atoms) == 6
            assert len(import_result.unmapped_functions) == 0

            # Step 3: Export fnirs-flow atoms → AnalyzIR R script
            script = convert_flow_to_analyzir(import_result.atoms)
            assert len(script.steps) == 6
            assert len(script.unmapped_atoms) == 0

            # Step 4: Write R script
            r_path = write_analyzir_script(script, tmpdir, "pipeline.R")
            assert r_path.exists()

            # Step 5: Verify R script content
            r_content = r_path.read_text(encoding="utf-8")
            assert "hmrR_Intensity2OD" in r_content
            assert "hmrR_MotionCorrectTD" in r_content
            assert "hmrR_BandpassFilt" in r_content
            assert "hmrR_OD2Conc" in r_content
            assert "hmrR_Sci" in r_content
            assert "hmrR_BlockAvg" in r_content

    def test_homer3_cfg_to_analyzir_r(self):
        """Full pipeline: Homer3 .cfg → fnirs-flow atoms → AnalyzIR R script."""
        cfg_content = """\
[data] = hmrR_Intensity2OD(data)
[data] = hmrR_MotionCorrectTD(data)
[data] = hmrR_BandpassFilt(data, 0.5, 0.01, 2)
[data] = hmrR_OD2Conc(data, [6, 6])
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Step 1: Write .cfg
            cfg_path = tmpdir / "process.cfg"
            cfg_path.write_text(cfg_content, encoding="utf-8")

            # Step 2: Import
            import_result = parse_homer3_cfg(cfg_path)
            assert len(import_result.atoms) == 4

            # Step 3: Export to AnalyzIR
            script = convert_flow_to_analyzir(import_result.atoms)
            r_content = generate_r_script(script)

            # Step 4: Verify
            assert "hmrR_Intensity2OD" in r_content
            assert "hmrR_MotionCorrectTD" in r_content
            assert "hmrR_BandpassFilt" in r_content
            assert "hmrR_OD2Conc" in r_content

    def test_homer3_process_func_to_analyzir_json(self):
        """Full pipeline: Homer3 processFunc → fnirs-flow atoms → AnalyzIR JSON."""
        process_func = [
            {"func": "hmrR_Intensity2OD", "param": []},
            {"func": "hmrR_MotionCorrectWavelet", "param": [1.5]},
            {"func": "hmrR_OD2Conc", "param": [[6, 6]]},
        ]

        # Step 1: Import
        import_result = parse_homer3_process_func(process_func)
        assert len(import_result.atoms) == 3

        # Step 2: Export to AnalyzIR
        script = convert_flow_to_analyzir(import_result.atoms)

        # Step 3: Verify atom types preserved
        atom_types = [s.name for s in script.steps]
        assert "optical_density" in atom_types
        assert "wavelet_motion_correction" in atom_types
        assert "beer_lambert_law" in atom_types

    def test_homer3_to_analyzir_preserves_parameters(self):
        """Verify parameters survive the full chain."""
        homer3_config = {
            "steps": [
                {
                    "name": "bp",
                    "func": "hmrR_BandpassFilt",
                    "params": {"lpf": 0.3, "hpf": 0.02, "Order": 4},
                },
                {
                    "name": "bll",
                    "func": "hmrR_OD2Conc",
                    "params": {"DPF": [7.0, 7.0]},
                },
                {
                    "name": "sci",
                    "func": "hmrR_Sci",
                    "params": {"sciThresh": 0.7},
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            homer3_path = tmpdir / "config.json"
            homer3_path.write_text(json.dumps(homer3_config), encoding="utf-8")

            # Import
            import_result = parse_homer3_json(homer3_path)

            # Export to AnalyzIR
            script = convert_flow_to_analyzir(import_result.atoms)
            r_content = generate_r_script(script)

            # Verify parameters in R output
            assert "lpf=0.3" in r_content
            assert "hpf=0.02" in r_content
            assert "sciThresh=0.7" in r_content
            assert "DPF=c(7.0, 7.0)" in r_content

    def test_homer3_to_analyzir_unmapped_functions_tracked(self):
        """Verify unmapped Homer3 functions are tracked through the chain."""
        homer3_config = {
            "steps": [
                {"name": "od", "func": "hmrR_Intensity2OD", "params": {}},
                {"name": "custom", "func": "hmrR_CustomFutureFunction", "params": {}},
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            homer3_path = tmpdir / "config.json"
            homer3_path.write_text(json.dumps(homer3_config), encoding="utf-8")

            # Import
            import_result = parse_homer3_json(homer3_path)
            assert len(import_result.atoms) == 1
            assert len(import_result.unmapped_functions) == 1

            # Export (only mapped atoms go through)
            script = convert_flow_to_analyzir(import_result.atoms)
            assert len(script.steps) == 1
            assert len(script.unmapped_atoms) == 0  # No new unmapped

    def test_homer3_to_analyzir_roundtrip_file_io(self):
        """Full file-based round-trip: Homer3 JSON → files → AnalyzIR R → files."""
        homer3_config = {
            "steps": [
                {"name": "od", "func": "hmrR_Intensity2OD", "params": {}},
                {"name": "td", "func": "hmrR_MotionCorrectTD", "params": {}},
                {"name": "bp", "func": "hmrR_BandpassFilt", "params": {"lpf": 0.2, "hpf": 0.01}},
                {"name": "bll", "func": "hmrR_OD2Conc", "params": {"DPF": [6, 6]}},
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Write Homer3 config
            homer3_dir = tmpdir / "homer3"
            homer3_dir.mkdir()
            homer3_path = homer3_dir / "config.json"
            homer3_path.write_text(json.dumps(homer3_config), encoding="utf-8")

            # Import Homer3
            import_result = import_homer3(homer3_path)

            # Export AnalyzIR
            analyzir_dir = tmpdir / "analyzir"
            script = convert_flow_to_analyzir(import_result.atoms)
            r_path = write_analyzir_script(script, analyzir_dir)

            # Verify files exist
            assert homer3_path.exists()
            assert r_path.exists()

            # Verify content consistency
            r_content = r_path.read_text(encoding="utf-8")
            assert "hmrR_Intensity2OD" in r_content
            assert "hmrR_MotionCorrectTD" in r_content
            assert "hmrR_BandpassFilt" in r_content
            assert "hmrR_OD2Conc" in r_content


# ============================================================================
# AnalyzIR → fnirs-flow → Homer3
# ============================================================================


class TestAnalyzIRToHomer3:
    """Test: AnalyzIR R script → import → fnirs-flow atoms → export → Homer3 config."""

    def test_analyzir_r_to_homer3_json(self):
        """Full pipeline: AnalyzIR R → fnirs-flow atoms → Homer3 JSON."""
        r_script = """\
data <- load("test.snirf")
data <- hmrR_Intensity2OD(data)
data <- hmrR_MotionCorrectTD(data)
data <- hmrR_BandpassFilt(data, lpf=0.5, hpf=0.01)
data <- hmrR_OD2Conc(data, DPF=c(6, 6))
data <- hmrR_Sci(data, sciThresh=0.8)
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Step 1: Write R script
            r_path = tmpdir / "pipeline.R"
            r_path.write_text(r_script, encoding="utf-8")

            # Step 2: Import AnalyzIR → fnirs-flow atoms
            import_result = parse_analyzir_r_script(r_path)
            assert len(import_result.atoms) == 5

            # Step 3: Export fnirs-flow atoms → Homer3 config
            config = convert_flow_to_homer3(import_result.atoms)
            assert len(config.steps) == 5
            assert len(config.unmapped_atoms) == 0

            # Step 4: Write Homer3 config
            homer3_path = write_homer3_config(config, tmpdir)
            assert homer3_path.exists()

            # Step 5: Verify content
            content = json.loads(homer3_path.read_text(encoding="utf-8"))
            funcs = [s["func"] for s in content["steps"]]
            assert "hmrR_Intensity2OD" in funcs
            assert "hmrR_MotionCorrectTD" in funcs
            assert "hmrR_BandpassFilt" in funcs
            assert "hmrR_OD2Conc" in funcs
            assert "hmrR_Sci" in funcs

    def test_analyzir_json_to_homer3_json(self):
        """Full pipeline: AnalyzIR JSON → fnirs-flow atoms → Homer3 JSON."""
        analyzir_config = {
            "data_path": "test.snirf",
            "steps": [
                {"func": "hmrR_Intensity2OD", "params": {}},
                {"func": "hmrR_MotionCorrectPCA", "params": {"SVDCut": 0.95}},
                {"func": "hmrR_OD2Conc", "params": {"DPF": [6, 6]}},
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Write AnalyzIR JSON
            json_path = tmpdir / "analyzir_config.json"
            json_path.write_text(json.dumps(analyzir_config), encoding="utf-8")

            # Import
            import_result = parse_analyzir_json(json_path)
            assert len(import_result.atoms) == 3

            # Export to Homer3
            config = convert_flow_to_homer3(import_result.atoms)
            assert len(config.steps) == 3

            # Verify functions
            funcs = {s.name: s.func for s in config.steps}
            assert funcs["optical_density"] == "hmrR_Intensity2OD"
            assert funcs["pca_motion_correction"] == "hmrR_MotionCorrectPCA"
            assert funcs["beer_lambert_law"] == "hmrR_OD2Conc"

    def test_analyzir_to_homer3_preserves_parameters(self):
        """Verify parameters survive AnalyzIR → Homer3 chain."""
        r_script = """\
data <- hmrR_BandpassFilt(data, lpf=0.3, hpf=0.02)
data <- hmrR_Sci(data, sciThresh=0.7)
data <- hmrR_MotionCorrectWavelet(data, iqr=2.0)
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            r_path = Path(tmpdir) / "pipeline.R"
            r_path.write_text(r_script, encoding="utf-8")

            # Import
            import_result = parse_analyzir_r_script(r_path)

            # Export to Homer3
            config = convert_flow_to_homer3(import_result.atoms)

            # Verify parameters
            # AnalyzIR import stores canonical fnirs-flow names (h_freq/l_freq)
            bp_step = next(s for s in config.steps if s.name == "bandpass_filter")
            assert bp_step.params["h_freq"] == 0.3
            assert bp_step.params["l_freq"] == 0.02

            sci_step = next(s for s in config.steps if s.name == "scalp_coupling_index")
            assert sci_step.params["sci_threshold"] == 0.7

            wavelet_step = next(s for s in config.steps if s.name == "wavelet_motion_correction")
            assert wavelet_step.params["threshold"] == 2.0

    def test_analyzir_to_homer3_unmapped_tracked(self):
        """Verify unmapped AnalyzIR functions are tracked."""
        r_script = """\
data <- hmrR_Intensity2OD(data)
data <- hmrR_FutureUnknown(data)
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            r_path = Path(tmpdir) / "pipeline.R"
            r_path.write_text(r_script, encoding="utf-8")

            import_result = parse_analyzir_r_script(r_path)
            assert len(import_result.atoms) == 1
            assert len(import_result.unmapped_functions) == 1

            config = convert_flow_to_homer3(import_result.atoms)
            assert len(config.steps) == 1


# ============================================================================
# Symmetry tests: Homer3 ↔ AnalyzIR ↔ fnirs-flow
# ============================================================================


class TestCrossBackendSymmetry:
    """Verify that the mapping is symmetric: both directions produce consistent results."""

    def test_fnirs_flow_atoms_to_both_and_back(self):
        """Export to both Homer3 and AnalyzIR, then import both back."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Export original atoms to both formats
            homer3_config = convert_flow_to_homer3(FULL_PIPELINE_ATOMS)
            analyzir_script = convert_flow_to_analyzir(FULL_PIPELINE_ATOMS)

            # Write both
            homer3_path = write_homer3_config(homer3_config, tmpdir / "homer3")
            r_path = write_analyzir_script(analyzir_script, tmpdir / "analyzir")

            # Import both back
            homer3_result = parse_homer3_json(homer3_path)
            analyzir_result = parse_analyzir_r_script(r_path)

            # Compare atom types
            homer3_types = {a["atom_type"] for a in homer3_result.atoms}
            analyzir_types = {a["atom_type"] for a in analyzir_result.atoms}

            assert homer3_types == analyzir_types

    def test_all_motion_corrections_symmetric(self):
        """All motion correction methods map correctly in both directions."""
        motion_atoms = [
            {"atom_type": "tddr_motion", "config": {"parameters": {"method": "tddr"}}},
            {
                "atom_type": "wavelet_motion_correction",
                "config": {"parameters": {"method": "wavelet", "threshold": 1.5}},
            },
            {
                "atom_type": "spline_motion_correction",
                "config": {"parameters": {"method": "spline", "threshold": 0.99}},
            },
            {"atom_type": "pca_motion_correction", "config": {"parameters": {"method": "pca", "n_components": 0.95}}},
            {"atom_type": "cbsi_motion_correction", "config": {"parameters": {"method": "cbsi", "alpha": 0.7}}},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Export to Homer3
            h3_config = convert_flow_to_homer3(motion_atoms)
            h3_path = write_homer3_config(h3_config, tmpdir / "h3")

            # Export to AnalyzIR
            az_script = convert_flow_to_analyzir(motion_atoms)
            az_path = write_analyzir_script(az_script, tmpdir / "az")

            # Import back
            h3_result = parse_homer3_json(h3_path)
            az_result = parse_analyzir_r_script(az_path)

            # All 5 motion methods should round-trip
            h3_types = {a["atom_type"] for a in h3_result.atoms}
            az_types = {a["atom_type"] for a in az_result.atoms}

            assert "tddr_motion" in h3_types
            assert "tddr_motion" in az_types
            assert "wavelet_motion_correction" in h3_types
            assert "wavelet_motion_correction" in az_types
            assert "spline_motion_correction" in h3_types
            assert "spline_motion_correction" in az_types
            assert "pca_motion_correction" in h3_types
            assert "pca_motion_correction" in az_types
            assert "cbsi_motion_correction" in h3_types
            assert "cbsi_motion_correction" in az_types

    def test_homer3_chain_to_analyzir_chain_to_homer3(self):
        """Triple chain: Homer3 → atoms → AnalyzIR R → atoms → Homer3 config."""
        original_homer3 = {
            "steps": [
                {"name": "od", "func": "hmrR_Intensity2OD", "params": {}},
                {"name": "td", "func": "hmrR_MotionCorrectTD", "params": {}},
                {"name": "bp", "func": "hmrR_BandpassFilt", "params": {"lpf": 0.2, "hpf": 0.01}},
                {"name": "bll", "func": "hmrR_OD2Conc", "params": {"DPF": [6, 6]}},
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Step 1: Write original Homer3 config
            h3_path_1 = tmpdir / "original.json"
            h3_path_1.write_text(json.dumps(original_homer3), encoding="utf-8")

            # Step 2: Import Homer3 → atoms
            atoms_1 = parse_homer3_json(h3_path_1)

            # Step 3: Export atoms → AnalyzIR R
            script = convert_flow_to_analyzir(atoms_1.atoms)
            r_path = write_analyzir_script(script, tmpdir / "analyzir")

            # Step 4: Import AnalyzIR R → atoms
            atoms_2 = parse_analyzir_r_script(r_path)

            # Step 5: Export atoms → Homer3 config
            config_2 = convert_flow_to_homer3(atoms_2.atoms)
            h3_path_2 = write_homer3_config(config_2, tmpdir / "final")

            # Step 6: Verify final Homer3 config
            final_config = json.loads(h3_path_2.read_text(encoding="utf-8"))
            final_funcs = [s["func"] for s in final_config["steps"]]

            # All original functions should survive the triple chain
            original_funcs = [s["func"] for s in original_homer3["steps"]]
            assert set(original_funcs) == set(final_funcs)

    def test_analyzir_chain_to_homer3_chain_to_analyzir(self):
        """Triple chain: AnalyzIR R → atoms → Homer3 → atoms → AnalyzIR R."""
        original_r = """\
data <- hmrR_Intensity2OD(data)
data <- hmrR_MotionCorrectTD(data)
data <- hmrR_BandpassFilt(data, lpf=0.2, hpf=0.01)
data <- hmrR_OD2Conc(data, DPF=c(6, 6))
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Step 1: Write original R script
            r_path_1 = tmpdir / "original.R"
            r_path_1.write_text(original_r, encoding="utf-8")

            # Step 2: Import R → atoms
            atoms_1 = parse_analyzir_r_script(r_path_1)

            # Step 3: Export atoms → Homer3
            config = convert_flow_to_homer3(atoms_1.atoms)
            h3_path = write_homer3_config(config, tmpdir / "homer3")

            # Step 4: Import Homer3 → atoms
            atoms_2 = parse_homer3_json(h3_path)

            # Step 5: Export atoms → AnalyzIR R
            script = convert_flow_to_analyzir(atoms_2.atoms)
            r_path_2 = write_analyzir_script(script, tmpdir / "final")

            # Step 6: Verify final R script
            final_r = r_path_2.read_text(encoding="utf-8")

            # All original functions should survive
            assert "hmrR_Intensity2OD" in final_r
            assert "hmrR_MotionCorrectTD" in final_r
            assert "hmrR_BandpassFilt" in final_r
            assert "hmrR_OD2Conc" in final_r

    def test_atom_count_preserved_through_chain(self):
        """Atom count is preserved through all conversion paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Homer3 path
            h3_config = convert_flow_to_homer3(FULL_PIPELINE_ATOMS)
            h3_path = write_homer3_config(h3_config, tmpdir / "h3")
            h3_imported = parse_homer3_json(h3_path)

            # AnalyzIR path
            az_script = convert_flow_to_analyzir(FULL_PIPELINE_ATOMS)
            r_path = write_analyzir_script(az_script, tmpdir / "az")
            az_imported = parse_analyzir_r_script(r_path)

            # Both should have same atom count
            assert len(h3_imported.atoms) == len(az_imported.atoms)

            # Cross-export
            h3_to_az = convert_flow_to_analyzir(h3_imported.atoms)
            az_to_h3 = convert_flow_to_homer3(az_imported.atoms)

            assert len(h3_to_az.steps) == len(az_to_h3.steps)

    def test_operation_field_consistent_across_backends(self):
        """The 'operation' field is consistent regardless of import source."""
        homer3_config = {
            "steps": [
                {"name": "od", "func": "hmrR_Intensity2OD", "params": {}},
                {"name": "bp", "func": "hmrR_BandpassFilt", "params": {"lpf": 0.5, "hpf": 0.01}},
                {"name": "bll", "func": "hmrR_OD2Conc", "params": {"DPF": [6, 6]}},
            ]
        }

        analyzir_r = """\
data <- hmrR_Intensity2OD(data)
data <- hmrR_BandpassFilt(data, lpf=0.5, hpf=0.01)
data <- hmrR_OD2Conc(data, DPF=c(6, 6))
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Import from both sources
            h3_path = tmpdir / "h3.json"
            h3_path.write_text(json.dumps(homer3_config), encoding="utf-8")
            h3_result = parse_homer3_json(h3_path)

            r_path = tmpdir / "az.R"
            r_path.write_text(analyzir_r, encoding="utf-8")
            az_result = parse_analyzir_r_script(r_path)

            # Compare operations
            h3_ops = {a["atom_type"]: a["operation"] for a in h3_result.atoms}
            az_ops = {a["atom_type"]: a["operation"] for a in az_result.atoms}

            assert h3_ops == az_ops
