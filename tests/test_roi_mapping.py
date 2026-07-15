"""Tests for ROI mapping module."""

from __future__ import annotations

import pytest

from fnirs_flow.adapters.roi_mapping import (
    STANDARD_ROI_TEMPLATES,
    ROIDefinition,
    ROIMapping,
    ROIMappingManager,
    aggregate_roi_data,
)


class TestROIDefinition:
    def test_valid_definition(self):
        roi = ROIDefinition(roi_id="r1", name="Test ROI", channels=["ch1"])
        assert roi.roi_id == "r1"
        assert roi.name == "Test ROI"
        assert roi.aggregation == "mean"
        assert roi.source == "user"

    def test_custom_aggregation(self):
        roi = ROIDefinition(roi_id="r1", name="Test", aggregation="median")
        assert roi.aggregation == "median"

    def test_invalid_aggregation(self):
        with pytest.raises(Exception):
            ROIDefinition(roi_id="r1", name="Test", aggregation="invalid")

    def test_invalid_source(self):
        with pytest.raises(Exception):
            ROIDefinition(roi_id="r1", name="Test", source="invalid")


class TestROIMapping:
    def test_empty_mapping(self):
        mapping = ROIMapping(mapping_id="m1")
        assert mapping.fallback_to_channel
        assert len(mapping.rois) == 0

    def test_add_roi(self):
        mapping = ROIMapping(mapping_id="m1")
        roi = ROIDefinition(roi_id="r1", name="Test", channels=["ch1"])
        mapping.rois.append(roi)
        assert len(mapping.rois) == 1


class TestStandardTemplates:
    def test_motor_template_exists(self):
        assert "motor" in STANDARD_ROI_TEMPLATES
        assert len(STANDARD_ROI_TEMPLATES["motor"]) == 2

    def test_prefrontal_template_exists(self):
        assert "prefrontal" in STANDARD_ROI_TEMPLATES
        assert len(STANDARD_ROI_TEMPLATES["prefrontal"]) == 2

    def test_broca_template_exists(self):
        assert "broca" in STANDARD_ROI_TEMPLATES
        assert len(STANDARD_ROI_TEMPLATES["broca"]) == 1

    def test_all_templates_have_valid_rois(self):
        for name, rois in STANDARD_ROI_TEMPLATES.items():
            for roi in rois:
                assert roi.source == "template"
                assert roi.roi_id
                assert roi.name


