"""Reject research, audit, or test artifacts from Python distributions."""

from __future__ import annotations

import glob
import tarfile
import zipfile
from pathlib import PurePosixPath

forbidden = ("research/", "scripts/", "docs/", "test-artifacts/", "outputs/")
required = (
    "fnirs_flow/resources/schemas/fnirs_flow.schema.json",
    "fnirs_flow/registry/methodatom_lib/method_atoms.csv",
)


def normalized_sdist_names(names: list[str]) -> list[str]:
    return [str(PurePosixPath(*PurePosixPath(name).parts[1:])) for name in names]


def check_names(label: str, names: list[str], *, require_runtime: bool) -> None:
    unexpected = [
        name
        for name in names
        if name.startswith(forbidden)
        and name != "tests/package_blackbox.py"
    ]
    if unexpected:
        raise SystemExit(f"Unexpected {label} contents:\n" + "\n".join(unexpected))
    if not require_runtime:
        return
    missing = [name for name in required if name not in names]
    webui_assets_missing = not any(name.startswith("fnirs_flow/resources/webui/dist/assets/") for name in names)
    if missing or webui_assets_missing:
        details = [*missing]
        if webui_assets_missing:
            details.append("fnirs_flow/resources/webui/dist/assets/")
        raise SystemExit(f"Required runtime resources are missing from {label}: " + ", ".join(details))


wheel = sorted(glob.glob("dist/*.whl"))[-1]
with zipfile.ZipFile(wheel) as archive:
    check_names("wheel", archive.namelist(), require_runtime=True)

sdist = sorted(glob.glob("dist/*.tar.gz"))[-1]
with tarfile.open(sdist, "r:gz") as archive:
    check_names("sdist", normalized_sdist_names(archive.getnames()), require_runtime=False)
