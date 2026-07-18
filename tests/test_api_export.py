"""Tests for the export-package API endpoint."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from fnirs_flow.api.app import app
from fnirs_flow.api.projects import ProjectStore


@pytest.fixture(autouse=True)
def setup_store(tmp_path):
    """Use a temporary store for each test."""
    import fnirs_flow.api.app as api_module

    store = ProjectStore(tmp_path)
    with patch.object(api_module, "_store", store):
        yield


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
        assert "manifest.json" in names


def test_export_removes_macos_appledouble_sidecar(tmp_path, monkeypatch):
    import shutil

    from fastapi.testclient import TestClient

    client = TestClient(app)
    pid = _create_and_compile_flow(client, tmp_path)
    real_copy2 = shutil.copy2

    def copy2_with_sidecar(src, dst, *args, **kwargs):
        result = real_copy2(src, dst, *args, **kwargs)
        Path(dst).with_name(f"._{Path(dst).name}").write_bytes(b"appledouble")
        Path(dst).parent.with_name(f"._{Path(dst).parent.name}").write_bytes(b"appledouble")
        outputs_dir = Path(dst).parent.parent
        outputs_dir.with_name(f"._{outputs_dir.name}").write_bytes(b"appledouble")
        (outputs_dir.parent / "._project.json").write_bytes(b"appledouble")
        return result

    monkeypatch.setattr(shutil, "copy2", copy2_with_sidecar)

    resp = client.post(f"/api/projects/{pid}/export-package")

    assert resp.status_code == 200
    package_path = Path(resp.json()["package_path"])
    workspace = package_path.parent.parent.parent
    assert package_path.exists()
    assert not package_path.with_name(f"._{package_path.name}").exists()
    assert not package_path.parent.with_name(f"._{package_path.parent.name}").exists()
    assert not list(workspace.rglob("._*"))


@pytest.mark.parametrize(
    ("profile", "expected", "unexpected"),
    [
        ("submission_package", "risk_register.json", "execution_dag.json"),
        ("reviewer_package", "execution_dag.json", None),
        ("reproducibility_package", "reproducibility_manifest.json", None),
    ],
)
def test_export_profile_controls_archive_contents(tmp_path, profile, expected, unexpected):
    from fastapi.testclient import TestClient

    client = TestClient(app)
    pid = _create_and_compile_flow(client, tmp_path)
    response = client.post(
        f"/api/projects/{pid}/export-package",
        json={"profile": profile},
    )

    assert response.status_code == 200
    assert response.json()["profile"] == profile
    with zipfile.ZipFile(response.json()["package_path"]) as archive:
        names = archive.namelist()
        assert expected in names
        if unexpected:
            assert unexpected not in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["profile"] == profile


def test_package_profiles_endpoint_is_authoritative():
    from fastapi.testclient import TestClient

    response = TestClient(app).get("/api/package-profiles")
    assert response.status_code == 200
    assert {item["profile_id"] for item in response.json()} == {
        "reproducibility_package",
        "submission_package",
        "reviewer_package",
    }


def test_export_package_no_compile():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "No Compile"}).json()
    pid = proj["id"]

    resp = client.post(f"/api/projects/{pid}/export-package")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "PLAN_NOT_COMPILED"


def test_export_package_not_found():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/api/projects/nonexistent/export-package")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


def test_imported_project_is_read_only_and_fork_owns_package(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(app)
    source_id = _create_and_compile_flow(client, tmp_path)
    package_response = client.post(f"/api/projects/{source_id}/export-package")
    package_path = package_response.json()["package_path"]

    target = client.post("/api/projects", json={"name": "Imported"}).json()
    target_id = target["id"]
    imported = client.post(
        f"/api/projects/{target_id}/import-package",
        params={"package_path": package_path},
    )
    assert imported.status_code == 200
    assert client.get(f"/api/projects/{target_id}/flow").json()["flow_id"]
    assert (
        client.put(
            f"/api/projects/{target_id}/flow",
            json={"flow": {"flow_id": "forbidden"}},
        ).status_code
        == 409
    )
    assert client.post(f"/api/projects/{target_id}/compile").status_code == 409

    forked = client.post(
        f"/api/projects/{target_id}/fork",
        params={"fork_name": "Editable Copy"},
    )
    assert forked.status_code == 200
    fork_id = forked.json()["fork_project_id"]
    fork_flow = client.get(f"/api/projects/{fork_id}/flow").json()
    assert fork_flow["flow_id"]
    import fnirs_flow.api.app as api_module

    fork_output = api_module.get_store().get_output_dir(fork_id)
    assert (fork_output / "compiled" / "plan.json").exists()
    fork_status = client.get(f"/api/projects/{fork_id}/import-status").json()
    assert not fork_status["read_only"]


def test_relink_imported_data_updates_manifest(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(app)
    source_id = _create_and_compile_flow(client, tmp_path)
    import fnirs_flow.api.app as api_module

    compiled = api_module.get_store().get_output_dir(source_id) / "compiled"
    (compiled / "data_manifest.json").write_text(
        json.dumps(
            {
                "local_root": "/source/machine",
                "subject_session_runs": [
                    {"relative_path": "sub-01/run.snirf", "path": "/source/machine/sub-01/run.snirf"}
                ],
            }
        ),
        encoding="utf-8",
    )
    package_path = client.post(f"/api/projects/{source_id}/export-package").json()["package_path"]
    target_id = client.post("/api/projects", json={"name": "Relink"}).json()["id"]
    assert (
        client.post(
            f"/api/projects/{target_id}/import-package",
            params={"package_path": package_path},
        ).status_code
        == 200
    )

    data_root = tmp_path / "local-data"
    data_root.mkdir()
    response = client.post(
        f"/api/projects/{target_id}/relink-data",
        params={"data_root": str(data_root)},
    )
    assert response.status_code == 200
    manifest = json.loads(
        (api_module.get_store().get_output_dir(target_id) / "compiled" / "data_manifest.json").read_text()
    )
    assert manifest["local_root"] == ""
    assert manifest["subject_session_runs"][0]["path"] == "external-data://dataset/sub-01/run.snirf"
    assert manifest["subject_session_runs"][0]["uri"] == "external-data://dataset/sub-01/run.snirf"
    assert response.json()["data_uri"] == "external-data://dataset/"


def test_results_endpoint_reads_imported_group_results(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Results"}).json()
    import fnirs_flow.api.app as api_module

    outdir = api_module.get_store().get_output_dir(project["id"])
    group_dir = outdir / "compiled" / "derivatives" / "group"
    group_dir.mkdir(parents=True)
    (group_dir / "group_summary.json").write_text(
        json.dumps({"summaries": [{"roi": "motor", "mean_beta": 1.25}]}),
        encoding="utf-8",
    )
    (group_dir / "contrast_effects.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><text>contrast</text></svg>',
        encoding="utf-8",
    )

    response = client.get(f"/api/projects/{project['id']}/results/group")

    assert response.status_code == 200
    assert response.json()["file_count"] == 1
    assert response.json()["files"][0]["data"]["summaries"][0]["roi"] == "motor"
    assert response.json()["figures"][0]["path"] == "derivatives/group/contrast_effects.svg"
    assert "contrast" in response.json()["figures"][0]["svg"]


def test_results_endpoint_sanitizes_svg_figures(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Sanitize Results"}).json()
    import fnirs_flow.api.app as api_module

    outdir = api_module.get_store().get_output_dir(project["id"])
    group_dir = outdir / "compiled" / "derivatives" / "group"
    group_dir.mkdir(parents=True)
    (group_dir / "contrast_effects.svg").write_text(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
            '<script>alert(1)</script><a href="javascript:alert(2)"><text>bad</text></a>'
            '<text onclick="alert(3)">contrast</text></svg>'
        ),
        encoding="utf-8",
    )

    response = client.get(f"/api/projects/{project['id']}/results/group")

    assert response.status_code == 200
    svg = response.json()["figures"][0]["svg"]
    assert "contrast" in svg
    assert "script" not in svg.lower()
    assert "javascript:" not in svg.lower()
    assert "onload" not in svg.lower()
    assert "onclick" not in svg.lower()


# ============================================================================
# rerun_package tests
# ============================================================================


class TestRerunPackage:
    def test_relink_package_rewrites_run_and_event_paths(self, tmp_path):
        from fnirs_flow.exporters.package_importer import relink_package_data

        old_root = tmp_path / "old"
        new_root = tmp_path / "new"
        relative = Path("sub-01/nirs/sub-01_task-test_run-01_nirs.snirf")
        run_path = new_root / relative
        run_path.parent.mkdir(parents=True)
        run_path.write_text("snirf", encoding="utf-8")
        events_path = run_path.with_name("sub-01_task-test_run-01_events.tsv")
        events_path.write_text("onset\n", encoding="utf-8")
        (tmp_path / "data_manifest.json").write_text(
            json.dumps(
                {
                    "local_root": str(old_root),
                    "subject_session_runs": [
                        {
                            "relative_path": relative.as_posix(),
                            "path": str(old_root / relative),
                            "events_path": str(old_root / events_path.relative_to(new_root)),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = relink_package_data(tmp_path, new_root)
        manifest = json.loads((tmp_path / "data_manifest.json").read_text())
        bindings = json.loads((tmp_path / "uri_bindings.json").read_text())

        assert result["missing_paths"] == []
        assert bindings["bindings"]["dataset"] == str(new_root.resolve())
        assert manifest["subject_session_runs"][0]["path"] == (
            "external-data://dataset/sub-01/nirs/sub-01_task-test_run-01_nirs.snirf"
        )
        assert manifest["subject_session_runs"][0]["events_path"] == (
            "external-data://dataset/sub-01/nirs/sub-01_task-test_run-01_events.tsv"
        )

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
        with pytest.raises(ValueError, match="no valid local_root or external-data binding"):
            rerun_package(tmp_path)

    def test_rerun_uses_external_data_binding_when_local_root_is_empty(self, tmp_path, monkeypatch):
        from fnirs_flow.api.uri import URIBindingStore
        from fnirs_flow.exporters.package_importer import rerun_package

        data_root = tmp_path / "data"
        data_root.mkdir()
        (tmp_path / "plan.json").write_text("{}", encoding="utf-8")
        (tmp_path / "data_manifest.json").write_text(
            json.dumps({"dataset_id": "dataset", "local_root": ""}),
            encoding="utf-8",
        )
        URIBindingStore(tmp_path).bind("dataset", data_root)

        class FakeResult:
            attempt_id = "attempt-1"
            total_runs = 1
            successful_runs = 1
            failed_runs = 0
            skipped_runs = 0
            reports = {}
            failure_ids = []

        class FakeExecutionService:
            def execute(self, request):
                assert request.data_root == str(data_root.resolve())
                return FakeResult()

        monkeypatch.setattr("fnirs_flow.execution.service.ExecutionService", FakeExecutionService)

        result = rerun_package(tmp_path)

        assert result["successful_runs"] == 1

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

    def test_trust_atom_updates_quarantine_ledger(self, tmp_path):
        from fnirs_flow.exporters.package_importer import trust_atom

        (tmp_path / "plan.json").write_text(
            json.dumps({"preprocessing_atoms": [{"atom_id": "custom-1", "operation": "custom-operation"}]}),
            encoding="utf-8",
        )
        (tmp_path / "import_metadata.json").write_text(
            json.dumps({"read_only": True, "quarantined_atoms": ["custom-1"]}),
            encoding="utf-8",
        )

        result = trust_atom(tmp_path, "custom-1")
        metadata = json.loads((tmp_path / "import_metadata.json").read_text())

        assert result["status"] == "trusted"
        assert metadata["quarantined_atoms"] == []
        assert metadata["trust_decisions"][-1]["atom_id"] == "custom-1"
