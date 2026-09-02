"""Backward-compatible execution service facade."""

from __future__ import annotations

from fnirs_flow.execution.errors import ExecutionCancelledError
from fnirs_flow.execution.models import (
    ExecutionRequest,
    ExecutionResult,
    RunExecutionResult,
)
from fnirs_flow.execution.orchestrator_impl import (
    ExecutionService as _ExecutionOrchestrator,
)
from fnirs_flow.execution.orchestrator_impl import (
    resolve_atom_backend_id,
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
