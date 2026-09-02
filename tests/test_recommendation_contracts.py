from datetime import datetime, timezone

import pytest

from fnirs_flow.recommendation import (
    CandidateScope,
    EvidenceAppraisal,
    ExecutionFeasibility,
    RecommendationContext,
    RecommendationDecision,
)
from fnirs_flow.recommendation.contracts import (
    DecisionStatus,
    ExecutionStatus,
    SourceMode,
    Tier,
)


def test_contracts_keep_missing_scores_null_and_are_immutable() -> None:
    appraisal = EvidenceAppraisal(
        evidence_id="E1",
        claim_type="method_definition",
        profile_version="1.0.0",
        dimensions={"directness": None},
        dimension_reasons={"directness": "source not located"},
    )
    decision = RecommendationDecision(
        decision_id="D1",
        rules_version="1.3.0",
        context=RecommendationContext(scenario="task_glm", fields={"short_channel": "unknown"}),
        candidate_scope=CandidateScope(slot_id="filter_slot", candidate_ids=("A1",)),
        appraisals=(appraisal,),
        tier=None,
        decision_status=DecisionStatus.NEEDS_REVIEW,
        execution_status=ExecutionStatus.BLOCKED,
        source_mode=SourceMode.RULE_BASED_FALLBACK,
        generated_at=datetime.now(timezone.utc),
    )
    assert decision.appraisals[0].score is None
    assert decision.tier is None
    with pytest.raises(Exception):
        decision.tier = Tier.BEST  # type: ignore[misc]


def test_execution_feasibility_is_orthogonal_to_method_fit() -> None:
    result = ExecutionFeasibility(candidate_id="A1", status=ExecutionStatus.UNAVAILABLE, backend_id="mne")
    assert result.status is ExecutionStatus.UNAVAILABLE
