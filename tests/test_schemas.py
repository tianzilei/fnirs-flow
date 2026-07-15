"""Tests for flow schemas module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fnirs_flow.flow.schemas import (
    flow_to_dict,
    load_flow_from_dict,
    load_flow_from_file,
    validate_flow_dict,
)


class TestValidateFlowDict:
    """Tests for validate_flow_dict function."""

    def test_valid_flow_passes(self) -> None:
        """Test that a valid flow dict passes validation."""
        flow = {
            "schema_version": "0.2.0",
            "flow_id": "test_flow",
            "nodes": [],
            "edges": [],
        }
        errors = validate_flow_dict(flow)
        assert errors == []

    def test_missing_schema_version(self) -> None:
        """Test that missing schema_version is caught."""
        flow = {
            "flow_id": "test_flow",
            "nodes": [],
            "edges": [],
        }
        errors = validate_flow_dict(flow)
        assert any("schema_version" in e for e in errors)

    def test_missing_flow_id(self) -> None:
        """Test that missing flow_id is caught."""
        flow = {
            "schema_version": "0.2.0",
            "nodes": [],
            "edges": [],
        }
        errors = validate_flow_dict(flow)
        assert any("flow_id" in e for e in errors)

    def test_missing_edges(self) -> None:
        """Test that missing edges is caught."""
        flow = {
            "schema_version": "0.2.0",
            "flow_id": "test_flow",
            "nodes": [],
        }
        errors = validate_flow_dict(flow)
        assert any("edges" in e for e in errors)

    def test_missing_nodes_and_flow_atoms(self) -> None:
        """Test that missing nodes/flow_atoms is caught."""
        flow = {
            "schema_version": "0.2.0",
            "flow_id": "test_flow",
            "edges": [],
        }
        errors = validate_flow_dict(flow)
        assert any("nodes" in e or "flow_atoms" in e for e in errors)

    def test_invalid_nodes_type(self) -> None:
        """Test that non-list nodes is caught."""
        flow = {
            "schema_version": "0.2.0",
            "flow_id": "test_flow",
            "nodes": "not_a_list",
            "edges": [],
        }
        errors = validate_flow_dict(flow)
        assert any("nodes" in e and "array" in e for e in errors)

    def test_invalid_edges_type(self) -> None:
        """Test that non-list edges is caught."""
        flow = {
            "schema_version": "0.2.0",
            "flow_id": "test_flow",
            "nodes": [],
            "edges": "not_a_list",
        }
        errors = validate_flow_dict(flow)
        assert any("edges" in e and "array" in e for e in errors)

    def test_non_dict_input(self) -> None:
        """Test that non-dict input is caught."""
        errors = validate_flow_dict("not a dict")  # type: ignore[arg-type]
        assert len(errors) > 0
        assert any("JSON object" in e for e in errors)

    def test_flow_atoms_instead_of_nodes(self) -> None:
        """Test that flow_atoms is accepted instead of nodes."""
        flow = {
            "schema_version": "0.2.0",
            "flow_id": "test_flow",
            "flow_atoms": [],
            "edges": [],
        }
        errors = validate_flow_dict(flow)
        assert errors == []


class TestLoadFlowFromDict:
    """Tests for load_flow_from_dict function."""

    def test_valid_flow_loads(self) -> None:
        """Test that a valid flow dict loads successfully."""
        flow = {
            "schema_version": "0.2.0",
            "flow_id": "test_flow",
            "nodes": [],
            "edges": [],
        }
        result = load_flow_from_dict(flow)
        assert result.flow_id == "test_flow"

    def test_invalid_flow_raises(self) -> None:
        """Test that an invalid flow dict raises ValidationError."""
        flow = {
            "schema_version": "0.2.0",
            "flow_id": "test_flow",
            "nodes": "not_a_list",  # Invalid: should be a list
            "edges": [],
        }
        with pytest.raises(Exception):
            load_flow_from_dict(flow)


class TestLoadFlowFromFile:
    """Tests for load_flow_from_file function."""

    def test_load_valid_file(self, tmp_path: Path) -> None:
        """Test loading a valid flow from file."""
        flow = {
            "schema_version": "0.2.0",
            "flow_id": "test_flow",
            "nodes": [],
            "edges": [],
        }
        flow_file = tmp_path / "test_flow.json"
        flow_file.write_text(json.dumps(flow), encoding="utf-8")

        result = load_flow_from_file(flow_file)
        assert result.flow_id == "test_flow"

    def test_load_nonexistent_file(self) -> None:
        """Test that loading a nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_flow_from_file("/nonexistent/path.json")


class TestFlowToDict:
    """Tests for flow_to_dict function."""

    def test_serialization(self) -> None:
        """Test that a FlowGraph serializes to dict correctly."""
        flow = {
            "schema_version": "0.2.0",
            "flow_id": "test_flow",
            "nodes": [],
            "edges": [],
        }
        graph = load_flow_from_dict(flow)
        result = flow_to_dict(graph)

        assert isinstance(result, dict)
        assert result["flow_id"] == "test_flow"
