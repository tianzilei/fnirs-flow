"""Tests for failure store."""

from __future__ import annotations

from fnirs_flow.execution.failures import (
    ActionAttempt,
    FailureRecord,
    FailureStore,
)


class TestFailureRecord:
    def test_basic_record(self):
        rec = FailureRecord(
            failure_id="f1",
            subject="sub-01",
            exception_type="ValueError",
            message="bad data",
        )
        assert rec.failure_id == "f1"
        assert rec.subject == "sub-01"
        assert rec.recoverable is False

    def test_model_dump(self):
        rec = FailureRecord(failure_id="f1", subject="sub-01")
        data = rec.model_dump()
        assert data["failure_id"] == "f1"
        assert data["subject"] == "sub-01"


class TestActionAttempt:
    def test_default_status(self):
        attempt = ActionAttempt(attempt_id="a1")
        assert attempt.status == "planned"

    def test_valid_statuses(self):
        for status in ("planned", "running", "completed", "failed", "partial"):
            attempt = ActionAttempt(attempt_id="a1", status=status)
            assert attempt.status == status

    def test_invalid_status(self):
        import pytest
        with pytest.raises(Exception):
            ActionAttempt(attempt_id="a1", status="invalid")


class TestFailureStore:
    def test_register(self):
        store = FailureStore()
        rec = store.register(subject="sub-01", session="ses-01", message="error")
        assert rec.subject == "sub-01"
        assert rec.session == "ses-01"
        assert rec.timestamp  # should be populated

    def test_all(self):
        store = FailureStore()
        store.register(subject="sub-01", message="err1")
        store.register(subject="sub-02", message="err2")
        failures = store.all()
        assert len(failures) == 2

    def test_register_attempt_failed(self):
        store = FailureStore()
        attempt = ActionAttempt(
            attempt_id="a1",
            subject="sub-01",
            status="failed",
            error_type="ValueError",
            error_message="bad input",
        )
        store.register_attempt(attempt)
        failures = store.all()
        assert len(failures) == 1
        assert failures[0].exception_type == "ValueError"
        assert failures[0].message == "bad input"

    def test_register_attempt_non_failed(self):
        store = FailureStore()
        for status in ("planned", "running", "completed", "partial"):
            attempt = ActionAttempt(attempt_id="a1", subject="sub-01", status=status)
            store.register_attempt(attempt)
        assert len(store.all()) == 0

    def test_write_csv(self, tmp_path):
        store = FailureStore()
        store.register(subject="sub-01", message="err1")
        store.register(subject="sub-02", message="err2")
        path = store.write_csv(tmp_path)
        assert path.exists()
        assert path.name == "failure_manifest.csv"
        content = path.read_text(encoding="utf-8")
        assert "sub-01" in content
        assert "sub-02" in content

    def test_write_json(self, tmp_path):
        store = FailureStore()
        store.register(subject="sub-01", message="err1")
        path = store.write_json(tmp_path)
        assert path.exists()
        assert path.name == "failure_manifest.json"
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["subject"] == "sub-01"

    def test_write_csv_empty(self, tmp_path):
        store = FailureStore()
        path = store.write_csv(tmp_path)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "failure_id" in content  # header

    def test_write_json_empty(self, tmp_path):
        store = FailureStore()
        path = store.write_json(tmp_path)
        assert path.exists()
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == []
