"""Package importer: imports .fnirsflow.zip packages."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from fnirs_flow.infrastructure.filesystem import (
    is_macos_metadata_path,
    macos_metadata_ignore,
    remove_macos_metadata_paths,
)
from fnirs_flow.infrastructure.portability import (
    find_archive_absolute_path_records,
    format_archive_portability_error,
)
from fnirs_flow.infrastructure.uri import ProjectURI, URIBindingStore, create_external_data_uri

MAX_PACKAGE_BYTES = 10 * 1024**2
MAX_UNCOMPRESSED_BYTES = 10 * 1024**2
MAX_MEMBER_BYTES = 8 * 1024**2
MAX_PACKAGE_FILES = 5_000
MAX_COMPRESSION_RATIO = 1_000
MAX_MANIFEST_BYTES = 1024**2


def _relative_data_path(value: str, old_root: Path | None = None) -> str:
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


def _relink_manifest(manifest: dict[str, Any], data_root: Path) -> dict[str, Any]:
    """Bind portable data URIs to a local root without replacing stable identifiers."""
    root = data_root.resolve()
    if not root.is_dir():
        raise ValueError(f"Data root does not exist or is not a directory: {root}")
    old_root_text = str(manifest.get("local_root", ""))
    old_root = Path(old_root_text) if old_root_text else None
    dataset_id = str(manifest.get("dataset_id") or "dataset")
    missing_paths = []
    for run in manifest.get("subject_session_runs", []):
        relative_text = str(run.get("relative_path", ""))
        if not relative_text:
            relative_text = _relative_data_path(str(run.get("uri") or run.get("path", "")), old_root)
        if relative_text:
            run_path = root / relative_text
            run_uri = str(create_external_data_uri(dataset_id, relative_text))
            run["relative_path"] = relative_text
            run["path"] = run_uri
            run["uri"] = run_uri
            if not run_path.exists():
                missing_paths.append(str(run_path))

        events_text = str(run.get("events_uri") or run.get("events_path", ""))
        events_relative = _relative_data_path(events_text, old_root)
        if not events_relative and relative_text.endswith("_nirs.snirf"):
            events_relative = relative_text.removesuffix("_nirs.snirf") + "_events.tsv"
        if events_relative:
            events_path = root / events_relative
            events_uri = str(create_external_data_uri(dataset_id, events_relative))
            run["events_path"] = events_uri if events_path.exists() else ""
            run["events_uri"] = events_uri

    for item in manifest.get("files", []):
        relative = _relative_data_path(str(item.get("uri") or item.get("path", "")), old_root)
        if relative:
            uri = str(create_external_data_uri(dataset_id, relative))
            item["path"] = uri
            item["uri"] = uri

    for table in manifest.get("metadata_tables", []):
        relative = _relative_data_path(str(table.get("uri") or table.get("path", "")), old_root)
        if relative:
            uri = str(create_external_data_uri(dataset_id, relative))
            table["path"] = uri
            table["uri"] = uri

    manifest["local_root"] = ""
    manifest["external_data_uri_prefix"] = f"external-data://{dataset_id}/"
    manifest["requires_data_binding"] = False
    return {"data_root": str(root), "missing_paths": missing_paths}


def _write_uri_binding(package_dir: Path, dataset_id: str, data_root: Path) -> None:
    """Persist a local-only binding for imported package reruns."""
    URIBindingStore(package_dir).bind(dataset_id, data_root)


def relink_package_data(
    package_dir: str | Path,
    data_root: str | Path,
    *,
    persist_binding: bool = True,
) -> dict[str, Any]:
    """Relink an imported package in root or project/compiled layout."""
    package_dir = Path(package_dir)
    manifest_path = package_dir / "data_manifest.json"
    if not manifest_path.exists():
        manifest_path = package_dir / "compiled" / "data_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"data_manifest.json not found in {package_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = _relink_manifest(manifest, Path(data_root))
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if persist_binding:
        _write_uri_binding(package_dir, str(manifest.get("dataset_id") or "dataset"), Path(data_root))
    metadata_path = package_dir / "import_metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["relinked"] = True
        metadata["dataset_id"] = str(manifest.get("dataset_id") or "dataset")
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return {**result, "manifest_path": str(manifest_path)}


def _validate_zip_path(member: str, outdir: Path) -> bool:
    """Check that a zip member path doesn't escape the output directory."""
    try:
        if not member or "\\" in member or member.startswith(("/", "~/", "//")):
            return False
        if len(member) >= 3 and member[0].isalpha() and member[1:3] in {":/", ":\\"}:
            return False
        path = PurePosixPath(member.rstrip("/"))
        if is_macos_metadata_path(path):
            return False
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            return False
        target = (outdir / member).resolve()
        return target.is_relative_to(outdir.resolve())
    except (ValueError, OSError):
        return False


