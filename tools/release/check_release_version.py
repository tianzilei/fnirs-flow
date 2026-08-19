"""Check that project release metadata agrees with a version or Git tag."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]


def _read_versions() -> dict[str, str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_json = json.loads((ROOT / "webui" / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads((ROOT / "webui" / "package-lock.json").read_text(encoding="utf-8"))
    init_text = (ROOT / "fnirs_flow" / "__init__.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    fallback = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    readme_version = re.search(r"\*\*v([^*]+)\*\*", readme)
    changelog_version = re.search(r"^## \[([^]]+)]", changelog, re.MULTILINE)
    if not fallback or not readme_version or not changelog_version:
        raise SystemExit("Unable to read all release version declarations")
    return {
        "pyproject": str(pyproject["project"]["version"]),
        "python_fallback": fallback.group(1),
        "webui": str(package_json["version"]),
        "webui_lock": str(package_lock["version"]),
        "webui_lock_root": str(package_lock["packages"][""]["version"]),
        "readme": readme_version.group(1),
        "changelog": changelog_version.group(1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", help="Expected release version, without a leading v")
    parser.add_argument("--tag", help="Expected Git tag in vMAJOR.MINOR.PATCH form")
    args = parser.parse_args()
    if args.expected and args.tag:
        parser.error("provide at most one of --expected or --tag")
    versions = _read_versions()
    expected = args.expected or (str(args.tag)[1:] if args.tag else versions["pyproject"])
    if args.tag and (not args.tag.startswith("v") or args.tag == "v"):
        parser.error("--tag must use vMAJOR.MINOR.PATCH form")
    mismatches = {name: value for name, value in versions.items() if value != expected}
    if mismatches:
        rendered = ", ".join(f"{name}={value}" for name, value in sorted(mismatches.items()))
        raise SystemExit(f"Release version mismatch; expected {expected}: {rendered}")
    print(f"Release version {expected} is consistent across {len(versions)} declarations.")


if __name__ == "__main__":
    main()
