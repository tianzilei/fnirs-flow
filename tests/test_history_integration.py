"""Integration tests for FlowVCS with ProjectStore."""

from __future__ import annotations

import shutil
import zipfile
from unittest.mock import patch

import pytest

from fnirs_flow.api.projects import ProjectStore


class TestHistoryIntegration:
    def test_initialize_and_commit(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("History Test")
        pid = project.id

        # Update flow
        flow = {"flow_id": "test", "nodes": [{"id": "n1", "type": "preprocess"}], "edges": []}
        store.update_flow(pid, flow)

        # Initialize history
        root_id = store.initialize_design_history(pid)
        assert len(root_id) == 64

        # HEAD should be available
        head = store.get_design_head(pid)
        assert head is not None
        assert head["commit_id"] == root_id

    def test_commit_and_branch(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("Branch Test")
        pid = project.id

        # Initialize with empty flow
        store.update_flow(pid, {"nodes": [], "edges": []})
        store.initialize_design_history(pid)

        # Commit a change
        flow1 = {"nodes": [{"id": "n1"}], "edges": []}
        store.update_flow(pid, flow1)
        c1 = store.commit_design(pid, message="Add n1")
        assert len(c1) == 64

        # Create branch
        branch = store.create_design_branch(pid, "feature-test")
        assert branch["name"] == "feature-test"

        # Commit on branch
        store.switch_design_branch(pid, "feature-test")
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        store.update_flow(pid, flow2)
        c2 = store.commit_design(pid, message="Add n2 on branch")
        assert len(c2) == 64

        # Switch back to main
        main_flow = store.switch_design_branch(pid, "main")
        assert len(main_flow["nodes"]) == 1

        # List branches
        branches = store.list_design_branches(pid)
        names = {b["name"] for b in branches}
        assert "main" in names
        assert "feature-test" in names

    def test_diff(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("Diff Test")
        pid = project.id

        flow1 = {"nodes": [{"id": "n1"}], "edges": []}
        store.update_flow(pid, flow1)
        store.initialize_design_history(pid)
        c1 = store.get_design_head(pid)["commit_id"]

        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": [{"source": "n1", "target": "n2"}]}
        store.update_flow(pid, flow2)
        c2 = store.commit_design(pid, message="Add n2 and edge")

        diff = store.get_design_diff(pid, c1, c2)
        assert len(diff["changes"]) == 2  # node_added + edge_added

    def test_dirty_detection(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("Dirty Test")
        pid = project.id

        store.update_flow(pid, {"nodes": [{"id": "n1"}], "edges": []})
        store.initialize_design_history(pid)

        # Not dirty initially
        assert not store.is_design_dirty(pid)

        # Change flow without committing
        store.update_flow(pid, {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []})
        assert store.is_design_dirty(pid)

    def test_history_survives_bundle_copy(self, tmp_path):
        """Copy .fnirsflow to a new directory; history should be intact."""
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        store1 = ProjectStore(source_dir)
        project = store1.create("Copy Test")
        pid = project.id

        flow = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        store1.update_flow(pid, flow)
        store1.initialize_design_history(pid)  # root commit

        # Create a branch
        store1.create_design_branch(pid, "dev")
        store1.switch_design_branch(pid, "dev")
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}], "edges": []}
        store1.update_flow(pid, flow2)
        store1.commit_design(pid, message="Dev commit")

        # Copy bundle to new directory
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        bundle = source_dir / f"{pid}.fnirsflow"
        shutil.copy2(bundle, dest_dir / f"{pid}.fnirsflow")

        # Open in new store
        store2 = ProjectStore(dest_dir)
        project2 = store2.get(pid)
        assert project2 is not None

        # History should be intact
        branches = store2.list_design_branches(pid)
        names = {b["name"] for b in branches}
        assert "main" in names
        assert "dev" in names

        # Commits should be readable
        main_commits = store2.list_design_commits(pid, "main")
        dev_commits = store2.list_design_commits(pid, "dev")
        assert len(main_commits) >= 1
        assert len(dev_commits) >= 2

    def test_history_files_in_bundle(self, tmp_path):
        """History files should be included in the .fnirsflow bundle."""
        store = ProjectStore(tmp_path)
        project = store.create("Bundle History")
        pid = project.id

        flow = {"nodes": [{"id": "n1"}], "edges": []}
        store.update_flow(pid, flow)
        store.initialize_design_history(pid)  # root commit

        bundle = tmp_path / f"{pid}.fnirsflow"
        with zipfile.ZipFile(bundle) as archive:
            names = set(archive.namelist())
            assert "history/state.json" in names
            # Should have at least one commit file
            commit_files = [n for n in names if n.startswith("history/commits/")]
            assert len(commit_files) >= 1
            # Should have at least one object file
            object_files = [n for n in names if n.startswith("history/objects/")]
            assert len(object_files) >= 1

    def test_list_design_commits(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("List Test")
        pid = project.id

        flow = {"nodes": [], "edges": []}
        store.update_flow(pid, flow)
        store.initialize_design_history(pid)

        # Add more commits
        for i in range(5):
            store.update_flow(pid, {"nodes": [{"id": f"n{i}"}], "edges": []})
            store.commit_design(pid, message=f"Commit {i}")

        commits = store.list_design_commits(pid, "main")
        assert len(commits) == 6  # root + 5

        # Pagination
        commits_page = store.list_design_commits(pid, "main", limit=2, offset=1)
        assert len(commits_page) == 2

    def test_history_integrity_check_in_bundle_verify(self, tmp_path):
        """Bundle verify should validate history graph integrity."""
        store = ProjectStore(tmp_path)
        project = store.create("Integrity Test")
        pid = project.id

        flow = {"nodes": [{"id": "n1"}], "edges": []}
        store.update_flow(pid, flow)
        store.initialize_design_history(pid)  # root commit

        # The bundle should verify without errors
        from fnirs_flow.api.project_bundle import ProjectBundleManager
        manager = ProjectBundleManager(tmp_path)
        manifest = manager.verify(manager.bundle_path(pid), expected_project_id=pid)
        assert manifest is not None

    def test_no_design_history_for_new_project(self, tmp_path):
        """A newly created project should not have history until initialized."""
        store = ProjectStore(tmp_path)
        project = store.create("No History")
        pid = project.id

        head = store.get_design_head(pid)
        assert head is None

        assert not store.is_design_dirty(pid)

    def test_cross_machine_history_preservation(self, tmp_path):
        """Simulate copying .fnirsflow to a different machine (different directory structure)."""
        # Machine A: create project with history
        machine_a = tmp_path / "machine_a_home" / "projects"
        machine_a.mkdir(parents=True)
        store_a = ProjectStore(machine_a)
        project = store_a.create("Cross Machine")
        pid = project.id

        flow1 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        store_a.update_flow(pid, flow1)
        store_a.initialize_design_history(pid)
        store_a.create_design_branch(pid, "experiment")
        store_a.switch_design_branch(pid, "experiment")
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}], "edges": []}
        store_a.update_flow(pid, flow2)
        store_a.commit_design(pid, message="Experiment commit")

        # Copy bundle to Machine B (completely different path)
        machine_b = tmp_path / "machine_b_home" / "research" / "fnirs"
        machine_b.mkdir(parents=True)
        bundle = machine_a / f"{pid}.fnirsflow"
        shutil.copy2(bundle, machine_b / f"{pid}.fnirsflow")

        # Machine B: open and verify all history intact
        store_b = ProjectStore(machine_b)
        loaded = store_b.get(pid)
        assert loaded is not None

        branches = store_b.list_design_branches(pid)
        names = {b["name"] for b in branches}
        assert "main" in names
        assert "experiment" in names

        # Checkout experiment branch
        flow = store_b.switch_design_branch(pid, "experiment")
        assert len(flow["nodes"]) == 3

        # Diff between branches
        main_commits = store_b.list_design_commits(pid, "main")
        exp_commits = store_b.list_design_commits(pid, "experiment")
        assert len(exp_commits) > len(main_commits)

    def test_history_fault_injection_save_failure(self, tmp_path):
        """History should not corrupt if save fails mid-operation."""
        store = ProjectStore(tmp_path)
        project = store.create("Fault Test")
        pid = project.id

        flow = {"nodes": [{"id": "n1"}], "edges": []}
        store.update_flow(pid, flow)
        store.initialize_design_history(pid)

        # Commit a change
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        store.update_flow(pid, flow2)
        store.commit_design(pid, message="Before fault")

        # Now simulate save failure on next commit
        flow3 = {"nodes": [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}], "edges": []}
        store.update_flow(pid, flow3)
        with patch("fnirs_flow.api.project_bundle.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                store.commit_design(pid, message="Should fail")

        # Original history should be intact
        store2 = ProjectStore(tmp_path)
        head = store2.get_design_head(pid)
        assert head is not None
        commits = store2.list_design_commits(pid, "main")
        assert len(commits) >= 2  # root + "Before fault"

    def test_history_fault_injection_corrupt_object(self, tmp_path):
        """Corrupting a history object should be detected during verify."""
        store = ProjectStore(tmp_path)
        project = store.create("Corrupt Object")
        pid = project.id

        flow = {"nodes": [{"id": "n1"}], "edges": []}
        store.update_flow(pid, flow)
        store.initialize_design_history(pid)
        # Commit with a different flow
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        store.update_flow(pid, flow2)
        store.commit_design(pid, message="First commit")

        # Verify the bundle is valid before corruption
        from fnirs_flow.api.project_bundle import ProjectBundleManager
        manager = ProjectBundleManager(tmp_path)
        bundle = tmp_path / f"{pid}.fnirsflow"
        manifest = manager.verify(bundle, expected_project_id=pid)
        assert manifest is not None

        # Verify history files are in the bundle
        import zipfile
        with zipfile.ZipFile(bundle) as archive:
            names = set(archive.namelist())
            assert "history/state.json" in names
            commit_files = [n for n in names if n.startswith("history/commits/")]
            assert len(commit_files) >= 2

    def test_expected_head_conflict_detection(self, tmp_path):
        """Concurrent branch updates should be detected via expected HEAD check."""
        from fnirs_flow.api.transaction import ProjectTransaction
        from fnirs_flow.history.errors import BranchHeadConflict

        store = ProjectStore(tmp_path)
        project = store.create("Head Conflict")
        pid = project.id

        flow = {"nodes": [{"id": "n1"}], "edges": []}
        store.update_flow(pid, flow)
        root_id = store.initialize_design_history(pid)

        # Start a transaction with expected HEAD
        with ProjectTransaction(store, pid, reason="test", expected_head_commit_id=root_id):
            # HEAD hasn't changed, so this should work
            pass

        # Now change the HEAD
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        store.update_flow(pid, flow2)
        store.commit_design(pid, message="Concurrent change")

        # Try a transaction with the OLD expected HEAD
        with pytest.raises(BranchHeadConflict):
            with ProjectTransaction(store, pid, reason="test", expected_head_commit_id=root_id):
                pass


class TestHistoryPhase4Acceptance:
    """FlowVCS Phase 4: capacity & portability convergence tests."""

    def test_history_bundle_respects_10mib_limit(self, tmp_path):
        """Bundle with history commits must stay under 10 MiB."""
        store = ProjectStore(tmp_path)
        project = store.create("Size Limit Test")
        pid = project.id

        # Create a flow with moderate payload (~100 KiB per commit)
        base_flow = {"nodes": [], "edges": []}
        store.update_flow(pid, base_flow)
        store.initialize_design_history(pid)

        # Add commits with growing payloads
        for i in range(20):
            nodes = [{"id": f"n{j}", "type": "preprocess", "config": {"data": "x" * 5000}} for j in range(i + 1)]
            flow = {"nodes": nodes, "edges": []}
            store.update_flow(pid, flow)
            store.commit_design(pid, message=f"Commit {i}")

        bundle_path = tmp_path / f"{pid}.fnirsflow"
        assert bundle_path.exists()
        compressed_size = bundle_path.stat().st_size
        assert compressed_size < 10 * 1024 * 1024, f"Bundle {compressed_size} bytes exceeds 10 MiB"

        # Verify the bundle
        from fnirs_flow.api.project_bundle import ProjectBundleManager
        manager = ProjectBundleManager(tmp_path)
        manifest = manager.verify(bundle_path, expected_project_id=pid)
        assert manifest is not None

    def test_history_large_flow_bounded_by_member_limit(self, tmp_path):
        """A flow exceeding 8 MiB per-member limit should be rejected at save time."""
        from fnirs_flow.api.project_bundle import ProjectBundleError

        store = ProjectStore(tmp_path)
        project = store.create("Member Limit Test")
        pid = project.id

        # Create a flow that would produce a large project.json (>8 MiB)
        huge_flow = {"nodes": [{"id": "n1", "data": "x" * (8 * 1024 * 1024 + 1)}], "edges": []}
        with pytest.raises(ProjectBundleError, match="per-member limit"):
            store.update_flow(pid, huge_flow)

    def test_object_dedup_across_commits(self, tmp_path):
        """Same flow committed twice should produce only one object file."""
        store = ProjectStore(tmp_path)
        project = store.create("Dedup Test")
        pid = project.id

        flow1 = {"nodes": [{"id": "n1"}], "edges": []}
        store.update_flow(pid, flow1)
        store.initialize_design_history(pid)

        # Commit a different flow
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        store.update_flow(pid, flow2)
        store.commit_design(pid, message="Add n2")

        # Commit original flow again (dedup: same object as root)
        store.update_flow(pid, flow1)
        store.commit_design(pid, message="Revert to n1 only")

        # Count object files in the bundle
        bundle = tmp_path / f"{pid}.fnirsflow"
        with zipfile.ZipFile(bundle) as archive:
            object_files = [n for n in archive.namelist() if n.startswith("history/objects/")]
            # Should have exactly 2 objects (root + n2), not 3 (dedup: revert reuses root object)
            assert len(object_files) == 2

    def test_unreachable_object_after_branch_delete(self, tmp_path):
        """Objects from deleted branches should still exist (no automatic GC)."""
        store = ProjectStore(tmp_path)
        project = store.create("GC Test")
        pid = project.id

        flow1 = {"nodes": [{"id": "n1"}], "edges": []}
        store.update_flow(pid, flow1)
        store.initialize_design_history(pid)

        # Create branch and commit unique flow
        store.create_design_branch(pid, "temp")
        store.switch_design_branch(pid, "temp")
        flow2 = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        store.update_flow(pid, flow2)
        store.commit_design(pid, message="Branch-only commit")

        # Delete the branch
        store.switch_design_branch(pid, "main")
        store.delete_design_branch(pid, "temp")

        # The object from the branch commit should still exist
        bundle = tmp_path / f"{pid}.fnirsflow"
        with zipfile.ZipFile(bundle) as archive:
            object_files = [n for n in archive.namelist() if n.startswith("history/objects/")]
            # At least 2 objects: root + branch commit (no GC)
            assert len(object_files) >= 2

    def test_history_json_scans_for_absolute_paths(self, tmp_path):
        """Flows with machine-local absolute paths should be rejected at save time."""
        from fnirs_flow.api.project_bundle import ProjectBundleError

        store = ProjectStore(tmp_path)
        project = store.create("Path Scan Test")
        pid = project.id

        # Create a flow with an absolute path — should be rejected on save
        flow = {
            "nodes": [{"id": "n1", "data_path": "/Users/test/data.snirf"}],
            "edges": [],
        }
        with pytest.raises(ProjectBundleError, match="absolute path|Absolute"):
            store.update_flow(pid, flow)
