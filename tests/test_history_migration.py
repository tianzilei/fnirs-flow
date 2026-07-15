"""Tests for FlowVCS migration (legacy snapshot import)."""

from __future__ import annotations

from fnirs_flow.history.memory_store import MemoryHistoryStore
from fnirs_flow.history.migration import MigrationReport, migrate_snapshots_to_history
from fnirs_flow.history.service import HistoryService


class TestMigration:
    def test_migrate_empty_snapshots(self):
        store = MemoryHistoryStore()
        svc = HistoryService(store)
        svc.initialize({"nodes": [], "edges": []})
        report = migrate_snapshots_to_history(svc, [])
        assert report.success
        assert report.snapshots_imported == 0
        assert "No snapshots" in report.warnings[0]

    def test_migrate_single_snapshot(self):
        store = MemoryHistoryStore()
        svc = HistoryService(store)
        svc.initialize({"nodes": [], "edges": []})
        snapshots = [
            {
                "snapshot_id": "snap-abc123",
                "flow": {"nodes": [{"id": "n1", "type": "preprocess"}], "edges": []},
                "flow_hash": "hash1",
                "created_at": "2026-07-10T10:00:00Z",
                "description": "First design",
                "tags": ["baseline"],
            }
        ]
        report = migrate_snapshots_to_history(svc, snapshots)
        assert report.success
        assert report.snapshots_imported == 1
        assert report.snapshots_skipped == 0
        # Verify the legacy branch exists
        state = store.get_state()
        assert "legacy/snapshots" in state.refs.heads

    def test_migrate_multiple_snapshots_chain(self):
        store = MemoryHistoryStore()
        svc = HistoryService(store)
        svc.initialize({"nodes": [], "edges": []})
        snapshots = [
            {
                "snapshot_id": "snap-1",
                "flow": {"nodes": [{"id": "n1"}], "edges": []},
                "flow_hash": "h1",
                "created_at": "2026-07-10T10:00:00Z",
            },
            {
                "snapshot_id": "snap-2",
                "flow": {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []},
                "flow_hash": "h2",
                "created_at": "2026-07-11T10:00:00Z",
            },
            {
                "snapshot_id": "snap-3",
                "flow": {"nodes": [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}], "edges": []},
                "flow_hash": "h3",
                "created_at": "2026-07-12T10:00:00Z",
            },
        ]
        report = migrate_snapshots_to_history(svc, snapshots)
        assert report.success
        assert report.snapshots_imported == 3
        # Verify the chain
        state = store.get_state()
        legacy_tip = state.refs.heads["legacy/snapshots"]
        commit = store.get_commit(legacy_tip)
        assert len(commit.parents) == 1  # has parent
        parent = store.get_commit(commit.parents[0])
        assert len(parent.parents) == 1  # has grandparent
        grandparent = store.get_commit(parent.parents[0])
        assert len(grandparent.parents) == 0  # root of legacy chain

    def test_migrate_deduplicates_same_flow(self):
        store = MemoryHistoryStore()
        svc = HistoryService(store)
        svc.initialize({"nodes": [], "edges": []})
        snapshots = [
            {
                "snapshot_id": "snap-1",
                "flow": {"nodes": [{"id": "n1"}], "edges": []},
                "flow_hash": "h1",
                "created_at": "2026-07-10T10:00:00Z",
            },
            {
                "snapshot_id": "snap-2",
                "flow": {"nodes": [{"id": "n1"}], "edges": []},  # same flow
                "flow_hash": "h1",
                "created_at": "2026-07-11T10:00:00Z",
            },
        ]
        report = migrate_snapshots_to_history(svc, snapshots)
        assert report.success
        assert report.snapshots_imported == 1
        assert report.snapshots_skipped == 1
        assert report.objects_deduplicated == 1

    def test_migrate_skips_empty_flows(self):
        store = MemoryHistoryStore()
        svc = HistoryService(store)
        svc.initialize({"nodes": [], "edges": []})
        snapshots = [
            {
                "snapshot_id": "snap-empty",
                "flow": {},
                "flow_hash": "",
                "created_at": "2026-07-10T10:00:00Z",
            },
            {
                "snapshot_id": "snap-valid",
                "flow": {"nodes": [{"id": "n1"}], "edges": []},
                "flow_hash": "h1",
                "created_at": "2026-07-11T10:00:00Z",
            },
        ]
        report = migrate_snapshots_to_history(svc, snapshots)
        assert report.success
        assert report.snapshots_imported == 1
        assert report.snapshots_skipped == 1

    def test_migrate_with_current_flow_creates_main_commit(self):
        store = MemoryHistoryStore()
        svc = HistoryService(store)
        # Initialize with empty flow
        svc.initialize({"nodes": [], "edges": []})
        snapshots = [
            {
                "snapshot_id": "snap-1",
                "flow": {"nodes": [{"id": "n1"}], "edges": []},
                "flow_hash": "h1",
                "created_at": "2026-07-10T10:00:00Z",
            },
        ]
        current_flow = {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": []}
        report = migrate_snapshots_to_history(svc, snapshots, current_flow=current_flow)
        assert report.success
        state = store.get_state()
        # main should point to a commit with the current flow
        main_commit = store.get_commit(state.refs.heads["main"])
        obj = store.get_object(main_commit.design_object_id)
        assert obj.flow == current_flow

    def test_migrate_preserves_snapshot_metadata(self):
        store = MemoryHistoryStore()
        svc = HistoryService(store)
        svc.initialize({"nodes": [], "edges": []})
        snapshots = [
            {
                "snapshot_id": "snap-meta",
                "flow": {"nodes": [{"id": "n1"}], "edges": []},
                "flow_hash": "h1",
                "created_at": "2026-07-10T10:00:00Z",
                "description": "Test snapshot",
                "tags": ["test", "baseline"],
            },
        ]
        report = migrate_snapshots_to_history(svc, snapshots)
        assert report.success
        state = store.get_state()
        commit = store.get_commit(state.refs.heads["legacy/snapshots"])
        assert commit.metadata.get("snapshot_id") == "snap-meta"
        assert commit.metadata.get("tags") == ["test", "baseline"]
        assert commit.reason == "legacy_snapshot_import"

    def test_migration_report_model_dump(self):
        report = MigrationReport()
        report.snapshots_imported = 5
        report.success = True
        d = report.model_dump()
        assert d["snapshots_imported"] == 5
        assert d["success"]
        assert isinstance(d["warnings"], list)
