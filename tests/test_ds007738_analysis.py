"""Regression tests for the ds007738 full-analysis workflow."""

from __future__ import annotations

import csv
import json

from scripts import analyze_ds007738_qc_sensitivity as sensitivity_script
from scripts import audit_ds007738_outputs as audit_script
from scripts import build_ds007738_exclusion_manifests as exclusion_script
from scripts import compare_ds007738_golden_rerun as comparison_script
from scripts import run_ds007738_full_analysis as analysis_script
from scripts.run_ds007738_full_analysis import RunRecord, build_contrasts, load_task_events


def test_left_minus_right_contrast_is_independent_of_event_order():
    left_first = build_contrasts({"Covert Left": 1, "Covert Right": 2})[0]
    right_first = build_contrasts({"Covert Right": 1, "Covert Left": 2})[0]

    assert left_first["name"] == "Covert_Left_minus_Covert_Right"
    assert right_first["name"] == left_first["name"]
    assert left_first["weights"] == [1.0, -1.0, 0.0]
    assert right_first["weights"] == [-1.0, 1.0, 0.0]


def test_dataset_loader_excludes_include_zero_trials(tmp_path):
    events_path = tmp_path / "events.tsv"
    with events_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["onset", "duration", "trial_type", "include"])
        writer.writerow([1.0, 5.0, "Left", 1])
        writer.writerow([2.0, 5.0, "Right", 0])
        writer.writerow([3.0, 2.5, "Right", 1])
    run = RunRecord(
        subject="01",
        task="covert",
        run="01",
        relative_path="sub-01/test.snirf",
        path=str(tmp_path / "test.snirf"),
        events_path=str(events_path),
    )

    class Raw:
        info = {"sfreq": 10.0}

    events, event_id, counts = load_task_events(run, Raw())

    assert event_id == {"Left": 1, "Right": 2}
    assert events.tolist() == [[10, 50, 1], [30, 25, 2]]
    assert counts == {"Left": 1, "Right": 1}


def test_discover_runs_ignores_appledouble_sidecars(tmp_path, monkeypatch):
    snirf_path = tmp_path / "sub-01" / "nirs" / "sub-01_task-rest_run-01_nirs.snirf"
    snirf_path.parent.mkdir(parents=True)
    snirf_path.write_bytes(b"snirf")
    snirf_path.with_name(f"._{snirf_path.name}").write_bytes(b"appledouble")
    monkeypatch.setattr(analysis_script, "DATASET_ROOT", tmp_path)

    runs = analysis_script.discover_runs()

    assert [run.run_id for run in runs] == ["sub-01_task-rest_run-01"]


def test_audit_file_loaders_ignore_appledouble_sidecars(tmp_path, monkeypatch):
    results_dir = tmp_path / "run_results"
    reports_dir = tmp_path / "reports"
    results_dir.mkdir()
    reports_dir.mkdir()
    result_path = results_dir / "sub-01_task-rest_run-01_result.json"
    result_path.write_text(json.dumps({"run_id": "sub-01_task-rest_run-01"}), encoding="utf-8")
    result_path.with_name(f"._{result_path.name}").write_bytes(b"\x00\xb0appledouble")
    report_path = reports_dir / "sub-01_task-rest_run-01_desc-import_summary.json"
    report_path.write_text("{}", encoding="utf-8")
    report_path.with_name(f"._{report_path.name}").write_bytes(b"appledouble")
    monkeypatch.setattr(audit_script, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(audit_script, "REPORTS_DIR", reports_dir)

    assert audit_script.load_results() == [{"run_id": "sub-01_task-rest_run-01"}]
    assert audit_script.report_counts()["import"] == 1


def test_audit_locates_nested_nonfinite_values():
    value = {"finite": 1.0, "nested": [{"nan": float("nan")}, float("inf")]}

    assert audit_script.nonfinite_locations(value) == ["nested[0].nan", "nested[1]"]


def test_qc_sensitivity_matrix_counts_threshold_and_gate_combinations():
    records = [
        sensitivity_script.summarize_sci("run-1", "task", [0.4, 0.6, 0.8, 1.0]),
        sensitivity_script.summarize_sci("run-2", "task", [0.9, 0.9, 0.9, 0.9]),
        {"run_id": "run-3", "task": "task", "status": "data_invalid"},
    ]

    matrix = sensitivity_script.gate_matrix(records)
    baseline = next(
        row for row in matrix if row["sci_threshold"] == 0.8 and row["min_pass_rate"] == 0.5
    )

    assert baseline == {
        "sci_threshold": 0.8,
        "min_pass_rate": 0.5,
        "passed_runs": 2,
        "failed_runs": 0,
        "readable_runs": 2,
        "pass_fraction": 1.0,
    }


def test_exclusion_manifest_distinguishes_qc_events_and_invalid_data(tmp_path):
    base = {"run_id": "sub-01_task-test_run-01", "subject": "01", "task": "test", "run": "01"}
    result_path = tmp_path / "result.json"

    qc = exclusion_script.classify_exclusion(
        {**base, "status": "qc_failed", "qc": {"sci_pass_rate": 0.2}}, result_path
    )
    missing_events = exclusion_script.classify_exclusion(
        {**base, "status": "preprocessed_no_glm", "message": "events.tsv not found"}, result_path
    )
    invalid = exclusion_script.classify_exclusion(
        {**base, "status": "data_invalid", "message": "malformed SNIRF"}, result_path
    )

    assert qc and (qc["category"], qc["reason_code"]) == ("quality_exclusion", "SCI_GATE_FAILED")
    assert missing_events and missing_events["reason_code"] == "EVENTS_FILE_MISSING"
    assert missing_events["recoverable"] is True
    assert invalid and (invalid["category"], invalid["reason_code"]) == (
        "source_data_invalid",
        "SNIRF_METADATA_INVALID",
    )


def test_reproducibility_comparison_distinguishes_numeric_and_metadata_leaves():
    numeric, metadata = comparison_script.flatten_values(
        {"rows": [{"beta": 1.0, "channel": "S1_D1"}], "passed": True}
    )

    assert numeric == {"$.rows[0].beta": 1.0}
    assert metadata == {"$.rows[0].channel": "S1_D1", "$.passed": True}
