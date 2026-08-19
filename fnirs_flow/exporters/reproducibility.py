"""Enhanced reproducibility: environment, config snapshot, processing logs."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def capture_environment() -> dict[str, Any]:
    """Capture current Python environment for reproducibility.

    Returns:
        Dict with environment details
    """
    env: dict[str, Any] = {
        "python_version": sys.version,
        "platform": sys.platform,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Capture installed packages
    try:
        import importlib.metadata

        packages = {}
        for dist in importlib.metadata.distributions():
            name = dist.metadata["Name"]
            version = dist.metadata["Version"]
            packages[name.lower()] = version
        env["packages"] = packages
    except (OSError, importlib.metadata.PackageNotFoundError, TypeError):
        env["packages"] = {}

    # Capture MNE versions
    try:
        import mne

        env["mne_version"] = mne.__version__
    except ImportError:
        env["mne_version"] = "not installed"

    try:
        import mne_nirs

        env["mne_nirs_version"] = getattr(mne_nirs, "__version__", "unknown")
    except ImportError:
        env["mne_nirs_version"] = "not installed"

    return env


def create_config_snapshot(
    flow_dict: dict[str, Any],
    plan_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a configuration snapshot for reproducibility.

    Args:
        flow_dict: Flow configuration
        plan_dict: Optional compiled plan

    Returns:
        Config snapshot dict
    """
    snapshot: dict[str, Any] = {
        "flow": flow_dict,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if plan_dict:
        snapshot["plan"] = plan_dict

    return snapshot


def generate_reproducibility_manifest(
    flow_dict: dict[str, Any],
    plan_dict: dict[str, Any] | None = None,
    processing_log: list[dict[str, Any]] | None = None,
    outdir: Path | None = None,
) -> dict[str, Any]:
    """Generate complete reproducibility manifest.

    Args:
        flow_dict: Flow configuration
        plan_dict: Optional compiled plan
        processing_log: Optional processing log entries
        outdir: Output directory for writing files

    Returns:
        Reproducibility manifest dict
    """
    manifest: dict[str, Any] = {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": capture_environment(),
        "config_snapshot": create_config_snapshot(flow_dict, plan_dict),
        "processing_log": processing_log or [],
    }

    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)

        # Write manifest
        manifest_path = outdir / "reproducibility_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # Write environment.yml equivalent
        env_path = outdir / "environment.json"
        env_path.write_text(json.dumps(manifest["environment"], indent=2), encoding="utf-8")

        # Write config snapshot
        config_path = outdir / "config_snapshot.json"
        config_path.write_text(json.dumps(manifest["config_snapshot"], indent=2), encoding="utf-8")

        # Generate requirements.txt equivalent
        req_path = outdir / "requirements.txt"
        packages = manifest["environment"].get("packages", {})
        req_lines = [f"{name}=={version}" for name, version in sorted(packages.items())]
        req_path.write_text("\n".join(req_lines), encoding="utf-8")

    return manifest


def write_reproducibility_package(
    flow_dict: dict[str, Any],
    plan_dict: dict[str, Any],
    outdir: Path,
    include_logs: list[dict[str, Any]] | None = None,
) -> Path:
    """Write complete reproducibility package.

    Args:
        flow_dict: Flow configuration
        plan_dict: Compiled plan
        outdir: Output directory
        include_logs: Processing logs to include

    Returns:
        Path to the reproducibility manifest
    """
    generate_reproducibility_manifest(
        flow_dict=flow_dict,
        plan_dict=plan_dict,
        processing_log=include_logs,
        outdir=outdir,
    )

    return outdir / "reproducibility_manifest.json"
