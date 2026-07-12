"""Package importer: imports .fnirsflow.zip packages."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _validate_zip_path(member: str, outdir: Path) -> bool:
    """Check that a zip member path doesn't escape the output directory."""
    try:
        target = (outdir / member).resolve()
        return target.is_relative_to(outdir.resolve())
    except (ValueError, OSError):
        return False


def import_package(
    package_path: str | Path,
    outdir: str | Path,
    relink_data: bool = False,
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    """Import a .fnirsflow.zip package.

    Args:
        package_path: Path to the .fnirsflow.zip file
        outdir: Directory to extract contents to
        relink_data: Whether to relink data paths
        data_root: New data root path for relinking

    Returns:
        Dict with import results
    """
    package_path = Path(package_path)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    extracted_files: list[str] = []

    with zipfile.ZipFile(package_path, "r") as zf:
        # Validate all paths before extraction (Zip Slip prevention)
        for member in zf.namelist():
            if not _validate_zip_path(member, outdir):
                raise ValueError(f"Unsafe zip entry: {member}")

        zf.extractall(outdir)
        extracted_files = zf.namelist()

    # Relink data if requested
    relinked = False
    if relink_data and data_root is not None:
        manifest_path = outdir / "data_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["local_root"] = str(data_root)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            relinked = True

    # Mark imported flow as read-only and quarantine custom atoms
    import_metadata: dict[str, Any] = {
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "source_package": str(package_path),
        "read_only": True,
        "quarantined_atoms": [],
    }

    # Check for custom atoms in plan.json and mark them as quarantined
    plan_path = outdir / "plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        for atom_chain in ["preprocessing_atoms", "analysis_atoms", "output_atoms"]:
            for atom in plan.get(atom_chain, []):
                # Atoms with non-builtin operations are custom
                operation = atom.get("operation", "")
                if operation:
                    from fnirs_flow.execution.operations import create_default_registry

                    registry = create_default_registry()
                    if not registry.has(operation):
                        atom["security_status"] = "quarantined"
                        import_metadata["quarantined_atoms"].append(atom.get("atom_id", operation))
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    # Write import metadata
    metadata_path = outdir / "import_metadata.json"
    metadata_path.write_text(json.dumps(import_metadata, indent=2), encoding="utf-8")

    return {
        "extracted_files": extracted_files,
        "relinked": relinked,
        "read_only": True,
        "quarantined_atoms": import_metadata["quarantined_atoms"],
        "package_path": str(package_path),
        "output_dir": str(outdir),
    }


def fork_package(
    package_dir: str | Path,
    fork_dir: str | Path,
    unfork: bool = False,
) -> dict[str, Any]:
    """Fork an imported package to a new editable directory.

    Args:
        package_dir: Directory containing the imported package
        fork_dir: New directory for the forked copy
        unfork: If True, remove read-only and quarantine restrictions

    Returns:
        Dict with fork results
    """
    import shutil

    package_dir = Path(package_dir)
    fork_dir = Path(fork_dir)

    if fork_dir.exists():
        raise ValueError(f"Fork directory already exists: {fork_dir}")

    # Copy the package
    shutil.copytree(package_dir, fork_dir)

    # Update import metadata
    metadata_path = fork_dir / "import_metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if unfork:
            metadata["read_only"] = False
            metadata["forked_at"] = datetime.now(timezone.utc).isoformat()
            metadata["quarantined_atoms"] = []
            # Remove quarantine from plan.json
            plan_path = fork_dir / "plan.json"
            if plan_path.exists():
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                for atom_chain in ["preprocessing_atoms", "analysis_atoms", "output_atoms"]:
                    for atom in plan.get(atom_chain, []):
                        atom.pop("security_status", None)
                plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        else:
            metadata["forked_at"] = datetime.now(timezone.utc).isoformat()
            metadata["read_only"] = True
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "fork_dir": str(fork_dir),
        "read_only": not unfork,
        "unforked": unfork,
    }


