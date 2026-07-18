"""Empty/no-op MethodAtom marker normalization."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EmptyMarkerSpec:
    category: str
    input_schema: str
    output_schema: str
    label: str

    @property
    def atom_id(self) -> str:
        return f"empty_{self.category}"

    @property
    def template_id(self) -> str:
        return f"empty_marker_{self.category}"


EMPTY_MARKER_SPECS: tuple[EmptyMarkerSpec, ...] = (
    EmptyMarkerSpec("design", "DesignSpec", "DesignSpec", "Empty design marker"),
    EmptyMarkerSpec("preprocessing", "OpticalDensityData", "OpticalDensityData", "Empty preprocessing marker"),
    EmptyMarkerSpec("analysis", "ContrastResults", "ContrastResults", "Empty analysis marker"),
    EmptyMarkerSpec("output", "CSVFile", "CSVFile", "Empty output marker"),
    EmptyMarkerSpec("validation", "ValidationResults", "ValidationResults", "Empty validation marker"),
    EmptyMarkerSpec("export", "Package", "Package", "Empty export marker"),
)


def empty_marker_specs_json() -> list[dict[str, str]]:
    """Return API-friendly empty marker specs."""
    return [asdict(spec) | {"atom_id": spec.atom_id, "template_id": spec.template_id} for spec in EMPTY_MARKER_SPECS]


def _atom_collection_key(flow: dict[str, Any]) -> str:
    return "flow_atoms" if isinstance(flow.get("flow_atoms"), list) else "nodes"


def _order_policy(flow: dict[str, Any]) -> dict[str, Any]:
    metadata = flow.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    policy = metadata.get("order_policy")
    return policy if isinstance(policy, dict) else {}


def is_empty_marker_atom(atom: dict[str, Any]) -> bool:
    metadata = atom.get("metadata") if isinstance(atom.get("metadata"), dict) else {}
    return (
        atom.get("operation") == "empty_marker"
        or atom.get("atom_type") == "empty_marker"
        or metadata.get("empty_atom") is True
    )


def create_empty_marker_atom(spec: EmptyMarkerSpec, index: int = 0) -> dict[str, Any]:
    """Create a schema-preserving no-op atom for one processing stage."""
    ports = [
        {
            "name": "marker_in",
            "direction": "in",
            "schema": spec.input_schema,
            "required": False,
        },
        {
            "name": "marker_out",
            "direction": "out",
            "schema": spec.output_schema,
            "required": False,
        },
    ]
    return {
        "id": spec.atom_id,
        "atom_id": spec.atom_id,
        "atom_type": "empty_marker",
        "type": "empty_marker",
        "template_id": spec.template_id,
        "category": spec.category,
        "origin": "builtin",
        "operation": "empty_marker",
        "description": f"{spec.label}; no processing is executed.",
        "ports": ports,
        "input_ports": [ports[0]],
        "output_ports": [ports[1]],
        "evidence_refs": [],
        "readiness_status": "ready",
        "execution_status": "not_run",
        "security_status": "trusted",
        "parameters": {},
        "config": {
            "empty_processing": True,
            "state_marker": spec.atom_id,
            "no_op": True,
            "input_schema": spec.input_schema,
            "output_schema": spec.output_schema,
        },
        "metadata": {
            "empty_atom": True,
            "auto_generated_empty_atom": True,
            "skipped_processing_category": spec.category,
            "input_schema": spec.input_schema,
            "output_schema": spec.output_schema,
        },
        "position": {"x": 680, "y": 110 + index * 118},
    }


def normalize_empty_markers(flow: dict[str, Any]) -> dict[str, Any]:
    """Add missing empty marker atoms when allow_empty_edges is enabled."""
    policy = _order_policy(flow)
    if policy.get("allow_empty_edges") is not True:
        return flow

    result = deepcopy(flow)
    atom_key = _atom_collection_key(result)
    atoms = list(result.get(atom_key) or [])
    existing_ids = {str(atom.get("id", "")) for atom in atoms if isinstance(atom, dict)}
    missing = [
        create_empty_marker_atom(spec, index)
        for index, spec in enumerate(EMPTY_MARKER_SPECS)
        if spec.atom_id not in existing_ids
    ]
    if not missing:
        return result

    next_atoms = [*atoms, *missing]
    result[atom_key] = next_atoms
    if atom_key == "flow_atoms" and isinstance(result.get("nodes"), list):
        result["nodes"] = next_atoms
    return result


def remove_unconnected_auto_empty_markers(flow: dict[str, Any]) -> dict[str, Any]:
    """Remove only unconnected auto-generated empty markers."""
    result = deepcopy(flow)
    atom_key = _atom_collection_key(result)
    atoms = list(result.get(atom_key) or [])
    connected_ids = {
        str(edge.get(endpoint, ""))
        for edge in result.get("edges", [])
        if isinstance(edge, dict)
        for endpoint in ("source", "target")
    }

    next_atoms = []
    for atom in atoms:
        if not isinstance(atom, dict):
            next_atoms.append(atom)
            continue
        metadata = atom.get("metadata") if isinstance(atom.get("metadata"), dict) else {}
        auto_empty = metadata.get("auto_generated_empty_atom") is True and is_empty_marker_atom(atom)
        if auto_empty and str(atom.get("id", "")) not in connected_ids:
            continue
        next_atoms.append(atom)

    result[atom_key] = next_atoms
    if atom_key == "flow_atoms" and isinstance(result.get("nodes"), list):
        result["nodes"] = next_atoms
    return result
