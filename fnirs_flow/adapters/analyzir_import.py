"""AnalyzIR import adapter: reads AnalyzIR R scripts and converts to fnirs-flow atoms.

Supports:
- AnalyzIR R script files (.R)
- AnalyzIR pipeline JSON configs
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class AnalyzIRImportResult(BaseModel):
    """Result of importing an AnalyzIR configuration."""

    atoms: list[dict[str, Any]] = Field(default_factory=list)
    unmapped_functions: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_format: str = ""
    source_path: str = ""
    data_path: str = ""


# Reverse mapping: AnalyzIR R function -> fnirs-flow atom type
ANALYZIR_TO_ATOM: dict[str, dict[str, Any]] = {
    "hmrR_Intensity2OD": {
        "atom_type": "optical_density",
        "operation": "optical_density",
        "category": "preprocessing",
        "default_params": {},
    },
    "hmrR_BandpassFilt": {
        "atom_type": "bandpass_filter",
        "operation": "filtering",
        "category": "preprocessing",
        "default_params": {},
        "param_mapper": "_parse_bandpass_r",
    },
    "hmrR_MotionCorrectTD": {
        "atom_type": "tddr_motion",
        "operation": "motion_correction",
        "category": "preprocessing",
        "default_params": {"method": "tddr"},
    },
    "hmrR_MotionCorrectWavelet": {
        "atom_type": "wavelet_motion_correction",
        "operation": "motion_correction",
        "category": "preprocessing",
        "default_params": {"method": "wavelet"},
        "param_mapper": "_parse_wavelet_r",
    },
    "hmrR_MotionCorrectSpline": {
        "atom_type": "spline_motion_correction",
        "operation": "motion_correction",
        "category": "preprocessing",
        "default_params": {"method": "spline"},
        "param_mapper": "_parse_spline_r",
    },
    "hmrR_MotionCorrectPCA": {
        "atom_type": "pca_motion_correction",
        "operation": "motion_correction",
        "category": "preprocessing",
        "default_params": {"method": "pca"},
        "param_mapper": "_parse_pca_r",
    },
    "hmrR_MotionCorrectCBSI": {
        "atom_type": "cbsi_motion_correction",
        "operation": "motion_correction",
        "category": "preprocessing",
        "default_params": {"method": "cbsi"},
        "param_mapper": "_parse_cbsi_r",
    },
    "hmrR_OD2Conc": {
        "atom_type": "beer_lambert_law",
        "operation": "beer_lambert_law",
        "category": "preprocessing",
        "default_params": {},
        "param_mapper": "_parse_bll_r",
    },
    "hmrR_Sci": {
        "atom_type": "scalp_coupling_index",
        "operation": "compute_qc",
        "category": "qc",
        "default_params": {},
        "param_mapper": "_parse_sci_r",
    },
    "hmrR_StatAvg": {
        "atom_type": "short_channel_regression",
        "operation": "short_channel_regression",
        "category": "preprocessing",
        "default_params": {},
    },
    "hmrR_BlockAvg": {
        "atom_type": "block_averaging",
        "operation": "block_averaging",
        "category": "analysis",
        "default_params": {},
        "param_mapper": "_parse_block_avg_r",
    },
    "hmrR_GLM": {
        "atom_type": "first_level_glm",
        "operation": "first_level_glm",
        "category": "analysis",
        "default_params": {},
    },
    "hmrR_tCCA": {
        "atom_type": "temporal_cca",
        "operation": "short_channel_regression",
        "category": "preprocessing",
        "default_params": {"method": "tcca"},
    },
    "hmrR_StimRejection": {
        "atom_type": "stim_rejection",
        "operation": "stim_rejection",
        "category": "preprocessing",
        "default_params": {},
    },
    "hmrR_MotionCorrectCW": {
        "atom_type": "motion_correct_cw",
        "operation": "motion_correction",
        "category": "preprocessing",
        "default_params": {"method": "cw"},
    },
}


# R parameter parsers
def _parse_bandpass_r(r_params: str) -> dict[str, Any]:
    """Parse R bandpass filter parameters."""
    params: dict[str, Any] = {}
    lpf = _extract_r_param(r_params, "lpf")
    hpf = _extract_r_param(r_params, "hpf")
    if lpf is not None:
        params["h_freq"] = lpf
    if hpf is not None:
        params["l_freq"] = hpf
    # Detect notch
    if lpf == -1 and hpf == -1:
        params["method"] = "notch"
    else:
        params["method"] = "bandpass"
    return params


def _parse_wavelet_r(r_params: str) -> dict[str, Any]:
    """Parse R wavelet motion correction parameters."""
    params: dict[str, Any] = {"method": "wavelet"}
    iqr = _extract_r_param(r_params, "iqr")
    if iqr is not None:
        params["threshold"] = iqr
    return params


def _parse_spline_r(r_params: str) -> dict[str, Any]:
    """Parse R spline motion correction parameters."""
    params: dict[str, Any] = {"method": "spline"}
    p = _extract_r_param(r_params, "p")
    frame = _extract_r_param(r_params, "FrameSize")
    weight = _extract_r_param(r_params, "Weight")
    if p is not None:
        params["threshold"] = p
    if frame is not None:
        params["spline_segments"] = int(frame)
    if weight is not None:
        params["weight"] = weight
    return params


def _parse_pca_r(r_params: str) -> dict[str, Any]:
    """Parse R PCA motion correction parameters."""
    params: dict[str, Any] = {"method": "pca"}
    svd = _extract_r_param(r_params, "SVDCut")
    if svd is not None:
        params["n_components"] = svd
    return params


def _parse_cbsi_r(r_params: str) -> dict[str, Any]:
    """Parse R CBSI parameters."""
    params: dict[str, Any] = {"method": "cbsi"}
    alpha = _extract_r_param(r_params, "alpha")
    if alpha is not None:
        params["alpha"] = alpha
    return params


def _parse_bll_r(r_params: str) -> dict[str, Any]:
    """Parse R Beer-Lambert law parameters."""
    params: dict[str, Any] = {}
    dpf_match = re.search(r"DPF\s*=\s*c\(([^)]+)\)", r_params)
    if dpf_match:
        vals = [float(v.strip()) for v in dpf_match.group(1).split(",")]
        if vals:
            params["ppf"] = vals[0]
    return params


def _parse_sci_r(r_params: str) -> dict[str, Any]:
    """Parse R SCI parameters."""
    params: dict[str, Any] = {}
    thresh = _extract_r_param(r_params, "sciThresh")
    if thresh is not None:
        params["sci_threshold"] = thresh
    return params


def _parse_block_avg_r(r_params: str) -> dict[str, Any]:
    """Parse R block averaging parameters."""
    params: dict[str, Any] = {}
    tr_match = re.search(r"tRange\s*=\s*c\(([^)]+)\)", r_params)
    if tr_match:
        vals = [float(v.strip()) for v in tr_match.group(1).split(",")]
        if len(vals) == 2:
            params["baseline_window"] = (vals[0], 0.0)
            params["response_window"] = (0.0, vals[1])
    return params


R_PARAM_PARSERS: dict[str, Any] = {
    "_parse_bandpass_r": _parse_bandpass_r,
    "_parse_wavelet_r": _parse_wavelet_r,
    "_parse_spline_r": _parse_spline_r,
    "_parse_pca_r": _parse_pca_r,
    "_parse_cbsi_r": _parse_cbsi_r,
    "_parse_bll_r": _parse_bll_r,
    "_parse_sci_r": _parse_sci_r,
    "_parse_block_avg_r": _parse_block_avg_r,
}


def _extract_r_param(r_params: str, param_name: str) -> float | None:
    """Extract a numeric parameter from R function call string."""
    pattern = rf"{param_name}\s*=\s*([-+]?\d*\.?\d+)"
    match = re.search(pattern, r_params)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _extract_balanced_parens(text: str, start: int) -> str | None:
    """Extract content between balanced parentheses starting from `start`.

    Assumes `start` is right after an opening '('. Walks forward counting
    nested parens until the matching ')' is found.
    """
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        i += 1
    if depth != 0:
        return None
    return text[start : i - 1]


def _extract_r_string_param(r_params: str, param_name: str) -> str | None:
    """Extract a string parameter from R function call string."""
    pattern = rf'{param_name}\s*=\s*"([^"]*)"'
    match = re.search(pattern, r_params)
    if match:
        return match.group(1)
    # Try single quotes
    pattern = rf"{param_name}\s*=\s*'([^']*)'"
    match = re.search(pattern, r_params)
    if match:
        return match.group(1)
    return None


def _map_analyzir_function(
    func_name: str,
    r_params: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Map an AnalyzIR R function to an fnirs-flow atom.

    Returns:
        Tuple of (atom_dict, unmapped_info). One will be None.
    """
    mapping = ANALYZIR_TO_ATOM.get(func_name)
    if mapping is None:
        return None, {
            "function": func_name,
            "r_params": r_params,
            "reason": "no_mapping_available",
        }

    # Start with default params
    params = dict(mapping.get("default_params", {}))

    # Apply parameter parser if available
    parser_name = mapping.get("param_mapper")
    if parser_name and parser_name in R_PARAM_PARSERS:
        parsed = R_PARAM_PARSERS[parser_name](r_params)
        params.update(parsed)

    atom = {
        "atom_type": mapping["atom_type"],
        "operation": mapping["operation"],
        "category": mapping["category"],
        "config": {"parameters": params},
        "source": "analyzir_import",
        "source_function": func_name,
    }
    return atom, None