def trust_atom(
    project_dir: str | Path,
    atom_id: str,
) -> dict[str, Any]:
    """Trust a quarantined atom, allowing it to execute.

    Args:
        project_dir: Directory containing the project
        atom_id: ID of the atom to trust

    Returns:
        Dict with trust result
    """
    project_dir = Path(project_dir)
    plan_path = project_dir / "plan.json"

    if not plan_path.exists():
        return {"error": "plan.json not found"}

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    found = False

    for atom_chain in ["preprocessing_atoms", "analysis_atoms", "output_atoms"]:
        for atom in plan.get(atom_chain, []):
            if atom.get("atom_id") == atom_id:
                atom["security_status"] = "trusted"
                atom["trusted_at"] = datetime.now(timezone.utc).isoformat()
                found = True
                break

    if found:
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        return {"atom_id": atom_id, "status": "trusted"}
    else:
        return {"error": f"Atom not found: {atom_id}"}


def check_package_integrity(package_path: str | Path) -> dict[str, Any]:
    """Check package integrity and required files."""
    package_path = Path(package_path)
    issues: list[str] = []

    if not package_path.exists():
        return {"valid": False, "issues": ["Package file does not exist"], "file_count": 0}

    required_files = ["plan.json", "execution_dag.json"]
    names: list[str] = []

    try:
        with zipfile.ZipFile(package_path, "r") as zf:
            names = zf.namelist()
            for req in required_files:
                if req not in names:
                    issues.append(f"Missing required file: {req}")
    except zipfile.BadZipFile:
        return {"valid": False, "issues": ["Corrupt zip file"], "file_count": 0}

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "file_count": len(names),
    }


def rerun_package(
    package_dir: str | Path,
    outdir: str | Path | None = None,
    participant_labels: list[str] | None = None,
    continue_on_failure: bool = True,
) -> dict[str, Any]:
    """Rerun an imported package after data relink.

    Validates that data_manifest.json has a valid local_root, then
    triggers ExecutionService to re-execute the analysis pipeline.

    Args:
        package_dir: Directory containing the imported package
        outdir: Output directory for results (defaults to package_dir)
        participant_labels: Filter by participant labels
        continue_on_failure: Continue processing if one run fails

    Returns:
        Dict with rerun results including attempt_id, run counts, and report paths

    Raises:
        FileNotFoundError: If package_dir or required files don't exist
        ValueError: If data_manifest.json is missing or local_root is invalid
    """
    from fnirs_flow.execution.service import ExecutionRequest, ExecutionService

    package_dir = Path(package_dir)
    outdir_path = Path(outdir) if outdir else package_dir

    # Validate package structure
    plan_path = package_dir / "plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(f"plan.json not found in {package_dir}")

    manifest_path = package_dir / "data_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"data_manifest.json not found in {package_dir}. "
            "Run import_package() with relink_data=True and data_root first."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    local_root = manifest.get("local_root", "")
    if not local_root or not Path(local_root).exists():
        raise ValueError(
            f"data_manifest.json local_root is invalid or missing: '{local_root}'. "
            "Relink data paths before rerunning."
        )

    # Check for quarantined atoms
    metadata_path = package_dir / "import_metadata.json"
    quarantined: list[str] = []
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        quarantined = metadata.get("quarantined_atoms", [])
        if quarantined:
            raise ValueError(
                f"Package has quarantined atoms: {quarantined}. "
                "Trust them via trust_atom() or fork_package(unfork=True) before rerunning."
            )

    # Execute via ExecutionService
    service = ExecutionService()
    request = ExecutionRequest(
        project_dir=str(package_dir),
        outdir=str(outdir_path),
        participant_labels=participant_labels or [],
        continue_on_failure=continue_on_failure,
    )
    result = service.execute(request)

    return {
        "attempt_id": result.attempt_id,
        "total_runs": result.total_runs,
        "successful_runs": result.successful_runs,
        "failed_runs": result.failed_runs,
        "skipped_runs": result.skipped_runs,
        "reports": result.reports,
        "failure_ids": result.failure_ids,
        "outdir": str(outdir_path),
    }
