"""Tests for the AI draft flow generator."""

from __future__ import annotations

import pytest

from fnirs_flow.ai.draft_generator import generate_draft_flow
from fnirs_flow.validation.api import validate_flow


class TestDraftGenerator:
    def test_unknown_scenario_raises(self):
        with pytest.raises(ValueError, match="Unknown scenario: nonexistent"):
            generate_draft_flow("nonexistent")

    def test_task_scenario_generates_nodes(self):
        flow = generate_draft_flow("task")
        assert len(flow["nodes"]) > 0
        for node in flow["nodes"]:
            assert "id" in node
            assert "type" in node
            assert "label" in node

    def test_required_atoms_connect_only_compatible_ports(self):
        flow = generate_draft_flow("task")
        nodes = {node["id"]: node for node in flow["nodes"]}
        assert flow["edges"]
        for edge in flow["edges"]:
            source_ports = {
                port["name"]: port["schema"]
                for port in nodes[edge["source"]]["ports"]
                if port["direction"] == "out"
            }
            target_ports = {
                port["name"]: port["schema"]
                for port in nodes[edge["target"]]["ports"]
                if port["direction"] == "in"
            }
            assert source_ports[edge["source_handle"]] == target_ports[edge["target_handle"]]

    def test_task_draft_has_no_schema_or_graph_errors(self):
        report = validate_flow(generate_draft_flow("task"))
        assert report.errors == []

    def test_high_impact_atoms_marked_for_review(self):
        flow = generate_draft_flow("task")
        high_impact = {"motion_correction", "filtering", "design_matrix", "first_level_glm", "contrast"}
        for node in flow["nodes"]:
            if node["type"] in high_impact:
                assert node.get("requires_review")
                assert node["readiness_status"] == "needs_attention"

    def test_assumptions_include_format_and_conditions(self):
        flow = generate_draft_flow("task", data_format="nirx", conditions=["left", "right"])
        assumptions = flow["metadata"]["ai_generation"]["assumptions"]
        assert any("nirx" in a for a in assumptions)
        assert any("left" in a and "right" in a for a in assumptions)

    def test_confirmations_for_high_impact_atoms(self):
        flow = generate_draft_flow("task")
        confirmations = flow["metadata"]["ai_generation"]["requires_user_confirmation"]
        assert len(confirmations) > 0
        assert any("motion_correction" in c for c in confirmations)
        assert any("filtering" in c for c in confirmations)

    def test_metadata_ai_generation_block(self):
        flow = generate_draft_flow("task", model_name="test-model")
        ai = flow["metadata"]["ai_generation"]
        assert ai["generated_by"] == "generative_ai"
        assert ai["model"] == "test-model"
        assert ai["created_at"]  # non-empty
        assert ai["not_used_for_execution"]

    def test_flow_id_prefix(self):
        flow = generate_draft_flow("task")
        assert flow["flow_id"].startswith("draft-task-")

    def test_not_used_for_execution_always_true(self):
        flow = generate_draft_flow("task")
        assert flow["metadata"]["ai_generation"]["not_used_for_execution"]
        flow2 = generate_draft_flow("resting_state")
        assert flow2["metadata"]["ai_generation"]["not_used_for_execution"]

    def test_user_confirmations_merged(self):
        flow = generate_draft_flow("task", user_confirmations=["custom check"])
        confirmations = flow["metadata"]["ai_generation"]["requires_user_confirmation"]
        assert "custom check" in confirmations

    def test_custom_assumptions_merged(self):
        flow = generate_draft_flow("task", assumptions=["Special protocol"])
        assumptions = flow["metadata"]["ai_generation"]["assumptions"]
        assert "Special protocol" in assumptions

    def test_study_name_in_flow(self):
        flow = generate_draft_flow("task", study_name="My Study")
        assert flow["name"] == "My Study"
        assert "ai-generated" in flow["metadata"]["tags"]
