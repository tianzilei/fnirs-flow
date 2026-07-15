"""AnalyzIR export adapter: converts fnirs-flow preprocessing chains to AnalyzIR R script.

AnalyzIR (https://github.com/huppertt/nirs-toolbox) is an R/MATLAB toolbox for fNIRS analysis.
This adapter generates an R script using the AnalyzIR-compatible function calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class AnalyzIRStep(BaseModel):
    """A single step in an AnalyzIR processing pipeline."""

    name: str
    func: str
    params: dict[str, Any] = Field(default_factory=dict)
    r_comment: str = ""


class AnalyzIRScript(BaseModel):
    """An AnalyzIR R script."""

    steps: list[AnalyzIRStep] = Field(default_factory=list)
    unmapped_atoms: list[str] = Field(default_factory=list)
    data_load_cmd: str = ""
    output_cmds: list[str] = Field(default_factory=list)


# Mapping from fnirs-flow atom_type to AnalyzIR R function
ATOM_TO_ANALYZIR: dict[str, dict[str, Any]] = {
    "optical_density": {
        "func": "hmrR_Intensity2OD",
        "params": {},
        "comment": "Convert intensity to optical density",
    },
    "bandpass_filter": {
        "func": "hmrR_BandpassFilt",
        "params": {},
        "comment": "Bandpass filter",
        "param_mapper": "_r_bandpass_params",
    },
    "notch_filter": {
        "func": "hmrR_BandpassFilt",
        "params": {"lpf": -1, "hpf": -1},
        "comment": "Notch filter (via bandpass with -1 flags)",
    },
    "tddr_motion": {
        "func": "hmrR_MotionCorrectTD",
        "params": {},
        "comment": "TDDR motion correction",
    },
    "wavelet_motion_correction": {
        "func": "hmrR_MotionCorrectWavelet",
        "params": {"iqr": 1.5},
        "comment": "Wavelet motion correction",
        "param_mapper": "_r_wavelet_params",
    },
    "spline_motion_correction": {
        "func": "hmrR_MotionCorrectSpline",
        "params": {"p": 0.99, "FrameSize": 10, "Weight": 5},
        "comment": "Spline interpolation motion correction",
        "param_mapper": "_r_spline_params",
    },
    "pca_motion_correction": {
        "func": "hmrR_MotionCorrectPCA",
        "params": {"SVDCut": 1.0},
        "comment": "PCA motion correction",
        "param_mapper": "_r_pca_params",
    },
    "cbsi_motion_correction": {
        "func": "hmrR_MotionCorrectCBSI",
        "params": {"alpha": 0.7},
        "comment": "CBSI motion correction",
        "param_mapper": "_r_cbsi_params",
    },
    "ica_motion_correction": {
        "func": None,
        "params": {},
        "comment": "ICA not available in AnalyzIR",
    },
    "beer_lambert_law": {
        "func": "hmrR_OD2Conc",
        "params": {"DPF": [6, 6]},
        "comment": "Beer-Lambert law conversion",
        "param_mapper": "_r_bll_params",
    },
    "scalp_coupling_index": {
        "func": "hmrR_Sci",
        "params": {"sciThresh": 0.8},
        "comment": "Scalp Coupling Index QC",
        "param_mapper": "_r_sci_params",
    },
    "short_channel_regression": {
        "func": "hmrR_StatAvg",
        "params": {},
        "comment": "Short channel regression",
    },
    "block_averaging": {
        "func": "hmrR_BlockAvg",
        "params": {"tRange": [-5, 20]},
        "comment": "Block/trial averaging",
        "param_mapper": "_r_block_avg_params",
    },
    "first_level_glm": {
        "func": "hmrR_GLM",
        "params": {},
        "comment": "First-level GLM",
    },
    "build_design_matrix": {
        "func": "hmrR_GLM",
        "params": {},
        "comment": "Design matrix (part of GLM in AnalyzIR)",
    },
    "estimate_contrast": {
        "func": "hmrR_GLM",
        "params": {},
        "comment": "Contrast estimation (part of GLM in AnalyzIR)",
    },
    "temporal_derivative_distribution_repair": {
        "func": "hmrR_MotionCorrectTD",
        "params": {},
        "comment": "TDDR motion correction",
    },
}


# Parameter mappers for R script generation
def _r_bandpass_params(params: dict[str, Any]) -> str:
    """Generate R parameter string for bandpass filter."""
    h_freq = params.get("h_freq", params.get("lpf", 0.5))
    l_freq = params.get("l_freq", params.get("hpf", 0.01))
    return f"lpf={h_freq}, hpf={l_freq}"


def _r_wavelet_params(params: dict[str, Any]) -> str:
    """Generate R parameter string for wavelet motion correction."""
    threshold = params.get("threshold", params.get("iqr", 1.5))
    return f"iqr={threshold}"


def _r_spline_params(params: dict[str, Any]) -> str:
    """Generate R parameter string for spline motion correction."""
    p = params.get("threshold", params.get("p", 0.99))
    frame = params.get("spline_segments", params.get("FrameSize", 10))
    weight = params.get("Weight", 5)
    return f"p={p}, FrameSize={frame}, Weight={weight}"


def _r_pca_params(params: dict[str, Any]) -> str:
    """Generate R parameter string for PCA motion correction."""
    n = params.get("n_components", params.get("SVDCut", 1.0))
    return f"SVDCut={n}"


def _r_cbsi_params(params: dict[str, Any]) -> str:
    """Generate R parameter string for CBSI."""
    alpha = params.get("alpha", 0.7)
    return f"alpha={alpha}"


def _r_bll_params(params: dict[str, Any]) -> str:
    """Generate R parameter string for Beer-Lambert law."""
    ppf = params.get("ppf", 6.0)
    return f"DPF=c({ppf}, {ppf})"


def _r_sci_params(params: dict[str, Any]) -> str:
    """Generate R parameter string for SCI."""
    thresh = params.get("sci_threshold", params.get("sciThresh", 0.8))
    return f"sciThresh={thresh}"


def _r_block_avg_params(params: dict[str, Any]) -> str:
    """Generate R parameter string for block averaging."""
    baseline = params.get("baseline_window", [-5, 0])
    response = params.get("response_window", [0, 20])
    if isinstance(baseline, (list, tuple)) and isinstance(response, (list, tuple)):
        return f"tRange=c({baseline[0]}, {response[1]})"
    return "tRange=c(-5, 20)"


R_PARAM_MAPPERS: dict[str, Any] = {
    "_r_bandpass_params": _r_bandpass_params,
    "_r_wavelet_params": _r_wavelet_params,
    "_r_spline_params": _r_spline_params,
    "_r_pca_params": _r_pca_params,
    "_r_cbsi_params": _r_cbsi_params,
    "_r_bll_params": _r_bll_params,
    "_r_sci_params": _r_sci_params,
    "_r_block_avg_params": _r_block_avg_params,
}


def _format_r_params(
    func_name: str,
    flow_params: dict[str, Any],
    default_params: dict[str, Any],
    mapper_name: str | None = None,
) -> str:
    """Format parameters as R function arguments."""
    if mapper_name and mapper_name in R_PARAM_MAPPERS:
        result: str = R_PARAM_MAPPERS[mapper_name](flow_params)
        return result

    # Merge defaults with flow params
    merged = {**default_params, **flow_params}
    if not merged:
        return ""

    parts = []
    for key, val in merged.items():
        if isinstance(val, bool):
            parts.append(f"{key}={'TRUE' if val else 'FALSE'}")
        elif isinstance(val, str):
            parts.append(f'{key}="{val}"')
        elif isinstance(val, list):
            r_vec = ", ".join(str(v) for v in val)
            parts.append(f"{key}=c({r_vec})")
        else:
            parts.append(f"{key}={val}")
    return ", ".join(parts)


def convert_flow_to_analyzir(
    flow_atoms: list[dict[str, Any]],
    data_path: str = "",
    output_dir: str = "",
) -> AnalyzIRScript:
    """Convert fnirs-flow atoms to an AnalyzIR R script.

    Args:
        flow_atoms: List of atom dicts with 'atom_type' or 'type' field
        data_path: Path to input data file (SNIRF)
        output_dir: Output directory for results

    Returns:
        AnalyzIRScript with R-compatible steps
    """
    script = AnalyzIRScript()

    # Data loading command
    if data_path:
        script.data_load_cmd = f'data <- load("{data_path}")'
    else:
        script.data_load_cmd = "# TODO: Set data path\ndata <- load(\"your_data.snirf\")"

    for atom in flow_atoms:
        atom_type = atom.get("atom_type") or atom.get("type", "")
        params = atom.get("config", {}).get("parameters", {})

        mapping = ATOM_TO_ANALYZIR.get(atom_type)
        if mapping is None or mapping.get("func") is None:
            script.unmapped_atoms.append(atom_type)
            continue

        # Build R parameter string
        r_params = _format_r_params(
            mapping["func"],
            params,
            mapping.get("params", {}),
            mapping.get("param_mapper"),
        )

        step = AnalyzIRStep(
            name=atom_type,
            func=mapping["func"],
            params=params,
            r_comment=mapping.get("comment", ""),
        )

        # Generate R call
        if r_params:
            step.r_comment = f"{step.r_comment}: {mapping['func']}({r_params})"
        else:
            step.r_comment = f"{step.r_comment}: {mapping['func']}()"

        script.steps.append(step)

    # Output commands
    if output_dir:
        script.output_cmds = [
            f'# Save results to {output_dir}',
            f'dir.create("{output_dir}", showWarnings = FALSE, recursive = TRUE)',
            f'save(data, file = file.path("{output_dir}", "analyzir_result.RData"))',
        ]
    else:
        script.output_cmds = ["# TODO: Add output commands"]

    return script


def generate_r_script(script: AnalyzIRScript, include_comments: bool = True) -> str:
    """Generate an R script from AnalyzIRScript.

    Args:
        script: AnalyzIRScript object
        include_comments: Whether to include descriptive comments

    Returns:
        R script as string
    """
    lines = [
        "# AnalyzIR processing script",
        "# Generated by fnirs-flow",
        "# Reference: https://github.com/huppertt/nirs-toolbox",
        "",
    ]

    if include_comments:
        lines.append("# === Load Data ===")
    lines.append(script.data_load_cmd)
    lines.append("")

    if include_comments:
        lines.append("# === Preprocessing Steps ===")
    lines.append("")

    for i, step in enumerate(script.steps, 1):
        # Comment
        if include_comments and step.r_comment:
            lines.append(f"# Step {i}: {step.r_comment}")

        # Build R call
        mapping = ATOM_TO_ANALYZIR.get(step.name)
        if mapping and mapping.get("func"):
            func = mapping["func"]
            r_params = _format_r_params(
                func,
                step.params,
                mapping.get("params", {}),
                mapping.get("param_mapper"),
            )
            if r_params:
                lines.append(f"data <- {func}(data, {r_params})")
            else:
                lines.append(f"data <- {func}(data)")
        lines.append("")

    # Output section
    if include_comments:
        lines.append("# === Save Results ===")
    for cmd in script.output_cmds:
        lines.append(cmd)

    return "\n".join(lines)


def write_analyzir_script(
    script: AnalyzIRScript,
    outdir: Path,
    filename: str = "fnirs_pipeline.R",
) -> Path:
    """Write AnalyzIR R script to file."""
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / filename
    r_content = generate_r_script(script)
    path.write_text(r_content, encoding="utf-8")
    return path


def write_analyzir_mapping_report(
    script: AnalyzIRScript,
    outdir: Path,
) -> Path:
    """Write a mapping report showing which atoms could/couldn't be mapped."""
    lines = [
        "# AnalyzIR Export Report",
        "",
        f"**Total atoms:** {len(script.steps) + len(script.unmapped_atoms)}",
        f"**Mapped:** {len(script.steps)}",
        f"**Unmapped:** {len(script.unmapped_atoms)}",
        "",
    ]

    if script.steps:
        lines.append("## Mapped Steps")
        lines.append("")
        lines.append("| Atom Type | AnalyzIR Function | Parameters |")
        lines.append("|-----------|-------------------|------------|")
        for step in script.steps:
            params_str = ", ".join(f"{k}={v}" for k, v in step.params.items()) if step.params else "-"
            lines.append(f"| {step.name} | `{step.func}` | {params_str} |")
        lines.append("")

    if script.unmapped_atoms:
        lines.append("## Unmapped Atoms")
        lines.append("")
        lines.append("These atoms have no AnalyzIR equivalent:")
        lines.append("")
        for atom in script.unmapped_atoms:
            lines.append(f"- `{atom}`")
        lines.append("")

    path = outdir / "analyzir_export_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
