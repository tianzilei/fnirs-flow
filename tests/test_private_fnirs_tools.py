"""Tests for managed MethodAtoms adapted from the owner's private scripts."""

from __future__ import annotations

import csv
import json

from fnirs_flow.adapters.private_fnirs_tools import (
    inspect_nirs_spm_headers,
    inventory_fnirs_filenames,
    split_probe_layout_csv,
)
from fnirs_flow.execution.operations import create_default_registry
from fnirs_flow.execution.service import ExecutionService
from fnirs_flow.flow.atoms import ReadinessStatus
from fnirs_flow.registry.node_library import create_builtin_library


def test_private_script_atoms_are_registered_with_provenance():
    library = create_builtin_library()
    registry = create_default_registry()

    for template_id in (
        "fnirs_filename_inventory",
        "nirs_spm_header_inspection",
        "probe_layout_split",
    ):
        template = library.get(template_id)
        assert template is not None
        assert template.operation == template_id
        assert template.default_execution_scope == "group"
        assert template.default_readiness_status == ReadinessStatus.NEEDS_ATTENTION
        assert template.metadata["source_project"] == "tianzilei/MainCodeRepo"
        assert template.metadata["source_license"] == "Apache-2.0"
        assert registry.has(template_id)


def test_inventory_fnirs_filenames_is_recursive_non_destructive_and_deterministic(tmp_path):
    source = tmp_path / "input"
    nested = source / "nested"
    nested.mkdir(parents=True)
    valid = nested / "20260815001ABCDN.snirf"
    invalid = source / "notes.txt"
    ignored = source / "image.png"
    valid.write_text("snirf", encoding="utf-8")
    invalid.write_text("notes", encoding="utf-8")
    ignored.write_text("image", encoding="utf-8")

    result = inventory_fnirs_filenames(
        source,
        tmp_path / "out",
        extensions=[".snirf", ".txt"],
        atom_id="inventory",
    )

    assert result["output"]["files"] == 2
    assert result["output"]["valid"] == 1
    assert result["output"]["invalid"] == 1
    assert valid.exists() and invalid.exists() and ignored.exists()
    with (tmp_path / "out" / "inventory_valid_filenames.csv").open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["date"] == "20260815"
    assert row["relative_path"] == "nested/20260815001ABCDN.snirf"


def test_inspect_nirs_spm_headers_redacts_subject_id_by_default(tmp_path):
    source = tmp_path / "sample.TXT"
    source.write_text(
        "[Data Line] 8\n"
        "Measured Date 2026-08-15 10:30:00\n"
        "ID\tparticipant-secret\n"
        "Name\tP01\n"
        "[Text Info.]\n"
        "(1,1),(2,2)\n"
        "Time(sec) Task Mark Count CH1 CH2 CH3 CH4 CH5 CH6\n"
        "0 0 0 0 1 2 3 4 5 6\n",
        encoding="utf-8",
    )

    result = inspect_nirs_spm_headers(source, tmp_path / "out", atom_id="header")
    report = result["output"]["reports"][0]

    assert report["subject_id_present"] is True
    assert "subject_id" not in report
    serialized = json.dumps(result["output"])
    assert "participant-secret" not in serialized
    assert report["channel_pairs"] == 2
    assert report["inferred_channels"] == 2


def test_split_probe_layout_csv_handles_channel_prefix_before_source_prefix(tmp_path):
    layout = tmp_path / "layout.csv"
    layout.write_text(
        "layout,x,y,z\nT1,1,2,3\nS2,4,5,6\nR1,7,8,9\nD2,10,11,12\nCH1,13,14,15\nOTHER,0,0,0\n",
        encoding="utf-8",
    )

    result = split_probe_layout_csv(layout, tmp_path / "out", coordinate_set_id="set-a")

    assert result["output"]["sources"] == 2
    assert result["output"]["detectors"] == 2
    assert result["output"]["channels"] == 1
    assert result["output"]["unclassified_labels"] == ["OTHER"]
    assert (tmp_path / "out" / "set-a_source_coordinates.csv").exists()
    assert (tmp_path / "out" / "set-a_detector_coordinates.csv").exists()
    assert (tmp_path / "out" / "set-a_channel_coordinates.csv").exists()


def test_filename_inventory_executes_as_group_scope_atom(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "20260815001ABCDN.snirf").write_text("snirf", encoding="utf-8")
    dag = {
        "atoms": [
            {
                "atom_id": "private-inventory",
                "operation": "fnirs_filename_inventory",
                "category": "data",
                "execution_scope": "group",
                "parameters": {"path": str(source), "extensions": [".snirf"]},
            }
        ]
    }

    results = ExecutionService()._execute_group_scope_atoms(dag, tmp_path)

    assert len(results) == 1
    assert results[0].status == "completed"
    assert results[0].output_handles["type"] == "FnirsFilenameInventory"
    assert results[0].output_handles["valid"] == 1
    assert len(results[0].artifacts) == 4
    assert all(artifact["exists"] for artifact in results[0].artifacts)
