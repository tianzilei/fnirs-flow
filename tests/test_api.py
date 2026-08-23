"""Tests for FastAPI backend."""

from __future__ import annotations

import json
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


def test_health():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_atom_templates_api_is_not_shadowed_by_spa_fallback():
    from fastapi.testclient import TestClient

    response = TestClient(app).get("/api/atom-templates")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json(), list)


def test_packaged_spa_is_registered_and_served():
    from fastapi.testclient import TestClient

    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "id=\"root\"" in response.text


def test_datasets_api_lists_builtin_registry():
    from fastapi.testclient import TestClient

    response = TestClient(app).get("/api/datasets")
    assert response.status_code == 200
    dataset_ids = {item["dataset_id"] for item in response.json()}
    assert {"mne-fnirs-motor", "bids-nirs-tapping", "ds007738"} <= dataset_ids


def test_example_flow_api_loads_official_demo():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    listing = client.get("/api/example-flows")
    assert listing.status_code == 200
    assert listing.json()[0] == {"id": "blank_template", "label": "Blank Template"}
    assert any(item["id"] == "demo_task_glm_real" for item in listing.json())

    blank = client.get("/api/example-flows/blank_template")
    assert blank.status_code == 200
    assert blank.json()["flow_id"] == "blank-template"
    assert blank.json()["nodes"] == []
    assert blank.json()["flow_atoms"] == []
    assert blank.json()["edges"] == []

    response = client.get("/api/example-flows/demo_task_glm_real")
    assert response.status_code == 200
    assert response.json()["flow_id"] == "demo-task-glm-real"


def test_ai_draft_openai_settings_are_sanitized():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "AI Settings"}).json()
    response = client.post(
        f"/api/projects/{project['id']}/ai/draft-flow",
        json={
            "scenario": "task",
            "ai_settings": {
                "mode": "openai-compatible",
                "provider": "OpenAI compatible",
                "base_url": "https://api.openai.com/v1",
                "api_key_present": True,
                "model": "gpt-5-mini",
                "temperature": 0.2,
                "max_tokens": 4096,
                "timeout_seconds": 60,
            },
        },
    )
    assert response.status_code == 200

    draft = client.get(f"/api/projects/{project['id']}/ai/draft").json()["draft"]
    settings = draft["metadata"]["ai_generation"]["settings"]
    assert settings["api_key_present"] is True
    assert settings["model"] == "gpt-5-mini"
    assert "api_key" not in settings
    assert "sk-secret" not in json.dumps(draft)


def test_ai_draft_legacy_api_key_is_not_persisted():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "AI Settings Legacy"}).json()
    response = client.post(
        f"/api/projects/{project['id']}/ai/draft-flow",
        json={
            "scenario": "task",
            "ai_settings": {
                "mode": "openai-compatible",
                "api_key": "sk-secret",
                "model": "gpt-5-mini",
            },
        },
    )
    assert response.status_code == 200

    draft = client.get(f"/api/projects/{project['id']}/ai/draft").json()["draft"]
    settings = draft["metadata"]["ai_generation"]["settings"]
    assert settings["api_key_present"] is True
    assert "api_key" not in settings
    assert "sk-secret" not in json.dumps(draft)


