"""Tests for scenario definitions, registry, and validation."""

from __future__ import annotations

from fnirs_flow.flow.models import FlowGraph, FlowNode, NodeCategory
from fnirs_flow.registry.scenarios import (
    MACHINE_LEARNING_SCENARIO,
    MULTI_SITE_SCENARIO,
    RESTING_STATE_SCENARIO,
    SCENARIO_NODE_TEMPLATES,
    TASK_SCENARIO,
    ScenarioRegistry,
)
from fnirs_flow.registry.validators import validate_scenario_constraints


class TestScenarioRegistry:
    def test_builtin_scenarios(self):
        registry = ScenarioRegistry()
        assert len(registry.list_ids()) == 6

    def test_get_scenario(self):
        registry = ScenarioRegistry()
        task = registry.get("task")
        assert task is not None
        assert task.name == "Task-Based fNIRS"

    def test_detect_scenario_task(self):
        registry = ScenarioRegistry()
        config = {"uses_resting_state": False, "is_real_world": False}
        assert registry.detect_scenario(config) == "task"

    def test_detect_scenario_resting(self):
        registry = ScenarioRegistry()
        config = {"uses_resting_state": True}
        assert registry.detect_scenario(config) == "resting_state"

    def test_detect_scenario_ml(self):
        registry = ScenarioRegistry()
        config = {"uses_machine_learning": True}
        assert registry.detect_scenario(config) == "machine_learning"

    def test_detect_scenario_multi_site(self):
        registry = ScenarioRegistry()
        # Multi-site scenario should be detectable
        assert registry.get("multi_site") is not None


class TestScenarioDefinitions:
    def test_task_required_nodes(self):
        assert "dataset_discovery" in TASK_SCENARIO.required_node_types
        assert "first_level_glm" in TASK_SCENARIO.required_node_types

    def test_resting_state_required_nodes(self):
        assert "connectivity_analysis" in RESTING_STATE_SCENARIO.required_node_types

    def test_ml_constraints(self):
        assert "subject_wise" in MACHINE_LEARNING_SCENARIO.constraints["split_strategies"]
        assert "random_trial_split" in MACHINE_LEARNING_SCENARIO.constraints["prohibited"]

    def test_multi_site_required_nodes(self):
        assert "site_metadata_extraction" in MULTI_SITE_SCENARIO.required_node_types
        assert "site_level_qc" in MULTI_SITE_SCENARIO.required_node_types
        assert "multi_site_harmonization" in MULTI_SITE_SCENARIO.required_node_types

    def test_multi_site_constraints(self):
        assert "combat" in MULTI_SITE_SCENARIO.constraints["harmonization_methods"]
        assert MULTI_SITE_SCENARIO.constraints["min_sites"] == 2


class TestScenarioValidation:
    def _make_flow(self, node_types: list[str]) -> FlowGraph:
        atoms = [
            FlowNode(
                id=f"n{i}",
                atom_type=nt,
                category=NodeCategory.ANALYSIS,
            )
            for i, nt in enumerate(node_types)
        ]
        return FlowGraph(flow_atoms=atoms)

    def test_task_missing_contrast(self):
        flow = self._make_flow(["dataset_discovery", "study_design", "first_level_glm"])
        risks = validate_scenario_constraints(flow, "task")
        assert any("contrast" in r.message.lower() for r in risks)

    def test_task_complete(self):
        flow = self._make_flow(
            [
                "dataset_discovery",
                "study_design",
                "event_extraction",
                "optical_density",
                "motion_correction",
                "filtering",
                "beer_lambert_law",
                "design_matrix",
                "first_level_glm",
                "contrast",
            ]
        )
        risks = validate_scenario_constraints(flow, "task")
        # Should have no high/fatal risks
        serious = [r for r in risks if r.severity in ("high", "fatal")]
        assert len(serious) == 0

    def test_resting_missing_connectivity(self):
        flow = self._make_flow(["dataset_discovery", "optical_density"])
        risks = validate_scenario_constraints(flow, "resting_state")
        assert any("connectivity" in r.message.lower() for r in risks)

    def test_ml_prohibited_split(self):
        flow = self._make_flow(
            [
                "dataset_discovery",
                "optical_density",
                "feature_extraction",
                "ml_model",
            ]
        )
        # Set prohibited split strategy
        for node in flow.flow_atoms:
            if node.atom_type == "ml_model":
                node.config = {"split_strategy": "random_trial"}

        risks = validate_scenario_constraints(flow, "machine_learning")
        assert any("leakage" in r.message.lower() or "prohibited" in r.message.lower() for r in risks)
        assert any(r.severity == "fatal" for r in risks)

    def test_unknown_scenario(self):
        flow = self._make_flow(["dataset_discovery"])
        risks = validate_scenario_constraints(flow, "nonexistent")
        assert any("unknown" in r.message.lower() for r in risks)


class TestScenarioNodeTemplates:
    def test_resting_state_templates(self):
        templates = SCENARIO_NODE_TEMPLATES.get("resting_state", [])
        assert len(templates) > 0
        assert any(t.template_id == "connectivity_analysis" for t in templates)

    def test_ml_templates(self):
        templates = SCENARIO_NODE_TEMPLATES.get("machine_learning", [])
        assert len(templates) == 2
        assert any(t.template_id == "feature_extraction" for t in templates)
        assert any(t.template_id == "ml_model" for t in templates)

    def test_multi_site_templates(self):
        templates = SCENARIO_NODE_TEMPLATES.get("multi_site", [])
        assert len(templates) == 4
        assert any(t.template_id == "site_metadata_extraction" for t in templates)
        assert any(t.template_id == "site_level_qc" for t in templates)
        assert any(t.template_id == "combat_harmonization" for t in templates)
        assert any(t.template_id == "batch_effect_diagnostics" for t in templates)
