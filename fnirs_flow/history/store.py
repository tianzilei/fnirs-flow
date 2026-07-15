"""HistoryStore Protocol defining the storage interface for FlowVCS."""

from __future__ import annotations

from typing import Protocol

from fnirs_flow.history.models import (
    CommitLogEntry,
    DesignCommit,
    DesignObject,
    HistoryState,
)


class HistoryStore(Protocol):
    """Abstract storage interface for design history.

    Implementations must be deterministic and thread-safe within a single
    ProjectTransaction scope.
    """

    def is_initialized(self) -> bool:
        """Return True if history state exists in the store."""
        ...

    def initialize(self, state: HistoryState) -> None:
        """Persist the initial history state."""
        ...

    def get_state(self) -> HistoryState:
        """Read the current history state. Raises HistoryNotInitialized if absent."""
        ...

    def save_state(self, state: HistoryState) -> None:
        """Persist an updated history state."""
        ...

    def get_object(self, object_id: str) -> DesignObject:
        """Read a design object by its content ID. Raises HistoryObjectMissing if absent."""
        ...

    def put_object(self, obj: DesignObject, object_id: str) -> None:
        """Store a design object. Must not overwrite an existing object with a different ID."""
        ...

    def has_object(self, object_id: str) -> bool:
        """Return True if the object exists in the store."""
        ...

    def get_commit(self, commit_id: str) -> DesignCommit:
        """Read a commit by its content ID. Raises CommitNotFound if absent."""
        ...

    def put_commit(self, commit: DesignCommit, commit_id: str) -> None:
        """Store a design commit."""
        ...

    def has_commit(self, commit_id: str) -> bool:
        """Return True if the commit exists in the store."""
        ...

    def list_commits(
        self,
        branch: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CommitLogEntry]:
        """List commits in reverse chronological order, optionally filtered by branch."""
        ...
