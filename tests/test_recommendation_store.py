from pathlib import Path

import pytest

from fnirs_flow.recommendation import build_static_decision
from fnirs_flow.recommendation.diff import decision_diff, reevaluate_decision
from fnirs_flow.recommendation.store import RecommendationStore


def test_store_is_append_only(tmp_path: Path) -> None:
    store = RecommendationStore(tmp_path / "decisions.jsonl")
    decision = build_static_decision(scenario="task_glm", slot_id="filter_slot", candidate_id="A1")
    store.save(decision)
    assert store.get(decision.decision_id) == decision
    with pytest.raises(ValueError):
        store.save(decision)


def test_reevaluation_creates_new_linked_decision_and_diff() -> None:
    original = build_static_decision(scenario="task_glm", slot_id="filter_slot", candidate_id="A1")
    revised = reevaluate_decision(original)
    assert revised.decision_id != original.decision_id
    assert revised.supersedes_decision_id == original.decision_id
    diff = decision_diff(original, revised)
    assert diff["from_decision_id"] == original.decision_id
    assert any(item["field"] == "decision_id" for item in diff["changes"])
