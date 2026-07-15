"""FlowVCS error hierarchy."""

from __future__ import annotations


class HistoryError(Exception):
    """Base for all FlowVCS errors."""


class HistoryNotInitialized(HistoryError):
    """History has not been initialized for this project."""


class HistoryCorrupt(HistoryError):
    """History graph is structurally invalid."""


class HistoryObjectMissing(HistoryError):
    """A referenced design object does not exist in the store."""


class HistoryHashMismatch(HistoryError):
    """Content hash does not match the expected ID."""


class BranchNotFound(HistoryError):
    """The requested branch does not exist."""


class BranchAlreadyExists(HistoryError):
    """A branch with this name already exists."""


class BranchNameInvalid(HistoryError):
    """The branch name violates naming rules."""


class BranchHeadConflict(HistoryError):
    """The branch HEAD was updated concurrently."""


class WorktreeDirty(HistoryError):
    """The working tree has uncommitted changes."""


class CommitNotFound(HistoryError):
    """The requested commit does not exist."""


class NoChanges(HistoryError):
    """The flow is identical to the current HEAD — nothing to commit."""


class CommitNotReachable(HistoryError):
    """The target commit is not reachable from any branch."""


class MergeNotSupported(HistoryError):
    """Merge is not supported in this version."""
