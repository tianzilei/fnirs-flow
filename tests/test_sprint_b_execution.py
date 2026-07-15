"""Sprint B tests: derivatives layout, FailureRecord,"
"ActionAttempt, reportlets, package profiles."""

from __future__ import annotations

import json

from fnirs_flow.execution.batch import run_batch, write_batch_report
from fnirs_flow.execution.engine import DryRunResult, RunContext, ensure_derivatives_layout
from fnirs_flow.execution.failures import ActionAttempt, FailureRecord, FailureStore
from fnirs_flow.exporters.package_exporter import (
    PACKAGE_PROFILES,
    get_package_profile,
    list_package_profiles,
)
from fnirs_flow.exporters.reports import (
    generate_all_reportlets,
    generate_run_reportlet,
    generate_session_reportlet,
    generate_subject_reportlet,
)

# ============================================================================
# FailureRecord tests
# ============================================================================


class TestFailureRecord:
    def test_create_failure_record(self):
        rec = FailureRecord(
            failure_id="fail-sub01_ses01_run01_atom-1",
            subject="01",
            session="01",
            run="01",
            atom_id="atom-1",
            exception_type="ValueError",
            message="Bad input",
            recoverable=True,
        )
        assert rec.failure_id == "fail-sub01_ses01_run01_atom-1"
        assert rec.recoverable

    def test_failure_record_to_dict(self):
        rec = FailureRecord(
            failure_id="f1",
            subject="01",
            session="01",
            run="01",
            atom_id="a1",
            message="err",
        )
        d = rec.model_dump()
        assert d["failure_id"] == "f1"
        assert "log_path" in d


# ============================================================================
# ActionAttempt tests
# ============================================================================


class TestActionAttempt:
    def test_create_attempt(self):
        a = ActionAttempt(
            attempt_id="att-1",
            subject="01",
            session="01",
            run="01",
            atom_id="atom-1",
            status="planned",
        )
        assert a.status == "planned"
        assert a.error_type is None

    def test_attempt_status_pattern(self):
        a = ActionAttempt(
            attempt_id="att-1",
            status="completed",
            atom_id="a1",
        )
        assert a.status == "completed"


# ============================================================================
# FailureStore tests
# ============================================================================


