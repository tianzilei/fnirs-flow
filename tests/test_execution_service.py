"""Tests for ExecutionService key paths: injection, dispatch, BIDS parsing."""

from __future__ import annotations

import csv

import numpy as np
import pytest

from fnirs_flow.execution.service import ExecutionRequest, ExecutionService

# ============================================================================
# _build_run_id tests
# ============================================================================


class TestBuildRunId:
    def test_full_entities(self):
        from fnirs_flow.execution.engine import _build_run_id

        result = _build_run_id(
            {
                "subject": "01",
                "session": "pre",
                "task": "motor",
                "run": "02",
            }
        )
        assert result == "sub-01_ses-pre_task-motor_run-02"

    def test_partial_entities(self):
        from fnirs_flow.execution.engine import _build_run_id

        result = _build_run_id({"subject": "01", "task": "rest"})
        assert result == "sub-01_task-rest"

    def test_no_entities(self):
        from fnirs_flow.execution.engine import _build_run_id

        result = _build_run_id({})
        assert result == "run-unknown"


# ============================================================================
# _parse_bids_events_tsv tests
# ============================================================================


class TestParseBidsEventsTsv:
    def _write_events_tsv(self, tmp_path, rows, header=None):
        path = tmp_path / "events.tsv"
        if header is None:
            header = ["onset", "trial_type"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(header)
            for row in rows:
                writer.writerow(row)
        return path

    def test_basic_parsing(self, tmp_path):
        path = self._write_events_tsv(
            tmp_path,
            [
                [0.0, "condA"],
                [5.0, "condB"],
                [10.0, "condA"],
            ],
        )
        service = ExecutionService()
        events, event_id = service._parse_bids_events_tsv(str(path), sfreq=10.0)
        assert events.shape == (3, 3)
        assert event_id == {"condA": 1, "condB": 2}
        assert events[0, 0] == 0  # onset 0.0 * 10 = sample 0
        assert events[1, 0] == 50  # onset 5.0 * 10 = sample 50

    def test_empty_file_raises(self, tmp_path):
        path = tmp_path / "events.tsv"
        path.write_text("onset\ttrial_type\n", encoding="utf-8")
        service = ExecutionService()
        with pytest.raises(ValueError, match="Empty events file"):
            service._parse_bids_events_tsv(str(path), sfreq=10.0)

    def test_missing_onset_raises(self, tmp_path):
        path = tmp_path / "events.tsv"
        path.write_text("trial_type\ncondA\n", encoding="utf-8")
        service = ExecutionService()
        with pytest.raises(ValueError, match="No 'onset' column"):
            service._parse_bids_events_tsv(str(path), sfreq=10.0)


# ============================================================================
# _inject_dependencies tests
# ============================================================================


class TestInjectDependencies:
    def test_inject_design_matrix(self):
        service = ExecutionService()
        atom = {"operation": "first_level_glm", "parameters": {}}
        params = {}
        state = {"design_matrix": {"X": [1, 2, 3]}}
        service._inject_dependencies(atom, params, state)
        assert params["design_matrix"] == {"X": [1, 2, 3]}

    def test_inject_does_not_overwrite_existing(self):
        service = ExecutionService()
        atom = {"operation": "first_level_glm", "parameters": {}}
        params = {"design_matrix": {"X": "existing"}}
        state = {"design_matrix": {"X": "new"}}
        service._inject_dependencies(atom, params, state)
        assert params["design_matrix"] == {"X": "existing"}

    def test_inject_contrast_result(self):
        service = ExecutionService()
        atom = {"operation": "channel_output", "parameters": {}}
        params = {}
        state = {"contrast_result": {"contrasts": []}}
        service._inject_dependencies(atom, params, state)
        assert params["contrast_result"] == {"contrasts": []}

    def test_inject_roi_channel_results(self):
        service = ExecutionService()
        atom = {"operation": "roi_output", "parameters": {}}
        params = {}
        state = {"channel_results": {"channels": []}}
        service._inject_dependencies(atom, params, state)
        assert params["channel_results"] == {"channels": []}

    def test_inject_contrasts_from_atom_config(self):
        service = ExecutionService()
        atom = {
            "operation": "estimate_contrast",
            "parameters": {"contrasts": [{"name": "A-B", "weights": [1, -1]}]},
        }
        params = {}
        state = {"glm_result": {"betas": []}}
        service._inject_dependencies(atom, params, state)
        assert params["glm_result"] == {"betas": []}
        assert params["contrasts"] == [{"name": "A-B", "weights": [1, -1]}]

    def test_inject_events_from_tsv(self, tmp_path):
        path = tmp_path / "events.tsv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(["onset", "trial_type"])
            writer.writerow([0.0, "condA"])
            writer.writerow([5.0, "condB"])

        service = ExecutionService()
        atom = {"operation": "build_design_matrix", "parameters": {}}
        params = {}
        state = {"events_path": str(path), "raw": None}
        service._inject_dependencies(atom, params, state)
        assert "events" in params
        assert "event_id" in params
        assert params["event_id"] == {"condA": 1, "condB": 2}

    def test_no_injection_for_unknown_operation(self):
        service = ExecutionService()
        atom = {"operation": "unknown_op", "parameters": {}}
        params = {}
        state = {"design_matrix": {"X": 1}}
        service._inject_dependencies(atom, params, state)
        assert params == {}


# ============================================================================
# _dispatch_preprocessing tests
# ============================================================================


class TestDispatchPreprocessing:
    def _make_mock_adapter(self):
        class MockAdapter:
            def to_optical_density(self, raw):
                return {"type": "od"}

            def compute_qc(self, raw):
                return {"sci": 0.9}

            def apply_motion_correction(self, raw, method="tddr"):
                return {"corrected": True}

            def apply_filter(self, raw, l_freq=0.01, h_freq=0.2):
                return {"filtered": True}

            def to_haemoglobin(self, raw, ppf=6.0):
                return {"hb": True}

        return MockAdapter()

    def test_dispatch_optical_density(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "optical_density", {})
        assert result == {"type": "od"}

    def test_dispatch_compute_qc(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "compute_qc", {})
        assert result == {"sci": 0.9}

    def test_dispatch_motion_correction(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "motion_correction", {"method": "wavelet"})
        assert result == {"corrected": True}

    def test_dispatch_filtering(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "filtering", {"l_freq": 0.01, "h_freq": 0.5})
        assert result == {"filtered": True}

    def test_dispatch_beer_lambert(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "beer_lambert_law", {"ppf": 6.0})
        assert result == {"hb": True}

    def test_dispatch_unknown_raises(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        with pytest.raises(ValueError, match="Unknown preprocessing"):
            service._dispatch_preprocessing(adapter, "raw", "nonexistent", {})


# ============================================================================
# _dispatch_analysis tests
# ============================================================================


class TestDispatchAnalysis:
    def _make_mock_adapter(self):
        class MockAdapter:
            def block_averaging(self, raw, baseline_window=(-5, 0), response_window=(0, 20)):
                return {"n_trials": 10}

            def build_design_matrix(self, raw, events, event_id, hrf_model="glover", drift_order=1, high_pass=0.01):
                return {"n_conditions": len(event_id)}

            def fit_first_level_glm(self, raw, design_matrix, hrf_model="glover", noise_model="ar1"):
                return {"n_channels": 10}

            def estimate_contrast(self, glm_result, contrasts):
                return {"contrasts": []}

            def channel_output(self, contrast_result):
                return {"channels": []}

            def roi_output(self, channel_results, atlas="mni", roi_mapping=None):
                return {"rois": []}

        return MockAdapter()

    def test_dispatch_block_averaging(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_analysis(adapter, "raw", "block_averaging", {})
        assert result == {"n_trials": 10}

    def test_dispatch_build_design_matrix(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_analysis(
            adapter,
            "raw",
            "build_design_matrix",
            {
                "events": np.array([[0, 0, 1]]),
                "event_id": {"condA": 1},
            },
        )
        assert result == {"n_conditions": 1}

    def test_dispatch_build_design_matrix_no_events_raises(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        with pytest.raises(ValueError, match="requires 'events'"):
            service._dispatch_analysis(adapter, "raw", "build_design_matrix", {})

    def test_dispatch_first_level_glm(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_analysis(
            adapter,
            "raw",
            "first_level_glm",
            {
                "design_matrix": {"X": [1, 2]},
            },
        )
        assert result == {"n_channels": 10}

    def test_dispatch_first_level_glm_no_dm_raises(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        with pytest.raises(ValueError, match="requires 'design_matrix'"):
            service._dispatch_analysis(adapter, "raw", "first_level_glm", {})

    def test_dispatch_estimate_contrast(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_analysis(
            adapter,
            "raw",
            "estimate_contrast",
            {
                "glm_result": {"betas": []},
                "contrasts": [{"name": "A-B", "weights": [1, -1]}],
            },
        )
        assert result == {"contrasts": []}

    def test_dispatch_estimate_contrast_no_glm_raises(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        with pytest.raises(ValueError, match="requires 'glm_result'"):
            service._dispatch_analysis(adapter, "raw", "estimate_contrast", {"contrasts": []})

    def test_dispatch_channel_output(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_analysis(
            adapter,
            "raw",
            "channel_output",
            {
                "contrast_result": {"contrasts": []},
            },
        )
        assert result == {"channels": []}

    def test_dispatch_roi_output(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_analysis(
            adapter,
            "raw",
            "roi_output",
            {
                "channel_results": {"channels": []},
            },
        )
        assert result == {"rois": []}

    def test_dispatch_unknown_raises(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        with pytest.raises(ValueError, match="Unknown analysis"):
            service._dispatch_analysis(adapter, "raw", "nonexistent", {})


# ============================================================================
# OperationRegistry tests
# ============================================================================


class TestOperationRegistry:
    def test_registry_has_all_operations(self):
        from fnirs_flow.execution.operations import create_default_registry

        registry = create_default_registry()
        ops = registry.list_operations()
        # Preprocessing
        assert "optical_density" in ops
        assert "filtering" in ops
        assert "beer_lambert_law" in ops
        # Analysis
        assert "build_design_matrix" in ops
        assert "first_level_glm" in ops
        assert "estimate_contrast" in ops
        assert "channel_output" in ops
        assert "roi_output" in ops

    def test_registry_has_category(self):
        from fnirs_flow.execution.operations import create_default_registry

        registry = create_default_registry()
        spec = registry.get("optical_density")
        assert spec is not None
        assert spec.category == "preprocessing"

    def test_registry_no_duplicates(self):
        from fnirs_flow.execution.operations import OperationRegistry, OperationSpec

        registry = OperationRegistry()
        registry.register(OperationSpec(operation_id="op1", category="test"))
        with pytest.raises(ValueError, match="Duplicate"):
            registry.register(OperationSpec(operation_id="op1", category="test"))


# ============================================================================
# ExecutionRequest tests
# ============================================================================


class TestExecutionRequest:
    def test_defaults(self):
        req = ExecutionRequest(project_dir="/tmp/proj")
        assert req.continue_on_failure is True
        assert req.reports_only is False
        assert req.participant_labels == []
        assert req.session_labels == []

    def test_custom_values(self):
        req = ExecutionRequest(
            project_dir="/tmp/proj",
            participant_labels=["01", "02"],
            continue_on_failure=False,
        )
        assert req.participant_labels == ["01", "02"]
        assert req.continue_on_failure is False


# ============================================================================
# Group summary tests
# ============================================================================


class TestGroupSummary:
    def test_extract_roi_list_from_dict(self):
        svc = ExecutionService()
        roi_output = {
            "rois": [
                {"roi_name": "LeftMotor", "n_channels": 28, "tapping_vs_control_beta_mean": 4.21e-08},
                {"roi_name": "RightMotor", "n_channels": 28, "tapping_vs_control_beta_mean": 4.97e-08},
            ],
            "n_rois": 2,
        }
        result = svc._extract_roi_list(roi_output)
        assert len(result) == 2
        assert result[0]["roi_name"] == "LeftMotor"

    def test_extract_roi_list_empty(self):
        svc = ExecutionService()
        assert svc._extract_roi_list({}) == []
        assert svc._extract_roi_list(None) == []

    def test_extract_channel_list_from_dict(self):
        svc = ExecutionService()
        channel_output = {
            "channels": [
                {"channel_idx": 0, "tapping_vs_control_beta": 1.56e-07},
                {"channel_idx": 1, "tapping_vs_control_beta": -4.5e-08},
            ],
            "n_channels": 2,
        }
        result = svc._extract_channel_list(channel_output)
        assert len(result) == 2

    def test_generate_group_summary_from_run_results(self):
        from fnirs_flow.execution.service import RunExecutionResult

        svc = ExecutionService()

        # Create mock run results with ROI data
        run_results = [
            RunExecutionResult(
                run_id="sub-01_task-tapping",
                status="completed",
                roi_results=[
                    {"roi_name": "LeftMotor", "n_channels": 28, "tapping_vs_control_beta_mean": 4.21e-08},
                    {"roi_name": "RightMotor", "n_channels": 28, "tapping_vs_control_beta_mean": 4.97e-08},
                ],
            ),
            RunExecutionResult(
                run_id="sub-02_task-tapping",
                status="completed",
                roi_results=[
                    {"roi_name": "LeftMotor", "n_channels": 28, "tapping_vs_control_beta_mean": 3.88e-08},
                    {"roi_name": "RightMotor", "n_channels": 28, "tapping_vs_control_beta_mean": 5.12e-08},
                ],
            ),
            RunExecutionResult(
                run_id="sub-03_task-tapping",
                status="failed",
                roi_results=[],
            ),
        ]

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path
            outdir = Path(tmpdir)
            csv_path = svc._generate_group_summary(run_results, outdir)

            assert csv_path is not None
            assert csv_path.exists()
            assert csv_path.name == "group_summary.csv"

            # Verify CSV content
            import csv as csv_mod
            with open(csv_path, encoding="utf-8") as f:
                reader = csv_mod.DictReader(f)
                rows = list(reader)

            assert len(rows) == 2  # 2 ROIs
            assert rows[0]["roi"] in ("LeftMotor", "RightMotor")
            assert int(rows[0]["n_subjects"]) == 2
            assert rows[0]["excluded_subjects"] == "sub-03_task-tapping"

            # Verify JSON summary
            import json
            json_path = outdir / "derivatives" / "group" / "group_summary.json"
            assert json_path.exists()
            summary = json.loads(json_path.read_text(encoding="utf-8"))
            assert summary["n_subjects_included"] == 2
            assert summary["n_subjects_excluded"] == 1

    def test_generate_group_summary_no_data(self):
        from fnirs_flow.execution.service import RunExecutionResult

        svc = ExecutionService()
        run_results = [
            RunExecutionResult(run_id="sub-01", status="skipped"),
        ]

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path
            result = svc._generate_group_summary(run_results, Path(tmpdir))
            assert result is None
