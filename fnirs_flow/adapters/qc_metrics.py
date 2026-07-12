"""Enhanced QC metrics: SCI, CV, SNR, saturation, source-detector distance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class QCMetricResult(BaseModel):
    """Result of a single QC metric."""

    metric_name: str
    channel: str
    value: float
    threshold: float
    status: str = Field(pattern="^(pass|warn|fail)$")
    rationale: str = ""


class ChannelQCReport(BaseModel):
    """QC report for a single channel."""

    channel: str
    subject: str = ""
    session: str = ""
    run: str = ""
    metrics: list[QCMetricResult] = Field(default_factory=list)
    overall_status: str = "pass"

    def update_overall(self) -> None:
        """Update overall status based on individual metrics."""
        if any(m.status == "fail" for m in self.metrics):
            self.overall_status = "fail"
        elif any(m.status == "warn" for m in self.metrics):
            self.overall_status = "warn"
        else:
            self.overall_status = "pass"


class QCThresholds(BaseModel):
    """QC thresholds from presets."""

    sci_min: float = 0.8
    cv_max: float = 0.15
    snr_min: float = 2.0
    saturation_max: float = 0.1
    sd_distance_min: float = 0.01
    sd_distance_max: float = 0.08


class QCMetricsCalculator:
    """Calculate QC metrics for fNIRS data."""

    def __init__(self, thresholds: QCThresholds | None = None) -> None:
        self._thresholds = thresholds or QCThresholds()

    def compute_sci(self, raw: Any, l_freq: float = 0.7, h_freq: float = 1.5) -> dict[str, float]:
        """Compute Scalp Coupling Index.

        Args:
            raw: MNE Raw object with fnirs_od channels
            l_freq: Low frequency for cardiac band
            h_freq: High frequency for cardiac band

        Returns:
            Dict of channel_name -> SCI value
        """
        try:
            from mne.preprocessing.nirs import scalp_coupling_index

            # Get SCI values (one per SD-pair)
            sci_values = scalp_coupling_index(raw, l_freq=l_freq, h_freq=h_freq)

            # Get channel pairing information from MNE
            # MNE returns channels grouped by SD-pair with alternating wavelengths
            result = {}

            # Use picks to get the correct channel ordering
            picks = raw.pick("fnirs_od", exclude=[])
            ch_names = [raw.ch_names[p] for p in picks]

            # MNE-NIRS returns SCI in SD-pair order
            # Each SD-pair has 2 channels (one per wavelength)
            n_pairs = len(sci_values)

            # Get pair information from channel names
            # Channel names follow pattern: S<source>_D<detector> <wavelength>
            pair_groups: dict[str, list[str]] = {}
            for ch in ch_names:
                # Extract SD-pair ID (e.g., "S1_D1" from "S1_D1 760")
                parts = ch.split()
                if len(parts) >= 1:
                    pair_id = parts[0]
                    if pair_id not in pair_groups:
                        pair_groups[pair_id] = []
                    pair_groups[pair_id].append(ch)

            # Assign SCI values to channels
            for i, (pair_id, channels) in enumerate(pair_groups.items()):
                if i < n_pairs:
                    sci = float(sci_values[i])
                    for ch in channels:
                        result[ch] = sci

            return result
        except ImportError:
            return {}

    def compute_cv(self, raw: Any) -> dict[str, float]:
        """Compute Coefficient of Variation.

        Args:
            raw: MNE Raw object

        Returns:
            Dict of channel_name -> CV value
        """
        import numpy as np

        data = raw.get_data()
        ch_names = raw.ch_names

        result = {}
        for i, ch in enumerate(ch_names):
            signal = data[i]
            mean_val = np.mean(np.abs(signal))
            if mean_val > 0:
                cv = np.std(signal) / mean_val
                result[ch] = float(cv)
            else:
                result[ch] = float("inf")

        return result

    def compute_snr(self, raw: Any) -> dict[str, float]:
        """Compute Signal-to-Noise Ratio.

        Uses the standard definition: SNR = mean(signal) / std(noise)
        where noise is estimated from high-frequency components.

        Args:
            raw: MNE Raw object

        Returns:
            Dict of channel_name -> SNR value (linear scale)
        """
        import numpy as np

        data = raw.get_data()
        ch_names = raw.ch_names

        result = {}
        for i, ch in enumerate(ch_names):
            signal = data[i]
            signal_mean = np.mean(np.abs(signal))
            # Estimate noise from first-difference (high-frequency component)
            noise_std = np.std(np.diff(signal))
            if noise_std > 0:
                snr = signal_mean / noise_std
                result[ch] = float(snr)
            else:
                result[ch] = float("inf")

        return result

    def compute_saturation(self, raw: Any, threshold: float = 0.95) -> dict[str, float]:
        """Compute saturation/dropout ratio.

        Args:
            raw: MNE Raw object
            threshold: Saturation threshold (ratio of max value)

        Returns:
            Dict of channel_name -> saturation ratio
        """
        import numpy as np

        data = raw.get_data()
        ch_names = raw.ch_names

        result = {}
        for i, ch in enumerate(ch_names):
            signal = data[i]
            max_val = np.max(np.abs(signal))
            if max_val > 0:
                saturated = np.sum(np.abs(signal) > threshold * max_val) / len(signal)
                result[ch] = float(saturated)
            else:
                result[ch] = 0.0

        return result

    def compute_sd_distances(self, info: Any) -> dict[str, float]:
        """Compute source-detector distances.

        Args:
            info: MNE Info object

        Returns:
            Dict of channel_name -> distance in meters
        """
        try:
            from mne.preprocessing.nirs import source_detector_distances

            # Get distances (one per SD-pair)
            distances = source_detector_distances(info)

            # Get fNIRS channel names
            fnirs_chs = [ch for ch in info.ch_names if "hbo" in ch.lower() or "hbr" in ch.lower()]

            # Group channels by SD-pair ID
            pair_groups: dict[str, list[str]] = {}
            for ch in fnirs_chs:
                # Extract SD-pair ID (e.g., "S1_D1" from "S1_D1 hbo")
                parts = ch.split()
                if len(parts) >= 1:
                    pair_id = parts[0]
                    if pair_id not in pair_groups:
                        pair_groups[pair_id] = []
                    pair_groups[pair_id].append(ch)

            # Assign distances to channels
            result = {}
            for i, (pair_id, channels) in enumerate(pair_groups.items()):
                if i < len(distances):
                    dist = float(distances[i])
                    for ch in channels:
                        result[ch] = dist

            return result
        except ImportError:
            return {}

    def evaluate_metric(self, name: str, value: float) -> QCMetricResult:
        """Evaluate a metric against thresholds.

        Args:
            name: Metric name
            value: Metric value

        Returns:
            QCMetricResult with pass/warn/fail status
        """
        thresholds = self._thresholds

        if name == "sci":
            if value >= thresholds.sci_min:
                status = "pass"
            elif value >= thresholds.sci_min * 0.8:
                status = "warn"
            else:
                status = "fail"
            return QCMetricResult(
                metric_name="SCI",
                channel="",
                value=value,
                threshold=thresholds.sci_min,
                status=status,
                rationale=f"SCI threshold: {thresholds.sci_min}",
            )
        elif name == "cv":
            if value <= thresholds.cv_max:
                status = "pass"
            elif value <= thresholds.cv_max * 1.5:
                status = "warn"
            else:
                status = "fail"
            return QCMetricResult(
                metric_name="CV",
                channel="",
                value=value,
                threshold=thresholds.cv_max,
                status=status,
                rationale=f"CV threshold: {thresholds.cv_max}",
            )
        elif name == "snr":
            if value >= thresholds.snr_min:
                status = "pass"
            elif value >= thresholds.snr_min * 0.7:
                status = "warn"
            else:
                status = "fail"
            return QCMetricResult(
                metric_name="SNR",
                channel="",
                value=value,
                threshold=thresholds.snr_min,
                status=status,
                rationale=f"SNR threshold: {thresholds.snr_min}",
            )
        elif name == "saturation":
            if value <= thresholds.saturation_max:
                status = "pass"
            elif value <= thresholds.saturation_max * 2:
                status = "warn"
            else:
                status = "fail"
            return QCMetricResult(
                metric_name="Saturation",
                channel="",
                value=value,
                threshold=thresholds.saturation_max,
                status=status,
                rationale=f"Saturation threshold: {thresholds.saturation_max}",
            )
        elif name == "sd_distance":
            if thresholds.sd_distance_min <= value <= thresholds.sd_distance_max:
                status = "pass"
            else:
                status = "warn"
            return QCMetricResult(
                metric_name="SD Distance",
                channel="",
                value=value,
                threshold=thresholds.sd_distance_max,
                status=status,
                rationale=(f"SD distance range: {thresholds.sd_distance_min}-{thresholds.sd_distance_max}m"),
            )
        else:
            return QCMetricResult(
                metric_name=name,
                channel="",
                value=value,
                threshold=0.0,
                status="pass",
            )

    def compute_full_report(
        self,
        raw: Any,
        subject: str = "",
        session: str = "",
        run: str = "",
    ) -> list[ChannelQCReport]:
        """Compute full QC report for all channels.

        Args:
            raw: MNE Raw object
            subject: Subject ID
            session: Session ID
            run: Run ID

        Returns:
            List of ChannelQCReport per channel
        """
        reports: list[ChannelQCReport] = []

        # Compute all metrics
        sci_values = self.compute_sci(raw)
        cv_values = self.compute_cv(raw)
        snr_values = self.compute_snr(raw)
        saturation_values = self.compute_saturation(raw)

        # Get unique channels
        ch_names = raw.ch_names

        for ch in ch_names:
            report = ChannelQCReport(
                channel=ch,
                subject=subject,
                session=session,
                run=run,
            )

            # SCI
            if ch in sci_values:
                metric = self.evaluate_metric("sci", sci_values[ch])
                metric.channel = ch
                report.metrics.append(metric)

            # CV
            if ch in cv_values:
                metric = self.evaluate_metric("cv", cv_values[ch])
                metric.channel = ch
                report.metrics.append(metric)

            # SNR
            if ch in snr_values:
                metric = self.evaluate_metric("snr", snr_values[ch])
                metric.channel = ch
                report.metrics.append(metric)

            # Saturation
            if ch in saturation_values:
                metric = self.evaluate_metric("saturation", saturation_values[ch])
                metric.channel = ch
                report.metrics.append(metric)

            report.update_overall()
            reports.append(report)

        return reports


def write_qc_report(reports: list[ChannelQCReport], outdir: Path) -> Path:
    """Write QC report to CSV file.

    Args:
        reports: List of ChannelQCReport
        outdir: Output directory

    Returns:
        Path to written file
    """
    import csv

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "qc_report.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "subject",
                "session",
                "run",
                "channel",
                "metric",
                "value",
                "threshold",
                "status",
            ]
        )

        for report in reports:
            for metric in report.metrics:
                writer.writerow(
                    [
                        report.subject,
                        report.session,
                        report.run,
                        report.channel,
                        metric.metric_name,
                        metric.value,
                        metric.threshold,
                        metric.status,
                    ]
                )

    return path
