"""MNE-NIRS preprocessing and quality-control operations."""

from __future__ import annotations

from typing import Any

import numpy as np


class GLMInputDataError(ValueError):
    """Raised when first-level GLM input contains non-finite values."""

    def __init__(self, message: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.details = details


__all__ = [
    "block_averaging",
    "build_design_matrix",
    "channel_output",
    "estimate_contrast",
    "first_level_glm",
    "roi_output",
]


def block_averaging(
    data: np.ndarray,
    events: np.ndarray,
    sfreq: float = 10.0,
    baseline_window: tuple[float, float] = (-5.0, 0.0),
    response_window: tuple[float, float] = (0.0, 20.0),
    baseline_correction: str = "mean",
) -> dict[str, Any]:
    """Average haemodynamic responses across trials/blocks.

    Evidence: 78 studies in literature report block averaging.

    Args:
        data: Haemoglobin data (channels x samples)
        events: Event array (n_events x 3) with [sample, duration, event_id]
        sfreq: Sampling frequency in Hz
        baseline_window: Baseline window in seconds (start, end)
        response_window: Response window in seconds (start, end)
        baseline_correction: Baseline correction method ('mean' or 'zscore')

    Returns:
        Dictionary with average response and metadata
    """
    n_channels = data.shape[0]
    n_events = events.shape[0]

    # Convert windows to samples
    baseline_start = int(baseline_window[0] * sfreq)
    baseline_end = int(baseline_window[1] * sfreq)
    response_start = int(response_window[0] * sfreq)
    response_end = int(response_window[1] * sfreq)

    # Extract epochs
    epoch_length = response_end - response_start
    epochs = []
    n_valid_trials = 0

    for ev_idx in range(n_events):
        event_sample = int(events[ev_idx, 0])

        # Extract response window
        start = event_sample + response_start
        end = start + epoch_length

        if start >= 0 and end <= data.shape[1]:
            epoch = data[:, start:end]

            # Baseline correction
            bl_start = event_sample + baseline_start
            bl_end = event_sample + baseline_end
            if bl_start >= 0 and bl_end <= data.shape[1]:
                baseline = data[:, bl_start:bl_end]

                if baseline_correction == "mean":
                    epoch = epoch - np.mean(baseline, axis=1, keepdims=True)
                elif baseline_correction == "zscore":
                    baseline_mean = np.mean(baseline, axis=1, keepdims=True)
                    baseline_std = np.std(baseline, axis=1, keepdims=True)
                    epoch = (epoch - baseline_mean) / baseline_std

            epochs.append(epoch)
            n_valid_trials += 1

    if n_valid_trials == 0:
        return {
            "average": np.zeros((n_channels, epoch_length)),
            "std": np.zeros((n_channels, epoch_length)),
            "sem": np.zeros((n_channels, epoch_length)),
            "n_trials": 0,
            "epoch_length": epoch_length,
            "sfreq": sfreq,
            "time_axis": np.arange(epoch_length) / sfreq + response_window[0],
        }

    epochs_array = np.array(epochs)

    # Average across trials
    average_response = np.mean(epochs_array, axis=0)
    std_response = np.std(epochs_array, axis=0)
    sem_response = std_response / np.sqrt(n_valid_trials)

    return {
        "average": average_response,
        "std": std_response,
        "sem": sem_response,
        "n_trials": n_valid_trials,
        "epoch_length": epoch_length,
        "sfreq": sfreq,
        "time_axis": np.arange(epoch_length) / sfreq + response_window[0],
    }


# ============================================================================
# GLM ANALYSIS (from MNE-NIRS)
# ============================================================================


def _canonical_hrf(sfreq: float, model: str, duration: float = 32.0) -> np.ndarray:
    """Return a normalized canonical double-gamma HRF sampled at ``sfreq``."""
    from scipy.stats import gamma

    times = np.arange(0.0, duration, 1.0 / sfreq)
    if model == "spm":
        hrf: np.ndarray = gamma.pdf(times, 6) - gamma.pdf(times, 16) / 6.0
    elif model == "glover":
        hrf = gamma.pdf(times, 6) - 0.35 * gamma.pdf(times, 12)
    else:
        raise ValueError(f"Unsupported HRF model: {model}")
    scale = np.max(hrf)
    result: np.ndarray = hrf / scale if scale else hrf
    return result


def build_design_matrix(
    raw: Any,
    events: np.ndarray,
    event_id: dict[str, int],
    sfreq: float,
    hrf_model: str = "glover",
    drift_order: int = 1,
    high_pass: float = 0.01,
) -> dict[str, Any]:
    """Build a GLM design matrix from events.

    Args:
        raw: MNE Raw object (used for time axis)
        events: MNE events array (n_events, 3)
        event_id: Mapping of condition names to event IDs
        sfreq: Sampling frequency
        hrf_model: HRF model type ('glover' or 'spm')
        drift_order: Drift polynomial order
        high_pass: High-pass filter cutoff for drift removal

    Returns:
        Dictionary with design matrix and metadata
    """
    if events.ndim != 2 or events.shape[1] < 3:
        raise ValueError("events must be an (n_events, 3) array")
    if sfreq <= 0:
        raise ValueError("sfreq must be positive")

    # Build duration-aware stimulus functions, then convolve with the selected
    # canonical HRF. The second events column stores duration in samples for
    # fnirs-flow; zero remains backward-compatible as a one-sample event.
    n_samples = len(raw.times)
    n_conditions = len(event_id)
    hrf = _canonical_hrf(sfreq, hrf_model)
    condition_columns: list[np.ndarray] = []

    for cond_name, cond_id in event_id.items():
        stimulus = np.zeros(n_samples, dtype=float)
        mask = events[:, 2] == cond_id
        for onset_sample, duration_samples in events[mask, :2]:
            start = max(0, int(onset_sample))
            duration_n = max(1, int(duration_samples))
            end = min(start + duration_n, n_samples)
            if start < n_samples:
                stimulus[start:end] = 1.0
        condition_columns.append(np.convolve(stimulus, hrf, mode="full")[:n_samples])

    regressor_names = list(event_id.keys())
    nuisance_columns: list[np.ndarray] = []
    sample_axis = np.linspace(-1.0, 1.0, n_samples)
    for degree in range(1, max(0, drift_order) + 1):
        nuisance_columns.append(sample_axis**degree)
        regressor_names.append(f"drift_{degree}")

    duration_seconds = n_samples / sfreq
    n_cosines = max(0, int(np.floor(2 * duration_seconds * max(0.0, high_pass))))
    sample_numbers = np.arange(n_samples, dtype=float) + 0.5
    for harmonic in range(1, n_cosines + 1):
        nuisance_columns.append(np.cos(np.pi * sample_numbers * harmonic / n_samples))
        regressor_names.append(f"high_pass_{harmonic}")

    columns = [*condition_columns, *nuisance_columns, np.ones(n_samples)]
    regressor_names.append("constant")
    X = np.column_stack(columns)

    return {
        "design_matrix": X,
        "n_samples": n_samples,
        "n_conditions": n_conditions,
        "conditions": list(event_id.keys()),
        "regressor_names": regressor_names,
        "n_regressors": X.shape[1],
        "hrf_model": hrf_model,
        "drift_order": drift_order,
        "high_pass": high_pass,
        "sfreq": sfreq,
    }


def first_level_glm(
    raw: Any,
    design_matrix: dict[str, Any],
    hrf_model: str = "glover",
    noise_model: str = "ar1",
    nonfinite_policy: str = "error",
) -> dict[str, Any]:
    """Fit a first-level GLM.

    Args:
        raw: MNE Raw object with haemoglobin channels
        design_matrix: Output from build_design_matrix
        hrf_model: HRF model type
        noise_model: Noise model ('ols' or 'ar1')
        nonfinite_policy: ``error`` fails closed and records input quality;
            ``drop_channels`` explicitly excludes affected channels while
            retaining their original channel indices in downstream outputs.

    Returns:
        Dictionary with GLM results (beta maps, statistics)
    """
    data = raw.get_data()
    channel_indices = list(range(data.shape[0]))
    X = design_matrix["design_matrix"]

    finite_mask = np.isfinite(data)
    data_quality: dict[str, Any] = {
        "status": "passed",
        "nonfinite_policy": nonfinite_policy,
        "nonfinite_value_count": 0,
        "affected_channel_count": 0,
        "affected_channel_indices": [],
        "excluded_channel_indices": [],
    }
    if not finite_mask.all():
        affected_channels = np.flatnonzero(~finite_mask.all(axis=1)).astype(int).tolist()
        details = {
            "status": "failed",
            "reason": "non_finite_haemoglobin_data",
            "nonfinite_value_count": int((~finite_mask).sum()),
            "affected_channel_count": len(affected_channels),
            "affected_channel_indices": affected_channels,
            "n_channels": int(data.shape[0]),
            "n_samples": int(data.shape[1]),
            "nonfinite_policy": nonfinite_policy,
        }
        if nonfinite_policy == "drop_channels":
            keep = finite_mask.all(axis=1)
            if not keep.any():
                details["reason"] = "no_finite_haemoglobin_channels"
                raise GLMInputDataError("GLM input has no fully finite channels", details)
            channel_indices = np.flatnonzero(keep).astype(int).tolist()
            data = data[keep]
            data_quality = {
                **details,
                "status": "adjusted",
                "reason": "non_finite_channels_dropped",
                "excluded_channel_indices": affected_channels,
                "included_channel_count": len(channel_indices),
            }
        elif nonfinite_policy == "error":
            raise GLMInputDataError(
                "GLM input data contains non-finite values "
                f"(count={details['nonfinite_value_count']}, "
                f"affected_channels={details['affected_channel_count']})",
                details,
            )
        else:
            raise ValueError("nonfinite_policy must be 'error' or 'drop_channels'")
    elif nonfinite_policy not in {"error", "drop_channels"}:
        raise ValueError("nonfinite_policy must be 'error' or 'drop_channels'")
    n_channels = data.shape[0]
    if not np.isfinite(X).all():
        raise ValueError("GLM design matrix contains non-finite values")
    if X.shape[0] <= X.shape[1]:
        raise ValueError("GLM requires more samples than regressors")

    # Solve OLS directly instead of forming the normal equations for the beta
    # estimate. Scaling prevents Accelerate/BLAS from emitting spurious
    # floating-point warnings for haemoglobin signals expressed around 1e-6 M.
    data_scale = float(np.max(np.abs(data)))
    if data_scale == 0.0:
        data_scale = 1.0
    scaled_data = data / data_scale
    scaled_betas = np.linalg.lstsq(X, scaled_data.T, rcond=None)[0].T
    fitted = np.einsum("cr,sr->cs", scaled_betas, X, optimize=False)
    scaled_residuals = scaled_data - fitted
    betas = scaled_betas * data_scale
    residuals = scaled_residuals * data_scale

    XtX_inv = np.linalg.pinv(X.T @ X)
    n = X.shape[0]
    p = X.shape[1]
    rss = np.sum(scaled_residuals**2, axis=1)
    mse = rss / (n - p)
    se = np.sqrt(mse[:, np.newaxis] * np.diag(XtX_inv)[np.newaxis, :])
    se[se == 0] = 1.0
    t_stats = scaled_betas / se

    return {
        "betas": betas,
        "t_stats": t_stats,
        "residuals": residuals,
        "n_channels": n_channels,
        "channel_indices": channel_indices,
        "n_conditions": len(design_matrix.get("conditions", [])),
        "n_regressors": X.shape[1],
        "conditions": design_matrix["conditions"],
        "regressor_names": design_matrix.get("regressor_names", []),
        "df": X.shape[0] - X.shape[1],
        "hrf_model": hrf_model,
        "noise_model": noise_model,
        "data_quality": data_quality,
    }


def estimate_contrast(
    glm_result: dict[str, Any],
    contrasts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate linear contrasts from GLM results.

    Args:
        glm_result: Output from first_level_glm
        contrasts: List of contrast definitions, each with 'name', 'weights'

    Returns:
        Dictionary with contrast results
    """
    betas = glm_result["betas"]
    n_channels = glm_result["n_channels"]
    channel_indices = list(glm_result.get("channel_indices", range(n_channels)))
    n_conditions = int(glm_result.get("n_conditions", len(glm_result.get("conditions", []))))
    n_regressors = int(glm_result.get("n_regressors", betas.shape[1]))
    model_conditions = [str(value) for value in glm_result.get("conditions", [])]
    regressor_names = [str(value) for value in glm_result.get("regressor_names", [])]

    contrast_results = []

    for contrast in contrasts:
        name = contrast.get("name", "unknown")
        source_weights = list(contrast.get("weights", []))
        source_conditions = [str(value) for value in contrast.get("conditions", [])]
        if source_conditions:
            if len(source_weights) != len(source_conditions):
                raise ValueError(
                    f"Contrast '{name}' has {len(source_weights)} weights for "
                    f"{len(source_conditions)} named conditions"
                )
            missing = [condition for condition in source_conditions if condition not in regressor_names]
            if missing:
                raise ValueError(f"Contrast '{name}' references unknown conditions: {missing}")
            weights = np.zeros(n_regressors, dtype=float)
            for condition, weight in zip(source_conditions, source_weights, strict=True):
                weights[regressor_names.index(condition)] = float(weight)
        elif len(source_weights) == n_conditions and model_conditions:
            weights = np.zeros(n_regressors, dtype=float)
            for condition, weight in zip(model_conditions, source_weights, strict=True):
                if condition not in regressor_names:
                    raise ValueError(f"GLM condition '{condition}' is absent from regressor_names")
                weights[regressor_names.index(condition)] = float(weight)
        elif len(source_weights) == n_regressors:
            weights = np.asarray(source_weights, dtype=float)
        else:
            raise ValueError(
                f"Contrast '{name}' has {len(source_weights)} weights; expected "
                f"{n_conditions} condition weights or {n_regressors} regressor weights"
            )

        c_betas = betas @ weights

        contrast_results.append(
            {
                "name": name,
                "weights": weights.tolist(),
                "contrast_values": c_betas,
                "n_channels": n_channels,
                "channel_indices": channel_indices,
            }
        )

    return {
        "contrasts": contrast_results,
        "n_contrasts": len(contrasts),
        "n_channels": n_channels,
        "channel_indices": channel_indices,
        "conditions": glm_result.get("conditions", []),
    }


def channel_output(contrast_result: dict[str, Any]) -> dict[str, Any]:
    """Export channel-level results.

    Args:
        contrast_result: Output from estimate_contrast

    Returns:
        Dictionary with channel-level results table
    """
    channels = []
    channel_indices = list(contrast_result.get("channel_indices", range(contrast_result["n_channels"])))
    for i, original_index in enumerate(channel_indices):
        ch_data: dict[str, Any] = {"channel_idx": original_index}
        for contrast in contrast_result["contrasts"]:
            ch_data[f"{contrast['name']}_beta"] = float(contrast["contrast_values"][i])
        channels.append(ch_data)

    return {
        "channels": channels,
        "n_channels": contrast_result["n_channels"],
        "n_contrasts": contrast_result["n_contrasts"],
    }


def roi_output(
    channel_results: dict[str, Any],
    atlas: str = "mni",
    roi_mapping: dict[str, list[int]] | None = None,
    aggregation: str = "mean",
) -> dict[str, Any]:
    """Export ROI-level results by averaging channels within ROIs.

    Args:
        channel_results: Output from channel_output
        atlas: Atlas name for ROI mapping
        roi_mapping: Optional mapping of ROI names to channel indices.
                     If None, returns empty results with warning.

    Returns:
        Dictionary with ROI-level results
    """
    if aggregation != "mean":
        raise ValueError("roi_output currently supports only aggregation='mean'")
    if roi_mapping is None:
        return {
            "rois": [],
            "n_rois": 0,
            "atlas": atlas,
            "warning": "No ROI mapping provided. Only channel-level results available.",
        }

    rois = []
    for roi_name, channel_indices in roi_mapping.items():
        selected_channels = [
            channel
            for channel in channel_results["channels"]
            if int(channel.get("channel_idx", -1)) in channel_indices
        ]
        roi_data = {"roi_name": roi_name, "n_channels": len(selected_channels)}
        for key in channel_results["channels"][0]:
            if key == "channel_idx":
                continue
            values = [
                channel[key]
                for channel in selected_channels
                if key in channel
            ]
            roi_data[f"{key}_mean"] = float(np.mean(values)) if values else 0.0
        rois.append(roi_data)

    return {
        "rois": rois,
        "n_rois": len(rois),
        "atlas": atlas,
        "aggregation": aggregation,
    }
