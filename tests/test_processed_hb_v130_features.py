import numpy as np
import pytest

from fnirs_flow.processed_hb import (
    evaluate_processed_hb_window_qc,
    extract_processed_hb_channel_window_features,
    ingest_frozen_window_set,
    join_channel_annotation_table,
    processed_hb_feature_dictionary,
    read_processed_hb_artifact_mask,
    validate_txt_to_snirf_roundtrip_audit,
)
from fnirs_flow.processed_hb.derivatives import freeze_processed_hb_feature_artifacts


class R:
    def __init__(self):
        self.timestamps_s = np.arange(0, 4, 0.5)
        self.hbo = np.array([[1, 2, 3, 4], [2, 3, 4, 5]], float)
        self.hbr = -self.hbo
        self.source = type("S", (), {"channels": []})()
        self.provenance = {"sha256": "a" * 64}


def test_half_open_windows_and_orientation():
    w = ingest_frozen_window_set(
        {
            "window_set_version": "v1",
            "windows": [{"window_id": "a", "start_s": 0, "end_s": 1}, {"window_id": "b", "start_s": 1, "end_s": 2}],
        }
    )
    r = R()
    r.source.channels = [type("C", (), {"channel": "ch-1"})(), type("C", (), {"channel": "ch-2"})()]
    q = evaluate_processed_hb_window_qc(r, w)
    assert q[0]["actual_sample_count"] == 2 and q[2]["actual_sample_count"] == 2
    assert len(extract_processed_hb_channel_window_features(r, q, w)) == 2 * 2 * 2 * 8


def test_window_overlap_rejected():
    with pytest.raises(ValueError):
        ingest_frozen_window_set(
            {"windows": [{"window_id": "a", "start_s": 0, "end_s": 2}, {"window_id": "b", "start_s": 1, "end_s": 3}]}
        )


def test_annotation_required_fields():
    with pytest.raises(ValueError):
        join_channel_annotation_table([{"channel_id": "ch-1"}], ["ch-1"])


def _annotation(channel_id, vendor_number, *, role="subject_re", pair=None):
    return {
        "channel_id": channel_id,
        "vendor_channel_number": vendor_number,
        "source_id": f"S{vendor_number}",
        "detector_id": f"D{vendor_number}",
        "source_detector_pair": pair or f"S{vendor_number}-D{vendor_number}",
        "mni_x": 1,
        "mni_y": 2,
        "mni_z": 3,
        "aal_label": "label",
        "roi_label": "roi",
        "laterality": "left",
        "probe_role": role,
        "localization_method": "fixture",
        "mapping_source": "fixture",
        "mapping_version": "v1",
    }


@pytest.mark.parametrize("observed_count", [41, 43])
def test_channel_count_gate_fails_closed(observed_count):
    rows = [_annotation(f"ch{i:03d}", i) for i in range(1, 43)]
    channels = [f"ch{i:03d}" for i in range(1, observed_count + 1)]
    with pytest.raises(ValueError, match="expected 42 channels"):
        join_channel_annotation_table(rows, channels, expected_channel_count=42)


@pytest.mark.parametrize("role", ["operator_op", "unknown"])
def test_probe_role_gate_fails_closed(role):
    with pytest.raises(ValueError, match="probe role not allowed"):
        join_channel_annotation_table(
            [_annotation("ch001", 1, role=role)],
            ["ch001"],
            expected_channel_count=1,
            allowed_probe_roles=["subject_re"],
        )


def test_duplicate_source_detector_pair_fails_closed():
    with pytest.raises(ValueError, match="duplicate source-detector pair"):
        join_channel_annotation_table(
            [_annotation("ch001", 1, pair="S1-D1"), _annotation("ch002", 2, pair="S1-D1")],
            ["ch001", "ch002"],
            expected_channel_count=2,
        )


def test_window_availability_does_not_merge_subjects():
    from fnirs_flow.processed_hb import aggregate_window_modality_availability

    rows = [
        {
            "subject_id": subject,
            "session_id": "ses-1",
            "record_pair_id": f"pair-{subject}",
            "window_id": "t7",
            "channel_id": "ch001",
            "qc_status": status,
        }
        for subject, status in (("sub-1", "pass"), ("sub-2", "fail"))
    ]
    result = aggregate_window_modality_availability(rows, min_valid_channel_fraction=0.5)
    assert len(result) == 2
    assert {row["subject_id"] for row in result} == {"sub-1", "sub-2"}
    assert {row["valid_channel_count"] for row in result} == {0, 1}


