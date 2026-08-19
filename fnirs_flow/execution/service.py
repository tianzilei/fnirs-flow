"""Backward-compatible execution service facade."""

from __future__ import annotations

from fnirs_flow.execution.models import (
    ExecutionRequest,
    ExecutionResult,
    RunExecutionResult,
)
from fnirs_flow.execution.orchestrator_impl import (
    ExecutionCancelledError,
    resolve_atom_backend_id,
)
from fnirs_flow.execution.orchestrator_impl import (
    ExecutionService as _ExecutionOrchestrator,
)


class ExecutionService(_ExecutionOrchestrator):
    """Compatibility facade; orchestration lives in ``orchestrator_impl``."""


__all__ = [
    "ExecutionCancelledError",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionService",
    "RunExecutionResult",
    "resolve_atom_backend_id",
]
