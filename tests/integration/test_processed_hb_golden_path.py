from __future__ import annotations

import csv
import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np

from fnirs_flow.compiler.compiler import compile_flow
from fnirs_flow.data.frozen_manifest import discover_frozen_processed_hb
from fnirs_flow.execution.processed_hb_acceptance import build_processed_hb_acceptance_report
from fnirs_flow.execution.processed_hb_pipeline import dry_run_processed_hb, run_processed_hb
from fnirs_flow.exporters.package_exporter import export_package
from fnirs_flow.exporters.package_importer import import_package, relink_package_data, rerun_package
from fnirs_flow.exporters.package_verifier import verify_package


def _fixture(root: Path) -> Path:
    freeze = root / "freeze"
    freeze.mkdir()
    signal = freeze / "record_RE.TXT"
    t = np.arange(0, 170, 0.1)
    lines = [
        "[File Information]",
        f"Points={len(t)}",
        "Channels=42",
    ]
    fields = ["Time(sec)", "Task", "Mark", "Count"]
    for channel in range(1, 43):
        fields.extend([f"CH{channel} oxyHb", f"CH{channel} deoxyHb", f"CH{channel} totalHb"])
    lines.append("\t".join(fields))
    for i, timestamp in enumerate(t):
        values = [f"{timestamp:.3f}", "0", "0", str(i)]
        for channel in range(1, 43):
            hbo = np.sin(timestamp / (12 + channel / 100)) + 2 + channel / 1000
            hbr = np.cos(timestamp / (15 + channel / 100)) + 2 - channel / 1200
            values.extend([f"{hbo:.8f}", f"{hbr:.8f}", f"{hbo + hbr:.8f}"])
        lines.append("\t".join(values))
    signal.write_text("\n".join(lines), encoding="utf-8")
    artifact_mask = freeze / "record_RE_artifact_mask.csv"
    with artifact_mask.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s", *(f"ch{channel:03d}" for channel in range(1, 43))])
        writer.writerows([[f"{timestamp:.3f}", *([0] * 42)] for timestamp in t])
    with (freeze / "fnirs_signal_provenance.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["fnirs_record_id", "fnirs_signal_path"])
        writer.writeheader()
        writer.writerow({"fnirs_record_id": "F1", "fnirs_signal_path": str(signal)})
    with (freeze / "analysis_population_manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = [
            "fnirs_record_id",
            "subject_id",
            "session_id",
            "linked_record_id",
            "record_pair_id",
            "artifact_mask_uri",
            "artifact_mask_sha256",
            "analysis_included",
            "event_primary_eligible",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow(
            {
                "fnirs_record_id": "F1",
                "subject_id": "sub-01",
                "session_id": "ses-01",
                "linked_record_id": "L1",
                "record_pair_id": "P1",
                "artifact_mask_uri": str(artifact_mask),
                "artifact_mask_sha256": hashlib.sha256(artifact_mask.read_bytes()).hexdigest(),
                "analysis_included": "true",
                "event_primary_eligible": "true",
            }
        )
    with (freeze / "fnirs_events.tsv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["fnirs_record_id", "onset", "duration", "trial_type", "window_id", "event_number", "event_eligible"]
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        events = [
            (5, 5, "condition_a", "window_a", "1"),
            (30, 5, "condition_b", "window_b", "2"),
            (55, 5, "condition_c", "window_c", "3"),
        ]
        for onset, duration, trial, window, number in events:
            writer.writerow(
                {
                    "fnirs_record_id": "F1",
                    "onset": onset,
                    "duration": duration,
                    "trial_type": trial,
                    "window_id": window,
                    "event_number": number,
                    "event_eligible": "true",
                }
            )
    (freeze / "contrast_matrix.csv").write_text(
        "model_id,contrast_id,component_id,regressor,weight\n"
        "glm_conditions_canonical_td_v1,condition_a,main,condition_a__canonical,1\n"
        "fir_post_event_0_30_10s_v1,joint_offset,early,offset__0_10s,1\n"
        "fir_post_event_0_30_10s_v1,joint_offset,late,offset__20_30s,1\n"
        "glm_event_order_linear_canonical_td_v1,linear_trend,main,event_order__linear_modulation__canonical,1\n",
        encoding="utf-8",
    )
    return freeze


def test_processed_hb_discover_dry_run_run_golden_path(tmp_path):
    freeze = _fixture(tmp_path)
    manifest = discover_frozen_processed_hb(
        freeze / "fnirs_signal_provenance.csv",
        freeze / "analysis_population_manifest.csv",
        events_uri=str(freeze / "fnirs_events.tsv"),
        contrast_matrix_uri=str(freeze / "contrast_matrix.csv"),
    )
    project = tmp_path / "project"
    flow_path = Path(__file__).resolve().parents[2] / "configs" / "vendor_processed_hb_flow.json"
    compile_flow(json.loads(flow_path.read_text(encoding="utf-8")), project)
    compiled = project / "compiled"
    (compiled / "data_manifest.json").write_text(json.dumps(manifest.model_dump(), indent=2), encoding="utf-8")
    preset = json.loads(
        (Path(__file__).resolve().parents[2] / "configs" / "presets" / "vendor_processed_hb_v1.json").read_text(
            encoding="utf-8"
        )
    )
    preset["time_regularization"].update(
        {
            "max_duplicate_fraction": 0.0,
            "max_jitter_abs_s": 0.005,
            "max_jitter_relative": 0.1,
            "max_interpolation_deviation_s": 0.03,
        }
    )
    preset["scientific_parameters_frozen"] = True
    preset["design_gates"] = {"condition_number_max": 1e12, "minimum_residual_df": 1}
    preset["solver_config"].update(
        {
            "rho_bound": 0.99,
            "ar_max_iterations": 50,
            "ar_tolerance": 1e-8,
            "huber_c": 1.345,
            "irls_max_iterations": 50,
            "irls_beta_tolerance": 1e-10,
            "irls_weight_tolerance": 1e-8,
            "minimum_effective_weight": 1e-8,
        }
    )
    preset["covariance_config"].update(
        {
            "covariance_symmetry_atol": 1e-12,
            "covariance_symmetry_rtol": 1e-8,
            "covariance_psd_tolerance": 1e-10,
        }
    )
    preset["qc_gates"] = {
        "hbt_absolute_tolerance": 1e-6,
        "hbt_exceedance_fraction_max": 0.0,
        "whitening_improvement_min": 0.0,
        "low_weight_fraction_max": 1.0,
        "event_coverage_tolerance_s": 0.0,
    }
    mapping = compiled / "fnirs_re_channel_layout_mapping.csv"
    with mapping.open("w", newline="", encoding="utf-8") as stream:
        fields = [
            "channel_id",
            "vendor_channel_number",
            "source_id",
            "detector_id",
            "source_detector_pair",
            "mni_x",
            "mni_y",
            "mni_z",
            "aal_label",
            "roi_label",
            "laterality",
            "probe_role",
            "localization_method",
            "mapping_source",
            "mapping_version",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for channel in range(1, 43):
            writer.writerow(
                {
                    "channel_id": f"ch{channel:03d}",
                    "vendor_channel_number": channel,
                    "source_id": f"S{channel}",
                    "detector_id": f"D{channel}",
                    "source_detector_pair": f"S{channel}-D{channel}",
                    "mni_x": channel,
                    "mni_y": 0,
                    "mni_z": 0,
                    "aal_label": "fixture",
                    "roi_label": "fixture",
                    "laterality": "left" if channel <= 21 else "right",
                    "probe_role": "subject_re",
                    "localization_method": "fixture",
                    "mapping_source": "fixture",
                    "mapping_version": "v1",
                }
            )
    preset["channel_annotation_path"] = mapping.name
    (compiled / "processed_hb_preset.json").write_text(json.dumps(preset, indent=2), encoding="utf-8")
    dry = dry_run_processed_hb(compiled)
    assert dry["counts"] == {"total": 1, "eligible": 1, "missing": 0}
    result = run_processed_hb(compiled, project)
    assert result["successful_record_pairs"] == 1
    derivatives = Path(result["derivatives"])
    required = {
        "input_provenance.csv",
        "run_manifest.csv",
        "event_ingestion_audit.csv",
        "design_matrix_manifest.csv",
        "first_level_glm_estimates.csv",
        "first_level_glm_covariance.csv",
        "first_level_contrasts.csv",
        "residual_qc.csv",
        "exclusion_manifest.csv",
        "analysis_manifest.json",
    }
    assert required <= {path.name for path in derivatives.iterdir()}
    assert (derivatives / "first_level_glm_covariance.csv").stat().st_size > 100
    with (derivatives / "first_level_contrasts.csv").open(newline="", encoding="utf-8") as stream:
        contrast_rows = list(csv.DictReader(stream))
    joint = [row for row in contrast_rows if row["contrast_id"] == "joint_offset"]
    assert joint and all(row["contrast_dimension"] == "2" and row["statistic_type"] == "F" for row in joint)
    assert "_RE.TXT" not in {path.name for path in derivatives.rglob("*")}
    package = export_package(project, tmp_path / "processed.fnirsflow.zip")
    verification = verify_package(package)
    assert verification.valid
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        assert any(name.endswith("first_level_glm_covariance.csv") for name in names)
        assert not any(name.upper().endswith("_RE.TXT") for name in names)
        provenance = archive.read("derivatives/processed_hb_first_level/input_provenance.csv").decode("utf-8")
        assert str(freeze) not in provenance
    imported = tmp_path / "imported"
    imported_result = import_package(package, imported)
    assert imported_result["quarantined_atoms"] == []
    relink = relink_package_data(imported, freeze)
    assert relink["missing_paths"] == []
    assert relink["hash_mismatches"] == []
    rerun_dir = tmp_path / "rerun"
    rerun = rerun_package(imported, rerun_dir)
    assert rerun["successful_runs"] == 1
    original_contrasts = (derivatives / "first_level_contrasts.csv").read_bytes()
    rerun_contrasts = (
        rerun_dir / "derivatives" / "processed_hb_first_level" / "first_level_contrasts.csv"
    ).read_bytes()
    assert rerun_contrasts == original_contrasts
    acceptance = build_processed_hb_acceptance_report(project, frozen_root=freeze, package_path=package)
    assert acceptance["checks"]["contrast_reconstruction"] is True
    assert acceptance["checks"]["output_artifact_hashes"] is True
    assert acceptance["checks"]["feature_freeze_hashes"] is True
    assert acceptance["contrast_reconstruction"]["failures"] == []
    assert acceptance["per_contrast_chromophore"]

    feature_table = derivatives / "processed_hb_window_features" / "channel_window_features.csv.gz"
    feature_table.write_bytes(feature_table.read_bytes() + b"tamper")
    tampered = build_processed_hb_acceptance_report(project, frozen_root=freeze, package_path=package)
    assert tampered["checks"]["feature_freeze_hashes"] is False
    assert "feature_table_sha256" in tampered["feature_freeze_hash_failures"]


def test_processed_hb_relink_rejects_sha256_mismatch(tmp_path):
    freeze = _fixture(tmp_path)
    manifest = discover_frozen_processed_hb(
        freeze / "fnirs_signal_provenance.csv",
        freeze / "analysis_population_manifest.csv",
        events_uri=str(freeze / "fnirs_events.tsv"),
        contrast_matrix_uri=str(freeze / "contrast_matrix.csv"),
    )
    manifest.runs[0].input_sha256 = "0" * 64
    imported = tmp_path / "imported"
    imported.mkdir()
    (imported / "data_manifest.json").write_text(json.dumps(manifest.model_dump(), indent=2), encoding="utf-8")
    with __import__("pytest").raises(ValueError, match="SHA-256 mismatch"):
        relink_package_data(imported, freeze)
