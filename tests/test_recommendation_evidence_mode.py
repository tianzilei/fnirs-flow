from fnirs_flow.recommendation import build_evidence_decision
from fnirs_flow.recommendation.contracts import (
    DecisionStatus,
    EvidenceDirection,
    EvidenceStrength,
    EvidenceSynthesis,
    MethodFit,
    SourceMode,
)


def test_evidence_mode_stays_reviewable_without_calibration() -> None:
    decision = build_evidence_decision(
        scenario="motion_correction",
        slot_id="motion_correction_slot",
        candidates=(MethodFit(candidate_id="A", status="eligible"),),
        appraisals=(),
        syntheses=(
            EvidenceSynthesis(
                claim_id="c1", strength=EvidenceStrength.MODERATE, direction=EvidenceDirection.SUPPORTS
            ),
        ),
        evidence_ready=False,
    )
    assert decision.source_mode is SourceMode.EVIDENCE_DRIVEN
    assert decision.tier is None
    assert decision.decision_status is DecisionStatus.NEEDS_REVIEW
    assert decision.required_user_confirmation


def test_evidence_mode_excludes_conflicting_synthesis() -> None:
    decision = build_evidence_decision(
        scenario="filter",
        slot_id="filter_slot",
        candidates=(MethodFit(candidate_id="A", status="eligible"),),
        appraisals=(),
        syntheses=(
            EvidenceSynthesis(
                claim_id="c1", strength=EvidenceStrength.CONFLICTING, direction=EvidenceDirection.NEUTRAL
            ),
        ),
        evidence_ready=True,
    )
    assert decision.decision_status is DecisionStatus.EXCLUDED
