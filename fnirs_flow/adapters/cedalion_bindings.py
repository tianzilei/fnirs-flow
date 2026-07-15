"""Explicit execution bindings for Cedalion-derived MethodAtoms.

These bindings describe which Cedalion adapter operation implements a
MethodAtom.  They do not imply that the operation has passed a real-data
contract test.  Verification status is tracked separately so catalogued
capabilities cannot silently become executable merely because their source
row mentions Cedalion.
"""

from __future__ import annotations

from typing import Final

CEDALION_METHOD_ATOM_BINDINGS: Final[dict[str, str]] = {
    "ATOM_dot_head_model": "create_head_model",
    "ATOM_dot_forward_model": "run_forward_model",
    "ATOM_dot_image_recon": "reconstruct_image",
    "ATOM_dot_tissue_properties": "get_tissue_properties",
    "ATOM_photogrammetry_coregistration": "photogrammetry_coregistration",
    "ATOM_spoc_decomposition": "spoc_decomposition",
    "ATOM_ica_signal_decomposition": "ica_decomposition",
    "ATOM_multimodal_signal_decomposition": "multimodal_decomposition",
    "ATOM_synthetic_hrf_generation": "generate_synthetic_hrf",
    "ATOM_synthetic_artifact_generation": "generate_synthetic_artifacts",
    "ATOM_epoch_feature_extraction": "extract_epoch_features",
    "ATOM_glm_basis_functions": "create_glm_basis_function",
    "ATOM_glm_design_matrix": "create_glm_design_matrix",
    "ATOM_glm_fit_with_uncertainty": "fit_glm",
    "ATOM_psp_quality_metric": "compute_psp",
    "ATOM_channel_distance_computation": "compute_channel_distances",
    "ATOM_extinction_coefficients": "get_extinction_coefficients",
}


# Promote an atom into this set only after its wrapper has been exercised
# against the pinned Cedalion release with representative real inputs.
VERIFIED_CEDALION_METHOD_ATOMS: Final[frozenset[str]] = frozenset(
    {
        "ATOM_channel_distance_computation",
        "ATOM_extinction_coefficients",
    }
)


def get_cedalion_binding(atom_id: str) -> str | None:
    """Return the Cedalion adapter operation explicitly bound to ``atom_id``."""
    return CEDALION_METHOD_ATOM_BINDINGS.get(atom_id)


def is_verified_cedalion_atom(atom_id: str) -> bool:
    """Return whether a Cedalion MethodAtom passed a real contract test."""
    return atom_id in VERIFIED_CEDALION_METHOD_ATOMS
