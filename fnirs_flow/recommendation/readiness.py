"""Deterministic Evidence Readiness Audit for the packaged CSV library."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from .contracts import EvidenceAdmission, EvidenceDirection


class SlotReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    slot_id: str
    candidate_count: int = 0
    evidence_count: int = 0
    bound_count: int = 0
    admitted_count: int = 0
    orphan_count: int = 0
    pending_review_count: int = 0
    unevaluable_count: int = 0
    source_unresolved_count: int = 0
    claim_missing_count: int = 0
    reviewed_count: int = 0
    direction_counts: dict[str, int] = Field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    repair_backlog: tuple[str, ...] = ()
    capability: str = "fallback_only"


class EvidenceReadinessAudit(BaseModel):
    """Auditable snapshot; no ranking or evidence-strength score is computed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_version: str = "1.0.0"
    source_counts: dict[str, int]
    link_counts: dict[str, int]
    slots: tuple[SlotReadiness, ...]
    generated_from: tuple[str, ...]

    def to_markdown(self) -> str:
        lines = [
            "# Evidence Readiness Audit",
            "",
            f"- Audit version: `{self.audit_version}`",
            "- Evidence strength and recommendation ranking are intentionally not computed.",
            "",
            "## Source counts",
            "",
        ]
        lines.extend(f"- {key}: {value}" for key, value in sorted(self.source_counts.items()))
        lines.extend(
            [
                "",
                "## Slot capability",
                "",
                "| Slot | Evidence | Bound | Orphan | Review | Unevaluable | Capability |",
                "|---|---:|---:|---:|---:|---:|---|",
            ]
        )
        for slot in self.slots:
            lines.append(
                f"| {slot.slot_id} | {slot.evidence_count} | {slot.bound_count} | "
                f"{slot.orphan_count} | {slot.pending_review_count} | "
                f"{slot.unevaluable_count} | {slot.capability} |"
            )
        return "\n".join(lines) + "\n"


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_evidence_link(link: dict[str, str], source: dict[str, str] | None = None) -> EvidenceAdmission:
    """Normalize legacy CSV links into the frozen admission contract.

    Missing P1 fields deliberately remain missing and make the record
    non-admitted; citation counts or legacy confidence are never promoted.
    """
    source = source or {}
    direction_raw = (link.get("direction") or link.get("evidence_use") or "neutral").strip().lower()
    try:
        direction = EvidenceDirection(direction_raw)
    except ValueError:
        direction = EvidenceDirection.NEUTRAL
    source_id = (link.get("source_id") or "").strip()
    source_locator = (link.get("source_locator") or "").strip() or (
        source.get("source_path_or_url", "").strip() or None
    )
    reasons: list[str] = []
    if not source_id:
        reasons.append("missing_source_id")
    if not source_locator:
        reasons.append("missing_source_locator")
    if not link.get("target_object_type"):
        reasons.append("missing_target_object_type")
    if not link.get("target_object_id"):
        reasons.append("unbound_target")
    if not (link.get("claim_id") or link.get("claim_type")):
        reasons.append("missing_claim_metadata")
    if not (link.get("study_id") or source.get("study_id")):
        reasons.append("missing_study_id")
    review = (link.get("extraction_review_status") or "not_reviewed").strip().lower()
    withdrawn = str(link.get("withdrawn_or_corrected", "")).lower() in {"1", "true", "yes"}
    if not source:
        reasons.append("invalid_source")
    admitted = not reasons and review == "reviewed" and not withdrawn and bool(source_id and source)
    if review != "reviewed":
        reasons.append("extraction_not_reviewed")
    if withdrawn:
        reasons.append("withdrawn_or_corrected")
    return EvidenceAdmission(
        evidence_id=link.get("evidence_id") or link.get("link_id") or "",
        source_id=source_id,
        source_valid=bool(source_id and source),
        source_status="valid" if source else "unknown",
        source_locator=source_locator,
        target_object_type=link.get("target_object_type") or None,
        target_object_id=link.get("target_object_id") or None,
        claim_id=link.get("claim_id") or None,
        claim_type=link.get("claim_type") or None,
        direction=direction,
        study_id=link.get("study_id") or source.get("study_id") or None,
        dataset_id=link.get("dataset_id") or link.get("queue_id") or None,
        extraction_review_status=review,
        withdrawn_or_corrected=str(link.get("withdrawn_or_corrected", "")).lower() in {"1", "true", "yes"},
        admitted=admitted,
        reasons=tuple(sorted(set(reasons))),
    )


def _source_access_status(source: dict[str, str] | None, *, library_dir: Path) -> str:
    """Classify whether a source locator resolves locally without network I/O."""
    if not source:
        return "missing_source_record"
    locator = (source.get("source_path_or_url") or "").strip()
    if not locator:
        return "missing_locator"
    parsed = urlparse(locator)
    if parsed.scheme in {"http", "https", "doi", "pmid", "pmcid"}:
        return "external_locator"
    path = Path(locator)
    if path.is_absolute() and path.exists():
        return "local_file"
    if (library_dir / path).exists():
        return "local_file"
    return "unresolved_local_path"