class TestFailureStore:
    def test_register_and_retrieve(self):
        store = FailureStore()
        rec = store.register(
            subject="01",
            session="01",
            run="01",
            atom_id="a1",
            message="test error",
        )
        assert len(store.all()) == 1
        assert rec.subject == "01"

    def test_register_attempt(self):
        store = FailureStore()
        attempt = ActionAttempt(
            attempt_id="att-1",
            subject="01",
            session="01",
            run="01",
            atom_id="a1",
            status="failed",
            error_type="ValueError",
            error_message="bad",
        )
        store.register_attempt(attempt)
        assert len(store.all()) == 1

    def test_write_json(self, tmp_path):
        store = FailureStore()
        store.register(subject="01", session="01", run="01", atom_id="a1", message="err")
        path = store.write_json(tmp_path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["subject"] == "01"

    def test_write_csv(self, tmp_path):
        store = FailureStore()
        store.register(subject="01", session="01", run="01", atom_id="a1", message="err")
        path = store.write_csv(tmp_path)
        assert path.exists()


# ============================================================================
# Derivatives layout tests
# ============================================================================


class TestDerivativesLayout:
    def test_creates_directories(self, tmp_path):
        dirs = ensure_derivatives_layout(tmp_path)
        assert dirs["compiled"].exists()
        assert dirs["work"].exists()
        assert dirs["derivatives"].exists()
        assert dirs["reports"].exists()
        assert dirs["group"].exists()
        assert dirs["logs"].exists()


# ============================================================================
# Package profile tests
# ============================================================================


class TestPackageProfiles:
    def test_all_profiles_exist(self):
        assert "reproducibility_package" in PACKAGE_PROFILES
        assert "submission_package" in PACKAGE_PROFILES
        assert "reviewer_package" in PACKAGE_PROFILES

    def test_get_profile(self):
        p = get_package_profile("reproducibility_package")
        assert p.profile_id == "reproducibility_package"
        assert len(p.include_patterns) > 0

    def test_list_profiles(self):
        profiles = list_package_profiles()
        assert len(profiles) == 3

    def test_unknown_profile_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Unsupported package profile"):
            get_package_profile("nonexistent")

    def test_submission_excludes_provenance(self):
        p = get_package_profile("submission_package")
        assert not p.include_provenance

    def test_reviewer_includes_provenance(self):
        p = get_package_profile("reviewer_package")
        assert p.include_provenance


# ============================================================================
# Reportlet tests
# ============================================================================


class TestReportlets:
    def test_subject_reportlet(self, tmp_path):
        runs = [
            {"session": "01", "run": "01", "status": "completed", "steps_completed": ["s1"]},
            {"session": "01", "run": "02", "status": "failed", "steps_completed": ["s1"]},
        ]
        path = generate_subject_reportlet("01", runs, tmp_path)
        assert path.exists()
        assert "sub-01" in path.name

    def test_session_reportlet(self, tmp_path):
        runs = [
            {"run": "01", "status": "completed", "steps_completed": ["s1"]},
        ]
        path = generate_session_reportlet("01", "01", runs, tmp_path)
        assert path.exists()
        assert "ses-01" in str(path)

    def test_run_reportlet(self, tmp_path):
        run_data = {
            "status": "completed",
            "steps_completed": ["s1", "s2"],
            "errors": [],
        }
        path = generate_run_reportlet("01", "01", "01", run_data, tmp_path)
        assert path.exists()
        assert "run-01" in str(path)

    def test_generate_all_reportlets(self, tmp_path):
        runs = [
            {
                "subject": "01",
                "session": "01",
                "run": "01",
                "status": "completed",
                "steps_completed": ["s1"],
            },
            {
                "subject": "01",
                "session": "01",
                "run": "02",
                "status": "completed",
                "steps_completed": ["s1"],
            },
            {
                "subject": "02",
                "session": "01",
                "run": "01",
                "status": "completed",
                "steps_completed": ["s1"],
            },
        ]
        paths = generate_all_reportlets(runs, tmp_path)
        # Should have: 2 subjects + 2 sessions + 3 runs = 7 reportlets
        assert len(paths) == 7


# ============================================================================
# Batch with ActionAttempt tests
# ============================================================================


class TestBatchWithAttempts:
    def test_batch_creates_attempts(self):
        dry = DryRunResult(
            total_runs=2,
            planned_runs=[
                RunContext(run_id="r1", subject="01", session="01", run="01"),
                RunContext(run_id="r2", subject="01", session="01", run="02"),
            ],
        )
        result = run_batch(dry)
        assert len(result.attempts) == 2
        assert all(a.status == "completed" for a in result.attempts)

    def test_batch_failure_creates_attempt(self):
        def fail_fn(ctx):
            raise ValueError("boom")

        dry = DryRunResult(
            total_runs=1,
            planned_runs=[
                RunContext(run_id="r1", subject="01", session="01", run="01"),
            ],
        )
        result = run_batch(dry, execute_fn=fail_fn)
        assert result.has_failures
        assert result.attempts[0].status == "failed"
        assert result.attempts[0].error_type == "ValueError"

    def test_write_batch_report(self, tmp_path):
        dry = DryRunResult(
            total_runs=1,
            planned_runs=[
                RunContext(run_id="r1", subject="01", session="01", run="01"),
            ],
        )
        result = run_batch(dry)
        write_batch_report(result, tmp_path)
        assert (tmp_path / "batch_summary.json").exists()
        assert (tmp_path / "action_attempts.json").exists()
