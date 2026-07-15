"""Lightweight capability probing for backends.

This module provides probing functions that check backend capabilities
WITHOUT importing the actual backend modules. It uses:
  - importlib.util.find_spec() for module existence
  - importlib.metadata for version info
  - Subprocess isolation for deeper probes (future)
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import logging
from typing import Any

logger = logging.getLogger(__name__)


def probe_package_availability(distribution: str, import_name: str) -> dict[str, Any]:
    """Probe if a package is available without importing it.

    Returns:
        Dictionary with:
        - installed: bool
        - version: str or None
        - importable: bool
        - error: str or None
    """
    result: dict[str, Any] = {
        "installed": False,
        "version": None,
        "importable": False,
        "error": None,
    }

    # Check if distribution is installed
    try:
        version = importlib.metadata.version(distribution)
        result["installed"] = True
        result["version"] = version
    except importlib.metadata.PackageNotFoundError:
        result["error"] = f"Package '{distribution}' not found"
        return result

    # Check if import entry point exists
    spec = importlib.util.find_spec(import_name)
    if spec is not None:
        result["importable"] = True
    else:
        result["error"] = f"Import '{import_name}' not found"

    return result


def probe_cedalion_capabilities() -> dict[str, Any]:
    """Probe Cedalion capabilities WITHOUT importing cedalion.

    Uses importlib.util.find_spec() to check for submodules.
    This is safe and does not trigger any cedalion initialization.
    """
    capabilities: dict[str, bool] = {}
    probe_details: dict[str, Any] = {
        "installed": False,
        "version": None,
        "capabilities": capabilities,
        "errors": [],
    }

    # First check if cedalion is installed
    try:
        version = importlib.metadata.version("cedalion")
        probe_details["installed"] = True
        probe_details["version"] = version
    except importlib.metadata.PackageNotFoundError:
        probe_details["errors"].append("Cedalion package not installed")
        return probe_details

    # Probe specific capabilities using find_spec
    capability_checks = {
        "snirf_read": "cedalion.io",
        "int2od": "cedalion.nirs.cw",
        "od2conc": "cedalion.nirs.cw",
        "glm": "cedalion.models.glm",
        "dot": "cedalion.dot",
        "signal_decomposition": "cedalion.sigdecomp",
        "extinction_coefficients": "cedalion.nirs.cw",
        "channel_distances": "cedalion.nirs.cw",
        "glm_basis_functions": "cedalion.models.glm",
        "glm_design_matrix": "cedalion.models.glm",
        "glm_fit_with_uncertainty": "cedalion.models.glm",
        "dot_head_model": "cedalion.dot",
        "dot_forward_model": "cedalion.dot",
        "dot_image_recon": "cedalion.dot",
        "dot_tissue_properties": "cedalion.dot",
        "spoc_decomposition": "cedalion.sigdecomp",
        "ica_signal_decomposition": "cedalion.sigdecomp",
        "multimodal_signal_decomposition": "cedalion.sigdecomp",
        "synthetic_hrf_generation": "cedalion.sim",
        "synthetic_artifact_generation": "cedalion.sim",
        "epoch_feature_extraction": "cedalion.mlutils",
        "psp_quality_metric": "cedalion.sigproc.quality",
        "motion_correction_spline": "cedalion.sigproc.motion",
        "photogrammetry_coregistration": "cedalion.geometry",
    }

    for capability, module_path in capability_checks.items():
        spec = importlib.util.find_spec(module_path)
        capabilities[capability] = spec is not None

    return probe_details


def probe_mne_nirs_capabilities() -> dict[str, Any]:
    """Probe MNE-NIRS capabilities WITHOUT importing mne.

    Uses importlib.util.find_spec() to check for submodules.
    """
    capabilities: dict[str, bool] = {}
    probe_details: dict[str, Any] = {
        "installed": False,
        "version": None,
        "mne_version": None,
        "capabilities": capabilities,
        "errors": [],
    }

    # Check MNE
    try:
        mne_version = importlib.metadata.version("mne")
        probe_details["mne_version"] = mne_version
    except importlib.metadata.PackageNotFoundError:
        probe_details["errors"].append("MNE package not installed")
        return probe_details

    # Check MNE-NIRS
    try:
        version = importlib.metadata.version("mne-nirs")
        probe_details["installed"] = True
        probe_details["version"] = version
    except importlib.metadata.PackageNotFoundError:
        probe_details["errors"].append("MNE-NIRS package not installed")
        return probe_details

    # Probe capabilities
    capability_checks = {
        "snirf_read": "mne.io",
        "optical_density": "mne_nirs",
        "beer_lambert_law": "mne_nirs",
        "filtering": "mne.filter",
        "motion_correction": "mne.preprocessing",
        "block_averaging": "mne.epochs",
        "glm": "mne_nirs.statistics",
    }

    for capability, module_path in capability_checks.items():
        spec = importlib.util.find_spec(module_path)
        capabilities[capability] = spec is not None

    return probe_details


def probe_backend(backend_id: str) -> dict[str, Any]:
    """Probe a backend's capabilities.

    Args:
        backend_id: The backend identifier

    Returns:
        Probe results dictionary
    """
    if backend_id == "cedalion":
        return probe_cedalion_capabilities()
    elif backend_id == "mne_nirs":
        return probe_mne_nirs_capabilities()
    else:
        return {
            "installed": False,
            "version": None,
            "capabilities": {},
            "errors": [f"Unknown backend: {backend_id}"],
        }
