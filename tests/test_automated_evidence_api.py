from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from fnirs_flow.api.app import app


def test_automated_run_endpoint_is_idempotent(tmp_path: Path) -> None:
    original = app.state.store_provider
    store = original()
    app.state.store_provider = lambda: store
    original_base = store._base_dir
    store._base_dir = tmp_path
    try:
        with TestClient(app) as client:
            request = {
                "source_ids": ["S1"], "slot_ids": ["motion_correction_slot"],
                "versions": {"extractor_a": "model-a-1", "extractor_b": "model-b-1"},
            }
            first = client.post(
                "/api/evidence/runs/extract", headers={"Idempotency-Key": "key-1"}, json=request,
            )
            replay = client.post(
                "/api/evidence/runs/extract", headers={"Idempotency-Key": "key-1"}, json=request,
            )
            assert first.status_code == replay.status_code == 202
            assert first.json()["run_id"] == replay.json()["run_id"]
            changed = client.post(
                "/api/evidence/runs/extract", headers={"Idempotency-Key": "key-1"},
                json={**request, "source_ids": ["S2"]},
            )
            assert changed.status_code == 422
    finally:
        store._base_dir = original_base
        app.state.store_provider = original


def test_candidate_snapshot_cannot_activate_without_release_gate(tmp_path: Path) -> None:
    original = app.state.store_provider
    store = original()
    app.state.store_provider = lambda: store
    original_base = store._base_dir
    store._base_dir = tmp_path
    try:
        with TestClient(app) as client:
            built = client.post(
                "/api/evidence/snapshots/build", headers={"Idempotency-Key": "snap-1"},
                json={"input_sha256": "a" * 64, "slot_id": "motion_correction_slot"},
            )
            assert built.status_code == 200
            snapshot_id = built.json()["manifest"]["snapshot_id"]
            activated = client.post(
                "/api/evidence/snapshots/activate",
                headers={"Idempotency-Key": "activate-1"},
                json={"snapshot_id": snapshot_id},
            )
            assert activated.status_code == 422
            assert activated.json()["detail"]["reason_code"] == "snapshot_release_gates_not_passed"
            rolled_back = client.post(
                f"/api/evidence/snapshots/{snapshot_id}/rollback",
                headers={"Idempotency-Key": "rollback-1"},
            )
            assert rolled_back.status_code == 422
    finally:
        store._base_dir = original_base
        app.state.store_provider = original
