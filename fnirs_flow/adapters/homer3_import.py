"""Homer3 import adapter: reads Homer3 process stream config and converts to fnirs-flow atoms.

Supports:
- Homer3 .cfg process stream files
- Homer3 .snirf files (extracts processing history)
- Homer3 processFunc call format (JSON)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Homer3ImportResult(BaseModel):
    """Result of importing a Homer3 configuration."""

    atoms: list[dict[str, Any]] = Field(default_factory=list)
    unmapped_functions: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_format: str = ""
    source_path: str = ""


# Reverse mapping: Homer3 function name -> fnirs-flow atom type
HOMER3_TO_ATOM: dict[str, dict[str, Any]] = {
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
        "param_mapper": "_map_bandpass_params",
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
        "param_mapper": "_map_wavelet_params",
    },
    "hmrR_MotionCorrectSpline": {
        "atom_type": "spline_motion_correction",
        "operation": "motion_correction",
        "category": "preprocessing",
        "default_params": {"method": "spline"},
        "param_mapper": "_map_spline_params",
    },
    "hmrR_MotionCorrectPCA": {
        "atom_type": "pca_motion_correction",
        "operation": "motion_correction",
        "category": "preprocessing",
        "default_params": {"method": "pca"},
        "param_mapper": "_map_pca_params",
    },
    "hmrR_MotionCorrectCBSI": {
        "atom_type": "cbsi_motion_correction",
        "operation": "motion_correction",
        "category": "preprocessing",
        "default_params": {"method": "cbsi"},
        "param_mapper": "_map_cbsi_params",
    },
    "hmrR_OD2Conc": {
        "atom_type": "beer_lambert_law",
        "operation": "beer_lambert_law",
        "category": "preprocessing",
        "default_params": {},
        "param_mapper": "_map_bll_params",
    },
    "hmrR_Sci": {
        "atom_type": "scalp_coupling_index",
        "operation": "compute_qc",
        "category": "qc",
        "default_params": {},
        "param_mapper": "_map_sci_params",
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
        "param_mapper": "_map_block_avg_params",
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
}


# Parameter mappers: Homer3 param names -> fnirs-flow param names
def _map_bandpass_params(homer3_params: dict[str, Any]) -> dict[str, Any]:
    """Map Homer3 bandpass filter params to fnirs-flow."""
    params: dict[str, Any] = {}
    if "lpf" in homer3_params:
        params["h_freq"] = homer3_params["lpf"]
    if "hpf" in homer3_params:
        params["l_freq"] = homer3_params["hpf"]
    # Detect notch filter (lpf=-1, hpf=-1)
    if homer3_params.get("lpf") == -1 and homer3_params.get("hpf") == -1:
        params["method"] = "notch"
    else:
        params["method"] = "bandpass"
    return params


def _map_wavelet_params(homer3_params: dict[str, Any]) -> dict[str, Any]:
    """Map Homer3 wavelet motion correction params."""
    params: dict[str, Any] = {"method": "wavelet"}
    if "iqr" in homer3_params:
        params["threshold"] = homer3_params["iqr"]
    return params


def _map_spline_params(homer3_params: dict[str, Any]) -> dict[str, Any]:
    """Map Homer3 spline motion correction params."""
    params: dict[str, Any] = {"method": "spline"}
    if "p" in homer3_params:
        params["threshold"] = homer3_params["p"]
    if "FrameSize" in homer3_params:
        params["spline_segments"] = homer3_params["FrameSize"]
    return params


def _map_pca_params(homer3_params: dict[str, Any]) -> dict[str, Any]:
    """Map Homer3 PCA motion correction params."""
    params: dict[str, Any] = {"method": "pca"}
    if "SVDCut" in homer3_params:
        params["n_components"] = homer3_params["SVDCut"]
    return params


def _map_cbsi_params(homer3_params: dict[str, Any]) -> dict[str, Any]:
    """Map Homer3 CBSI motion correction params."""
    params: dict[str, Any] = {"method": "cbsi"}
    if "alpha" in homer3_params:
        params["alpha"] = homer3_params["alpha"]
    return params


def _map_bll_params(homer3_params: dict[str, Any]) -> dict[str, Any]:
    """Map Homer3 Beer-Lambert law params."""
    params: dict[str, Any] = {}
    if "DPF" in homer3_params:
        dpf = homer3_params["DPF"]
        if isinstance(dpf, list) and len(dpf) >= 1:
            params["ppf"] = dpf[0]
        else:
            params["ppf"] = float(dpf)
    return params


def _map_sci_params(homer3_params: dict[str, Any]) -> dict[str, Any]:
    """Map Homer3 SCI params."""
    params: dict[str, Any] = {}
    if "sciThresh" in homer3_params:
        params["sci_threshold"] = homer3_params["sciThresh"]
    return params


def _map_block_avg_params(homer3_params: dict[str, Any]) -> dict[str, Any]:
    """Map Homer3 block averaging params."""
    params: dict[str, Any] = {}
    if "tRange" in homer3_params:
        tr = homer3_params["tRange"]
        if isinstance(tr, list) and len(tr) == 2:
            params["baseline_window"] = (float(tr[0]), 0.0)
            params["response_window"] = (0.0, float(tr[1]))
    return params


PARAM_MAPPERS: dict[str, Any] = {
    "_map_bandpass_params": _map_bandpass_params,
    "_map_wavelet_params": _map_wavelet_params,
    "_map_spline_params": _map_spline_params,
    "_map_pca_params": _map_pca_params,
    "_map_cbsi_params": _map_cbsi_params,
    "_map_bll_params": _map_bll_params,
    "_map_sci_params": _map_sci_params,
    "_map_block_avg_params": _map_block_avg_params,
}


def _map_homer3_function(
    func_name: str,
    homer3_params: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Map a Homer3 function to an fnirs-flow atom.

    Returns:
        Tuple of (atom_dict, unmapped_info). One will be None.
    """
    mapping = HOMER3_TO_ATOM.get(func_name)
    if mapping is None:
        return None, {
            "function": func_name,
            "params": homer3_params,
            "reason": "no_mapping_available",
        }

    # Start with default params
    params = dict(mapping.get("default_params", {}))

    # Apply parameter mapper if available
    mapper_name = mapping.get("param_mapper")
    if mapper_name and mapper_name in PARAM_MAPPERS:
        mapped = PARAM_MAPPERS[mapper_name](homer3_params)
        params.update(mapped)
    else:
        # Pass through params directly
        params.update(homer3_params)

    atom = {
        "atom_type": mapping["atom_type"],
        "operation": mapping["operation"],
        "category": mapping["category"],
        "config": {"parameters": params},
        "source": "homer3_import",
        "source_function": func_name,
    }
    return atom, None


