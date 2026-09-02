from fnirs_flow.recommendation import appraise_evidence, build_static_decision, synthesize_evidence
from fnirs_flow.recommendation.contracts import EvidenceStrength, SourceMode


def test_appraisal_does_not_turn_missing_dimension_into_zero() -> None:
    result = appraise_evidence(
        evidence_id="E1",
        claim_type="method_definition",
        values={"directness": 1.0},
        reasons={"directness": "direct"},
        source_locator="paper#methods",
    )
    assert result.score is None
    assert result.dimensions["design_adequacy"] is None


def test_synthesis_clusters_duplicate_reports_and_detects_conflict() -> None:
    result = synthesize_evidence(
        "claim-1",
        [
            {"evidence_id": "E2", "study_id": "S1", "direction": "supports", "admitted": "true"},
            {"evidence_id": "E1", "study_id": "S1", "direction": "supports", "admitted": "true"},
            {"evidence_id": "E3", "study_id": "S2", "direction": "opposes", "admitted": "true"},
        ],
    )
    assert result.strength is EvidenceStrength.CONFLICTING
    assert len(result.independent_study_clusters) == 2


def test_synthesis_requires_explicit_admission() -> None:
    result = synthesize_evidence(
        "claim-1",
        [{"evidence_id": "E1", "study_id": "S1", "direction": "supports"}],
    )
    assert result.evidence_ids == ()
    assert result.coverage == "unknown"
    assert "not_admitted" in result.reasons


def test_static_decision_is_explicit_fallback() -> None:
    decision = build_static_decision(scenario="task_glm", slot_id="filter_slot", candidate_id="A1")
    assert decision.source_mode is SourceMode.RULE_BASED_FALLBACK
    assert decision.tier is not None
    assert decision.decision_id.startswith("dec-")
