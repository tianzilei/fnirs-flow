from fnirs_flow.recommendation.evidence_count import CountEvidence, rank_by_evidence_count


def _e(eid, candidate, study, direction="supports", level="verbatim"):
    return CountEvidence(eid, candidate, study_id=study, direction=direction,
                         source_content_level="full_text", evidence_level=level,
                         source_valid=True, has_locator=True, has_claim=True, has_target=True)


def test_counts_independent_studies_once_and_exposes_conflict() -> None:
    rows = [_e("e1", "A", "S1"), _e("e2", "A", "S1"), _e("e3", "A", "S2"), _e("e4", "A", "S3", "opposes")]
    result = rank_by_evidence_count(rows)[0]
    assert result.supporting_studies == 2
    assert result.opposing_studies == 1
    assert result.status == "needs_review"
    assert "conflicting_directions" in result.reasons


def test_unverifiable_rows_are_excluded() -> None:
    result = rank_by_evidence_count([_e("e1", "A", "S1", level="not_reported")])[0]
    assert result.eligible_evidence_count == 0
    assert result.excluded_evidence_count == 1
    assert result.status == "needs_review"
    assert result.score is None
    assert "no_eligible_evidence" in result.reasons


def test_candidates_without_eligible_rows_sort_after_scored_candidates() -> None:
    scored = _e("e1", "A", "S1")
    empty = _e("e2", "B", "S2", level="not_reported")
    result = rank_by_evidence_count([empty, scored])
    assert [item.candidate_id for item in result] == ["A", "B"]
