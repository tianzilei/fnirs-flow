from fnirs_flow.recommendation import build_shadow_decision
from fnirs_flow.recommendation.contracts import MethodFit, SourceMode, Tier


def test_shadow_order_is_stable_and_does_not_claim_best() -> None:
    decision = build_shadow_decision(
        scenario="task_glm",
        slot_id="filter_slot",
        candidates=(
            MethodFit(candidate_id="B", status="eligible"),
            MethodFit(candidate_id="A", status="eligible"),
        ),
    )
    assert decision.source_mode is SourceMode.SHADOW
    assert decision.candidate_scope.candidate_ids == ("A", "B")
    assert decision.tier in {Tier.RECOMMENDED, Tier.ALTERNATIVE}
