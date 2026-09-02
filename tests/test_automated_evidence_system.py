from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from fnirs_flow.evidence import (
    AutomatedEvidenceWorkspace,
    PipelineState,
    ReleaseMetrics,
    evaluate_automated_gates,
    validate_transition,
)
from fnirs_flow.evidence.consensus import AdmissionOutcome, decide_consensus
from fnirs_flow.evidence.deterministic_verifier import verify_proposal
from fnirs_flow.evidence.extraction_proposals import (
    ClaimDirection,
    ExtractionProposal,
    ExtractorLane,
    NumericValue,
    TargetType,
)
from fnirs_flow.evidence.routing import RoutedObjectType, route_proposal
from fnirs_flow.evidence.segment_ledger import SegmentKind, SegmentLocator, make_segment, replay_locator
from fnirs_flow.evidence.semantic_verifier import (
    EvidenceSpan,
    SemanticVerdict,
    SemanticVerificationResult,
)
from fnirs_flow.evidence.synthesis import AdmittedEvidence, SynthesisStatus, synthesize
from fnirs_flow.recommendation import build_automated_evidence_decision
from fnirs_flow.recommendation.contracts import (
    ExecutionFeasibility,
    ExecutionStatus,
    MethodFit,
    SourceMode,
)

TEXT = "TDDR reduced artifacts at 0.5 Hz."


def _segment():
    locator = SegmentLocator(document_version="v1", xpath="/article/p[1]", char_start=0, char_end=len(TEXT))
    return make_segment(
        source_version_id="sv1", kind=SegmentKind.PARAGRAPH, raw_text=TEXT,
        locator=locator, parser_version="parser-1",
    )


def _proposal(lane: ExtractorLane, family: str, proposal_id: str) -> ExtractionProposal:
    segment = _segment()
    return ExtractionProposal(
        proposal_id=proposal_id, source_version_id="sv1", segment_id=segment.segment_id,
        quote=TEXT, locator=segment.locator, claim_type="parameter_candidate", subject="TDDR",
        predicate="cutoff", object="0.5 Hz", extractor_run_id=f"run-{lane.value}",
        extractor_lane=lane, model_family=family, model_version="fixed-1", prompt_sha256="a" * 64,
        target_type=TargetType.PARAMETER_CANDIDATE, target_id="motion_correction_slot",
        direction=ClaimDirection.SUPPORTS, study_id="study-1",
        numeric=NumericValue(raw="0.5 Hz", value=0.5, unit="Hz", context="motion correction"),
    )


def test_locator_replay_and_state_machine_reject_skips() -> None:
    segment = _segment()
    assert replay_locator(TEXT, segment) == TEXT
    validate_transition(PipelineState.DISCOVERED, PipelineState.ACQUIRED)
    with pytest.raises(ValueError, match="invalid_evidence_state_transition"):
        validate_transition(PipelineState.DISCOVERED, PipelineState.ADMITTED)


def test_proposal_schema_forbids_unknown_model_output() -> None:
    payload = _proposal(ExtractorLane.A, "family-a", "p-a").model_dump(mode="json")
    payload["model_guess"] = "not in source"
    with pytest.raises(ValidationError):
        ExtractionProposal.model_validate(payload)


def test_a_b_deterministic_c_consensus_admits_only_exact_agreement() -> None:
    segment = _segment()
    a = _proposal(ExtractorLane.A, "family-a", "p-a")
    b = _proposal(ExtractorLane.B, "family-b", "p-b")
    da = verify_proposal(
        a, segment, TEXT, verification_run_id="dv-a", verifier_version="1",
        valid_target_ids={"motion_correction_slot"},
    )
    db = verify_proposal(
        b, segment, TEXT, verification_run_id="dv-b", verifier_version="1",
        valid_target_ids={"motion_correction_slot"},
    )
    semantic = SemanticVerificationResult(
        verification_run_id="sv-c", proposal_id="p-a", verifier_model_family="family-c",
        verifier_model_version="fixed-1", prompt_sha256="b" * 64, verdict=SemanticVerdict.ENTAILED,
        evidence_spans=(EvidenceSpan(segment_id=segment.segment_id, char_start=0, char_end=len(TEXT)),),
        checks={"quote_entails_normalized_claim": SemanticVerdict.ENTAILED},
    )
    decision = decide_consensus(
        a, b, da, db, semantic, admission_run_id="admit-1", segment_length=len(TEXT),
    )
    assert decision.outcome is AdmissionOutcome.ADMITTED
    changed = b.model_copy(update={"direction": ClaimDirection.INSUFFICIENT})
    quarantined = decide_consensus(
        a, changed, da, db, semantic, admission_run_id="admit-2", segment_length=len(TEXT),
    )
    assert quarantined.outcome is AdmissionOutcome.QUARANTINED
    assert "extractor_critical_field_disagreement" in quarantined.reason_codes


def test_parameter_routing_never_promotes_default() -> None:
    routed = route_proposal(_proposal(ExtractorLane.A, "family-a", "p-a"), claim_id="c1", candidate_id="pc1")
    assert routed.object_type is RoutedObjectType.PARAMETER_CANDIDATE
    assert routed.verification_required
    assert not routed.promoted_to_runtime_default
    assert routed.payload["unit"] == "Hz"


