"""Tests for executable localization projection CSV import."""

from __future__ import annotations

import csv
import json

from fnirs_flow.adapters.localization_import import import_projection_coordinate_csv


def test_import_projection_coordinate_csv_standardizes_protocol02_shape(tmp_path):
    source = tmp_path / "protocol02.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "group_id",
                "point_index",
                "optode_name",
                "actual_projected_mni_x",
                "actual_projected_mni_y",
                "actual_projected_mni_z",
                "adjusted_projected_mni_x",
                "adjusted_projected_mni_y",
                "adjusted_projected_mni_z",
                "match_status",
                "accuracy_caveat",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "group_id": "Protocol02_QYZ",
                "point_index": "1",
                "optode_name": "LR1",
                "actual_projected_mni_x": "1",
                "actual_projected_mni_y": "2",
                "actual_projected_mni_z": "3",
                "adjusted_projected_mni_x": "4",
                "adjusted_projected_mni_y": "5",
                "adjusted_projected_mni_z": "6",
                "match_status": "complete_ready_to_use",
                "accuracy_caveat": "not_claimed_to_reproduce_nirsspm_accuracy",
            }
        )

    result = import_projection_coordinate_csv(source, tmp_path / "out", atom_id="loc")

    handles = result["output_handles"]
    assert handles["type"] == "ProjectedMNIChannels"
    assert handles["rows"] == 1
    assert handles["optodes"] == 1
    assert handles["not_nirsspm_equivalent"] is True
    assert json.loads((tmp_path / "out" / "Protocol02_QYZ_projected_mni_channels.json").read_text(encoding="utf-8"))[
        "coordinate_columns"
    ] == ["adjusted_projected_mni_x", "adjusted_projected_mni_y", "adjusted_projected_mni_z"]


def test_import_projection_coordinate_csv_filters_unmatched_and_fiducials(tmp_path):
    source = tmp_path / "combined.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "group_id",
                "raw_index",
                "projection_label",
                "projection_kind",
                "projected_mni_x",
                "projected_mni_y",
                "projected_mni_z",
                "match_status",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "group_id": "G3",
                "raw_index": "1",
                "projection_label": "NzHS",
                "projection_kind": "fiducial_or_reference",
                "projected_mni_x": "",
                "projected_mni_y": "",
                "projected_mni_z": "",
                "match_status": "matched",
            }
        )
        writer.writerow(
            {
                "group_id": "G3",
                "raw_index": "2",
                "projection_label": "CH01",
                "projection_kind": "channel",
                "projected_mni_x": "10",
                "projected_mni_y": "20",
                "projected_mni_z": "30",
                "match_status": "matched",
            }
        )
        writer.writerow(
            {
                "group_id": "G3",
                "raw_index": "3",
                "projection_label": "CH02",
                "projection_kind": "channel",
                "projected_mni_x": "11",
                "projected_mni_y": "21",
                "projected_mni_z": "31",
                "match_status": "review",
            }
        )

    result = import_projection_coordinate_csv(source, tmp_path / "out")

    handles = result["output_handles"]
    assert handles["rows"] == 1
    assert handles["channels"] == 1
    assert result["output"]["skipped_missing_mni"] == 1
    assert result["output"]["skipped_status"] == 1
