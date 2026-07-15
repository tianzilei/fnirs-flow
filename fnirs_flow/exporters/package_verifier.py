"""Package verifier: validates .fnirsflow.zip packages for completeness and integrity."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from pydantic import BaseModel, Field


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

    try:
        with zipfile.ZipFile(package_path, "r") as zf:
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
                manifest_data = json.loads(zf.read(manifest_path))
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


def _compute_file_hash(zf: zipfile.ZipFile, file_path: str) -> str:
    """Compute SHA256 hash of a file in the zip archive."""
    try:
        data = zf.read(file_path)
        return hashlib.sha256(data).hexdigest()
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
