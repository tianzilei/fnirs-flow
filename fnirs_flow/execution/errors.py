"""Execution-layer exceptions shared without importing orchestration services."""


class ExecutionCancelledError(RuntimeError):
    """Raised when an execution request is cancelled cooperatively."""