class TestROIMappingManager:
    def test_create_and_get_mapping(self):
        mgr = ROIMappingManager()
        mapping = mgr.create_mapping("m1", "Test Mapping")
        assert mapping.mapping_id == "m1"
        assert mgr.get_mapping("m1") is mapping

    def test_get_nonexistent_mapping(self):
        mgr = ROIMappingManager()
        assert mgr.get_mapping("nonexistent") is None

    def test_add_roi(self):
        mgr = ROIMappingManager()
        mgr.create_mapping("m1")
        roi = ROIDefinition(roi_id="r1", name="Test", channels=["ch1"])
        assert mgr.add_roi("m1", roi)
        mapping = mgr.get_mapping("m1")
        assert len(mapping.rois) == 1

    def test_add_roi_to_nonexistent_mapping(self):
        mgr = ROIMappingManager()
        roi = ROIDefinition(roi_id="r1", name="Test")
        assert not mgr.add_roi("nonexistent", roi)

    def test_create_from_template(self):
        mgr = ROIMappingManager()
        mapping = mgr.create_from_template("m1", "motor")
        assert mapping is not None
        assert len(mapping.rois) == 2
        assert mapping.name == "motor template"

    def test_create_from_nonexistent_template(self):
        mgr = ROIMappingManager()
        assert mgr.create_from_template("m1", "nonexistent") is None

    def test_assign_channels(self):
        mgr = ROIMappingManager()
        mgr.create_mapping("m1")
        roi = ROIDefinition(roi_id="r1", name="Test", channels=["ch1"])
        mgr.add_roi("m1", roi)
        assert mgr.assign_channels("m1", "r1", ["ch2", "ch3"])
        mapping = mgr.get_mapping("m1")
        assert mapping.rois[0].channels == ["ch2", "ch3"]

    def test_assign_channels_nonexistent_mapping(self):
        mgr = ROIMappingManager()
        assert not mgr.assign_channels("nonexistent", "r1", ["ch1"])

    def test_assign_channels_nonexistent_roi(self):
        mgr = ROIMappingManager()
        mgr.create_mapping("m1")
        assert not mgr.assign_channels("m1", "nonexistent", ["ch1"])

    def test_create_from_user_mapping(self):
        mgr = ROIMappingManager()
        pairs = [("ch1", "Left"), ("ch2", "Left"), ("ch3", "Right")]
        mapping = mgr.create_from_user_mapping("m1", pairs)
        assert len(mapping.rois) == 2
        left_roi = next(r for r in mapping.rois if r.name == "Left")
        assert left_roi.channels == ["ch1", "ch2"]

    def test_validate_mapping(self):
        mgr = ROIMappingManager()
        mgr.create_mapping("m1")
        roi = ROIDefinition(roi_id="r1", name="Test", channels=["ch1", "ch2"])
        mgr.add_roi("m1", roi)
        warnings = mgr.validate_mapping("m1", ["ch1", "ch2", "ch3"])
        assert len(warnings) == 0

    def test_validate_mapping_missing_channels(self):
        mgr = ROIMappingManager()
        mgr.create_mapping("m1")
        roi = ROIDefinition(roi_id="r1", name="Test", channels=["ch1", "ch_missing"])
        mgr.add_roi("m1", roi)
        warnings = mgr.validate_mapping("m1", ["ch1", "ch2"])
        assert len(warnings) == 1
        assert "ch_missing" in warnings[0]

    def test_validate_mapping_no_rois(self):
        mgr = ROIMappingManager()
        mgr.create_mapping("m1")
        warnings = mgr.validate_mapping("m1", ["ch1"])
        assert any("No ROIs" in w for w in warnings)

    def test_validate_nonexistent_mapping(self):
        mgr = ROIMappingManager()
        warnings = mgr.validate_mapping("nonexistent", ["ch1"])
        assert "Mapping not found" in warnings


class TestAggregateROIData:
    def test_mean_aggregation(self):
        data = {"ch1": [1.0, 2.0, 3.0], "ch2": [3.0, 4.0, 5.0]}
        roi = ROIDefinition(roi_id="r1", name="Test", channels=["ch1", "ch2"], aggregation="mean")
        result = aggregate_roi_data(data, roi)
        assert result == [2.0, 3.0, 4.0]

    def test_median_aggregation(self):
        data = {"ch1": [1.0, 2.0, 3.0], "ch2": [3.0, 4.0, 5.0]}
        roi = ROIDefinition(roi_id="r1", name="Test", channels=["ch1", "ch2"], aggregation="median")
        result = aggregate_roi_data(data, roi)
        assert result == [2.0, 3.0, 4.0]

    def test_max_aggregation(self):
        data = {"ch1": [1.0, 2.0, 3.0], "ch2": [3.0, 4.0, 5.0]}
        roi = ROIDefinition(roi_id="r1", name="Test", channels=["ch1", "ch2"], aggregation="max")
        result = aggregate_roi_data(data, roi)
        assert result == [3.0, 4.0, 5.0]

    def test_min_aggregation(self):
        data = {"ch1": [1.0, 2.0, 3.0], "ch2": [3.0, 4.0, 5.0]}
        roi = ROIDefinition(roi_id="r1", name="Test", channels=["ch1", "ch2"], aggregation="min")
        result = aggregate_roi_data(data, roi)
        assert result == [1.0, 2.0, 3.0]

    def test_empty_channels(self):
        data = {"ch1": [1.0, 2.0]}
        roi = ROIDefinition(roi_id="r1", name="Test", channels=[])
        result = aggregate_roi_data(data, roi)
        assert result == []

    def test_missing_channel_in_data(self):
        data = {"ch1": [1.0, 2.0]}
        roi = ROIDefinition(roi_id="r1", name="Test", channels=["ch1", "missing"])
        result = aggregate_roi_data(data, roi)
        assert result == [1.0, 2.0]
