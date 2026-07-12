"""Inclusion audit: check demographic fields for signal quality and exclusion patterns."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from fnirs_flow.validation.models import RiskItem


class DemographicField(BaseModel):
    """Defines a demographic field for inclusion audit."""

    field_id: str
    name: str
    description: str = ""
    data_type: str = "string"  # string, float, int, categorical
    categories: list[str] = Field(default_factory=list)
    required: bool = False
    affects_signal_quality: bool = False


class SubjectDemographics(BaseModel):
    """Demographics for a single subject."""

    subject_id: str
    fields: dict[str, Any] = Field(default_factory=dict)


class InclusionAuditResult(BaseModel):
    """Result of inclusion audit."""

    total_subjects: int = 0
    subjects_with_missing_fields: int = 0
    field_completeness: dict[str, float] = Field(default_factory=dict)
    signal_quality_by_group: dict[str, dict[str, float]] = Field(default_factory=dict)
    risks: list[RiskItem] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


# Standard demographic fields for fNIRS inclusion audit
STANDARD_DEMOGRAPHIC_FIELDS: list[DemographicField] = [
    DemographicField(
        field_id="age",
        name="Age",
        description="Participant age in years",
        data_type="float",
        required=True,
    ),
    DemographicField(
        field_id="sex",
        name="Sex",
        description="Biological sex",
        data_type="categorical",
        categories=["male", "female", "other"],
        required=True,
    ),
    DemographicField(
        field_id="skin_color",
        name="Skin Color",
        description="Skin color/fitzpatrick scale - affects light penetration",
        data_type="categorical",
        categories=["I", "II", "III", "IV", "V", "VI"],
        affects_signal_quality=True,
    ),
    DemographicField(
        field_id="hair_texture",
        name="Hair Texture",
        description="Hair texture/density - affects optode coupling",
        data_type="categorical",
        categories=["straight_thin", "straight_thick", "wavy", "curly", "coily"],
        affects_signal_quality=True,
    ),
    DemographicField(
        field_id="hair_density",
        name="Hair Density",
        description="Hair density - affects optode coupling",
        data_type="categorical",
        categories=["sparse", "medium", "dense"],
        affects_signal_quality=True,
    ),
    DemographicField(
        field_id="head_circumference",
        name="Head Circumference",
        description="Head circumference in cm",
        data_type="float",
    ),
    DemographicField(
        field_id="handedness",
        name="Handedness",
        description="Dominant hand",
        data_type="categorical",
        categories=["right", "left", "ambidextrous"],
    ),
]


class InclusionAuditor:
    """Audits demographic data for inclusion/exclusion patterns."""

    def __init__(self, fields: list[DemographicField] | None = None) -> None:
        self._fields = fields or STANDARD_DEMOGRAPHIC_FIELDS
        self._field_map = {f.field_id: f for f in self._fields}

    def audit(
        self,
        subjects: list[SubjectDemographics],
        qc_results: dict[str, dict[str, Any]] | None = None,
    ) -> InclusionAuditResult:
        """Run inclusion audit on subject demographics.

        Args:
            subjects: List of subject demographics
            qc_results: Optional QC results per subject (subject_id -> metrics)

        Returns:
            InclusionAuditResult with findings
        """
        result = InclusionAuditResult(total_subjects=len(subjects))

        if not subjects:
            result.risks.append(
                RiskItem(
                    risk_id="inclusion-no-subjects",
                    severity="medium",
                    domain="reporting",
                    message="No subjects provided for inclusion audit",
                )
            )
            return result

        # Calculate field completeness
        field_counts: dict[str, int] = {f.field_id: 0 for f in self._fields}
        for subject in subjects:
            for field_id in field_counts:
                if field_id in subject.fields and subject.fields[field_id] is not None:
                    field_counts[field_id] += 1

        n = len(subjects)
        for field_id, count in field_counts.items():
            result.field_completeness[field_id] = count / n if n > 0 else 0.0

        # Check for missing required fields — count unique subjects with any missing required field
        subjects_with_any_missing: set[str] = set()
        for field in self._fields:
            if field.required:
                completeness = result.field_completeness.get(field.field_id, 0.0)
                if completeness < 1.0:
                    for subject in subjects:
                        if field.field_id not in subject.fields or subject.fields[field.field_id] is None:
                            subjects_with_any_missing.add(subject.subject_id)
                    missing = int((1.0 - completeness) * n)
                    result.risks.append(
                        RiskItem(
                            risk_id=f"inclusion-missing-{field.field_id}",
                            severity="medium",
                            domain="reporting",
                            message=f"Missing {field.name} for {missing}/{n} subjects",
                            suggested_action=f"Collect {field.name} data for all participants",
                        )
                    )

        result.subjects_with_missing_fields = len(subjects_with_any_missing)

        # Check signal quality by demographic groups
        if qc_results:
            result.signal_quality_by_group = self._analyze_qc_by_group(subjects, qc_results)

        # Generate recommendations
        result.recommendations = self._generate_recommendations(result)

        return result

    def _analyze_qc_by_group(
        self,
        subjects: list[SubjectDemographics],
        qc_results: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, float]]:
        """Analyze QC metrics by demographic groups."""
        groups: dict[str, dict[str, list[float]]] = {}

        for subject in subjects:
            sid = subject.subject_id
            if sid not in qc_results:
                continue

            qc = qc_results[sid]
            sci_mean = qc.get("sci_mean", 0.0)

            for field_id, value in subject.fields.items():
                if value is None:
                    continue

                key = f"{field_id}_{value}"
                if key not in groups:
                    groups[key] = {"sci_means": []}
                groups[key]["sci_means"].append(sci_mean)

        # Calculate group statistics
        result: dict[str, dict[str, float]] = {}
        for key, data in groups.items():
            if data["sci_means"]:
                result[key] = {
                    "mean_sci": sum(data["sci_means"]) / len(data["sci_means"]),
                    "n_subjects": len(data["sci_means"]),
                }

        return result

    def _generate_recommendations(self, result: InclusionAuditResult) -> list[str]:
        """Generate recommendations based on audit findings."""
        recs: list[str] = []

        if result.subjects_with_missing_fields > 0:
            recs.append("Consider collecting missing demographic data to enable inclusion/exclusion analysis.")

        # Check for signal quality differences
        for group_key, stats in result.signal_quality_by_group.items():
            if stats.get("mean_sci", 1.0) < 0.7:
                recs.append(
                    f"Group '{group_key}' shows low mean SCI ({stats['mean_sci']:.2f}). "
                    "Consider investigating signal quality differences."
                )

        if not recs:
            recs.append("Demographic data completeness is adequate for basic reporting.")

        return recs


def write_inclusion_audit_report(
    audit_result: InclusionAuditResult,
    outdir: Path,
) -> Path:
    """Write inclusion audit report to file."""
    lines = [
        "# Inclusion Audit Report",
        "",
        f"**Total Subjects:** {audit_result.total_subjects}",
        f"**Subjects with Missing Fields:** {audit_result.subjects_with_missing_fields}",
        "",
        "## Field Completeness",
        "",
    ]

    for field_id, completeness in audit_result.field_completeness.items():
        pct = completeness * 100
        lines.append(f"- {field_id}: {pct:.1f}%")

    if audit_result.signal_quality_by_group:
        lines.extend(["", "## Signal Quality by Group", ""])
        for group, stats in audit_result.signal_quality_by_group.items():
            lines.append(f"- {group}: mean SCI = {stats.get('mean_sci', 'N/A'):.3f}")

    if audit_result.risks:
        lines.extend(["", "## Risks", ""])
        for risk in audit_result.risks:
            lines.append(f"- [{risk.severity}] {risk.message}")

    if audit_result.recommendations:
        lines.extend(["", "## Recommendations", ""])
        for rec in audit_result.recommendations:
            lines.append(f"- {rec}")

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "inclusion_audit_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
