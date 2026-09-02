"""JSON Schema loading and validation for flow files."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import ValidationError

try:
    import jsonschema
except ImportError:
    jsonschema = None  # type: ignore[assignment]

from fnirs_flow.flow.models import FlowGraph
from fnirs_flow.flow.serialization import load_canonical_flow, serialize_flow_payload

PROCESSED_HB_REQUIRED_OPERATIONS = {
    "frozen_manifest_discovery",
    "read_vendor_processed_hb",
    "ingest_frozen_events",
    "regularize_processed_hb_time",
    "compile_processed_hb_designs",
    "fit_processed_hb_first_level",
    "estimate_full_contrasts",
    "write_processed_hb_derivatives",
}

PROCESSED_HB_V130_OPERATIONS = {
    "ingest_frozen_window_set",
    "join_channel_annotation_table",
    "evaluate_processed_hb_window_qc",
    "aggregate_window_modality_availability",
    "extract_processed_hb_channel_window_features",
    "write_processed_hb_ml_derivatives",
    "freeze_processed_hb_feature_artifacts",
    "nested_grouped_regression",
    "validate_information_boundary",
    "run_continuous_vas_models",
}


def _missing_values(value: Any, prefix: str = "") -> list[str]:
    missing: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if item is None or item == "" or item == "TBD":
                missing.append(path)
            elif isinstance(item, dict):
                missing.extend(_missing_values(item, path))
    return missing


def _validate_processed_hb_contract(flow_dict: dict[str, Any], operations: set[str]) -> list[str]:
    errors: list[str] = []
    required_set = PROCESSED_HB_REQUIRED_OPERATIONS | PROCESSED_HB_V130_OPERATIONS
    required = required_set - operations
    if required:
        errors.append(f"vendor_processed_hb flow is missing required operations: {sorted(required)}")
    raw_only = {
        "optical_density",
        "motion_correction",
        "tddr",
        "wavelet",
        "spline",
        "ica",
        "pca",
        "filtering",
        "bandpass",
        "notch",
        "lowpass",
        "beer_lambert_law",
        "mbll",
        "short_channel_regression",
        "systemic_physiology_regression",
    }
    illegal = sorted(operations & raw_only)
    if illegal:
        errors.append(f"vendor_processed_hb cannot use raw-intensity operations: {illegal}")

    solver = flow_dict.get("solver", {})
    confirmatory = isinstance(solver, dict) and solver.get("confirmatory") is True
    contract = flow_dict.get("processed_hb", {})
    if not isinstance(contract, dict):
        errors.append("vendor_processed_hb processed_hb contract must be an object")
        return errors
    if confirmatory:
        if solver.get("requested") not in {"ols", "ar1", "ar1_irls"}:
            errors.append("confirmatory processed-Hb solver must be ols, ar1, or ar1_irls")
        if solver.get("fallback_policy") != "forbid":
            errors.append("confirmatory processed-Hb solver fallback_policy must be forbid")
        if contract.get("scientific_parameters_frozen") is not True:
            errors.append("confirmatory processed-Hb requires scientific_parameters_frozen=true")
        required_sections = ("parser", "time_regularization", "design", "solver", "covariance", "qc")
        for section in required_sections:
            if not isinstance(contract.get(section), dict) or not contract[section]:
                errors.append(f"confirmatory processed-Hb requires a non-empty {section} contract")
        missing = _missing_values({key: contract.get(key) for key in required_sections})
        if missing:
            errors.append(f"confirmatory processed-Hb has unfrozen values: {sorted(missing)}")
        weights = (
            contract.get("design", {}).get("fir_0_30_weights", []) if isinstance(contract.get("design"), dict) else []
        )
        if not isinstance(weights, list) or len(weights) != 3 or not all(isinstance(v, int | float) for v in weights):
            errors.append("confirmatory processed-Hb requires three frozen FIR 0-30 s weights")
    models = contract.get("design", {}).get("models", []) if isinstance(contract.get("design"), dict) else []
    if any("fir" in str(model).casefold() and "canonical" in str(model).casefold() for model in models):
        errors.append("FIR models cannot bind a canonical-HRF operation")
    if (
        contract.get("design", {}).get("saturated_and_trend_same_model") is True
        if isinstance(contract.get("design"), dict)
        else False
    ):
        errors.append("saturated M1-M5 and deterministic trend columns cannot coexist in one model")
    roi = contract.get("roi_mapping")
    if "roi_output" in operations and not (
        isinstance(roi, dict) and roi.get("mapping_id") and roi.get("version") and roi.get("sha256")
    ):
        errors.append("processed-Hb ROI output requires a versioned mapping_id and SHA-256")
    return errors


def _load_schema(name: str) -> dict[str, Any]:
    """Load an authoritative JSON Schema from the installed package."""
    schema_resource = files("fnirs_flow.resources.schemas").joinpath(name)
    if not schema_resource.is_file():
        raise FileNotFoundError(f"Packaged Schema not found: {name}")
    # utf-8-sig remains compatible with ordinary UTF-8 and tolerates schemas
    # written by Windows tooling that emits a BOM.
    with schema_resource.open("r", encoding="utf-8-sig") as f:
        result: dict[str, Any] = json.load(f)
        return result


def validate_flow_dict(flow_dict: dict[str, Any]) -> list[str]:
    """Validate a flow dict against the JSON Schema. Returns list of error strings."""
    errors: list[str] = []

    if not isinstance(flow_dict, dict):
        return ["Flow must be a JSON object"]

    for field in ("schema_version", "flow_id", "edges"):
        if field not in flow_dict:
            errors.append(f"'{field}' is a required property")

    has_nodes = "nodes" in flow_dict
    has_flow_atoms = "flow_atoms" in flow_dict
    if not has_nodes and not has_flow_atoms:
        errors.append("'nodes' or 'flow_atoms' is a required property")

    if has_nodes and not isinstance(flow_dict.get("nodes"), list):
        errors.append("'nodes' must be an array")
    if has_flow_atoms and not isinstance(flow_dict.get("flow_atoms"), list):
        errors.append("'flow_atoms' must be an array")
    if "edges" in flow_dict and not isinstance(flow_dict.get("edges"), list):
        errors.append("'edges' must be an array")

    if jsonschema is None:  # pragma: no cover - declared runtime dependency
        try:
            load_canonical_flow(flow_dict)
        except ValidationError as exc:
            errors.extend(str(err["msg"]) for err in exc.errors())
        return errors  # Fall back to built-in structural checks
    schema = _load_schema("fnirs_flow.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    errors.extend(err.message for err in validator.iter_errors(flow_dict))
    semantics = flow_dict.get("data_semantics", {})
    if isinstance(semantics, dict) and semantics.get("branch") == "vendor_processed_hb":
        if semantics.get("absolute_unit_verified") is not False:
            errors.append("vendor_processed_hb requires absolute_unit_verified=false")
        atoms = flow_dict.get("flow_atoms", flow_dict.get("nodes", []))
        operations = {
            str(atom.get("operation", atom.get("atom_type", atom.get("type", ""))))
            for atom in atoms
            if isinstance(atom, dict)
        }
        errors.extend(_validate_processed_hb_contract(flow_dict, operations))
    return errors


def load_flow_from_dict(data: dict[str, Any]) -> FlowGraph:
    """Load a FlowGraph from a dict. Raises ValidationError on invalid data."""
    return load_canonical_flow(data)


def load_flow_from_file(path: str | Path) -> FlowGraph:
    """Load a FlowGraph from a JSON file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return load_flow_from_dict(data)


def flow_to_dict(flow: FlowGraph) -> dict[str, Any]:
    """Serialize a FlowGraph to a JSON-compatible dict."""
    return serialize_flow_payload(flow)
