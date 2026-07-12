"""Tests for the export-package API endpoint."""

from __future__ import annotations

import json
import zipfile
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


def _create_and_compile_flow(client, tmp_path):
    """Helper: create project, set demo flow, compile."""
    demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
    flow = json.loads(demo_path.read_text())

    proj = client.post("/api/projects", json={"name": "Export Test"}).json()
    pid = proj["id"]
    client.put(f"/api/projects/{pid}/flow", json={"flow": flow})
    client.post(f"/api/projects/{pid}/compile")
    return pid


def test_export_package_success(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(app)
    pid = _create_and_compile_flow(client, tmp_path)

    resp = client.post(f"/api/projects/{pid}/export-package")
    assert resp.status_code == 200
    data = resp.json()
    assert "package_path" in data
    assert data["size_bytes"] > 0

    # Verify the zip is valid and contains expected files
    pkg = Path(data["package_path"])
    assert pkg.exists()
    with zipfile.ZipFile(pkg) as zf:
        names = zf.namelist()
        assert "plan.json" in names
        assert "RELINK_INSTRUCTIONS.json" in names


def test_export_package_no_compile():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "No Compile"}).json()
    pid = proj["id"]

    resp = client.post(f"/api/projects/{pid}/export-package")
    assert resp.status_code == 400


def test_export_package_not_found():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/api/projects/nonexistent/export-package")
    assert resp.status_code == 400


# ============================================================================
# rerun_package tests
# ============================================================================


class TestRerunPackage:
    def test_rerun_missing_plan(self, tmp_path):
        from fnirs_flow.exporters.package_importer import rerun_package

        with pytest.raises(FileNotFoundError, match="plan.json not found"):
            rerun_package(tmp_path)

    def test_rerun_missing_manifest(self, tmp_path):
        from fnirs_flow.exporters.package_importer import rerun_package

        (tmp_path / "plan.json").write_text("{}", encoding="utf-8")
        with pytest.raises(FileNotFoundError, match="data_manifest.json not found"):
            rerun_package(tmp_path)

    def test_rerun_invalid_local_root(self, tmp_path):
        from fnirs_flow.exporters.package_importer import rerun_package

        (tmp_path / "plan.json").write_text("{}", encoding="utf-8")
        (tmp_path / "data_manifest.json").write_text(
            json.dumps({"local_root": "/nonexistent/path"}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="local_root is invalid"):
            rerun_package(tmp_path)

    def test_rerun_quarantined_atoms(self, tmp_path):
        from fnirs_flow.exporters.package_importer import rerun_package

        (tmp_path / "plan.json").write_text("{}", encoding="utf-8")
        (tmp_path / "data_manifest.json").write_text(
            json.dumps({"local_root": str(tmp_path)}),
            encoding="utf-8",
        )
        (tmp_path / "import_metadata.json").write_text(
            json.dumps({"quarantined_atoms": ["custom_op"]}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="quarantined atoms"):
            rerun_package(tmp_path)
