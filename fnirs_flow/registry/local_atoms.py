"""Static discovery of user-installed MethodAtom declarations.

Local declarations are data, not plugins executed during discovery. JSON files
contain one template object (or ``{"templates": [...]}``). Python files expose
the same literal data through a top-level ``METHOD_ATOM`` or ``METHOD_ATOMS``
assignment; the file is parsed with ``ast.literal_eval`` and is never imported.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fnirs_flow.flow.atoms import MethodAtomOrigin
from fnirs_flow.registry.node_library import MethodAtomTemplate

LOCAL_ATOM_HEADER = "METHOD_ATOM"
LOCAL_ATOMS_HEADER = "METHOD_ATOMS"
SUPPORTED_SUFFIXES = frozenset({".json", ".py"})


@dataclass
class LocalAtomDiscovery:
    templates: list[MethodAtomTemplate] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def default_local_atom_dir() -> Path:
    """Return the per-user installation directory for MethodAtoms."""
    return Path.home() / ".fnirsflow" / "atoms"


def local_atom_library_state(directory: str | Path) -> dict[str, Any]:
    """Return a deterministic fingerprint without creating the directory."""
    root = Path(directory).expanduser()
    files = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES),
        key=lambda path: path.as_posix().lower(),
    ) if root.is_dir() else []
    return {
        "local_atoms_dir": str(root),
        "local_atom_files": [str(path) for path in files],
        "local_atom_fingerprint": [
            [str(path), path.stat().st_size, path.stat().st_mtime_ns] for path in files
        ],
    }


def _python_declarations(path: Path) -> Any:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    declarations: list[Any] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name)
            and target.id in {LOCAL_ATOM_HEADER, LOCAL_ATOMS_HEADER}
            for target in targets
        ):
            continue
        value = node.value
        if value is None:
            continue
        try:
            declarations.append(ast.literal_eval(value))
        except (ValueError, SyntaxError) as exc:
            raise ValueError(
                f"{path}: {LOCAL_ATOM_HEADER}/{LOCAL_ATOMS_HEADER} must be literal data"
            ) from exc
    if not declarations:
        raise ValueError(f"{path}: missing {LOCAL_ATOM_HEADER} or {LOCAL_ATOMS_HEADER} declaration")
    return declarations[0] if len(declarations) == 1 else declarations


def _template_records(value: Any, path: Path) -> list[dict[str, Any]]:
    if isinstance(value, dict) and "templates" in value:
        value = value["templates"]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{path}: declaration must be a template object or a list of template objects")
    return value


def load_local_method_atom_file(path: str | Path) -> list[MethodAtomTemplate]:
    source = Path(path)
    if source.suffix.lower() == ".json":
        value = json.loads(source.read_text(encoding="utf-8"))
    elif source.suffix.lower() == ".py":
        value = _python_declarations(source)
    else:
        raise ValueError(f"Unsupported local MethodAtom file: {source}")

    templates: list[MethodAtomTemplate] = []
    for raw in _template_records(value, source):
        record = dict(raw)
        implementation = record.pop("implementation", None)
        if implementation is not None:
            if not isinstance(implementation, str) or ":" not in implementation:
                raise ValueError(f"{source}: implementation must use 'module:callable' syntax")
            module_name, callable_name = implementation.split(":", 1)
            record["implementation_module"] = module_name.strip()
            record["implementation_callable"] = callable_name.strip()
            record.setdefault("implementation_status", "dependency_gated")
        record["origin"] = MethodAtomOrigin.IMPORTED.value
        metadata = dict(record.get("metadata") or {})
        metadata.update(
            {
                "local_atom_file": str(source),
                "local_atom_format": source.suffix.lower().lstrip("."),
            }
        )
        record["metadata"] = metadata
        templates.append(MethodAtomTemplate.model_validate(record))
    return templates


def discover_local_method_atom_templates(directory: str | Path) -> LocalAtomDiscovery:
    state = local_atom_library_state(directory)
    result = LocalAtomDiscovery(files=list(state["local_atom_files"]))
    for filename in result.files:
        try:
            result.templates.extend(load_local_method_atom_file(filename))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            result.errors.append(str(exc))
    return result
