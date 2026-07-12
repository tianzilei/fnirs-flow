"""ProjectSnapshot, ActionAttempt, and WorkingState models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from fnirs_flow.validation.models import ReadinessResult, RiskItem


class WorkingState(BaseModel):
    """Mutable working state for editing a flow."""

    flow: dict[str, Any] = Field(default_factory=dict)
    modified_at: str = ""
    description: str = ""


class ProjectSnapshot(BaseModel):
    """Immutable design snapshot. Must NOT contain current_attempt."""

    snapshot_id: str
    flow: dict[str, Any]
    flow_hash: str
    created_at: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class ActionAttempt(BaseModel):
    """An action (run/report/export/package) referencing an immutable ProjectSnapshot."""

    attempt_id: str
    snapshot_id: str
    action_type: str = Field(pattern="^(validate|compile|dry_run|execute|export|package)$")
    status: str = Field(default="pending", pattern="^(pending|running|completed|failed|cancelled)$")
    created_at: str
    completed_at: str = ""
    readiness_check: ReadinessResult | None = None
    risk_register: list[RiskItem] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    failure_manifest: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectHistory(BaseModel):
    snapshots: list[ProjectSnapshot] = Field(default_factory=list)
    attempts: list[ActionAttempt] = Field(default_factory=list)
