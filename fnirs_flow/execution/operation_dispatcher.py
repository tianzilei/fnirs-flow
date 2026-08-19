"""Operation dispatch boundary for gradual handler migration."""

from __future__ import annotations

from typing import Any

from fnirs_flow.execution.operations import OperationContext, OperationRegistry, canonical_operation


class OperationDispatcher:
    def __init__(self, registry: OperationRegistry) -> None:
        self.registry = registry

    def canonicalize(self, operation_id: str) -> str:
        if self.registry.has(operation_id):
            return self.registry.canonicalize(operation_id)
        return canonical_operation(operation_id)

    def require_registered(self, operation_id: str) -> str:
        canonical = self.canonicalize(operation_id)
        if not self.registry.has(canonical):
            raise ValueError(f"Unknown operation: {operation_id}")
        return canonical

    def execute(self, operation_id: str, context: OperationContext) -> Any:
        """Execute through the registered handler for the declared operation."""
        registered = operation_id if self.registry.has(operation_id) else self.require_registered(operation_id)
        return self.registry.execute(registered, context)
