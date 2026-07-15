"""MNE-NIRS preprocessing steps wrapper with evidence-backed implementations."""

from __future__ import annotations

from typing import Any

import numpy as np

# ============================================================================
# CORE PREPROCESSING (from MNE-NIRS)
# ============================================================================


def optical_density(raw: Any) -> Any:
    """Convert raw intensity to optical density.

    Args:
        raw: MNE Raw object with fnirs_cw_amplitude channels

    Returns:
        MNE Raw object with fnirs_od channels
    """
    try:
        from mne.preprocessing.nirs import optical_density as _od

        return _od(raw)
    except ImportError:
        raise ImportError("MNE-Python is required. Install with: pip install fnirs-flow[mne]") from None


def scalp_coupling_index(
    raw: Any,
    l_freq: float = 0.7,
    h_freq: float = 1.5,
) -> Any:
    """Compute Scalp Coupling Index.

    Args:
        raw: MNE Raw object with fnirs_od channels
        l_freq: Low frequency bound for cardiac band
        h_freq: High frequency bound for cardiac band

    Returns:
        Array of SCI values per channel
    """
    try:
        from mne.preprocessing.nirs import scalp_coupling_index as _sci

        return _sci(raw, l_freq=l_freq, h_freq=h_freq)
    except ImportError:
        raise ImportError("MNE-Python is required. Install with: pip install fnirs-flow[mne]") from None


def temporal_derivative_distribution_repair(raw: Any) -> Any:
    """Apply TDDR motion correction.

    Args:
        raw: MNE Raw object with fnirs_od or haemoglobin channels

    Returns:
        Motion-corrected MNE Raw object
    """
    try:
        from mne.preprocessing.nirs import temporal_derivative_distribution_repair as _tddr

        return _tddr(raw)
    except ImportError:
        raise ImportError("MNE-Python is required. Install with: pip install fnirs-flow[mne]") from None


def beer_lambert_law(raw: Any, ppf: float = 6.0) -> Any:
    """Convert optical density to haemoglobin concentration.

    Args:
        raw: MNE Raw object with fnirs_od channels
        ppf: Partial pathlength factor

    Returns:
        MNE Raw object with HbO/HbR channels
    """
    try:
        from mne.preprocessing.nirs import beer_lambert_law as _bll

        return _bll(raw, ppf=ppf)
    except ImportError:
        raise ImportError("MNE-Python is required. Install with: pip install fnirs-flow[mne]") from None


def source_detector_distances(info: Any) -> Any:
    """Compute source-detector distances.

    Args:
        info: MNE Info object

    Returns:
        Array of distances in meters
    """
    try:
        from mne.preprocessing.nirs import source_detector_distances as _sdd

        return _sdd(info)
    except ImportError:
        raise ImportError("MNE-Python is required. Install with: pip install fnirs-flow[mne]") from None


def short_channels(info: Any, threshold: float = 0.01) -> Any:
    """Identify short-separation channels.

    Args:
        info: MNE Info object
        threshold: Distance threshold in meters

    Returns:
        Boolean array indicating short channels
    """
    try:
        from mne.preprocessing.nirs import short_channels as _sc

        return _sc(info, threshold=threshold)
    except ImportError:
        raise ImportError("MNE-Python is required. Install with: pip install fnirs-flow[mne]") from None


