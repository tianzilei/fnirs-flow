"""Tests for FastAPI backend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fnirs_flow.api.app import app
from fnirs_flow.api.projects import ProjectStore


@pytest.fixture(autouse=True)
def setup_store(tmp_path):
    """Use a temporary store for each test."""
    import fnirs_flow.api.app as api_module

    api_module._store = ProjectStore(tmp_path)
    yield
    api_module._store = None


def test_health():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_invalid_content_length_returns_400():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/health", headers={"content-length": "invalid"})
    assert resp.status_code == 400


def test_create_project():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/api/projects", json={"name": "Test", "description": "desc"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test"
    assert "id" in data


def test_list_projects():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    client.post("/api/projects", json={"name": "P1"})
    client.post("/api/projects", json={"name": "P2"})
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_update_and_get_flow():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "Test"}).json()
    pid = proj["id"]

    flow = {"flow_id": "f1", "nodes": [], "edges": []}
    resp = client.put(f"/api/projects/{pid}/flow", json={"flow": flow})
    assert resp.status_code == 200

    resp = client.get(f"/api/projects/{pid}/flow")
    assert resp.status_code == 200
    assert resp.json()["flow_id"] == "f1"


def test_validate_flow():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "Test"}).json()
    pid = proj["id"]

    # Set a valid flow
    demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
    flow = json.loads(demo_path.read_text())
    client.put(f"/api/projects/{pid}/flow", json={"flow": flow})

    resp = client.post(f"/api/projects/{pid}/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_valid" in data


def test_compile_flow():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "Test"}).json()
    pid = proj["id"]

    demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
    flow = json.loads(demo_path.read_text())
    client.put(f"/api/projects/{pid}/flow", json={"flow": flow})

    resp = client.post(f"/api/projects/{pid}/compile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["steps"] > 0


def test_compile_without_flow():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "Test"}).json()
    pid = proj["id"]

    resp = client.post(f"/api/projects/{pid}/compile")
    assert resp.status_code == 404


def test_create_snapshot():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "Test"}).json()
    pid = proj["id"]

    flow = {"flow_id": "f1", "nodes": [], "edges": []}
    client.put(f"/api/projects/{pid}/flow", json={"flow": flow})

    resp = client.post(f"/api/projects/{pid}/snapshots")
    assert resp.status_code == 200
    data = resp.json()
    assert "snapshot_id" in data
    assert "flow_hash" in data
