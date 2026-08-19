"""Tests for scenario-guided flow checklists."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from fnirs_flow.flow.checklists import get_flow_checklist, list_flow_checklists, validate_checklist_coverage
from fnirs_flow.flow.serialization import load_canonical_flow
from fnirs_flow.validation.api import validate_flow

pytestmark = pytest.mark.core


def test_task_glm_checklist_available():
    checklist = get_flow_checklist("task_glm")

    assert checklist is not None
    assert checklist.label == "Task GLM"
    assert checklist.version
    assert checklist.steps[0].slot_id == "data_input"
    assert checklist.steps[1].input_requirements == ("DataManifest",)
    assert checklist.steps[-1].slot_id == "outputs"


def test_multiple_guided_scenarios_available():
    scenario_ids = {item["scenario_id"] for item in list_flow_checklists()}

    assert {
        "task_glm",
        "resting_state_connectivity",
        "group_analysis",
        "ml_classification",
    }.issubset(scenario_ids)


def test_checklist_coverage_reports_missing_required_steps(minimal_flow_dict):
    flow = load_canonical_flow(minimal_flow_dict)

    risks = validate_checklist_coverage(flow, "task_glm")

    assert any(r.code == "CHECKLIST_REQUIRED_STEP_MISSING" for r in risks)
    assert all(r.severity != "fatal" for r in risks)


def test_validate_flow_uses_metadata_checklist(minimal_flow_dict):
    flow = deepcopy(minimal_flow_dict)
    flow["metadata"]["checklist"] = {"scenario_id": "task_glm"}

    report = validate_flow(flow)

    assert report.is_valid
    assert any(r.code == "CHECKLIST_REQUIRED_STEP_MISSING" for r in report.risks)


def test_checklist_coverage_reports_existing_atom_missing_input_links():
    flow = load_canonical_flow(
        {
            "schema_version": "0.1.0",
            "flow_id": "input-risk-flow",
            "name": "Input risk flow",
            "nodes": [
                {
                    "id": "dataset",
                    "type": "dataset_discovery",
                    "atom_type": "dataset_discovery",
                    "template_id": "dataset_discovery",
                    "category": "data",
                    "position": {"x": 0, "y": 0},
                    "ports": [{"name": "manifest", "direction": "out", "schema": "DataManifest"}],
                },
                {
                    "id": "reader",
                    "type": "read_run",
                    "atom_type": "read_run",
                    "template_id": "read_run",
                    "category": "data",
                    "position": {"x": 200, "y": 0},
                    "ports": [
                        {"name": "manifest", "direction": "in", "schema": "DataManifest"},
                        {"name": "raw", "direction": "out", "schema": "RawData"},
                    ],
                },
            ],
            "edges": [],
            "metadata": {},
        }
    )

    risks = validate_checklist_coverage(flow, "task_glm")

    assert any(r.code == "CHECKLIST_STEP_INPUTS_MISSING" and "DataManifest" in r.message for r in risks)


def test_task_glm_demo_flow_satisfies_required_checklist_steps():
    flow_dict = json.loads(Path("configs/demo_task_glm_real.json").read_text(encoding="utf-8"))
    flow = load_canonical_flow(flow_dict)

    risks = validate_checklist_coverage(flow, "task_glm")

    blocking_codes = {
        "CHECKLIST_REQUIRED_STEP_MISSING",
        "CHECKLIST_STEP_INPUTS_MISSING",
    }
    assert [risk.message for risk in risks if risk.code in blocking_codes] == []
