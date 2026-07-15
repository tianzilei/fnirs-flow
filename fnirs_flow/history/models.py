"""FlowVCS data models for design history."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Branch name validation: ASCII letters, digits, -, _, ., /
_BRANCH_RE = re.compile(r"^[a-zA-Z0-9._/\-]+$")
_RESERVED_PREFIXES = ("recovery/", "legacy/", "system/")
_MAX_BRANCH_LEN = 128


class AuthorInfo(BaseModel):
    """Identity of the commit author."""

    id: str = "local-user"
    display_name: str = "Researcher"


class DesignObject(BaseModel):
    """An immutable, content-addressed design snapshot.

    object_id = sha256(canonical_json(design_object))  (computed externally)
    """

    schema_version: str = "1.0.0"
    kind: Literal["flow_design"] = "flow_design"
    flow: dict[str, Any] = Field(default_factory=dict)
    semantic_flow_hash: str = ""


class DesignCommit(BaseModel):
    """An immutable history node linking parents, a design object, and metadata.

    commit_id = sha256(canonical_json(commit_payload))  (computed externally,
    the commit_id field itself is NOT part of the hashed payload).
    """

    schema_version: str = "1.0.0"
    commit_id: str = ""
    parents: list[str] = Field(default_factory=list)
    design_object_id: str = ""
    semantic_flow_hash: str = ""
    message: str = ""
    author: AuthorInfo = Field(default_factory=AuthorInfo)
    created_at: str = ""
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parents")
    @classmethod
    def validate_parents(cls, v: list[str]) -> list[str]:
        if len(v) > 2:
            raise ValueError("A commit may have at most 2 parents (merge)")
        return v


class HeadRef(BaseModel):
    """Current HEAD position."""

    mode: Literal["branch", "detached"] = "branch"
    branch: str | None = "main"
    commit_id: str = ""


class RefsState(BaseModel):
    """All branch refs (branch_name → commit_id)."""

    heads: dict[str, str] = Field(default_factory=dict)


class HistoryState(BaseModel):
    """The persisted state of the design history."""

    schema_version: str = "1.0.0"
    head: HeadRef = Field(default_factory=HeadRef)
    refs: RefsState = Field(default_factory=RefsState)


class BranchInfo(BaseModel):
    """Summary of a single branch."""

    name: str
    commit_id: str
    is_current: bool = False


class CommitLogEntry(BaseModel):
    """A lightweight commit summary for listing (no full object)."""

    commit_id: str
    parents: list[str] = Field(default_factory=list)
    semantic_flow_hash: str = ""
    message: str = ""
    author: AuthorInfo = Field(default_factory=AuthorInfo)
    created_at: str = ""
    reason: str = ""


class DiffChange(BaseModel):
    """A single structural change between two flows."""

    kind: Literal[
        "node_added",
        "node_removed",
        "node_changed",
        "edge_added",
        "edge_removed",
        "edge_changed",
        "flow_hash_changed",
    ]
    node_id: str | None = None
    edge_id: str | None = None
    path: str | None = None
    before: Any = None
    after: Any = None


class DiffResult(BaseModel):
    """Structured diff between two commits."""

    from_commit: str
    to_commit: str
    from_flow_hash: str
    to_flow_hash: str
    changes: list[DiffChange] = Field(default_factory=list)


def validate_branch_name(name: str) -> None:
    """Raise BranchNameInvalid if the name is not legal."""
    from fnirs_flow.history.errors import BranchNameInvalid

    if not name or len(name) > _MAX_BRANCH_LEN:
        raise BranchNameInvalid(f"Branch name must be 1-{_MAX_BRANCH_LEN} characters: {name!r}")
    if ".." in name or "//" in name or name.endswith("/"):
        raise BranchNameInvalid(f"Branch name contains illegal sequence: {name!r}")
    if name.startswith(("/", "~/")):
        raise BranchNameInvalid(f"Branch name must not start with / or ~/: {name!r}")
    if not _BRANCH_RE.match(name):
        raise BranchNameInvalid(f"Branch name contains invalid characters: {name!r}")
    if name.endswith(".lock"):
        raise BranchNameInvalid(f"Branch name must not end with .lock: {name!r}")
    for prefix in _RESERVED_PREFIXES:
        if name.startswith(prefix):
            raise BranchNameInvalid(f"Branch name uses reserved prefix {prefix!r}: {name!r}")
