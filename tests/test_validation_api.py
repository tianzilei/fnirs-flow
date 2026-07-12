"""Tests for the top-level validation API."""

from __future__ import annotations

import json
from pathlib import Path

from fnirs_flow.validation.api import validate_flow


class TestValidationAPI:
    def test_valid_flow(self, minimal_flow_dict):
        report = validate_flow(minimal_flow_dict)
        assert report.is_valid
        assert not report.has_fatal_risks
        assert report.readiness is not None
        assert report.readiness.status == "Ready"

    def test_missing_required_fields(self):
        report = validate_flow({"schema_version": "0.1.0"})
        assert not report.is_valid
        assert len(report.errors) > 0
        assert report.readiness is not None
        assert report.readiness.status == "Blocked"

    def test_invalid_json(self):
        report = validate_flow({"not_a": "valid_flow"})
        assert not report.is_valid
        assert report.readiness is not None
        assert report.readiness.status == "Blocked"

    def test_demo_flow_valid(self):
        demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
        if demo_path.exists():
            flow_dict = json.loads(demo_path.read_text())
            report = validate_flow(flow_dict)
            assert report.is_valid, f"Demo flow errors: {report.errors}"
            # May have low-severity risks (auto-resolve, etc.)
            fatal_risks = [r for r in report.risks if r.severity == "fatal"]
            assert len(fatal_risks) == 0, f"Fatal risks: {[r.message for r in fatal_risks]}"

    def test_high_risk_flow_needs_attention(self, minimal_flow_dict):
        flow = dict(minimal_flow_dict)
        flow["nodes"] = [dict(node, status="blocked") for node in minimal_flow_dict["nodes"]]
        report = validate_flow(flow)
        assert report.readiness is not None
        assert report.readiness.status == "Needs Attention"
