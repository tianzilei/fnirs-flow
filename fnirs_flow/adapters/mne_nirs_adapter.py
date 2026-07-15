"""MNE-NIRS adapter: wraps MNE-NIRS functions for fnirs-flow execution.

Each adapter step emits a structured ArtifactRecord with checksum,
software versions, parameters, and subject/session/run tracking.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from fnirs_flow.adapters.mne_nirs_io import capture_versions, read_raw_snirf
from fnirs_flow.adapters.mne_nirs_steps import (
    beer_lambert_law,
    block_averaging,
    build_design_matrix,
    cbsi_motion_correction,
    channel_output,
    compute_coefficient_of_variation,
    compute_snr,
    detect_bad_channels,
    estimate_contrast,
    filter_raw,
    first_level_glm,
    ica_motion_correction,
    notch_filter,
    optical_density,
    pca_motion_correction,
    roi_output,
    scalp_coupling_index,
    short_channel_regression,
    short_channels,
    source_detector_distances,
    spline_motion_correction,
    temporal_derivative_distribution_repair,
    wavelet_motion_correction,
)
from fnirs_flow.execution.artifacts import ArtifactRecord, ArtifactStore
from fnirs_flow.execution.provenance import ProvenanceRecord


def _copy_raw_with_data(raw: Any, new_data: np.ndarray) -> Any:
    """Create a new MNE Raw object with replaced data, avoiding private attribute mutation."""
    try:
        import mne

        info = raw.info.copy()
        new_raw = mne.io.RawArray(new_data, info, first_samp=raw.first_samp, verbose=False)
        return new_raw
    except ImportError:
        raise ImportError("MNE-Python is required. Install with: pip install fnirs-flow[mne]") from None


def _compute_raw_hash(raw: Any) -> str:
    """Compute a content hash of an MNE Raw object."""
    try:
        ch_names = str(raw.ch_names).encode()
        n_channels = str(len(raw.ch_names)).encode()
        n_times = str(len(raw.times)).encode()

        data = raw.get_data()
        sample = np.concatenate([data[:, :100], data[:, -100:]]) if data.shape[1] > 200 else data
        data_bytes = sample.tobytes()

        combined = ch_names + n_channels + n_times + data_bytes
        return hashlib.sha256(combined).hexdigest()[:16]
    except (AttributeError, ValueError, TypeError):
        return hashlib.sha256(str(raw.ch_names).encode()).hexdigest()[:16]


class MneNirsAdapter:
    """Adapter for MNE-NIRS backend execution.

    Each step:
      1. Executes the MNE-NIRS function
      2. Records provenance (parameters, hashes)
      3. Emits a structured ArtifactRecord
      4. Writes real artifact files (JSON/TSV) to outdir
    """

    def __init__(
        self,
        subject: str = "",
        session: str = "",
        task: str = "",
        run: str = "",
        outdir: str | Path | None = None,
    ) -> None:
        self._versions = capture_versions()
        self._provenance = ProvenanceRecord()
        self._artifacts = ArtifactStore()
        self._subject = subject
        self._session = session
        self._task = task
        self._run = run
        self._outdir = Path(outdir) if outdir else None
        if self._outdir:
            self._outdir.mkdir(parents=True, exist_ok=True)

    def _entity_prefix(self) -> str:
        """Return a collision-safe BIDS-like prefix for generated artifacts."""
        prefix = f"sub-{self._subject}" if self._subject else "sub-unknown"
        if self._session:
            prefix += f"_ses-{self._session}"
        if self._task:
            prefix += f"_task-{self._task}"
        if self._run:
            prefix += f"_run-{self._run}"
        return prefix

    def _entity_id(self) -> str:
        return "_".join(value for value in (self._subject, self._session, self._task, self._run) if value)

    @property
    def versions(self) -> dict[str, str]:
        return self._versions

    @property
    def provenance(self) -> ProvenanceRecord:
        return self._provenance

    @property
    def artifacts(self) -> ArtifactStore:
        return self._artifacts

    def _emit_artifact(
        self,
        artifact_type: str,
        raw: Any,
        step_id: str,
        parameters: dict[str, Any],
    ) -> ArtifactRecord:
        """Emit a structured artifact record for a step."""
        checksum = _compute_raw_hash(raw) if raw is not None else ""
        artifact_id = f"{step_id}-{self._entity_id()}-{checksum[:8]}"
        record = ArtifactRecord(
            artifact_id=artifact_id,
            subject=self._subject,
            session=self._session,
            task=self._task,
            run=self._run,
            step_id=step_id,
            artifact_type=artifact_type,
            sha256=checksum,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._artifacts.register(record)
        return record

    def _write_artifact_file(
        self,
        step_id: str,
        suffix: str,
        data: dict[str, Any],
        fmt: str = "json",
    ) -> Path | None:
        """Write an artifact file to outdir. Returns path if written."""
        if not self._outdir:
            return None
        prefix = self._entity_prefix()
        filename = f"{prefix}_desc-{suffix}.{fmt}"
        path = self._outdir / filename
        import json as _json

        path.write_text(_json.dumps(data, indent=2, default=str), encoding="utf-8")
        resolved_path = path.resolve()
        self._artifacts.register(
            ArtifactRecord(
                artifact_id=f"{step_id}-{suffix}-{self._entity_id()}",
                subject=self._subject,
                session=self._session,
                task=self._task,
                run=self._run,
                step_id=step_id,
                artifact_type="".join(part.title() for part in suffix.split("_")),
                path=str(resolved_path),
                sha256=hashlib.sha256(resolved_path.read_bytes()).hexdigest(),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        return path

    def _write_qc_tsv(self, qc: dict[str, Any]) -> Path | None:
        """Write QC channel-level results as TSV."""
        if not self._outdir:
            return None
        import csv

        prefix = self._entity_prefix()
        filename = f"{prefix}_desc-qc_channels.tsv"
        path = self._outdir / filename
        bad_mask = qc.get("bad_channel_mask", [])
        sci_vals = qc.get("sci_values", [])
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(["channel_idx", "sci", "is_bad"])
            for i in range(qc.get("n_channels", 0)):
                sci = sci_vals[i] if i < len(sci_vals) else ""
                is_bad = bad_mask[i] if i < len(bad_mask) else ""
                writer.writerow([i, sci, is_bad])
        resolved_path = path.resolve()
        self._artifacts.register(
            ArtifactRecord(
                artifact_id=f"compute_qc-qc_channels-{self._entity_id()}",
                subject=self._subject,
                session=self._session,
                task=self._task,
                run=self._run,
                step_id="compute_qc",
                artifact_type="QCChannels",
                path=str(resolved_path),
                sha256=hashlib.sha256(resolved_path.read_bytes()).hexdigest(),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        return path

    def read_run(self, filepath: str | Path) -> Any:
        """Read a SNIRF run file."""
        raw = read_raw_snirf(filepath)
        source_name = Path(filepath).name
        self._provenance.log(
            step_id="read_run",
            parameters={"source_file": source_name},
        )
        self._emit_artifact("RawIntensity", raw, "read_run", {"source_file": source_name})
        # Write import summary
        summary = {
            "step": "read_run",
            "source_file": source_name,
            "n_channels": len(raw.ch_names),
            "n_times": len(raw.times),
            "sfreq": raw.info.get("sfreq", 0),
            "ch_names": raw.ch_names[:20],
            "duration_s": float(raw.times[-1]) if len(raw.times) > 0 else 0,
        }
        self._write_artifact_file("read_run", "import_summary", summary)
        return raw

    def to_optical_density(self, raw: Any) -> Any:
        """Convert intensity to optical density."""
        input_hash = _compute_raw_hash(raw)
        result = optical_density(raw)
        output_hash = _compute_raw_hash(result)
        self._provenance.log(
            step_id="optical_density",
            parameters={},
            input_hashes={"raw": input_hash},
            output_hashes={"od": output_hash},
        )
        self._emit_artifact("OpticalDensity", result, "optical_density", {})
        # Write OD summary
        data = result.get_data()
        summary = {
            "step": "optical_density",
            "n_channels": data.shape[0],
            "n_times": data.shape[1],
            "od_mean": float(np.mean(data)) if data.size > 0 else 0,
            "od_std": float(np.std(data)) if data.size > 0 else 0,
            "input_hash": input_hash,
            "output_hash": output_hash,
        }
        self._write_artifact_file("optical_density", "od_summary", summary)
        return result

    def compute_qc(self, raw: Any, sci_threshold: float = 0.8) -> dict[str, Any]:
        """Compute QC metrics."""
        sci_values = scalp_coupling_index(raw)
        sd_dists = source_detector_distances(raw.info)
        short_chs = short_channels(raw.info)

        qc = {
            "sci_mean": float(sci_values.mean()) if len(sci_values) > 0 else 0.0,
            "sci_min": float(sci_values.min()) if len(sci_values) > 0 else 0.0,
            "n_channels": len(sci_values),
            "n_short_channels": int(short_chs.sum()) if hasattr(short_chs, "sum") else 0,
            "sd_distance_mean": float(sd_dists.mean()) if len(sd_dists) > 0 else 0.0,
            "sci_values": sci_values.tolist(),
            "sci_threshold": sci_threshold,
        }

        self._provenance.log(
            step_id="compute_qc",
            parameters={"sci_threshold": sci_threshold},
        )
        # Emit QC report artifact (no raw object, use None)
        artifact_id = f"qc-{self._entity_id()}"
        self._artifacts.register(
            ArtifactRecord(
                artifact_id=artifact_id,
                subject=self._subject,
                session=self._session,
                task=self._task,
                run=self._run,
                step_id="compute_qc",
                artifact_type="QCReport",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        # Write QC summary JSON
        summary = {k: v for k, v in qc.items() if k != "sci_values"}
        self._write_artifact_file("compute_qc", "qc_summary", summary)
        # Write QC channels TSV
        self._write_qc_tsv(qc)
        return qc

    def apply_motion_correction(
        self,
        raw: Any,
        method: str = "tddr",
        **kwargs: Any,
    ) -> Any:
        """Apply motion correction."""
        input_hash = _compute_raw_hash(raw)
        data = raw.get_data()

        if method == "tddr":
            result = temporal_derivative_distribution_repair(raw)
        elif method == "wavelet":
            corrected = wavelet_motion_correction(
                data,
                wavelet_level=kwargs.get("wavelet_level", 5),
                threshold_type=kwargs.get("threshold_type", "soft"),
            )
            result = _copy_raw_with_data(raw, corrected)
        elif method == "spline":
            corrected = spline_motion_correction(
                data,
                spline_segments=kwargs.get("spline_segments", 3),
                threshold=kwargs.get("threshold", 1.0),
            )
            result = _copy_raw_with_data(raw, corrected)
        elif method == "ica":
            corrected, components = ica_motion_correction(
                data,
                n_components=kwargs.get("n_components"),
                threshold=kwargs.get("threshold", 3.0),
            )
            result = _copy_raw_with_data(raw, corrected)
        elif method == "pca":
            corrected = pca_motion_correction(
                data,
                n_components=kwargs.get("n_components", 0.95),
                threshold=kwargs.get("threshold", 3.0),
            )
            result = _copy_raw_with_data(raw, corrected)
        elif method == "cbsi":
            raise ValueError("CBSI requires separate HbO/HbR signals. Use apply_cbsi_correction() instead.")
        else:
            raise ValueError(
                f"Unknown motion correction method: {method}. Supported: tddr, wavelet, spline, ica, pca, cbsi"
            )

        output_hash = _compute_raw_hash(result)
        self._provenance.log(
            step_id="motion_correction",
            parameters={"method": method, **kwargs},
            input_hashes={"raw": input_hash},
            output_hashes={"corrected": output_hash},
        )
        self._emit_artifact(
            "OpticalDensity" if method in ("tddr",) else "RawIntensity",
            result,
            "motion_correction",
            {"method": method, **kwargs},
        )
        # Write motion correction report
        report = {
            "step": "motion_correction",
            "method": method,
            "parameters": kwargs,
            "input_hash": input_hash,
            "output_hash": output_hash,
        }
        self._write_artifact_file("motion_correction", "motion_report", report)
        return result

    def apply_cbsi_correction(self, hbo: Any, hbr: Any) -> tuple[Any, Any]:
        """Apply CBSI motion correction to HbO and HbR signals."""
        input_hash_hbo = _compute_raw_hash(hbo)
        input_hash_hbr = _compute_raw_hash(hbr)

        hbo_data = hbo.get_data()
        hbr_data = hbr.get_data()
        corrected_hbo, corrected_hbr = cbsi_motion_correction(hbo_data, hbr_data)

        hbo = _copy_raw_with_data(hbo, corrected_hbo)
        hbr = _copy_raw_with_data(hbr, corrected_hbr)

        self._provenance.log(
            step_id="cbsi_correction",
            parameters={},
            input_hashes={"hbo": input_hash_hbo, "hbr": input_hash_hbr},
            output_hashes={
                "hbo_corrected": _compute_raw_hash(hbo),
                "hbr_corrected": _compute_raw_hash(hbr),
            },
        )
        self._emit_artifact("HaemoglobinData", hbo, "cbsi_correction", {})
        return hbo, hbr

    def apply_filter(
        self,
        raw: Any,
        l_freq: float = 0.01,
        h_freq: float = 0.2,
        method: str = "bandpass",
        **kwargs: Any,
    ) -> Any:
        """Apply filter to raw data."""
        input_hash = _compute_raw_hash(raw)

        if method == "bandpass":
            result = filter_raw(raw, l_freq=l_freq, h_freq=h_freq, method="iir", **kwargs)
        elif method == "notch":
            freqs = kwargs.get("freqs", [50.0, 100.0])
            result = notch_filter(raw, freqs=freqs, **kwargs)
        elif method == "lowpass":
            result = filter_raw(raw, l_freq=None, h_freq=h_freq, **kwargs)
        else:
            raise ValueError(f"Unknown filter method: {method}. Supported: bandpass, notch, lowpass")

        output_hash = _compute_raw_hash(result)
        self._provenance.log(
            step_id="filtering",
            parameters={"l_freq": l_freq, "h_freq": h_freq, "method": method},
            input_hashes={"raw": input_hash},
            output_hashes={"filtered": output_hash},
        )
        self._emit_artifact("OpticalDensity", result, "filtering", {"method": method})
        # Write filter summary
        summary = {
            "step": "filtering",
            "method": method,
            "l_freq": l_freq,
            "h_freq": h_freq,
            "input_hash": input_hash,
            "output_hash": output_hash,
        }
        self._write_artifact_file("filtering", "filter_summary", summary)
        return result

    def compute_advanced_qc(
        self,
        raw: Any,
        sci_threshold: float = 0.8,
        cv_threshold: float = 0.15,
        snr_threshold: float = 2.0,
    ) -> dict[str, Any]:
        """Compute comprehensive QC metrics."""
        data = raw.get_data()

        sci_values = scalp_coupling_index(raw)
        cv_values = compute_coefficient_of_variation(data)
        snr_values = compute_snr(data, fs=raw.info["sfreq"])
        sd_dists = source_detector_distances(raw.info)
        short_chs = short_channels(raw.info)

        bad_channels = detect_bad_channels(
            data,
            sci_values=sci_values,
            cv_threshold=cv_threshold,
            snr_threshold=snr_threshold,
            sci_threshold=sci_threshold,
        )

        qc = {
            "sci_mean": float(np.mean(sci_values)) if len(sci_values) > 0 else 0.0,
            "sci_min": float(np.min(sci_values)) if len(sci_values) > 0 else 0.0,
            "sci_pass_rate": (float(np.mean(sci_values >= sci_threshold)) if len(sci_values) > 0 else 0.0),
            "cv_mean": float(np.mean(cv_values)) if len(cv_values) > 0 else 0.0,
            "cv_max": float(np.max(cv_values)) if len(cv_values) > 0 else 0.0,
            "snr_mean": float(np.mean(snr_values)) if len(snr_values) > 0 else 0.0,
            "snr_min": float(np.min(snr_values)) if len(snr_values) > 0 else 0.0,
            "n_channels": len(sci_values),
            "n_short_channels": int(short_chs.sum()) if hasattr(short_chs, "sum") else 0,
            "sd_distance_mean": float(np.mean(sd_dists)) if len(sd_dists) > 0 else 0.0,
            "n_bad_channels": bad_channels["n_bad"],
            "bad_channel_percentage": bad_channels["bad_percentage"],
            "bad_channel_mask": bad_channels["bad_mask"].tolist(),
            "thresholds": {
                "sci": sci_threshold,
                "cv": cv_threshold,
                "snr": snr_threshold,
            },
        }

        self._provenance.log(
            step_id="compute_advanced_qc",
            parameters={
                "sci_threshold": sci_threshold,
                "cv_threshold": cv_threshold,
                "snr_threshold": snr_threshold,
            },
        )
        self._emit_artifact(
            "QCReport",
            raw,
            "compute_advanced_qc",
            {
                "sci_threshold": sci_threshold,
                "cv_threshold": cv_threshold,
                "snr_threshold": snr_threshold,
            },
        )
        return qc

    def apply_short_channel_regression(
        self,
        raw: Any,
        short_channel_threshold: float = 0.01,
        method: str = "linear",
    ) -> Any:
        """Apply short-channel regression to remove systemic physiological noise."""
        input_hash = _compute_raw_hash(raw)

        data = raw.get_data()
        short_ch_mask = short_channels(raw.info, threshold=short_channel_threshold)

        if not short_ch_mask.any():
            self._provenance.log(
                step_id="short_channel_regression",
                parameters={"method": method, "n_short_channels": 0},
                input_hashes={"raw": input_hash},
                output_hashes={"cleaned": input_hash},
            )
            return raw

        cleaned_data = short_channel_regression(data, short_ch_mask, method=method)
        raw = _copy_raw_with_data(raw, cleaned_data)

        output_hash = _compute_raw_hash(raw)
        self._provenance.log(
            step_id="short_channel_regression",
            parameters={
                "method": method,
                "n_short_channels": int(short_ch_mask.sum()),
            },
            input_hashes={"raw": input_hash},
            output_hashes={"cleaned": output_hash},
        )
        self._emit_artifact("HaemoglobinData", raw, "short_channel_regression", {"method": method})
        return raw

    def apply_block_averaging(
        self,
        raw: Any,
        events: np.ndarray,
        baseline_window: tuple[float, float] = (-5.0, 0.0),
        response_window: tuple[float, float] = (0.0, 20.0),
        baseline_correction: str = "mean",
    ) -> dict[str, Any]:
        """Apply block/trial averaging."""
        data = raw.get_data()
        sfreq = raw.info["sfreq"]

        result = block_averaging(
            data,
            events,
            sfreq=sfreq,
            baseline_window=baseline_window,
            response_window=response_window,
            baseline_correction=baseline_correction,
        )

        self._provenance.log(
            step_id="block_averaging",
            parameters={
                "baseline_window": list(baseline_window),
                "response_window": list(response_window),
                "baseline_correction": baseline_correction,
                "n_trials": result["n_trials"],
            },
        )
        artifact_id = f"block-avg-{self._entity_id()}"
        self._artifacts.register(
            ArtifactRecord(
                artifact_id=artifact_id,
                subject=self._subject,
                session=self._session,
                task=self._task,
                run=self._run,
                step_id="block_averaging",
                artifact_type="ChannelSummary",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        return result

    def to_haemoglobin(self, raw: Any, ppf: float = 6.0) -> Any:
        """Convert OD to haemoglobin concentration."""
        input_hash = _compute_raw_hash(raw)
        result = beer_lambert_law(raw, ppf=ppf)
        output_hash = _compute_raw_hash(result)
        self._provenance.log(
            step_id="beer_lambert_law",
            parameters={"ppf": ppf},
            input_hashes={"od": input_hash},
            output_hashes={"haemoglobin": output_hash},
        )
        self._emit_artifact("HaemoglobinData", result, "beer_lambert_law", {"ppf": ppf})
        # Write HB summary
        data = result.get_data()
        ch_names = result.ch_names if hasattr(result, "ch_names") else []
        summary = {
            "step": "beer_lambert_law",
            "ppf": ppf,
            "n_channels": data.shape[0],
            "n_times": data.shape[1],
            "ch_names": ch_names[:20],
            "hbo_mean": float(np.mean(data[::2])) if data.size > 0 else 0,
            "hbr_mean": float(np.mean(data[1::2])) if data.size > 1 else 0,
            "input_hash": input_hash,
            "output_hash": output_hash,
        }
        self._write_artifact_file("beer_lambert_law", "hb_summary", summary)
        return result

    def export_channel_results(self, results: dict[str, Any], outdir: Path) -> Path:
        """Export channel-level results to CSV."""
        import csv

        outdir.mkdir(parents=True, exist_ok=True)
        path = outdir / f"{self._entity_prefix()}_desc-channel_results.csv"

        # Handle both formats: channel_output dict or raw dict
        if "channels" in results:
            channel_list = results["channels"]
            keys = [k for k in channel_list[0].keys() if k != "channel_idx"] if channel_list else []
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["channel_idx"] + keys)
                for ch in channel_list:
                    writer.writerow([ch.get("channel_idx", "")] + [ch.get(k, "") for k in keys])
        else:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["channel", "hbo_beta", "hbr_beta", "hbo_t", "hbr_t", "p_value"])
                for ch_name, vals in results.items():
                    if isinstance(vals, dict):
                        writer.writerow(
                            [
                                ch_name,
                                vals.get("hbo_beta", ""),
                                vals.get("hbr_beta", ""),
                                vals.get("hbo_t", ""),
                                vals.get("hbr_t", ""),
                                vals.get("p_value", ""),
                            ]
                        )

        self._artifacts.register(
            ArtifactRecord(
                artifact_id=f"channel-results-{path.stem}",
                artifact_type="ChannelSummary",
                path=str(path),
                step_id="export_channel_results",
                subject=self._subject,
                session=self._session,
                task=self._task,
                run=self._run,
            )
        )
        return path

    def build_design_matrix(
        self,
        raw: Any,
        events: np.ndarray,
        event_id: dict[str, int],
        hrf_model: str = "glover",
        drift_order: int = 1,
        high_pass: float = 0.01,
    ) -> dict[str, Any]:
        """Build a GLM design matrix from events."""
        sfreq = raw.info.get("sfreq", 10.0)
        result = build_design_matrix(
            raw,
            events,
            event_id,
            sfreq,
            hrf_model=hrf_model,
            drift_order=drift_order,
            high_pass=high_pass,
        )
        self._provenance.log(
            step_id="build_design_matrix",
            parameters={
                "hrf_model": hrf_model,
                "drift_order": drift_order,
                "high_pass": high_pass,
                "n_conditions": result.get("n_conditions", 0),
            },
        )
        self._emit_artifact(
            "DesignMatrix",
            raw,
            "build_design_matrix",
            {
                "hrf_model": hrf_model,
            },
        )
        # Write design matrix summary
        summary = {
            "step": "build_design_matrix",
            "n_samples": result.get("n_samples", 0),
            "n_conditions": result.get("n_conditions", 0),
            "conditions": result.get("conditions", []),
            "hrf_model": hrf_model,
        }
        self._write_artifact_file("build_design_matrix", "design_matrix_summary", summary)
        return result

    def fit_first_level_glm(
        self,
        raw: Any,
        design_matrix: dict[str, Any],
        hrf_model: str = "glover",
        noise_model: str = "ar1",
    ) -> dict[str, Any]:
        """Fit first-level GLM."""
        result = first_level_glm(
            raw,
            design_matrix,
            hrf_model=hrf_model,
            noise_model=noise_model,
        )
        self._provenance.log(
            step_id="first_level_glm",
            parameters={"hrf_model": hrf_model, "noise_model": noise_model},
        )
        self._emit_artifact(
            "GLMResult",
            raw,
            "first_level_glm",
            {
                "hrf_model": hrf_model,
            },
        )
        # Write GLM summary
        summary = {
            "step": "first_level_glm",
            "n_channels": result.get("n_channels", 0),
            "n_conditions": result.get("n_conditions", 0),
            "df": result.get("df", 0),
        }
        self._write_artifact_file("first_level_glm", "glm_summary", summary)
        return result

    def estimate_contrast(
        self,
        glm_result: dict[str, Any],
        contrasts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Estimate linear contrasts."""
        result = estimate_contrast(glm_result, contrasts)
        self._provenance.log(
            step_id="estimate_contrast",
            parameters={"n_contrasts": len(contrasts)},
        )
        self._emit_artifact(
            "ContrastResult",
            None,
            "estimate_contrast",
            {
                "n_contrasts": len(contrasts),
            },
        )
        return result

    def channel_output(self, contrast_result: dict[str, Any]) -> dict[str, Any]:
        """Export channel-level results."""
        result = channel_output(contrast_result)
        self._provenance.log(
            step_id="channel_output",
            parameters={"n_channels": result.get("n_channels", 0)},
        )
        artifact_id = f"channel-output-{self._entity_id()}"
        self._artifacts.register(
            ArtifactRecord(
                artifact_id=artifact_id,
                subject=self._subject,
                session=self._session,
                task=self._task,
                run=self._run,
                step_id="channel_output",
                artifact_type="ChannelSummary",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        return result

    def roi_output(
        self,
        channel_results: dict[str, Any],
        atlas: str = "mni",
        roi_mapping: dict[str, list[int]] | None = None,
    ) -> dict[str, Any]:
        """Export ROI-level results."""
        result = roi_output(channel_results, atlas=atlas, roi_mapping=roi_mapping)
        self._provenance.log(
            step_id="roi_output",
            parameters={"atlas": atlas, "n_rois": result.get("n_rois", 0)},
        )
        return result
