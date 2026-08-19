"""Validate release license metadata and third-party notices.

The check is intentionally limited to declared direct dependencies. Transitive
inventories are still emitted by ``pip-licenses``/npm for audit, while this
gate prevents a release from silently adding a direct dependency without a
license declaration or notice coverage.
"""

from __future__ import annotations

import argparse
import json
import re

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_LICENSE_TOKENS = ("AGPL", "PROPRIETARY", "COMMERCIAL")
AUDIT_TOOLING = {"pip-audit", "pip-licenses"}


def _dependency_name(requirement: str) -> str:
    requirement = requirement.split(";", 1)[0].strip()
    requirement = requirement.split("@", 1)[0].strip()
    return re.split(r"[<>=!~\[]", requirement, maxsplit=1)[0].strip().lower().replace("_", "-")


def _declared_python_dependencies(document: dict[str, Any]) -> set[str]:
    project = document["project"]
    requirements = list(project.get("dependencies", []))
    for values in project.get("optional-dependencies", {}).values():
        requirements.extend(values)
    return {
        name
        for requirement in requirements
        if (name := _dependency_name(str(requirement))) and name != "fnirs-flow"
    }


def _load_python_inventory(path: Path) -> dict[str, str]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(row.get("Name", "")).lower().replace("_", "-"): str(row.get("License", ""))
        for row in rows
        if row.get("Name")
    }


def _direct_web_dependencies(lock: dict[str, Any]) -> dict[str, str]:
    root = lock.get("packages", {}).get("", {})
    names = set(root.get("dependencies", {})) | set(root.get("devDependencies", {}))
    packages = lock.get("packages", {})
    return {
        name: str(packages.get(f"node_modules/{name}", {}).get("license", ""))
        for name in sorted(names)
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-inventory", type=Path, required=True)
    args = parser.parse_args()

    license_path = ROOT / "LICENSE"
    notices_path = ROOT / "THIRD_PARTY_NOTICES.md"
    if not license_path.is_file() or "MIT License" not in license_path.read_text(encoding="utf-8"):
        raise SystemExit("LICENSE is missing or does not contain the declared MIT license")
    if not notices_path.is_file():
        raise SystemExit("THIRD_PARTY_NOTICES.md is required")
    notices = notices_path.read_text(encoding="utf-8").lower()

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = _declared_python_dependencies(pyproject)
    inventory = _load_python_inventory(args.python_inventory)
    missing = sorted(
        name
        for name in declared
        if name not in inventory and name not in AUDIT_TOOLING and name not in notices
    )
    if missing:
        raise SystemExit("Declared Python dependencies missing from license inventory: " + ", ".join(missing))

    web = _direct_web_dependencies(json.loads((ROOT / "webui" / "package-lock.json").read_text(encoding="utf-8")))
    missing_web = sorted(name for name, license_name in web.items() if not license_name)
    if missing_web:
        raise SystemExit("Direct WebUI dependencies lack license metadata: " + ", ".join(missing_web))

    licenses = [*inventory.values(), *web.values()]
    forbidden = sorted(
        license_name
        for license_name in licenses
        if any(token in license_name.upper() for token in FORBIDDEN_LICENSE_TOKENS)
    )
    if forbidden:
        raise SystemExit("Forbidden dependency licenses found: " + ", ".join(forbidden))

    notice_groups = ("pydantic", "fastapi", "mne", "cedalion", "react", "typescript", "vite")
    missing_notices = [name for name in notice_groups if name not in notices]
    if missing_notices:
        raise SystemExit("THIRD_PARTY_NOTICES.md lacks dependency groups: " + ", ".join(missing_notices))

    print(f"License/notices check passed ({len(inventory)} Python, {len(web)} direct WebUI packages).")


if __name__ == "__main__":
    main()