def _hash_zip_member(zf: zipfile.ZipFile, member: str) -> str:
    digest = hashlib.sha256()
    with zf.open(member) as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_declared_manifest(zf: zipfile.ZipFile, names: set[str]) -> None:
    if "manifest.json" not in names:
        return
    manifest_info = zf.getinfo("manifest.json")
    if manifest_info.file_size > MAX_MANIFEST_BYTES:
        raise ValueError("manifest.json exceeds the 1 MiB size limit")
    try:
        manifest = json.loads(zf.read(manifest_info))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid manifest.json: {exc}") from exc
    declared = manifest.get("files", {})
    if not isinstance(declared, dict):
        raise ValueError("manifest.json files field must be an object")
    for member, details in declared.items():
        if member == "manifest.json":
            continue
        if member not in names:
            raise ValueError(f"Manifest declares missing file: {member}")
        if not isinstance(details, dict):
            raise ValueError(f"Manifest entry for {member} must be an object")
        expected = str(details.get("sha256", ""))
        if expected and _hash_zip_member(zf, member) != expected:
            raise ValueError(f"Checksum mismatch for {member}")


def _validate_zip_for_import(package_path: Path, zf: zipfile.ZipFile, extract_dir: Path) -> list[zipfile.ZipInfo]:
    if package_path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ValueError("Package exceeds the 10 MiB size limit")
    infos = zf.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise ValueError("Package contains duplicate paths")
    if len(names) > MAX_PACKAGE_FILES:
        raise ValueError("Package contains too many files")

    total_uncompressed = 0
    file_infos: list[zipfile.ZipInfo] = []
    for info in infos:
        member = info.filename
        if member.endswith("/"):
            if not _validate_zip_path(member.rstrip("/"), extract_dir):
                raise ValueError(f"Unsafe zip entry: {member}")
            continue
        if not _validate_zip_path(member, extract_dir):
            raise ValueError(f"Unsafe zip entry: {member}")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symbolic links are not allowed in packages: {member}")
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError(f"Package member exceeds the 8 MiB size limit: {member}")
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Package exceeds the 10 MiB extracted-size limit")
        if info.file_size and info.compress_size == 0:
            raise ValueError(f"Package member has an invalid compressed size: {member}")
        if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            raise ValueError(f"Package member compression ratio is too high: {member}")
        file_infos.append(info)

    path_findings = find_archive_absolute_path_records(zf)
    if path_findings:
        raise ValueError(format_archive_portability_error(path_findings))

    _verify_declared_manifest(zf, set(names))
    return file_infos


def _extract_validated_members(zf: zipfile.ZipFile, infos: list[zipfile.ZipInfo], extract_dir: Path) -> list[str]:
    extracted: list[str] = []
    for info in infos:
        target = (extract_dir / info.filename).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)
        extracted.append(info.filename)
    return extracted


