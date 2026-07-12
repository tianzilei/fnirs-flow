"""Tests for ProjectSnapshot and ActionAttempt models."""

from __future__ import annotations

from fnirs_flow.flow.snapshots import (
    ActionAttempt,
    ProjectHistory,
    ProjectSnapshot,
    ReadinessResult,
    RiskItem,
    WorkingState,
)


class TestProjectSnapshot:
    def test_create_snapshot(self):
        snap = ProjectSnapshot(
            snapshot_id="snap-001",
            flow={"nodes": [], "edges": []},
            flow_hash="abc123",
            created_at="2026-01-01T00:00:00Z",
        )
        assert snap.snapshot_id == "snap-001"
        assert snap.flow_hash == "abc123"

    def test_snapshot_no_attempt_field(self):
        """ProjectSnapshot must not contain current_attempt."""
        snap = ProjectSnapshot(
            snapshot_id="s1",
            flow={},
            flow_hash="h",
            created_at="t",
        )
        d = snap.model_dump()
        assert "current_attempt" not in d


class TestActionAttempt:
    def test_create_attempt(self):
        attempt = ActionAttempt(
            attempt_id="att-001",
            snapshot_id="snap-001",
            action_type="execute",
            status="running",
            created_at="2026-01-01T00:00:00Z",
        )
        assert attempt.snapshot_id == "snap-001"
        assert attempt.action_type == "execute"

    def test_attempt_references_snapshot(self):
        attempt = ActionAttempt(
            attempt_id="a1",
            snapshot_id="snap-1",
            action_type="dry_run",
            created_at="t",
        )
        assert attempt.snapshot_id == "snap-1"

    def test_attempt_with_risks(self):
        risk = RiskItem(
            risk_id="r1",
            severity="high",
            domain="adapter",
            message="Missing adapter",
        )
        attempt = ActionAttempt(
            attempt_id="a1",
            snapshot_id="s1",
            action_type="validate",
            created_at="t",
            risk_register=[risk],
        )
        assert len(attempt.risk_register) == 1
        assert attempt.risk_register[0].severity == "high"


class TestReadinessResult:
    def test_ready(self):
        r = ReadinessResult(status="Ready")
        assert r.status == "Ready"

    def test_blocked(self):
        r = ReadinessResult(status="Blocked", checks=[])
        assert r.status == "Blocked"


class TestProjectHistory:
    def test_history(self):
        h = ProjectHistory()
        assert len(h.snapshots) == 0
        assert len(h.attempts) == 0


class TestWorkingState:
    def test_working_state(self):
        ws = WorkingState(flow={"nodes": []})
        assert ws.flow == {"nodes": []}
