from fnirs_flow.recommendation import (
    ExecutionFeasibility,
    MethodFit,
    build_evidence_decision,
)
from fnirs_flow.recommendation.contracts import ExecutionStatus


def test_unverified_evidence_does_not_block_analysis_execution() -> None:
    decision = build_evidence_decision(
        scenario="task_glm",
        slot_id="task_glm_slot",
        candidates=(MethodFit(candidate_id="glm", status="eligible"),),
        appraisals=(),
        syntheses=(),
        evidence_ready=False,
        execution=(ExecutionFeasibility(candidate_id="glm", status=ExecutionStatus.READY),),
    )
    assert decision.decision_status.value == "needs_review"
    assert decision.execution_status is ExecutionStatus.READY
    assert decision.tier is None
