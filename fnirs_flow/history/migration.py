"""Migration: import legacy snapshots and revisions into FlowVCS history."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fnirs_flow.history.canonical import (
    compute_commit_id,
    compute_object_id,
    compute_semantic_flow_id,
)
from fnirs_flow.history.models import AuthorInfo, DesignCommit, DesignObject
from fnirs_flow.history.service import HistoryService

logger = logging.getLogger(__name__)


class MigrationReport:
    """Report produced by a migration operation."""

    def __init__(self) -> None:
        self.snapshots_imported: int = 0
        self.snapshots_skipped: int = 0
        self.revisions_imported: int = 0
        self.revisions_skipped: int = 0
        self.objects_deduplicated: int = 0
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.success: bool = False

    def model_dump(self) -> dict[str, Any]:
        return {
            "snapshots_imported": self.snapshots_imported,
            "snapshots_skipped": self.snapshots_skipped,
            "revisions_imported": self.revisions_imported,
            "revisions_skipped": self.revisions_skipped,
            "objects_deduplicated": self.objects_deduplicated,
            "warnings": self.warnings,
            "errors": self.errors,
            "success": self.success,
        }


def migrate_snapshots_to_history(
    svc: HistoryService,
    snapshots: list[dict[str, Any]],
    *,
    current_flow: dict[str, Any] | None = None,
) -> MigrationReport:
    """Import legacy ProjectSnapshot entries into design history.

    Snapshots are sorted by created_at, deduplicated by object content,
    and linked as a parent chain under a ``legacy/snapshots`` branch.

    Args:
        svc: Initialized HistoryService.
        snapshots: List of snapshot dicts (from project.json["snapshots"]).
        current_flow: If provided, ensure a commit exists for this flow on main.

    Returns:
        MigrationReport with counts and warnings.
    """
    report = MigrationReport()

    if not snapshots:
        report.warnings.append("No snapshots to migrate")
        report.success = True
        return report

    # Sort snapshots by created_at
    sorted_snaps = sorted(snapshots, key=lambda s: s.get("created_at", ""))

    # Build a parent chain from the snapshots
    parent_id: str | None = None
    seen_object_ids: set[str] = set()

    state = svc.store.get_state()

    for snap in sorted_snaps:
        flow = snap.get("flow")
        if not flow or not isinstance(flow, dict) or not flow.get("nodes"):
            report.snapshots_skipped += 1
            report.warnings.append(f"Snapshot {snap.get('snapshot_id', '?')}: empty or invalid flow, skipped")
            continue

        flow_hash = compute_semantic_flow_id(flow)

        # Build DesignObject
        obj = DesignObject(flow=flow, semantic_flow_hash=flow_hash)
        obj_id = compute_object_id(obj.model_dump())

        if obj_id in seen_object_ids:
            report.objects_deduplicated += 1
            report.snapshots_skipped += 1
            continue

        # Store object if new
        if not svc.store.has_object(obj_id):
            svc.store.put_object(obj, obj_id)
        else:
            report.objects_deduplicated += 1

        seen_object_ids.add(obj_id)

        # Build commit
        created_at = snap.get("created_at", datetime.now(timezone.utc).isoformat())
        snapshot_id = snap.get("snapshot_id", "")
        description = snap.get("description", "")
        tags = snap.get("tags", [])

        parents = [parent_id] if parent_id else []
        commit_payload = {
            "schema_version": "1.0.0",
            "parents": parents,
            "design_object_id": obj_id,
            "semantic_flow_hash": flow_hash,
            "message": description or f"Migrated snapshot {snapshot_id}",
            "author": {"id": "migration", "display_name": "Legacy Import"},
            "created_at": created_at,
            "reason": "legacy_snapshot_import",
            "metadata": {"snapshot_id": snapshot_id, "tags": tags},
        }
        commit_id = compute_commit_id(commit_payload)
        commit = DesignCommit(
            commit_id=commit_id,
            parents=parents,
            design_object_id=obj_id,
            semantic_flow_hash=flow_hash,
            message=description or f"Migrated snapshot {snapshot_id}",
            author=AuthorInfo(id="migration", display_name="Legacy Import"),
            created_at=created_at,
            reason="legacy_snapshot_import",
            metadata={"snapshot_id": snapshot_id, "tags": tags},
        )
        svc.store.put_commit(commit, commit_id)
        parent_id = commit_id
        report.snapshots_imported += 1

    # Create legacy/snapshots branch pointing to the last imported commit
    if parent_id is not None:
        state = svc.store.get_state()
        state.refs.heads["legacy/snapshots"] = parent_id
        # If main still points to the root and we have a current flow,
        # create a main commit on top of the legacy chain
        if current_flow is not None:
            current_hash = compute_semantic_flow_id(current_flow)
            head_commit = svc.store.get_commit(state.head.commit_id)
            if current_hash != head_commit.semantic_flow_hash:
                # Create a new commit for the current state
                obj = DesignObject(flow=current_flow, semantic_flow_hash=current_hash)
                obj_id = compute_object_id(obj.model_dump())
                if not svc.store.has_object(obj_id):
                    svc.store.put_object(obj, obj_id)
                now = datetime.now(timezone.utc).isoformat()
                commit_data = {
                    "schema_version": "1.0.0",
                    "parents": [parent_id],
                    "design_object_id": obj_id,
                    "semantic_flow_hash": current_hash,
                    "message": "Current state after migration",
                    "author": {"id": "migration", "display_name": "Migration"},
                    "created_at": now,
                    "reason": "migration_current_state",
                    "metadata": {},
                }
                cid = compute_commit_id(commit_data)
                c = DesignCommit(
                    commit_id=cid,
                    parents=[parent_id],
                    design_object_id=obj_id,
                    semantic_flow_hash=current_hash,
                    message="Current state after migration",
                    author=AuthorInfo(id="migration", display_name="Migration"),
                    created_at=now,
                    reason="migration_current_state",
                )
                svc.store.put_commit(c, cid)
                state.refs.heads["main"] = cid
                state.head.commit_id = cid
            else:
                # Current flow matches head, just point main to the chain end
                state.refs.heads["main"] = parent_id
                state.head.commit_id = parent_id
        svc.store.save_state(state)

    report.success = True
    return report