def test_synthesis_is_order_independent_and_count_does_not_bypass_quality() -> None:
    rows = (
        AdmittedEvidence(claim_id="c1", evidence_id="e1", component_id="s1", direction="supports"),
        AdmittedEvidence(claim_id="c2", evidence_id="e2", component_id="s2", direction="supports"),
        AdmittedEvidence(claim_id="c3", evidence_id="e3", component_id="s3", direction="supports"),
    )
    first = synthesize(synthesis_id="syn", snapshot_id="snap", policy_version="2", evidence=rows)
    second = synthesize(synthesis_id="syn", snapshot_id="snap", policy_version="2", evidence=tuple(reversed(rows)))
    assert first == second
    assert first.status is SynthesisStatus.INSUFFICIENT
    assert first.score is None


def test_release_gate_requires_domain_benchmark_and_falls_back_to_shadow() -> None:
    metrics = ReleaseMetrics(
        locator_exact_match_rate=1, schema_and_reference_integrity=1,
        numeric_round_trip_accuracy=0.999, unit_dimension_accuracy=1,
        hard_exclusion_false_accepts=0, adversarial_false_best=0,
        unsupported_claim_admission_rate=0.001, critical_field_cross_model_agreement=0.99,
        explanation_and_lineage_completeness=1, repeatability_failures=0,
        corpus_processed_coverage=0.5, claim_extraction_coverage=0.4, admission_coverage=0.2,
    )
    gated = evaluate_automated_gates(
        metrics, slot_id="motion_correction_slot", independent_fnirs_benchmark=False,
    )
    assert not gated.passed
    assert gated.source_mode == "shadow"
    decision = build_automated_evidence_decision(
        scenario="motion", slot_id="motion_correction_slot",
        candidates=(MethodFit(candidate_id="TDDR", status="eligible"),),
        appraisals=(), syntheses=(), snapshot_id="snap", release_gate_passed=True,
        independent_fnirs_benchmark=False,
    )
    assert decision.source_mode is SourceMode.SHADOW


def test_automated_decision_uses_selected_candidate_execution() -> None:
    decision = build_automated_evidence_decision(
        scenario="motion", slot_id="motion_correction_slot",
        candidates=(MethodFit(candidate_id="A", status="eligible"),
                    MethodFit(candidate_id="B", status="eligible")),
        appraisals=(), syntheses=(), snapshot_id="snap", release_gate_passed=True,
        independent_fnirs_benchmark=True,
        execution=(ExecutionFeasibility(candidate_id="B", status=ExecutionStatus.READY),
                   ExecutionFeasibility(candidate_id="A", status=ExecutionStatus.BLOCKED)),
    )
    assert decision.source_mode is SourceMode.SHADOW
    assert decision.execution_status is ExecutionStatus.BLOCKED


def test_workspace_idempotency_and_optimistic_concurrency(tmp_path: Path) -> None:
    workspace = AutomatedEvidenceWorkspace(tmp_path / "workspace.sqlite3")
    provenance = {"actor": "extractor-a", "at": datetime.now(timezone.utc).isoformat()}
    first = workspace.start_run(
        run_id="run-1", stage="extract", idempotency_key="same-key", payload={}, provenance=provenance,
    )
    replay = workspace.start_run(
        run_id="run-2", stage="extract", idempotency_key="same-key", payload={}, provenance=provenance,
    )
    assert replay["run_id"] == first["run_id"] == "run-1"
    updated = workspace.update_run("run-1", expected_version=1, status="running")
    assert updated["version"] == 2
    with pytest.raises(ValueError, match="run_version_conflict"):
        workspace.update_run("run-1", expected_version=1, status="complete")


def test_workspace_idempotency_is_stage_scoped_and_rejects_payload_change(tmp_path: Path) -> None:
    workspace = AutomatedEvidenceWorkspace(tmp_path / "workspace.sqlite3")
    provenance = {"actor": "test"}
    workspace.start_run(
        run_id="run-harvest", stage="harvest", idempotency_key="same", payload={"value": 1},
        provenance=provenance,
    )
    extracted = workspace.start_run(
        run_id="run-extract", stage="extract", idempotency_key="same", payload={"value": 1},
        provenance=provenance,
    )
    assert extracted["run_id"] == "run-extract"
    with pytest.raises(ValueError, match="idempotency_key_reused_with_different_request"):
        workspace.start_run(
            run_id="ignored", stage="extract", idempotency_key="same", payload={"value": 2},
            provenance=provenance,
        )


def test_workspace_state_events_are_append_only_and_reject_skips(tmp_path: Path) -> None:
    workspace = AutomatedEvidenceWorkspace(tmp_path / "workspace.sqlite3")
    workspace.record_transition(
        object_id="source-1", old_state="discovered", new_state="acquired", reason_code="source_fetched",
        input_sha256="a" * 64, output_sha256="b" * 64, execution_version="harvester-1",
    )
    assert workspace.lineage("source-1")[0]["reason_code"] == "source_fetched"
    with pytest.raises(ValueError, match="invalid_evidence_state_transition"):
        workspace.record_transition(
            object_id="source-1", old_state="acquired", new_state="admitted", reason_code="skip",
            input_sha256="b" * 64, output_sha256="c" * 64, execution_version="bad",
        )
    with pytest.raises(ValueError, match="state_event_disconnected"):
        workspace.record_transition(
            object_id="source-1", old_state="discovered", new_state="metadata_only",
            reason_code="disconnected", input_sha256="b" * 64, output_sha256="c" * 64,
            execution_version="bad",
        )
