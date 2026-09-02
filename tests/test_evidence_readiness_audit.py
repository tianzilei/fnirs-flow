import csv
from pathlib import Path

from fnirs_flow.recommendation.readiness import audit_library, normalize_evidence_link


def _write(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_audit_is_conservative_and_reports_orphans(tmp_path: Path) -> None:
    _write(tmp_path / "sources.csv", ["source_id"], [{"source_id": "S1"}])
    _write(
        tmp_path / "method_atoms.csv",
        ["atom_id", "target_flow_slot", "input_schema", "output_schema"],
        [{"atom_id": "A1", "target_flow_slot": "filter_slot", "input_schema": "x", "output_schema": "y"}],
    )
    _write(tmp_path / "flow_slot_contracts.csv", ["slot_id"], [{"slot_id": "filter_slot"}])
    fields = [
        "evidence_ref",
        "target_object_type",
        "target_object_id",
        "evidence_use",
        "confidence",
        "quote_or_summary",
        "source_id",
    ]
    _write(
        tmp_path / "atom_evidence_links.csv",
        fields,
        [
            {
                "evidence_ref": "E1",
                "target_object_type": "method_atom",
                "target_object_id": "A1",
                "evidence_use": "supports",
                "confidence": "high",
                "quote_or_summary": "quoted",
                "source_id": "S1",
            },
            {
                "evidence_ref": "E2",
                "target_object_type": "",
                "target_object_id": "",
                "evidence_use": "background_only",
                "confidence": "high",
                "quote_or_summary": "context",
                "source_id": "S1",
            },
        ],
    )
    first = audit_library(tmp_path)
    second = audit_library(tmp_path)
    assert first.model_dump() == second.model_dump()
    slot = next(item for item in first.slots if item.slot_id == "unassigned")
    assert slot.orphan_count == 1
    assert slot.capability == "fallback_only"
    assert slot.evidence_count == 1
    assert first.link_counts["evidence_links"] == 2


def test_normalize_link_rejects_missing_source_record() -> None:
    admission = normalize_evidence_link(
        {
            "evidence_id": "E1",
            "source_id": "MISSING",
            "source_locator": "paper#methods",
            "target_object_type": "method_atom",
            "target_object_id": "A1",
            "claim_type": "method_definition",
            "study_id": "S1",
            "extraction_review_status": "reviewed",
        },
        source=None,
    )
    assert admission.source_valid is False
    assert admission.admitted is False
    assert "invalid_source" in admission.reasons
