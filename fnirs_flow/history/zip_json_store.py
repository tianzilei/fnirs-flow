"""ZIP-workspace JSON HistoryStore implementation.

Reads and writes history objects as JSON files under the managed workspace's
``history/`` directory.  Objects are sharded by the first two hex characters
of their content-addressed ID to avoid single-directory file count issues.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fnirs_flow.history.errors import (
    CommitNotFound,
    HistoryNotInitialized,
    HistoryObjectMissing,
)
from fnirs_flow.history.models import (
    CommitLogEntry,
    DesignCommit,
    DesignObject,
    HistoryState,
)

_HISTORY_DIR = "history"
_STATE_FILE = "state.json"
_OBJECTS_DIR = "objects"
_COMMITS_DIR = "commits"


class ZipJsonHistoryStore:
    """Store that persists history as JSON files inside a workspace directory."""

    def __init__(self, workspace: Path) -> None:
        self._root = Path(workspace) / _HISTORY_DIR

    # -- directory helpers --

    def _state_path(self) -> Path:
        return self._root / _STATE_FILE

    def _object_path(self, object_id: str) -> Path:
        return self._root / _OBJECTS_DIR / object_id[:2] / f"{object_id[2:]}.json"

    def _commit_path(self, commit_id: str) -> Path:
        return self._root / _COMMITS_DIR / commit_id[:2] / f"{commit_id[2:]}.json"

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    # -- HistoryStore interface --

    def is_initialized(self) -> bool:
        return self._state_path().is_file()

    def initialize(self, state: HistoryState) -> None:
        self._write_json(self._state_path(), state.model_dump())

    def get_state(self) -> HistoryState:
        path = self._state_path()
        if not path.is_file():
            raise HistoryNotInitialized("History has not been initialized")
        return HistoryState.model_validate(self._read_json(path))

    def save_state(self, state: HistoryState) -> None:
        self._write_json(self._state_path(), state.model_dump())

    def get_object(self, object_id: str) -> DesignObject:
        path = self._object_path(object_id)
        if not path.is_file():
            raise HistoryObjectMissing(f"Object not found: {object_id}")
        return DesignObject.model_validate(self._read_json(path))

    def put_object(self, obj: DesignObject, object_id: str) -> None:
        path = self._object_path(object_id)
        if path.is_file():
            return  # content-addressed; identical content is idempotent
        self._write_json(path, obj.model_dump())

    def has_object(self, object_id: str) -> bool:
        return self._object_path(object_id).is_file()

    def get_commit(self, commit_id: str) -> DesignCommit:
        path = self._commit_path(commit_id)
        if not path.is_file():
            raise CommitNotFound(f"Commit not found: {commit_id}")
        return DesignCommit.model_validate(self._read_json(path))

    def put_commit(self, commit: DesignCommit, commit_id: str) -> None:
        path = self._commit_path(commit_id)
        if path.is_file():
            return  # content-addressed; idempotent
        self._write_json(path, commit.model_dump())

    def has_commit(self, commit_id: str) -> bool:
        return self._commit_path(commit_id).is_file()

    def list_commits(
        self,
        branch: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CommitLogEntry]:
        state = self.get_state()
        if branch is not None:
            start_id = state.refs.heads.get(branch)
            if start_id is None:
                return []
        else:
            start_id = state.head.commit_id
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
            try:
                commit = self.get_commit(cid)
            except CommitNotFound:
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
