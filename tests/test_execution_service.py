"""Tests for ExecutionService key paths: injection, dispatch, BIDS parsing."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from fnirs_flow.execution.service import ExecutionRequest, ExecutionService, resolve_atom_backend_id

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
        assert result == "run-unlabeled"


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

    def test_declared_condition_order_is_stable(self, tmp_path):
        path = self._write_events_tsv(tmp_path, [[0.0, "Right"], [5.0, "Left"]])

        events, event_id = ExecutionService()._parse_bids_events_tsv(
            str(path), sfreq=10.0, expected_conditions=["Left", "Right"]
        )

        assert event_id == {"Left": 1, "Right": 2}
        assert events[:, 2].tolist() == [2, 1]

    def test_condition_contract_fails_closed_on_mismatch(self, tmp_path):
        path = self._write_events_tsv(tmp_path, [[0.0, "Left"], [5.0, "Unexpected"]])

        with pytest.raises(ValueError, match="EVENT_CONDITION_MISMATCH"):
            ExecutionService()._parse_bids_events_tsv(
                str(path), sfreq=10.0, expected_conditions=["Left", "Right"]
            )

    def test_explicit_excluded_event_label_is_removed_before_validation(self, tmp_path):
        path = self._write_events_tsv(tmp_path, [[0.0, "15.0"], [5.0, "Left"], [10.0, "Right"]])

        events, event_id = ExecutionService()._parse_bids_events_tsv(
            str(path),
            sfreq=10.0,
            expected_conditions=["Left", "Right"],
            excluded_conditions=["15.0"],
        )

        assert event_id == {"Left": 1, "Right": 2}
        assert events.tolist() == [[50, 1, 1], [100, 1, 2]]


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

    def test_parse_events_filters_excluded_trials_and_preserves_duration(self, tmp_path):
        path = tmp_path / "events.tsv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream, delimiter="\t")
            writer.writerow(["onset", "duration", "trial_type", "include"])
            writer.writerow([1.0, 5.0, "Left", 1])
            writer.writerow([2.0, 5.0, "Right", 0])
            writer.writerow([3.0, 2.5, "Right", 1])

        events, event_id = ExecutionService()._parse_bids_events_tsv(str(path), sfreq=10.0)

        assert event_id == {"Left": 1, "Right": 2}
        assert events.tolist() == [[10, 50, 1], [30, 25, 2]]

    def test_no_injection_for_unknown_operation(self):
        service = ExecutionService()
        atom = {"operation": "unknown_op", "parameters": {}}
        params = {}
        state = {"design_matrix": {"X": 1}}
        service._inject_dependencies(atom, params, state)
        assert params == {}


class TestBackendCreation:
    def test_null_backend_id_uses_default_backend(self):
        assert resolve_atom_backend_id({"backend_id": None}, "mne_nirs") == "mne_nirs"
        assert resolve_atom_backend_id({"backend_id": ""}, "mne_nirs") == "mne_nirs"
        assert resolve_atom_backend_id({}, "mne_nirs") == "mne_nirs"
        assert resolve_atom_backend_id({"backend_id": "cedalion"}, "mne_nirs") == "cedalion"

    def test_requested_backend_is_not_silently_replaced(self):
        registry = MagicMock()
        registry.create.side_effect = ValueError("Backend cedalion is not available")
        service = ExecutionService()

        with pytest.raises(ImportError, match="Required backend 'cedalion' is unavailable"):
            service._create_backend_adapter(registry, "cedalion")

        registry.create.assert_called_once_with("cedalion")


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

            def apply_motion_correction(self, raw, method="tddr", **kwargs):
                return {"corrected": True, "method": method, "kwargs": kwargs}

            def apply_filter(self, raw, l_freq=0.01, h_freq=0.2, method="bandpass", **kwargs):
                return {"filtered": True, "method": method, "l_freq": l_freq, "h_freq": h_freq, "kwargs": kwargs}

            def to_haemoglobin(self, raw, ppf=6.0):
                return {"hb": True}

        return MockAdapter()

    def test_dispatch_optical_density(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "optical_density", {})
        assert result == {"type": "od"}

    def test_dispatch_template_optical_density_alias(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "optical_density_conversion", {})
        assert result == {"type": "od"}

    def test_dispatch_compute_qc(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "compute_qc", {})
        assert result == {"sci": 0.9}

    def test_dispatch_legacy_qc_alias(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "qc_metrics", {})
        assert result == {"sci": 0.9}

    def test_dispatch_qc_converts_raw_intensity_when_needed(self):
        class Adapter:
            versions = {}

            def __init__(self):
                self.converted = False

            def compute_qc(self, raw):
                if raw == "raw":
                    raise RuntimeError("Scalp coupling index must operate on optical density data, but none was found.")
                return {"sci": 0.9, "raw": raw}

            def to_optical_density(self, raw):
                self.converted = True
                return f"od({raw})"

        service = ExecutionService()
        adapter = Adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "compute_qc", {})
        assert adapter.converted is True
        assert result == {"sci": 0.9, "raw": "od(raw)"}

    def test_dispatch_motion_correction(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "motion_correction", {"method": "wavelet"})
        assert result["method"] == "wavelet"

    def test_dispatch_motion_template_alias_preserves_method(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "spline", {"spline_segments": 4})
        assert result["method"] == "spline"
        assert result["kwargs"]["spline_segments"] == 4

    def test_dispatch_filtering(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "filtering", {"l_freq": 0.01, "h_freq": 0.5})
        assert result["method"] == "bandpass"
        assert result["h_freq"] == 0.5

    def test_dispatch_filter_template_alias_preserves_method(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "notch", {"freqs": [60.0]})
        assert result["method"] == "notch"
        assert result["kwargs"]["freqs"] == [60.0]

    def test_dispatch_beer_lambert(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "beer_lambert_law", {"ppf": 6.0})
        assert result == {"hb": True}

    def test_dispatch_template_beer_lambert_alias(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "mbll", {"ppf": 6.0})
        assert result == {"hb": True}

    def test_dispatch_combat_alias_passes_input_through(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_preprocessing(adapter, "raw", "multi_site_harmonization", {})
        assert result == "raw"

    def test_dispatch_unknown_raises(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        with pytest.raises(ValueError, match="no registered preprocessing handler"):
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
                return {"n_conditions": len(event_id), "hrf_model": hrf_model}

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
        assert result == {"n_conditions": 1, "hrf_model": "glover"}

    def test_dispatch_legacy_design_matrix_alias(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_analysis(
            adapter,
            "raw",
            "design_matrix",
            {
                "events": np.array([[0, 0, 1]]),
                "event_id": {"condA": 1},
            },
        )
        assert result == {"n_conditions": 1, "hrf_model": "glover"}

    def test_dispatch_template_advanced_glm_aliases(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        for operation in ("linear_mixed_effects_glm", "nuisance_glm", "site_covariate_glm"):
            result = service._dispatch_analysis(
                adapter,
                "raw",
                operation,
                {"design_matrix": {"columns": ["condA"]}},
            )
            assert result == {"n_channels": 10}

    def test_dispatch_legacy_canonical_hrf_maps_to_glover(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_analysis(
            adapter,
            "raw",
            "build_design_matrix",
            {
                "events": np.array([[0, 0, 1]]),
                "event_id": {"condA": 1},
                "hrf_model": "canonical",
            },
        )
        assert result == {"n_conditions": 1, "hrf_model": "glover"}

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

    def test_dispatch_legacy_string_contrast_alias(self):
        service = ExecutionService()
        adapter = self._make_mock_adapter()
        result = service._dispatch_analysis(
            adapter,
            "raw",
            "contrast",
            {
                "glm_result": {"betas": [], "n_conditions": 2, "conditions": ["tapping", "rest"]},
                "contrasts": ["tapping > rest"],
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
        with pytest.raises(ValueError, match="no registered analysis handler"):
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
        assert "optical_density_conversion" in ops
        assert "compute_qc" in ops
        assert "qc_metrics" in ops
        assert "sci_check" in ops
        assert "cv_check" in ops
        assert "snr_check" in ops
        assert "bad_channel_detection" in ops
        assert "tddr" in ops
        assert "wavelet" in ops
        assert "spline" in ops
        assert "ica" in ops
        assert "pca" in ops
        assert "cbsi" in ops
        assert "filtering" in ops
        assert "bandpass" in ops
        assert "notch" in ops
        assert "lowpass" in ops
        assert "beer_lambert_law" in ops
        assert "mbll" in ops
        assert "combat_harmonization" in ops
        assert "multi_site_harmonization" in ops
        # Analysis
        assert "build_design_matrix" in ops
        assert "design_matrix" in ops
        assert "first_level_glm" in ops
        assert "linear_mixed_effects_glm" in ops
        assert "mixed_effects_glm" in ops
        assert "nuisance_glm" in ops
        assert "site_covariate_glm" in ops
        assert "estimate_contrast" in ops
        assert "contrast" in ops
        assert "channel_output" in ops
        assert "roi_output" in ops
        # Participant metadata and group scope
        assert "participant_table_input" in ops
        assert "participant_metadata_join" in ops
        assert "group_design_matrix" in ops
        assert "participant_dpf_projection" in ops
        assert "participant_outcome_projection" in ops
        assert "combat_preflight" in ops
        assert "empty_marker" in ops

    def test_registry_has_category(self):
        from fnirs_flow.execution.operations import create_default_registry

        registry = create_default_registry()
        spec = registry.get("optical_density")
        assert spec is not None
        assert spec.category == "preprocessing"
        empty_spec = registry.get("empty_marker")
        assert empty_spec is not None
        assert empty_spec.category == "control"

    def test_registry_no_duplicates(self):
        from fnirs_flow.execution.operations import OperationRegistry, OperationSpec

        registry = OperationRegistry()
        registry.register(OperationSpec(operation_id="op1", category="test"))
        with pytest.raises(ValueError, match="Duplicate"):
            registry.register(OperationSpec(operation_id="op1", category="test"))

    def test_executable_node_template_operations_have_runtime_aliases(self):
        from fnirs_flow.execution.operations import canonical_operation
        from fnirs_flow.registry.node_templates import ALL_NODE_TEMPLATES

        expected = {
            "optical_density": "optical_density",
            "tddr_motion_correction": "motion_correction",
            "spline_motion_correction": "motion_correction",
            "wavelet_motion_correction": "motion_correction",
            "ica_motion_correction": "motion_correction",
            "pca_motion_correction": "motion_correction",
            "cbsi_motion_correction": "motion_correction",
            "bandpass_filter": "filtering",
            "notch_filter": "filtering",
            "lowpass_filter": "filtering",
            "beer_lambert_law": "beer_lambert_law",
            "qc_metrics": "compute_qc",
            "sci_check": "compute_qc",
            "cv_check": "compute_qc",
            "snr_check": "compute_qc",
            "bad_channel_detection": "compute_qc",
            "design_matrix": "build_design_matrix",
            "first_level_glm": "first_level_glm",
            "contrast": "estimate_contrast",
            "nuisance_glm": "first_level_glm",
            "linear_mixed_effects_glm": "first_level_glm",
            "site_covariate_glm": "first_level_glm",
            "channel_output": "channel_output",
            "roi_output": "roi_output",
        }
        by_id = {template.template_id: template for template in ALL_NODE_TEMPLATES}

        for template_id, canonical in expected.items():
            template = by_id[template_id]
            assert canonical_operation(template.operation or template.atom_type) == canonical


# ============================================================================
# ExecutionRequest tests
# ============================================================================


class TestExecutionRequest:
    def test_defaults(self):
        req = ExecutionRequest(project_dir="/tmp/proj")
        assert req.continue_on_failure
        assert not req.reports_only
        assert req.participant_labels == []
        assert req.session_labels == []
        assert req.task_labels == []

    def test_custom_values(self):
        req = ExecutionRequest(
            project_dir="/tmp/proj",
            participant_labels=["01", "02"],
            task_labels=["covert"],
            continue_on_failure=False,
        )
        assert req.participant_labels == ["01", "02"]
        assert req.task_labels == ["covert"]
        assert not req.continue_on_failure

    def test_task_filter_selects_only_requested_task(self, tmp_path):
        manifest = {
            "subject_session_runs": [
                {"subject": "01", "task": "covert", "run": "01", "path": "covert.snirf"},
                {"subject": "01", "task": "resting", "run": "01", "path": "resting.snirf"},
            ]
        }
        (tmp_path / "data_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        runs = ExecutionService()._resolve_runs(
            tmp_path,
            ExecutionRequest(project_dir=str(tmp_path), task_labels=["covert"]),
        )

        assert [(run.task, run.run) for run in runs] == [("covert", "01")]


class TestExecutionFailureAggregation:
    class _Artifacts:
        def all(self):
            return []

    class _Adapter:
        versions = {}
        artifacts = None

        def __init__(self):
            self.artifacts = TestExecutionFailureAggregation._Artifacts()

        def read_run(self, path):
            return object()

    class _Registry:
        def create(self, backend_id, **kwargs):
            return TestExecutionFailureAggregation._Adapter()

    def test_failed_atom_never_counts_run_as_success(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {
                    "atom_id": "bad-atom",
                    "step_id": "bad-atom",
                    "operation": "unsupported-operation",
                    "category": "preprocessing",
                    "parameters": {},
                }
            ],
            "execution_layers": [["bad-atom"]],
            "edges": [],
        }

        with patch(
            "fnirs_flow.adapters.backend_registry.get_registry",
            return_value=self._Registry(),
        ):
            result = ExecutionService()._execute_run(
                RunContext(run_id="run-1", data_path=str(data_path)),
                {},
                dag,
                tmp_path,
                continue_on_failure=True,
            )

        assert result.status == "failed"
        assert len(result.atom_results) == 1
        assert result.atom_results[0].status == "failed"
        assert result.planned_steps == ["bad-atom"]
        assert result.failed_step == "bad-atom"
        assert result.failed_error_code == "UNREGISTERED_OPERATION"
        assert result.failed_error == "Unregistered operation: unsupported-operation"

    def test_stop_on_failure_records_atom_once(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {
                    "atom_id": "bad-atom",
                    "operation": "unsupported-operation",
                    "category": "preprocessing",
                    "parameters": {},
                }
            ],
            "execution_layers": [["bad-atom"]],
            "edges": [],
        }
        with patch(
            "fnirs_flow.adapters.backend_registry.get_registry",
            return_value=self._Registry(),
        ):
            result = ExecutionService()._execute_run(
                RunContext(run_id="run-1", data_path=str(data_path)),
                {},
                dag,
                tmp_path,
                continue_on_failure=False,
            )

        assert result.status == "failed"
        assert [(item.atom_id, item.status) for item in result.atom_results] == [("bad-atom", "failed")]


class TestValidationQcExecution:
    class _Artifacts:
        def all(self):
            return []

    class _Adapter:
        versions = {}

        def __init__(self):
            self.artifacts = TestValidationQcExecution._Artifacts()
            self.qc_inputs = []

        def read_run(self, path):
            return {"raw_path": path}

        def compute_qc(self, raw, **kwargs):
            self.qc_inputs.append((raw, kwargs))
            return {"sci": 0.9}

    class _Registry:
        def __init__(self):
            self.adapter = TestValidationQcExecution._Adapter()

        def create(self, backend_id, **kwargs):
            return self.adapter

    def test_validation_qc_template_executes_instead_of_skipping(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {
                    "atom_id": "sci",
                    "operation": "sci_check",
                    "category": "validation",
                    "parameters": {"threshold": 0.75},
                }
            ],
            "execution_layers": [["sci"]],
            "edges": [],
        }
        registry = self._Registry()

        with patch("fnirs_flow.adapters.backend_registry.get_registry", return_value=registry):
            result = ExecutionService()._execute_run(
                RunContext(run_id="run-1", data_path=str(data_path)),
                {},
                dag,
                tmp_path,
            )

        assert result.status == "completed"
        assert [(item.atom_id, item.status) for item in result.atom_results] == [("sci", "completed")]
        assert registry.adapter.qc_inputs[0][1]["sci_threshold"] == 0.75


class TestEmptyMarkerExecution:
    class _Artifacts:
        def all(self):
            return []

    class _Adapter:
        versions = {}

        def __init__(self):
            self.artifacts = TestEmptyMarkerExecution._Artifacts()

        def read_run(self, path):
            return {"raw_path": path}

        def apply_filter(self, *_args, **_kwargs):
            raise AssertionError("empty_marker must not dispatch preprocessing")

        def to_optical_density(self, *_args, **_kwargs):
            raise AssertionError("empty_marker must not dispatch preprocessing")

    class _Registry:
        def create(self, backend_id, **kwargs):
            return TestEmptyMarkerExecution._Adapter()

    def test_empty_marker_marks_state_without_processing(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {
                    "atom_id": "empty_preprocessing",
                    "step_id": "empty_preprocessing",
                    "operation": "empty_marker",
                    "category": "preprocessing",
                    "parameters": {"state_marker": "empty_preprocessing"},
                }
            ],
            "execution_layers": [["empty_preprocessing"]],
            "edges": [],
        }

        with patch("fnirs_flow.adapters.backend_registry.get_registry", return_value=self._Registry()):
            result = ExecutionService()._execute_run(
                RunContext(run_id="run-1", data_path=str(data_path)),
                {},
                dag,
                tmp_path,
                continue_on_failure=True,
            )

        assert result.status == "completed"
        assert len(result.atom_results) == 1
        atom_result = result.atom_results[0]
        assert atom_result.status == "completed"
        assert atom_result.output_handles["marker"]["status"] == "empty"
        assert atom_result.provenance["empty_processing"] is True


class TestDagBranchIsolation:
    class _Artifacts:
        def all(self):
            return []

    class _Adapter:
        versions = {}

        def __init__(self):
            self.artifacts = TestDagBranchIsolation._Artifacts()
            self.contrast_inputs = []
            self.roi_inputs = []

        def read_run(self, path):
            return object()

        def build_design_matrix(self, raw, events, event_id, **kwargs):
            return f"design-{events}"

        def fit_first_level_glm(self, raw, design_matrix, **kwargs):
            return f"glm({design_matrix})"

        def estimate_contrast(self, glm_result, contrasts):
            self.contrast_inputs.append((contrasts[0], glm_result))
            return {"glm_result": glm_result}

        def channel_output(self, contrast_result):
            return {"channels": [{"channel_idx": 1, "task_beta": contrast_result.get("beta", 1.0)}]}

        def roi_output(self, channel_results, atlas="mni", roi_mapping=None):
            self.roi_inputs.append(channel_results)
            return {"rois": [{"roi_name": "motor", "task_beta_mean": 2.0, "n_channels": 1}]}

    class _Registry:
        def __init__(self):
            self.adapter = TestDagBranchIsolation._Adapter()

        def create(self, backend_id, **kwargs):
            return self.adapter

    def test_parallel_branches_consume_only_connected_predecessor(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        atoms = [
            {
                "atom_id": "design-a",
                "step_id": "design-a",
                "operation": "build_design_matrix",
                "category": "analysis",
                "parameters": {"events": "A"},
            },
            {
                "atom_id": "design-b",
                "step_id": "design-b",
                "operation": "build_design_matrix",
                "category": "analysis",
                "parameters": {"events": "B"},
            },
            {
                "atom_id": "glm-a",
                "step_id": "glm-a",
                "operation": "first_level_glm",
                "category": "analysis",
                "parameters": {},
            },
            {
                "atom_id": "glm-b",
                "step_id": "glm-b",
                "operation": "first_level_glm",
                "category": "analysis",
                "parameters": {},
            },
            {
                "atom_id": "contrast-a",
                "step_id": "contrast-a",
                "operation": "estimate_contrast",
                "category": "analysis",
                "parameters": {"contrasts": ["A"]},
            },
            {
                "atom_id": "contrast-b",
                "step_id": "contrast-b",
                "operation": "estimate_contrast",
                "category": "analysis",
                "parameters": {"contrasts": ["B"]},
            },
        ]
        dag = {
            "atoms": atoms,
            "execution_layers": [
                ["design-a", "design-b"],
                ["glm-a", "glm-b"],
                ["contrast-a", "contrast-b"],
            ],
            "edges": [
                {"source": "design-a", "target": "glm-a"},
                {"source": "design-b", "target": "glm-b"},
                {"source": "glm-a", "target": "contrast-a"},
                {"source": "glm-b", "target": "contrast-b"},
            ],
        }
        registry = self._Registry()

        with patch(
            "fnirs_flow.adapters.backend_registry.get_registry",
            return_value=registry,
        ):
            result = ExecutionService()._execute_run(
                RunContext(run_id="run-1", data_path=str(data_path)),
                {},
                dag,
                tmp_path,
            )

        assert result.status == "completed"
        assert registry.adapter.contrast_inputs == [
            ("A", "glm(design-A)"),
            ("B", "glm(design-B)"),
        ]
        lineage = {item.atom_id: item.provenance["predecessor_atom_ids"] for item in result.atom_results}
        assert lineage["glm-a"] == ["design-a"]
        assert lineage["glm-b"] == ["design-b"]
        assert lineage["contrast-a"] == ["glm-a"]
        assert lineage["contrast-b"] == ["glm-b"]

    def test_partial_execution_layers_do_not_omit_run_atoms(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {
                    "atom_id": "design",
                    "operation": "build_design_matrix",
                    "category": "analysis",
                    "parameters": {"events": "task"},
                },
                {
                    "atom_id": "glm",
                    "operation": "first_level_glm",
                    "category": "analysis",
                    "parameters": {},
                },
            ],
            "execution_layers": [["design"]],
            "edges": [{"source": "design", "target": "glm"}],
        }

        with patch("fnirs_flow.adapters.backend_registry.get_registry", return_value=self._Registry()):
            result = ExecutionService()._execute_run(
                RunContext(run_id="run-1", data_path=str(data_path)), {}, dag, tmp_path
            )

        assert [(item.atom_id, item.status) for item in result.atom_results] == [
            ("design", "completed"),
            ("glm", "completed"),
        ]

    def test_distinct_preprocessing_branches_require_explicit_merge(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        class BranchAdapter(TestDagBranchIsolation._Adapter):
            def to_optical_density(self, _raw):
                return object()

        class BranchRegistry:
            def __init__(self):
                self.adapter = BranchAdapter()

            def create(self, _backend_id, **_kwargs):
                return self.adapter

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {
                    "atom_id": "od-a",
                    "operation": "optical_density",
                    "category": "preprocessing",
                    "parameters": {},
                },
                {
                    "atom_id": "od-b",
                    "operation": "optical_density",
                    "category": "preprocessing",
                    "parameters": {},
                },
                {
                    "atom_id": "design",
                    "operation": "build_design_matrix",
                    "category": "analysis",
                    "parameters": {"events": "task"},
                },
            ],
            "execution_layers": [["od-a", "od-b"], ["design"]],
            "edges": [
                {"source": "od-a", "target": "design"},
                {"source": "od-b", "target": "design"},
            ],
        }

        with patch("fnirs_flow.adapters.backend_registry.get_registry", return_value=BranchRegistry()):
            result = ExecutionService()._execute_run(
                RunContext(run_id="run-1", data_path=str(data_path)), {}, dag, tmp_path
            )

        design = next(item for item in result.atom_results if item.atom_id == "design")
        assert design.status == "failed"
        assert design.error_code == "EXECUTION_VALIDATION_ERROR"
        assert "['od-a', 'od-b']" in design.error
        assert "explicit merge atom" in design.error

    def test_group_core_backend_does_not_select_run_reader(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        class RecordingRegistry:
            def __init__(self):
                self.adapter = TestDagBranchIsolation._Adapter()
                self.backend_ids = []

            def create(self, backend_id, **_kwargs):
                self.backend_ids.append(backend_id)
                return self.adapter

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {
                    "atom_id": "group-design",
                    "operation": "group_design_matrix",
                    "execution_scope": "group",
                    "backend_id": "core",
                    "parameters": {},
                },
                {
                    "atom_id": "design",
                    "operation": "build_design_matrix",
                    "category": "analysis",
                    "execution_scope": "run",
                    "parameters": {"events": "task"},
                },
            ],
            "execution_layers": [["group-design"], ["design"]],
            "edges": [],
        }
        registry = RecordingRegistry()

        with patch("fnirs_flow.adapters.backend_registry.get_registry", return_value=registry):
            result = ExecutionService()._execute_run(
                RunContext(run_id="run-1", data_path=str(data_path)), {}, dag, tmp_path
            )

        assert result.status == "completed"
        assert registry.backend_ids == ["mne_nirs"]

    def test_group_only_dag_does_not_load_run_backend(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        registry = MagicMock()
        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {
                    "atom_id": "group-design",
                    "operation": "group_design_matrix",
                    "execution_scope": "group",
                    "backend_id": "core",
                    "parameters": {},
                }
            ],
            "execution_layers": [["group-design"]],
            "edges": [],
        }

        with patch("fnirs_flow.adapters.backend_registry.get_registry", return_value=registry):
            result = ExecutionService()._execute_run(
                RunContext(run_id="run-1", data_path=str(data_path)), {}, dag, tmp_path
            )

        assert result.status == "completed"
        assert result.atom_results == []
        registry.create.assert_not_called()

    def test_failure_propagates_only_within_connected_branch(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {"atom_id": "bad", "operation": "unknown", "category": "preprocessing", "parameters": {}},
                {
                    "atom_id": "design-good",
                    "operation": "build_design_matrix",
                    "category": "analysis",
                    "parameters": {"events": "GOOD"},
                },
                {"atom_id": "bad-child", "operation": "first_level_glm", "category": "analysis", "parameters": {}},
                {"atom_id": "glm-good", "operation": "first_level_glm", "category": "analysis", "parameters": {}},
            ],
            "execution_layers": [["bad", "design-good"], ["bad-child", "glm-good"]],
            "edges": [
                {"source": "bad", "target": "bad-child"},
                {"source": "design-good", "target": "glm-good"},
            ],
        }
        with patch("fnirs_flow.adapters.backend_registry.get_registry", return_value=self._Registry()):
            result = ExecutionService()._execute_run(
                RunContext(run_id="run-1", data_path=str(data_path)), {}, dag, tmp_path
            )

        statuses = {item.atom_id: item.status for item in result.atom_results}
        assert statuses == {
            "bad": "failed",
            "design-good": "completed",
            "bad-child": "skipped",
            "glm-good": "completed",
        }

    def test_upstream_failure_skips_connected_downstream(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {
                    "atom_id": "bad",
                    "step_id": "bad",
                    "operation": "unknown",
                    "category": "preprocessing",
                    "parameters": {},
                },
                {
                    "atom_id": "downstream",
                    "step_id": "downstream",
                    "operation": "first_level_glm",
                    "category": "analysis",
                    "parameters": {},
                },
            ],
            "execution_layers": [["bad"], ["downstream"]],
            "edges": [{"source": "bad", "target": "downstream"}],
        }
        registry = self._Registry()

        with patch(
            "fnirs_flow.adapters.backend_registry.get_registry",
            return_value=registry,
        ):
            result = ExecutionService()._execute_run(
                RunContext(run_id="run-1", data_path=str(data_path)),
                {},
                dag,
                tmp_path,
            )

        assert result.status == "failed"
        assert [(item.atom_id, item.status) for item in result.atom_results] == [
            ("bad", "failed"),
            ("downstream", "skipped"),
        ]

    def test_channel_output_is_retained_on_run_result(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {
                    "atom_id": "channels",
                    "step_id": "channels",
                    "operation": "channel_output",
                    "category": "output",
                    "parameters": {"contrast_result": {"beta": 2.5}},
                }
            ],
            "execution_layers": [["channels"]],
            "edges": [],
        }
        with patch(
            "fnirs_flow.adapters.backend_registry.get_registry",
            return_value=self._Registry(),
        ):
            result = ExecutionService()._execute_run(
                RunContext(run_id="sub-01", data_path=str(data_path)), {}, dag, tmp_path
            )

        assert result.status == "completed"
        assert result.channel_results == [
            {"channel_idx": 1, "task_beta": 2.5, "source_atom_id": "channels"}
        ]
        assert (tmp_path / "derivatives/channel/sub-01_channel_results.csv").exists()


    def test_dual_channel_and_roi_outputs_are_accumulated_by_branch(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {
                    "atom_id": "channels-a",
                    "operation": "channel_output",
                    "category": "output",
                    "parameters": {"contrast_result": {"beta": 1.0}},
                },
                {
                    "atom_id": "channels-b",
                    "operation": "channel_output",
                    "category": "output",
                    "parameters": {"contrast_result": {"beta": 3.0}},
                },
                {"atom_id": "roi-a", "operation": "roi_output", "category": "output", "parameters": {}},
                {"atom_id": "roi-b", "operation": "roi_output", "category": "output", "parameters": {}},
            ],
            "execution_layers": [["channels-a", "channels-b"], ["roi-a", "roi-b"]],
            "edges": [
                {"source": "channels-a", "target": "roi-a"},
                {"source": "channels-b", "target": "roi-b"},
            ],
        }
        registry = self._Registry()
        with patch("fnirs_flow.adapters.backend_registry.get_registry", return_value=registry):
            result = ExecutionService()._execute_run(
                RunContext(run_id="sub-01", data_path=str(data_path)), {}, dag, tmp_path
            )

        assert [(row["source_atom_id"], row["task_beta"]) for row in result.channel_results] == [
            ("channels-a", 1.0),
            ("channels-b", 3.0),
        ]
        assert [row["source_atom_id"] for row in result.roi_results] == ["roi-a", "roi-b"]
        assert all("source_atom_id" not in row for value in registry.adapter.roi_inputs for row in value["channels"])
        assert (tmp_path / "derivatives/roi/sub-01_roi_results.csv").exists()

    def test_atom_progress_events_are_ordered_and_detailed(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        events = []
        dag = {
            "atoms": [
                {
                    "atom_id": "channels",
                    "operation": "channel_output",
                    "category": "output",
                    "parameters": {"contrast_result": {"beta": 1.0}},
                }
            ],
            "execution_layers": [["channels"]],
            "edges": [],
        }
        with patch(
            "fnirs_flow.adapters.backend_registry.get_registry",
            return_value=self._Registry(),
        ):
            ExecutionService(progress_callback=events.append)._execute_run(
                RunContext(run_id="sub-01", data_path=str(data_path)), {}, dag, tmp_path
            )

        assert [event["type"] for event in events] == ["atom_started", "atom_completed"]
        assert events[1]["atom_id"] == "channels"
        assert events[1]["status"] == "completed"

    def test_dual_glm_lineage_is_persisted_in_provenance_log(self, tmp_path):
        import json

        compiled = tmp_path / "compiled"
        compiled.mkdir()
        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        atoms = [
            {
                "atom_id": "design-a",
                "operation": "build_design_matrix",
                "category": "analysis",
                "parameters": {"events": "A"},
            },
            {
                "atom_id": "design-b",
                "operation": "build_design_matrix",
                "category": "analysis",
                "parameters": {"events": "B"},
            },
            {"atom_id": "glm-a", "operation": "first_level_glm", "category": "analysis", "parameters": {}},
            {"atom_id": "glm-b", "operation": "first_level_glm", "category": "analysis", "parameters": {}},
            {
                "atom_id": "contrast-a",
                "operation": "estimate_contrast",
                "category": "analysis",
                "parameters": {"contrasts": ["A"]},
            },
            {
                "atom_id": "contrast-b",
                "operation": "estimate_contrast",
                "category": "analysis",
                "parameters": {"contrasts": ["B"]},
            },
        ]
        dag = {
            "atoms": atoms,
            "execution_layers": [["design-a", "design-b"], ["glm-a", "glm-b"], ["contrast-a", "contrast-b"]],
            "edges": [
                {"source": "design-a", "target": "glm-a"},
                {"source": "design-b", "target": "glm-b"},
                {"source": "glm-a", "target": "contrast-a"},
                {"source": "glm-b", "target": "contrast-b"},
            ],
        }
        (compiled / "plan.json").write_text("{}", encoding="utf-8")
        (compiled / "execution_dag.json").write_text(json.dumps(dag), encoding="utf-8")
        (compiled / "data_manifest.json").write_text(
            json.dumps({"subject_session_runs": [{"subject": "01", "task": "test", "path": str(data_path)}]}),
            encoding="utf-8",
        )

        with patch("fnirs_flow.adapters.backend_registry.get_registry", return_value=self._Registry()):
            result = ExecutionService().execute(
                ExecutionRequest(project_dir=str(tmp_path), outdir=str(tmp_path), attempt_id="attempt-provenance")
            )

        assert result.attempt_id == "attempt-provenance"
        provenance_path = next(tmp_path.rglob("provenance_log.json"))
        records = json.loads(provenance_path.read_text(encoding="utf-8"))
        lineage = {
            record["step_id"].split("/")[-1]: record["parameters"]["lineage"]["predecessor_atom_ids"]
            for record in records
        }
        assert lineage["glm-a"] == ["design-a"]
        assert lineage["glm-b"] == ["design-b"]
        assert lineage["contrast-a"] == ["glm-a"]
        assert lineage["contrast-b"] == ["glm-b"]


class TestGroupScopeExecution:
    @staticmethod
    def _write_compiled_project(tmp_path, dag):
        compiled = tmp_path / "compiled"
        compiled.mkdir()
        data_path = tmp_path / "sub-01.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        (compiled / "plan.json").write_text("{}", encoding="utf-8")
        (compiled / "execution_dag.json").write_text(json.dumps(dag), encoding="utf-8")
        (compiled / "data_manifest.json").write_text(
            json.dumps({"subject_session_runs": [{"subject": "01", "task": "test", "path": str(data_path)}]}),
            encoding="utf-8",
        )

    def test_group_summary_artifacts_are_in_final_manifest(self, tmp_path):
        dag = {
            "atoms": [
                {
                    "atom_id": "channels",
                    "operation": "channel_output",
                    "category": "output",
                    "parameters": {"contrast_result": {"beta": 1.0}},
                },
                {
                    "atom_id": "roi",
                    "operation": "roi_output",
                    "category": "output",
                    "parameters": {},
                },
            ],
            "execution_layers": [["channels"], ["roi"]],
            "edges": [{"source": "channels", "target": "roi"}],
        }
        self._write_compiled_project(tmp_path, dag)

        with patch(
            "fnirs_flow.adapters.backend_registry.get_registry",
            return_value=TestDagBranchIsolation._Registry(),
        ):
            result = ExecutionService().execute(
                ExecutionRequest(project_dir=str(tmp_path), outdir=str(tmp_path), attempt_id="attempt-summary")
            )

        manifest = json.loads((tmp_path / "logs" / "artifact_manifest.json").read_text(encoding="utf-8"))
        manifest_types = {item["artifact_type"] for item in manifest["artifacts"]}
        result_types = {item["type"] for item in result.artifacts}
        assert {"GroupSummaryTable", "GroupSummaryJson"} <= manifest_types
        assert {"GroupSummaryTable", "GroupSummaryJson"} <= result_types

    def test_group_atom_failures_are_written_to_failure_manifest(self, tmp_path):
        dag = {
            "atoms": [
                {
                    "atom_id": "bad-group",
                    "operation": "unsupported_group_operation",
                    "execution_scope": "group",
                    "backend_id": "core",
                    "parameters": {},
                },
                {
                    "atom_id": "run-design",
                    "operation": "build_design_matrix",
                    "category": "analysis",
                    "parameters": {"events": "task"},
                },
            ],
            "execution_layers": [["bad-group"], ["run-design"]],
            "edges": [],
        }
        self._write_compiled_project(tmp_path, dag)

        with patch(
            "fnirs_flow.adapters.backend_registry.get_registry",
            return_value=TestDagBranchIsolation._Registry(),
        ):
            result = ExecutionService().execute(
                ExecutionRequest(project_dir=str(tmp_path), outdir=str(tmp_path), attempt_id="attempt-group-failure")
            )

        failures = json.loads((tmp_path / "logs" / "failure_manifest.json").read_text(encoding="utf-8"))
        assert result.failed_runs == 1
        assert result.failure_ids == ["group"]
        assert [(item["run"], item["atom_id"]) for item in failures] == [("group", "bad-group")]

    def test_group_scope_atoms_run_once_without_inflating_run_counts(self, tmp_path):
        compiled = tmp_path / "compiled"
        compiled.mkdir()
        data_path = tmp_path / "sub-01.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        table_path = tmp_path / "participants.tsv"
        table_path.write_text(
            "participant_id\tinclude\tgroup\tlabel\tsite\tage\tclinical_score\n"
            "sub-01\t1\tcontrol\tcontrol\tsite_A\t24\t9.5\n",
            encoding="utf-8",
        )
        dag = {
            "atoms": [
                {
                    "atom_id": "participants",
                    "operation": "participant_table_input",
                    "execution_scope": "group",
                    "parameters": {"path": str(table_path), "label_column": "label"},
                },
                {
                    "atom_id": "labels",
                    "operation": "participant_label_projection",
                    "execution_scope": "group",
                    "parameters": {"label_column": "label"},
                },
                {
                    "atom_id": "covariates",
                    "operation": "participant_covariate_projection",
                    "execution_scope": "group",
                    "parameters": {"covariates": ["age"]},
                },
                {
                    "atom_id": "dpf",
                    "operation": "participant_dpf_projection",
                    "execution_scope": "group",
                    "parameters": {"age_column": "age"},
                },
                {
                    "atom_id": "outcome",
                    "operation": "participant_outcome_projection",
                    "execution_scope": "group",
                    "parameters": {"outcome_column": "clinical_score", "outcome_kind": "clinical"},
                },
                {
                    "atom_id": "combat",
                    "operation": "combat_preflight",
                    "execution_scope": "group",
                    "parameters": {"biological_covariates": ["age", "group"], "min_samples_per_site": 1},
                },
                {
                    "atom_id": "run-design",
                    "operation": "build_design_matrix",
                    "category": "analysis",
                    "execution_scope": "run",
                    "parameters": {"events": "task"},
                },
            ],
            "edges": [],
        }
        (compiled / "plan.json").write_text("{}", encoding="utf-8")
        (compiled / "execution_dag.json").write_text(json.dumps(dag), encoding="utf-8")
        (compiled / "data_manifest.json").write_text(
            json.dumps({"subject_session_runs": [{"subject": "01", "task": "test", "path": str(data_path)}]}),
            encoding="utf-8",
        )

        with patch(
            "fnirs_flow.adapters.backend_registry.get_registry",
            return_value=TestDagBranchIsolation._Registry(),
        ):
            result = ExecutionService().execute(
                ExecutionRequest(project_dir=str(tmp_path), outdir=str(tmp_path), attempt_id="attempt-group")
            )

        assert result.total_runs == 1
        assert result.successful_runs == 1
        assert result.failed_runs == 0
        group_result = next(item for item in result.run_results if item.run_id == "group")
        assert [atom.atom_id for atom in group_result.atom_results] == [
            "participants",
            "labels",
            "covariates",
            "dpf",
            "outcome",
            "combat",
        ]
        outputs = {atom.atom_id: atom.output_handles for atom in group_result.atom_results}
        assert outputs["dpf"]["type"] == "DPFInput"
        assert outputs["outcome"]["type"] == "OutcomeVector"
        assert outputs["combat"]["ready"]
        run_result = next(item for item in result.run_results if item.run_id != "group")
        assert [atom.atom_id for atom in run_result.atom_results] == ["run-design"]

        summary = json.loads((tmp_path / "logs" / "execution_summary.json").read_text(encoding="utf-8"))
        assert summary["total_runs"] == 1
        assert summary["successful_runs"] == 1
        run_summary = next(item for item in summary["run_results"] if item["run_id"] != "group")
        assert run_summary["planned_steps"] == ["run-design"]
        assert run_summary["completed_steps"] == ["run-design"]
        assert run_summary["failed_error_code"] == ""
        assert run_summary["failed_error"] == ""
        assert (compiled / "participant_table_manifest.json").exists()

    def test_localization_projection_import_runs_as_group_atom(self, tmp_path):
        compiled = tmp_path / "compiled"
        compiled.mkdir()
        data_path = tmp_path / "sub-01.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        csv_path = tmp_path / "projection.csv"
        csv_path.write_text(
            (
                "group_id,projection_label,projection_kind,projected_mni_x,projected_mni_y,projected_mni_z,match_status\n"
                "G1,CH01,channel,1,2,3,matched\n"
            ),
            encoding="utf-8",
        )
        dag = {
            "atoms": [
                {
                    "atom_id": "loc",
                    "operation": "localization_projection_import",
                    "category": "data",
                    "execution_scope": "group",
                    "parameters": {"path": str(csv_path), "coordinate_set_id": "G1"},
                },
                {
                    "atom_id": "run-design",
                    "operation": "build_design_matrix",
                    "category": "analysis",
                    "execution_scope": "run",
                    "parameters": {"events": "task"},
                },
            ],
            "edges": [],
        }
        (compiled / "plan.json").write_text("{}", encoding="utf-8")
        (compiled / "execution_dag.json").write_text(json.dumps(dag), encoding="utf-8")
        (compiled / "data_manifest.json").write_text(
            json.dumps({"subject_session_runs": [{"subject": "01", "task": "test", "path": str(data_path)}]}),
            encoding="utf-8",
        )

        with patch(
            "fnirs_flow.adapters.backend_registry.get_registry",
            return_value=TestDagBranchIsolation._Registry(),
        ):
            result = ExecutionService().execute(
                ExecutionRequest(project_dir=str(tmp_path), outdir=str(tmp_path), attempt_id="attempt-localization")
            )

        group_result = next(item for item in result.run_results if item.run_id == "group")
        loc_result = group_result.atom_results[0]
        assert loc_result.status == "completed"
        assert loc_result.output_handles["type"] == "ProjectedMNIChannels"
        assert loc_result.output_handles["rows"] == 1
        assert loc_result.output_handles["not_nirsspm_equivalent"] is True
        assert (tmp_path / "derivatives" / "localization" / "G1_projected_mni_channels.csv").exists()
        manifest = json.loads((tmp_path / "logs" / "artifact_manifest.json").read_text(encoding="utf-8"))
        assert any(item["artifact_type"] == "ProjectedMNIChannels" for item in manifest["artifacts"])

    def test_nirs_spm_surface_projection_runs_as_group_atom(self, tmp_path):
        from fnirs_flow.adapters import nirsspm_projection

        class TinyProjector:
            reference_dir = "synthetic-nirsspm-reference"
            surface_reference_count = 1

            def project_head_to_cortex(self, points):
                return np.asarray(points, dtype=float)

        compiled = tmp_path / "compiled"
        compiled.mkdir()
        data_path = tmp_path / "sub-01.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        csv_path = tmp_path / "projection.csv"
        csv_path.write_text(
            (
                "group_id,projection_label,projection_kind,projected_head_x,projected_head_y,projected_head_z,"
                "projected_mni_x,projected_mni_y,projected_mni_z\n"
                "G1,CH01,channel,1,2,3,1,2,3\n"
            ),
            encoding="utf-8",
        )
        dag = {
            "atoms": [
                {
                    "atom_id": "nirsspm-proj",
                    "operation": "nirs_spm_surface_projection",
                    "category": "data",
                    "execution_scope": "group",
                    "parameters": {"path": str(csv_path), "coordinate_set_id": "G1"},
                },
                {
                    "atom_id": "run-design",
                    "operation": "build_design_matrix",
                    "category": "analysis",
                    "execution_scope": "run",
                    "parameters": {"events": "task"},
                },
            ],
            "edges": [],
        }
        (compiled / "plan.json").write_text("{}", encoding="utf-8")
        (compiled / "execution_dag.json").write_text(json.dumps(dag), encoding="utf-8")
        (compiled / "data_manifest.json").write_text(
            json.dumps({"subject_session_runs": [{"subject": "01", "task": "test", "path": str(data_path)}]}),
            encoding="utf-8",
        )

        with (
            patch("fnirs_flow.adapters.backend_registry.get_registry", return_value=TestDagBranchIsolation._Registry()),
            patch.object(
                nirsspm_projection.NirsspmSurfaceProjector,
                "from_reference_dir",
                classmethod(lambda cls, reference_dir: TinyProjector()),
            ),
        ):
            result = ExecutionService().execute(
                ExecutionRequest(project_dir=str(tmp_path), outdir=str(tmp_path), attempt_id="attempt-nirsspm")
            )

        group_result = next(item for item in result.run_results if item.run_id == "group")
        projection_result = group_result.atom_results[0]
        assert projection_result.status == "completed"
        assert projection_result.output_handles["type"] == "NirsspmSurfaceProjection"
        assert projection_result.output_handles["rows"] == 1
        assert projection_result.output_handles["validation"]["max_distance_mm"] == 0
        assert (tmp_path / "derivatives" / "localization" / "G1_nirsspm_surface_projection.csv").exists()
        manifest = json.loads((tmp_path / "logs" / "artifact_manifest.json").read_text(encoding="utf-8"))
        assert any(item["artifact_type"] == "NirsspmSurfaceProjection" for item in manifest["artifacts"])


# ============================================================================
# Group summary tests
# ============================================================================


class TestAtomDerivativeLocations:
    class _Adapter:
        versions = {}

        def __init__(self, outdir):
            from fnirs_flow.execution.artifacts import ArtifactStore

            self.outdir = outdir
            self.artifacts = ArtifactStore()

        def _write(self, step_id, artifact_type, filename):
            from fnirs_flow.execution.artifacts import ArtifactRecord

            path = self.outdir / filename
            path.write_text(step_id, encoding="utf-8")
            self.artifacts.register(
                ArtifactRecord(
                    artifact_id=f"{step_id}-{filename}",
                    step_id=step_id,
                    artifact_type=artifact_type,
                    path=str(path),
                )
            )
            return object()

        def read_run(self, _path):
            return self._write("read_run", "ImportSummary", "import.json")

        def to_optical_density(self, _raw):
            return self._write("optical_density", "ODSummary", "od.json")

    class _Registry:
        def __init__(self):
            self.adapter = None

        def create(self, _backend_id, **kwargs):
            if self.adapter is None:
                self.adapter = TestAtomDerivativeLocations._Adapter(kwargs["outdir"])
            return self.adapter

    def test_files_are_attached_to_the_atom_that_created_them(self, tmp_path):
        from fnirs_flow.execution.engine import RunContext

        data_path = tmp_path / "run.snirf"
        data_path.write_text("placeholder", encoding="utf-8")
        dag = {
            "atoms": [
                {
                    "atom_id": "reader",
                    "operation": "read_run",
                    "category": "data",
                    "parameters": {},
                },
                {
                    "atom_id": "od",
                    "operation": "optical_density",
                    "category": "preprocessing",
                    "parameters": {},
                },
            ],
            "execution_layers": [["reader"], ["od"]],
            "edges": [{"source": "reader", "target": "od"}],
        }

        with patch("fnirs_flow.adapters.backend_registry.get_registry", return_value=self._Registry()):
            result = ExecutionService()._execute_run(
                RunContext(run_id="run-1", data_path=str(data_path)),
                {},
                dag,
                tmp_path,
            )

        atoms = {atom.atom_id: atom for atom in result.atom_results}
        assert [(item.atom_id, item.status) for item in result.atom_results] == [
            ("reader", "completed"),
            ("od", "completed"),
        ]
        assert atoms["reader"].artifacts[0]["atom_id"] == "reader"
        assert atoms["reader"].artifacts[0]["relative_path"] == "run-1/import.json"
        assert atoms["reader"].artifacts[0]["path"] == "project://outputs/run-1/import.json"
        assert Path(atoms["reader"].artifacts[0]["resolved_path"]).name == "import.json"
        assert atoms["reader"].artifacts[0]["exists"]
        assert atoms["od"].artifacts[0]["atom_id"] == "od"
        assert atoms["od"].artifacts[0]["relative_path"] == "run-1/od.json"
        assert {artifact["atom_id"] for artifact in result.artifacts} == {"reader", "od"}

    def test_external_data_uri_is_resolved_from_manifest_binding(self, tmp_path):
        compiled = tmp_path / "compiled"
        data_root = tmp_path / "data"
        run_path = data_root / "sub-01" / "run.snirf"
        events_path = data_root / "sub-01" / "events.tsv"
        compiled.mkdir()
        run_path.parent.mkdir(parents=True)
        run_path.write_text("snirf", encoding="utf-8")
        events_path.write_text("onset\n", encoding="utf-8")
        (compiled / "data_manifest.json").write_text(
            json.dumps(
                {
                    "dataset_id": "dataset",
                    "local_root": str(data_root),
                    "subject_session_runs": [
                        {
                            "subject": "01",
                            "relative_path": "sub-01/run.snirf",
                            "path": "external-data://dataset/sub-01/run.snirf",
                            "events_path": "external-data://dataset/sub-01/events.tsv",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        runs = ExecutionService()._resolve_runs(
            compiled,
            ExecutionRequest(project_dir=str(tmp_path)),
        )

        assert runs[0].data_path == str(run_path)
        assert runs[0].events_path == str(events_path)


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
            assert rows[0]["excluded_subjects"] == "sub-03"

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

    def test_generate_channel_group_summary_without_roi(self, tmp_path):
        from fnirs_flow.execution.service import RunExecutionResult

        result = ExecutionService()._generate_group_summary(
            [
                RunExecutionResult(
                    run_id="sub-01_task-test",
                    status="completed",
                    channel_results=[{"channel_idx": 1, "task_beta": 2.0}],
                ),
                RunExecutionResult(
                    run_id="sub-02_task-test",
                    status="completed",
                    channel_results=[{"channel_idx": 1, "task_beta": 4.0}],
                ),
            ],
            tmp_path,
        )

        assert result == tmp_path / "derivatives" / "group" / "channel_group_summary.csv"
        with result.open(encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        assert rows[0]["mean_beta"] == "3.0"

    def test_channel_group_summary_does_not_count_runs_as_subjects(self, tmp_path):
        from fnirs_flow.execution.service import RunExecutionResult

        result = ExecutionService()._generate_group_summary(
            [
                RunExecutionResult(
                    run_id="sub-01_task-test_run-01",
                    status="completed",
                    channel_results=[{"channel_idx": 1, "task_beta": 1.0}],
                ),
                RunExecutionResult(
                    run_id="sub-01_task-test_run-02",
                    status="completed",
                    channel_results=[{"channel_idx": 1, "task_beta": 3.0}],
                ),
                RunExecutionResult(
                    run_id="sub-02_task-test_run-01",
                    status="completed",
                    channel_results=[{"channel_idx": 1, "task_beta": 6.0}],
                ),
            ],
            tmp_path,
        )

        with result.open(encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        assert rows[0]["n_subjects"] == "2"
        assert rows[0]["mean_beta"] == "4.0"

    def test_group_summary_keeps_dual_roi_branches_separate(self, tmp_path):
        from fnirs_flow.execution.service import RunExecutionResult

        runs = []
        for subject, offset in (("sub-01", 0.0), ("sub-02", 1.0)):
            runs.append(
                RunExecutionResult(
                    run_id=subject,
                    status="completed",
                    roi_results=[
                        {
                            "source_atom_id": "roi-a",
                            "roi_name": "motor",
                            "task_beta_mean": 1.0 + offset,
                            "n_channels": 2,
                        },
                        {
                            "source_atom_id": "roi-b",
                            "roi_name": "motor",
                            "task_beta_mean": 10.0 + offset,
                            "n_channels": 2,
                        },
                    ],
                )
            )

        result = ExecutionService()._generate_group_summary(runs, tmp_path)
        assert result is not None
        with result.open(encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        assert [(row["source_atom_id"], row["n_subjects"]) for row in rows] == [
            ("roi-a", "2"),
            ("roi-b", "2"),
        ]

    def test_group_summary_honors_participant_metadata_exclusions(self, tmp_path):
        from fnirs_flow.data.participant_tables import read_participant_table, write_participant_table_artifacts
        from fnirs_flow.execution.service import RunExecutionResult

        table_path = tmp_path / "participants.tsv"
        table_path.write_text(
            (
                "participant_id\tinclude\tgroup\n"
                "sub-01\t1\tcontrol\n"
                "sub-02\t1\tpatient\n"
                "sub-03\t0\tpatient\n"
                "sub-04\t1\tcontrol\n"
                "sub-05\t1\tpatient\n"
            ),
            encoding="utf-8",
        )
        compiled = tmp_path / "compiled"
        compiled.mkdir()
        table = read_participant_table(table_path)
        write_participant_table_artifacts(table, compiled)

        result = ExecutionService()._generate_group_summary(
            [
                RunExecutionResult(
                    run_id="sub-01_task-test",
                    status="completed",
                    roi_results=[{"roi_name": "motor", "task_beta_mean": 1.0}],
                ),
                RunExecutionResult(
                    run_id="sub-02_task-test",
                    status="completed",
                    roi_results=[{"roi_name": "motor", "task_beta_mean": 3.0}],
                ),
                RunExecutionResult(
                    run_id="sub-04_task-test",
                    status="completed",
                    roi_results=[{"roi_name": "motor", "task_beta_mean": 1.5}],
                ),
                RunExecutionResult(
                    run_id="sub-05_task-test",
                    status="completed",
                    roi_results=[{"roi_name": "motor", "task_beta_mean": 3.5}],
                ),
                RunExecutionResult(
                    run_id="sub-03_task-test",
                    status="completed",
                    roi_results=[{"roi_name": "motor", "task_beta_mean": 9.0}],
                ),
            ],
            tmp_path,
        )

        assert result is not None
        with result.open(encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        assert rows[0]["n_subjects"] == "4"
        assert rows[0]["excluded_subjects"] == "sub-03"
        assert (tmp_path / "derivatives" / "group" / "analysis_table.csv").exists()
        assert (tmp_path / "derivatives" / "group" / "group_design_matrix.csv").exists()
        assert (tmp_path / "derivatives" / "group" / "group_glm_results.csv").exists()
        assert (tmp_path / "derivatives" / "group" / "group_glm_results.json").exists()
        assert (tmp_path / "derivatives" / "group" / "contrast_matrix.csv").exists()
        assert (tmp_path / "derivatives" / "group" / "contrast_results.csv").exists()
        assert (tmp_path / "derivatives" / "group" / "contrast_results.json").exists()
        assert (tmp_path / "derivatives" / "group" / "contrast_effects.svg").exists()
        assert (tmp_path / "derivatives" / "group" / "effect_sizes.csv").exists()
        assert (tmp_path / "derivatives" / "group" / "multiple_comparison_results.csv").exists()
        artifacts = ExecutionService()._collect_group_result_artifacts(tmp_path)
        artifact_types = {artifact["type"] for artifact in artifacts}
        assert "ContrastResultsJson" in artifact_types
        assert "ContrastEffectFigure" in artifact_types

    def test_group_config_merges_contrast_atom_parameters(self):
        config = ExecutionService._extract_group_config(
            {},
            {
                "atoms": [
                    {
                        "atom_id": "design",
                        "operation": "group_design_matrix",
                        "parameters": {"design_type": "two_sample_t", "group_column": "group"},
                    },
                    {
                        "atom_id": "contrast",
                        "operation": "group_contrast",
                        "parameters": {
                            "contrast_name": "patient > control",
                            "contrast_type": "T",
                            "contrast_expression": "group[patient] - group[control]",
                        },
                    },
                ]
            },
        )

        assert config["design_type"] == "two_sample_t"
        assert config["contrasts"] == [
            {
                "name": "patient > control",
                "type": "T",
                "expression": "group[patient] - group[control]",
                "weights": None,
                "weight_matrix": None,
                "terms": None,
            }
        ]

    def test_group_summary_writes_advanced_design_inference_artifacts(self, tmp_path):
        from fnirs_flow.data.participant_tables import read_participant_table, write_participant_table_artifacts
        from fnirs_flow.execution.service import RunExecutionResult

        table_path = tmp_path / "participants.tsv"
        table_path.write_text(
            (
                "participant_id\tinclude\tgroup\tsex\tsite\n"
                "sub-01\t1\tcontrol\tF\tA\n"
                "sub-02\t1\tcontrol\tM\tA\n"
                "sub-03\t1\tpatient\tF\tB\n"
                "sub-04\t1\tpatient\tM\tB\n"
                "sub-05\t1\tcontrol\tF\tB\n"
                "sub-06\t1\tpatient\tM\tA\n"
            ),
            encoding="utf-8",
        )
        compiled = tmp_path / "compiled"
        compiled.mkdir()
        write_participant_table_artifacts(read_participant_table(table_path), compiled)

        runs = [
            RunExecutionResult(
                run_id=f"sub-0{index}_task-test",
                status="completed",
                roi_results=[{"roi_name": "motor", "task_beta_mean": beta}],
            )
            for index, beta in enumerate([1.0, 1.1, 2.0, 2.2, 0.9, 2.1], start=1)
        ]
        result = ExecutionService()._generate_group_summary(
            runs,
            tmp_path,
            group_config={
                "design_type": "full_factorial",
                "factors": ["group", "sex"],
                "covariance": "hc0",
                "permutation_count": 5,
                "cluster_inference": True,
                "cluster_alpha": 1.0,
                "random_seed": 11,
                "contrasts": [{"name": "group main", "type": "F", "terms": ["group"]}],
                "sensitivity_branches": [{"name": "site A only", "filter": {"site": "A"}}],
            },
        )

        assert result is not None
        group_dir = tmp_path / "derivatives" / "group"
        spec = json.loads((group_dir / "group_design_spec.json").read_text(encoding="utf-8"))
        assert spec["design_type"] == "full_factorial"
        assert spec["factors"] == ["group", "sex"]
        assert spec["covariance"] == "hc0"
        assert spec["permutation_count"] == 5
        assert spec["cluster_inference"]
        with (group_dir / "multiple_comparison_results.csv").open(encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        assert rows[0]["covariance"] == "hc0"
        assert rows[0]["permutation_count"] == "5"
        assert (group_dir / "sensitivity_analysis_results.csv").exists()
        assert (group_dir / "cluster_inference_results.csv").exists()
