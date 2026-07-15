"""Package verifier: validates .fnirsflow.zip packages for completeness and integrity."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field

from fnirs_flow.filesystem import is_macos_metadata_path

MAX_PACKAGE_BYTES = 10 * 1024**2
MAX_UNCOMPRESSED_BYTES = 10 * 1024**2
MAX_MEMBER_BYTES = 8 * 1024**2
MAX_PACKAGE_FILES = 5_000
MAX_COMPRESSION_RATIO = 1_000
MAX_MANIFEST_BYTES = 1024**2


class VerificationResult(BaseModel):
    """Result of package verification."""

    valid: bool = True
    profile: str = ""
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_files: list[str] = Field(default_factory=list)
    missing_files: list[str] = Field(default_factory=list)
    checksum_mismatches: list[str] = Field(default_factory=list)
    schema_version: str = ""


def verify_package(package_path: str | Path, expected_profile: str | None = None) -> VerificationResult:
    """Verify a .fnirsflow.zip package.

    Args:
        package_path: Path to the .fnirsflow.zip file
        expected_profile: Expected package profile (optional)

    Returns:
        VerificationResult with verification details
    """
    result = VerificationResult()
    package_path = Path(package_path)

    if not package_path.exists():
        result.valid = False
        result.errors.append(f"Package file not found: {package_path}")
        return result

    if package_path.suffix != ".zip":
        result.valid = False
        result.errors.append(f"Package must be a .zip file: {package_path}")
        return result

    if package_path.stat().st_size > MAX_PACKAGE_BYTES:
        result.valid = False
        result.errors.append("Package exceeds the 10 MiB size limit")
        return result

    try:
        with zipfile.ZipFile(package_path, "r") as zf:
            if not _validate_archive_bounds(zf, result):
                result.valid = False
                return result
            # Check for manifest (exact match for "manifest.json")
            manifest_path = None
            for name in zf.namelist():
                if name == "manifest.json":
                    manifest_path = name
                    break

            if manifest_path is None:
                result.valid = False
                result.errors.append("No manifest.json found in package")
                return result

            # Read and validate manifest
            try:
                manifest_info = zf.getinfo(manifest_path)
                if manifest_info.file_size > MAX_MANIFEST_BYTES:
                    result.valid = False
                    result.errors.append("manifest.json exceeds the 1 MiB size limit")
                    return result
                manifest_data = json.loads(zf.read(manifest_info))
            except json.JSONDecodeError as e:
                result.valid = False
                result.errors.append(f"Invalid manifest.json: {e}")
                return result

            # Check schema version
            result.schema_version = manifest_data.get("schema_version", "")
            if not result.schema_version:
                result.warnings.append("No schema_version in manifest")

            # Check profile
            profile = manifest_data.get("profile", "")
            result.profile = profile
            if expected_profile and profile != expected_profile:
                result.warnings.append(f"Profile mismatch: expected {expected_profile}, got {profile}")

            # Check required files based on profile
            required_files = _get_required_files(profile)
            manifest_files = manifest_data.get("files", {})

            for req_file in required_files:
                result.checked_files.append(req_file)
                if req_file not in manifest_files:
                    result.missing_files.append(req_file)

            # Verify checksums
            for file_path, file_info in manifest_files.items():
                if file_path in zf.namelist():
                    expected_checksum = file_info.get("sha256", "")
                    if expected_checksum:
                        actual_checksum = _compute_file_hash(zf, file_path)
                        if actual_checksum != expected_checksum:
                            result.checksum_mismatches.append(file_path)
                else:
                    if file_path in required_files:
                        # Already reported as missing
                        pass
                    else:
                        result.warnings.append(f"File in manifest but not in archive: {file_path}")

            # Check for unexpected files
            archive_files = set(zf.namelist())
            manifest_file_set = set(manifest_files.keys())
            unexpected = archive_files - manifest_file_set - {manifest_path}
            if unexpected:
                result.warnings.append(f"Unexpected files in archive: {unexpected}")

            # Update validity
            if result.missing_files or result.checksum_mismatches:
                result.valid = False

    except zipfile.BadZipFile:
        result.valid = False
        result.errors.append(f"Invalid zip file: {package_path}")
    except Exception as e:
        result.valid = False
        result.errors.append(f"Verification error: {e}")

    return result


def _get_required_files(profile: str) -> list[str]:
    """Get required files for a package profile."""
    # Base required files
    required = [
        "plan.json",
        "manifest.json",
    ]

    # Profile-specific requirements
    if profile == "reproducibility_package":
        required.extend([
            "execution_dag.json",
            "adapter_manifest.json",
            "risk_register.json",
            "reproducibility_manifest.json",
        ])
    elif profile == "reviewer_package":
        required.extend([
            "execution_dag.json",
            "adapter_manifest.json",
            "risk_register.json",
            "reproducibility_manifest.json",
        ])
    elif profile == "submission_package":
        required.extend([
            "risk_register.json",
        ])

    return required


def _is_safe_member_path(name: str) -> bool:
    if not name or "\\" in name or name.startswith(("/", "~/", "//")):
        return False
    if len(name) >= 3 and name[0].isalpha() and name[1:3] in {":/", ":\\"}:
        return False
    path = PurePosixPath(name.rstrip("/"))
    if is_macos_metadata_path(path):
        return False
    return (
        not path.is_absolute()
        and bool(path.parts)
        and not any(part in {"", ".", ".."} for part in path.parts)
    )


def _validate_archive_bounds(zf: zipfile.ZipFile, result: VerificationResult) -> bool:
    infos = zf.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        result.errors.append("Package contains duplicate paths")
        return False
    if len(names) > MAX_PACKAGE_FILES:
        result.errors.append("Package contains too many files")
        return False

    total_uncompressed = 0
    for info in infos:
        if not _is_safe_member_path(info.filename):
            result.errors.append(f"Unsafe zip entry: {info.filename}")
            return False
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            result.errors.append(f"Symbolic links are not allowed: {info.filename}")
            return False
        if info.is_dir():
            continue
        if info.file_size > MAX_MEMBER_BYTES:
            result.errors.append(f"Package member exceeds the 8 MiB size limit: {info.filename}")
            return False
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            result.errors.append("Package exceeds the 10 MiB extracted-size limit")
            return False
        if info.file_size and info.compress_size == 0:
            result.errors.append(f"Package member has an invalid compressed size: {info.filename}")
            return False
        if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            result.errors.append(f"Package member compression ratio is too high: {info.filename}")
            return False
    return True


def _compute_file_hash(zf: zipfile.ZipFile, file_path: str) -> str:
    """Compute SHA256 hash of a file in the zip archive."""
    try:
        digest = hashlib.sha256()
        with zf.open(file_path) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return ""


def verify_and_print(package_path: str | Path, expected_profile: str | None = None) -> int:
    """Verify a package and print results. Returns 0 if valid, 1 otherwise."""
    result = verify_package(package_path, expected_profile)

    print(f"Package Verification: {'PASS' if result.valid else 'FAIL'}")
    print("=" * 60)

    if result.profile:
        print(f"Profile: {result.profile}")
    if result.schema_version:
        print(f"Schema Version: {result.schema_version}")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors:
            print(f"  ✗ {error}")

    if result.missing_files:
        print(f"\nMissing Files ({len(result.missing_files)}):")
        for f in result.missing_files:
            print(f"  ✗ {f}")

    if result.checksum_mismatches:
        print(f"\nChecksum Mismatches ({len(result.checksum_mismatches)}):")
        for f in result.checksum_mismatches:
            print(f"  ✗ {f}")

    if result.warnings:
        print(f"\nWarnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"  ⚠ {w}")

    if result.checked_files:
        print(f"\nChecked Files: {len(result.checked_files)}")

    return 0 if result.valid else 1
