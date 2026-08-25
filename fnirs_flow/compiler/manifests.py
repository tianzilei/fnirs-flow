"""Manifest writers: adapter_manifest, risk_register, reporting_checklist, etc.

v0.2: manifests include atom-level provenance (atom_id, template_id, evidence_refs).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fnirs_flow.flow.models import FlowGraph
from fnirs_flow.infrastructure.portability import portable_json_value
from fnirs_flow.validation.models import RiskItem


def _portable_template_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a declaration snapshot without machine-local source paths."""
    portable = portable_json_value(snapshot)
    return portable if isinstance(portable, dict) else {}


def _definition_filename(template_id: str, content: bytes) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", template_id).strip(".-") or "local-atom"
    digest = hashlib.sha256(content).hexdigest()[:12]
    return f"{safe_id}-{digest}.json"


def write_method_atom_manifest(flow: FlowGraph, outdir: Path) -> Path:
    """Persist Atom provenance and portable copies of local declarations.

    Raw local Python files are deliberately not copied: discovery treats their
    headers as data, but the rest of such a file may contain arbitrary code.
    Instead, the validated ``MethodAtomTemplate`` snapshot is emitted as JSON.
    """
    definitions_dir = outdir / "method_atoms"
    atoms: list[dict[str, Any]] = []
    embedded: list[dict[str, Any]] = []
    definition_by_template: dict[str, dict[str, Any]] = {}

    for atom in flow.flow_atoms:
        origin = atom.origin.value if hasattr(atom.origin, "value") else str(atom.origin)
        trust_level = (
            atom.execution_trust_level.value
            if hasattr(atom.execution_trust_level, "value")
            else str(atom.execution_trust_level)
        )
        security_status = (
            atom.security_status.value
            if hasattr(atom.security_status, "value")
            else str(atom.security_status)
        )
        record: dict[str, Any] = {
            "atom_id": atom.id,
            "atom_type": atom.atom_type,
            "template_id": atom.template_id,
            "operation": atom.operation or atom.config.get("operation") or atom.atom_type,
            "origin": origin,
            "execution_trust_level": trust_level,
            "security_status": security_status,
            "evidence_refs": list(atom.evidence_refs),
        }

        is_local = origin == "imported" or trust_level == "imported_custom"
        snapshot = _portable_template_snapshot(atom.template_snapshot)
        if is_local and atom.template_id and snapshot:
            definition = definition_by_template.get(atom.template_id)
            if definition is None:
                content = json.dumps(
                    snapshot,
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
                filename = _definition_filename(atom.template_id, content)
                definitions_dir.mkdir(parents=True, exist_ok=True)
                definition_path = definitions_dir / filename
                definition_path.write_bytes(content)
                definition = {
                    "template_id": atom.template_id,
                    "path": f"method_atoms/{filename}",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "format": "validated_methodatom_template_json",
                }
                definition_by_template[atom.template_id] = definition
                embedded.append(definition)
            record["embedded_definition"] = definition["path"]
            record["definition_sha256"] = definition["sha256"]
        atoms.append(record)

    data = {
        "schema_version": "0.1.0",
        "atoms": atoms,
        "atom_count": len(atoms),
        "embedded_local_atoms": embedded,
        "embedded_local_atom_count": len(embedded),
    }
    path = outdir / "method_atom_manifest.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_adapter_manifest(flow: FlowGraph, outdir: Path) -> Path:
    """Write adapter_manifest.json with atom-level provenance."""
    adapters_data = []
    for a in flow.adapter_registry:
        adapter_dict = a.model_dump()
        adapters_data.append(adapter_dict)

    # Collect backend bindings from atoms
    backend_bindings = []
    for node in flow.flow_atoms:
        if node.backend_binding:
            backend_bindings.append({
                "atom_id": node.id,
                "atom_type": node.atom_type,
                "backend_id": node.backend_binding.backend_id,
                "operation": node.backend_binding.operation,
                "version_spec": node.backend_binding.version_spec,
            })

    data = {
        "schema_version": "0.4.0",
        "adapters": adapters_data,
        "backend_bindings": backend_bindings,
        "atom_edge_count": len(flow.edges),
    }
    path = outdir / "adapter_manifest.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_risk_register(risks: list[RiskItem], outdir: Path) -> Path:
    """Write risk_register.json with atom-level affected objects."""
    data = {
        "schema_version": "0.2.0",
        "risks": [r.model_dump() for r in risks],
        "risk_count": len(risks),
        "atom_risks": [r.model_dump() for r in risks if r.affected_object and r.affected_object.startswith("atom:")],
    }
    path = outdir / "risk_register.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_reporting_checklist(outdir: Path) -> Path:
    """Write reporting_checklist.json."""
    data = {
        "schema_version": "0.2.0",
        "required_sections": [
            "dataset_description",
            "acquisition_parameters",
            "preprocessing_pipeline",
            "qc_summary",
            "analysis_model",
            "results_summary",
            "reproducibility_manifest",
        ],
    }
    path = outdir / "reporting_checklist.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_artifact_manifest(artifacts: list[dict[str, Any]], outdir: Path) -> Path:
    """Write artifact_manifest.json with atom-level provenance."""
    data = {
        "schema_version": "0.2.0",
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
    }
    path = outdir / "artifact_manifest.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_reproducibility_manifest(outdir: Path) -> Path:
    """Write reproducibility_manifest.json."""
    import sys

    data = {
        "schema_version": "0.2.0",
        "python_version": sys.version,
        "environment": {},
    }
    path = outdir / "reproducibility_manifest.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
