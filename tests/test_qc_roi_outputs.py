"""Tests for QC metrics, ROI mapping, and output export."""

from __future__ import annotations

from fnirs_flow.adapters.qc_metrics import (
    ChannelQCReport,
    QCMetricResult,
    QCMetricsCalculator,
    QCThresholds,
    write_qc_report,
)
from fnirs_flow.adapters.roi_mapping import (
    ROIDefinition,
    ROIMappingManager,
    aggregate_roi_data,
)
from fnirs_flow.exporters.outputs import (
    ChannelResult,
    GroupSummary,
    ROIResult,
    compute_group_statistics,
    export_channel_results,
    export_group_summary,
    export_roi_results,
)


class TestQCMetrics:
    def test_thresholds(self):
        t = QCThresholds()
        assert t.sci_min == 0.8
        assert t.cv_max == 0.15

    def test_evaluate_sci_pass(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("sci", 0.9)
        assert result.status == "pass"
        assert result.value == 0.9

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

    def test_evaluate_cv_fail(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("cv", 0.5)
        assert result.status == "fail"

    def test_evaluate_snr_pass(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("snr", 5.0)
        assert result.status == "pass"

    def test_evaluate_snr_fail(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("snr", 0.5)
        assert result.status == "fail"

    def test_evaluate_saturation_pass(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("saturation", 0.05)
        assert result.status == "pass"

    def test_evaluate_sd_distance_pass(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("sd_distance", 0.03)
        assert result.status == "pass"

    def test_evaluate_sd_distance_warn(self):
        calc = QCMetricsCalculator()
        result = calc.evaluate_metric("sd_distance", 0.1)
        assert result.status == "warn"

    def test_write_qc_report(self, tmp_path):
        reports = [
            ChannelQCReport(
                channel="S1_D1 hbo",
                subject="01",
                metrics=[
                    QCMetricResult(
                        metric_name="SCI",
                        channel="S1_D1 hbo",
                        value=0.9,
                        threshold=0.8,
                        status="pass",
                    ),
                ],
                overall_status="pass",
            ),
        ]
        path = write_qc_report(reports, tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "S1_D1 hbo" in content


class TestROIMapping:
    def test_create_mapping(self):
        mgr = ROIMappingManager()
        mapping = mgr.create_mapping("test", "Test Mapping")
        assert mapping.mapping_id == "test"
        assert len(mapping.rois) == 0

    def test_add_roi(self):
        mgr = ROIMappingManager()
        mgr.create_mapping("test")
        roi = ROIDefinition(roi_id="roi1", name="ROI 1", channels=["ch1", "ch2"])
        assert mgr.add_roi("test", roi)
        mapping = mgr.get_mapping("test")
        assert len(mapping.rois) == 1

    def test_create_from_template(self):
        mgr = ROIMappingManager()
        mapping = mgr.create_from_template("motor", "motor")
        assert mapping is not None
        assert len(mapping.rois) == 2

    def test_create_from_user_mapping(self):
        mgr = ROIMappingManager()
        pairs = [
            ("S1_D1 hbo", "Left Motor"),
            ("S1_D2 hbo", "Left Motor"),
            ("S2_D1 hbo", "Right Motor"),
        ]
        mapping = mgr.create_from_user_mapping("user", pairs)
        assert len(mapping.rois) == 2

    def test_assign_channels(self):
        mgr = ROIMappingManager()
        mgr.create_from_template("motor", "motor")
        assert mgr.assign_channels("motor", "left_motor", ["ch1", "ch2"])

    def test_validate_mapping(self):
        mgr = ROIMappingManager()
        mgr.create_from_template("motor", "motor")
        mgr.assign_channels("motor", "left_motor", ["ch1", "ch2"])
        warnings = mgr.validate_mapping("motor", ["ch1", "ch2", "ch3"])
        assert len(warnings) == 0

    def test_validate_missing_channel(self):
        mgr = ROIMappingManager()
        mgr.create_from_template("motor", "motor")
        mgr.assign_channels("motor", "left_motor", ["ch1", "missing"])
        warnings = mgr.validate_mapping("motor", ["ch1", "ch2"])
        assert any("missing" in w for w in warnings)

    def test_aggregate_roi_data_mean(self):
        data = {"ch1": [1.0, 2.0, 3.0], "ch2": [4.0, 5.0, 6.0]}
        roi = ROIDefinition(roi_id="r1", name="R1", channels=["ch1", "ch2"], aggregation="mean")
        result = aggregate_roi_data(data, roi)
        assert result == [2.5, 3.5, 4.5]


class TestOutputExport:
    def test_export_channel_results(self, tmp_path):
        results = [
            ChannelResult(
                subject="01",
                channel="S1_D1 hbo",
                chromophore="hbo",
                condition="tapping",
                contrast="tapping > rest",
                beta=0.5,
                t_stat=2.1,
                p_value=0.03,
            ),
        ]
        path = export_channel_results(results, tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "S1_D1 hbo" in content

    def test_export_roi_results(self, tmp_path):
        results = [
            ROIResult(
                subject="01",
                roi="left_motor",
                chromophore="hbo",
                beta=0.5,
                t_stat=2.1,
                n_channels=4,
                channels=["ch1", "ch2", "ch3", "ch4"],
            ),
        ]
        path = export_roi_results(results, tmp_path)
        assert path.exists()

    def test_export_group_summary(self, tmp_path):
        summaries = [
            GroupSummary(
                roi="left_motor",
                chromophore="hbo",
                contrast="tapping > rest",
                n_subjects=10,
                mean_beta=0.5,
                std_beta=0.2,
            ),
        ]
        path = export_group_summary(summaries, tmp_path)
        assert path.exists()

    def test_compute_group_statistics(self):
        results = [
            ROIResult(subject="s1", roi="r1", beta=0.5),
            ROIResult(subject="s2", roi="r1", beta=0.3),
            ROIResult(subject="s3", roi="r1", beta=0.4),
        ]
        summaries = compute_group_statistics(results)
        assert len(summaries) == 1
        assert summaries[0].n_subjects == 3
        assert abs(summaries[0].mean_beta - 0.4) < 0.01

    def test_compute_group_with_exclusion(self):
        results = [
            ROIResult(subject="s1", roi="r1", beta=0.5),
            ROIResult(subject="s2", roi="r1", beta=0.3),
            ROIResult(subject="s3", roi="r1", beta=0.4),
        ]
        summaries = compute_group_statistics(results, exclude_subjects=["s3"])
        assert summaries[0].n_subjects == 2

    def test_compute_group_averages_repeated_runs_within_subject(self):
        results = [
            ROIResult(subject="s1", run="01", roi="r1", beta=1.0),
            ROIResult(subject="s1", run="02", roi="r1", beta=3.0),
            ROIResult(subject="s2", run="01", roi="r1", beta=6.0),
        ]

        summary = compute_group_statistics(results)[0]

        assert summary.n_subjects == 2
        assert summary.mean_beta == 4.0
