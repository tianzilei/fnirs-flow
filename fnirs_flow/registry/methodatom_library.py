"""Load literature-derived MethodAtom templates bundled with the package."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from fnirs_flow.flow.atoms import AtomPort, BackendBinding, MethodAtomCategory, MethodAtomOrigin
from fnirs_flow.registry.node_library import MethodAtomTemplate

PACKAGE_LIBRARY_DIR = Path(__file__).resolve().parent / "methodatom_lib"
METHOD_ATOMS_CSV = PACKAGE_LIBRARY_DIR / "method_atoms.csv"
ATOM_EVIDENCE_LINKS_CSV = PACKAGE_LIBRARY_DIR / "atom_evidence_links.csv"
RUNTIME_TEMPLATE_STATE_JSON = PACKAGE_LIBRARY_DIR / "runtime_template_state.json"

DOMAIN_CATEGORY_MAP: dict[str, MethodAtomCategory] = {
    "data_import": MethodAtomCategory.DATA,
    "acquisition": MethodAtomCategory.DATA,
    "preprocessing": MethodAtomCategory.PREPROCESSING,
    "physiology": MethodAtomCategory.PREPROCESSING,
    "qc": MethodAtomCategory.VALIDATION,
    "analysis": MethodAtomCategory.ANALYSIS,
    "machine_learning": MethodAtomCategory.ANALYSIS,
    "deep_learning": MethodAtomCategory.ANALYSIS,
    "reporting": MethodAtomCategory.VALIDATION,
    "export": MethodAtomCategory.EXPORT,
}

_LOADED = False
LITERATURE_METHOD_ATOM_TEMPLATES: list[MethodAtomTemplate] = []


def _safe_json(value: str, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _schema_type(value: str, fallback: str) -> str:
    parsed = _safe_json(value, {})
    if isinstance(parsed, dict):
        schema_type = parsed.get("type")
        if schema_type:
            return str(schema_type)
    return fallback


def _template_id(atom_id: str) -> str:
    normalized = atom_id.strip().lower()
    if normalized.startswith("atom_"):
        normalized = normalized[5:]
    return f"atom_{normalized}"


def _method_name(row: dict[str, str]) -> str:
    label = row.get("method_label", "").strip()
    if label:
        return label
    operation = row.get("operation", "").replace("_", " ").strip()
    return operation.title() if operation else row["atom_id"]


def _evidence_refs(row: dict[str, str]) -> list[str]:
    refs = _safe_json(row.get("evidence_refs", ""), [])
    if isinstance(refs, list):
        return [str(ref) for ref in refs]
    ref = row.get("evidence_refs", "").strip()
    return [ref] if ref else []


def _load_evidence_link_refs(csv_path: str | Path) -> dict[str, list[str]]:
    path = Path(csv_path)
    if not path.exists():
        return {}
    refs_by_atom: dict[str, list[str]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            target_id = row.get("target_object_id", "").strip()
            evidence_ref = row.get("evidence_ref", "").strip()
            if not target_id or not evidence_ref:
                continue
            refs_by_atom.setdefault(target_id, []).append(evidence_ref)
    return refs_by_atom


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def method_atom_library_state(
    method_atoms_path: str | Path = METHOD_ATOMS_CSV,
    evidence_links_path: str | Path = ATOM_EVIDENCE_LINKS_CSV,
) -> dict[str, Any]:
    """Return simple path, row-count, size, and timestamp metadata."""
    atoms_path = Path(method_atoms_path)
    links_path = Path(evidence_links_path)
    return {
        "method_atoms_csv": str(atoms_path),
        "atom_evidence_links_csv": str(links_path),
        "method_atoms_rows": _count_csv_rows(atoms_path),
        "atom_evidence_links_rows": _count_csv_rows(links_path),
        "method_atoms_size": atoms_path.stat().st_size if atoms_path.exists() else 0,
        "atom_evidence_links_size": links_path.stat().st_size if links_path.exists() else 0,
        "method_atoms_modified": atoms_path.stat().st_mtime_ns if atoms_path.exists() else 0,
        "atom_evidence_links_modified": links_path.stat().st_mtime_ns if links_path.exists() else 0,
    }


def write_runtime_state(state: dict[str, Any], cache_dir: str | Path) -> Path:
    """Persist registry state atomically outside immutable package resources."""
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "runtime_template_state.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


@lru_cache(maxsize=1)
def _cedalion_enrichment() -> tuple[Any, Any]:
    """Load optional Cedalion enrichment lazily, never during metadata import."""
    try:
        from fnirs_flow.adapters.cedalion_bindings import get_cedalion_binding, is_verified_cedalion_atom
    except ImportError:
        return (lambda _atom_id: None, lambda _atom_id: False)
    return get_cedalion_binding, is_verified_cedalion_atom


def _ports(row: dict[str, str]) -> list[AtomPort]:
    input_schema = _schema_type(row.get("input_schema", ""), "Any")
    output_schema = _schema_type(row.get("output_schema", ""), "Any")
    input_name = row.get("input_port", "").strip() or row.get("required_input", "").strip() or "input"
    output_name = row.get("output_port", "").strip() or row.get("produced_output", "").strip() or "output"
    return [
        AtomPort(name=input_name, direction="in", schema=input_schema),
        AtomPort(name=output_name, direction="out", schema=output_schema),
    ]


def _default_config(row: dict[str, str]) -> dict[str, Any]:
    parameters = _safe_json(row.get("parameters", ""), {})
    if not isinstance(parameters, dict):
        parameters = {"value": parameters}
    return {
        **parameters,
        "source_atom_id": row.get("atom_id", ""),
        "source_study_id": row.get("study_id", ""),
        "target_flow_slot": row.get("target_flow_slot", ""),
        "scenario": row.get("scenario", ""),
        "readiness_status": row.get("method_readiness", "").strip()
        or row.get("readiness_status", ""),
        "execution_readiness": row.get("execution_readiness", "").strip()
        or row.get("readiness_status", ""),
        "execution_scope": row.get("execution_scope", "").strip() or "run",
        "missing_for_execution": row.get("missing_for_execution", "").strip(),
        "confidence": row.get("confidence", ""),
        "review_required": row.get("review_required", ""),
    }


def load_literature_method_atom_templates(
    csv_path: str | Path = METHOD_ATOMS_CSV,
    evidence_links_path: str | Path = ATOM_EVIDENCE_LINKS_CSV,
) -> list[MethodAtomTemplate]:
    """Load synthesized MethodAtom records as built-in template definitions."""
    path = Path(csv_path)
    if not path.exists():
        return []

    evidence_refs_by_atom = _load_evidence_link_refs(evidence_links_path)
    templates: list[MethodAtomTemplate] = []
    seen_ids: set[str] = set()
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            atom_id = row.get("atom_id", "").strip()
            if not atom_id:
                raise ValueError(f"Invalid MethodAtom resource {path}: atom_id is required")
            template_id = _template_id(atom_id)
            if template_id in seen_ids:
                raise ValueError(f"Duplicate MethodAtom template id in {path}: {template_id}")
            seen_ids.add(template_id)
            domain = row.get("domain", "").strip()
            category = DOMAIN_CATEGORY_MAP.get(domain, MethodAtomCategory.ANALYSIS)
            operation = row.get("operation", "").strip() or None
            target_atom_type = row.get("target_atom_type", "").strip()
            atom_type = target_atom_type or operation or atom_id.lower()
            get_cedalion_binding, is_verified_cedalion_atom = _cedalion_enrichment()
            backend_operation = get_cedalion_binding(atom_id)
            default_config = _default_config(row)
            if backend_operation and not is_verified_cedalion_atom(atom_id):
                default_config["readiness_status"] = "needs_attention"
                default_config["verification_status"] = "contract_test_required"
            tags = [
                "literature_derived",
                "methodatom_library",
                domain,
                row.get("scenario", "").strip(),
            ]
            if backend_operation:
                tags.append("cedalion")
                if not is_verified_cedalion_atom(atom_id):
                    tags.append("experimental")
            templates.append(
                MethodAtomTemplate(
                    template_id=template_id,
                    name=_method_name(row),
                    category=category,
                    atom_type=atom_type,
                    operation=operation,
                    description=row.get("notes", "").strip(),
                    default_config=default_config,
                    ports=_ports(row),
                    origin=MethodAtomOrigin.EVIDENCE_DERIVED,
                    evidence_refs=evidence_refs_by_atom.get(atom_id) or _evidence_refs(row),
                    reference=row.get("evidence_refs", "").strip(),
                    tags=[tag for tag in tags if tag],
                    backend_binding=(
                        BackendBinding(
                            backend_id="cedalion",
                            operation=backend_operation,
                            version_spec=">=26.5,<27",
                        )
                        if backend_operation
                        else None
                    ),
                )
            )
    return templates


def ensure_literature_method_atom_templates_current(
    *,
    force: bool = False,
    write_state: bool = True,
) -> dict[str, Any]:
    """Reload bundled literature templates when their CSV inputs changed."""
    global _LOADED, LITERATURE_METHOD_ATOM_TEMPLATES

    library_state = method_atom_library_state()
    changed = force or not _LOADED
    if changed:
        LITERATURE_METHOD_ATOM_TEMPLATES = load_literature_method_atom_templates()
        _LOADED = True

    state = {
        **library_state,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "changed": changed,
        "loaded_templates": len(LITERATURE_METHOD_ATOM_TEMPLATES),
    }
    # ``write_state`` is retained for API compatibility. Package resources are
    # immutable; composition roots persist this state to their configured cache.
    return state


ensure_literature_method_atom_templates_current(force=True, write_state=False)
