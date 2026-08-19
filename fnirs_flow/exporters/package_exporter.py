"""Package exporter: creates .fnirsflow.zip packages with multiple profiles."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

import fnirs_flow
from fnirs_flow.infrastructure.filesystem import is_macos_metadata_path, is_visible_data_file
from fnirs_flow.infrastructure.portability import (
    SIGNAL_OR_WORK_EXTENSIONS,
    TRACKABLE_EXTENSIONS,
    find_absolute_path_records,
)
from fnirs_flow.infrastructure.uri import ProjectURI, create_external_data_uri, create_project_uri

MAX_PACKAGE_BYTES = 10 * 1024**2


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
            "flow.json",
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
            # §11: Dependency provenance files
            "dependency_plan.json",
            "environment_manifest.json",
            "backend_probe.json",
            "dependency_installation_record.json",
            "parameter_confirmation_record.json",
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
            "flow.json",
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
            "flow.json",
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
            # §11: Dependency provenance files
            "dependency_plan.json",
            "environment_manifest.json",
            "backend_probe.json",
            "parameter_confirmation_record.json",
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


def _portable_relative_path(value: str, old_root: Path | None) -> str:
    if not value:
        return ""
    if value.startswith("external-data://"):
        try:
            return ProjectURI(value).path.as_posix()
        except ValueError:
            return ""
    path = Path(value)
    if path.is_absolute():
        if old_root is None:
            return ""
        try:
            return path.relative_to(old_root).as_posix()
        except ValueError:
            return ""
    return path.as_posix()


def _portable_data_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a package-safe manifest with no machine-local data paths."""
    portable = cast(dict[str, Any], json.loads(json.dumps(manifest)))
    dataset_id = str(portable.get("dataset_id") or "dataset")
    old_root_text = str(portable.get("local_root", ""))
    old_root = Path(old_root_text) if old_root_text else None
    portable["local_root"] = ""
    portable["external_data_uri_prefix"] = f"external-data://{dataset_id}/"
    portable["requires_data_binding"] = True
    access_instructions = str(portable.get("access_instructions", ""))
    if old_root_text and old_root_text in access_instructions:
        portable["access_instructions"] = (
            f"Bind external-data://{dataset_id}/ to a local dataset directory before rerunning."
        )

    for item in portable.get("files", []):
        relative = _portable_relative_path(str(item.get("uri") or item.get("path", "")), old_root)
        if relative:
            uri = str(create_external_data_uri(dataset_id, relative))
            item["path"] = uri
            item["uri"] = uri

    for run in portable.get("subject_session_runs", []):
        relative = str(run.get("relative_path", "")) or _portable_relative_path(
            str(run.get("uri") or run.get("path", "")), old_root
        )
        if relative:
            uri = str(create_external_data_uri(dataset_id, relative))
            run["relative_path"] = relative
            run["path"] = uri
            run["uri"] = uri

        events_relative = _portable_relative_path(
            str(run.get("events_uri") or run.get("events_path", "")), old_root
        )
        if events_relative:
            events_uri = str(create_external_data_uri(dataset_id, events_relative))
            run["events_path"] = events_uri
            run["events_uri"] = events_uri

    for table in portable.get("metadata_tables", []):
        relative = _portable_relative_path(str(table.get("uri") or table.get("path", "")), old_root)
        if relative:
            uri = str(create_external_data_uri(dataset_id, relative))
            table["path"] = uri
            table["uri"] = uri
    return portable