def test_freeze_identity_changes_with_config_and_never_overwrites(tmp_path):
    import gzip
    import json

    with gzip.open(tmp_path / "channel_window_features.csv.gz", "wt", encoding="utf-8") as stream:
        stream.write("feature\n1\n")
    with gzip.open(tmp_path / "channel_window_qc.csv.gz", "wt", encoding="utf-8") as stream:
        stream.write("qc\npass\n")
    config = tmp_path / "preset.json"
    input_manifest = tmp_path / "input_manifest.csv"
    mapping = tmp_path / "mapping.csv"
    config.write_text('{"version":1}', encoding="utf-8")
    input_manifest.write_text("record\nr1\n", encoding="utf-8")
    mapping.write_text("channel\nch001\n", encoding="utf-8")
    first = freeze_processed_hb_feature_artifacts(
        tmp_path,
        config_path=config,
        input_manifest_path=input_manifest,
        mapping_path=mapping,
        software_version="1.3.0",
        git_commit="abc",
        command="fnirs-flow run plan --outdir output",
        freeze_id="v1",
    )
    config.write_text('{"version":2}', encoding="utf-8")
    second = freeze_processed_hb_feature_artifacts(
        tmp_path,
        config_path=config,
        input_manifest_path=input_manifest,
        mapping_path=mapping,
        software_version="1.3.0",
        git_commit="abc",
        command="fnirs-flow run plan --outdir output",
        freeze_id="v1",
    )
    assert first != second and first.exists() and second.exists()
    first_payload = json.loads(first.read_text(encoding="utf-8"))
    second_payload = json.loads(second.read_text(encoding="utf-8"))
    assert first_payload["config_sha256"] != second_payload["config_sha256"]
    assert first_payload["input_manifest_sha256"]
    assert first_payload["mapping_sha256"]
    assert first_payload["config_path"] == "preset.json"


@pytest.mark.parametrize("changed", ["input", "mapping", "software"])
def test_freeze_identity_changes_for_every_frozen_input(tmp_path, changed):
    import gzip
    import json

    with gzip.open(tmp_path / "channel_window_features.csv.gz", "wt", encoding="utf-8") as stream:
        stream.write("feature\n1\n")
    with gzip.open(tmp_path / "channel_window_qc.csv.gz", "wt", encoding="utf-8") as stream:
        stream.write("qc\npass\n")
    config = tmp_path / "preset.json"
    input_manifest = tmp_path / "input_manifest.csv"
    mapping = tmp_path / "mapping.csv"
    config.write_text("{}", encoding="utf-8")
    input_manifest.write_text("record\nr1\n", encoding="utf-8")
    mapping.write_text("channel\nch1\n", encoding="utf-8")

    def freeze(version):
        return freeze_processed_hb_feature_artifacts(
            tmp_path,
            config_path=config,
            input_manifest_path=input_manifest,
            mapping_path=mapping,
            software_version=version,
            git_commit="abc",
            command="fnirs-flow run",
            freeze_id="change",
        )

    first = freeze("1.0")
    if changed == "input":
        input_manifest.write_text("record\nr2\n", encoding="utf-8")
    elif changed == "mapping":
        mapping.write_text("channel\nch2\n", encoding="utf-8")
    second = freeze("2.0" if changed == "software" else "1.0")
    assert first != second
    assert json.loads(first.read_text(encoding="utf-8"))["freeze_identity_sha256"] != json.loads(
        second.read_text(encoding="utf-8")
    )["freeze_identity_sha256"]


def test_nonfinite_samples_can_pass_when_valid_fraction_meets_threshold():
    recording = R()
    recording.source.channels = [
        type("C", (), {"channel": "ch-1"})(),
        type("C", (), {"channel": "ch-2"})(),
    ]
    recording.hbo[0, 0] = np.nan
    windows = ingest_frozen_window_set({"windows": [{"window_id": "all", "start_s": 0, "end_s": 2}]})
    rows = evaluate_processed_hb_window_qc(recording, windows, min_valid_sample_fraction=0.75)
    assert rows[0]["valid_sample_count"] == 3
    assert rows[0]["valid_sample_fraction"] == pytest.approx(0.75)
    assert rows[0]["qc_status"] == "pass"


def test_nonfinite_samples_report_reason_below_valid_fraction_threshold():
    recording = R()
    recording.source.channels = [
        type("C", (), {"channel": "ch-1"})(),
        type("C", (), {"channel": "ch-2"})(),
    ]
    recording.hbo[0, :2] = np.nan
    windows = ingest_frozen_window_set({"windows": [{"window_id": "all", "start_s": 0, "end_s": 2}]})
    rows = evaluate_processed_hb_window_qc(recording, windows, min_valid_sample_fraction=0.75)
    assert rows[0]["qc_status"] == "fail"
    assert rows[0]["qc_reason_code"] == "NONFINITE_SIGNAL"


def test_all_eight_feature_values_and_hbt_exclusion():
    recording = R()
    recording.timestamps_s = np.arange(4, dtype=float)
    recording.hbo = np.array([[1, 2, 3, 4], [-1, -2, -3, -4]], dtype=float)
    recording.hbr = -recording.hbo
    recording.source.channels = [
        type("C", (), {"channel": "ch-1"})(),
        type("C", (), {"channel": "ch-2"})(),
    ]
    windows = ingest_frozen_window_set({"windows": [{"window_id": "all", "start_s": 0, "end_s": 4}]})
    qc = evaluate_processed_hb_window_qc(recording, windows)
    rows = extract_processed_hb_channel_window_features(recording, qc, windows)
    values = {
        row["feature_name"]: row["feature_value"]
        for row in rows
        if row["channel_id"] == "ch-1" and row["chromophore"] == "hbo"
    }
    assert values == pytest.approx(
        {
            "mean": 2.5,
            "sd": np.sqrt(5 / 3),
            "median": 2.5,
            "iqr": 1.5,
            "min": 1.0,
            "max": 4.0,
            "linear_slope": 1.0,
            "auc_abs_signal": 7.5,
        }
    )
    dictionary = processed_hb_feature_dictionary()
    assert dictionary["default_ml_chromophores"] == ["hbo", "hbr"]
    assert "hbt" not in {row["chromophore"] for row in rows}