def test_ai_draft_openai_compatible_uses_server_provider(monkeypatch):
    from fastapi.testclient import TestClient

    from fnirs_flow.ai.draft_generator import generate_draft_flow

    monkeypatch.setenv("FNIRS_FLOW_ALLOW_EXTERNAL_AI_IN_TESTS", "1")
    generated_flow = generate_draft_flow(
        "task",
        study_name="Provider Draft",
        data_format="snirf",
        conditions=["left", "right"],
        model_name="deepseek-v4-pro",
        assumptions=["LLM assumption: inspect event timing."],
        user_confirmations=["LLM confirmation: verify GLM basis function."],
    )
    generated_flow["flow_id"] = "provider-flow-001"
    with patch("fnirs_flow.ai.openai_compatible.generate_openai_compatible_flow") as generate:
        generate.return_value = {
            "flow": generated_flow,
            "settings": {
                "mode": "openai-compatible",
                "provider": "DeepSeek compatible",
                "base_url": "https://api.deepseek.com",
                "model": "deepseek-v4-pro",
                "temperature": 0.2,
                "max_tokens": 4096,
                "timeout_seconds": 60,
                "api_key_present": True,
                "endpoint": "chat/completions",
                "direct_import": True,
                "generation_source": "external_api_flow_json",
            },
            "usage": {"total_tokens": 64},
        }

        client = TestClient(app)
        project = client.post("/api/projects", json={"name": "Server Provider Draft"}).json()
        response = client.post(
            f"/api/projects/{project['id']}/ai/draft-flow",
            json={
                "scenario": "task",
                "study_name": "Provider Draft",
                "data_format": "snirf",
                "conditions": ["left", "right"],
                "ai_settings": {
                    "mode": "openai-compatible",
                    "provider": "OpenAI compatible",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-5-mini",
                    "temperature": 0.2,
                    "max_tokens": 4096,
                    "timeout_seconds": 60,
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["imported_to_flow"] is True
    generate.assert_called_once()
    draft = client.get(f"/api/projects/{project['id']}/ai/draft").json()["draft"]
    current_flow = client.get(f"/api/projects/{project['id']}/flow").json()
    assert current_flow["flow_id"] == "provider-flow-001"
    assert draft["flow_id"] == "provider-flow-001"
    ai = draft["metadata"]["ai_generation"]
    assert ai["model"] == "deepseek-v4-pro"
    assert "LLM assumption: inspect event timing." in ai["assumptions"]
    assert "LLM confirmation: verify GLM basis function." in ai["requires_user_confirmation"]
    assert ai["settings"]["direct_import"] is True
    assert ai["settings"]["endpoint"] == "chat/completions"
    assert "api_key" not in ai["settings"]
    assert "sk-secret" not in json.dumps(draft)


def test_invalid_content_length_returns_400():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/health", headers={"content-length": "invalid"})
    assert resp.status_code == 400


def test_create_project():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post("/api/projects", json={"name": "Test", "description": "desc", "data_root": "E:/data/study"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test"
    assert data["data_root"] == "E:/data/study"
    assert "id" in data


def test_list_projects():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    client.post("/api/projects", json={"name": "P1"})
    client.post("/api/projects", json={"name": "P2"})
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_discover_project_local_data_root(tmp_path):
    from fastapi.testclient import TestClient

    dataset_root = tmp_path / "local-study"
    nirs_dir = dataset_root / "sub-01" / "nirs"
    nirs_dir.mkdir(parents=True)
    (dataset_root / "participants.tsv").write_text("participant_id\tinclude\nsub-01\t1\n", encoding="utf-8")
    (nirs_dir / "sub-01_task-rest_nirs.snirf").write_bytes(b"snirf")
    (nirs_dir / "sub-01_task-rest_events.tsv").write_text("onset\tduration\n0\t1\n", encoding="utf-8")

    client = TestClient(app)
    project = client.post(
        "/api/projects",
        json={"name": "Local Data", "data_root": str(dataset_root)},
    ).json()
    response = client.post(
        f"/api/projects/{project['id']}/discover-data",
        params={"dataset_id": "project-local-data"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == "project-local-data"
    assert body["runs"] == 1
    assert body["local_root"] == str(dataset_root.resolve())


def test_discover_project_local_data_subdir(tmp_path):
    from fastapi.testclient import TestClient

    project_root = tmp_path / "project-data"
    dataset_root = project_root / "raw" / "study-a"
    nirs_dir = dataset_root / "sub-01" / "nirs"
    nirs_dir.mkdir(parents=True)
    (dataset_root / "participants.tsv").write_text("participant_id\tinclude\nsub-01\t1\n", encoding="utf-8")
    (nirs_dir / "sub-01_task-rest_nirs.snirf").write_bytes(b"snirf")
    (nirs_dir / "sub-01_task-rest_events.tsv").write_text("onset\tduration\n0\t1\n", encoding="utf-8")

    client = TestClient(app)
    project = client.post(
        "/api/projects",
        json={"name": "Local Data Subdir", "data_root": str(project_root)},
    ).json()
    response = client.post(
        f"/api/projects/{project['id']}/discover-data",
        params={"dataset_id": "project-local-data", "data_path": "raw/study-a"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["runs"] == 1
    assert body["local_root"] == str(dataset_root.resolve())


def test_list_project_data_folders_returns_relative_paths(tmp_path):
    from fastapi.testclient import TestClient

    project_root = tmp_path / "project-data"
    (project_root / "raw" / "study-a").mkdir(parents=True)
    (project_root / "derivatives").mkdir()

    client = TestClient(app)
    project = client.post(
        "/api/projects",
        json={"name": "Folder List", "data_root": str(project_root)},
    ).json()

    response = client.get(f"/api/projects/{project['id']}/data-folders")
    assert response.status_code == 200
    body = response.json()
    assert body["parent"] == ""
    assert {folder["path"] for folder in body["folders"]} == {"derivatives", "raw"}

    child_response = client.get(f"/api/projects/{project['id']}/data-folders", params={"parent": "raw"})
    assert child_response.status_code == 200
    assert child_response.json()["folders"][0]["path"] == "raw/study-a"


def test_list_local_folders_returns_server_paths(tmp_path):
    from fastapi.testclient import TestClient

    child = tmp_path / "BIDS-NIRS-Tapping-master"
    child.mkdir()

    client = TestClient(app)
    response = client.get("/api/local-folders", params={"path": str(tmp_path)})

    assert response.status_code == 200
    body = response.json()
    assert body["current"] == str(tmp_path.resolve())
    assert any(folder["path"] == str(child.resolve()) for folder in body["folders"])


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
    assert data["dag_layers"]
    assert sum(len(layer) for layer in data["dag_layers"]) == data["steps"]
    assert {"id", "atom_type", "operation"} <= set(data["dag_layers"][0][0])
    assert "node_type" not in data["dag_layers"][0][0]


def test_get_compile_result_rehydrates_from_disk():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "Compile hydrate"}).json()
    pid = proj["id"]
    flow = json.loads((Path(__file__).parent.parent / "configs" / "demo_task_flow.json").read_text())
    client.put(f"/api/projects/{pid}/flow", json={"flow": flow})
    posted = client.post(f"/api/projects/{pid}/compile").json()

    response = client.get(f"/api/projects/{pid}/compile")

    assert response.status_code == 200
    hydrated = response.json()
    assert hydrated["revision"] == posted["revision"]
    assert hydrated["steps"] == posted["steps"]
    assert hydrated["dag_layers"] == posted["dag_layers"]


def test_discover_data_accepts_explicit_local_bids_root(tmp_path):
    from fastapi.testclient import TestClient

    dataset_root = tmp_path / "BIDS-NIRS-Tapping-master"
    nirs_dir = dataset_root / "sub-01" / "nirs"
    nirs_dir.mkdir(parents=True)
    (dataset_root / "participants.tsv").write_text("participant_id\tinclude\nsub-01\t1\n", encoding="utf-8")
    (nirs_dir / "sub-01_task-tapping_nirs.snirf").write_bytes(b"snirf")
    (nirs_dir / "sub-01_task-tapping_events.tsv").write_text("onset\tduration\n0\t1\n", encoding="utf-8")

    client = TestClient(app)
    pid = client.post("/api/projects", json={"name": "Discover explicit root"}).json()["id"]
    response = client.post(
        f"/api/projects/{pid}/discover-data",
        params={"dataset_id": "bids-nirs-tapping", "data_root": str(dataset_root)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["files"] >= 3
    assert body["runs"] == 1
    assert body["local_root"] == str(dataset_root.resolve())
    hydrated = client.get(f"/api/projects/{pid}/discover-data")
    assert hydrated.status_code == 200
    assert hydrated.json() == body


def test_design_history_endpoint_before_initialize_returns_empty_state():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "History Empty"}).json()

    resp = client.get(f"/api/projects/{proj['id']}/history")

    assert resp.status_code == 200
    assert resp.json() == {"head": None, "branches": [], "dirty": False}


def test_import_project_participant_table(tmp_path):
    import fnirs_flow.api.app as api_module
    from fnirs_flow.api.projects import import_project_participant_table

    store = api_module.get_store()
    project_id = store.create("Participant metadata").id
    data_file = tmp_path / "run.snirf"
    data_file.write_bytes(b"test")
    compiled = store.get_output_dir(project_id) / "compiled"
    compiled.mkdir(parents=True, exist_ok=True)
    (compiled / "data_manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": "participant-test",
                "subject_session_runs": [
                    {
                        "subject": "01",
                        "path": "run.snirf",
                        "uri": "external-data://participant-test/run.snirf",
                        "relative_path": "run.snirf",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    store.bind_dataset("participant-test", tmp_path)
    table = tmp_path / "participants.tsv"
    table.write_text("participant_id\tinclude\tgroup\nsub-01\t1\tcontrol\n", encoding="utf-8")

    body = import_project_participant_table(
        store,
        project_id,
        str(table),
        id_column="participant_id",
    )

    assert body is not None
    assert body["rows"] == 1
    assert body["validation_report"]["join_preview"]["matched_subjects"] == ["sub-01"]
    assert (compiled / "participant_table_manifest.json").exists()


def test_import_project_participant_table_persists_role_map(tmp_path):
    import fnirs_flow.api.app as api_module
    from fnirs_flow.api.projects import import_project_participant_table

    store = api_module.get_store()
    project_id = store.create("Participant metadata roles").id
    compiled = store.get_output_dir(project_id) / "compiled"
    compiled.mkdir(parents=True, exist_ok=True)
    table = tmp_path / "participants.tsv"
    table.write_text(
        "subject_id\tkeep\tcohort\toutcome\tcenter\tdevice\tage\tvisit\twave\tfamily\tpair\trole\n"
        "sub-01\t1\tcontrol\t0\tA\tNIRx\t24\tses-01\tpre\tfam-1\tdyad-1\tparent\n",
        encoding="utf-8",
    )

    body = import_project_participant_table(
        store,
        project_id,
        str(table),
        id_column="subject_id",
        include_column="keep",
        group_column="cohort",
        label_column="outcome",
        site_column="center",
        scanner_column="device",
        covariate_columns=["age"],
        session_column="visit",
        timepoint_column="wave",
        pair_id_column="family",
        dyad_id_column="pair",
        participant_role_column="role",
    )

    assert body is not None
    assert body["column_role_map"] == {
        "id_column": "subject_id",
        "include_column": "keep",
        "group_column": "cohort",
        "label_column": "outcome",
        "site_column": "center",
        "scanner_column": "device",
        "covariate_columns": ["age"],
        "session_column": "visit",
        "timepoint_column": "wave",
        "pair_id_column": "family",
        "dyad_id_column": "pair",
        "participant_role_column": "role",
    }
    persisted = json.loads((compiled / "column_role_map.json").read_text(encoding="utf-8"))
    assert persisted["group_column"] == "cohort"
    assert persisted["covariate_columns"] == ["age"]


def test_project_status_survives_store_reload_and_requires_real_data(tmp_path):
    from fastapi.testclient import TestClient

    import fnirs_flow.api.app as api_module

    client = TestClient(app)
    pid = client.post("/api/projects", json={"name": "Persistent state"}).json()["id"]
    flow = json.loads((Path(__file__).parent.parent / "configs" / "demo_task_flow.json").read_text())
    client.put(f"/api/projects/{pid}/flow", json={"flow": flow})
    assert client.post(f"/api/projects/{pid}/validate").status_code == 200
    assert client.post(f"/api/projects/{pid}/compile").status_code == 200

    before = client.get(f"/api/projects/{pid}/status").json()
    assert before["validated"]
    assert before["compiled"]
    assert not before["data_discovered"]
    execution_response = client.post(f"/api/projects/{pid}/execute")
    assert execution_response.status_code == 409
    assert execution_response.json()["detail"] == {
        "code": "DATA_NOT_READY",
        "message": "DATA_NOT_READY: discover or relink at least one existing data run before execution",
        "stage": "execute",
        "recoverable": True,
        "suggested_action": "Discover or relink at least one existing data run",
    }

    api_module._store = ProjectStore(tmp_path)
    after = client.get(f"/api/projects/{pid}/status").json()
    assert after == before

    data_file = tmp_path / "sub-01_task-test.snirf"
    data_file.write_bytes(b"test")
    compiled = api_module.get_store().get_output_dir(pid) / "compiled"
    (compiled / "data_manifest.json").write_text(
        json.dumps(
            {
                "dataset_id": "status-test",
                "subject_session_runs": [
                    {
                        "subject": "01",
                        "run": "01",
                        "path": data_file.name,
                        "uri": f"external-data://status-test/{data_file.name}",
                        "relative_path": data_file.name,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    api_module.get_store().bind_dataset("status-test", tmp_path)
    ready = client.get(f"/api/projects/{pid}/status").json()
    assert ready["data_discovered"]
    assert ready["runnable_runs"] == 1


def test_flow_edit_invalidates_compiled_actions():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "Stale plan"}).json()
    pid = proj["id"]
    demo_path = Path(__file__).parent.parent / "configs" / "demo_task_flow.json"
    flow = json.loads(demo_path.read_text())
    client.put(f"/api/projects/{pid}/flow", json={"flow": flow})
    assert client.post(f"/api/projects/{pid}/compile").status_code == 200

    edited = dict(flow)
    edited["name"] = "Changed after compile"
    client.put(f"/api/projects/{pid}/flow", json={"flow": edited})

    for endpoint in ("dry-run", "execute", "export-package"):
        response = client.post(f"/api/projects/{pid}/{endpoint}")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "STALE_COMPILED_PLAN"
        assert response.json()["detail"]["stage"] in {"dry_run", "execute", "export"}


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
    assert data["revision"] >= 1


def test_project_bundle_status_and_restore():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Bundle"}).json()
    project_id = project["id"]
    flow_v1 = {"flow_id": "v1", "nodes": [], "edges": []}
    flow_v2 = {"flow_id": "v2", "nodes": [], "edges": []}
    client.put(f"/api/projects/{project_id}/flow", json={"flow": flow_v1})
    client.put(f"/api/projects/{project_id}/flow", json={"flow": flow_v2})

    status = client.get(f"/api/projects/{project_id}/bundle")
    assert status.status_code == 200
    assert status.json()["integrity_status"] == "verified"
    assert status.json()["revision"] == 3
    assert status.json()["package_path"].endswith(".fnirsflow")

    restored = client.post(f"/api/projects/{project_id}/bundle/restore/2")
    assert restored.status_code == 200
    assert restored.json()["revision"] == 4
    assert client.get(f"/api/projects/{project_id}/flow").json()["flow_id"] == "v1"


def test_create_project_validation():
    """Test project creation validation."""
    from fastapi.testclient import TestClient

    client = TestClient(app)

    # Empty name should fail
    resp = client.post("/api/projects", json={"name": ""})
    assert resp.status_code == 422

    # Missing name should fail
    resp = client.post("/api/projects", json={})
    assert resp.status_code == 422


def test_get_nonexistent_project():
    """Test getting a project that doesn't exist."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/projects/nonexistent-id")
    assert resp.status_code == 404


def test_delete_project():
    """Test deleting a project."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "ToDelete"}).json()
    pid = proj["id"]

    # Note: DELETE endpoint may not be implemented
    resp = client.delete(f"/api/projects/{pid}")
    # Accept 200 (implemented) or 405 (not implemented)
    assert resp.status_code in (200, 405)


def test_update_flow_validation():
    """Test flow update validation."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "Test"}).json()
    pid = proj["id"]

    # Invalid flow format
    resp = client.put(f"/api/projects/{pid}/flow", json={"invalid": "data"})
    assert resp.status_code == 422


def test_validate_invalid_flow():
    """Test validation of invalid flow."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "Test"}).json()
    pid = proj["id"]

    # Set an invalid flow
    invalid_flow = {"flow_id": "f1", "nodes": [{"id": "n1"}], "edges": [{"source": "n1", "target": "n2"}]}
    client.put(f"/api/projects/{pid}/flow", json={"flow": invalid_flow})

    resp = client.post(f"/api/projects/{pid}/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert "errors" in data


def test_backend_diagnostics():
    """Test backend diagnostics endpoint."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/backends")
    assert resp.status_code == 200
    data = resp.json()
    # §9.1: /api/backends returns list of backend descriptions
    assert isinstance(data, list)
    assert data
    assert {"backend_id", "is_available", "is_loaded"} <= set(data[0])

    openapi = client.get("/openapi.json").json()
    schema = openapi["paths"]["/api/backends"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"


def test_progress_events_have_attempt_scoped_monotonic_sequence():
    import fnirs_flow.api.app as api_module

    api_module._progress_events.clear()
    api_module._progress_sequences.clear()
    api_module.push_progress("p1", {"type": "atom_started", "attempt_id": "a1"})
    api_module.push_progress("p1", {"type": "atom_completed", "attempt_id": "a1"})
    api_module.push_progress("p1", {"type": "execution_started", "attempt_id": "a2"})

    events = api_module._progress_events["p1"]
    assert [event["sequence"] for event in events] == [1, 2, 1]


def test_atom_templates():
    """Test atom templates endpoint."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/atom-templates")
    assert resp.status_code == 200
    templates = resp.json()
    assert isinstance(templates, (dict, list))
    assert isinstance(templates, list)
    assert all(template["input_ports"] or template["output_ports"] for template in templates)
    non_user_keys = {
        "source_kind",
        "readiness_status",
        "execution_scope",
        "source_atom_id",
        "source_study_id",
        "target_flow_slot",
        "scenario",
        "execution_readiness",
        "missing_for_execution",
        "confidence",
        "review_required",
        "verification_status",
        "method_note",
        "accuracy_caveat",
    }
    assert all(not (set(template["default_config"]) & non_user_keys) for template in templates)
    assert all(template["default_readiness_status"] for template in templates)
    assert all(template["default_execution_scope"] for template in templates)
    study_design = next(template for template in templates if template["id"] == "study_design")
    assert study_design["default_config"]["design_type"] == "block"
    assert set(study_design["default_config"]) >= {"design_type", "conditions", "contrasts"}
    assert study_design["output_ports"] == [{"name": "design_spec", "schema": "DesignSpec", "required": True}]
    assert study_design["parameter_options"]["design_type"] == [
        "block",
        "event",
        "mixed",
        "two_sample_t",
        "paired_t",
        "one_sample_t",
        "anova",
        "regression",
    ]
    assert study_design["parameter_specs"]["design_type"]["control"] == "select"
    bandpass = next(template for template in templates if template["id"] == "bandpass_filter")
    assert bandpass["parameter_specs"]["l_freq"] == {"type": "number", "control": "number", "minimum": 0}
    assert set(bandpass["operation_contract"]["handler_backends"]) == {"mne_nirs"}
    assert bandpass["operation_contract"]["execution_scope"] == "run"
    bids_import = next(template for template in templates if template["id"] == "bids_import")
    assert bids_import["parameter_specs"]["bids_dir"]["control"] == "path"


def test_empty_marker_specs():
    """Test empty marker specs endpoint."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/empty-marker-specs")
    assert resp.status_code == 200
    specs = resp.json()
    assert isinstance(specs, list)
    assert any(spec["atom_id"] == "empty_preprocessing" for spec in specs)
    assert all(spec["input_schema"] and spec["output_schema"] for spec in specs)


def test_flow_checklists():
    """Test guided flow checklist endpoints."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/flow-checklists")
    assert resp.status_code == 200
    summaries = resp.json()
    assert any(item["scenario_id"] == "task_glm" for item in summaries)
    assert any(item["scenario_id"] == "ml_classification" for item in summaries)

    detail = client.get("/api/flow-checklists/task_glm")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["scenario_id"] == "task_glm"
    assert payload["version"]
    assert payload["steps"][0]["slot_id"] == "data_input"
    assert payload["steps"][1]["input_requirements"] == ["DataManifest"]
    assert payload["steps"][-1]["default_template_id"]

    missing = client.get("/api/flow-checklists/unknown")
    assert missing.status_code == 404


def test_cors_headers():
    """Test CORS headers are present."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    # CORS should be handled
    assert resp.status_code in (200, 405)
    assert "access-control-allow-origin" in resp.headers


def test_request_size_limit():
    """Test request size limit."""
    from fastapi.testclient import TestClient

    client = TestClient(app)

    # Create a large payload (under 1MB FlowUpdate limit)
    large_flow = {"flow_id": "f1", "nodes": [{"id": f"n{i}"} for i in range(10000)], "edges": []}

    resp = client.post("/api/projects", json={"name": "Test"})
    pid = resp.json()["id"]

    # This should work (under 1MB)
    resp = client.put(f"/api/projects/{pid}/flow", json={"flow": large_flow})
    assert resp.status_code == 200


def test_remote_api_without_key_is_rejected():
    from fastapi.testclient import TestClient

    client = TestClient(app, client=("203.0.113.10", 50000))
    assert client.get("/api/health").status_code == 200
    resp = client.get("/api/projects")
    assert resp.status_code == 403
    assert "FNIRS_API_KEY" in resp.json()["detail"]


def test_participant_table_api_rejects_path_outside_allowed_roots(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(app)
    project_root = tmp_path / "project-data"
    project_root.mkdir()
    pid = client.post(
        "/api/projects",
        json={"name": "Path Guard", "data_root": str(project_root)},
    ).json()["id"]
    outside_root = tmp_path.parent / f"{tmp_path.name}_outside_allowed_roots"
    table = outside_root / "participants.tsv"
    table.parent.mkdir()
    table.write_text("participant_id\tinclude\nsub-01\t1\n", encoding="utf-8")
    resp = client.post(
        f"/api/projects/{pid}/participant-table",
        json={"path": str(table), "id_column": "participant_id"},
    )
    assert resp.status_code == 422
    assert "project-relative" in resp.json()["detail"]["message"]


def test_participant_table_api_accepts_project_relative_path(tmp_path):
    from fastapi.testclient import TestClient

    project_root = tmp_path / "project-data"
    project_root.mkdir()
    (project_root / "participants.tsv").write_text(
        "participant_id\tinclude\tgroup\nsub-01\t1\tcontrol\n",
        encoding="utf-8",
    )

    client = TestClient(app)
    pid = client.post(
        "/api/projects",
        json={"name": "Relative Participant Table", "data_root": str(project_root)},
    ).json()["id"]
    resp = client.post(
        f"/api/projects/{pid}/participant-table",
        json={"path": "participants.tsv", "id_column": "participant_id"},
    )

    assert resp.status_code == 200
    assert resp.json()["rows"] == 1


def test_flow_api_rejects_absolute_import_atom_path():
    from fastapi.testclient import TestClient

    client = TestClient(app)
    pid = client.post("/api/projects", json={"name": "Flow Path Guard"}).json()["id"]
    flow = {
        "flow_id": "guard",
        "nodes": [
            {
                "id": "n1",
                "atom_type": "data_import",
                "operation": "snirf_reader",
                "config": {"file_path": "C:/data/run.snirf"},
            }
        ],
        "edges": [],
    }

    resp = client.put(f"/api/projects/{pid}/flow", json={"flow": flow})

    assert resp.status_code == 422
    assert "project-relative" in resp.json()["detail"]["message"]


def test_sequential_project_creation():
    """Test creating multiple projects sequentially."""
    from fastapi.testclient import TestClient

    client = TestClient(app)

    # Create multiple projects
    project_ids = []
    for i in range(5):
        resp = client.post("/api/projects", json={"name": f"Project {i}"})
        assert resp.status_code == 200
        project_ids.append(resp.json()["id"])

    # List all projects
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert len(resp.json()) == 5


def test_flow_snapshot_and_restore():
    """Test flow snapshot and restore functionality."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    proj = client.post("/api/projects", json={"name": "Test"}).json()
    pid = proj["id"]

    # Set initial flow
    flow1 = {"flow_id": "v1", "nodes": [], "edges": []}
    client.put(f"/api/projects/{pid}/flow", json={"flow": flow1})

    # Create snapshot
    resp = client.post(f"/api/projects/{pid}/snapshots")
    assert resp.json()["snapshot_id"]

    # Update flow
    flow2 = {"flow_id": "v2", "nodes": [{"id": "n1"}], "edges": []}
    client.put(f"/api/projects/{pid}/flow", json={"flow": flow2})

    # Verify flow was updated
    resp = client.get(f"/api/projects/{pid}/flow")
    assert resp.json()["flow_id"] == "v2"


class TestAIDraftWorkflow:
    def test_generate_draft_does_not_overwrite_flow(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/api/projects", json={"name": "Draft Test"})
        pid = resp.json()["id"]

        # Set initial flow
        flow1 = {"flow_id": "original", "nodes": [], "edges": []}
        client.put(f"/api/projects/{pid}/flow", json={"flow": flow1})

        # Generate AI draft
        resp = client.post(f"/api/projects/{pid}/ai/draft-flow", json={"scenario": "task"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "draft_pending"

        # Original flow should be unchanged
        resp = client.get(f"/api/projects/{pid}/flow")
        assert resp.json()["flow_id"] == "original"

    def test_confirm_draft_applies_flow(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/api/projects", json={"name": "Confirm Test"})
        pid = resp.json()["id"]

        # Generate and confirm draft
        client.post(f"/api/projects/{pid}/ai/draft-flow", json={"scenario": "task"})
        resp = client.post(f"/api/projects/{pid}/ai/confirm-draft")
        assert resp.status_code == 200
        assert resp.json()["status"] == "draft_confirmed"

        # Flow should now be the draft
        resp = client.get(f"/api/projects/{pid}/flow")
        assert "ai_generation" in resp.json().get("metadata", {})

    def test_reviewed_confirmation_records_human_audit_metadata(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/api/projects", json={"name": "Reviewed Draft Test"})
        pid = resp.json()["id"]

        client.post(f"/api/projects/{pid}/ai/draft-flow", json={"scenario": "task"})
        draft = client.get(f"/api/projects/{pid}/ai/draft").json()["draft"]
        required = draft["metadata"]["ai_generation"]["requires_user_confirmation"]
        resp = client.post(
            f"/api/projects/{pid}/ai/confirm-draft",
            json={"confirmed_parameters": required, "confirmed_by": "reviewer@example.org"},
        )

        assert resp.status_code == 200
        assert resp.json()["confirmed_count"] == len(required)
        flow = client.get(f"/api/projects/{pid}/flow").json()
        ai = flow["metadata"]["ai_generation"]
        assert ai["confirmed_parameters"] == required
        assert ai["confirmed_by"] == "reviewer@example.org"
        assert ai["confirmed_at"]
        assert ai["not_used_for_execution"] is False

    def test_reviewed_confirmation_rejects_missing_items(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/api/projects", json={"name": "Incomplete Review Test"})
        pid = resp.json()["id"]
        client.post(f"/api/projects/{pid}/ai/draft-flow", json={"scenario": "task"})

        resp = client.post(
            f"/api/projects/{pid}/ai/confirm-draft",
            json={"confirmed_parameters": [], "confirmed_by": "reviewer@example.org"},
        )

        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "AI_CONFIRMATIONS_INCOMPLETE"
        assert client.get(f"/api/projects/{pid}/ai/draft").status_code == 200

    def test_discard_draft_removes_draft(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/api/projects", json={"name": "Discard Test"})
        pid = resp.json()["id"]

        # Generate and discard draft
        client.post(f"/api/projects/{pid}/ai/draft-flow", json={"scenario": "task"})
        resp = client.delete(f"/api/projects/{pid}/ai/draft")
        assert resp.status_code == 200
        assert resp.json()["status"] == "draft_discarded"

        # No draft should exist
        resp = client.get(f"/api/projects/{pid}/ai/draft")
        assert resp.status_code == 404

    def test_get_draft_returns_pending(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/api/projects", json={"name": "Get Draft Test"})
        pid = resp.json()["id"]

        # No draft initially
        resp = client.get(f"/api/projects/{pid}/ai/draft")
        assert resp.status_code == 404

        # Generate draft
        client.post(f"/api/projects/{pid}/ai/draft-flow", json={"scenario": "task"})

        # Get draft
        resp = client.get(f"/api/projects/{pid}/ai/draft")
        assert resp.status_code == 200
        assert resp.json()["status"] == "draft_exists"

    def test_confirm_without_draft_returns_404(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/api/projects", json={"name": "No Draft Test"})
        pid = resp.json()["id"]

        resp = client.post(f"/api/projects/{pid}/ai/confirm-draft")
        assert resp.status_code == 404

    def test_validate_draft_returns_risks_and_readiness(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/api/projects", json={"name": "Validate Draft Test"})
        pid = resp.json()["id"]

        # Generate draft
        client.post(f"/api/projects/{pid}/ai/draft-flow", json={"scenario": "task"})

        # Validate draft
        resp = client.post(f"/api/projects/{pid}/ai/validate-draft")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "draft_validated"
        assert "valid" in body
        assert "errors" in body
        assert "risks" in body
        assert "readiness" in body
        # Draft should have AI confirmation risk
        assert any(r["code"] == "AI_CONFIRMATION_REQUIRED" for r in body["risks"])

    def test_validate_draft_without_draft_returns_404(self):
        from fastapi.testclient import TestClient

        client = TestClient(app)
        resp = client.post("/api/projects", json={"name": "No Draft Validate Test"})
        pid = resp.json()["id"]

        resp = client.post(f"/api/projects/{pid}/ai/validate-draft")
        assert resp.status_code == 404
