"""ComBat harmonization diagnostics atom: preflight checks and output manifests.

This module provides precondition validation and diagnostic outputs
for multi-site fNIRS harmonization using ComBat/neuroCombat.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from fnirs_flow.validation.models import RiskItem


class ComBatPreflightResult(BaseModel):
    """Result of ComBat preflight diagnostics."""

    ready: bool = False
    risks: list[RiskItem] = Field(default_factory=list)
    site_summary: dict[str, Any] = Field(default_factory=dict)
    covariate_summary: dict[str, Any] = Field(default_factory=dict)


class ComBatOutputManifest(BaseModel):
    """Output manifest for ComBat harmonization."""

    harmonization_method: str = "neuroCombat"
    input_site_count: int = 0
    input_subject_count: int = 0
    covariates_preserved: list[str] = Field(default_factory=list)
    site_effects_removed: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


def validate_combat_preflight(
    data_manifest: dict[str, Any],
    site_field: str = "site",
    biological_covariates: list[str] | None = None,
    min_samples_per_site: int = 5,
) -> ComBatPreflightResult:
    """Validate preconditions for ComBat harmonization.

    Checks:
    - site field exists in data manifest
    - Each site has sufficient samples
    - Biological covariates are declared
    - Site is not completely confounded with group

    Args:
        data_manifest: Data manifest dict with subject_session_runs
        site_field: Field name for site/device information
        biological_covariates: List of biological covariate names to preserve
        min_samples_per_site: Minimum samples required per site

    Returns:
        ComBatPreflightResult with risks and readiness status
    """
    result = ComBatPreflightResult()
    if biological_covariates is None:
        biological_covariates = []

    runs = data_manifest.get("subject_session_runs", [])

    # Check 1: site field exists
    has_site = any(site_field in run for run in runs)
    if not has_site:
        result.risks.append(
            RiskItem(
                risk_id="combat-no-site-field",
                severity="fatal",
                domain="harmonization",
                message=f"Site field '{site_field}' not found in data manifest",
                suggested_action=(f"Add '{site_field}' field to each entry in data_manifest.subject_session_runs"),
            )
        )
        result.ready = False
        return result

    # Check 2: site distribution
    site_counts: dict[str, int] = {}
    for run in runs:
        site = run.get(site_field, "unknown")
        site_counts[site] = site_counts.get(site, 0) + 1

    result.site_summary = {
        "n_sites": len(site_counts),
        "site_counts": site_counts,
        "total_runs": len(runs),
    }

    # Check 3: minimum samples per site
    for site, count in site_counts.items():
        if count < min_samples_per_site:
            severity = "high" if count < 3 else "medium"
            result.risks.append(
                RiskItem(
                    risk_id=f"combat-few-samples-{site}",
                    severity=severity,
                    domain="harmonization",
                    message=f"Site '{site}' has only {count} samples (minimum: {min_samples_per_site})",
                    suggested_action="Consider merging similar sites or collecting more data",
                )
            )

    # Check 4: covariates declared
    result.covariate_summary = {
        "declared_covariates": biological_covariates,
        "n_covariates": len(biological_covariates),
    }

    if not biological_covariates:
        result.risks.append(
            RiskItem(
                risk_id="combat-no-covariates",
                severity="medium",
                domain="harmonization",
                message="No biological covariates declared for harmonization",
                suggested_action=("Declare biological covariates (age, sex, etc.) to preserve during harmonization"),
            )
        )

    # Check 5: site-group confounding (if group field available)
    has_group = any("group" in run for run in runs)
    if has_group and len(site_counts) > 1:
        site_groups: dict[str, set[str]] = {}
        for run in runs:
            site = run.get(site_field, "unknown")
            group = run.get("group", "unknown")
            site_groups.setdefault(site, set()).add(group)

        # Check if each site has only one group
        confounded = all(len(groups) == 1 for groups in site_groups.values())
        if confounded:
            result.risks.append(
                RiskItem(
                    risk_id="combat-site-confounded",
                    severity="high",
                    domain="harmonization",
                    message="Site is completely confounded with group variable",
                    suggested_action=(
                        "Site and group are perfectly correlated - harmonization may remove biological effects"
                    ),
                )
            )

    # Determine readiness
    fatal = any(r.severity == "fatal" for r in result.risks)
    result.ready = not fatal

    return result


def generate_combat_output_manifest(
    preflight: ComBatPreflightResult,
    harmonization_params: dict[str, Any] | None = None,
) -> ComBatOutputManifest:
    """Generate output manifest after ComBat harmonization."""
    return ComBatOutputManifest(
        input_site_count=preflight.site_summary.get("n_sites", 0),
        input_subject_count=preflight.site_summary.get("total_runs", 0),
        covariates_preserved=preflight.covariate_summary.get("declared_covariates", []),
        parameters=harmonization_params or {},
    )
