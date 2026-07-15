"""Cedalion step implementations: wrappers for Cedalion operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def read_snirf(filepath: str, recording_index: int | None = None) -> Any:
    """Read a SNIRF file using Cedalion.

    Returns:
        Cedalion Recording object
    """
    try:
        import cedalion.io

        recordings = cedalion.io.read_snirf(filepath)
        if recording_index is None:
            if len(recordings) != 1:
                raise ValueError(
                    f"SNIRF file contains {len(recordings)} recordings; "
                    "set recording_index explicitly"
                )
            recording_index = 0
        try:
            return recordings[recording_index]
        except IndexError as exc:
            raise IndexError(
                f"recording_index={recording_index} is out of range for "
                f"{len(recordings)} recordings"
            ) from exc
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to read SNIRF file: {e}") from e


def intensity_to_od(
    recording: Any,
    amplitude_key: str = "amp",
    output_key: str = "od",
    nonpositive_policy: str = "nan",
) -> Any:
    """Convert intensity to optical density using Cedalion.

    Args:
        recording: Cedalion Recording with intensity data

    Returns:
        Cedalion Recording with optical density data
    """
    try:
        import cedalion.nirs.cw

        amplitudes = recording.get_timeseries(amplitude_key)
        nonpositive_count = int((amplitudes <= 0).sum().item())
        if nonpositive_count:
            if nonpositive_policy == "raise":
                raise ValueError(
                    f"{nonpositive_count} non-positive intensity samples cannot be "
                    "converted to optical density"
                )
            if nonpositive_policy != "nan":
                raise ValueError("nonpositive_policy must be 'nan' or 'raise'")
            amplitudes = amplitudes.where(amplitudes > 0)

        od = cedalion.nirs.cw.int2od(amplitudes)
        od.attrs["fnirs_flow_nonpositive_policy"] = nonpositive_policy
        od.attrs["fnirs_flow_nonpositive_count"] = nonpositive_count
        recording.set_timeseries(output_key, od, overwrite=True)
        return recording
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to convert intensity to OD: {e}") from e


def od_to_concentration(
    recording: Any,
    ppf: float | Sequence[float] | Mapping[float, float] = 6.0,
    od_key: str = "od",
    output_key: str = "conc",
    spectrum: str = "prahl",
) -> Any:
    """Convert optical density to concentration using Cedalion.

    Args:
        recording: Cedalion Recording with optical density data
        ppf: Partial path length factor

    Returns:
        Cedalion Recording with concentration data
    """
    try:
        import cedalion.nirs.cw
        import xarray as xr

        od = recording.get_timeseries(od_key)
        wavelengths = [float(value) for value in od.wavelength.values]
        if isinstance(ppf, Mapping):
            dpf_values = [float(ppf[wavelength]) for wavelength in wavelengths]
        elif isinstance(ppf, Sequence) and not isinstance(ppf, (str, bytes)):
            dpf_values = [float(value) for value in ppf]
            if len(dpf_values) != len(wavelengths):
                raise ValueError(
                    "ppf sequence length must match the number of wavelengths"
                )
        else:
            dpf_values = [float(ppf)] * len(wavelengths)

        dpf = xr.DataArray(
            dpf_values,
            dims=["wavelength"],
            coords={"wavelength": wavelengths},
            name="dpf",
        )
        concentration = cedalion.nirs.cw.od2conc(
            od,
            recording.geo3d,
            dpf,
            spectrum=spectrum,
        )
        concentration.attrs["fnirs_flow_dpf"] = dpf_values
        concentration.attrs["fnirs_flow_spectrum"] = spectrum
        recording.set_timeseries(output_key, concentration, overwrite=True)
        return recording
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to convert OD to concentration: {e}") from e


def compute_sci(recording: Any) -> Any:
    """Compute Scalp Coupling Index using Cedalion.

    Args:
        recording: Cedalion Recording

    Returns:
        SCI values
    """
    try:
        import cedalion
        import cedalion.nirs.qc

        return cedalion.nirs.qc.scalp_coupling_index(recording)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to compute SCI: {e}") from e


def apply_filter(recording: Any, l_freq: float = 0.01, h_freq: float = 0.2) -> Any:
    """Apply bandpass filter using Cedalion.

    Args:
        recording: Cedalion Recording
        l_freq: Low frequency cutoff
        h_freq: High frequency cutoff

    Returns:
        Filtered Cedalion Recording
    """
    try:
        import cedalion
        import cedalion.nirs.signal

        return cedalion.nirs.signal.bandpass_filter(recording, l_freq, h_freq)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to apply filter: {e}") from e


def motion_correction_tddr(recording: Any) -> Any:
    """Apply Temporal Derivative Distribution Repair using Cedalion.

    Args:
        recording: Cedalion Recording

    Returns:
        Corrected Cedalion Recording
    """
    try:
        import cedalion
        import cedalion.nirs.motion

        return cedalion.nirs.motion.tddr(recording)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to apply TDDR: {e}") from e


def get_recording_info(recording: Any) -> dict[str, Any]:
    """Extract information from a Cedalion Recording.

    Args:
        recording: Cedalion Recording

    Returns:
        Dictionary with recording information
    """
    timeseries = recording
    timeseries_keys: list[str] = []
    if hasattr(recording, "timeseries") and hasattr(recording, "get_timeseries"):
        timeseries_keys = list(recording.timeseries)
        timeseries = recording.get_timeseries()

    info = {
        "type": type(recording).__name__,
        "dims": list(timeseries.dims) if hasattr(timeseries, "dims") else [],
        "shape": timeseries.shape if hasattr(timeseries, "shape") else None,
    }
    if timeseries_keys:
        info["timeseries_keys"] = timeseries_keys

    # Extract time information
    if hasattr(timeseries, "time"):
        times = timeseries.time.values
        info["n_times"] = len(times)
        info["duration_s"] = float(times[-1] - times[0]) if len(times) > 1 else 0.0
        info["sfreq"] = 1.0 / (times[1] - times[0]) if len(times) > 1 else 0.0

    # Extract channel information
    if hasattr(timeseries, "channel"):
        info["n_channels"] = len(timeseries.channel)
        info["channel_labels"] = timeseries.channel.values.tolist()[:20]  # First 20

    # Extract wavelength information
    if hasattr(timeseries, "wavelength"):
        info["wavelengths"] = sorted(timeseries.wavelength.values.tolist())

    # Extract chromophore information
    chromo = getattr(timeseries, "chromo", None)
    if chromo is not None:
        info["chromophores"] = sorted(chromo.values.tolist())

    return info


def get_extinction_coefficients(wavelengths: list[float], spectrum: str = "prahl") -> Any:
    """Get molar extinction coefficients for given wavelengths.

    Args:
        wavelengths: List of wavelengths in nm
        spectrum: Spectrum source ("prahl" or "matlab_hb")

    Returns:
        Extinction coefficients array
    """
    try:
        import cedalion.nirs.common
        return cedalion.nirs.common.get_extinction_coefficients(spectrum, wavelengths)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to get extinction coefficients: {e}") from e


def compute_channel_distances(amplitudes: Any, geo3d: Any) -> Any:
    """Compute source-detector channel distances.

    Args:
        geo3d: 3D optode positions

    Returns:
        Channel distances array
    """
    try:
        import cedalion.nirs.common
        return cedalion.nirs.common.channel_distances(amplitudes, geo3d)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to compute channel distances: {e}") from e


def split_long_short_channels(amplitudes: Any, geo3d: Any, threshold_mm: float = 15.0) -> Any:
    """Split channels into long and short separation channels.

    Args:
        amplitudes: Input time series
        geo3d: 3D optode positions
        threshold_mm: Distance threshold in mm

    Returns:
        Tuple of (long_channels, short_channels)
    """
    try:
        import cedalion.nirs.common
        from cedalion import units

        return cedalion.nirs.common.split_long_short_channels(
            amplitudes,
            geo3d,
            threshold_mm * units.mm,
        )
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to split channels: {e}") from e


def create_head_model(segmentation_dir: str, mask_files: dict[str, str] | None = None,
                      landmarks_file: str | None = None, **kwargs) -> Any:
    """Create a two-surface head model from segmentation masks.

    Args:
        segmentation_dir: Directory containing segmentation masks
        mask_files: Dictionary mapping tissue types to mask files
        landmarks_file: File containing anatomical landmarks
        **kwargs: Additional parameters for head model construction

    Returns:
        TwoSurfaceHeadModel instance
    """
    try:
        from cedalion.dot.head_model import TwoSurfaceHeadModel
        return TwoSurfaceHeadModel.from_segmentation(
            segmentation_dir, mask_files, landmarks_file, **kwargs
        )
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to create head model: {e}") from e


def get_tissue_properties(segmentation_masks: Any, wavelengths: list[float]) -> Any:
    """Return Cedalion optical properties for labeled tissue masks."""
    try:
        from cedalion.dot.tissue_properties import get_tissue_properties as cedalion_get

        return cedalion_get(segmentation_masks, wavelengths)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to get tissue properties: {e}") from e


def run_forward_model(head_model: Any, geo3d: Any, geo3d_dir: Any,
                      n_photons: int = 1000000, method: str = "MCX", **kwargs) -> Any:
    """Run forward model simulation for light transport.

    Args:
        head_model: TwoSurfaceHeadModel instance
        geo3d: Optode positions
        geo3d_dir: Optode orientations
        n_photons: Number of photons for simulation
        method: Simulation method ("MCX" or "NIRFASTer")
        **kwargs: Additional parameters

    Returns:
        ForwardModel instance with computed fluence
    """
    try:
        from cedalion.dot.forward_model import ForwardModel
        fm = ForwardModel(head_model, geo3d, geo3d_dir, **kwargs)
        fm.compute_fluence(n_photons)
        return fm
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to run forward model: {e}") from e


def reconstruct_image(forward_model: Any, od_data: Any, method: str = "Tikhonov",
                      alpha_meas: float = 0.001, alpha_spatial: float = 0.01, **kwargs) -> Any:
    """Perform DOT image reconstruction.

    Args:
        forward_model: ForwardModel with computed fluence
        od_data: Optical density data
        method: Reconstruction method ("Tikhonov" or "SBF_gaussians")
        alpha_meas: Measurement regularization parameter
        alpha_spatial: Spatial regularization parameter
        **kwargs: Additional parameters

    Returns:
        ImageRecon instance with reconstructed concentrations
    """
    try:
        from cedalion.dot.image_recon import ImageRecon
        recon = ImageRecon(forward_model, method=method, **kwargs)
        recon.solve(od_data, alpha_meas=alpha_meas, alpha_spatial=alpha_spatial)
        return recon
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to reconstruct image: {e}") from e


def spoc_decomposition(fnirs_data: Any, target_signal: Any, n_components: int = 5,
                       method: str = "spoc", **kwargs) -> Any:
    """Perform SpOC (Spatial Patterns of Covariance) decomposition.

    Args:
        fnirs_data: fNIRS time series data
        target_signal: Target signal for covariance optimization
        n_components: Number of components to extract
        method: Decomposition method ("spoc" or "cca")
        **kwargs: Additional parameters

    Returns:
        SpOC decomposition results
    """
    try:
        from cedalion.sigdecomp.unimodal.spoc import SpOC
        spoc = SpOC(n_components=n_components, **kwargs)
        return spoc.fit(fnirs_data, target_signal)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to perform SpOC decomposition: {e}") from e


def ica_decomposition(fnirs_data: Any, method: str = "EBM", n_components: int | None = None,
                      **kwargs) -> Any:
    """Perform ICA-based signal decomposition.

    Args:
        fnirs_data: fNIRS time series data
        method: ICA method ("EBM" or "ERBM")
        n_components: Number of components (None for auto)
        **kwargs: Additional parameters

    Returns:
        ICA decomposition results
    """
    try:
        if method.upper() == "EBM":
            from cedalion.sigdecomp.unimodal.ica_ebm import ICA_EBM as ICAClass
        else:
            from cedalion.sigdecomp.unimodal.ica_erbm import ICA_ERBM as ICAClass
        ica = ICAClass(n_components=n_components, **kwargs)
        return ica.fit(fnirs_data)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to perform ICA decomposition: {e}") from e


def multimodal_decomposition(fnirs_data: Any, auxiliary_data: Any, method: str = "MSPoC",
                             n_components: int = 5, **kwargs) -> Any:
    """Perform multimodal signal decomposition.

    Args:
        fnirs_data: fNIRS time series data
        auxiliary_data: Auxiliary modality data (EEG, MEG, etc.)
        method: Decomposition method ("MSPoC", "tCCA", "ARC_EBM", "ARC_ERBM")
        n_components: Number of components
        **kwargs: Additional parameters

    Returns:
        Multimodal decomposition results
    """
    try:
        if method.upper() == "MSPOC":
            from cedalion.sigdecomp.multimodal.mspoc import MSPoC as DecompClass
        elif method.upper() == "TCCA":
            from cedalion.sigdecomp.multimodal.tcca import TCCA as DecompClass
        elif method.upper() == "ARC_EBM":
            from cedalion.sigdecomp.multimodal.arc_ebm import ARC_EBM as DecompClass
        else:
            from cedalion.sigdecomp.multimodal.arc_erbm import ARC_ERBM as DecompClass
        decomp = DecompClass(n_components=n_components, **kwargs)
        return decomp.fit(fnirs_data, auxiliary_data)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to perform multimodal decomposition: {e}") from e


def generate_synthetic_hrf(brain_surface: Any, seed_vertices: list[int],
                           spatial_scale_cm: float = 1.0, intensity_uM: float = 1.0,
                           **kwargs) -> Any:
    """Generate synthetic hemodynamic response functions.

    Args:
        brain_surface: Brain surface mesh
        seed_vertices: Vertex indices for activation centers
        spatial_scale_cm: Spatial scale in cm
        intensity_uM: Intensity in micromolar
        **kwargs: Additional parameters

    Returns:
        Synthetic HRF data
    """
    try:
        from cedalion import units
        from cedalion.sim.synthetic_hrf import build_spatial_activation
        activation = build_spatial_activation(
            brain_surface, seed_vertices,
            spatial_scale=spatial_scale_cm * units.cm,
            intensity_scale=intensity_uM * units.micromolar,
            **kwargs
        )
        return activation
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to generate synthetic HRF: {e}") from e


def generate_synthetic_artifacts(clean_signal: Any, n_artifacts: int = 5,
                                 artifact_types: list[str] | None = None, **kwargs) -> Any:
    """Generate synthetic motion artifacts in clean signals.

    Args:
        clean_signal: Clean fNIRS signal
        n_artifacts: Number of artifacts to inject
        artifact_types: Types of artifacts to generate
        **kwargs: Additional parameters

    Returns:
        Signal with injected artifacts
    """
    try:
        from cedalion.sim.synthetic_artifact import inject_artifacts
        if artifact_types is None:
            artifact_types = ["baseline_shift", "spike", "motion"]
        return inject_artifacts(clean_signal, n_artifacts=n_artifacts,
                               artifact_types=artifact_types, **kwargs)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to generate synthetic artifacts: {e}") from e


def extract_epoch_features(epochs: Any, feature_types: list[str] | None = None,
                           reltime_slices: dict | None = None) -> Any:
    """Extract features from epoched data for ML.

    Args:
        epochs: Epoched fNIRS data
        feature_types: Feature types to extract (slope, mean, max, min, auc)
        reltime_slices: Time windows for each feature type

    Returns:
        Feature matrix for ML classifiers
    """
    try:
        from cedalion.mlutils.features import epoch_features
        if feature_types is None:
            feature_types = ["slope", "mean", "max", "min", "auc"]
        return epoch_features(epochs, feature_types, reltime_slices)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to extract epoch features: {e}") from e


def compute_psp(amplitudes: Any, window_length_s: float = 10.0,
                psp_threshold: float = 0.1, **kwargs) -> Any:
    """Compute Peak Spectral Power quality metric.

    Args:
        amplitudes: Input time series
        window_length_s: Window length in seconds
        psp_threshold: Threshold for good channels
        **kwargs: Additional parameters

    Returns:
        PSP values and channel quality mask
    """
    try:
        from cedalion import units
        from cedalion.sigproc.quality import psp
        window_length = window_length_s * units.seconds
        return psp(amplitudes, window_length, psp_threshold, **kwargs)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to compute PSP: {e}") from e


def motion_correction_spline(ts: Any, t_inc_ch: Any, p: float = 0.99) -> Any:
    """Apply spline interpolation motion correction.

    Args:
        ts: Time series to correct
        t_inc_ch: Motion artifact mask
        p: Smoothing factor

    Returns:
        Motion-corrected time series
    """
    try:
        from cedalion.sigproc.motion import spline
        return spline(ts, t_inc_ch, p)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to apply spline motion correction: {e}") from e


def create_glm_basis_function(basis_type: str = "gamma", n_basis: int = 3,
                              temporal_extent_s: float = 32.0, **kwargs) -> Any:
    """Create temporal basis functions for GLM.

    Args:
        basis_type: Type of basis function ("gamma", "gaussian_kernels", "dirac_delta")
        n_basis: Number of basis functions
        temporal_extent_s: Temporal extent in seconds
        **kwargs: Additional parameters

    Returns:
        Basis function set
    """
    try:
        from cedalion import units
        from cedalion.models.glm.basis_functions import DiracDelta, Gamma, GaussianKernels
        if basis_type == "gamma":
            basis = Gamma(n_basis=n_basis, temporal_extent=temporal_extent_s * units.seconds, **kwargs)
        elif basis_type == "gaussian_kernels":
            basis = GaussianKernels(n_basis=n_basis, temporal_extent=temporal_extent_s * units.seconds, **kwargs)
        else:
            basis = DiracDelta(**kwargs)
        return basis
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to create basis function: {e}") from e


def create_glm_design_matrix(stimulus_df: Any, basis_functions: Any,
                             drift_order: int = 3, **kwargs) -> Any:
    """Create GLM design matrix.

    Args:
        stimulus_df: Stimulus DataFrame
        basis_functions: Temporal basis functions
        drift_order: Polynomial drift order
        **kwargs: Additional parameters

    Returns:
        Design matrix
    """
    try:
        from cedalion.models.glm.design_matrix import hrf_regressors
        return hrf_regressors(stimulus_df, basis_functions, drift_order=drift_order, **kwargs)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to create design matrix: {e}") from e


def fit_glm(design_matrix: Any, data: Any, method: str = "OLS",
            confidence_level: float = 0.95, **kwargs) -> Any:
    """Fit GLM model to data.

    Args:
        design_matrix: GLM design matrix
        data: Input data
        method: Fitting method ("OLS" or "weighted_LS")
        confidence_level: Confidence level for intervals
        **kwargs: Additional parameters

    Returns:
        GLM fit results with uncertainty estimates
    """
    try:
        from cedalion.models.glm import fit
        return fit(design_matrix, data, method=method, confidence_level=confidence_level, **kwargs)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to fit GLM: {e}") from e


def photogrammetry_coregistration(scan_file: str, head_model: Any,
                                  method: str = "colored_sticker", **kwargs) -> Any:
    """Perform photogrammetric optode co-registration.

    Args:
        scan_file: Path to 3D scan file
        head_model: Head model for registration
        method: Registration method ("colored_sticker" or "fiducial_manual")
        **kwargs: Additional parameters

    Returns:
        Registered optode positions
    """
    try:
        from cedalion.geometry.photogrammetry.processors import ColoredStickerProcessor
        processor = ColoredStickerProcessor(**kwargs)
        return processor.process(scan_file, head_model)
    except ImportError:
        raise ImportError("Cedalion is required. Install with: pip install cedalion") from None
    except Exception as e:
        raise RuntimeError(f"Failed to perform photogrammetry co-registration: {e}") from e