def parse_homer3_cfg(cfg_path: str | Path) -> Homer3ImportResult:
    """Parse a Homer3 .cfg process stream file.

    Homer3 .cfg files contain process function calls in the format:
        funcName(param1, param2, ...)
    or
        [result] = funcName(param1, param2, ...)

    Args:
        cfg_path: Path to .cfg file

    Returns:
        Homer3ImportResult with parsed atoms
    """
    cfg_path = Path(cfg_path)
    result = Homer3ImportResult(
        source_format="homer3_cfg",
        source_path=str(cfg_path),
    )

    if not cfg_path.exists():
        result.warnings.append(f"File not found: {cfg_path}")
        return result

    content = cfg_path.read_text(encoding="utf-8")

    # Parse processFunc calls
    # Pattern: optional assignment, function name, parameters in parens
    pattern = re.compile(
        r"(?:\[.*?\]\s*=\s*)?"  # Optional assignment
        r"(\w+)"  # Function name
        r"\(([^)]*)\)",  # Parameters
        re.MULTILINE,
    )

    for match in pattern.finditer(content):
        func_name = match.group(1)
        raw_params = match.group(2).strip()

        # Parse parameters
        params = _parse_homer3_params(raw_params)

        atom, unmapped = _map_homer3_function(func_name, params)
        if atom:
            result.atoms.append(atom)
        elif unmapped:
            result.unmapped_functions.append(unmapped)

    return result


def parse_homer3_json(json_path: str | Path) -> Homer3ImportResult:
    """Parse a Homer3 process config JSON file.

    This handles the JSON format exported by fnirs-flow's homer3_export.py
    and Homer3-compatible JSON configs.

    Args:
        json_path: Path to .json file

    Returns:
        Homer3ImportResult with parsed atoms
    """
    json_path = Path(json_path)
    result = Homer3ImportResult(
        source_format="homer3_json",
        source_path=str(json_path),
    )

    if not json_path.exists():
        result.warnings.append(f"File not found: {json_path}")
        return result

    content = json_path.read_text(encoding="utf-8")
    data = json.loads(content)

    # Handle different JSON structures
    steps: list[dict[str, Any]] = []
    if isinstance(data, dict):
        steps = data.get("steps", data.get("processFunc", [])) or []
    elif isinstance(data, list):
        steps = data

    for step in steps:
        if not isinstance(step, dict):
            continue

        func_name: str = str(step.get("func", step.get("name", "")))
        params: dict[str, Any] = step.get("params", step.get("parameters", {})) or {}

        atom, unmapped = _map_homer3_function(func_name, params)
        if atom:
            result.atoms.append(atom)
        elif unmapped:
            result.unmapped_functions.append(unmapped)

    return result


