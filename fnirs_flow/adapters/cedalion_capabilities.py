"""Cedalion capability detection and version checking."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def detect_cedalion() -> dict[str, Any]:
    """Detect Cedalion installation and capabilities.

    Returns:
        Dictionary with:
        - installed: bool
        - version: str (if installed)
        - compatible: bool
        - supported_operations: list[str]
        - limitations: list[str]
    """
    limitations: list[str] = []
    supported_operations: list[str] = []
    result: dict[str, Any] = {
        "installed": False,
        "version": "",
        "compatible": False,
        "supported_operations": supported_operations,
        "limitations": limitations,
    }

    try:
        import cedalion
        result["installed"] = True
        version_str: str = str(getattr(cedalion, "__version__", "unknown"))
        result["version"] = version_str

        # Check version compatibility
        if version_str and version_str != "unknown":
            # Parse version - expected format: YYYY.M.D or similar
            try:
                parts = version_str.split(".")
                if len(parts) >= 2:
                    release = int(parts[0])
                    month = int(parts[1]) if len(parts) > 1 else 0

                    # Cedalion uses YY.M.PATCH calendar versions (for example 26.5.1).
                    if release > 26 or (release == 26 and month >= 5):
                        result["compatible"] = True
                    else:
                        limitations.append(f"Version {version_str} may not be fully compatible")
            except (ValueError, IndexError):
                limitations.append(f"Cannot parse version: {version_str}")

        # Check supported operations
        result["supported_operations"] = _detect_supported_operations()

    except ImportError:
        limitations.append("Cedalion not installed")
    except Exception as e:
        limitations.append(f"Error detecting Cedalion: {e}")

    return result


def _detect_supported_operations() -> list[str]:
    """Detect which operations Cedalion supports."""
    import importlib.util

    operations = []

    # Check for SNIRF reading
    if importlib.util.find_spec("cedalion.io") is not None:
        operations.append("snirf_read")

    # Check for intensity to OD conversion
    if importlib.util.find_spec("cedalion.nirs.cw") is not None:
        operations.append("int2od")
        operations.append("od2conc")
        operations.append("extinction_coefficients")
        operations.append("channel_distances")

    # Check for GLM
    if importlib.util.find_spec("cedalion.models.glm") is not None:
        operations.append("glm")
        operations.append("glm_basis_functions")
        operations.append("glm_design_matrix")
        operations.append("glm_fit_with_uncertainty")

    # Check for DOT
    if importlib.util.find_spec("cedalion.dot") is not None:
        operations.append("dot")
        operations.append("dot_head_model")
        operations.append("dot_forward_model")
        operations.append("dot_image_recon")
        operations.append("dot_tissue_properties")

    # Check for signal decomposition
    if importlib.util.find_spec("cedalion.sigdecomp") is not None:
        operations.append("spoc_decomposition")
        operations.append("ica_signal_decomposition")
        operations.append("multimodal_signal_decomposition")

    # Check for synthetic data
    if importlib.util.find_spec("cedalion.sim") is not None:
        operations.append("synthetic_hrf_generation")
        operations.append("synthetic_artifact_generation")

    # Check for ML utilities
    if importlib.util.find_spec("cedalion.mlutils") is not None:
        operations.append("epoch_feature_extraction")

    # Check for quality control
    if importlib.util.find_spec("cedalion.sigproc.quality") is not None:
        operations.append("psp_quality_metric")

    # Check for motion correction
    if importlib.util.find_spec("cedalion.sigproc.motion") is not None:
        operations.append("motion_correction_spline")

    # Check for geometry
    if importlib.util.find_spec("cedalion.geometry") is not None:
        operations.append("photogrammetry_coregistration")

    return operations


def get_cedalion_info() -> dict[str, Any]:
    """Get detailed Cedalion information for diagnostics."""
    info = detect_cedalion()

    if info["installed"]:
        try:
            import cedalion
            info["python_package"] = cedalion.__name__
            info["python_file"] = getattr(cedalion, "__file__", "")
        except (ImportError, AttributeError) as e:
            logger.debug("Could not get Cedalion package info: %s", e)

    return info
