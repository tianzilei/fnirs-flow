"""Package exporter: creates .fnirsflow.zip packages with multiple profiles."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

import fnirs_flow


class PackageProfile(BaseModel):
    """Definition of a package export profile."""

    profile_id: str
    name: str
    description: str
    include_patterns: list[str] = Field(default_factory=list)
    include_reports: bool = True
    include_provenance: bool = False
    include_failure_manifest: bool = False


# Built-in package profiles
PACKAGE_PROFILES: dict[str, PackageProfile] = {
    "reproducibility_package": PackageProfile(
        profile_id="reproducibility_package",
        name="Reproducibility Package",
        description="Full package for reproducing analysis results",
        include_patterns=[
            "plan.json",
            "execution_dag.json",
            "adapter_manifest.json",
            "risk_register.json",
            "reporting_checklist.json",
            "artifact_manifest.json",
            "reproducibility_manifest.json",
            "data_manifest.json",
            "analysis_plan.md",
            "validation_report.md",
            "run_report.md",
        ],
        include_reports=True,
        include_provenance=True,
        include_failure_manifest=True,
    ),
    "submission_package": PackageProfile(
        profile_id="submission_package",
        name="Submission Package",
        description="Lightweight package for journal submission",
        include_patterns=[
            "plan.json",
            "analysis_plan.md",
            "risk_register.json",
            "validation_report.md",
        ],
        include_reports=True,
        include_provenance=False,
        include_failure_manifest=False,
    ),
    "reviewer_package": PackageProfile(
        profile_id="reviewer_package",
        name="Reviewer Package",
        description="Comprehensive package for peer review",
        include_patterns=[
            "plan.json",
            "execution_dag.json",
            "adapter_manifest.json",
            "risk_register.json",
            "reporting_checklist.json",
            "artifact_manifest.json",
            "reproducibility_manifest.json",
            "data_manifest.json",
            "analysis_plan.md",
            "validation_report.md",
            "run_report.md",
        ],
        include_reports=True,
        include_provenance=True,
        include_failure_manifest=True,
    ),
}


def get_package_profile(profile_id: str) -> PackageProfile:
    """Get a package profile by ID. Raises ValueError if not found."""
    if profile_id not in PACKAGE_PROFILES:
        available = ", ".join(PACKAGE_PROFILES.keys())
        raise ValueError(f"Unsupported package profile: '{profile_id}'. Available: {available}")
    return PACKAGE_PROFILES[profile_id]


def list_package_profiles() -> list[PackageProfile]:
    """List all available package profiles."""
    return list(PACKAGE_PROFILES.values())


def export_package(
    outdir: str | Path,
    package_path: str | Path,
    profile_id: str = "reproducibility_package",
    include_snapshots: bool = True,
    include_attempts: bool = False,
    exclude_raw_data: bool = True,
) -> Path:
    """Export a .fnirsflow.zip package.

    Args:
        outdir: Directory containing compiled outputs
        package_path: Output path for the .zip file
        profile_id: Package profile to use (default: reproducibility_package)
        include_snapshots: Include ProjectSnapshot files
        include_attempts: Include ActionAttempt files
        exclude_raw_data: Always True for v1

    Returns:
        Path to the created package

    Raises:
        ValueError: If profile_id is not recognized
    """
    outdir = Path(outdir)
    package_path = Path(package_path)
    profile = get_package_profile(profile_id)

    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add profile-specified files (check both root and compiled/ subdirectory)
        for pattern in profile.include_patterns:
            filepath = outdir / pattern
            compiled_path = outdir / "compiled" / pattern
            if filepath.exists():
                zf.write(filepath, filepath.name)
            elif compiled_path.exists():
                zf.write(compiled_path, compiled_path.name)

        # Add any .md reports if profile includes them
        if profile.include_reports:
            for md_file in outdir.glob("*.md"):
                if md_file.name not in [f for f in profile.include_patterns if f.endswith(".md")]:
                    zf.write(md_file, md_file.name)

        # Add provenance log if profile includes it
        if profile.include_provenance:
            candidates = [
                outdir / "provenance_log.json",
                outdir / "logs" / "provenance_log.json",
            ]
            for candidate in candidates:
                if candidate.exists():
                    zf.write(candidate, candidate.name)
                    break

        # Add failure manifest if profile includes it
        if profile.include_failure_manifest:
            candidates = [
                outdir / "failure_manifest.json",
                outdir / "logs" / "failure_manifest.json",
            ]
            for candidate in candidates:
                if candidate.exists():
                    zf.write(candidate, candidate.name)
                    break

        # Add data manifest relink instructions
        relink_content: dict[str, Any] = {
            "relink_instructions": (
                "To use this package, update the 'local_root' field in "
                "data_manifest.json to point to your local data directory."
            ),
            "profile": profile_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "fnirs_flow_version": fnirs_flow.__version__,
        }

        # Detect AI involvement from flow metadata
        plan_path = outdir / "plan.json"
        compiled_plan_path = outdir / "compiled" / "plan.json"
        for candidate in [plan_path, compiled_plan_path]:
            if candidate.exists():
                try:
                    plan_data = json.loads(candidate.read_text(encoding="utf-8"))
                    flow_meta = plan_data.get("flow", {}).get("metadata", {})
                    ai_gen = flow_meta.get("ai_generation")
                    if ai_gen:
                        relink_content["ai_assisted"] = True
                        relink_content["ai_generation"] = ai_gen
                except (json.JSONDecodeError, KeyError):
                    pass
                break

        zf.writestr("RELINK_INSTRUCTIONS.json", json.dumps(relink_content, indent=2))

    return package_path


def get_package_contents(package_path: str | Path) -> list[str]:
    """List contents of a .fnirsflow.zip package."""
    with zipfile.ZipFile(package_path, "r") as zf:
        return zf.namelist()
