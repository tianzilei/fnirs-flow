"""Application errors mapped to interface responses by the API layer."""

from __future__ import annotations


class ProjectTransactionError(Exception):
    """Raised when a project transaction operation fails."""


class ProjectRevisionConflictError(ProjectTransactionError):
    """Raised when base_revision does not match the current revision.

    Attributes:
        current_revision: The latest revision in the bundle.
        requested_revision: The revision the caller thought was current.
    """

    def __init__(self, current_revision: int, requested_revision: int) -> None:
        self.current_revision = current_revision
        self.requested_revision = requested_revision
        super().__init__(
            f"Revision conflict: current={current_revision}, requested={requested_revision}"
        )


class ProjectLockTimeoutError(ProjectTransactionError):
    """Raised when a write lock cannot be acquired within the timeout."""

    def __init__(self, project_id: str, timeout: float) -> None:
        self.project_id = project_id
        self.timeout = timeout
        super().__init__(
            f"Could not acquire write lock for project '{project_id}' within {timeout}s"
        )


class ProjectBusyError(ProjectTransactionError):
    """Raised when a project is currently executing another write operation.

    Attributes:
        operation: The operation that is holding the lock.
        holder_id: Identifier of the lock holder.
    """

    def __init__(self, operation: str, holder_id: str) -> None:
        self.operation = operation
        self.holder_id = holder_id
        super().__init__(
            f"Project is busy: operation '{operation}' is in progress (holder: {holder_id})"
        )


class StagingDirectoryError(ProjectTransactionError):
    """Raised when staging directory operations fail."""
