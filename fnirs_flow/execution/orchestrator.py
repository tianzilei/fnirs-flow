"""Execution orchestration boundary.

The legacy service remains the compatibility facade while this object owns the
top-level request lifecycle. Subsystems can be migrated behind this boundary
without changing CLI/API contracts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fnirs_flow.execution.models import ExecutionRequest, ExecutionResult

if TYPE_CHECKING:
    from fnirs_flow.execution.orchestrator_impl import ExecutionService


class ExecutionOrchestrator:
    def __init__(self, service: ExecutionService) -> None:
        self.service = service

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return self.service._execute_impl(request)
