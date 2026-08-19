"""Contract tests for HistoryStore implementations.

Each test is parametrized over both MemoryHistoryStore and ZipJsonHistoryStore
to ensure they satisfy the same interface contract.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from fnirs_flow.history.errors import (
    BranchAlreadyExists,
    BranchNotFound,
    CommitNotFound,
    HistoryNotInitialized,
    HistoryObjectMissing,
    NoChanges,
)
from fnirs_flow.history.memory_store import MemoryHistoryStore
from fnirs_flow.history.models import DesignCommit, DesignObject, HeadRef, HistoryState, RefsState
from fnirs_flow.history.service import HistoryService
from fnirs_flow.history.zip_json_store import ZipJsonHistoryStore


def _make_memory_store():
    return MemoryHistoryStore()


def _make_zip_store():
    tmpdir = tempfile.mkdtemp()
    return ZipJsonHistoryStore(Path(tmpdir)), tmpdir


@pytest.fixture(params=["memory", "zip"])
def store(request):
    if request.param == "memory":
        yield _make_memory_store()
    else:
        s, td = _make_zip_store()
        yield s


@pytest.fixture
def svc(store):
    return HistoryService(store)


# -- Initialization --

class TestInitialization:
    def test_not_initialized(self, store):
        assert not store.is_initialized()

    def test_initialize_and_read(self, store):
        state = HistoryState(
            head=HeadRef(commit_id="abc"),
            refs=RefsState(heads={"main": "abc"}),
        )
        store.initialize(state)
        assert store.is_initialized()
        got = store.get_state()
        assert got.head.commit_id == "abc"

    def test_get_state_before_init_raises(self, store):
        with pytest.raises(HistoryNotInitialized):
            store.get_state()


# -- Objects --

class TestObjects:
    def test_put_and_get(self, store):
        obj = DesignObject(flow={"nodes": []}, semantic_flow_hash="h")
        from fnirs_flow.history.canonical import compute_object_id
        oid = compute_object_id(obj.model_dump())
        store.put_object(obj, oid)
        assert store.has_object(oid)
        got = store.get_object(oid)
        assert got.flow == {"nodes": []}

    def test_get_missing_raises(self, store):
        with pytest.raises(HistoryObjectMissing):
            store.get_object("0" * 64)


# -- Commits --

class TestCommits:
    def test_put_and_get(self, store):
        commit = DesignCommit(commit_id="a" * 64, design_object_id="b" * 64)
        store.put_commit(commit, "a" * 64)
        assert store.has_commit("a" * 64)
        got = store.get_commit("a" * 64)
        assert got.design_object_id == "b" * 64

    def test_get_missing_raises(self, store):
        with pytest.raises(CommitNotFound):
            store.get_commit("0" * 64)


# -- Service: Commit --

class TestServiceCommit:
    def test_initialize_creates_root(self, svc):
        flow = {"nodes": [{"id": "n1"}], "edges": []}
        root_id = svc.initialize(flow)
        assert len(root_id) == 64
        state = svc.store.get_state()
        assert state.head.commit_id == root_id
        assert state.refs.heads["main"] == root_id

    def test_commit_extends_chain(self, svc):
        flow1 = {"nodes": [{"id": "n1"}], "edges": []}
        root_id = svc.initialize(flow1)
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        c2 = svc.commit(flow2, message="add node")
        assert c2 != root_id
        assert svc.store.get_state().head.commit_id == c2

    def test_no_changes_raises(self, svc):
        flow = {"nodes": [{"id": "n1"}], "edges": []}
        svc.initialize(flow)
        with pytest.raises(NoChanges):
            svc.commit(flow)

    def test_same_content_different_metadata_still_no_changes(self, svc):
        """NoChanges is based on flow content, not metadata."""
        flow = {"nodes": [{"id": "n1"}], "edges": []}
        svc.initialize(flow)
        # Same flow content → NoChanges even with different message
        with pytest.raises(NoChanges):
            svc.commit(flow, message="different message")


# -- Service: Branch --

class TestServiceBranch:
    def test_create_branch(self, svc):
        flow = {"nodes": [], "edges": []}
        svc.initialize(flow)
        branch = svc.create_branch("dev")
        assert branch.name == "dev"
        assert branch.commit_id == svc.store.get_state().head.commit_id

    def test_create_duplicate_raises(self, svc):
        svc.initialize({"nodes": [], "edges": []})
        svc.create_branch("dev")
        with pytest.raises(BranchAlreadyExists):
            svc.create_branch("dev")

    def test_delete_branch(self, svc):
        svc.initialize({"nodes": [], "edges": []})
        svc.create_branch("dev")
        svc.delete_branch("dev")
        branches = svc.list_branches()
        assert all(b.name != "dev" for b in branches)

    def test_delete_current_branch_raises(self, svc):
        svc.initialize({"nodes": [], "edges": []})
        with pytest.raises(ValueError, match="current"):
            svc.delete_branch("main")

    def test_list_branches(self, svc):
        svc.initialize({"nodes": [], "edges": []})
        svc.create_branch("dev")
        svc.create_branch("staging")
        branches = svc.list_branches()
        names = {b.name for b in branches}
        assert names == {"main", "dev", "staging"}


# -- Service: Checkout --

class TestServiceCheckout:
    def test_checkout_branch(self, svc):
        flow1 = {"nodes": [{"id": "n1"}], "edges": []}
        svc.initialize(flow1)
        svc.create_branch("dev")
        # Commit on dev
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        svc.checkout("dev")
        svc.commit(flow2, message="dev commit")
        # Switch back to main
        main_flow = svc.checkout("main")
        assert len(main_flow["nodes"]) == 1

    def test_checkout_detached(self, svc):
        flow1 = {"nodes": [{"id": "n1"}], "edges": []}
        root_id = svc.initialize(flow1)
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        svc.commit(flow2)
        # Checkout root by commit_id
        root_flow = svc.checkout(root_id)
        assert len(root_flow["nodes"]) == 1

    def test_checkout_nonexistent_raises(self, svc):
        svc.initialize({"nodes": [], "edges": []})
        with pytest.raises(BranchNotFound):
            svc.checkout("nonexistent")


# -- Service: Diff --

class TestServiceDiff:
    def test_diff_add_node(self, svc):
        flow1 = {"nodes": [{"id": "n1"}], "edges": []}
        c1 = svc.initialize(flow1)
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        c2 = svc.commit(flow2)
        result = svc.diff(c1, c2)
        assert result.from_commit == c1
        assert result.to_commit == c2
        added = [ch for ch in result.changes if ch.kind == "node_added"]
        assert len(added) == 1
        assert added[0].node_id == "n2"

    def test_diff_change_node_type(self, svc):
        flow1 = {"nodes": [{"id": "n1", "type": "preprocess"}], "edges": []}
        c1 = svc.initialize(flow1)
        flow2 = {"nodes": [{"id": "n1", "type": "glm"}], "edges": []}
        c2 = svc.commit(flow2)
        result = svc.diff(c1, c2)
        changed = [ch for ch in result.changes if ch.kind == "node_changed"]
        assert len(changed) == 1
        assert changed[0].path == "atom_type"
        assert changed[0].before == "preprocess"
        assert changed[0].after == "glm"


# -- Service: List Commits --

class TestListCommits:
    def test_list_commits_on_main(self, svc):
        flow1 = {"nodes": [{"id": "n1"}], "edges": []}
        svc.initialize(flow1)
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        svc.commit(flow2)
        commits = svc.list_commits("main")
        assert len(commits) == 2
        assert commits[0].message != "" or commits[0].commit_id  # has data

    def test_list_commits_per_branch(self, svc):
        flow1 = {"nodes": [{"id": "n1"}], "edges": []}
        svc.initialize(flow1)
        svc.create_branch("dev")
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        svc.checkout("dev")
        svc.commit(flow2, message="dev commit")
        main_commits = svc.list_commits("main")
        dev_commits = svc.list_commits("dev")
        assert len(main_commits) == 1
        assert len(dev_commits) == 2


# -- Dirty Detection --

class TestDirtyDetection:
    def test_not_dirty_after_init(self, svc):
        flow = {"nodes": [{"id": "n1"}], "edges": []}
        svc.initialize(flow)
        assert not svc.check_dirty(flow)

    def test_dirty_after_change(self, svc):
        flow1 = {"nodes": [{"id": "n1"}], "edges": []}
        svc.initialize(flow1)
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        assert svc.check_dirty(flow2)


# -- Object Deduplication --

class TestObjectDedup:
    def test_same_flow_produces_same_object_id(self, svc):
        """Committing identical flow twice should reuse the same object."""
        flow = {"nodes": [{"id": "n1"}], "edges": []}
        svc.initialize(flow)

        # Modify then restore original flow
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        svc.commit(flow2)
        svc.commit(flow)  # back to original

        # Both commits should reference the same object
        commits = svc.list_commits("main")
        assert len(commits) == 3
        c0 = svc.get_commit(commits[2].commit_id)  # root
        c2 = svc.get_commit(commits[0].commit_id)  # latest
        assert c0.design_object_id == c2.design_object_id