def _portable_project_json(value: Any, project_root: Path) -> Any:
    """Remove machine-local project paths from packaged JSON documents."""
    if isinstance(value, dict):
        portable: dict[str, Any] = {}
        for key, item in value.items():
            if key == "resolved_path":
                continue
            portable[key] = _portable_project_json(item, project_root)
        if portable.get("uri") and "path" in portable:
            portable["path"] = portable["uri"]
        elif portable.get("relative_path") and "path" in portable:
            portable["path"] = str(create_project_uri(f"outputs/{portable['relative_path']}"))
        return portable
    if isinstance(value, list):
        return [_portable_project_json(item, project_root) for item in value]
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute():
            try:
                relative = path.resolve().relative_to(project_root.resolve())
            except (OSError, ValueError):
                return path.name
            return str(create_project_uri(f"outputs/{relative.as_posix()}"))
    return value


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
    if not exclude_raw_data:
        raise ValueError("Raw signal data cannot be embedded in a .fnirsflow package")

    def add_portable_file(zf: zipfile.ZipFile, source: Path, arcname: str) -> None:
        if source.suffix.lower() in SIGNAL_OR_WORK_EXTENSIONS:
            return
        if source.suffix.lower() not in TRACKABLE_EXTENSIONS:
            return
        if source.suffix.lower() == ".json":
            try:
                payload = json.loads(source.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
            else:
                zf.writestr(arcname, json.dumps(_portable_project_json(payload, outdir), indent=2))
                return
        findings = find_absolute_path_records(source)
        if findings:
            raise ValueError(f"Package file contains a machine-local path: {source.name}")
        zf.write(source, arcname)

    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add profile-specified files (check both root and compiled/ subdirectory)
        for pattern in profile.include_patterns:
            candidates = [
                outdir / pattern,
                outdir / "logs" / pattern,
                outdir / "compiled" / pattern,
            ]
            for candidate in candidates:
                if candidate.exists():
                    if pattern == "data_manifest.json":
                        manifest_data = json.loads(candidate.read_text(encoding="utf-8"))
                        zf.writestr(candidate.name, json.dumps(_portable_data_manifest(manifest_data), indent=2))
                    elif pattern == "artifact_manifest.json":
                        artifact_data = json.loads(candidate.read_text(encoding="utf-8"))
                        zf.writestr(
                            candidate.name,
                            json.dumps(_portable_project_json(artifact_data, outdir), indent=2),
                        )
                    else:
                        add_portable_file(zf, candidate, candidate.name)
                    break

        # Reproducibility and reviewer packages carry realized tabular results,
        # while raw input data remain excluded.
        if profile_id in {"reproducibility_package", "reviewer_package"}:
            derivatives = outdir / "derivatives"
            if derivatives.exists():
                for result_file in sorted(derivatives.rglob("*")):
                    if is_visible_data_file(result_file, root=outdir):
                        add_portable_file(
                            zf, result_file, result_file.relative_to(outdir).as_posix()
                        )

        # Add any .md reports if profile includes them
        if profile.include_reports:
            for md_file in outdir.glob("*.md"):
                if is_macos_metadata_path(md_file.name):
                    continue
                if md_file.name not in [f for f in profile.include_patterns if f.endswith(".md")]:
                    add_portable_file(zf, md_file, md_file.name)

        # Add provenance log if profile includes it
        if profile.include_provenance:
            candidates = [
                outdir / "provenance_log.json",
                outdir / "logs" / "provenance_log.json",
            ]
            for candidate in candidates:
                if candidate.exists():
                    provenance_data = json.loads(candidate.read_text(encoding="utf-8"))
                    zf.writestr(
                        candidate.name,
                        json.dumps(_portable_project_json(provenance_data, outdir), indent=2),
                    )
                    break

        # Add failure manifest if profile includes it
        if profile.include_failure_manifest:
            candidates = [
                outdir / "failure_manifest.json",
                outdir / "logs" / "failure_manifest.json",
            ]
            for candidate in candidates:
                if candidate.exists():
                    add_portable_file(zf, candidate, candidate.name)
                    break

        # Add data manifest relink instructions
        relink_content: dict[str, Any] = {
            "relink_instructions": (
                "Bind the external-data:// dataset URI to a local data directory "
                "with the import or relink-data command before rerunning."
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
                    flow_meta = plan_data.get("metadata") or plan_data.get("flow", {}).get("metadata", {})
                    ai_gen = flow_meta.get("ai_generation")
                    if ai_gen:
                        relink_content["ai_assisted"] = True
                        relink_content["ai_generation"] = ai_gen

                    # Add backend information
                    backend_info = {}
                    for atom in plan_data.get("preprocessing_atoms", []) + plan_data.get("analysis_atoms", []):
                        if atom.get("backend_id"):
                            backend_id = atom["backend_id"]
                            if backend_id not in backend_info:
                                backend_info[backend_id] = {
                                    "operations": [],
                                    "version_spec": atom.get("backend_version_spec", ""),
                                }
                            backend_info[backend_id]["operations"].append(atom.get("operation", ""))

                    if backend_info:
                        relink_content["backends"] = backend_info

                except (json.JSONDecodeError, KeyError):
                    pass
                break

        zf.writestr("RELINK_INSTRUCTIONS.json", json.dumps(relink_content, indent=2))

    # Write an authoritative package manifest after all profile files are known.
    with zipfile.ZipFile(package_path, "r") as zf:
        file_manifest = {
            name: {"sha256": hashlib.sha256(zf.read(name)).hexdigest()}
            for name in zf.namelist()
            if name != "manifest.json"
        }
    file_manifest["manifest.json"] = {"sha256": ""}
    manifest = {
        "schema_version": "1.0.0",
        "profile": profile_id,
        "files": file_manifest,
    }
    with zipfile.ZipFile(package_path, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    with zipfile.ZipFile(package_path, "r") as zf:
        uncompressed_size = sum(info.file_size for info in zf.infolist())
    if package_path.stat().st_size > MAX_PACKAGE_BYTES or uncompressed_size > MAX_PACKAGE_BYTES:
        package_path.unlink(missing_ok=True)
        raise ValueError("Export package exceeds the 10 MiB size limit")

    return package_path


def get_package_contents(package_path: str | Path) -> list[str]:
    """List contents of a .fnirsflow.zip package."""
    with zipfile.ZipFile(package_path, "r") as zf:
        return zf.namelist()
