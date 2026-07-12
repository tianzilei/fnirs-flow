"""Tests for ProjectStore JSON file persistence."""

from __future__ import annotations

import json

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

        meta_file = tmp_path / pid / "project.json"
        assert meta_file.exists()
        data = json.loads(meta_file.read_text())
        assert data["name"] == "Disk Test"
        assert data["id"] == pid

    def test_list_all_after_restart(self, tmp_path):
        store1 = ProjectStore(tmp_path)
        store1.create("P1")
        store1.create("P2")

        store2 = ProjectStore(tmp_path)
        projects = store2.list_all()
        assert len(projects) == 2
        names = {p.name for p in projects}
        assert names == {"P1", "P2"}