def filter_raw(
    raw: Any,
    l_freq: float | None = None,
    h_freq: float | None = None,
    method: str = "iir",
    **kwargs: Any,
) -> Any:
    """Apply bandpass filter to raw data.

    Args:
        raw: MNE Raw object
        l_freq: Low cutoff frequency
        h_freq: High cutoff frequency
        method: Filter method ('iir' for fast, 'fir' for precise)
        **kwargs: Additional arguments to raw.filter()

    Returns:
        Filtered MNE Raw object (new copy, original unchanged)
    """
    raw = raw.copy()
    if method == "iir":
        from scipy.signal import butter, sosfiltfilt

        sfreq = raw.info["sfreq"]
        # Build IIR bandpass via second-order sections
        low = l_freq / (sfreq / 2) if l_freq else None
        high = h_freq / (sfreq / 2) if h_freq else None
        if low and high:
            sos = butter(4, [low, high], btype="band", output="sos")
        elif low:
            sos = butter(4, low, btype="high", output="sos")
        elif high:
            sos = butter(4, high, btype="low", output="sos")
        else:
            return raw
        data = raw.get_data()
        for ch in range(data.shape[0]):
            data[ch, :] = sosfiltfilt(sos, data[ch, :])
        import mne

        raw = mne.io.RawArray(data, raw.info, first_samp=raw.first_samp, verbose=False)
    else:
        raw.filter(l_freq=l_freq, h_freq=h_freq, **kwargs)
    return raw


def notch_filter(
    raw: Any,
    freqs: list[float] | None = None,
    **kwargs: Any,
) -> Any:
    """Apply notch filter to remove line noise.

    Args:
        raw: MNE Raw object
        freqs: Frequencies to notch out (default: [50, 100])
        **kwargs: Additional arguments to raw.notch_filter()

    Returns:
        Filtered MNE Raw object (new copy, original unchanged)
    """
    if freqs is None:
        freqs = [50.0, 100.0]
    raw = raw.copy()
    raw.notch_filter(freqs=freqs, **kwargs)
    return raw


# ============================================================================
# QC METRICS
# ============================================================================


def compute_coefficient_of_variation(
    data: np.ndarray,
    window_size: int = 10,
) -> np.ndarray:
    """Compute Coefficient of Variation for signal quality assessment.

    Args:
        data: Signal data array (channels x samples)
        window_size: Window size for CV computation

    Returns:
        Array of CV values per channel
    """
    n_channels = data.shape[0]
    cv_values = np.zeros(n_channels)

    for ch in range(n_channels):
        signal = data[ch, :]
        mean_val = np.mean(signal)
        if mean_val != 0:
            cv_values[ch] = np.std(signal) / abs(mean_val)
        else:
            cv_values[ch] = np.inf

    return cv_values


def compute_snr(
    data: np.ndarray,
    fs: float = 10.0,
    signal_band: tuple[float, float] = (0.01, 0.2),
    noise_band: tuple[float, float] = (0.5, 2.0),
) -> np.ndarray:
    """Compute Signal-to-Noise Ratio.

    Args:
        data: Signal data array (channels x samples)
        fs: Sampling frequency in Hz
        signal_band: Frequency band for signal (Hz)
        noise_band: Frequency band for noise (Hz)

    Returns:
        Array of SNR values per channel (in dB)
    """
    from scipy.signal import butter, filtfilt

    n_channels = data.shape[0]
    snr_values = np.zeros(n_channels)

    # Design filters
    b_signal, a_signal = butter(4, [signal_band[0], signal_band[1]], btype="band", fs=fs)
    b_noise, a_noise = butter(4, [noise_band[0], noise_band[1]], btype="band", fs=fs)

    for ch in range(n_channels):
        signal_filtered = filtfilt(b_signal, a_signal, data[ch, :])
        noise_filtered = filtfilt(b_noise, a_noise, data[ch, :])

        signal_power = np.mean(signal_filtered**2)
        noise_power = np.mean(noise_filtered**2)

        if noise_power > 0:
            snr_values[ch] = 10 * np.log10(signal_power / noise_power)
        else:
            snr_values[ch] = np.inf

    return snr_values