def parse_analyzir_r_script(r_path: str | Path) -> AnalyzIRImportResult:
    """Parse an AnalyzIR R script file.

    Recognizes patterns like:
        data <- hmrR_Function(data, param1, param2)
        data <- hmrR_Function(data, lpf=0.5, hpf=0.01)

    Args:
        r_path: Path to .R file

    Returns:
        AnalyzIRImportResult with parsed atoms
    """
    r_path = Path(r_path)
    result = AnalyzIRImportResult(
        source_format="analyzir_r_script",
        source_path=str(r_path),
    )

    if not r_path.exists():
        result.warnings.append(f"File not found: {r_path}")
        return result

    content = r_path.read_text(encoding="utf-8")

    # Extract data path from load/read commands
    data_match = re.search(r'(?:load|read\.snirf|read\.nirx)\s*\(\s*["\']([^"\']+)["\']', content)
    if data_match:
        result.data_path = data_match.group(1)

    # Parse R function calls
    # Pattern: data <- hmrR_Function(data, params)
    # Also handles: result <- hmrR_Function(data, params)
    # Use balanced-paren matching to handle nested calls like c(6.2, 6.2)
    pattern = re.compile(
        r"(?:(\w+)\s*<-\s*)?"  # Optional assignment
        r"(hmrR_\w+)"  # Function name (must start with hmrR_)
        r"\s*\(",  # Open paren
        re.MULTILINE,
    )

    for match in pattern.finditer(content):
        # Skip matches inside comments (# ...)
        line_start = content.rfind("\n", 0, match.start()) + 1
        line_prefix = content[line_start:match.start()].lstrip()
        if line_prefix.startswith("#"):
            continue

        func_name = match.group(2)
        # Extract balanced parameters (handles nested parens like c(6.2, 6.2))
        start = match.end()  # Position right after the opening paren
        raw_params = _extract_balanced_parens(content, start)
        if raw_params is None:
            continue

        # Remove 'data' or 'd' first argument (input handle)
        # hmrR functions typically have (data, ...) format
        params_str = re.sub(r"^(?:data|d)\s*,?\s*", "", raw_params.strip())

        atom, unmapped = _map_analyzir_function(func_name, params_str)
        if atom:
            result.atoms.append(atom)
        elif unmapped:
            result.unmapped_functions.append(unmapped)

    return result


