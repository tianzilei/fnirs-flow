"""Transactional automated workspace and immutable snapshot activation facade."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from fnirs_flow.history.canonical import canonical_json_bytes

from .contracts import EvidenceSnapshotManifest
from .store import VersionedEvidenceStore


class AutomatedEvidenceWorkspace:
    """SQLite mutable run state; immutable evidence objects remain in snapshots."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, stage TEXT NOT NULL, status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE, version INTEGER NOT NULL DEFAULT 1,
                    payload_json TEXT NOT NULL, provenance_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS state_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, object_id TEXT NOT NULL,
                    old_state TEXT NOT NULL, new_state TEXT NOT NULL, reason_code TEXT NOT NULL,
                    input_sha256 TEXT NOT NULL, output_sha256 TEXT NOT NULL,
                    execution_version TEXT NOT NULL, UNIQUE(object_id, new_state, output_sha256)
                );
                CREATE TABLE IF NOT EXISTS records (
                    object_type TEXT NOT NULL, object_id TEXT NOT NULL, version INTEGER NOT NULL,
                    status TEXT NOT NULL, payload_json TEXT NOT NULL, run_id TEXT NOT NULL,
                    PRIMARY KEY(object_type, object_id, version),
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS records_status_idx ON records(object_type, status);
                CREATE TABLE IF NOT EXISTS api_operations (
                    operation_type TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL, status TEXT NOT NULL,
                    result_json TEXT,
                    PRIMARY KEY(operation_type, idempotency_key)
                );
                """
            )
            connection.commit()
            rows = connection.execute(
                "SELECT run_id, stage, idempotency_key FROM runs WHERE instr(idempotency_key, char(0)) = 0"
            ).fetchall()
            for row in rows:
                scoped_key = f"{row['stage']}\0{row['idempotency_key']}"
                try:
                    connection.execute(
                        "UPDATE runs SET idempotency_key = ? WHERE run_id = ?", (scoped_key, row["run_id"]),
                    )
                except sqlite3.IntegrityError:
                    # Preserve legacy rows on collision; new requests remain safely scoped.
                    continue
            connection.commit()
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def start_run(
        self, *, run_id: str, stage: str, idempotency_key: str,
        payload: dict[str, Any], provenance: dict[str, Any],
    ) -> dict[str, Any]:
        """Create once by idempotency key and return the original run on replay."""
        encoded_payload = canonical_json_bytes(payload).decode()
        encoded_provenance = canonical_json_bytes(provenance).decode()
        scoped_key = f"{stage}\0{idempotency_key}"
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM runs WHERE idempotency_key = ?", (scoped_key,)
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] != encoded_payload or existing["provenance_json"] != encoded_provenance:
                    raise ValueError("idempotency_key_reused_with_different_request")
                return dict(existing)
            connection.execute(
                "INSERT INTO runs(run_id, stage, status, idempotency_key, payload_json, provenance_json) "
                "VALUES (?, ?, 'pending', ?, ?, ?)",
                (run_id, stage, scoped_key, encoded_payload, encoded_provenance),
            )
            return dict(connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())

    def update_run(self, run_id: str, *, expected_version: int, status: str) -> dict[str, Any]:
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE runs SET status = ?, version = version + 1 WHERE run_id = ? AND version = ?",
                (status, run_id, expected_version),
            ).rowcount
            if not changed:
                raise ValueError("run_version_conflict")
            return dict(connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone())

    def reserve_operation(
        self, *, operation_type: str, idempotency_key: str, payload_sha256: str,
    ) -> dict[str, Any] | None:
        """Reserve an API mutation, returning its persisted response on replay."""
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM api_operations WHERE operation_type = ? AND idempotency_key = ?",
                (operation_type, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["payload_sha256"] != payload_sha256:
                    raise ValueError("idempotency_key_reused_with_different_request")
                if existing["status"] != "complete" or not existing["result_json"]:
                    raise ValueError("idempotent_operation_in_progress")
                return cast(dict[str, Any], json.loads(existing["result_json"]))
            connection.execute(
                "INSERT INTO api_operations(operation_type, idempotency_key, payload_sha256, status) "
                "VALUES (?, ?, ?, 'pending')",
                (operation_type, idempotency_key, payload_sha256),
            )
            return None

    def complete_operation(
        self, *, operation_type: str, idempotency_key: str, result: dict[str, Any],
    ) -> None:
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE api_operations SET status = 'complete', result_json = ? "
                "WHERE operation_type = ? AND idempotency_key = ? AND status = 'pending'",
                (canonical_json_bytes(result).decode(), operation_type, idempotency_key),
            ).rowcount
            if changed != 1:
                raise ValueError("idempotent_operation_not_reserved")

    def cancel_operation(self, *, operation_type: str, idempotency_key: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM api_operations WHERE operation_type = ? AND idempotency_key = ? AND status = 'pending'",
                (operation_type, idempotency_key),
            )

    def records(self, object_type: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        clauses, values = [], []
        if object_type:
            clauses.append("object_type = ?")
            values.append(object_type)
        if status:
            clauses.append("status = ?")
            values.append(status)
        query = "SELECT * FROM records"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY object_type, object_id, version"
        connection = self._connect()
        try:
            return [dict(row) for row in connection.execute(query, values)]
        finally:
            connection.close()

    def add_records_atomic(self, run_id: str, records: tuple[dict[str, Any], ...]) -> None:
        with self.transaction() as connection:
            if connection.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone() is None:
                raise KeyError(f"unknown_run:{run_id}")
            for record in records:
                current = connection.execute(
                    "SELECT MAX(version) FROM records WHERE object_type = ? AND object_id = ?",
                    (record["object_type"], record["object_id"]),
                ).fetchone()[0] or 0
                version = record.get("version", current + 1)
                if version != current + 1:
                    raise ValueError("record_version_conflict")
                connection.execute(
                    "INSERT INTO records(object_type, object_id, version, status, payload_json, run_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        record["object_type"], record["object_id"], version,
                        record["status"], canonical_json_bytes(record.get("payload", {})).decode(), run_id,
                    ),
                )

    def record_transition(
        self, *, object_id: str, old_state: str, new_state: str, reason_code: str,
        input_sha256: str, output_sha256: str, execution_version: str,
    ) -> None:
        from .document_pipeline import PipelineState, validate_transition

        old = PipelineState(old_state)
        new = PipelineState(new_state)
        validate_transition(old, new)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", input_sha256) or not re.fullmatch(r"[0-9a-fA-F]{64}", output_sha256):
            raise ValueError("state_event_hash_must_be_sha256")
        with self.transaction() as connection:
            previous = connection.execute(
                "SELECT new_state FROM state_events WHERE object_id = ? ORDER BY sequence DESC LIMIT 1",
                (object_id,),
            ).fetchone()
            if previous is not None and previous["new_state"] != old_state:
                raise ValueError("state_event_disconnected")
            connection.execute(
                "INSERT INTO state_events(object_id, old_state, new_state, reason_code, input_sha256, "
                "output_sha256, execution_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (object_id, old_state, new_state, reason_code, input_sha256, output_sha256, execution_version),
            )

    def lineage(self, object_id: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM state_events WHERE object_id = ? ORDER BY sequence", (object_id,)
            )]
        finally:
            connection.close()


class SnapshotController:
    def __init__(self, store: VersionedEvidenceStore) -> None:
        self.store = store

    def activate(self, snapshot_id: str) -> EvidenceSnapshotManifest:
        manifest = self.store.verify_snapshot(snapshot_id)
        if manifest.status != "published" or not manifest.release_gate_passed:
            raise ValueError("snapshot_release_gates_not_passed")
        return self.store.rollback(snapshot_id, reason="activate")

    def rollback(self, snapshot_id: str) -> EvidenceSnapshotManifest:
        """Switch the active pointer to a verified historical snapshot."""
        manifest = self.store.verify_snapshot(snapshot_id)
        if manifest.status != "published" or not manifest.release_gate_passed:
            raise ValueError("snapshot_release_gates_not_passed")
        return self.store.rollback(snapshot_id, reason="rollback")

    def qa(self, snapshot_id: str) -> dict[str, Any]:
        manifest = self.store.verify_snapshot(snapshot_id)
        path = self.store.snapshots_dir / manifest.snapshot_id / "qa.json"
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