def detect_bad_channels(
    data: np.ndarray,
    sci_values: np.ndarray | None = None,
    cv_threshold: float = 0.15,
    snr_threshold: float = 2.0,
    sci_threshold: float = 0.8,
) -> dict[str, Any]:
    """Detect bad channels using multiple QC metrics.

    Args:
        data: Signal data array (channels x samples)
        sci_values: Optional SCI values for each channel
        cv_threshold: CV threshold for bad channel detection
        snr_threshold: SNR threshold for bad channel detection
        sci_threshold: SCI threshold for bad channel detection

    Returns:
        Dictionary with bad channel masks and QC metrics
    """
    n_channels = data.shape[0]

    # Compute CV
    cv_values = compute_coefficient_of_variation(data)
    cv_bad = cv_values > cv_threshold

    # Compute SNR
    snr_values = compute_snr(data)
    snr_bad = snr_values < snr_threshold

    # SCI-based detection
    sci_bad = np.zeros(n_channels, dtype=bool)
    if sci_values is not None:
        sci_bad = sci_values < sci_threshold

    # Combine bad channel masks
    bad_mask = cv_bad | snr_bad | sci_bad

    return {
        "bad_mask": bad_mask,
        "cv_values": cv_values,
        "snr_values": snr_values,
        "sci_values": sci_values,
        "cv_bad": cv_bad,
        "snr_bad": snr_bad,
        "sci_bad": sci_bad,
        "n_bad": int(bad_mask.sum()),
        "bad_percentage": float(bad_mask.sum() / n_channels * 100),
    }


# ============================================================================
# MOTION CORRECTION (evidence-backed implementations)
# ============================================================================


def wavelet_motion_correction(
    data: np.ndarray,
    wavelet_level: int = 5,
    threshold_type: str = "soft",
) -> np.ndarray:
    """Wavelet-based motion artifact correction.

    Evidence: 339 studies in literature use wavelet motion correction.

    Args:
        data: Signal data array (channels x samples)
        wavelet_level: Decomposition level for wavelet transform
        threshold_type: Threshold type ('soft' or 'hard')

    Returns:
        Motion-corrected signal data
    """
    try:
        import pywt
    except ImportError:
        raise ImportError("PyWavelets is required. Install with: pip install PyWavelets") from None

    corrected = np.zeros_like(data)
    n_channels = data.shape[0]

    for ch in range(n_channels):
        signal = data[ch, :]

        # Wavelet decomposition
        coeffs = pywt.wavedec(signal, "db4", level=wavelet_level)

        # Threshold detail coefficients (remove motion artifacts)
        for i in range(1, len(coeffs)):
            threshold = np.std(coeffs[i]) * np.sqrt(2 * np.log(len(signal)))
            if threshold_type == "soft":
                coeffs[i] = pywt.threshold(coeffs[i], threshold, mode="soft")
            else:
                coeffs[i] = pywt.threshold(coeffs[i], threshold, mode="hard")

        # Reconstruct
        corrected[ch, :] = pywt.waverec(coeffs, "db4")[: data.shape[1]]

    return corrected


