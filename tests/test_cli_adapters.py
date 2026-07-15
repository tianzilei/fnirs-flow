"""Tests for backend adapter CLI commands: import-homer3, import-analyzir, export-homer3, export-analyzir."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from cli import main

# ============================================================================
# Fixtures
# ============================================================================

SAMPLE_HOMER3_JSON = {
    "process_type": "preprocessing",
    "steps": [
        {"name": "od", "func": "hmrR_Intensity2OD", "params": {}},
        {"name": "td", "func": "hmrR_MotionCorrectTD", "params": {}},
        {"name": "bp", "func": "hmrR_BandpassFilt", "params": {"lpf": 0.2, "hpf": 0.01}},
        {"name": "bll", "func": "hmrR_OD2Conc", "params": {"DPF": [6, 6]}},
    ],
}

SAMPLE_HOMER3_CFG = """\
[data] = hmrR_Intensity2OD(data)
[data] = hmrR_MotionCorrectTD(data)
[data] = hmrR_BandpassFilt(data, 0.2, 0.01, 2)
[data] = hmrR_OD2Conc(data, [6, 6])
"""

SAMPLE_ANALYZIR_R = """\
data <- load("test.snirf")
data <- hmrR_Intensity2OD(data)
data <- hmrR_MotionCorrectTD(data)
data <- hmrR_BandpassFilt(data, lpf=0.2, hpf=0.01)
data <- hmrR_OD2Conc(data, DPF=c(6, 6))
"""

SAMPLE_ATOMS = [
    {
        "atom_type": "optical_density",
        "operation": "optical_density",
        "category": "preprocessing",
        "config": {"parameters": {}},
    },
    {
        "atom_type": "tddr_motion",
        "operation": "motion_correction",
        "category": "preprocessing",
        "config": {"parameters": {"method": "tddr"}},
    },
    {
        "atom_type": "bandpass_filter",
        "operation": "filtering",
        "category": "preprocessing",
        "config": {"parameters": {"l_freq": 0.01, "h_freq": 0.2}},
    },
    {
        "atom_type": "beer_lambert_law",
        "operation": "beer_lambert_law",
        "category": "preprocessing",
        "config": {"parameters": {"ppf": 6.0}},
    },
]


# ============================================================================
# import-homer3
# ============================================================================


class TestImportHomer3CLI:
    """Test `fnirs-flow import-homer3` command."""

    def test_import_homer3_json_success(self):
        """Import a Homer3 JSON config successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "config.json"
            src.write_text(json.dumps(SAMPLE_HOMER3_JSON), encoding="utf-8")
            outdir = tmpdir / "output"

            exit_code = main(["import-homer3", str(src), "--outdir", str(outdir)])
            assert exit_code == 0
            assert (outdir / "homer3_import_report.md").exists()
            assert (outdir / "imported_atoms.json").exists()

    def test_import_homer3_json_atoms_content(self):
        """Verify imported atoms JSON has correct content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "config.json"
            src.write_text(json.dumps(SAMPLE_HOMER3_JSON), encoding="utf-8")
            outdir = tmpdir / "output"

            main(["import-homer3", str(src), "--outdir", str(outdir)])

            atoms = json.loads((outdir / "imported_atoms.json").read_text(encoding="utf-8"))
            assert len(atoms) == 4
            atom_types = [a["atom_type"] for a in atoms]
            assert "optical_density" in atom_types
            assert "tddr_motion" in atom_types

    def test_import_homer3_cfg_success(self):
        """Import a Homer3 .cfg file successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "process.cfg"
            src.write_text(SAMPLE_HOMER3_CFG, encoding="utf-8")
            outdir = tmpdir / "output"

            exit_code = main(["import-homer3", str(src), "--outdir", str(outdir)])
            assert exit_code == 0

    def test_import_homer3_missing_file(self):
        """Import fails with missing file."""
        exit_code = main(["import-homer3", "/nonexistent/config.json", "--outdir", "/tmp/out"])
        assert exit_code == 1

    def test_import_homer3_no_command(self):
        """No command shows help."""
        exit_code = main([])
        assert exit_code == 0


# ============================================================================
# import-analyzir
# ============================================================================


