"""Tests for Homer3 bidirectional import/export adapters."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fnirs_flow.adapters.homer3_export import (
    Homer3ProcessConfig,
    convert_flow_to_homer3,
    write_homer3_config,
    write_homer3_mapping_report,
)
from fnirs_flow.adapters.homer3_import import (
    Homer3ImportResult,
    import_homer3,
    parse_homer3_cfg,
    parse_homer3_json,
    parse_homer3_process_func,
    write_import_report,
)

# ============================================================================
# Fixtures
# ============================================================================

SAMPLE_FLOW_ATOMS = [
    {
        "atom_type": "optical_density",
        "config": {"parameters": {}},
    },
    {
        "atom_type": "tddr_motion",
        "config": {"parameters": {}},
    },
    {
        "atom_type": "bandpass_filter",
        "config": {"parameters": {"l_freq": 0.01, "h_freq": 0.5}},
    },
    {
        "atom_type": "beer_lambert_law",
        "config": {"parameters": {"ppf": 6.0}},
    },
    {
        "atom_type": "block_averaging",
        "config": {"parameters": {"baseline_window": [-5, 0], "response_window": [0, 20]}},
    },
    {
        "atom_type": "unknown_custom_step",
        "config": {"parameters": {}},
    },
]

SAMPLE_HOMER3_CONFIG = {
    "process_type": "preprocessing",
    "steps": [
        {"name": "optical_density", "func": "hmrR_Intensity2OD", "params": {}},
        {"name": "tddr_motion", "func": "hmrR_MotionCorrectTD", "params": {}},
        {
            "name": "bandpass_filter",
            "func": "hmrR_BandpassFilt",
            "params": {"lpf": 0.5, "hpf": 0.01},
        },
        {
            "name": "beer_lambert_law",
            "func": "hmrR_OD2Conc",
            "params": {"DPF": [6, 6]},
        },
    ],
}

SAMPLE_PROCESS_FUNC = [
    {"func": "hmrR_Intensity2OD", "param": []},
    {"func": "hmrR_MotionCorrectTD", "param": []},
    {"func": "hmrR_BandpassFilt", "param": [0.5, 0.01, 2]},
    {"func": "hmrR_OD2Conc", "param": [[6, 6]]},
]


# ============================================================================
# Export Tests
# ============================================================================


class TestHomer3Export:
    """Test Homer3 export functionality."""

    def test_convert_flow_to_homer3_basic(self):
        """Test basic conversion of flow atoms to Homer3 config."""
        config = convert_flow_to_homer3(SAMPLE_FLOW_ATOMS)

        assert isinstance(config, Homer3ProcessConfig)
        assert len(config.steps) == 5  # 5 mapped atoms
        assert len(config.unmapped_atoms) == 1  # unknown_custom_step

    def test_convert_flow_to_homer3_step_names(self):
        """Test that step names are preserved."""
        config = convert_flow_to_homer3(SAMPLE_FLOW_ATOMS)

        step_names = [s.name for s in config.steps]
        assert "optical_density" in step_names
        assert "tddr_motion" in step_names
        assert "bandpass_filter" in step_names
        assert "beer_lambert_law" in step_names
        assert "block_averaging" in step_names

    def test_convert_flow_to_homer3_functions(self):
        """Test that Homer3 function names are correct."""
        config = convert_flow_to_homer3(SAMPLE_FLOW_ATOMS)

        func_map = {s.name: s.func for s in config.steps}
        assert func_map["optical_density"] == "hmrR_Intensity2OD"
        assert func_map["tddr_motion"] == "hmrR_MotionCorrectTD"
        assert func_map["bandpass_filter"] == "hmrR_BandpassFilt"
        assert func_map["beer_lambert_law"] == "hmrR_OD2Conc"

    def test_convert_flow_to_homer3_params(self):
        """Test that parameters are correctly mapped."""
        config = convert_flow_to_homer3(SAMPLE_FLOW_ATOMS)

        bp_step = next(s for s in config.steps if s.name == "bandpass_filter")
        assert bp_step.params["lpf"] == 0.5
        assert bp_step.params["hpf"] == 0.01

    def test_convert_flow_to_homer3_unmapped(self):
        """Test that unmapped atoms are tracked."""
        config = convert_flow_to_homer3(SAMPLE_FLOW_ATOMS)

        assert "unknown_custom_step" in config.unmapped_atoms

    def test_write_homer3_config(self):
        """Test writing Homer3 config to file."""
        config = convert_flow_to_homer3(SAMPLE_FLOW_ATOMS)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_homer3_config(config, Path(tmpdir))
            assert path.exists()
            assert path.name == "homer3_process_config.json"

            content = json.loads(path.read_text(encoding="utf-8"))
            assert "steps" in content
            assert len(content["steps"]) == 5

    def test_write_homer3_mapping_report(self):
        """Test writing Homer3 mapping report."""
        config = convert_flow_to_homer3(SAMPLE_FLOW_ATOMS)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_homer3_mapping_report(config, Path(tmpdir))
            assert path.exists()
            assert path.name == "homer3_mapping_report.md"

            content = path.read_text(encoding="utf-8")
            assert "Mapped Steps" in content
            assert "Unmapped Atoms" in content
            assert "hmrR_Intensity2OD" in content

    def test_convert_empty_atoms(self):
        """Test conversion with empty atom list."""
        config = convert_flow_to_homer3([])
        assert len(config.steps) == 0
        assert len(config.unmapped_atoms) == 0

    def test_convert_ica_unmapped(self):
        """Test that ICA motion correction is unmapped."""
        atoms = [{"atom_type": "ica_motion_correction", "config": {"parameters": {}}}]
        config = convert_flow_to_homer3(atoms)
        assert len(config.steps) == 0
        assert "ica_motion_correction" in config.unmapped_atoms


# ============================================================================
# Import Tests
# ============================================================================


class TestHomer3Import:
    """Test Homer3 import functionality."""

    def test_parse_homer3_json_basic(self):
        """Test parsing Homer3 JSON config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(SAMPLE_HOMER3_CONFIG), encoding="utf-8")

            result = parse_homer3_json(config_path)

            assert isinstance(result, Homer3ImportResult)
            assert len(result.atoms) == 4
            assert result.source_format == "homer3_json"

    def test_parse_homer3_json_atom_types(self):
        """Test that imported atom types are correct."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(SAMPLE_HOMER3_CONFIG), encoding="utf-8")

            result = parse_homer3_json(config_path)

            atom_types = [a["atom_type"] for a in result.atoms]
            assert "optical_density" in atom_types
            assert "tddr_motion" in atom_types
            assert "bandpass_filter" in atom_types
            assert "beer_lambert_law" in atom_types

    def test_parse_homer3_json_params(self):
        """Test that parameters are correctly imported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(SAMPLE_HOMER3_CONFIG), encoding="utf-8")

            result = parse_homer3_json(config_path)

            bp_atom = next(a for a in result.atoms if a["atom_type"] == "bandpass_filter")
            assert bp_atom["config"]["parameters"]["h_freq"] == 0.5
            assert bp_atom["config"]["parameters"]["l_freq"] == 0.01

    def test_parse_homer3_json_missing_file(self):
        """Test parsing non-existent file."""
        result = parse_homer3_json("/nonexistent/config.json")
        assert len(result.warnings) > 0
        assert len(result.atoms) == 0

    def test_parse_homer3_process_func(self):
        """Test parsing processFunc call list."""
        result = parse_homer3_process_func(SAMPLE_PROCESS_FUNC)

        assert len(result.atoms) == 4
        assert result.source_format == "homer3_process_func"

    def test_parse_homer3_process_func_params(self):
        """Test that positional params are correctly mapped."""
        result = parse_homer3_process_func(SAMPLE_PROCESS_FUNC)

        bp_atom = next(a for a in result.atoms if a["atom_type"] == "bandpass_filter")
        # Positional params go through _map_bandpass_params: lpf->h_freq, hpf->l_freq
        assert bp_atom["config"]["parameters"]["h_freq"] == 0.5
        assert bp_atom["config"]["parameters"]["l_freq"] == 0.01

    def test_parse_homer3_cfg(self):
        """Test parsing Homer3 .cfg file."""
        cfg_content = """\
[data] = hmrR_Intensity2OD(data)
[data] = hmrR_MotionCorrectTD(data)
[data] = hmrR_BandpassFilt(data, 0.5, 0.01, 2)
[data] = hmrR_OD2Conc(data, [6, 6])
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "process.cfg"
            cfg_path.write_text(cfg_content, encoding="utf-8")

            result = parse_homer3_cfg(cfg_path)

            assert len(result.atoms) == 4
            assert result.source_format == "homer3_cfg"

    def test_parse_homer3_cfg_missing_file(self):
        """Test parsing non-existent .cfg file."""
        result = parse_homer3_cfg("/nonexistent/process.cfg")
        assert len(result.warnings) > 0

    def test_import_homer3_json(self):
        """Test import_homer3 with JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(SAMPLE_HOMER3_CONFIG), encoding="utf-8")

            result = import_homer3(config_path)
            assert len(result.atoms) == 4

    def test_import_homer3_cfg(self):
        """Test import_homer3 with .cfg file."""
        cfg_content = '[data] = hmrR_Intensity2OD(data)\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "process.cfg"
            cfg_path.write_text(cfg_content, encoding="utf-8")

            result = import_homer3(cfg_path)
            assert len(result.atoms) == 1

    def test_import_homer3_unsupported(self):
        """Test import_homer3 with unsupported format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_path = Path(tmpdir) / "process.txt"
            txt_path.write_text("some content", encoding="utf-8")

            result = import_homer3(txt_path)
            assert len(result.warnings) > 0

    def test_write_import_report(self):
        """Test writing import report."""
        result = parse_homer3_process_func(SAMPLE_PROCESS_FUNC)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_import_report(result, Path(tmpdir))
            assert path.exists()
            assert path.name == "homer3_import_report.md"

            content = path.read_text(encoding="utf-8")
            assert "Imported Atoms" in content
            assert "hmrR_Intensity2OD" in content

    def test_import_unknown_function(self):
        """Test importing config with unknown function."""
        process_func = [
            {"func": "hmrR_Intensity2OD", "param": []},
            {"func": "hmrR_UnknownFunction", "param": []},
        ]
        result = parse_homer3_process_func(process_func)

        assert len(result.atoms) == 1
        assert len(result.unmapped_functions) == 1
        assert result.unmapped_functions[0]["function"] == "hmrR_UnknownFunction"


# ============================================================================
# Round-trip Tests
# ============================================================================


class TestHomer3RoundTrip:
    """Test export -> import round-trip consistency."""

    def test_export_then_import_preserves_atoms(self):
        """Test that export then import preserves the same atom types."""
        # Export
        config = convert_flow_to_homer3(SAMPLE_FLOW_ATOMS)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write exported config
            outdir = Path(tmpdir) / "export"
            write_homer3_config(config, outdir)

            # Import back
            config_path = outdir / "homer3_process_config.json"
            result = parse_homer3_json(config_path)

        # Compare atom types (excluding unmapped)
        exported_types = {s.name for s in config.steps}
        imported_types = {a["atom_type"] for a in result.atoms}

        assert exported_types == imported_types

    def test_export_then_import_preserves_operations(self):
        """Test that operations are preserved through round-trip."""
        config = convert_flow_to_homer3(SAMPLE_FLOW_ATOMS)

        with tempfile.TemporaryDirectory() as tmpdir:
            outdir = Path(tmpdir) / "export"
            write_homer3_config(config, outdir)

            config_path = outdir / "homer3_process_config.json"
            result = parse_homer3_json(config_path)

        exported_ops = {s.name: s.func for s in config.steps}
        for atom in result.atoms:
            atom_type = atom["atom_type"]
            if atom_type in exported_ops:
                assert atom["source_function"] == exported_ops[atom_type]
