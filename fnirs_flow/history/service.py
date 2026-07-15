"""HistoryService: business-logic layer for FlowVCS design history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fnirs_flow.compiler.hashing import compute_flow_hash
from fnirs_flow.history.canonical import compute_commit_id, compute_object_id
from fnirs_flow.history.diff import compute_flow_diff
from fnirs_flow.history.errors import (
    BranchAlreadyExists,
    BranchNotFound,
    CommitNotFound,
    HistoryNotInitialized,
    NoChanges,
)
from fnirs_flow.history.models import (
    AuthorInfo,
    BranchInfo,
    CommitLogEntry,
    DesignCommit,
    DesignObject,
    DiffResult,
    HeadRef,
    HistoryState,
    RefsState,
    validate_branch_name,
)
from fnirs_flow.history.store import HistoryStore


class HistoryService:
    """Provides commit, branch, checkout, diff, and dirty-check operations."""

    def __init__(self, store: HistoryStore) -> None:
        self._store = store

    @property
    def store(self) -> HistoryStore:
        return self._store

    # -- Initialization --

    def initialize(self, initial_flow: dict[str, Any]) -> str:
        """Initialize history with a root commit. Returns root commit_id.

        If already initialized, returns the current HEAD commit_id without
        creating a new commit.
        """
        if self._store.is_initialized():
            state = self._store.get_state()
            return state.head.commit_id

        # Create root design object
        flow_hash = compute_flow_hash(initial_flow)
        obj = DesignObject(flow=initial_flow, semantic_flow_hash=flow_hash)
        obj_id = compute_object_id(obj.model_dump())
        self._store.put_object(obj, obj_id)

        # Create root commit (no parents)
        now = datetime.now(timezone.utc).isoformat()
        commit_payload = {
            "schema_version": "1.0.0",
            "parents": [],
            "design_object_id": obj_id,
            "semantic_flow_hash": flow_hash,
            "message": "Initial design",
            "author": {"id": "local-user", "display_name": "Researcher"},
            "created_at": now,
            "reason": "history_initialized",
            "metadata": {},
        }
        commit_id = compute_commit_id(commit_payload)
        commit = DesignCommit(
            commit_id=commit_id,
            parents=[],
            design_object_id=obj_id,
            semantic_flow_hash=flow_hash,
            message="Initial design",
            author=AuthorInfo(),
            created_at=now,
            reason="history_initialized",
        )
        self._store.put_commit(commit, commit_id)

        # Initialize state with main branch pointing to root commit
        state = HistoryState(
            head=HeadRef(mode="branch", branch="main", commit_id=commit_id),
            refs=RefsState(heads={"main": commit_id}),
        )
        self._store.initialize(state)
        return commit_id

    # -- Commit --

    def commit(
        self,
        flow: dict[str, Any],
        message: str = "",
        *,
        reason: str = "manual_design_commit",
        author: AuthorInfo | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a new design commit from the current flow. Returns commit_id.

        Raises NoChanges if the flow is identical to HEAD.
        """
        state = self._require_initialized()
        flow_hash = compute_flow_hash(flow)

        # Check if flow is identical to HEAD
        head_commit = self._store.get_commit(state.head.commit_id)
        head_object = self._store.get_object(head_commit.design_object_id)
        if flow_hash == head_commit.semantic_flow_hash and flow == head_object.flow:
            raise NoChanges("Flow is identical to HEAD — nothing to commit")

        # Create or retrieve design object
        obj = DesignObject(flow=flow, semantic_flow_hash=flow_hash)
        obj_id = compute_object_id(obj.model_dump())
        if not self._store.has_object(obj_id):
            self._store.put_object(obj, obj_id)

        # Create commit
        now = datetime.now(timezone.utc).isoformat()
        resolved_author = author or AuthorInfo()
        parents = [state.head.commit_id]
        commit_payload = {
            "schema_version": "1.0.0",
            "parents": parents,
            "design_object_id": obj_id,
            "semantic_flow_hash": flow_hash,
            "message": message,
            "author": resolved_author.model_dump(),
            "created_at": now,
            "reason": reason,
            "metadata": metadata or {},
        }
        commit_id = compute_commit_id(commit_payload)
        commit = DesignCommit(
            commit_id=commit_id,
            parents=parents,
            design_object_id=obj_id,
            semantic_flow_hash=flow_hash,
            message=message,
            author=resolved_author,
            created_at=now,
            reason=reason,
            metadata=metadata or {},
        )
        self._store.put_commit(commit, commit_id)

        # Update branch ref and HEAD
        branch = state.head.branch
        if branch:
            state.refs.heads[branch] = commit_id
        state.head.commit_id = commit_id
        self._store.save_state(state)
        return commit_id

    # -- Branch --

    def create_branch(self, name: str, from_commit_id: str | None = None) -> BranchInfo:
        """Create a new branch. Defaults to branching from HEAD."""
        validate_branch_name(name)
        state = self._require_initialized()

        if name in state.refs.heads:
            raise BranchAlreadyExists(f"Branch already exists: {name}")

        target_id = from_commit_id or state.head.commit_id
        if not self._store.has_commit(target_id):
            raise CommitNotFound(f"Commit not found: {target_id}")

        state.refs.heads[name] = target_id
        self._store.save_state(state)
        return BranchInfo(name=name, commit_id=target_id, is_current=(name == state.head.branch))

    def delete_branch(self, name: str) -> None:
        """Delete a branch ref. Cannot delete the current branch."""
        state = self._require_initialized()
        if name not in state.refs.heads:
            raise BranchNotFound(f"Branch not found: {name}")
        if name == state.head.branch:
            raise ValueError(f"Cannot delete the current branch: {name}")
        del state.refs.heads[name]
        self._store.save_state(state)

    def list_branches(self) -> list[BranchInfo]:
        """List all branches."""
        state = self._require_initialized()
        return [
            BranchInfo(name=name, commit_id=cid, is_current=(name == state.head.branch))
            for name, cid in state.refs.heads.items()
        ]

    # -- Checkout --

    def checkout(self, target: str) -> dict[str, Any]:
        """Switch to a branch or commit. Returns the target flow dict."""
        state = self._require_initialized()

        # Resolve target to a commit_id
        branch: str | None = None
        if target in state.refs.heads:
            commit_id = state.refs.heads[target]
            branch = target
        elif self._store.has_commit(target):
            commit_id = target
        else:
            raise BranchNotFound(f"Branch or commit not found: {target}")

        is_branch = branch is not None
        commit = self._store.get_commit(commit_id)
        obj = self._store.get_object(commit.design_object_id)

        # Update HEAD
        head_mode = "branch" if is_branch else "detached"
        state.head = HeadRef(mode=head_mode, branch=branch, commit_id=commit_id)  # type: ignore[arg-type]
        if is_branch and branch is not None:
            state.refs.heads[branch] = commit_id
        self._store.save_state(state)
        return obj.flow

    def check_dirty(self, current_flow: dict[str, Any]) -> bool:
        """Return True if current_flow differs from HEAD."""
        state = self._require_initialized()
        head_commit = self._store.get_commit(state.head.commit_id)
        current_hash = compute_flow_hash(current_flow)
        return current_hash != head_commit.semantic_flow_hash

    # -- Query --

    def get_head_commit(self) -> CommitLogEntry:
        """Return the HEAD commit as a log entry."""
        state = self._require_initialized()
        commit = self._store.get_commit(state.head.commit_id)
        return CommitLogEntry(
            commit_id=commit.commit_id,
            parents=commit.parents,
            semantic_flow_hash=commit.semantic_flow_hash,
            message=commit.message,
            author=commit.author,
            created_at=commit.created_at,
            reason=commit.reason,
        )

    def get_current_flow(self) -> dict[str, Any]:
        """Return the flow at HEAD."""
        state = self._require_initialized()
        commit = self._store.get_commit(state.head.commit_id)
        obj = self._store.get_object(commit.design_object_id)
        return obj.flow

    def list_commits(
        self,
        branch: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CommitLogEntry]:
        """List commits in reverse chronological order."""
        self._require_initialized()
        return self._store.list_commits(branch, limit=limit, offset=offset)

    def get_commit(self, commit_id: str) -> DesignCommit:
        """Get a specific commit by ID."""
        self._require_initialized()
        return self._store.get_commit(commit_id)

    # -- Diff --

    def diff(self, from_commit_id: str, to_commit_id: str) -> DiffResult:
        """Compute structured diff between two commits."""
        self._require_initialized()
        from_commit = self._store.get_commit(from_commit_id)
        to_commit = self._store.get_commit(to_commit_id)
        from_obj = self._store.get_object(from_commit.design_object_id)
        to_obj = self._store.get_object(to_commit.design_object_id)
        changes = compute_flow_diff(from_obj.flow, to_obj.flow)
        return DiffResult(
            from_commit=from_commit_id,
            to_commit=to_commit_id,
            from_flow_hash=from_commit.semantic_flow_hash,
            to_flow_hash=to_commit.semantic_flow_hash,
            changes=changes,
        )

    # -- Internals --

    def _require_initialized(self) -> HistoryState:
        if not self._store.is_initialized():
            raise HistoryNotInitialized("History has not been initialized")
        return self._store.get_state()