def parse_homer3_process_func(process_func: list[dict[str, Any]]) -> Homer3ImportResult:
    """Parse a Homer3 processFunc call list.

    Args:
        process_func: List of dicts with 'func' and 'param' keys

    Returns:
        Homer3ImportResult with parsed atoms
    """
    result = Homer3ImportResult(source_format="homer3_process_func")

    for call in process_func:
        func_name = call.get("func", "")
        params = call.get("param", call.get("params", {}))

        if isinstance(params, list):
            # Convert positional params to dict
            params = _positional_to_dict(func_name, params)

        atom, unmapped = _map_homer3_function(func_name, params)
        if atom:
            result.atoms.append(atom)
        elif unmapped:
            result.unmapped_functions.append(unmapped)

    return result


def _parse_homer3_params(raw: str) -> dict[str, Any]:
    """Parse Homer3 parameter string into a dict.

    Handles formats like:
        '0.5, 0.01, 2'
        'lpf=0.5, hpf=0.01'
        '{"lpf": 0.5, "hpf": 0.01}'
    """
    raw = raw.strip()
    if not raw:
        return {}

    # Try JSON first
    if raw.startswith("{"):
        try:
            result: dict[str, Any] = json.loads(raw)
            return result
        except json.JSONDecodeError:
            pass

    # Try key=value format
    if "=" in raw:
        params: dict[str, Any] = {}
        for part in raw.split(","):
            part = part.strip()
            if "=" in part:
                key, val = part.split("=", 1)
                params[key.strip()] = _try_parse_value(val.strip())
        return params

    # Positional format - return as list wrapped in dict
    values = [_try_parse_value(v.strip()) for v in raw.split(",")]
    return {"positional": values}


def _try_parse_value(val: str) -> Any:
    """Try to parse a string value to a Python type."""
    if not val:
        return val
    # Boolean
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    # Number
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        pass
    # Array
    if val.startswith("["):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            pass
    # String (remove quotes)
    return val.strip("\"'")


def _positional_to_dict(func_name: str, params: list[Any]) -> dict[str, Any]:
    """Convert positional Homer3 params to named dict.

    Uses known parameter orders for common functions.
    """
    known_orders: dict[str, list[str]] = {
        "hmrR_BandpassFilt": ["lpf", "hpf", "Order"],
        "hmrR_MotionCorrectWavelet": ["iqr"],
        "hmrR_MotionCorrectSpline": ["p", "FrameSize", "Weight"],
        "hmrR_MotionCorrectPCA": ["SVDCut"],
        "hmrR_MotionCorrectCBSI": ["alpha"],
        "hmrR_OD2Conc": ["DPF"],
        "hmrR_Sci": ["sciThresh"],
        "hmrR_BlockAvg": ["tRange", "tRangeMan"],
        "hmrR_GLM": ["SDpairsInclude", "tCCAfilter", "rcMap"],
    }

    order = known_orders.get(func_name)
    if order is None:
        return {f"param_{i}": v for i, v in enumerate(params)}

    result: dict[str, Any] = {}
    for i, val in enumerate(params):
        if i < len(order):
            result[order[i]] = val
        else:
            result[f"param_{i}"] = val
    return result


def import_homer3(source: str | Path) -> Homer3ImportResult:
    """Import a Homer3 configuration file.

    Supports .cfg, .json, and processFunc call lists.

    Args:
        source: Path to Homer3 config file

    Returns:
        Homer3ImportResult with imported atoms
    """
    source = Path(source)

    if source.suffix == ".cfg":
        return parse_homer3_cfg(source)
    elif source.suffix == ".json":
        return parse_homer3_json(source)
    else:
        result = Homer3ImportResult(source_path=str(source))
        result.warnings.append(f"Unsupported file format: {source.suffix}")
        return result


def write_import_report(result: Homer3ImportResult, outdir: Path) -> Path:
    """Write an import report showing mapped and unmapped functions."""
    lines = [
        "# Homer3 Import Report",
        "",
        f"**Source:** `{result.source_path}`",
        f"**Format:** {result.source_format}",
        "",
        f"**Total atoms imported:** {len(result.atoms)}",
        f"**Unmapped functions:** {len(result.unmapped_functions)}",
        "",
    ]

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
        lines.append("These Homer3 functions have no fnirs-flow equivalent:")
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
    path = outdir / "homer3_import_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
