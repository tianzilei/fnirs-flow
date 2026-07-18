"""Tests for the NIRS-SPM projection_CS rewrite atom."""

from __future__ import annotations

import csv
import json

import numpy as np

from fnirs_flow.adapters import nirsspm_projection
from fnirs_flow.adapters.nirsspm_projection import run_nirsspm_surface_projection_csv


class _TinyProjector:
    reference_dir = "synthetic-nirsspm-reference"
    surface_reference_count = 1

    def project_head_to_cortex(self, points):
        return np.asarray(points, dtype=float) + np.asarray([1.0, 2.0, 3.0])


def test_run_nirsspm_surface_projection_csv_writes_validation_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(
        nirsspm_projection.NirsspmSurfaceProjector,
        "from_reference_dir",
        classmethod(lambda cls, reference_dir: _TinyProjector()),
    )
    source = tmp_path / "head_surface.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "group_id",
                "projection_label",
                "projection_kind",
                "projected_head_x",
                "projected_head_y",
                "projected_head_z",
                "projected_mni_x",
                "projected_mni_y",
                "projected_mni_z",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "group_id": "G1",
                "projection_label": "CH01",
                "projection_kind": "channel",
                "projected_head_x": "10",
                "projected_head_y": "20",
                "projected_head_z": "30",
                "projected_mni_x": "11",
                "projected_mni_y": "22",
                "projected_mni_z": "33",
            }
        )

    result = run_nirsspm_surface_projection_csv(source, tmp_path / "out", atom_id="projection")

    handles = result["output_handles"]
    assert handles["type"] == "NirsspmSurfaceProjection"
    assert handles["rows"] == 1
    assert handles["validation"]["max_distance_mm"] == 0
    assert handles["projection_algorithm"] == "NIRS-SPM_v4_r1_projection_CS_python_rewrite"
    output_csv = tmp_path / "out" / "G1_nirsspm_surface_projection.csv"
    assert output_csv.exists()
    with output_csv.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["projected_mni_x"] == "11.0"
    assert json.loads((tmp_path / "out" / "G1_nirsspm_surface_projection_manifest.json").read_text(encoding="utf-8"))[
        "projection_stage"
    ] == "head_surface_mni_to_cortical_surface_mni"


def test_run_nirsspm_surface_projection_warns_when_reference_differs(tmp_path, monkeypatch):
    monkeypatch.setattr(
        nirsspm_projection.NirsspmSurfaceProjector,
        "from_reference_dir",
        classmethod(lambda cls, reference_dir: _TinyProjector()),
    )
    source = tmp_path / "head_surface.csv"
    source.write_text(
        (
            "projection_label,projected_head_x,projected_head_y,projected_head_z,"
            "projected_mni_x,projected_mni_y,projected_mni_z\n"
            "CH01,0,0,0,20,0,0\n"
        ),
        encoding="utf-8",
    )

    result = run_nirsspm_surface_projection_csv(source, tmp_path / "out")

    assert result["output_handles"]["validation"]["max_distance_mm"] > 5
    assert result["warnings"]
