"""Tests for MethodAtom order and empty-link risk policy."""

from __future__ import annotations

from copy import deepcopy

import pytest

from fnirs_flow.flow.empty_markers import (
    EMPTY_MARKER_SPECS,
    normalize_empty_markers,
    remove_unconnected_auto_empty_markers,
)
from fnirs_flow.validation.api import validate_flow

pytestmark = pytest.mark.core


def test_order_violation_is_fatal_by_default(minimal_flow_dict):
    flow = deepcopy(minimal_flow_dict)
    flow["nodes"][0]["category"] = "data"
    flow["nodes"][0]["ports"] = [{"name": "input", "direction": "in", "schema": "X", "required": True}]
    flow["nodes"][1]["category"] = "analysis"
    flow["nodes"][1]["ports"] = [{"name": "output", "direction": "out", "schema": "X", "required": True}]
    flow["edges"] = [
        {
            "id": "edge-backwards",
            "source": "node-2",
            "target": "node-1",
            "source_handle": "output",
            "target_handle": "input",
        }
    ]

    report = validate_flow(flow)

    assert report.has_fatal_risks
    assert any(r.code == "ATOM_ORDER_VIOLATION" and r.severity == "fatal" for r in report.risks)


def test_order_violation_can_be_accepted_as_risk(minimal_flow_dict):
    flow = deepcopy(minimal_flow_dict)
    flow["metadata"]["order_policy"] = {"allow_order_violations": True}
    flow["nodes"][0]["category"] = "data"
    flow["nodes"][0]["ports"] = [{"name": "input", "direction": "in", "schema": "X", "required": True}]
    flow["nodes"][1]["category"] = "analysis"
    flow["nodes"][1]["ports"] = [{"name": "output", "direction": "out", "schema": "X", "required": True}]
    flow["edges"] = [
        {
            "id": "edge-backwards",
            "source": "node-2",
            "target": "node-1",
            "source_handle": "output",
            "target_handle": "input",
        }
    ]

    report = validate_flow(flow)

    order_risks = [r for r in report.risks if r.code == "ATOM_ORDER_VIOLATION"]
    assert order_risks
    assert all(r.severity != "fatal" for r in order_risks)


def test_empty_multi_atom_flow_is_fatal_by_default(minimal_flow_dict):
    flow = deepcopy(minimal_flow_dict)
    flow["edges"] = []
    for node in flow["nodes"]:
        node["ports"] = []

    report = validate_flow(flow)

    assert report.has_fatal_risks
    assert any(r.code == "ATOM_EMPTY_FLOW" and r.severity == "fatal" for r in report.risks)


def test_empty_multi_atom_flow_can_be_accepted_as_risk(minimal_flow_dict):
    flow = deepcopy(minimal_flow_dict)
    flow["edges"] = []
    flow["metadata"]["order_policy"] = {"allow_empty_edges": True}
    for node in flow["nodes"]:
        node["ports"] = []

    report = validate_flow(flow)

    empty_risks = [r for r in report.risks if r.code == "ATOM_EMPTY_MARKERS_ACTIVE"]
    assert empty_risks
    assert all(r.severity != "fatal" for r in empty_risks)


def test_empty_marker_normalization_adds_schema_preserving_atoms(minimal_flow_dict):
    flow = deepcopy(minimal_flow_dict)
    flow["metadata"]["order_policy"] = {"allow_empty_edges": True}

    normalized = normalize_empty_markers(flow)
    atoms = normalized["flow_atoms"]
    by_id = {atom["id"]: atom for atom in atoms}

    for spec in EMPTY_MARKER_SPECS:
        atom = by_id[spec.atom_id]
        assert atom["operation"] == "empty_marker"
        assert atom["category"] == spec.category
        assert atom["ports"][0]["schema"] == spec.input_schema
        assert atom["ports"][1]["schema"] == spec.output_schema


def test_remove_unconnected_auto_empty_markers_preserves_connected(minimal_flow_dict):
    flow = deepcopy(minimal_flow_dict)
    flow["metadata"]["order_policy"] = {"allow_empty_edges": True}
    normalized = normalize_empty_markers(flow)
    normalized["edges"].append(
        {
            "id": "edge-to-empty",
            "source": "node-2",
            "target": "empty_preprocessing",
            "source_handle": "output",
            "target_handle": "marker_in",
        }
    )

    cleaned = remove_unconnected_auto_empty_markers(normalized)
    ids = {atom["id"] for atom in cleaned["flow_atoms"]}

    assert "empty_preprocessing" in ids
    assert "empty_design" not in ids
