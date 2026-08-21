"""Tests for QC metrics module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from fnirs_flow.adapters.qc_metrics import (
    ChannelQCReport,
    QCMetricResult,
    QCMetricsCalculator,
    QCThresholds,
)


class TestQCMetricResult:
    def test_valid_result(self):
        r = QCMetricResult(
            metric_name="sci",
            channel="S1_D1",
            value=0.9,
            threshold=0.8,
            status="pass",
        )
        assert r.status == "pass"
        assert r.value == 0.9

    def test_warn_status(self):
        r = QCMetricResult(
            metric_name="sci",
            channel="S1_D1",
            value=0.7,
            threshold=0.8,
            status="warn",
        )
        assert r.status == "warn"

    def test_fail_status(self):
        r = QCMetricResult(
            metric_name="sci",
            channel="S1_D1",
            value=0.5,
            threshold=0.8,
            status="fail",
        )
        assert r.status == "fail"

    def test_invalid_status(self):
        with pytest.raises(Exception):
            QCMetricResult(
                metric_name="sci",
                channel="S1_D1",
                value=0.5,
                threshold=0.8,
                status="invalid",
            )


class TestChannelQCReport:
    def test_update_overall_fail(self):
        report = ChannelQCReport(channel="S1_D1")
        report.metrics = [
            QCMetricResult(
                metric_name="sci", channel="S1_D1",
                value=0.5, threshold=0.8, status="fail",
            ),
            QCMetricResult(
                metric_name="cv", channel="S1_D1",
                value=0.1, threshold=0.15, status="pass",
            ),
        ]
        report.update_overall()
        assert report.overall_status == "fail"

    def test_update_overall_warn(self):
        report = ChannelQCReport(channel="S1_D1")
        report.metrics = [
            QCMetricResult(
                metric_name="sci", channel="S1_D1",
                value=0.7, threshold=0.8, status="warn",
            ),
            QCMetricResult(
                metric_name="cv", channel="S1_D1",
                value=0.1, threshold=0.15, status="pass",
            ),
        ]
        report.update_overall()
        assert report.overall_status == "warn"

    def test_update_overall_pass(self):
        report = ChannelQCReport(channel="S1_D1")
        report.metrics = [
            QCMetricResult(
                metric_name="sci", channel="S1_D1",
                value=0.9, threshold=0.8, status="pass",
            ),
        ]
        report.update_overall()
        assert report.overall_status == "pass"

    def test_update_overall_empty(self):
        report = ChannelQCReport(channel="S1_D1")
        report.update_overall()
        assert report.overall_status == "not_evaluated"


class TestQCThresholds:
    def test_defaults(self):
        t = QCThresholds()
        assert t.sci_min == 0.8
        assert t.cv_max == 0.15
        assert t.snr_min == 2.0
        assert t.saturation_max == 0.1
        assert t.sd_distance_min == 0.01
        assert t.sd_distance_max == 0.08

    def test_custom_thresholds(self):
        t = QCThresholds(sci_min=0.7, cv_max=0.2)
        assert t.sci_min == 0.7
        assert t.cv_max == 0.2

    def test_rejects_invalid_threshold_ranges(self):
        with pytest.raises(ValueError):
            QCThresholds(sci_min=1.1)
        with pytest.raises(ValueError, match="sd_distance_min"):
            QCThresholds(sd_distance_min=0.09, sd_distance_max=0.08)


class TestQCMetricsCalculator:
    def test_evaluate_sci_pass(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("sci", 0.9)
        assert result.status == "pass"
        assert result.metric_name == "SCI"

    def test_evaluate_sci_warn(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("sci", 0.7)
        assert result.status == "warn"

    def test_evaluate_sci_fail(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("sci", 0.5)
        assert result.status == "fail"

    def test_evaluate_cv_pass(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("cv", 0.1)
        assert result.status == "pass"

    def test_evaluate_cv_warn(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("cv", 0.2)
        assert result.status == "warn"

    def test_evaluate_cv_fail(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("cv", 0.3)
        assert result.status == "fail"

    def test_evaluate_snr_pass(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("snr", 3.0)
        assert result.status == "pass"

    def test_evaluate_snr_warn(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("snr", 1.6)
        assert result.status == "warn"

    def test_evaluate_snr_fail(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("snr", 1.0)
        assert result.status == "fail"

    def test_evaluate_saturation_pass(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("saturation", 0.05)
        assert result.status == "pass"

    def test_evaluate_saturation_warn(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("saturation", 0.15)
        assert result.status == "warn"

    def test_evaluate_saturation_fail(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("saturation", 0.3)
        assert result.status == "fail"

    def test_evaluate_sd_distance_pass(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("sd_distance", 0.03)
        assert result.status == "pass"

    def test_evaluate_sd_distance_warn(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("sd_distance", 0.1)
        assert result.status == "warn"

    def test_evaluate_unknown_metric(self):
        calc = QCMetricsCalculator()
        with pytest.raises(ValueError, match="Unknown QC metric"):
            calc.evaluate_metric("unknown", 1.0)

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_nonfinite_metric_fails_without_serializing_nonfinite_number(self, value):
        result = QCMetricsCalculator().evaluate_metric("sci", value)
        assert result.status == "fail"
        assert result.value is None

    def test_compute_sci_maps_each_channel_and_does_not_mutate_raw(self):
        raw = MagicMock()
        picked = MagicMock()
        picked.ch_names = ["S1_D1 760", "S1_D1 850", "S2_D1 760", "S2_D1 850"]
        picked.pick.return_value = picked
        raw.copy.return_value = picked

        with patch("mne.preprocessing.nirs.scalp_coupling_index", return_value=np.array([0.9, 0.9, 0.4, 0.4])):
            result = QCMetricsCalculator().compute_sci(raw)

        assert result == dict(zip(picked.ch_names, [0.9, 0.9, 0.4, 0.4], strict=True))
        raw.pick.assert_not_called()
        raw.copy.assert_called_once()
        picked.pick.assert_called_once_with("fnirs_od", exclude=[])

    def test_nonfinite_and_short_signals_produce_failed_metrics(self):
        raw = MagicMock()
        raw.ch_names = ["nan", "short"]
        raw.get_data.return_value = np.array([[1.0, np.nan], [1.0, 1.0]])
        calc = QCMetricsCalculator()

        cv = calc.compute_cv(raw)
        snr = calc.compute_snr(raw)

        assert calc.evaluate_metric("cv", cv["nan"]).status == "fail"
        assert calc.evaluate_metric("snr", snr["short"]).status == "fail"

    def test_custom_thresholds(self):
        thresholds = QCThresholds(sci_min=0.7)
        calc = QCMetricsCalculator(thresholds=thresholds)
        result = calc.evaluate_metric("sci", 0.75)
        assert result.status == "pass"