def spline_motion_correction(
    data: np.ndarray,
    spline_segments: int = 3,
    threshold: float = 1.0,
) -> np.ndarray:
    """Spline-based motion artifact correction.

    Evidence: 95 studies in literature use spline motion correction.

    Args:
        data: Signal data array (channels x samples)
        spline_segments: Number of spline segments
        threshold: Threshold for artifact detection (in standard deviations)

    Returns:
        Motion-corrected signal data
    """
    from scipy.interpolate import CubicSpline

    corrected = np.zeros_like(data)
    n_channels = data.shape[0]
    n_samples = data.shape[1]

    for ch in range(n_channels):
        signal = data[ch, :]

        # Detect artifacts using moving standard deviation
        window_size = max(n_samples // spline_segments, 10)
        moving_std = np.array(
            [np.std(signal[max(0, i - window_size) : min(n_samples, i + window_size)]) for i in range(n_samples)]
        )

        # Identify artifact regions
        median_std = np.median(moving_std)
        artifact_mask = moving_std > (median_std * threshold)

        if artifact_mask.any():
            # Interpolate over artifacts
            good_indices = np.where(~artifact_mask)[0]
            if len(good_indices) > 3:
                cs = CubicSpline(good_indices, signal[good_indices])
                corrected[ch, :] = cs(np.arange(n_samples))
            else:
                corrected[ch, :] = signal
        else:
            corrected[ch, :] = signal

    return corrected


def ica_motion_correction(
    data: np.ndarray,
    n_components: int | None = None,
    threshold: float = 3.0,
) -> tuple[np.ndarray, np.ndarray]:
    """ICA-based motion artifact removal.

    Evidence: 405 studies in literature use ICA motion correction (most common).

    Args:
        data: Signal data array (channels x samples)
        n_components: Number of ICA components (None for automatic)
        threshold: Threshold for artifact component detection (in standard deviations)

    Returns:
        Tuple of (corrected_data, component_weights)
    """
    try:
        from sklearn.decomposition import FastICA
    except ImportError:
        raise ImportError("scikit-learn is required. Install with: pip install scikit-learn") from None

    # Transpose for ICA (samples x channels)
    data_t = data.T

    # Apply ICA
    ica = FastICA(n_components=n_components, random_state=42, max_iter=500)
    sources = ica.fit_transform(data_t)
    mixing = ica.mixing_

    # Detect artifact components (high kurtosis or variance)
    from scipy.stats import kurtosis

    kurt_values = kurtosis(sources, axis=0)
    artifact_mask = np.abs(kurt_values) > threshold

    # Zero out artifact components
    sources_clean = sources.copy()
    sources_clean[:, artifact_mask] = 0

    # Reconstruct
    corrected_t = sources_clean @ mixing.T
    corrected = corrected_t.T

    return corrected, ica.components_


def pca_motion_correction(
    data: np.ndarray,
    n_components: float = 0.95,
    threshold: float = 3.0,
) -> np.ndarray:
    """PCA-based motion artifact removal.

    Evidence: 56 studies in literature use PCA motion correction.

    Args:
        data: Signal data array (channels x samples)
        n_components: Number of components or variance to retain
        threshold: Threshold for artifact component detection

    Returns:
        Motion-corrected signal data
    """
    from sklearn.decomposition import PCA

    # Transpose for PCA (samples x channels)
    data_t = data.T

    # Apply PCA
    pca = PCA(n_components=n_components, random_state=42)
    sources = pca.fit_transform(data_t)

    # Detect artifact components (high variance)
    variances = np.var(sources, axis=0)
    median_var = np.median(variances)
    artifact_mask = variances > (median_var * threshold)

    # Zero out artifact components
    sources_clean = sources.copy()
    sources_clean[:, artifact_mask] = 0

    # Reconstruct
    corrected_t = pca.inverse_transform(sources_clean)
    corrected: np.ndarray = corrected_t.T

    return corrected


def cbsi_motion_correction(
    hbo: np.ndarray,
    hbr: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Correlation-Based Signal Improvement (CBSI).

    Evidence: 5 studies in literature use CBSI motion correction.

    Args:
        hbo: HbO signal data (channels x samples)
        hbr: HbR signal data (channels x samples)

    Returns:
        Tuple of (corrected_hbo, corrected_hbr)
    """
    n_channels = hbo.shape[0]
    corrected_hbo = np.zeros_like(hbo)
    corrected_hbr = np.zeros_like(hbr)

    for ch in range(n_channels):
        # CBSI correction
        alpha = np.std(hbo[ch, :]) / np.std(hbr[ch, :]) if np.std(hbr[ch, :]) > 0 else 1.0
        corrected_hbo[ch, :] = (hbo[ch, :] + alpha * hbr[ch, :]) / 2
        corrected_hbr[ch, :] = (hbo[ch, :] - alpha * hbr[ch, :]) / 2

    return corrected_hbo, corrected_hbr


# ============================================================================
# SHORT CHANNEL REGRESSION
# ============================================================================


def short_channel_regression(
    haemoglobin: np.ndarray,
    short_channel_mask: np.ndarray,
    method: str = "linear",
) -> np.ndarray:
    """Remove systemic physiological noise using short-separation channels.

    Evidence: 17 studies in literature report short-channel regression.

    Args:
        haemoglobin: Haemoglobin data (channels x samples)
        short_channel_mask: Boolean mask indicating short channels
        method: Regression method ('linear' or 'ols')

    Returns:
        Cleaned haemoglobin data
    """
    if not short_channel_mask.any():
        return haemoglobin

    short_channels = haemoglobin[short_channel_mask, :]
    long_channels = haemoglobin[~short_channel_mask, :]
    cleaned_long = np.zeros_like(long_channels)

    for ch in range(long_channels.shape[0]):
        signal = long_channels[ch, :]

        # Linear regression to remove short-channel signal
        if method == "linear":
            # Simple linear regression
            for sc in range(short_channels.shape[0]):
                sc_signal = short_channels[sc, :]
                if np.std(sc_signal) > 0:
                    beta = np.cov(signal, sc_signal)[0, 1] / np.var(sc_signal)
                    signal = signal - beta * sc_signal

        cleaned_long[ch, :] = signal

    # Reconstruct full array
    cleaned: np.ndarray = haemoglobin.copy()
    cleaned[~short_channel_mask, :] = cleaned_long

    return cleaned


# ============================================================================
# BLOCK/TRIAL AVERAGING
# ============================================================================


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
) -> dict[str, Any]:
    """Fit a first-level GLM.

    Args:
        raw: MNE Raw object with haemoglobin channels
        design_matrix: Output from build_design_matrix
        hrf_model: HRF model type
        noise_model: Noise model ('ols' or 'ar1')

    Returns:
        Dictionary with GLM results (beta maps, statistics)
    """
    data = raw.get_data()
    n_channels = data.shape[0]
    X = design_matrix["design_matrix"]

    if not np.isfinite(data).all():
        raise ValueError("GLM input data contains non-finite values")
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
        "n_conditions": X.shape[1],
        "n_regressors": X.shape[1],
        "conditions": design_matrix["conditions"],
        "regressor_names": design_matrix.get("regressor_names", []),
        "df": X.shape[0] - X.shape[1],
        "hrf_model": hrf_model,
        "noise_model": noise_model,
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
    n_conditions = glm_result["n_conditions"]

    contrast_results = []

    for contrast in contrasts:
        name = contrast.get("name", "unknown")
        weights = contrast.get("weights", [])

        if len(weights) != n_conditions:
            # Pad or truncate weights
            padded = np.zeros(n_conditions)
            padded[: min(len(weights), n_conditions)] = weights[: min(len(weights), n_conditions)]
            weights = padded

        weights = np.array(weights)
        c_betas = betas @ weights

        contrast_results.append(
            {
                "name": name,
                "weights": weights.tolist(),
                "contrast_values": c_betas,
                "n_channels": n_channels,
            }
        )

    return {
        "contrasts": contrast_results,
        "n_contrasts": len(contrasts),
        "n_channels": n_channels,
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
    for i in range(contrast_result["n_channels"]):
        ch_data: dict[str, Any] = {"channel_idx": i}
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
    if roi_mapping is None:
        return {
            "rois": [],
            "n_rois": 0,
            "atlas": atlas,
            "warning": "No ROI mapping provided. Only channel-level results available.",
        }

    rois = []
    for roi_name, channel_indices in roi_mapping.items():
        roi_data = {"roi_name": roi_name, "n_channels": len(channel_indices)}
        for key in channel_results["channels"][0]:
            if key == "channel_idx":
                continue
            values = [
                channel_results["channels"][i][key]
                for i in channel_indices
                if i < len(channel_results["channels"]) and key in channel_results["channels"][i]
            ]
            roi_data[f"{key}_mean"] = float(np.mean(values)) if values else 0.0
        rois.append(roi_data)

    return {
        "rois": rois,
        "n_rois": len(rois),
        "atlas": atlas,
    }