class TestImportAnalyzIRCLI:
    """Test `fnirs-flow import-analyzir` command."""

    def test_import_analyzir_r_success(self):
        """Import an AnalyzIR R script successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "pipeline.R"
            src.write_text(SAMPLE_ANALYZIR_R, encoding="utf-8")
            outdir = tmpdir / "output"

            exit_code = main(["import-analyzir", str(src), "--outdir", str(outdir)])
            assert exit_code == 0
            assert (outdir / "analyzir_import_report.md").exists()
            assert (outdir / "imported_atoms.json").exists()

    def test_import_analyzir_r_atoms_content(self):
        """Verify imported atoms JSON has correct content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "pipeline.R"
            src.write_text(SAMPLE_ANALYZIR_R, encoding="utf-8")
            outdir = tmpdir / "output"

            main(["import-analyzir", str(src), "--outdir", str(outdir)])

            atoms = json.loads((outdir / "imported_atoms.json").read_text(encoding="utf-8"))
            assert len(atoms) == 4
            atom_types = [a["atom_type"] for a in atoms]
            assert "optical_density" in atom_types

    def test_import_analyzir_json_success(self):
        """Import an AnalyzIR JSON config successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "config.json"
            config = {
                "data_path": "test.snirf",
                "steps": [
                    {"func": "hmrR_Intensity2OD", "params": {}},
                    {"func": "hmrR_OD2Conc", "params": {"DPF": [6, 6]}},
                ],
            }
            src.write_text(json.dumps(config), encoding="utf-8")
            outdir = tmpdir / "output"

            exit_code = main(["import-analyzir", str(src), "--outdir", str(outdir)])
            assert exit_code == 0

    def test_import_analyzir_missing_file(self):
        """Import fails with missing file."""
        exit_code = main(["import-analyzir", "/nonexistent/pipeline.R", "--outdir", "/tmp/out"])
        assert exit_code == 1


# ============================================================================
# export-homer3
# ============================================================================


class TestExportHomer3CLI:
    """Test `fnirs-flow export-homer3` command."""

    def test_export_homer3_success(self):
        """Export atoms to Homer3 config successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "atoms.json"
            src.write_text(json.dumps(SAMPLE_ATOMS), encoding="utf-8")
            outdir = tmpdir / "output"

            exit_code = main(["export-homer3", str(src), "--outdir", str(outdir)])
            assert exit_code == 0
            assert (outdir / "homer3_process_config.json").exists()
            assert (outdir / "homer3_mapping_report.md").exists()

    def test_export_homer3_config_content(self):
        """Verify exported Homer3 config has correct structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "atoms.json"
            src.write_text(json.dumps(SAMPLE_ATOMS), encoding="utf-8")
            outdir = tmpdir / "output"

            main(["export-homer3", str(src), "--outdir", str(outdir)])

            config = json.loads((outdir / "homer3_process_config.json").read_text(encoding="utf-8"))
            assert "steps" in config
            assert len(config["steps"]) == 4
            funcs = [s["func"] for s in config["steps"]]
            assert "hmrR_Intensity2OD" in funcs
            assert "hmrR_MotionCorrectTD" in funcs

    def test_export_homer3_missing_file(self):
        """Export fails with missing file."""
        exit_code = main(["export-homer3", "/nonexistent/atoms.json", "--outdir", "/tmp/out"])
        assert exit_code == 1

    def test_export_homer3_invalid_json(self):
        """Export fails with invalid JSON structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "atoms.json"
            src.write_text('{"not": "a list"}', encoding="utf-8")
            outdir = tmpdir / "output"

            exit_code = main(["export-homer3", str(src), "--outdir", str(outdir)])
            assert exit_code == 1


# ============================================================================
# export-analyzir
# ============================================================================