def import_package(
    package_path: str | Path,
    outdir: str | Path,
    relink_data: bool = False,
    data_root: str | Path | None = None,
    project_layout: bool = False,
    persist_binding: bool = True,
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
    extract_dir = outdir / "compiled" if project_layout else outdir
    extract_dir.mkdir(parents=True, exist_ok=True)

    extracted_files: list[str] = []

    with zipfile.ZipFile(package_path, "r") as zf:
        file_infos = _validate_zip_for_import(package_path, zf, extract_dir)
        extracted_files = _extract_validated_members(zf, file_infos, extract_dir)

    manifest_path = extract_dir / "data_manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {"dataset_id": "dataset"}
    )

    # Relink data if requested
    relinked = False
    if relink_data and data_root is not None:
        if manifest_path.exists():
            _relink_manifest(manifest, Path(data_root))
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            if persist_binding:
                _write_uri_binding(outdir, str(manifest.get("dataset_id") or "dataset"), Path(data_root))
            relinked = True

    # Mark imported flow as read-only and quarantine custom atoms
    import_metadata: dict[str, Any] = {
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "source_package": package_path.name,
        "source_package_sha256": hashlib.sha256(package_path.read_bytes()).hexdigest(),
        "read_only": True,
        "quarantined_atoms": [],
        "relinked": relinked,
        "dataset_id": str(manifest.get("dataset_id") or "dataset"),
    }

    # Check for custom atoms in plan.json and mark them as quarantined
    plan_path = extract_dir / "plan.json"
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
    remove_macos_metadata_paths(outdir)

    return {
        "extracted_files": extracted_files,
        "relinked": relinked,
        "read_only": True,
        "quarantined_atoms": import_metadata["quarantined_atoms"],
        "package_path": str(package_path),
        "output_dir": str(outdir),
        "compiled_dir": str(extract_dir),
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
        unfork: If True, remove the read-only editing restriction. Quarantine
            decisions remain intact and require explicit per-atom trust.

    Returns:
        Dict with fork results
    """
    import shutil

    package_dir = Path(package_dir)
    fork_dir = Path(fork_dir)

    if fork_dir.exists():
        raise ValueError(f"Fork directory already exists: {fork_dir}")

    # Copy the package without Finder/AppleDouble metadata sidecars.
    shutil.copytree(package_dir, fork_dir, ignore=macos_metadata_ignore)

    # Update import metadata
    metadata_path = fork_dir / "import_metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if unfork:
            metadata["read_only"] = False
            metadata["forked_at"] = datetime.now(timezone.utc).isoformat()
            # Forking makes the project editable but does not implicitly trust code.
            plan_path = fork_dir / "compiled" / "plan.json"
            if not plan_path.exists():
                plan_path = fork_dir / "plan.json"
            if plan_path.exists():
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                for atom_chain in ["preprocessing_atoms", "analysis_atoms", "output_atoms"]:
                    for atom in plan.get(atom_chain, []):
                        if atom.get("atom_id") not in metadata.get("quarantined_atoms", []):
                            atom.pop("security_status", None)
                plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        else:
            metadata["forked_at"] = datetime.now(timezone.utc).isoformat()
            metadata["read_only"] = True
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    remove_macos_metadata_paths(fork_dir)

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
    plan_path = project_dir / "compiled" / "plan.json"
    if not plan_path.exists():
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
        metadata_path = project_dir / "import_metadata.json"
        if not metadata_path.exists() and project_dir.name == "compiled":
            metadata_path = project_dir.parent / "import_metadata.json"
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["quarantined_atoms"] = [item for item in metadata.get("quarantined_atoms", []) if item != atom_id]
            metadata.setdefault("trust_decisions", []).append(
                {
                    "atom_id": atom_id,
                    "decision": "trusted",
                    "trusted_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
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
    task_labels: list[str] | None = None,
    run_labels: list[str] | None = None,
    continue_on_failure: bool = True,
) -> dict[str, Any]:
    """Rerun an imported package after data relink.

    Validates that data_manifest.json can be resolved through either the legacy
    local_root field or a local uri_bindings.json entry, then triggers
    ExecutionService to re-execute the analysis pipeline.

    Args:
        package_dir: Directory containing the imported package
        outdir: Output directory for results (defaults to package_dir)
        participant_labels: Filter by participant labels
        task_labels: Filter by task labels
        run_labels: Filter by run labels
        continue_on_failure: Continue processing if one run fails

    Returns:
        Dict with rerun results including attempt_id, run counts, and report paths

    Raises:
        FileNotFoundError: If package_dir or required files don't exist
        ValueError: If data_manifest.json is missing or no valid data binding exists
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
    local_root = str(manifest.get("local_root", "") or "")
    data_root = Path(local_root) if local_root else None
    if data_root is None or not data_root.exists():
        dataset_id = str(manifest.get("dataset_id") or "dataset")
        data_root = URIBindingStore(package_dir).get_binding(dataset_id)

    if data_root is None or not data_root.exists():
        raise ValueError(
            "data_manifest.json has no valid local_root or external-data binding. "
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
        task_labels=task_labels or [],
        run_labels=run_labels or [],
        data_root=str(data_root),
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
