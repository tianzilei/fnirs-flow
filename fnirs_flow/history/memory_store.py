"""In-memory HistoryStore implementation for testing."""

from __future__ import annotations

from fnirs_flow.history.errors import CommitNotFound, HistoryNotInitialized, HistoryObjectMissing
from fnirs_flow.history.models import (
    CommitLogEntry,
    DesignCommit,
    DesignObject,
    HistoryState,
)


class MemoryHistoryStore:
    """Pure in-memory store. Not thread-safe; for unit/contract tests only."""

    def __init__(self) -> None:
        self._state: HistoryState | None = None
        self._objects: dict[str, DesignObject] = {}
        self._commits: dict[str, DesignCommit] = {}

    def is_initialized(self) -> bool:
        return self._state is not None

    def initialize(self, state: HistoryState) -> None:
        self._state = state.model_copy(deep=True)

    def get_state(self) -> HistoryState:
        if self._state is None:
            raise HistoryNotInitialized("History has not been initialized")
        return self._state.model_copy(deep=True)

    def save_state(self, state: HistoryState) -> None:
        self._state = state.model_copy(deep=True)

    def get_object(self, object_id: str) -> DesignObject:
        obj = self._objects.get(object_id)
        if obj is None:
            raise HistoryObjectMissing(f"Object not found: {object_id}")
        return obj.model_copy(deep=True)

    def put_object(self, obj: DesignObject, object_id: str) -> None:
        self._objects[object_id] = obj.model_copy(deep=True)

    def has_object(self, object_id: str) -> bool:
        return object_id in self._objects

    def get_commit(self, commit_id: str) -> DesignCommit:
        commit = self._commits.get(commit_id)
        if commit is None:
            raise CommitNotFound(f"Commit not found: {commit_id}")
        return commit.model_copy(deep=True)

    def put_commit(self, commit: DesignCommit, commit_id: str) -> None:
        self._commits[commit_id] = commit.model_copy(deep=True)

    def has_commit(self, commit_id: str) -> bool:
        return commit_id in self._commits

    def list_commits(
        self,
        branch: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CommitLogEntry]:
        if self._state is None:
            return []
        # Walk backwards from HEAD
        if branch is not None:
            start_id = self._state.refs.heads.get(branch)
            if start_id is None:
                return []
        else:
            start_id = self._state.head.commit_id
        if not start_id:
            return []
        entries: list[CommitLogEntry] = []
        visited: set[str] = set()
        queue = [start_id]
        skipped = 0
        while queue and len(entries) < limit:
            cid = queue.pop(0)
            if cid in visited:
                continue
            visited.add(cid)
            commit = self._commits.get(cid)
            if commit is None:
                break
            if skipped < offset:
                skipped += 1
            else:
                entries.append(
                    CommitLogEntry(
                        commit_id=commit.commit_id,
                        parents=commit.parents,
                        semantic_flow_hash=commit.semantic_flow_hash,
                        message=commit.message,
                        author=commit.author,
                        created_at=commit.created_at,
                        reason=commit.reason,
                    )
                )
            queue.extend(commit.parents)
        return entries