class TestExportAnalyzIRCLI:
    """Test `fnirs-flow export-analyzir` command."""

    def test_export_analyzir_success(self):
        """Export atoms to AnalyzIR R script successfully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "atoms.json"
            src.write_text(json.dumps(SAMPLE_ATOMS), encoding="utf-8")
            outdir = tmpdir / "output"

            exit_code = main(["export-analyzir", str(src), "--outdir", str(outdir)])
            assert exit_code == 0
            assert (outdir / "fnirs_pipeline.R").exists()
            assert (outdir / "analyzir_export_report.md").exists()

    def test_export_analyzir_r_content(self):
        """Verify exported R script has correct content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "atoms.json"
            src.write_text(json.dumps(SAMPLE_ATOMS), encoding="utf-8")
            outdir = tmpdir / "output"

            main(["export-analyzir", str(src), "--outdir", str(outdir)])

            r_content = (outdir / "fnirs_pipeline.R").read_text(encoding="utf-8")
            assert "hmrR_Intensity2OD" in r_content
            assert "hmrR_MotionCorrectTD" in r_content
            assert "hmrR_BandpassFilt" in r_content
            assert "hmrR_OD2Conc" in r_content

    def test_export_analyzir_custom_filename(self):
        """Export with custom R script filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "atoms.json"
            src.write_text(json.dumps(SAMPLE_ATOMS), encoding="utf-8")
            outdir = tmpdir / "output"

            exit_code = main(["export-analyzir", str(src), "--outdir", str(outdir), "--filename", "my_pipeline.R"])
            assert exit_code == 0
            assert (outdir / "my_pipeline.R").exists()

    def test_export_analyzir_with_data_path(self):
        """Export with data path in R script."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "atoms.json"
            src.write_text(json.dumps(SAMPLE_ATOMS), encoding="utf-8")
            outdir = tmpdir / "output"

            main(["export-analyzir", str(src), "--outdir", str(outdir), "--data-path", "my_data.snirf"])

            r_content = (outdir / "fnirs_pipeline.R").read_text(encoding="utf-8")
            assert "my_data.snirf" in r_content

    def test_export_analyzir_missing_file(self):
        """Export fails with missing file."""
        exit_code = main(["export-analyzir", "/nonexistent/atoms.json", "--outdir", "/tmp/out"])
        assert exit_code == 1

    def test_export_analyzir_invalid_json(self):
        """Export fails with invalid JSON structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            src = tmpdir / "atoms.json"
            src.write_text('{"not": "a list"}', encoding="utf-8")
            outdir = tmpdir / "output"

            exit_code = main(["export-analyzir", str(src), "--outdir", str(outdir)])
            assert exit_code == 1


# ============================================================================
# Round-trip: import → export via CLI
# ============================================================================


class TestCLIAdapterRoundTrip:
    """Test full CLI round-trip: import-homer3 → export-analyzir and vice versa."""

    def test_homer3_import_then_analyzir_export(self):
        """Import Homer3 config, then export to AnalyzIR R script."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Write Homer3 config
            h3_src = tmpdir / "homer3.json"
            h3_src.write_text(json.dumps(SAMPLE_HOMER3_JSON), encoding="utf-8")

            # Import Homer3
            atoms_dir = tmpdir / "atoms"
            exit_code = main(["import-homer3", str(h3_src), "--outdir", str(atoms_dir)])
            assert exit_code == 0

            # Export to AnalyzIR
            az_dir = tmpdir / "analyzir"
            atoms_json = atoms_dir / "imported_atoms.json"
            exit_code = main(["export-analyzir", str(atoms_json), "--outdir", str(az_dir)])
            assert exit_code == 0

            # Verify R script
            r_content = (az_dir / "fnirs_pipeline.R").read_text(encoding="utf-8")
            assert "hmrR_Intensity2OD" in r_content
            assert "hmrR_MotionCorrectTD" in r_content

    def test_analyzir_import_then_homer3_export(self):
        """Import AnalyzIR R script, then export to Homer3 config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Write AnalyzIR R script
            az_src = tmpdir / "pipeline.R"
            az_src.write_text(SAMPLE_ANALYZIR_R, encoding="utf-8")

            # Import AnalyzIR
            atoms_dir = tmpdir / "atoms"
            exit_code = main(["import-analyzir", str(az_src), "--outdir", str(atoms_dir)])
            assert exit_code == 0

            # Export to Homer3
            h3_dir = tmpdir / "homer3"
            atoms_json = atoms_dir / "imported_atoms.json"
            exit_code = main(["export-homer3", str(atoms_json), "--outdir", str(h3_dir)])
            assert exit_code == 0

            # Verify config
            config = json.loads((h3_dir / "homer3_process_config.json").read_text(encoding="utf-8"))
            funcs = [s["func"] for s in config["steps"]]
            assert "hmrR_Intensity2OD" in funcs
            assert "hmrR_OD2Conc" in funcs
