"""Portability checks for files persisted inside editable project bundles."""

from __future__ import annotations

import csv
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

TEXT_EXTENSIONS = {
    ".cfg",
    ".csv",
    ".html",
    ".json",
    ".jsonl",
    ".md",
    ".r",
    ".rst",
    ".svg",
    ".toml",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
}

TRACKABLE_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".png"}

SIGNAL_OR_WORK_EXTENSIONS = {
    ".cnt",
    ".edf",
    ".eeg",
    ".fif",
    ".h5",
    ".hdf5",
    ".joblib",
    ".mat",
    ".nc",
    ".nirx",
    ".nirs",
    ".npy",
    ".npz",
    ".pickle",
    ".pkl",
    ".set",
    ".snirf",
    ".vhdr",
    ".zarr",
}

_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_EMBEDDED_LOCAL_PATH = re.compile(
    r"(?:file://|(?<![A-Za-z0-9])(?:/Users/|/home/|/Volumes/|/private/|/tmp/|/var/tmp/)"
    r"|(?<![A-Za-z0-9])[A-Za-z]:[\\/]|\\\\[^\\\s]+\\[^\s]+)"
)


def is_absolute_local_path(value: str) -> bool:
    """Return whether *value* is a machine-local absolute path."""
    stripped = value.strip()
    return bool(
        stripped.startswith(("/", "~/", "file://", "\\\\"))
        or _WINDOWS_ABSOLUTE.match(stripped)
    )


def _walk_path_records(value: Any, location: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{location}.{key}"
            if isinstance(item, str):
                if is_absolute_local_path(item) or _EMBEDDED_LOCAL_PATH.search(item):
                    findings.append(child)
            findings.extend(_walk_path_records(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_walk_path_records(item, f"{location}[{index}]"))
    return findings


def portable_json_value(value: Any) -> Any:
    """Remove runtime-only paths from a value before it is persisted as JSON."""
    if isinstance(value, dict):
        return {
            key: portable_json_value(item)
            for key, item in value.items()
            if str(key) != "resolved_path"
        }
    if isinstance(value, list):
        return [portable_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [portable_json_value(item) for item in value]
    if isinstance(value, str):
        if is_absolute_local_path(value):
            normalized = value.replace("\\", "/").rstrip("/")
            return normalized.rsplit("/", 1)[-1] or "<local-path>"
        return _EMBEDDED_LOCAL_PATH.sub("<local-path>", value)
    return value


def find_absolute_path_records(path: Path, *, content: bytes | None = None) -> list[str]:
    """Return logical locations containing machine-local paths in a text artifact.

    If *content* is provided the bytes are decoded directly instead of reading from *path*.
    """
    suffix = path.suffix.lower() if path.suffix else ""
    if suffix not in TEXT_EXTENSIONS:
        return []
    if content is not None:
        try:
            text = content.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return ["<not-valid-utf8>"]
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ["<not-valid-utf8>"]

    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            return _walk_path_records(json.loads(text))
        except json.JSONDecodeError:
            return ["<invalid-json>"]
    if suffix == ".jsonl":
        findings: list[str] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                findings.extend(
                    f"line {line_number}:{item}" for item in _walk_path_records(json.loads(line))
                )
            except json.JSONDecodeError:
                findings.append(f"line {line_number}:<invalid-json>")
        return findings
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        findings = []
        _original_limit = csv.field_size_limit()
        csv.field_size_limit(max(_original_limit, 10 * 1024**2))
        try:
            for row_number, row in enumerate(csv.reader(text.splitlines(), delimiter=delimiter), start=1):
                for column_number, value in enumerate(row, start=1):
                    if is_absolute_local_path(value) or _EMBEDDED_LOCAL_PATH.search(value):
                        findings.append(f"row {row_number}, column {column_number}")
        finally:
            csv.field_size_limit(_original_limit)
        return findings
    return ["text"] if _EMBEDDED_LOCAL_PATH.search(text) else []


def find_archive_absolute_path_records(zf: zipfile.ZipFile) -> list[str]:
    """Return text archive members and locations containing local paths."""
    findings: list[str] = []
    for info in zf.infolist():
        member_path = Path(info.filename)
        if info.is_dir() or member_path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        findings.extend(
            f"{info.filename}: {location}"
            for location in find_absolute_path_records(member_path, content=zf.read(info))
        )
    return findings


def format_archive_portability_error(findings: list[str]) -> str:
    """Summarize archive portability findings for CLI and API errors."""
    if not findings:
        return ""
    additional = len(findings) - 1
    suffix = f" ({additional} additional path records)" if additional else ""
    return f"Machine-local absolute path in {findings[0]}{suffix}"


def is_trackable_bundle_path(relative: PurePosixPath) -> bool:
    """Return whether a workspace file belongs in a lightweight project bundle."""
    if relative == PurePosixPath("project.json"):
        return True
    if not relative.parts:
        return False
    if relative.parts[0] == "history":
        return relative.suffix.lower() in TRACKABLE_EXTENSIONS
    if relative.parts[0] != "outputs":
        return False
    if len(relative.parts) > 1 and relative.parts[1] in {"export", "work"}:
        return False
    if relative.suffix.lower() in SIGNAL_OR_WORK_EXTENSIONS:
        return False
    return relative.suffix.lower() in TRACKABLE_EXTENSIONS