def parse_analyzir_json(json_path: str | Path) -> AnalyzIRImportResult:
    """Parse an AnalyzIR pipeline JSON config.

    Args:
        json_path: Path to .json file

    Returns:
        AnalyzIRImportResult with parsed atoms
    """
    json_path = Path(json_path)
    result = AnalyzIRImportResult(
        source_format="analyzir_json",
        source_path=str(json_path),
    )

    if not json_path.exists():
        result.warnings.append(f"File not found: {json_path}")
        return result

    content = json_path.read_text(encoding="utf-8")
    data = json.loads(content)

    steps: list[dict[str, Any]] = []
    if isinstance(data, dict):
        steps = data.get("steps", data.get("pipeline", [])) or []
        result.data_path = str(data.get("data_path", data.get("input", "")) or "")
    elif isinstance(data, list):
        steps = data

    for step in steps:
        if not isinstance(step, dict):
            continue

        func_name: str = str(step.get("func", step.get("function", "")) or "")
        params: Any = step.get("params", step.get("parameters", {}))

        # Convert params to R-style string for parsing
        if isinstance(params, dict):
            r_params = ", ".join(f"{k}={_to_r_value(v)}" for k, v in params.items())
        elif isinstance(params, str):
            r_params = params
        else:
            r_params = ""

        atom, unmapped = _map_analyzir_function(func_name, r_params)
        if atom:
            result.atoms.append(atom)
        elif unmapped:
            result.unmapped_functions.append(unmapped)

    return result


