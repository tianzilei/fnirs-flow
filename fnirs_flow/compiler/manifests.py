"""Manifest writers: adapter_manifest, risk_register, reporting_checklist, etc.

v0.2: manifests include atom-level provenance (atom_id, template_id, evidence_refs).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fnirs_flow.flow.models import FlowGraph
from fnirs_flow.validation.models import RiskItem


def write_adapter_manifest(flow: FlowGraph, outdir: Path) -> Path:
    """Write adapter_manifest.json with atom-level provenance."""
    adapters_data = []
    for a in flow.adapter_registry:
        adapter_dict = a.model_dump()
        adapters_data.append(adapter_dict)

    data = {
        "schema_version": "0.2.0",
        "adapters": adapters_data,
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


def write_reproducibility_manifest(flow_hash: str, outdir: Path) -> Path:
    """Write reproducibility_manifest.json."""
    import sys

    data = {
        "schema_version": "0.2.0",
        "flow_hash": flow_hash,
        "python_version": sys.version,
        "environment": {},
    }
    path = outdir / "reproducibility_manifest.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