def audit_library(library_dir: str | Path) -> EvidenceReadinessAudit:
    """Build a stable audit from package CSVs, conservatively fail-closed."""
    root = Path(library_dir)
    atoms = _rows(root / "method_atoms.csv")
    links = _rows(root / "atom_evidence_links.csv")
    slots = _rows(root / "flow_slot_contracts.csv")
    source_rows = _rows(root / "sources.csv")
    source_ids = {row.get("source_id", "") for row in source_rows}
    atom_by_id = {row.get("atom_id", ""): row for row in atoms}
    slot_ids = sorted({row.get("slot_id", "") for row in slots if row.get("slot_id")})
    for row in atoms:
        slot = row.get("target_flow_slot", "")
        if slot and slot not in slot_ids:
            slot_ids.append(slot)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for link in links:
        target = link.get("target_object_id", "")
        atom = atom_by_id.get(target)
        slot = atom.get("target_flow_slot", "") if atom else ""
        grouped[slot].append(link)
    if grouped.get(""):
        slot_ids.append("unassigned")
    results: list[SlotReadiness] = []
    for slot_id in sorted(slot_ids):
        candidates = [row for row in atoms if row.get("target_flow_slot") == slot_id]
        evidence = grouped.get("", []) if slot_id == "unassigned" else grouped.get(slot_id, [])
        directions: Counter[str] = Counter()
        for row in evidence:
            value = row.get("direction") or row.get("evidence_use") or "background_only"
            direction = value if value in {"supports", "opposes", "neutral", "background_only"} else "background_only"
            directions[direction] += 1
        missing: set[str] = set()
        backlog: set[str] = set()
        bound = admitted = orphan = pending = unevaluable = 0
        source_unresolved = claim_missing = reviewed_count = 0
        for row in evidence:
            source = next(
                (item for item in source_rows if item.get("source_id") == row.get("source_id")),
                None,
            )
            admission = normalize_evidence_link(row, source)
            if admission.admitted:
                admitted += 1
            if admission.extraction_review_status == "reviewed":
                reviewed_count += 1
            if _source_access_status(source, library_dir=root) == "unresolved_local_path":
                source_unresolved += 1
                unevaluable += 1
                missing.add("source_access")
                backlog.add("verify_source_locator")
            target = row.get("target_object_id", "")
            source_id = row.get("source_id", "")
            if target and target in atom_by_id:
                bound += 1
            else:
                orphan += 1
                backlog.add("bind_target_object")
            if source_id not in source_ids:
                unevaluable += 1
                missing.add("source_id")
            if not row.get("target_object_type"):
                missing.add("target_object_type")
                backlog.add("classify_target_object")
            if not row.get("claim_id") and not row.get("claim_type"):
                claim_missing += 1
                missing.add("claim_id_or_claim_type")
                backlog.add("bind_claim")
            if not row.get("study_id"):
                missing.add("study_id")
                backlog.add("bind_study")
            if not row.get("source_locator"):
                missing.add("source_locator")
                backlog.add("add_source_locator")
            if not row.get("quote_or_summary"):
                unevaluable += 1
                missing.add("quote_or_summary")
                backlog.add("add_source_locator_or_quote")
            if row.get("extraction_review_status", "not_reviewed") != "reviewed":
                pending += 1
                backlog.add("review_extraction")
        for candidate in candidates:
            if not candidate.get("input_schema"):
                missing.add("input_schema")
            if not candidate.get("output_schema"):
                missing.add("output_schema")
        capability = (
            "evidence_ready"
            if evidence and not orphan and not unevaluable and not pending and not missing
            else "fallback_only"
        )
        if not candidates and not evidence:
            capability = "unsupported"
        results.append(
            SlotReadiness(
                slot_id=slot_id,
                candidate_count=len(candidates),
                evidence_count=len(evidence),
                bound_count=bound,
                admitted_count=admitted,
                orphan_count=orphan,
                pending_review_count=pending,
                unevaluable_count=unevaluable,
                source_unresolved_count=source_unresolved,
                claim_missing_count=claim_missing,
                reviewed_count=reviewed_count,
                direction_counts=dict(sorted(directions.items())),
                missing_fields=tuple(sorted(missing)),
                repair_backlog=tuple(sorted(backlog)),
                capability=capability,
            )
        )
    return EvidenceReadinessAudit(
        source_counts={"sources": len(source_rows), "method_atoms": len(atoms), "flow_slots": len(slot_ids)},
        link_counts={"evidence_links": len(links)},
        slots=tuple(results),
        generated_from=("sources.csv", "method_atoms.csv", "flow_slot_contracts.csv", "atom_evidence_links.csv"),
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build a deterministic Evidence Readiness Audit")
    parser.add_argument("library_dir", nargs="?", default="fnirs_flow/registry/methodatom_lib")
    parser.add_argument("--output", type=Path, default=Path("outputs/methodatom_library/evidence_readiness_audit.json"))
    parser.add_argument("--markdown", type=Path, default=Path("outputs/methodatom_library/evidence_readiness_audit.md"))
    args = parser.parse_args()
    audit = audit_library(args.library_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.markdown.write_text(audit.to_markdown(), encoding="utf-8")
    print(f"Evidence Readiness Audit: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
