"""Homer3 export adapter: converts fnirs-flow preprocessing chains to Homer3 process config.

This adapter does NOT run Homer3. It exports the fnirs-flow pipeline
as a Homer3-compatible process configuration for external reproducibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Homer3ProcessStep(BaseModel):
    """A single step in a Homer3 process stream."""

    name: str
    func: str
    params: dict[str, Any] = Field(default_factory=dict)


class Homer3ProcessConfig(BaseModel):
    """Homer3 process stream configuration."""

    process_type: str = "preprocessing"
    steps: list[Homer3ProcessStep] = Field(default_factory=list)
    unmapped_atoms: list[str] = Field(default_factory=list)


# Mapping from fnirs-flow atom_type to Homer3 function name
ATOM_TO_HOMER3: dict[str, dict[str, Any]] = {
    "optical_density": {
        "func": "hmrR_Intensity2OD",
        "params": {},
    },
    "bandpass_filter": {
        "func": "hmrR_BandpassFilt",
        "params": {"lpf": 0.5, "hpf": 0.01, "Order": 2},
    },
    "notch_filter": {
        "func": "hmrR_BandpassFilt",
        "params": {"lpf": -1, "hpf": -1, "Order": 2},
    },
    "tddr_motion": {
        "func": "hmrR_MotionCorrectTD",
        "params": {},
    },
    "wavelet_motion_correction": {
        "func": "hmrR_MotionCorrectWavelet",
        "params": {"iqr": 1.5},
    },
    "spline_motion_correction": {
        "func": "hmrR_MotionCorrectSpline",
        "params": {"p": 0.99, "FrameSize": 10, "Weight": 5},
    },
    "pca_motion_correction": {
        "func": "hmrR_MotionCorrectPCA",
        "params": {"SVDCut": 1.0},
    },
    "ica_motion_correction": {
        # ICA is not a standard Homer3 function - will be unmapped
        "func": None,
        "params": {},
    },
    "cbsi_motion_correction": {
        "func": "hmrR_MotionCorrectCBSI",
        "params": {"alpha": 0.7},
    },
    "beer_lambert_law": {
        "func": "hmrR_OD2Conc",
        "params": {"DPF": [6, 6]},
    },
    "scalp_coupling_index": {
        "func": "hmrR_Sci",
        "params": {"sciThresh": 0.8},
    },
    "short_channel_regression": {
        "func": "hmrR_StatAvg",
        "params": {},
    },
    "block_averaging": {
        "func": "hmrR_BlockAvg",
        "params": {"tRange": [-5, 20]},
    },
}


def convert_flow_to_homer3(
    flow_atoms: list[dict[str, Any]],
) -> Homer3ProcessConfig:
    """Convert a list of fnirs-flow atoms to a Homer3 process config.

    Args:
        flow_atoms: List of atom dicts with 'atom_type' or 'type' field

    Returns:
        Homer3ProcessConfig with mapped steps and unmapped atoms
    """
    config = Homer3ProcessConfig()

    for atom in flow_atoms:
        atom_type = atom.get("atom_type") or atom.get("type", "")
        params = atom.get("config", {}).get("parameters", {})

        mapping = ATOM_TO_HOMER3.get(atom_type)
        if mapping is None or mapping["func"] is None:
            config.unmapped_atoms.append(atom_type)
            continue

        homer3_step = Homer3ProcessStep(
            name=atom_type,
            func=mapping["func"],
            params={**mapping["params"], **params},
        )
        config.steps.append(homer3_step)

    return config


def write_homer3_config(
    config: Homer3ProcessConfig,
    outdir: Path,
) -> Path:
    """Write Homer3 process config to JSON file."""
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "homer3_process_config.json"
    path.write_text(json.dumps(config.model_dump(), indent=2), encoding="utf-8")
    return path


def write_homer3_mapping_report(
    config: Homer3ProcessConfig,
    outdir: Path,
) -> Path:
    """Write a mapping report showing which atoms could/couldn't be mapped."""
    lines = [
        "# Homer3 Mapping Report",
        "",
        f"**Total atoms:** {len(config.steps) + len(config.unmapped_atoms)}",
        f"**Mapped:** {len(config.steps)}",
        f"**Unmapped:** {len(config.unmapped_atoms)}",
        "",
    ]

    if config.steps:
        lines.append("## Mapped Steps")
        lines.append("")
        lines.append("| Atom Type | Homer3 Function |")
        lines.append("|-----------|----------------|")
        for step in config.steps:
            lines.append(f"| {step.name} | `{step.func}` |")
        lines.append("")

    if config.unmapped_atoms:
        lines.append("## Unmapped Atoms")
        lines.append("")
        lines.append("These atoms have no Homer3 equivalent and would need manual implementation:")
        lines.append("")
        for atom in config.unmapped_atoms:
            lines.append(f"- `{atom}`")
        lines.append("")

    path = outdir / "homer3_mapping_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
