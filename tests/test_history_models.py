"""Tests for FlowVCS models and canonical hashing."""

from __future__ import annotations

import pytest

from fnirs_flow.history.canonical import canonical_json_bytes, compute_commit_id, compute_object_id
from fnirs_flow.history.errors import BranchNameInvalid
from fnirs_flow.history.models import (
    DesignCommit,
    DesignObject,
    HistoryState,
    validate_branch_name,
)


class TestCanonicalHash:
    def test_canonical_json_deterministic(self):
        a = {"b": 1, "a": 2}
        b = {"a": 2, "b": 1}
        assert canonical_json_bytes(a) == canonical_json_bytes(b)

    def test_canonical_json_no_whitespace(self):
        result = canonical_json_bytes({"key": "value"})
        assert b" " not in result

    def test_canonical_json_rejects_nan(self):
        import math

        with pytest.raises(ValueError):
            canonical_json_bytes({"v": math.nan})

    def test_compute_object_id_length(self):
        obj = DesignObject(flow={"nodes": []}, semantic_flow_hash="abc")
        oid = compute_object_id(obj.model_dump())
        assert len(oid) == 64
        assert oid == oid.lower()

    def test_compute_object_id_deterministic(self):
        obj = DesignObject(flow={"nodes": [{"id": "n1"}]}, semantic_flow_hash="def")
        id1 = compute_object_id(obj.model_dump())
        id2 = compute_object_id(obj.model_dump())
        assert id1 == id2

    def test_compute_object_id_differs_for_different_flows(self):
        obj1 = DesignObject(flow={"nodes": [{"id": "n1"}]}, semantic_flow_hash="a")
        obj2 = DesignObject(flow={"nodes": [{"id": "n2"}]}, semantic_flow_hash="b")
        assert compute_object_id(obj1.model_dump()) != compute_object_id(obj2.model_dump())

    def test_compute_commit_id_length(self):
        data = {
            "schema_version": "1.0.0",
            "parents": [],
            "design_object_id": "abc",
            "semantic_flow_hash": "def",
            "message": "test",
            "author": {"id": "u", "display_name": "U"},
            "created_at": "2026-01-01T00:00:00Z",
            "reason": "test",
            "metadata": {},
        }
        cid = compute_commit_id(data)
        assert len(cid) == 64

    def test_commit_id_changes_with_payload(self):
        """commit_id must change when payload content changes."""
        data = {
            "schema_version": "1.0.0",
            "parents": [],
            "design_object_id": "x",
            "semantic_flow_hash": "y",
            "message": "first",
            "author": {"id": "", "display_name": ""},
            "created_at": "",
            "reason": "",
            "metadata": {},
        }
        cid1 = compute_commit_id(data)
        data["message"] = "second"
        cid2 = compute_commit_id(data)
        assert cid1 != cid2


class TestModels:
    def test_design_object_round_trip(self):
        obj = DesignObject(flow={"nodes": [{"id": "n1"}], "edges": []}, semantic_flow_hash="abc")
        data = obj.model_dump()
        obj2 = DesignObject.model_validate(data)
        assert obj2.flow == obj.flow
        assert obj2.semantic_flow_hash == "abc"

    def test_design_commit_max_two_parents(self):
        commit = DesignCommit(parents=["a", "b"])
        assert len(commit.parents) == 2
        with pytest.raises(ValueError, match="at most 2"):
            DesignCommit(parents=["a", "b", "c"])

    def test_history_state_round_trip(self):
        from fnirs_flow.history.models import HeadRef, RefsState

        state = HistoryState(
            head=HeadRef(mode="branch", branch="main", commit_id="abc123"),
            refs=RefsState(heads={"main": "abc123", "dev": "def456"}),
        )
        data = state.model_dump()
        state2 = HistoryState.model_validate(data)
        assert state2.head.commit_id == "abc123"
        assert state2.refs.heads["dev"] == "def456"


class TestBranchValidation:
    def test_valid_names(self):
        for name in ["main", "feature/short-channel", "bugfix-123", "v1.2", "test_branch"]:
            validate_branch_name(name)  # should not raise

    def test_empty_name(self):
        with pytest.raises(BranchNameInvalid):
            validate_branch_name("")

    def test_too_long(self):
        with pytest.raises(BranchNameInvalid):
            validate_branch_name("a" * 129)

    def test_dotdot(self):
        with pytest.raises(BranchNameInvalid):
            validate_branch_name("../escape")

    def test_double_slash(self):
        with pytest.raises(BranchNameInvalid):
            validate_branch_name("a//b")

    def test_trailing_slash(self):
        with pytest.raises(BranchNameInvalid):
            validate_branch_name("feature/")

    def test_leading_slash(self):
        with pytest.raises(BranchNameInvalid):
            validate_branch_name("/main")

    def test_lock_suffix(self):
        with pytest.raises(BranchNameInvalid):
            validate_branch_name("main.lock")

    def test_reserved_prefix(self):
        with pytest.raises(BranchNameInvalid):
            validate_branch_name("recovery/test")

    def test_special_characters(self):
        with pytest.raises(BranchNameInvalid):
            validate_branch_name("feature branch")  # space
