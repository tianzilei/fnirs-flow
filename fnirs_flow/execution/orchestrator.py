"""Execution orchestration boundary.

The legacy service remains the compatibility facade while this object owns the
top-level request lifecycle. Subsystems can be migrated behind this boundary
without changing CLI/API contracts.
"""

from __future__ import annotations

from typing import Protocol

from fnirs_flow.execution.models import ExecutionRequest, ExecutionResult


class ExecutionServiceHost(Protocol):
    def _execute_impl(self, request: ExecutionRequest) -> ExecutionResult: ...


class ExecutionOrchestrator:
    def __init__(self, service: ExecutionServiceHost) -> None:
        self.service = service

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return self.service._execute_impl(request)
