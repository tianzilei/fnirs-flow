"""MNE-NIRS preprocessing and quality-control operations."""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = [
    "beer_lambert_law",
    "cbsi_motion_correction",
    "compute_coefficient_of_variation",
    "compute_snr",
    "detect_bad_channels",
    "filter_raw",
    "ica_motion_correction",
    "notch_filter",
    "optical_density",
    "pca_motion_correction",
    "scalp_coupling_index",
    "short_channel_regression",
    "short_channels",
    "source_detector_distances",
    "spline_motion_correction",
    "temporal_derivative_distribution_repair",
    "wavelet_motion_correction",
]

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
        data = sosfiltfilt(sos, raw.get_data(), axis=-1)
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
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError("QC data must be a 2D channels-by-samples array")
    n_channels = data.shape[0]
    cv_values = np.zeros(n_channels)

    for ch in range(n_channels):
        signal = data[ch, :]
        if signal.size == 0 or not np.isfinite(signal).all():
            cv_values[ch] = np.inf
            continue
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

    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError("QC data must be a 2D channels-by-samples array")
    if not np.isfinite(fs) or fs <= 0:
        raise ValueError("Sampling frequency must be finite and positive")
    n_channels = data.shape[0]
    snr_values = np.full(n_channels, -np.inf)

    nyquist = fs / 2.0
    signal_high = min(float(signal_band[1]), np.nextafter(nyquist, 0.0))
    noise_high = min(float(noise_band[1]), np.nextafter(nyquist, 0.0))
    if not 0 < signal_band[0] < signal_high or not 0 < noise_band[0] < noise_high:
        return snr_values

    # Design filters
    b_signal, a_signal = butter(4, [signal_band[0], signal_high], btype="band", fs=fs)
    b_noise, a_noise = butter(4, [noise_band[0], noise_high], btype="band", fs=fs)
    min_samples = 3 * max(len(a_signal), len(b_signal), len(a_noise), len(b_noise))

    for ch in range(n_channels):
        if data.shape[1] <= min_samples or not np.isfinite(data[ch, :]).all():
            continue
        signal_filtered = filtfilt(b_signal, a_signal, data[ch, :])
        noise_filtered = filtfilt(b_noise, a_noise, data[ch, :])

        signal_power = np.mean(signal_filtered**2)
        noise_power = np.mean(noise_filtered**2)

        if np.isfinite(signal_power) and np.isfinite(noise_power) and signal_power > 0 and noise_power > 0:
            snr_values[ch] = 10 * np.log10(signal_power / noise_power)

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
    data = np.asarray(data, dtype=float)
    if data.ndim != 2:
        raise ValueError("QC data must be a 2D channels-by-samples array")
    n_channels = data.shape[0]

    # Compute CV
    cv_values = compute_coefficient_of_variation(data)
    invalid_data = ~np.isfinite(data).all(axis=1) if data.shape[1] else np.ones(n_channels, dtype=bool)
    cv_bad = ~np.isfinite(cv_values) | (cv_values > cv_threshold)

    # Compute SNR
    snr_values = compute_snr(data)
    snr_bad = ~np.isfinite(snr_values) | (snr_values < snr_threshold)

    # SCI-based detection
    sci_bad = np.zeros(n_channels, dtype=bool)
    if sci_values is not None:
        sci_values = np.asarray(sci_values, dtype=float)
        if sci_values.shape != (n_channels,):
            raise ValueError(
                f"SCI values must contain one value per channel: expected {n_channels}, got {sci_values.size}"
            )
        sci_bad = ~np.isfinite(sci_values) | (sci_values < sci_threshold)

    # Combine bad channel masks
    bad_mask = invalid_data | cv_bad | snr_bad | sci_bad

    return {
        "bad_mask": bad_mask,
        "cv_values": cv_values,
        "snr_values": snr_values,
        "sci_values": sci_values,
        "cv_bad": cv_bad,
        "snr_bad": snr_bad,
        "sci_bad": sci_bad,
        "n_bad": int(bad_mask.sum()),
        "bad_percentage": float(bad_mask.sum() / n_channels * 100) if n_channels else 0.0,
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
