"""Enhanced QC metrics: SCI, CV, SNR, saturation, source-detector distance."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


class QCMetricResult(BaseModel):
    """Result of a single QC metric."""

    metric_name: str
    channel: str
    value: float | None
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
    overall_status: str = Field(default="not_evaluated", pattern="^(pass|warn|fail|not_evaluated)$")

    def update_overall(self) -> None:
        """Update overall status based on individual metrics."""
        if any(m.status == "fail" for m in self.metrics):
            self.overall_status = "fail"
        elif any(m.status == "warn" for m in self.metrics):
            self.overall_status = "warn"
        elif not self.metrics:
            self.overall_status = "not_evaluated"
        else:
            self.overall_status = "pass"


class QCThresholds(BaseModel):
    """QC thresholds from presets."""

    sci_min: float = Field(default=0.8, ge=0.0, le=1.0)
    cv_max: float = Field(default=0.15, ge=0.0)
    snr_min: float = Field(default=2.0, ge=0.0)
    saturation_max: float = Field(default=0.1, ge=0.0, le=1.0)
    sd_distance_min: float = Field(default=0.01, ge=0.0)
    sd_distance_max: float = Field(default=0.08, ge=0.0)

    @model_validator(mode="after")
    def validate_distance_range(self) -> QCThresholds:
        if self.sd_distance_min > self.sd_distance_max:
            raise ValueError("sd_distance_min must not exceed sd_distance_max")
        return self


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

            # MNE returns one value per optical-density channel, in picked order.
            sci_values = scalp_coupling_index(raw, l_freq=l_freq, h_freq=h_freq)
            picked = raw.copy().pick("fnirs_od", exclude=[])
            ch_names = list(picked.ch_names)
            if len(sci_values) != len(ch_names):
                raise ValueError(
                    f"SCI result length {len(sci_values)} does not match {len(ch_names)} optical-density channels"
                )
            return {channel: float(value) for channel, value in zip(ch_names, sci_values, strict=True)}
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
            if signal.size == 0 or not np.isfinite(signal).all():
                result[ch] = float("nan")
                continue
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
            if signal.size < 2 or not np.isfinite(signal).all():
                result[ch] = float("nan")
                continue
            signal_mean = np.mean(np.abs(signal))
            # Estimate noise from first-difference (high-frequency component)
            noise_std = np.std(np.diff(signal))
            if noise_std > 0:
                snr = signal_mean / noise_std
                result[ch] = float(snr)
            else:
                result[ch] = 0.0

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
            if signal.size == 0 or not np.isfinite(signal).all():
                result[ch] = float("nan")
                continue
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
            from mne import pick_types
            from mne.preprocessing.nirs import source_detector_distances

            picks = pick_types(info, fnirs=True, exclude=[])
            distances = source_detector_distances(info, picks=picks)
            ch_names = [info.ch_names[int(pick)] for pick in picks]
            if len(distances) != len(ch_names):
                raise ValueError(
                    f"Distance result length {len(distances)} does not match {len(ch_names)} fNIRS channels"
                )
            return {channel: float(value) for channel, value in zip(ch_names, distances, strict=True)}
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

        metric_metadata = {
            "sci": ("SCI", thresholds.sci_min, f"SCI threshold: {thresholds.sci_min}"),
            "cv": ("CV", thresholds.cv_max, f"CV threshold: {thresholds.cv_max}"),
            "snr": ("SNR", thresholds.snr_min, f"SNR threshold: {thresholds.snr_min}"),
            "saturation": (
                "Saturation",
                thresholds.saturation_max,
                f"Saturation threshold: {thresholds.saturation_max}",
            ),
            "sd_distance": (
                "SD Distance",
                thresholds.sd_distance_max,
                f"SD distance range: {thresholds.sd_distance_min}-{thresholds.sd_distance_max}m",
            ),
        }
        if name not in metric_metadata:
            raise ValueError(f"Unknown QC metric: {name}")
        if not math.isfinite(value):
            metric_name, threshold, rationale = metric_metadata[name]
            return QCMetricResult(
                metric_name=metric_name,
                channel="",
                value=None,
                threshold=threshold,
                status="fail",
                rationale=f"{rationale}; metric is non-finite or unavailable",
            )

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
        raise AssertionError(f"Unhandled QC metric: {name}")

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
        sd_distance_values = self.compute_sd_distances(raw.info)

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

            if ch in sd_distance_values:
                metric = self.evaluate_metric("sd_distance", sd_distance_values[ch])
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
