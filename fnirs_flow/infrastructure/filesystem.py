"""Filesystem helpers shared by scanners and archive validators."""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath

MACOS_METADATA_NAMES = {".DS_Store", ".AppleDouble", ".LSOverride", "__MACOSX"}


def is_macos_metadata_path(path: str | Path | PurePosixPath) -> bool:
    """Return True for macOS Finder/AppleDouble metadata paths."""
    normalized = str(path).replace("\\", "/")
    return any(
        part.startswith("._") or part in MACOS_METADATA_NAMES
        for part in PurePosixPath(normalized).parts
    )


def is_visible_data_file(path: Path, *, root: Path | None = None) -> bool:
    """Return True for real data files, excluding macOS metadata sidecars."""
    if not path.is_file():
        return False
    comparable = path.relative_to(root) if root is not None else path
    return not is_macos_metadata_path(comparable)


def macos_metadata_ignore(_directory: str, names: list[str]) -> list[str]:
    """shutil.copytree ignore callback for Finder/AppleDouble metadata."""
    return [name for name in names if is_macos_metadata_path(name)]


def remove_macos_metadata_paths(root: str | Path) -> list[Path]:
    """Remove macOS Finder/AppleDouble metadata files created on non-native volumes."""
    base = Path(root)
    if not base.exists():
        return []

    removed: list[Path] = []
    candidates = sorted(
        (path for path in base.rglob("*") if is_macos_metadata_path(path.relative_to(base))),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in candidates:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(path)
        except FileNotFoundError:
            continue
    return removed
