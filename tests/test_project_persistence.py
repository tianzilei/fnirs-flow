"""Tests for ProjectStore JSON file persistence."""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from unittest.mock import patch

import pytest

from fnirs_flow.api import project_bundle
from fnirs_flow.api.project_bundle import ProjectBundleError, ProjectBundleManager
from fnirs_flow.api.projects import ProjectStore


class TestProjectPersistence:
    def test_project_survives_restart(self, tmp_path):
        store1 = ProjectStore(tmp_path)
        proj = store1.create("Test Project", "A test")
        pid = proj.id

        # Simulate restart: new store instance on same directory
        store2 = ProjectStore(tmp_path)
        loaded = store2.get(pid)
        assert loaded is not None
        assert loaded.name == "Test Project"
        assert loaded.description == "A test"

    def test_flow_survives_restart(self, tmp_path):
        store1 = ProjectStore(tmp_path)
        proj = store1.create("Flow Test")
        pid = proj.id

        flow = {"flow_id": "test-flow", "nodes": [], "edges": []}
        store1.update_flow(pid, flow)

        # Simulate restart
        store2 = ProjectStore(tmp_path)
        loaded_flow = store2.get_flow(pid)
        assert loaded_flow is not None
        assert loaded_flow["flow_id"] == "test-flow"

    def test_snapshot_survives_restart(self, tmp_path):
        from fnirs_flow.api.projects import create_snapshot

        store1 = ProjectStore(tmp_path)
        proj = store1.create("Snapshot Test")
        pid = proj.id

        flow = {"flow_id": "snap-flow", "nodes": [], "edges": []}
        store1.update_flow(pid, flow)
        snap = create_snapshot(store1, pid)
        assert snap is not None

        # Simulate restart
        store2 = ProjectStore(tmp_path)
        loaded = store2.get(pid)
        assert loaded is not None

    def test_empty_dir_no_crash(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        store = ProjectStore(empty)
        assert store.list_all() == []

    def test_nonexistent_dir_no_crash(self, tmp_path):
        store = ProjectStore(tmp_path / "nonexistent")
        assert store.list_all() == []

    def test_project_json_on_disk(self, tmp_path):
        store = ProjectStore(tmp_path)
        proj = store.create("Disk Test")
        pid = proj.id

        bundle = tmp_path / f"{pid}.fnirsflow"
        assert bundle.exists()
        assert not (tmp_path / pid).exists()
        with zipfile.ZipFile(bundle) as archive:
            data = json.loads(archive.read("project.json"))
            manifest = json.loads(archive.read("bundle_manifest.json"))
        assert data["name"] == "Disk Test"
        assert data["id"] == pid
        assert manifest["project_id"] == pid
        assert manifest["files"]["project.json"]["sha256"]

    def test_managed_workspace_changes_are_discarded_on_restart(self, tmp_path):
        store1 = ProjectStore(tmp_path)
        project = store1.create("Protected")
        workspace_metadata = tmp_path / ".workspaces" / project.id / "project.json"
        workspace_metadata.write_text("{}", encoding="utf-8")

        store2 = ProjectStore(tmp_path)

        assert store2.get(project.id).name == "Protected"

    def test_save_keeps_rolling_full_bundle_versions(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("Versioned")
        store.update_flow(project.id, {"flow_id": "v1", "nodes": [], "edges": []})
        store.update_flow(project.id, {"flow_id": "v2", "nodes": [], "edges": []})

        versions = sorted(
            path
            for path in (tmp_path / ".versions" / project.id).glob("*.fnirsflow")
            if not path.name.startswith("._")
        )
        assert len(versions) == 2
        assert store.get(project.id).revision == 3

    def test_legacy_project_folder_is_migrated_to_bundle(self, tmp_path):
        project_id = "legacy01"
        legacy = tmp_path / project_id
        legacy.mkdir()
        (legacy / "project.json").write_text(
            json.dumps(
                {
                    "id": project_id,
                    "name": "Legacy",
                    "description": "",
                    "flow": {},
                    "snapshots": [],
                    "attempts": [],
                    "state": {},
                }
            ),
            encoding="utf-8",
        )

        store = ProjectStore(tmp_path)

        assert store.get(project_id).name == "Legacy"
        assert (tmp_path / f"{project_id}.fnirsflow").is_file()
        assert not legacy.exists()

    def test_legacy_migration_portableizes_runtime_absolute_paths(self, tmp_path):
        project_id = "legacy-paths"
        legacy = tmp_path / project_id
        compiled = legacy / "outputs" / "compiled"
        compiled.mkdir(parents=True)
        (legacy / "project.json").write_text(
            json.dumps(
                {
                    "id": project_id,
                    "name": "Legacy Paths",
                    "description": "",
                    "flow": {},
                    "snapshots": [],
                    "attempts": [],
                    "state": {},
                }
            ),
            encoding="utf-8",
        )
        (compiled / "data_manifest.json").write_text(
            json.dumps({"dataset_id": "d", "local_root": "/Volumes/private/data"}),
            encoding="utf-8",
        )

        store = ProjectStore(tmp_path)

        assert store.get(project_id).name == "Legacy Paths"
        with zipfile.ZipFile(tmp_path / f"{project_id}.fnirsflow") as archive:
            manifest = json.loads(archive.read("outputs/compiled/data_manifest.json"))
        assert manifest["local_root"] == "data"
        assert not legacy.exists()

    def test_retained_revision_can_be_restored_as_new_revision(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("Restore")
        store.update_flow(project.id, {"flow_id": "v1", "nodes": [], "edges": []})
        store.update_flow(project.id, {"flow_id": "v2", "nodes": [], "edges": []})

        restored = store.restore_bundle_revision(project.id, 2)

        assert restored is not None
        assert restored.revision == 4
        assert store.get_flow(project.id)["flow_id"] == "v1"

    def test_corrupt_bundle_is_visible_with_failed_integrity(self, tmp_path):
        store1 = ProjectStore(tmp_path)
        project = store1.create("Corrupt")
        (tmp_path / f"{project.id}.fnirsflow").write_bytes(b"not a zip")

        store2 = ProjectStore(tmp_path)

        # Corrupt projects are now visible with failed integrity status
        corrupt_project = store2.get(project.id)
        assert corrupt_project is not None
        assert corrupt_project.integrity_status == "failed"
        assert corrupt_project.integrity_error is not None

    def test_list_all_after_restart(self, tmp_path):
        store1 = ProjectStore(tmp_path)
        store1.create("P1")
        store1.create("P2")

        store2 = ProjectStore(tmp_path)
        projects = store2.list_all()
        assert len(projects) == 2
        names = {p.name for p in projects}
        assert names == {"P1", "P2"}

    def test_list_all_uses_cached_headers_without_full_verification(self, tmp_path):
        store1 = ProjectStore(tmp_path)
        project = store1.create("Lazy")
        store1.update_flow(project.id, {"flow_id": "lazy-flow", "nodes": [], "edges": []})
        shutil.rmtree(tmp_path / ".workspaces")

        store2 = ProjectStore(tmp_path)
        with patch.object(store2._bundles, "verify", wraps=store2._bundles.verify) as verify:
            projects = store2.list_all()

        assert len(projects) == 1
        assert projects[0].integrity_status == "unknown"
        assert projects[0].verification_scope == "header"
        verify.assert_not_called()
        assert not (tmp_path / ".workspaces" / project.id).exists()

    def test_open_verifies_and_flow_access_materializes_lazy_project(self, tmp_path):
        store1 = ProjectStore(tmp_path)
        project = store1.create("Lazy Open")
        store1.update_flow(project.id, {"flow_id": "lazy-flow", "nodes": [], "edges": []})
        shutil.rmtree(tmp_path / ".workspaces")

        store2 = ProjectStore(tmp_path)
        opened = store2.get(project.id)
        assert opened is not None
        assert opened.integrity_status == "verified"
        assert not (tmp_path / ".workspaces" / project.id).exists()

        flow = store2.get_flow(project.id)
        assert flow is not None
        assert flow["flow_id"] == "lazy-flow"
        assert (tmp_path / ".workspaces" / project.id / "project.json").is_file()

    def test_concurrent_first_load_materializes_workspace_once(self, tmp_path):
        import concurrent.futures
        import time

        store1 = ProjectStore(tmp_path)
        project = store1.create("Concurrent Lazy")
        store1.update_flow(project.id, {"flow_id": "concurrent-flow", "nodes": [], "edges": []})
        shutil.rmtree(tmp_path / ".workspaces")
        store2 = ProjectStore(tmp_path)
        calls = 0
        original_extract = store2._bundles.extract_verified

        def slow_extract(project_id: str):
            nonlocal calls
            calls += 1
            time.sleep(0.05)
            return original_extract(project_id)

        with patch.object(store2._bundles, "extract_verified", side_effect=slow_extract):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: store2.get_flow(project.id), range(2)))

        assert results == [
            {"flow_id": "concurrent-flow", "nodes": [], "edges": []},
            {"flow_id": "concurrent-flow", "nodes": [], "edges": []},
        ]
        assert calls == 1

    def test_bundle_header_read_is_size_bounded(self, tmp_path, monkeypatch):
        store = ProjectStore(tmp_path)
        project = store.create("Bounded Header")
        manager = ProjectBundleManager(tmp_path)
        monkeypatch.setattr(project_bundle, "MAX_BUNDLE_MANIFEST_BYTES", 16)

        with pytest.raises(ProjectBundleError, match="manifest exceeds"):
            manager.read_bundle_header(tmp_path / f"{project.id}.fnirsflow")

    def test_bundle_never_exceeds_ten_mib(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("Bounded")
        payload = store.get_output_dir(project.id) / "derivatives" / "large.txt"
        payload.parent.mkdir(parents=True)
        payload.write_text("x" * (project_bundle.MAX_BUNDLE_BYTES + 1), encoding="utf-8")

        with pytest.raises(ProjectBundleError, match="(10 MiB|per-member limit)"):
            store.commit_project(project.id, reason="oversized_result")

    def test_signal_and_unknown_binary_files_are_not_bundled(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("No signals")
        derivatives = store.get_output_dir(project.id) / "derivatives"
        derivatives.mkdir(parents=True)
        (derivatives / "raw_signal.snirf").write_bytes(os.urandom(1024))
        (derivatives / "intermediate.bin").write_bytes(os.urandom(1024))
        (derivatives / "group_statistics.csv").write_text("beta,p\n1.2,0.01\n", encoding="utf-8")

        store.commit_project(project.id, reason="results_updated")

        with zipfile.ZipFile(tmp_path / f"{project.id}.fnirsflow") as archive:
            names = set(archive.namelist())
        assert "outputs/derivatives/group_statistics.csv" in names
        assert "outputs/derivatives/raw_signal.snirf" not in names
        assert "outputs/derivatives/intermediate.bin" not in names

    def test_macos_metadata_files_are_not_bundled(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("No metadata")
        compiled = store.get_output_dir(project.id) / "compiled"
        compiled.mkdir(parents=True)
        (compiled / "flow.json").write_text("{}", encoding="utf-8")
        (compiled / "._flow.json").write_bytes(b"appledouble")
        (compiled / ".DS_Store").write_bytes(b"finder")
        macosx = store.get_output_dir(project.id) / "__MACOSX"
        macosx.mkdir()
        (macosx / "flow.json").write_text("{}", encoding="utf-8")

        store.commit_project(project.id, reason="metadata_noise")

        with zipfile.ZipFile(tmp_path / f"{project.id}.fnirsflow") as archive:
            names = set(archive.namelist())
        assert "outputs/compiled/flow.json" in names
        assert not any("._" in name or ".DS_Store" in name or "__MACOSX" in name for name in names)

    def test_lazy_bundle_header_rejects_macos_metadata_members(self, tmp_path):
        manager = ProjectBundleManager(tmp_path)
        bundle_path = tmp_path / "sidecar.fnirsflow"
        with zipfile.ZipFile(bundle_path, "w") as archive:
            archive.writestr("project.json", json.dumps({"id": "sidecar", "name": "Sidecar"}))
            archive.writestr("__MACOSX/._project.json", b"appledouble")
            archive.writestr(
                "bundle_manifest.json",
                json.dumps(
                    {
                        "schema_version": project_bundle.BUNDLE_SCHEMA_VERSION,
                        "project_id": "sidecar",
                        "revision": 1,
                        "files": {"project.json": {"sha256": "", "size": 0}},
                    }
                ),
            )

        with pytest.raises(ProjectBundleError, match="macOS metadata"):
            manager.read_bundle_header(bundle_path)

    def test_save_removes_macos_metadata_from_workspace(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("Clean Workspace")
        compiled = store.get_output_dir(project.id) / "compiled"
        compiled.mkdir(parents=True)
        (compiled / "plan.json").write_text("{}", encoding="utf-8")
        (compiled / "._plan.json").write_bytes(b"appledouble")
        (tmp_path / "._uri_bindings.json").write_bytes(b"appledouble")
        versions = tmp_path / ".versions" / project.id
        versions.mkdir(parents=True)
        (versions / "._revision-00000001.fnirsflow").write_bytes(b"appledouble")

        store.commit_project(project.id, reason="metadata_cleanup")

        workspace = store._bundles.workspace_path(project.id)
        assert (workspace / "outputs" / "compiled" / "plan.json").exists()
        assert not list(workspace.rglob("._*"))
        assert not list(tmp_path.rglob("._*"))

    def test_machine_local_paths_are_rejected(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("Portable")
        report = store.get_output_dir(project.id) / "compiled" / "data_manifest.json"
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({"local_root": "/Volumes/private/data"}), encoding="utf-8")

        with pytest.raises(ProjectBundleError, match="absolute path"):
            store.commit_project(project.id, reason="nonportable_manifest")

    @pytest.mark.parametrize("name", ["C:/data/file.json", "folder\\file.json", "a//b.json"])
    def test_archive_member_paths_must_be_portable(self, name):
        with pytest.raises(ProjectBundleError, match="Unsafe path"):
            ProjectBundleManager._validate_member_path(name)

    def test_uri_bindings_are_machine_local_sidecars(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("Bindings")
        data_root = tmp_path / "raw-data"
        data_root.mkdir()
        store.bind_dataset("dataset", data_root)
        store.commit_project(project.id, reason="binding_updated")

        with zipfile.ZipFile(tmp_path / f"{project.id}.fnirsflow") as archive:
            assert "uri_bindings.json" not in archive.namelist()
        assert store.get_dataset_binding("dataset") == data_root.resolve()

    def test_corrupt_bundles_do_not_consume_revision_slots(self, tmp_path):
        # Use ProjectBundleManager directly with retained_versions=2
        manager = ProjectBundleManager(tmp_path, retained_versions=2)
        project_id = "quarantine01"
        workspace = manager.workspace_path(project_id)
        workspace.mkdir(parents=True)
        (workspace / "project.json").write_text(json.dumps({
            "id": project_id, "name": "Q", "description": "",
            "flow": {}, "snapshots": [], "attempts": [], "state": {},
        }), encoding="utf-8")
        # Save 3 revisions — with retained_versions=2, oldest gets evicted
        manager.save(project_id, reason="v1")
        manager.save(project_id, reason="v2")
        manager.save(project_id, reason="v3")
        version_dir = tmp_path / ".versions" / project_id
        revisions = sorted(p for p in version_dir.glob("*.fnirsflow") if p.name.startswith("revision-"))
        assert len(revisions) == 2
        # Add a corrupt bundle
        (version_dir / "corrupt-20260714T000000.fnirsflow").write_bytes(b"bad")
        # Save one more — should evict 1 revision but keep corrupt
        manager.save(project_id, reason="v4")
        revisions_after = sorted(p for p in version_dir.glob("*.fnirsflow") if p.name.startswith("revision-"))
        corrupt_files = list(version_dir.glob("corrupt-*.fnirsflow"))
        assert len(revisions_after) == 2  # still 2 revisions
        assert len(corrupt_files) == 1  # corrupt untouched

    def test_single_file_size_limit_rejected(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("Big File")
        big_file = store.get_output_dir(project.id) / "derivatives" / "huge.csv"
        big_file.parent.mkdir(parents=True)
        big_file.write_text("x" * (project_bundle.MAX_MEMBER_BYTES + 1), encoding="utf-8")
        with pytest.raises(ProjectBundleError, match="per-member limit"):
            store.commit_project(project.id, reason="oversized_member")

    def test_debounce_flush_and_cancel(self, tmp_path):
        import time
        store = ProjectStore(tmp_path)
        project = store.create("Debounce")
        # Debounced update should not persist immediately
        store.update_flow(project.id, {"flow_id": "db1", "nodes": [], "edges": []}, debounce=True)
        # The in-memory state is updated, but the bundle may not be persisted yet
        # Cancel before the timer fires
        store.cancel_debounce(project.id)
        # Short sleep to let any pending timer attempt to fire
        time.sleep(0.1)
        # Reload from disk — the debounced persist was cancelled
        store2 = ProjectStore(tmp_path)
        loaded_flow = store2.get_flow(project.id)
        # Bundle should reflect the last non-debounced state (initial creation)
        assert loaded_flow == {}

    def test_save_failure_preserves_original_bundle(self, tmp_path):
        store = ProjectStore(tmp_path)
        project = store.create("Fail Save")
        store.update_flow(project.id, {"flow_id": "ok", "nodes": [], "edges": []})
        original_bundle = tmp_path / f"{project.id}.fnirsflow"
        original_size = original_bundle.stat().st_size
        # Mock os.replace to fail during the next save
        with patch("fnirs_flow.api.project_bundle.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                store.update_flow(project.id, {"flow_id": "fail", "nodes": [], "edges": []})
        # Original bundle should be intact
        assert original_bundle.exists()
        assert original_bundle.stat().st_size == original_size

    def test_cross_directory_bundle_move(self, tmp_path):
        # Create a project in one directory
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        store1 = ProjectStore(source_dir)
        project = store1.create("Moveable", "Cross-dir test")
        store1.update_flow(project.id, {"flow_id": "moved", "nodes": [{"id": "n1"}], "edges": []})
        # Copy the bundle to a new directory
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        bundle_file = source_dir / f"{project.id}.fnirsflow"
        shutil.copy2(bundle_file, dest_dir / f"{project.id}.fnirsflow")
        # Open with a new store — should work without the original workspace
        store2 = ProjectStore(dest_dir)
        loaded = store2.get(project.id)
        assert loaded is not None
        assert loaded.name == "Moveable"
        assert loaded.integrity_status == "verified"
        flow = store2.get_flow(project.id)
        assert flow["flow_id"] == "moved"
        assert len(flow["nodes"]) == 1

    def test_cross_directory_with_uri_rebinding(self, tmp_path):
        # Create a project with URI bindings
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        data_root = tmp_path / "external-data"
        data_root.mkdir()
        store1 = ProjectStore(source_dir)
        project = store1.create("URI Move")
        store1.bind_dataset("ds001", data_root)
        store1.update_flow(project.id, {"flow_id": "uri-flow", "nodes": [], "edges": []})
        # Copy bundle to new location
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        bundle_file = source_dir / f"{project.id}.fnirsflow"
        shutil.copy2(bundle_file, dest_dir / f"{project.id}.fnirsflow")
        # Open in new store — URI bindings are machine-local, need rebinding
        store2 = ProjectStore(dest_dir)
        loaded = store2.get(project.id)
        assert loaded is not None
        # Rebind the dataset in the new location
        new_data_root = tmp_path / "new-external-data"
        new_data_root.mkdir()
        store2.bind_dataset("ds001", new_data_root)
        assert store2.get_dataset_binding("ds001") == new_data_root.resolve()
