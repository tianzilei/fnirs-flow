"""Tests for enhanced reporting, inclusion audit, and reproducibility."""

from __future__ import annotations

from fnirs_flow.exporters.inclusion_audit import (
    InclusionAuditor,
    SubjectDemographics,
    write_inclusion_audit_report,
)
from fnirs_flow.exporters.methods_report import generate_methods_section, write_methods_report
from fnirs_flow.exporters.reproducibility import (
    capture_environment,
    create_config_snapshot,
    generate_reproducibility_manifest,
)


class TestMethodsReport:
    def test_generate_methods_section(self):
        plan = {
            "flow_id": "test",
            "acquisition": {
                "device": "NIRx",
                "wavelengths": [760, 850],
                "sampling_rate": 10.0,
            },
        }
        section = generate_methods_section(plan)
        assert "Methods" in section
        assert "NIRx" in section

    def test_generate_with_qc(self):
        plan = {"flow_id": "test"}
        qc = {"sci_threshold": 0.8, "n_channels_excluded": 5}
        section = generate_methods_section(plan, qc_summary=qc)
        assert "SCI" in section
        assert "5" in section

    def test_generate_with_preprocessing(self):
        plan = {"flow_id": "test"}
        prep = {
            "motion_correction": "TDDR",
            "filter": {"l_freq": 0.01, "h_freq": 0.2},
            "mbll": True,
        }
        section = generate_methods_section(plan, preprocessing_params=prep)
        assert "TDDR" in section
        assert "Beer-Lambert" in section

    def test_write_methods_report(self, tmp_path):
        plan = {"flow_id": "test"}
        path = write_methods_report(plan, tmp_path)
        assert path.exists()
        assert "Methods" in path.read_text()


class TestInclusionAudit:
    def test_audit_with_complete_data(self):
        auditor = InclusionAuditor()
        subjects = [
            SubjectDemographics(subject_id="s1", fields={"age": 25, "sex": "male"}),
            SubjectDemographics(subject_id="s2", fields={"age": 30, "sex": "female"}),
        ]
        result = auditor.audit(subjects)
        assert result.total_subjects == 2
        assert result.subjects_with_missing_fields == 0

    def test_audit_with_missing_fields(self):
        auditor = InclusionAuditor()
        subjects = [
            SubjectDemographics(subject_id="s1", fields={"age": 25}),
            SubjectDemographics(subject_id="s2", fields={}),
        ]
        result = auditor.audit(subjects)
        assert result.total_subjects == 2
        assert result.subjects_with_missing_fields > 0
        assert len(result.risks) > 0

    def test_audit_with_signal_quality(self):
        auditor = InclusionAuditor()
        subjects = [
            SubjectDemographics(
                subject_id="s1",
                fields={"skin_color": "I", "hair_texture": "straight_thin"},
            ),
            SubjectDemographics(
                subject_id="s2",
                fields={"skin_color": "VI", "hair_texture": "coily"},
            ),
        ]
        qc = {
            "s1": {"sci_mean": 0.9},
            "s2": {"sci_mean": 0.5},
        }
        result = auditor.audit(subjects, qc_results=qc)
        assert len(result.signal_quality_by_group) > 0

    def test_write_audit_report(self, tmp_path):
        auditor = InclusionAuditor()
        subjects = [
            SubjectDemographics(subject_id="s1", fields={"age": 25}),
        ]
        result = auditor.audit(subjects)
        path = write_inclusion_audit_report(result, tmp_path)
        assert path.exists()
        assert "Inclusion Audit" in path.read_text()


class TestReproducibility:
    def test_capture_environment(self):
        env = capture_environment()
        assert "python_version" in env
        assert "platform" in env
        assert "timestamp" in env

    def test_create_config_snapshot(self):
        flow = {"flow_id": "test", "nodes": []}
        snapshot = create_config_snapshot(flow)
        assert snapshot["flow"] == flow
        assert snapshot["flow"] == flow

    def test_generate_manifest(self, tmp_path):
        flow = {"flow_id": "test"}
        manifest = generate_reproducibility_manifest(flow, outdir=tmp_path)
        assert "environment" in manifest
        assert "config_snapshot" in manifest
        assert (tmp_path / "reproducibility_manifest.json").exists()
        assert (tmp_path / "environment.json").exists()
        assert (tmp_path / "requirements.txt").exists()

    def test_manifest_with_plan(self, tmp_path):
        flow = {"flow_id": "test"}
        plan = {"schema_version": "0.1.0", "steps": []}
        manifest = generate_reproducibility_manifest(flow, plan_dict=plan, outdir=tmp_path)
        assert manifest["config_snapshot"].get("plan") is not None
