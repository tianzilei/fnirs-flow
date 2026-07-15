"""Cedalion adapter: wraps Cedalion functions for fnirs-flow execution."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fnirs_flow.adapters.cedalion_capabilities import detect_cedalion
from fnirs_flow.adapters.cedalion_steps import (
    compute_channel_distances,
    compute_psp,
    create_glm_basis_function,
    create_glm_design_matrix,
    create_head_model,
    extract_epoch_features,
    fit_glm,
    generate_synthetic_artifacts,
    generate_synthetic_hrf,
    get_extinction_coefficients,
    get_recording_info,
    get_tissue_properties,
    ica_decomposition,
    intensity_to_od,
    motion_correction_spline,
    multimodal_decomposition,
    od_to_concentration,
    photogrammetry_coregistration,
    read_snirf,
    reconstruct_image,
    run_forward_model,
    split_long_short_channels,
    spoc_decomposition,
)
from fnirs_flow.execution.artifacts import ArtifactRecord, ArtifactStore
from fnirs_flow.execution.provenance import ProvenanceRecord


def _compute_recording_hash(recording: Any) -> str:
    """Compute a content hash of a Cedalion Recording."""
    try:
        if hasattr(recording, "timeseries"):
            digest = hashlib.sha256()
            for key, timeseries in recording.timeseries.items():
                digest.update(str(key).encode())
                digest.update(timeseries.values.tobytes())
            return digest.hexdigest()[:16]
        # Try to hash the data array
        if hasattr(recording, "values"):
            data_bytes = recording.values.tobytes()
            return hashlib.sha256(data_bytes).hexdigest()[:16]
        # Fallback to string representation
        return hashlib.sha256(str(recording).encode()).hexdigest()[:16]
    except Exception:
        return hashlib.sha256(str(type(recording)).encode()).hexdigest()[:16]


class CedalionAdapter:
    """Adapter for Cedalion backend execution.

    Each step:
      1. Executes the Cedalion function
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
        self._capabilities = detect_cedalion()
        self._provenance = ProvenanceRecord()
        self._artifacts = ArtifactStore()
        self._subject = subject
        self._session = session
        self._task = task
        self._run = run
        self._outdir = Path(outdir) if outdir else None
        if self._outdir:
            self._outdir.mkdir(parents=True, exist_ok=True)

        if not self._capabilities["installed"]:
            raise ImportError("Cedalion is not installed")
        if not self._capabilities["compatible"]:
            import warnings

            warnings.warn(f"Cedalion version {self._capabilities['version']} may not be fully compatible")

    def _entity_prefix(self) -> str:
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
        """Return Cedalion version information."""
        return {
            "cedalion": self._capabilities["version"],
            "python": __import__("sys").version,
        }

    @property
    def capabilities(self) -> dict[str, Any]:
        """Return Cedalion capabilities."""
        return self._capabilities

    @property
    def provenance(self) -> ProvenanceRecord:
        return self._provenance

    @property
    def artifacts(self) -> ArtifactStore:
        return self._artifacts

    def _emit_artifact(
        self,
        artifact_type: str,
        recording: Any,
        step_id: str,
        parameters: dict[str, Any],
    ) -> ArtifactRecord:
        """Emit a structured artifact record for a step."""
        checksum = _compute_recording_hash(recording) if recording is not None else ""
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

    def read_run(self, filepath: str | Path) -> Any:
        """Read a SNIRF run file."""
        recording = read_snirf(str(filepath))
        source_name = Path(filepath).name
        self._provenance.log(
            step_id="read_run",
            parameters={"source_file": source_name},
        )
        self._emit_artifact("RawIntensity", recording, "read_run", {"source_file": source_name})

        # Write import summary
        info = get_recording_info(recording)
        summary = {
            "step": "read_run",
            "source_file": source_name,
            **info,
        }
        self._write_artifact_file("read_run", "import_summary", summary)
        return recording

    def to_optical_density(
        self,
        recording: Any,
        nonpositive_policy: str = "nan",
    ) -> Any:
        """Convert intensity to optical density."""
        input_hash = _compute_recording_hash(recording)
        result = intensity_to_od(
            recording,
            nonpositive_policy=nonpositive_policy,
        )
        output_hash = _compute_recording_hash(result)
        od = result.get_timeseries("od")
        nonpositive_count = int(od.attrs.get("fnirs_flow_nonpositive_count", 0))
        parameters = {
            "nonpositive_policy": nonpositive_policy,
            "nonpositive_count": nonpositive_count,
        }

        self._provenance.log(
            step_id="optical_density",
            parameters=parameters,
            input_hashes={"raw": input_hash},
            output_hashes={"od": output_hash},
        )
        self._emit_artifact("OpticalDensity", result, "optical_density", parameters)

        # Write OD summary
        info = get_recording_info(result)
        summary = {
            "step": "optical_density",
            **parameters,
            **info,
            "input_hash": input_hash,
            "output_hash": output_hash,
        }
        self._write_artifact_file("optical_density", "od_summary", summary)
        return result

    def to_haemoglobin(
        self,
        recording: Any,
        ppf: float | list[float] | dict[float, float] = 6.0,
        spectrum: str = "prahl",
    ) -> Any:
        """Convert OD to haemoglobin concentration."""
        input_hash = _compute_recording_hash(recording)
        result = od_to_concentration(recording, ppf=ppf, spectrum=spectrum)
        output_hash = _compute_recording_hash(result)
        parameters = {"ppf": ppf, "spectrum": spectrum}

        self._provenance.log(
            step_id="beer_lambert_law",
            parameters=parameters,
            input_hashes={"od": input_hash},
            output_hashes={"haemoglobin": output_hash},
        )
        self._emit_artifact("HaemoglobinData", result, "beer_lambert_law", parameters)

        # Write HB summary
        info = get_recording_info(result)
        summary = {
            "step": "beer_lambert_law",
            "ppf": ppf,
            "spectrum": spectrum,
            **info,
            "input_hash": input_hash,
            "output_hash": output_hash,
        }
        self._write_artifact_file("beer_lambert_law", "hb_summary", summary)
        return result

    def get_citations(self) -> list[dict[str, Any]]:
        """Get citations for Cedalion methods used.

        Returns list of citation dictionaries with:
        - method: method name
        - citation: citation string
        - doi: DOI if available
        """
        citations = []

        # Cedalion itself
        citations.append(
            {
                "method": "cedalion",
                "citation": "Cedalion: A Python toolbox for fNIRS data analysis",
                "doi": "",
                "version": self._capabilities["version"],
            }
        )

        # Methods we use
        if "snirf_read" in self._capabilities["supported_operations"]:
            citations.append(
                {
                    "method": "snirf_read",
                    "citation": "SNIRF: Shared Near Infrared Spectroscopy Format",
                    "doi": "10.1117/1.NPh.8.1.010401",
                }
            )

        if "int2od" in self._capabilities["supported_operations"]:
            citations.append(
                {
                    "method": "int2od",
                    "citation": "Intensity to optical density conversion",
                    "doi": "",
                }
            )

        if "od2conc" in self._capabilities["supported_operations"]:
            citations.append(
                {
                    "method": "od2conc",
                    "citation": "Modified Beer-Lambert Law for concentration conversion",
                    "doi": "",
                }
            )

        return citations

    def get_extinction_coefficients(self, wavelengths: list[float], spectrum: str = "prahl") -> Any:
        """Get molar extinction coefficients for given wavelengths."""
        return get_extinction_coefficients(wavelengths, spectrum)

    def compute_channel_distances(self, amplitudes: Any, geo3d: Any) -> Any:
        """Compute source-detector channel distances."""
        return compute_channel_distances(amplitudes, geo3d)

    def get_tissue_properties(
        self,
        segmentation_masks: Any,
        wavelengths: list[float],
    ) -> Any:
        """Return optical properties for labeled tissue masks."""
        return get_tissue_properties(segmentation_masks, wavelengths)

    def split_long_short_channels(self, amplitudes: Any, geo3d: Any, threshold_mm: float = 15.0) -> Any:
        """Split channels into long and short separation channels."""
        return split_long_short_channels(amplitudes, geo3d, threshold_mm)

    def create_head_model(
        self,
        segmentation_dir: str,
        mask_files: dict[str, str] | None = None,
        landmarks_file: str | None = None,
        **kwargs,
    ) -> Any:
        """Create a two-surface head model from segmentation masks."""
        return create_head_model(segmentation_dir, mask_files, landmarks_file, **kwargs)

    def run_forward_model(
        self, head_model: Any, geo3d: Any, geo3d_dir: Any, n_photons: int = 1000000, method: str = "MCX", **kwargs
    ) -> Any:
        """Run forward model simulation for light transport."""
        return run_forward_model(head_model, geo3d, geo3d_dir, n_photons, method, **kwargs)

    def reconstruct_image(
        self,
        forward_model: Any,
        od_data: Any,
        method: str = "Tikhonov",
        alpha_meas: float = 0.001,
        alpha_spatial: float = 0.01,
        **kwargs,
    ) -> Any:
        """Perform DOT image reconstruction."""
        return reconstruct_image(forward_model, od_data, method, alpha_meas, alpha_spatial, **kwargs)

    def spoc_decomposition(
        self, fnirs_data: Any, target_signal: Any, n_components: int = 5, method: str = "spoc", **kwargs
    ) -> Any:
        """Perform SpOC (Spatial Patterns of Covariance) decomposition."""
        return spoc_decomposition(fnirs_data, target_signal, n_components, method, **kwargs)

    def ica_decomposition(self, fnirs_data: Any, method: str = "EBM", n_components: int | None = None, **kwargs) -> Any:
        """Perform ICA-based signal decomposition."""
        return ica_decomposition(fnirs_data, method, n_components, **kwargs)

    def multimodal_decomposition(
        self, fnirs_data: Any, auxiliary_data: Any, method: str = "MSPoC", n_components: int = 5, **kwargs
    ) -> Any:
        """Perform multimodal signal decomposition."""
        return multimodal_decomposition(fnirs_data, auxiliary_data, method, n_components, **kwargs)

    def generate_synthetic_hrf(
        self,
        brain_surface: Any,
        seed_vertices: list[int],
        spatial_scale_cm: float = 1.0,
        intensity_uM: float = 1.0,
        **kwargs,
    ) -> Any:
        """Generate synthetic hemodynamic response functions."""
        return generate_synthetic_hrf(brain_surface, seed_vertices, spatial_scale_cm, intensity_uM, **kwargs)

    def generate_synthetic_artifacts(
        self, clean_signal: Any, n_artifacts: int = 5, artifact_types: list[str] | None = None, **kwargs
    ) -> Any:
        """Generate synthetic motion artifacts in clean signals."""
        return generate_synthetic_artifacts(clean_signal, n_artifacts, artifact_types, **kwargs)

    def extract_epoch_features(
        self,
        epochs: Any,
        feature_types: list[str] | None = None,
        reltime_slices: dict | None = None,
    ) -> Any:
        """Extract features from epoched data for ML."""
        return extract_epoch_features(epochs, feature_types, reltime_slices)

    def compute_psp(self, amplitudes: Any, window_length_s: float = 10.0, psp_threshold: float = 0.1, **kwargs) -> Any:
        """Compute Peak Spectral Power quality metric."""
        return compute_psp(amplitudes, window_length_s, psp_threshold, **kwargs)

    def motion_correction_spline(self, ts: Any, t_inc_ch: Any, p: float = 0.99) -> Any:
        """Apply spline interpolation motion correction."""
        return motion_correction_spline(ts, t_inc_ch, p)

    def create_glm_basis_function(
        self, basis_type: str = "gamma", n_basis: int = 3, temporal_extent_s: float = 32.0, **kwargs
    ) -> Any:
        """Create temporal basis functions for GLM."""
        return create_glm_basis_function(basis_type, n_basis, temporal_extent_s, **kwargs)

    def create_glm_design_matrix(self, stimulus_df: Any, basis_functions: Any, drift_order: int = 3, **kwargs) -> Any:
        """Create GLM design matrix."""
        return create_glm_design_matrix(stimulus_df, basis_functions, drift_order, **kwargs)

    def fit_glm(
        self, design_matrix: Any, data: Any, method: str = "OLS", confidence_level: float = 0.95, **kwargs
    ) -> Any:
        """Fit GLM model to data."""
        return fit_glm(design_matrix, data, method, confidence_level, **kwargs)

    def photogrammetry_coregistration(
        self, scan_file: str, head_model: Any, method: str = "colored_sticker", **kwargs
    ) -> Any:
        """Perform photogrammetric optode co-registration."""
        return photogrammetry_coregistration(scan_file, head_model, method, **kwargs)