def _to_r_value(val: Any) -> str:
    """Convert Python value to R string representation."""
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, list):
        inner = ", ".join(str(v) for v in val)
        return f"c({inner})"
    if isinstance(val, str):
        return f'"{val}"'
    return str(val)


def import_analyzir(source: str | Path) -> AnalyzIRImportResult:
    """Import an AnalyzIR configuration file.

    Supports .R and .json files.

    Args:
        source: Path to AnalyzIR config file

    Returns:
        AnalyzIRImportResult with imported atoms
    """
    source = Path(source)

    if source.suffix.lower() == ".r":
        return parse_analyzir_r_script(source)
    elif source.suffix.lower() == ".json":
        return parse_analyzir_json(source)
    else:
        result = AnalyzIRImportResult(source_path=str(source))
        result.warnings.append(f"Unsupported file format: {source.suffix}")
        return result


def write_import_report(result: AnalyzIRImportResult, outdir: Path) -> Path:
    """Write an import report showing mapped and unmapped functions."""
    lines = [
        "# AnalyzIR Import Report",
        "",
        f"**Source:** `{result.source_path}`",
        f"**Format:** {result.source_format}",
        "",
        f"**Total atoms imported:** {len(result.atoms)}",
        f"**Unmapped functions:** {len(result.unmapped_functions)}",
        "",
    ]

    if result.data_path:
        lines.append(f"**Data path:** `{result.data_path}`")
        lines.append("")

    if result.atoms:
        lines.append("## Imported Atoms")
        lines.append("")
        lines.append("| # | Atom Type | Operation | Category | Source Function |")
        lines.append("|---|-----------|-----------|----------|-----------------|")
        for i, atom in enumerate(result.atoms, 1):
            lines.append(
                f"| {i} | `{atom.get('atom_type', '')}` "
                f"| `{atom.get('operation', '')}` "
                f"| {atom.get('category', '')} "
                f"| `{atom.get('source_function', '')}` |"
            )
        lines.append("")

    if result.unmapped_functions:
        lines.append("## Unmapped Functions")
        lines.append("")
        lines.append("These AnalyzIR functions have no fnirs-flow equivalent:")
        lines.append("")
        for unmapped in result.unmapped_functions:
            lines.append(f"- `{unmapped['function']}`: {unmapped['reason']}")
        lines.append("")

    if result.warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in result.warnings:
            lines.append(f"- {warning}")
        lines.append("")

    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "analyzir_import_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
