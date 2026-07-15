"""JSON Schema loading and validation for flow files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

try:
    import jsonschema
except ImportError:
    jsonschema = None  # type: ignore[assignment]

from fnirs_flow.flow.models import FlowGraph

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"


def _load_schema(name: str) -> dict[str, Any]:
    schema_path = _SCHEMAS_DIR / name
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")
    with open(schema_path, encoding="utf-8") as f:
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

    if jsonschema is None:
        try:
            FlowGraph.model_validate(flow_dict)
        except ValidationError as exc:
            errors.extend(str(err["msg"]) for err in exc.errors())
        return errors  # Fall back to built-in structural checks
    try:
        schema = _load_schema("fnirs_flow.schema.json")
    except FileNotFoundError:
        try:
            FlowGraph.model_validate(flow_dict)
        except ValidationError as exc:
            errors.extend(str(err["msg"]) for err in exc.errors())
        return errors
    validator = jsonschema.Draft202012Validator(schema)
    errors.extend(err.message for err in validator.iter_errors(flow_dict))
    return errors


def load_flow_from_dict(data: dict[str, Any]) -> FlowGraph:
    """Load a FlowGraph from a dict. Raises ValidationError on invalid data."""
    return FlowGraph.model_validate(data)


def load_flow_from_file(path: str | Path) -> FlowGraph:
    """Load a FlowGraph from a JSON file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return load_flow_from_dict(data)


def flow_to_dict(flow: FlowGraph) -> dict[str, Any]:
    """Serialize a FlowGraph to a JSON-compatible dict."""
    return flow.model_dump(exclude_none=True)
