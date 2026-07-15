"""Tests for QC metrics module."""

from __future__ import annotations

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
        assert report.overall_status == "pass"


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
        result = calc.evaluate_metric("unknown", 1.0)
        assert result.status == "pass"
        assert result.metric_name == "unknown"

    def test_custom_thresholds(self):
        thresholds = QCThresholds(sci_min=0.7)
        calc = QCMetricsCalculator(thresholds=thresholds)
        result = calc.evaluate_metric("sci", 0.75)
        assert result.status == "pass"