def test_single_sample_window_contract():
    recording = R()
    recording.source.channels = [
        type("C", (), {"channel": "ch-1"})(),
        type("C", (), {"channel": "ch-2"})(),
    ]
    windows = ingest_frozen_window_set({"windows": [{"window_id": "one", "start_s": 0, "end_s": 0.5}]})
    qc = evaluate_processed_hb_window_qc(recording, windows)
    rows = extract_processed_hb_channel_window_features(recording, qc, windows)
    values = {
        row["feature_name"]: row["feature_value"]
        for row in rows
        if row["channel_id"] == "ch-1" and row["chromophore"] == "hbo"
    }
    assert np.isnan(values["sd"])
    assert np.isnan(values["linear_slope"])
    assert values["auc_abs_signal"] == 0.0


def test_qc_equality_boundaries_and_invalid_rows_are_retained():
    recording = R()
    recording.timestamps_s = np.arange(0, 20, dtype=float)
    recording.hbo = np.ones((2, 20), dtype=float)
    recording.hbr = -recording.hbo
    recording.source.channels = [
        type("C", (), {"channel": "ch-1"})(),
        type("C", (), {"channel": "ch-2"})(),
    ]
    windows = ingest_frozen_window_set({"windows": [{"window_id": "all", "start_s": 0, "end_s": 20}]})
    mask = np.zeros((20, 2), dtype=bool)
    mask[:4, 0] = True
    mask[:10, 1] = True
    qc = evaluate_processed_hb_window_qc(
        recording,
        windows,
        artifact_mask=mask,
        min_valid_sample_fraction=0.8,
        max_artifact_duration_s=10.0,
    )
    assert qc[0]["valid_sample_fraction"] == pytest.approx(0.8)
    assert qc[0]["qc_status"] == "pass"
    assert qc[1]["longest_artifact_duration_s"] == pytest.approx(10.0)
    assert qc[1]["qc_status"] == "fail"
    availability = __import__(
        "fnirs_flow.processed_hb", fromlist=["aggregate_window_modality_availability"]
    ).aggregate_window_modality_availability(
        [{"subject_id": "s", "session_id": "1", "record_pair_id": "r", **row} for row in qc]
    )
    assert availability[0]["valid_channel_fraction"] == pytest.approx(0.5)
    assert availability[0]["fnirs_available"] is True
    features = extract_processed_hb_channel_window_features(recording, qc, windows, artifact_mask=mask)
    invalid = [row for row in features if row["channel_id"] == "ch-2"]
    assert len(invalid) == 16
    assert all(np.isnan(row["feature_value"]) for row in invalid)
    assert all(row["qc_status"] == "fail" for row in invalid)


def test_artifact_mask_sidecar_is_strict_and_aligned(tmp_path):
    path = tmp_path / "mask.csv"
    path.write_text("time_s,ch-1,ch-2\n0,0,1\n1,1,0\n", encoding="utf-8")
    result = read_processed_hb_artifact_mask(path, [0.01, 0.99], ["ch-1", "ch-2"], max_time_deviation_s=0.02)
    assert result.mask.tolist() == [[False, True], [True, False]]
    assert result.sha256
    with pytest.raises(ValueError, match="ALIGNMENT_EXCEEDED"):
        read_processed_hb_artifact_mask(path, [0.1], ["ch-1", "ch-2"], max_time_deviation_s=0.02)


def test_external_txt_to_snirf_roundtrip_audit_requires_all_preservation_checks(tmp_path):
    source = tmp_path / "input.txt"
    snirf = tmp_path / "output.snirf"
    source.write_bytes(b"vendor-data")
    snirf.write_bytes(b"snirf-data")
    import hashlib

    audit = {
        "converter_name": "project_converter",
        "converter_version": "1.0",
        "converter_commit": "c" * 64,
        "input_txt_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output_snirf_sha256": hashlib.sha256(snirf.read_bytes()).hexdigest(),
        "roundtrip_checks": {
            "channel_count_equal": True,
            "time_axis_equal": True,
            "timestamps_equal": True,
            "events_equal": True,
            "hbo_values_equal": True,
            "hbr_values_equal": True,
        },
    }
    result = validate_txt_to_snirf_roundtrip_audit(audit, input_txt=source, output_snirf=snirf)
    assert result["status"] == "validated_external_roundtrip_evidence"
    assert result["operation_registration"] == "not_registered"
    audit["roundtrip_checks"]["events_equal"] = False
    with pytest.raises(ValueError, match="CONVERSION_ROUNDTRIP_NOT_PRESERVED"):
        validate_txt_to_snirf_roundtrip_audit(audit)
